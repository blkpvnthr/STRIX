"""Contract tests for strix.native.statistics — descriptive statistics (R1).

Every public function is deterministic exact-Decimal arithmetic built on
:mod:`strix.native.arithmetic`: ``float`` is forbidden, NaN/Inf rejected,
results quantized to :data:`strix.native.arithmetic.STAT_QUANTUM`, and invalid
inputs raise :class:`strix.errors.CalculationError`.

Each function carries (a) at least one hand-computed known-value assertion and,
where a stdlib analogue exists, (b) a cross-check against Python's ``statistics``
module using a *relative* tolerance.
"""

from __future__ import annotations

import statistics
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.errors import CalculationError
from strix.native import statistics as S
from strix.native.arithmetic import STAT_QUANTUM

# A reusable asymmetric sample with an exact population std of 2.
SAMPLE = [2, 4, 4, 4, 5, 5, 7, 9]


def _rel_close(dec_value: Decimal, stdlib_value: float, tol: float = 1e-9) -> bool:
    """Relative-tolerance comparison of a Decimal result against a stdlib float."""
    dec_float = float(dec_value)
    return abs(dec_float - stdlib_value) / max(1.0, abs(stdlib_value)) < tol


class TestMean:
    def test_hand_computed(self) -> None:
        assert S.mean([2, 4, 4, 4, 5, 5, 7, 9]) == Decimal("5")

    def test_cross_check_stdlib(self) -> None:
        data = ["1.5", "2.25", "3.125", "10", "-4"]
        assert _rel_close(S.mean(data), statistics.mean([1.5, 2.25, 3.125, 10, -4]))

    def test_single_value(self) -> None:
        assert S.mean(["7.5"]) == Decimal("7.5")

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            S.mean([1.0, 2.0])

    def test_rejects_nan(self) -> None:
        with pytest.raises(CalculationError):
            S.mean([Decimal("NaN"), Decimal("1")])

    def test_rejects_empty(self) -> None:
        with pytest.raises(CalculationError):
            S.mean([])


class TestWeightedMean:
    def test_hand_computed(self) -> None:
        # (1*1 + 2*2 + 3*3) / (1+2+3) = 14/6
        assert S.weighted_mean([1, 2, 3], [1, 2, 3]) == Decimal("2.333333333333")

    def test_equal_weights_matches_mean(self) -> None:
        assert S.weighted_mean([2, 4, 6], [1, 1, 1]) == S.mean([2, 4, 6])

    def test_length_mismatch(self) -> None:
        with pytest.raises(CalculationError):
            S.weighted_mean([1, 2, 3], [1, 2])

    def test_zero_weight_sum(self) -> None:
        with pytest.raises(CalculationError):
            S.weighted_mean([1, 2], [1, -1])

    def test_empty(self) -> None:
        with pytest.raises(CalculationError):
            S.weighted_mean([], [])


class TestMedian:
    def test_odd_hand_computed(self) -> None:
        assert S.median([3, 1, 2]) == Decimal("2")

    def test_even_hand_computed(self) -> None:
        assert S.median([1, 2, 3, 4]) == Decimal("2.5")

    def test_cross_check_odd(self) -> None:
        data = [5, 1, 9, 3, 7]
        assert _rel_close(S.median(data), statistics.median([5, 1, 9, 3, 7]))

    def test_cross_check_even(self) -> None:
        data = [5, 1, 9, 3, 7, 11]
        assert _rel_close(S.median(data), statistics.median([5, 1, 9, 3, 7, 11]))

    def test_empty(self) -> None:
        with pytest.raises(CalculationError):
            S.median([])


class TestQuantile:
    def test_hand_computed_quartiles(self) -> None:
        data = [1, 2, 3, 4, 5]
        assert S.quantile(data, "0.25") == Decimal("2")
        assert S.quantile(data, "0.5") == Decimal("3")
        assert S.quantile(data, "0.75") == Decimal("4")

    def test_hand_computed_interpolated(self) -> None:
        # h = (4-1)*0.5 = 1.5 -> 2 + 0.5*(3-2) = 2.5
        assert S.quantile([1, 2, 3, 4], "0.5") == Decimal("2.5")

    def test_bounds(self) -> None:
        data = [10, 20, 30]
        assert S.quantile(data, 0) == Decimal("10")
        assert S.quantile(data, 1) == Decimal("30")

    def test_cross_check_stdlib_inclusive(self) -> None:
        data = [7, 2, 11, 5, 3, 9, 1, 8]
        fdata = [float(x) for x in data]
        q25, q50, q75 = statistics.quantiles(fdata, n=4, method="inclusive")
        assert _rel_close(S.quantile(data, "0.25"), q25)
        assert _rel_close(S.quantile(data, "0.5"), q50)
        assert _rel_close(S.quantile(data, "0.75"), q75)

    def test_out_of_range(self) -> None:
        with pytest.raises(CalculationError):
            S.quantile([1, 2, 3], "1.5")
        with pytest.raises(CalculationError):
            S.quantile([1, 2, 3], "-0.1")

    def test_empty(self) -> None:
        with pytest.raises(CalculationError):
            S.quantile([], "0.5")

    def test_rejects_float_q(self) -> None:
        with pytest.raises(CalculationError):
            S.quantile([1, 2, 3], 0.5)


class TestPercentile:
    def test_hand_computed(self) -> None:
        data = [1, 2, 3, 4, 5]
        assert S.percentile(data, 25) == Decimal("2")
        assert S.percentile(data, 75) == Decimal("4")

    def test_matches_quantile(self) -> None:
        data = [7, 2, 11, 5, 3]
        assert S.percentile(data, 50) == S.quantile(data, "0.5")

    def test_out_of_range(self) -> None:
        with pytest.raises(CalculationError):
            S.percentile([1, 2, 3], 150)


class TestVariance:
    def test_sample_hand_computed(self) -> None:
        # sum sq dev = 32, n-1 = 7 -> 32/7 = 4.571428571428... -> quantized
        assert S.variance(SAMPLE) == Decimal("4.571428571429")

    def test_population_hand_computed(self) -> None:
        assert S.variance(SAMPLE, sample=False) == Decimal("4")

    def test_cross_check_sample(self) -> None:
        fdata = [float(x) for x in SAMPLE]
        assert _rel_close(S.variance(SAMPLE), statistics.variance(fdata))

    def test_cross_check_population(self) -> None:
        fdata = [float(x) for x in SAMPLE]
        assert _rel_close(S.variance(SAMPLE, sample=False), statistics.pvariance(fdata))

    def test_sample_needs_two(self) -> None:
        with pytest.raises(CalculationError):
            S.variance([5])

    def test_population_single_ok(self) -> None:
        assert S.variance([5], sample=False) == Decimal("0")

    def test_empty(self) -> None:
        with pytest.raises(CalculationError):
            S.variance([], sample=False)


class TestStdev:
    def test_population_hand_computed(self) -> None:
        assert S.stdev(SAMPLE, sample=False) == Decimal("2")

    def test_cross_check_sample(self) -> None:
        fdata = [float(x) for x in SAMPLE]
        assert _rel_close(S.stdev(SAMPLE), statistics.stdev(fdata))

    def test_cross_check_population(self) -> None:
        fdata = [float(x) for x in SAMPLE]
        assert _rel_close(S.stdev(SAMPLE, sample=False), statistics.pstdev(fdata))

    def test_sample_needs_two(self) -> None:
        with pytest.raises(CalculationError):
            S.stdev([5])


class TestMad:
    def test_hand_computed(self) -> None:
        # median([1,2,3,4,5]) = 3; abs devs [2,1,0,1,2]; median = 1
        assert S.mad([1, 2, 3, 4, 5]) == Decimal("1")

    def test_empty(self) -> None:
        with pytest.raises(CalculationError):
            S.mad([])


class TestIqr:
    def test_hand_computed(self) -> None:
        assert S.iqr([1, 2, 3, 4, 5]) == Decimal("2")

    def test_empty(self) -> None:
        with pytest.raises(CalculationError):
            S.iqr([])


class TestExtremes:
    def test_minimum(self) -> None:
        assert S.minimum([3, 1, 2, 9, -4]) == Decimal("-4")

    def test_maximum(self) -> None:
        assert S.maximum([3, 1, 2, 9, -4]) == Decimal("9")

    def test_range(self) -> None:
        assert S.data_range([3, 1, 2, 9, -4]) == Decimal("13")

    def test_min_empty(self) -> None:
        with pytest.raises(CalculationError):
            S.minimum([])

    def test_max_empty(self) -> None:
        with pytest.raises(CalculationError):
            S.maximum([])

    def test_range_empty(self) -> None:
        with pytest.raises(CalculationError):
            S.data_range([])


class TestSkewness:
    def test_symmetric_is_zero(self) -> None:
        assert S.skewness([1, 2, 3, 4, 5]) == Decimal("0")

    def test_hand_computed(self) -> None:
        # dev cubes: -27,-1,-1,-1,0,0,8,64 -> sum 42; m3 = 42/8 = 5.25;
        # stdev_pop^3 = 2^3 = 8; g1 = 5.25/8 = 0.65625
        assert S.skewness(SAMPLE) == Decimal("0.65625")

    def test_needs_three(self) -> None:
        with pytest.raises(CalculationError):
            S.skewness([1, 2])

    def test_constant_undefined(self) -> None:
        with pytest.raises(CalculationError):
            S.skewness([4, 4, 4, 4])


class TestKurtosis:
    def test_excess_hand_computed(self) -> None:
        # m4 = (1/8)*356 = 44.5; stdev_pop^4 = 16; 44.5/16 = 2.78125; -3 = -0.21875
        assert S.kurtosis(SAMPLE) == Decimal("-0.21875")

    def test_non_excess_hand_computed(self) -> None:
        assert S.kurtosis(SAMPLE, excess=False) == Decimal("2.78125")

    def test_needs_four(self) -> None:
        with pytest.raises(CalculationError):
            S.kurtosis([1, 2, 3])

    def test_constant_undefined(self) -> None:
        with pytest.raises(CalculationError):
            S.kurtosis([4, 4, 4, 4, 4])


class TestCoverage:
    def test_hand_computed(self) -> None:
        assert S.coverage([1, None, 3, None]) == Decimal("0.5")

    def test_full_coverage(self) -> None:
        assert S.coverage([1, 2, 3]) == Decimal("1")

    def test_empty(self) -> None:
        with pytest.raises(CalculationError):
            S.coverage([])

    def test_rejects_float_present_value(self) -> None:
        with pytest.raises(CalculationError):
            S.coverage([1.0, None])


class TestDescribe:
    def test_fields_hand_computed(self) -> None:
        summary = S.describe([1, 2, 3, 4, 5])
        assert summary.n == 5
        assert summary.mean == Decimal("3")
        assert summary.median == Decimal("3")
        assert summary.minimum == Decimal("1")
        assert summary.maximum == Decimal("5")
        assert summary.q1 == Decimal("2")
        assert summary.q3 == Decimal("4")

    def test_is_frozen(self) -> None:
        summary = S.describe([1, 2, 3, 4, 5])
        with pytest.raises(ValidationError):
            summary.n = 99  # type: ignore[misc]

    def test_stdev_matches_function(self) -> None:
        summary = S.describe(SAMPLE)
        assert summary.stdev == S.stdev(SAMPLE)

    def test_needs_two(self) -> None:
        with pytest.raises(CalculationError):
            S.describe([5])


class TestQuantization:
    def test_scalar_results_are_quantized(self) -> None:
        result = S.mean([1, 2])
        assert result == result.quantize(STAT_QUANTUM)
