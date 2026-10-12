import base64
import json

MAX_IMAGE_BYTES = 10 * 1024 * 1024


def fetch_image_as_base64(url: str) -> str:
    """
    Downloads an image from a URL and returns it as a base64 encoded string.
    Use this tool to physically 'see' the image before judging its alt text.

    Only public http(s) hosts are allowed: the download goes through the
    SSRF-safe fetcher (``bondy.core.netguard``), which pins the validated IP,
    re-validates every redirect and caps the size.

    Args:
        url: The URL of the image to download (e.g. https://images.unsplash.com/...)

    Returns:
        A JSON string containing the base64 encoded image and its mime type.
    """
    try:
        from bondy.core.netguard import fetch_public_bytes
    except ImportError:  # fail closed: never fall back to an unguarded urlopen
        return json.dumps({"error": "SSRF guard unavailable (bondy not installed)."})

    try:
        res = fetch_public_bytes(url, MAX_IMAGE_BYTES, 10)
    except Exception as e:  # NetGuardError (blocked), FetchError, OSError
        return json.dumps({"error": str(e)})
    mime_type = res.content_type
    if not mime_type.startswith("image/"):
        mime_type = "image/jpeg"
    encoded = base64.b64encode(res.data).decode("utf-8")
    return json.dumps({"mime_type": mime_type, "data": encoded})


if __name__ == "__main__":
    import sys

    content = sys.stdin.read().strip()
    if content:
        print(fetch_image_as_base64(content))
