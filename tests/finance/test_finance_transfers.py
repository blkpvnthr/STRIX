"""Tests for internal-transfer / credit-card-repayment matching.

The correctness property under test: a transfer between the user's own
accounts (including a credit-card repayment or a brokerage deposit) must
never be counted as new income or expense.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.errors import StrixError
from strix.finance.transfers import (
    NormalizedTransaction,
    TransferCandidate,
    TransferMatch,
    TransferMatchError,
    classify_income_expense,
    match_transfers,
)

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _txn(
    txn_id: str,
    account_id: str,
    amount: str,
    day: int,
    *,
    owned: bool = True,
) -> NormalizedTransaction:
    return NormalizedTransaction(
        txn_id=txn_id,
        account_id=account_id,
        amount=Decimal(amount),
        posted_date=date(2026, 1, day),
        owned=owned,
    )


# --------------------------------------------------------------------------
# Model guards
# --------------------------------------------------------------------------


def test_transfer_match_is_strix_model_frozen_and_closed() -> None:
    match = TransferMatch(
        outflow_txn_id="a",
        inflow_txn_id="b",
        amount=Decimal("100.00"),
        match_reason="test",
    )
    with pytest.raises(ValidationError):
        match.amount = Decimal("1")  # type: ignore[misc]
    with pytest.raises(ValidationError):
        TransferMatch(
            outflow_txn_id="a",
            inflow_txn_id="b",
            amount=Decimal("1"),
            match_reason="x",
            extra="nope",  # type: ignore[call-arg]
        )


def test_transaction_amount_rejects_float() -> None:
    with pytest.raises(ValidationError):
        NormalizedTransaction(
            txn_id="t",
            account_id="A",
            amount=1.0,
            posted_date=date(2026, 1, 1),
        )


def test_transfer_candidate_exposed() -> None:
    cand = TransferCandidate(
        outflow_txn_id="a",
        inflow_txn_id="b",
        amount=Decimal("5"),
        day_gap=1,
        match_reason="r",
    )
    assert cand.day_gap == 1
    assert isinstance(cand.amount, Decimal)


# --------------------------------------------------------------------------
# Happy path: a pure A -> B transfer
# --------------------------------------------------------------------------


def test_simple_transfer_is_matched() -> None:
    txns = [
        _txn("out", "A", "-100.00", 10),
        _txn("in", "B", "100.00", 11),
    ]
    matches = match_transfers(txns)
    assert len(matches) == 1
    (m,) = matches
    assert m.outflow_txn_id == "out"
    assert m.inflow_txn_id == "in"
    assert m.amount == Decimal("100.00")


def test_pure_transfer_yields_zero_income_and_expense() -> None:
    txns = [
        _txn("out", "A", "-100.00", 10),
        _txn("in", "B", "100.00", 11),
    ]
    matches = match_transfers(txns)
    income, expense, transfer = classify_income_expense(txns, matches)
    assert income == Decimal(0)
    assert expense == Decimal(0)
    assert transfer == Decimal("100.00")


def test_credit_card_repayment_is_a_transfer() -> None:
    # Checking (asset) -> Visa (liability) repayment; same absolute amount.
    txns = [
        _txn("checking_out", "CHECKING", "-523.45", 5),
        _txn("visa_in", "VISA", "523.45", 5),
    ]
    matches = match_transfers(txns)
    assert len(matches) == 1
    income, expense, transfer = classify_income_expense(txns, matches)
    assert income == Decimal(0)
    assert expense == Decimal(0)
    assert transfer == Decimal("523.45")


# --------------------------------------------------------------------------
# Genuine income / expense are NOT matched
# --------------------------------------------------------------------------


def test_genuine_income_and_expense_are_counted() -> None:
    txns = [
        _txn("salary", "CHECKING", "3000.00", 1),  # income
        _txn("rent", "CHECKING", "-1200.00", 2),  # expense
    ]
    matches = match_transfers(txns)
    assert matches == ()
    income, expense, transfer = classify_income_expense(txns, matches)
    assert income == Decimal("3000.00")
    assert expense == Decimal("1200.00")
    assert transfer == Decimal(0)


def test_transfer_legs_excluded_but_other_activity_counted() -> None:
    txns = [
        _txn("out", "A", "-100.00", 10),
        _txn("in", "B", "100.00", 10),
        _txn("salary", "A", "2500.00", 1),
        _txn("coffee", "A", "-4.50", 3),
    ]
    matches = match_transfers(txns)
    assert len(matches) == 1
    income, expense, transfer = classify_income_expense(txns, matches)
    assert income == Decimal("2500.00")
    assert expense == Decimal("4.50")
    assert transfer == Decimal("100.00")


# --------------------------------------------------------------------------
# Non-matches: amount mismatch, window, same account, non-owned
# --------------------------------------------------------------------------


def test_amount_mismatch_is_not_matched() -> None:
    txns = [
        _txn("out", "A", "-100.00", 10),
        _txn("in", "B", "99.99", 10),
    ]
    assert match_transfers(txns) == ()


def test_outside_window_is_not_matched() -> None:
    txns = [
        _txn("out", "A", "-100.00", 1),
        _txn("in", "B", "100.00", 10),  # 9 days apart, default gap 3
    ]
    assert match_transfers(txns) == ()


def test_window_boundary_is_inclusive() -> None:
    txns = [
        _txn("out", "A", "-100.00", 1),
        _txn("in", "B", "100.00", 4),  # exactly 3 days
    ]
    assert len(match_transfers(txns, max_day_gap=3)) == 1


def test_same_account_is_not_matched() -> None:
    # Opposite legs in the SAME account are not a transfer between accounts.
    txns = [
        _txn("out", "A", "-100.00", 10),
        _txn("in", "A", "100.00", 10),
    ]
    assert match_transfers(txns) == ()


def test_non_owned_leg_is_not_matched_but_counted() -> None:
    txns = [
        _txn("out", "A", "-100.00", 10, owned=True),
        _txn("in", "EXTERNAL", "100.00", 10, owned=False),
    ]
    matches = match_transfers(txns)
    assert matches == ()
    income, expense, transfer = classify_income_expense(txns, matches)
    assert income == Decimal("100.00")
    assert expense == Decimal("100.00")
    assert transfer == Decimal(0)


def test_two_outflows_no_inflow_not_matched() -> None:
    txns = [
        _txn("out1", "A", "-100.00", 10),
        _txn("out2", "B", "-100.00", 10),
    ]
    assert match_transfers(txns) == ()


# --------------------------------------------------------------------------
# Each leg matched at most once + greedy nearest-date
# --------------------------------------------------------------------------


def test_each_leg_matched_at_most_once() -> None:
    # One outflow, two eligible inflows of the same amount; only one match.
    txns = [
        _txn("out", "A", "-50.00", 10),
        _txn("in_near", "B", "50.00", 11),
        _txn("in_far", "C", "50.00", 13),
    ]
    matches = match_transfers(txns)
    assert len(matches) == 1
    (m,) = matches
    # Greedy by nearest date picks the 1-day-gap inflow.
    assert m.inflow_txn_id == "in_near"


def test_two_independent_transfers_both_matched() -> None:
    txns = [
        _txn("o1", "A", "-100.00", 10),
        _txn("i1", "B", "100.00", 10),
        _txn("o2", "C", "-250.00", 12),
        _txn("i2", "D", "250.00", 12),
    ]
    matches = match_transfers(txns)
    assert len(matches) == 2
    income, expense, transfer = classify_income_expense(txns, matches)
    assert income == Decimal(0)
    assert expense == Decimal(0)
    assert transfer == Decimal("350.00")


def test_tie_break_is_deterministic_by_txn_id() -> None:
    # Two inflows at the SAME day-gap; tie-break must be deterministic.
    txns = [
        _txn("out", "A", "-50.00", 10),
        _txn("in_z", "B", "50.00", 11),
        _txn("in_a", "C", "50.00", 11),
    ]
    first = match_transfers(txns)
    # Reversed input order must give the same chosen leg.
    second = match_transfers(list(reversed(txns)))
    assert first == second
    assert len(first) == 1
    assert first[0].inflow_txn_id == "in_a"  # lexicographically smallest


def test_determinism_across_runs() -> None:
    txns = [
        _txn("o1", "A", "-100.00", 10),
        _txn("i1", "B", "100.00", 11),
        _txn("o2", "C", "-100.00", 10),
        _txn("i2", "D", "100.00", 12),
    ]
    assert match_transfers(txns) == match_transfers(list(txns))
    assert match_transfers(txns) == match_transfers(list(reversed(txns)))


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------


def test_negative_max_day_gap_rejected() -> None:
    with pytest.raises(TransferMatchError):
        match_transfers([_txn("o", "A", "-1", 1)], max_day_gap=-1)


def test_duplicate_txn_id_rejected() -> None:
    txns = [
        _txn("dup", "A", "-100.00", 10),
        _txn("dup", "B", "100.00", 10),
    ]
    with pytest.raises(TransferMatchError):
        match_transfers(txns)


def test_error_is_strix_error() -> None:
    assert issubclass(TransferMatchError, StrixError)


def test_empty_input() -> None:
    assert match_transfers([]) == ()
    income, expense, transfer = classify_income_expense([], ())
    assert income == Decimal(0)
    assert expense == Decimal(0)
    assert transfer == Decimal(0)
