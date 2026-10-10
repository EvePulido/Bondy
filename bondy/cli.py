"""Bondy command line: ``bondy scan <path>`` and ``bondy doctor``.

Exit codes for ``scan``: 0 = nothing at/above ``--fail-on``; 1 = findings at or
above the threshold; 2 = usage/config error or a scanner failed (incomplete).
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from bondy.config import ConfigError, load_settings

EXIT_USAGE = 2


def _version() -> str:
    try:
        return version("bondy")
    except PackageNotFoundError:
        return "0.0.0+local"


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
    scan.add_argument("--config", help="path to bondy.toml (default: nearest one)")
    scan.add_argument(
        "--no-llm",
        action="store_true",
        default=None,
        help="deterministic scanners only (no API key, no network)",
    )
    scan.add_argument("--format", choices=["terminal", "json"], help="output format")
    scan.add_argument(
        "--fail-on",
        dest="fail_on",
        choices=["critical", "warning", "never"],
        help="lowest severity that makes the exit code non-zero",
    )
    scan.add_argument(
        "--checks", help='comma-separated criteria, e.g. "WCAG 1.1.1,WCAG 3.1.1"'
    )
    scan.add_argument("--include", help="comma-separated glob(s) of files to scan")
    scan.add_argument("--exclude", help="comma-separated glob(s) to skip")

    doctor = sub.add_parser("doctor", help="check the local environment")
    doctor.add_argument("--config", help="path to bondy.toml")
    return parser


def _render_terminal(results, notes: list[str]) -> str:
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
    return "\n".join(lines)


def _cmd_scan(args: argparse.Namespace) -> int:
    from bondy.scan import exit_code, scan_path

    flags = {
        "no_llm": args.no_llm,
        "format": args.format,
        "fail_on": args.fail_on,
        "checks": args.checks,
        "include": args.include,
        "exclude": args.exclude,
    }
    try:
        settings = load_settings(flags=flags, config_path=args.config)
    except ConfigError as e:
        print(f"bondy: config error: {e}", file=sys.stderr)
        return EXIT_USAGE

    notes: list[str] = []
    if not settings.no_llm:
        notes.append(
            "The LLM semantic pipeline is not available yet; ran deterministic "
            "scanners only (same as --no-llm). Alt-text quality and decorative-image "
            "judgement were not evaluated."
        )

    try:
        results = scan_path(
            Path(args.path), settings.include, settings.exclude, settings.checks
        )
    except FileNotFoundError as e:
        print(f"bondy: {e}", file=sys.stderr)
        return EXIT_USAGE

    if not results:
        notes.append("No HTML files found to scan.")
    code = exit_code(results, settings.fail_on)

    if settings.format == "json":
        payload = {
            "version": _version(),
            "mode": "no-llm",
            "exit_code": code,
            "notes": notes,
            "files": [
                {
                    "path": r.path,
                    "skipped": r.skipped,
                    "errors": r.errors,
                    "findings": r.findings,
                }
                for r in results
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(_render_terminal(results, notes))
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
    if args.command == "doctor":
        return _cmd_doctor(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
