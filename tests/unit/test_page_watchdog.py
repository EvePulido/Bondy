"""P1-2: hard per-page watchdog (a JS loop after ``load`` must not stall the scan)."""

import json
import time
import types

import pytest

from bondy import config
from bondy.app_utils import browser as bw
from bondy.core.pipeline import EXIT_PARTIAL, exit_code, run_scan
from bondy.scan import (
    PAGE_TIMEOUT_SKIP,
    SCAN_TIMEOUT_SKIP,
    FileResult,
    scan_loaded,
)

GOOD = (
    '<html lang="en"><head><title>T</title></head>'
    "<body><main><h1>Hi</h1></main></body></html>"
)
HUNG = (
    '<html lang="en"><head><title>T</title></head><body><main><h1>Hi</h1></main><script>'
    "window.addEventListener('load', () => setTimeout(() => { for (;;); }, 50));"
    "</script></body></html>"
)


def _settings(tmp_path, **flags):
    flags.setdefault("no_llm", True)
    return config.load_settings(flags=flags, env={}, start_dir=tmp_path)


# ----- no browser: fake driver, fast -----
class FakePW:
    """Just enough of Playwright's private chain for ``driver_pid``."""

    def __init__(self):
        proc = types.SimpleNamespace(pid=4242)
        transport = types.SimpleNamespace(_proc=proc)
        connection = types.SimpleNamespace(_transport=transport)
        self._impl_obj = types.SimpleNamespace(_connection=connection)
        self.stopped = False

    def stop(self):
        self.stopped = True


@pytest.fixture
def killed(monkeypatch):
    pids: list[int] = []
    monkeypatch.setattr(bw, "kill_process_tree", pids.append)
    fake_browser = types.SimpleNamespace(is_connected=lambda: True, close=lambda: None)
    monkeypatch.setattr(bw, "launch_with_label", lambda pw: (fake_browser, "fake"))
    return pids


def _pages(n):
    return [FileResult(path=f"p{i}.html", html=GOOD) for i in range(n)]


def test_hung_page_is_skipped_and_the_rest_is_scanned(killed):
    calls: list[str] = []

    def scanner(html):
        calls.append(html)
        if len(calls) == 2:  # second page: hangs until the watchdog kills it
            time.sleep(0.6)
            raise RuntimeError("Connection closed while reading from the driver")
        return [
            {
                "scanner": "s",
                "wcag": ["1.1.1"],
                "severity": "critical",
                "message": "m",
            }
        ]

    results = _pages(3)
    with bw.browser_session(0.2) as session:
        session._pw = FakePW()
        started = time.monotonic()
        scan_loaded(results, scanners={"s": scanner})
        elapsed = time.monotonic() - started
    assert killed == [4242]
    assert results[1].skipped.startswith(PAGE_TIMEOUT_SKIP)
    assert "0.2 s" in results[1].skipped
    assert results[1].findings == [] and results[1].errors == []
    assert [r.skipped for r in (results[0], results[2])] == [None, None]
    assert len(results[0].findings) == 1 and len(results[2].findings) == 1
    assert elapsed < 3
    assert session.hung_pages == 1


def test_remaining_browser_scanners_of_a_killed_page_are_not_run(killed, monkeypatch):
    from bondy import scan as scan_mod

    ran: list[str] = []

    def hang(html):
        time.sleep(0.5)
        raise RuntimeError("Connection closed")

    def after(html):
        ran.append("axe-after")
        return []

    monkeypatch.setattr(scan_mod, "BROWSER_SCANNERS", {"axe", "contrast"})
    results = _pages(1)
    with bw.browser_session(0.2) as session:
        session._pw = FakePW()
        scan_loaded(
            results,
            scanners={
                "axe": hang,
                "contrast": after,
                "lang": lambda h: ran.append("lang") or [],
            },
        )
    assert "axe-after" not in ran
    assert results[0].skipped.startswith(PAGE_TIMEOUT_SKIP)


def test_scan_deadline_caps_the_page_budget(killed):
    def slow(html):
        time.sleep(0.6)
        raise RuntimeError("Connection closed")

    results = _pages(2)
    with bw.browser_session(30) as session:  # page budget alone would be 30 s
        session._pw = FakePW()
        started = time.monotonic()
        scan_loaded(
            results,
            scanners={"s": slow},
            deadline=time.monotonic() + 0.2,
        )
        elapsed = time.monotonic() - started
    assert elapsed < 3
    assert [r.skipped for r in results] == [SCAN_TIMEOUT_SKIP, SCAN_TIMEOUT_SKIP]


def test_no_session_or_zero_timeout_means_no_watchdog(killed):
    results = _pages(1)
    scan_loaded(results, scanners={"s": lambda h: []})  # no session
    with bw.browser_session(0):
        scan_loaded(results, scanners={"s": lambda h: []})  # 0 = no limit
    assert killed == [] and results[0].skipped is None


def test_fast_page_disarms_the_timer(killed):
    results = _pages(1)
    with bw.browser_session(0.3) as session:
        session._pw = FakePW()
        scan_loaded(results, scanners={"s": lambda h: []})
        time.sleep(0.5)  # a leaked timer would fire now
    assert killed == [] and not session.page_hung


def test_browser_restarts_after_a_kill_but_not_within_the_same_page(monkeypatch):
    launched: list[object] = []

    def launch(pw):
        b = types.SimpleNamespace(is_connected=lambda: True, close=lambda: None)
        launched.append(b)
        return b, "fake"

    monkeypatch.setattr(bw, "launch_with_label", launch)
    session = bw.BrowserSession(5)
    first_pw = FakePW()
    session._pw = first_pw
    first = session.browser()
    session.page_hung = True
    session._driver_dead = True
    with pytest.raises(bw.PageHungError):
        session.browser()  # same page: no relaunch
    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: types.SimpleNamespace(start=lambda: FakePW()),
    )
    session.begin_page()
    second = session.browser()
    assert second is not first and len(launched) == 2
    assert first_pw.stopped


# ----- real Chromium: the scenario of the plan -----
@pytest.fixture(scope="module")
def need_browser():
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            bw.launch_browser(p).close()
    except Exception as e:
        pytest.skip(f"No browser available: {e}")


def test_js_loop_after_load_ends_at_the_timeout_and_scan_continues(
    tmp_path, need_browser
):
    (tmp_path / "a.html").write_text(GOOD, encoding="utf-8")
    (tmp_path / "b.html").write_text(HUNG, encoding="utf-8")
    (tmp_path / "c.html").write_text(GOOD, encoding="utf-8")
    stamps: list[tuple[str, float]] = []

    def progress(msg):
        stamps.append((msg, time.monotonic()))

    timeout = 4
    started = time.monotonic()
    report = run_scan(
        tmp_path,
        _settings(tmp_path, timeout=timeout, scan_timeout=0),
        resume=True,
        progress=progress,
    )
    total = time.monotonic() - started

    by_name = {r.path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]: r for r in report.files}
    hung = by_name["b.html"]
    assert hung.skipped and hung.skipped.startswith(PAGE_TIMEOUT_SKIP)
    assert by_name["a.html"].skipped is None and by_name["c.html"].skipped is None
    # c.html was really scanned (in a fresh browser): lang/axe ran without errors
    assert by_name["c.html"].errors == [] and by_name["c.html"].axe_stats

    # time spent on the hung page: its progress line to the next one
    pages = [t for m, t in stamps if m.startswith("page ")]
    assert len(pages) == 3
    hung_seconds = pages[2] - pages[1]
    print(
        f"hung page took {hung_seconds:.2f} s (timeout {timeout} s); total {total:.1f} s"
    )
    assert timeout <= hung_seconds < timeout + 8

    assert report.partial and exit_code(report, "critical") == EXIT_PARTIAL
    assert any(PAGE_TIMEOUT_SKIP in r for r in report.usage.partial_reasons)
    marker = json.loads(
        (tmp_path / ".bondy" / "cache" / "resume.json").read_text(encoding="utf-8")
    )
    assert marker["pages_pending"] == 1
    # the hung page is not stored for reuse; the finished ones are
    pages_json = json.loads(
        (tmp_path / ".bondy" / "cache" / "pages.json").read_text(encoding="utf-8")
    )
    saved = json.dumps(pages_json)
    assert "a.html" in saved and "c.html" in saved and "b.html" not in saved
