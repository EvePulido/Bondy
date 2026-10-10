"""Deterministic (no-LLM) scan: runs the bundled scanner scripts on HTML files.

This module is part of the core package: it needs only Playwright (for the
browser-based scanners) and never imports FastAPI, ADK or the Gemini client.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bondy.app_utils.security import validate_input_before_audit
from bondy.resources import SKILLS_DIR

MAX_FILE_BYTES = 2 * 1024 * 1024  # larger files are skipped with a note
SEVERITY_RANK = {"warning": 1, "critical": 2}

Scanner = Callable[[str], list[dict]]


@dataclass
class FileResult:
    path: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: str | None = None


# ----- Discovery -----
def _matches(rel: str, pattern: str) -> bool:
    if fnmatch.fnmatch(rel, pattern):
        return True
    if pattern.startswith("**/") and fnmatch.fnmatch(rel, pattern[3:]):
        return True
    if pattern.endswith("/**"):
        head = pattern[:-3]
        # "node_modules/**" also excludes nested node_modules directories
        if "/" not in head and "*" not in head and head in rel.split("/")[:-1]:
            return True
    return False


def discover(
    target: Path | str, include: Iterable[str], exclude: Iterable[str]
) -> list[Path]:
    """HTML files under ``target`` (a file or a directory), sorted, honoring globs.

    An explicit file is always returned (include/exclude only filter folders).
    Symlinked directories are not followed.
    """
    target = Path(target)
    if target.is_file():
        return [target]
    if not target.is_dir():
        raise FileNotFoundError(f"Path not found: {target}")
    include, exclude = list(include), list(exclude)
    found: list[Path] = []
    for root, dirs, files in os.walk(target, followlinks=False):
        rel_root = Path(root).relative_to(target).as_posix()
        prefix = "" if rel_root == "." else rel_root + "/"
        dirs[:] = sorted(
            d for d in dirs if not any(_matches(f"{prefix}{d}/x", p) for p in exclude)
        )
        for name in sorted(files):
            rel = f"{prefix}{name}"
            if any(_matches(rel, p) for p in include) and not any(
                _matches(rel, p) for p in exclude
            ):
                found.append(Path(root) / name)
    return found


# ----- Scanner loading -----
def _load_script(skill: str, script: str):
    path = SKILLS_DIR / skill / "scripts" / script
    spec = importlib.util.spec_from_file_location(f"bondy_scan_{path.stem}", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _finding(
    scanner: str, wcag: list[str], severity: str, message: str, **extra: Any
) -> dict[str, Any]:
    return {
        "scanner": scanner,
        "wcag": wcag,
        "severity": severity,
        "message": message,
        **extra,
    }


# ----- Individual scanners: each returns a list of normalized findings -----
def _run_axe(html: str) -> list[dict]:
    report = _load_script("axe-accessibility-scanner", "axe_scan.py").scan(html)
    out = [
        _finding(
            "axe",
            v["wcag"],
            v["severity"],
            v["help"],
            rule=v["rule_id"],
            count=v["total_nodes"],
            nodes=v["nodes"],
        )
        for v in report["violations"]
    ]
    out += [
        _finding(
            "axe-tree",
            ["4.1.2"],
            "critical",
            u["problem"],
            nodes=[{"html": u["html"]}],
        )
        for u in report["unnamed_interactive_elements"]
    ]
    return out


def _run_contrast(html: str) -> list[dict]:
    mod = _load_script("text-contrast-calculator", "contrast.py")
    return [
        _finding(
            "contrast",
            ["1.4.3"],
            "critical",
            f"Contrast {i.get('contrast_ratio')}:1 is below {i.get('required')}:1",
            selector=i.get("selector"),
            text=i.get("text_snippet"),
        )
        for i in mod.check_contrast_in_page(html)["issues"]
    ]


def _run_focus_trap(html: str) -> list[dict]:
    mod = _load_script("focus-trap-detector", "focus_trap.py")
    r = mod.detect_focus_trap(html)
    if not r.get("trap_detected"):
        return []
    return [
        _finding(
            "focus-trap",
            ["2.1.2"],
            "critical",
            "Keyboard focus is trapped in a small set of elements",
            selectors=r.get("involved_selectors", []),
        )
    ]


def _run_focus_order(html: str) -> list[dict]:
    mod = _load_script("focus-order-validator", "focus_order.py")
    return [
        _finding("focus-order", ["2.4.3"], "warning", a)
        for a in mod.evaluate_focus_order(html).get("anomalies", [])
    ]


def _run_lang(html: str) -> list[dict]:
    if "<html" not in html.lower():
        return []  # fragment without a document root: nothing to check
    r = _load_script("document-language-validator", "check_lang.py").check_lang(html)
    if r["present"] and r["valid"]:
        return []
    why = "is missing" if not r["present"] else f"is invalid ({r['value']!r})"
    return [_finding("lang", ["3.1.1"], "critical", f"<html lang> {why}")]


def _run_labels(html: str) -> list[dict]:
    mod = _load_script("form-labels-validator", "form_labels.py")
    return [
        _finding(
            "labels",
            ["1.3.1", "4.1.2"],
            "critical",
            f"Form control '{i['selector']}' has no accessible label",
            selector=i["selector"],
        )
        for i in mod.check_form_labels(html)
        if not i["has_label"]
    ]


def _run_names(html: str) -> list[dict]:
    mod = _load_script("interactive-elements-validator", "accessible_name.py")
    return [
        _finding(
            "accessible-name",
            ["2.4.4", "4.1.2"],
            "critical",
            f"<{i['type']}> '{i['selector']}' has no accessible name",
            selector=i["selector"],
        )
        for i in mod.check_accessible_name(html)
        if not i["has_accessible_name"]
    ]


SCANNERS: dict[str, Scanner] = {
    "axe": _run_axe,
    "contrast": _run_contrast,
    "focus-trap": _run_focus_trap,
    "focus-order": _run_focus_order,
    "lang": _run_lang,
    "labels": _run_labels,
    "accessible-name": _run_names,
}


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _criteria(checks: Iterable[str]) -> set[str]:
    return {c.strip().removeprefix("WCAG").strip() for c in checks if c.strip()}


def scan_html(
    html: str,
    checks: Iterable[str] = (),
    scanners: dict[str, Scanner] | None = None,
) -> tuple[list[dict], list[str]]:
    """Runs every scanner on ``html``. Returns (findings, errors).

    A failing scanner (e.g. browser missing) is reported in ``errors`` and does
    not abort the others. ``checks`` (e.g. ``["WCAG 1.1.1"]``) keeps only
    findings that map to those criteria.
    """
    findings: list[dict] = []
    errors: list[str] = []
    for name, run in (scanners or SCANNERS).items():
        try:
            findings.extend(run(html))
        except Exception as e:
            lines = str(e).strip().splitlines()
            errors.append(f"{name}: {type(e).__name__}: {lines[0] if lines else ''}")
    wanted = _criteria(checks)
    if wanted:
        findings = [f for f in findings if wanted & set(f["wcag"])]
    return findings, errors


def scan_path(
    target: Path | str,
    include: Iterable[str],
    exclude: Iterable[str],
    checks: Iterable[str] = (),
    scanners: dict[str, Scanner] | None = None,
) -> list[FileResult]:
    results: list[FileResult] = []
    for path in discover(target, include, exclude):
        result = FileResult(path=str(path))
        results.append(result)
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                result.skipped = f"larger than {MAX_FILE_BYTES // (1024 * 1024)} MB"
                continue
            html = _read_text(path)
            # AGENTS.md rule 1: validate before any Playwright navigation. The
            # content is passed as raw HTML (the page is never fetched by URL).
            validate_input_before_audit(str(path), raw_html=html)
        except (OSError, ValueError) as e:
            result.errors.append(str(e))
            continue
        result.findings, result.errors = scan_html(html, checks, scanners)
    return results


def worst_severity(results: Iterable[FileResult]) -> int:
    return max(
        (SEVERITY_RANK.get(f["severity"], 1) for r in results for f in r.findings),
        default=0,
    )


def exit_code(results: list[FileResult], fail_on: str) -> int:
    """0 clean / below threshold, 1 findings at or above ``fail_on``, 2 errors."""
    if any(r.errors for r in results):
        return 2
    threshold = {"critical": 2, "warning": 1}.get(fail_on)
    if threshold is None:
        return 0
    return 1 if worst_severity(results) >= threshold else 0
