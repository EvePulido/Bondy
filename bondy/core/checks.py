"""Single source of truth for which checks exist and their WCAG mapping.

Scanners (``bondy.scan``), the semantic image stage and the agent-mode prompt
all read from here so the mapping cannot drift between them.
"""

from __future__ import annotations

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


def check_wcag(check_id: str) -> list[str]:
    """WCAG criteria a check maps to (new list each call)."""
    return list(_BY_ID[check_id].wcag)


def all_criteria_instruction() -> str:
    """Sentence telling the agent which criteria to audit when none is chosen."""
    listed = ", ".join(f"WCAG {c}" for c in ALL_CRITERIA)
    return f"Audit all criteria ({listed})."


# Value of <meta name="generator"> in Bondy's own HTML report: scans skip such
# files so a report written inside the scanned folder is never audited.
REPORT_GENERATOR = "bondy-report"
