"""P4: several paths, live progress on stderr, notice of what is sent."""

import json

import pytest

from bondy import cli, config
from bondy.core.pipeline import project_root, run_scan
from bondy.core.providers.fake import FakeProvider
from bondy.scan import SCANNERS, discover

HTML = "<html lang='en'><body><p>hi</p></body></html>"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture
def stub_scanners(monkeypatch):
    for name in SCANNERS:
        monkeypatch.setitem(SCANNERS, name, lambda html: [])


def _site(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    for rel in ("a/one.html", "a/two.html", "b/three.html"):
        (tmp_path / rel).write_text(HTML, encoding="utf-8")
    return tmp_path


def test_discover_accepts_several_paths_in_order_without_duplicates(tmp_path):
    _site(tmp_path)
    got = discover(
        [
            tmp_path / "b" / "three.html",
            tmp_path / "a",  # folder containing one.html and two.html
            tmp_path / "a" / "one.html",  # reachable twice
            tmp_path / "b" / "three.html",  # same path again
        ],
        ["**/*.html"],
        [],
    )
    rel = [p.relative_to(tmp_path).as_posix() for p in got]
    assert rel == ["b/three.html", "a/one.html", "a/two.html"]


def test_project_root_of_several_paths_is_their_common_folder(tmp_path):
    _site(tmp_path)
    root = project_root([tmp_path / "a" / "one.html", tmp_path / "b" / "three.html"])
    assert root == tmp_path.resolve()
    assert project_root([tmp_path / "a" / "one.html"]) == (tmp_path / "a").resolve()


def test_cli_scans_several_paths_once_each(tmp_path, stub_scanners, capsys):
    _site(tmp_path)
    one, three = tmp_path / "a" / "one.html", tmp_path / "b" / "three.html"
    code = cli.main(
        ["scan", str(one), str(three), str(one), "--no-llm", "--format", "json"]
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert sorted(f["path"] for f in out["files"]) == ["a/one.html", "b/three.html"]


def test_cli_missing_path_names_every_missing_one_and_scans_nothing(
    tmp_path, stub_scanners, capsys
):
    _site(tmp_path)
    ok = tmp_path / "a" / "one.html"
    code = cli.main(
        ["scan", str(ok), str(tmp_path / "nope.html"), str(tmp_path / "x"), "--no-llm"]
    )
    captured = capsys.readouterr()
    assert code == 2 and captured.out == ""
    assert "2 paths not found" in captured.err
    assert "nope.html" in captured.err and str(tmp_path / "x") in captured.err


def test_cli_single_missing_path_message(tmp_path, capsys):
    assert cli.main(["scan", str(tmp_path / "gone.html")]) == 2
    assert "Path not found" in capsys.readouterr().err


def test_progress_goes_to_stderr_only_and_needs_a_tty_or_flag(
    tmp_path, stub_scanners, capsys
):
    _site(tmp_path)
    args = ["scan", str(tmp_path), "--no-llm", "--format", "json"]
    assert cli.main(args) == 0
    quiet_default = capsys.readouterr()
    assert "page 1/" not in quiet_default.err  # not a TTY under pytest

    assert cli.main([*args, "--progress"]) == 0
    shown = capsys.readouterr()
    json.loads(shown.out)  # stdout is still only the report
    assert "bondy: page 1/3: a/one.html" in shown.err
    assert "page 3/3: b/three.html" in shown.err

    assert cli.main([*args, "--progress", "--quiet"]) == 0
    assert "page 1/" not in capsys.readouterr().err


def test_progress_line_is_terminal_safe_and_redacted():
    line = cli._line_safe("img \x1b[31mred\x1b[0m\r token=ghp_" + "a1" * 20)
    assert "\x1b" not in line and "\r" not in line
    assert "ghp_" not in line
    assert len(cli._line_safe("x" * 1000)) <= cli._PROGRESS_MAX


def _llm_project(tmp_path):
    (tmp_path / "index.html").write_text(
        '<html lang="en"><body><img src="i0.png" alt="a"><img src="i1.png" alt="b">'
        '<img src="https://cdn.example.com/x.png" alt="c"></body></html>',
        encoding="utf-8",
    )
    (tmp_path / "i0.png").write_bytes(PNG + b"0")
    (tmp_path / "i1.png").write_bytes(PNG + b"1")


def _run(tmp_path, notices, **flags):
    from bondy.core.images import LoadedImage

    settings = config.load_settings(
        flags={"api_key": "k", **flags}, env={}, start_dir=tmp_path
    )
    provider = FakeProvider()
    seen_requests = []

    def notify(msg):
        seen_requests.append(provider.http_requests)  # requests when it was shown
        notices.append(msg)

    report = run_scan(
        tmp_path,
        settings,
        scanners={"stub": lambda html: []},
        provider=provider,
        loader=lambda occ: LoadedImage(PNG, "image/png"),
        notify=notify,
    )
    return report, provider, seen_requests


def test_notice_precedes_the_first_request_and_says_what_is_sent(tmp_path):
    _llm_project(tmp_path)
    notices: list[str] = []
    _, provider, at_notice = _run(tmp_path, notices)
    assert len(notices) == 1 and at_notice == [0] and provider.http_requests >= 1
    text = notices[0]
    assert "fake-provider.invalid" in text and "3 unique image(s)" in text
    assert "DOWNLOAD 1 http(s) image(s) from cdn.example.com" in text


def test_notice_reports_remote_opt_out(tmp_path):
    _llm_project(tmp_path)
    notices: list[str] = []
    _run(tmp_path, notices, remote_images=False)
    assert "will NOT be downloaded" in notices[0]


def test_no_notice_without_the_llm(tmp_path):
    _llm_project(tmp_path)
    notices: list[str] = []
    settings = config.load_settings(flags={"no_llm": True}, env={}, start_dir=tmp_path)
    run_scan(
        tmp_path, settings, scanners={"stub": lambda html: []}, notify=notices.append
    )
    assert notices == []


def test_semantic_stage_reports_progress_per_image_and_batch(tmp_path):
    from bondy.core.images import LoadedImage

    _llm_project(tmp_path)
    settings = config.load_settings(flags={"api_key": "k"}, env={}, start_dir=tmp_path)
    lines: list[str] = []
    run_scan(
        tmp_path,
        settings,
        scanners={"stub": lambda html: []},
        provider=FakeProvider(),
        loader=lambda occ: LoadedImage(PNG, "image/png"),
        progress=lines.append,
    )
    assert any(line.startswith("image 1/3: i0.png") for line in lines)
    assert any("asking the model, batch 1/1" in line for line in lines)
    assert any(line.startswith("page 1/1: index.html") for line in lines)
