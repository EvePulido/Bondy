import os

# Statically allowed paths to prevent navigation to arbitrary URLs
ALLOWED_SOURCES = {
    "demo_sites/site_1_bad_alt",
    "demo_sites/site_2_focus_trap",
    "demo_sites/site_3_mixed_errors",
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
            "Path traversal detected. Recovery: Please provide a safe, direct path inside the 'demo_sites' directory without using '../' or absolute paths."
        )

    # Allow any file or directory strictly inside the 'demo_sites' folder
    demo_sites_abs = os.path.abspath(os.path.join(base_dir, "demo_sites"))
    is_allowed = resolved_path == demo_sites_abs or resolved_path.startswith(
        demo_sites_abs + os.sep
    )

    if not is_allowed:
        raise ValueError(
            f"The path '{source}' is not allowed for security reasons. Recovery: Please make sure the path is strictly inside the 'demo_sites' folder, or switch to the 'HTML' tab to paste your code directly."
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
