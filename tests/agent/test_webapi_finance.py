"""Tests for the finance API (§3).

The project test suite forbids network/event-loop sockets, so these exercise the
server-independent operation functions directly (the route wrappers are thin) plus
request-model validation and route registration. Covers typed schemas, exact-Decimal
money as strings (no float over the wire), pagination, and structured HTTP errors.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from strix.finance.service import FinanceService
from strix.webapi.app import create_app
from strix.webapi.finance_api import (
    AccountCreate,
    TransactionCreate,
    create_account_op,
    create_transaction_op,
    get_account_op,
    income_expense_op,
    list_transactions_op,
    net_worth_op,
)


def _svc_with_account(**over: object) -> tuple[FinanceService, str]:
    svc = FinanceService()
    body = AccountCreate(name="Checking", account_type="asset", owner="me",
                         opening_balance="1000.00", **over)  # type: ignore[arg-type]
    acct = create_account_op(svc, body)
    return svc, acct.account_id


def test_create_account_returns_string_money() -> None:
    svc, acct_id = _svc_with_account()
    assert acct_id.startswith("ACCT-")
    acct = get_account_op(svc, acct_id)
    assert acct.opening_balance == "1000.00"  # exact string money, no float
    assert acct.account_type == "asset"


def test_get_unknown_account_is_404() -> None:
    with pytest.raises(HTTPException) as exc:
        get_account_op(FinanceService(), "ACCT-nope")
    assert exc.value.status_code == 404


def test_invalid_account_type_is_400() -> None:
    with pytest.raises(HTTPException) as exc:
        create_account_op(FinanceService(),
                          AccountCreate(name="x", account_type="bogus", owner="me"))
    assert exc.value.status_code == 400


def test_invalid_opening_balance_is_400() -> None:
    with pytest.raises(HTTPException) as exc:
        create_account_op(FinanceService(),
                          AccountCreate(name="x", account_type="asset", owner="me",
                                        opening_balance="not-a-number"))
    assert exc.value.status_code == 400


def test_transaction_to_unknown_account_is_404() -> None:
    with pytest.raises(HTTPException) as exc:
        create_transaction_op(FinanceService(), TransactionCreate(
            account_id="ACCT-nope", posted_date=date(2026, 1, 1), amount="-5.00"))
    assert exc.value.status_code == 404


def test_float_amount_is_rejected_by_the_request_schema() -> None:
    # A JSON number (float) for a string money field must fail schema validation.
    with pytest.raises(ValidationError):
        TransactionCreate(account_id="A", posted_date=date(2026, 1, 1), amount=1.5)  # type: ignore[arg-type]


def test_transactions_pagination_newest_first() -> None:
    svc, acct_id = _svc_with_account()
    for day in range(1, 6):
        create_transaction_op(svc, TransactionCreate(
            account_id=acct_id, posted_date=date(2026, 1, day), amount=f"-{day}.00"))
    page = list_transactions_op(svc, account_id=acct_id, start=None, end=None, limit=2, offset=0)
    assert page.total == 5
    assert len(page.items) == 2
    assert page.items[0].posted_date == date(2026, 1, 5)


def test_net_worth_op() -> None:
    svc, _ = _svc_with_account()
    create_account_op(svc, AccountCreate(name="Visa", account_type="liability", owner="me",
                                         opening_balance="200.00"))
    nw = net_worth_op(svc)
    assert nw.assets_total == "1000.00"
    assert nw.liabilities_total == "200.00"
    assert nw.net_worth == "800.00"


def test_income_expense_op_is_exact() -> None:
    svc, acct_id = _svc_with_account()
    create_transaction_op(svc, TransactionCreate(
        account_id=acct_id, posted_date=date(2026, 1, 1), amount="3000.00"))
    create_transaction_op(svc, TransactionCreate(
        account_id=acct_id, posted_date=date(2026, 1, 5), amount="-1200.75"))
    s = income_expense_op(svc, start=date(2026, 1, 1), end=date(2026, 1, 31), owner=None)
    assert s.inflow == "3000.00"
    assert s.outflow == "1200.75"
    assert s.net == "1799.25"


# --- adversarial-review regressions ---------------------------------------


def test_absurd_opening_balance_rejected_at_write() -> None:
    # A finite-but-astronomical Decimal must be rejected at the write boundary,
    # so it can never poison net_worth with an uncaught decimal.Overflow (DoS).
    with pytest.raises(HTTPException) as exc:
        create_account_op(FinanceService(), AccountCreate(
            name="A", account_type="asset", owner="o", opening_balance="1E+2000000"))
    assert exc.value.status_code == 400


def test_absurd_transaction_amount_rejected_at_write() -> None:
    svc, acct_id = _svc_with_account()
    with pytest.raises(HTTPException) as exc:
        create_transaction_op(svc, TransactionCreate(
            account_id=acct_id, posted_date=date(2026, 1, 1), amount="-1E+2000000"))
    assert exc.value.status_code == 400
    # State is not poisoned: summaries still work.
    assert net_worth_op(svc).net_worth == "1000.00"


def test_large_but_sane_money_is_accepted() -> None:
    svc = FinanceService()
    acct = create_account_op(svc, AccountCreate(
        name="Endowment", account_type="asset", owner="o",
        opening_balance="1000000000000.00"))  # 1e12, fine
    assert acct.opening_balance == "1000000000000.00"


def test_list_transactions_op_negative_limit_is_400() -> None:
    with pytest.raises(HTTPException) as exc:
        list_transactions_op(FinanceService(), account_id=None, start=None, end=None,
                             limit=-1, offset=0)
    assert exc.value.status_code == 400


def test_finance_routes_registered(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(tmp_path, finance=FinanceService())
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/finance/accounts" in paths
    assert "/api/finance/accounts/{account_id}" in paths
    assert "/api/finance/transactions" in paths
    assert "/api/finance/net-worth" in paths
    assert "/api/finance/income-expense" in paths
