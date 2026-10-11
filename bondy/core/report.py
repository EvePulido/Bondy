"""The single internal report model every output format is rendered from.

``build_report`` flattens the scanners' findings into one ``Item`` per affected
element (the unit that baselines, suppressions and SARIF results work on),
makes every path relative to the scanned root with ``/`` separators and
computes a stable fingerprint per item. Formats (``bondy.core.formats``) only
*present* this model; none of them re-derives anything.

Everything that comes from the scanned project (paths, selectors, HTML
snippets, alt text) is untrusted data: this module never interprets it, and the
renderers escape it for their medium.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from bondy.core.checks import CHECKS
from bondy.core.dedupe import dedupe_items
from bondy.core.models import ScanReport, UsageSummary
from bondy.core.redact import redact_secrets
from bondy.core.source import PageIndex
from bondy.core.store import sha256_hex

SEVERITIES = ("critical", "warning")
SEVERITY_RANK = {"warning": 1, "critical": 2}
EXIT_PARTIAL = 3

# One line of advice per rule for scanners that do not carry their own.
FIX_HINTS = {
    "lang": 'Add a valid language to the root element, e.g. <html lang="en">.',
    "labels": "Associate a <label for=...> with the control or add an aria-label.",
    "accessible-name": "Give the element visible text or an aria-label.",
    "contrast": "Change the text or background colour to reach the required ratio.",
    "focus-trap": "Make sure keyboard focus can leave the component (e.g. Esc/Tab).",
    "focus-order": "Reorder the markup (or remove positive tabindex) so focus is logical.",
    "img-alt": 'Add an alt attribute (alt="" when the image is decorative).',
    "axe-tree": "Give the interactive element an accessible name.",
}
_TITLES = {c.id: c.title for c in CHECKS}
_WS = re.compile(r"\s+")
_LINE_PREFIX = re.compile(r"^line \d+: ")


@dataclass
class Item:
    """One reported issue: a finding narrowed to a single element."""

    file: str  # relative to the scanned root, "/" separators
    scanner: str
    rule: str  # axe rule id, or the scanner name for Bondy's own checks
    wcag: list[str]
    severity: str
    message: str
    selector: str | None = None
    snippet: str | None = None
    line: int | None = None
    fix: str | None = None
    fingerprint: str = ""
    status: str = "new"  # new | baselined | suppressed
    suppressed_by: dict[str, Any] | None = None
    details: dict[str, Any] = field(default_factory=dict)  # alt-text specifics
    # duplicates of this problem found by other scanners and merged into it:
    # [{"scanner", "rule", "message", "fingerprint"}] (see bondy.core.dedupe)
    merged_from: list[dict[str, Any]] = field(default_factory=list)

    def all_fingerprints(self) -> list[str]:
        """Own fingerprint plus the ones of the findings merged into it."""
        return [self.fingerprint, *(m["fingerprint"] for m in self.merged_from)]

    def all_rules(self) -> list[str]:
        """Own rule plus the rules of the findings merged into it."""
        return [self.rule, *(m["rule"] for m in self.merged_from)]


@dataclass
class FileEntry:
    path: str
    skipped: str | None = None
    errors: list[str] = field(default_factory=list)
    omitted: dict[str, str] = field(default_factory=dict)
    reused: bool = False


@dataclass
class Suppression:
    """An ignore directive and what it did in this scan."""

    source: str  # "comment" | "config"
    file: str  # relative file (comment) or glob (config)
    rule: str
    reason: str
    line: int | None = None
    matched: int = 0
    status: str = "applied"  # applied | obsolete | unverified
    detail: str = ""


@dataclass
class BaselineInfo:
    file: str  # the name the user passed (never resolved to an absolute path)
    known: int = 0  # entries in the baseline file
    matched: int = 0  # items hidden because they are in the baseline
    resolved: int = 0
    not_evaluated: int = 0
    resolved_items: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Report:
    version: str
    mode: str
    files: list[FileEntry]
    items: list[Item]
    fixes: list[dict[str, Any]]
    notes: list[str]
    usage: UsageSummary
    suppressions: list[Suppression] = field(default_factory=list)
    baseline: BaselineInfo | None = None
    static_mode: bool = False
    duplicates_merged: int = 0  # findings absorbed into another (dedupe)

    # ----- views -----
    @property
    def new_items(self) -> list[Item]:
        return [i for i in self.items if i.status == "new"]

    @property
    def baselined_items(self) -> list[Item]:
        return [i for i in self.items if i.status == "baselined"]

    @property
    def suppressed_items(self) -> list[Item]:
        return [i for i in self.items if i.status == "suppressed"]

    @property
    def partial(self) -> bool:
        return self.usage.partial

    @property
    def has_errors(self) -> bool:
        return any(f.errors for f in self.files)

    def count_by_severity(self, items: list[Item] | None = None) -> dict[str, int]:
        items = self.new_items if items is None else items
        counts = dict.fromkeys(SEVERITIES, 0)
        for i in items:
            counts[i.severity] = counts.get(i.severity, 0) + 1
        return counts

    def summary(self) -> dict[str, Any]:
        """The numbers and the next step shown at the end of every format."""
        new = self.new_items
        obsolete = [s for s in self.suppressions if s.status == "obsolete"]
        applied = [s for s in self.suppressions if s.status == "applied"]
        u = self.usage
        out: dict[str, Any] = {
            "findings": {
                "new": {**self.count_by_severity(), "total": len(new)},
                "baselined": len(self.baselined_items),
                "suppressed": len(self.suppressed_items),
                "duplicates_merged": self.duplicates_merged,
            },
            "baseline": asdict(self.baseline) if self.baseline else None,
            "suppressions": {"applied": len(applied), "obsolete": len(obsolete)},
            "pages": {
                "total": len(self.files),
                "scanned": u.pages_scanned,
                "reused": u.pages_reused,
                "skipped": sum(1 for f in self.files if f.skipped),
                "with_errors": sum(1 for f in self.files if f.errors),
            },
            "partial": self.partial,
        }
        if out["baseline"]:
            out["baseline"].pop("resolved_items", None)
        out["next_step"] = self.next_step()
        return out

    def next_step(self) -> str:
        new = self.new_items
        resolved = self.baseline.resolved if self.baseline else 0
        obsolete = sum(1 for s in self.suppressions if s.status == "obsolete")
        if self.has_errors:
            return (
                "Fix the scan errors listed above and run again: the result is "
                "incomplete."
            )
        if self.partial:
            return (
                "The result is partial. Run again with --resume to finish "
                "without repeating work (or raise the limit that was reached)."
            )
        if new:
            counts = self.count_by_severity(new)
            return (
                f"Fix the {len(new)} new finding(s) ({counts['critical']} critical, "
                f"{counts['warning']} warning) using the suggested fixes, then run "
                "again. To accept the current state instead: bondy baseline "
                "create <path>."
            )
        if obsolete:
            return (
                f"No new findings. Remove the {obsolete} obsolete ignore(s) "
                "listed above: they match nothing."
            )
        if resolved:
            return (
                f"No new findings. {resolved} baselined finding(s) were fixed: "
                "run bondy baseline create <path> to shrink the baseline."
            )
        return "No new findings. Nothing to do."

    def exit_code(self, fail_on: str) -> int:
        """0 clean / below threshold, 1 new findings at or above ``fail_on``,
        2 scan errors, 3 partial result with nothing at/above the threshold.

        Only NEW items count: baselined and suppressed ones never fail a run.
        """
        if self.has_errors:
            return 2
        threshold = {"critical": 2, "warning": 1}.get(fail_on)
        if threshold is None:
            return 0
        worst = max(
            (SEVERITY_RANK.get(i.severity, 1) for i in self.new_items), default=0
        )
        if worst >= threshold:
            return 1
        return EXIT_PARTIAL if self.partial else 0


# ----- helpers -----
def relative_path(path: str | Path, root: Path) -> str:
    """Path relative to ``root`` with ``/``; never an absolute path."""
    p = Path(path)
    try:
        return p.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return p.name


def scrubber(root: Path):
    """Function removing the absolute scanned root from free text."""
    variants = sorted(
        {str(root), root.as_posix(), str(root).replace("\\", "/")},
        key=len,
        reverse=True,
    )

    def scrub(text: str) -> str:
        for v in variants:
            if v:
                text = text.replace(v + "/", "").replace(v + "\\", "").replace(v, ".")
        return text

    return scrub


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _fix_for(f: dict[str, Any], rule: str, node: dict[str, Any] | None) -> str | None:
    if f.get("scanner") == "alt-text":
        if "suggested_alt" in f:
            new = f.get("suggested_alt")
            if new == "":
                return 'Set alt="" (the image is decorative).'
            return f'Set alt="{new}".' if new else None
        return "Review the image and write an alt that conveys its purpose."
    if node and node.get("failure"):
        return _norm(node["failure"])
    return FIX_HINTS.get(rule)


def _expand(f: dict[str, Any]) -> list[dict[str, Any]]:
    """One dict per affected element of a finding (before paths/fingerprints)."""
    scanner = f.get("scanner") or "unknown"
    rule = f.get("rule") or scanner
    message = _LINE_PREFIX.sub("", f.get("message") or "")
    base = {
        "scanner": scanner,
        "rule": rule,
        "wcag": list(f.get("wcag") or []),
        "severity": f.get("severity") or "warning",
        "message": message,
        "line": f.get("line"),
        "details": {
            k: f[k]
            for k in ("classification", "suggested_alt", "confidence", "origin", "src")
            if k in f
        },
    }
    nodes = [n for n in (f.get("nodes") or []) if isinstance(n, dict)]
    if nodes:
        return [
            {
                **base,
                "selector": n.get("selector") or None,
                "snippet": n.get("html") or None,
                "fix": _fix_for(f, rule, n),
            }
            for n in nodes
        ]
    selectors = f.get("selectors")
    selector = (
        ", ".join(str(s) for s in selectors)
        if isinstance(selectors, list) and selectors
        else f.get("selector")
    )
    return [
        {
            **base,
            "selector": selector or None,
            "snippet": f.get("text") or None,
            "fix": _fix_for(f, rule, None),
        }
    ]


def _redact_item(item: Item) -> None:
    """Reports are meant to be shared: secret-looking values never appear."""
    item.message = redact_secrets(item.message)
    for name in ("selector", "snippet", "fix"):
        value = getattr(item, name)
        if value:
            setattr(item, name, redact_secrets(value))
    item.details = {
        k: redact_secrets(v) if isinstance(v, str) else v
        for k, v in item.details.items()
    }


def fingerprint_key(item: Item) -> str:
    """What identifies an item besides its rule and file (never a line number)."""
    return _norm(item.selector or item.snippet or item.message)


def rule_titles(items: list[Item]) -> dict[str, str]:
    """Rule id -> short human title (first message seen, or the check title)."""
    titles: dict[str, str] = {}
    for i in items:
        if i.rule not in titles:
            titles[i.rule] = (
                _TITLES.get(i.scanner) if i.scanner == i.rule else None
            ) or i.message
    return titles


def build_report(
    scan: ScanReport,
    root: Path,
    *,
    version: str = "",
    baseline: Any = None,
    ignore_rules: Any = (),
    checks: Any = (),
) -> Report:
    """Turns a pipeline ``ScanReport`` into the presentation-neutral ``Report``.

    ``ignore_rules`` (``[[ignore]]`` of bondy.toml) and inline ``bondy-ignore``
    comments are applied first, then ``baseline`` (a ``baseline.Baseline``):
    an item that is explicitly suppressed is never counted as baselined.
    """
    root = root.resolve()
    scrub = scrubber(root)
    files: list[FileEntry] = []
    items: list[Item] = []
    notes = [redact_secrets(scrub(n)) for n in scan.notes]
    seen: dict[tuple[str, str, str], int] = {}
    indexes: dict[str, PageIndex] = {}

    for r in scan.files:
        rel = relative_path(r.path, root)
        files.append(
            FileEntry(
                path=rel,
                skipped=scrub(r.skipped) if r.skipped else None,
                errors=[redact_secrets(scrub(e)) for e in r.errors],
                omitted=dict(r.omitted),
                reused=r.reused,
            )
        )
        index = PageIndex(r.html) if r.html else None
        if index is not None:
            indexes[rel] = index
        for finding in r.findings:
            if finding.get("count", 0) > len(finding.get("nodes") or []) > 0:
                notes.append(
                    f"{rel}: rule {finding.get('rule')} affects "
                    f"{finding['count']} element(s); the first "
                    f"{len(finding['nodes'])} are listed."
                )
            for d in _expand(finding):
                item = Item(file=rel, **d)
                if item.line is None and index is not None:
                    item.line = index.line_for(
                        item.snippet, item.selector, page_level=item.scanner == "lang"
                    )
                item.message = scrub(item.message)
                key = (item.rule, rel, fingerprint_key(item))
                seen[key] = seen.get(key, 0) + 1
                base = sha256_hex(*key)[:32]
                item.fingerprint = base if seen[key] == 1 else f"{base}~{seen[key]}"
                _redact_item(item)  # after the fingerprint: it hashes raw text
                items.append(item)

    fixes = []
    for fx in scan.fixes:
        d = asdict(fx)
        d["file"] = relative_path(d["file"], root)
        for k in ("title", "before", "after", "explanation"):
            if isinstance(d.get(k), str):
                d[k] = redact_secrets(d[k])
        fixes.append(d)

    # Same problem on the same element reported by several scanners: one item.
    # Before suppressions and baseline, so both act on the merged item (they
    # also see the rules/fingerprints of what was merged into it).
    items, merged = dedupe_items(items, indexes)

    report = Report(
        version=version,
        mode=scan.usage.mode,
        files=files,
        items=items,
        fixes=fixes,
        notes=notes,
        usage=scan.usage,
        static_mode=any(r.omitted for r in scan.files),
        duplicates_merged=merged,
    )
    if ignore_rules or any(
        r.html and "bondy-ignore" in r.html.lower() for r in scan.files
    ):
        from bondy.core.suppress import apply_suppressions

        pages = {relative_path(r.path, root): r.html for r in scan.files if r.html}
        apply_suppressions(report, pages, ignore_rules, checks)
    if baseline is not None:
        from bondy.core.baseline import apply_baseline

        apply_baseline(report, baseline, checks)
    return report
