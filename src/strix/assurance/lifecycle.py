"""The governed research lifecycle (R2-A, R1 §4).

Composes the six assurance pillars into one governed execution:

    request -> pre-execution authorization (behavior monitor) -> governed answer
    synthesis from admitted findings -> uncertainty assessment -> final gateway
    authorization -> cryptographic claim signing -> persistent audit record.

The gateway's outcome governs whether the answer is released; the autonomous
agent cannot override it (R1 §2). This layer operates over already-admitted
findings — the seam at which a live research agent supplies collected, verified
evidence — so it is fully offline-testable; wiring the live OpenAI agent's
evidence collection into ``findings`` is the remaining integration step.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from strix.answering.models import AnswerRequirement, VerifiedResearchResponse
from strix.answering.pipeline import answer_question
from strix.answering.synthesize import AdmittedFinding
from strix.assurance.authorization import AuthorizationDecision
from strix.assurance.gateway import GatewayDecision, GatewayOutcome, evaluate_gateway
from strix.assurance.monitoring import BehaviorMonitor, MonitorFinding
from strix.assurance.signing import Keyring, Signature, VerifyingKeyRecord, sign_certificate
from strix.assurance.uncertainty import UncertaintyAssessment, assess_uncertainty
from strix.audit.events import EventDraft, EventType
from strix.audit.ledger import EventLedger
from strix.evidence_graph.nodes import AdmissionOutcome, VerificationOutcome
from strix.evidence_graph.predicates import AdmissionDecision

#: Signature domain for claim certificates (domain-separated, R2-E).
CLAIM_SIGNING_DOMAIN = "strix.claim"


@dataclass(frozen=True)
class GovernedResearchResult:
    """The outcome of one governed research lifecycle."""

    question: str
    response: VerifiedResearchResponse
    gateway_decision: GatewayDecision
    uncertainty: UncertaintyAssessment
    monitor_finding: MonitorFinding
    audit_event_ids: tuple[str, ...]
    signatures: tuple[Signature, ...] = ()
    keyring: Keyring | None = None


def run_governed_research(
    *,
    question: str,
    requirements: tuple[AnswerRequirement, ...],
    findings: tuple[AdmittedFinding, ...],
    monitor: BehaviorMonitor,
    ledger: EventLedger,
    run_id: str,
    now: datetime,
    required_requirement_ids: frozenset[str] | None = None,
    max_evidence_age_seconds: int | None = None,
    freshness_limit_seconds: int | None = None,
    authorization: AuthorizationDecision | None = None,
    signing_key: bytes | None = None,
    signing_key_record: VerifyingKeyRecord | None = None,
) -> GovernedResearchResult:
    """Run the governed lifecycle and return its audited, gated result."""
    event_ids: list[str] = []

    def emit(event_type: EventType, label: str, idempotency_key: str) -> None:
        record = ledger.append(
            EventDraft(
                research_run_id=run_id,
                correlation_id=run_id,
                event_type=event_type,
                event_timestamp=now,
                actor="governed_lifecycle",
                payload={"label": label},
                idempotency_key=idempotency_key,
            )
        )
        event_ids.append(record.event_id)

    emit(EventType.RESEARCH_REQUESTED, question, "research-requested")

    # Pre-execution authorization signal: the independent monitor's standing.
    monitor_finding = monitor.assess()

    # Governed execution: synthesize the answer from admitted findings ONLY.
    response = answer_question(question, requirements, findings)
    for finding in findings:
        if finding.is_usable():
            emit(
                EventType.CLAIM_VERIFIED,
                finding.certificate.certificate_id,
                f"claim-{finding.certificate.certificate_id}",
            )
    emit(EventType.ANSWER_SYNTHESIZED, response.answer_status.value, "answer-synthesized")
    emit(
        EventType.ANSWER_VALIDATED,
        "ok" if response.validation.ok else "unsupported",
        "answer-validated",
    )

    # Uncertainty (ordinal, never a fabricated probability).
    requirement_ids = frozenset(r.requirement_id for r in requirements)
    admitted_requirement_ids = frozenset(
        coverage.requirement_id
        for coverage in response.coverage.per_requirement
        if coverage.satisfied
    )
    uncertainty = assess_uncertainty(
        total_requirements=len(requirements),
        admitted_requirement_ids=admitted_requirement_ids,
        required_requirement_ids=required_requirement_ids or requirement_ids,
        contradiction_count=0,
        max_evidence_age_seconds=max_evidence_age_seconds,
        freshness_limit_seconds=freshness_limit_seconds,
        has_confidence_interval=False,
        authorization_status=authorization.decision if authorization is not None else "n/a",
    )

    # Final authorization through the six-pillar gateway.
    admitted = [finding for finding in findings if finding.is_usable()]
    if admitted:
        admission: AdmissionDecision = admitted[0].decision
    else:
        admission = AdmissionDecision(
            outcome=AdmissionOutcome.ABSTAINED,
            verification_outcome=VerificationOutcome.INSUFFICIENT_EVIDENCE,
            predicate_results=(),
            policy_version="governed-lifecycle",
            claim_id="none",
        )
    gateway_decision = evaluate_gateway(
        admission=admission,
        uncertainty=uncertainty,
        monitor_finding=monitor_finding,
        authorization=authorization,
    )

    # Cryptographically sign the admitted claim certificates, if a key is given.
    signatures: tuple[Signature, ...] = ()
    keyring: Keyring | None = None
    if signing_key is not None and signing_key_record is not None:
        keyring = Keyring()
        keyring.register(signing_key_record)
        signatures = tuple(
            sign_certificate(
                finding.certificate,
                signing_key,
                signing_key_record,
                domain=CLAIM_SIGNING_DOMAIN,
                signed_at=now,
            )
            for finding in admitted
        )

    terminal = (
        EventType.RESEARCH_TERMINATED
        if gateway_decision.outcome is GatewayOutcome.REJECTED
        else EventType.RESEARCH_COMPLETED
    )
    emit(terminal, gateway_decision.outcome.value, "terminal")

    return GovernedResearchResult(
        question=question,
        response=response,
        gateway_decision=gateway_decision,
        uncertainty=uncertainty,
        monitor_finding=monitor_finding,
        audit_event_ids=tuple(event_ids),
        signatures=signatures,
        keyring=keyring,
    )
