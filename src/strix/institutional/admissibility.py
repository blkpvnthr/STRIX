"""Institutional evidence admissibility — the ``A_inst`` predicate (R-N6, part 1).

Reference implementation of research engine R-N6 (confidential companion §9). Distinguishes
*factual correctness* from *institutional applicability*: whether a piece of evidence may be
used in a given institutional context ``Ω = (o, u, r, p, j, t, P)``:

    A_inst(e, Ω) = O(e,Ω) ∧ L(e,Ω) ∧ J(e,Ω) ∧ X(e,Ω)

with O = organizational applicability, L = access authorization, J = governing authority /
jurisdiction, X = project/procedural applicability. Composition uses the same four-valued
admission algebra. **Fail-closed:** missing institutional metadata is UNKNOWN (abstain),
never favorable; unresolved policy precedence denies (`policy_reasoner`). Builds on the
existing per-institution isolation (`institutional/{models,isolation,registry}.py`), which
it does not replace.
"""

from __future__ import annotations

from strix.evidence_graph.calculus import compose_statuses
from strix.evidence_graph.nodes import PredicateName, PredicateResult, PredicateStatus
from strix.models import StrixModel

__all__ = [
    "InstitutionalContext",
    "InstitutionalLabel",
    "assess_institutional",
    "institution_admissible_ids",
]


class InstitutionalContext(StrixModel):
    """The requesting institutional context ``Ω`` and the grants it carries.

    The grant tuples enumerate what this context is authorized for; evidence is admissible
    only when its label falls within every grant dimension.
    """

    organization: str
    user: str
    role: str
    project: str
    jurisdiction: str
    authorized_organizations: tuple[str, ...]
    authorized_access_levels: tuple[str, ...]
    authorized_jurisdictions: tuple[str, ...]
    authorized_projects: tuple[str, ...]


class InstitutionalLabel(StrixModel):
    """The institutional attributes an evidence artifact declares."""

    evidence_id: str
    organization: str
    access_level: str
    jurisdiction: str
    project: str


def _membership(
    value: str, allowed: tuple[str, ...], code_ok: str, code_bad: str
) -> tuple[PredicateStatus, str]:
    if not value:
        return PredicateStatus.UNKNOWN, f"{code_bad}:unresolved"
    if value in allowed:
        return PredicateStatus.PASS, code_ok
    return PredicateStatus.FAIL, code_bad


def assess_institutional(
    label: InstitutionalLabel | None, context: InstitutionalContext
) -> PredicateResult:
    """Evaluate ``A_inst = O ∧ L ∧ J ∧ X`` for one evidence item under *context*.

    A missing label (``None``) is UNKNOWN (abstain) — institutional applicability cannot be
    established, which must never default to admissible.
    """
    if label is None:
        return PredicateResult(
            predicate=PredicateName.INSTITUTIONAL,
            status=PredicateStatus.UNKNOWN,
            reason_codes=("institutional_metadata_absent",),
            detail="no institutional label; applicability cannot be established",
        )
    o_status, o_code = _membership(
        label.organization, context.authorized_organizations, "org_applicable", "org_not_applicable"
    )
    l_status, l_code = _membership(
        label.access_level, context.authorized_access_levels, "access_authorized", "access_denied"
    )
    j_status, j_code = _membership(
        label.jurisdiction, context.authorized_jurisdictions, "jurisdiction_governed",
        "jurisdiction_not_governed",
    )
    x_status, x_code = _membership(
        label.project, context.authorized_projects, "project_applicable", "project_not_applicable"
    )
    statuses = (o_status, l_status, j_status, x_status)
    overall = compose_statuses(statuses)
    codes = tuple(
        code
        for status, code in (
            (o_status, o_code), (l_status, l_code), (j_status, j_code), (x_status, x_code)
        )
        if status is not PredicateStatus.PASS
    ) or ("institutionally_admissible",)
    return PredicateResult(
        predicate=PredicateName.INSTITUTIONAL,
        status=overall,
        reason_codes=codes,
        detail=f"O={o_status.value} L={l_status.value} J={j_status.value} X={x_status.value}",
    )


def institution_admissible_ids(
    labels: tuple[InstitutionalLabel, ...], context: InstitutionalContext
) -> frozenset[str]:
    """The institutionally-scoped node set ``V_Ω = {v : A_inst(v,Ω)=PASS}``."""
    return frozenset(
        label.evidence_id
        for label in labels
        if assess_institutional(label, context).status is PredicateStatus.PASS
    )
