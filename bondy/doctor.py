"""`bondy doctor`: offline environment checks with the exact command to fix each.

Nothing here calls the network or the Gemini API. A live API-key validation
(one minimal request) is intentionally not part of this module yet.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from bondy.app_utils.browser import (
    INSTALL_COMMAND,
    BrowserUnavailableError,
    find_system_browsers,
    launch_with_label,
)
from bondy.config import API_KEY_ENV_VARS, ConfigError, load_settings
from bondy.resources import SKILLS_DIR

PYTHON_MIN, PYTHON_MAX_EXCL = (3, 11), (3, 14)


@dataclass
class Check:
    name: str
    status: str  # "ok" | "warn" | "fail"
    detail: str
    fix: str | None = None


def check_python(version: tuple[int, int] | None = None) -> Check:
    v = version or sys.version_info[:2]
    label = f"{v[0]}.{v[1]}"
    if PYTHON_MIN <= v < PYTHON_MAX_EXCL:
        return Check("python", "ok", f"Python {label}")
    return Check(
        "python",
        "fail",
        f"Python {label} is outside the supported range 3.11-3.13",
        "Install Python 3.11-3.13 and recreate the environment (uv python install 3.12)",
    )


def check_playwright_package() -> Check:
    try:
        from importlib.metadata import version

        return Check("playwright", "ok", f"playwright {version('playwright')}")
    except Exception:
        return Check(
            "playwright",
            "fail",
            "The 'playwright' package is not installed",
            "pip install bondy  (or: uv sync)",
        )


def check_browser() -> Check:
    """Launches the browser the scanners would use and reports which one it is."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, label = launch_with_label(p)
            browser.close()
        return Check("browser", "ok", f"Scans will use: {label}")
    except BrowserUnavailableError:
        system = find_system_browsers()
        found = (
            " Found on disk but not launchable: "
            + ", ".join(f"{k} ({v})" for k, v in system.items())
            + "."
            if system
            else ""
        )
        return Check(
            "browser",
            "warn",
            "No usable browser: `bondy scan` will run in STATIC mode (HTML parsing "
            "only; axe, contrast and focus checks are skipped)." + found,
            INSTALL_COMMAND,
        )
    except Exception as e:  # playwright itself missing or broken
        return Check(
            "browser",
            "warn",
            f"Could not start a browser ({type(e).__name__}); scans will run in "
            "STATIC mode.",
            INSTALL_COMMAND,
        )


def check_api_key(env: Mapping[str, str] | None = None) -> Check:
    env = os.environ if env is None else env
    for name in API_KEY_ENV_VARS:
        if env.get(name, "").strip():
            # Never print any part of the key.
            return Check(
                "api-key", "ok", f"{name} is set (value hidden; not validated)"
            )
    return Check(
        "api-key",
        "warn",
        "No API key found; only --no-llm scans will work",
        "Create a key at https://aistudio.google.com/apikey and set GEMINI_API_KEY "
        "(PowerShell: $env:GEMINI_API_KEY='...'; bash: export GEMINI_API_KEY=...)",
    )


def check_axe() -> Check:
    axe = SKILLS_DIR / "axe-accessibility-scanner" / "scripts" / "axe.min.js"
    if not axe.is_file():
        return Check(
            "axe-core",
            "fail",
            f"axe.min.js not found at {axe}",
            "pip install --force-reinstall bondy",
        )
    head = axe.read_text(encoding="utf-8", errors="replace")[:400]
    m = re.search(r"axe v(\d+\.\d+\.\d+)", head)
    return Check(
        "axe-core", "ok", f"axe-core {m.group(1) if m else '(unknown version)'}"
    )


def check_write_access(directory: Path | None = None) -> Check:
    directory = directory or Path.cwd()
    try:
        with tempfile.TemporaryFile(dir=directory):
            pass
        return Check("write-access", "ok", f"Can write to {directory}")
    except OSError as e:
        return Check(
            "write-access",
            "fail",
            f"Cannot write to {directory}: {e}",
            "Run bondy from a writable directory (bondy stores its cache in .bondy/)",
        )


def check_config(config_path: str | None = None) -> Check:
    try:
        s = load_settings(config_path=config_path)
    except ConfigError as e:
        return Check(
            "config", "fail", str(e), "Fix or remove the offending bondy.toml entry"
        )
    where = (
        str(s.config_path) if s.config_path else "no bondy.toml found (using defaults)"
    )
    return Check("config", "ok", where)


def run_checks(config_path: str | None = None) -> list[Check]:
    return [
        check_python(),
        check_playwright_package(),
        check_browser(),
        check_axe(),
        check_config(config_path),
        check_api_key(),
        check_write_access(),
    ]
