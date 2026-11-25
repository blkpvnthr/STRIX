"""Account management on top of the double-entry ledger foundation.

The ledger (:mod:`strix.finance.ledger`) owns the deterministic accounting
core: a chart of :class:`~strix.finance.ledger.Account` records and the
balanced journal entries posted against them. This module adds the everyday
*account-management* layer on top of that core: a richer
:class:`AccountRecord` (institution, masked number, connection provider,
lifecycle status, opening balance) and an :class:`AccountStore` that registers
records, isolates them by owner, and drives their lifecycle transitions
(connected -> disconnected -> closed).

Design rules this module upholds (shared with the rest of the finance engine):

* Models are frozen and closed (``strix.models.StrixModel``). Lifecycle
  transitions produce copies via ``model_copy(update=...)`` — the stored
  record is replaced, never mutated in place.
* Monetary amounts use ``strix.models.DecimalValue`` — binary ``float`` is
  rejected at the model boundary; no amount is ever a ``float``.
* Content-derived identifiers come from ``strix.canonical.make_id``; the
  identifier is a stable hash of the account's *defining* fields and never
  includes the mutable lifecycle ``status`` (so a status transition keeps the
  same id) nor the id itself.
* Failures raise :class:`~strix.finance.ledger.FinanceError` (a
  ``strix.errors.StrixError``).

No network access and no live account aggregation happen here; the
``connected_provider`` field only records *which* aggregator a record was
imported from — connecting to it is a separate, credential-gated concern.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from enum import StrEnum

from strix.canonical import make_id
from strix.finance.ledger import AccountType, FinanceError
from strix.models import DecimalValue, StrixModel

__all__ = [
    "AccountRecord",
    "AccountStatus",
    "AccountStore",
    "consolidated_by_type",
    "make_account_record",
    "map_subtype",
]


class AccountStatus(StrEnum):
    """Lifecycle state of a managed account.

    * :attr:`ACTIVE` — connected to a live aggregator and syncing.
    * :attr:`DISCONNECTED` — was connected, but the link is no longer live;
      the record and its history are retained.
    * :attr:`CLOSED` — the account is closed and should no longer accrue
      activity; retained for historical reporting.
    * :attr:`MANUAL` — entered by hand, never linked to an aggregator (the
      default for a freshly created record).
    """

    ACTIVE = "active"
    CLOSED = "closed"
    DISCONNECTED = "disconnected"
    MANUAL = "manual"


class AccountRecord(StrixModel):
    """A managed account: a ledger account enriched with management metadata.

    The ledger identifies an account by (name, type, currency, owner). An
    :class:`AccountRecord` adds the fields an account-management layer needs —
    the institution it lives at, the masked last-four digits, the aggregator it
    was connected through, its lifecycle :class:`AccountStatus`, and an
    ``opening_balance`` — while keeping the same content-identity discipline.

    The ``account_id`` is a stable ``ACCT-`` content hash of the record's
    *defining* fields; it deliberately excludes the mutable ``status`` so that
    disconnecting or closing an account preserves its identity.
    """

    account_id: str
    name: str
    account_type: AccountType
    owner: str
    institution: str = ""
    #: Masked last-four digits of the account number (never the full number).
    mask: str = ""
    currency: str = "USD"
    status: AccountStatus = AccountStatus.MANUAL
    #: Name of the aggregator the record was imported from, if any.
    connected_provider: str | None = None
    opening_balance: DecimalValue = Decimal(0)


def make_account_record(
    *,
    name: str,
    account_type: AccountType,
    owner: str,
    institution: str = "",
    mask: str = "",
    currency: str = "USD",
    status: AccountStatus = AccountStatus.MANUAL,
    connected_provider: str | None = None,
    opening_balance: Decimal = Decimal(0),
) -> AccountRecord:
    """Build an :class:`AccountRecord` with a content-derived ``ACCT-`` id.

    Inputs are validated at the model boundary first (which rejects binary
    ``float`` for ``opening_balance``), then the content id is derived from the
    validated *defining* fields. The mutable ``status`` is excluded from the id
    so that identical account content yields the same identifier regardless of
    where it is in its lifecycle; identical content therefore always produces
    the same account id.
    """
    draft = AccountRecord(
        account_id="ACCT-pending",
        name=name,
        account_type=account_type,
        owner=owner,
        institution=institution,
        mask=mask,
        currency=currency,
        status=status,
        connected_provider=connected_provider,
        opening_balance=opening_balance,
    )
    payload: Mapping[str, object] = {
        "name": draft.name,
        "account_type": draft.account_type,
        "owner": draft.owner,
        "institution": draft.institution,
        "mask": draft.mask,
        "currency": draft.currency,
        "connected_provider": draft.connected_provider,
        "opening_balance": draft.opening_balance,
    }
    return draft.model_copy(update={"account_id": make_id("ACCT", payload)})


class AccountStore:
    """An in-memory registry of :class:`AccountRecord` keyed by content id.

    The store owns registration (rejecting a duplicate id), lookup, filtered
    listing (by owner, by type), and lifecycle transitions. Transitions replace
    the stored record with a status-updated copy; the record's identity (its
    ``account_id``) is preserved. Every unknown-id lookup or transition and
    every duplicate registration raises :class:`FinanceError`.
    """

    def __init__(self) -> None:
        self._records: dict[str, AccountRecord] = {}

    def register(self, record: AccountRecord) -> None:
        """Register *record*; reject a second record with the same id.

        Raises :class:`FinanceError` if an account with the same
        ``account_id`` is already registered — re-registration is never a
        silent overwrite.
        """
        if record.account_id in self._records:
            raise FinanceError(
                f"account {record.account_id!r} is already registered"
            )
        self._records[record.account_id] = record

    def all_records(self) -> tuple[AccountRecord, ...]:
        """Every registered record, ordered by ``account_id`` (deterministic)."""
        return tuple(self._records[k] for k in sorted(self._records))

    def get(self, account_id: str) -> AccountRecord:
        """Return the registered record for *account_id*.

        Raises :class:`FinanceError` if no such account is registered.
        """
        return self._require(account_id)

    def _require(self, account_id: str) -> AccountRecord:
        record = self._records.get(account_id)
        if record is None:
            raise FinanceError(f"unknown account {account_id!r}")
        return record

    def list_by_owner(self, owner: str) -> tuple[AccountRecord, ...]:
        """All registered records belonging to *owner*, in insertion order.

        Returns an empty tuple when the owner holds no accounts; a record is
        only ever returned to its own owner.
        """
        return tuple(
            record
            for record in self._records.values()
            if record.owner == owner
        )

    def list_by_type(
        self, account_type: AccountType
    ) -> tuple[AccountRecord, ...]:
        """All registered records of *account_type*, in insertion order."""
        return tuple(
            record
            for record in self._records.values()
            if record.account_type is account_type
        )

    def disconnect(self, account_id: str) -> AccountRecord:
        """Mark *account_id* as :attr:`AccountStatus.DISCONNECTED`.

        Replaces the stored record with a status-updated copy (identity and
        every other field preserved) and returns it. Raises
        :class:`FinanceError` for an unknown account.
        """
        return self._set_status(account_id, AccountStatus.DISCONNECTED)

    def close(self, account_id: str) -> AccountRecord:
        """Mark *account_id* as :attr:`AccountStatus.CLOSED`.

        Replaces the stored record with a status-updated copy (identity and
        every other field preserved) and returns it. Raises
        :class:`FinanceError` for an unknown account.
        """
        return self._set_status(account_id, AccountStatus.CLOSED)

    def _set_status(
        self, account_id: str, status: AccountStatus
    ) -> AccountRecord:
        record = self._require(account_id)
        updated = record.model_copy(update={"status": status})
        self._records[account_id] = updated
        return updated


def consolidated_by_type(
    records: Iterable[AccountRecord],
) -> dict[AccountType, tuple[str, ...]]:
    """Group account ids by their :class:`AccountType`.

    Returns a mapping from each account type *present* in *records* to the
    tuple of account ids of that type, preserving the input order within each
    group. A type with no records is absent from the result (so an empty input
    yields an empty mapping).
    """
    grouped: dict[AccountType, list[str]] = {}
    for record in records:
        grouped.setdefault(record.account_type, []).append(record.account_id)
    return {
        account_type: tuple(ids) for account_type, ids in grouped.items()
    }


#: Everyday account subtype names mapped onto the five fundamental account
#: classes. Checking, savings, and brokerage accounts hold assets. Credit
#: cards and loans are liabilities. Retirement and trust accounts hold assets
#: owned by the beneficiary (the custodial/fiduciary wrapper does not change
#: the underlying normal balance), so they are classified as :attr:`ASSET`.
_SUBTYPE_MAP: Mapping[str, AccountType] = {
    "checking": AccountType.ASSET,
    "savings": AccountType.ASSET,
    "brokerage": AccountType.ASSET,
    "retirement": AccountType.ASSET,
    "trust": AccountType.ASSET,
    "credit_card": AccountType.LIABILITY,
    "loan": AccountType.LIABILITY,
}


def map_subtype(name: str) -> AccountType:
    """Map an everyday account subtype *name* onto an :class:`AccountType`.

    The lookup is case-insensitive. See :data:`_SUBTYPE_MAP` for the supported
    subtypes and the rationale for retirement/trust accounts classifying as
    :attr:`AccountType.ASSET`. Raises :class:`FinanceError` for an unrecognized
    subtype — the mapping never silently guesses.
    """
    account_type = _SUBTYPE_MAP.get(name.lower())
    if account_type is None:
        raise FinanceError(f"unknown account subtype {name!r}")
    return account_type
