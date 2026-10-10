"""Code-driven scan pipeline: scanners -> semantic stage -> fixes -> report.

No LLM "agent" decides the order of steps: this module does. The LLM is only
asked for what code cannot decide (see ``bondy.core.semantic``).

Exit codes (``exit_code``): 0 clean / below threshold, 1 findings at or above
``--fail-on``, 2 error (a scanner or file failed), 3 PARTIAL result (a hard
limit or the API quota stopped the scan before it finished and nothing at or
above the threshold was found, so a clean pass cannot be claimed).
"""

from __future__ import annotations

import html as html_lib
from collections.abc import Callable, Iterable
from functools import partial
from pathlib import Path

from bondy.config import Settings
from bondy.core.budget import (
    Limits,
    Pricing,
    UsageTracker,
    require_prices_for_limits,
)
from bondy.core.checks import check_wcag
from bondy.core.fixes import build_fix
from bondy.core.images import ImageLoader, extract_images, load_image
from bondy.core.models import ImageOccurrence, ImageOutcome, ScanReport, UsageSummary
from bondy.core.providers.base import LLMProvider
from bondy.core.semantic import analyze_images
from bondy.scan import (
    MAX_PAGES_SKIP,
    FileResult,
    Scanner,
    _read_text,
    scan_path,
    static_mode_note,
)
from bondy.scan import (
    exit_code as scan_exit_code,
)

EXIT_PARTIAL = 3

NO_KEY_NOTE = (
    "No API key found (set GEMINI_API_KEY or GOOGLE_API_KEY): ran deterministic "
    "scanners only, same as --no-llm. Alt-text quality and decorative-image "
    "judgement were not evaluated."
)


def project_root(target: Path | str) -> Path:
    target = Path(target)
    return (target if target.is_dir() else target.parent).resolve()


def collect_images(
    files: Iterable[FileResult], target: Path | str
) -> list[ImageOccurrence]:
    """``<img>`` occurrences of every scanned page, in document order."""
    root = project_root(target)
    out: list[ImageOccurrence] = []
    for r in files:
        if r.skipped:
            continue
        path = Path(r.path)
        try:
            html = _read_text(path)
        except OSError:
            continue
        out += extract_images(html, str(path), str(path.resolve().parent), str(root))
    return out


def _finding_for(o: ImageOutcome) -> dict:
    wcag = check_wcag("alt-text")
    where = f"line {o.line}"
    if o.recommendation == "fix":
        new = o.suggested_alt
        what = 'alt="" (decorative)' if new == "" else f'alt="{new}"'
        return {
            "scanner": "alt-text",
            "wcag": wcag,
            "severity": o.severity,
            "message": f"{where}: set {what}: {o.reason}",
            "line": o.line,
            "src": o.src,
            "classification": o.classification,
            "suggested_alt": new,
            "confidence": o.confidence,
            "origin": o.origin,
            "nodes": [{"html": o.tag[:300]}],
        }
    return {
        "scanner": "alt-text",
        "wcag": wcag,
        "severity": "warning",
        "message": f"{where}: needs manual review: {o.reason}",
        "line": o.line,
        "src": o.src,
        "classification": o.classification,
        "nodes": [{"html": o.tag[:300]}],
    }


def _drop_duplicate_image_alt(result: FileResult, handled_srcs: set[str]) -> None:
    """Removes axe/static 'missing alt' nodes the semantic stage already covers."""
    wanted = {html_lib.unescape(s) for s in handled_srcs}
    kept: list[dict] = []
    for f in result.findings:
        is_alt = f.get("rule") == "image-alt" or f.get("scanner") == "img-alt"
        if not is_alt or not f.get("nodes"):
            kept.append(f)
            continue
        nodes = [
            n
            for n in f["nodes"]
            if not any(s in html_lib.unescape(n.get("html", "")) for s in wanted)
        ]
        if not nodes:
            continue
        if len(nodes) != len(f["nodes"]):
            f["nodes"] = nodes
            if "count" in f:
                f["count"] = len(nodes)
        kept.append(f)
    result.findings = kept


def _apply_image_results(
    report: ScanReport,
    occurrences: list[ImageOccurrence],
    outcomes: list[ImageOutcome],
) -> None:
    by_file = {r.path: r for r in report.files}
    handled: dict[str, set[str]] = {}
    fix_index: dict[tuple[str, str, str], int] = {}
    counters: dict[str, int] = {}
    for occ, out in zip(occurrences, outcomes, strict=True):
        report.images.append(out)
        if out.recommendation not in ("fix", "needs_manual_review"):
            continue
        result = by_file[occ.file]
        result.findings.append(_finding_for(out))
        if occ.src:
            handled.setdefault(occ.file, set()).add(occ.src)
        if out.recommendation != "fix":
            continue
        fix_key = (occ.file, occ.tag, out.suggested_alt or "")
        if fix_key in fix_index:
            report.fixes[fix_index[fix_key]].occurrences += 1
            continue
        counters[occ.file] = counters.get(occ.file, 0) + 1
        fix_index[fix_key] = len(report.fixes)
        report.fixes.append(build_fix(counters[occ.file], occ, out))
    for path, srcs in handled.items():
        _drop_duplicate_image_alt(by_file[path], srcs)


def run_scan(
    target: Path | str,
    settings: Settings,
    *,
    scanners: dict[str, Scanner] | None = None,
    provider: LLMProvider | None = None,
    loader: ImageLoader | None = None,
    progress: Callable[[str], None] | None = None,
) -> ScanReport:
    """Runs the whole pipeline for ``target`` and returns a ``ScanReport``.

    ``provider``/``loader`` are injectable (tests use ``FakeProvider``); by
    default the Gemini provider is built from ``settings`` and images are
    loaded from the project or, for http(s), through the public-host guard.
    """
    require_prices_for_limits(settings)  # before any scanner/request
    results = scan_path(
        target,
        settings.include,
        settings.exclude,
        settings.checks,
        scanners=scanners,
        force_static=settings.static,
        max_files=settings.max_pages,
    )
    report = ScanReport(files=results, usage=UsageSummary())
    usage = report.usage
    if not results:
        report.notes.append("No HTML files found to scan.")
    static_note = static_mode_note(results)
    if static_note:
        report.notes.append(static_note)
    cut = [r for r in results if r.skipped and r.skipped.startswith(MAX_PAGES_SKIP)]
    if cut:
        usage.partial = True
        usage.partial_reasons.append(
            f"{MAX_PAGES_SKIP} ({settings.max_pages}): {len(cut)} page(s) not scanned"
        )

    if settings.no_llm:
        usage.mode = "no-llm"
    elif provider is None and not settings.api_key:
        usage.mode = "no-llm"
        report.notes.append(NO_KEY_NOTE)
    else:
        usage.mode = "llm"
        _semantic_stage(report, settings, target, provider, loader, progress)

    return report


def _semantic_stage(
    report: ScanReport,
    settings: Settings,
    target: Path | str,
    provider: LLMProvider | None,
    loader: ImageLoader | None,
    progress: Callable[[str], None] | None,
) -> None:
    usage = report.usage
    occurrences = collect_images(report.files, target)
    usage.images_found = len(occurrences)
    if not occurrences:
        return
    if provider is None:
        from bondy.core.providers.gemini import GeminiProvider

        provider = GeminiProvider.from_settings(settings)
    tracker = UsageTracker(
        Limits.from_settings(settings), Pricing.from_settings(settings)
    )
    stage = analyze_images(
        occurrences,
        provider,
        tracker,
        loader=loader or partial(load_image, allow_remote=settings.remote_images),
        batch_size=settings.batch_size,
        max_images=settings.max_images,
        tokens_per_image=settings.tokens_per_image,
        progress=progress,
    )
    _apply_image_results(report, occurrences, stage.outcomes)
    tracker.fill(usage)
    usage.images_unique = stage.unique
    usage.images_verified = stage.verified
    usage.images_by_template = stage.by_template
    usage.images_manual_review = stage.manual_review
    usage.images_skipped = stage.skipped
    if stage.partial_reasons:
        usage.partial = True
        usage.partial_reasons += stage.partial_reasons
    skipped = sum(1 for o in stage.outcomes if o.recommendation == "skipped")
    if skipped:
        report.notes.append(
            f"{skipped} image occurrence(s) were not verified (see partial reasons)."
        )


def exit_code(report: ScanReport, fail_on: str) -> int:
    """See the module docstring for the meaning of each code."""
    code = scan_exit_code(report.files, fail_on)
    if code == 0 and report.partial and fail_on != "never":
        return EXIT_PARTIAL
    return code
