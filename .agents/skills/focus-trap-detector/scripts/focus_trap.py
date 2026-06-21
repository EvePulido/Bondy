import json
import os
import sys
import tempfile

from playwright.sync_api import sync_playwright


def detect_focus_trap(content: str) -> dict:
    """
    Simulates tab navigation using Playwright to detect if focus becomes
    trapped within a subset of elements (modal dialog, dropdown menu, etc.).
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        is_file = False
        temp_path = None

        if content.startswith("http://") or content.startswith("https://"):
            page.goto(content)
        else:
            fd, temp_path = tempfile.mkstemp(suffix=".html")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            page.goto(f"file://{temp_path}")
            is_file = True

        focus_sequence = []

        # Simulate 30 tabs
        for _ in range(30):
            page.keyboard.press("Tab")

            sel = page.evaluate("""() => {
                const el = document.activeElement;
                if (!el || el === document.body) return null;
                let s = el.tagName.toLowerCase();
                if (el.id) s += '#' + el.id;
                return s;
            }""")

            if sel:
                focus_sequence.append(sel)

        browser.close()

        if is_file and temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass

        # Detect cycle
        trap = False
        unique_elements = (
            set(focus_sequence[-10:])
            if len(focus_sequence) >= 10
            else set(focus_sequence)
        )

        # If after 30 tabs the focus keeps cycling between a very small set of elements (<= 3)
        if (
            len(focus_sequence) >= 30
            and len(unique_elements) > 0
            and len(unique_elements) <= 3
        ):
            trap = True

        return {
            "trap_detected": trap,
            "involved_selectors": list(unique_elements),
            "num_presses_without_exit": 30 if trap else 0,
        }


if __name__ == "__main__":
    content = sys.stdin.read()
    if not content.strip():
        print(json.dumps({"error": "No input provided"}))
        sys.exit(1)

    result = detect_focus_trap(content)
    print(json.dumps(result, indent=2))
