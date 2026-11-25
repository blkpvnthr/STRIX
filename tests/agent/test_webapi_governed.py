"""Wave 4: the web research service applies the governed assurance envelope.

Every completed research job carries an independent six-pillar gateway verdict
(``assurance``) alongside the answer, and the answer/response payload is preserved
for transparency. The assurance block is the authoritative release signal.
"""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from tests.agent.agent_fixtures import build_config

from strix.agent.budget import BudgetSnapshot
from strix.agent.contracts import TokenUsage
from strix.agent.models import (
    AgentClaim,
    AgentClaimType,
    AgentVerificationStatus,
    ClaimVerification,
    ResearchAnswer,
)
from strix.agent.orchestrator import ResearchOutcome
from strix.webapi.service import Job, ResearchService


def _usage() -> BudgetSnapshot:
    return BudgetSnapshot(
        model_calls=1, tool_calls=1, usage=TokenUsage(), estimated_cost_usd=Decimal("0.01"),
        tool_cost_usd=Decimal("0"), pricing_version="v1", elapsed_seconds=Decimal("1"),
        exhausted=False, exhausted_reason=None,
    )


def _outcome(run_dir: Path, *, verified: int) -> ResearchOutcome:
    claims = tuple(
        AgentClaim(
            claim_id=f"CL-v{i}", claim_type=AgentClaimType.QUANTITATIVE,
            statement=f"c{i}", evidence_ids=("EV-1",),
            verification=ClaimVerification(status=AgentVerificationStatus.VERIFIED),
        )
        for i in range(verified)
    )
    answer = ResearchAnswer(
        run_id="RUN-20261125-010", question="q", data_as_of=None, summary="S.",
        verified_claims=claims, unresolved_claims=(), evidence=(), limitations=(),
        disclaimer="x",
    )
    return ResearchOutcome(
        answer=answer, run_id="RUN-20261125-010", run_dir=run_dir, usage=_usage(), claims=claims,
    )


def _poll(service: ResearchService, rid: str) -> Job:
    for _ in range(200):
        job = service.get(rid)
        if job is not None and job.status in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def _service(tmp_path: Path, *, verified: int) -> ResearchService:
    def runner(question: str, **kwargs: Any) -> ResearchOutcome:
        return _outcome(tmp_path, verified=verified)

    return ResearchService(tmp_path, config_loader=lambda: build_config(), runner=runner)


def test_verified_run_is_authorized_and_released(tmp_path: Path) -> None:
    service = _service(tmp_path, verified=2)
    job = service.submit("q")
    done = _poll(service, job.id)
    assert done.status == "completed"
    assert done.result is not None
    assurance = done.result["assurance"]
    assert assurance["gateway_outcome"] == "authorized"
    assert assurance["answer_released"] is True
    assert assurance["certificate_id"].startswith("AGC-")
    assert len(assurance["audit_event_ids"]) >= 3
    # Answer payload is preserved for transparency.
    assert done.result["answer"]["summary"] == "S."


def test_unverified_run_abstains_but_payload_preserved(tmp_path: Path) -> None:
    service = _service(tmp_path, verified=0)
    job = service.submit("q")
    done = _poll(service, job.id)
    assert done.status == "completed"
    assert done.result is not None
    assurance = done.result["assurance"]
    assert assurance["gateway_outcome"] == "abstain"
    assert assurance["answer_released"] is False
    # The answer is still serialized (transparency), but not marked released.
    assert done.result["answer"]["summary"] == "S."


def test_audit_chain_is_persisted_and_verifiable(tmp_path: Path) -> None:
    from strix.audit.ledger import EventLedger

    service = _service(tmp_path, verified=1)
    job = service.submit("q")
    done = _poll(service, job.id)
    assert done.result is not None
    ledger = EventLedger(tmp_path / "audit")
    chain = ledger.verify_chain("RUN-20261125-010")
    assert chain.ok
    assert chain.event_count >= 3  # requested + claim + synth + terminal
