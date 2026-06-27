import base64
import json
import urllib.request
from urllib.error import HTTPError, URLError


def fetch_image_as_base64(url: str) -> str:
    """
    Downloads an image from a URL and returns it as a base64 encoded string.
    Use this tool to physically 'see' the image before judging its alt text.

    Args:
        url: The URL of the image to download (e.g. https://images.unsplash.com/...)

    Returns:
        A JSON string containing the base64 encoded image and its mime type.
    """
    try:
        if not url.startswith("http"):
            return json.dumps({"error": "Only HTTP/HTTPS URLs are supported."})

        req = urllib.request.Request(url, headers={"User-Agent": "Bondy/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            image_data = response.read()
            mime_type = response.headers.get_content_type()
            if not mime_type or not mime_type.startswith("image/"):
                mime_type = "image/jpeg"

            encoded = base64.b64encode(image_data).decode("utf-8")
            return json.dumps({"mime_type": mime_type, "data": encoded})
    except HTTPError as e:
        return json.dumps({"error": f"HTTP Error {e.code}: {e.reason}"})
    except URLError as e:
        return json.dumps({"error": f"URL Error: {e.reason}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    import sys

    content = sys.stdin.read().strip()
    if content:
        print(fetch_image_as_base64(content))
