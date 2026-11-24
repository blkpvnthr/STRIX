"""Regression for the GAP-003 exactness defect (review wf_4e2cb7c3-6ee): the
reconstruction/residual ran under the global prec-28 decimal context, so a large
exact reconciliation was silently misclassified near a zero tolerance."""

from __future__ import annotations

from decimal import Decimal

from strix.reconciliation.reconcile import reconcile_aggregate


def test_large_exact_reconciliation_is_within_tolerance() -> None:
    # 30 * 1e27 + 0.01 — the exact sum needs 29 integer + 2 fractional digits, so
    # a prec-28 accumulation drops the 0.01 and fabricates a residual.
    components = [Decimal("1000000000000000000000000000")] * 30 + [Decimal("0.01")]
    observed = Decimal("30000000000000000000000000000.01")
    result = reconcile_aggregate(
        "spend", observed, components, aggregation="sum",
        abs_tol=Decimal("0"), rel_tol=Decimal("0"),
    )
    assert result.absolute_residual == Decimal("0")
    assert result.classification == "within_tolerance"


def test_large_planted_discrepancy_is_mismatch() -> None:
    components = [Decimal("1000000000000000000000000000")] * 30 + [Decimal("0.01")]
    observed = Decimal("30000000000000000000000000000.02")  # off by exactly 0.01
    result = reconcile_aggregate(
        "spend", observed, components, aggregation="sum",
        abs_tol=Decimal("0"), rel_tol=Decimal("0"),
    )
    assert result.absolute_residual == Decimal("0.01")
    assert result.classification == "mismatch"
