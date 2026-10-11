"""Semantic stage for images: batching, one fused verify+classify call per batch.

Code decides everything it can (heuristics, static alt checks, templates, the
final recommendation); the model only judges what the image shows, whether it
is decorative/informative/functional and drafts the alt text. HTML and alt
strings are untrusted data: they are delimited, size-limited, and the model's
answer is validated against a schema before anything uses it.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ValidationError

from bondy.core.alt_rules import (
    ALT_SYSTEM_RULES,
    REDUNDANT_PREFIX,
    AltVerdict,
    alt_text_static_checks,
    decide_alt_recommendation,
    decorative_heuristics,
)
from bondy.core.budget import (
    OUTPUT_TOKENS_PER_IMAGE,
    OVERHEAD_OUTPUT_TOKENS,
    UsageTracker,
    estimate_text_tokens,
)
from bondy.core.fixes import strip_redundant_prefix
from bondy.core.images import (
    ImageLoader,
    ImageLoadError,
    LoadedImage,
    source_key,
)
from bondy.core.models import ImageOccurrence, ImageOutcome
from bondy.core.providers.base import (
    LLMProvider,
    LLMRequest,
    MediaPart,
    ProviderError,
)
from bondy.core.redact import redact_secrets
from bondy.core.store import Store, sha256_hex

# Bump when ALT_SYSTEM_RULES/BATCH_RULES or the schema change (cache key, B4).
PROMPT_VERSION = "alt-batch-1"
DEFAULT_BATCH_SIZE = 8
# Inline image data share one request: stay well under the provider's ceiling
# (about 20 MB per request for Gemini inline data; not verified live).
MAX_BATCH_BYTES = 15 * 1024 * 1024
CONTEXT_FOR_MODEL_CHARS = 600
ALT_FOR_MODEL_CHARS = 500

BATCH_RULES = (
    ALT_SYSTEM_RULES
    + """
BATCH FORMAT:
- You receive several images. Each starts with a marker [IMAGE index=N] followed by the image and its untrusted data: <current_alt> (present="false" means the attribute is absent), <page_lang>, <signals> and <html_context>.
- Return ONE object per image in "results", copying its index. Do not skip images.
- classification: "decorative" = adds no information (ornament, spacer, redundant with adjacent text) -> alt must be empty; "informative" = conveys content; "functional" = it is the only content of a link/button -> suggested_alt must describe the action or destination (use the href), not the picture.
- For a decorative image set suggested_alt to "".
- Write suggested_alt in the language of <page_lang> when current_alt is empty or absent.
"""
)


class ImageAnalysis(BaseModel):
    """What the model must say about one image of the batch."""

    index: int
    visible_content: str
    matches_current_alt: Literal["yes", "partially", "no"]
    classification: Literal["decorative", "informative", "functional"]
    suggested_alt: str
    confidence: Literal["high", "medium", "low"]
    uncertain_details: list[str]


class BatchAnalysis(BaseModel):
    results: list[ImageAnalysis]


# Changes whenever the prompt text, its version or the output schema change, so
# cached verdicts made under another prompt/schema are never reused (B4).
PROMPT_FINGERPRINT = sha256_hex(
    PROMPT_VERSION,
    BATCH_RULES,
    json.dumps(BatchAnalysis.model_json_schema(), sort_keys=True),
)[:16]


# ----- Groups: unique (image, alt) pairs -----
@dataclass
class Group:
    key: tuple[str, str | None]
    occurrences: list[ImageOccurrence]
    positions: list[int] = field(default_factory=list)  # index in the page list
    image: LoadedImage | None = None
    analysis: ImageAnalysis | None = None
    failure: str | None = None  # why it could not be verified (manual review)
    skipped: str | None = None  # why it was not processed (limit/quota)
    transient: bool = False  # failure may not repeat (provider/network)
    cache_key: str | None = None
    from_cache: bool = False


@dataclass
class StageResult:
    """Output of the semantic stage (one outcome per occurrence, same order)."""

    outcomes: list[ImageOutcome]
    partial_reasons: list[str] = field(default_factory=list)
    unique: int = 0
    verified: int = 0  # judged by the model
    by_template: int = 0  # resolved in code
    manual_review: int = 0
    skipped: int = 0
    batches: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_writes: int = 0


# ----- Deterministic part -----
def _neutralize(text: str, limit: int) -> str:
    """Truncates and defuses our own delimiters inside untrusted text."""
    text = text[:limit]
    text = re.sub(
        r"<(/?)(current_alt|html_context|page_lang|signals)\b",
        r"<\1_\2",
        text,
        flags=re.I,
    )
    return text.replace("[IMAGE", "[ IMAGE")


def _outcome(occ: ImageOccurrence, recommendation: str, **kw) -> ImageOutcome:
    return ImageOutcome(
        file=occ.file,
        line=occ.line,
        src=occ.src,
        tag=occ.tag,
        current_alt=occ.alt,
        recommendation=recommendation,  # type: ignore[arg-type]
        static_problems=alt_text_static_checks(occ.alt),
        **kw,
    )


def resolve_deterministic(occ: ImageOccurrence) -> ImageOutcome | None:
    """Decides without the model when an explicit signal settles it."""
    heur = decorative_heuristics(occ.tag, occ.context)
    if heur["verdict"] != "decorative":
        return None
    signals = ", ".join(heur["signals"])
    if occ.alt is not None and occ.alt.strip() == "":
        return _outcome(
            occ,
            "keep",
            classification="decorative",
            origin="template",
            reason=f"decorative ({signals}); alt is already empty",
        )
    return _outcome(
        occ,
        "fix",
        classification="decorative",
        suggested_alt="",
        origin="template",
        severity="warning",
        reason=f"decorative image ({signals}): alt must be empty",
    )


def fallback_outcome(
    occ: ImageOccurrence, reason: str, transient: bool = False
) -> ImageOutcome:
    """Image could not be verified: template fix if the alt text alone allows it."""
    static = alt_text_static_checks(occ.alt)
    if occ.alt and "redundant_prefix" in static:
        cleaned = strip_redundant_prefix(occ.alt)
        if cleaned:
            return _outcome(
                occ,
                "fix",
                suggested_alt=cleaned,
                origin="template",
                severity="warning",
                reason=(
                    "redundant prefix removed (wording only; the image itself "
                    f"was not verified: {reason})"
                ),
            )
    return _outcome(
        occ,
        "needs_manual_review",
        reason=f"could not verify the image: {reason}",
        transient=transient,
    )


def decide(occ: ImageOccurrence, a: ImageAnalysis) -> ImageOutcome:
    """Final recommendation for one occurrence, made in code (temperature 0)."""
    static = alt_text_static_checks(occ.alt)
    heur = decorative_heuristics(occ.tag, occ.context)
    classification = (
        "functional" if heur["verdict"] == "functional" else a.classification
    )
    common = {
        "classification": classification,
        "confidence": a.confidence,
        "origin": "llm",
    }

    if classification == "decorative":
        if a.confidence == "low":
            return _outcome(
                occ,
                "needs_manual_review",
                reason="the model is not confident the image is decorative",
                **common,
            )
        if occ.alt is not None and occ.alt.strip() == "":
            return _outcome(
                occ, "keep", reason="decorative, alt already empty", **common
            )
        return _outcome(
            occ,
            "fix",
            suggested_alt="",
            severity="warning",
            reason="decorative image: alt must be empty",
            **common,
        )

    verdict = AltVerdict(
        visible_content=a.visible_content,
        matches_current_alt=a.matches_current_alt,
        suggested_alt=a.suggested_alt,
        confidence=a.confidence,
        uncertain_details=a.uncertain_details,
    )
    rec = decide_alt_recommendation(static, verdict)
    if rec == "keep":
        return _outcome(occ, "keep", reason="alt matches the image", **common)
    if rec == "needs_manual_review":
        return _outcome(
            occ,
            "needs_manual_review",
            reason="the description could not be verified with confidence",
            suggested_alt=a.suggested_alt or None,
            **common,
        )

    # rec == "fix": pick the replacement text
    if a.matches_current_alt == "yes" and occ.alt:
        # Accurate but with a style problem: the model was told to copy the
        # current alt, so only the deterministic prefix template can improve it.
        new_alt = (
            strip_redundant_prefix(occ.alt) if "redundant_prefix" in static else None
        )
        reason = "alt describes the image but starts with a redundant prefix"
    else:
        new_alt = a.suggested_alt.strip()
        if REDUNDANT_PREFIX.match(new_alt):
            new_alt = strip_redundant_prefix(new_alt) or new_alt
        reason = (
            "does not match the image"
            if a.matches_current_alt == "no"
            else "incomplete or inaccurate for the image"
        )
        if "empty_or_missing" in static:
            reason = (
                "missing alt text"
                if occ.alt is None
                else f"empty alt on an image that is {classification}"
            )
    if not new_alt or new_alt == (occ.alt or ""):
        return _outcome(
            occ,
            "needs_manual_review",
            reason=f"alt has problems ({', '.join(static)}) but no safe replacement",
            **common,
        )
    critical = "empty_or_missing" in static or a.matches_current_alt == "no"
    return _outcome(
        occ,
        "fix",
        suggested_alt=new_alt,
        severity="critical" if critical else "warning",
        reason=reason,
        **common,
    )


# ----- Requests -----
def _image_payload(occ: ImageOccurrence) -> tuple[str, str, str, str, str]:
    """Exactly what the model is told about an image besides its pixels."""
    heur = decorative_heuristics(occ.tag, occ.context)
    attr = "false" if occ.alt is None else "true"
    # D3: redact BEFORE truncating (a cut can leave a recognizable prefix) and
    # before anything is hashed for the verdict cache or sent to the model.
    alt = _neutralize(redact_secrets(occ.alt or ""), ALT_FOR_MODEL_CHARS)
    context = _neutralize(redact_secrets(occ.context), CONTEXT_FOR_MODEL_CHARS)
    lang = re.sub(r"[^A-Za-z-]", "", occ.lang)[:12] or "unknown"
    return attr, alt, lang, ", ".join(heur["signals"]), context


def verdict_cache_key(g: Group, model: str) -> str:
    """Hash of everything that determines the model's answer (B4).

    image bytes + alt + the trimmed context/lang/signals actually sent + model +
    prompt/schema fingerprint. No path, no key: safe to store.
    """
    assert g.image is not None
    attr, alt, lang, signals, context = _image_payload(g.occurrences[0])
    return sha256_hex(
        PROMPT_FINGERPRINT,
        model,
        sha256_hex(g.image.data),
        attr,
        alt,
        lang,
        signals,
        context,
    )


def _image_block(index: int, g: Group) -> list:
    attr, alt, lang, signals, context = _image_payload(g.occurrences[0])
    assert g.image is not None
    return [
        f"[IMAGE index={index}]",
        MediaPart(g.image.data, g.image.mime),
        f'<current_alt present="{attr}">{alt}</current_alt>\n'
        f"<page_lang>{lang}</page_lang>\n"
        f"<signals>{signals}</signals>\n"
        f"<html_context>{context}</html_context>",
    ]


def build_request(groups: Sequence[Group], note: str | None = None) -> LLMRequest:
    parts: list = [BATCH_RULES]
    for i, g in enumerate(groups):
        parts += _image_block(i, g)
    if note:
        parts.append(note)
    parts.append("Respond with the JSON object only.")
    return LLMRequest(parts=parts, schema=BatchAnalysis)


def estimate_request_tokens(
    groups: Sequence[Group], tokens_per_image: int
) -> tuple[int, int]:
    """(input, output) token estimate for one batch request."""
    text = BATCH_RULES
    for g in groups:
        occ = g.occurrences[0]
        text += (occ.alt or "")[:ALT_FOR_MODEL_CHARS]
        text += occ.context[:CONTEXT_FOR_MODEL_CHARS] + "[IMAGE index=00]<signals>"
    tokens_in = estimate_text_tokens(text) + len(groups) * tokens_per_image
    tokens_out = len(groups) * OUTPUT_TOKENS_PER_IMAGE + OVERHEAD_OUTPUT_TOKENS
    return tokens_in, tokens_out


def make_batches(
    groups: Sequence[Group], batch_size: int, max_bytes: int = MAX_BATCH_BYTES
) -> list[list[Group]]:
    """Splits by image count and by total image bytes (one request's payload)."""
    batches: list[list[Group]] = []
    current: list[Group] = []
    size = 0
    for g in groups:
        n = len(g.image.data) if g.image else 0
        if current and (len(current) >= batch_size or size + n > max_bytes):
            batches.append(current)
            current, size = [], 0
        current.append(g)
        size += n
    if current:
        batches.append(current)
    return batches


def parse_batch(text: str, expected: int) -> tuple[dict[int, ImageAnalysis], str]:
    """Validates the model's JSON. Returns (valid by index, error summary)."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        return {}, f"the response was not valid JSON ({str(e)[:120]})"
    items = data.get("results") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return {}, 'the JSON must be an object with a "results" array'
    valid: dict[int, ImageAnalysis] = {}
    problems: list[str] = []
    for item in items:
        try:
            a = ImageAnalysis.model_validate(item)
        except ValidationError as e:
            first = e.errors()[0]
            problems.append(f"{'.'.join(map(str, first['loc']))}: {first['msg']}")
            continue
        if 0 <= a.index < expected and a.index not in valid:
            valid[a.index] = a
    missing = [i for i in range(expected) if i not in valid]
    if missing:
        detail = "; ".join(problems[:3])
        return valid, (
            f"missing or invalid results for index {missing}"
            + (f" ({detail[:200]})" if detail else "")
        )
    return valid, ""


# ----- Orchestration -----
@dataclass
class Prepared:
    """Result of triage + image loading (everything before the first request)."""

    decided: dict[int, ImageOutcome]  # position -> outcome, no model needed
    pending: list[Group]  # groups that need the model (or failed to load)
    to_send: list[Group]  # loaded, within --max-images: will be sent
    unique: int  # unique (image, alt) pairs overall
    by_template: int  # unique pairs fully resolved in code


def prepare(
    occurrences: Sequence[ImageOccurrence],
    loader: ImageLoader,
    max_images: int | None = None,
    store: Store | None = None,
    model: str = "",
    progress: Callable[[str], None] | None = None,
) -> Prepared:
    """Deterministic triage + loading + cache lookup, de-duplicating by (image, alt).

    Cache hits are free: they set ``analysis`` and neither count against
    ``max_images`` nor are sent.
    """
    decided: dict[int, ImageOutcome] = {}
    groups: dict[tuple[str, str | None], Group] = {}
    all_keys: set[tuple[str, str | None]] = set()
    for pos, occ in enumerate(occurrences):
        key = (source_key(occ) if occ.src else f"<no-src>{pos}", occ.alt)
        all_keys.add(key)
        done = resolve_deterministic(occ)
        if done is not None:
            decided[pos] = done
            continue
        g = groups.setdefault(key, Group(key, []))
        g.occurrences.append(occ)
        g.positions.append(pos)

    to_send: list[Group] = []
    for gi, g in enumerate(groups.values(), 1):
        if progress:
            progress(f"image {gi}/{len(groups)}: {g.occurrences[0].src or '(no src)'}")
        try:
            g.image = loader(g.occurrences[0])
        except ImageLoadError as e:
            g.failure = str(e)
            g.transient = g.failure.startswith("could not download")
            continue
        if store is not None and store.enabled:
            g.cache_key = verdict_cache_key(g, model)
            hit = store.get_verdict(g.cache_key)
            if hit is not None:
                g.analysis, g.from_cache = hit, True
                store.hits += 1
                continue
            store.misses += 1
        if max_images is not None and len(to_send) >= max_images:
            g.skipped = f"--max-images limit reached ({max_images})"
            continue
        to_send.append(g)
    return Prepared(
        decided=decided,
        pending=list(groups.values()),
        to_send=to_send,
        unique=len(all_keys),
        by_template=len(all_keys) - len(groups),
    )


def _unprocessed(occurrences, reason: str, reasons: list[str]) -> StageResult:
    reasons.append(reason)
    return StageResult(
        outcomes=[_outcome(o, "skipped", reason=reason) for o in occurrences],
        partial_reasons=reasons,
        unique=len(occurrences),
        skipped=len(occurrences),
    )


INTERRUPTED = "interrupted by the user (Ctrl+C)"
_KIND_TEXT = {
    "quota_daily": "daily API quota exhausted (not retried)",
    "network": "the API could not be reached (network error)",
    "timeout": "the API timed out",
    "unavailable": "the API is unavailable (503)",
}


def analyze_images(
    occurrences: Sequence[ImageOccurrence],
    provider: LLMProvider,
    tracker: UsageTracker,
    *,
    loader: ImageLoader,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_images: int | None = None,
    tokens_per_image: int = 1100,
    max_batch_bytes: int = MAX_BATCH_BYTES,
    progress: Callable[[str], None] | None = None,
    store: Store | None = None,
    model: str = "",
    deadline: float | None = None,
) -> StageResult:
    """Runs the stage: triage, load, cache, batch, ask, validate, decide.

    Never raises for Ctrl+C: it returns what is done (verdicts already cached)
    with the rest ``skipped``. An invalid API key raises ``ProviderError``
    (kind ``invalid_key``) immediately: nothing else is requested.
    """
    reasons: list[str] = []
    try:
        prep = prepare(occurrences, loader, max_images, store, model, progress)
    except KeyboardInterrupt:
        return _unprocessed(occurrences, INTERRUPTED, reasons)
    if any(g.skipped for g in prep.pending):
        reasons.append(f"--max-images limit reached ({max_images})")

    batches = make_batches(prep.to_send, batch_size, max_batch_bytes)
    consecutive_failures = 0
    stopped: str | None = None
    writes_before = store.writes if store else 0
    for bi, batch in enumerate(batches, 1):
        if stopped is None:
            est_in, est_out = estimate_request_tokens(batch, tokens_per_image)
            stopped = tracker.stop_reason(est_in, est_out)
            if stopped is None and deadline is not None and time.monotonic() > deadline:
                stopped = "--scan-timeout reached"
            if stopped:
                reasons.append(stopped)
        if stopped:
            for g in batch:
                g.skipped = stopped
            continue
        if progress:
            progress(
                f"asking the model, batch {bi}/{len(batches)}: {len(batch)} image(s)"
            )
        tracker.batches += 1
        try:
            failed = _run_batch(batch, provider, tracker, est_in, est_out)
        except KeyboardInterrupt:
            # the batch in flight is dropped whole and retried on resume
            stopped = INTERRUPTED
            reasons.append(stopped)
            for g in batch:
                g.analysis, g.failure, g.skipped = None, None, stopped
            continue
        if failed is None:
            consecutive_failures = 0
            if store is not None:
                for g in batch:
                    if g.analysis is not None and g.cache_key:
                        store.put_verdict(g.cache_key, g.analysis)
            continue
        kind, message = failed
        if kind == "invalid_key":
            raise ProviderError("invalid_key", message, tracker.requests)
        consecutive_failures += 1
        if kind in ("quota_daily", "attempt_limit") or consecutive_failures >= 2:
            stopped = (
                tracker.limits.requests_message()
                if kind == "attempt_limit"
                else _KIND_TEXT.get(kind, f"provider failed repeatedly ({message})")
            )
            reasons.append(stopped)
            if kind in ("quota_daily", "attempt_limit"):
                # not a verdict on the images: they were simply not processed
                for g in batch:
                    g.failure, g.skipped = None, stopped

    decided = dict(prep.decided)
    result = StageResult(
        outcomes=[],
        partial_reasons=reasons,
        unique=prep.unique,
        by_template=prep.by_template,
        batches=tracker.batches,
    )
    if store is not None and store.enabled:
        result.cache_hits = sum(1 for g in prep.pending if g.from_cache)
        result.cache_misses = sum(
            1 for g in prep.pending if g.cache_key and not g.from_cache
        )
        result.cache_writes = store.writes - writes_before
    for g in prep.pending:
        if g.analysis is not None:
            result.verified += 1
        elif g.skipped:
            result.skipped += 1
        else:
            result.manual_review += 1
        for pos, occ in zip(g.positions, g.occurrences, strict=True):
            if g.analysis is not None:
                decided[pos] = decide(occ, g.analysis)
            elif g.skipped:
                decided[pos] = _outcome(occ, "skipped", reason=g.skipped)
            else:
                decided[pos] = fallback_outcome(
                    occ, g.failure or "no answer from the model", g.transient
                )
    result.outcomes = [decided[i] for i in range(len(occurrences))]
    return result


def _run_batch(
    batch: list[Group],
    provider: LLMProvider,
    tracker: UsageTracker,
    est_in: int,
    est_out: int,
) -> tuple[str, str] | None:
    """Asks the model about ``batch``; sets ``analysis``/``failure`` on groups.

    Returns None on success (even if some images are left for manual review),
    or (error kind, message) when the provider failed.
    """
    request = build_request(batch)
    try:
        res = provider.generate(request, max_attempts=tracker.remaining_requests())
    except ProviderError as e:
        tracker.record(e.attempts, None, est_in, est_out, success=False)
        for g in batch:
            g.failure, g.transient = f"provider error ({e.kind})", True
        return e.kind, str(e)
    tracker.record(res.attempts, res.usage, est_in, est_out)
    valid, error = parse_batch(res.text, len(batch))
    for i, a in valid.items():
        batch[i].analysis = a

    missing = [i for i in range(len(batch)) if i not in valid]
    if missing:
        # ONE corrective retry, only for the images with a bad/missing answer.
        sub = [batch[i] for i in missing]
        sub_in, sub_out = estimate_request_tokens(sub, 0)
        note = (
            "Your previous response was rejected: "
            f"{_neutralize(error, 300)}. Return ONLY a valid JSON object matching "
            "the schema, with one result per image."
        )
        if tracker.stop_reason(sub_in, sub_out) is None:
            try:
                res2 = provider.generate(
                    build_request(sub, note),
                    max_attempts=tracker.remaining_requests(),
                )
            except ProviderError as e:
                tracker.record(e.attempts, None, sub_in, sub_out, success=False)
                for g in sub:
                    g.failure = f"provider error ({e.kind}) on the corrective retry"
                    g.transient = True
                return e.kind, str(e)
            tracker.record(res2.attempts, res2.usage, sub_in, sub_out)
            valid2, _ = parse_batch(res2.text, len(sub))
            for j, a in valid2.items():
                sub[j].analysis = a
        for g in sub:
            if g.analysis is None:
                g.failure = "the model returned invalid JSON twice"
                g.transient = True
    return None
