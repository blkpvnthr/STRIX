"""Typed provider-level contracts: token usage, cost, and model responses.

These are the frozen, Decimal-exact records the provider returns and the budget
tracker accounts against. Evidence and claim contracts (spec §9-11) live in
later phases; this module is the foundation the provider and budget share.

Cost is computed with **no double counting**: reasoning tokens are a subset of
``output_tokens`` (confirmed against the live Responses API), so they are billed
once at the output rate, never added again. Cached input tokens are a subset of
``input_tokens`` and are billed at the cached rate; the remaining uncached input
is billed at the input rate.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from strix.agent.config import PricingConfig

#: USD are accounted to 8 decimal places (sub-micro-dollar token costs).
_USD_QUANTUM = Decimal("0.00000001")
_PER_MILLION = Decimal("1000000")


class TokenUsage(BaseModel):
    """Token counts for one or more model calls (all non-negative integers)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    #: Subset of ``output_tokens`` spent on reasoning (reported, not re-billed).
    reasoning_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)

    @classmethod
    def from_response_usage(cls, usage: Any) -> TokenUsage:
        """Map an OpenAI ``ResponseUsage`` object to a ``TokenUsage``.

        Tolerant of absent detail blocks (older/leaner responses) via getattr.
        """
        if usage is None:
            return cls()
        input_details = getattr(usage, "input_tokens_details", None)
        output_details = getattr(usage, "output_tokens_details", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        cached = int(getattr(input_details, "cached_tokens", 0) or 0) if input_details else 0
        reasoning = (
            int(getattr(output_details, "reasoning_tokens", 0) or 0) if output_details else 0
        )
        total = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0)
        return cls(
            input_tokens=input_tokens,
            cached_input_tokens=min(cached, input_tokens),
            output_tokens=output_tokens,
            reasoning_tokens=min(reasoning, output_tokens),
            total_tokens=total,
        )

    def combine(self, other: TokenUsage) -> TokenUsage:
        """Sum two usage records field-by-field."""
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


class CostBreakdown(BaseModel):
    """Exact USD cost of some token usage under a pricing version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    pricing_version: str
    input_cost_usd: Decimal
    cached_input_cost_usd: Decimal
    output_cost_usd: Decimal
    #: Separately billed tool fees (e.g. hosted web search), when known.
    tool_cost_usd: Decimal = Decimal("0")
    total_cost_usd: Decimal


def estimate_cost(
    usage: TokenUsage,
    pricing: PricingConfig,
    *,
    tool_cost_usd: Decimal = Decimal("0"),
) -> CostBreakdown:
    """Compute exact USD cost for token usage (no double counting of reasoning)."""
    uncached_input = max(usage.input_tokens - usage.cached_input_tokens, 0)
    input_cost = _usd(uncached_input, pricing.input_usd_per_1m)
    cached_cost = _usd(usage.cached_input_tokens, pricing.cached_input_usd_per_1m)
    output_cost = _usd(usage.output_tokens, pricing.output_usd_per_1m)
    tool_cost = tool_cost_usd.quantize(_USD_QUANTUM, rounding=ROUND_HALF_EVEN)
    total = (input_cost + cached_cost + output_cost + tool_cost).quantize(
        _USD_QUANTUM, rounding=ROUND_HALF_EVEN
    )
    return CostBreakdown(
        model=pricing.model,
        pricing_version=pricing.pricing_version,
        input_cost_usd=input_cost,
        cached_input_cost_usd=cached_cost,
        output_cost_usd=output_cost,
        tool_cost_usd=tool_cost,
        total_cost_usd=total,
    )


def _usd(tokens: int, rate_per_1m: Decimal) -> Decimal:
    return (Decimal(tokens) / _PER_MILLION * rate_per_1m).quantize(
        _USD_QUANTUM, rounding=ROUND_HALF_EVEN
    )


class ToolCall(BaseModel):
    """A function/tool invocation the model requested on one turn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: str
    name: str
    #: Raw JSON arguments string as returned by the model (validated later).
    arguments: str


class ModelResponse(BaseModel):
    """A typed Responses-API result for one model call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    response_id: str
    model: str
    status: str
    output_text: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: TokenUsage = TokenUsage()
    cost: CostBreakdown
    #: Set when ``status`` is not ``completed`` (e.g. ``max_output_tokens``).
    incomplete_reason: str | None = None

    @property
    def is_complete(self) -> bool:
        return self.status == "completed"
