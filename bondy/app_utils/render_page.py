"""Renders an HTML page to a PNG screenshot with headless Chromium.

Runs as a separate process (see vision_tools.py) so Playwright's sync API never
collides with the running asyncio event loop of the API server.

Usage:
    python -m bondy.app_utils.render_page --out shot.png --source examples/site_1
    python -m bondy.app_utils.render_page --out shot.png < page.html
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DEMO_SITES = (BASE_DIR / "examples").resolve()
MAX_HEIGHT = 4000


def render(html: str | None, source: str | None, out_path: str) -> None:
    from playwright.sync_api import sync_playwright

    from bondy.app_utils.browser import open_page

    temp_path = None
    if source:
        from bondy.app_utils.security import get_safe_demo_path

        target = Path(get_safe_demo_path(source)).resolve()
    else:
        fd, temp_path = tempfile.mkstemp(suffix=".html")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(html or "")
        target = Path(temp_path).resolve()

    try:
        with sync_playwright() as p:
            with open_page(
                p,
                path=target,
                allowed_dirs=[DEMO_SITES],
                viewport={"width": 1280, "height": 800},
                goto_kwargs={"wait_until": "load", "timeout": 20000},
            ) as page:
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
