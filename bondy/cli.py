"""Bondy command line: ``bondy scan``, ``bondy estimate`` and ``bondy doctor``.

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
import sys
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from bondy.config import ConfigError, load_settings

EXIT_USAGE = 2


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
    parser.add_argument("--format", choices=["terminal", "json"], help="output format")
    parser.add_argument(
        "--checks", help='comma-separated criteria, e.g. "WCAG 1.1.1,WCAG 3.1.1"'
    )
    parser.add_argument("--include", help="comma-separated glob(s) of files to scan")
    parser.add_argument("--exclude", help="comma-separated glob(s) to skip")
    parser.add_argument(
        "--batch-size", dest="batch_size", type=int, help="images per LLM request"
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
    scan.add_argument("path", help="HTML file or folder to scan")
    _add_shared_options(scan)
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
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="estimate requests/tokens/cost (like `bondy estimate`) and exit; "
        "runs no scanner and makes no request",
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
    return parser


def _render_usage(u) -> list[str]:
    if u.mode == "no-llm":
        return ["LLM usage: none (deterministic scanners only)."]
    tokens = "not reported"
    if u.input_tokens is not None:
        tilde = "~" if u.tokens_estimated else ""
        tokens = f"{tilde}{u.input_tokens} in / {tilde}{u.output_tokens} out"
    if u.cost_usd is not None:
        cost = f"~${u.cost_usd:.4f} (estimate, with your configured prices)"
    else:
        cost = f"not available ({u.cost_unavailable_reason})"
    lines = [
        "LLM usage:",
        f"  requests: {u.requests} ({u.batches} batch(es))",
        f"  images: {u.images_found} found, {u.images_unique} unique; "
        f"{u.images_verified} verified by the model, {u.images_by_template} resolved "
        f"in code, {u.images_manual_review} for manual review, "
        f"{u.images_skipped} skipped",
        f"  tokens: {tokens}",
        f"  cost: {cost}",
    ]
    if u.request_limit is not None:
        origin = (
            "default; --max-requests N to change, 0 for no limit"
            if u.request_limit_is_default
            else "--max-requests"
        )
        lines.append(f"  request limit: {u.request_limit} ({origin})")
    return lines


def _render_terminal(results, notes: list[str], usage=None) -> str:
    lines: list[str] = []
    total = 0
    for r in results:
        lines.append(f"{r.path}")
        if r.skipped:
            lines.append(f"  skipped: {r.skipped}")
        for e in r.errors:
            lines.append(f"  ERROR {e}")
        for f in r.findings:
            total += 1
            wcag = ",".join(f["wcag"]) or "-"
            lines.append(
                f"  [{f['severity']:<8}] {f['scanner']:<15} WCAG {wcag}: {f['message']}"
            )
    lines.append("")
    lines.append(f"{len(results)} file(s) scanned, {total} finding(s).")
    lines.extend(f"note: {n}" for n in notes)
    if usage is not None:
        lines.extend(_render_usage(usage))
        if usage.partial:
            lines.append("PARTIAL RESULT: " + "; ".join(usage.partial_reasons))
    return chr(10).join(lines)


_FLAG_NAMES = (
    "no_llm", "static", "format", "fail_on", "checks", "include", "exclude",
    "batch_size", "max_requests", "max_usd", "max_pages", "max_images",
    "remote_images",
)  # fmt: skip


def _flags(args: argparse.Namespace) -> dict:
    return {name: getattr(args, name, None) for name in _FLAG_NAMES}


def _print_estimate(args: argparse.Namespace, settings) -> int:
    from bondy.core.estimate import estimate_scan, format_estimate

    try:
        est = estimate_scan(Path(args.path), settings)
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
    return _print_estimate(args, settings)


def _cmd_scan(args: argparse.Namespace) -> int:
    from bondy.core.pipeline import exit_code, run_scan

    flags = _flags(args)
    try:
        settings = load_settings(flags=flags, config_path=args.config)
    except ConfigError as e:
        print(f"bondy: config error: {e}", file=sys.stderr)
        return EXIT_USAGE

    if args.dry_run:
        return _print_estimate(args, settings)

    try:
        report = run_scan(Path(args.path), settings)
    except (FileNotFoundError, ConfigError) as e:
        print(f"bondy: {e}", file=sys.stderr)
        return EXIT_USAGE

    results, notes = report.files, report.notes
    code = exit_code(report, settings.fail_on)

    if settings.format == "json":
        payload = {
            "version": _version(),
            "mode": report.usage.mode,
            "exit_code": code,
            "static_mode": any(r.omitted for r in results),
            "notes": notes,
            "usage": report.usage.as_dict(),
            "fixes": [asdict(f) for f in report.fixes],
            "files": [
                {
                    "path": r.path,
                    "skipped": r.skipped,
                    "errors": r.errors,
                    "omitted_checks": r.omitted,
                    "findings": r.findings,
                }
                for r in results
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(_render_terminal(results, notes, report.usage))
    return code


def _cmd_doctor(args: argparse.Namespace) -> int:
    from bondy.doctor import run_checks

    checks = run_checks(args.config)
    marks = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}
    for c in checks:
        print(f"[{marks[c.status]}] {c.name}: {c.detail}")
        if c.status != "ok" and c.fix:
            print(f"       fix: {c.fix}")
    return 1 if any(c.status == "fail" for c in checks) else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "scan":
        return _cmd_scan(args)
    if args.command == "estimate":
        return _cmd_estimate(args)
    if args.command == "doctor":
        return _cmd_doctor(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
