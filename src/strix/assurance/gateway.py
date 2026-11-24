"""The six-pillar independent assurance gateway (R2, R1 §2).

STRIX routes every externally-consequential answer or action through ONE
independent authorization gateway that composes the six assurance pillars into a
single deterministic :class:`GatewayDecision`:

1. **Evidence verification** — the admission decision over the five independent
   predicates (:class:`~strix.evidence_graph.predicates.AdmissionDecision`).
2. **Policy enforcement** — the independent-execution authorization kernel
   (:class:`~strix.assurance.authorization.AuthorizationDecision`), present only
   when the request carries an external state-changing action.
3. **Behavior monitoring** — the runtime behavior monitor's terminal
   intervention (:class:`~strix.assurance.monitoring.MonitorFinding`).
4. **Uncertainty scoring** — the honest ordinal uncertainty assessment
   (:class:`~strix.assurance.uncertainty.UncertaintyAssessment`).
5. **Adversarial testing** — exercised upstream and locked by the regression
   fixtures that pin this gateway's precedence (see the accompanying tests).
6. **Decision traceability** — every contributing pillar signal is surfaced as a
   typed :class:`GatewayReasonCode`, and each pillar's own terminal verdict is
   carried verbatim on the :class:`GatewayDecision`.

Independence & non-override (R1 §2)
-----------------------------------
The autonomous agent does not own this gateway. :func:`evaluate_gateway` is a
pure, deterministic composition of the four pillar inputs; none of them is an
agent-settable "approve" switch. The central invariant — enforced by the
documented precedence below and exhaustively by the tests — is that the gateway
**never** returns :attr:`GatewayOutcome.AUTHORIZED` while *any* pillar objects.
A favourable signal on one pillar can never relax another pillar's objection.

Honesty
-------
The gateway emits an ordinal :class:`GatewayOutcome` plus explicit named reason
codes derived deterministically from the pillar verdicts — never an invented
probability. Cryptographic integrity/authenticity (what the authorization and
evidence pillars attest) is distinct from factual correctness: an
``AUTHORIZED`` outcome means every independent control cleared the action, not
that the underlying answer is *true*.

Precedence (most severe wins; fully deterministic)
--------------------------------------------------
1. ``REJECTED`` — the monitor says ``terminate``, OR evidence admission was
   ``REJECTED``, OR a present authorization was ``denied``.
2. ``REVIEW_REQUIRED`` — the monitor says ``escalate_human`` or ``restrict``.
3. ``ABSTAIN`` — evidence admission was ``ABSTAINED``, OR the monitor says
   ``abstain``, OR uncertainty is ``insufficient``, OR an abstention is
   recommended.
4. ``QUALIFIED`` — admission ``ADMITTED`` but uncertainty is ``moderate`` /
   ``high`` (or answer coverage is only partial).
5. ``AUTHORIZED`` — admission ``ADMITTED``, uncertainty ``low`` with full
   coverage, the monitor says ``continue``, and any authorization present is
   ``granted``.

A defensive final fallback returns ``REVIEW_REQUIRED`` for any combination not
matched above: the gateway fails closed, never to ``AUTHORIZED`` (R1 §2).
"""

from __future__ import annotations

from enum import StrEnum

from strix.assurance.authorization import AuthorizationDecision, Decision
from strix.assurance.monitoring import Intervention, MonitorFinding
from strix.assurance.uncertainty import UncertaintyAssessment, UncertaintyLevel
from strix.evidence_graph.nodes import AdmissionOutcome
from strix.evidence_graph.predicates import AdmissionDecision
from strix.models import StrixModel

__all__ = [
    "GatewayDecision",
    "GatewayOutcome",
    "GatewayReasonCode",
    "evaluate_gateway",
]

#: Label on ``answer_completeness`` (uncertainty's completeness dimension) that
#: marks coverage as only partial — never eligible for full authorization.
_PARTIAL_COVERAGE = "partial"

#: The ONLY answer-completeness label eligible for full authorization. The
#: AUTHORIZED gate whitelists this value, so any other/unknown label fails closed.
_COMPLETE_COVERAGE = "complete"

#: Uncertainty levels that downgrade an admitted answer to ``QUALIFIED``.
_ELEVATED_LEVELS = frozenset({UncertaintyLevel.MODERATE, UncertaintyLevel.HIGH})


class GatewayOutcome(StrEnum):
    """The gateway's terminal ordinal outcome (least→most permissive is not the
    ordering here; selection is by *severity* per the documented precedence)."""

    AUTHORIZED = "authorized"
    QUALIFIED = "qualified"
    REVIEW_REQUIRED = "review_required"
    ABSTAIN = "abstain"
    REJECTED = "rejected"


class GatewayReasonCode(StrEnum):
    """Typed, deterministic reason codes naming each contributing pillar signal.

    Every code is a pure function of the pillar inputs; the tuple ordering on a
    decision is sorted and de-duplicated for stable auditability.
    """

    # Rejected tier
    MONITOR_TERMINATE = "monitor_intervention_terminate"
    ADMISSION_REJECTED = "evidence_admission_rejected"
    AUTHORIZATION_DENIED = "authorization_denied"
    # Review-required tier
    MONITOR_ESCALATE_HUMAN = "monitor_intervention_escalate_human"
    MONITOR_RESTRICT = "monitor_intervention_restrict"
    # Abstain tier
    ADMISSION_ABSTAINED = "evidence_admission_abstained"
    MONITOR_ABSTAIN = "monitor_intervention_abstain"
    UNCERTAINTY_INSUFFICIENT = "uncertainty_level_insufficient"
    ABSTENTION_RECOMMENDED = "uncertainty_abstention_recommended"
    # Qualified tier
    UNCERTAINTY_ELEVATED = "uncertainty_level_elevated"
    PARTIAL_COVERAGE = "answer_coverage_partial"
    # Authorized tier
    ALL_PILLARS_CLEARED = "all_pillars_cleared"
    # Defensive fallback
    UNCLASSIFIED_COMBINATION = "unclassified_pillar_combination"


class GatewayDecision(StrixModel):
    """The single, fully-diagnosed outcome of composing the six pillars.

    ``outcome`` is the ordinal verdict; ``reason_codes`` aggregates every
    contributing pillar signal (sorted, de-duplicated). The remaining fields
    carry each pillar's own terminal verdict verbatim for traceability:
    ``verification_outcome`` (evidence), ``authorization_decision`` (policy, or
    ``None`` when no external action was authorized), ``uncertainty_level``, and
    ``intervention`` (behavior monitor).
    """

    outcome: GatewayOutcome
    reason_codes: tuple[str, ...]
    verification_outcome: str
    authorization_decision: str | None
    uncertainty_level: str
    intervention: str


def _reject_codes(
    admission: AdmissionDecision,
    monitor_finding: MonitorFinding,
    authorization: AuthorizationDecision | None,
) -> list[GatewayReasonCode]:
    """Collect every rejection signal that applies (aggregate, not short-circuit)."""
    codes: list[GatewayReasonCode] = []
    if monitor_finding.intervention is Intervention.TERMINATE:
        codes.append(GatewayReasonCode.MONITOR_TERMINATE)
    if admission.outcome is AdmissionOutcome.REJECTED:
        codes.append(GatewayReasonCode.ADMISSION_REJECTED)
    if authorization is not None and authorization.decision is Decision.DENIED:
        codes.append(GatewayReasonCode.AUTHORIZATION_DENIED)
    return codes


def _review_codes(monitor_finding: MonitorFinding) -> list[GatewayReasonCode]:
    """Collect every review-required signal that applies."""
    codes: list[GatewayReasonCode] = []
    if monitor_finding.intervention is Intervention.ESCALATE_HUMAN:
        codes.append(GatewayReasonCode.MONITOR_ESCALATE_HUMAN)
    if monitor_finding.intervention is Intervention.RESTRICT:
        codes.append(GatewayReasonCode.MONITOR_RESTRICT)
    return codes


def _abstain_codes(
    admission: AdmissionDecision,
    uncertainty: UncertaintyAssessment,
    monitor_finding: MonitorFinding,
) -> list[GatewayReasonCode]:
    """Collect every abstain signal that applies."""
    codes: list[GatewayReasonCode] = []
    if admission.outcome is AdmissionOutcome.ABSTAINED:
        codes.append(GatewayReasonCode.ADMISSION_ABSTAINED)
    if monitor_finding.intervention is Intervention.ABSTAIN:
        codes.append(GatewayReasonCode.MONITOR_ABSTAIN)
    if uncertainty.level is UncertaintyLevel.INSUFFICIENT:
        codes.append(GatewayReasonCode.UNCERTAINTY_INSUFFICIENT)
    if uncertainty.components.abstention_recommended:
        codes.append(GatewayReasonCode.ABSTENTION_RECOMMENDED)
    return codes


def _qualified_codes(uncertainty: UncertaintyAssessment) -> list[GatewayReasonCode]:
    """Collect every qualified (downgrade-from-authorized) signal that applies."""
    codes: list[GatewayReasonCode] = []
    if uncertainty.level in _ELEVATED_LEVELS:
        codes.append(GatewayReasonCode.UNCERTAINTY_ELEVATED)
    if uncertainty.dimensions.answer_completeness == _PARTIAL_COVERAGE:
        codes.append(GatewayReasonCode.PARTIAL_COVERAGE)
    return codes


def _finalize(
    outcome: GatewayOutcome,
    codes: list[GatewayReasonCode],
    *,
    admission: AdmissionDecision,
    uncertainty: UncertaintyAssessment,
    monitor_finding: MonitorFinding,
    authorization: AuthorizationDecision | None,
) -> GatewayDecision:
    """Assemble the decision, carrying each pillar's verbatim terminal verdict."""
    reason_codes = tuple(sorted({code.value for code in codes}))
    return GatewayDecision(
        outcome=outcome,
        reason_codes=reason_codes,
        verification_outcome=admission.verification_outcome.value,
        authorization_decision=(
            None if authorization is None else authorization.decision.value
        ),
        uncertainty_level=uncertainty.level.value,
        intervention=monitor_finding.intervention.value,
    )


def evaluate_gateway(
    *,
    admission: AdmissionDecision,
    uncertainty: UncertaintyAssessment,
    monitor_finding: MonitorFinding,
    authorization: AuthorizationDecision | None = None,
) -> GatewayDecision:
    """Compose the six pillars into one deterministic :class:`GatewayDecision`.

    Applies the documented, severity-ordered precedence (see the module
    docstring). This is the independent authorization gateway (R1 §2): it is a
    pure function of the pillar verdicts and the autonomous agent cannot override
    it. The gateway **never** returns :attr:`GatewayOutcome.AUTHORIZED` while any
    pillar objects; an unclassified combination fails closed to
    :attr:`GatewayOutcome.REVIEW_REQUIRED`.

    ``authorization`` is ``None`` when the evaluated answer carries no external
    state-changing action (there is nothing for the policy pillar to authorize);
    its absence is treated as "no objection from that pillar", never as a grant.
    """
    # 1. REJECTED — most severe: a hard stop from monitor, evidence, or policy.
    reject = _reject_codes(admission, monitor_finding, authorization)
    if reject:
        return _finalize(
            GatewayOutcome.REJECTED,
            reject,
            admission=admission,
            uncertainty=uncertainty,
            monitor_finding=monitor_finding,
            authorization=authorization,
        )

    # 2. REVIEW_REQUIRED — the monitor demands human escalation or restriction.
    review = _review_codes(monitor_finding)
    if review:
        return _finalize(
            GatewayOutcome.REVIEW_REQUIRED,
            review,
            admission=admission,
            uncertainty=uncertainty,
            monitor_finding=monitor_finding,
            authorization=authorization,
        )

    # 3. ABSTAIN — evidence/monitor/uncertainty counsel withholding a verdict.
    abstain = _abstain_codes(admission, uncertainty, monitor_finding)
    if abstain:
        return _finalize(
            GatewayOutcome.ABSTAIN,
            abstain,
            admission=admission,
            uncertainty=uncertainty,
            monitor_finding=monitor_finding,
            authorization=authorization,
        )

    # 4. QUALIFIED — admitted, but uncertainty is elevated or coverage partial.
    if admission.outcome is AdmissionOutcome.ADMITTED:
        qualified = _qualified_codes(uncertainty)
        if qualified:
            return _finalize(
                GatewayOutcome.QUALIFIED,
                qualified,
                admission=admission,
                uncertainty=uncertainty,
                monitor_finding=monitor_finding,
                authorization=authorization,
            )

        # 5. AUTHORIZED — every pillar cleared: admitted, low uncertainty with
        #    full coverage, monitor continue, and any authorization granted.
        if (
            uncertainty.level is UncertaintyLevel.LOW
            and uncertainty.dimensions.answer_completeness == _COMPLETE_COVERAGE
            and monitor_finding.intervention is Intervention.CONTINUE
            and (authorization is None or authorization.decision is Decision.GRANTED)
        ):
            return _finalize(
                GatewayOutcome.AUTHORIZED,
                [GatewayReasonCode.ALL_PILLARS_CLEARED],
                admission=admission,
                uncertainty=uncertainty,
                monitor_finding=monitor_finding,
                authorization=authorization,
            )

    # Defensive fallback: fail closed, never to AUTHORIZED (R1 §2).
    return _finalize(
        GatewayOutcome.REVIEW_REQUIRED,
        [GatewayReasonCode.UNCLASSIFIED_COMBINATION],
        admission=admission,
        uncertainty=uncertainty,
        monitor_finding=monitor_finding,
        authorization=authorization,
    )
