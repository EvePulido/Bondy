import json
import re
import sys


def check_accessible_name(html_str):
    results = []

    # Encontrar todos los a y button
    elements = re.finditer(
        r"<(a|button)([^>]*)>(.*?)</\1>", html_str, re.IGNORECASE | re.DOTALL
    )

    for match in elements:
        tag_name = match.group(1).lower()
        attrs = match.group(2)
        inner_html = match.group(3)

        has_name = False

        # Chequear aria-label
        if re.search(r'aria-label\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE):
            has_name = True
        # Chequear aria-labelledby
        elif re.search(
            r'aria-labelledby\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE
        ):
            has_name = True
        else:
            # Texto interno (remover tags HTML)
            text_content = re.sub(r"<[^>]+>", "", inner_html).strip()
            if text_content:
                has_name = True
            else:
                # Chequear imagen con alt
                alt_match = re.search(
                    r'<img[^>]+alt\s*=\s*["\']([^"\']+)["\']', inner_html, re.IGNORECASE
                )
                if alt_match and alt_match.group(1).strip():
                    has_name = True

        # Extraer ID o clase para el selector
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

        results.append(
            {"selector": selector, "tipo": tag_name, "tiene_nombre_accesible": has_name}
        )

    return results


if __name__ == "__main__":
    html_input = sys.stdin.read()
    issues = check_accessible_name(html_input)
    print(json.dumps({"issues": issues}, indent=2))
