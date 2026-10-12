"""`bondy estimate` / `scan --dry-run` (B5): no model call, consistent numbers."""

import json

import pytest

from bondy import cli, config
from bondy import scan as scan_mod
from bondy.core.estimate import estimate_scan, format_estimate
from bondy.core.pipeline import run_scan
from bondy.core.providers.fake import FakeProvider

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def project(tmp_path, n=10, decorative=2, remote=0, broken=1):
    body = "".join(f'<img src="i{i}.png" alt="alt {i}">' for i in range(n))
    body += "".join(
        f'<img src="d{i}.png" role="presentation" alt="x">' for i in range(decorative)
    )
    body += "".join(
        f'<img src="https://cdn.example.com/r{i}.jpg" alt="remote {i}">'
        for i in range(remote)
    )
    body += "".join(f'<img src="gone{i}.png" alt="gone">' for i in range(broken))
    (tmp_path / "index.html").write_text(
        f'<html lang="en"><body>{body}</body></html>', encoding="utf-8"
    )
    for i in range(n):
        (tmp_path / f"i{i}.png").write_bytes(PNG)
    for i in range(decorative):
        (tmp_path / f"d{i}.png").write_bytes(PNG)
    return tmp_path


def settings(tmp_path, **flags):
    flags.setdefault("api_key", "k")
    return config.load_settings(flags=flags, env={}, start_dir=tmp_path)


@pytest.fixture
def no_model(monkeypatch):
    """Any attempt to build a provider or touch the network fails the test."""
    from bondy.core.providers.gemini import GeminiProvider

    def forbidden(*a, **k):
        raise AssertionError("estimate must not create/call a provider")

    monkeypatch.setattr(GeminiProvider, "from_settings", classmethod(forbidden))
    monkeypatch.setattr(GeminiProvider, "_send", forbidden)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", forbidden)


def test_counts_free_and_paid_images_and_batches(tmp_path, no_model):
    project(tmp_path, n=10, decorative=2, remote=3, broken=1)
    est = estimate_scan(tmp_path, settings(tmp_path, batch_size=4))
    assert est.pages == 1 and est.images_found == 16
    assert est.images_by_template == 2  # decorative signals
    assert est.images_unloadable == 1  # missing file
    assert est.images_remote == 3 and est.images_to_verify == 13
    assert est.batches == 4  # ceil(13 / 4)
    assert est.requests_min == 4 and est.requests_max == 8
    assert est.input_tokens_min > 13 * 1100  # per-image figure is included
    # no prices configured: tokens yes, dollars never invented
    assert est.cost_min_usd is None and est.cost_max_usd is None
    assert not est.prices_configured
    assert est.cost_unavailable_reason is not None
    assert "price_input_per_mtok" in est.cost_unavailable_reason


def test_estimate_matches_real_run_with_fake_provider(tmp_path):
    project(tmp_path, n=9, decorative=1, remote=0, broken=1)
    s = settings(tmp_path, batch_size=4)
    est = estimate_scan(tmp_path, s)
    p = FakeProvider()
    report = run_scan(tmp_path, s, scanners={"x": lambda h: []}, provider=p)
    assert p.http_requests == est.requests_min == report.usage.requests
    assert report.usage.images_unique == est.images_unique
    assert report.usage.images_by_template == est.images_by_template


def test_no_llm_estimate_is_zero(tmp_path, no_model):
    project(tmp_path)
    est = estimate_scan(tmp_path, settings(tmp_path, no_llm=True))
    assert est.requests_max == 0 and est.cost_max_usd is None
    assert "$0.00" in format_estimate(est)


def test_limits_are_reflected_in_the_estimate(tmp_path, no_model):
    project(tmp_path, n=10, decorative=0, broken=0)
    est = estimate_scan(
        tmp_path, settings(tmp_path, batch_size=2, max_requests=2, max_images=6)
    )
    assert est.images_to_verify == 6 and est.images_over_limit == 4
    assert est.batches == 3
    assert any("--max-requests" in w for w in est.exceeds_limits)


def test_cli_estimate_and_dry_run_never_scan_or_call(
    tmp_path, monkeypatch, capsys, no_model
):
    project(tmp_path, n=5, decorative=0, broken=0)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    def boom(html):
        raise AssertionError("dry-run must not run scanners")

    for name in list(scan_mod.SCANNERS):
        monkeypatch.setitem(scan_mod.SCANNERS, name, boom)

    assert cli.main(["estimate", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "requests: 1 to 2" in out and "ESTIMATE" in out
    assert "tokens: ~" in out
    assert "cost: not available" in out and "price_input_per_mtok" in out
    assert "~$" not in out and "PLACEHOLDER" not in out

    assert cli.main(["scan", str(tmp_path), "--dry-run", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["requests_min"] == 1 and "disclaimer" in data
    assert data["cost_min_usd"] is None and data["cost_unavailable_reason"]


def test_estimate_with_configured_prices_shows_cost_range(tmp_path, no_model):
    project(tmp_path, n=4, decorative=0, broken=0)
    (tmp_path / "bondy.toml").write_text(
        "price_input_per_mtok = 0.1\nprice_output_per_mtok = 0.4\n"
    )
    s = config.load_settings(flags={"api_key": "k"}, env={}, start_dir=tmp_path)
    est = estimate_scan(tmp_path, s)
    assert est.prices_configured and est.cost_unavailable_reason is None
    assert est.cost_min_usd is not None and est.cost_max_usd is not None
    assert 0 < est.cost_min_usd < est.cost_max_usd
    text = format_estimate(est)
    assert "~$" in text and "not available" not in text


def test_estimate_reflects_remote_images_opt_out(tmp_path, no_model):
    project(tmp_path, n=2, decorative=0, remote=3, broken=0)
    on = estimate_scan(tmp_path, settings(tmp_path))
    off = estimate_scan(tmp_path, settings(tmp_path, remote_images=False))
    assert on.images_remote == 3 and on.images_to_verify == 5 and on.remote_images
    assert off.images_remote == 0 and off.images_to_verify == 2
    assert off.images_unloadable == 3 and not off.remote_images


def test_estimate_mentions_default_request_limit(tmp_path, no_model):
    project(tmp_path, n=2, decorative=0, broken=0)
    est = estimate_scan(tmp_path, settings(tmp_path))
    assert est.request_limit == 50 and est.request_limit_is_default
    assert "default" in format_estimate(est)


def test_estimate_with_max_usd_and_no_prices_is_a_usage_error(
    tmp_path, monkeypatch, capsys, no_model
):
    project(tmp_path, n=2, decorative=0, broken=0)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert cli.main(["estimate", str(tmp_path), "--max-usd", "1"]) == 2
    assert "price_input_per_mtok" in capsys.readouterr().err


def test_estimate_discounts_cached_verdicts(tmp_path, no_model):
    project(tmp_path, n=4, decorative=0, broken=0)
    s = settings(tmp_path, batch_size=2)
    before = estimate_scan(tmp_path, s)
    assert before.requests_min == 2 and before.images_cached == 0
    run_scan(tmp_path, s, scanners={"x": lambda h: []}, provider=FakeProvider())
    after = estimate_scan(tmp_path, s)
    assert after.images_cached == 4 and after.images_to_verify == 0
    assert after.requests_min == 0 and after.requests_max == 0
