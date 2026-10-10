import json
import os
import sys
import tempfile

from playwright.sync_api import sync_playwright


def check_contrast_in_page(content: str) -> dict:
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

        # Extract contrast data using page.evaluate
        results = page.evaluate("""() => {
            function parseRGB(color) {
                const rgb = color.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                if (rgb) return [parseInt(rgb[1]), parseInt(rgb[2]), parseInt(rgb[3])];
                return [0, 0, 0];
            }
            function getLuminance(r, g, b) {
                let a = [r, g, b].map(function (v) {
                    v /= 255;
                    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
                });
                return a[0] * 0.2126 + a[1] * 0.7152 + a[2] * 0.0722;
            }
            function getContrastRatio(l1, l2) {
                const lighter = Math.max(l1, l2);
                const darker = Math.min(l1, l2);
                return (lighter + 0.05) / (darker + 0.05);
            }
            function isTransparent(color) {
                return color === 'transparent' || color === 'rgba(0, 0, 0, 0)';
            }
            function getEffectiveBackground(element) {
                let current = element;
                while (current && current !== document) {
                    const bg = window.getComputedStyle(current).backgroundColor;
                    if (!isTransparent(bg)) return bg;
                    current = current.parentElement;
                }
                return 'rgb(255, 255, 255)'; // Default white
            }

            const issues = [];
            const elements = document.querySelectorAll('h1, h2, h3, h4, h5, h6, p, span, a, button, li, label, div');

            elements.forEach(el => {
                if (!el.innerText || !el.innerText.trim()) return;

                // Ensure the element has direct text content
                let hasDirectText = false;
                for (let i = 0; i < el.childNodes.length; i++) {
                    if (el.childNodes[i].nodeType === Node.TEXT_NODE && el.childNodes[i].textContent.trim() !== "") {
                        hasDirectText = true;
                        break;
                    }
                }
                if (!hasDirectText) return;

                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return;

                const fg = style.color;
                const bg = getEffectiveBackground(el);

                const fgRgb = parseRGB(fg);
                const bgRgb = parseRGB(bg);

                const l1 = getLuminance(fgRgb[0], fgRgb[1], fgRgb[2]);
                const l2 = getLuminance(bgRgb[0], bgRgb[1], bgRgb[2]);
                const ratio = getContrastRatio(l1, l2);

                const fontSize = parseFloat(style.fontSize);
                const fontWeight = parseInt(style.fontWeight) || 400;

                const isLarge = fontSize >= 24 || (fontSize >= 18.66 && fontWeight >= 700);
                const passes = isLarge ? ratio >= 3.0 : ratio >= 4.5;

                if (!passes) {
                    let selector = el.tagName.toLowerCase();
                    if (el.id) selector += '#' + el.id;
                    else if (el.className && typeof el.className === 'string') selector += '.' + el.className.split(' ')[0];

                    issues.push({
                        selector: selector,
                        text_snippet: el.innerText.trim().substring(0, 30),
                        fg_color: fg,
                        bg_color: bg,
                        contrast_ratio: Math.round(ratio * 100) / 100,
                        passes_wcag: passes,
                        required: isLarge ? 3.0 : 4.5
                    });
                }
            });
            return issues;
        }""")

        browser.close()

        if is_file and temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass

        return {"issues": results}


if __name__ == "__main__":
    content = sys.stdin.read()
    if not content.strip():
        print(json.dumps({"error": "No input provided"}))
        sys.exit(1)

    result = check_contrast_in_page(content)
    print(json.dumps(result, indent=2))
