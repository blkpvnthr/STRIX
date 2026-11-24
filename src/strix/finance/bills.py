"""Recurring-obligation detection and offline bill reminders.

This module screens a sequence of :class:`NormalizedTransaction` outflows for
*recurring obligations* — subscriptions, rent, utilities, memberships — using
deterministic grouping and a median inter-arrival cadence. From a detected
obligation it can *estimate* the next due date, lay out an upcoming payment
calendar, flag past-due unconfirmed obligations, and deliver reminders to an
in-memory inbox.

Every output is **estimated, not confirmed**. Detection never asserts that a
future charge will actually post: a detected
:class:`RecurringObligation` carries ``confirmed=False`` and every
:func:`next_due` result is a projection from the observed cadence, not a
promise. A caller confirms an obligation by copying it with ``confirmed=True``;
only then is a reminder treated as a confirmed bill rather than an estimate.

Design rules this module upholds (shared with :mod:`strix.finance.anomaly`):

* Models are frozen and closed (:class:`strix.models.StrixModel`).
* Monetary amounts use :class:`strix.models.DecimalValue` — binary ``float``
  is rejected at the model boundary.
* Cadence is inferred from the exact-Decimal median of integer inter-arrival
  day gaps via :mod:`strix.native.statistics`, so grouping and detection are
  deterministic regardless of input order.
* Content-derived identifiers come from :func:`strix.canonical.make_id`; an id
  never participates in its own payload.
* Invalid inputs raise :class:`BillError` (a :class:`strix.errors.StrixError`).

No email, no network, and no live account aggregation happen here. The
notification adapter is a pure in-memory inbox.
"""

from __future__ import annotations

import calendar
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from itertools import pairwise

from strix.canonical import make_id
from strix.errors import StrixError
from strix.finance.transactions import NormalizedTransaction, make_transaction
from strix.models import DecimalValue, StrixModel
from strix.native import statistics as stats

__all__ = [
    "BillError",
    "Cadence",
    "LocalNotificationAdapter",
    "NormalizedTransaction",
    "Notification",
    "RecurringObligation",
    "detect_recurring",
    "make_transaction",
    "next_due",
    "overdue",
    "payment_calendar",
    "reminder_for",
]


class BillError(StrixError):
    """A bill-reminder input could not be trusted: an attempt to estimate an
    irregular obligation (which has no fixed cadence) or a negative calendar
    horizon."""


class Cadence(StrEnum):
    """The inter-arrival rhythm of a recurring obligation.

    :attr:`IRREGULAR` names a group whose observed median gap matches none of
    the fixed cadences; it is detected and reported but never projected forward
    (estimating its next due date raises :class:`BillError`).
    """

    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    IRREGULAR = "irregular"


class RecurringObligation(StrixModel):
    """A detected recurring outflow — a subscription, rent, or utility bill.

    ``typical_amount`` is the median outflow **magnitude** (a positive amount)
    and ``last_date`` is the most recent observed posting. ``confirmed`` is
    ``False`` for a freshly detected obligation: detection is a hypothesis, not
    a confirmed bill. A caller promotes it by copying with ``confirmed=True``.
    """

    obligation_id: str
    merchant: str
    typical_amount: DecimalValue
    cadence: Cadence
    last_date: date
    confirmed: bool = False


class Notification(StrixModel):
    """A single bill reminder destined for the in-memory inbox.

    ``estimated`` records whether the reminder is a projection from an
    unconfirmed obligation (``True``) or a reminder for a user-confirmed bill
    (``False``). The delivery key is ``(obligation_id, due_date)``.
    """

    obligation_id: str
    merchant: str
    due_date: date
    amount: DecimalValue
    note: str
    estimated: bool = True


# Nominal cadence intervals, used only to *project* future due dates. The day
# ranges below classify an observed median gap into one of these cadences.
_WEEK = timedelta(days=7)
_FORTNIGHT = timedelta(days=14)


def _normalize_merchant(text: str) -> str:
    """Case-fold and collapse internal whitespace for deterministic grouping."""
    return " ".join(text.lower().split())


def _amount_bucket(magnitude: Decimal) -> Decimal:
    """Round an outflow magnitude to the nearest whole unit for grouping.

    Charges that drift by cents (``15.99`` vs ``16.00``) still group together,
    while genuinely different amounts stay apart. Deterministic: banker's
    rounding on an exact Decimal.
    """
    return magnitude.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)


def _infer_cadence(median_days: Decimal) -> Cadence:
    """Classify a median inter-arrival gap (in days) into a :class:`Cadence`.

    The windows are deliberately wide enough to absorb calendar jitter (28-31
    day months, weekend-shifted postings) yet disjoint, so a gap maps to at
    most one fixed cadence; anything else is :attr:`Cadence.IRREGULAR`.
    """
    if Decimal(5) <= median_days <= Decimal(9):
        return Cadence.WEEKLY
    if Decimal(11) <= median_days <= Decimal(18):
        return Cadence.BIWEEKLY
    if Decimal(26) <= median_days <= Decimal(33):
        return Cadence.MONTHLY
    if Decimal(84) <= median_days <= Decimal(96):
        return Cadence.QUARTERLY
    if Decimal(350) <= median_days <= Decimal(380):
        return Cadence.YEARLY
    return Cadence.IRREGULAR


def _add_months(anchor: date, months: int) -> date:
    """Advance ``anchor`` by whole months, clamping the day to the month end."""
    index = anchor.month - 1 + months
    year = anchor.year + index // 12
    month = index % 12 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _step(anchor: date, cadence: Cadence) -> date:
    """Project one nominal cadence interval forward from ``anchor``.

    Weekly and biweekly step by fixed days; monthly, quarterly, and yearly step
    by whole calendar months so a charge keeps its day-of-month. Irregular has
    no fixed interval and raises :class:`BillError`.
    """
    if cadence is Cadence.WEEKLY:
        return anchor + _WEEK
    if cadence is Cadence.BIWEEKLY:
        return anchor + _FORTNIGHT
    if cadence is Cadence.MONTHLY:
        return _add_months(anchor, 1)
    if cadence is Cadence.QUARTERLY:
        return _add_months(anchor, 3)
    if cadence is Cadence.YEARLY:
        return _add_months(anchor, 12)
    raise BillError(
        "cannot project a due date for an irregular obligation (no fixed cadence)"
    )


def detect_recurring(
    txns: Sequence[NormalizedTransaction],
    *,
    min_occurrences: int = 3,
) -> tuple[RecurringObligation, ...]:
    """Detect recurring outflow obligations from a transaction history.

    Outflows (negative amounts) are grouped by normalized merchant and rounded
    magnitude; inflows are ignored. A group with at least ``min_occurrences``
    members becomes one :class:`RecurringObligation` whose cadence is inferred
    from the exact-Decimal median of its consecutive inter-arrival day gaps. A
    detected obligation is always ``confirmed=False`` — detection proposes, it
    does not confirm. The result is sorted by ``(merchant, typical_amount)`` so
    it is deterministic regardless of input order.
    """
    groups: dict[tuple[str, Decimal], list[NormalizedTransaction]] = {}
    for txn in txns:
        if txn.amount >= 0:
            continue
        magnitude = -txn.amount
        key = (_normalize_merchant(txn.description), _amount_bucket(magnitude))
        groups.setdefault(key, []).append(txn)

    obligations: list[RecurringObligation] = []
    for (merchant, _bucket), members in groups.items():
        if len(members) < min_occurrences:
            continue
        ordered = sorted(members, key=lambda t: t.posted_date)
        magnitudes = [-t.amount for t in ordered]
        typical_amount = stats.median(magnitudes)

        gaps = [
            (later.posted_date - earlier.posted_date).days
            for earlier, later in pairwise(ordered)
        ]
        cadence = (
            _infer_cadence(stats.median(gaps)) if gaps else Cadence.IRREGULAR
        )

        payload: Mapping[str, object] = {
            "merchant": merchant,
            "typical_amount": typical_amount,
            "cadence": cadence,
            "last_date": ordered[-1].posted_date,
        }
        obligations.append(
            RecurringObligation(
                obligation_id=make_id("OBL", payload),
                merchant=merchant,
                typical_amount=typical_amount,
                cadence=cadence,
                last_date=ordered[-1].posted_date,
            )
        )

    return tuple(
        sorted(obligations, key=lambda o: (o.merchant, o.typical_amount))
    )


def _next_after(anchor: date, cadence: Cadence) -> date:
    """The first projected due date strictly after ``anchor`` (one step)."""
    return _step(anchor, cadence)


def next_due(obligation: RecurringObligation, *, from_date: date) -> date:
    """Estimate the next due date strictly after ``from_date``.

    The projection starts one cadence step past ``last_date`` (the last observed
    payment is already made) and advances until it clears ``from_date``. The
    returned date is an **estimate** from the observed cadence, not a confirmed
    charge. An irregular obligation has no fixed cadence and raises
    :class:`BillError`.
    """
    if obligation.cadence is Cadence.IRREGULAR:
        raise BillError(
            "cannot estimate the next due date for an irregular obligation"
        )
    candidate = _next_after(obligation.last_date, obligation.cadence)
    while candidate <= from_date:
        candidate = _step(candidate, obligation.cadence)
    return candidate


def payment_calendar(
    obligations: Sequence[RecurringObligation],
    *,
    from_date: date,
    horizon_days: int,
) -> tuple[tuple[date, str, Decimal], ...]:
    """Lay out every estimated due date within the horizon window.

    Produces one ``(due_date, merchant, amount)`` row per projected payment in
    ``(from_date, from_date + horizon_days]`` for every non-irregular
    obligation, sorted by ``(due_date, merchant, amount)``. Irregular
    obligations are skipped (they cannot be projected). A negative
    ``horizon_days`` raises :class:`BillError`.
    """
    if horizon_days < 0:
        raise BillError(f"horizon_days must be non-negative, got {horizon_days}")
    end = from_date + timedelta(days=horizon_days)

    rows: list[tuple[date, str, Decimal]] = []
    for obligation in obligations:
        if obligation.cadence is Cadence.IRREGULAR:
            continue
        due = next_due(obligation, from_date=from_date)
        while due <= end:
            rows.append((due, obligation.merchant, obligation.typical_amount))
            due = _step(due, obligation.cadence)

    return tuple(sorted(rows, key=lambda r: (r[0], r[1], r[2])))


def overdue(
    obligations: Sequence[RecurringObligation],
    *,
    today: date,
) -> tuple[RecurringObligation, ...]:
    """Flag unconfirmed obligations whose next expected payment is past due.

    An obligation is overdue when it is unconfirmed, has a fixed cadence, and
    the first payment projected after ``last_date`` falls before ``today`` —
    i.e. a charge was expected by now but the obligation has not been confirmed.
    Confirmed and irregular obligations are never flagged. The result is sorted
    by ``(last_date, merchant)``.
    """
    flagged = [
        obligation
        for obligation in obligations
        if not obligation.confirmed
        and obligation.cadence is not Cadence.IRREGULAR
        and _next_after(obligation.last_date, obligation.cadence) < today
    ]
    return tuple(sorted(flagged, key=lambda o: (o.last_date, o.merchant)))


def reminder_for(
    obligation: RecurringObligation,
    *,
    due_date: date,
) -> Notification:
    """Build a :class:`Notification` for ``obligation`` at ``due_date``.

    The reminder is marked ``estimated`` unless the obligation has been
    confirmed, preserving the estimate-versus-confirmed distinction all the way
    to delivery. The note text is explicit about which it is.
    """
    estimated = not obligation.confirmed
    qualifier = "Estimated" if estimated else "Confirmed"
    note = (
        f"{qualifier} {obligation.cadence.value} payment of "
        f"{obligation.typical_amount} to {obligation.merchant} is due on "
        f"{due_date.isoformat()}."
    )
    return Notification(
        obligation_id=obligation.obligation_id,
        merchant=obligation.merchant,
        due_date=due_date,
        amount=obligation.typical_amount,
        note=note,
        estimated=estimated,
    )


class LocalNotificationAdapter:
    """An offline, in-memory reminder inbox — no email and no network.

    Delivery is idempotent on the ``(obligation_id, due_date)`` key: sending the
    same reminder twice records exactly one inbox entry, so re-running a
    calendar never produces duplicate reminders.
    """

    def __init__(self) -> None:
        self._inbox: list[Notification] = []
        self._keys: set[tuple[str, date]] = set()

    def send(self, notification: Notification) -> bool:
        """Record ``notification`` unless its delivery key was already seen.

        Returns ``True`` when the reminder is newly recorded and ``False`` when
        an identical ``(obligation_id, due_date)`` reminder was already
        delivered (the duplicate is suppressed).
        """
        key = (notification.obligation_id, notification.due_date)
        if key in self._keys:
            return False
        self._keys.add(key)
        self._inbox.append(notification)
        return True

    @property
    def inbox(self) -> tuple[Notification, ...]:
        """The delivered reminders, in delivery order."""
        return tuple(self._inbox)
