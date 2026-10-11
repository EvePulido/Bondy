"""E2: baseline create / --baseline: only NEW findings count."""

import json
import re

import pytest

from bondy import cli
from bondy.core.baseline import BASELINE_VERSION
from bondy.core.formats import FORMATS
from bondy.scan import SCANNERS


def labels(html):
    """One critical finding per id="..." element, located by selector."""
    return [
        {
            "scanner": "labels",
            "wcag": ["1.3.1"],
            "severity": "critical",
            "message": f"control #{m} has no label",
            "selector": f"#{m}",
        }
        for m in re.findall(r'id="(\w+)"', html)
    ]


def page(*ids, pad=""):
    body = "".join(f'<input id="{i}">' for i in ids)
    return f'<html lang="en"><body>{pad}{body}</body></html>'


@pytest.fixture
def proj(tmp_path, monkeypatch):
    for name in SCANNERS:
        monkeypatch.setitem(SCANNERS, name, lambda html: [])
    monkeypatch.setitem(SCANNERS, "labels", labels)
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "a.html").write_text(page("one", "two"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(*argv):
    return cli.main(["scan", "site", "--no-llm", *argv])


def create(proj, *extra, out="base.json"):
    code = cli.main(["baseline", "create", "site", "--no-llm", "-o", out, *extra])
    return code, proj / out


def test_create_writes_a_deterministic_relative_baseline(proj, capsys):
    code, path = create(proj)
    assert code == 0 and "2 finding(s)" in capsys.readouterr().out
    first = path.read_text(encoding="utf-8")
    doc = json.loads(first)
    assert doc["version"] == BASELINE_VERSION and len(doc["findings"]) == 2
    assert {f["file"] for f in doc["findings"]} == {"a.html"}
    assert str(proj) not in first and "line" not in {
        k for f in doc["findings"] for k in f
    }
    create(proj)
    assert path.read_text(encoding="utf-8") == first  # byte-for-byte stable


def test_known_findings_are_hidden_and_exit_code_is_clean(proj, capsys):
    create(proj)
    capsys.readouterr()
    assert run("--fail-on", "warning") == 1  # without the baseline: fails
    capsys.readouterr()
    code = run("--baseline", "base.json", "--fail-on", "warning")
    out = capsys.readouterr().out
    assert code == 0
    assert "2 known finding(s) hidden" in out and "0 finding(s)" in out


def test_only_new_findings_fail_and_line_moves_do_not_matter(proj, capsys):
    create(proj)
    capsys.readouterr()
    (proj / "site" / "a.html").write_text(
        page("one", "two", "three", pad="\n\n\n"), encoding="utf-8"
    )
    code = run("--baseline", "base.json", "--format", "json")
    payload = json.loads(capsys.readouterr().out)
    found = payload["files"][0]["findings"]
    assert code == 1 and [f["selector"] for f in found] == ["#three"]
    assert payload["summary"]["findings"]["baselined"] == 2
    assert payload["baseline"]["matched"] == 2


def test_fixed_findings_are_reported_as_resolved(proj, capsys):
    create(proj)
    capsys.readouterr()
    (proj / "site" / "a.html").write_text(page("one"), encoding="utf-8")
    code = run("--baseline", "base.json")
    out = capsys.readouterr().out
    assert code == 0 and "1 resolved" in out
    assert "Resolved since the baseline was created" in out
    assert "bondy baseline create" in out  # next step suggests regenerating


def test_deleted_or_unscanned_files_are_not_claimed_as_resolved(proj, capsys):
    create(proj)
    capsys.readouterr()
    (proj / "site" / "a.html").unlink()
    (proj / "site" / "b.html").write_text(page(), encoding="utf-8")
    run("--baseline", "base.json", "--format", "json")
    payload = json.loads(capsys.readouterr().out)
    assert payload["baseline"]["resolved"] == 0
    assert payload["baseline"]["not_evaluated"] == 2


@pytest.mark.parametrize("fmt", FORMATS)
def test_every_format_applies_the_baseline_to_the_exit_code(proj, capsys, fmt):
    create(proj)
    (proj / "site" / "a.html").write_text(page("one", "two", "x"), encoding="utf-8")
    capsys.readouterr()
    assert run("--baseline", "base.json", "--format", fmt) == 1
    (proj / "site" / "a.html").write_text(page("one", "two"), encoding="utf-8")
    assert run("--baseline", "base.json", "--format", fmt) == 0
    capsys.readouterr()


def test_sarif_omits_baselined_results(proj, capsys):
    create(proj)
    capsys.readouterr()
    run("--baseline", "base.json", "--format", "sarif")
    doc = json.loads(capsys.readouterr().out)
    run_ = doc["runs"][0]
    assert run_["results"] == [] and run_["properties"]["bondy"]["baselined"] == 2


@pytest.mark.parametrize(
    ("content", "needle"),
    [
        ("{not json", "not valid JSON"),
        ("[]", "not a Bondy baseline"),
        (json.dumps({"schema": "bondy-baseline", "version": 99, "findings": []}),
         "format version 99"),
        (json.dumps({"schema": "bondy-baseline", "version": 1, "findings": "x"}),
         "malformed"),
    ],
)  # fmt: skip
def test_bad_baseline_is_a_usage_error_before_any_scan(
    proj, capsys, monkeypatch, content, needle
):
    (proj / "bad.json").write_text(content, encoding="utf-8")
    monkeypatch.setitem(
        SCANNERS, "labels", lambda h: pytest.fail("scan must not start")
    )
    code = run("--baseline", "bad.json")
    err = capsys.readouterr().err
    assert code == 2 and needle in err and "bondy baseline create" in err


def test_missing_baseline_is_a_usage_error(proj, capsys):
    assert run("--baseline", "nope.json") == 2
    assert "not found" in capsys.readouterr().err


def test_create_refuses_incomplete_scans(proj, capsys, monkeypatch):
    def boom(html):
        raise RuntimeError("scanner exploded")

    monkeypatch.setitem(SCANNERS, "labels", boom)
    code, path = create(proj)
    assert code == 2 and not path.exists()
    assert "nothing was written" in capsys.readouterr().err
    monkeypatch.setitem(SCANNERS, "labels", labels)
    (proj / "site" / "b.html").write_text(page("z"), encoding="utf-8")
    code, path = create(proj, "--max-pages", "1")
    assert code == 3 and not path.exists()


def test_baseline_path_in_bondy_toml_is_relative_to_that_file(proj, capsys):
    create(proj, out="site/base.json")
    (proj / "site" / "bondy.toml").write_text(
        'baseline = "base.json"\n', encoding="utf-8"
    )
    capsys.readouterr()
    code = cli.main(["scan", "site", "--no-llm", "--config", "site/bondy.toml"])
    assert code == 0 and "2 known finding(s) hidden" in capsys.readouterr().out


def test_checks_filter_does_not_mark_other_criteria_resolved(proj, capsys):
    create(proj)
    capsys.readouterr()
    run("--baseline", "base.json", "--checks", "WCAG 1.1.1", "--format", "json")
    payload = json.loads(capsys.readouterr().out)
    assert payload["baseline"]["resolved"] == 0
