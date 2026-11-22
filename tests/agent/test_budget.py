"""Tests for in-code budget enforcement."""

from __future__ import annotations

from decimal import Decimal

import pytest
from tests.agent.agent_fixtures import build_config

from strix.agent.budget import BudgetTracker
from strix.agent.contracts import TokenUsage
from strix.errors import BudgetExceededError


class FakeClock:
    """Deterministic monotonic clock driven by the test."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_records_usage_and_cost() -> None:
    tracker = BudgetTracker(build_config(), now_fn=FakeClock())
    breakdown = tracker.record_model_call(
        TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    )
    assert breakdown.total_cost_usd == Decimal("0.60000000")
    assert tracker.spent_usd == Decimal("0.60000000")
    assert tracker.model_calls == 1


def test_model_call_limit_enforced() -> None:
    tracker = BudgetTracker(build_config(STRIX_AGENT_MAX_MODEL_CALLS="2"), now_fn=FakeClock())
    tracker.ensure_can_call_model()
    tracker.record_model_call(TokenUsage(input_tokens=1, output_tokens=1))
    tracker.ensure_can_call_model()
    tracker.record_model_call(TokenUsage(input_tokens=1, output_tokens=1))
    with pytest.raises(BudgetExceededError, match="model-call limit"):
        tracker.ensure_can_call_model()


def test_cost_limit_enforced() -> None:
    # Raise the token ceiling so cost is the binding constraint, not tokens.
    tracker = BudgetTracker(
        build_config(
            STRIX_AGENT_MAX_COST_USD="0.05",
            STRIX_AGENT_MAX_TOTAL_OUTPUT_TOKENS="1000000",
        ),
        now_fn=FakeClock(),
    )
    # 100k output tokens @ $0.50/1M = $0.05 -> reaches the ceiling.
    tracker.record_model_call(TokenUsage(output_tokens=100_000))
    assert tracker.spent_usd == Decimal("0.05000000")
    assert tracker.would_exceed_cost() is True
    with pytest.raises(BudgetExceededError, match="cost limit"):
        tracker.ensure_can_call_model()


def test_output_token_limit_enforced() -> None:
    tracker = BudgetTracker(
        build_config(STRIX_AGENT_MAX_TOTAL_OUTPUT_TOKENS="100"), now_fn=FakeClock()
    )
    tracker.record_model_call(TokenUsage(output_tokens=100))
    with pytest.raises(BudgetExceededError, match="output-token limit"):
        tracker.ensure_can_call_model()


def test_time_limit_enforced() -> None:
    clock = FakeClock()
    tracker = BudgetTracker(build_config(STRIX_AGENT_MAX_RESEARCH_SECONDS="10"), now_fn=clock)
    tracker.ensure_can_call_model()  # t=0, fine
    clock.t = 10.0
    with pytest.raises(BudgetExceededError, match="time limit"):
        tracker.ensure_can_call_model()


def test_tool_call_limit_enforced() -> None:
    tracker = BudgetTracker(build_config(STRIX_AGENT_MAX_TOOL_CALLS="1"), now_fn=FakeClock())
    tracker.ensure_can_call_tool()
    tracker.record_tool_call()
    with pytest.raises(BudgetExceededError, match="tool-call limit"):
        tracker.ensure_can_call_tool()


def test_snapshot_fields() -> None:
    clock = FakeClock()
    tracker = BudgetTracker(build_config(), now_fn=clock)
    tracker.record_model_call(TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15))
    tracker.record_tool_call(tool_cost_usd=Decimal("0.001"))
    clock.t = 3.5
    snap = tracker.snapshot(exhausted_reason=None)
    assert snap.model_calls == 1
    assert snap.tool_calls == 1
    assert snap.usage.total_tokens == 15
    assert snap.elapsed_seconds == Decimal("3.5")
    assert snap.exhausted is False
    snap2 = tracker.snapshot(exhausted_reason="cost limit reached")
    assert snap2.exhausted is True
    assert snap2.exhausted_reason == "cost limit reached"
