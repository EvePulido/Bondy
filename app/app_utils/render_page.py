"""Renders an HTML page to a PNG screenshot with headless Chromium.

Runs as a separate process (see vision_tools.py) so Playwright's sync API never
collides with the running asyncio event loop of the API server.

Usage:
    python -m app.app_utils.render_page --out shot.png --source demo_sites/site_1
    python -m app.app_utils.render_page --out shot.png < page.html
"""

import argparse
import os
import socket
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parents[2]
DEMO_SITES = (BASE_DIR / "demo_sites").resolve()
MAX_HEIGHT = 4000


def _is_public_host(host: str, cache: dict[str, bool]) -> bool:
    if host not in cache:
        from app.app_utils.security import validate_public_url

        try:
            validate_public_url(f"https://{host}/")
            cache[host] = True
        except (ValueError, socket.gaierror):
            cache[host] = False
    return cache[host]


def _file_path_from_url(url: str) -> Path:
    parsed = urlparse(url)
    path = unquote(parsed.path)
    if os.name == "nt" and path.startswith("/"):
        path = path[1:]
    return Path(path).resolve()


def render(html: str | None, source: str | None, out_path: str) -> None:
    from playwright.sync_api import sync_playwright

    temp_path = None
    if source:
        from app.app_utils.security import get_safe_demo_path

        target = Path(get_safe_demo_path(source)).resolve()
    else:
        fd, temp_path = tempfile.mkstemp(suffix=".html")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(html or "")
        target = Path(temp_path).resolve()

    allowed_roots = [DEMO_SITES, target]
    host_cache: dict[str, bool] = {}

    def handle(route):
        url = route.request.url
        if url.startswith(("data:", "about:")):
            return route.continue_()
        if url.startswith("file:"):
            p = _file_path_from_url(url)
            ok = any(p == r or r in p.parents for r in allowed_roots)
            return route.continue_() if ok else route.abort()
        host = urlparse(url).hostname
        if url.startswith(("http://", "https://")) and host:
            return (
                route.continue_()
                if _is_public_host(host, host_cache)
                else route.abort()
            )
        return route.abort()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                page.route("**/*", handle)
                page.goto(target.as_uri(), wait_until="load", timeout=20000)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                height = page.evaluate("document.documentElement.scrollHeight")
                if height > MAX_HEIGHT:
                    page.screenshot(
                        path=out_path,
                        clip={"x": 0, "y": 0, "width": 1280, "height": MAX_HEIGHT},
                        full_page=True,
                    )
                else:
                    page.screenshot(path=out_path, full_page=True)
            finally:
                browser.close()
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def main() -> int:
    sys.path.insert(0, str(BASE_DIR))
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--source", default=None)
    args = parser.parse_args()

    html = None if args.source else sys.stdin.read()
    if not args.source and not (html or "").strip():
        print("No input provided", file=sys.stderr)
        return 1
    render(html, args.source, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
