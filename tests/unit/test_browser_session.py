"""Shared browser session (D6): one browser, timeouts, guaranteed close."""

import pytest

from bondy.app_utils import browser as bw


class FakePage:
    def goto(self, url, **kw):
        self.url = url


class FakeContext:
    def __init__(self, log):
        self.log = log
        self.closed = False

    def set_default_timeout(self, ms):
        self.log.append(("timeout", ms))

    def set_default_navigation_timeout(self, ms):
        self.log.append(("nav_timeout", ms))

    def route(self, pattern, handler):
        self.log.append(("route", pattern))

    def new_page(self):
        return FakePage()

    def close(self):
        self.closed = True
        self.log.append(("context_closed",))


class FakeBrowser:
    def __init__(self, log):
        self.log = log
        self.closed = False
        self.contexts: list[FakeContext] = []

    def is_connected(self):
        return not self.closed

    def new_context(self, **kw):
        c = FakeContext(self.log)
        self.contexts.append(c)
        return c

    def close(self):
        self.closed = True
        self.log.append(("browser_closed",))


class FakePW:
    def __init__(self, log):
        self.log = log

    def start(self):
        self.log.append(("pw_start",))
        return self

    def stop(self):
        self.log.append(("pw_stop",))


@pytest.fixture
def fakes(monkeypatch):
    log: list[tuple] = []
    browsers: list[FakeBrowser] = []

    def launch(pw):
        b = FakeBrowser(log)
        browsers.append(b)
        return b, "fake"

    monkeypatch.setattr(bw, "launch_with_label", launch)
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: FakePW(log))
    return log, browsers


def test_many_pages_share_one_browser_and_get_timeouts(fakes):
    log, browsers = fakes
    with bw.browser_session(page_timeout=12.5):
        for _ in range(3):
            with bw.playwright_context() as p, bw.open_page(p, html="<p>x</p>"):
                assert p is None  # the session owns the driver
    assert len(browsers) == 1
    assert log.count(("pw_start",)) == 1 and log.count(("context_closed",)) == 3
    assert ("timeout", 12500) in log and ("nav_timeout", 12500) in log
    assert browsers[0].closed and log[-1] == ("pw_stop",)


def test_browser_is_closed_when_the_block_raises(fakes):
    log, browsers = fakes
    with pytest.raises(RuntimeError):
        with bw.browser_session():
            with bw.open_page(None, html="<p>x</p>"):
                raise RuntimeError("scanner blew up")
    assert browsers[0].closed and ("pw_stop",) in log
    assert browsers[0].contexts[0].closed


def test_browser_is_closed_on_ctrl_c(fakes):
    log, browsers = fakes
    with pytest.raises(KeyboardInterrupt):
        with bw.browser_session():
            with bw.open_page(None, html="<p>x</p>"):
                raise KeyboardInterrupt
    assert browsers[0].closed and ("pw_stop",) in log


def test_session_without_pages_never_launches(fakes):
    log, browsers = fakes
    with bw.browser_session():
        pass
    assert browsers == [] and log == []


def test_launch_failure_is_remembered_not_retried(monkeypatch):
    calls = []

    def boom(pw):
        calls.append(1)
        raise bw.BrowserUnavailableError("none")

    monkeypatch.setattr(bw, "launch_with_label", boom)
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: FakePW([]))
    with bw.browser_session():
        for _ in range(3):
            with pytest.raises(bw.BrowserUnavailableError):
                with bw.open_page(None, html="x"):
                    pass
    assert len(calls) == 1


def test_sessions_are_per_thread(fakes):
    import threading

    seen = {}

    def other():
        seen["active"] = bw._active()

    with bw.browser_session():
        t = threading.Thread(target=other)
        t.start()
        t.join()
        assert bw._active() is not None
    assert seen["active"] is None and bw._active() is None


def test_timeout_settings_defaults_and_precedence(tmp_path):
    from bondy import config

    s = config.load_settings(flags={}, env={}, start_dir=tmp_path)
    assert s.timeout == 60.0 and s.scan_timeout == 900.0
    z = config.load_settings(
        flags={"timeout": 0, "scan_timeout": 5},
        env={"BONDY_TIMEOUT": "9"},
        start_dir=tmp_path,
    )
    assert z.timeout is None and z.scan_timeout == 5.0  # 0 = no limit
    e = config.load_settings(flags={}, env={"BONDY_TIMEOUT": "9"}, start_dir=tmp_path)
    assert e.timeout == 9.0 and e.sources["timeout"] == "env"


def test_run_scan_wraps_scanners_in_one_session(tmp_path, fakes, monkeypatch):
    """The pipeline opens exactly one session and passes the page timeout."""
    from bondy import config
    from bondy.core.pipeline import run_scan

    for n in "ab":
        (tmp_path / f"{n}.html").write_text("<html lang='en'><p>x</p></html>")
    sessions = []
    real = bw.browser_session

    def spy(timeout=None):
        sessions.append(timeout)
        return real(timeout)

    monkeypatch.setattr("bondy.core.pipeline.browser_session", spy)
    s = config.load_settings(
        flags={"no_llm": True, "timeout": 7}, env={}, start_dir=tmp_path
    )
    run_scan(tmp_path, s, scanners={"s": lambda h: []})
    assert sessions == [7.0]
