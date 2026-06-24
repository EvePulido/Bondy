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

    # Clean backslashes for Windows and Linux cross-compatibility
    clean_source = source.replace("\\", "/")

    is_allowed = False
    for allowed in ALLOWED_SOURCES:
        if allowed in clean_source:
            is_allowed = True
            break

    if not is_allowed:
        raise ValueError(
            f"Access denied (Security Module). Source not allowed: {source}. "
            f"Please use an authorized demo site or input raw HTML content directly."
        )


def get_safe_demo_path(source: str) -> str:
    """
    Returns the absolute local path to index.html if the source passes safety validation.
    """
    validate_input_before_audit(source)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    # Previene la duplicación si el agente ya incluyó index.html en la ruta
    clean_src = source.replace("\\", "/")
    if clean_src.endswith("index.html"):
        safe_path = os.path.join(base_dir, source)
    else:
        safe_path = os.path.join(base_dir, source, "index.html")

    if not os.path.exists(safe_path):
        raise FileNotFoundError(f"The demo site file does not exist at: {safe_path}")
    return safe_path
