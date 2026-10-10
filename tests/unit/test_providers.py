"""LLMProvider retry/fallback policy, exercised through FakeProvider (no network)."""

import pytest

from bondy.core.providers.base import LLMRequest, ProviderError
from bondy.core.providers.fake import (
    RATE_LIMIT_DAY,
    RATE_LIMIT_MINUTE,
    UNAVAILABLE,
    FakeProvider,
)
from bondy.core.providers.gemini import GeminiProvider

REQ = LLMRequest(parts=["hello"])


def test_minute_quota_waits_and_retries_same_model():
    p = FakeProvider([Exception(RATE_LIMIT_MINUTE)])
    res = p.generate(REQ)
    assert res.attempts == 2 and p.http_requests == 2
    assert p.models_used == ["fake-model", "fake-model"]
    assert p.sleeps == [3.0]  # retry in 2s + 1s margin


def test_daily_quota_is_not_retried_and_falls_back_to_next_model():
    p = FakeProvider([Exception(RATE_LIMIT_DAY)])
    res = p.generate(REQ)
    assert p.sleeps == []
    assert p.models_used == ["fake-model", "fake-fallback"] and res.attempts == 2


def test_daily_quota_on_every_model_raises_quota_daily():
    p = FakeProvider([Exception(RATE_LIMIT_DAY), Exception(RATE_LIMIT_DAY)])
    with pytest.raises(ProviderError) as e:
        p.generate(REQ)
    assert e.value.kind == "quota_daily" and e.value.attempts == 2


def test_503_goes_to_fallback_without_waiting():
    p = FakeProvider([Exception(UNAVAILABLE)])
    p.generate(REQ)
    assert p.sleeps == [] and p.models_used[-1] == "fake-fallback"


def test_timeout_everywhere_raises_timeout():
    p = FakeProvider([TimeoutError("read timed out")] * 2)
    with pytest.raises(ProviderError) as e:
        p.generate(REQ)
    assert e.value.kind == "timeout"


def test_max_attempts_caps_retries():
    p = FakeProvider([Exception(RATE_LIMIT_MINUTE)] * 5)
    with pytest.raises(ProviderError) as e:
        p.generate(REQ, max_attempts=1)
    assert e.value.kind == "attempt_limit" and p.http_requests == 1


def test_usage_is_reported_or_none():
    assert FakeProvider().generate(REQ).usage.input_tokens == 1000
    assert FakeProvider(tokens_per_request=None).generate(REQ).usage is None


def test_gemini_provider_passes_explicit_key_and_redacts_it(monkeypatch):
    sentinel = "SENTINEL-KEY-123"
    captured = {}

    class Boom:
        def __init__(self, **kw):
            captured.update(kw)
            self.models = self

        def generate_content(self, **kw):
            raise RuntimeError(f"400 bad request for key={sentinel}")

    monkeypatch.setattr("google.genai.Client", Boom)
    monkeypatch.setenv("GOOGLE_API_KEY", "other-key-from-env")
    p = GeminiProvider(sentinel, "m", "v", "", sleep=lambda s: None)
    with pytest.raises(ProviderError) as e:
        p.generate(REQ)
    assert captured["api_key"] == sentinel
    assert sentinel not in str(e.value) and sentinel not in repr(p)
    assert "***" in str(e.value)


def test_gemini_provider_reads_usage_and_uses_vision_model():
    class Meta:
        prompt_token_count = 10
        candidates_token_count = 4
        thoughts_token_count = 2

    class Res:
        text = "{}"
        usage_metadata = Meta()

    seen = []

    class Client:
        class models:
            @staticmethod
            def generate_content(model, contents, config):
                seen.append(model)
                return Res()

    from bondy.core.providers.base import MediaPart

    p = GeminiProvider("k", "text-m", "vision-m", client=Client())
    r = p.generate(LLMRequest(parts=["x", MediaPart(b"\x89PNG", "image/png")]))
    assert seen == ["vision-m"] and r.usage.output_tokens == 6
    assert p.generate(LLMRequest(parts=["x"])).model == "text-m"
