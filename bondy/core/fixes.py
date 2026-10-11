"""Deterministic fix templates: building ``before``/``after`` for an ``<img>``."""

from __future__ import annotations

import html
import re

from bondy.core.alt_rules import GENERIC_ALT, REDUNDANT_PREFIX
from bondy.core.models import ImageFix, ImageOccurrence, ImageOutcome

_ALT_ATTR = re.compile(r"""(?<![\w:-])alt\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", re.I)
_TAG_END = re.compile(r"(\s*/?>)\s*$")
_SEPARATORS = re.compile(r"^[\s:,\-–—]+|[\s:,\-–—]+$")  # noqa: RUF001 (en/em dash on purpose)


def strip_redundant_prefix(alt: str) -> str | None:
    """ "Image of a dog" -> "A dog". None if nothing meaningful would be left."""
    m = REDUNDANT_PREFIX.match(alt)
    if not m:
        return None
    rest = _SEPARATORS.sub("", alt[m.end() :])
    if not rest or rest.lower().rstrip(".") in GENERIC_ALT:
        return None
    return rest[0].upper() + rest[1:]


def set_alt(tag: str, new_alt: str) -> str:
    """Returns ``tag`` with ``alt`` set to ``new_alt`` (added if absent)."""
    value = html.escape(new_alt, quote=True)
    attr = f'alt="{value}"'
    if _ALT_ATTR.search(tag):
        return _ALT_ATTR.sub(lambda _m: attr, tag, count=1)
    end = _TAG_END.search(tag)
    if not end:
        return tag  # malformed tag: leave untouched
    return tag[: end.start()] + " " + attr + end.group(1)


def build_fix(
    n: int, occ: ImageOccurrence, outcome: ImageOutcome, occurrences: int = 1
) -> ImageFix:
    """Fix for an outcome whose recommendation is ``fix``."""
    assert outcome.recommendation == "fix" and outcome.suggested_alt is not None
    new_alt = outcome.suggested_alt
    if new_alt == "":
        title = "Decorative image should have an empty alt"
    elif outcome.severity == "critical":
        title = "Missing or incorrect alt text"
    else:
        title = "Alt text needs improvement"
    return ImageFix(
        file=occ.file,
        finding_id=f"img-{n:03d}",
        wcag="1.1.1",
        severity=outcome.severity,
        title=title,
        before=occ.tag,
        after=set_alt(occ.tag, new_alt),
        explanation=outcome.reason,
        origin="template" if outcome.origin == "template" else "llm",
        confidence=outcome.confidence,
        safe_to_apply=outcome.origin == "template" or outcome.confidence != "low",
        occurrences=occurrences,
    )
