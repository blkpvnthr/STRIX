"""Tests for the monthly accounting workflow.

The correctness properties under test:

* Journal entries built from a mix of income, expense, and internal-transfer
  transactions are all balanced (debits equal credits), and matched transfer
  legs are posted account-to-account — never as income or expense.
* Monthly statements are exact Decimal and traceable (income, expense, net
  worth, net cash flow, transfer total, per-category breakdown).
* Statement reconciliation classifies within-tolerance vs exception exactly.
* A closed period cannot be reopened without authorization.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.errors import StrixError
from strix.finance.accounting import (
    AccountingPeriod,
    MonthlyStatements,
    ReconciliationExceptionReport,
    close_period,
    generate_monthly_statements,
    journal_entries_from_transactions,
    reconcile_statement,
    reopen_period,
)
from strix.finance.categorize import Category
from strix.finance.ledger import (
    Account,
    AccountType,
    FinanceError,
    Ledger,
    make_account,
)
from strix.finance.transactions import NormalizedTransaction, make_transaction
from strix.finance.transfers import match_transfers

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _accounts() -> dict[str, Account]:
    checking = make_account(
        name="Checking", account_type=AccountType.ASSET, owner="u"
    )
    savings = make_account(
        name="Savings", account_type=AccountType.ASSET, owner="u"
    )
    income = make_account(
        name="Salary", account_type=AccountType.INCOME, owner="u"
    )
    groceries = make_account(
        name="Groceries", account_type=AccountType.EXPENSE, owner="u"
    )
    return {
        "checking": checking,
        "savings": savings,
        "income": income,
        "groceries": groceries,
    }


def _mixed_txns(accts: dict[str, Account]) -> list[NormalizedTransaction]:
    checking = accts["checking"].account_id
    savings = accts["savings"].account_id
    return [
        make_transaction(
            posted_date=date(2026, 1, 1),
            amount=Decimal("5000.00"),
            account_id=checking,
            description="Payroll direct deposit",
        ),
        make_transaction(
            posted_date=date(2026, 1, 2),
            amount=Decimal("-200.00"),
            account_id=checking,
            description="Whole Foods",
        ),
        make_transaction(
            posted_date=date(2026, 1, 3),
            amount=Decimal("-1000.00"),
            account_id=checking,
            description="Outbound to savings",
        ),
        make_transaction(
            posted_date=date(2026, 1, 5),
            amount=Decimal("1000.00"),
            account_id=savings,
            description="Inbound from checking",
        ),
    ]


def _by_id(accts: dict[str, Account]) -> dict[str, Account]:
    return {account.account_id: account for account in accts.values()}


def _category_map(accts: dict[str, Account]) -> dict[Category, str]:
    return {
        Category.INCOME: accts["income"].account_id,
        Category.GROCERIES: accts["groceries"].account_id,
    }


def _build_ledger(accts: dict[str, Account]) -> Ledger:
    ledger = Ledger()
    for account in accts.values():
        ledger.add_account(account)
    return ledger


# --------------------------------------------------------------------------
# Journal entries
# --------------------------------------------------------------------------


def test_journal_entries_all_balanced_and_exclude_transfer_legs() -> None:
    accts = _accounts()
    txns = _mixed_txns(accts)
    category_account_id = _category_map(accts)

    entries = journal_entries_from_transactions(
        txns, accounts=_by_id(accts), category_account_id=category_account_id
    )

    # One transfer pair collapses to one entry; income + expense are one each.
    assert len(entries) == 3

    for entry in entries:
        debits = sum((p.debit for p in entry.postings), Decimal(0))
        credits = sum((p.credit for p in entry.postings), Decimal(0))
        assert debits == credits

    checking = accts["checking"].account_id
    savings = accts["savings"].account_id
    income = accts["income"].account_id
    groceries = accts["groceries"].account_id

    # Exactly one entry references only the two owned accounts: the transfer.
    transfer_entries = [
        e
        for e in entries
        if {p.account_id for p in e.postings} == {checking, savings}
    ]
    assert len(transfer_entries) == 1
    # The transfer never touches an income/expense category account.
    transfer_accounts = {p.account_id for p in transfer_entries[0].postings}
    assert income not in transfer_accounts
    assert groceries not in transfer_accounts


def test_journal_entries_posted_totals_exclude_transfers() -> None:
    accts = _accounts()
    txns = _mixed_txns(accts)
    ledger = _build_ledger(accts)

    entries = journal_entries_from_transactions(
        txns, accounts=_by_id(accts), category_account_id=_category_map(accts)
    )
    for entry in entries:
        ledger.post(entry)
    ledger.assert_balanced()

    assert ledger.income_total() == Decimal("5000.00")
    assert ledger.expense_total() == Decimal("200.00")
    # checking: +5000 (income) -1000 (transfer out) -200 (grocery) = 3800
    # savings: +1000 (transfer in)
    assert ledger.net_worth() == Decimal("4800.00")


def test_pure_transfer_does_not_change_income_or_expense() -> None:
    accts = _accounts()
    checking = accts["checking"].account_id
    savings = accts["savings"].account_id
    txns = [
        make_transaction(
            posted_date=date(2026, 1, 3),
            amount=Decimal("-1000.00"),
            account_id=checking,
            description="Outbound to savings",
        ),
        make_transaction(
            posted_date=date(2026, 1, 4),
            amount=Decimal("1000.00"),
            account_id=savings,
            description="Inbound from checking",
        ),
    ]
    ledger = _build_ledger(accts)
    entries = journal_entries_from_transactions(
        txns, accounts=_by_id(accts), category_account_id=_category_map(accts)
    )
    assert len(entries) == 1
    for entry in entries:
        ledger.post(entry)

    assert ledger.income_total() == Decimal("0")
    assert ledger.expense_total() == Decimal("0")

    matches = match_transfers(txns)
    statements = generate_monthly_statements(ledger, txns, matches)
    assert statements.income_total == Decimal("0")
    assert statements.expense_total == Decimal("0")
    assert statements.transfer_total == Decimal("1000.00")


def test_journal_entries_unknown_account_raises() -> None:
    accts = _accounts()
    txns = [
        make_transaction(
            posted_date=date(2026, 1, 2),
            amount=Decimal("-50.00"),
            account_id="not-a-real-account",
            description="Whole Foods",
        ),
    ]
    with pytest.raises(FinanceError):
        journal_entries_from_transactions(
            txns, accounts=_by_id(accts), category_account_id=_category_map(accts)
        )


def test_journal_entries_category_resolver_as_callable() -> None:
    accts = _accounts()
    txns = _mixed_txns(accts)
    mapping = _category_map(accts)

    def resolver(category: Category) -> str:
        return mapping[category]

    entries = journal_entries_from_transactions(
        txns, accounts=_by_id(accts), category_account_id=resolver
    )
    assert len(entries) == 3


# --------------------------------------------------------------------------
# Monthly statements
# --------------------------------------------------------------------------


def test_monthly_statements_are_exact_and_traceable() -> None:
    accts = _accounts()
    txns = _mixed_txns(accts)
    ledger = _build_ledger(accts)
    entries = journal_entries_from_transactions(
        txns, accounts=_by_id(accts), category_account_id=_category_map(accts)
    )
    for entry in entries:
        ledger.post(entry)

    matches = match_transfers(txns)
    statements = generate_monthly_statements(ledger, txns, matches)

    assert isinstance(statements, MonthlyStatements)
    assert statements.income_total == Decimal("5000.00")
    assert statements.expense_total == Decimal("200.00")
    assert statements.transfer_total == Decimal("1000.00")
    assert statements.net_cash_flow == Decimal("4800.00")
    assert statements.net_worth == Decimal("4800.00")

    by_category = dict(statements.by_category)
    assert by_category[Category.INCOME.value] == Decimal("5000.00")
    assert by_category[Category.GROCERIES.value] == Decimal("200.00")
    # Transfer legs are excluded from the category breakdown.
    assert Category.TRANSFERS.value not in by_category


# --------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------


def test_reconcile_within_tolerance() -> None:
    report = reconcile_statement(
        Decimal("4800.00"),
        Decimal("4800.02"),
        tolerance=Decimal("0.05"),
    )
    assert isinstance(report, ReconciliationExceptionReport)
    assert report.within_tolerance is True
    assert report.classification == "within_tolerance"
    assert report.difference == Decimal("-0.02")


def test_reconcile_exception_outside_tolerance() -> None:
    report = reconcile_statement(
        Decimal("4800.00"),
        Decimal("4700.00"),
        tolerance=Decimal("0.05"),
    )
    assert report.within_tolerance is False
    assert report.classification == "exception"
    assert report.difference == Decimal("100.00")


def test_reconcile_negative_tolerance_raises() -> None:
    with pytest.raises(FinanceError):
        reconcile_statement(
            Decimal("1"), Decimal("1"), tolerance=Decimal("-0.01")
        )


# --------------------------------------------------------------------------
# Period close / reopen
# --------------------------------------------------------------------------


def test_close_then_reopen_requires_authorization() -> None:
    period = AccountingPeriod(period="2026-01", status="open")
    closed = close_period(period)
    assert closed.status == "closed"
    assert closed.closed_at is not None

    with pytest.raises(FinanceError):
        reopen_period(closed, authorized=False)

    reopened = reopen_period(closed, authorized=True)
    assert reopened.status == "open"
    assert reopened.closed_at is None


def test_closing_an_already_closed_period_raises() -> None:
    period = AccountingPeriod(period="2026-01", status="open")
    closed = close_period(period)
    with pytest.raises(FinanceError):
        close_period(closed)


def test_accounting_period_is_frozen_and_closed() -> None:
    period = AccountingPeriod(period="2026-01", status="open")
    with pytest.raises(ValidationError):
        period.status = "closed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        AccountingPeriod(period="2026-01", status="open", extra="no")  # type: ignore[call-arg]


def test_accounting_period_rejects_malformed_period() -> None:
    with pytest.raises(ValidationError):
        AccountingPeriod(period="2026/01", status="open")


def test_finance_error_is_strix_error() -> None:
    assert issubclass(FinanceError, StrixError)
