"""R2-A governed research lifecycle (DoD §4): request -> pre-execution
authorization -> governed execution -> evidence admission -> claim certification
-> uncertainty -> answer synthesis -> final gateway authorization -> persistent
audit record, composing all six assurance pillars. Offline-testable over the
deterministic pipeline (the live-agent evidence-collection seam is `findings`)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from strix.answering.models import AnswerStatus, make_answer_requirement
from strix.answering.synthesize import AdmittedFinding
from strix.assurance.gateway import GatewayOutcome
from strix.assurance.lifecycle import GovernedResearchResult, run_governed_research
from strix.assurance.monitoring import (
    BehaviorMonitor,
    MonitoredEvent,
    MonitoredEventType,
    MonitorPolicy,
)
from strix.assurance.signing import generate_keypair, verify_signature
from strix.audit.ledger import EventLedger
from strix.canonical import canonical_hash
from strix.evidence_graph.certificates import build_claim_certificate
from strix.evidence_graph.graph import EvidenceGraph
from strix.evidence_graph.nodes import (
    Assertion,
    PredicateName,
    TemporalMode,
    make_candidate_claim,
    make_verification_policy,
)
from strix.evidence_graph.predicates import AdmissionOutcome, admit
from strix.models import SourceArtifact, SourceType
from strix.native.backends.python_reference import PythonReferenceBackend

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
HEX64 = "a" * 64
_ALL = (
    PredicateName.INTEGRITY, PredicateName.TYPE_TEMPORAL, PredicateName.PROVENANCE,
    PredicateName.DERIVATION, PredicateName.SUPPORT,
)
QUESTION = "What was ACME's revenue growth?"


def _finding(*, value: Decimal) -> AdmittedFinding:
    art = SourceArtifact(
        artifact_id="ART-rev", source_type=SourceType.SYNTHETIC_FIXTURE,
        source_name="revenue.json", source_version="v1", content_hash=HEX64,
        known_at=NOW, local_path="raw/revenue.json", byte_size=100,
    )
    comp = PythonReferenceBackend().run(
        "growth_rate", {"first": Decimal("100000000"), "last": Decimal("125000000")},
        input_artifact_refs=("ART-rev",),
    )
    g = EvidenceGraph()
    g.add_node(art)
    g.add_node(comp)
    claim = make_candidate_claim(
        subject_id="ACME", claim_type="revenue_growth", statement="ACME grew.",
        evidence_ids=(comp.computation_id,),
        assertions=(Assertion(metric="revenue_growth", asserted_value=value, unit="ratio",
                              evidence_id=comp.computation_id),),
    )
    policy = make_verification_policy(
        version="r2-pol-1", mandatory_predicates=_ALL, temporal_mode=TemporalMode.RETROSPECTIVE,
        absolute_tolerance=Decimal("0.0001"), relative_tolerance=Decimal("0.0001"),
    )
    decision = admit(g, claim, policy)
    cert = build_claim_certificate(
        claim_id=claim.candidate_claim_id, canonical_claim_digest=canonical_hash(claim),
        evidence_graph_snapshot_digest=g.graph_hash(),
        supporting_evidence_ids=(comp.computation_id,),
        dependency_closure=(comp.computation_id, "ART-rev"),
        predicate_results=decision.predicate_results,
        verification_policy_version=decision.policy_version,
        verifier_version="r2-verifier-1", computation_certificate_refs=(),
        verified_value=value, measurement_unit="ratio", numerical_tolerance=Decimal("0.0001"),
        issued_at=NOW,
    )
    return AdmittedFinding(claim=claim, decision=decision, certificate=cert)


def _requirement() -> object:
    return make_answer_requirement(
        text=QUESTION, weight=Decimal("1"), subject_id="ACME", metric="revenue_growth"
    )


def _monitor(events: list[MonitoredEvent]) -> BehaviorMonitor:
    policy = MonitorPolicy(
        max_tool_calls=100, max_identical_calls=5, max_cost=Decimal("1.0"),
        max_verification_failures=3,
    )
    monitor = BehaviorMonitor(policy)
    for e in events:
        monitor.record(e)
    return monitor


def test_governed_research_authorized_and_audited(tmp_path) -> None:  # type: ignore[no-untyped-def]
    finding = _finding(value=Decimal("0.25"))
    assert finding.decision.outcome is AdmissionOutcome.ADMITTED
    ledger = EventLedger(tmp_path)
    priv, key_record = generate_keypair(created_at=NOW)

    result = run_governed_research(
        question=QUESTION, requirements=(_requirement(),), findings=(finding,),  # type: ignore[arg-type]
        monitor=_monitor([]), ledger=ledger, run_id="RUN-GOV-1", now=NOW,
        signing_key=priv, signing_key_record=key_record,
    )
    assert isinstance(result, GovernedResearchResult)
    assert result.gateway_decision.outcome is GatewayOutcome.AUTHORIZED
    assert result.response.answer_status is AnswerStatus.COMPLETE_ANSWER
    assert "25" in result.response.answer_text
    # Persistent audit record exists and its hash chain verifies.
    assert len(result.audit_event_ids) >= 2
    assert ledger.verify_chain("RUN-GOV-1").ok
    # The claim certificate was cryptographically signed and the signature verifies.
    assert len(result.signatures) == 1
    assert verify_signature(
        finding.certificate, result.signatures[0], result.keyring, expected_domain="strix.claim",
    )


def test_governed_research_rejected_when_monitor_terminates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    finding = _finding(value=Decimal("0.25"))
    ledger = EventLedger(tmp_path)
    bad = [MonitoredEvent(event_type=MonitoredEventType.UNAUTHORIZED_OPERATION,
                          label="rogue tool", timestamp=NOW)]
    result = run_governed_research(
        question=QUESTION, requirements=(_requirement(),), findings=(finding,),  # type: ignore[arg-type]
        monitor=_monitor(bad), ledger=ledger, run_id="RUN-GOV-2", now=NOW,
    )
    # A monitor termination forces REJECTED regardless of a valid answer.
    assert result.gateway_decision.outcome is GatewayOutcome.REJECTED
    assert ledger.verify_chain("RUN-GOV-2").ok


def test_governed_research_abstains_without_admitted_findings(tmp_path) -> None:  # type: ignore[no-untyped-def]
    rejected = _finding(value=Decimal("0.99"))  # fabricated -> not admitted
    assert rejected.decision.outcome is AdmissionOutcome.REJECTED
    ledger = EventLedger(tmp_path)
    result = run_governed_research(
        question=QUESTION, requirements=(_requirement(),), findings=(rejected,),  # type: ignore[arg-type]
        monitor=_monitor([]), ledger=ledger, run_id="RUN-GOV-3", now=NOW,
    )
    assert result.gateway_decision.outcome is GatewayOutcome.ABSTAIN
    assert result.response.answer_status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert "99" not in result.response.answer_text
