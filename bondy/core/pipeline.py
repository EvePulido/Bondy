"""Code-driven scan pipeline: scanners -> semantic stage -> fixes -> report.

No LLM "agent" decides the order of steps: this module does. The LLM is only
asked for what code cannot decide (see ``bondy.core.semantic``).

Exit codes (``exit_code``): 0 clean / below threshold, 1 findings at or above
``--fail-on``, 2 error (a scanner or file failed), 3 PARTIAL result (a hard
limit or the API quota stopped the scan before it finished and nothing at or
above the threshold was found, so a clean pass cannot be claimed).
"""

from __future__ import annotations

import hashlib
import html as html_lib
import os
import re
import subprocess
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict
from functools import partial
from pathlib import Path

from bondy.app_utils.browser import browser_session
from bondy.config import ConfigError, Settings
from bondy.core.budget import (
    Limits,
    Pricing,
    UsageTracker,
    require_prices_for_limits,
)
from bondy.core.checks import CHECKS, check_wcag
from bondy.core.fixes import build_fix
from bondy.core.images import (
    ImageLoader,
    asset_fingerprint,
    extract_images,
    is_remote_src,
    load_image,
)
from bondy.core.models import (
    ImageFix,
    ImageOccurrence,
    ImageOutcome,
    ScanReport,
    UsageSummary,
)
from bondy.core.providers.base import LLMProvider
from bondy.core.redact import contains_secret
from bondy.core.semantic import PROMPT_FINGERPRINT, analyze_images
from bondy.core.store import (
    Store,
    bondy_version,
    resolve_cache_dir,
    sha256_hex,
)
from bondy.core.suppress import check_inline_syntax
from bondy.scan import (
    INTERRUPTED_SKIP,
    MAX_PAGES_SKIP,
    SCAN_TIMEOUT_SKIP,
    SCANNERS,
    FileResult,
    Scanner,
    _read_text,
    discover,
    load_page,
    scan_loaded,
    static_mode_note,
)
from bondy.scan import (
    exit_code as scan_exit_code,
)

EXIT_PARTIAL = 3

# Shape of the findings stored per page. Bump it when a scanner starts to
# report more/other data, so saved pages from older versions are not reused.
# 2: accessible-name / labels findings carry the element's HTML (``nodes``).
FINDINGS_SCHEMA = 2

NO_KEY_NOTE = (
    "No API key found (set GEMINI_API_KEY or GOOGLE_API_KEY): ran deterministic "
    "scanners only, same as --no-llm. Alt-text quality and decorative-image "
    "judgement were not evaluated."
)


Target = Path | str | Sequence[Path | str]


def project_root(target: Target) -> Path:
    """Folder the report's relative paths hang from.

    A single file/folder: itself (or the file's folder). Several: their closest
    common folder. Raises ``ConfigError`` when they share none (other drives).
    """
    if isinstance(target, (list, tuple)):
        roots = [project_root(t) for t in target]
        if len(roots) == 1:
            return roots[0]
        try:
            return Path(os.path.commonpath([str(r) for r in roots]))
        except ValueError as e:
            raise ConfigError(
                "The paths have no common folder (different drives?). "
                "Scan them in separate runs."
            ) from e
    target = Path(target)
    return (target if target.is_dir() else target.parent).resolve()


def collect_images(
    files: Iterable[FileResult], target: Target
) -> list[ImageOccurrence]:
    """``<img>`` occurrences of every scanned page, in document order."""
    root = project_root(target)
    out: list[ImageOccurrence] = []
    for r in files:
        if r.skipped:
            continue
        path = Path(r.path)
        html = r.html
        if html is None:
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
    pages: list[FileResult] | None = None,
) -> None:
    by_file = {r.path: r for r in (pages if pages is not None else report.files)}
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


_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@^~{}+-]*$")


def changed_since(root: Path, ref: str) -> set[str]:
    """Resolved paths of files changed vs ``ref`` (tracked diff + untracked).

    ``ref`` is validated (no leading dash, no spaces) and passed after the
    subcommand with ``--`` ending the revision list, so it cannot inject git
    options.
    """
    if not _REF.match(ref):
        raise ConfigError(f"--since: {ref!r} is not a valid git ref.")
    cmds = (
        ["git", "-C", str(root), "diff", "--name-only", "--relative", ref, "--"],
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
    )
    names: set[str] = set()
    for cmd in cmds:
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, check=False
            )
        except (OSError, subprocess.SubprocessError) as e:
            raise ConfigError(f"--since needs git: {e}") from e
        if out.returncode != 0:
            raise ConfigError(
                f"--since {ref}: git failed ({out.stderr.strip()[:200] or 'error'}). "
                "Is the folder inside a git repository and the ref valid?"
            )
        names.update(line for line in out.stdout.splitlines() if line.strip())
    return {str((root / n).resolve()) for n in names}


def config_fingerprint(
    settings: Settings, llm: bool, scanners: dict[str, Scanner] | None
) -> str:
    """Anything that changes what a page's result would be (B9/B10)."""
    parts = [
        bondy_version(),
        f"findings={FINDINGS_SCHEMA}",
        ",".join(sorted(settings.checks)),
        f"static={settings.static}",
        f"llm={llm}",
        ",".join(c.id for c in CHECKS),
        ",".join(sorted(scanners or SCANNERS)),
    ]
    if llm:
        parts += [
            settings.vision_model,
            settings.fallback_model,
            f"remote={settings.remote_images}",
            PROMPT_FINGERPRINT,
        ]
    return sha256_hex(*parts)


def _rel(path: str | Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root).as_posix()
    except ValueError:
        return Path(path).resolve().as_posix()


def _is_complete(r: FileResult, outcomes: list[ImageOutcome]) -> bool:
    """Only a fully resolved page may be stored/reused."""
    if r.html is None or r.skipped or r.errors:
        return False
    return not any(o.recommendation == "skipped" or o.transient for o in outcomes)


def _entry(
    r: FileResult,
    outcomes: list[ImageOutcome],
    fixes: list[ImageFix],
    images_fp: str | None,
) -> dict:
    def strip(d: dict) -> dict:
        d = dict(d)
        d.pop("file", None)  # no absolute paths in the store
        return d

    return {
        "sha256": r.sha256,
        "images": images_fp,
        "findings": r.findings,
        "omitted": r.omitted,
        "fallbacks": r.fallbacks,
        "outcomes": [strip(asdict(o)) for o in outcomes],
        "fixes": [strip(asdict(f)) for f in fixes],
    }


def _images_fp(occs: list[ImageOccurrence]) -> str:
    """Hash of the local image files a page references (remote ones: by URL)."""
    seen: dict[str, str] = {}
    for o in occs:
        if o.src and o.src not in seen:
            seen[o.src] = asset_fingerprint(o)
    return sha256_hex(*[f"{k}\0{v}" for k, v in sorted(seen.items())])


def run_scan(
    target: Target,
    settings: Settings,
    *,
    scanners: dict[str, Scanner] | None = None,
    provider: LLMProvider | None = None,
    loader: ImageLoader | None = None,
    progress: Callable[[str], None] | None = None,
    notify: Callable[[str], None] | None = None,
    changed_only: bool = False,
    resume: bool = False,
    since: str | None = None,
    clear_cache: bool = False,
) -> ScanReport:
    """Runs the whole pipeline for ``target`` and returns a ``ScanReport``.

    Order: discover/load pages -> reuse unchanged pages (``changed_only`` /
    ``resume``) -> semantic image stage (cache first, so a bad API key fails
    before any browser starts) -> scanners in ONE shared browser -> merge ->
    persist page state and the resume marker.

    ``provider``/``loader`` are injectable (tests use ``FakeProvider``).
    ``progress`` receives live one-line messages (page / image / batch);
    ``notify`` receives, once and only in LLM mode, what is about to be sent to
    the provider (before the first image is downloaded or requested).
    """
    require_prices_for_limits(settings)  # before any scanner/request
    root = project_root(target)
    cache_dir = resolve_cache_dir(settings.cache_dir, root)
    if (changed_only or resume) and not settings.cache:
        raise ConfigError(
            "--changed-only/--resume need the cache directory, but caching is "
            "disabled (--no-cache / cache = false)."
        )
    if clear_cache:
        Store(cache_dir, enabled=True).clear()
    started = time.monotonic()
    deadline = started + settings.scan_timeout if settings.scan_timeout else None

    report = ScanReport(files=[], usage=UsageSummary())
    usage = report.usage
    llm = not settings.no_llm and (provider is not None or bool(settings.api_key))
    # Persistence is only created when something needs it (verdict cache with
    # the LLM, --changed-only, --since, --resume): a plain deterministic scan
    # writes nothing into the scanned project.
    needs_disk = llm or changed_only or resume or since is not None
    store = Store(cache_dir, enabled=settings.cache and needs_disk)
    usage.cache_enabled = store.enabled
    if settings.no_llm:
        usage.mode = "no-llm"
    elif not llm:
        usage.mode = "no-llm"
        report.notes.append(NO_KEY_NOTE)
    else:
        usage.mode = "llm"
    config_fp = config_fingerprint(settings, llm, scanners)

    # 1. discover + load (content is read once: it is what gets scanned/hashed)
    selected = changed_since(root, since) if since else None
    results: list[FileResult] = []
    unselected: set[str] = set()  # pages outside the --since diff (reuse-only)
    for index, path in enumerate(discover(target, settings.include, settings.exclude)):
        if settings.max_pages is not None and index >= settings.max_pages:
            results.append(
                FileResult(
                    path=str(path),
                    skipped=f"{MAX_PAGES_SKIP} ({settings.max_pages})",
                )
            )
        elif selected is not None and str(path.resolve()) not in selected:
            # Read it anyway: a valid saved result (same content hash and
            # configuration) is reused; otherwise it is reported as skipped.
            page = load_page(path)
            unselected.add(page.path)
            results.append(page)
        else:
            results.append(load_page(path))
    report.files = results
    # E4: a malformed bondy-ignore comment is a usage error, raised before any
    # request or browser work.
    check_inline_syntax(
        {_rel(r.path, root): r.html for r in results if r.html is not None}
    )
    if not results:
        report.notes.append("No HTML files found to scan.")
    cut = [r for r in results if r.skipped and r.skipped.startswith(MAX_PAGES_SKIP)]
    if cut:
        usage.partial = True
        usage.partial_reasons.append(
            f"{MAX_PAGES_SKIP} ({settings.max_pages}): {len(cut)} page(s) not scanned"
        )

    # 2. occurrences per page and reuse of unchanged pages
    loaded = [r for r in results if r.html is not None and not r.skipped]
    occs_by_file: dict[str, list[ImageOccurrence]] = {
        r.path: extract_images(
            r.html or "", r.path, str(Path(r.path).resolve().parent), str(root)
        )
        for r in loaded
    }
    images_fp = {
        r.path: (_images_fp(occs_by_file[r.path]) if llm else None) for r in loaded
    }
    prior_all = store.load_pages(config_fp)
    resume_marker = store.load_resume() if resume else None
    if resume:
        usage.resumed = resume_marker is not None
        if resume_marker is None:
            report.notes.append(
                "--resume: no interrupted scan found; running a normal scan."
            )
        elif resume_marker.get("config") != config_fp:
            usage.resumed = False
            report.notes.append(
                "--resume: Bondy version/configuration changed since the "
                "interrupted scan; its page results were discarded."
            )
    todo: list[FileResult] = []
    reuse_ok = (changed_only or (resume and usage.resumed)) and bool(prior_all)
    for r in loaded:
        outside_diff = r.path in unselected
        # Pages outside the --since diff may always reuse a valid saved result.
        allowed = bool(prior_all) if outside_diff else reuse_ok
        entry = prior_all.get(_rel(r.path, root)) if allowed else None
        if (
            entry
            and entry.get("sha256") == r.sha256
            and entry.get("images") == images_fp[r.path]
        ):
            _apply_entry(report, r, entry)
            usage.pages_reused += 1
        elif outside_diff:
            r.skipped = f"unchanged since {since} (no saved result to reuse)"
        else:
            todo.append(r)
    usage.pages_scanned = len(todo)

    # 3. semantic stage on the pages that need work (cache -> batches)
    todo_occs = [o for r in todo for o in occs_by_file[r.path]]
    stage = None
    if llm:
        usage.images_found = len(todo_occs)
    if llm and todo_occs:
        stage = _semantic_stage(
            report,
            settings,
            todo_occs,
            provider,
            loader,
            progress,
            store,
            deadline,
            notify,
        )

    # 4. deterministic scanners, ONE browser for the whole scan
    with browser_session(settings.timeout):
        scan_loaded(
            todo,
            settings.checks,
            scanners,
            force_static=settings.static,
            deadline=deadline,
            on_page=(
                (lambda i, n, r: progress(f"page {i}/{n}: {_rel(r.path, root)}"))
                if progress
                else None
            ),
        )
    static_note = static_mode_note(results)
    if static_note:
        report.notes.append(static_note)

    # 5. merge image verdicts into the pages (after scanners: they replace findings)
    if stage is not None:
        _apply_image_results(report, todo_occs, stage.outcomes, todo)
    interrupted = [r for r in results if r.skipped == INTERRUPTED_SKIP]
    timed_out = [r for r in results if r.skipped == SCAN_TIMEOUT_SKIP]
    for pages, reason in (
        (interrupted, INTERRUPTED_SKIP),
        (timed_out, SCAN_TIMEOUT_SKIP),
    ):
        if pages:
            usage.partial = True
            msg = f"{reason}: {len(pages)} page(s) not scanned"
            if msg not in usage.partial_reasons:
                usage.partial_reasons.append(msg)

    # 6. persist: page results, resume marker, usage of the cache
    _persist(report, store, config_fp, root, todo, images_fp, occs_by_file, prior_all)
    report.notes.extend(w for w in store.warnings if w not in report.notes)
    if usage.partial and store.enabled and results:
        pending = sum(1 for r in results if r.skipped or r.errors)
        store.save_resume(config_fp, list(usage.partial_reasons), pending)
    elif store.enabled and results:
        store.clear_resume()
    return report


def _apply_entry(report: ScanReport, r: FileResult, entry: dict) -> None:
    r.findings = list(entry.get("findings", []))
    r.omitted = dict(entry.get("omitted", {}))
    r.fallbacks = list(entry.get("fallbacks", []))
    r.reused = True
    for d in entry.get("outcomes", []):
        report.images.append(ImageOutcome(file=r.path, **d))
    for d in entry.get("fixes", []):
        report.fixes.append(ImageFix(file=r.path, **d))


def _persist(
    report: ScanReport,
    store: Store,
    config_fp: str,
    root: Path,
    todo: list[FileResult],
    images_fp: dict[str, str | None],
    occs_by_file: dict[str, list[ImageOccurrence]],
    prior_all: dict[str, dict],
) -> None:
    """Writes complete, unmodified pages to ``pages.json``."""
    if not store.enabled or not report.files:
        return  # nothing scanned: leave no trace on disk
    pages = {
        k: v for k, v in prior_all.items() if (root / k).exists()
    }  # forget deleted pages
    changed_during_scan = 0
    with_secrets = 0
    for r in todo:
        key = _rel(r.path, root)
        outcomes = [o for o in report.images if o.file == r.path]
        if not _is_complete(r, outcomes):
            pages.pop(key, None)  # stale result: never reuse it
            continue
        try:
            now = hashlib.sha256(Path(r.path).read_bytes()).hexdigest()
        except OSError:
            now = None
        if now != r.sha256:
            changed_during_scan += 1
            pages.pop(key, None)
            continue
        fixes = [f for f in report.fixes if f.file == r.path]
        entry = _entry(r, outcomes, fixes, images_fp.get(r.path))
        if contains_secret(entry):
            # D3: its findings quote the project's HTML; never write secret-like
            # text to disk. The page is simply re-scanned next time (its model
            # verdicts are cached, so that costs no request).
            with_secrets += 1
            pages.pop(key, None)
            continue
        pages[key] = entry
    if changed_during_scan:
        report.notes.append(
            f"{changed_during_scan} page(s) changed while being scanned: their "
            "results are valid for the content that was read but were not saved "
            "for reuse."
        )
    if with_secrets:
        report.notes.append(
            f"{with_secrets} page(s) contain secret-like text in their findings "
            "and were not saved for reuse (they are re-scanned each time)."
        )
    store.save_pages(config_fp, pages)


def _semantic_stage(
    report: ScanReport,
    settings: Settings,
    occurrences: list[ImageOccurrence],
    provider: LLMProvider | None,
    loader: ImageLoader | None,
    progress: Callable[[str], None] | None,
    store: Store,
    deadline: float | None,
    notify: Callable[[str], None] | None = None,
):
    usage = report.usage
    if provider is None:
        from bondy.core.providers.gemini import GeminiProvider

        provider = GeminiProvider.from_settings(settings)
    if notify is not None:
        notify(send_notice(occurrences, settings, provider))
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
        store=store,
        model=settings.vision_model,
        deadline=deadline,
    )
    tracker.fill(usage)
    usage.images_unique = stage.unique
    usage.images_verified = stage.verified
    usage.images_by_template = stage.by_template
    usage.images_manual_review = stage.manual_review
    usage.images_skipped = stage.skipped
    usage.cache_hits = stage.cache_hits
    usage.cache_misses = stage.cache_misses
    usage.cache_writes = stage.cache_writes
    if stage.partial_reasons:
        usage.partial = True
        usage.partial_reasons += stage.partial_reasons
    skipped = sum(1 for o in stage.outcomes if o.recommendation == "skipped")
    if skipped:
        report.notes.append(
            f"{skipped} image occurrence(s) were not verified (see partial reasons)."
        )
    return stage


def send_notice(
    occurrences: Sequence[ImageOccurrence], settings: Settings, provider: object
) -> str:
    """What this run will transmit to the model provider (shown before it does).

    Counts come from the page HTML (no download has happened yet), so "up to":
    cached verdicts, deterministic triage and unloadable images are not sent.
    """
    from urllib.parse import urlparse

    unique = {(o.src or f"<no-src>{i}", o.alt) for i, o in enumerate(occurrences)}
    remote_hosts: dict[str, int] = {}
    for o in occurrences:
        if o.src and is_remote_src(o.src):
            host = urlparse(o.src if "//" in o.src else "//" + o.src).hostname
            remote_hosts[host or "?"] = remote_hosts.get(host or "?", 0) + 1
    endpoint = getattr(provider, "endpoint_host", None) or "the configured provider"
    model = settings.vision_model or "default"
    lines = [
        f"Sending data to {endpoint} (model {model}): up to "
        f"{len(unique)} unique image(s) from {len(occurrences)} <img> tag(s), "
        f"in batches of {settings.batch_size}. Each image goes with its alt text "
        "and a short HTML snippet around it (secret-like text is redacted). "
        "Verdicts already in the cache are not sent again.",
    ]
    n_remote = sum(remote_hosts.values())
    if n_remote and settings.remote_images:
        shown = ", ".join(sorted(remote_hosts)[:5])
        more = "..." if len(remote_hosts) > 5 else ""
        lines.append(
            f"Remote images: Bondy will DOWNLOAD {n_remote} http(s) image(s) from "
            f"{shown}{more} and forward their bytes (use --no-remote-images to "
            "keep them out)."
        )
    elif n_remote:
        lines.append(
            f"Remote images: {n_remote} http(s) image(s) will NOT be downloaded "
            "(--no-remote-images); they go to manual review."
        )
    else:
        lines.append("Remote images: none; only local image files are read.")
    return " ".join(lines)


def exit_code(report: ScanReport, fail_on: str) -> int:
    """See the module docstring for the meaning of each code."""
    code = scan_exit_code(report.files, fail_on)
    if code == 0 and report.partial and fail_on != "never":
        return EXIT_PARTIAL
    return code
