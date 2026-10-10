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

from bondy.core.alt_rules import quota_retry_delay

ErrorKind = Literal[
    "invalid_key",  # 400 API_KEY_INVALID / 401 / 403: never retried, scan aborts
    "quota_daily",
    "rate_limit",
    "network",  # cannot reach the API at all (DNS, refused, offline)
    "unavailable",
    "timeout",
    "attempt_limit",
    "other",
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
    max_output_tokens: int | None = None

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
# ``quota_retry_delay`` (imported above) is the single implementation of the
# policy: a per-minute 429 returns the wait in seconds (max 60); a daily quota
# ("PerDay") and any non-429 error return None.

_INVALID_KEY = re.compile(
    r"API_KEY_INVALID|API key (?:not valid|expired)|UNAUTHENTICATED|"
    r"PERMISSION_DENIED|^\s*(?:401|403)\b",
    re.IGNORECASE,
)
_NETWORK = re.compile(
    r"ConnectError|ConnectTimeout|ConnectionError|getaddrinfo|Name or service|"
    r"Temporary failure in name|Network is unreachable|connection "
    r"(?:refused|reset|aborted)|SSLError",
    re.IGNORECASE,
)


def classify_error(error: Exception) -> ErrorKind:
    msg = str(error)
    # quota first: a 429 body may mention keys/projects in passing
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return "quota_daily" if "PerDay" in msg else "rate_limit"
    if _INVALID_KEY.search(msg):
        return "invalid_key"
    if isinstance(error, ConnectionError) or _NETWORK.search(msg):
        return "network"
    if isinstance(error, TimeoutError) or re.search(
        r"timed? ?out|DEADLINE_EXCEEDED", msg, re.IGNORECASE
    ):
        return "timeout"
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
                    if classify_error(e) == "invalid_key":
                        # a bad key fails on every model: no retry, no fallback
                        raise ProviderError(
                            "invalid_key", self._summary(e), attempts
                        ) from None
                    delay = quota_retry_delay(e)
                    if delay is None or attempt == 1:
                        break  # not a per-minute quota, or already retried
                    self._sleep(delay)
        assert last is not None
        kind = classify_error(last)
        raise ProviderError(
            kind, f"All models failed ({kind}): {self._summary(last)}", attempts
        )

    def _summary(self, error: Exception) -> str:
        first_line = self._redact(str(error)).strip().splitlines()[:1]
        return first_line[0][:300] if first_line else type(error).__name__

    def check_key(self) -> LLMResponse:
        """ONE minimal request, no retries: validates key/network/quota.

        Spends a request (a few tokens). Raises ``ProviderError`` with kind
        ``invalid_key`` / ``rate_limit`` / ``quota_daily`` / ``network`` / ...
        """
        model = (self._text_models or self._vision_models or [""])[0]
        request = LLMRequest(parts=["Reply with OK."], max_output_tokens=4)
        try:
            text, usage = self._send(model, request)
        except Exception as e:
            raise ProviderError(classify_error(e), self._summary(e), 1) from None
        return LLMResponse(text, model, 1, usage)
