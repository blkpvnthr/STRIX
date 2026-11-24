"""Regressions for the R3 finance adversarial review (workflow wf_f3b24e12-d14):

- MAJOR transfers: greedy nearest-date assignment is not a maximum matching, so a
  genuine transfer could be missed and its legs double-counted as income+expense.
  Fix: maximum-cardinality bipartite matching.
- MAJOR anomaly: the duplicate self-guard compared content-derived txn_ids, so two
  genuine identical charges (same fields -> same id) were skipped — exactly the
  canonical double charge the detector exists to catch. Fix: positional guard.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from strix.finance.anomaly import AnomalyMethod, detect_duplicate_charges
from strix.finance.transactions import make_transaction
from strix.finance.transfers import classify_income_expense, match_transfers


def _t(account: str, amount: str, day: int, desc: str = "", *, owned: bool = True) -> object:
    return make_transaction(
        posted_date=date(2026, 1, day), amount=Decimal(amount),
        account_id=account, description=desc, owned=owned,
    )


class TestTransferMaximumMatching:
    def test_both_disjoint_transfers_matched(self) -> None:
        # Greedy would take O2-I1 (gap 0), stranding O1 (whose only edge is I1).
        # A maximum matching finds {O1-I1, O2-I2}.
        o1, o2 = _t("A", "-100", 1), _t("A", "-100", 11)
        i1, i2 = _t("B", "100", 11), _t("B", "100", 14)
        txns = [o1, o2, i1, i2]
        matches = match_transfers(txns, max_day_gap=10)  # type: ignore[arg-type]
        assert len(matches) == 2
        income, expense, transfer = classify_income_expense(txns, matches)  # type: ignore[arg-type]
        assert income == Decimal(0)
        assert expense == Decimal(0)
        assert transfer == Decimal("200")


class TestDuplicateChargeDetection:
    def test_identical_content_duplicate_is_flagged(self) -> None:
        # Same amount/description/date/account -> identical content txn_id; the
        # canonical double charge must still be flagged (was suppressed before).
        a, b = _t("CARD", "-50", 5, "Coffee"), _t("CARD", "-50", 5, "Coffee")
        findings = detect_duplicate_charges([a, b], max_day_gap=2)  # type: ignore[arg-type]
        assert len(findings) >= 1
        assert all(f.method is AnomalyMethod.DUPLICATE for f in findings)
        assert all("fraud" not in f.note.lower() for f in findings)
