"""Merging of findings that report the SAME problem on the SAME element.

Several scanners look at one element from different angles: for an unnamed
``<a href="/search"><img src="search.png"></a>`` axe says ``link-name``, the
accessibility-tree check says "role 'link' has no accessible name" and the
HTML check says "<a> has no accessible name". They are one problem to fix, so
the report shows it once and keeps the others as ``merged_from`` (traceability
for JSON/SARIF, ignore comments and baselines).

The rules are deliberately conservative and purely deterministic (no model,
no browser, no dependency on scanner order):

* Only items of the SAME FILE and the SAME problem *family* can merge
  (``_family``). Different natures never merge: contrast vs name, the name of a
  link vs the ``alt`` of the image inside it, focus order, ``region``...
* Two items are "the same element" only when both can be tied to an element
  and the element descriptions agree: the sequence of start tags of their HTML
  snippet (tag + normalized attributes, outer element first; snippets may be
  cut) or, when there is no HTML, the single element a CSS selector designates.
  Anything ambiguous stays separate.
* One group never holds two items of the same rule (two identical elements are
  two problems), and items whose known source lines differ never merge.
* The surviving item is the one with the most actionable context
  (``_score``); it keeps its own fingerprint, takes the worst severity and the
  union of WCAG criteria, and lists the others in ``merged_from`` together with
  their original fingerprints, so existing baselines keep matching.

``dedupe_items`` is a pure function of the items and the page indexes, so it
gives the same result for a fresh scan, ``--changed-only`` and ``--resume``
(the cache stores the raw findings, never the merged ones).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from bondy.core.source import PageIndex, parse_elements

# axe rules that say "this control has no accessible name / label".
_AXE_NAME_RULES = frozenset(
    {
        "link-name",
        "button-name",
        "input-button-name",
        "input-image-alt",
        "label",
        "select-name",
        "summary-name",
        "aria-command-name",
        "aria-input-field-name",
        "aria-meter-name",
        "aria-progressbar-name",
        "aria-toggle-field-name",
        "aria-tooltip-name",
        "aria-treeitem-name",
        "aria-dialog-name",
    }
)
# Bondy's own checks that are the same statement as the axe name rules.
_NAME_SCANNERS = frozenset({"axe-tree", "accessible-name", "labels"})

FAMILY_NAME = "accessible-name"
FAMILY_CONTRAST = "contrast"

_MAX_TAGS = 4  # tags compared per snippet (outer element and a few children)
_SEVERITY_RANK = {"warning": 1, "critical": 2}

Signature = tuple[str, tuple[tuple[str, str], ...]]


def family(item) -> str | None:
    """The problem family an item belongs to (None: never merged)."""
    if item.scanner in _NAME_SCANNERS:
        return FAMILY_NAME
    if item.scanner == "axe":
        if item.rule in _AXE_NAME_RULES:
            return FAMILY_NAME
        if item.rule == "color-contrast":
            return FAMILY_CONTRAST
    if item.scanner == "contrast":
        return FAMILY_CONTRAST
    return None


def tag_signatures(snippet: str | None) -> tuple[Signature, ...]:
    """Start tags (tag + normalized attributes) of an outerHTML snippet.

    Only complete tags count: a snippet cut inside a tag drops that tag.
    Plain text (the contrast checker quotes the element's text) gives ``()``.
    """
    if not snippet:
        return ()
    text = snippet.lstrip()
    if not text.startswith("<"):
        return ()
    end = text.rfind(">")
    if end == -1:
        return ()
    return tuple(e.signature for e in parse_elements(text[: end + 1])[:_MAX_TAGS])


def element_key(item, index: PageIndex | None) -> tuple[Signature, ...] | None:
    """Description of the element an item refers to, or ``None`` if unknown."""
    sigs = tag_signatures(item.snippet)
    if sigs:
        return sigs
    if index is not None and item.selector:
        found = index.by_selector(item.selector)  # [] unless exactly one element
        if found:
            return (found[0].signature,)
    return None


def same_element(a: tuple[Signature, ...], b: tuple[Signature, ...]) -> bool:
    """Descriptions agree on every tag both of them contain (cut snippets)."""
    n = min(len(a), len(b))
    return n > 0 and a[:n] == b[:n]


def _score(item) -> tuple[int, int, int, int]:
    """Actionable context: fix text, selector, snippet, criteria (more = better)."""
    from_node = bool(item.fix) and item.scanner == "axe"
    return (
        int(from_node),
        int(bool(item.selector)) + int(bool(item.snippet)),
        len(item.wcag),
        int(item.line is not None),
    )


@dataclass
class _Group:
    leader: object
    key: tuple[Signature, ...]
    pos: int
    members: list
    rules: set


def _compatible_lines(a, b) -> bool:
    return a.line is None or b.line is None or a.line == b.line


def dedupe_items(
    items: Sequence, indexes: Mapping[str, PageIndex] | None = None
) -> tuple[list, int]:
    """Returns ``(items, merged)``: ``items`` without the duplicates (survivors
    keep their original relative order) and how many items were absorbed.

    Idempotent: running it again on its own output merges nothing.
    """
    indexes = indexes or {}
    candidates: dict[tuple[str, str], list[tuple[int, object, tuple]]] = {}
    for pos, item in enumerate(items):
        fam = family(item)
        if fam is None:
            continue
        key = element_key(item, indexes.get(item.file))
        if key is None:
            continue
        candidates.setdefault((item.file, fam), []).append((pos, item, key))

    absorbed: set[int] = set()
    survivors: dict[int, object] = {}  # position of the leader -> merged item
    merged = 0
    for entries in candidates.values():
        # Total order independent of how scanners were listed: best context
        # first, then more specific snippets, then rule/text, then position.
        ordered = sorted(
            entries,
            key=lambda e: (
                tuple(-v for v in _score(e[1])),
                -len(e[2]),
                e[1].rule,
                e[1].scanner,
                repr(e[2]),
                e[1].message,
                e[0],
            ),
        )
        groups: list[_Group] = []
        for pos, item, key in ordered:
            best: _Group | None = None
            for g in groups:
                if item.rule in g.rules or not _compatible_lines(g.leader, item):
                    continue
                if not same_element(g.key, key):
                    continue
                if best is None or (g.key == key and best.key != key):
                    best = g
            if best is None:
                seen_rules = {item.rule, *(m["rule"] for m in item.merged_from)}
                groups.append(_Group(item, key, pos, [item], seen_rules))
            else:
                best.members.append(item)
                best.rules.update({item.rule, *(m["rule"] for m in item.merged_from)})
                absorbed.add(pos)
                merged += 1
        for g in groups:
            if len(g.members) > 1:
                survivors[g.pos] = _merge(g)

    out = []
    for pos, item in enumerate(items):
        if pos in absorbed:
            continue
        out.append(survivors.get(pos, item))
    return out, merged


def _merge(group: _Group):
    """The leader enriched with what the other members add."""
    leader = group.leader
    others = group.members[1:]
    extra: list[dict[str, str]] = []
    for o in sorted(others, key=lambda o: (o.rule, o.fingerprint)):
        extra.append(
            {
                "scanner": o.scanner,
                "rule": o.rule,
                "message": o.message,
                "fingerprint": o.fingerprint,
            }
        )
        extra.extend(o.merged_from)  # already merged before (flat, no nesting)
    leader.merged_from = [*leader.merged_from, *extra]
    for o in others:
        if _SEVERITY_RANK.get(o.severity, 1) > _SEVERITY_RANK.get(leader.severity, 1):
            leader.severity = o.severity
        for c in o.wcag:
            if c not in leader.wcag:
                leader.wcag.append(c)
        for name in ("selector", "snippet", "line", "fix"):
            if getattr(leader, name) in (None, "") and getattr(o, name):
                setattr(leader, name, getattr(o, name))
        for k, v in o.details.items():
            leader.details.setdefault(k, v)
    leader.wcag = sorted(set(leader.wcag))  # same order whatever the merge order
    return leader
