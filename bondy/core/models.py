"""Data contracts between pipeline stages (plain dataclasses, JSON-friendly)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Recommendation = Literal["keep", "fix", "needs_manual_review", "skipped"]
Classification = Literal["decorative", "informative", "functional"]


@dataclass
class ImageOccurrence:
    """One ``<img>`` found in a page (input of the semantic stage)."""

    file: str
    line: int
    tag: str  # exact source text of the tag (used as the fix's "before")
    src: str | None
    alt: str | None  # None = attribute absent
    context: str  # short HTML slice around the tag (untrusted data)
    lang: str = ""  # page <html lang>, may be empty
    page_dir: str = ""  # directory of the page (relative src resolution)
    root_dir: str = ""  # project root (root-relative src and containment)


@dataclass
class ImageOutcome:
    """Decision for one occurrence."""

    file: str
    line: int
    src: str | None
    tag: str
    current_alt: str | None
    recommendation: Recommendation
    classification: Classification | None = None
    suggested_alt: str | None = None
    confidence: str | None = None
    static_problems: list[str] = field(default_factory=list)
    reason: str = ""  # why manual review / skipped, or why a fix
    severity: Literal["critical", "warning"] = "warning"
    origin: Literal["template", "llm", "none"] = "none"


@dataclass
class ImageFix:
    """A concrete before/after patch for one image tag."""

    file: str
    finding_id: str
    wcag: str
    severity: Literal["critical", "warning"]
    title: str
    before: str
    after: str
    explanation: str
    origin: Literal["template", "llm"]
    confidence: str | None
    # Never auto-apply a fix that came from a low-confidence judgement.
    safe_to_apply: bool
    occurrences: int = 1  # identical tags in the file


@dataclass
class UsageSummary:
    """What a scan spent. ``requests`` counts every HTTP attempt (retries too)."""

    mode: str = "no-llm"
    requests: int = 0
    batches: int = 0
    images_found: int = 0
    images_unique: int = 0
    images_verified: int = 0  # judged by the LLM
    images_by_template: int = 0  # resolved in code, no LLM
    images_manual_review: int = 0
    images_skipped: int = 0  # not processed (limit / quota)
    input_tokens: int | None = None
    output_tokens: int | None = None
    tokens_estimated: bool = False
    # None when no prices are configured (then cost_unavailable_reason says why)
    cost_usd: float | None = None
    cost_unavailable_reason: str | None = None
    cost_is_estimate: bool = True
    request_limit: int | None = None
    request_limit_is_default: bool = False
    partial: bool = False
    partial_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanReport:
    """Result of the whole pipeline."""

    files: list[Any]  # list[bondy.scan.FileResult]
    images: list[ImageOutcome] = field(default_factory=list)
    fixes: list[ImageFix] = field(default_factory=list)
    usage: UsageSummary = field(default_factory=UsageSummary)
    notes: list[str] = field(default_factory=list)

    @property
    def partial(self) -> bool:
        return self.usage.partial
