"""Tests for R-N4: calibration diagnostics, uncertainty propagation, selective admission.

Covers Brier/ECE/reliability (exact Decimal), first-order variance propagation, and the
non-overridable selective-release constraint (g=1 ⇒ admitted) incl. a property test.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from strix.assurance.abstention import (
    SelectiveDecision,
    coverage,
    select_release,
    selective_risk,
)
from strix.assurance.calibration import (
    CalibrationSample,
    brier_score,
    expected_calibration_error,
    propagate_variance,
    reliability_bins,
)


def _s(p: str, y: int) -> CalibrationSample:
    return CalibrationSample(prediction=Decimal(p), label=y)


# --------------------------------------------------------------------------
# Brier / ECE / reliability
# --------------------------------------------------------------------------


def test_brier_perfect_is_zero() -> None:
    assert brier_score((_s("1", 1), _s("0", 0))) == Decimal(0)


def test_brier_worst_is_one() -> None:
    assert brier_score((_s("1", 0), _s("0", 1))) == Decimal(1)


def test_brier_known_value() -> None:
    assert brier_score((_s("0.9", 1), _s("0.2", 0))) == Decimal("0.025")


def test_ece_known_value() -> None:
    ece = expected_calibration_error((_s("0.1", 0), _s("0.9", 1)), n_bins=2)
    assert ece == Decimal("0.1")


def test_ece_perfectly_calibrated_low() -> None:
    # Predictions equal empirical frequency within each bin -> ECE 0.
    samples = (_s("1", 1), _s("1", 1), _s("0", 0), _s("0", 0))
    assert expected_calibration_error(samples, n_bins=2) == Decimal(0)


def test_reliability_bins_counts() -> None:
    bins = reliability_bins((_s("0.1", 0), _s("0.9", 1), _s("1", 1)), n_bins=2)
    assert bins[0].count == 1  # 0.1 in [0,0.5)
    assert bins[1].count == 2  # 0.9, 1.0 in [0.5,1]
    assert bins[1].accuracy == Decimal(1)


def test_calibration_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="at least one"):
        brier_score(())
    with pytest.raises(ValueError, match="outside"):
        brier_score((_s("1.5", 1),))
    with pytest.raises(ValueError, match="not 0 or 1"):
        brier_score((CalibrationSample(prediction=Decimal("0.5"), label=2),))


# --------------------------------------------------------------------------
# Uncertainty propagation
# --------------------------------------------------------------------------


def test_propagate_variance_diagonal() -> None:
    cov = [[Decimal(1), Decimal(0)], [Decimal(0), Decimal(1)]]
    assert propagate_variance((Decimal(2), Decimal(3)), cov) == Decimal(13)  # 4 + 9


def test_propagate_variance_with_covariance() -> None:
    cov = [[Decimal(1), Decimal("0.5")], [Decimal("0.5"), Decimal(1)]]
    # 4 + 9 + 2*2*3*0.5 = 19 (dependency term raises the variance)
    assert propagate_variance((Decimal(2), Decimal(3)), cov) == Decimal(19)


def test_propagate_variance_requires_symmetric_square() -> None:
    with pytest.raises(ValueError, match="n x n"):
        propagate_variance((Decimal(1),), [[Decimal(1), Decimal(0)]])
    asymmetric = [[Decimal(1), Decimal(1)], [Decimal(0), Decimal(1)]]
    with pytest.raises(ValueError, match="symmetric"):
        propagate_variance((Decimal(1), Decimal(1)), asymmetric)


# --------------------------------------------------------------------------
# Selective admission — non-override
# --------------------------------------------------------------------------


def test_release_requires_admission() -> None:
    assert select_release("c", admitted=True, uncertainty_acceptable=True).release is True
    d = select_release("c", admitted=False, uncertainty_acceptable=True)
    assert d.release is False and d.reason == "not_admitted"


def test_uncertainty_gate_cannot_release_unadmitted() -> None:
    # Even with acceptable uncertainty, a non-admitted claim is never released.
    assert select_release("c", admitted=False, uncertainty_acceptable=True).release is False


def test_high_uncertainty_withholds_admitted() -> None:
    d = select_release("c", admitted=True, uncertainty_acceptable=False)
    assert d.release is False and d.reason == "uncertainty_too_high"


def test_coverage_fraction() -> None:
    decisions = (
        SelectiveDecision(claim_id="a", release=True, reason="released"),
        SelectiveDecision(claim_id="b", release=False, reason="not_admitted"),
    )
    assert coverage(decisions) == Decimal("0.5")


def test_selective_risk_none_when_nothing_released() -> None:
    decisions = (SelectiveDecision(claim_id="a", release=False, reason="not_admitted"),)
    assert selective_risk(decisions, {}) is None


def test_selective_risk_average_loss() -> None:
    decisions = (
        SelectiveDecision(claim_id="a", release=True, reason="released"),
        SelectiveDecision(claim_id="b", release=True, reason="released"),
    )
    assert selective_risk(decisions, {"a": Decimal(1), "b": Decimal(0)}) == Decimal("0.5")


@given(st.booleans(), st.booleans())
def test_invn4_1_non_override(admitted: bool, unc_ok: bool) -> None:
    """INV-N4-1: g=1 (release) implies the claim was admitted — never overridden."""
    d = select_release("c", admitted=admitted, uncertainty_acceptable=unc_ok)
    if d.release:
        assert admitted is True


def test_propagate_variance_exact_large_magnitude() -> None:
    # Reviewer's case: a 31-significant-digit variance must not round in the global context.
    big = Decimal("1234567890123456789012345678901")
    assert propagate_variance((Decimal(1),), [[big]]) == big
