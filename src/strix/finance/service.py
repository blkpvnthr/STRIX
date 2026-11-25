"""Finance application service — the logic layer behind the finance HTTP API (§3/§5).

Composes the existing finance modules (account store, canonical transactions, exact
Decimal arithmetic) into a single thread-safe service the HTTP layer can call. It
holds state in memory (manual/synthetic accounts and transactions) behind a narrow
interface, so a durable PostgreSQL-backed store can replace the internals later
without changing callers. Money is exact Decimal end to end; a second financial
computation engine is deliberately NOT introduced.
"""

from __future__ import annotations

import threading
from datetime import date
from decimal import Decimal

from strix.finance.accounts import AccountRecord, AccountStatus, AccountStore, make_account_record
from strix.finance.budgets import BudgetVariance, CategoryBudget, compute_variances
from strix.finance.categorize import DEFAULT_RULES, Category, categorize
from strix.finance.ledger import AccountType, FinanceError
from strix.finance.transactions import NormalizedTransaction, make_transaction
from strix.models import DecimalValue, StrixModel
from strix.native.arithmetic import checked_sum


def _period_of(day: date) -> str:
    """The ``YYYY-MM`` budget period a date falls in."""
    return f"{day.year:04d}-{day.month:02d}"


class AccountBalance(StrixModel):
    """An account and its computed balance (opening + posted transactions)."""

    account_id: str
    name: str
    account_type: AccountType
    balance: DecimalValue


class NetWorthSummary(StrixModel):
    """Assets minus liabilities, with the per-account breakdown."""

    assets_total: DecimalValue
    liabilities_total: DecimalValue
    net_worth: DecimalValue
    accounts: tuple[AccountBalance, ...]


class IncomeExpenseSummary(StrixModel):
    """Inflow/outflow totals over a date range (exact Decimal)."""

    start: date
    end: date
    inflow: DecimalValue
    outflow: DecimalValue
    net: DecimalValue
    transaction_count: int


class TransactionPage(StrixModel):
    """A page of transactions plus the unpaginated total."""

    items: tuple[NormalizedTransaction, ...]
    total: int
    limit: int
    offset: int


class FinanceService:
    """Thread-safe, in-memory finance application service."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._accounts = AccountStore()
        self._transactions: list[NormalizedTransaction] = []
        self._budgets: dict[tuple[str, str], CategoryBudget] = {}

    # -- accounts ----------------------------------------------------------

    def add_account(
        self,
        *,
        name: str,
        account_type: AccountType,
        owner: str,
        institution: str = "",
        mask: str = "",
        currency: str = "USD",
        status: AccountStatus = AccountStatus.MANUAL,
        opening_balance: Decimal = Decimal(0),
    ) -> AccountRecord:
        record = make_account_record(
            name=name, account_type=account_type, owner=owner, institution=institution,
            mask=mask, currency=currency, status=status, opening_balance=opening_balance,
        )
        with self._lock:
            self._accounts.register(record)
        return record

    def list_accounts(self, *, owner: str | None = None) -> tuple[AccountRecord, ...]:
        with self._lock:
            if owner is not None:
                return self._accounts.list_by_owner(owner)
            return self._accounts.all_records()

    def get_account(self, account_id: str) -> AccountRecord:
        with self._lock:
            return self._accounts.get(account_id)

    # -- transactions ------------------------------------------------------

    def add_transaction(
        self,
        *,
        account_id: str,
        posted_date: date,
        amount: Decimal,
        description: str = "",
        owned: bool = True,
    ) -> NormalizedTransaction:
        with self._lock:
            self._accounts.get(account_id)  # raises FinanceError if unknown
            txn = make_transaction(
                posted_date=posted_date, amount=amount, account_id=account_id,
                description=description, owned=owned,
            )
            self._transactions.append(txn)
            return txn

    def list_transactions(
        self,
        *,
        account_id: str | None = None,
        start: date | None = None,
        end: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> TransactionPage:
        if limit < 0 or offset < 0:
            raise FinanceError("limit and offset must be non-negative")
        with self._lock:
            matched = [
                t
                for t in self._transactions
                if (account_id is None or t.account_id == account_id)
                and (start is None or t.posted_date >= start)
                and (end is None or t.posted_date <= end)
            ]
        # Deterministic: newest first, ties broken by txn_id.
        matched.sort(key=lambda t: (t.posted_date, t.txn_id), reverse=True)
        window = tuple(matched[offset : offset + limit])
        return TransactionPage(items=window, total=len(matched), limit=limit, offset=offset)

    def _account_txns(self, account_id: str) -> list[NormalizedTransaction]:
        return [t for t in self._transactions if t.account_id == account_id]

    def account_balance(self, account_id: str) -> Decimal:
        with self._lock:
            record = self._accounts.get(account_id)
            amounts = [record.opening_balance, *(t.amount for t in self._account_txns(account_id))]
        return checked_sum(amounts)

    # -- summaries ---------------------------------------------------------

    def net_worth(self) -> NetWorthSummary:
        balances: list[AccountBalance] = []
        asset_bals: list[Decimal] = []
        liability_bals: list[Decimal] = []
        with self._lock:
            records = list(self._accounts.all_records())
            per_account = {
                rec.account_id: checked_sum(
                    [rec.opening_balance, *(t.amount for t in self._account_txns(rec.account_id))]
                )
                for rec in records
            }
        for rec in records:
            bal = per_account[rec.account_id]
            balances.append(
                AccountBalance(
                    account_id=rec.account_id, name=rec.name,
                    account_type=rec.account_type, balance=bal,
                )
            )
            if rec.account_type is AccountType.ASSET:
                asset_bals.append(bal)
            elif rec.account_type is AccountType.LIABILITY:
                liability_bals.append(bal)
        assets_total = checked_sum(asset_bals) if asset_bals else Decimal(0)
        liabilities_total = checked_sum(liability_bals) if liability_bals else Decimal(0)
        return NetWorthSummary(
            assets_total=assets_total,
            liabilities_total=liabilities_total,
            net_worth=assets_total - liabilities_total,
            accounts=tuple(balances),
        )

    # -- categorization ----------------------------------------------------

    def _transaction(self, txn_id: str) -> NormalizedTransaction:
        for txn in self._transactions:
            if txn.txn_id == txn_id:
                return txn
        raise FinanceError(f"unknown transaction {txn_id!r}")

    def categorize_transaction(self, txn_id: str) -> Category:
        """The deterministic spending category for a transaction (default rules)."""
        with self._lock:
            txn = self._transaction(txn_id)
        return categorize(txn, DEFAULT_RULES)

    # -- budgets -----------------------------------------------------------

    def set_budget(
        self, *, category: str, monthly_limit: Decimal, period: str
    ) -> CategoryBudget:
        """Set (or replace) a category's monthly budget for a ``YYYY-MM`` period."""
        budget = CategoryBudget(category=category, monthly_limit=monthly_limit, period=period)
        with self._lock:
            self._budgets[(period, category)] = budget
        return budget

    def list_budgets(self, *, period: str | None = None) -> tuple[CategoryBudget, ...]:
        with self._lock:
            items = list(self._budgets.values())
        if period is not None:
            items = [b for b in items if b.period == period]
        return tuple(sorted(items, key=lambda b: (b.period, b.category)))

    def budget_variance(self, *, period: str) -> tuple[BudgetVariance, ...]:
        """Score each category's budget for ``period`` against actual outflow spend."""
        with self._lock:
            budgets = [b for b in self._budgets.values() if b.period == period]
            txns = [t for t in self._transactions if _period_of(t.posted_date) == period]
        # Actual spend per category = exact sum of OUTFLOW magnitudes.
        by_category: dict[str, list[Decimal]] = {}
        for txn in txns:
            if txn.amount < 0:
                category = categorize(txn, DEFAULT_RULES).value
                by_category.setdefault(category, []).append(-txn.amount)
        actuals = {cat: checked_sum(amounts) for cat, amounts in by_category.items()}
        return compute_variances(budgets, actuals)

    def income_expense_summary(
        self, *, start: date, end: date, owner: str | None = None
    ) -> IncomeExpenseSummary:
        if start > end:
            raise FinanceError("start date must not be after end date")
        with self._lock:
            owned_ids: set[str] | None = None
            if owner is not None:
                owned_ids = {a.account_id for a in self._accounts.list_by_owner(owner)}
            txns = [
                t
                for t in self._transactions
                if start <= t.posted_date <= end
                and (owned_ids is None or t.account_id in owned_ids)
            ]
        inflows = [t.amount for t in txns if t.amount > 0]
        outflows = [-t.amount for t in txns if t.amount < 0]
        inflow = checked_sum(inflows) if inflows else Decimal(0)
        outflow = checked_sum(outflows) if outflows else Decimal(0)
        return IncomeExpenseSummary(
            start=start, end=end, inflow=inflow, outflow=outflow,
            net=inflow - outflow, transaction_count=len(txns),
        )
