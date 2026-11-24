"""Decimal-safe double-entry ledger foundation.

This is the deterministic accounting core of the offline personal-finance
engine. Every posting is an exact :class:`~decimal.Decimal` amount, every
journal entry must balance (total debits equal total credits), and every
balance is a signed exact sum taken with respect to the account's *normal
balance* side.

Design rules this module upholds:

* Models are frozen and closed (``strix.models.StrixModel``).
* Monetary amounts use ``strix.models.DecimalValue`` — binary ``float`` is
  rejected at the model boundary; no amount is ever a ``float``.
* Arithmetic goes through ``strix.native.arithmetic`` (``checked_sum`` /
  ``checked_sub``) so sums stay exact regardless of magnitude or count.
* Content-derived identifiers come from ``strix.canonical.make_id``; an id
  never participates in its own payload.
* Failures raise :class:`FinanceError` (a ``strix.errors.StrixError``).

No network access and no live account aggregation happen here; those are a
separate, credential-gated concern.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import ValidationError, model_validator

from strix.canonical import make_id
from strix.errors import StrixError
from strix.models import DecimalValue, StrixModel
from strix.native.arithmetic import checked_sub, checked_sum

__all__ = [
    "Account",
    "AccountType",
    "FinanceError",
    "JournalEntry",
    "Ledger",
    "NormalBalance",
    "Posting",
    "make_account",
    "make_journal_entry",
    "normal_balance",
]


class FinanceError(StrixError):
    """A ledger operation received invalid input or violated an invariant
    (an imbalanced entry, a posting to an unknown account, or a lookup of an
    account the ledger does not hold)."""


class AccountType(StrEnum):
    """The five fundamental account classes.

    Everyday account kinds map onto these: checking, savings, and brokerage
    accounts are :attr:`ASSET`; credit cards and loans are :attr:`LIABILITY`.
    """

    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"
    EXPENSE = "expense"


class NormalBalance(StrEnum):
    """The side on which an account type carries a positive balance."""

    DEBIT = "debit"
    CREDIT = "credit"


#: Account types whose positive balance lives on the debit side.
_DEBIT_NORMAL: frozenset[AccountType] = frozenset(
    {AccountType.ASSET, AccountType.EXPENSE}
)


def normal_balance(account_type: AccountType) -> NormalBalance:
    """Return the normal-balance side for *account_type*.

    Assets and expenses are debit-normal; liabilities, equity, and income are
    credit-normal.
    """
    return (
        NormalBalance.DEBIT
        if account_type in _DEBIT_NORMAL
        else NormalBalance.CREDIT
    )


class Account(StrixModel):
    """A single account in a chart of accounts, identified by content hash."""

    account_id: str
    name: str
    account_type: AccountType
    currency: str = "USD"
    owner: str


def make_account(
    *,
    name: str,
    account_type: AccountType,
    owner: str,
    currency: str = "USD",
) -> Account:
    """Build an :class:`Account` with a content-derived ``ACCT-`` identifier.

    The identifier is a stable hash of the account's defining fields (name,
    type, currency, owner) — never of the id itself — so identical content
    always yields the same account.
    """
    payload: Mapping[str, object] = {
        "name": name,
        "account_type": account_type,
        "currency": currency,
        "owner": owner,
    }
    return Account(
        account_id=make_id("ACCT", payload),
        name=name,
        account_type=account_type,
        currency=currency,
        owner=owner,
    )


class Posting(StrixModel):
    """One leg of a journal entry: an exact debit or credit to one account.

    Exactly one of ``debit`` / ``credit`` is non-zero and both are
    non-negative; a posting that sets both, sets neither, or carries a
    negative amount is rejected at construction.
    """

    account_id: str
    debit: DecimalValue = Decimal(0)
    credit: DecimalValue = Decimal(0)

    @model_validator(mode="after")
    def _exactly_one_non_negative_side(self) -> Posting:
        if self.debit < 0 or self.credit < 0:
            raise ValueError("posting amounts must be non-negative")
        if (self.debit != 0) == (self.credit != 0):
            raise ValueError(
                "exactly one of debit/credit must be non-zero"
            )
        return self


class JournalEntry(StrixModel):
    """A balanced set of postings recorded on a single date.

    Invariant (enforced here): there are at least two postings and the exact
    sum of all debits equals the exact sum of all credits. Account existence
    is not checked here — the entry only references accounts by id; the ledger
    resolves and validates those ids when the entry is posted.
    """

    entry_id: str
    date: date
    description: str
    postings: tuple[Posting, ...]

    @model_validator(mode="after")
    def _balanced(self) -> JournalEntry:
        if len(self.postings) < 2:
            raise ValueError("a journal entry requires at least two postings")
        debits = checked_sum([posting.debit for posting in self.postings])
        credits = checked_sum([posting.credit for posting in self.postings])
        if debits != credits:
            raise ValueError(
                f"journal entry is not balanced: debits {debits} != credits {credits}"
            )
        return self


def make_journal_entry(
    *,
    entry_date: date,
    description: str,
    postings: Iterable[Posting],
) -> JournalEntry:
    """Build a balanced :class:`JournalEntry` with a ``JE-`` content id.

    Raises :class:`FinanceError` if the entry is imbalanced or has fewer than
    two postings (the underlying model invariant surfaced as a typed finance
    error for callers).
    """
    ordered = tuple(postings)
    payload: Mapping[str, object] = {
        "date": entry_date,
        "description": description,
        "postings": list(ordered),
    }
    try:
        return JournalEntry(
            entry_id=make_id("JE", payload),
            date=entry_date,
            description=description,
            postings=ordered,
        )
    except ValidationError as exc:
        raise FinanceError(f"invalid journal entry: {exc}") from exc


def _exact_sum(values: Iterable[Decimal]) -> Decimal:
    """Exact sum that returns ``Decimal(0)`` for an empty input."""
    items = list(values)
    return checked_sum(items) if items else Decimal(0)


class Ledger:
    """An in-memory container of accounts and the journal entries posted
    against them.

    The ledger owns all cross-entry invariants: it rejects entries that
    reference unknown accounts or fail to balance, and it computes balances,
    trial balances, net worth, and income/expense totals as exact signed
    Decimal sums with respect to each account's normal-balance side.
    """

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}
        self._entries: list[JournalEntry] = []

    # -- registration ------------------------------------------------------

    def add_account(self, account: Account) -> None:
        """Register *account*; re-adding the same content id is idempotent."""
        self._accounts[account.account_id] = account

    @property
    def accounts(self) -> tuple[Account, ...]:
        """All registered accounts, in insertion order."""
        return tuple(self._accounts.values())

    @property
    def entries(self) -> tuple[JournalEntry, ...]:
        """All posted journal entries, in posting order."""
        return tuple(self._entries)

    # -- posting -----------------------------------------------------------

    def post(self, entry: JournalEntry) -> None:
        """Validate and append *entry*.

        Raises :class:`FinanceError` if any posting references an account the
        ledger does not hold, or if the entry's debits and credits do not
        balance. The ledger is left unchanged when validation fails.
        """
        for posting in entry.postings:
            if posting.account_id not in self._accounts:
                raise FinanceError(
                    f"posting references unknown account {posting.account_id!r}"
                )
        debits = checked_sum([posting.debit for posting in entry.postings])
        credits = checked_sum([posting.credit for posting in entry.postings])
        if debits != credits:
            raise FinanceError(
                f"journal entry is not balanced: debits {debits} != credits {credits}"
            )
        self._entries.append(entry)

    # -- queries -----------------------------------------------------------

    def _require_account(self, account_id: str) -> Account:
        account = self._accounts.get(account_id)
        if account is None:
            raise FinanceError(f"unknown account {account_id!r}")
        return account

    def _sided_sums(
        self,
        account_id: str,
        *,
        start: date | None,
        end: date | None,
    ) -> tuple[Decimal, Decimal]:
        """Exact (debits, credits) for *account_id* over an optional date
        window (inclusive on both ends)."""
        debit_values: list[Decimal] = []
        credit_values: list[Decimal] = []
        for entry in self._entries:
            if start is not None and entry.date < start:
                continue
            if end is not None and entry.date > end:
                continue
            for posting in entry.postings:
                if posting.account_id != account_id:
                    continue
                debit_values.append(posting.debit)
                credit_values.append(posting.credit)
        return _exact_sum(debit_values), _exact_sum(credit_values)

    def balance(
        self,
        account_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> Decimal:
        """Exact signed balance of *account_id* on its normal-balance side.

        Debit-normal accounts return ``debits - credits``; credit-normal
        accounts return ``credits - debits``. An optional inclusive date
        window restricts which posted entries are counted. Raises
        :class:`FinanceError` for an unknown account.
        """
        account = self._require_account(account_id)
        debits, credits = self._sided_sums(account_id, start=start, end=end)
        if normal_balance(account.account_type) is NormalBalance.DEBIT:
            return checked_sub(debits, credits)
        return checked_sub(credits, debits)

    def trial_balance(self) -> dict[str, Decimal]:
        """Map every registered account id to its normal-side signed balance.

        For a correctly posted ledger the debit-normal balances and the
        credit-normal balances sum to the same total (see
        :meth:`assert_balanced`).
        """
        return {
            account_id: self.balance(account_id)
            for account_id in self._accounts
        }

    def assert_balanced(self) -> None:
        """Assert the whole ledger balances: total debits equal total credits
        across every posted entry. Raises :class:`FinanceError` otherwise."""
        all_debits = _exact_sum(
            posting.debit
            for entry in self._entries
            for posting in entry.postings
        )
        all_credits = _exact_sum(
            posting.credit
            for entry in self._entries
            for posting in entry.postings
        )
        if all_debits != all_credits:
            raise FinanceError(
                f"ledger is not balanced: total debits {all_debits} "
                f"!= total credits {all_credits}"
            )

    def _total_for_types(
        self,
        account_types: frozenset[AccountType],
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> Decimal:
        balances = [
            self.balance(account.account_id, start=start, end=end)
            for account in self._accounts.values()
            if account.account_type in account_types
        ]
        return _exact_sum(balances)

    def net_worth(self) -> Decimal:
        """Exact net worth: total asset balances minus total liability
        balances (each taken on its normal side)."""
        assets = self._total_for_types(frozenset({AccountType.ASSET}))
        liabilities = self._total_for_types(frozenset({AccountType.LIABILITY}))
        return checked_sub(assets, liabilities)

    def income_total(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> Decimal:
        """Total income (credit-normal) over an optional inclusive date
        window."""
        return self._total_for_types(
            frozenset({AccountType.INCOME}), start=start, end=end
        )

    def expense_total(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> Decimal:
        """Total expense (debit-normal) over an optional inclusive date
        window."""
        return self._total_for_types(
            frozenset({AccountType.EXPENSE}), start=start, end=end
        )
