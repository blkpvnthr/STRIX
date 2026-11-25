"""Regression tests for adversarial-review findings on the Wave-4 governed envelope.

1. MAJOR — the behavior-monitoring pillar was structurally inert (permissive
   monitor, no events). It must now be SEEDED from the run's real signals so budget
   exhaustion, cost overruns, and verification-failure accumulation independently
   drive the gateway away from release.
2. MINOR — the audit ledger defaulted to a shared top-level dir, so a reused run_id
   could merge with a stale chain. It now defaults INSIDE the run directory.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from strix.agent.budget import BudgetSnapshot
from strix.agent.contracts import TokenUsage
from strix.agent.governed import govern_agent_outcome
from strix.agent.models import (
    AgentClaim,
    AgentClaimType,
    AgentVerificationStatus,
    ClaimVerification,
    ResearchAnswer,
)
from strix.agent.orchestrator import ResearchOutcome
from strix.assurance.gateway import GatewayOutcome
from strix.audit.ledger import EventLedger

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
RUN_ID = "RUN-20261125-050"


def _claim(cid: str, status: AgentVerificationStatus) -> AgentClaim:
    return AgentClaim(
        claim_id=cid, claim_type=AgentClaimType.QUANTITATIVE, statement=f"c{cid}",
        evidence_ids=("EV-1",), verification=ClaimVerification(status=status),
    )


def _outcome(
    run_dir: Path, *, verified: int = 1, contradicted: int = 0,
    tool_calls: int = 2, cost: str = "0.01", exhausted: bool = False,
) -> ResearchOutcome:
    v = tuple(_claim(f"v{i}", AgentVerificationStatus.VERIFIED) for i in range(verified))
    c = tuple(_claim(f"c{i}", AgentVerificationStatus.CONTRADICTED) for i in range(contradicted))
    answer = ResearchAnswer(
        run_id=RUN_ID, question="q", data_as_of=None, summary="S.", verified_claims=v,
        unresolved_claims=(), evidence=(), limitations=(), disclaimer="x",
    )
    usage = BudgetSnapshot(
        model_calls=1, tool_calls=tool_calls, usage=TokenUsage(),
        estimated_cost_usd=Decimal(cost), tool_cost_usd=Decimal("0"), pricing_version="v1",
        elapsed_seconds=Decimal("1"), exhausted=exhausted,
        exhausted_reason="tool budget exhausted" if exhausted else None,
    )
    return ResearchOutcome(
        answer=answer, run_id=RUN_ID, run_dir=run_dir, usage=usage, claims=(*v, *c))


# --- Finding 1: the monitor pillar is now live -----------------------------


def test_healthy_run_still_authorized(tmp_path: Path) -> None:
    governed = govern_agent_outcome(_outcome(tmp_path), now=NOW)
    assert governed.gateway_decision.outcome is GatewayOutcome.AUTHORIZED
    assert governed.answer_released is True


def test_budget_exhausted_run_is_not_released(tmp_path: Path) -> None:
    governed = govern_agent_outcome(_outcome(tmp_path, exhausted=True), now=NOW)
    assert governed.gateway_decision.outcome is not GatewayOutcome.AUTHORIZED
    assert governed.answer_released is False
    assert governed.monitor_finding.intervention.value != "continue"


def test_cost_overrun_is_rejected(tmp_path: Path) -> None:
    governed = govern_agent_outcome(_outcome(tmp_path, cost="500"), now=NOW)
    assert governed.gateway_decision.outcome is GatewayOutcome.REJECTED
    assert governed.answer_released is False


def test_excess_verification_failures_block_release(tmp_path: Path) -> None:
    governed = govern_agent_outcome(_outcome(tmp_path, verified=1, contradicted=20), now=NOW)
    assert governed.answer_released is False
    assert governed.monitor_finding.verification_failures == 20


def test_many_tool_calls_do_not_false_trigger_loop(tmp_path: Path) -> None:
    # Distinct tool-invocation labels must not be mistaken for an identical-call loop.
    governed = govern_agent_outcome(_outcome(tmp_path, tool_calls=50), now=NOW)
    assert governed.gateway_decision.outcome is GatewayOutcome.AUTHORIZED


# --- Finding 2: ledger defaults inside the run directory --------------------


def test_ledger_defaults_to_run_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    governed = govern_agent_outcome(_outcome(run_dir), now=NOW)
    # Events are written under <run_dir>/audit, not a shared top-level dir.
    in_run = EventLedger(run_dir / "audit")
    assert in_run.verify_chain(RUN_ID).ok
    assert in_run.verify_chain(RUN_ID).event_count >= 3
    assert not (tmp_path / "audit").exists()
    assert len(governed.audit_event_ids) >= 3
