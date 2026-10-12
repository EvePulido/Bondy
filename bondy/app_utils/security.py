import os


def _is_within(path: str, root: str) -> bool:
    """True if ``path`` is ``root`` or inside it (separator-aware: '/a/Bondy-evil'
    is NOT inside '/a/Bondy'; case-insensitive on Windows)."""
    path, root = os.path.normcase(path), os.path.normcase(root)
    return path == root or path.startswith(root.rstrip("\\/") + os.sep)


def validate_input_before_audit(source: str, raw_html: str | None = None) -> None:
    """
    Security Guardrail (Pillar 4): Validates the source input before allowing
    Playwright to load any web page.
    Only allows paths inside the 'examples' folder or raw HTML input.
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
    if not _is_within(resolved_path, base_dir):
        raise ValueError(
            "Path traversal detected. Recovery: Please provide a safe, direct path inside the 'examples' directory without using '../' or absolute paths."
        )

    # Allow any file or directory strictly inside the 'examples' folder
    examples_abs = os.path.abspath(os.path.join(base_dir, "examples"))
    is_allowed = _is_within(resolved_path, examples_abs)

    if not is_allowed:
        renamed = ""
        if clean_source.replace("\\", "/").split("/", 1)[0] == "demo_sites":
            renamed = " The 'demo_sites' folder was renamed to 'examples'."
        raise ValueError(
            f"The path '{source}' is not allowed for security reasons.{renamed} Recovery: Please make sure the path is strictly inside the 'examples' folder, or switch to the 'HTML' tab to paste your code directly."
        )


def validate_public_url(url: str) -> None:
    """
    SSRF pre-check: only http(s) URLs without credentials whose host resolves
    exclusively to public IP addresses. This alone does NOT stop DNS rebinding
    (the connection resolves again); to download use
    ``bondy.core.netguard.fetch_public_bytes``, which pins the validated IP.
    """
    from bondy.core.netguard import validate_public_url as _validate

    _validate(url)


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
