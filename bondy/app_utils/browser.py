"""Single place that launches Chromium and confines what a scanned page can reach.

Every Playwright-based script (axe, contrast, focus order/trap, render_page) goes
through ``open_page`` so that:

* the browser is Playwright's Chromium, or, if that is missing or fails to start,
  the system Chrome / Edge (``channel="chrome"`` / ``"msedge"``);
* every network request the page makes is aborted unless it is ``data:`` /
  ``about:`` or a ``file://`` URL for the exact file (or folder) being scanned.
  Remote content is never fetched, so a hostile HTML cannot be used for SSRF or
  to leak the scan.

A scan can share ONE browser (``browser_session``): every ``open_page`` inside
it gets a fresh, isolated context of that browser with the same network guard
and per-page timeouts, and the browser is always closed on exit (error or
Ctrl+C included). Outside a session each ``open_page`` launches its own.

Inside a session ``page_watchdog`` adds a HARD per-page limit: ``page.evaluate``
has no timeout in Playwright, so a page stuck in a JS loop after ``load`` would
block the scan indefinitely. When the budget expires a timer thread kills the
Playwright driver process tree (driver + browser); the blocked call fails with
"Connection closed", the page is reported as hung and the next page gets a
fresh driver and browser.

This module only imports Playwright lazily and never ADK / FastAPI / Gemini.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

# route() does not see WebSockets (and route_web_socket handlers deadlock with the
# sync API), so the browser also gets a dead proxy, loopback included: anything
# the guard misses simply cannot connect. file:// and data: are unaffected.
DEAD_PROXY_ARGS = [
    "--proxy-server=http://127.0.0.1:1",
    "--proxy-bypass-list=<-loopback>",
]
INSTALL_COMMAND = "python -m playwright install chromium"

SYSTEM_BROWSER_CANDIDATES = {
    "chrome": [
        "google-chrome",
        "google-chrome-stable",
        "chrome",
        "chromium",
        "chromium-browser",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ],
    "msedge": [
        "microsoft-edge",
        "msedge",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ],
}


class BrowserUnavailableError(RuntimeError):
    """No usable Chromium-based browser could be launched."""


class PageHungError(RuntimeError):
    """The page in progress exceeded its hard time budget and was killed."""


def find_system_browsers() -> dict[str, str]:
    """Chrome / Edge executables found on this machine, keyed by channel."""
    found: dict[str, str] = {}
    for channel, candidates in SYSTEM_BROWSER_CANDIDATES.items():
        for candidate in candidates:
            path = shutil.which(candidate) or (
                candidate
                if os.path.isabs(candidate) and os.path.exists(candidate)
                else None
            )
            if path:
                found[channel] = path
                break
    return found


def _first_line(exc: Exception) -> str:
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else type(exc).__name__


def launch_with_label(playwright: Any) -> tuple[Any, str]:
    """Launches a headless browser; returns ``(browser, label)``.

    Order: Playwright's Chromium, ``channel="chrome"``, ``channel="msedge"``, then
    the executables found on PATH / in the usual install folders. Raises
    ``BrowserUnavailableError`` with the exact install command if none starts.
    """
    attempts: list[tuple[str, dict[str, Any]]] = [
        ("Playwright Chromium", {}),
        ("system Chrome (channel=chrome)", {"channel": "chrome"}),
        ("system Edge (channel=msedge)", {"channel": "msedge"}),
    ]
    try:
        system = find_system_browsers()
    except Exception:
        system = {}
    names = {"chrome": "system Chrome", "msedge": "system Edge"}
    for channel, path in system.items():
        attempts.append((f"{names[channel]} ({path})", {"executable_path": path}))

    errors: list[str] = []
    for label, kwargs in attempts:
        try:
            return (
                playwright.chromium.launch(
                    headless=True, args=DEAD_PROXY_ARGS, **kwargs
                ),
                label,
            )
        except Exception as e:  # missing binary, incompatible version, sandbox...
            errors.append(f"{label}: {_first_line(e)}")
    raise BrowserUnavailableError(
        "No usable browser: Playwright Chromium is not installed and no system "
        "Chrome/Edge could be started. Install it with: "
        f"{INSTALL_COMMAND}  (tried: " + "; ".join(errors) + ")"
    )


def launch_browser(playwright: Any) -> Any:
    return launch_with_label(playwright)[0]


# ----- Network confinement -----
def _file_path_from_url(url: str) -> Path:
    path = unquote(urlparse(url).path)
    if os.name == "nt" and re.match(r"^/[A-Za-z]:", path):
        path = path[1:]
    return Path(path)


def _norm(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def is_request_allowed(
    url: str,
    allowed_files: Iterable[Path] = (),
    allowed_dirs: Iterable[Path] = (),
    allow_remote: Callable[[str], bool] | None = None,
) -> bool:
    """Policy for one request. Default: only data:/about: and the allowed files."""
    if url.startswith(("data:", "about:")):
        return True
    if url.startswith("file:"):
        try:
            p = _norm(_file_path_from_url(url))
        except (OSError, ValueError):
            return False
        if p in {_norm(f) for f in allowed_files}:
            return True
        return any(
            p == (d := _norm(root)) or p.startswith(d.rstrip(os.sep) + os.sep)
            for root in allowed_dirs
        )
    if allow_remote is not None and url.startswith(("http://", "https://")):
        return bool(allow_remote(url))
    return False


def install_network_guard(
    context: Any,
    allowed_files: Iterable[Path] = (),
    allowed_dirs: Iterable[Path] = (),
    allow_remote: Callable[[str], bool] | None = None,
) -> None:
    """Aborts every request of every page in ``context`` that the policy rejects."""
    files, dirs = list(allowed_files), list(allowed_dirs)

    def handle(route):
        if is_request_allowed(route.request.url, files, dirs, allow_remote):
            return route.continue_()
        return route.abort()

    context.route("**/*", handle)


class BrowserSession:
    """One lazily started Playwright driver + browser shared by a whole scan.

    Starting is lazy so a scan that never needs a browser (static mode, cached
    pages) never launches one. A failed start is remembered and re-raised, so
    later scanners do not retry the launch.
    """

    def __init__(self, page_timeout: float | None = None):
        # seconds; None = Playwright's default (30 s); 0 = no timeout
        self.page_timeout = page_timeout
        self.label: str | None = None
        self._pw: Any = None
        self._browser: Any = None
        self._error: BrowserUnavailableError | None = None
        self.launches = 0
        # hard-watchdog state (see page_watchdog)
        self._lock = threading.Lock()
        self._driver_dead = False  # driver tree was killed: restart before use
        self.page_hung = False  # the page in progress was killed by the watchdog
        self.hung_pages = 0

    def driver_pid(self) -> int | None:
        """PID of the Playwright driver (its child is the browser).

        Playwright exposes no public handle, so this reads private attributes
        defensively; None means the watchdog cannot act (the scan then simply
        keeps its cooperative timeouts).
        """
        try:
            proc = self._pw._impl_obj._connection._transport._proc
            return int(proc.pid)
        except Exception:
            return None

    def kill_driver(self) -> bool:
        """Kills the driver process tree (called from the watchdog thread)."""
        pid = self.driver_pid()
        if pid is None:
            return False
        self._driver_dead = True
        kill_process_tree(pid)
        return True

    def begin_page(self) -> None:
        """Forgets the hung state of the previous page."""
        self.page_hung = False

    def prepare(self) -> None:
        """Starts the browser (if needed) so launching never counts as page time.

        A failed launch is remembered by ``browser()`` and surfaces from the
        scanners as usual; it is not raised here.
        """
        self.begin_page()
        try:
            self.browser()
        except Exception:
            pass

    def browser(self) -> Any:
        if self._error is not None:
            raise self._error
        if self.page_hung:
            # the remaining browser scanners of a killed page must not relaunch
            # a browser just to hang again on the same page
            raise PageHungError("page exceeded its time budget (browser killed)")
        if self._driver_dead:
            pw = self._pw
            self._browser = self._pw = None
            self._driver_dead = False
            if pw is not None:
                try:
                    pw.stop()
                except Exception:
                    pass
        if self._browser is not None:
            try:
                if self._browser.is_connected():
                    return self._browser
            except Exception:
                pass
            self._browser = None  # crashed: start a new one
        try:
            if self._pw is None:
                from playwright.sync_api import sync_playwright

                self._pw = sync_playwright().start()
            self._browser, self.label = launch_with_label(self._pw)
            self.launches += 1
        except BrowserUnavailableError as e:
            self._error = e
            self.close()
            raise
        return self._browser

    def close(self) -> None:
        browser, pw = self._browser, self._pw
        self._browser = self._pw = None
        for closer in (browser and browser.close, pw and pw.stop):
            if closer:
                try:
                    closer()
                except Exception:
                    pass


def kill_process_tree(pid: int) -> None:
    """Best effort: ``pid`` and its descendants. Never raises."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=15,
                check=False,
            )
            return
        # the browser is the driver's direct child; its own helpers exit with it
        subprocess.run(
            ["pkill", "-KILL", "-P", str(pid)],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except Exception:
        pass
    if os.name != "nt":
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


class PageWatchdog:
    """Timer armed by ``BrowserSession.page_watchdog``; ``fired`` tells the outcome."""

    def __init__(self, session: BrowserSession, seconds: float):
        self.session = session
        self.seconds = seconds
        self.fired = False
        self._done = False
        self._timer = threading.Timer(seconds, self._fire)
        self._timer.daemon = True

    def _fire(self) -> None:
        with self.session._lock:  # held through the kill: disarm() waits for it
            if self._done:
                return
            self.session.page_hung = True
            self.fired = self.session.kill_driver()
            if not self.fired:
                self.session.page_hung = False
            else:
                self.session.hung_pages += 1

    def disarm(self) -> None:
        self._timer.cancel()
        with self.session._lock:
            self._done = True


@contextmanager
def page_watchdog(seconds: float | None = None) -> Iterator[PageWatchdog | None]:
    """Hard limit for the page scanned inside the block (needs a session).

    ``seconds`` defaults to the session's ``page_timeout``. Yields None (no
    watchdog) outside a session or when the limit is None / 0.
    """
    session = _active()
    limit = session.page_timeout if seconds is None and session else seconds
    if session is None or not limit or limit <= 0:
        yield None
        return
    session.begin_page()
    dog = PageWatchdog(session, float(limit))
    dog._timer.start()
    try:
        yield dog
    finally:
        dog.disarm()


def active_session() -> BrowserSession | None:
    """The browser session of the current scan (this thread), if any."""
    return _active()


def page_hung() -> bool:
    """True when the active session's current page was killed by the watchdog."""
    session = _active()
    return bool(session and session.page_hung)


# per thread: two scans in one process (library use) never share a session
_STATE = threading.local()


def _active() -> BrowserSession | None:
    return getattr(_STATE, "session", None)


@contextmanager
def browser_session(page_timeout: float | None = None) -> Iterator[BrowserSession]:
    """Shares one browser among every ``open_page`` call made inside the block."""
    previous, session = _active(), BrowserSession(page_timeout)
    _STATE.session = session
    try:
        yield session
    finally:
        _STATE.session = previous
        session.close()


@contextmanager
def playwright_context() -> Iterator[Any]:
    """What scanner scripts use instead of ``sync_playwright()``.

    Inside a ``browser_session`` it yields None (the session owns the driver and
    ``open_page`` ignores the argument); otherwise a real Playwright instance.
    """
    if _active() is not None:
        yield None
        return
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        yield p


@contextmanager
def open_page(
    playwright: Any,
    *,
    html: str | None = None,
    path: Path | str | None = None,
    allowed_dirs: Iterable[Path] = (),
    allow_remote: Callable[[str], bool] | None = None,
    viewport: dict[str, int] | None = None,
    goto_kwargs: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Yields a Playwright page already navigated to ``html`` or ``path``.

    ``html`` is written to a temp file (removed on exit). The page can only load
    the file itself, ``allowed_dirs`` and whatever ``allow_remote`` accepts. With
    an active ``browser_session`` the page lives in a throwaway context of the
    shared browser (closed on exit); otherwise a browser is launched from
    ``playwright`` and always closed.
    """
    if (html is None) == (path is None):
        raise ValueError("Pass exactly one of html or path")
    temp_path: str | None = None
    if html is not None:
        fd, temp_path = tempfile.mkstemp(suffix=".html")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(html)
        target = Path(temp_path).resolve()
    else:
        target = Path(str(path)).resolve()

    session = _active()
    browser = None
    context = None
    try:
        if session is not None:
            browser = session.browser()
        else:
            browser = launch_browser(playwright)
        ctx_kwargs: dict[str, Any] = {"accept_downloads": False}
        if viewport:
            ctx_kwargs["viewport"] = viewport
        # bypass_csp: the page's own Content-Security-Policy must not block the
        # scanner's injected scripts (axe). It does not open the network: the
        # route guard installed below still aborts every non-local request.
        context = browser.new_context(
            service_workers="block", bypass_csp=True, **ctx_kwargs
        )
        if session is not None and session.page_timeout is not None:
            ms = int(session.page_timeout * 1000)
            context.set_default_timeout(ms)
            context.set_default_navigation_timeout(ms)
        install_network_guard(context, [target], allowed_dirs, allow_remote)
        page = context.new_page()
        page.goto(target.as_uri(), **(goto_kwargs or {}))
        yield page
    finally:
        if session is not None:
            # A watchdog kill left no driver to answer: on Linux (CPython
            # 3.13) ``context.close()`` then blocks forever. The session
            # relaunches the whole browser, so the context needs no close.
            if context is not None and not (session.page_hung or session._driver_dead):
                try:
                    context.close()
                except Exception:
                    pass
        elif browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass
