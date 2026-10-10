import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).parents[2]
    / "bondy/resources/skills/axe-accessibility-scanner/scripts/axe_scan.py"
)
SITE3 = Path(__file__).parents[2] / "demo_sites/site_3_mixed_errors/index.html"


def _load():
    spec = importlib.util.spec_from_file_location("axe_scan", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["axe_scan"] = module
    spec.loader.exec_module(module)
    return module


def test_wcag_criteria_conversion():
    m = _load()
    assert m._wcag_criteria(["wcag2a", "wcag143", "wcag1410", "wcag258"]) == [
        "1.4.3",
        "1.4.10",
        "2.5.8",
    ]


def test_severity_mapping():
    m = _load()
    assert m._impact_to_severity("critical") == "critical"
    assert m._impact_to_severity("serious") == "critical"
    assert m._impact_to_severity("moderate") == "warning"
    assert m._impact_to_severity(None) == "warning"


def test_scan_detects_known_violations():
    m = _load()
    try:
        report = m.scan(SITE3.read_text(encoding="utf-8"))
    except Exception as e:  # Chromium not installed in this environment
        pytest.skip(f"Playwright/Chromium unavailable: {e}")
    rules = {v["rule_id"] for v in report["violations"]}
    assert {"button-name", "html-has-lang", "label"} <= rules
    assert report["summary"]["passes"] > 0
    json.dumps(report)  # must be serializable
