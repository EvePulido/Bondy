import json
import sys
from pathlib import Path

try:
    from bondy.app_utils.browser import open_page, playwright_context
except ImportError:  # run as a standalone script: put the package root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
    from bondy.app_utils.browser import open_page, playwright_context


MAX_TABS = 60  # hard cap; the loop normally stops as soon as focus wraps around

_FOCUS_PROBE = """() => {
    const el = document.activeElement;
    if (!el || el === document.body || el === document.documentElement) return null;

    // Stable identity per DOM element: the same element focused again means the
    // Tab order wrapped around (and elements with the same selector stay apart).
    if (!window.__bondyFocusIds) {
        window.__bondyFocusIds = new WeakMap();
        window.__bondyFocusCount = 0;
    }
    const ids = window.__bondyFocusIds;
    if (!ids.has(el)) ids.set(el, ++window.__bondyFocusCount);

    let sel = el.tagName.toLowerCase();
    if (el.id) sel += '#' + el.id;
    else if (el.className && typeof el.className === 'string') {
        const c = el.className.split(' ')[0];
        if (c) sel += '.' + c;
    }

    // A visible element has a bounding rectangle width and height > 0
    const rect = el.getBoundingClientRect();
    const isVisible = rect.width > 0 && rect.height > 0;

    return {
        uid: ids.get(el),
        selector: sel,
        html: el.outerHTML.slice(0, 300),
        isVisible: isVisible,
        tabIndex: el.getAttribute('tabindex')
    };
}"""


def evaluate_focus_order(content: str) -> dict:
    """
    Simulates tab navigation using Playwright, records the focused elements,
    and returns the focus sequence and any detected accessibility anomalies.

    Each distinct element is visited once: the walk stops when focus wraps
    around (an element is focused a second time) or when there is nothing left
    to focus, so an invisible element yields ONE anomaly, not one per lap.
    ``invisible`` carries the same anomalies with the element's HTML snippet.
    """
    with playwright_context() as p:
        # open_page aborts every request except the temp file, data: and about:
        with open_page(p, html=content) as page:
            focus_sequence: list[dict] = []
            anomalies: list[str] = []
            invisible: list[dict] = []
            seen: set[int] = set()
            idle = 0

            for _ in range(MAX_TABS):
                page.keyboard.press("Tab")
                info = page.evaluate(_FOCUS_PROBE)

                if info is None:
                    # focus went to the document / browser UI: two in a row
                    # means no focusable element is left to reach
                    idle += 1
                    if idle >= 2:
                        break
                    continue
                idle = 0
                if info["uid"] in seen:
                    break  # wrapped around
                seen.add(info["uid"])
                focus_sequence.append(info)
                if not info["isVisible"]:
                    anomalies.append(
                        f"Element {info['selector']} receives focus but is not visible."
                    )
                    invisible.append(
                        {"selector": info["selector"], "html": info["html"]}
                    )

        return {
            "focus_sequence": [item["selector"] for item in focus_sequence],
            "anomalies": anomalies,
            "invisible": invisible,
        }


if __name__ == "__main__":
    content = sys.stdin.read()
    if not content.strip():
        print(json.dumps({"error": "No input provided"}))
        sys.exit(1)

    result = evaluate_focus_order(content)
    print(json.dumps(result, indent=2))
