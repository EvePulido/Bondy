import json
import re
import sys


def check_accessible_name(html_str: str) -> list:
    """
    Scans interactive elements (a, button) to check if they contain an accessible name.
    """
    results = []

    # Find all <a> and <button> tags with their inner HTML
    elements = re.finditer(
        r"<(a|button)([^>]*)>(.*?)</\1>", html_str, re.IGNORECASE | re.DOTALL
    )

    for match in elements:
        tag_name = match.group(1).lower()
        attrs = match.group(2)
        inner_html = match.group(3)

        has_name = False

        # Check aria-label
        if re.search(r'aria-label\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE):
            has_name = True
        # Check aria-labelledby
        elif re.search(
            r'aria-labelledby\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE
        ):
            has_name = True
        else:
            # Text content (strip out inner HTML tags)
            text_content = re.sub(r"<[^>]+>", "", inner_html).strip()
            if text_content:
                has_name = True
            else:
                # Check for an img tag with a valid alt attribute inside
                alt_match = re.search(
                    r'<img[^>]+alt\s*=\s*["\']([^"\']+)["\']', inner_html, re.IGNORECASE
                )
                if alt_match and alt_match.group(1).strip():
                    has_name = True

        # Extract ID or Class to build a selector representation
        id_match = re.search(r'id\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        class_match = re.search(
            r'class\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE
        )

        selector = tag_name
        if id_match:
            selector += f"#{id_match.group(1)}"
        elif class_match:
            classes = class_match.group(1).split()
            if classes:
                selector += f".{classes[0]}"

        # Extract inner classes to help identify icon fonts
        icon_classes = []
        class_matches = re.findall(
            r'class\s*=\s*["\']([^"\']+)["\']', inner_html, re.IGNORECASE
        )
        for c_match in class_matches:
            icon_classes.extend(c_match.split())

        results.append(
            {
                "selector": selector,
                "type": tag_name,
                "has_accessible_name": has_name,
                "icon_hint": " ".join(icon_classes)
                if not has_name and icon_classes
                else None,
                "inner_html": inner_html.strip(),
            }
        )

    return results


if __name__ == "__main__":
    html_input = sys.stdin.read()
    issues = check_accessible_name(html_input)
    print(json.dumps({"issues": issues}, indent=2))
