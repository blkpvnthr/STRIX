"""Tests for deterministic agent calculators (exact Decimal, known values)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from strix.agent import calculations as calc
from strix.agent.models import CalculationMethod
from strix.errors import CalculationError


def D(*xs: str) -> list[Decimal]:
    return [Decimal(x) for x in xs]


def test_period_return() -> None:
    assert calc.period_return(D("100", "110")) == Decimal("0.100000")
    assert calc.period_return(D("100", "90")) == Decimal("-0.100000")


def test_period_return_requires_positive_start() -> None:
    with pytest.raises(CalculationError, match="positive starting value"):
        calc.period_return(D("0", "10"))


def test_period_return_needs_two_points() -> None:
    with pytest.raises(CalculationError, match="at least 2"):
        calc.period_return(D("100"))


def test_max_drawdown() -> None:
    # peak 120, trough 60 -> -0.5
    assert calc.max_drawdown(D("100", "120", "60", "80")) == Decimal("-0.500000")
    # monotonically rising -> no drawdown
    assert calc.max_drawdown(D("100", "101", "102")) == Decimal("0")


def test_moving_average() -> None:
    assert calc.moving_average(D("1", "2", "3", "4"), window=2) == Decimal("3.500000")
    assert calc.moving_average(D("1", "2", "3", "4"), window=4) == Decimal("2.500000")


def test_moving_average_window_bounds() -> None:
    with pytest.raises(CalculationError, match="window must be positive"):
        calc.moving_average(D("1", "2"), window=0)
    with pytest.raises(CalculationError, match="at least 5"):
        calc.moving_average(D("1", "2"), window=5)


def test_relative_performance() -> None:
    assert calc.relative_performance(D("100", "110"), D("100", "105")) == Decimal("0.050000")


def test_correlation_perfect_positive() -> None:
    # b = 10 * a -> identical simple returns -> correlation 1.
    assert calc.correlation(D("1", "2", "3", "4"), D("10", "20", "30", "40")) == Decimal(
        "1.000000"
    )


def test_correlation_constant_series_rejected() -> None:
    with pytest.raises(CalculationError, match="constant series"):
        calc.correlation(D("5", "5", "5", "5"), D("1", "2", "3", "4"))


def test_correlation_length_mismatch() -> None:
    with pytest.raises(CalculationError, match="equal-length"):
        calc.correlation(D("1", "2", "3"), D("1", "2", "3", "4"))


def test_realized_volatility_zero_for_constant_growth() -> None:
    # Equal period ratios -> equal log returns -> zero dispersion.
    assert calc.realized_volatility(D("100", "110", "121")) == Decimal("0")


def test_realized_volatility_positive_and_deterministic() -> None:
    values = D("100", "110", "99", "105")
    first = calc.realized_volatility(values)
    second = calc.realized_volatility(values)
    assert first == second
    assert first > 0


def test_realized_volatility_rejects_nonpositive_prices() -> None:
    with pytest.raises(CalculationError, match="positive prices"):
        calc.realized_volatility(D("100", "0", "50"))


def test_recompute_dispatch_matches_direct() -> None:
    values = D("100", "110", "99", "105")
    assert calc.recompute(CalculationMethod.PERIOD_RETURN, [values], {}) == calc.period_return(
        values
    )
    assert calc.recompute(CalculationMethod.MAX_DRAWDOWN, [values], {}) == calc.max_drawdown(
        values
    )
    assert calc.recompute(
        CalculationMethod.MOVING_AVERAGE, [values], {"window": "2"}
    ) == calc.moving_average(values, window=2)
    assert calc.recompute(
        CalculationMethod.REALIZED_VOLATILITY, [values], {"periods_per_year": "252"}
    ) == calc.realized_volatility(values, periods_per_year=252)


def test_recompute_two_series() -> None:
    a = D("100", "110")
    b = D("100", "105")
    assert calc.recompute(CalculationMethod.RELATIVE_PERFORMANCE, [a, b], {}) == (
        calc.relative_performance(a, b)
    )


def test_recompute_wrong_series_count() -> None:
    with pytest.raises(CalculationError, match="expects 2 series"):
        calc.recompute(CalculationMethod.CORRELATION, [D("1", "2", "3")], {})


def test_recompute_bad_int_param() -> None:
    with pytest.raises(CalculationError, match="must be an integer"):
        calc.recompute(CalculationMethod.MOVING_AVERAGE, [D("1", "2", "3")], {"window": "two"})
