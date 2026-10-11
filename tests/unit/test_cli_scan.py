import json

import pytest

from bondy import cli
from bondy.scan import SCANNERS, discover, exit_code, scan_html, scan_path

HTML = "<html lang='en'><body><img src='a.png'></body></html>"


def _stub(findings):
    return lambda html: list(findings)


CRIT = {"scanner": "stub", "wcag": ["1.1.1"], "severity": "critical", "message": "m"}
WARN = {"scanner": "stub", "wcag": ["2.4.3"], "severity": "warning", "message": "w"}


def test_discover_include_exclude(tmp_path):
    (tmp_path / "index.html").write_text(HTML)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.htm").write_text(HTML)
    (tmp_path / "sub" / "notes.txt").write_text("x")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "x.html").write_text(HTML)
    (tmp_path / "sub" / "node_modules").mkdir()
    (tmp_path / "sub" / "node_modules" / "y.html").write_text(HTML)
    found = discover(tmp_path, ["**/*.html", "**/*.htm"], ["node_modules/**"])
    assert [p.relative_to(tmp_path).as_posix() for p in found] == [
        "index.html",
        "sub/a.htm",
    ]


def test_discover_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        discover(tmp_path / "nope", ["**/*.html"], [])


def test_scan_html_isolates_scanner_errors_and_filters_checks():
    def boom(html):
        raise RuntimeError("browser missing\nmore")

    findings, errors = scan_html(
        HTML, scanners={"a": _stub([CRIT, WARN]), "b": boom}, checks=["WCAG 1.1.1"]
    )
    assert findings == [CRIT]
    assert errors == ["b: RuntimeError: browser missing"]


def test_exit_codes(tmp_path):
    f = tmp_path / "p.html"
    f.write_text(HTML)
    clean = scan_path(f, ["*.html"], [], scanners={"a": _stub([])})
    warn = scan_path(f, ["*.html"], [], scanners={"a": _stub([WARN])})
    crit = scan_path(f, ["*.html"], [], scanners={"a": _stub([CRIT])})
    assert exit_code(clean, "critical") == 0
    assert exit_code(warn, "critical") == 0
    assert exit_code(warn, "warning") == 1
    assert exit_code(crit, "critical") == 1
    assert exit_code(crit, "never") == 0

    def boom(html):
        raise RuntimeError("x")

    assert exit_code(scan_path(f, ["*.html"], [], scanners={"a": boom}), "never") == 2


def test_cli_json_output_and_exit_code(tmp_path, monkeypatch, capsys):
    (tmp_path / "p.html").write_text(HTML, encoding="utf-8")
    monkeypatch.setitem(SCANNERS, "axe", _stub([CRIT]))
    for name in [n for n in SCANNERS if n != "axe"]:
        monkeypatch.setitem(SCANNERS, name, _stub([]))
    monkeypatch.chdir(tmp_path)
    code = cli.main(["scan", str(tmp_path), "--no-llm", "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out["exit_code"] == 1 and out["mode"] == "no-llm"
    assert out["files"][0]["findings"][0]["severity"] == "critical"
    assert cli.main(["scan", str(tmp_path), "--fail-on", "never"]) == 0


def test_cli_usage_errors(tmp_path, capsys):
    assert cli.main(["scan", str(tmp_path / "missing")]) == 2
    bad = tmp_path / "bondy.toml"
    bad.write_text('format = "pdf"\n')
    assert cli.main(["scan", str(tmp_path), "--config", str(bad)]) == 2
    assert "config error" in capsys.readouterr().err


def test_cli_empty_folder(tmp_path, capsys):
    assert cli.main(["scan", str(tmp_path)]) == 0
    assert "No HTML files found" in capsys.readouterr().out


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert capsys.readouterr().out.startswith("bondy ")
