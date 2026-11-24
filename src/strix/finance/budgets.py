"""Decimal-exact category budgeting, savings goals, and cash-flow projection.

This module layers lightweight planning on top of the offline finance engine.
It operates on *category totals* only — categories are plain strings, so there
is no dependency on any categorizer; a caller supplies whatever labels it keeps
and the already-summed actual spend per label.

Three concerns live here:

* :class:`CategoryBudget` records a positive monthly spending limit for one
  category in one ``YYYY-MM`` period.
* :class:`SavingsGoal` tracks progress toward a positive target amount; its
  :attr:`~SavingsGoal.progress` is the exact ``saved / target`` ratio.
* :func:`compute_variances` scores actual spend against budgets (a missing
  category scores zero spend), and :func:`cash_flow_projection` rolls an
  opening balance forward by a fixed net monthly flow.

Design rules this module upholds (shared with :mod:`strix.finance.ledger`):

* Models are frozen and closed (:class:`strix.models.StrixModel`).
* Monetary amounts use :class:`strix.models.DecimalValue` — binary ``float``
  is rejected at the model boundary and in every parameter.
* Arithmetic goes through :mod:`strix.native.arithmetic` (``checked_sum`` /
  ``checked_sub`` / ``checked_div``) so every result is exact Decimal
  regardless of magnitude or count.
* Invalid inputs raise :class:`BudgetError` (a :class:`strix.errors.StrixError`)
  or a pydantic ``ValidationError`` at the model boundary.

No network access and no live account aggregation happen here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

from pydantic import Field, field_validator

from strix.errors import StrixError
from strix.models import DecimalValue, StrixModel
from strix.native.arithmetic import (
    as_decimal,
    checked_div,
    checked_sub,
    checked_sum,
)

__all__ = [
    "BudgetError",
    "BudgetVariance",
    "CategoryBudget",
    "SavingsGoal",
    "cash_flow_projection",
    "compute_variances",
]

#: Accepted period format: a four-digit year, a hyphen, and a 01..12 month.
_PERIOD_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


class BudgetError(StrixError):
    """A budgeting input could not be trusted: a negative actual spend or a
    non-positive projection horizon. Model-level violations (a non-positive
    limit or target, a negative saved amount, a malformed period, or a binary
    ``float``) surface as a pydantic ``ValidationError`` instead."""


class CategoryBudget(StrixModel):
    """A positive monthly spending limit for one category in one period.

    ``category`` is an opaque label (no dependency on any categorizer) and
    ``period`` is a ``YYYY-MM`` calendar month (e.g. ``"2026-01"``). The limit
    must be strictly positive — a zero or negative budget is meaningless.
    """

    category: str = Field(min_length=1)
    monthly_limit: DecimalValue = Field(gt=Decimal(0))
    period: str = Field(pattern=_PERIOD_PATTERN)


class SavingsGoal(StrixModel):
    """Progress tracking toward a positive savings target.

    ``target_amount`` is strictly positive and ``saved_amount`` is non-negative
    (it defaults to zero). :attr:`progress` is the exact ``saved / target``
    ratio and may exceed one once the goal is over-funded.
    """

    goal_id: str
    name: str = Field(min_length=1)
    target_amount: DecimalValue = Field(gt=Decimal(0))
    saved_amount: DecimalValue = Decimal(0)
    target_date: date | None = None

    @field_validator("saved_amount")
    @classmethod
    def _non_negative_saved(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("saved_amount must be non-negative")
        return value

    @property
    def progress(self) -> Decimal:
        """Exact ``saved_amount / target_amount`` ratio.

        ``target_amount`` is guaranteed positive at construction, so this never
        divides by zero.
        """
        return checked_div(self.saved_amount, self.target_amount)


class BudgetVariance(StrixModel):
    """The outcome of scoring one category's actual spend against its budget.

    ``variance`` is ``limit - actual``: a negative variance means the category
    overspent its limit, mirrored by ``over_budget``.
    """

    category: str
    limit: DecimalValue
    actual: DecimalValue
    variance: DecimalValue
    over_budget: bool


def compute_variances(
    budgets: Sequence[CategoryBudget],
    actuals: Mapping[str, Decimal],
) -> tuple[BudgetVariance, ...]:
    """Score each budget against actual spend, preserving ``budgets`` order.

    A category absent from ``actuals`` is treated as zero spend. Each actual is
    coerced exactly (binary ``float`` is rejected); a negative actual is not a
    valid spend total and raises :class:`BudgetError`. The variance
    (``limit - actual``) and the ``over_budget`` flag are exact.
    """
    results: list[BudgetVariance] = []
    for budget in budgets:
        raw = actuals.get(budget.category, Decimal(0))
        actual = as_decimal(raw)
        if actual < 0:
            raise BudgetError(
                f"actual spend for {budget.category!r} must be non-negative, "
                f"got {actual}"
            )
        variance = checked_sub(budget.monthly_limit, actual)
        results.append(
            BudgetVariance(
                category=budget.category,
                limit=budget.monthly_limit,
                actual=actual,
                variance=variance,
                over_budget=variance < 0,
            )
        )
    return tuple(results)


def cash_flow_projection(
    opening: Decimal,
    recurring_in: Sequence[Decimal],
    recurring_out: Sequence[Decimal],
    months: int,
) -> tuple[Decimal, ...]:
    """Project end-of-month balances for a fixed net monthly flow.

    The net monthly flow is ``sum(recurring_in) - sum(recurring_out)``; the
    returned tuple holds the balance at the end of each of ``months`` months,
    starting from ``opening``. Every amount is coerced exactly (binary
    ``float`` is rejected) and accumulated with exact Decimal arithmetic.

    Raises :class:`BudgetError` if ``months`` is not strictly positive.
    """
    if months <= 0:
        raise BudgetError(f"months must be a positive integer, got {months}")
    opening_balance = as_decimal(opening)
    inflows = [as_decimal(value) for value in recurring_in]
    outflows = [as_decimal(value) for value in recurring_out]
    total_in = checked_sum(inflows) if inflows else Decimal(0)
    total_out = checked_sum(outflows) if outflows else Decimal(0)
    net = checked_sub(total_in, total_out)
    balances: list[Decimal] = []
    balance = opening_balance
    for _ in range(months):
        balance = checked_sum([balance, net])
        balances.append(balance)
    return tuple(balances)
