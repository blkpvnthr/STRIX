"""Tests for account management built on top of the ledger foundation."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.errors import StrixError
from strix.finance.accounts import (
    AccountRecord,
    AccountStatus,
    AccountStore,
    consolidated_by_type,
    make_account_record,
    map_subtype,
)
from strix.finance.ledger import AccountType, FinanceError

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _checking(owner: str = "alice") -> AccountRecord:
    return make_account_record(
        name="Checking",
        account_type=AccountType.ASSET,
        owner=owner,
        institution="Acme Bank",
        mask="1234",
    )


def _card(owner: str = "alice") -> AccountRecord:
    return make_account_record(
        name="Visa",
        account_type=AccountType.LIABILITY,
        owner=owner,
        institution="Acme Bank",
        mask="4321",
    )


def _brokerage(owner: str = "alice") -> AccountRecord:
    return make_account_record(
        name="Brokerage",
        account_type=AccountType.ASSET,
        owner=owner,
    )


# --------------------------------------------------------------------------
# AccountRecord / factory
# --------------------------------------------------------------------------


def test_make_account_record_defaults() -> None:
    record = _checking()
    assert record.account_id.startswith("ACCT-")
    assert record.name == "Checking"
    assert record.account_type is AccountType.ASSET
    assert record.owner == "alice"
    assert record.institution == "Acme Bank"
    assert record.mask == "1234"
    assert record.currency == "USD"
    assert record.status is AccountStatus.MANUAL
    assert record.connected_provider is None
    assert record.opening_balance == Decimal(0)


def test_make_account_record_is_deterministic() -> None:
    assert _checking().account_id == _checking().account_id


def test_make_account_record_distinct_content_distinct_id() -> None:
    assert _checking().account_id != _card().account_id


def test_account_record_is_frozen() -> None:
    record = _checking()
    with pytest.raises(ValidationError):
        record.name = "Renamed"  # type: ignore[misc]


def test_account_record_rejects_float_opening_balance() -> None:
    with pytest.raises(ValidationError):
        make_account_record(
            name="Checking",
            account_type=AccountType.ASSET,
            owner="alice",
            opening_balance=1.5,  # type: ignore[arg-type]
        )


def test_status_is_only_distinguisher_not_in_id() -> None:
    base = _checking()
    reconnected = base.model_copy(update={"status": AccountStatus.ACTIVE})
    assert reconnected.account_id == base.account_id


# --------------------------------------------------------------------------
# AccountStore: register / get
# --------------------------------------------------------------------------


def test_register_and_get() -> None:
    store = AccountStore()
    record = _checking()
    store.register(record)
    assert store.get(record.account_id) == record


def test_register_duplicate_rejected() -> None:
    store = AccountStore()
    record = _checking()
    store.register(record)
    with pytest.raises(FinanceError):
        store.register(_checking())


def test_get_unknown_raises() -> None:
    store = AccountStore()
    with pytest.raises(FinanceError):
        store.get("ACCT-doesnotexist")


def test_finance_error_is_strix_error() -> None:
    store = AccountStore()
    with pytest.raises(StrixError):
        store.get("ACCT-missing")


# --------------------------------------------------------------------------
# AccountStore: listing / ownership isolation
# --------------------------------------------------------------------------


def test_list_by_owner_isolation() -> None:
    store = AccountStore()
    alice_checking = _checking("alice")
    bob_card = _card("bob")
    store.register(alice_checking)
    store.register(bob_card)
    assert store.list_by_owner("alice") == (alice_checking,)
    assert store.list_by_owner("bob") == (bob_card,)


def test_list_by_owner_empty() -> None:
    store = AccountStore()
    store.register(_checking("alice"))
    assert store.list_by_owner("nobody") == ()


def test_list_by_owner_insertion_order() -> None:
    store = AccountStore()
    checking = _checking("alice")
    brokerage = _brokerage("alice")
    store.register(checking)
    store.register(brokerage)
    assert store.list_by_owner("alice") == (checking, brokerage)


def test_list_by_type() -> None:
    store = AccountStore()
    checking = _checking("alice")
    brokerage = _brokerage("alice")
    card = _card("alice")
    for rec in (checking, brokerage, card):
        store.register(rec)
    assert store.list_by_type(AccountType.ASSET) == (checking, brokerage)
    assert store.list_by_type(AccountType.LIABILITY) == (card,)
    assert store.list_by_type(AccountType.INCOME) == ()


# --------------------------------------------------------------------------
# AccountStore: status transitions
# --------------------------------------------------------------------------


def test_disconnect_sets_status() -> None:
    store = AccountStore()
    record = _checking()
    store.register(record)
    updated = store.disconnect(record.account_id)
    assert updated.status is AccountStatus.DISCONNECTED
    assert store.get(record.account_id).status is AccountStatus.DISCONNECTED
    assert updated.account_id == record.account_id


def test_close_sets_status() -> None:
    store = AccountStore()
    record = _checking()
    store.register(record)
    updated = store.close(record.account_id)
    assert updated.status is AccountStatus.CLOSED
    assert store.get(record.account_id).status is AccountStatus.CLOSED


def test_disconnect_unknown_raises() -> None:
    store = AccountStore()
    with pytest.raises(FinanceError):
        store.disconnect("ACCT-missing")


def test_close_unknown_raises() -> None:
    store = AccountStore()
    with pytest.raises(FinanceError):
        store.close("ACCT-missing")


def test_transition_preserves_other_fields() -> None:
    store = AccountStore()
    record = _checking()
    store.register(record)
    updated = store.disconnect(record.account_id)
    assert updated.name == record.name
    assert updated.institution == record.institution
    assert updated.mask == record.mask


# --------------------------------------------------------------------------
# consolidated_by_type
# --------------------------------------------------------------------------


def test_consolidated_by_type() -> None:
    checking = _checking("alice")
    brokerage = _brokerage("alice")
    card = _card("alice")
    result = consolidated_by_type((checking, brokerage, card))
    assert result[AccountType.ASSET] == (
        checking.account_id,
        brokerage.account_id,
    )
    assert result[AccountType.LIABILITY] == (card.account_id,)
    assert AccountType.INCOME not in result


def test_consolidated_by_type_empty() -> None:
    assert consolidated_by_type(()) == {}


# --------------------------------------------------------------------------
# map_subtype
# --------------------------------------------------------------------------


def test_map_subtype_assets() -> None:
    for name in ("checking", "savings", "brokerage"):
        assert map_subtype(name) is AccountType.ASSET


def test_map_subtype_liabilities() -> None:
    for name in ("credit_card", "loan"):
        assert map_subtype(name) is AccountType.LIABILITY


def test_map_subtype_retirement_and_trust() -> None:
    assert map_subtype("retirement") is AccountType.ASSET
    assert map_subtype("trust") is AccountType.ASSET


def test_map_subtype_case_insensitive() -> None:
    assert map_subtype("Checking") is AccountType.ASSET
    assert map_subtype("CREDIT_CARD") is AccountType.LIABILITY


def test_map_subtype_unknown_raises() -> None:
    with pytest.raises(FinanceError):
        map_subtype("cryptowallet")
