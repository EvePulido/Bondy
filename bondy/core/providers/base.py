"""Minimal LLM provider interface plus the shared quota/retry policy.

``LLMProvider`` is the only thing the pipeline knows about a model vendor.
``RetryingProvider`` implements the retry policy once (quota per minute waits,
daily quota is not retried, model fallback) so the real provider and the fake
used in tests behave identically.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel

from bondy.app_utils.vision_tools import _quota_retry_delay

ErrorKind = Literal[
    "quota_daily", "rate_limit", "unavailable", "timeout", "attempt_limit", "other"
]


@dataclass(frozen=True)
class MediaPart:
    """Binary input (an image) for a request."""

    data: bytes
    mime_type: str


Part = str | MediaPart


@dataclass(frozen=True)
class LLMRequest:
    """One model call: ordered text/media parts and the expected JSON schema."""

    parts: Sequence[Part]
    schema: type[BaseModel] | None = None

    @property
    def has_media(self) -> bool:
        return any(isinstance(p, MediaPart) for p in self.parts)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class LLMResponse:
    text: str
    model: str
    attempts: int  # HTTP requests this call consumed (retries included)
    usage: TokenUsage | None = None  # None when the provider did not report it


class ProviderError(Exception):
    """A call failed after the retry policy. ``attempts`` were consumed."""

    def __init__(self, kind: ErrorKind, message: str, attempts: int = 0):
        super().__init__(message)
        self.kind: ErrorKind = kind
        self.attempts = attempts


class LLMProvider(Protocol):
    def generate(
        self, request: LLMRequest, *, max_attempts: int | None = None
    ) -> LLMResponse:
        """Sends ``request``; raises ``ProviderError`` when it cannot succeed.

        ``max_attempts`` caps the HTTP requests this call may spend (retries
        included); reaching it raises ``ProviderError("attempt_limit")``.
        """
        ...


# ----- Quota / error classification -----
# Reused as-is from the legacy vision tools (one implementation of the policy):
# a per-minute 429 returns the wait in seconds (max 60); a daily quota
# ("PerDay") and any non-429 error return None.
quota_retry_delay = _quota_retry_delay


def classify_error(error: Exception) -> ErrorKind:
    msg = str(error)
    if isinstance(error, TimeoutError) or re.search(
        r"timed? ?out|DEADLINE_EXCEEDED", msg, re.IGNORECASE
    ):
        return "timeout"
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return "quota_daily" if "PerDay" in msg else "rate_limit"
    if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
        return "unavailable"
    return "other"


class RetryingProvider:
    """Template: subclasses implement ``_send``; retries/fallback live here.

    Policy (same as the legacy vision tools): per model, one retry after a
    per-minute 429 (waiting the server's ``retryDelay``); a daily quota, a 503,
    a timeout or any other error moves on to the fallback model immediately.
    """

    def __init__(
        self,
        models: Sequence[str],
        vision_models: Sequence[str] | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        secrets: Sequence[str] = (),
    ):
        self._text_models = [m for m in models if m]
        self._vision_models = [m for m in (vision_models or models) if m]
        self._sleep = sleep
        self._secrets = [s for s in secrets if s]

    def _send(
        self, model: str, request: LLMRequest
    ) -> tuple[str, TokenUsage | None]:  # pragma: no cover - abstract
        raise NotImplementedError

    def _redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return text

    def generate(
        self, request: LLMRequest, *, max_attempts: int | None = None
    ) -> LLMResponse:
        models = self._vision_models if request.has_media else self._text_models
        if not models:
            raise ProviderError("other", "No model configured.", 0)
        attempts = 0
        last: Exception | None = None
        for model in models:
            for attempt in range(2):
                if max_attempts is not None and attempts >= max_attempts:
                    raise ProviderError(
                        "attempt_limit", "Request limit reached.", attempts
                    )
                attempts += 1
                try:
                    text, usage = self._send(model, request)
                    return LLMResponse(text, model, attempts, usage)
                except Exception as e:  # classified below
                    last = e
                    delay = quota_retry_delay(e)
                    if delay is None or attempt == 1:
                        break  # not a per-minute quota, or already retried
                    self._sleep(delay)
        assert last is not None
        kind = classify_error(last)
        first_line = self._redact(str(last)).strip().splitlines()[:1]
        detail = first_line[0][:300] if first_line else type(last).__name__
        raise ProviderError(kind, f"All models failed ({kind}): {detail}", attempts)
