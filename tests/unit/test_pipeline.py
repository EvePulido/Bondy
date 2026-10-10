"""Pipeline orchestration and the single checks registry (no network, no LLM)."""

from bondy import scan
from bondy.config import load_settings
from bondy.core import checks
from bondy.core.pipeline import NO_KEY_NOTE, run_scan

HTML = "<html lang='en'><body><p>hi</p></body></html>"
CRIT = {"scanner": "stub", "wcag": ["1.1.1"], "severity": "critical", "message": "m"}


def _settings(tmp_path, **flags):
    return load_settings(flags=flags, env={}, start_dir=tmp_path)


def test_pipeline_without_key_falls_back_to_deterministic(tmp_path):
    (tmp_path / "p.html").write_text(HTML, encoding="utf-8")
    report = run_scan(
        tmp_path, _settings(tmp_path), scanners={"a": lambda html: [dict(CRIT)]}
    )
    assert report.usage.mode == "no-llm" and NO_KEY_NOTE in report.notes
    assert report.usage.requests == 0
    assert report.files[0].findings == [CRIT]


def test_checks_registry_matches_scanner_findings():
    # every wcag value a scanner emits comes from the registry
    assert checks.check_wcag("lang") == ["3.1.1"]
    assert set(checks.ALL_CRITERIA) >= {"1.1.1", "3.1.1", "2.4.3"}
    for name in scan.SCANNERS:
        assert name in {c.id for c in checks.CHECKS}
    assert checks.all_criteria_instruction().startswith(
        "Audit all criteria (WCAG 1.1.1"
    )
