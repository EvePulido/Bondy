"""Cost model, hard limits and usage accounting for the LLM stage.

Prices are **user inputs**, never facts: Bondy ships no price values. Without
configured prices, requests and tokens are still reported but the dollar cost
is "not available" (it is never invented).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from bondy.config import ConfigError, Settings
from bondy.core.models import UsageSummary
from bondy.core.providers.base import TokenUsage

# Rough sizes used only to *estimate* (the real numbers come from the provider).
CHARS_PER_TOKEN = 4
OUTPUT_TOKENS_PER_IMAGE = 120
OVERHEAD_OUTPUT_TOKENS = 20

PRICES_HOWTO = (
    "set price_input_per_mtok and price_output_per_mtok (USD per million tokens) "
    "in bondy.toml, or BONDY_PRICE_INPUT_PER_MTOK / BONDY_PRICE_OUTPUT_PER_MTOK"
)
NO_PRICES_REASON = f"prices are not configured: {PRICES_HOWTO}"


@dataclass(frozen=True)
class Pricing:
    """USD per million tokens; ``None`` = not configured."""

    input_per_mtok: float | None = None
    output_per_mtok: float | None = None

    @property
    def available(self) -> bool:
        return self.input_per_mtok is not None and self.output_per_mtok is not None

    def cost(self, input_tokens: int, output_tokens: int) -> float | None:
        if self.input_per_mtok is None or self.output_per_mtok is None:
            return None
        return (
            input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok
        ) / 1_000_000

    @classmethod
    def from_settings(cls, s: Settings) -> Pricing:
        return cls(s.price_input_per_mtok, s.price_output_per_mtok)


@dataclass(frozen=True)
class Limits:
    """Hard limits; ``None`` = unlimited."""

    max_requests: int | None = None
    max_usd: float | None = None
    max_pages: int | None = None
    max_images: int | None = None
    # True when max_requests is the built-in default, not something the user set.
    max_requests_is_default: bool = False

    @classmethod
    def from_settings(cls, s: Settings) -> Limits:
        return cls(
            s.max_requests,
            s.max_usd,
            s.max_pages,
            s.max_images,
            max_requests_is_default=s.max_requests is not None
            and s.sources.get("max_requests") == "default",
        )

    def requests_message(self) -> str:
        n = self.max_requests
        if self.max_requests_is_default:
            return (
                f"--max-requests limit reached ({n}, the default); raise it with "
                "--max-requests N, or pass --max-requests 0 for no limit"
            )
        return f"--max-requests limit reached ({n})"


def require_prices_for_limits(settings: Settings) -> None:
    """``--max-usd`` needs prices: fail before any request, never ignore it."""
    if settings.no_llm or settings.max_usd is None:
        return
    if not Pricing.from_settings(settings).available:
        raise ConfigError(
            f"--max-usd {settings.max_usd:g} cannot be enforced because "
            f"{NO_PRICES_REASON}. Configure the prices or drop --max-usd."
        )


def estimate_text_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


class UsageTracker:
    """Accumulates real usage and answers "may I make the next request?"."""

    def __init__(self, limits: Limits, pricing: Pricing):
        self.limits = limits
        self.pricing = pricing
        self.requests = 0
        self.batches = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.tokens_estimated = False
        self._successes = 0

    # ----- before a request -----
    def remaining_requests(self) -> int | None:
        if self.limits.max_requests is None:
            return None
        return max(self.limits.max_requests - self.requests, 0)

    def spent_usd(self) -> float | None:
        return self.pricing.cost(self.input_tokens, self.output_tokens)

    def stop_reason(self, est_input: int = 0, est_output: int = 0) -> str | None:
        """Why the next request must not be made, or None if it may."""
        left = self.remaining_requests()
        if left is not None and left < 1:
            return self.limits.requests_message()
        cap = self.limits.max_usd
        if cap is not None and self.pricing.available:
            projected = (self.spent_usd() or 0.0) + (
                self.pricing.cost(est_input, est_output) or 0.0
            )
            if projected > cap:
                return (
                    f"--max-usd limit would be exceeded (estimated "
                    f"${projected:.4f} > ${cap:.4f})"
                )
        return None

    # ----- after a request -----
    def record(
        self,
        attempts: int,
        usage: TokenUsage | None,
        est_input: int,
        est_output: int,
        *,
        success: bool = True,
    ) -> None:
        self.requests += attempts
        if not success:
            return  # a failed call is not billed; only the attempt is counted
        self._successes += 1
        if usage is None:
            self.tokens_estimated = True
            self.input_tokens += est_input
            self.output_tokens += est_output
        else:
            self.input_tokens += usage.input_tokens
            self.output_tokens += usage.output_tokens

    def fill(self, summary: UsageSummary) -> None:
        summary.requests = self.requests
        summary.batches = self.batches
        summary.input_tokens = self.input_tokens if self._successes else None
        summary.output_tokens = self.output_tokens if self._successes else None
        summary.tokens_estimated = self.tokens_estimated
        summary.request_limit = self.limits.max_requests
        summary.request_limit_is_default = self.limits.max_requests_is_default
        spent = self.spent_usd()
        if spent is None:
            summary.cost_usd = None
            summary.cost_unavailable_reason = NO_PRICES_REASON
        else:
            summary.cost_usd = round(spent, 6)
            summary.cost_unavailable_reason = None
        summary.cost_is_estimate = True  # tokens may be estimated; prices are yours
