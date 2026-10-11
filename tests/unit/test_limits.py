"""Hard limits (B6): requests, USD, pages, images -> PARTIAL result + exit code."""

import json

import pytest

from bondy import cli, config
from bondy.core.pipeline import EXIT_PARTIAL, exit_code, run_scan
from bondy.core.providers.fake import RATE_LIMIT_MINUTE, FakeProvider

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
STUB = {"stub": lambda html: []}


def settings(tmp_path, **flags):
    flags.setdefault("api_key", "test-key")
    return config.load_settings(flags=flags, env={}, start_dir=tmp_path)


def images(tmp_path, n, pages=1):
    per = n // pages
    for p in range(pages):
        body = "".join(
            f'<img src="i{p}_{i}.png" alt="alt {p} {i}">' for i in range(per)
        )
        (tmp_path / f"page{p}.html").write_text(
            f'<html lang="en"><body>{body}</body></html>', encoding="utf-8"
        )
        for i in range(per):
            (tmp_path / f"i{p}_{i}.png").write_bytes(PNG)


def run(tmp_path, provider=None, **flags):
    provider = provider or FakeProvider()
    report = run_scan(
        tmp_path, settings(tmp_path, **flags), scanners=STUB, provider=provider
    )
    return report, provider


def test_max_requests_stops_with_partial_result(tmp_path):
    images(tmp_path, 10)
    report, p = run(tmp_path, batch_size=2, max_requests=2)
    assert p.http_requests == 2 and report.usage.requests == 2
    assert report.partial
    assert any("--max-requests" in r for r in report.usage.partial_reasons)
    assert report.usage.images_verified == 4 and report.usage.images_skipped == 6
    assert exit_code(report, "critical") in (1, EXIT_PARTIAL)


def test_max_requests_also_caps_retries_inside_a_call(tmp_path):
    images(tmp_path, 2)
    p = FakeProvider([Exception(RATE_LIMIT_MINUTE)] * 3)
    report, p = run(tmp_path, p, max_requests=1)
    assert p.http_requests == 1  # the 429 retry would have been request #2
    assert report.usage.requests == 1 and report.partial


def test_max_usd_uses_configured_prices(tmp_path):
    images(tmp_path, 8)
    report, p = run(
        tmp_path,
        batch_size=2,
        max_usd=5.5,
        price_input_per_mtok=1000.0,
        price_output_per_mtok=0.0,
    )
    assert p.http_requests == 3  # 4th would project past $5.50
    assert any("--max-usd" in r for r in report.usage.partial_reasons)
    assert report.usage.cost_usd == pytest.approx(3.0)
    assert report.usage.cost_unavailable_reason is None
    assert report.usage.cost_is_estimate


def test_max_pages_skips_remaining_pages(tmp_path):
    images(tmp_path, 6, pages=3)
    report, _ = run(tmp_path, max_pages=2)
    skipped = [r for r in report.files if r.skipped]
    assert len(report.files) == 3 and len(skipped) == 1
    assert report.partial and "--max-pages" in report.usage.partial_reasons[0]
    assert report.usage.images_found == 4  # only the scanned pages


def test_max_images_limits_unique_images_sent(tmp_path):
    images(tmp_path, 5)
    report, p = run(tmp_path, max_images=3)
    assert report.usage.images_verified == 3 and report.usage.images_skipped == 2
    assert any("--max-images" in r for r in report.usage.partial_reasons)
    sent = sum(1 for r in p.requests for x in r.parts if not isinstance(x, str))
    assert sent == 3


def test_no_limits_is_not_partial(tmp_path):
    images(tmp_path, 4)
    report, _ = run(tmp_path)
    assert not report.partial and not report.usage.partial_reasons


def test_exit_codes_for_partial_results(tmp_path):
    images(tmp_path, 4)

    def accurate(request):
        n = sum(not isinstance(x, str) for x in request.parts)
        items = [
            {
                "index": i,
                "visible_content": "x",
                "matches_current_alt": "yes",
                "classification": "informative",
                "suggested_alt": "x",
                "confidence": "high",
                "uncertain_details": [],
            }
            for i in range(n)
        ]
        return json.dumps({"results": items})

    report, _ = run(tmp_path, FakeProvider(responder=accurate), max_images=1)
    assert report.partial and not any(r.findings for r in report.files)
    # unverified images (warnings only) + partial: cannot claim a clean pass
    assert exit_code(report, "critical") == EXIT_PARTIAL
    assert exit_code(report, "never") == 0
    # a finding at the threshold still wins: that fact holds regardless of partial
    report.files[0].findings.append(
        {"scanner": "s", "wcag": ["1.1.1"], "severity": "critical", "message": "m"}
    )
    assert exit_code(report, "critical") == 1


def test_limits_precedence_flag_env_file(tmp_path):
    (tmp_path / "bondy.toml").write_text("max_requests = 5\nmax_usd = 1.5\n")
    env = {"BONDY_MAX_REQUESTS": "7", "BONDY_MAX_PAGES": "0"}
    s = config.load_settings(
        flags={"max_images": 9, "max_requests": None},
        env=env,
        start_dir=tmp_path,
    )
    assert s.max_requests == 7 and s.sources["max_requests"] == "env"
    assert s.max_usd == 1.5 and s.sources["max_usd"] == "file"
    assert s.max_pages is None  # 0 = unlimited
    assert s.max_images == 9 and s.sources["max_images"] == "flag"
    s2 = config.load_settings(flags={"max_requests": 3}, env=env, start_dir=tmp_path)
    assert s2.max_requests == 3 and s2.sources["max_requests"] == "flag"
    with pytest.raises(config.ConfigError):
        config.load_settings(env={"BONDY_BATCH_SIZE": "0"}, start_dir=tmp_path)
    with pytest.raises(config.ConfigError):
        config.load_settings(env={"BONDY_MAX_USD": "abc"}, start_dir=tmp_path)


def test_no_default_prices(tmp_path):
    from bondy.core.budget import Pricing

    s = settings(tmp_path)
    assert s.price_input_per_mtok is None and s.price_output_per_mtok is None
    assert not Pricing.from_settings(s).available
    half = settings(tmp_path, price_input_per_mtok=1.0)
    assert not Pricing.from_settings(half).available
    full = settings(tmp_path, price_input_per_mtok=1.0, price_output_per_mtok=0.0)
    assert Pricing.from_settings(full).available  # 0 is a valid price


def test_usage_without_prices_reports_tokens_but_no_dollars(tmp_path):
    images(tmp_path, 2)
    report, _ = run(tmp_path)
    u = report.usage
    assert u.requests == 1 and u.input_tokens == 1000
    assert u.cost_usd is None and "price_input_per_mtok" in u.cost_unavailable_reason
    assert u.as_dict()["cost_usd"] is None


def test_default_request_limit_is_50_and_zero_removes_it(tmp_path):
    s = settings(tmp_path)
    assert s.max_requests == 50 and s.sources["max_requests"] == "default"
    assert settings(tmp_path, max_requests=0).max_requests is None
    (tmp_path / "bondy.toml").write_text("max_requests = 0\n")
    s2 = config.load_settings(flags={"api_key": "k"}, env={}, start_dir=tmp_path)
    assert s2.max_requests is None and s2.sources["max_requests"] == "file"


def test_reaching_default_limit_says_how_to_raise_it(tmp_path):
    images(tmp_path, 60)
    report, p = run(tmp_path, batch_size=1)  # default cap: 50 requests
    assert p.http_requests == 50 and report.partial
    reason = report.usage.partial_reasons[0]
    assert "default" in reason and "--max-requests N" in reason and "0" in reason
    assert report.usage.request_limit == 50 and report.usage.request_limit_is_default


def test_explicit_limit_is_not_reported_as_default(tmp_path):
    images(tmp_path, 4)
    report, _ = run(tmp_path, batch_size=1, max_requests=2)
    assert not report.usage.request_limit_is_default
    assert "default" not in report.usage.partial_reasons[0]


def test_max_usd_without_prices_fails_before_calling_provider(
    tmp_path, monkeypatch, capsys
):
    from bondy import scan as scan_mod
    from bondy.core.providers.gemini import GeminiProvider

    images(tmp_path, 2)

    def forbidden(*a, **k):
        raise AssertionError("provider must not be created or called")

    monkeypatch.setattr(GeminiProvider, "from_settings", classmethod(forbidden))
    for name in list(scan_mod.SCANNERS):
        monkeypatch.setitem(scan_mod.SCANNERS, name, forbidden)  # not even scanners
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["scan", str(tmp_path), "--max-usd", "0.5"]) == 2
    err = capsys.readouterr().err
    assert "--max-usd" in err and "price_input_per_mtok" in err
    assert "BONDY_PRICE_OUTPUT_PER_MTOK" in err
    # same with the library entry point
    with pytest.raises(config.ConfigError):
        run_scan(
            tmp_path,
            settings(tmp_path, max_usd=0.5),
            scanners=STUB,
            provider=FakeProvider(),
        )


def test_max_usd_without_prices_is_ignored_in_no_llm_mode(tmp_path):
    images(tmp_path, 1)
    report = run_scan(
        tmp_path, settings(tmp_path, max_usd=0.5, no_llm=True), scanners=STUB
    )
    assert report.usage.mode == "no-llm"


def test_remote_images_opt_out_makes_no_download_and_goes_to_manual_review(
    tmp_path, monkeypatch
):
    from bondy.core.images import REMOTE_DISABLED_REASON

    (tmp_path / "p.html").write_text(
        '<html lang="en"><body><img src="https://cdn.example.com/a.jpg" alt="Remote">'
        '<img src="//cdn.example.com/b.jpg" alt="Proto"></body></html>',
        encoding="utf-8",
    )

    def forbidden(*a, **k):
        raise AssertionError("no network/validation call allowed with the opt-out")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", forbidden)
    monkeypatch.setattr("bondy.app_utils.security.validate_public_url", forbidden)
    monkeypatch.setattr("bondy.core.netguard.fetch_public_bytes", forbidden)
    report, p = run(tmp_path, remote_images=False)  # default loader
    assert p.http_requests == 0 and report.usage.requests == 0
    assert [o.recommendation for o in report.images] == ["needs_manual_review"] * 2
    assert all("--no-remote-images" in o.reason for o in report.images)
    assert REMOTE_DISABLED_REASON in report.images[0].reason


def test_remote_images_enabled_by_default_and_flag_precedence(tmp_path):
    assert settings(tmp_path).remote_images is True
    assert settings(tmp_path, remote_images=False).remote_images is False
    (tmp_path / "bondy.toml").write_text("remote_images = false\n")
    f = config.load_settings(flags={}, env={}, start_dir=tmp_path)
    assert f.remote_images is False and f.sources["remote_images"] == "file"
    e = config.load_settings(
        flags={}, env={"BONDY_REMOTE_IMAGES": "true"}, start_dir=tmp_path
    )
    assert e.remote_images is True and e.sources["remote_images"] == "env"
    g = config.load_settings(
        flags={"remote_images": False},
        env={"BONDY_REMOTE_IMAGES": "true"},
        start_dir=tmp_path,
    )
    assert g.remote_images is False and g.sources["remote_images"] == "flag"


def test_cli_no_remote_images_flag(tmp_path, monkeypatch, capsys):
    from bondy import scan as scan_mod
    from bondy.core.providers.gemini import GeminiProvider

    (tmp_path / "p.html").write_text(
        '<html lang="en"><img src="https://cdn.example.com/a.jpg" alt="R"></html>',
        encoding="utf-8",
    )
    for name in list(scan_mod.SCANNERS):
        monkeypatch.setitem(scan_mod.SCANNERS, name, lambda h: [])
    fake = FakeProvider()
    monkeypatch.setattr(
        GeminiProvider, "from_settings", classmethod(lambda cls, s, **kw: fake)
    )

    def no_network(*a, **k):
        raise AssertionError("network")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", no_network)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.chdir(tmp_path)
    cli.main(["scan", str(tmp_path), "--no-remote-images", "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    assert fake.http_requests == 0
    assert out["usage"]["images_manual_review"] == 1
    assert out["usage"]["cost_usd"] is None and out["usage"]["cost_unavailable_reason"]


def test_cli_partial_exit_code_and_message(tmp_path, monkeypatch, capsys):
    from bondy import scan as scan_mod
    from bondy.core.providers.gemini import GeminiProvider

    images(tmp_path, 4)
    for name in list(scan_mod.SCANNERS):
        monkeypatch.setitem(scan_mod.SCANNERS, name, lambda h: [])
    fake = FakeProvider()
    monkeypatch.setattr(
        GeminiProvider, "from_settings", classmethod(lambda cls, s, **kw: fake)
    )
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.chdir(tmp_path)
    code = cli.main(
        ["scan", str(tmp_path), "--batch-size", "1", "--max-requests", "1",
         "--fail-on", "warning", "--format", "json"]
    )  # fmt: skip
    out = json.loads(capsys.readouterr().out)
    # fixes (warnings/criticals) exist -> findings reach the threshold: exit 1
    assert code == 1 and out["usage"]["partial"] is True
    assert out["usage"]["requests"] == 1
    code = cli.main(["scan", str(tmp_path), "--batch-size", "1", "--max-requests", "1"])
    assert "PARTIAL RESULT" in capsys.readouterr().out and code in (1, 3)
