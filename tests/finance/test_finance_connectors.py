"""Tests for read-only provider connector contracts + fixture adapters.

These tests prove the adapter contract entirely offline: no network, no
credentials, no live HTTP. A :class:`FixtureConnector` serves preserved
provider payloads deterministically, and ``to_normalized`` maps one provider
transaction onto the engine's canonical :class:`NormalizedTransaction`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.errors import StrixError
from strix.finance.connectors import (
    ConnectorError,
    FixtureBundle,
    FixtureConnector,
    ProviderAccount,
    ProviderConnector,
    ProviderTransaction,
)
from strix.finance.transactions import NormalizedTransaction

# --------------------------------------------------------------------------
# Fixtures (synthetic — no real accounts, tokens, or PII)
# --------------------------------------------------------------------------

_ACCESS_REF = "ACCESS-fixture-001"
_CHECKING = "ACCT-checking-01"
_CREDIT = "ACCT-credit-02"

_ACCOUNTS = (
    ProviderAccount(
        account_id=_CHECKING,
        name="Everyday Checking",
        account_type="depository",
    ),
    ProviderAccount(
        account_id=_CREDIT,
        name="Rewards Card",
        account_type="credit",
    ),
)

_CHECKING_TXNS = (
    ProviderTransaction(
        provider_txn_id="PTX-1",
        account_id=_CHECKING,
        posted_date=date(2024, 1, 5),
        amount=Decimal("-42.50"),
        description="Coffee Shop",
    ),
    ProviderTransaction(
        provider_txn_id="PTX-2",
        account_id=_CHECKING,
        posted_date=date(2024, 1, 6),
        amount=Decimal("1500.00"),
        description="Paycheck",
    ),
)

_CREDIT_TXNS = (
    ProviderTransaction(
        provider_txn_id="PTX-3",
        account_id=_CREDIT,
        posted_date=date(2024, 1, 7),
        amount=Decimal("-9.99"),
        description="Streaming",
    ),
)

_BUNDLE = FixtureBundle(
    accounts=_ACCOUNTS,
    transactions={_CHECKING: _CHECKING_TXNS, _CREDIT: _CREDIT_TXNS},
)


def _connector() -> FixtureConnector:
    return FixtureConnector(
        provider_name="fixture", fixtures={_ACCESS_REF: _BUNDLE}
    )


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------


def test_fetch_accounts_returns_fixtures_deterministically() -> None:
    conn = _connector()
    first = conn.fetch_accounts(_ACCESS_REF)
    second = conn.fetch_accounts(_ACCESS_REF)
    assert first == _ACCOUNTS
    assert first == second
    assert isinstance(first, tuple)


def test_fetch_transactions_returns_fixtures_deterministically() -> None:
    conn = _connector()
    checking = conn.fetch_transactions(_ACCESS_REF, _CHECKING)
    assert checking == _CHECKING_TXNS
    assert conn.fetch_transactions(_ACCESS_REF, _CREDIT) == _CREDIT_TXNS
    # Repeated calls are identical.
    assert conn.fetch_transactions(_ACCESS_REF, _CHECKING) == checking
    assert isinstance(checking, tuple)


def test_provider_name_is_exposed() -> None:
    assert _connector().provider_name == "fixture"


def test_to_normalized_maps_amount_and_date() -> None:
    txn = _CHECKING_TXNS[0]
    normalized = FixtureConnector.to_normalized(txn, _CHECKING)
    assert isinstance(normalized, NormalizedTransaction)
    assert normalized.amount == Decimal("-42.50")
    assert normalized.posted_date == date(2024, 1, 5)
    assert normalized.description == "Coffee Shop"
    assert normalized.account_id == _CHECKING
    assert normalized.txn_id.startswith("TXN-")


def test_to_normalized_preserves_inflow_sign() -> None:
    normalized = FixtureConnector.to_normalized(_CHECKING_TXNS[1], _CHECKING)
    assert normalized.amount == Decimal("1500.00")
    assert normalized.amount > 0


def test_to_normalized_is_deterministic() -> None:
    txn = _CHECKING_TXNS[0]
    first = FixtureConnector.to_normalized(txn, _CHECKING)
    second = FixtureConnector.to_normalized(txn, _CHECKING)
    assert first == second
    assert first.txn_id == second.txn_id


def test_to_normalized_account_id_overrides_payload() -> None:
    # The passed account_id is the source of truth for the normalized line.
    normalized = FixtureConnector.to_normalized(_CHECKING_TXNS[0], _CREDIT)
    assert normalized.account_id == _CREDIT


# --------------------------------------------------------------------------
# Protocol conformance + read-only guarantee
# --------------------------------------------------------------------------


def test_fixture_connector_satisfies_protocol() -> None:
    assert isinstance(_connector(), ProviderConnector)


_FORBIDDEN_METHODS = frozenset(
    {
        "write",
        "trade",
        "transfer",
        "place_order",
        "submit_order",
        "create_order",
        "cancel_order",
        "post",
        "put",
        "patch",
        "delete",
        "move",
        "pay",
        "withdraw",
        "deposit",
        "send",
        "execute",
    }
)


def test_protocol_exposes_no_write_methods() -> None:
    names = {n for n in dir(ProviderConnector) if not n.startswith("_")}
    assert names.isdisjoint(_FORBIDDEN_METHODS)
    # Only the read-only fetch surface is present as callables.
    assert {"fetch_accounts", "fetch_transactions"} <= names
    # provider_name is a bare attribute annotation on the Protocol.
    assert "provider_name" in ProviderConnector.__annotations__


def test_fixture_connector_exposes_no_write_methods() -> None:
    names = {n for n in dir(FixtureConnector) if not n.startswith("_")}
    assert names.isdisjoint(_FORBIDDEN_METHODS)


# --------------------------------------------------------------------------
# Adversarial / edge
# --------------------------------------------------------------------------


def test_unknown_access_ref_raises_connector_error() -> None:
    conn = _connector()
    with pytest.raises(ConnectorError) as excinfo:
        conn.fetch_accounts("ACCESS-does-not-exist")
    assert "ACCESS-does-not-exist" in str(excinfo.value)


def test_unknown_access_ref_on_transactions_raises() -> None:
    conn = _connector()
    with pytest.raises(ConnectorError):
        conn.fetch_transactions("ACCESS-nope", _CHECKING)


def test_unknown_account_id_raises_connector_error() -> None:
    conn = _connector()
    with pytest.raises(ConnectorError) as excinfo:
        conn.fetch_transactions(_ACCESS_REF, "ACCT-ghost")
    assert "ACCT-ghost" in str(excinfo.value)


def test_connector_error_is_strix_error() -> None:
    assert issubclass(ConnectorError, StrixError)


def test_provider_transaction_rejects_float_amount() -> None:
    with pytest.raises(ValidationError):
        ProviderTransaction(
            provider_txn_id="PTX-x",
            account_id=_CHECKING,
            posted_date=date(2024, 1, 1),
            amount=1.5,
            description="float money",
        )


def test_provider_models_are_frozen() -> None:
    with pytest.raises(ValidationError):
        _ACCOUNTS[0].name = "mutated"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _CHECKING_TXNS[0].amount = Decimal("0")  # type: ignore[misc]


def test_fixture_bundle_is_frozen() -> None:
    with pytest.raises(ValidationError):
        _BUNDLE.accounts = ()  # type: ignore[misc]
