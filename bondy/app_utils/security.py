import os

# Statically allowed paths to prevent navigation to arbitrary URLs
ALLOWED_SOURCES = {
    "examples/site_1_bad_alt",
    "examples/site_2_focus_trap",
    "examples/site_3_mixed_errors",
}


def validate_input_before_audit(source: str, raw_html: str | None = None) -> None:
    """
    Security Guardrail (Pillar 4): Validates the source input before allowing
    Playwright to load any web page.
    Only allows pre-registered local demo sites in ALLOWED_SOURCES or raw HTML input.
    """
    if raw_html is not None:
        return  # Raw HTML pasted directly: allowed

    # Safely resolve the absolute real path
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    # Prevent malicious absolute paths from bypassing os.path.join if source starts with / or C:\
    clean_source = source.lstrip("/\\")
    if ":" in clean_source:
        clean_source = clean_source.split(":", 1)[1].lstrip("/\\")

    resolved_path = os.path.abspath(os.path.join(base_dir, clean_source))

    # The final path MUST be contained within the base_dir to prevent Directory Traversal
    if not resolved_path.startswith(base_dir):
        raise ValueError(
            "Path traversal detected. Recovery: Please provide a safe, direct path inside the 'examples' directory without using '../' or absolute paths."
        )

    # Allow any file or directory strictly inside the 'examples' folder
    examples_abs = os.path.abspath(os.path.join(base_dir, "examples"))
    is_allowed = resolved_path == examples_abs or resolved_path.startswith(
        examples_abs + os.sep
    )

    if not is_allowed:
        renamed = ""
        if clean_source.replace("\\", "/").split("/", 1)[0] == "demo_sites":
            renamed = " The 'demo_sites' folder was renamed to 'examples'."
        raise ValueError(
            f"The path '{source}' is not allowed for security reasons.{renamed} Recovery: Please make sure the path is strictly inside the 'examples' folder, or switch to the 'HTML' tab to paste your code directly."
        )


def validate_public_url(url: str) -> None:
    """
    SSRF guardrail: only allows http(s) URLs whose host resolves exclusively to
    public IP addresses (no loopback, private, link-local or metadata ranges).
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"URL not allowed: '{url}'. Only http(s) URLs are supported.")

    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve host '{parsed.hostname}': {e}") from e

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValueError(
                f"URL not allowed: '{parsed.hostname}' resolves to a non-public address."
            )


def get_safe_demo_path(source: str) -> str:
    """
    Returns the absolute local path to index.html if the source passes safety validation.
    """
    validate_input_before_audit(source)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    safe_path = os.path.join(base_dir, source)

    # If the path is a directory, attempt to resolve its index.html
    if os.path.isdir(safe_path):
        safe_path = os.path.join(safe_path, "index.html")

    if not os.path.exists(safe_path):
        raise FileNotFoundError(
            f"File not found: '{safe_path}'. Recovery: Please verify that you typed the path correctly and that the file actually exists in the local project."
        )
    return safe_path
