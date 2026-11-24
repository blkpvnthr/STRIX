"""Read-only provider-adapter contracts + offline fixture implementations.

Live account aggregation (Plaid, Teller, SnapTrade, Alpaca) is a separate,
credential-gated concern from the deterministic ledger core. This module
defines the *contract* every such adapter must satisfy and ships one fully
offline implementation — :class:`FixtureConnector` — that serves preserved
synthetic payloads. It performs **no network I/O, reads no credentials, and
makes no live calls**; it exists so the adapter boundary can be exercised and
regression-tested without touching a real provider.

The contract is deliberately **read-only**. :class:`ProviderConnector` exposes
exactly two fetch methods and a name — there is no write, trade, transfer,
order, or payment method anywhere on the surface. A personal-finance research
engine observes balances and transactions; it never moves money.

Provider sign convention
------------------------
:class:`ProviderTransaction.amount` is already carried in the engine's signed
convention: **negative is an outflow** (money leaving the account — a spend,
charge, or debit) and **positive is an inflow**. An adapter for a provider that
uses the opposite convention (e.g. Plaid, where a positive amount is an
outflow) is responsible for flipping the sign at *its* boundary so that every
:class:`ProviderTransaction` this module sees is already normalized. From
there, :meth:`FixtureConnector.to_normalized` maps one provider transaction
onto the canonical :class:`~strix.finance.transactions.NormalizedTransaction`
with a deterministic ``TXN-`` content id and a ``raw_digest`` that binds the
normalized line back to the exact provider payload it came from.

LIVE_VALIDATED procedure (documentation only — no HTTP is implemented here)
---------------------------------------------------------------------------
A concrete live adapter (built elsewhere, behind credentials) is considered
``LIVE_VALIDATED`` only after a single **read-only** endpoint has been reached
with a real token supplied through the provider's environment variable. The
exact token variable and the one read-only endpoint per provider are:

* **Plaid** — token env ``PLAID_ACCESS_TOKEN`` (with ``PLAID_CLIENT_ID`` and
  ``PLAID_SECRET``); read-only call ``POST /accounts/get``. (Balances and
  accounts only; no item mutation.)
* **Teller** — token env ``TELLER_ACCESS_TOKEN``; read-only call
  ``GET https://api.teller.io/accounts``.
* **SnapTrade** — credentials env ``SNAPTRADE_CLIENT_ID``,
  ``SNAPTRADE_CONSUMER_KEY``, ``SNAPTRADE_USER_ID``, ``SNAPTRADE_USER_SECRET``;
  read-only call ``GET /api/v1/accounts``.
* **Alpaca** — credentials env ``APCA_API_KEY_ID`` and ``APCA_API_SECRET_KEY``;
  read-only call ``GET /v2/account`` (the trading-account snapshot; the
  order-placement endpoints are deliberately never called).

None of the above is implemented in this module: the only HTTP that ever runs
against a provider lives in a separate, credential-gated package. This module
and its tests remain fully offline.

Design rules upheld here (shared with :mod:`strix.finance.ledger`):

* Models are frozen and closed (``strix.models.StrixModel``).
* Monetary amounts use ``strix.models.DecimalValue`` — binary ``float`` is
  rejected at the model boundary; no amount is ever a ``float``.
* Content-derived identifiers and digests come from ``strix.canonical``.
* Failures raise :class:`ConnectorError` (a ``strix.errors.StrixError``).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Protocol, runtime_checkable

from strix.canonical import canonical_hash
from strix.errors import StrixError
from strix.finance.transactions import NormalizedTransaction, make_transaction
from strix.models import DecimalValue, StrixModel

__all__ = [
    "ConnectorError",
    "FixtureBundle",
    "FixtureConnector",
    "ProviderAccount",
    "ProviderConnector",
    "ProviderTransaction",
]


class ConnectorError(StrixError):
    """A read-only connector could not serve a requested payload.

    Raised for an ``access_ref`` or ``account_id`` the connector has no
    fixtures for. Never raised to signal a live failure — this module makes no
    live calls.
    """


class ProviderAccount(StrixModel):
    """Normalized provider account payload (the read-only accounts shape).

    ``account_id`` is the provider's stable account identifier; ``account_type``
    is the provider's category string (e.g. ``"depository"``, ``"credit"``,
    ``"brokerage"``). ``owned`` marks whether the account belongs to the user
    (it does by default); a non-owned account can still be read but its lines
    can never form an internal transfer.
    """

    account_id: str
    name: str
    account_type: str
    currency: str = "USD"
    owned: bool = True


class ProviderTransaction(StrixModel):
    """Normalized provider transaction payload (the read-only txn shape).

    ``amount`` is signed in the engine's convention: negative is an outflow,
    positive is an inflow. An adapter whose provider uses the opposite
    convention flips the sign before constructing this model, so every
    ``ProviderTransaction`` seen here is already normalized.
    """

    provider_txn_id: str
    account_id: str
    posted_date: date
    #: Signed amount; negative = outflow, positive = inflow.
    amount: DecimalValue
    description: str = ""


class FixtureBundle(StrixModel):
    """Preserved payloads for one ``access_ref``: accounts + per-account txns.

    ``accounts`` is the tuple returned by ``fetch_accounts``; ``transactions``
    maps each account id to the tuple returned by ``fetch_transactions`` for
    that account.
    """

    accounts: tuple[ProviderAccount, ...]
    transactions: Mapping[str, tuple[ProviderTransaction, ...]]


@runtime_checkable
class ProviderConnector(Protocol):
    """The read-only contract every provider adapter must satisfy.

    The surface is intentionally minimal and contains **no** write, trade,
    transfer, order, or payment method: a connector only *observes* accounts
    and transactions.
    """

    #: Stable short name of the backing provider (e.g. ``"plaid"``).
    provider_name: str

    def fetch_accounts(self, access_ref: str) -> tuple[ProviderAccount, ...]:
        """Return the accounts reachable through *access_ref* (read-only)."""
        ...

    def fetch_transactions(
        self, access_ref: str, account_id: str
    ) -> tuple[ProviderTransaction, ...]:
        """Return the transactions for one account (read-only)."""
        ...


class FixtureConnector:
    """Deterministic, fully offline :class:`ProviderConnector` implementation.

    It serves preserved :class:`FixtureBundle` payloads keyed by ``access_ref``
    and proves the adapter contract without any network, credential, or live
    call. Requesting an unknown ``access_ref`` or ``account_id`` raises
    :class:`ConnectorError`.
    """

    def __init__(
        self, provider_name: str, fixtures: Mapping[str, FixtureBundle]
    ) -> None:
        """Bind a provider name and its preserved per-``access_ref`` fixtures."""
        self.provider_name = provider_name
        self._fixtures: dict[str, FixtureBundle] = dict(fixtures)

    def _bundle(self, access_ref: str) -> FixtureBundle:
        """Return the fixture bundle for *access_ref* or raise."""
        try:
            return self._fixtures[access_ref]
        except KeyError as exc:
            raise ConnectorError(
                f"no fixtures for access_ref {access_ref!r}"
            ) from exc

    def fetch_accounts(self, access_ref: str) -> tuple[ProviderAccount, ...]:
        """Return the preserved accounts for *access_ref* deterministically."""
        return self._bundle(access_ref).accounts

    def fetch_transactions(
        self, access_ref: str, account_id: str
    ) -> tuple[ProviderTransaction, ...]:
        """Return the preserved transactions for one account deterministically.

        Raises :class:`ConnectorError` for an unknown *access_ref* or an
        *account_id* with no preserved transactions under that reference.
        """
        bundle = self._bundle(access_ref)
        try:
            return bundle.transactions[account_id]
        except KeyError as exc:
            raise ConnectorError(
                f"no fixtures for account_id {account_id!r} "
                f"under access_ref {access_ref!r}"
            ) from exc

    @staticmethod
    def to_normalized(
        transaction: ProviderTransaction, account_id: str
    ) -> NormalizedTransaction:
        """Map a provider transaction onto a canonical normalized line.

        The signed ``amount`` and ``posted_date`` pass through unchanged (the
        provider payload is already in the engine's sign convention). The
        normalized line is attached to *account_id* and carries a
        ``raw_digest`` — the canonical hash of the originating provider
        payload — so the normalized form stays bound to its exact source. The
        ``TXN-`` id is derived deterministically from the normalized content.
        """
        return make_transaction(
            posted_date=transaction.posted_date,
            amount=transaction.amount,
            account_id=account_id,
            description=transaction.description,
            raw_digest=canonical_hash(transaction),
        )
