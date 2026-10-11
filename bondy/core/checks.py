"""Single source of truth for which checks exist and their WCAG mapping.

Scanners (``bondy.scan``), the semantic image stage and the agent-mode prompt
all read from here so the mapping cannot drift between them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CheckSpec:
    """One check Bondy runs. ``wcag`` are success criteria like ``"1.1.1"``."""

    id: str
    wcag: tuple[str, ...]
    title: str
    needs_browser: bool = False
    needs_llm: bool = False
    # Whether the criteria are part of the default "audit everything" request.
    default: bool = True


CHECKS: tuple[CheckSpec, ...] = (
    CheckSpec("axe", (), "axe-core rules (WCAG A/AA)", needs_browser=True),
    CheckSpec("contrast", ("1.4.3",), "Text contrast", needs_browser=True),
    CheckSpec("focus-trap", ("2.1.2",), "Keyboard focus trap", needs_browser=True),
    CheckSpec("focus-order", ("2.4.3",), "Logical focus order", needs_browser=True),
    CheckSpec("lang", ("3.1.1",), "Document language"),
    CheckSpec("labels", ("1.3.1", "4.1.2"), "Form control labels"),
    CheckSpec("accessible-name", ("2.4.4", "4.1.2"), "Links/buttons accessible name"),
    CheckSpec("img-alt", ("1.1.1",), "Missing alt attribute (static)"),
    CheckSpec("alt-text", ("1.1.1",), "Alt text quality (LLM)", needs_llm=True),
)

_BY_ID = {c.id: c for c in CHECKS}

# Criteria requested when nothing is selected, in the order users see them.
# (Kept identical to the list the web API has always sent to the agent.)
ALL_CRITERIA: tuple[str, ...] = (
    "1.1.1",
    "1.3.1",
    "1.4.3",
    "2.4.4",
    "3.1.1",
    "2.1.2",
    "2.4.3",
)


@dataclass(frozen=True)
class CheckGroup:
    """A user-facing category (the web UI's checkboxes) and its WCAG criteria."""

    id: str
    title: str
    criteria: tuple[str, ...]


# The categories the web UI offers. The UI sends these ids; the server resolves
# them here, so the checks -> WCAG mapping lives only in this module.
GROUPS: tuple[CheckGroup, ...] = (
    CheckGroup("images", "Images", ("1.1.1",)),
    CheckGroup("forms", "Forms", ("1.3.1",)),
    CheckGroup("keyboard", "Keyboard focus", ("2.4.4", "2.1.2", "2.4.3")),
    CheckGroup("contrast", "Contrast & structure", ("1.4.3", "3.1.1")),
)
_GROUPS_BY_ID = {g.id: g for g in GROUPS}
_CRITERION = re.compile(r"^(?:wcag\s*)?(\d\.\d\.\d{1,2})$", re.I)


def check_wcag(check_id: str) -> list[str]:
    """WCAG criteria a check maps to (new list each call)."""
    return list(_BY_ID[check_id].wcag)


def all_criteria_instruction() -> str:
    """Sentence telling the agent which criteria to audit when none is chosen."""
    listed = ", ".join(f"WCAG {c}" for c in ALL_CRITERIA)
    return f"Audit all criteria ({listed})."


def resolve_criteria(tokens: list[str] | tuple[str, ...]) -> list[str]:
    """Turns what a client selected into WCAG criteria (``["1.1.1", ...]``).

    Accepts a group id (``"images"``), a check id with a WCAG mapping
    (``"contrast"``) or a criterion (``"WCAG 1.1.1"`` / ``"1.1.1"``). Order of
    first appearance is kept; duplicates are dropped. Raises ``ValueError``
    with the valid options for anything else.
    """
    out: list[str] = []

    def add(values: tuple[str, ...]) -> None:
        for v in values:
            if v not in out:
                out.append(v)

    for raw in tokens:
        token = raw.strip()
        if not token:
            continue
        m = _CRITERION.match(token)
        if m:
            add((m.group(1),))
        elif token.lower() in _GROUPS_BY_ID:
            add(_GROUPS_BY_ID[token.lower()].criteria)
        elif token.lower() in _BY_ID and _BY_ID[token.lower()].wcag:
            add(_BY_ID[token.lower()].wcag)
        else:
            valid = sorted({*_GROUPS_BY_ID, *(c.id for c in CHECKS if c.wcag)})
            raise ValueError(
                f"Unknown check {raw!r}. Use a WCAG criterion (e.g. 'WCAG 1.1.1') "
                f"or one of: {', '.join(valid)}."
            )
    return out


def describe_checks() -> dict[str, list[dict]]:
    """JSON-friendly catalogue served to the web UI (``GET /api/checks``)."""
    return {
        "groups": [
            {
                "id": g.id,
                "title": g.title,
                "criteria": [f"WCAG {c}" for c in g.criteria],
            }
            for g in GROUPS
        ],
        "checks": [
            {
                "id": c.id,
                "title": c.title,
                "wcag": [f"WCAG {w}" for w in c.wcag],
                "needs_browser": c.needs_browser,
                "needs_llm": c.needs_llm,
            }
            for c in CHECKS
        ],
    }


# Value of <meta name="generator"> in Bondy's own HTML report: scans skip such
# files so a report written inside the scanned folder is never audited.
REPORT_GENERATOR = "bondy-report"
