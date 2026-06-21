import json
import re
import sys


def check_lang(html_str: str) -> dict:
    """
    Checks if the HTML document's root tag has a valid lang attribute.
    Returns a dictionary indicating presence, value, and validity according to BCP 47.
    """
    # Find <html ...> tag ignoring case and whitespace
    match = re.search(r"<html([^>]+)>", html_str, re.IGNORECASE)
    if not match:
        # The tag might be a bare <html> without attributes
        if re.search(r"<html>", html_str, re.IGNORECASE):
            return {"present": False, "value": None, "valid": False}
        # If no html tag is found, return a safe fallback state
        return {"present": False, "value": None, "valid": False}

    attrs_str = match.group(1)

    # Search for lang="..." or lang='...'
    lang_match = re.search(r'lang\s*=\s*["\']([^"\']*)["\']', attrs_str, re.IGNORECASE)
    if not lang_match:
        return {"present": False, "value": None, "valid": False}

    lang_val = lang_match.group(1).strip()

    if not lang_val:
        return {"present": True, "value": "", "valid": False}

    # Validate basic BCP 47 format (e.g., 'es', 'en-US', 'es-419')
    # Two or three lowercase letters, optionally followed by a hyphen and subtags
    is_valid = bool(re.match(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]+)*$", lang_val))

    return {"present": True, "value": lang_val, "valid": is_valid}


if __name__ == "__main__":
    # Read the HTML content from standard input (stdin)
    html_input = sys.stdin.read()
    if not html_input.strip():
        print(json.dumps({"error": "No input provided"}))
        sys.exit(1)

    result = check_lang(html_input)
    print(json.dumps({"issue": result}, indent=2))
