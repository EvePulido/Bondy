"""Versionable suppressions (E4): inline comments and ``[[ignore]]`` entries.

Two forms, both REQUIRING a reason:

* in the HTML, applied to the element that follows the comment::

      <!-- bondy-ignore: image-alt, 1.4.3 -- decorative logo, text is adjacent -->
      <img src="logo.png">

* in ``bondy.toml``::

      [[ignore]]
      path = "legacy/**"
      rule = "color-contrast"
      reason = "legacy pages are being retired in Q3"

``rule`` is a rule id (axe rule or Bondy check name) or a WCAG criterion
(``1.4.3`` / ``WCAG 1.4.3``). Applied suppressions are listed with their
reason in every report; ones that match nothing are reported as obsolete.
"""

from __future__ import annotations

import re

from bondy.config import ConfigError, IgnoreRule, normalize_rule_token
from bondy.core.redact import redact_secrets
from bondy.core.report import Item, Report, Suppression
from bondy.core.source import ElementCollector, PageIndex
from bondy.scan import _matches

_INLINE = re.compile(r"^\s*bondy-ignore\b(.*)$", re.DOTALL | re.IGNORECASE)
_FULL = re.compile(r"^\s*:\s*(?P<rules>.+?)\s+--\s+(?P<reason>\S.*?)\s*$", re.DOTALL)
SYNTAX = "<!-- bondy-ignore: <rule|wcag>[, ...] -- <reason> -->"


class Directive:
    """One ``bondy-ignore`` comment and the element it is attached to."""

    def __init__(self, line: int, rules: list[str], reason: str):
        self.line = line
        self.rules = rules
        self.reason = reason
        self.target = None  # Element | None (None: no element follows)


class _Parser(ElementCollector):
    def __init__(self) -> None:
        super().__init__()
        self.directives: list[Directive] = []
        self.problems: list[str] = []
        self._bondy_pending: list[Directive] = []

    def handle_comment(self, data: str) -> None:
        m = _INLINE.match(data)
        if not m:
            return
        line = self.getpos()[0]
        full = _FULL.match(m.group(1))
        if not full:
            self.problems.append(
                f"line {line}: a bondy-ignore comment needs a rule and a reason. "
                f"Use {SYNTAX}"
            )
            return
        try:
            rules = [
                normalize_rule_token(t, f"line {line}")
                for t in full.group("rules").split(",")
            ]
        except ConfigError as e:
            self.problems.append(str(e))
            return
        d = Directive(line, rules, re.sub(r"\s+", " ", full.group("reason")))
        self.directives.append(d)
        self._bondy_pending.append(d)

    def handle_starttag(self, tag, attrs):
        before = len(self.elements)
        super().handle_starttag(tag, attrs)
        if self._bondy_pending and len(self.elements) > before:
            for d in self._bondy_pending:
                d.target = self.elements[-1]
            self._bondy_pending = []


def parse_directives(html: str) -> tuple[list[Directive], list[str]]:
    """Inline directives of a page and the problems found (missing reason...)."""
    parser = _Parser()
    parser.feed(html)
    parser.close()
    return parser.directives, parser.problems


def check_inline_syntax(pages: dict[str, str]) -> None:
    """Raises ``ConfigError`` listing every malformed inline directive."""
    problems = [
        f"  {rel}: {p}"
        for rel, html in pages.items()
        if "bondy-ignore" in html.lower()
        for p in parse_directives(html)[1]
    ]
    if problems:
        raise ConfigError(
            "invalid bondy-ignore comment(s); every suppression needs a rule "
            f"and a reason ({SYNTAX}):\n" + "\n".join(problems)
        )


def _token_matches(token: str, item: Item) -> bool:
    if re.fullmatch(r"\d\.\d\.\d{1,2}", token):
        return token in {c.removeprefix("WCAG").strip() for c in item.wcag}
    # a finding merged into this one (same problem, other scanner) counts too:
    # `bondy-ignore: accessible-name` keeps silencing it after the merge
    return token in {r.lower() for r in item.all_rules()}


def apply_suppressions(
    report: Report,
    pages: dict[str, str],
    ignore_rules: tuple[IgnoreRule, ...] | list[IgnoreRule] = (),
    checks=(),
) -> None:
    """Marks suppressed items and records every suppression's outcome."""
    indexes: dict[str, PageIndex] = {}
    sups: list[tuple[Suppression, Directive | None, IgnoreRule | None]] = []
    for rel, html in pages.items():
        if "bondy-ignore" not in html.lower():
            continue
        directives, _ = parse_directives(html)
        indexes[rel] = PageIndex(html)
        for d in directives:
            for token in d.rules:
                s = Suppression(
                    "comment", rel, token, redact_secrets(d.reason), line=d.line
                )
                sups.append((s, d, None))
    for r in ignore_rules:
        s = Suppression("config", r.path, r.rule, r.reason)
        sups.append((s, None, r))

    for item in report.items:
        for sup, directive, rule in sups:
            if not _token_matches(sup.rule, item):
                continue
            if directive is not None:
                if sup.file != item.file or directive.target is None:
                    continue
                idx = indexes[item.file]
                cands = idx.candidates(item.snippet, item.selector)
                page_level = not item.snippet and not item.selector
                hit = directive.target in cands or (
                    page_level and directive.target.tag == "html"
                )
            else:
                hit = rule is not None and _matches(item.file, rule.path)
            if not hit:
                continue
            sup.matched += 1
            if item.status == "new":
                item.status = "suppressed"
                item.suppressed_by = {
                    "source": sup.source,
                    "file": sup.file,
                    "line": sup.line,
                    "rule": sup.rule,
                    "reason": sup.reason,
                }
    wanted = bool([c for c in checks if c.strip()])
    for sup, directive, rule in sups:
        _classify(report, sup, directive, rule, wanted)
        report.suppressions.append(sup)


def _evaluable(report: Report, path: str) -> bool:
    f = next((x for x in report.files if x.path == path), None)
    return f is not None and not (f.skipped or f.errors or f.omitted)


def _classify(report, sup, directive, rule, checks_filtered: bool) -> None:
    if sup.matched:
        sup.status = "applied"
        return
    sup.status = "unverified"
    if checks_filtered or report.partial:
        return
    if sup.rule == "alt-text" and report.mode != "llm":
        sup.detail = "alt-text findings need the model; not evaluated in this run"
        return
    if directive is not None:
        if directive.target is None:
            sup.status, sup.detail = "obsolete", "no element follows the comment"
        elif _evaluable(report, sup.file):
            sup.status = "obsolete"
            sup.detail = "no finding for that element and rule"
        return
    files = [f.path for f in report.files if rule and _matches(f.path, rule.path)]
    if not files:
        sup.status, sup.detail = "obsolete", "the path pattern matches no scanned file"
    elif all(_evaluable(report, p) for p in files):
        sup.status, sup.detail = "obsolete", "no finding matched path and rule"
