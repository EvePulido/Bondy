"""Single place that launches Chromium and confines what a scanned page can reach.

Every Playwright-based script (axe, contrast, focus order/trap, render_page) goes
through ``open_page`` so that:

* the browser is Playwright's Chromium, or, if that is missing or fails to start,
  the system Chrome / Edge (``channel="chrome"`` / ``"msedge"``);
* every network request the page makes is aborted unless it is ``data:`` /
  ``about:`` or a ``file://`` URL for the exact file (or folder) being scanned.
  Remote content is never fetched, so a hostile HTML cannot be used for SSRF or
  to leak the scan.

This module only imports Playwright lazily and never ADK / FastAPI / Gemini.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
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
SYSTEM_CHANNELS = ("chrome", "msedge")

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

    ``html`` is written to a temp file (removed on exit). The browser is always
    closed, and the page can only load the file itself, ``allowed_dirs`` and
    whatever ``allow_remote`` accepts.
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

    browser = None
    try:
        browser = launch_browser(playwright)
        ctx_kwargs: dict[str, Any] = {"accept_downloads": False}
        if viewport:
            ctx_kwargs["viewport"] = viewport
        context = browser.new_context(service_workers="block", **ctx_kwargs)
        install_network_guard(context, [target], allowed_dirs, allow_remote)
        page = context.new_page()
        page.goto(target.as_uri(), **(goto_kwargs or {}))
        yield page
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass
