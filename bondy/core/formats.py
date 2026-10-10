"""Renderers: turn a ``Report`` into terminal text, JSON, Markdown, HTML or SARIF.

Renderers only present the model built by ``bondy.core.report``; they derive
nothing from the findings themselves. Every string that originates in the
scanned project is untrusted and is escaped for its medium here:

* HTML: ``html.escape`` on every interpolated value, no script, no remote
  resource, plus a restrictive Content-Security-Policy as defense in depth.
* Markdown: structural characters escaped in prose, untrusted values placed in
  code spans whose fence is longer than any backtick run they contain.
* SARIF/JSON: ``json.dumps`` (strings are data).
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from dataclasses import asdict
from typing import Any

from bondy.core.checks import REPORT_GENERATOR
from bondy.core.report import SEVERITIES, Item, Report, rule_titles

FORMATS = ("terminal", "json", "markdown", "html", "sarif")
SARIF_SCHEMA = (
    "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/"
    "sarif-schema-2.1.0.json"
)
SARIF_FINGERPRINT_KEY = "bondyFingerprint/v1"
_LEVEL = {"critical": "error", "warning": "warning"}


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _t(value: object) -> str:
    """Terminal-safe: control characters (ANSI escapes, CR, ...) become ``?``."""
    return _CONTROL.sub("?", str(value))


def _wcag(item: Item) -> str:
    return ", ".join(item.wcag) if item.wcag else "-"


def _place(item: Item) -> str:
    return f"line {item.line}" if item.line else ""


# ----- terminal -----
def render_usage(u: Any) -> list[str]:
    pages = []
    if u.pages_reused:
        pages = [
            f"Pages: {u.pages_scanned} scanned, {u.pages_reused} reused from the "
            "previous scan (unchanged)"
        ]
    if u.mode == "no-llm":
        return [*pages, "LLM usage: none (deterministic scanners only)."]
    tokens = "not reported"
    if u.input_tokens is not None:
        tilde = "~" if u.tokens_estimated else ""
        tokens = f"{tilde}{u.input_tokens} in / {tilde}{u.output_tokens} out"
    if u.cost_usd is not None:
        cost = f"~${u.cost_usd:.4f} (estimate, with your configured prices)"
    else:
        cost = f"not available ({u.cost_unavailable_reason})"
    lines = [
        *pages,
        "LLM usage:",
        f"  requests: {u.requests} ({u.batches} batch(es))",
        f"  images: {u.images_found} found, {u.images_unique} unique; "
        f"{u.images_verified} verified by the model, {u.images_by_template} resolved "
        f"in code, {u.images_manual_review} for manual review, "
        f"{u.images_skipped} skipped",
        f"  tokens: {tokens}",
        f"  cost: {cost}",
    ]
    if u.cache_enabled:
        lines.append(
            f"  cache: {u.cache_hits} hit(s), {u.cache_misses} miss(es), "
            f"{u.cache_writes} saved"
        )
    else:
        lines.append("  cache: disabled")
    if u.request_limit is not None:
        origin = (
            "default; --max-requests N to change, 0 for no limit"
            if u.request_limit_is_default
            else "--max-requests"
        )
        lines.append(f"  request limit: {u.request_limit} ({origin})")
    return lines


def _sup_where(s: Any) -> str:
    where = f"{s.file}:{s.line}" if s.line else s.file
    return f"{where} ({s.source})"


def render_summary(report: Report) -> list[str]:
    """Terminal block: totals, baseline, suppressions, pages, next step."""
    sm = report.summary()
    new, pages = sm["findings"]["new"], sm["pages"]
    lines = [
        "",
        "Summary",
        f"  New findings: {new['total']} ({new['critical']} critical, "
        f"{new['warning']} warning)",
    ]
    if report.baseline:
        b = report.baseline
        extra = f", {b.not_evaluated} not re-evaluated" if b.not_evaluated else ""
        lines.append(
            f"  Baseline ({_t(b.file)}): {b.matched} known finding(s) hidden, "
            f"{b.resolved} resolved{extra}"
        )
    lines.append(
        f"  Suppressed by ignore rules: {sm['findings']['suppressed']}"
        f" ({sm['suppressions']['applied']} rule(s) applied, "
        f"{sm['suppressions']['obsolete']} obsolete)"
    )
    lines.append(
        f"  Pages: {pages['scanned']} scanned, {pages['reused']} reused from the "
        f"previous scan, {pages['skipped']} skipped"
    )
    applied = [s for s in report.suppressions if s.status == "applied"]
    if applied:
        lines += ["", "Suppressions applied:"]
        lines += [
            f"  - {_t(s.rule)} at {_t(_sup_where(s))}: {s.matched} finding(s); "
            f"reason: {_t(s.reason)}"
            for s in applied
        ]
    obsolete = [s for s in report.suppressions if s.status == "obsolete"]
    if obsolete:
        lines += ["", "Obsolete suppressions (they match nothing; remove them):"]
        lines += [
            f"  - {_t(s.rule)} at {_t(_sup_where(s))}"
            + (f": {_t(s.detail)}" if s.detail else "")
            for s in obsolete
        ]
    if report.baseline and report.baseline.resolved_items:
        lines += ["", "Resolved since the baseline was created:"]
        for r in report.baseline.resolved_items[:10]:
            lines.append(f"  - {_t(r['file'])}: {_t(r['rule'])}")
        extra_n = len(report.baseline.resolved_items) - 10
        if extra_n > 0:
            lines.append(f"  ... and {extra_n} more")
    return lines


def render_terminal(report: Report) -> str:
    by_file: dict[str, list[Item]] = {}
    for item in report.new_items:
        by_file.setdefault(item.file, []).append(item)
    lines: list[str] = []
    for f in report.files:
        lines.append(_t(f.path))
        if f.skipped:
            lines.append(f"  skipped: {_t(f.skipped)}")
        if f.reused:
            lines.append("  (unchanged: result reused from the previous scan)")
        lines.extend(f"  ERROR {_t(e)}" for e in f.errors)
        for i in by_file.get(f.path, []):
            lines.append(
                f"  [{i.severity:<8}] {_t(i.scanner):<15} WCAG {_t(_wcag(i))}: "
                f"{_t(i.message)}"
            )
            where = " ".join(
                p
                for p in (i.selector and f"selector: {_t(i.selector)}", _place(i))
                if p
            )
            if where:
                lines.append(f"      {where}")
    lines.append("")
    lines.append(
        f"{len(report.files)} file(s) scanned, {len(report.new_items)} finding(s)."
    )
    lines.extend(f"note: {_t(n)}" for n in report.notes)
    lines.extend(render_summary(report))
    usage = render_usage(report.usage)
    if usage:
        lines += ["", *usage]
    if report.partial:
        lines.append("PARTIAL RESULT: " + _t("; ".join(report.usage.partial_reasons)))
    lines += ["", f"Next step: {report.next_step()}"]
    return "\n".join(lines)


# ----- JSON -----
def _item_dict(i: Item) -> dict[str, Any]:
    d: dict[str, Any] = {
        "scanner": i.scanner,
        "rule": i.rule,
        "wcag": i.wcag,
        "severity": i.severity,
        "message": i.message,
        "selector": i.selector,
        "snippet": i.snippet,
        "line": i.line,
        "fix": i.fix,
        "fingerprint": i.fingerprint,
    }
    d.update(i.details)
    return d


def to_json_dict(report: Report, exit_code: int) -> dict[str, Any]:
    return {
        "version": report.version,
        "mode": report.mode,
        "exit_code": exit_code,
        "static_mode": report.static_mode,
        "notes": report.notes,
        "usage": report.usage.as_dict(),
        "summary": report.summary(),
        "baseline": asdict(report.baseline) if report.baseline else None,
        "suppressions": [asdict(x) for x in report.suppressions],
        "suppressed": [
            {**_item_dict(i), "file": i.file, "suppressed_by": i.suppressed_by}
            for i in report.suppressed_items
        ],
        "fixes": report.fixes,
        "files": [
            {
                "path": f.path,
                "skipped": f.skipped,
                "errors": f.errors,
                "omitted_checks": f.omitted,
                "reused": f.reused,
                "findings": [
                    _item_dict(i) for i in report.new_items if i.file == f.path
                ],
            }
            for f in report.files
        ],
    }


def render_json(report: Report, exit_code: int) -> str:
    return json.dumps(to_json_dict(report, exit_code), indent=2, ensure_ascii=False)


# ----- Markdown -----
_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>|#~&!])")


def md_text(value: object) -> str:
    """Prose-safe: no markup, links, HTML or table breaks survive."""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return _MD_SPECIAL.sub(r"\\\1", text)


def md_code(value: object) -> str:
    """Inline code span that cannot be closed by the content."""
    text = re.sub(r"\s+", " ", str(value)).strip() or "(empty)"
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text[0] in "` " or text[-1] in "` " else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def render_markdown(report: Report, exit_code: int) -> str:
    new = report.new_items
    counts = report.count_by_severity()
    out = [
        "# Bondy accessibility report",
        "",
        f"- Bondy version: {md_text(report.version or 'unknown')}",
        f"- Mode: {md_text(report.mode)}",
        f"- Files scanned: {len(report.files)}",
        f"- New findings: {len(new)}",
        f"- Exit code: {exit_code}",
    ]
    if report.partial:
        out.append(
            f"- **Partial result:** {md_text('; '.join(report.usage.partial_reasons))}"
        )
    out += ["", "## Summary", "", "| Severity | Findings |", "| --- | ---: |"]
    out += [f"| {s} | {counts.get(s, 0)} |" for s in SEVERITIES]
    out += [f"| **Total** | {len(new)} |", ""]
    sm = report.summary()
    out += [
        f"- Suppressed by ignore rules: {sm['findings']['suppressed']}",
        f"- Hidden by the baseline: {sm['findings']['baselined']}",
        f"- Pages: {sm['pages']['scanned']} scanned, {sm['pages']['reused']} "
        f"reused, {sm['pages']['skipped']} skipped",
        "",
    ]
    if report.baseline:
        b = report.baseline
        out += [
            "## Baseline",
            "",
            f"- File: {md_code(b.file)}",
            f"- Known findings hidden: {b.matched}",
            f"- Resolved since it was created: {b.resolved}",
            f"- Not re-evaluated in this run: {b.not_evaluated}",
            "",
        ]
    sups = [x for x in report.suppressions if x.status in ("applied", "obsolete")]
    if sups:
        out += ["## Suppressions", ""]
        for x in sups:
            tag = "obsolete (matches nothing)" if x.status == "obsolete" else "applied"
            out.append(
                f"- {md_code(x.rule)} at {md_code(_sup_where(x))}: {tag}; "
                f"{x.matched} finding(s); reason: {md_text(x.reason)}"
            )
        out.append("")
    if report.notes:
        out += ["## Notes", ""]
        out += [f"- {md_text(n)}" for n in report.notes] + [""]

    out += ["## Findings", ""]
    if not new and not any(f.errors or f.skipped for f in report.files):
        out += ["No new findings.", ""]
    for f in report.files:
        file_items = [i for i in new if i.file == f.path]
        if not (file_items or f.errors or f.skipped):
            continue
        out += [f"### {md_code(f.path)}", ""]
        if f.skipped:
            out += [f"- Skipped: {md_text(f.skipped)}"]
        out += [f"- **Error:** {md_text(e)}" for e in f.errors]
        for i in file_items:
            out += [
                f"#### {i.severity.capitalize()}: {md_code(i.rule)}",
                "",
                f"- WCAG: {md_text(_wcag(i))}",
                f"- Rule: {md_code(i.rule)} ({md_text(i.scanner)})",
                f"- Message: {md_text(i.message)}",
            ]
            if i.selector:
                out.append(f"- Selector: {md_code(i.selector)}")
            if i.line:
                out.append(f"- Line: {i.line}")
            if i.snippet:
                out.append(f"- Snippet: {md_code(i.snippet)}")
            if i.fix:
                out.append(f"- Suggested fix: {md_text(i.fix)}")
            out.append("")
    out += ["## Next step", "", md_text(report.next_step()), ""]
    return "\n".join(out).rstrip() + "\n"


# ----- HTML -----
_CSS = """
:root{color-scheme:light dark;--bg:#fff;--fg:#1b1b1b;--muted:#4a4a4a;--line:#c8c8c8;
--crit:#a30000;--warn:#7a4a00;--code:#f1f1f1}
@media (prefers-color-scheme:dark){:root{--bg:#121212;--fg:#ececec;--muted:#c4c4c4;
--line:#555;--crit:#ff9c9c;--warn:#ffd28a;--code:#262626}}
body{margin:0;padding:1rem 1rem 3rem;background:var(--bg);color:var(--fg);
font:1rem/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main,header,footer{max-width:60rem;margin:0 auto}
h1,h2,h3{line-height:1.25}
a{color:inherit}
.skip{position:absolute;left:-999px}.skip:focus{position:static}
table{border-collapse:collapse;width:100%;margin:1rem 0}
th,td{border:1px solid var(--line);padding:.4rem .6rem;text-align:left}
code,pre{background:var(--code);border-radius:3px}
code{padding:0 .2rem;overflow-wrap:anywhere}
pre{padding:.6rem;white-space:pre-wrap;overflow-wrap:anywhere}
ul.findings{list-style:none;padding:0}
ul.findings>li{border:1px solid var(--line);border-radius:6px;margin:.8rem 0;padding:.6rem .9rem}
dl{margin:.4rem 0}dt{font-weight:600}dd{margin:0 0 .4rem 0}
.sev{font-weight:700}.sev-critical{color:var(--crit)}.sev-warning{color:var(--warn)}
.muted{color:var(--muted)}
:focus-visible{outline:3px solid currentColor;outline-offset:2px}
""".strip()


def render_html(report: Report, exit_code: int) -> str:
    e = html.escape  # quote=True: safe in text and in attribute values
    new = report.new_items
    counts = report.count_by_severity()
    p: list[str] = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<meta name="generator" content="{REPORT_GENERATOR}">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'\">",
        "<title>Bondy accessibility report</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        '<a class="skip" href="#findings">Skip to findings</a>',
        "<header>",
        "<h1>Bondy accessibility report</h1>",
        f'<p class="muted">Bondy {e(report.version or "unknown")}, mode '
        f"{e(report.mode)}. {len(report.files)} file(s) scanned, "
        f"{len(new)} new finding(s). Exit code {exit_code}.</p>",
        "</header>",
        '<main id="main">',
    ]
    if report.partial:
        p.append(
            '<p role="status"><strong>Partial result:</strong> '
            f"{e('; '.join(report.usage.partial_reasons))}</p>"
        )
    p += [
        '<section aria-labelledby="summary-h">',
        '<h2 id="summary-h">Summary</h2>',
        "<table>",
        "<caption>New findings by severity</caption>",
        '<thead><tr><th scope="col">Severity</th>'
        '<th scope="col">Findings</th></tr></thead>',
        "<tbody>",
    ]
    for s in SEVERITIES:
        p.append(f'<tr><th scope="row">{e(s)}</th><td>{counts.get(s, 0)}</td></tr>')
    p += [
        f'<tr><th scope="row">Total</th><td>{len(new)}</td></tr>',
        "</tbody></table>",
        "</section>",
    ]
    sm = report.summary()
    p.append(
        f"<p>Suppressed by ignore rules: {sm['findings']['suppressed']}. Hidden by "
        f"the baseline: {sm['findings']['baselined']}. Pages: "
        f"{sm['pages']['scanned']} scanned, {sm['pages']['reused']} reused, "
        f"{sm['pages']['skipped']} skipped.</p>"
    )
    if report.baseline:
        b = report.baseline
        p.append(
            f"<p>Baseline <code>{e(b.file)}</code>: {b.matched} known finding(s) "
            f"hidden, {b.resolved} resolved, {b.not_evaluated} not re-evaluated.</p>"
        )
    sups = [x for x in report.suppressions if x.status in ("applied", "obsolete")]
    if sups:
        p += ['<h3 id="sup-h">Suppressions</h3>', "<ul>"]
        for x in sups:
            tag = "obsolete (matches nothing)" if x.status == "obsolete" else "applied"
            p.append(
                f"<li><code>{e(x.rule)}</code> at <code>{e(_sup_where(x))}</code>: "
                f"{tag}; {x.matched} finding(s); reason: {e(x.reason)}</li>"
            )
        p.append("</ul>")
    p.append(f"<p><strong>Next step:</strong> {e(report.next_step())}</p>")
    if report.notes:
        p += ['<section aria-labelledby="notes-h">', '<h2 id="notes-h">Notes</h2><ul>']
        p += [f"<li>{e(n)}</li>" for n in report.notes]
        p += ["</ul></section>"]

    p += ['<section id="findings" aria-labelledby="findings-h">']
    p += ['<h2 id="findings-h">Findings</h2>']
    shown = False
    for f in report.files:
        file_items = [i for i in new if i.file == f.path]
        if not (file_items or f.errors or f.skipped):
            continue
        shown = True
        p.append(f"<h3><code>{e(f.path)}</code></h3>")
        if f.skipped:
            p.append(f"<p>Skipped: {e(f.skipped)}</p>")
        p += [f"<p><strong>Error:</strong> {e(x)}</p>" for x in f.errors]
        if file_items:
            p.append('<ul class="findings">')
        for i in file_items:
            p.append("<li>")
            p.append(
                f'<p><span class="sev sev-{e(i.severity)}">{e(i.severity.capitalize())}'
                f"</span>: <code>{e(i.rule)}</code></p>"
            )
            p.append(f"<p>{e(i.message)}</p><dl>")
            p.append(f"<dt>WCAG</dt><dd>{e(_wcag(i))}</dd>")
            if i.selector:
                p.append(f"<dt>Selector</dt><dd><code>{e(i.selector)}</code></dd>")
            if i.line:
                p.append(f"<dt>Line</dt><dd>{i.line}</dd>")
            if i.snippet:
                p.append(
                    f"<dt>Snippet</dt><dd><pre><code>{e(i.snippet)}</code></pre></dd>"
                )
            if i.fix:
                p.append(f"<dt>Suggested fix</dt><dd>{e(i.fix)}</dd>")
            p.append("</dl></li>")
        if file_items:
            p.append("</ul>")
    if not shown:
        p.append("<p>No new findings.</p>")
    p += [
        "</section>",
        "</main>",
        "<footer>",
        '<p class="muted">Generated by Bondy.</p>',
    ]
    p += ["</footer>", "</body>", "</html>"]
    return "\n".join(p) + "\n"


# ----- SARIF 2.1.0 -----
def _uri(path: str, prefix: str) -> str:
    joined = f"{prefix.strip('/')}/{path}" if prefix.strip("/") else path
    return urllib.parse.quote(joined, safe="/")


def to_sarif_dict(report: Report, exit_code: int, prefix: str = "") -> dict[str, Any]:
    items = report.new_items
    titles = rule_titles(items)
    rule_ids = sorted({i.rule for i in items})
    rules = []
    for rid in rule_ids:
        sample = next(i for i in items if i.rule == rid)
        rules.append(
            {
                "id": rid,
                "name": rid,
                "shortDescription": {"text": titles[rid]},
                "defaultConfiguration": {
                    "level": _LEVEL.get(sample.severity, "warning")
                },
                "properties": {
                    "tags": ["accessibility"]
                    + [
                        f"wcag-{c}"
                        for c in sorted(
                            {c for i in items if i.rule == rid for c in i.wcag}
                        )
                    ]
                },
            }
        )
    results = []
    for i in items:
        physical: dict[str, Any] = {
            "artifactLocation": {"uri": _uri(i.file, prefix), "uriBaseId": "%SRCROOT%"}
        }
        if i.line:
            physical["region"] = {"startLine": i.line}
        props: dict[str, Any] = {"scanner": i.scanner, "wcag": i.wcag}
        for key, value in (
            ("selector", i.selector),
            ("snippet", i.snippet),
            ("fix", i.fix),
        ):
            if value:
                props[key] = value
        results.append(
            {
                "ruleId": i.rule,
                "ruleIndex": rule_ids.index(i.rule),
                "level": _LEVEL.get(i.severity, "warning"),
                "message": {"text": i.message or i.rule},
                "locations": [{"physicalLocation": physical}],
                "partialFingerprints": {SARIF_FINGERPRINT_KEY: i.fingerprint},
                "properties": props,
            }
        )
    notifications = [
        {"level": "error", "message": {"text": f"{f.path}: {err}"}}
        for f in report.files
        for err in f.errors
    ] + [{"level": "note", "message": {"text": n}} for n in report.notes]
    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Bondy",
                        "version": report.version or "unknown",
                        "rules": rules,
                    }
                },
                "results": results,
                "properties": {
                    "bondy": {
                        "baselined": len(report.baselined_items),
                        "suppressed": len(report.suppressed_items),
                        "summary": report.summary(),
                    }
                },
                "invocations": [
                    {
                        "executionSuccessful": not report.has_errors,
                        "exitCode": exit_code,
                        "toolExecutionNotifications": notifications,
                    }
                ],
            }
        ],
    }


def render_sarif(report: Report, exit_code: int, prefix: str = "") -> str:
    return json.dumps(
        to_sarif_dict(report, exit_code, prefix), indent=2, ensure_ascii=False
    )


def render(fmt: str, report: Report, exit_code: int, *, sarif_prefix: str = "") -> str:
    """Report text in ``fmt`` (one of ``FORMATS``)."""
    if fmt == "json":
        return render_json(report, exit_code)
    if fmt == "markdown":
        return render_markdown(report, exit_code)
    if fmt == "html":
        return render_html(report, exit_code)
    if fmt == "sarif":
        return render_sarif(report, exit_code, sarif_prefix)
    return render_terminal(report)
