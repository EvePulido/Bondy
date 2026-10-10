"""Baselines: accept the debt that exists today, fail only on what is new (E2).

A baseline is a small, deterministic JSON file meant to be committed. Each
entry is the stable fingerprint of an item (rule + path relative to the scanned
root + normalized selector/snippet; never a line number, see ``report``). A run
with ``--baseline`` hides the matching items, counts them, and reports baseline
entries that no longer occur as *resolved* so the file can be regenerated.
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bondy.config import ConfigError
from bondy.core.report import BaselineInfo, Item, Report

BASELINE_VERSION = 1
BASELINE_SCHEMA = "bondy-baseline"
DEFAULT_BASELINE_FILE = "bondy-baseline.json"
MAX_BASELINE_BYTES = 20 * 1024 * 1024

# scanner -> the browser scanner that must have run for the entry to be judged
_OWNER = {
    "axe": "axe",
    "axe-tree": "axe",
    "contrast": "contrast",
    "focus-trap": "focus-trap",
    "focus-order": "focus-order",
}


class BaselineError(ConfigError):
    """The baseline file is unusable (message says how to fix it)."""


@dataclass
class Baseline:
    name: str  # as given by the user; never resolved to an absolute path
    entries: dict[str, dict[str, Any]]  # fingerprint -> entry


def build_document(items: list[Item], bondy_version: str = "") -> dict[str, Any]:
    """Deterministic document (no timestamp, sorted) so diffs show real changes."""
    findings = [
        {
            "fingerprint": i.fingerprint,
            "rule": i.rule,
            "scanner": i.scanner,
            "file": i.file,
            "wcag": i.wcag,
            "severity": i.severity,
            "selector": i.selector,
            "message": i.message,
        }
        for i in items
    ]
    findings.sort(key=lambda f: (f["file"], f["rule"], f["fingerprint"]))
    return {
        "schema": BASELINE_SCHEMA,
        "version": BASELINE_VERSION,
        "bondy": bondy_version,
        "findings": findings,
    }


def write_baseline(path: Path, document: dict[str, Any]) -> None:
    """Atomic UTF-8 write. Raises ``OSError`` (caller reports it)."""
    if path.is_dir():
        raise IsADirectoryError(f"{path} is a directory")
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def load_baseline(path: Path | str) -> Baseline:
    """Reads and validates a baseline; every problem is a ``BaselineError``."""
    path = Path(path)
    fix = f"Regenerate it with: bondy baseline create <path> -o {path.name}"
    if not path.is_file():
        raise BaselineError(
            f"baseline file not found: {path}. Create one with: "
            f"bondy baseline create <path> -o {path}"
        )
    try:
        if path.stat().st_size > MAX_BASELINE_BYTES:
            raise BaselineError(f"baseline {path} is larger than 20 MB. {fix}")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        raise BaselineError(f"baseline {path} cannot be read ({e}). {fix}") from e
    except ValueError as e:
        raise BaselineError(f"baseline {path} is not valid JSON ({e}). {fix}") from e
    if not isinstance(data, dict) or data.get("schema") != BASELINE_SCHEMA:
        raise BaselineError(f"{path} is not a Bondy baseline file. {fix}")
    if data.get("version") != BASELINE_VERSION:
        raise BaselineError(
            f"baseline {path} has format version {data.get('version')!r}; this "
            f"Bondy understands version {BASELINE_VERSION}. Update Bondy (if the "
            f"file is newer) or regenerate it. {fix}"
        )
    findings = data.get("findings")
    if not isinstance(findings, list) or not all(
        isinstance(f, dict) and isinstance(f.get("fingerprint"), str) for f in findings
    ):
        raise BaselineError(f"baseline {path} is malformed ('findings'). {fix}")
    return Baseline(path.name, {f["fingerprint"]: f for f in findings})


def _evaluated(entry: dict[str, Any], report: Report, wanted: set[str]) -> bool:
    """Could this run have reproduced the entry? (else it is not 'resolved')"""
    file = next((f for f in report.files if f.path == entry.get("file")), None)
    if file is None or file.skipped or file.errors:
        return False
    if report.partial:
        return False
    if wanted and not wanted & set(entry.get("wcag") or []):
        return False  # --checks filtered this criterion out
    scanner = entry.get("scanner", "")
    if scanner == "alt-text":
        return report.mode == "llm"
    if scanner == "img-alt":  # static stand-in for axe, only runs without a browser
        return "axe" in file.omitted
    owner = _OWNER.get(scanner)
    return not (owner and owner in file.omitted)


def apply_baseline(report: Report, baseline: Baseline, checks=()) -> None:
    """Marks known items ``baselined`` and records what was resolved."""
    wanted = {c.strip().removeprefix("WCAG").strip() for c in checks if c.strip()}
    info = BaselineInfo(file=baseline.name, known=len(baseline.entries))
    seen: set[str] = set()
    for item in report.items:
        if item.status == "new" and item.fingerprint in baseline.entries:
            item.status = "baselined"
            seen.add(item.fingerprint)
            info.matched += 1
    for fp, entry in baseline.entries.items():
        if fp in seen:
            continue
        # an entry hidden by a suppression this run is neither resolved nor lost
        if any(i.fingerprint == fp for i in report.items):
            continue
        if _evaluated(entry, report, wanted):
            info.resolved += 1
            info.resolved_items.append(
                {
                    "fingerprint": fp,
                    "rule": entry.get("rule"),
                    "file": entry.get("file"),
                    "message": entry.get("message"),
                }
            )
        else:
            info.not_evaluated += 1
    report.baseline = info
