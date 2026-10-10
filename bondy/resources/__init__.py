"""Package data bundled with Bondy (skills, web UI, fix patterns).

Paths are resolved from the installed package location (never from the CWD),
so they work from any directory and from an installed wheel.
"""

from importlib.resources import files
from pathlib import Path

RESOURCES_DIR = Path(str(files("bondy") / "resources"))
SKILLS_DIR = RESOURCES_DIR / "skills"
WEB_DIR = RESOURCES_DIR / "web"
FIX_PATTERNS_PATH = RESOURCES_DIR / "fix_patterns.md"
AXE_SCAN_SCRIPT = SKILLS_DIR / "axe-accessibility-scanner" / "scripts" / "axe_scan.py"
