"""Tests for token-usage mapping and exact cost accounting."""

from __future__ import annotations

from decimal import Decimal

from tests.agent.agent_fixtures import FakeUsage

from strix.agent.config import PricingConfig
from strix.agent.contracts import TokenUsage, estimate_cost

_PRICING = PricingConfig.for_model("gpt-6-luna")


def test_from_response_usage_maps_all_fields() -> None:
    usage = TokenUsage.from_response_usage(
        FakeUsage(
            input_tokens=100,
            cached_tokens=40,
            output_tokens=20,
            reasoning_tokens=8,
            total_tokens=120,
        )
    )
    assert usage.input_tokens == 100
    assert usage.cached_input_tokens == 40
    assert usage.output_tokens == 20
    assert usage.reasoning_tokens == 8
    assert usage.total_tokens == 120


def test_from_response_usage_handles_none() -> None:
    assert TokenUsage.from_response_usage(None) == TokenUsage()


def test_cost_no_double_counting_of_reasoning() -> None:
    # 1M uncached input @ $0.10 + 1M output @ $0.50 = $0.60. Reasoning tokens are
    # a subset of output and must NOT add extra cost.
    usage = TokenUsage(
        input_tokens=1_000_000,
        cached_input_tokens=0,
        output_tokens=1_000_000,
        reasoning_tokens=500_000,
        total_tokens=2_000_000,
    )
    cost = estimate_cost(usage, _PRICING)
    assert cost.input_cost_usd == Decimal("0.10000000")
    assert cost.output_cost_usd == Decimal("0.50000000")
    assert cost.total_cost_usd == Decimal("0.60000000")


def test_cached_input_billed_at_cached_rate() -> None:
    # 1M input of which 1M cached: billed entirely at the $0.01 cached rate.
    usage = TokenUsage(input_tokens=1_000_000, cached_input_tokens=1_000_000)
    cost = estimate_cost(usage, _PRICING)
    assert cost.input_cost_usd == Decimal("0")
    assert cost.cached_input_cost_usd == Decimal("0.01000000")
    assert cost.total_cost_usd == Decimal("0.01000000")


def test_tool_cost_added() -> None:
    cost = estimate_cost(TokenUsage(), _PRICING, tool_cost_usd=Decimal("0.025"))
    assert cost.tool_cost_usd == Decimal("0.02500000")
    assert cost.total_cost_usd == Decimal("0.02500000")


def test_combine_sums_fields() -> None:
    a = TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15)
    b = TokenUsage(input_tokens=3, output_tokens=2, total_tokens=5)
    combined = a.combine(b)
    assert combined.input_tokens == 13
    assert combined.output_tokens == 7
    assert combined.total_tokens == 20


def test_cached_clamped_to_input() -> None:
    # Defensive: cached can never exceed input.
    usage = TokenUsage.from_response_usage(
        FakeUsage(input_tokens=5, cached_tokens=99, output_tokens=0)
    )
    assert usage.cached_input_tokens == 5
