"""Gemini implementation of ``LLMProvider`` on top of ``google-genai``.

The API key is passed explicitly to the ``Client`` (never read from a hidden
``os.environ`` lookup inside the SDK) and is redacted from error messages. It
is never logged.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from bondy.config import Settings
from bondy.core.providers.base import (
    LLMRequest,
    MediaPart,
    RetryingProvider,
    TokenUsage,
)

REQUEST_TIMEOUT_MS = 60_000


class GeminiProvider(RetryingProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        vision_model: str,
        fallback_model: str = "",
        *,
        client: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout_ms: int = REQUEST_TIMEOUT_MS,
    ):
        super().__init__(
            models=[model, fallback_model],
            vision_models=[vision_model, fallback_model],
            sleep=sleep,
            secrets=[api_key],
        )
        self._api_key = api_key
        self._client = client
        self._timeout_ms = timeout_ms

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Any) -> GeminiProvider:
        if not settings.api_key:
            raise ValueError("A Gemini API key is required.")
        return cls(
            settings.api_key,
            settings.model,
            settings.vision_model,
            settings.fallback_model,
            **kwargs,
        )

    def __repr__(self) -> str:  # never expose the key
        return f"GeminiProvider(models={self._text_models!r})"

    def _get_client(self):
        if self._client is None:
            from google.genai import Client, types

            # vertexai=False: the key is an AI Studio key, whatever the env says
            self._client = Client(
                vertexai=False,
                api_key=self._api_key,
                http_options=types.HttpOptions(timeout=self._timeout_ms),
            )
        return self._client

    def _send(self, model: str, request: LLMRequest):
        from google.genai import types

        contents = [
            types.Part.from_bytes(data=p.data, mime_type=p.mime_type)
            if isinstance(p, MediaPart)
            else p
            for p in request.parts
        ]
        config = types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=request.max_output_tokens,
            response_mime_type="application/json" if request.schema else None,
            response_schema=request.schema,
        )
        res = self._get_client().models.generate_content(
            model=model, contents=contents, config=config
        )
        meta = getattr(res, "usage_metadata", None)
        usage = None
        if meta is not None and getattr(meta, "prompt_token_count", None) is not None:
            # thinking tokens are billed as output
            out = (getattr(meta, "candidates_token_count", 0) or 0) + (
                getattr(meta, "thoughts_token_count", 0) or 0
            )
            usage = TokenUsage(int(meta.prompt_token_count), int(out))
        return res.text or "", usage
