"""Tests for deterministic spending-anomaly detection.

These detectors use robust descriptive statistics (not ML). Every finding is
*evidence for investigation* — it never asserts fraud and never triggers an
automatic action. The tests assert the happy paths (an obvious large outflow
and a duplicate charge are flagged), the invariants (clean series are not
flagged; findings never say "fraud"; results are deterministic), and the
adversarial edges (empty / single-transaction inputs, float rejection, and
invalid parameters raise a typed error).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.errors import StrixError
from strix.finance.anomaly import (
    AnomalyError,
    AnomalyMethod,
    NormalizedTransaction,
    SpendingAnomaly,
    detect_anomalies,
    detect_duplicate_charges,
    detect_large_transactions,
    make_transaction,
)

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _txn(
    txn_id: str,
    amount: str,
    *,
    day: int,
    description: str = "GROCERY",
) -> NormalizedTransaction:
    """A transaction on 2026-01-<day>; negative ``amount`` is an outflow."""
    return NormalizedTransaction(
        txn_id=txn_id,
        account_id="ACCT",
        posted_date=date(2026, 1, day),
        description=description,
        amount=Decimal(amount),
    )


def _small_outflows() -> list[NormalizedTransaction]:
    """Six similar small outflows (magnitudes 9..13) — no outliers."""
    return [
        _txn("t1", "-10", day=1),
        _txn("t2", "-12", day=2),
        _txn("t3", "-11", day=3),
        _txn("t4", "-13", day=4),
        _txn("t5", "-9", day=5),
        _txn("t6", "-10", day=6),
    ]


# --------------------------------------------------------------------------
# detect_large_transactions
# --------------------------------------------------------------------------


def test_obvious_large_outflow_is_flagged() -> None:
    txns = [*_small_outflows(), _txn("big", "-500", day=7)]
    found = detect_large_transactions(txns)
    assert len(found) == 1
    anomaly = found[0]
    assert anomaly.txn_id == "big"
    assert anomaly.method is AnomalyMethod.large_transaction
    # Reported magnitude strictly exceeds the IQR upper-fence baseline.
    assert anomaly.amount == Decimal(500)
    assert anomaly.amount > anomaly.baseline
    assert anomaly.baseline > 0


def test_clean_series_is_not_flagged() -> None:
    assert detect_large_transactions(_small_outflows()) == ()


def test_large_inflow_is_ignored() -> None:
    # A huge *inflow* (positive) is not a spending outflow and must not flag.
    txns = [*_small_outflows(), _txn("salary", "5000", day=7, description="PAY")]
    assert detect_large_transactions(txns) == ()


def test_large_transaction_baseline_scales_with_k() -> None:
    txns = [*_small_outflows(), _txn("big", "-30", day=7)]
    # A tight fence (k=1) flags the 30 outflow; a loose fence (k=10) does not.
    assert len(detect_large_transactions(txns, iqr_k=Decimal("1"))) == 1
    assert detect_large_transactions(txns, iqr_k=Decimal("10")) == ()


def test_single_outflow_is_never_a_large_outlier() -> None:
    assert detect_large_transactions([_txn("solo", "-999", day=1)]) == ()


def test_large_transactions_empty_input() -> None:
    assert detect_large_transactions([]) == ()


# --------------------------------------------------------------------------
# detect_duplicate_charges
# --------------------------------------------------------------------------


def test_duplicate_charge_pair_is_flagged() -> None:
    txns = [
        _txn("a", "-5.00", day=10, description="COFFEE"),
        _txn("b", "-5.00", day=11, description="COFFEE"),
        _txn("c", "-42.00", day=12, description="FUEL"),
    ]
    found = detect_duplicate_charges(txns)
    flagged = {a.txn_id for a in found}
    assert flagged == {"a", "b"}
    for anomaly in found:
        assert anomaly.method is AnomalyMethod.duplicate
        assert anomaly.amount == Decimal("5.00")


def test_same_amount_different_description_is_not_duplicate() -> None:
    txns = [
        _txn("a", "-5.00", day=10, description="COFFEE"),
        _txn("b", "-5.00", day=11, description="SNACK"),
    ]
    assert detect_duplicate_charges(txns) == ()


def test_same_charge_outside_window_is_not_duplicate() -> None:
    txns = [
        _txn("a", "-5.00", day=1, description="COFFEE"),
        _txn("b", "-5.00", day=20, description="COFFEE"),
    ]
    assert detect_duplicate_charges(txns, max_day_gap=2) == ()


def test_same_day_duplicate_is_flagged() -> None:
    txns = [
        _txn("a", "-7.00", day=4, description="APP STORE"),
        _txn("b", "-7.00", day=4, description="APP STORE"),
    ]
    assert {a.txn_id for a in detect_duplicate_charges(txns, max_day_gap=0)} == {
        "a",
        "b",
    }


def test_duplicate_ignores_inflows() -> None:
    # Two identical *inflows* are not duplicate charges.
    txns = [
        _txn("a", "5.00", day=10, description="REFUND"),
        _txn("b", "5.00", day=11, description="REFUND"),
    ]
    assert detect_duplicate_charges(txns) == ()


def test_duplicate_empty_and_single() -> None:
    assert detect_duplicate_charges([]) == ()
    assert detect_duplicate_charges([_txn("a", "-5.00", day=1)]) == ()


# --------------------------------------------------------------------------
# detect_anomalies (union)
# --------------------------------------------------------------------------


def test_detect_anomalies_unions_detectors() -> None:
    txns = [
        *_small_outflows(),
        _txn("big", "-500", day=7),
        _txn("dup1", "-5.00", day=8, description="COFFEE"),
        _txn("dup2", "-5.00", day=9, description="COFFEE"),
    ]
    found = detect_anomalies(txns)
    methods = {a.method for a in found}
    assert methods == {AnomalyMethod.large_transaction, AnomalyMethod.duplicate}
    assert {a.txn_id for a in found} >= {"big", "dup1", "dup2"}


def test_detect_anomalies_is_deterministic_and_sorted() -> None:
    txns = [
        _txn("big", "-500", day=7),
        *_small_outflows(),
        _txn("dup2", "-5.00", day=9, description="COFFEE"),
        _txn("dup1", "-5.00", day=8, description="COFFEE"),
    ]
    first = detect_anomalies(txns)
    second = detect_anomalies(txns)
    assert first == second
    keys = [(a.method.value, a.txn_id, a.reason_code) for a in first]
    assert keys == sorted(keys)


def test_detect_anomalies_empty() -> None:
    assert detect_anomalies([]) == ()


# --------------------------------------------------------------------------
# Invariants: never "fraud", machine-readable reason codes
# --------------------------------------------------------------------------


def test_findings_never_assert_fraud() -> None:
    txns = [
        *_small_outflows(),
        _txn("big", "-500", day=7),
        _txn("dup1", "-5.00", day=8, description="COFFEE"),
        _txn("dup2", "-5.00", day=9, description="COFFEE"),
    ]
    found = detect_anomalies(txns)
    assert found  # non-empty, so the assertion below is meaningful
    for anomaly in found:
        assert "fraud" not in anomaly.reason_code.lower()
        assert "fraud" not in anomaly.note.lower()


def test_reason_codes_are_machine_readable() -> None:
    txns = [
        *_small_outflows(),
        _txn("big", "-500", day=7),
        _txn("dup1", "-5.00", day=8, description="COFFEE"),
        _txn("dup2", "-5.00", day=9, description="COFFEE"),
    ]
    for anomaly in detect_anomalies(txns):
        assert re.fullmatch(r"[a-z][a-z0-9_]*", anomaly.reason_code)
        assert anomaly.note  # human-readable note present


# --------------------------------------------------------------------------
# Adversarial: float rejection and invalid parameters
# --------------------------------------------------------------------------


def test_transaction_rejects_float_amount() -> None:
    with pytest.raises(ValidationError):
        NormalizedTransaction(
            txn_id="t",
            account_id="ACCT",
            posted_date=date(2026, 1, 1),
            description="X",
            amount=1.0,
        )


def test_spending_anomaly_rejects_float_amount() -> None:
    with pytest.raises(ValidationError):
        SpendingAnomaly(
            method=AnomalyMethod.large_transaction,
            txn_id="t",
            amount=1.0,
            baseline=Decimal(0),
            reason_code="x",
            note="n",
        )


def test_large_transactions_rejects_float_k() -> None:
    with pytest.raises(AnomalyError):
        detect_large_transactions(_small_outflows(), iqr_k=1.5)  # type: ignore[arg-type]


def test_large_transactions_rejects_negative_k() -> None:
    with pytest.raises(AnomalyError):
        detect_large_transactions(_small_outflows(), iqr_k=Decimal("-1"))


def test_duplicate_rejects_negative_gap() -> None:
    with pytest.raises(AnomalyError):
        detect_duplicate_charges(_small_outflows(), max_day_gap=-1)


def test_anomaly_error_is_a_strix_error() -> None:
    assert issubclass(AnomalyError, StrixError)


# --------------------------------------------------------------------------
# make_transaction convenience constructor
# --------------------------------------------------------------------------


def test_make_transaction_builds_content_id() -> None:
    txn = make_transaction(
        posted_date=date(2026, 1, 1), description="COFFEE", amount=Decimal("-5.00")
    )
    assert txn.txn_id.startswith("TXN-")
    # Deterministic: identical content yields an identical id.
    again = make_transaction(
        posted_date=date(2026, 1, 1), description="COFFEE", amount=Decimal("-5.00")
    )
    assert txn.txn_id == again.txn_id


def test_make_transaction_rejects_float() -> None:
    with pytest.raises(ValidationError):
        make_transaction(
            posted_date=date(2026, 1, 1),
            description="COFFEE",
            amount=5.0,  # type: ignore[arg-type]
        )
