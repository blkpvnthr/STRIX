"""Deterministic rule-based categorization and merchant normalization.

This module assigns a coarse spending :class:`Category` to each normalized
transaction and cleans card-processor noise out of merchant descriptions. It is
pure and deterministic: identical inputs always yield identical outputs, no
machine learning is involved, and nothing here touches the network or any live
account aggregation.

Design rules this module upholds (shared with :mod:`strix.finance.ledger` and
:mod:`strix.finance.anomaly`):

* Models are frozen and closed (:class:`strix.models.StrixModel`).
* Categorization is a total function of ``(description, amount)`` against an
  ordered rule set — a rule matches by a case-insensitive substring of the
  description, the highest-priority match wins (ties broken by rule order), and
  an unmatched transaction falls through to :attr:`Category.INCOME` when its
  amount is a positive inflow and :attr:`Category.OTHER` otherwise.
* Merchant normalization strips a leading ``POS`` marker, store numbers, dates,
  and trailing US state codes, then collapses whitespace and title-cases the
  result.

The categorization is descriptive bookkeeping only; it never asserts anything
about the legitimacy of a transaction.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum

from pydantic import Field

from strix.finance.transactions import NormalizedTransaction, make_transaction
from strix.models import StrixModel

__all__ = [
    "DEFAULT_RULES",
    "Category",
    "CategoryRule",
    "NormalizedTransaction",
    "categorize",
    "categorize_all",
    "make_transaction",
    "normalize_merchant",
]


class Category(StrEnum):
    """A coarse spending bucket assigned to a transaction.

    The vocabulary is intentionally small and stable; :attr:`INCOME` and
    :attr:`OTHER` are the two fall-through buckets used when no rule matches.
    """

    INCOME = "income"
    GROCERIES = "groceries"
    DINING = "dining"
    TRANSPORT = "transport"
    UTILITIES = "utilities"
    HOUSING = "housing"
    HEALTHCARE = "healthcare"
    ENTERTAINMENT = "entertainment"
    SHOPPING = "shopping"
    SUBSCRIPTIONS = "subscriptions"
    TRANSFERS = "transfers"
    FEES = "fees"
    TAXES = "taxes"
    OTHER = "other"


class CategoryRule(StrixModel):
    """One categorization rule: a substring pattern mapped to a category.

    ``pattern`` is matched case-insensitively as a substring against a
    transaction's description. ``priority`` orders competing matches — a higher
    priority wins, and equal priorities are broken by the rule's position in the
    rule set (earlier wins). An empty ``pattern`` is rejected because it would
    match every description.
    """

    pattern: str = Field(min_length=1)
    category: Category
    priority: int = 0


# --------------------------------------------------------------------------
# Merchant normalization
# --------------------------------------------------------------------------

# Trailing two-letter US state/territory codes stripped from merchant strings.
_US_STATE_CODES = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC", "PR", "VI", "GU", "AS", "MP",
    }
)

#: Leading point-of-sale marker, e.g. ``"POS "`` or ``"POS DEBIT "``.
_POS_PREFIX = re.compile(r"^\s*POS(?:\s+DEBIT|\s+PURCHASE)?\s+", re.IGNORECASE)
#: A ``#``-prefixed store/terminal number, e.g. ``"#1234"``.
_STORE_HASH = re.compile(r"#\s*\w+")
#: Dates in ``MM/DD`` / ``MM/DD/YY(YY)`` or ISO ``YYYY-MM-DD`` form.
_DATE = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b\d{4}-\d{2}-\d{2}\b")
#: A bare run of three or more digits (store number without a ``#``).
_BARE_NUMBER = re.compile(r"\b\d{3,}\b")


def normalize_merchant(description: str) -> str:
    """Return a cleaned, title-cased merchant name from a raw description.

    Card-processor noise is removed deterministically: a leading ``POS`` marker,
    ``#``-prefixed store numbers, embedded dates, bare long digit runs, and
    trailing US state codes. The remaining tokens are whitespace-collapsed and
    title-cased. An input that is entirely noise normalizes to the empty string.
    """
    text = _POS_PREFIX.sub(" ", description)
    text = _STORE_HASH.sub(" ", text)
    text = _DATE.sub(" ", text)
    text = _BARE_NUMBER.sub(" ", text)

    tokens = text.split()
    # Drop one or more trailing uppercase state codes (e.g. "SEATTLE WA").
    while tokens and tokens[-1].isupper() and tokens[-1] in _US_STATE_CODES:
        tokens.pop()

    return " ".join(tokens).title()


# --------------------------------------------------------------------------
# Categorization
# --------------------------------------------------------------------------


def categorize(
    txn: NormalizedTransaction,
    rules: Sequence[CategoryRule],
) -> Category:
    """Return the :class:`Category` for *txn* under *rules*.

    Every rule whose ``pattern`` appears (case-insensitively) in the
    transaction's description is a candidate; the candidate with the highest
    ``priority`` wins, ties broken by the rule's position in *rules*. A matching
    rule always decides the category, regardless of amount sign. With no match,
    a positive (inflow) amount is :attr:`Category.INCOME` and any other amount is
    :attr:`Category.OTHER`.
    """
    description = txn.description.lower()
    best: tuple[int, int] | None = None
    best_category: Category | None = None
    for index, rule in enumerate(rules):
        if rule.pattern.lower() not in description:
            continue
        # Higher priority wins; earlier index breaks ties.
        key = (-rule.priority, index)
        if best is None or key < best:
            best = key
            best_category = rule.category

    if best_category is not None:
        return best_category
    if txn.amount > 0:
        return Category.INCOME
    return Category.OTHER


def categorize_all(
    txns: Sequence[NormalizedTransaction],
    rules: Sequence[CategoryRule],
) -> tuple[tuple[str, Category], ...]:
    """Categorize every transaction, preserving input order.

    Returns a tuple of ``(txn_id, category)`` pairs — one per input transaction,
    in the same order — so the result is fully reproducible.
    """
    return tuple((txn.txn_id, categorize(txn, rules)) for txn in txns)


# --------------------------------------------------------------------------
# Built-in ruleset
# --------------------------------------------------------------------------

#: A small, conservative default ruleset. Patterns are chosen to avoid common
#: substring collisions (e.g. "rent payment" rather than "rent", which is a
#: substring of "current"). Income markers carry a higher priority so a payroll
#: or deposit line is never shadowed by an incidental merchant match.
DEFAULT_RULES: tuple[CategoryRule, ...] = (
    CategoryRule(pattern="payroll", category=Category.INCOME, priority=10),
    CategoryRule(pattern="direct deposit", category=Category.INCOME, priority=10),
    CategoryRule(pattern="whole foods", category=Category.GROCERIES),
    CategoryRule(pattern="grocery", category=Category.GROCERIES),
    CategoryRule(pattern="safeway", category=Category.GROCERIES),
    CategoryRule(pattern="trader joe", category=Category.GROCERIES),
    CategoryRule(pattern="restaurant", category=Category.DINING),
    CategoryRule(pattern="starbucks", category=Category.DINING),
    CategoryRule(pattern="chipotle", category=Category.DINING),
    CategoryRule(pattern="uber", category=Category.TRANSPORT),
    CategoryRule(pattern="lyft", category=Category.TRANSPORT),
    CategoryRule(pattern="chevron", category=Category.TRANSPORT),
    CategoryRule(pattern="shell oil", category=Category.TRANSPORT),
    CategoryRule(pattern="electric", category=Category.UTILITIES),
    CategoryRule(pattern="comcast", category=Category.UTILITIES),
    CategoryRule(pattern="internet", category=Category.UTILITIES),
    CategoryRule(pattern="rent payment", category=Category.HOUSING),
    CategoryRule(pattern="mortgage", category=Category.HOUSING),
    CategoryRule(pattern="pharmacy", category=Category.HEALTHCARE),
    CategoryRule(pattern="cvs", category=Category.HEALTHCARE),
    CategoryRule(pattern="netflix", category=Category.SUBSCRIPTIONS),
    CategoryRule(pattern="spotify", category=Category.SUBSCRIPTIONS),
    CategoryRule(pattern="cinema", category=Category.ENTERTAINMENT),
    CategoryRule(pattern="amazon", category=Category.SHOPPING),
    CategoryRule(pattern="target", category=Category.SHOPPING),
    CategoryRule(pattern="transfer", category=Category.TRANSFERS),
    CategoryRule(pattern="service fee", category=Category.FEES),
    CategoryRule(pattern="atm fee", category=Category.FEES),
    CategoryRule(pattern="overdraft", category=Category.FEES),
    CategoryRule(pattern="irs", category=Category.TAXES),
    CategoryRule(pattern="tax payment", category=Category.TAXES),
)
