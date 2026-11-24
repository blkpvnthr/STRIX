"""Tests for strix.reconciliation.reconcile (R1 §12, GAP-003).

Covers sum/mean reconciliation within and outside tolerance (with exact
residuals), the missing-components and incompatible guards, IQR and z-score
anomaly screening on clean and outlier series, and the ``float``-rejection
discipline. A ReconciliationResult is evidence only — it never admits a claim.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from strix.native.arithmetic import checked_div
from strix.reconciliation.reconcile import (
    AnomalyFinding,
    ReconciliationError,
    ReconciliationResult,
    reconcile_aggregate,
    screen_anomalies,
)

# --------------------------------------------------------------------------
# reconcile_aggregate — sum
# --------------------------------------------------------------------------


def test_reconcile_sum_within_tolerance() -> None:
    result = reconcile_aggregate(
        "total_revenue",
        Decimal("300"),
        [Decimal("100"), Decimal("200")],
        abs_tol=Decimal("0"),
        rel_tol=Decimal("0"),
        source_references=("FACT-a", "FACT-b"),
    )
    assert isinstance(result, ReconciliationResult)
    assert result.classification == "within_tolerance"
    assert result.reconstructed_value == Decimal("300")
    assert result.absolute_residual == Decimal("0")
    assert result.relative_residual == Decimal("0")
    assert result.source_references == ("FACT-a", "FACT-b")


def test_reconcile_sum_within_relative_tolerance() -> None:
    # observed 1000, components sum 999 -> residual 1; rel_tol 0.01 * 1000 = 10.
    result = reconcile_aggregate(
        "total",
        Decimal("1000"),
        [Decimal("500"), Decimal("499")],
        abs_tol=Decimal("0"),
        rel_tol=Decimal("0.01"),
    )
    assert result.classification == "within_tolerance"
    assert result.absolute_residual == Decimal("1")


def test_reconcile_sum_mismatch() -> None:
    result = reconcile_aggregate(
        "total",
        Decimal("300"),
        [Decimal("100"), Decimal("150")],
        abs_tol=Decimal("1"),
        rel_tol=Decimal("0"),
    )
    assert result.classification == "mismatch"
    assert result.reconstructed_value == Decimal("250")
    assert result.absolute_residual == Decimal("50")
    assert result.relative_residual == checked_div(Decimal("50"), Decimal("300"))


# --------------------------------------------------------------------------
# reconcile_aggregate — mean
# --------------------------------------------------------------------------


def test_reconcile_mean_within_tolerance() -> None:
    result = reconcile_aggregate(
        "avg_margin",
        Decimal("20"),
        [Decimal("10"), Decimal("30")],
        aggregation="mean",
        abs_tol=Decimal("0"),
        rel_tol=Decimal("0"),
    )
    assert result.classification == "within_tolerance"
    assert result.reconstructed_value == Decimal("20")


# --------------------------------------------------------------------------
# Guards
# --------------------------------------------------------------------------


def test_reconcile_missing_components() -> None:
    result = reconcile_aggregate(
        "total",
        Decimal("300"),
        [],
        abs_tol=Decimal("1"),
        rel_tol=Decimal("0"),
    )
    assert result.classification == "missing_components"
    assert result.missing_components == ("components",)


def test_reconcile_incompatible_aggregation() -> None:
    result = reconcile_aggregate(
        "total",
        Decimal("300"),
        [Decimal("100"), Decimal("200")],
        aggregation="product",
        abs_tol=Decimal("1"),
        rel_tol=Decimal("0"),
    )
    assert result.classification == "incompatible"


def test_reconcile_rejects_negative_tolerance() -> None:
    with pytest.raises(ReconciliationError):
        reconcile_aggregate(
            "total",
            Decimal("300"),
            [Decimal("300")],
            abs_tol=Decimal("-1"),
            rel_tol=Decimal("0"),
        )


def test_reconcile_rejects_float_observed() -> None:
    with pytest.raises(ReconciliationError):
        reconcile_aggregate(
            "total",
            300.0,  # type: ignore[arg-type]
            [Decimal("300")],
            abs_tol=Decimal("0"),
            rel_tol=Decimal("0"),
        )


def test_reconcile_rejects_float_component() -> None:
    with pytest.raises(ReconciliationError):
        reconcile_aggregate(
            "total",
            Decimal("300"),
            [100.0, Decimal("200")],  # type: ignore[list-item]
            abs_tol=Decimal("0"),
            rel_tol=Decimal("0"),
        )


# --------------------------------------------------------------------------
# screen_anomalies — IQR
# --------------------------------------------------------------------------


def test_screen_anomalies_iqr_flags_outlier() -> None:
    values = [Decimal(str(v)) for v in (10, 11, 12, 13, 12, 11, 10, 12, 11, 1000)]
    finding = screen_anomalies(values, method="iqr", k="1.5")
    assert isinstance(finding, AnomalyFinding)
    assert finding.classification == "anomalies_present"
    assert 9 in finding.flagged_indices
    assert Decimal("1000") in finding.flagged_values


def test_screen_anomalies_iqr_clean() -> None:
    values = [Decimal(str(v)) for v in (10, 11, 12, 13, 12, 11, 10, 12, 11, 13)]
    finding = screen_anomalies(values, method="iqr", k="1.5")
    assert finding.classification == "clean"
    assert finding.flagged_indices == ()


# --------------------------------------------------------------------------
# screen_anomalies — z-score
# --------------------------------------------------------------------------


def test_screen_anomalies_zscore_flags_outlier() -> None:
    values = [Decimal(str(v)) for v in (10, 10, 10, 10, 10, 10, 10, 10, 10, 200)]
    finding = screen_anomalies(values, method="zscore", k="2")
    assert finding.classification == "anomalies_present"
    assert 9 in finding.flagged_indices


def test_screen_anomalies_zscore_constant_series_clean() -> None:
    values = [Decimal("5")] * 5
    finding = screen_anomalies(values, method="zscore", k="2")
    assert finding.classification == "clean"


def test_screen_anomalies_rejects_unknown_method() -> None:
    with pytest.raises(ReconciliationError):
        screen_anomalies([Decimal("1"), Decimal("2")], method="mahalanobis")


def test_screen_anomalies_rejects_float() -> None:
    with pytest.raises(ReconciliationError):
        screen_anomalies([1.0, 2.0], method="iqr")  # type: ignore[list-item]


def test_screen_anomalies_requires_two_observations() -> None:
    with pytest.raises(ReconciliationError):
        screen_anomalies([Decimal("1")], method="iqr")
