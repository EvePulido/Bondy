import json

from bondy import cli, doctor
from bondy.app_utils import browser as bw
from bondy.scan import SCANNERS, exit_code, scan_path, static_mode_note

PAGE = """<html><body>
<img src="a.png">
<img src="b.png" alt="">
<img src="c.png" alt="chart">
<img src="d.png" role="presentation">
<input type="text" id="q">
<button></button>
</body></html>"""

CLEAN = (
    '<html lang="en"><body><img src="a.png" alt="x"><a href="/">Home</a></body></html>'
)


def _no_browser(monkeypatch):
    def boom(playwright):
        raise bw.BrowserUnavailableError("No usable browser ... install it")

    monkeypatch.setattr(bw, "launch_with_label", boom)


def test_static_mode_runs_html_checks_and_reports_omissions(tmp_path, monkeypatch):
    _no_browser(monkeypatch)
    (tmp_path / "a.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "b.html").write_text(PAGE, encoding="utf-8")
    results = scan_path(tmp_path, ["*.html"], [])
    assert len(results) == 2
    for r in results:
        assert r.errors == []  # an absent browser is not an error
        assert set(r.omitted) == {"axe", "contrast", "focus-trap", "focus-order"}
        scanners = {f["scanner"] for f in r.findings}
        assert {"lang", "labels", "accessible-name", "img-alt"} <= scanners
        alt = [f for f in r.findings if f["scanner"] == "img-alt"]
        assert len(alt) == 1  # only <img src="a.png"> lacks alt
    note = static_mode_note(results)
    assert "STATIC MODE" in note and "python -m playwright install chromium" in note
    assert "axe" in note and "contrast" in note


def test_cli_static_mode_exit_codes_and_notes(tmp_path, monkeypatch, capsys):
    _no_browser(monkeypatch)
    (tmp_path / "p.html").write_text(PAGE, encoding="utf-8")
    code = cli.main(["scan", str(tmp_path), "--no-llm", "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out["exit_code"] == 1  # findings, not 2
    assert out["static_mode"] is True
    assert any("STATIC MODE" in n for n in out["notes"])
    assert out["files"][0]["errors"] == []
    assert "axe" in out["files"][0]["omitted_checks"]

    only = tmp_path / "only"
    only.mkdir()
    (only / "ok.html").write_text(CLEAN, encoding="utf-8")
    assert cli.main(["scan", str(only), "--no-llm"]) == 0
    assert "STATIC MODE" in capsys.readouterr().out


def test_real_scanner_error_still_exits_2_in_static_mode(tmp_path, monkeypatch):
    _no_browser(monkeypatch)
    (tmp_path / "p.html").write_text(PAGE, encoding="utf-8")

    def broken(html):
        raise RuntimeError("bug")

    monkeypatch.setitem(SCANNERS, "lang", broken)
    results = scan_path(tmp_path, ["*.html"], [])
    assert any("lang: RuntimeError" in e for e in results[0].errors)
    assert exit_code(results, "critical") == 2


def test_doctor_reports_which_browser_will_be_used(monkeypatch):
    class Fake:
        def close(self):
            pass

    monkeypatch.setattr(
        doctor, "launch_with_label", lambda p: (Fake(), "system Edge (channel=msedge)")
    )
    c = doctor.check_browser()
    assert c.status == "ok" and "system Edge" in c.detail


def test_doctor_warns_about_static_mode_with_install_command(monkeypatch):
    def boom(p):
        raise bw.BrowserUnavailableError("none")

    monkeypatch.setattr(doctor, "launch_with_label", boom)
    monkeypatch.setattr(doctor, "find_system_browsers", lambda: {})
    c = doctor.check_browser()
    assert c.status == "warn" and "STATIC" in c.detail
    assert c.fix == "python -m playwright install chromium"


def test_static_flag_never_launches_a_browser(tmp_path, monkeypatch, capsys):
    def must_not_launch(playwright):
        raise AssertionError("browser launched despite --static")

    monkeypatch.setattr(bw, "launch_with_label", must_not_launch)
    (tmp_path / "p.html").write_text(PAGE, encoding="utf-8")
    code = cli.main(["scan", str(tmp_path), "--no-llm", "--static", "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1  # findings from the HTML-only checks, not a usage error
    assert out["static_mode"] is True
    assert out["files"][0]["errors"] == []
    note = " ".join(out["notes"])
    assert "--static" in note and "playwright install" not in note


def test_static_can_be_set_from_environment(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BONDY_STATIC", "1")
    monkeypatch.setattr(
        bw,
        "launch_with_label",
        lambda p: (_ for _ in ()).throw(AssertionError("launched")),
    )
    (tmp_path / "ok.html").write_text(CLEAN, encoding="utf-8")
    assert cli.main(["scan", str(tmp_path), "--no-llm"]) == 0
    assert "STATIC MODE" in capsys.readouterr().out


def test_render_page_allows_no_remote_hosts():
    import inspect

    from bondy.app_utils import render_page

    src = inspect.getsource(render_page)
    assert "allow_remote" not in src and "_is_public_host" not in src
