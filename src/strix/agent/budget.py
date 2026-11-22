"""Per-run budget accounting and enforcement.

Every limit in the spec is enforced here, not merely advised. The orchestrator
asks the tracker *before* each model or tool call whether the budget still
allows it; if not, it stops and returns whatever verified findings it already
has (fail-soft on budget, never a silent overrun). Cost is accumulated from
real reported token usage priced with the versioned :class:`PricingConfig`.

Wall-clock time uses an injectable monotonic source so tests are deterministic
and never sleep.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from strix.agent.config import AgentConfig
from strix.agent.contracts import CostBreakdown, TokenUsage, estimate_cost
from strix.errors import BudgetExceededError


class BudgetSnapshot(BaseModel):
    """Immutable accounting snapshot for persistence and the final response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_calls: int
    tool_calls: int
    usage: TokenUsage
    estimated_cost_usd: Decimal
    tool_cost_usd: Decimal
    pricing_version: str
    elapsed_seconds: Decimal
    exhausted: bool
    exhausted_reason: str | None


class BudgetTracker:
    """Accumulates usage/cost/time and enforces configured ceilings."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        now_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._now = now_fn
        self._start = now_fn()
        self._model_calls = 0
        self._tool_calls = 0
        self._usage = TokenUsage()
        self._token_cost = Decimal("0")
        self._tool_cost = Decimal("0")

    # -- accounting --------------------------------------------------------

    def record_model_call(self, usage: TokenUsage) -> CostBreakdown:
        """Record one model call's usage and return its cost breakdown."""
        self._model_calls += 1
        self._usage = self._usage.combine(usage)
        breakdown = estimate_cost(usage, self._config.pricing)
        self._token_cost += breakdown.total_cost_usd
        return breakdown

    def record_tool_call(self, *, tool_cost_usd: Decimal = Decimal("0")) -> None:
        """Record one tool call and any separately billed tool fee."""
        self._tool_calls += 1
        self._tool_cost += tool_cost_usd

    # -- enforcement -------------------------------------------------------

    def ensure_can_call_model(self) -> None:
        """Raise :class:`BudgetExceededError` if another model call is not allowed."""
        self._check_time()
        if self._model_calls >= self._config.max_model_calls:
            raise BudgetExceededError(
                f"model-call limit reached ({self._config.max_model_calls})"
            )
        if self._usage.output_tokens >= self._config.max_total_output_tokens:
            raise BudgetExceededError(
                f"output-token limit reached ({self._config.max_total_output_tokens})"
            )
        if self._usage.input_tokens >= self._config.max_input_tokens:
            raise BudgetExceededError(
                f"input-token limit reached ({self._config.max_input_tokens})"
            )
        self._check_cost()

    def ensure_can_call_tool(self) -> None:
        """Raise :class:`BudgetExceededError` if another tool call is not allowed."""
        self._check_time()
        if self._tool_calls >= self._config.max_tool_calls:
            raise BudgetExceededError(
                f"tool-call limit reached ({self._config.max_tool_calls})"
            )
        self._check_cost()

    def would_exceed_cost(self) -> bool:
        """True if accumulated cost has reached the configured ceiling."""
        return self.spent_usd >= self._config.max_cost_usd

    def _check_cost(self) -> None:
        if self.would_exceed_cost():
            raise BudgetExceededError(
                f"cost limit reached (${self.spent_usd} >= ${self._config.max_cost_usd})"
            )

    def _check_time(self) -> None:
        if self.elapsed_seconds >= Decimal(self._config.max_research_seconds):
            raise BudgetExceededError(
                f"time limit reached ({self._config.max_research_seconds}s)"
            )

    # -- read-only state ---------------------------------------------------

    @property
    def spent_usd(self) -> Decimal:
        return self._token_cost + self._tool_cost

    @property
    def remaining_usd(self) -> Decimal:
        return max(self._config.max_cost_usd - self.spent_usd, Decimal("0"))

    @property
    def elapsed_seconds(self) -> Decimal:
        return Decimal(str(round(self._now() - self._start, 3)))

    @property
    def model_calls(self) -> int:
        return self._model_calls

    @property
    def tool_calls(self) -> int:
        return self._tool_calls

    @property
    def usage(self) -> TokenUsage:
        return self._usage

    def snapshot(self, *, exhausted_reason: str | None = None) -> BudgetSnapshot:
        return BudgetSnapshot(
            model_calls=self._model_calls,
            tool_calls=self._tool_calls,
            usage=self._usage,
            estimated_cost_usd=self.spent_usd,
            tool_cost_usd=self._tool_cost,
            pricing_version=self._config.pricing.pricing_version,
            elapsed_seconds=self.elapsed_seconds,
            exhausted=exhausted_reason is not None,
            exhausted_reason=exhausted_reason,
        )
