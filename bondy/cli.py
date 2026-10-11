"""Bondy command line: ``bondy scan``, ``bondy estimate`` and ``bondy doctor``.

``bondy scan`` takes one or more files/folders. Live progress and the notice of
what is sent to the model provider go to **stderr** (stdout carries only the
report); progress is shown on a TTY or with ``--progress`` and hidden by
``--quiet``.

Exit codes for ``scan``: 0 = nothing at/above ``--fail-on``; 1 = findings at or
above the threshold; 2 = usage/config error or a scanner failed (incomplete);
3 = PARTIAL result (a --max-* limit or the API quota stopped the scan) with
nothing at/above the threshold, so a clean pass cannot be claimed.
Without any usable browser the scan runs in static mode (HTML parsing only),
says so in ``notes`` and still exits 0/1.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from bondy.config import ConfigError, load_settings
from bondy.core.baseline import (
    DEFAULT_BASELINE_FILE,
    build_document,
    load_baseline,
    write_baseline,
)
from bondy.core.formats import FORMATS, render
from bondy.core.providers.base import ProviderError
from bondy.core.redact import redact_secrets
from bondy.core.report import build_report

EXIT_USAGE = 2
NL = "\n"


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_PROGRESS_MAX = 200


def _line_safe(text: str) -> str:
    """One terminal-safe line: control characters out, secrets redacted."""
    text = _CONTROL.sub("?", redact_secrets(str(text)))
    return text if len(text) <= _PROGRESS_MAX else text[: _PROGRESS_MAX - 3] + "..."


def _stderr_sink(prefix: str):
    def sink(message: str) -> None:
        print(f"{prefix}{_line_safe(message)}", file=sys.stderr, flush=True)

    return sink


def _resolve_targets(raw: list[str]) -> list[Path]:
    """Existing, de-duplicated paths in the order given.

    Raises ``FileNotFoundError`` naming EVERY missing path at once.
    """
    missing = [p for p in raw if not Path(p).exists()]
    if missing:
        shown = ", ".join(f'"{p}"' for p in missing)
        raise FileNotFoundError(
            f"Path not found: {shown}"
            if len(missing) == 1
            else f"{len(missing)} paths not found: {shown}"
        )
    seen: set[str] = set()
    out: list[Path] = []
    for p in raw:
        key = os.path.normcase(str(Path(p).resolve()))
        if key not in seen:
            seen.add(key)
            out.append(Path(p))
    return out


def _version() -> str:
    try:
        return version("bondy")
    except PackageNotFoundError:
        return "0.0.0+local"


def _add_shared_options(parser: argparse.ArgumentParser) -> None:
    """Options shared by ``scan`` and ``estimate`` (same names, same precedence)."""
    parser.add_argument("--config", help="path to bondy.toml (default: nearest one)")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        default=None,
        help="deterministic scanners only (no API key, no network)",
    )
    parser.add_argument("--format", choices=list(FORMATS), help="output format")
    parser.add_argument(
        "--checks", help='comma-separated criteria, e.g. "WCAG 1.1.1,WCAG 3.1.1"'
    )
    parser.add_argument("--include", help="comma-separated glob(s) of files to scan")
    parser.add_argument("--exclude", help="comma-separated glob(s) to skip")
    parser.add_argument(
        "--batch-size", dest="batch_size", type=int, help="images per LLM request"
    )
    parser.add_argument(
        "--no-cache",
        dest="cache",
        action="store_const",
        const=False,
        default=None,
        help="do not read or write anything under the cache directory "
        "(verdict cache, page state, resume marker)",
    )
    parser.add_argument(
        "--cache-dir",
        dest="cache_dir",
        help="cache directory (default: <scanned folder>/.bondy/cache; a "
        "relative path is resolved against the scanned folder)",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout",
        type=float,
        help="seconds per page for browser work (default 60; 0 = no limit)",
    )
    parser.add_argument(
        "--scan-timeout",
        dest="scan_timeout",
        type=float,
        help="seconds for the whole scan (default 900; 0 = no limit); on "
        "expiry the result is PARTIAL",
    )
    parser.add_argument(
        "--no-remote-images",
        dest="remote_images",
        action="store_const",
        const=False,
        default=None,
        help="do not download http(s) images (they go to manual review); "
        "local images are unaffected",
    )
    limits = parser.add_argument_group(
        "hard limits",
        "When one is reached the scan stops and returns a PARTIAL result "
        "(exit code 3 unless findings reach --fail-on). 0 = unlimited.",
    )
    limits.add_argument(
        "--max-requests",
        dest="max_requests",
        type=int,
        help="HTTP requests to the model, retries included (default 50; 0 = no limit)",
    )
    limits.add_argument(
        "--max-usd",
        dest="max_usd",
        type=float,
        help="estimated spend cap; requires price_input_per_mtok and "
        "price_output_per_mtok to be configured",
    )
    limits.add_argument("--max-pages", dest="max_pages", type=int)
    limits.add_argument("--max-images", dest="max_images", type=int)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bondy", description="Local, BYOK web accessibility auditor."
    )
    parser.add_argument("--version", action="version", version=f"bondy {_version()}")
    sub = parser.add_subparsers(dest="command")

    scan = sub.add_parser(
        "scan",
        help="scan an HTML file or a folder",
        description="Scan HTML for WCAG issues.",
    )
    scan.add_argument(
        "path",
        nargs="+",
        metavar="PATH",
        help="HTML file(s) or folder(s) to scan; duplicates are scanned once. "
        "With several paths, report paths are relative to their common folder",
    )
    _add_shared_options(scan)
    scan.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="no live progress on stderr (the report and the notice of what is "
        "sent to the model are unaffected)",
    )
    scan.add_argument(
        "--progress",
        action="store_true",
        help="show live progress on stderr even when it is not a terminal",
    )
    scan.add_argument(
        "--static",
        action="store_true",
        default=None,
        help="force static mode: HTML-parsing checks only, never launch a browser",
    )
    scan.add_argument(
        "--fail-on",
        dest="fail_on",
        choices=["critical", "warning", "never"],
        help="lowest severity that makes the exit code non-zero",
    )
    scan.add_argument(
        "--baseline",
        metavar="FILE",
        help="ignore findings recorded in this baseline (see `bondy baseline "
        "create`); only NEW findings affect the exit code",
    )
    scan.add_argument(
        "--output",
        "-o",
        dest="output",
        metavar="FILE",
        help="write the report (in --format) to FILE; the terminal summary is "
        "still printed",
    )
    scan.add_argument(
        "--sarif-prefix",
        dest="sarif_prefix",
        metavar="DIR",
        default="",
        help="SARIF only: folder of the scanned root relative to the repository "
        "root (GitHub resolves SARIF paths from the repository root)",
    )
    scan.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="estimate requests/tokens/cost (like `bondy estimate`) and exit; "
        "runs no scanner and makes no request",
    )

    scan.add_argument(
        "--changed-only",
        dest="changed_only",
        action="store_true",
        help="re-scan only pages whose content (or local images) changed since "
        "the last scan; reuse the stored result of the rest",
    )
    scan.add_argument(
        "--since",
        metavar="GIT_REF",
        help="scan only files changed vs this git ref (plus untracked); the "
        "others are listed as skipped, not as a partial result",
    )
    scan.add_argument(
        "--resume",
        action="store_true",
        help="continue an interrupted/partial scan: finished pages and "
        "already-answered images are not repeated",
    )
    scan.add_argument(
        "--clear-cache",
        dest="clear_cache",
        action="store_true",
        help="delete Bondy's cache/state in the cache directory before scanning",
    )

    estimate = sub.add_parser(
        "estimate",
        help="estimate LLM requests, tokens and cost before scanning",
        description="Estimate the cost of `bondy scan` WITHOUT calling the model. "
        "Numbers are approximations; prices come from your configuration.",
    )
    estimate.add_argument("path", help="HTML file or folder to analyse")
    _add_shared_options(estimate)

    doctor = sub.add_parser("doctor", help="check the local environment")
    doctor.add_argument("--config", help="path to bondy.toml")
    doctor.add_argument(
        "--check-key",
        dest="check_key",
        action="store_true",
        help="validate the API key with ONE minimal request (spends a request; "
        "without this flag doctor stays offline)",
    )

    baseline = sub.add_parser(
        "baseline", help="manage the baseline of accepted findings"
    )
    baseline_sub = baseline.add_subparsers(dest="baseline_command")
    create = baseline_sub.add_parser(
        "create",
        help="scan and record the current findings as the baseline",
        description="Scan PATH and write its findings to a baseline file. "
        "Refuses to write if the scan had errors or is partial.",
    )
    create.add_argument("path", help="HTML file or folder to scan")
    _add_shared_options(create)
    create.add_argument(
        "--static", action="store_true", default=None, help="force static mode"
    )
    create.add_argument(
        "-o",
        "--output",
        default=DEFAULT_BASELINE_FILE,
        help=f"baseline file to write (default: {DEFAULT_BASELINE_FILE})",
    )

    cache = sub.add_parser("cache", help="manage Bondy's cache")
    cache_sub = cache.add_subparsers(dest="cache_command")
    clear = cache_sub.add_parser(
        "clear", help="delete cached verdicts and page state (only Bondy's files)"
    )
    clear.add_argument("path", nargs="?", default=".", help="scanned folder")
    clear.add_argument("--config", help="path to bondy.toml")
    clear.add_argument("--cache-dir", dest="cache_dir")
    clear.add_argument(
        "--keep-state",
        dest="keep_state",
        action="store_true",
        help="delete only the verdict cache, keep page results/resume marker",
    )
    return parser


_FLAG_NAMES = (
    "no_llm", "static", "format", "fail_on", "checks", "include", "exclude",
    "batch_size", "max_requests", "max_usd", "max_pages", "max_images",
    "remote_images", "cache", "cache_dir", "timeout", "scan_timeout", "baseline",
)  # fmt: skip


def _flags(args: argparse.Namespace) -> dict:
    return {name: getattr(args, name, None) for name in _FLAG_NAMES}


def _print_estimate(targets, settings) -> int:
    from bondy.core.estimate import estimate_scan, format_estimate

    try:
        est = estimate_scan(targets, settings)
    except (FileNotFoundError, ConfigError) as e:
        print(f"bondy: {e}", file=sys.stderr)
        return EXIT_USAGE
    if settings.format == "json":
        print(json.dumps(est.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(format_estimate(est))
    return 0


def _cmd_estimate(args: argparse.Namespace) -> int:
    try:
        settings = load_settings(flags=_flags(args), config_path=args.config)
    except ConfigError as e:
        print(f"bondy: config error: {e}", file=sys.stderr)
        return EXIT_USAGE
    return _print_estimate(Path(args.path), settings)


def _cmd_scan(args: argparse.Namespace) -> int:
    from bondy.core.pipeline import project_root, run_scan

    flags = _flags(args)
    try:
        settings = load_settings(flags=flags, config_path=args.config)
    except ConfigError as e:
        print(f"bondy: config error: {e}", file=sys.stderr)
        return EXIT_USAGE

    try:
        targets = _resolve_targets(args.path)
        root = project_root(targets)
    except (FileNotFoundError, ConfigError) as e:
        print(f"bondy: {e}", file=sys.stderr)
        return EXIT_USAGE

    if args.dry_run:
        return _print_estimate(targets, settings)

    baseline = None
    if settings.baseline:  # validated before anything is scanned or spent
        try:
            baseline = load_baseline(settings.baseline)
        except ConfigError as e:
            print(f"bondy: {e}", file=sys.stderr)
            return EXIT_USAGE

    try:
        show_progress = not args.quiet and (args.progress or sys.stderr.isatty())
        report = run_scan(
            targets,
            settings,
            progress=_stderr_sink("bondy: ") if show_progress else None,
            notify=_stderr_sink("bondy: NOTICE: "),
            changed_only=args.changed_only,
            resume=args.resume,
            since=args.since,
            clear_cache=args.clear_cache,
        )
    except (FileNotFoundError, ConfigError) as e:
        print(f"bondy: {e}", file=sys.stderr)
        return EXIT_USAGE
    except ProviderError as e:
        if e.kind != "invalid_key":
            raise
        print(
            "bondy: the API key was rejected by the API (invalid, expired or "
            "without permission). No further requests were made. Create or "
            "check a key at https://aistudio.google.com/apikey, or run with "
            "--no-llm.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    model = build_report(
        report,
        root,
        version=_version(),
        baseline=baseline,
        ignore_rules=settings.ignore,
        checks=settings.checks,
    )
    code = model.exit_code(settings.fail_on)
    return _emit(model, code, settings.format, args.output, args.sarif_prefix)


def _emit(model, code: int, fmt: str, output: str | None, sarif_prefix: str) -> int:
    """Prints/writes the report. Returns ``code`` or 2 if the file cannot be written."""
    text = render(fmt, model, code, sarif_prefix=sarif_prefix)
    if output is None:
        print(text)
        return code
    try:
        _write_text(Path(output), text if text.endswith(NL) else text + NL)
    except OSError as e:
        print(f"bondy: cannot write --output {output}: {e}", file=sys.stderr)
        return EXIT_USAGE
    if fmt == "terminal":
        print(f"Report written to {output}")
    else:
        print(render("terminal", model, code))
        print(f"{fmt} report written to {output}")
    return code


def _write_text(path: Path, text: str) -> None:
    """UTF-8 write via a temp file in the same folder (no half-written report)."""
    if path.is_dir():
        raise IsADirectoryError(f"{path} is a directory")
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline=NL)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _cmd_baseline(args: argparse.Namespace) -> int:
    from bondy.core.pipeline import project_root, run_scan

    if args.baseline_command != "create":
        print("usage: bondy baseline create <path> [-o FILE]", file=sys.stderr)
        return EXIT_USAGE
    try:
        settings = load_settings(flags=_flags(args), config_path=args.config)
        report = run_scan(Path(args.path), settings)
    except (FileNotFoundError, ConfigError) as e:
        print(f"bondy: {e}", file=sys.stderr)
        return EXIT_USAGE
    except ProviderError as e:
        if e.kind != "invalid_key":
            raise
        print(
            "bondy: the API key was rejected by the API; no baseline written. "
            "Fix the key or run with --no-llm.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    model = build_report(
        report,
        project_root(Path(args.path)),
        version=_version(),
        ignore_rules=settings.ignore,
        checks=settings.checks,
    )
    if model.has_errors:
        print(
            "bondy: the scan had errors, so the baseline would be incomplete; "
            "nothing was written. Fix the errors (run `bondy scan` to see them).",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if model.partial:
        print(
            "bondy: the scan is PARTIAL ("
            + "; ".join(model.usage.partial_reasons)
            + "); nothing was written. Re-run with --resume or raise the limits.",
            file=sys.stderr,
        )
        return 3
    items = model.new_items
    try:
        write_baseline(Path(args.output), build_document(items, _version()))
    except OSError as e:
        print(f"bondy: cannot write {args.output}: {e}", file=sys.stderr)
        return EXIT_USAGE
    counts = model.count_by_severity(items)
    print(
        f"Baseline written to {args.output}: {len(items)} finding(s) "
        f"({counts['critical']} critical, {counts['warning']} warning). "
        f"Use it with: bondy scan {args.path} --baseline {args.output}"
    )
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    from bondy.doctor import run_checks

    checks = run_checks(args.config, check_key=args.check_key)
    marks = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}
    for c in checks:
        print(f"[{marks[c.status]}] {c.name}: {c.detail}")
        if c.status != "ok" and c.fix:
            print(f"       fix: {c.fix}")
    return 1 if any(c.status == "fail" for c in checks) else 0


def _cmd_cache(args: argparse.Namespace) -> int:
    from bondy.core.pipeline import project_root
    from bondy.core.store import Store, resolve_cache_dir

    if args.cache_command != "clear":
        print("usage: bondy cache clear [path] [--keep-state]", file=sys.stderr)
        return EXIT_USAGE
    try:
        settings = load_settings(
            flags={"cache_dir": args.cache_dir}, config_path=args.config
        )
    except ConfigError as e:
        print(f"bondy: config error: {e}", file=sys.stderr)
        return EXIT_USAGE
    root = project_root(Path(args.path))
    directory = resolve_cache_dir(settings.cache_dir, root)
    removed = Store(directory).clear(include_state=not args.keep_state)
    print(f"Removed {removed} file(s) from {directory}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "scan":
        return _cmd_scan(args)
    if args.command == "estimate":
        return _cmd_estimate(args)
    if args.command == "doctor":
        return _cmd_doctor(args)
    if args.command == "cache":
        return _cmd_cache(args)
    if args.command == "baseline":
        return _cmd_baseline(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
