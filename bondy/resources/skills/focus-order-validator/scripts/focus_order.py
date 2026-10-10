import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

try:
    from bondy.app_utils.browser import open_page
except ImportError:  # run as a standalone script: put the package root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
    from bondy.app_utils.browser import open_page


def evaluate_focus_order(content: str) -> dict:
    """
    Simulates tab navigation using Playwright, records the focused elements,
    and returns the focus sequence and any detected accessibility anomalies.
    """
    with sync_playwright() as p:
        # open_page aborts every request except the temp file, data: and about:
        with open_page(p, html=content) as page:
            focus_sequence = []
            anomalies = []

            # Simulate 20 tabs
            for _ in range(20):
                page.keyboard.press("Tab")

                focused_info = page.evaluate("""() => {
                    const el = document.activeElement;
                    if (!el || el === document.body) return null;

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
                        selector: sel,
                        isVisible: isVisible,
                        tabIndex: el.getAttribute('tabindex')
                    };
                }""")

                if focused_info:
                    # Avoid reporting consecutive duplicate elements if focus did not move
                    if (
                        not focus_sequence
                        or focus_sequence[-1]["selector"] != focused_info["selector"]
                    ):
                        focus_sequence.append(focused_info)
                        if not focused_info["isVisible"]:
                            anomalies.append(
                                f"Element {focused_info['selector']} receives focus but is not visible."
                            )

        return {
            "focus_sequence": [item["selector"] for item in focus_sequence],
            "anomalies": anomalies,
        }


if __name__ == "__main__":
    content = sys.stdin.read()
    if not content.strip():
        print(json.dumps({"error": "No input provided"}))
        sys.exit(1)

    result = evaluate_focus_order(content)
    print(json.dumps(result, indent=2))
