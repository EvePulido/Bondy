import json
import os
import sys
import tempfile

from playwright.sync_api import sync_playwright


def evaluate_focus_order(content):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        is_file = False
        temp_path = None

        if content.startswith("http://") or content.startswith("https://"):
            page.goto(content)
        else:
            # Playwright sometimes struggles with set_content and focus, better to use file URL
            fd, temp_path = tempfile.mkstemp(suffix=".html")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            page.goto(f"file://{temp_path}")
            is_file = True

        focus_sequence = []
        anomalies = []

        # Simular 20 tabs
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

                // Un elemento visible tiene layout rect > 0
                const rect = el.getBoundingClientRect();
                const isVisible = rect.width > 0 && rect.height > 0;

                return {
                    selector: sel,
                    isVisible: isVisible,
                    tabIndex: el.getAttribute('tabindex')
                };
            }""")

            if focused_info:
                # Evitar reportar elementos consecutivos iguales si el foco no se movió
                if (
                    not focus_sequence
                    or focus_sequence[-1]["selector"] != focused_info["selector"]
                ):
                    focus_sequence.append(focused_info)
                    if not focused_info["isVisible"]:
                        anomalies.append(
                            f"El elemento {focused_info['selector']} recibe el foco pero no es visible."
                        )

        browser.close()

        if is_file and temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass

        return {
            "secuencia_foco": [item["selector"] for item in focus_sequence],
            "anomalias": anomalies,
        }


if __name__ == "__main__":
    content = sys.stdin.read()
    if not content.strip():
        print(json.dumps({"error": "No input provided"}))
        sys.exit(1)

    result = evaluate_focus_order(content)
    print(json.dumps(result, indent=2))
