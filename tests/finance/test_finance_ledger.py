"""Tests for the decimal-safe double-entry ledger foundation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.errors import StrixError
from strix.finance.ledger import (
    Account,
    AccountType,
    FinanceError,
    JournalEntry,
    Ledger,
    NormalBalance,
    Posting,
    make_account,
    make_journal_entry,
    normal_balance,
)

# --------------------------------------------------------------------------
# Fixtures: a tiny chart of accounts
# --------------------------------------------------------------------------


def _checking() -> Account:
    return make_account(name="Checking", account_type=AccountType.ASSET, owner="alice")


def _card() -> Account:
    return make_account(
        name="Visa", account_type=AccountType.LIABILITY, owner="alice"
    )


def _salary() -> Account:
    return make_account(name="Salary", account_type=AccountType.INCOME, owner="alice")


def _groceries() -> Account:
    return make_account(
        name="Groceries", account_type=AccountType.EXPENSE, owner="alice"
    )


def _funded_ledger() -> tuple[Ledger, Account, Account, Account, Account]:
    """A ledger with a $1000 salary deposit and a $200 grocery card purchase."""
    checking, card, salary, groceries = _checking(), _card(), _salary(), _groceries()
    ledger = Ledger()
    for acct in (checking, card, salary, groceries):
        ledger.add_account(acct)
    ledger.post(
        make_journal_entry(
            entry_date=date(2026, 1, 1),
            description="Paycheck",
            postings=(
                Posting(account_id=checking.account_id, debit=Decimal("1000")),
                Posting(account_id=salary.account_id, credit=Decimal("1000")),
            ),
        )
    )
    ledger.post(
        make_journal_entry(
            entry_date=date(2026, 1, 2),
            description="Groceries on card",
            postings=(
                Posting(account_id=groceries.account_id, debit=Decimal("200")),
                Posting(account_id=card.account_id, credit=Decimal("200")),
            ),
        )
    )
    return ledger, checking, card, salary, groceries


# --------------------------------------------------------------------------
# Normal balance helper
# --------------------------------------------------------------------------


def test_normal_balance_mapping() -> None:
    assert normal_balance(AccountType.ASSET) is NormalBalance.DEBIT
    assert normal_balance(AccountType.EXPENSE) is NormalBalance.DEBIT
    assert normal_balance(AccountType.LIABILITY) is NormalBalance.CREDIT
    assert normal_balance(AccountType.EQUITY) is NormalBalance.CREDIT
    assert normal_balance(AccountType.INCOME) is NormalBalance.CREDIT


# --------------------------------------------------------------------------
# Factories and content ids
# --------------------------------------------------------------------------


def test_make_account_content_id_and_reproducible() -> None:
    a = make_account(name="Checking", account_type=AccountType.ASSET, owner="alice")
    b = make_account(name="Checking", account_type=AccountType.ASSET, owner="alice")
    assert a.account_id.startswith("ACCT-")
    assert a == b  # same content -> same id
    assert a.currency == "USD"
    other = make_account(name="Checking", account_type=AccountType.ASSET, owner="bob")
    assert other.account_id != a.account_id


def test_make_journal_entry_content_id() -> None:
    checking, salary = _checking(), _salary()
    entry = make_journal_entry(
        entry_date=date(2026, 1, 1),
        description="Paycheck",
        postings=(
            Posting(account_id=checking.account_id, debit=Decimal("1000")),
            Posting(account_id=salary.account_id, credit=Decimal("1000")),
        ),
    )
    assert entry.entry_id.startswith("JE-")
    assert len(entry.postings) == 2


# --------------------------------------------------------------------------
# Posting validation
# --------------------------------------------------------------------------


def test_posting_rejects_both_sides_set() -> None:
    with pytest.raises(ValidationError):
        Posting(account_id="ACCT-x", debit=Decimal("5"), credit=Decimal("5"))


def test_posting_rejects_zero_zero() -> None:
    with pytest.raises(ValidationError):
        Posting(account_id="ACCT-x")


def test_posting_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        Posting(account_id="ACCT-x", debit=Decimal("-5"))


def test_posting_rejects_float_money() -> None:
    with pytest.raises(ValidationError):
        Posting(account_id="ACCT-x", debit=1000.0)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Journal-entry invariant
# --------------------------------------------------------------------------


def test_balanced_entry_posts() -> None:
    ledger, checking, _card, salary, _groceries = _funded_ledger()
    assert len(ledger.entries) == 2
    assert ledger.balance(checking.account_id) == Decimal("1000")
    assert ledger.balance(salary.account_id) == Decimal("1000")


def test_imbalanced_entry_raises_finance_error() -> None:
    checking, salary = _checking(), _salary()
    with pytest.raises(FinanceError):
        make_journal_entry(
            entry_date=date(2026, 1, 1),
            description="Bad",
            postings=(
                Posting(account_id=checking.account_id, debit=Decimal("1000")),
                Posting(account_id=salary.account_id, credit=Decimal("999")),
            ),
        )


def test_single_posting_entry_raises() -> None:
    checking = _checking()
    with pytest.raises(FinanceError):
        make_journal_entry(
            entry_date=date(2026, 1, 1),
            description="Lonely",
            postings=(Posting(account_id=checking.account_id, debit=Decimal("1")),),
        )


def test_finance_error_is_strix_error() -> None:
    assert issubclass(FinanceError, StrixError)


# --------------------------------------------------------------------------
# Ledger.post guards
# --------------------------------------------------------------------------


def test_post_unknown_account_raises() -> None:
    checking, salary = _checking(), _salary()
    ledger = Ledger()
    ledger.add_account(checking)  # salary account intentionally not added
    entry = make_journal_entry(
        entry_date=date(2026, 1, 1),
        description="Paycheck",
        postings=(
            Posting(account_id=checking.account_id, debit=Decimal("1000")),
            Posting(account_id=salary.account_id, credit=Decimal("1000")),
        ),
    )
    with pytest.raises(FinanceError):
        ledger.post(entry)
    assert ledger.entries == ()  # nothing partially posted


# --------------------------------------------------------------------------
# Balances: debit-normal and credit-normal
# --------------------------------------------------------------------------


def test_debit_and_credit_normal_balances() -> None:
    ledger, checking, card, salary, groceries = _funded_ledger()
    # Asset (debit-normal): debits - credits
    assert ledger.balance(checking.account_id) == Decimal("1000")
    # Expense (debit-normal)
    assert ledger.balance(groceries.account_id) == Decimal("200")
    # Liability (credit-normal): credits - debits
    assert ledger.balance(card.account_id) == Decimal("200")
    # Income (credit-normal)
    assert ledger.balance(salary.account_id) == Decimal("1000")


def test_balance_unknown_account_raises() -> None:
    ledger = Ledger()
    with pytest.raises(FinanceError):
        ledger.balance("ACCT-missing")


def test_balance_is_exact_decimal() -> None:
    checking = _checking()
    cash = make_account(name="Cash", account_type=AccountType.ASSET, owner="alice")
    ledger = Ledger()
    ledger.add_account(checking)
    ledger.add_account(cash)
    ledger.post(
        make_journal_entry(
            entry_date=date(2026, 1, 1),
            description="penny transfer",
            postings=(
                Posting(account_id=checking.account_id, debit=Decimal("0.10")),
                Posting(account_id=cash.account_id, credit=Decimal("0.10")),
            ),
        )
    )
    ledger.post(
        make_journal_entry(
            entry_date=date(2026, 1, 2),
            description="penny transfer",
            postings=(
                Posting(account_id=checking.account_id, debit=Decimal("0.20")),
                Posting(account_id=cash.account_id, credit=Decimal("0.20")),
            ),
        )
    )
    assert ledger.balance(checking.account_id) == Decimal("0.30")


# --------------------------------------------------------------------------
# Trial balance / net worth / income / expense
# --------------------------------------------------------------------------


def test_trial_balance_balances() -> None:
    ledger, *_ = _funded_ledger()
    tb = ledger.trial_balance()
    assert isinstance(tb, dict)
    ledger.assert_balanced()  # must not raise


def test_net_worth_is_assets_minus_liabilities() -> None:
    ledger, _checking, _card, _salary, _groceries = _funded_ledger()
    # assets: checking 1000 ; liabilities: card 200 -> net worth 800
    assert ledger.net_worth() == Decimal("800")


def test_income_and_expense_totals() -> None:
    ledger, *_ = _funded_ledger()
    assert ledger.income_total() == Decimal("1000")
    assert ledger.expense_total() == Decimal("200")


def test_income_total_date_range_excludes_out_of_range() -> None:
    ledger, *_ = _funded_ledger()
    # Both entries are in Jan 2026; a December window sees nothing.
    assert ledger.income_total(
        start=date(2025, 12, 1), end=date(2025, 12, 31)
    ) == Decimal("0")
    assert ledger.expense_total(
        start=date(2026, 1, 2), end=date(2026, 1, 2)
    ) == Decimal("200")


def test_account_and_journal_entry_are_frozen() -> None:
    acct = _checking()
    with pytest.raises(ValidationError):
        acct.name = "mutated"  # type: ignore[misc]
    entry = make_journal_entry(
        entry_date=date(2026, 1, 1),
        description="x",
        postings=(
            Posting(account_id=acct.account_id, debit=Decimal("1")),
            Posting(account_id=acct.account_id, credit=Decimal("1")),
        ),
    )
    assert isinstance(entry, JournalEntry)
