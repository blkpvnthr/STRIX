"""Tests for experiment statistical analysis (reuses strix.native.inference)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from strix.errors import StrixError
from strix.research_eval.analysis import (
    ComparisonResult,
    bootstrap_ci,
    holm_or_bh_correction,
    paired_comparison,
)


def _decs(values: list[str]) -> list[Decimal]:
    return [Decimal(v) for v in values]


# --------------------------------------------------------------------------
# bootstrap_ci
# --------------------------------------------------------------------------


def test_bootstrap_ci_reproducible_given_seed() -> None:
    values = _decs(["1.0", "2.0", "3.0", "4.0", "5.0"])
    a = bootstrap_ci(values, seed=1234, n_resamples=500)
    b = bootstrap_ci(values, seed=1234, n_resamples=500)
    assert a == b


def test_bootstrap_ci_differs_across_seeds() -> None:
    values = _decs(["1.0", "2.0", "3.0", "4.0", "5.0"])
    a = bootstrap_ci(values, seed=1, n_resamples=500)
    b = bootstrap_ci(values, seed=2, n_resamples=500)
    assert a != b


def test_bootstrap_ci_brackets_the_mean() -> None:
    values = _decs(["10.0", "11.0", "12.0", "13.0", "14.0"])
    point, lower, upper = bootstrap_ci(values, seed=7, n_resamples=1000)
    assert point == Decimal("12")
    assert lower <= point <= upper


def test_bootstrap_ci_returns_three_decimals() -> None:
    values = _decs(["1.0", "2.0", "3.0"])
    result = bootstrap_ci(values, seed=5)
    assert len(result) == 3
    assert all(isinstance(x, Decimal) for x in result)


def test_bootstrap_ci_rejects_float_input() -> None:
    with pytest.raises(StrixError):
        bootstrap_ci([1.0, 2.0, 3.0], seed=1)  # type: ignore[list-item]


# --------------------------------------------------------------------------
# paired_comparison
# --------------------------------------------------------------------------


def test_paired_comparison_positive_difference() -> None:
    arm_a = _decs(["5.0", "6.0", "7.0", "8.0", "9.0"])
    arm_b = _decs(["1.0", "2.0", "3.0", "4.0", "5.0"])
    result = paired_comparison(arm_a, arm_b)
    assert isinstance(result, ComparisonResult)
    assert result.mean_a == Decimal("7")
    assert result.mean_b == Decimal("3")
    assert result.mean_difference > 0
    assert result.t_statistic > 0
    assert result.effect_size > 0
    assert result.n == 5
    # Clear separation -> small p-value.
    assert result.p_value < Decimal("0.05")


def test_paired_comparison_negative_difference() -> None:
    arm_a = _decs(["1.0", "2.0", "3.0", "4.0", "5.0"])
    arm_b = _decs(["5.0", "6.0", "7.0", "8.0", "9.0"])
    result = paired_comparison(arm_a, arm_b)
    assert result.mean_difference < 0
    assert result.t_statistic < 0
    assert result.effect_size < 0


def test_paired_comparison_difference_matches_means() -> None:
    arm_a = _decs(["2.0", "4.0", "6.0", "8.0"])
    arm_b = _decs(["1.0", "2.0", "3.0", "4.0"])
    result = paired_comparison(arm_a, arm_b)
    assert result.mean_difference == result.mean_a - result.mean_b


def test_paired_comparison_requires_equal_length() -> None:
    with pytest.raises(StrixError):
        paired_comparison(_decs(["1.0", "2.0", "3.0"]), _decs(["1.0", "2.0"]))


def test_paired_comparison_rejects_float() -> None:
    with pytest.raises(StrixError):
        paired_comparison([1.0, 2.0], [3.0, 4.0])  # type: ignore[list-item]


# --------------------------------------------------------------------------
# holm_or_bh_correction
# --------------------------------------------------------------------------


def test_bh_correction_known_set() -> None:
    pvalues = _decs(["0.001", "0.02", "0.5", "0.9"])
    mask = holm_or_bh_correction(pvalues, alpha="0.05")
    assert mask == (True, True, False, False)


def test_bh_correction_preserves_input_order() -> None:
    pvalues = _decs(["0.9", "0.001", "0.5", "0.02"])
    mask = holm_or_bh_correction(pvalues, alpha="0.05")
    assert mask == (False, True, False, True)


def test_bh_correction_empty() -> None:
    assert holm_or_bh_correction([]) == ()


def test_bh_correction_none_significant() -> None:
    pvalues = _decs(["0.4", "0.6", "0.8"])
    mask = holm_or_bh_correction(pvalues, alpha="0.05")
    assert mask == (False, False, False)


# --------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------


def test_paired_comparison_deterministic() -> None:
    arm_a = _decs(["5.0", "6.0", "7.0", "8.0"])
    arm_b = _decs(["1.0", "2.0", "3.0", "4.0"])
    assert paired_comparison(arm_a, arm_b) == paired_comparison(arm_a, arm_b)
