"""Web UI / POST /api/audit on the deterministic pipeline (P1).

No network, no browser, no API quota: scanners are stubs and the model is a
FakeProvider.
"""

import shutil
import uuid
from pathlib import Path
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from bondy import fast_api_app, scan
from bondy.core import checks, semantic, web_audit
from bondy.core.models import ScanReport, UsageSummary
from bondy.core.pipeline import NO_KEY_NOTE
from bondy.core.providers.fake import RATE_LIMIT_DAY, FakeProvider
from bondy.scan import FileResult

DEMO = Path(__file__).parents[2] / "demo_sites"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
HTML = "<html lang='en'><body><p>hi</p></body></html>"
CONTRACT_KEYS = {"finding_id", "wcag", "severity", "title", "before", "after"} | {
    "explanation"
}

F_IMG = {
    "scanner": "img-alt",
    "wcag": ["1.1.1"],
    "severity": "critical",
    "message": "Image without alt",
    "nodes": [{"html": '<img src="x.png">'}],
}
F_LANG = {
    "scanner": "lang",
    "wcag": ["3.1.1"],
    "severity": "warning",
    "message": "Missing lang",
    "nodes": [{"html": "<html>"}],
}


class _Found(list):
    stats: ClassVar[dict[str, int]] = {"passes": 40, "violations": 2, "needs_review": 1}


def _stub(findings, with_stats=False):
    def run(html):
        out = _Found(findings) if with_stats else list(findings)
        return out

    return {"stub": run}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No key, no cache writes: the real environment never leaks into a test."""
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "BONDY_NO_LLM"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BONDY_CACHE", "0")


@pytest.fixture
def client():
    return TestClient(fast_api_app.app)


@pytest.fixture
def demo_site():
    name = f"_test_web_{uuid.uuid4().hex[:8]}"
    folder = DEMO / name
    folder.mkdir()
    (folder / "index.html").write_text(
        '<html lang="en"><body><img src="a.png"></body></html>', encoding="utf-8"
    )
    (folder / "a.png").write_bytes(PNG)
    yield f"demo_sites/{name}"
    shutil.rmtree(folder, ignore_errors=True)


def _use_scanners(monkeypatch, scanners):
    monkeypatch.setattr(scan, "SCANNERS", scanners)


# ----- the pure adapter -----
def test_scan_to_payload_contract_and_stats(tmp_path):
    page = tmp_path / "p.html"
    result = FileResult(
        path=str(page),
        findings=[dict(F_IMG), dict(F_LANG)],
        html=HTML,
        axe_stats={"passes": 5, "violations": 1, "needs_review": 0},
    )
    scan_report = ScanReport(files=[result], usage=UsageSummary())
    payload, patch_ids = web_audit.scan_to_payload(
        scan_report, tmp_path, source_type="raw_html", file_path=None
    )
    assert payload["status"] == "success"
    assert payload["source_type"] == "raw_html" and payload["file_path"] is None
    assert payload["stats"] == {"passes": 5, "violations": 1, "needs_review": 0}
    assert payload["mode"] == "no-llm" and payload["partial"] is False
    assert len(payload["data"]) == 2 and patch_ids == set()
    for entry in payload["data"]:
        assert CONTRACT_KEYS <= set(entry)
        assert entry["severity"] in ("critical", "warning")
    first = payload["data"][0]
    assert first["wcag"] == "1.1.1" and first["before"] == '<img src="x.png">'


def test_stats_null_when_axe_did_not_run(tmp_path):
    result = FileResult(path=str(tmp_path / "p.html"), html=HTML)
    payload, _ = web_audit.scan_to_payload(
        ScanReport(files=[result], usage=UsageSummary()),
        tmp_path,
        source_type="raw_html",
        file_path=None,
    )
    assert payload["stats"] is None and payload["data"] == []


def test_rule_without_wcag_is_labelled_best_practice(tmp_path):
    finding = {**F_LANG, "wcag": [], "scanner": "axe", "rule": "region"}
    result = FileResult(path=str(tmp_path / "p.html"), findings=[finding], html=HTML)
    payload, _ = web_audit.scan_to_payload(
        ScanReport(files=[result], usage=UsageSummary()),
        tmp_path,
        source_type="raw_html",
        file_path=None,
    )
    assert payload["data"][0]["wcag"] == web_audit.BEST_PRACTICE


def test_crlf_is_normalised_in_snippets(tmp_path):
    finding = {**F_IMG, "nodes": [{"html": '<img\r\nsrc="x.png">'}]}
    result = FileResult(path=str(tmp_path / "p.html"), findings=[finding], html=HTML)
    payload, _ = web_audit.scan_to_payload(
        ScanReport(files=[result], usage=UsageSummary()),
        tmp_path,
        source_type="raw_html",
        file_path=None,
    )
    assert payload["data"][0]["before"] == '<img\nsrc="x.png">'


# ----- single source of the checks -> WCAG mapping -----
def test_resolve_criteria_groups_ids_and_criteria():
    assert checks.resolve_criteria(["images"]) == ["1.1.1"]
    assert checks.resolve_criteria(["WCAG 1.1.1", "images", "wcag 3.1.1"]) == [
        "1.1.1",
        "3.1.1",
    ]
    assert checks.resolve_criteria(["lang"]) == ["3.1.1"]
    with pytest.raises(ValueError, match="Unknown check"):
        checks.resolve_criteria(["axe"])  # no WCAG mapping: cannot filter


def test_groups_only_use_known_criteria():
    known = {w for c in checks.CHECKS for w in c.wcag}
    for group in checks.GROUPS:
        assert set(group.criteria) <= known


def test_checks_endpoint_serves_the_registry(client):
    r = client.get("/api/checks")
    assert r.status_code == 200
    body = r.json()
    ids = {g["id"]: g["criteria"] for g in body["groups"]}
    assert ids["images"] == ["WCAG 1.1.1"]
    assert {c["id"] for c in body["checks"]} == {c.id for c in checks.CHECKS}


def test_app_js_has_no_own_wcag_mapping():
    js = (
        Path(__file__).parents[2] / "bondy" / "resources" / "web" / "app.js"
    ).read_text(encoding="utf-8")
    assert "enabledChecks.push('WCAG" not in js


# ----- POST /api/audit -----
def test_audit_raw_html_without_key_runs_deterministic_and_keeps_contract(
    client, monkeypatch
):
    _use_scanners(monkeypatch, _stub([F_IMG, F_LANG], with_stats=True))
    r = client.post("/api/audit", json={"source": "raw_html", "raw_html": HTML})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["source_type"] == "raw_html" and body["file_path"] is None
    assert body["stats"] == {"passes": 40, "violations": 2, "needs_review": 1}
    assert body["mode"] == "no-llm"
    assert NO_KEY_NOTE in body["notes"]
    assert [d["wcag"] for d in body["data"]] == ["1.1.1", "3.1.1"]
    assert all(CONTRACT_KEYS <= set(d) for d in body["data"])
    # pasted HTML has no file to patch: no occurrence counts
    assert all("before_occurrences" not in d for d in body["data"])


def test_audit_raw_html_temp_dir_is_removed(client, monkeypatch):
    _use_scanners(monkeypatch, _stub([]))
    seen = []
    original = web_audit.run_scan

    def spy(target, *a, **kw):
        seen.append(Path(target))
        assert Path(target).read_text(encoding="utf-8") == HTML
        return original(target, *a, **kw)

    monkeypatch.setattr(web_audit, "run_scan", spy)
    r = client.post("/api/audit", json={"source": "raw_html", "raw_html": HTML})
    assert r.status_code == 200
    assert len(seen) == 1 and seen[0].name == "page.html"
    assert not seen[0].exists() and not seen[0].parent.exists()


def test_audit_raw_html_temp_dir_is_removed_on_failure(client, monkeypatch):
    seen = []

    def boom(target, *a, **kw):
        seen.append(Path(target))
        raise RuntimeError("scanner exploded")

    monkeypatch.setattr(web_audit, "run_scan", boom)
    r = client.post("/api/audit", json={"source": "raw_html", "raw_html": HTML})
    assert r.status_code == 500
    assert r.json() == {"status": "error", "message": "scanner exploded"}
    assert seen and not seen[0].parent.exists()


def test_audit_preserves_crlf_and_bom_in_raw_html(client, monkeypatch):
    _use_scanners(monkeypatch, _stub([]))
    seen = []
    original = web_audit.run_scan

    def spy(target, *a, **kw):
        seen.append(Path(target).read_bytes())
        return original(target, *a, **kw)

    monkeypatch.setattr(web_audit, "run_scan", spy)
    html = "\ufeff<html lang='en'>\r\n<body></body>\r\n</html>"
    r = client.post("/api/audit", json={"source": "raw_html", "raw_html": html})
    assert r.status_code == 200
    assert seen[0] == html.encode("utf-8")


@pytest.mark.parametrize(
    "source", ["../etc/passwd", "C:\\Windows\\win.ini", "bondy/config.py"]
)
def test_audit_rejects_unsafe_source_with_403(client, source):
    r = client.post("/api/audit", json={"source": source})
    assert r.status_code == 403
    assert r.json()["status"] == "error"


def test_audit_enabled_checks_filter_findings(client, monkeypatch):
    _use_scanners(monkeypatch, _stub([F_IMG, F_LANG]))
    r = client.post(
        "/api/audit",
        json={"source": "raw_html", "raw_html": HTML, "enabled_checks": ["images"]},
    )
    assert [d["wcag"] for d in r.json()["data"]] == ["1.1.1"]
    r = client.post(
        "/api/audit",
        json={
            "source": "raw_html",
            "raw_html": HTML,
            "enabled_checks": ["WCAG 3.1.1"],
        },
    )
    assert [d["wcag"] for d in r.json()["data"]] == ["3.1.1"]


def test_audit_enabled_checks_become_settings_checks(client, monkeypatch):
    captured = {}

    def spy(target, settings, **kw):
        captured["checks"] = list(settings.checks)
        return ScanReport(
            files=[FileResult(path=str(target), html=HTML)], usage=UsageSummary()
        )

    monkeypatch.setattr(web_audit, "run_scan", spy)
    client.post(
        "/api/audit",
        json={
            "source": "raw_html",
            "raw_html": HTML,
            "enabled_checks": ["images", "keyboard"],
        },
    )
    assert captured["checks"] == [
        "WCAG 1.1.1",
        "WCAG 2.4.4",
        "WCAG 2.1.2",
        "WCAG 2.4.3",
    ]


def test_audit_unknown_check_is_a_403(client, monkeypatch):
    _use_scanners(monkeypatch, _stub([]))
    r = client.post(
        "/api/audit",
        json={"source": "raw_html", "raw_html": HTML, "enabled_checks": ["nope"]},
    )
    assert r.status_code == 403
    assert "Unknown check" in r.json()["message"]


def test_audit_local_demo_with_provider_gives_patchable_fix(
    client, monkeypatch, demo_site
):
    _use_scanners(monkeypatch, _stub([F_LANG]))
    provider = FakeProvider()
    monkeypatch.setattr(fast_api_app, "_audit_provider", lambda: provider)
    r = client.post("/api/audit", json={"source": demo_site})
    assert r.status_code == 200
    body = r.json()
    assert body["source_type"] == "local_file" and body["file_path"] == demo_site
    assert body["mode"] == "llm" and NO_KEY_NOTE not in body["notes"]
    assert provider.http_requests == 1
    fix = next(d for d in body["data"] if d["finding_id"].startswith("img-"))
    assert fix["before"] == '<img src="a.png">'
    assert "Fake description 0" in fix["after"]
    assert fix["before_occurrences"] == 1
    # advice-only entries must never look applicable
    advice = [d for d in body["data"] if d is not fix]
    assert advice and all("before_occurrences" not in d for d in advice)


def test_audit_daily_quota_is_429(client, monkeypatch, demo_site):
    _use_scanners(monkeypatch, _stub([]))
    provider = FakeProvider([Exception(RATE_LIMIT_DAY)] * 2)
    monkeypatch.setattr(fast_api_app, "_audit_provider", lambda: provider)
    r = client.post("/api/audit", json={"source": demo_site})
    assert r.status_code == 429
    assert "Daily Gemini quota exhausted" in r.json()["message"]
    assert provider.http_requests <= 2


def test_audit_invalid_key_is_500_with_actionable_message(
    client, monkeypatch, demo_site
):
    _use_scanners(monkeypatch, _stub([]))
    bad = "400 INVALID_ARGUMENT API key not valid. API_KEY_INVALID"
    provider = FakeProvider([Exception(bad)] * 3)
    monkeypatch.setattr(fast_api_app, "_audit_provider", lambda: provider)
    r = client.post("/api/audit", json={"source": demo_site})
    assert r.status_code == 500
    assert "API key was rejected" in r.json()["message"]
    assert provider.http_requests == 1


def test_quota_marker_matches_the_semantic_stage_text():
    assert web_audit.QUOTA_DAILY_MARKER in semantic._KIND_TEXT["quota_daily"]


def test_audit_missing_demo_file_is_500(client):
    r = client.post("/api/audit", json={"source": "demo_sites/does_not_exist"})
    assert r.status_code == 500
    assert "File not found" in r.json()["message"]
