"""Wave 4: governed envelope over the research-agent outcome.

Applies the independent six-pillar gateway + hash-chained audit + signed run
certificate over a :class:`ResearchOutcome`, deriving the gateway inputs from the
agent's own verification results. The agent's answer is only released when the
independent gateway authorizes it — a second, independent final authorization on
top of the agent's fail-closed validation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from strix.agent.budget import BudgetSnapshot
from strix.agent.contracts import TokenUsage
from strix.agent.governed import (
    AGENT_RUN_SIGNING_DOMAIN,
    AgentRunCertificate,
    govern_agent_outcome,
)
from strix.agent.models import (
    AgentClaim,
    AgentClaimType,
    AgentVerificationStatus,
    ClaimVerification,
    ResearchAnswer,
)
from strix.agent.orchestrator import ResearchOutcome
from strix.assurance.gateway import GatewayOutcome
from strix.assurance.monitoring import (
    BehaviorMonitor,
    MonitoredEvent,
    MonitoredEventType,
    MonitorPolicy,
)
from strix.assurance.signing import generate_keypair, verify_signature
from strix.audit.ledger import EventLedger

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
RUN_ID = "RUN-20261125-001"


def _claim(cid: str, *, verified: bool) -> AgentClaim:
    status = (
        AgentVerificationStatus.VERIFIED
        if verified
        else AgentVerificationStatus.INSUFFICIENT_EVIDENCE
    )
    return AgentClaim(
        claim_id=cid,
        claim_type=AgentClaimType.QUANTITATIVE,
        statement=f"claim {cid}",
        evidence_ids=("EV-1",),
        verification=ClaimVerification(status=status),
    )


def _outcome(*, verified: int, unresolved: int) -> ResearchOutcome:
    v = tuple(_claim(f"CL-v{i}", verified=True) for i in range(verified))
    u = tuple(_claim(f"CL-u{i}", verified=False) for i in range(unresolved))
    answer = ResearchAnswer(
        run_id=RUN_ID, question="What was ACME's revenue growth?", data_as_of=NOW,
        summary="ACME grew.", verified_claims=v, unresolved_claims=u, evidence=(),
        limitations=(), disclaimer="synthetic",
    )
    usage = BudgetSnapshot(
        model_calls=1, tool_calls=2, usage=TokenUsage(), estimated_cost_usd=Decimal("0.01"),
        tool_cost_usd=Decimal("0"), pricing_version="v1", elapsed_seconds=Decimal("1"),
        exhausted=False, exhausted_reason=None,
    )
    return ResearchOutcome(
        answer=answer, run_id=RUN_ID, run_dir=Path("/tmp/none"), usage=usage, claims=(*v, *u),
    )


def test_fully_verified_run_is_authorized_and_audited(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    governed = govern_agent_outcome(_outcome(verified=2, unresolved=0), ledger=ledger, now=NOW)
    assert governed.gateway_decision.outcome is GatewayOutcome.AUTHORIZED
    assert governed.answer_released is True
    assert len(governed.audit_event_ids) >= 4  # requested + 2 claims + synth + terminal
    assert ledger.verify_chain(RUN_ID).ok


def test_partial_coverage_is_qualified_but_released(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    governed = govern_agent_outcome(_outcome(verified=1, unresolved=2), ledger=ledger, now=NOW)
    assert governed.gateway_decision.outcome is GatewayOutcome.QUALIFIED
    assert governed.answer_released is True


def test_no_verified_claims_abstains_and_not_released(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    governed = govern_agent_outcome(_outcome(verified=0, unresolved=2), ledger=ledger, now=NOW)
    assert governed.gateway_decision.outcome is GatewayOutcome.ABSTAIN
    assert governed.answer_released is False
    assert ledger.verify_chain(RUN_ID).ok


def test_rejected_conclusion_verdict_drives_gateway_rejection(tmp_path: Path) -> None:
    # Step 7: the REAL conclusion-level DTEC verdict is the gateway's evidence signal. Even with
    # verified claims present, a REJECTED conclusion (e.g. a recompute-contradicted run) must
    # drive the gateway to reject and withhold the answer.
    from strix.agent.models import ConclusionVerification

    base = _outcome(verified=2, unresolved=0)
    answer = base.answer.model_copy(
        update={
            "conclusion_verification": ConclusionVerification(
                outcome="rejected", reason_codes=("recompute_contradicted_evidence",)
            )
        }
    )
    outcome = base.__class__(
        answer=answer, run_id=base.run_id, run_dir=base.run_dir, usage=base.usage,
        claims=base.claims,
    )
    governed = govern_agent_outcome(outcome, ledger=EventLedger(tmp_path), now=NOW)
    assert governed.gateway_decision.outcome is GatewayOutcome.REJECTED
    assert governed.answer_released is False


def test_monitor_termination_forces_rejected(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    monitor = BehaviorMonitor(MonitorPolicy(
        max_tool_calls=100, max_identical_calls=5, max_cost=Decimal("1"),
        max_verification_failures=3))
    monitor.record(MonitoredEvent(
        event_type=MonitoredEventType.UNAUTHORIZED_OPERATION, label="rogue", timestamp=NOW))
    governed = govern_agent_outcome(
        _outcome(verified=2, unresolved=0), ledger=ledger, now=NOW, monitor=monitor)
    assert governed.gateway_decision.outcome is GatewayOutcome.REJECTED
    assert governed.answer_released is False
    assert ledger.verify_chain(RUN_ID).ok


def test_run_certificate_is_signed_and_verifies(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    priv, record = generate_keypair(created_at=NOW)
    governed = govern_agent_outcome(
        _outcome(verified=2, unresolved=0), ledger=ledger, now=NOW,
        signing_key=priv, signing_key_record=record)
    assert isinstance(governed.certificate, AgentRunCertificate)
    assert governed.signature is not None and governed.keyring is not None
    assert verify_signature(
        governed.certificate, governed.signature, governed.keyring,
        expected_domain=AGENT_RUN_SIGNING_DOMAIN)
    # A different run's certificate would have a different content id.
    assert governed.certificate.certificate_id.startswith("AGC-")
    assert governed.certificate.verified_claim_ids == ("CL-v0", "CL-v1")


def test_certificate_id_is_deterministic(tmp_path: Path) -> None:
    g1 = govern_agent_outcome(
        _outcome(verified=1, unresolved=0), ledger=EventLedger(tmp_path / "a"), now=NOW)
    g2 = govern_agent_outcome(
        _outcome(verified=1, unresolved=0), ledger=EventLedger(tmp_path / "b"), now=NOW)
    assert g1.certificate.certificate_id == g2.certificate.certificate_id
