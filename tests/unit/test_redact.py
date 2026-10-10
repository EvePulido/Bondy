"""D3: secrets are redacted before text reaches the model, the cache or a report."""

import pytest

from bondy import cli, config
from bondy.core import formats
from bondy.core.models import ImageOccurrence
from bondy.core.pipeline import project_root, run_scan
from bondy.core.providers.fake import FakeProvider
from bondy.core.redact import REDACTED, contains_secret, redact_secrets
from bondy.core.report import build_report
from bondy.core.semantic import _image_payload

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
STUB = {"stub": lambda html: []}

AIZA = "AIza" + "SENTINEL" + "x" * 27
SK = "sk-SENTINEL" + "a" * 24
GHP = "ghp_SENTINEL" + "b" * 30
AKIA = "AKIASENTINELAWS12345"
JWT = "eyJSENTINEL.eyJpayloadSENTINEL.sigSENTINEL"
PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\nSENTINELKEYBODY\nmore\n"
    "-----END RSA PRIVATE KEY-----"
)


@pytest.mark.parametrize(
    "text",
    [
        AIZA,
        SK,
        GHP,
        AKIA,
        JWT,
        PEM,
        "Authorization: Bearer SENTINELtokenvalue123",
        "authorization: Basic U0VOVElORUw6cGFzcw==",
        'data-api-key="SENTINELvalue"',
        "const apiKey = 'SENTINELvalue';",
        '{"password": "SENTINELvalue"}',
        "secret=SENTINELvalue&x=1",
        '<script>var token = "SENTINELvalue"</script>',
        "https://user:SENTINELpass@host.example/path",
        "https://SENTINELpat@github.example/repo.git",
        "https://cdn.example/a.png?token=SENTINELvalue&w=1",
        "https://cdn.example/a.png?w=1&amp;key=SENTINELvalue",
        "slack xoxb-SENTINEL-1234567890",
    ],
)
def test_secret_shapes_are_redacted(text):
    out = redact_secrets(text)
    assert "SENTINEL" not in out and "SENTINEL".lower() not in out.lower()
    assert REDACTED in out
    assert redact_secrets(out) == out  # idempotent
    assert contains_secret(text) and not contains_secret(out)


@pytest.mark.parametrize(
    "text",
    [
        "",
        '<input type="password" name="password" autocomplete="current-password">',
        '<img src="logo.png" alt="Password reset illustration">',
        "Password: choose a strong one",
        '<a href="https://example.com:8080/docs?page=2&amp;lang=en">docs</a>',
        "mail me at someone@example.com",
        '<meta name="author" content="Jane">',
        '<button aria-describedby="token-help">Go</button>',
    ],
)
def test_ordinary_markup_is_left_alone(text):
    assert redact_secrets(text) == text


def test_url_credentials_keep_the_host():
    out = redact_secrets("go to https://bob:hunter22@intranet.example/x now")
    assert out == f"go to https://{REDACTED}@intranet.example/x now"


def test_redaction_happens_before_truncation():
    occ = ImageOccurrence(
        file="a.html", line=1, tag="<img>", src="a.png", alt=None,
        context=" " * 590 + f'<i data-token="{SK}">', lang="en",
    )  # fmt: skip
    payload = " ".join(_image_payload(occ))
    assert "sk-" not in payload and "SENTINEL" not in payload


def _project(tmp_path, secret_suffix=""):
    html = f"""<html lang="en"><body>
<script>var apiKey = "{SK}{secret_suffix}"; // {AIZA}</script>
<div data-token="{GHP}" data-aws="{AKIA}">
<a href="https://user:SENTINELpass@host.example/x?token={JWT}"><img src="i.png"
 alt="Logo {AIZA}"></a>
<p>Authorization: Bearer SENTINELbearer123456</p>
<pre>{PEM}</pre>
</div>
<img src="other.png" alt="plain">
</body></html>"""
    (tmp_path / "index.html").write_text(html, encoding="utf-8")
    (tmp_path / "i.png").write_bytes(PNG + b"1")
    (tmp_path / "other.png").write_bytes(PNG + b"2")


def _settings(tmp_path, **flags):
    flags.setdefault("api_key", "test-key")
    return config.load_settings(flags=flags, env={}, start_dir=tmp_path)


def _sent_text(provider: FakeProvider) -> str:
    return "\n".join(
        p for r in provider.requests for p in r.parts if isinstance(p, str)
    )


def _disk(tmp_path) -> str:
    return "\n".join(
        f.read_text(encoding="utf-8", errors="replace")
        for f in (tmp_path / ".bondy").rglob("*")
        if f.is_file()
    )


def test_secrets_never_reach_the_model_the_cache_or_any_report(tmp_path):
    _project(tmp_path)
    fake = FakeProvider()
    scan = run_scan(
        tmp_path, _settings(tmp_path), scanners=STUB, provider=fake, changed_only=False
    )
    sent = _sent_text(fake)
    assert "SENTINEL" not in sent and fake.http_requests == 1
    assert REDACTED in sent and "Logo" in sent  # the useful context is kept
    disk = _disk(tmp_path)
    assert disk and "SENTINEL" not in disk
    assert any("secret-like" in n for n in scan.notes)
    model = build_report(scan, project_root(tmp_path), version="1")
    assert model.items  # the alt-text finding exists
    for fmt in formats.FORMATS:
        assert "SENTINEL" not in formats.render(fmt, model, 1), fmt
    assert "SENTINEL" not in "\n".join(model.notes)
    assert all("SENTINEL" not in str(f) for f in model.fixes)


def test_cache_key_is_computed_from_redacted_context(tmp_path):
    _project(tmp_path, secret_suffix="v1")
    first = FakeProvider()
    run_scan(tmp_path, _settings(tmp_path), scanners=STUB, provider=first)
    assert first.http_requests == 1
    # same page, only the secret VALUE rotated: same redacted text -> cache hit
    _project(tmp_path, secret_suffix="v2")
    second = FakeProvider()
    r = run_scan(tmp_path, _settings(tmp_path), scanners=STUB, provider=second)
    assert second.http_requests == 0 and r.usage.cache_hits >= 1


def test_secret_pages_are_rescanned_not_reused(tmp_path):
    _project(tmp_path)
    run_scan(tmp_path, _settings(tmp_path), scanners=STUB, provider=FakeProvider())
    second = FakeProvider()
    r = run_scan(
        tmp_path, _settings(tmp_path), scanners=STUB, provider=second, changed_only=True
    )
    assert r.usage.pages_reused == 0 and r.usage.pages_scanned == 1
    assert second.http_requests == 0  # verdicts came from the cache


def test_env_file_is_never_loaded_as_an_image(tmp_path):
    (tmp_path / ".env").write_bytes(PNG + b"API_KEY=SENTINELenv")  # PNG magic!
    (tmp_path / "index.html").write_text(
        '<html lang="en"><body><img src=".env" alt="x"></body></html>',
        encoding="utf-8",
    )
    fake = FakeProvider()
    r = run_scan(tmp_path, _settings(tmp_path), scanners=STUB, provider=fake)
    assert fake.http_requests == 0
    assert "credentials file" in r.images[0].reason
    assert "SENTINEL" not in _sent_text(fake)


def test_cli_end_to_end_with_sentinels(tmp_path, monkeypatch, capsys):
    from bondy import scan as scan_mod
    from bondy.core.providers.gemini import GeminiProvider

    _project(tmp_path)
    for name in list(scan_mod.SCANNERS):
        monkeypatch.setitem(scan_mod.SCANNERS, name, lambda h: [])
    fake = FakeProvider()
    monkeypatch.setattr(
        GeminiProvider, "from_settings", classmethod(lambda cls, s, **kw: fake)
    )
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.chdir(tmp_path)
    for fmt in formats.FORMATS:
        cli.main(["scan", ".", "--format", fmt, "--fail-on", "never"])
        assert "SENTINEL" not in capsys.readouterr().out, fmt
    assert "SENTINEL" not in _sent_text(fake) and "SENTINEL" not in _disk(tmp_path)
