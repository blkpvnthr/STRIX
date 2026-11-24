"""Contract tests for strix.native.multivariate — exact-Decimal multivariate
statistics (R1 §6/§7).

Every function is exercised with at least one HAND-COMPUTED known value and,
where Python's stdlib ``statistics`` provides an equivalent, a CROSS-CHECK
using a relative tolerance (Decimal -> float). Error paths (float rejected,
NaN rejected, too few observations, unequal length, zero/constant where the
quantity is undefined) are tested throughout.
"""

from __future__ import annotations

import statistics
from decimal import Decimal, getcontext

import pytest
from pydantic import ValidationError

from strix.errors import CalculationError
from strix.native import multivariate as M

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _rel_close(dec_value: Decimal, reference: float, tol: float = 1e-9) -> bool:
    """Relative-tolerance float comparison for stdlib cross-checks."""
    return abs(float(dec_value) - reference) / max(1.0, abs(reference)) < tol


def D(*values: str) -> tuple[Decimal, ...]:
    return tuple(Decimal(v) for v in values)


# ---------------------------------------------------------------------------
# covariance
# ---------------------------------------------------------------------------


class TestCovariance:
    def test_hand_computed_sample(self) -> None:
        # x=[1,2,3] y=[2,4,6]: devs (-1,0,1),(-2,0,2); sum products = 4.
        # sample cov = 4 / (n-1=2) = 2.
        assert M.covariance(D("1", "2", "3"), D("2", "4", "6")) == Decimal(
            "2.000000000000"
        )

    def test_hand_computed_population(self) -> None:
        # population cov = 4 / 3.
        got = M.covariance(D("1", "2", "3"), D("2", "4", "6"), sample=False)
        assert _rel_close(got, 4.0 / 3.0)

    def test_cross_check_statistics_covariance(self) -> None:
        x = ["1.5", "2.25", "3.75", "4.1", "5.9", "0.3"]
        y = ["2.0", "1.0", "6.5", "3.3", "7.7", "0.9"]
        got = M.covariance(tuple(Decimal(v) for v in x), tuple(Decimal(v) for v in y))
        ref = statistics.covariance([float(v) for v in x], [float(v) for v in y])
        assert _rel_close(got, ref)

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            M.covariance([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])  # type: ignore[list-item]

    def test_rejects_nan(self) -> None:
        with pytest.raises(CalculationError):
            M.covariance([Decimal("NaN"), Decimal("2")], [Decimal("1"), Decimal("2")])

    def test_rejects_unequal_length(self) -> None:
        with pytest.raises(CalculationError):
            M.covariance(D("1", "2", "3"), D("1", "2"))

    def test_rejects_too_few_observations(self) -> None:
        with pytest.raises(CalculationError):
            M.covariance(D("1"), D("2"))

    def test_does_not_mutate_global_context(self) -> None:
        before = getcontext().prec
        M.covariance(D("1", "2", "3"), D("2", "4", "6"))
        assert getcontext().prec == before


# ---------------------------------------------------------------------------
# correlation
# ---------------------------------------------------------------------------


class TestCorrelation:
    def test_perfectly_correlated(self) -> None:
        assert M.correlation(D("1", "2", "3"), D("2", "4", "6")) == Decimal(
            "1.000000000000"
        )

    def test_hand_computed_half(self) -> None:
        # x=[1,2,3] y=[1,3,2]: dx(-1,0,1) dy(-1,1,0); sp=1; ssx=2, ssy=2.
        # r = 1 / sqrt(4) = 0.5.
        assert M.correlation(D("1", "2", "3"), D("1", "3", "2")) == Decimal(
            "0.500000000000"
        )

    def test_cross_check_statistics_correlation(self) -> None:
        x = ["1.5", "2.25", "3.75", "4.1", "5.9", "0.3"]
        y = ["2.0", "1.0", "6.5", "3.3", "7.7", "0.9"]
        got = M.correlation(tuple(Decimal(v) for v in x), tuple(Decimal(v) for v in y))
        ref = statistics.correlation([float(v) for v in x], [float(v) for v in y])
        assert _rel_close(got, ref)

    def test_bounded_in_unit_interval(self) -> None:
        got = M.correlation(D("1", "2", "3", "10"), D("9", "1", "4", "2"))
        assert Decimal("-1") <= got <= Decimal("1")

    def test_rejects_constant_series(self) -> None:
        with pytest.raises(CalculationError):
            M.correlation(D("5", "5", "5"), D("1", "2", "3"))

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            M.correlation([1.0, 2.0], [1.0, 2.0])  # type: ignore[list-item]

    def test_rejects_unequal_length(self) -> None:
        with pytest.raises(CalculationError):
            M.correlation(D("1", "2", "3"), D("1", "2"))


# ---------------------------------------------------------------------------
# covariance_matrix
# ---------------------------------------------------------------------------


class TestCovarianceMatrix:
    def test_hand_computed(self) -> None:
        # cols x=[1,2,3], y=[2,4,6]; sample var(x)=1, var(y)=4, cov=2.
        m = M.covariance_matrix([D("1", "2", "3"), D("2", "4", "6")])
        assert m == (
            (Decimal("1.000000000000"), Decimal("2.000000000000")),
            (Decimal("2.000000000000"), Decimal("4.000000000000")),
        )

    def test_symmetric(self) -> None:
        m = M.covariance_matrix(
            [D("1", "2", "3", "7"), D("2", "4", "6", "1"), D("9", "1", "4", "3")]
        )
        for i in range(3):
            for j in range(3):
                assert m[i][j] == m[j][i]

    def test_diagonal_cross_check_variance(self) -> None:
        x = ["1.5", "2.25", "3.75", "4.1", "5.9"]
        m = M.covariance_matrix([tuple(Decimal(v) for v in x)])
        ref = statistics.variance([float(v) for v in x])
        assert _rel_close(m[0][0], ref)

    def test_rejects_unequal_length_columns(self) -> None:
        with pytest.raises(CalculationError):
            M.covariance_matrix([D("1", "2", "3"), D("1", "2")])

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            M.covariance_matrix([[1.0, 2.0, 3.0]])  # type: ignore[list-item]

    def test_rejects_empty(self) -> None:
        with pytest.raises(CalculationError):
            M.covariance_matrix([])


# ---------------------------------------------------------------------------
# correlation_matrix
# ---------------------------------------------------------------------------


class TestCorrelationMatrix:
    def test_hand_computed(self) -> None:
        m = M.correlation_matrix([D("1", "2", "3"), D("1", "3", "2")])
        assert m == (
            (Decimal("1.000000000000"), Decimal("0.500000000000")),
            (Decimal("0.500000000000"), Decimal("1.000000000000")),
        )

    def test_diagonal_exactly_one(self) -> None:
        m = M.correlation_matrix(
            [D("1", "2", "3", "7"), D("2", "4", "6", "1"), D("9", "1", "4", "3")]
        )
        for i in range(3):
            assert m[i][i] == Decimal("1.000000000000")

    def test_symmetric(self) -> None:
        m = M.correlation_matrix(
            [D("1", "2", "3", "7"), D("2", "4", "6", "1"), D("9", "1", "4", "3")]
        )
        for i in range(3):
            for j in range(3):
                assert m[i][j] == m[j][i]

    def test_rejects_constant_column(self) -> None:
        with pytest.raises(CalculationError):
            M.correlation_matrix([D("1", "2", "3"), D("5", "5", "5")])

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            M.correlation_matrix([[1.0, 2.0, 3.0]])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# weighted_covariance
# ---------------------------------------------------------------------------


class TestWeightedCovariance:
    def test_equal_weights_reduce_to_ordinary_sample(self) -> None:
        got = M.weighted_covariance(
            D("1", "2", "3"), D("2", "4", "6"), D("1", "1", "1")
        )
        assert got == Decimal("2.000000000000")

    def test_hand_computed_sample(self) -> None:
        # w=[1,2,3], x=y=[1,2,3]; sp=10/3; sample denom = 6 - 14/6 = 11/3.
        # sample cov = (10/3)/(11/3) = 10/11.
        got = M.weighted_covariance(
            D("1", "2", "3"), D("1", "2", "3"), D("1", "2", "3")
        )
        assert _rel_close(got, 10.0 / 11.0)

    def test_hand_computed_population(self) -> None:
        # population cov = (10/3) / W(=6) = 5/9.
        got = M.weighted_covariance(
            D("1", "2", "3"), D("1", "2", "3"), D("1", "2", "3"), sample=False
        )
        assert _rel_close(got, 5.0 / 9.0)

    def test_rejects_zero_weight_sum(self) -> None:
        with pytest.raises(CalculationError):
            M.weighted_covariance(
                D("1", "2", "3"), D("1", "2", "3"), D("1", "-1", "0")
            )

    def test_rejects_unequal_length(self) -> None:
        with pytest.raises(CalculationError):
            M.weighted_covariance(D("1", "2", "3"), D("1", "2", "3"), D("1", "1"))

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            M.weighted_covariance(
                [1.0, 2.0, 3.0], [1.0, 2.0, 3.0], [1.0, 1.0, 1.0]  # type: ignore[list-item]
            )


# ---------------------------------------------------------------------------
# ewma_covariance
# ---------------------------------------------------------------------------


class TestEwmaCovariance:
    def test_hand_computed_alpha(self) -> None:
        # alpha=0.5 -> decay=0.5; weights (by age) newest->oldest 1,0.5,0.25.
        # x=y=[1,2,3]; weighted-mean-adjusted cov = 26/49.
        got = M.ewma_covariance(D("1", "2", "3"), D("1", "2", "3"), alpha="0.5")
        assert _rel_close(got, 26.0 / 49.0)

    def test_span_matches_equivalent_alpha(self) -> None:
        # span=3 -> alpha = 2/(3+1) = 0.5 -> same as the alpha case.
        by_span = M.ewma_covariance(D("1", "2", "3"), D("1", "2", "3"), span=3)
        by_alpha = M.ewma_covariance(D("1", "2", "3"), D("1", "2", "3"), alpha="0.5")
        assert by_span == by_alpha

    def test_requires_exactly_one_of_span_alpha(self) -> None:
        with pytest.raises(CalculationError):
            M.ewma_covariance(D("1", "2", "3"), D("1", "2", "3"))
        with pytest.raises(CalculationError):
            M.ewma_covariance(D("1", "2", "3"), D("1", "2", "3"), span=3, alpha="0.5")

    def test_rejects_too_few_observations(self) -> None:
        with pytest.raises(CalculationError):
            M.ewma_covariance(D("1"), D("1"), alpha="0.5")

    def test_rejects_unequal_length(self) -> None:
        with pytest.raises(CalculationError):
            M.ewma_covariance(D("1", "2", "3"), D("1", "2"), alpha="0.5")

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            M.ewma_covariance([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], alpha="0.5")  # type: ignore[list-item]

    def test_rejects_bad_alpha(self) -> None:
        with pytest.raises(CalculationError):
            M.ewma_covariance(D("1", "2", "3"), D("1", "2", "3"), alpha="0")
        with pytest.raises(CalculationError):
            M.ewma_covariance(D("1", "2", "3"), D("1", "2", "3"), alpha="1.5")

    def test_rejects_bad_span(self) -> None:
        with pytest.raises(CalculationError):
            M.ewma_covariance(D("1", "2", "3"), D("1", "2", "3"), span=0)


# ---------------------------------------------------------------------------
# linear_regression
# ---------------------------------------------------------------------------


class TestLinearRegression:
    def test_hand_computed_perfect_fit(self) -> None:
        fit = M.linear_regression(D("1", "2", "3"), D("2", "4", "6"))
        assert fit.slope == Decimal("2.000000000000")
        assert fit.intercept == Decimal("0.000000000000")
        assert fit.r_squared == Decimal("1.000000000000")
        assert fit.std_error_slope == Decimal("0.000000000000")
        assert fit.n == 3
        assert fit.residuals == (
            Decimal("0.000000000000"),
            Decimal("0.000000000000"),
            Decimal("0.000000000000"),
        )

    def test_hand_computed_partial_fit(self) -> None:
        # x=[1,2,3] y=[1,3,2]: slope=0.5, intercept=1, r_squared=0.25.
        # residuals = (-0.5, 1, -0.5); std_error_slope = sqrt(0.75).
        fit = M.linear_regression(D("1", "2", "3"), D("1", "3", "2"))
        assert fit.slope == Decimal("0.500000000000")
        assert fit.intercept == Decimal("1.000000000000")
        assert fit.r_squared == Decimal("0.250000000000")
        assert fit.residuals == (
            Decimal("-0.500000000000"),
            Decimal("1.000000000000"),
            Decimal("-0.500000000000"),
        )
        assert _rel_close(fit.std_error_slope, 0.75 ** 0.5)
        assert fit.n == 3

    def test_cross_check_statistics_linear_regression(self) -> None:
        x = ["1.5", "2.25", "3.75", "4.1", "5.9", "0.3"]
        y = ["2.0", "1.0", "6.5", "3.3", "7.7", "0.9"]
        fit = M.linear_regression(
            tuple(Decimal(v) for v in x), tuple(Decimal(v) for v in y)
        )
        ref = statistics.linear_regression(
            [float(v) for v in x], [float(v) for v in y]
        )
        assert _rel_close(fit.slope, ref.slope)
        assert _rel_close(fit.intercept, ref.intercept)
        # r_squared cross-check: equals correlation squared.
        corr = statistics.correlation([float(v) for v in x], [float(v) for v in y])
        assert _rel_close(fit.r_squared, corr * corr)

    def test_frozen_model(self) -> None:
        fit = M.linear_regression(D("1", "2", "3"), D("2", "4", "6"))
        with pytest.raises(ValidationError):
            fit.slope = Decimal("9")  # type: ignore[misc]

    def test_rejects_too_few_observations(self) -> None:
        with pytest.raises(CalculationError):
            M.linear_regression(D("1", "2"), D("2", "4"))

    def test_rejects_constant_x(self) -> None:
        with pytest.raises(CalculationError):
            M.linear_regression(D("5", "5", "5"), D("1", "2", "3"))

    def test_rejects_constant_y(self) -> None:
        with pytest.raises(CalculationError):
            M.linear_regression(D("1", "2", "3"), D("5", "5", "5"))

    def test_rejects_unequal_length(self) -> None:
        with pytest.raises(CalculationError):
            M.linear_regression(D("1", "2", "3"), D("1", "2"))

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            M.linear_regression([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])  # type: ignore[list-item]
