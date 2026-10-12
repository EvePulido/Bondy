"""Deterministic (no-LLM) scan: runs the bundled scanner scripts on HTML files.

This module is part of the core package: it needs only Playwright (for the
browser-based scanners) and never imports FastAPI, ADK or the Gemini client.
"""

from __future__ import annotations

import fnmatch
import hashlib
import importlib.util
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from bondy.app_utils.browser import (
    INSTALL_COMMAND,
    BrowserUnavailableError,
    active_session,
    page_hung,
    page_watchdog,
)
from bondy.app_utils.security import validate_input_before_audit
from bondy.core.checks import check_wcag
from bondy.resources import SKILLS_DIR

MAX_FILE_BYTES = 2 * 1024 * 1024  # larger files are skipped with a note
SEVERITY_RANK = {"warning": 1, "critical": 2}
MAX_PAGES_SKIP = "--max-pages limit reached"
INTERRUPTED_SKIP = "interrupted by the user (Ctrl+C)"
SCAN_TIMEOUT_SKIP = "--scan-timeout reached"
# a page whose browser work exceeded --timeout (hung JS loop): the browser was
# killed; the reason is followed by " (<n> s)"
PAGE_TIMEOUT_SKIP = "page exceeded --timeout (hung page, browser killed)"

Scanner = Callable[[str], list[dict]]


@dataclass
class FileResult:
    path: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: str | None = None
    # checks that could not run (name -> reason), e.g. no browser: not an error
    omitted: dict[str, str] = field(default_factory=dict)
    # browser-free replacements that ran instead of an omitted check
    fallbacks: list[str] = field(default_factory=list)
    # content read ONCE at load time: what was scanned and its hash (B9)
    html: str | None = field(default=None, repr=False)
    sha256: str | None = None
    # previous result reused because the page (and its images) did not change
    reused: bool = False
    # axe rule counts {passes, violations, needs_review} when axe ran (else None)
    axe_stats: dict[str, int] | None = None


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
    target: Path | str | Sequence[Path | str],
    include: Iterable[str],
    exclude: Iterable[str],
) -> list[Path]:
    """HTML files under ``target`` (a file or a directory), sorted, honoring globs.

    ``target`` may also be a sequence of files/folders: results keep the order
    of the arguments and a file reachable twice (a folder plus a file inside
    it, or the same path twice) is returned once.

    An explicit file is always returned (include/exclude only filter folders).
    Symlinked directories are not followed.
    """
    if isinstance(target, (list, tuple)):
        include, exclude = list(include), list(exclude)
        seen: set[str] = set()
        merged: list[Path] = []
        for one in target:
            for p in discover(one, include, exclude):
                key = os.path.normcase(str(p.resolve()))
                if key not in seen:
                    seen.add(key)
                    merged.append(p)
        return merged
    target = Path(cast("Path | str", target))  # not a list/tuple here
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
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load scanner script: {path}")
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


class _AxeFindings(list):
    """Findings list that also carries axe's real rule counts (``stats``)."""

    stats: dict[str, int] | None = None


# ----- Individual scanners: each returns a list of normalized findings -----
def _run_axe(html: str) -> list[dict]:
    report = _load_script("axe-accessibility-scanner", "axe_scan.py").scan(html)
    out = _AxeFindings(
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
    )
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
    summary = report["summary"]
    out.stats = {
        "passes": summary["passes"],
        "violations": summary["violations"],
        "needs_review": summary["needs_review"],
    }
    return out


def _run_contrast(html: str) -> list[dict]:
    mod = _load_script("text-contrast-calculator", "contrast.py")
    return [
        _finding(
            "contrast",
            check_wcag("contrast"),
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
            check_wcag("focus-trap"),
            "critical",
            "Keyboard focus is trapped in a small set of elements",
            selectors=r.get("involved_selectors", []),
        )
    ]


def _run_focus_order(html: str) -> list[dict]:
    mod = _load_script("focus-order-validator", "focus_order.py")
    result = mod.evaluate_focus_order(html)
    invisible = result.get("invisible")
    if invisible is not None:
        # one finding per element, located by its own HTML (not "whole page")
        return [
            _finding(
                "focus-order",
                check_wcag("focus-order"),
                "warning",
                f"Element {i['selector']} receives focus but is not visible.",
                nodes=[{"html": i["html"]}],
            )
            for i in invisible
        ]
    return [
        _finding("focus-order", check_wcag("focus-order"), "warning", a)
        for a in result.get("anomalies", [])
    ]


def _run_lang(html: str) -> list[dict]:
    if "<html" not in html.lower():
        return []  # fragment without a document root: nothing to check
    r = _load_script("document-language-validator", "check_lang.py").check_lang(html)
    if r["present"] and r["valid"]:
        return []
    why = "is missing" if not r["present"] else f"is invalid ({r['value']!r})"
    return [_finding("lang", check_wcag("lang"), "critical", f"<html lang> {why}")]


def _html_node(issue: dict[str, Any]) -> dict[str, Any]:
    """``nodes`` with the element's own HTML, when the script reported it.

    The selector stays on the node: the report takes selector and snippet from
    the node, and the fingerprint (selector first) must not change.
    """
    if not issue.get("html"):
        return {}
    return {"nodes": [{"selector": issue["selector"], "html": issue["html"]}]}


def _run_labels(html: str) -> list[dict]:
    mod = _load_script("form-labels-validator", "form_labels.py")
    return [
        _finding(
            "labels",
            check_wcag("labels"),
            "critical",
            f"Form control '{i['selector']}' has no accessible label",
            selector=i["selector"],
            **_html_node(i),
        )
        for i in mod.check_form_labels(html)
        if not i["has_label"]
    ]


def _run_names(html: str) -> list[dict]:
    mod = _load_script("interactive-elements-validator", "accessible_name.py")
    return [
        _finding(
            "accessible-name",
            check_wcag("accessible-name"),
            "critical",
            f"<{i['type']}> '{i['selector']}' has no accessible name",
            selector=i["selector"],
            **_html_node(i),
        )
        for i in mod.check_accessible_name(html)
        if not i["has_accessible_name"]
    ]


_IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_ALT_ATTR = re.compile(r"(?<![\w-])alt\s*=", re.IGNORECASE)
_PRESENTATION = re.compile(r"""role\s*=\s*["']?(presentation|none)\b""", re.IGNORECASE)


def _run_img_alt(html: str) -> list[dict]:
    """Static stand-in for axe's ``image-alt``: <img> with no alt attribute."""
    out = []
    for m in _IMG_TAG.finditer(html):
        tag = m.group(0)
        if _ALT_ATTR.search(tag) or _PRESENTATION.search(tag):
            continue
        out.append(
            _finding(
                "img-alt",
                check_wcag("img-alt"),
                "critical",
                "<img> has no alt attribute",
                nodes=[{"html": tag[:300]}],
            )
        )
    return out


SCANNERS: dict[str, Scanner] = {
    "axe": _run_axe,
    "contrast": _run_contrast,
    "focus-trap": _run_focus_trap,
    "focus-order": _run_focus_order,
    "lang": _run_lang,
    "labels": _run_labels,
    "accessible-name": _run_names,
}


# Scanners that need a rendered page (they fail with BrowserUnavailableError when
# no browser exists) and the browser-free check that partly replaces each one.
BROWSER_SCANNERS = {"axe", "contrast", "focus-trap", "focus-order"}
STATIC_FALLBACKS: dict[str, tuple[str, Scanner]] = {"axe": ("img-alt", _run_img_alt)}
STATIC_FORCED = "static mode forced"
STATIC_FORCED_REASON = "skipped: static mode forced (--static)"


def decode_html(raw: bytes) -> str:
    """UTF-8 (BOM tolerated) or, failing that, Latin-1. CRLF is preserved."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _read_text(path: Path) -> str:
    return decode_html(path.read_bytes())


def _is_bondy_report(html: str) -> bool:
    """True for the HTML report Bondy itself writes (marked in its <head>)."""
    from bondy.core.checks import REPORT_GENERATOR

    head = html[:4096].lower()
    return f'name="generator" content="{REPORT_GENERATOR}"' in head


def load_page(path: Path) -> FileResult:
    """Reads and validates one page (no scanning). Content is read exactly once."""
    result = FileResult(path=str(path))
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            result.skipped = f"larger than {MAX_FILE_BYTES // (1024 * 1024)} MB"
            return result
        raw = path.read_bytes()
        html = decode_html(raw)
        # AGENTS.md rule 1: validate before any Playwright navigation. The
        # content is passed as raw HTML (the page is never fetched by URL).
        validate_input_before_audit(str(path), raw_html=html)
    except (OSError, ValueError) as e:
        result.errors.append(str(e))
        return result
    if _is_bondy_report(html):
        result.skipped = "Bondy report (not a page to scan)"
        return result
    result.html = html
    result.sha256 = hashlib.sha256(raw).hexdigest()
    return result


def _criteria(checks: Iterable[str]) -> set[str]:
    return {c.strip().removeprefix("WCAG").strip() for c in checks if c.strip()}


def run_scanners(
    html: str,
    checks: Iterable[str] = (),
    scanners: Mapping[str, Scanner] | None = None,
    stats: dict[str, int] | None = None,
) -> tuple[list[dict], list[str], dict[str, str]]:
    """Runs every scanner on ``html``. Returns (findings, errors, unavailable).

    ``stats``, when given, is filled with axe's rule counts if axe ran.

    A failing scanner is reported in ``errors`` and does not abort the others.
    A scanner that cannot start because no browser exists goes to
    ``unavailable`` (name -> reason) instead, and its static fallback (if any)
    runs in its place. ``checks`` (e.g. ``["WCAG 1.1.1"]``) keeps only findings
    that map to those criteria.

    When the hard page watchdog killed the browser (``page_hung()``), the
    remaining browser scanners of the page are skipped and no per-scanner error
    is recorded (the caller marks the whole page).
    """
    findings: list[dict] = []
    errors: list[str] = []
    unavailable: dict[str, str] = {}
    hung = False
    for name, run in (scanners or SCANNERS).items():
        if hung and name in BROWSER_SCANNERS:
            continue
        try:
            found = run(html)
            findings.extend(found)
            found_stats = getattr(found, "stats", None)
            if stats is not None and found_stats:
                stats.update(found_stats)
        except BrowserUnavailableError as e:
            unavailable[name] = str(e)
        except Exception as e:
            if page_hung():
                hung = True
                continue
            lines = str(e).strip().splitlines()
            errors.append(f"{name}: {type(e).__name__}: {lines[0] if lines else ''}")
    for name in unavailable:
        fallback = STATIC_FALLBACKS.get(name)
        if fallback:
            try:
                findings.extend(fallback[1](html))
            except Exception as e:
                errors.append(f"{fallback[0]}: {type(e).__name__}: {e}")
    wanted = _criteria(checks)
    if wanted:
        findings = [f for f in findings if wanted & set(f["wcag"])]
    return findings, errors, unavailable


def scan_html(
    html: str,
    checks: Iterable[str] = (),
    scanners: Mapping[str, Scanner] | None = None,
) -> tuple[list[dict], list[str]]:
    """Like ``run_scanners`` but an unavailable browser is reported as an error."""
    findings, errors, unavailable = run_scanners(html, checks, scanners)
    errors += [f"{name}: BrowserUnavailableError" for name in unavailable]
    return findings, errors


def scan_loaded(
    results: list[FileResult],
    checks: Iterable[str] = (),
    scanners: Mapping[str, Scanner] | None = None,
    force_static: bool = False,
    deadline: float | None = None,
    on_page: Callable[[int, int, FileResult], None] | None = None,
) -> None:
    """Runs the scanners on pages already loaded with ``load_page`` (in place).

    ``on_page(index, total, result)`` is called before each page is scanned
    (live progress; it must not raise).

    ``deadline`` is a ``time.monotonic()`` instant: pages not started by then
    are marked skipped (``SCAN_TIMEOUT_SKIP``). Ctrl+C marks the page in
    progress and the rest as skipped (``INTERRUPTED_SKIP``) and returns.

    Inside a ``browser_session`` each page also has a HARD budget (the
    session's ``page_timeout``, capped by the time left until ``deadline``):
    ``page.evaluate`` has no timeout, so a watchdog kills the browser of a page
    stuck in a JS loop. That page is marked skipped (``PAGE_TIMEOUT_SKIP``, or
    ``SCAN_TIMEOUT_SKIP`` when the whole-scan deadline was the limit) and the
    scan goes on with the next page in a fresh browser.
    """
    active = dict(scanners or SCANNERS)
    # Reason the browser scanners were dropped; set on the first launch failure
    # so later files do not retry (and re-fail) the launch for every scanner.
    browser_down: str | None = STATIC_FORCED if force_static else None
    todo = [r for r in results if r.html is not None and not r.skipped]
    for i, result in enumerate(todo):
        if deadline is not None and time.monotonic() > deadline:
            for r in todo[i:]:
                r.skipped = SCAN_TIMEOUT_SKIP
            return
        if on_page is not None:
            on_page(i + 1, len(todo), result)
        to_run = active
        if browser_down is not None:
            to_run = {n: r for n, r in active.items() if n not in BROWSER_SCANNERS}
            for n in active:
                if n in BROWSER_SCANNERS and n in STATIC_FALLBACKS:
                    fb_name, fb = STATIC_FALLBACKS[n]
                    to_run[fb_name] = fb
        stats: dict[str, int] = {}
        session = active_session()
        if session is not None and any(n in BROWSER_SCANNERS for n in to_run):
            session.prepare()  # (re)launching is not page time
        limit = session.page_timeout if session else None
        scan_bound = False
        if deadline is not None:
            left = max(deadline - time.monotonic(), 0.001)
            if not limit or left < limit:
                limit, scan_bound = left, True
        try:
            with page_watchdog(limit) as dog:
                result.findings, result.errors, unavailable = run_scanners(
                    result.html or "", checks, to_run, stats
                )
            result.axe_stats = stats or None
        except KeyboardInterrupt:
            for r in todo[i:]:
                r.findings, r.errors, r.skipped = [], [], INTERRUPTED_SKIP
            return
        if dog is not None and dog.fired:
            # killed mid-page: nothing it produced is trustworthy or complete
            result.findings, result.errors, result.axe_stats = [], [], None
            result.skipped = (
                SCAN_TIMEOUT_SKIP
                if scan_bound
                else f"{PAGE_TIMEOUT_SKIP} ({dog.seconds:g} s)"
            )
            continue
        if browser_down is None and unavailable:
            browser_down = next(iter(unavailable.values()))
        if browser_down is not None:
            dropped = [n for n in active if n in BROWSER_SCANNERS]
            reason = (
                STATIC_FORCED_REASON
                if browser_down == STATIC_FORCED
                else "needs a browser (none available)"
            )
            result.omitted = dict.fromkeys(dropped, reason)
            result.fallbacks = [
                STATIC_FALLBACKS[n][0] for n in dropped if n in STATIC_FALLBACKS
            ]


def scan_path(
    target: Path | str,
    include: Iterable[str],
    exclude: Iterable[str],
    checks: Iterable[str] = (),
    scanners: Mapping[str, Scanner] | None = None,
    force_static: bool = False,
    max_files: int | None = None,
    deadline: float | None = None,
) -> list[FileResult]:
    """Scans ``target``. Files beyond ``max_files`` are listed as skipped."""
    results: list[FileResult] = []
    for index, path in enumerate(discover(target, include, exclude)):
        if max_files is not None and index >= max_files:
            results.append(
                FileResult(path=str(path), skipped=f"{MAX_PAGES_SKIP} ({max_files})")
            )
        else:
            results.append(load_page(path))
    scan_loaded(results, checks, scanners, force_static, deadline)
    return results


def static_mode_note(results: Iterable[FileResult]) -> str | None:
    """Human-readable explanation when browser scanners were skipped."""
    omitted: dict[str, str] = {}
    fallbacks: list[str] = []
    for r in results:
        omitted.update(r.omitted)
        fallbacks += [f for f in r.fallbacks if f not in fallbacks]
    if not omitted:
        return None
    ran = [n for n in SCANNERS if n not in BROWSER_SCANNERS] + fallbacks
    forced = all(v == STATIC_FORCED_REASON for v in omitted.values())
    why = (
        "it was requested with --static, so"
        if forced
        else "no usable browser was found, so"
    )
    return (
        f"STATIC MODE: {why} checks that need a rendered "
        f"page were skipped: {', '.join(omitted)} (contrast, keyboard focus and axe "
        "rules). Only HTML-parsing checks ran: "
        f"{', '.join(ran)}; they are less precise than the full scan. "
        + ("" if forced else f"Install a browser with: {INSTALL_COMMAND}")
    )


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
