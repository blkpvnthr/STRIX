"""The monthly accounting workflow: journalizing, statements, close/reopen.

This module composes the deterministic finance core into the recurring
bookkeeping cycle a household (or back office) runs each period:

1. **Journalize.** :func:`journal_entries_from_transactions` turns normalized
   bank/brokerage lines into balanced double-entry :class:`JournalEntry`
   records. Internal transfers (reused from :mod:`strix.finance.transfers`) are
   posted account-to-account so a relocation of existing money is *never*
   recorded as new income or new expense.
2. **Report.** :func:`generate_monthly_statements` summarizes a period into an
   exact, traceable :class:`MonthlyStatements` — income, expense, transfer
   total, net cash flow, net worth, and a per-category breakdown.
3. **Reconcile.** :func:`reconcile_statement` compares a ledger balance against
   an external statement balance within an exact Decimal tolerance, emitting a
   :class:`ReconciliationExceptionReport`.
4. **Close / reopen.** :func:`close_period` seals a period; :func:`reopen_period`
   re-opens one only when the caller is explicitly authorized.

Design rules this module upholds (shared with :mod:`strix.finance.ledger`):

* Models are frozen and closed (:class:`strix.models.StrixModel`).
* Monetary amounts use :class:`strix.models.DecimalValue`; binary ``float`` is
  rejected at the model boundary and no amount is ever a ``float``.
* Reductions go through :mod:`strix.native.arithmetic` (``checked_sum`` /
  ``checked_sub``) so every reported figure is an exact Decimal.
* Failures raise :class:`strix.finance.ledger.FinanceError` (a ``StrixError``).

No network access and no live account aggregation happen here; those are a
separate, credential-gated concern.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import AwareDatetime, Field

from strix.finance.categorize import (
    DEFAULT_RULES,
    Category,
    CategoryRule,
    categorize_all,
)
from strix.finance.ledger import (
    Account,
    FinanceError,
    JournalEntry,
    Ledger,
    Posting,
    make_journal_entry,
)
from strix.finance.transactions import NormalizedTransaction
from strix.finance.transfers import (
    TransferMatch,
    classify_income_expense,
    match_transfers,
)
from strix.models import DecimalValue, StrixModel
from strix.native.arithmetic import checked_sub, checked_sum

__all__ = [
    "AccountingPeriod",
    "CategoryAccountResolver",
    "MonthlyStatements",
    "ReconciliationExceptionReport",
    "close_period",
    "generate_monthly_statements",
    "journal_entries_from_transactions",
    "reconcile_statement",
    "reopen_period",
]

#: A way to resolve the income/expense account id for a spending category:
#: either a callable or a plain mapping keyed by :class:`Category`.
CategoryAccountResolver = Callable[[Category], str] | Mapping[Category, str]


def _exact_sum(values: Sequence[Decimal]) -> Decimal:
    """Exact sum that returns ``Decimal(0)`` for an empty input."""
    return checked_sum(list(values)) if values else Decimal(0)


def _resolve_category_account(
    resolver: CategoryAccountResolver, category: Category
) -> str:
    """Resolve the ledger account id that backs *category*.

    Raises :class:`FinanceError` when the resolver has no account for the
    category (an unmapped key or a lookup failure in a callable).
    """
    try:
        if callable(resolver):
            return resolver(category)
        return resolver[category]
    except (KeyError, LookupError) as exc:
        raise FinanceError(
            f"no account mapped for category {category.value!r}"
        ) from exc


def _require_account(accounts: Mapping[str, Account], account_id: str) -> Account:
    """Return the :class:`Account` registered under *account_id* or raise."""
    account = accounts.get(account_id)
    if account is None:
        raise FinanceError(
            f"transaction references unknown account {account_id!r}"
        )
    return account


def journal_entries_from_transactions(
    txns: Sequence[NormalizedTransaction],
    *,
    accounts: Mapping[str, Account],
    category_account_id: CategoryAccountResolver,
    rules: Sequence[CategoryRule] = DEFAULT_RULES,
    max_day_gap: int = 3,
) -> tuple[JournalEntry, ...]:
    """Build balanced double-entry journal entries from *txns*.

    Matched internal transfers (paired by
    :func:`strix.finance.transfers.match_transfers`) are collapsed into a single
    account-to-account entry each — debiting the receiving account and crediting
    the sending account — so a transfer is **never** journalized as income or
    expense. Every remaining transaction becomes an income/expense entry: an
    inflow debits its account and credits the resolved category account; an
    outflow debits the category account and credits its account. Each category
    is obtained from :func:`strix.finance.categorize.categorize_all` under
    *rules* and mapped to an account id through *category_account_id*.

    Returned entries are deterministic: transfer entries first (in matched
    order), then income/expense entries in input order. A zero-amount
    transaction produces no entry (it has no non-zero posting side).

    Raises :class:`FinanceError` if a transaction references an account absent
    from *accounts*, or if a category has no mapped account.
    """
    matches = match_transfers(txns, max_day_gap=max_day_gap)
    txn_by_id = {txn.txn_id: txn for txn in txns}
    matched_ids: set[str] = set()
    for match in matches:
        matched_ids.add(match.outflow_txn_id)
        matched_ids.add(match.inflow_txn_id)

    entries: list[JournalEntry] = []

    # 1. Account-to-account transfer entries (never income/expense).
    for match in matches:
        outflow = txn_by_id[match.outflow_txn_id]
        inflow = txn_by_id[match.inflow_txn_id]
        source = _require_account(accounts, outflow.account_id)
        destination = _require_account(accounts, inflow.account_id)
        entries.append(
            make_journal_entry(
                entry_date=outflow.posted_date,
                description="internal transfer",
                postings=(
                    Posting(account_id=destination.account_id, debit=match.amount),
                    Posting(account_id=source.account_id, credit=match.amount),
                ),
            )
        )

    # 2. Income / expense entries for every non-transfer transaction.
    categories = dict(
        categorize_all(
            [txn for txn in txns if txn.txn_id not in matched_ids], rules
        )
    )
    for txn in txns:
        if txn.txn_id in matched_ids:
            continue
        if txn.amount == 0:
            continue
        account = _require_account(accounts, txn.account_id)
        category_account = _resolve_category_account(
            category_account_id, categories[txn.txn_id]
        )
        magnitude = abs(txn.amount)
        if txn.amount > 0:
            postings = (
                Posting(account_id=account.account_id, debit=magnitude),
                Posting(account_id=category_account, credit=magnitude),
            )
        else:
            postings = (
                Posting(account_id=category_account, debit=magnitude),
                Posting(account_id=account.account_id, credit=magnitude),
            )
        entries.append(
            make_journal_entry(
                entry_date=txn.posted_date,
                description=txn.description,
                postings=postings,
            )
        )

    return tuple(entries)


class MonthlyStatements(StrixModel):
    """An exact, traceable summary of one accounting period.

    Every figure is an exact :class:`~decimal.Decimal`: ``income_total`` and
    ``expense_total`` exclude matched transfer legs, ``net_cash_flow`` is their
    difference, ``transfer_total`` is the absolute value moved between owned
    accounts, ``net_worth`` is taken from the ledger, and ``by_category`` is the
    per-category spend/earn breakdown (transfer legs excluded), sorted by
    category name.
    """

    net_worth: DecimalValue
    income_total: DecimalValue
    expense_total: DecimalValue
    transfer_total: DecimalValue
    net_cash_flow: DecimalValue
    by_category: tuple[tuple[str, Decimal], ...]


def generate_monthly_statements(
    ledger: Ledger,
    txns: Sequence[NormalizedTransaction],
    matches: Sequence[TransferMatch],
    *,
    rules: Sequence[CategoryRule] = DEFAULT_RULES,
) -> MonthlyStatements:
    """Summarize a period into an exact :class:`MonthlyStatements`.

    Income, expense, and transfer totals come from
    :func:`strix.finance.transfers.classify_income_expense` (so matched transfer
    legs are excluded from income/expense); net cash flow is
    ``income_total - expense_total``; net worth is :meth:`Ledger.net_worth`; the
    category breakdown is the exact sum of absolute amounts per
    :class:`strix.finance.categorize.Category` over the non-transfer
    transactions. Every value is an exact Decimal traceable to its inputs.
    """
    income_total, expense_total, transfer_total = classify_income_expense(
        txns, matches
    )
    net_cash_flow = checked_sub(income_total, expense_total)

    matched_ids: set[str] = set()
    for match in matches:
        matched_ids.add(match.outflow_txn_id)
        matched_ids.add(match.inflow_txn_id)

    non_transfer = [txn for txn in txns if txn.txn_id not in matched_ids]
    categories = dict(categorize_all(non_transfer, rules))
    buckets: dict[str, list[Decimal]] = {}
    for txn in non_transfer:
        name = categories[txn.txn_id].value
        buckets.setdefault(name, []).append(abs(txn.amount))
    by_category = tuple(
        (name, _exact_sum(values)) for name, values in sorted(buckets.items())
    )

    return MonthlyStatements(
        net_worth=ledger.net_worth(),
        income_total=income_total,
        expense_total=expense_total,
        transfer_total=transfer_total,
        net_cash_flow=net_cash_flow,
        by_category=by_category,
    )


class ReconciliationExceptionReport(StrixModel):
    """Evidence that a ledger balance does (or does not) agree with an external
    statement balance within tolerance.

    ``difference`` is ``ledger_balance - statement_balance`` (exact);
    ``within_tolerance`` is ``True`` when ``abs(difference) <= tolerance`` and
    the ``classification`` is ``within_tolerance``, otherwise ``exception``.
    """

    ledger_balance: DecimalValue
    statement_balance: DecimalValue
    difference: DecimalValue
    tolerance: DecimalValue
    within_tolerance: bool
    #: within_tolerance | exception
    classification: str


def reconcile_statement(
    ledger_balance: Decimal,
    statement_balance: Decimal,
    *,
    tolerance: Decimal,
) -> ReconciliationExceptionReport:
    """Reconcile a ledger balance against an external *statement_balance*.

    The signed residual ``ledger_balance - statement_balance`` is computed
    exactly; the balances agree when its absolute value does not exceed
    ``tolerance``. Raises :class:`FinanceError` for a negative tolerance.
    """
    if tolerance < 0:
        raise FinanceError(f"tolerance must be non-negative, got {tolerance}")
    difference = checked_sub(ledger_balance, statement_balance)
    within = abs(difference) <= tolerance
    return ReconciliationExceptionReport(
        ledger_balance=ledger_balance,
        statement_balance=statement_balance,
        difference=difference,
        tolerance=tolerance,
        within_tolerance=within,
        classification="within_tolerance" if within else "exception",
    )


class AccountingPeriod(StrixModel):
    """A single monthly accounting period and its open/closed lifecycle state.

    ``period`` is a ``YYYY-MM`` label; ``status`` is ``open`` or ``closed``;
    ``closed_at`` is the timezone-aware instant the period was sealed (``None``
    while open).
    """

    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    status: str = Field(pattern=r"^(open|closed)$")
    closed_at: AwareDatetime | None = None


def close_period(period: AccountingPeriod) -> AccountingPeriod:
    """Seal *period*, stamping the close instant in UTC.

    Raises :class:`FinanceError` if the period is already closed.
    """
    if period.status == "closed":
        raise FinanceError(f"period {period.period} is already closed")
    return period.model_copy(
        update={"status": "closed", "closed_at": datetime.now(UTC)}
    )


def reopen_period(
    period: AccountingPeriod, *, authorized: bool
) -> AccountingPeriod:
    """Reopen a closed *period* — only when *authorized* is ``True``.

    Reopening a sealed period is a privileged correction; an unauthorized call
    raises :class:`FinanceError` and the period is left untouched. Reopening an
    already-open period is likewise rejected.
    """
    if not authorized:
        raise FinanceError(
            f"reopening period {period.period} requires authorization"
        )
    if period.status == "open":
        raise FinanceError(f"period {period.period} is already open")
    return period.model_copy(update={"status": "open", "closed_at": None})
