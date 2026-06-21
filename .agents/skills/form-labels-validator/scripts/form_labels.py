import json
import re
import sys


def check_form_labels(html_str):
    results = []

    # Encontrar todos los input, select, textarea
    elements = re.finditer(r"<(input|select|textarea)([^>]*)>", html_str, re.IGNORECASE)

    for match in elements:
        tag_name = match.group(1).lower()
        attrs = match.group(2)

        # Ignorar tipos que no requieren label
        type_match = re.search(r'type\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        input_type = type_match.group(1).lower() if type_match else "text"

        if tag_name == "input" and input_type in [
            "hidden",
            "submit",
            "button",
            "reset",
            "image",
        ]:
            continue

        has_label = False
        method = None

        # aria-label
        if re.search(r'aria-label\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE):
            has_label = True
            method = "aria-label"
        # aria-labelledby
        elif re.search(
            r'aria-labelledby\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE
        ):
            has_label = True
            method = "aria-labelledby"

        id_match = re.search(r'id\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        input_id = id_match.group(1) if id_match else None

        # <label for="...">
        if not has_label and input_id:
            label_for_pattern = (
                f"<label[^>]*for\\s*=\\s*[\"']{re.escape(input_id)}[\"'][^>]*>"
            )
            if re.search(label_for_pattern, html_str, re.IGNORECASE):
                has_label = True
                method = "label[for]"

        # Implicit <label> wrapping - comprobación básica para el mock
        if not has_label:
            # Buscar <label>...</label> que contenga a este elemento
            # Esta es una aproximación usando re, funciona para casos simples de demo
            wrapper_match = re.search(
                r"<label[^>]*>.*?<(?:input|select|textarea)[^>]*>.*?</label>",
                html_str,
                re.IGNORECASE | re.DOTALL,
            )
            if wrapper_match:
                has_label = True
                method = "implicit-label"

        selector = tag_name
        if input_id:
            selector += f"#{input_id}"

        results.append(
            {
                "selector": selector,
                "tipo_input": input_type if tag_name == "input" else tag_name,
                "tiene_label": has_label,
                "metodo_detectado": method,
            }
        )

    return results


if __name__ == "__main__":
    html_input = sys.stdin.read()
    issues = check_form_labels(html_input)
    print(json.dumps({"issues": issues}, indent=2))
