"""Selective admission / abstention (R-N4, part 2).

Reference implementation of the selective classifier ``g`` and its risk-coverage metrics
(confidential companion §7). The defining constraint is **non-overridable**:

    g(c) = 1  ⇒  A_DTEC(c) = PASS

i.e. a claim may be released only if it was independently admitted; statistical
confidence / low uncertainty can never override a failed or abstained mandatory predicate.
Selective risk is undefined when nothing is released (reported as ``None``, never 0).
"""

from __future__ import annotations

from decimal import Decimal

from strix.models import DecimalValue, StrixModel
from strix.native.arithmetic import checked_div, checked_sum

__all__ = [
    "SelectiveDecision",
    "coverage",
    "select_release",
    "selective_risk",
]


class SelectiveDecision(StrixModel):
    """Whether a claim is released (``g``), with the governing reason."""

    claim_id: str
    release: bool
    reason: str


def select_release(
    claim_id: str, *, admitted: bool, uncertainty_acceptable: bool = True
) -> SelectiveDecision:
    """Decide ``g`` for a claim.

    ``admitted`` is whether ``A_DTEC`` returned PASS for the claim — the **mandatory,
    non-overridable** precondition for release. ``uncertainty_acceptable`` is an
    *additional* (never substitutive) gate: even when True it cannot release a
    non-admitted claim. Release iff ``admitted and uncertainty_acceptable``.
    """
    if not admitted:
        # Hard rule: a non-admitted claim is never released, regardless of confidence.
        return SelectiveDecision(claim_id=claim_id, release=False, reason="not_admitted")
    if not uncertainty_acceptable:
        return SelectiveDecision(claim_id=claim_id, release=False, reason="uncertainty_too_high")
    return SelectiveDecision(claim_id=claim_id, release=True, reason="released")


def coverage(decisions: tuple[SelectiveDecision, ...]) -> DecimalValue:
    """Coverage ``= N⁻¹ Σ g_i`` — the fraction of claims released. Empty set ⇒ 0."""
    if not decisions:
        return Decimal(0)
    released = sum(1 for d in decisions if d.release)
    return checked_div(Decimal(released), Decimal(len(decisions)))


def selective_risk(
    decisions: tuple[SelectiveDecision, ...], losses: dict[str, Decimal]
) -> Decimal | None:
    """Selective risk ``= Σ_{g=1} l_i / Σ g_i`` over released claims.

    Returns ``None`` when nothing is released (the risk is *undefined*, never reported as
    0). A released claim with no supplied loss is treated as loss 0.
    """
    released = [d for d in decisions if d.release]
    if not released:
        return None
    total_loss = checked_sum([losses.get(d.claim_id, Decimal(0)) for d in released])
    return checked_div(total_loss, Decimal(len(released)))
