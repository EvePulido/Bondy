"""Pre-flight estimate of what an LLM scan would cost. Never calls the model.

It runs the same triage and image loading as the real stage (so it knows which
images code resolves for free and which cannot be loaded) but never downloads
remote images (those are assumed loadable) and never contacts a provider. All
numbers are estimates: token counts use a characters/4 rule plus a configured
per-image figure, and prices come from the user's configuration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from bondy.config import Settings
from bondy.core.budget import (
    NO_PRICES_REASON,
    Limits,
    Pricing,
    require_prices_for_limits,
)
from bondy.core.images import LoadedImage, is_remote_src, load_image
from bondy.core.models import ImageOccurrence
from bondy.core.pipeline import collect_images
from bondy.core.semantic import (
    estimate_request_tokens,
    make_batches,
    prepare,
)
from bondy.scan import MAX_FILE_BYTES, discover

# Worst case per batch: the first answer is invalid and ONE corrective retry
# re-sends the same images (provider 429/503 retries are not billed requests).
WORST_CASE_FACTOR = 2

DISCLAIMER = (
    "This is an ESTIMATE made without calling the model: tokens are "
    "approximated (characters/4 + a per-image figure) and prices come from your "
    "configuration (price_input_per_mtok / price_output_per_mtok in bondy.toml); "
    "check them against your provider's current price list."
)


@dataclass
class Estimate:
    mode: str  # "llm" | "no-llm"
    pages: int = 0
    pages_skipped: int = 0
    images_found: int = 0
    images_unique: int = 0
    images_by_template: int = 0  # resolved in code, free
    images_unloadable: int = 0  # manual review, free
    images_remote: int = 0  # assumed loadable (not downloaded to estimate)
    images_to_verify: int = 0
    images_over_limit: int = 0  # cut by --max-images
    batch_size: int = 0
    batches: int = 0
    requests_min: int = 0
    requests_max: int = 0
    input_tokens_min: int = 0
    input_tokens_max: int = 0
    output_tokens_min: int = 0
    output_tokens_max: int = 0
    # None when no prices are configured (cost_unavailable_reason says why)
    cost_min_usd: float | None = None
    cost_max_usd: float | None = None
    cost_unavailable_reason: str | None = None
    prices_configured: bool = False
    remote_images: bool = True
    request_limit: int | None = None
    request_limit_is_default: bool = False
    exceeds_limits: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "disclaimer": DISCLAIMER}


def _make_loader(remote_images: bool):
    def loader(occ: ImageOccurrence) -> LoadedImage:
        if remote_images and is_remote_src(occ.src):
            return LoadedImage(b"", "image/png")  # assumed loadable, not downloaded
        # local files are really read; remote ones fail with the opt-out reason
        return load_image(occ, allow_remote=False)

    return loader


def estimate_scan(target: Path | str, settings: Settings) -> Estimate:
    """Counts pages/images/batches and prices them. No model, no network."""
    require_prices_for_limits(settings)
    est = Estimate(mode="no-llm" if settings.no_llm else "llm")
    est.remote_images = settings.remote_images
    files = discover(target, settings.include, settings.exclude)
    if settings.max_pages is not None and len(files) > settings.max_pages:
        est.pages_skipped = len(files) - settings.max_pages
        files = files[: settings.max_pages]
        est.notes.append(
            f"--max-pages {settings.max_pages}: {est.pages_skipped} page(s) would "
            "not be scanned."
        )
    est.pages = len(files)
    pricing = Pricing.from_settings(settings)
    est.prices_configured = pricing.available
    limits = Limits.from_settings(settings)
    est.request_limit = limits.max_requests
    est.request_limit_is_default = limits.max_requests_is_default

    if settings.no_llm:
        est.notes.append("--no-llm: no model requests will be made.")
        return est

    # reuse the pipeline's reader but only over files that would be scanned
    from bondy.scan import FileResult

    results = [
        FileResult(path=str(p), skipped="too large")
        if p.stat().st_size > MAX_FILE_BYTES
        else FileResult(path=str(p))
        for p in files
    ]
    occurrences = collect_images(results, target)
    est.images_found = len(occurrences)
    prep = prepare(
        occurrences, _make_loader(settings.remote_images), settings.max_images
    )
    est.images_unique = prep.unique
    est.images_by_template = prep.by_template
    est.images_unloadable = sum(1 for g in prep.pending if g.failure)
    est.images_over_limit = sum(1 for g in prep.pending if g.skipped)
    est.images_to_verify = len(prep.to_send)
    est.images_remote = sum(
        1 for g in prep.to_send if is_remote_src(g.occurrences[0].src)
    )
    if est.images_remote:
        est.notes.append(
            f"{est.images_remote} remote image(s) were not downloaded; they are "
            "assumed loadable. Some may turn out 404/too large (manual review)."
        )
    if est.images_over_limit:
        est.notes.append(
            f"--max-images {settings.max_images}: {est.images_over_limit} image(s) "
            "would not be verified."
        )

    batches = make_batches(prep.to_send, settings.batch_size)
    est.batches = len(batches)
    est.batch_size = settings.batch_size
    for batch in batches:
        tin, tout = estimate_request_tokens(batch, settings.tokens_per_image)
        est.input_tokens_min += tin
        est.output_tokens_min += tout
    est.requests_min = est.batches
    est.requests_max = est.batches * WORST_CASE_FACTOR
    est.input_tokens_max = est.input_tokens_min * WORST_CASE_FACTOR
    est.output_tokens_max = est.output_tokens_min * WORST_CASE_FACTOR
    est.cost_min_usd = pricing.cost(est.input_tokens_min, est.output_tokens_min)
    est.cost_max_usd = pricing.cost(est.input_tokens_max, est.output_tokens_max)
    if est.cost_min_usd is None:
        est.cost_unavailable_reason = NO_PRICES_REASON

    if limits.max_requests is not None and est.requests_min > limits.max_requests:
        hint = (
            " (the default; raise it with --max-requests N, or 0 for no limit)"
            if limits.max_requests_is_default
            else ""
        )
        est.exceeds_limits.append(
            f"--max-requests {limits.max_requests}{hint} is below the "
            f"{est.requests_min} request(s) needed: the scan would be PARTIAL."
        )
    if (
        limits.max_usd is not None
        and est.cost_min_usd is not None
        and est.cost_min_usd > limits.max_usd
    ):
        est.exceeds_limits.append(
            f"--max-usd {limits.max_usd:g} is below the estimated minimum "
            f"${est.cost_min_usd:.4f}: the scan would be PARTIAL."
        )
    return est


def format_estimate(est: Estimate) -> str:
    """Human-readable summary ("N requests, ~X tokens, ~$Y")."""
    lines = [f"Estimate for {est.pages} page(s) (mode: {est.mode})"]
    if est.mode == "no-llm":
        lines += [f"  {n}" for n in est.notes]
        lines.append("  0 requests, 0 tokens, $0.00")
        return "\n".join(lines)
    lines += [
        f"  images: {est.images_found} found, {est.images_unique} unique "
        f"({est.images_by_template} resolved in code, {est.images_unloadable} "
        f"not loadable, {est.images_to_verify} for the model)",
        f"  batches: {est.batches} (up to {est.batch_size} images per request)",
        f"  requests: {est.requests_min} to {est.requests_max}",
        f"  tokens: ~{est.input_tokens_min} to ~{est.input_tokens_max} in, "
        f"~{est.output_tokens_min} to ~{est.output_tokens_max} out",
    ]
    if est.cost_min_usd is None:
        lines.append(f"  cost: not available ({est.cost_unavailable_reason})")
    else:
        lines.append(
            f"  cost: ~${est.cost_min_usd:.4f} to ~${est.cost_max_usd:.4f} "
            "(with your configured prices)"
        )
    if est.request_limit is not None and est.request_limit_is_default:
        lines.append(
            f"  request limit: {est.request_limit} (default; --max-requests N "
            "to change, 0 for no limit)"
        )
    lines += [f"  note: {n}" for n in est.notes]
    lines += [f"  WARNING: {w}" for w in est.exceeds_limits]
    lines.append(f"  {DISCLAIMER}")
    return "\n".join(lines)
