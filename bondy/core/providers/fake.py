"""Scripted provider for tests and offline measurements. Makes no network call.

It shares ``RetryingProvider``'s retry policy with the real provider, so a
simulated 429/503/timeout exercises the same code path as Gemini.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence

from bondy.core.providers.base import (
    LLMRequest,
    RetryingProvider,
    TokenUsage,
)

# Error texts shaped like the ones Gemini returns.
RATE_LIMIT_MINUTE = (
    "429 RESOURCE_EXHAUSTED. Quota exceeded for metric "
    "GenerateRequestsPerMinutePerProjectPerModel. Please retry in 2s."
)
RATE_LIMIT_DAY = (
    "429 RESOURCE_EXHAUSTED quotaId 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'"
)
UNAVAILABLE = "503 UNAVAILABLE. The model is overloaded."

# A scripted step is an Exception to raise, a str to return, or a callable.
Step = Exception | str | Callable[[LLMRequest], str]


def default_responder(request: LLMRequest) -> str:
    """Answers every ``[IMAGE index=N]`` marker with a plausible JSON verdict."""
    text = "\n".join(p for p in request.parts if isinstance(p, str))
    indexes = [int(i) for i in re.findall(r"\[IMAGE index=(\d+)\]", text)]
    results = [
        {
            "index": i,
            "visible_content": "A photo",
            "matches_current_alt": "no",
            "classification": "informative",
            "suggested_alt": f"Fake description {i}",
            "confidence": "high",
            "uncertain_details": [],
        }
        for i in indexes
    ]
    return json.dumps({"results": results})


class FakeProvider(RetryingProvider):
    """Counts requests; ``script`` steps are consumed one per HTTP attempt.

    When the script is exhausted the ``responder`` answers. It never sleeps:
    requested waits are recorded in ``sleeps``.
    """

    endpoint_host = "fake-provider.invalid"

    def __init__(
        self,
        script: Sequence[Step] = (),
        responder: Callable[[LLMRequest], str] = default_responder,
        *,
        models: Sequence[str] = ("fake-model", "fake-fallback"),
        tokens_per_request: tuple[int, int] | None = (1000, 100),
    ):
        self.sleeps: list[float] = []
        super().__init__(models=models, sleep=self.sleeps.append)
        self._script = list(script)
        self._responder = responder
        self._tokens = tokens_per_request
        self.http_requests = 0  # every attempt, including retries
        self.models_used: list[str] = []
        self.requests: list[LLMRequest] = []

    def _send(self, model: str, request: LLMRequest):
        self.http_requests += 1
        self.models_used.append(model)
        self.requests.append(request)
        step = self._script.pop(0) if self._script else self._responder
        if isinstance(step, Exception):
            raise step
        text = step if isinstance(step, str) else step(request)
        usage = TokenUsage(*self._tokens) if self._tokens else None
        return text, usage
