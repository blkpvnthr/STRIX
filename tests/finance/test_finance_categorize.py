"""Tests for deterministic rule-based categorization and merchant normalization.

Categorization is a pure, deterministic function of a transaction's description
and amount against an ordered rule set — no machine learning and no network.
The tests assert the happy paths (a grocery/dining/utility description maps via
``DEFAULT_RULES``; card-processor noise is stripped from a merchant name), the
invariants (priority ordering is honored; unmatched positive -> income and
unmatched negative -> other; results are byte-for-byte reproducible) and the
adversarial edges (an empty rule pattern is rejected at the model boundary).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.finance.categorize import (
    DEFAULT_RULES,
    Category,
    CategoryRule,
    NormalizedTransaction,
    categorize,
    categorize_all,
    make_transaction,
    normalize_merchant,
)

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _txn(amount: str, *, description: str, day: int = 1) -> NormalizedTransaction:
    """A transaction on 2026-01-<day>; negative ``amount`` is an outflow."""
    return make_transaction(
        posted_date=date(2026, 1, day),
        amount=Decimal(amount),
        account_id="ACCT",
        description=description,
    )


# --------------------------------------------------------------------------
# Category vocabulary
# --------------------------------------------------------------------------


def test_category_has_at_least_twelve_members() -> None:
    assert len(Category) >= 12
    # Required anchors used elsewhere in the module contract.
    assert Category.INCOME in Category
    assert Category.OTHER in Category


# --------------------------------------------------------------------------
# normalize_merchant
# --------------------------------------------------------------------------


def test_normalize_strips_pos_store_date_and_state_noise() -> None:
    raw = "POS WHOLE FOODS #1234 SEATTLE WA 01/23"
    out = normalize_merchant(raw)
    assert out == "Whole Foods Seattle"
    # None of the card-processor noise survives.
    assert "POS" not in out.upper().split()
    assert "#" not in out
    assert not any(ch.isdigit() for ch in out)
    assert "WA" not in out.split()


def test_normalize_collapses_whitespace_and_title_cases() -> None:
    assert normalize_merchant("TRADER    JOES     ") == "Trader Joes"


def test_normalize_strips_iso_date_and_bare_store_number() -> None:
    assert normalize_merchant("SHELL OIL 55123 2026-01-23") == "Shell Oil"


def test_normalize_is_deterministic() -> None:
    raw = "POS STARBUCKS #0099 PORTLAND OR 12/31"
    assert normalize_merchant(raw) == normalize_merchant(raw)


def test_normalize_leaves_clean_name_only_title_cased() -> None:
    assert normalize_merchant("comcast internet") == "Comcast Internet"


# --------------------------------------------------------------------------
# categorize via DEFAULT_RULES
# --------------------------------------------------------------------------


def test_default_rules_map_grocery_dining_utility() -> None:
    assert categorize(_txn("-80", description="WHOLE FOODS MARKET #123"), DEFAULT_RULES) == (
        Category.GROCERIES
    )
    assert categorize(_txn("-6", description="STARBUCKS STORE 55"), DEFAULT_RULES) == (
        Category.DINING
    )
    assert categorize(_txn("-120", description="COMCAST INTERNET"), DEFAULT_RULES) == (
        Category.UTILITIES
    )


def test_default_rules_are_case_insensitive() -> None:
    assert categorize(_txn("-80", description="whole foods"), DEFAULT_RULES) == (
        Category.GROCERIES
    )


# --------------------------------------------------------------------------
# priority ordering
# --------------------------------------------------------------------------


def test_higher_priority_rule_wins_over_lower() -> None:
    rules = (
        CategoryRule(pattern="shop", category=Category.SHOPPING, priority=0),
        CategoryRule(pattern="market", category=Category.GROCERIES, priority=5),
    )
    # Description matches both patterns; the higher-priority rule decides.
    txn = _txn("-20", description="SUPER SHOP MARKET")
    assert categorize(txn, rules) == Category.GROCERIES


def test_equal_priority_breaks_ties_by_rule_order() -> None:
    rules = (
        CategoryRule(pattern="shop", category=Category.SHOPPING, priority=0),
        CategoryRule(pattern="market", category=Category.GROCERIES, priority=0),
    )
    txn = _txn("-20", description="SUPER SHOP MARKET")
    # Both priority 0; the first rule in declaration order wins.
    assert categorize(txn, rules) == Category.SHOPPING


# --------------------------------------------------------------------------
# unmatched fallthrough
# --------------------------------------------------------------------------


def test_unmatched_positive_amount_is_income() -> None:
    txn = _txn("500", description="MYSTERY INFLOW XYZ")
    assert categorize(txn, DEFAULT_RULES) == Category.INCOME


def test_unmatched_negative_amount_is_other() -> None:
    txn = _txn("-33", description="MYSTERY OUTFLOW XYZ")
    assert categorize(txn, DEFAULT_RULES) == Category.OTHER


def test_matching_rule_wins_even_for_positive_amount() -> None:
    # A positive refund that still matches a merchant rule keeps that category.
    txn = _txn("25", description="AMAZON REFUND")
    assert categorize(txn, DEFAULT_RULES) == Category.SHOPPING


def test_empty_rules_falls_through_by_sign() -> None:
    assert categorize(_txn("5", description="X"), ()) == Category.INCOME
    assert categorize(_txn("-5", description="X"), ()) == Category.OTHER
    # Zero amount is not income.
    assert categorize(_txn("0", description="X"), ()) == Category.OTHER


# --------------------------------------------------------------------------
# categorize_all
# --------------------------------------------------------------------------


def test_categorize_all_pairs_ids_with_categories_in_order() -> None:
    txns = [
        _txn("-80", description="WHOLE FOODS", day=1),
        _txn("-6", description="STARBUCKS", day=2),
        _txn("500", description="PAYROLL DEPOSIT", day=3),
    ]
    result = categorize_all(txns, DEFAULT_RULES)
    assert result == (
        (txns[0].txn_id, Category.GROCERIES),
        (txns[1].txn_id, Category.DINING),
        (txns[2].txn_id, Category.INCOME),
    )


def test_categorize_all_is_deterministic() -> None:
    txns = [
        _txn("-80", description="WHOLE FOODS", day=1),
        _txn("-120", description="COMCAST INTERNET", day=2),
    ]
    assert categorize_all(txns, DEFAULT_RULES) == categorize_all(txns, DEFAULT_RULES)


# --------------------------------------------------------------------------
# adversarial / model boundary
# --------------------------------------------------------------------------


def test_empty_pattern_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CategoryRule(pattern="", category=Category.OTHER)


def test_category_rule_is_frozen() -> None:
    rule = CategoryRule(pattern="x", category=Category.OTHER)
    with pytest.raises(ValidationError):
        rule.pattern = "y"  # type: ignore[misc]


def test_category_rule_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        CategoryRule(pattern="x", category=Category.OTHER, bogus=1)  # type: ignore[call-arg]
