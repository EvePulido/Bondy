"""E5: the closing summary (terminal and JSON) and its actionable next step."""

import json
import re

import pytest

from bondy import cli
from bondy.core.models import UsageSummary
from bondy.core.report import BaselineInfo, FileEntry, Item, Report, Suppression
from bondy.scan import SCANNERS


def item(severity="critical", **kw):
    return Item(
        file="a.html",
        scanner="labels",
        rule="labels",
        wcag=["1.3.1"],
        severity=severity,
        message="m",
        fingerprint=kw.pop("fingerprint", severity),
        **kw,
    )


def report(items=(), **kw):
    return Report(
        version="1",
        mode="no-llm",
        files=[FileEntry("a.html")],
        items=list(items),
        fixes=[],
        notes=[],
        usage=kw.pop("usage", UsageSummary()),
        **kw,
    )


def test_next_step_covers_every_state():
    assert "Nothing to do" in report().next_step()
    assert (
        "Fix the 2 new finding(s) (1 critical, 1 warning)"
        in report([item(), item("warning")]).next_step()
    )
    r = report()
    r.files[0].errors = ["boom"]
    assert "Fix the scan errors" in r.next_step()
    r = report(usage=UsageSummary(partial=True))
    assert "--resume" in r.next_step()
    r = report(suppressions=[Suppression("config", "x", "r", "why", status="obsolete")])
    assert "Remove the 1 obsolete" in r.next_step()
    r = report(baseline=BaselineInfo("b.json", known=3, resolved=2))
    assert "2 baselined finding(s) were fixed" in r.next_step()


def test_summary_counts_are_consistent():
    items = [item(), item("warning", fingerprint="w")]
    items[1].status = "baselined"
    s = report(items).summary()
    assert s["findings"] == {
        "new": {"critical": 1, "warning": 0, "total": 1},
        "baselined": 1,
        "suppressed": 0,
        "duplicates_merged": 0,
    }
    assert s["pages"]["total"] == 1 and s["partial"] is False


@pytest.fixture
def proj(tmp_path, monkeypatch):
    for name in SCANNERS:
        monkeypatch.setitem(SCANNERS, name, lambda html: [])

    def labels(html):
        out = []
        for i, m in enumerate(re.findall(r'<input id="(\w+)">', html)):
            out.append(
                {
                    "scanner": "labels",
                    "wcag": ["1.3.1"],
                    "severity": "critical" if i == 0 else "warning",
                    "message": f"#{m}",
                    "nodes": [{"selector": f"#{m}", "html": f'<input id="{m}">'}],
                }
            )
        return out

    monkeypatch.setitem(SCANNERS, "labels", labels)
    (tmp_path / "p.html").write_text(
        '<html lang="en"><body><input id="a"><input id="b"><input id="c">'
        "</body></html>",
        encoding="utf-8",
    )
    (tmp_path / "q.html").write_text(
        '<html lang="en"><body><p>x</p></body></html>', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_terminal_summary_has_every_number_and_the_next_step(proj, capsys):
    cli.main(["baseline", "create", ".", "--no-llm", "-o", "b.json"])
    cli.main(["scan", ".", "--no-llm", "--changed-only"])  # saves page state
    (proj / "p.html").write_text(
        '<html lang="en"><body><!-- bondy-ignore: labels -- legacy -->'
        '<input id="a"><input id="b"><input id="d"></body></html>',
        encoding="utf-8",
    )
    capsys.readouterr()
    code = cli.main(
        [
            "scan", ".", "--no-llm", "--baseline", "b.json", "--changed-only",
            "--fail-on", "warning",
        ]
    )  # fmt: skip
    out = capsys.readouterr().out
    assert code == 1
    assert "New findings: 1 (0 critical, 1 warning)" in out
    assert "Baseline (b.json): 1 known finding(s) hidden, 1 resolved" in out
    assert "Suppressed by ignore rules: 1 (1 rule(s) applied, 0 obsolete)" in out
    assert "Pages: 1 scanned, 1 reused from the previous scan, 0 skipped" in out
    assert "Suppressions applied:" in out and "reason: legacy" in out
    assert out.rstrip().splitlines()[-1].startswith("Next step: Fix the 1 new")


def test_json_summary_matches_the_terminal_numbers(proj, capsys):
    cli.main(["scan", ".", "--no-llm", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    s = data["summary"]
    assert s["findings"]["new"] == {"critical": 1, "warning": 2, "total": 3}
    assert s["pages"] == {
        "total": 2, "scanned": 2, "reused": 0, "skipped": 0, "with_errors": 0,
    }  # fmt: skip
    assert s["next_step"].startswith("Fix the 3 new finding(s)")
    assert len(data["files"][0]["findings"]) == 3
    cli.main(["scan", ".", "--no-llm"])
    assert "New findings: 3 (1 critical, 2 warning)" in capsys.readouterr().out


def test_clean_scan_says_nothing_to_do(proj, capsys):
    (proj / "p.html").write_text('<html lang="en"></html>', encoding="utf-8")
    assert cli.main(["scan", ".", "--no-llm"]) == 0
    assert "Next step: No new findings. Nothing to do." in capsys.readouterr().out
