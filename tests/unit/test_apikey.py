"""API-key validation: rejected key vs quota vs network; never prints the key."""

import json

import pytest

from bondy import cli, config, doctor
from bondy.core.pipeline import run_scan
from bondy.core.providers.base import (
    LLMRequest,
    ProviderError,
    classify_error,
)
from bondy.core.providers.fake import FakeProvider
from bondy.core.providers.gemini import GeminiProvider

SENTINEL = "SENTINEL-API-KEY-77aa"
BAD_KEY = (
    "400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': 'API key not valid. "
    "Please pass a valid API key.', 'status': 'INVALID_ARGUMENT', 'details': "
    "[{'reason': 'API_KEY_INVALID'}]}}"
)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        (BAD_KEY, "invalid_key"),
        ("403 PERMISSION_DENIED. The caller does not have permission", "invalid_key"),
        ("401 UNAUTHENTICATED. Request had invalid authentication", "invalid_key"),
        ("429 RESOURCE_EXHAUSTED. quota PerDay exceeded", "quota_daily"),
        ("429 RESOURCE_EXHAUSTED. retry in 5s", "rate_limit"),
        ("httpx.ConnectError: [Errno 11001] getaddrinfo failed", "network"),
        ("Connection refused", "network"),
        ("503 UNAVAILABLE. overloaded", "unavailable"),
        ("The read operation timed out", "timeout"),
        ("400 INVALID_ARGUMENT. response schema is invalid", "other"),
    ],
)
def test_classification(message, kind):
    assert classify_error(Exception(message)) == kind


def test_invalid_key_is_not_retried_nor_sent_to_the_fallback_model():
    p = FakeProvider([Exception(BAD_KEY)] * 5)
    with pytest.raises(ProviderError) as e:
        p.generate(LLMRequest(parts=["hi"]))
    assert e.value.kind == "invalid_key" and p.http_requests == 1
    assert p.models_used == ["fake-model"] and p.sleeps == []


def project(tmp_path, n=2):
    body = "".join(f'<img src="i{i}.png" alt="a{i}">' for i in range(n))
    (tmp_path / "p.html").write_text(
        f'<html lang="en"><body>{body}</body></html>', encoding="utf-8"
    )
    for i in range(n):
        (tmp_path / f"i{i}.png").write_bytes(PNG + bytes([i]))


def test_scan_aborts_on_first_batch_with_invalid_key(tmp_path):
    project(tmp_path, n=6)
    ran = []
    p = FakeProvider([Exception(BAD_KEY)] * 4)
    s = config.load_settings(
        flags={"api_key": SENTINEL, "batch_size": 2}, env={}, start_dir=tmp_path
    )
    with pytest.raises(ProviderError) as e:
        run_scan(
            tmp_path,
            s,
            scanners={"s": lambda h: ran.append(h) or []},
            provider=p,
        )
    assert e.value.kind == "invalid_key"
    assert p.http_requests == 1  # no retries, no further batches
    assert ran == []  # failed before any browser/scanner work


def _cli_env(monkeypatch, tmp_path, provider):
    from bondy import scan as scan_mod

    for name in list(scan_mod.SCANNERS):
        monkeypatch.setitem(scan_mod.SCANNERS, name, lambda h: [])
    monkeypatch.setattr(
        GeminiProvider, "from_settings", classmethod(lambda cls, s, **kw: provider)
    )
    monkeypatch.setenv("GEMINI_API_KEY", SENTINEL)
    monkeypatch.chdir(tmp_path)


def test_cli_invalid_key_exits_2_with_actionable_message(tmp_path, monkeypatch, capsys):
    project(tmp_path)
    fake = FakeProvider([Exception(BAD_KEY)])
    _cli_env(monkeypatch, tmp_path, fake)
    code = cli.main(["scan", str(tmp_path)])
    out = capsys.readouterr()
    assert code == 2 and fake.http_requests == 1
    assert "API key was rejected" in out.err and "--no-llm" in out.err
    assert SENTINEL not in out.out and SENTINEL not in out.err


def test_cached_scan_never_needs_the_key(tmp_path):
    project(tmp_path)
    s = config.load_settings(flags={"api_key": "ok"}, env={}, start_dir=tmp_path)
    run_scan(tmp_path, s, scanners={"s": lambda h: []}, provider=FakeProvider())
    revoked = FakeProvider([Exception(BAD_KEY)])
    r = run_scan(tmp_path, s, scanners={"s": lambda h: []}, provider=revoked)
    assert revoked.http_requests == 0 and r.usage.cache_hits == 2


# ----- doctor --check-key -----
def test_doctor_is_offline_by_default(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("doctor must not call the API without --check-key")

    monkeypatch.setattr(GeminiProvider, "check_key", forbidden)
    monkeypatch.setattr(GeminiProvider, "_send", forbidden)
    monkeypatch.setenv("GEMINI_API_KEY", SENTINEL)
    names = [c.name for c in doctor.run_checks()]
    assert "api-key" in names and "api-key (live)" not in names


@pytest.mark.parametrize(
    ("script", "status", "needle"),
    [
        ([], "ok", "accepted the key"),
        ([Exception(BAD_KEY)], "fail", "rejected the key"),
        ([Exception("429 RESOURCE_EXHAUSTED PerDay")], "warn", "quota is exhausted"),
        ([Exception("429 RESOURCE_EXHAUSTED retry in 3s")], "warn", "per minute"),
        ([Exception("ConnectError: getaddrinfo failed")], "warn", "Could not reach"),
    ],
)
def test_doctor_check_key_distinguishes_key_quota_and_network(
    tmp_path, monkeypatch, script, status, needle
):
    monkeypatch.setenv("GEMINI_API_KEY", SENTINEL)
    fake = FakeProvider(script)
    c = doctor.check_key_live(provider=fake)
    assert c.status == status and needle in c.detail
    assert fake.http_requests == 1  # exactly one minimal request, no retries
    assert SENTINEL not in c.detail and SENTINEL not in (c.fix or "")


def test_doctor_cli_check_key_flag(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", SENTINEL)
    monkeypatch.chdir(tmp_path)

    def boom(self, model, request):
        raise RuntimeError(f"400 API key not valid: {SENTINEL} API_KEY_INVALID")

    monkeypatch.setattr(GeminiProvider, "_send", boom)
    code = cli.main(["doctor", "--check-key"])
    out = capsys.readouterr()
    assert code == 1 and "rejected the key" in out.out
    assert SENTINEL not in out.out and SENTINEL not in out.err


def test_gemini_check_key_uses_one_tiny_request():
    seen = []

    class Res:
        text = "OK"
        usage_metadata = None

    class Client:
        class models:
            @staticmethod
            def generate_content(model, contents, config):
                seen.append((model, config.max_output_tokens))
                return Res()

    p = GeminiProvider("k", "text-m", "vision-m", client=Client())
    p.check_key()
    assert seen == [("text-m", 4)]


def test_json_output_never_contains_the_key(tmp_path, monkeypatch, capsys):
    project(tmp_path)
    fake = FakeProvider()
    _cli_env(monkeypatch, tmp_path, fake)
    cli.main(["scan", str(tmp_path), "--format", "json"])
    out = capsys.readouterr().out
    json.loads(out)
    assert SENTINEL not in out
    for f in (tmp_path / ".bondy").rglob("*.json"):
        assert SENTINEL not in f.read_text(encoding="utf-8")
