"""Resource-bounded verification planning — the ``M_B`` predicate (R-N5).

Reference implementation of research engine R-N5 (confidential companion §8). Given a set
of verification operations with (additive) costs, prerequisites, and a mandatory subset,
it plans which operations to run under a resource budget so as to maximize verified
utility, and exposes the ``M_B`` predicate:

    M_B = PASS   iff all mandatory verifications fit within the budget B
        = ABSTAIN (UNKNOWN) otherwise — resource exhaustion NEVER weakens mandatory
          assurance; an infeasible mandatory plan abstains rather than dropping a
          mandatory op (hard invariant, INV-N5-1).

The planner is a **deterministic greedy ratio scheduler** (utility per unit cost) — no
new dependency, no approximation guarantee claimed (INV-N5-3). A MIP/exact formulation
(CVXPY/OR-Tools) is a later, profiled, benchmarked option (ALG-N5-3). Costs are exact
:class:`~decimal.Decimal`. Only an additive scalar budget is modelled here; non-additive
resources (wall-clock, peak memory) require separate scheduling constraints (future work).
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import field_validator

from strix.evidence_graph.nodes import PredicateName, PredicateResult, PredicateStatus
from strix.models import DecimalValue, StrixModel
from strix.native.arithmetic import as_decimal, checked_sum, require_finite

__all__ = [
    "ResourceBudget",
    "VerificationOp",
    "VerificationPlan",
    "assess_budget",
    "plan_verification",
    "verified_yield",
]


class VerificationOp(StrixModel):
    """A candidate verification operation ``v_i = (u_i, b_i, D_i)``.

    ``utility`` is the expected verified-information utility, ``cost`` the (additive)
    resource consumption, ``prerequisites`` the op ids that must also run if this one
    does, and ``mandatory`` marks an operation that must run (or the plan abstains).
    """

    op_id: str
    utility: DecimalValue
    cost: DecimalValue
    prerequisites: tuple[str, ...] = ()
    mandatory: bool = False

    @field_validator("utility", "cost")
    @classmethod
    def _non_negative_finite(cls, value: Decimal) -> Decimal:
        # A negative or non-finite cost could net against others so a mandatory bundle
        # appears to fit the budget while a mandatory op is genuinely unaffordable
        # (fail-open for INV-N5-1). Reject at the boundary.
        require_finite(value)
        if value < 0:
            raise ValueError("utility and cost must be non-negative")
        return value


class ResourceBudget(StrixModel):
    """An additive scalar resource budget ``B`` (non-negative, finite)."""

    total: DecimalValue

    @field_validator("total")
    @classmethod
    def _non_negative_finite(cls, value: Decimal) -> Decimal:
        require_finite(value)
        if value < 0:
            raise ValueError("budget total must be non-negative")
        return value


class VerificationPlan(StrixModel):
    """The outcome of planning: the selected op ids, feasibility, and accounting."""

    selected: tuple[str, ...]
    mandatory_feasible: bool
    total_cost: DecimalValue
    budget: DecimalValue
    detail: str = ""


def _ops_by_id(ops: tuple[VerificationOp, ...]) -> dict[str, VerificationOp]:
    by_id: dict[str, VerificationOp] = {}
    for op in ops:
        if op.op_id in by_id:
            raise ValueError(f"duplicate verification op id {op.op_id!r}")
        by_id[op.op_id] = op
    return by_id


def _prereq_closure(
    op_id: str, by_id: dict[str, VerificationOp], _seen: frozenset[str]
) -> set[str]:
    """The op plus the transitive closure of its prerequisites. Raises on an unknown
    prerequisite or a prerequisite cycle (fail-closed — a malformed plan is not run)."""
    if op_id not in by_id:
        raise ValueError(f"unknown prerequisite op id {op_id!r}")
    if op_id in _seen:
        raise ValueError(f"prerequisite cycle through {op_id!r}")
    closure = {op_id}
    for prereq in by_id[op_id].prerequisites:
        closure |= _prereq_closure(prereq, by_id, _seen | {op_id})
    return closure


def _cost_of(ids: set[str], by_id: dict[str, VerificationOp]) -> Decimal:
    if not ids:
        return Decimal(0)
    return checked_sum([by_id[i].cost for i in ids])


def plan_verification(
    ops: tuple[VerificationOp, ...], budget: ResourceBudget
) -> VerificationPlan:
    """Plan verification under *budget* (greedy ratio over optional ops, mandatory first).

    Mandatory operations and their prerequisite closure are selected first. If they do not
    fit the budget the plan is **mandatory-infeasible** (``mandatory_feasible=False``,
    empty selection) — the caller must abstain (``M_B``), never drop a mandatory op.
    Remaining budget is filled greedily by optional operations in descending utility/cost
    ratio (free ops first), including each op's prerequisite closure, deterministic
    tie-break by op id.
    """
    by_id = _ops_by_id(ops)
    budget_total = Decimal(budget.total)

    # Validate the whole prerequisite graph upfront (fail-closed): a cycle or an unknown
    # prerequisite anywhere is a malformed plan and raises, rather than being silently
    # skipped for optional ops.
    for op in ops:
        _prereq_closure(op.op_id, by_id, frozenset())

    mandatory_bundle: set[str] = set()
    for op in ops:
        if op.mandatory:
            mandatory_bundle |= _prereq_closure(op.op_id, by_id, frozenset())
    mandatory_cost = _cost_of(mandatory_bundle, by_id)
    if mandatory_cost > budget_total:
        return VerificationPlan(
            selected=(),
            mandatory_feasible=False,
            total_cost=Decimal(0),
            budget=budget_total,
            detail=f"mandatory bundle costs {mandatory_cost} > budget {budget_total}",
        )

    selected = set(mandatory_bundle)
    spent = mandatory_cost

    # Greedy over optional ops by utility/cost ratio (free ops first), deterministic.
    def sort_key(op: VerificationOp) -> tuple[int, Decimal, str]:
        if op.cost == 0:
            return (0, Decimal(0), op.op_id)  # free ops first
        ratio = Decimal(op.utility) / Decimal(op.cost)
        return (1, -ratio, op.op_id)  # higher ratio first; id tie-break

    for op in sorted(ops, key=sort_key):
        if op.op_id in selected:
            continue
        bundle = _prereq_closure(op.op_id, by_id, frozenset())  # validated above
        delta = bundle - selected
        delta_cost = _cost_of(delta, by_id)
        if spent + delta_cost <= budget_total:
            selected |= delta
            spent += delta_cost

    return VerificationPlan(
        selected=tuple(sorted(selected)),
        mandatory_feasible=True,
        total_cost=spent,
        budget=budget_total,
        detail=f"selected {len(selected)} op(s) within budget {budget_total}",
    )


def assess_budget(ops: tuple[VerificationOp, ...], budget: ResourceBudget) -> PredicateResult:
    """The ``M_B`` predicate: PASS iff mandatory verification fits the budget, else ABSTAIN.

    Resource exhaustion must never weaken mandatory assurance — an infeasible mandatory
    plan yields UNKNOWN (abstain), never a silent pass (INV-N5-1).
    """
    result = plan_verification(ops, budget)
    if result.mandatory_feasible:
        return PredicateResult(
            predicate=PredicateName.BUDGET,
            status=PredicateStatus.PASS,
            reason_codes=("mandatory_within_budget",),
            detail=result.detail,
        )
    return PredicateResult(
        predicate=PredicateName.BUDGET,
        status=PredicateStatus.UNKNOWN,
        reason_codes=("mandatory_exceeds_budget",),
        detail=result.detail,
    )


def verified_yield(
    ops: tuple[VerificationOp, ...],
    completed: frozenset[str],
    correctness: dict[str, bool],
) -> Decimal:
    """Independently-assessed verified yield ``Y_ver = Σ_i q_i · 1[A_i=PASS] · y_i``.

    Sums the utility ``q_i`` of operations that were both completed and independently
    assessed correct (``correctness[op_id] is True``). Without labels the caller should
    report admitted utility separately; this function requires explicit correctness labels
    and never assumes correctness.
    """
    by_id = _ops_by_id(ops)
    contributing = [
        by_id[op_id].utility
        for op_id in completed
        if op_id in by_id and correctness.get(op_id) is True
    ]
    if not contributing:
        return Decimal(0)
    return checked_sum([as_decimal(u) for u in contributing])
