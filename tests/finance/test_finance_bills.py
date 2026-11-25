"""Tests for recurring-obligation detection and offline bill reminders.

The module screens a sequence of normalized transactions for *recurring
outflows* (subscriptions, rent, utilities) using deterministic grouping and a
median inter-arrival cadence. A detected obligation is **estimated, never
confirmed** — detection never asserts that a future charge will actually post.

These tests assert the happy paths (a monthly charge is detected with monthly
cadence; the next due date is estimated; a calendar is produced in date order),
the invariants (confirmed obligations are distinguished from estimated ones;
notification delivery is idempotent by ``(obligation_id, due_date)``), the
overdue flagging of past-due unconfirmed obligations, and the adversarial edges
(float rejection at the model boundary, a negative horizon, and an irregular
obligation that cannot be estimated all raise a typed error).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.errors import StrixError
from strix.finance.bills import (
    BillError,
    Cadence,
    LocalNotificationAdapter,
    Notification,
    RecurringObligation,
    detect_recurring,
    next_due,
    overdue,
    payment_calendar,
    reminder_for,
)
from strix.finance.transactions import NormalizedTransaction, make_transaction

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _txn(posted: str, amount: str, description: str) -> NormalizedTransaction:
    """Build an outflow transaction (negative amount) from string inputs."""
    return make_transaction(
        posted_date=date.fromisoformat(posted),
        amount=Decimal(amount),
        description=description,
    )


def _monthly_netflix() -> list[NormalizedTransaction]:
    """A clean monthly subscription charge posted on the 15th for 4 months."""
    return [
        _txn("2025-01-15", "-15.99", "NETFLIX.COM"),
        _txn("2025-02-15", "-15.99", "NETFLIX.COM"),
        _txn("2025-03-15", "-15.99", "NETFLIX.COM"),
        _txn("2025-04-15", "-15.99", "NETFLIX.COM"),
    ]


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------


def test_monthly_charge_detected_with_monthly_cadence() -> None:
    obligations = detect_recurring(_monthly_netflix())
    assert len(obligations) == 1
    ob = obligations[0]
    assert ob.cadence is Cadence.MONTHLY
    assert ob.merchant == "netflix.com"
    assert ob.typical_amount == Decimal("15.99")
    assert ob.last_date == date(2025, 4, 15)
    assert ob.confirmed is False
    assert ob.obligation_id.startswith("OBL-")


def test_detection_is_deterministic() -> None:
    txns = _monthly_netflix()
    first = detect_recurring(txns)
    # Reversed input must yield an identical result (ids and ordering stable).
    second = detect_recurring(list(reversed(txns)))
    assert first == second


def test_below_min_occurrences_is_not_detected() -> None:
    txns = _monthly_netflix()[:2]
    assert detect_recurring(txns) == ()


def test_min_occurrences_override_detects_short_series() -> None:
    txns = _monthly_netflix()[:2]
    obligations = detect_recurring(txns, min_occurrences=2)
    assert len(obligations) == 1
    assert obligations[0].cadence is Cadence.MONTHLY


def test_weekly_cadence_inferred() -> None:
    txns = [
        _txn("2025-01-06", "-9.00", "GYM"),
        _txn("2025-01-13", "-9.00", "GYM"),
        _txn("2025-01-20", "-9.00", "GYM"),
        _txn("2025-01-27", "-9.00", "GYM"),
    ]
    (ob,) = detect_recurring(txns)
    assert ob.cadence is Cadence.WEEKLY


def test_inflows_are_ignored() -> None:
    txns = [
        make_transaction(
            posted_date=date(2025, 1, 1), amount=Decimal("1000.00"), description="PAYROLL"
        ),
        make_transaction(
            posted_date=date(2025, 2, 1), amount=Decimal("1000.00"), description="PAYROLL"
        ),
        make_transaction(
            posted_date=date(2025, 3, 1), amount=Decimal("1000.00"), description="PAYROLL"
        ),
    ]
    assert detect_recurring(txns) == ()


def test_empty_input_detects_nothing() -> None:
    assert detect_recurring([]) == ()


# --------------------------------------------------------------------------
# next_due estimation
# --------------------------------------------------------------------------


def test_next_due_is_estimated_after_from_date() -> None:
    (ob,) = detect_recurring(_monthly_netflix())
    due = next_due(ob, from_date=date(2025, 4, 20))
    assert due == date(2025, 5, 15)


def test_next_due_advances_past_a_distant_from_date() -> None:
    (ob,) = detect_recurring(_monthly_netflix())
    due = next_due(ob, from_date=date(2025, 7, 1))
    assert due == date(2025, 7, 15)


def test_next_due_irregular_raises() -> None:
    ob = RecurringObligation(
        obligation_id="OBL-test",
        merchant="odd",
        typical_amount=Decimal("5.00"),
        cadence=Cadence.IRREGULAR,
        last_date=date(2025, 1, 1),
    )
    with pytest.raises(BillError):
        next_due(ob, from_date=date(2025, 2, 1))


# --------------------------------------------------------------------------
# payment_calendar
# --------------------------------------------------------------------------


def test_payment_calendar_is_sorted_by_date() -> None:
    netflix = detect_recurring(_monthly_netflix())
    rent = detect_recurring(
        [
            _txn("2025-01-01", "-1200.00", "RENT"),
            _txn("2025-02-01", "-1200.00", "RENT"),
            _txn("2025-03-01", "-1200.00", "RENT"),
            _txn("2025-04-01", "-1200.00", "RENT"),
        ]
    )
    calendar = payment_calendar(
        [*netflix, *rent], from_date=date(2025, 4, 15), horizon_days=40
    )
    dates = [row[0] for row in calendar]
    assert dates == sorted(dates)
    # Rent on the 1st (2025-05-01) and Netflix on the 15th (2025-05-15) both land.
    assert (date(2025, 5, 1), "rent", Decimal("1200.00")) in calendar
    assert (date(2025, 5, 15), "netflix.com", Decimal("15.99")) in calendar


def test_payment_calendar_excludes_irregular() -> None:
    ob = RecurringObligation(
        obligation_id="OBL-x",
        merchant="odd",
        typical_amount=Decimal("5.00"),
        cadence=Cadence.IRREGULAR,
        last_date=date(2025, 1, 1),
    )
    assert payment_calendar([ob], from_date=date(2025, 1, 1), horizon_days=400) == ()


def test_payment_calendar_negative_horizon_raises() -> None:
    (ob,) = detect_recurring(_monthly_netflix())
    with pytest.raises(BillError):
        payment_calendar([ob], from_date=date(2025, 4, 15), horizon_days=-1)


# --------------------------------------------------------------------------
# overdue
# --------------------------------------------------------------------------


def test_overdue_flags_past_due_unconfirmed() -> None:
    (ob,) = detect_recurring(_monthly_netflix())  # last_date 2025-04-15, monthly
    # The next expected charge (2025-05-15) is before "today", and unconfirmed.
    flagged = overdue([ob], today=date(2025, 6, 1))
    assert flagged == (ob,)


def test_overdue_skips_confirmed() -> None:
    (ob,) = detect_recurring(_monthly_netflix())
    confirmed = ob.model_copy(update={"confirmed": True})
    assert overdue([confirmed], today=date(2025, 6, 1)) == ()


def test_overdue_skips_not_yet_due() -> None:
    (ob,) = detect_recurring(_monthly_netflix())
    assert overdue([ob], today=date(2025, 4, 20)) == ()


# --------------------------------------------------------------------------
# Notification adapter idempotency + estimated/confirmed distinction
# --------------------------------------------------------------------------


def test_notification_delivery_is_idempotent() -> None:
    (ob,) = detect_recurring(_monthly_netflix())
    note = reminder_for(ob, due_date=date(2025, 5, 15))
    adapter = LocalNotificationAdapter()
    assert adapter.send(note) is True
    # Same (obligation_id, due_date) key -> suppressed, one inbox entry.
    assert adapter.send(note) is False
    assert len(adapter.inbox) == 1


def test_distinct_due_dates_are_separate_reminders() -> None:
    (ob,) = detect_recurring(_monthly_netflix())
    adapter = LocalNotificationAdapter()
    adapter.send(reminder_for(ob, due_date=date(2025, 5, 15)))
    adapter.send(reminder_for(ob, due_date=date(2025, 6, 15)))
    assert len(adapter.inbox) == 2


def test_reminder_for_estimated_obligation_is_estimated() -> None:
    (ob,) = detect_recurring(_monthly_netflix())
    note = reminder_for(ob, due_date=date(2025, 5, 15))
    assert note.estimated is True
    assert note.obligation_id == ob.obligation_id
    assert note.amount == ob.typical_amount


def test_reminder_for_confirmed_obligation_is_not_estimated() -> None:
    (ob,) = detect_recurring(_monthly_netflix())
    confirmed = ob.model_copy(update={"confirmed": True})
    note = reminder_for(confirmed, due_date=date(2025, 5, 15))
    assert note.estimated is False


# --------------------------------------------------------------------------
# Model boundary: float rejection
# --------------------------------------------------------------------------


def test_obligation_rejects_float_amount() -> None:
    with pytest.raises(ValidationError):
        RecurringObligation(
            obligation_id="OBL-f",
            merchant="x",
            typical_amount=1.5,  # type: ignore[arg-type]
            cadence=Cadence.MONTHLY,
            last_date=date(2025, 1, 1),
        )


def test_notification_rejects_float_amount() -> None:
    with pytest.raises(ValidationError):
        Notification(
            obligation_id="OBL-f",
            merchant="x",
            due_date=date(2025, 1, 1),
            amount=1.5,  # type: ignore[arg-type]
            note="n",
        )


def test_bill_error_is_strix_error() -> None:
    assert issubclass(BillError, StrixError)
