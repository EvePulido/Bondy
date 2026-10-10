"""Scanners must never let the audited page reach the network.

The browser tests start a local HTTP server that records every request and scan
an HTML whose script/img/css/fetch/iframe all point at it: it must see none.
They are skipped when no Chromium (Playwright's or the system's) can start.
"""

import importlib.util
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from bondy.app_utils import browser as bw

ROOT = Path(__file__).parents[2]
SKILLS = ROOT / "bondy/resources/skills"


def _load(skill: str, script: str):
    path = SKILLS / skill / "scripts" / script
    spec = importlib.util.spec_from_file_location(f"guard_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ----- Policy (no browser needed) -----
def test_policy_allows_only_own_file_data_and_about(tmp_path):
    own = tmp_path / "page.html"
    other = tmp_path / "other.html"

    def allow(url):
        return bw.is_request_allowed(url, [own])

    assert allow(own.as_uri())
    assert not allow(other.as_uri())
    assert allow("data:text/plain,hi") and allow("about:blank")
    assert not allow("http://127.0.0.1:9/x.js")
    assert not allow("https://example.com/")
    assert not allow("ftp://example.com/")
    assert not allow("blob:null/abc")


def test_policy_allowed_dirs_and_remote_hook(tmp_path):
    (tmp_path / "sub").mkdir()
    inside = (tmp_path / "sub" / "a.png").as_uri()
    outside = (tmp_path.parent / "secret.png").as_uri()
    assert bw.is_request_allowed(inside, allowed_dirs=[tmp_path])
    assert not bw.is_request_allowed(outside, allowed_dirs=[tmp_path])
    assert bw.is_request_allowed(
        "https://ok.example/", allow_remote=lambda u: "ok.example" in u
    )
    assert not bw.is_request_allowed(
        "https://bad.example/", allow_remote=lambda u: "ok.example" in u
    )


# ----- Launcher fallback (fake Playwright) -----
class _FakeChromium:
    def __init__(self, working):
        self.working, self.calls = working, []

    def launch(self, headless=True, args=None, **kwargs):
        self.calls.append(kwargs)
        key = kwargs.get("channel") or kwargs.get("executable_path") or "playwright"
        if key not in self.working:
            raise RuntimeError(f"Executable doesn't exist ({key})\nmore detail")
        return f"browser:{key}"


class _FakePlaywright:
    def __init__(self, working):
        self.chromium = _FakeChromium(working)


def test_launcher_prefers_playwright_chromium(monkeypatch):
    monkeypatch.setattr(bw, "find_system_browsers", lambda: {})
    b, label = bw.launch_with_label(_FakePlaywright({"playwright", "chrome"}))
    assert b == "browser:playwright" and label == "Playwright Chromium"


def test_launcher_falls_back_to_chrome_then_edge(monkeypatch):
    monkeypatch.setattr(bw, "find_system_browsers", lambda: {})
    b, label = bw.launch_with_label(_FakePlaywright({"chrome", "msedge"}))
    assert b == "browser:chrome" and "chrome" in label
    b, label = bw.launch_with_label(_FakePlaywright({"msedge"}))
    assert b == "browser:msedge" and "Edge" in label


def test_launcher_uses_executable_path_when_channel_fails(monkeypatch):
    monkeypatch.setattr(bw, "find_system_browsers", lambda: {"chrome": "/x/chrome"})
    b, _ = bw.launch_with_label(_FakePlaywright({"/x/chrome"}))
    assert b == "browser:/x/chrome"


def test_launcher_error_has_exact_install_command(monkeypatch):
    monkeypatch.setattr(bw, "find_system_browsers", lambda: {})
    with pytest.raises(bw.BrowserUnavailableError) as e:
        bw.launch_with_label(_FakePlaywright(set()))
    assert "python -m playwright install chromium" in str(e.value)


# ----- Real browser: zero requests reach a local server -----
class _Recorder(BaseHTTPRequestHandler):
    hits: ClassVar[list[str]] = []

    def do_GET(self):
        type(self).hits.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"x")

    def log_message(self, *args, **kwargs):
        pass


@pytest.fixture
def server():
    _Recorder.hits = []
    srv = HTTPServer(("127.0.0.1", 0), _Recorder)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", _Recorder.hits
    srv.shutdown()
    srv.server_close()


def _hostile_html(base: str) -> str:
    port = base.rsplit(":", 1)[1]
    return f"""<!doctype html><html lang="en"><head><title>t</title>
<script src="{base}/x.js"></script>
<link rel="stylesheet" href="{base}/s.css">
</head><body>
<img src="{base}/i.png" alt="logo">
<iframe src="{base}/frame.html"></iframe>
<a href="#">link</a><button>ok</button>
<script>
fetch("{base}/fetch").catch(() => {{}});
try {{ new WebSocket("ws://127.0.0.1:{port}/ws"); }} catch (e) {{}}
</script>
</body></html>"""


@pytest.fixture(scope="module")
def need_browser():
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            bw.launch_browser(p).close()
    except Exception as e:
        pytest.skip(f"No browser available: {e}")


def test_control_unguarded_page_does_hit_the_server(server, need_browser):
    """Sanity: without the guard the recorder does see requests."""
    from playwright.sync_api import sync_playwright

    base, hits = server
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)  # no guard, no dead proxy
        page = b.new_page()
        page.goto(base + "/")
        b.close()
    assert hits


def test_axe_scan_makes_no_network_requests(server, need_browser):
    base, hits = server
    m = _load("axe-accessibility-scanner", "axe_scan.py")
    report = m.scan(_hostile_html(base))
    assert report["summary"]["passes"] > 0  # the page really was scanned
    assert hits == []


def test_contrast_makes_no_network_requests(server, need_browser):
    base, hits = server
    m = _load("text-contrast-calculator", "contrast.py")
    assert "issues" in m.check_contrast_in_page(_hostile_html(base))
    assert hits == []


def test_focus_trap_makes_no_network_requests(server, need_browser):
    base, hits = server
    m = _load("focus-trap-detector", "focus_trap.py")
    assert "trap_detected" in m.detect_focus_trap(_hostile_html(base))
    assert hits == []


def test_focus_order_makes_no_network_requests(server, need_browser):
    base, hits = server
    m = _load("focus-order-validator", "focus_order.py")
    assert "focus_sequence" in m.evaluate_focus_order(_hostile_html(base))
    assert hits == []


def test_render_page_makes_no_network_requests(server, need_browser, tmp_path):
    from bondy.app_utils import render_page

    base, hits = server
    out = tmp_path / "shot.png"
    render_page.render(_hostile_html(base), None, str(out))
    assert out.stat().st_size > 0
    assert hits == []


def test_content_that_looks_like_a_url_is_never_navigated(server, need_browser):
    """contrast/focus scripts used to page.goto() content starting with http://."""
    base, hits = server
    m = _load("text-contrast-calculator", "contrast.py")
    m.check_contrast_in_page(base + "/secret")
    f = _load("focus-order-validator", "focus_order.py")
    f.evaluate_focus_order(base + "/secret")
    assert hits == []
