"""Tests for the assurance inspector (decision-traceability made inspectable).

The inspector independently RE-VERIFIES a governed run — its audit hash chain and
its certificate signatures — and summarizes the gateway decision, so a governed
result can be audited after the fact rather than trusted on its word.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from strix.answering.models import make_answer_requirement
from strix.answering.synthesize import AdmittedFinding
from strix.assurance.inspector import inspect_governed_result, render_assurance_report
from strix.assurance.lifecycle import GovernedResearchResult, run_governed_research
from strix.assurance.monitoring import (
    BehaviorMonitor,
    MonitoredEvent,
    MonitoredEventType,
    MonitorPolicy,
)
from strix.assurance.signing import generate_keypair
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
from strix.evidence_graph.predicates import admit
from strix.models import SourceArtifact, SourceType
from strix.native.backends.python_reference import PythonReferenceBackend

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
HEX64 = "a" * 64
_ALL = (
    PredicateName.INTEGRITY, PredicateName.TYPE_TEMPORAL, PredicateName.PROVENANCE,
    PredicateName.DERIVATION, PredicateName.SUPPORT,
)
QUESTION = "What was ACME's revenue growth?"


def _finding(value: Decimal) -> AdmittedFinding:
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
        version="insp-pol-1", mandatory_predicates=_ALL, temporal_mode=TemporalMode.RETROSPECTIVE,
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
        verifier_version="insp-verifier-1", computation_certificate_refs=(),
        verified_value=value, measurement_unit="ratio", numerical_tolerance=Decimal("0.0001"),
        issued_at=NOW,
    )
    return AdmittedFinding(claim=claim, decision=decision, certificate=cert)


def _monitor(events: list[MonitoredEvent]) -> BehaviorMonitor:
    monitor = BehaviorMonitor(
        MonitorPolicy(max_tool_calls=100, max_identical_calls=5, max_cost=Decimal("1.0"),
                      max_verification_failures=3)
    )
    for e in events:
        monitor.record(e)
    return monitor


def _run(tmp_path: Path, run_id: str, events: list[MonitoredEvent], *, sign: bool) -> tuple[
    GovernedResearchResult, EventLedger, AdmittedFinding
]:
    finding = _finding(Decimal("0.25"))
    ledger = EventLedger(tmp_path)
    kwargs = {}
    if sign:
        priv, record = generate_keypair(created_at=NOW)
        kwargs = {"signing_key": priv, "signing_key_record": record}
    result = run_governed_research(
        question=QUESTION, requirements=(make_answer_requirement(
            text=QUESTION, weight=Decimal("1"), subject_id="ACME", metric="revenue_growth"),),
        findings=(finding,), monitor=_monitor(events), ledger=ledger, run_id=run_id, now=NOW,
        **kwargs,  # type: ignore[arg-type]
    )
    return result, ledger, finding


def test_inspect_authorized_run_verifies_chain_and_signatures(tmp_path: Path) -> None:
    result, ledger, finding = _run(tmp_path, "RUN-INS-1", [], sign=True)
    report = inspect_governed_result(
        result, ledger, "RUN-INS-1", signed_certificates=(finding.certificate,)
    )
    assert report.gateway_outcome == "authorized"
    assert report.answer_released is True
    assert report.audit_chain_verified is True
    assert report.audit_chain_issue_count == 0
    assert report.audit_event_count >= 2
    assert report.signatures_present == 1
    assert report.signatures_verified is True


def test_inspect_rejected_run_reports_not_released_but_chain_ok(tmp_path: Path) -> None:
    events = [MonitoredEvent(event_type=MonitoredEventType.UNAUTHORIZED_OPERATION,
                             label="rogue", timestamp=NOW)]
    result, ledger, _ = _run(tmp_path, "RUN-INS-2", events, sign=False)
    report = inspect_governed_result(result, ledger, "RUN-INS-2")
    assert report.gateway_outcome == "rejected"
    assert report.answer_released is False
    assert report.audit_chain_verified is True


def test_signatures_not_checked_when_no_certificates_supplied(tmp_path: Path) -> None:
    result, ledger, _ = _run(tmp_path, "RUN-INS-3", [], sign=True)
    report = inspect_governed_result(result, ledger, "RUN-INS-3")
    assert report.signatures_present == 1
    assert report.signatures_verified is None  # present but not independently checked


def test_signature_reverification_catches_wrong_certificate(tmp_path: Path) -> None:
    result, ledger, _ = _run(tmp_path, "RUN-INS-4", [], sign=True)
    # Supply a DIFFERENT certificate than the one signed → re-verification fails.
    other = _finding(Decimal("0.99")).certificate
    report = inspect_governed_result(
        result, ledger, "RUN-INS-4", signed_certificates=(other,)
    )
    assert report.signatures_verified is False


def test_inspector_detects_tampered_audit_chain(tmp_path: Path) -> None:
    result, ledger, _ = _run(tmp_path, "RUN-INS-5", [], sign=False)
    # Corrupt the on-disk ledger so the hash chain no longer verifies.
    path = ledger.ledger_path("RUN-INS-5")
    data = path.read_text().splitlines()
    data[0] = data[0].replace("research_requested", "tampered_type", 1)
    path.write_text("\n".join(data) + "\n")
    report = inspect_governed_result(result, ledger, "RUN-INS-5")
    assert report.audit_chain_verified is False
    assert report.audit_chain_issue_count >= 1


def test_render_report_is_human_readable(tmp_path: Path) -> None:
    result, ledger, finding = _run(tmp_path, "RUN-INS-6", [], sign=True)
    report = inspect_governed_result(
        result, ledger, "RUN-INS-6", signed_certificates=(finding.certificate,)
    )
    text = render_assurance_report(report)
    assert "RUN-INS-6" in text
    assert "authorized" in text.lower()
    assert "chain" in text.lower()
