"""The one canonical normalized-transaction model for the finance engine.

Every offline personal-finance stage — CSV import (Bronze -> Silver),
internal-transfer matching, and spending-anomaly screening — speaks the same
Silver-layer shape so the modules compose without translation. That shape is
:class:`NormalizedTransaction`: one posted ledger line from an owned (or
external) account.

Design rules this module upholds (shared with :mod:`strix.finance.ledger`):

* The model is frozen and closed (``strix.models.StrixModel``).
* ``amount`` is signed on the account's own perspective and uses
  ``strix.models.DecimalValue`` — negative is an outflow (money leaving the
  account), positive is an inflow. Binary ``float`` is rejected at the model
  boundary; no amount is ever a ``float``.
* Content-derived identifiers come from ``strix.canonical.make_id``; an id
  never participates in its own payload.

No network access and no live account aggregation happen here; those are a
separate, credential-gated concern.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from strix.canonical import make_id
from strix.models import DecimalValue, StrixModel

__all__ = [
    "NormalizedTransaction",
    "make_transaction",
]


class NormalizedTransaction(StrixModel):
    """One normalized Silver-layer ledger line, shared across finance stages.

    ``amount`` is signed on the account's own perspective: a negative amount is
    an **outflow** (money leaving the account — a spend, charge, or debit) and a
    positive amount is an inflow. Spending-anomaly screening considers outflows
    only; transfer matching pairs an outflow leg with an equal-and-opposite
    inflow leg. Only transactions in an ``owned`` account are eligible to form a
    transfer; a non-owned (external counterparty) line is still counted toward
    income/expense but can never be a transfer leg.

    ``raw_digest`` links back to the originating Bronze row when the line came
    from CSV import (``None`` when it was constructed directly); ``txn_id`` is a
    deterministic ``TXN-`` content identifier.
    """

    txn_id: str
    account_id: str
    posted_date: date
    #: Signed amount; negative = outflow, positive = inflow.
    amount: DecimalValue
    description: str = ""
    raw_digest: str | None = None
    owned: bool = True


def make_transaction(
    *,
    posted_date: date,
    amount: Decimal,
    account_id: str = "",
    description: str = "",
    raw_digest: str | None = None,
    owned: bool = True,
) -> NormalizedTransaction:
    """Build a :class:`NormalizedTransaction` with a content-derived ``TXN-`` id.

    The identifier is a stable hash of the transaction's defining fields —
    every field except the ``txn_id`` itself — so identical content always
    yields the same transaction id. Inputs are validated at the model boundary
    first (which rejects binary ``float``), then the content id is derived from
    the validated fields.
    """
    draft = NormalizedTransaction(
        txn_id="TXN-pending",
        account_id=account_id,
        posted_date=posted_date,
        amount=amount,
        description=description,
        raw_digest=raw_digest,
        owned=owned,
    )
    payload: Mapping[str, object] = {
        "account_id": draft.account_id,
        "posted_date": draft.posted_date,
        "amount": draft.amount,
        "description": draft.description,
        "raw_digest": draft.raw_digest,
        "owned": draft.owned,
    }
    return draft.model_copy(update={"txn_id": make_id("TXN", payload)})
