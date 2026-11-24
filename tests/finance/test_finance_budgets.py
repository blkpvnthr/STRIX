"""Tests for category budgeting, savings goals, and cash-flow projection.

These cover the happy paths (exact budget variance including the over-budget
flag, savings-goal progress, an N-month cash-flow projection), the invariants
(a category with no recorded spend scores an actual of zero, results are exact
Decimal and deterministic), and the adversarial edges (a non-positive limit or
target, a negative saved amount, a negative actual, a non-positive month count,
a malformed period, and binary ``float`` are all rejected).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.errors import StrixError
from strix.finance.budgets import (
    BudgetError,
    BudgetVariance,
    CategoryBudget,
    SavingsGoal,
    cash_flow_projection,
    compute_variances,
)

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _budget(category: str, limit: str, period: str = "2026-01") -> CategoryBudget:
    return CategoryBudget(
        category=category, monthly_limit=Decimal(limit), period=period
    )


# --------------------------------------------------------------------------
# CategoryBudget model
# --------------------------------------------------------------------------


def test_category_budget_holds_exact_fields() -> None:
    budget = _budget("groceries", "500.00")
    assert budget.category == "groceries"
    assert budget.monthly_limit == Decimal("500.00")
    assert budget.period == "2026-01"


@pytest.mark.parametrize("limit", ["0", "-1", "-0.01"])
def test_category_budget_rejects_non_positive_limit(limit: str) -> None:
    with pytest.raises(ValidationError):
        _budget("groceries", limit)


def test_category_budget_rejects_float_limit() -> None:
    with pytest.raises(ValidationError):
        CategoryBudget(
            category="groceries",
            monthly_limit=500.0,
            period="2026-01",
        )


@pytest.mark.parametrize("period", ["2026-1", "2026/01", "2026-13", "2026-00", "jan"])
def test_category_budget_rejects_malformed_period(period: str) -> None:
    with pytest.raises(ValidationError):
        _budget("groceries", "500", period)


def test_category_budget_is_frozen_and_closed() -> None:
    budget = _budget("groceries", "500")
    with pytest.raises(ValidationError):
        budget.monthly_limit = Decimal("600")  # type: ignore[misc]
    with pytest.raises(ValidationError):
        CategoryBudget(
            category="groceries",
            monthly_limit=Decimal("500"),
            period="2026-01",
            unexpected="x",  # type: ignore[call-arg]
        )


# --------------------------------------------------------------------------
# SavingsGoal model
# --------------------------------------------------------------------------


def test_savings_goal_progress_is_exact_ratio() -> None:
    goal = SavingsGoal(
        goal_id="G1",
        name="Emergency fund",
        target_amount=Decimal("1000"),
        saved_amount=Decimal("250"),
    )
    assert goal.progress == Decimal("0.25")


def test_savings_goal_default_saved_is_zero_progress() -> None:
    goal = SavingsGoal(
        goal_id="G1", name="Vacation", target_amount=Decimal("2000")
    )
    assert goal.saved_amount == Decimal(0)
    assert goal.progress == Decimal(0)
    assert goal.target_date is None


def test_savings_goal_progress_can_exceed_one() -> None:
    goal = SavingsGoal(
        goal_id="G1",
        name="Overshoot",
        target_amount=Decimal("100"),
        saved_amount=Decimal("150"),
    )
    assert goal.progress == Decimal("1.5")


def test_savings_goal_accepts_target_date() -> None:
    goal = SavingsGoal(
        goal_id="G1",
        name="House",
        target_amount=Decimal("50000"),
        target_date=date(2027, 12, 31),
    )
    assert goal.target_date == date(2027, 12, 31)


@pytest.mark.parametrize("target", ["0", "-1"])
def test_savings_goal_rejects_non_positive_target(target: str) -> None:
    with pytest.raises(ValidationError):
        SavingsGoal(goal_id="G1", name="n", target_amount=Decimal(target))


def test_savings_goal_rejects_negative_saved() -> None:
    with pytest.raises(ValidationError):
        SavingsGoal(
            goal_id="G1",
            name="n",
            target_amount=Decimal("100"),
            saved_amount=Decimal("-1"),
        )


def test_savings_goal_rejects_float_amounts() -> None:
    with pytest.raises(ValidationError):
        SavingsGoal(
            goal_id="G1",
            name="n",
            target_amount=100.0,
        )


# --------------------------------------------------------------------------
# compute_variances
# --------------------------------------------------------------------------


def test_compute_variances_under_budget() -> None:
    budgets = [_budget("groceries", "500")]
    (variance,) = compute_variances(budgets, {"groceries": Decimal("320.50")})
    assert variance == BudgetVariance(
        category="groceries",
        limit=Decimal("500"),
        actual=Decimal("320.50"),
        variance=Decimal("179.50"),
        over_budget=False,
    )


def test_compute_variances_over_budget_flag_and_negative_variance() -> None:
    budgets = [_budget("dining", "200")]
    (variance,) = compute_variances(budgets, {"dining": Decimal("275.25")})
    assert variance.variance == Decimal("-75.25")
    assert variance.over_budget is True


def test_compute_variances_exactly_at_limit_is_not_over_budget() -> None:
    budgets = [_budget("rent", "1500")]
    (variance,) = compute_variances(budgets, {"rent": Decimal("1500")})
    assert variance.variance == Decimal("0")
    assert variance.over_budget is False


def test_compute_variances_missing_category_scores_zero_actual() -> None:
    budgets = [_budget("travel", "800")]
    (variance,) = compute_variances(budgets, {})
    assert variance.actual == Decimal("0")
    assert variance.variance == Decimal("800")
    assert variance.over_budget is False


def test_compute_variances_preserves_budget_order() -> None:
    budgets = [
        _budget("a", "100"),
        _budget("b", "200"),
        _budget("c", "300"),
    ]
    actuals = {"a": Decimal("10"), "b": Decimal("20"), "c": Decimal("30")}
    result = compute_variances(budgets, actuals)
    assert [v.category for v in result] == ["a", "b", "c"]


def test_compute_variances_is_deterministic() -> None:
    budgets = [_budget("groceries", "500"), _budget("dining", "200")]
    actuals = {"groceries": Decimal("450"), "dining": Decimal("210")}
    assert compute_variances(budgets, actuals) == compute_variances(
        budgets, actuals
    )


def test_compute_variances_empty_budgets_is_empty_tuple() -> None:
    assert compute_variances([], {"x": Decimal("5")}) == ()


def test_compute_variances_rejects_negative_actual() -> None:
    budgets = [_budget("groceries", "500")]
    with pytest.raises(BudgetError):
        compute_variances(budgets, {"groceries": Decimal("-1")})


def test_compute_variances_rejects_float_actual() -> None:
    budgets = [_budget("groceries", "500")]
    with pytest.raises(StrixError):
        compute_variances(budgets, {"groceries": 320.0})  # type: ignore[dict-item]


def test_compute_variances_exact_for_large_magnitudes() -> None:
    budgets = [_budget("capex", "100000000000000.01")]
    (variance,) = compute_variances(
        budgets, {"capex": Decimal("0.01")}
    )
    assert variance.variance == Decimal("100000000000000.00")


# --------------------------------------------------------------------------
# cash_flow_projection
# --------------------------------------------------------------------------


def test_cash_flow_projection_accumulates_net_each_month() -> None:
    projection = cash_flow_projection(
        opening=Decimal("1000"),
        recurring_in=[Decimal("500"), Decimal("250")],
        recurring_out=[Decimal("300")],
        months=3,
    )
    # net = 750 - 300 = 450 per month.
    assert projection == (Decimal("1450"), Decimal("1900"), Decimal("2350"))


def test_cash_flow_projection_single_month() -> None:
    projection = cash_flow_projection(
        opening=Decimal("0"),
        recurring_in=[Decimal("100")],
        recurring_out=[],
        months=1,
    )
    assert projection == (Decimal("100"),)


def test_cash_flow_projection_net_negative_draws_down() -> None:
    projection = cash_flow_projection(
        opening=Decimal("500"),
        recurring_in=[],
        recurring_out=[Decimal("200")],
        months=2,
    )
    assert projection == (Decimal("300"), Decimal("100"))


def test_cash_flow_projection_flat_when_no_flows() -> None:
    projection = cash_flow_projection(
        opening=Decimal("750"),
        recurring_in=[],
        recurring_out=[],
        months=4,
    )
    assert projection == (
        Decimal("750"),
        Decimal("750"),
        Decimal("750"),
        Decimal("750"),
    )


def test_cash_flow_projection_is_exact_with_cents() -> None:
    projection = cash_flow_projection(
        opening=Decimal("0.00"),
        recurring_in=[Decimal("0.10")],
        recurring_out=[Decimal("0.03")],
        months=3,
    )
    assert projection == (Decimal("0.07"), Decimal("0.14"), Decimal("0.21"))


def test_cash_flow_projection_is_deterministic() -> None:
    kwargs = {
        "opening": Decimal("1000"),
        "recurring_in": [Decimal("500")],
        "recurring_out": [Decimal("100")],
        "months": 5,
    }
    assert cash_flow_projection(**kwargs) == cash_flow_projection(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("months", [0, -1])
def test_cash_flow_projection_rejects_non_positive_months(months: int) -> None:
    with pytest.raises(BudgetError):
        cash_flow_projection(
            opening=Decimal("0"),
            recurring_in=[],
            recurring_out=[],
            months=months,
        )


def test_cash_flow_projection_rejects_float_opening() -> None:
    with pytest.raises(StrixError):
        cash_flow_projection(
            opening=1000.0,  # type: ignore[arg-type]
            recurring_in=[],
            recurring_out=[],
            months=1,
        )


def test_cash_flow_projection_rejects_float_flow() -> None:
    with pytest.raises(StrixError):
        cash_flow_projection(
            opening=Decimal("0"),
            recurring_in=[500.0],  # type: ignore[list-item]
            recurring_out=[],
            months=1,
        )


def test_budget_error_is_strix_error() -> None:
    assert issubclass(BudgetError, StrixError)
