"""Tests for resource-bounded verification planning (R-N5): greedy plan + M_B predicate.

Covers the mandatory-first greedy planner, prerequisite handling, the ``M_B`` fail-safe
(infeasible mandatory ⇒ ABSTAIN, never a silent pass — INV-N5-1), verified yield, and a
Hypothesis property test of the mandatory-feasibility invariant.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from strix.assurance.verification_planner import (
    ResourceBudget,
    VerificationOp,
    assess_budget,
    plan_verification,
    verified_yield,
)
from strix.evidence_graph.nodes import PredicateName, PredicateStatus


def _op(op_id, utility="1", cost="1", prerequisites=(), mandatory=False) -> VerificationOp:
    return VerificationOp(
        op_id=op_id,
        utility=Decimal(utility),
        cost=Decimal(cost),
        prerequisites=prerequisites,
        mandatory=mandatory,
    )


def _budget(total) -> ResourceBudget:
    return ResourceBudget(total=Decimal(total))


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------


def test_mandatory_selected_first() -> None:
    ops = (_op("m", mandatory=True, cost="3"), _op("o", utility="1", cost="1"))
    plan = plan_verification(ops, _budget("3"))
    assert plan.mandatory_feasible
    assert "m" in plan.selected and "o" not in plan.selected  # only mandatory fits


def test_mandatory_infeasible_yields_empty_plan() -> None:
    ops = (_op("m", mandatory=True, cost="10"),)
    plan = plan_verification(ops, _budget("5"))
    assert not plan.mandatory_feasible
    assert plan.selected == ()


def test_greedy_prefers_higher_ratio() -> None:
    # Budget 2: op "hi" (u=10,c=1) beats "lo" (u=1,c=2) by ratio; both can't both fit? hi+lo=3>2.
    ops = (_op("hi", utility="10", cost="1"), _op("lo", utility="1", cost="2"))
    plan = plan_verification(ops, _budget("2"))
    assert "hi" in plan.selected and "lo" not in plan.selected


def test_prerequisite_included_with_op() -> None:
    ops = (
        _op("base", utility="0", cost="1"),
        _op("dep", utility="5", cost="1", prerequisites=("base",)),
    )
    plan = plan_verification(ops, _budget("2"))
    assert "dep" in plan.selected and "base" in plan.selected


def test_op_excluded_when_prereq_does_not_fit() -> None:
    ops = (
        _op("base", utility="0", cost="5"),
        _op("dep", utility="5", cost="1", prerequisites=("base",)),
    )
    plan = plan_verification(ops, _budget("3"))  # base+dep=6>3
    assert "dep" not in plan.selected and "base" not in plan.selected


def test_free_ops_always_included() -> None:
    ops = (_op("free", utility="1", cost="0"), _op("m", mandatory=True, cost="2"))
    plan = plan_verification(ops, _budget("2"))
    assert "free" in plan.selected and "m" in plan.selected


def test_total_cost_within_budget() -> None:
    ops = (
        _op("a", utility="3", cost="2"),
        _op("b", utility="2", cost="2"),
        _op("c", utility="1", cost="2"),
    )
    plan = plan_verification(ops, _budget("5"))
    assert plan.total_cost <= Decimal("5")


def test_prereq_cycle_raises() -> None:
    ops = (_op("a", prerequisites=("b",)), _op("b", prerequisites=("a",)))
    with pytest.raises(ValueError, match="cycle"):
        plan_verification(ops, _budget("10"))


def test_unknown_prereq_raises_for_mandatory() -> None:
    ops = (_op("a", mandatory=True, prerequisites=("missing",)),)
    with pytest.raises(ValueError, match="unknown prerequisite"):
        plan_verification(ops, _budget("10"))


def test_duplicate_op_id_raises() -> None:
    ops = (_op("a"), _op("a"))
    with pytest.raises(ValueError, match="duplicate"):
        plan_verification(ops, _budget("10"))


# --------------------------------------------------------------------------
# M_B predicate
# --------------------------------------------------------------------------


def test_mb_pass_when_mandatory_fits() -> None:
    ops = (_op("m", mandatory=True, cost="3"),)
    res = assess_budget(ops, _budget("5"))
    assert res.status is PredicateStatus.PASS
    assert res.predicate is PredicateName.BUDGET


def test_mb_abstains_when_mandatory_infeasible() -> None:
    ops = (_op("m", mandatory=True, cost="10"),)
    res = assess_budget(ops, _budget("5"))
    assert res.status is PredicateStatus.UNKNOWN  # never a silent pass
    assert res.reason_codes == ("mandatory_exceeds_budget",)


def test_mb_pass_with_no_mandatory_ops() -> None:
    ops = (_op("o", cost="1"),)
    assert assess_budget(ops, _budget("0")).status is PredicateStatus.PASS  # 0 mandatory fits 0


# --------------------------------------------------------------------------
# Verified yield
# --------------------------------------------------------------------------


def test_verified_yield_sums_correct_only() -> None:
    ops = (_op("a", utility="3"), _op("b", utility="5"), _op("c", utility="7"))
    y = verified_yield(ops, frozenset({"a", "b", "c"}), {"a": True, "b": False, "c": True})
    assert y == Decimal("10")  # a + c; b incorrect excluded


def test_verified_yield_zero_without_correct() -> None:
    ops = (_op("a", utility="3"),)
    assert verified_yield(ops, frozenset({"a"}), {"a": False}) == Decimal(0)


# --------------------------------------------------------------------------
# Property test — INV-N5-1 mandatory feasibility
# --------------------------------------------------------------------------


@st.composite
def _ops_and_budget(draw):
    n = draw(st.integers(min_value=1, max_value=6))
    ops = []
    for i in range(n):
        ops.append(
            _op(
                f"op{i}",
                utility=str(draw(st.integers(min_value=0, max_value=9))),
                cost=str(draw(st.integers(min_value=0, max_value=9))),
                mandatory=draw(st.booleans()),
            )
        )
    return tuple(ops), _budget(str(draw(st.integers(min_value=0, max_value=30))))


@settings(max_examples=250)
@given(_ops_and_budget())
def test_invn5_1_mandatory_feasibility_and_budget(data) -> None:
    ops, budget = data
    plan = plan_verification(ops, budget)
    mandatory_cost = sum((Decimal(o.cost) for o in ops if o.mandatory), Decimal(0))
    # M_B PASS iff mandatory fits; never a silent pass when infeasible.
    mb = assess_budget(ops, budget)
    if mandatory_cost > Decimal(budget.total):
        assert not plan.mandatory_feasible
        assert mb.status is PredicateStatus.UNKNOWN
    else:
        assert plan.mandatory_feasible
        assert mb.status is PredicateStatus.PASS
        # every mandatory op is in the selection
        for o in ops:
            if o.mandatory:
                assert o.op_id in plan.selected
        assert plan.total_cost <= Decimal(budget.total)


def test_negative_cost_rejected_at_boundary() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        VerificationOp(op_id="m", utility=Decimal(1), cost=Decimal("-1000"), mandatory=True)


def test_negative_budget_rejected_at_boundary() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ResourceBudget(total=Decimal("-5"))
