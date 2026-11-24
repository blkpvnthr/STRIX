"""Internal-transfer and credit-card-repayment matching.

The deterministic core correctness property this module upholds: a transfer
between the user's *own* accounts — an account-to-account move, a credit-card
repayment, or a brokerage deposit — must never be counted as new income or
new expense. It is a relocation of existing money, not a flow in or out of the
household balance sheet.

The engine normalizes each bank/brokerage line into a
:class:`NormalizedTransaction` (a signed exact :class:`~decimal.Decimal`
amount: negative = outflow, positive = inflow), then pairs an outflow in one
owned account with an equal-and-opposite inflow in a *different* owned account
that lands within a bounded number of days. Each transaction is consumed by at
most one pairing; matching is greedy by nearest date with a deterministic
tie-break on transaction id, so the result never depends on input ordering.

Design rules upheld here (shared with :mod:`strix.finance.ledger`):

* Models are frozen and closed (``strix.models.StrixModel``).
* Monetary amounts use ``strix.models.DecimalValue`` — binary ``float`` is
  rejected at the model boundary; no amount is ever a ``float``.
* Reductions go through ``strix.native.arithmetic`` (``checked_sum``) so sums
  stay exact regardless of magnitude or count.
* Failures raise :class:`TransferMatchError` (a ``strix.errors.StrixError``).

No network access and no live account aggregation happen here; those are a
separate, credential-gated concern.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal

from pydantic import model_validator

from strix.finance.ledger import FinanceError
from strix.finance.transactions import NormalizedTransaction
from strix.models import DecimalValue, StrixModel
from strix.native.arithmetic import checked_sum

__all__ = [
    "NormalizedTransaction",
    "TransferCandidate",
    "TransferMatch",
    "TransferMatchError",
    "classify_income_expense",
    "match_transfers",
]


class TransferMatchError(FinanceError):
    """Transfer matching received invalid input (a negative day window, or two
    transactions sharing one id so a leg could be matched twice)."""


class TransferCandidate(StrixModel):
    """A possible pairing of an outflow leg with an inflow leg.

    Carries the inter-leg ``day_gap`` so candidates can be ranked by nearest
    date before the greedy, at-most-once assignment is made.
    """

    outflow_txn_id: str
    inflow_txn_id: str
    amount: DecimalValue
    day_gap: int
    match_reason: str


class TransferMatch(StrixModel):
    """A confirmed internal transfer: an outflow leg and the inflow leg it was
    paired with, plus the exact absolute amount moved."""

    outflow_txn_id: str
    inflow_txn_id: str
    amount: DecimalValue
    match_reason: str

    @model_validator(mode="after")
    def _distinct_legs(self) -> TransferMatch:
        if self.outflow_txn_id == self.inflow_txn_id:
            raise ValueError("a transfer's two legs must be distinct transactions")
        return self


def _exact_sum(values: Iterable[Decimal]) -> Decimal:
    """Exact sum that returns ``Decimal(0)`` for an empty input."""
    items = list(values)
    return checked_sum(items) if items else Decimal(0)


def _day_gap(a: date, b: date) -> int:
    """Absolute whole-day distance between two posting dates."""
    return abs((a - b).days)


def match_transfers(
    transactions: Sequence[NormalizedTransaction],
    *,
    max_day_gap: int = 3,
) -> tuple[TransferMatch, ...]:
    """Pair equal-and-opposite legs across different owned accounts.

    An outflow (negative amount) in one owned account is matched with an
    inflow (positive amount) of the *same absolute* Decimal amount in a
    *different* owned account whose posting date is within ``max_day_gap``
    days (inclusive). Amounts must match exactly as Decimals.

    Assignment is a **maximum-cardinality bipartite matching** (not greedy), so
    the largest possible set of transfers is paired; each leg is used at most
    once and the result is independent of input ordering (deterministic, with a
    nearest-date preference).

    LIMITATION (known false-positive mode): matching uses only amount magnitude,
    opposite sign, a different owned account, and the date window — it has no
    corroborating signal (counterparty, memo). Two *unrelated* genuine
    transactions of equal magnitude within the window (e.g. a $2,500 rent expense
    and a $2,500 salary deposit) can be wrongly matched as a transfer, hiding
    both from income/expense. Treat a :class:`TransferMatch` as a *candidate for
    review*, not a confirmed transfer; production use should corroborate with
    counterparty/description data. See ``research/limitations.md``.

    Raises :class:`TransferMatchError` if ``max_day_gap`` is negative or if two
    transactions share a ``txn_id`` (which would let one leg be matched twice).
    """
    if max_day_gap < 0:
        raise TransferMatchError(
            f"max_day_gap must be non-negative, got {max_day_gap}"
        )

    seen: set[str] = set()
    for txn in transactions:
        if txn.txn_id in seen:
            raise TransferMatchError(
                f"duplicate transaction id {txn.txn_id!r}"
            )
        seen.add(txn.txn_id)

    outflows = [
        txn for txn in transactions if txn.owned and txn.amount < 0
    ]
    inflows = [
        txn for txn in transactions if txn.owned and txn.amount > 0
    ]

    candidates: list[TransferCandidate] = []
    for outflow in outflows:
        magnitude = -outflow.amount
        for inflow in inflows:
            if inflow.account_id == outflow.account_id:
                continue
            if inflow.amount != magnitude:
                continue
            gap = _day_gap(outflow.posted_date, inflow.posted_date)
            if gap > max_day_gap:
                continue
            candidates.append(
                TransferCandidate(
                    outflow_txn_id=outflow.txn_id,
                    inflow_txn_id=inflow.txn_id,
                    amount=magnitude,
                    day_gap=gap,
                    match_reason=(
                        "internal transfer: equal and opposite amount "
                        f"{magnitude} across accounts within {gap} day(s)"
                    ),
                )
            )

    # Maximum-cardinality bipartite matching (Kuhn's augmenting paths), so the
    # most transfers possible are paired. Greedy nearest-date assignment could
    # strand a leg whose only feasible partner was consumed by a shorter-gap
    # edge, leaving a real transfer unmatched and double-counting it as both
    # income and expense. Adjacency is ordered (day_gap, inflow id) and outflows
    # are processed in id order, so a maximum matching is selected deterministically
    # with a nearest-date preference.
    candidate_by_pair: dict[tuple[str, str], TransferCandidate] = {
        (c.outflow_txn_id, c.inflow_txn_id): c for c in candidates
    }
    adjacency: dict[str, list[str]] = {}
    for candidate in sorted(candidates, key=lambda c: (c.day_gap, c.inflow_txn_id)):
        adjacency.setdefault(candidate.outflow_txn_id, []).append(candidate.inflow_txn_id)

    inflow_match: dict[str, str] = {}  # inflow_txn_id -> outflow_txn_id

    def _augment(outflow_id: str, visited: set[str]) -> bool:
        for inflow_id in adjacency.get(outflow_id, ()):
            if inflow_id in visited:
                continue
            visited.add(inflow_id)
            current = inflow_match.get(inflow_id)
            if current is None or _augment(current, visited):
                inflow_match[inflow_id] = outflow_id
                return True
        return False

    for outflow in sorted(outflows, key=lambda t: t.txn_id):
        _augment(outflow.txn_id, set())

    matches = [
        TransferMatch(
            outflow_txn_id=outflow_id,
            inflow_txn_id=inflow_id,
            amount=candidate_by_pair[(outflow_id, inflow_id)].amount,
            match_reason=candidate_by_pair[(outflow_id, inflow_id)].match_reason,
        )
        for inflow_id, outflow_id in inflow_match.items()
    ]
    matches.sort(key=lambda m: (m.outflow_txn_id, m.inflow_txn_id))
    return tuple(matches)


def classify_income_expense(
    transactions: Sequence[NormalizedTransaction],
    matches: Sequence[TransferMatch],
) -> tuple[Decimal, Decimal, Decimal]:
    """Split transactions into income, expense, and transfer totals.

    The legs of every :class:`TransferMatch` are excluded from both income and
    expense. Of the remaining transactions, positive amounts are summed as
    income and the absolute value of negative amounts is summed as expense;
    the exact absolute amounts of the matched transfers are summed separately.

    Returns ``(income_total, expense_total, transfer_total)`` as exact
    :class:`~decimal.Decimal` values. A pure account-to-account transfer
    therefore yields ``income_total == 0`` and ``expense_total == 0``.
    """
    matched_ids: set[str] = set()
    for match in matches:
        matched_ids.add(match.outflow_txn_id)
        matched_ids.add(match.inflow_txn_id)

    income_parts = [
        txn.amount
        for txn in transactions
        if txn.txn_id not in matched_ids and txn.amount > 0
    ]
    expense_parts = [
        -txn.amount
        for txn in transactions
        if txn.txn_id not in matched_ids and txn.amount < 0
    ]
    transfer_parts = [match.amount for match in matches]

    return (
        _exact_sum(income_parts),
        _exact_sum(expense_parts),
        _exact_sum(transfer_parts),
    )
