"""Wave 4: governed envelope over the research-agent outcome (§4).

The research agent (:func:`strix.agent.orchestrator.run_research_question`) runs its
own bounded tool loop, independent verifier, and fail-closed answer validation, but
is otherwise decoupled from the six-pillar assurance core. This module applies that
core as an INDEPENDENT final authorization over a completed :class:`ResearchOutcome`:

* derive the gateway's evidence (admission), uncertainty, and behavior-monitor
  signals from the agent's OWN verification results (no re-verification, no
  evidence-graph reconstruction);
* run :func:`evaluate_gateway` for the terminal authorization;
* persist a hash-chained audit trail for the run;
* mint and (optionally) Ed25519-sign a run-level :class:`AgentRunCertificate`;
* report whether the answer may be released.

The gateway is fail-closed and the agent cannot override it. This is an additive
envelope — it does not modify the agent loop and assigns no new factual verdicts.
The admission signal is explicitly the agent verifier's verdict surfaced to the
gateway (``policy_version="agent-verifier-bridge-1"``), NOT a claim that the
evidence-graph predicates ran.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime

from strix.agent.models import AgentVerificationStatus
from strix.agent.orchestrator import ResearchOutcome
from strix.assurance.authorization import AuthorizationDecision
from strix.assurance.gateway import GatewayDecision, GatewayOutcome, evaluate_gateway
from strix.assurance.monitoring import (
    BehaviorMonitor,
    MonitoredEvent,
    MonitoredEventType,
    MonitorFinding,
    MonitorPolicy,
)
from strix.assurance.signing import (
    Keyring,
    Signature,
    VerifyingKeyRecord,
    sign_certificate,
)
from strix.assurance.uncertainty import UncertaintyAssessment, assess_uncertainty
from strix.audit.events import EventDraft, EventType
from strix.audit.ledger import EventLedger
from strix.canonical import canonical_hash, make_id
from strix.evidence_graph.nodes import AdmissionOutcome, VerificationOutcome
from strix.evidence_graph.predicates import AdmissionDecision
from strix.models import StrixModel

#: Domain-separation tag for the run-level signature.
AGENT_RUN_SIGNING_DOMAIN = "strix.agent-run"
_BRIDGE_POLICY_VERSION = "agent-verifier-bridge-1"

#: Gateway outcomes under which the answer is released to the caller.
_RELEASED = frozenset({GatewayOutcome.AUTHORIZED, GatewayOutcome.QUALIFIED})

#: Trusted default thresholds for the independent behavior monitor over a completed
#: agent run. Lenient enough for a normal run, strict enough that a cost overrun,
#: tool-call blowout, or verification-failure pile-up is caught independently of the
#: agent's own (earlier, in-loop) budget enforcement.
DEFAULT_AGENT_MONITOR_POLICY = MonitorPolicy(
    max_tool_calls=1000,
    max_identical_calls=1000,
    max_cost=Decimal("100"),
    max_verification_failures=10,
)


def _seed_monitor_from_outcome(
    outcome: ResearchOutcome, policy: MonitorPolicy, now: datetime
) -> BehaviorMonitor:
    """Build an independent monitor and feed it the run's REAL behavioral signals.

    A monitor fed nothing is not a control; this surfaces the completed run's
    tool-call count, total cost, contradicted-claim verification failures, and
    budget exhaustion so the monitor pillar can independently drive RESTRICT /
    ESCALATE_HUMAN / TERMINATE.
    """
    monitor = BehaviorMonitor(policy)
    usage = outcome.usage
    # Distinct labels so the count is measured without false identical-call loops.
    for i in range(usage.tool_calls):
        monitor.record(
            MonitoredEvent(
                event_type=MonitoredEventType.TOOL_INVOCATION,
                label=f"tool-{i}",
                timestamp=now,
            )
        )
    monitor.record(
        MonitoredEvent(
            event_type=MonitoredEventType.COST_INCURRED,
            label="run-cost",
            cost=usage.estimated_cost_usd + usage.tool_cost_usd,
            timestamp=now,
        )
    )
    # A contradicted claim is a genuine verification failure (the verifier found it
    # false); unresolved claims are coverage gaps, handled by uncertainty instead.
    for claim in outcome.claims:
        if claim.verification.status is AgentVerificationStatus.CONTRADICTED:
            monitor.record(
                MonitoredEvent(
                    event_type=MonitoredEventType.VERIFICATION_FAILURE,
                    label=f"contradicted-{claim.claim_id}",
                    timestamp=now,
                )
            )
    if usage.exhausted:
        # A run that could not finish within budget warrants review before release.
        monitor.record(
            MonitoredEvent(
                event_type=MonitoredEventType.POLICY_VIOLATION,
                label=f"budget_exhausted:{usage.exhausted_reason or 'unknown'}",
                timestamp=now,
            )
        )
    return monitor


class AgentRunCertificate(StrixModel):
    """A content-addressed, signable attestation of one governed agent run."""

    certificate_id: str
    run_id: str
    question: str
    answer_digest: str
    verified_claim_ids: tuple[str, ...]
    gateway_outcome: str
    issued_at: AwareDatetime


@dataclass(frozen=True)
class GovernedAgentOutcome:
    """A research-agent outcome wrapped in the six-pillar assurance envelope."""

    outcome: ResearchOutcome
    gateway_decision: GatewayDecision
    uncertainty: UncertaintyAssessment
    monitor_finding: MonitorFinding
    audit_event_ids: tuple[str, ...]
    certificate: AgentRunCertificate
    answer_released: bool
    signature: Signature | None = None
    keyring: Keyring | None = None


def _derive_admission(outcome: ResearchOutcome) -> AdmissionDecision:
    """Surface the agent verifier's verdict as the gateway's evidence signal."""
    verified = outcome.answer.verified_claims
    if verified:
        return AdmissionDecision(
            outcome=AdmissionOutcome.ADMITTED,
            verification_outcome=VerificationOutcome.VERIFIED,
            predicate_results=(),
            policy_version=_BRIDGE_POLICY_VERSION,
            claim_id=verified[0].claim_id,
        )
    return AdmissionDecision(
        outcome=AdmissionOutcome.ABSTAINED,
        verification_outcome=VerificationOutcome.INSUFFICIENT_EVIDENCE,
        predicate_results=(),
        policy_version=_BRIDGE_POLICY_VERSION,
        claim_id="none",
    )


def _derive_uncertainty(
    outcome: ResearchOutcome, authorization: AuthorizationDecision | None
) -> UncertaintyAssessment:
    """Derive ordinal uncertainty from the agent's verified-vs-unresolved coverage."""
    verified = outcome.answer.verified_claims
    unresolved = outcome.answer.unresolved_claims
    all_ids = frozenset(c.claim_id for c in (*verified, *unresolved))
    admitted_ids = frozenset(c.claim_id for c in verified)
    contradictions = sum(
        1
        for c in outcome.claims
        if c.verification.status is AgentVerificationStatus.CONTRADICTED
    )
    return assess_uncertainty(
        total_requirements=len(all_ids),
        admitted_requirement_ids=admitted_ids,
        required_requirement_ids=all_ids,
        contradiction_count=contradictions,
        max_evidence_age_seconds=None,
        freshness_limit_seconds=None,
        has_confidence_interval=False,
        authorization_status=authorization.decision if authorization is not None else "n/a",
    )


def govern_agent_outcome(
    outcome: ResearchOutcome,
    *,
    now: datetime,
    ledger: EventLedger | None = None,
    monitor: BehaviorMonitor | None = None,
    monitor_policy: MonitorPolicy | None = None,
    authorization: AuthorizationDecision | None = None,
    signing_key: bytes | None = None,
    signing_key_record: VerifyingKeyRecord | None = None,
) -> GovernedAgentOutcome:
    """Apply the six-pillar assurance envelope to a completed agent outcome.

    ``ledger`` defaults to a hash-chained ledger INSIDE the run directory
    (``<run_dir>/audit``), so a reused ``run_id`` can never merge with a stale
    top-level chain and concurrent runs never share one ledger. ``monitor``
    defaults to an independent monitor seeded from the run's real behavioral
    signals (see :func:`_seed_monitor_from_outcome`).
    """
    run_id = outcome.run_id
    if ledger is None:
        ledger = EventLedger(outcome.run_dir / "audit")
    event_ids: list[str] = []

    def emit(event_type: EventType, label: str, idempotency_key: str) -> None:
        record = ledger.append(
            EventDraft(
                research_run_id=run_id,
                correlation_id=run_id,
                event_type=event_type,
                event_timestamp=now,
                actor="agent_governance",
                payload={"label": label},
                idempotency_key=idempotency_key,
            )
        )
        event_ids.append(record.event_id)

    emit(EventType.RESEARCH_REQUESTED, outcome.answer.question, "research-requested")

    if monitor is not None:
        active_monitor = monitor
    else:
        active_monitor = _seed_monitor_from_outcome(
            outcome, monitor_policy or DEFAULT_AGENT_MONITOR_POLICY, now
        )
    monitor_finding = active_monitor.assess()
    admission = _derive_admission(outcome)
    uncertainty = _derive_uncertainty(outcome, authorization)

    for claim in outcome.answer.verified_claims:
        emit(EventType.CLAIM_VERIFIED, claim.claim_id, f"claim-{claim.claim_id}")
    emit(EventType.ANSWER_SYNTHESIZED, run_id, "answer-synthesized")

    gateway_decision = evaluate_gateway(
        admission=admission,
        uncertainty=uncertainty,
        monitor_finding=monitor_finding,
        authorization=authorization,
    )

    verified_claim_ids = tuple(c.claim_id for c in outcome.answer.verified_claims)
    answer_digest = canonical_hash(
        {"summary": outcome.answer.summary, "verified_claim_ids": list(verified_claim_ids)}
    )
    cert_fields = {
        "run_id": run_id,
        "question": outcome.answer.question,
        "answer_digest": answer_digest,
        "verified_claim_ids": list(verified_claim_ids),
        "gateway_outcome": gateway_decision.outcome.value,
        "issued_at": now,
    }
    certificate = AgentRunCertificate(
        certificate_id=make_id("AGC", cert_fields),
        run_id=run_id,
        question=outcome.answer.question,
        answer_digest=answer_digest,
        verified_claim_ids=verified_claim_ids,
        gateway_outcome=gateway_decision.outcome.value,
        issued_at=now,
    )

    signature: Signature | None = None
    keyring: Keyring | None = None
    if signing_key is not None and signing_key_record is not None:
        keyring = Keyring()
        keyring.register(signing_key_record)
        signature = sign_certificate(
            certificate,
            signing_key,
            signing_key_record,
            domain=AGENT_RUN_SIGNING_DOMAIN,
            signed_at=now,
        )

    terminal = (
        EventType.RESEARCH_TERMINATED
        if gateway_decision.outcome is GatewayOutcome.REJECTED
        else EventType.RESEARCH_COMPLETED
    )
    emit(terminal, gateway_decision.outcome.value, "terminal")

    return GovernedAgentOutcome(
        outcome=outcome,
        gateway_decision=gateway_decision,
        uncertainty=uncertainty,
        monitor_finding=monitor_finding,
        audit_event_ids=tuple(event_ids),
        certificate=certificate,
        answer_released=gateway_decision.outcome in _RELEASED,
        signature=signature,
        keyring=keyring,
    )
