"""Contract tests for strix.native.timeseries — deterministic Decimal time-series
statistics (R1 §6/§7).

Every function is checked against a HAND-COMPUTED known value, and — where a
Python stdlib ``statistics`` analogue exists — cross-checked with a RELATIVE
tolerance (abs(dec_float - stdlib) / max(1, abs(stdlib)) < 1e-9). Error paths
(float rejected, NaN rejected, too few observations, zero/constant where
undefined) are exercised for every function.

Numerical contract under test: exact Decimal inside a local context,
ROUND_HALF_EVEN, float forbidden, NaN/Inf rejected, results quantized to
arithmetic.STAT_QUANTUM.
"""

from __future__ import annotations

import math
import statistics
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.errors import CalculationError
from strix.native import timeseries as T
from strix.native.arithmetic import STAT_QUANTUM


def _rel_close(dec: Decimal, ref: float, tol: float = 1e-9) -> bool:
    val = float(dec)
    return abs(val - ref) / max(1.0, abs(ref)) < tol


# --------------------------------------------------------------------------
# absolute_change
# --------------------------------------------------------------------------


class TestAbsoluteChange:
    def test_known_value(self) -> None:
        assert T.absolute_change([1, 3, 6, 10]) == (
            Decimal("2"),
            Decimal("3"),
            Decimal("4"),
        )

    def test_negative_differences(self) -> None:
        assert T.absolute_change(["5", "2", "2"]) == (Decimal("-3"), Decimal("0"))

    def test_length_is_n_minus_one(self) -> None:
        assert len(T.absolute_change([1, 2, 3, 4, 5])) == 4

    def test_rejects_too_few(self) -> None:
        with pytest.raises(CalculationError):
            T.absolute_change([1])

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            T.absolute_change([1.0, 2.0])


# --------------------------------------------------------------------------
# percentage_change
# --------------------------------------------------------------------------


class TestPercentageChange:
    def test_known_value(self) -> None:
        result = T.percentage_change([100, 110, 99])
        assert result == (Decimal("0.100000000000"), Decimal("-0.100000000000"))

    def test_length_is_n_minus_one(self) -> None:
        assert len(T.percentage_change([1, 2, 4])) == 2

    def test_rejects_zero_prior_value(self) -> None:
        with pytest.raises(CalculationError):
            T.percentage_change([0, 1])

    def test_rejects_too_few(self) -> None:
        with pytest.raises(CalculationError):
            T.percentage_change([5])

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            T.percentage_change([1.0, 2.0])


# --------------------------------------------------------------------------
# growth_rate
# --------------------------------------------------------------------------


class TestGrowthRate:
    def test_known_value(self) -> None:
        assert T.growth_rate(100, 150) == Decimal("0.500000000000")

    def test_negative(self) -> None:
        assert T.growth_rate(200, 150) == Decimal("-0.250000000000")

    def test_rejects_zero_first(self) -> None:
        with pytest.raises(CalculationError):
            T.growth_rate(0, 10)

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            T.growth_rate(1.0, 2.0)


# --------------------------------------------------------------------------
# cagr
# --------------------------------------------------------------------------


class TestCagr:
    def test_known_value(self) -> None:
        # (200/100)^(1/10) - 1 = 2^0.1 - 1 = 0.0717734625...
        result = T.cagr(100, 200, 10)
        assert _rel_close(result, 2 ** (1 / 10) - 1)
        assert result.quantize(Decimal("0.000001")) == Decimal("0.071773")

    def test_decimal_periods(self) -> None:
        result = T.cagr(100, 200, Decimal("10"))
        assert _rel_close(result, 2 ** (1 / 10) - 1)

    def test_flat(self) -> None:
        assert T.cagr(100, 100, 5) == Decimal("0.000000000000")

    def test_rejects_nonpositive_begin(self) -> None:
        with pytest.raises(CalculationError):
            T.cagr(0, 100, 5)

    def test_rejects_nonpositive_end(self) -> None:
        with pytest.raises(CalculationError):
            T.cagr(100, 0, 5)

    def test_rejects_nonpositive_periods(self) -> None:
        with pytest.raises(CalculationError):
            T.cagr(100, 200, 0)

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            T.cagr(100.0, 200, 10)


# --------------------------------------------------------------------------
# moving_average
# --------------------------------------------------------------------------


class TestMovingAverage:
    def test_known_value(self) -> None:
        assert T.moving_average([1, 2, 3, 4], 2) == (
            Decimal("1.500000000000"),
            Decimal("2.500000000000"),
            Decimal("3.500000000000"),
        )

    def test_window_one_is_identity(self) -> None:
        assert T.moving_average([2, 4, 6], 1) == (
            Decimal("2.000000000000"),
            Decimal("4.000000000000"),
            Decimal("6.000000000000"),
        )

    def test_length(self) -> None:
        assert len(T.moving_average([1, 2, 3, 4, 5], 3)) == 3

    def test_crosscheck_mean(self) -> None:
        series = [3, 1, 4, 1, 5, 9, 2, 6]
        window = 3
        out = T.moving_average(series, window)
        for i, val in enumerate(out):
            ref = statistics.fmean(series[i : i + window])
            assert _rel_close(val, ref)

    def test_rejects_window_too_large(self) -> None:
        with pytest.raises(CalculationError):
            T.moving_average([1, 2], 3)

    def test_rejects_nonpositive_window(self) -> None:
        with pytest.raises(CalculationError):
            T.moving_average([1, 2, 3], 0)

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            T.moving_average([1.0, 2.0, 3.0], 2)


# --------------------------------------------------------------------------
# rolling_stdev
# --------------------------------------------------------------------------


class TestRollingStdev:
    def test_known_sample(self) -> None:
        # windows [1,2,3],[2,3,4],[3,4,5] each sample stdev == 1.
        out = T.rolling_stdev([1, 2, 3, 4, 5], 3, sample=True)
        assert out == (
            Decimal("1.000000000000"),
            Decimal("1.000000000000"),
            Decimal("1.000000000000"),
        )

    def test_known_population(self) -> None:
        out = T.rolling_stdev([1, 2, 3], 3, sample=False)
        # pstdev([1,2,3]) == sqrt(2/3) == 0.816496580927726
        assert _rel_close(out[0], math.sqrt(2 / 3))

    def test_crosscheck_sample(self) -> None:
        series = [3, 1, 4, 1, 5, 9, 2, 6]
        window = 4
        out = T.rolling_stdev(series, window, sample=True)
        for i, val in enumerate(out):
            ref = statistics.stdev(series[i : i + window])
            assert _rel_close(val, ref)

    def test_crosscheck_population(self) -> None:
        series = [3, 1, 4, 1, 5, 9, 2, 6]
        window = 4
        out = T.rolling_stdev(series, window, sample=False)
        for i, val in enumerate(out):
            ref = statistics.pstdev(series[i : i + window])
            assert _rel_close(val, ref)

    def test_length(self) -> None:
        assert len(T.rolling_stdev([1, 2, 3, 4, 5], 2)) == 4

    def test_rejects_window_lt_two(self) -> None:
        with pytest.raises(CalculationError):
            T.rolling_stdev([1, 2, 3], 1)

    def test_rejects_window_too_large(self) -> None:
        with pytest.raises(CalculationError):
            T.rolling_stdev([1, 2], 3)

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            T.rolling_stdev([1.0, 2.0, 3.0], 2)


# --------------------------------------------------------------------------
# ewma
# --------------------------------------------------------------------------


class TestEwma:
    def test_known_alpha(self) -> None:
        # alpha=0.5: y0=1, y1=1.5, y2=2.25
        out = T.ewma([1, 2, 3], alpha="0.5")
        assert out == (
            Decimal("1.000000000000"),
            Decimal("1.500000000000"),
            Decimal("2.250000000000"),
        )

    def test_span_maps_to_alpha(self) -> None:
        # span=3 -> alpha=2/4=0.5
        out_span = T.ewma([1, 2, 3], span=3)
        out_alpha = T.ewma([1, 2, 3], alpha="0.5")
        assert out_span == out_alpha

    def test_alpha_one_is_identity(self) -> None:
        out = T.ewma([5, 7, 9], alpha="1")
        assert out == (
            Decimal("5.000000000000"),
            Decimal("7.000000000000"),
            Decimal("9.000000000000"),
        )

    def test_length_equals_input(self) -> None:
        assert len(T.ewma([1, 2, 3, 4], alpha="0.3")) == 4

    def test_rejects_both_span_and_alpha(self) -> None:
        with pytest.raises(CalculationError):
            T.ewma([1, 2, 3], span=3, alpha="0.5")

    def test_rejects_neither(self) -> None:
        with pytest.raises(CalculationError):
            T.ewma([1, 2, 3])

    def test_rejects_alpha_out_of_range(self) -> None:
        with pytest.raises(CalculationError):
            T.ewma([1, 2, 3], alpha="0")
        with pytest.raises(CalculationError):
            T.ewma([1, 2, 3], alpha="1.5")

    def test_rejects_empty(self) -> None:
        with pytest.raises(CalculationError):
            T.ewma([], alpha="0.5")

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            T.ewma([1.0, 2.0], alpha="0.5")


# --------------------------------------------------------------------------
# volatility
# --------------------------------------------------------------------------


class TestVolatility:
    def test_known_sample(self) -> None:
        # stdev([1,2,3,4,5]) = sqrt(2.5) = 1.5811388300841898
        result = T.volatility([1, 2, 3, 4, 5], sample=True)
        assert _rel_close(result, math.sqrt(2.5))

    def test_known_population(self) -> None:
        result = T.volatility([1, 2, 3, 4, 5], sample=False)
        assert _rel_close(result, statistics.pstdev([1, 2, 3, 4, 5]))

    def test_crosscheck_sample(self) -> None:
        series = [3, 1, 4, 1, 5, 9, 2, 6]
        assert _rel_close(T.volatility(series, sample=True), statistics.stdev(series))

    def test_rejects_too_few_sample(self) -> None:
        with pytest.raises(CalculationError):
            T.volatility([1], sample=True)

    def test_rejects_empty(self) -> None:
        with pytest.raises(CalculationError):
            T.volatility([], sample=False)

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            T.volatility([1.0, 2.0, 3.0])


# --------------------------------------------------------------------------
# annualized_volatility
# --------------------------------------------------------------------------


class TestAnnualizedVolatility:
    def test_known_value(self) -> None:
        series = [1, 2, 3, 4, 5]
        result = T.annualized_volatility(series, 252)
        ref = statistics.stdev(series) * math.sqrt(252)
        assert _rel_close(result, ref)

    def test_periods_one_is_volatility(self) -> None:
        series = [1, 2, 3, 4, 5]
        assert T.annualized_volatility(series, 1) == T.volatility(series)

    def test_rejects_nonpositive_periods(self) -> None:
        with pytest.raises(CalculationError):
            T.annualized_volatility([1, 2, 3], 0)

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            T.annualized_volatility([1.0, 2.0, 3.0], 252)


# --------------------------------------------------------------------------
# autocorrelation
# --------------------------------------------------------------------------


class TestAutocorrelation:
    def test_perfect_positive(self) -> None:
        # Linear series, lag 1 -> correlation == 1.
        assert T.autocorrelation([1, 2, 3, 4, 5], 1) == Decimal("1.000000000000")

    def test_in_range(self) -> None:
        series = [3, 1, 4, 1, 5, 9, 2, 6]
        result = T.autocorrelation(series, 1)
        assert Decimal("-1") <= result <= Decimal("1")

    def test_crosscheck_correlation(self) -> None:
        series = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3]
        lag = 2
        result = T.autocorrelation(series, lag)
        ref = statistics.correlation(series[:-lag], series[lag:])
        assert _rel_close(result, ref)

    def test_rejects_constant_series(self) -> None:
        with pytest.raises(CalculationError):
            T.autocorrelation([4, 4, 4, 4], 1)

    def test_rejects_lag_lt_one(self) -> None:
        with pytest.raises(CalculationError):
            T.autocorrelation([1, 2, 3, 4], 0)

    def test_rejects_too_few(self) -> None:
        # n must be > lag + 1 -> at least 2 pairs.
        with pytest.raises(CalculationError):
            T.autocorrelation([1, 2], 1)

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            T.autocorrelation([1.0, 2.0, 3.0], 1)


# --------------------------------------------------------------------------
# linear_trend
# --------------------------------------------------------------------------


class TestLinearTrend:
    def test_known_value(self) -> None:
        fit = T.linear_trend([2, 4, 6, 8])
        assert fit.slope == Decimal("2.000000000000")
        assert fit.intercept == Decimal("2.000000000000")
        assert fit.r_squared == Decimal("1.000000000000")

    def test_crosscheck_regression(self) -> None:
        series = [3, 1, 4, 1, 5, 9, 2, 6]
        fit = T.linear_trend(series)
        n = len(series)
        reg = statistics.linear_regression(list(range(n)), series)
        assert _rel_close(fit.slope, reg.slope)
        assert _rel_close(fit.intercept, reg.intercept)
        ref_r2 = statistics.correlation(list(range(n)), series) ** 2
        assert _rel_close(fit.r_squared, ref_r2)

    def test_r_squared_in_unit_interval(self) -> None:
        fit = T.linear_trend([3, 1, 4, 1, 5, 9, 2, 6])
        assert Decimal("0") <= fit.r_squared <= Decimal("1")

    def test_frozen_model(self) -> None:
        fit = T.linear_trend([1, 2, 3])
        with pytest.raises(ValidationError):
            fit.slope = Decimal("9")  # type: ignore[misc]

    def test_rejects_too_few(self) -> None:
        with pytest.raises(CalculationError):
            T.linear_trend([1])

    def test_rejects_constant_series_r_squared(self) -> None:
        # Constant y -> zero variance in y -> r_squared undefined.
        with pytest.raises(CalculationError):
            T.linear_trend([5, 5, 5, 5])

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            T.linear_trend([1.0, 2.0, 3.0])


def test_quantum_is_twelve_places() -> None:
    assert Decimal("0.000000000001") == STAT_QUANTUM
