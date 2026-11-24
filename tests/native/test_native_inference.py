"""Contract tests for strix.native.inference — statistical inference (R1 §6.4).

Inference (confidence intervals, effect sizes, t-tests, bootstrap, multiple-
comparison correction) is the "approximate"/"stochastic" numerical-contract
class: inputs are exact Decimals (float is still rejected at the boundary),
internal computation is float64, and results carry documented tolerances. The
Student-t survival function is implemented via the regularized incomplete beta.

Known reference values are hand-computed:

- a=[1,2,3,4,5], b=[2,4,6,8,10]: Cohen's d = -1.2 exactly (pooled sd = 2.5).
- Welch t for the same: t = -1.8974, df = 5.8824.
- 95% t critical value for df=4 is 2.7764; CI of a = [1.0367, 4.9633].
- Student-t two-sided p(t=2, df=10) ~= 0.07339; p(t=0, df=5) = 1.0.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from strix.errors import CalculationError
from strix.native import inference as I

A = [Decimal(x) for x in (1, 2, 3, 4, 5)]
B = [Decimal(x) for x in (2, 4, 6, 8, 10)]


class TestStudentT:
    def test_two_sided_p_known_value(self) -> None:
        p = float(I.student_t_two_sided_p(Decimal("2"), Decimal("10")))
        assert p == pytest.approx(0.07339, abs=1e-4)

    def test_two_sided_p_at_zero_is_one(self) -> None:
        p = float(I.student_t_two_sided_p(Decimal("0"), Decimal("5")))
        assert p == pytest.approx(1.0, abs=1e-9)

    def test_sf_is_half_at_zero(self) -> None:
        assert float(I.student_t_sf(Decimal("0"), Decimal("7"))) == pytest.approx(0.5, abs=1e-9)

    def test_sf_known_value(self) -> None:
        sf = float(I.student_t_sf(Decimal("2"), Decimal("10")))
        assert sf == pytest.approx(0.03669, abs=1e-4)

    def test_large_df_approaches_normal(self) -> None:
        # t=1.959964 with huge df -> two-sided p ~ 0.05 (normal limit).
        p = float(I.student_t_two_sided_p(Decimal("1.959964"), Decimal("100000000")))
        assert p == pytest.approx(0.05, abs=1e-3)

    def test_rejects_nonpositive_df(self) -> None:
        with pytest.raises(CalculationError):
            I.student_t_two_sided_p(Decimal("2"), Decimal("0"))


class TestCohensD:
    def test_known_value(self) -> None:
        assert float(I.cohens_d(A, B)) == pytest.approx(-1.2, abs=1e-9)

    def test_rejects_float_input(self) -> None:
        with pytest.raises(CalculationError):
            I.cohens_d([1.0, 2.0, 3.0], B)  # type: ignore[list-item]

    def test_rejects_too_few(self) -> None:
        with pytest.raises(CalculationError):
            I.cohens_d([Decimal("1")], [Decimal("2")])


class TestWelchTTest:
    def test_statistic_and_df(self) -> None:
        r = I.welch_t_test(A, B)
        assert float(r.t_statistic) == pytest.approx(-1.8974, abs=1e-3)
        assert float(r.degrees_of_freedom) == pytest.approx(5.8824, abs=1e-3)

    def test_p_value_plausible(self) -> None:
        r = I.welch_t_test(A, B)
        assert 0.08 < float(r.p_value_two_sided) < 0.13

    def test_identical_samples_p_is_one(self) -> None:
        r = I.welch_t_test(A, A)
        assert float(r.p_value_two_sided) == pytest.approx(1.0, abs=1e-6)


class TestMeanConfidenceInterval:
    def test_known_interval(self) -> None:
        ci = I.mean_confidence_interval(A, confidence="0.95")
        assert float(ci.point) == pytest.approx(3.0, abs=1e-9)
        assert float(ci.lower) == pytest.approx(1.0367, abs=1e-3)
        assert float(ci.upper) == pytest.approx(4.9633, abs=1e-3)

    def test_rejects_too_few(self) -> None:
        with pytest.raises(CalculationError):
            I.mean_confidence_interval([Decimal("1")], confidence="0.95")


class TestBootstrapMeanCI:
    def test_reproducible_with_seed(self) -> None:
        r1 = I.bootstrap_mean_ci(A, confidence="0.95", n_resamples=500, seed=42)
        r2 = I.bootstrap_mean_ci(A, confidence="0.95", n_resamples=500, seed=42)
        assert r1.lower == r2.lower and r1.upper == r2.upper
        assert r1.seed == 42

    def test_interval_brackets_mean(self) -> None:
        r = I.bootstrap_mean_ci(A, confidence="0.95", n_resamples=500, seed=7)
        assert float(r.lower) <= 3.0 <= float(r.upper)


class TestMultipleComparison:
    def test_benjamini_hochberg_classic(self) -> None:
        rejected = I.benjamini_hochberg(["0.005", "0.02", "0.5", "0.9"], alpha="0.05")
        assert rejected == (True, True, False, False)

    def test_benjamini_hochberg_all_reject(self) -> None:
        rejected = I.benjamini_hochberg(["0.01", "0.02", "0.03", "0.04", "0.05"], alpha="0.05")
        assert rejected == (True, True, True, True, True)

    def test_bonferroni(self) -> None:
        rejected = I.bonferroni(["0.005", "0.02", "0.5", "0.9"], alpha="0.05")
        assert rejected == (True, False, False, False)

    def test_bonferroni_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            I.bonferroni([0.005, 0.02], alpha="0.05")  # type: ignore[list-item]
