"""A report written inside the scanned folder must not break the next scan, and
pages with a strict Content-Security-Policy must still be scannable."""

import json

import pytest

from bondy import cli
from bondy.scan import SCANNERS, run_scanners

PAGE = '<html lang="en"><body><img src="a.png"><button></button></body></html>'
CSP_PAGE = (
    '<html lang="en"><head><meta http-equiv="Content-Security-Policy" '
    "content=\"default-src 'none'; script-src 'none'\"></head>"
    "<body><button></button></body></html>"
)


def test_html_report_inside_the_project_is_skipped_on_the_next_scan(tmp_path, capsys):
    (tmp_path / "index.html").write_text(PAGE, encoding="utf-8")
    report = tmp_path / "report.html"
    cli.main(
        [
            "scan",
            str(tmp_path),
            "--static",
            "--no-llm",
            "--format",
            "html",
            "--output",
            str(report),
            "--fail-on",
            "never",
        ]
    )
    assert report.is_file()
    capsys.readouterr()

    code = cli.main(["scan", str(tmp_path), "--static", "--no-llm", "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    by_name = {f["path"].replace("\\", "/").split("/")[-1]: f for f in out["files"]}
    assert by_name["report.html"]["skipped"] == "Bondy report (not a page to scan)"
    assert by_name["report.html"]["findings"] == []
    assert by_name["report.html"]["errors"] == []
    assert code in (0, 1)  # findings from index.html, never 2 because of the report


def test_page_with_strict_csp_is_still_scanned_by_axe():
    findings, errors, unavailable = run_scanners(
        CSP_PAGE, scanners={"axe": SCANNERS["axe"]}
    )
    if unavailable:
        pytest.skip("no browser available for the axe scanner")
    assert errors == []  # was: "Executing inline script violates ... CSP"
    assert any(f["scanner"] == "axe" for f in findings)  # empty <button>
