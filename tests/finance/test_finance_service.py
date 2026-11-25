"""Tests for the finance application service (§3/§5 — the HTTP API's logic layer)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from strix.finance.ledger import AccountType, FinanceError
from strix.finance.service import FinanceService


def _svc() -> FinanceService:
    svc = FinanceService()
    svc.add_account(
        name="Checking", account_type=AccountType.ASSET, owner="me",
        opening_balance=Decimal("1000"),
    )
    svc.add_account(
        name="Visa", account_type=AccountType.LIABILITY, owner="me",
        opening_balance=Decimal("200"),
    )
    return svc


def test_add_and_list_accounts() -> None:
    svc = _svc()
    accounts = svc.list_accounts(owner="me")
    assert {a.name for a in accounts} == {"Checking", "Visa"}


def test_get_unknown_account_raises() -> None:
    with pytest.raises(FinanceError):
        FinanceService().get_account("ACCT-nope")


def test_add_transaction_requires_known_account() -> None:
    with pytest.raises(FinanceError):
        FinanceService().add_transaction(
            account_id="ACCT-nope", posted_date=date(2026, 1, 1), amount=Decimal("-5")
        )


def test_account_balance_includes_opening_and_transactions() -> None:
    svc = _svc()
    checking = svc.list_accounts(owner="me")[0]
    assert checking.name == "Checking"
    svc.add_transaction(account_id=checking.account_id, posted_date=date(2026, 1, 2),
                        amount=Decimal("-150.50"))
    svc.add_transaction(account_id=checking.account_id, posted_date=date(2026, 1, 3),
                        amount=Decimal("25.25"))
    # 1000 - 150.50 + 25.25 = 874.75 (exact Decimal)
    assert svc.account_balance(checking.account_id) == Decimal("874.75")


def test_net_worth_is_assets_minus_liabilities() -> None:
    svc = _svc()
    nw = svc.net_worth()
    # assets 1000, liabilities 200 -> net 800
    assert nw.assets_total == Decimal("1000")
    assert nw.liabilities_total == Decimal("200")
    assert nw.net_worth == Decimal("800")
    assert len(nw.accounts) == 2


def test_transactions_pagination_and_filter() -> None:
    svc = _svc()
    acct = svc.list_accounts(owner="me")[0].account_id
    for day in range(1, 6):
        svc.add_transaction(account_id=acct, posted_date=date(2026, 1, day),
                            amount=Decimal(f"-{day}"))
    page = svc.list_transactions(account_id=acct, limit=2, offset=0)
    assert page.total == 5
    assert len(page.items) == 2
    # Newest first (date desc).
    assert page.items[0].posted_date == date(2026, 1, 5)
    page2 = svc.list_transactions(account_id=acct, limit=2, offset=2)
    assert page2.items[0].posted_date == date(2026, 1, 3)


def test_transactions_date_range_filter() -> None:
    svc = _svc()
    acct = svc.list_accounts(owner="me")[0].account_id
    for day in range(1, 6):
        svc.add_transaction(account_id=acct, posted_date=date(2026, 1, day), amount=Decimal("-1"))
    page = svc.list_transactions(start=date(2026, 1, 2), end=date(2026, 1, 4))
    assert {t.posted_date.day for t in page.items} == {2, 3, 4}


def test_income_expense_summary_is_exact() -> None:
    svc = _svc()
    acct = svc.list_accounts(owner="me")[0].account_id
    svc.add_transaction(account_id=acct, posted_date=date(2026, 1, 1), amount=Decimal("3000.00"))
    svc.add_transaction(account_id=acct, posted_date=date(2026, 1, 5), amount=Decimal("-1200.75"))
    svc.add_transaction(account_id=acct, posted_date=date(2026, 1, 9), amount=Decimal("-99.25"))
    s = svc.income_expense_summary(start=date(2026, 1, 1), end=date(2026, 1, 31))
    assert s.inflow == Decimal("3000.00")
    assert s.outflow == Decimal("1300.00")
    assert s.net == Decimal("1700.00")
    assert s.transaction_count == 3


def test_budgets_set_list_and_variance() -> None:
    svc = _svc()
    acct = svc.list_accounts(owner="me")[0].account_id
    svc.set_budget(category="groceries", monthly_limit=Decimal("500"), period="2026-01")
    budgets = svc.list_budgets(period="2026-01")
    assert len(budgets) == 1 and budgets[0].monthly_limit == Decimal("500")
    # A grocery outflow in the period counts toward actual spend.
    svc.add_transaction(account_id=acct, posted_date=date(2026, 1, 10),
                        amount=Decimal("-120.00"), description="WHOLE FOODS MARKET")
    variances = svc.budget_variance(period="2026-01")
    grocery = next(v for v in variances if v.category == "groceries")
    assert grocery.actual == Decimal("120.00")
    assert grocery.variance == Decimal("380.00")
    assert grocery.over_budget is False


def test_budget_variance_flags_overspend() -> None:
    svc = _svc()
    acct = svc.list_accounts(owner="me")[0].account_id
    svc.set_budget(category="groceries", monthly_limit=Decimal("100"), period="2026-02")
    svc.add_transaction(account_id=acct, posted_date=date(2026, 2, 3),
                        amount=Decimal("-150.00"), description="WHOLE FOODS")
    (v,) = svc.budget_variance(period="2026-02")
    assert v.over_budget is True
    assert v.variance == Decimal("-50.00")


def test_categorize_transaction_is_deterministic() -> None:
    svc = _svc()
    acct = svc.list_accounts(owner="me")[0].account_id
    txn = svc.add_transaction(account_id=acct, posted_date=date(2026, 1, 1),
                              amount=Decimal("-50.00"), description="WHOLE FOODS MARKET")
    assert svc.categorize_transaction(txn.txn_id).value == "groceries"


def test_add_transaction_rejects_float_amount() -> None:
    svc = _svc()
    acct = svc.list_accounts(owner="me")[0].account_id
    with pytest.raises(ValueError):  # DecimalValue bans float
        svc.add_transaction(account_id=acct, posted_date=date(2026, 1, 1), amount=1.5)  # type: ignore[arg-type]
