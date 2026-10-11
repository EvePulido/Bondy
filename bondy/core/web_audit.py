"""Web UI / ``POST /api/audit`` on top of the deterministic pipeline.

No FastAPI and no ADK here: ``run_web_audit`` is a plain synchronous function
(the server runs it in a worker thread) and ``scan_to_payload`` is a pure
adapter from a ``ScanReport`` to the response shape ``web/app.js`` consumes:

``{status, data: [{finding_id, wcag, severity, title, before, after,
explanation}], stats: {passes, violations, needs_review} | None, source_type,
file_path, notes, mode, partial}``

``notes``, ``mode`` and ``partial`` are additions the UI may show; the other
keys keep the contract the UI always had.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bondy.app_utils.security import get_safe_demo_path
from bondy.config import ConfigError, load_settings
from bondy.core.checks import resolve_criteria
from bondy.core.models import ScanReport
from bondy.core.pipeline import project_root, run_scan
from bondy.core.providers.base import LLMProvider, ProviderError
from bondy.core.report import Item, build_report
from bondy.scan import Scanner

# Text the semantic stage uses when the daily API quota stops a scan.
QUOTA_DAILY_MARKER = "daily API quota exhausted"
QUOTA_MESSAGE = (
    "Daily Gemini quota exhausted for this API key/model. Recovery: wait for the "
    "quota reset, use a billing-enabled key or Vertex AI, or run without an API "
    "key (deterministic checks only)."
)
QUOTA_PARTIAL_NOTE = (
    "Partial result: the daily Gemini quota was exhausted, so only the "
    "deterministic findings are shown (no AI image verification). Run the audit "
    "again after the quota resets to complete it."
)
KEY_REJECTED_MESSAGE = (
    "The API key was rejected by the API (invalid, expired or without permission). "
    "Recovery: check GEMINI_API_KEY / GOOGLE_API_KEY "
    "(https://aistudio.google.com/apikey) or unset it to run the deterministic "
    "checks only."
)
BEST_PRACTICE = "Best practice"
_TITLE_MAX = 140


class WebAuditError(Exception):
    """An audit that cannot answer with findings. ``status`` is the HTTP code."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _lf(text: str | None) -> str:
    """CRLF -> LF so snippets match what ``/api/apply-fix`` reads from disk."""
    return (text or "").replace("\r\n", "\n")


def _item_entry(item: Item, n: int) -> dict[str, Any]:
    where = f" (line {item.line})" if item.line else ""
    return {
        "finding_id": f"{item.rule}-{n:03d}",
        "wcag": ", ".join(item.wcag) if item.wcag else BEST_PRACTICE,
        "severity": item.severity,
        "title": _lf(item.message)[:_TITLE_MAX] or item.rule,
        "before": _lf(item.snippet or item.selector or "(whole page)"),
        "after": _lf(item.fix or ""),
        "explanation": _lf(item.message) + where,
    }


def scan_to_payload(
    scan: ScanReport,
    root: Path,
    *,
    source_type: str,
    file_path: str | None,
) -> tuple[dict[str, Any], set[str]]:
    """Adapts a pipeline report to the UI contract.

    Returns ``(payload, patch_ids)``. ``patch_ids`` are the ``finding_id`` of
    the entries whose ``after`` is a real replacement for ``before`` (image
    fixes). Only those may be offered as "Apply to File": for every other entry
    ``after`` is advice text, never code to write.
    """
    model = build_report(scan, root)
    data: list[dict[str, Any]] = []
    patch_ids: set[str] = set()

    for fx in model.fixes:
        entry = {
            "finding_id": fx["finding_id"],
            "wcag": fx["wcag"],
            "severity": fx["severity"],
            "title": _lf(fx["title"]),
            "before": _lf(fx["before"]),
            "after": _lf(fx["after"]),
            "explanation": _lf(fx["explanation"]),
        }
        data.append(entry)
        patch_ids.add(entry["finding_id"])

    n = 0
    for item in model.new_items:
        # An alt-text item with a suggestion is already shown as an image fix.
        if item.scanner == "alt-text" and "suggested_alt" in item.details:
            continue
        n += 1
        data.append(_item_entry(item, n))

    stat_list = [r.axe_stats for r in scan.files if r.axe_stats]
    stats = (
        {
            key: sum(s.get(key, 0) for s in stat_list)
            for key in ("passes", "violations", "needs_review")
        }
        if stat_list
        else None
    )
    notes = list(model.notes)
    for f in model.files:
        if f.skipped:
            notes.append(f"{f.path}: skipped ({f.skipped}).")
        notes.extend(f"{f.path}: {e}" for e in f.errors)
    if scan.usage.partial:
        notes.extend(scan.usage.partial_reasons)

    payload = {
        "status": "success",
        "data": data,
        "stats": stats,
        "source_type": source_type,
        "file_path": file_path,
        "notes": notes,
        "mode": scan.usage.mode,
        "partial": scan.usage.partial,
    }
    return payload, patch_ids


def _cache_dir(repo_root: Path) -> str:
    # One shared, git-ignored verdict cache: never write into a scanned folder.
    return str(repo_root / ".bondy" / "cache")


def run_web_audit(
    *,
    source: str,
    raw_html: str | None,
    enabled_checks: list[str] | None,
    repo_root: Path,
    provider: LLMProvider | None = None,
    no_llm: bool | None = None,
    env: Mapping[str, str] | None = None,
    scanners: dict[str, Scanner] | None = None,
) -> tuple[dict[str, Any], set[str]]:
    """Scans a pasted HTML string or a demo file and returns ``scan_to_payload``.

    The caller has already validated ``source``/``raw_html`` with
    ``validate_input_before_audit``. Raises ``WebAuditError`` (429 daily quota with nothing to show,
    403 invalid selection, 500 anything else). Without an API key (or with
    ``no_llm``) only the deterministic checks run and ``notes`` says so.
    """
    try:
        criteria = resolve_criteria(enabled_checks or [])
    except ValueError as e:
        raise WebAuditError(403, str(e)) from e
    if enabled_checks and any(t.strip() for t in enabled_checks) and not criteria:
        raise WebAuditError(403, "No valid check selected.")

    flags: dict[str, Any] = {
        "checks": [f"WCAG {c}" for c in criteria] or None,
        "cache_dir": _cache_dir(repo_root),
    }
    if no_llm is not None:
        flags["no_llm"] = no_llm

    try:
        settings = load_settings(flags=flags, env=env, start_dir=repo_root)
        if raw_html is not None:
            # The page is only ever read from this private folder, which is
            # always removed (also when the scan fails).
            with tempfile.TemporaryDirectory(
                prefix="bondy-web-", ignore_cleanup_errors=True
            ) as tmp:
                page = Path(tmp) / "page.html"
                page.write_bytes(raw_html.encode("utf-8"))
                scan = run_scan(page, settings, scanners=scanners, provider=provider)
                return _finish(scan, project_root(page), "raw_html", None)
        path = Path(get_safe_demo_path(source))
        scan = run_scan(path, settings, scanners=scanners, provider=provider)
        return _finish(scan, project_root(path), "local_file", source)
    except WebAuditError:
        raise
    except ProviderError as e:
        if e.kind == "invalid_key":
            raise WebAuditError(500, KEY_REJECTED_MESSAGE) from e
        if e.kind == "quota_daily":
            raise WebAuditError(429, QUOTA_MESSAGE) from e
        raise WebAuditError(500, str(e)) from e
    except (ConfigError, OSError, ValueError) as e:
        raise WebAuditError(500, str(e)) from e


def _finish(
    scan: ScanReport, root: Path, source_type: str, file_path: str | None
) -> tuple[dict[str, Any], set[str]]:
    if not scan.files or any(r.html is None for r in scan.files):
        reasons = [
            r.skipped or "; ".join(r.errors) or "could not be read" for r in scan.files
        ] or ["no HTML to scan"]
        raise WebAuditError(500, "The page could not be scanned: " + "; ".join(reasons))
    payload, patch_ids = scan_to_payload(
        scan, root, source_type=source_type, file_path=file_path
    )
    if any(QUOTA_DAILY_MARKER in r for r in scan.usage.partial_reasons):
        if not payload["data"]:
            # nothing to show: the quota error is the whole answer
            raise WebAuditError(429, QUOTA_MESSAGE)
        # The deterministic scanners did produce findings: return them (200)
        # as a partial result instead of throwing the work away.
        payload["partial"] = True
        payload["notes"].append(QUOTA_PARTIAL_NOTE)
    return payload, patch_ids
