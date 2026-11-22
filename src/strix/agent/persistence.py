"""Persist an agent research run atomically and replayably.

Reuses :meth:`strix.run_store.RunStore.persist_generic` (the same crash-safe
staging + atomic-rename protocol the rest of STRIX uses). Preserved source
artifacts are written byte-exact under ``raw/`` with hash re-verification;
``manifest.json`` is written last and carries a ``mode`` of ``agent_research``
so the existing replay dispatcher routes it correctly.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from strix.agent import AGENT_INSTRUCTION_VERSION, AGENT_VERSION
from strix.agent.budget import BudgetSnapshot
from strix.agent.calculations import CALC_VERSION
from strix.agent.config import AgentConfig
from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import AgentClaim, AgentVerificationStatus, ResearchAnswer
from strix.agent.response_builder import render_answer
from strix.agent.verifier import VERIFIER_VERSION
from strix.canonical import canonical_hash, pretty_json_bytes
from strix.run_store import RunStore


def persist_agent_run(
    state_dir: Path,
    *,
    question: str,
    as_of: str,
    config: AgentConfig,
    collector: EvidenceCollector,
    claims: tuple[AgentClaim, ...],
    make_answer: Callable[[str], ResearchAnswer],
    usage: BudgetSnapshot,
    now: datetime,
) -> tuple[str, Path, ResearchAnswer]:
    """Write a complete agent run; return (run_id, run_dir, finalized answer)."""
    evidence_dumps = [e.model_dump() for e in collector.all_evidence()]
    series_dumps = [s.model_dump() for s in collector.all_series()]
    claim_dumps = [c.model_dump() for c in claims]

    json_artifacts = {
        "question.json": {
            "question": question,
            "as_of": as_of,
            "model": config.model,
            "agent_version": AGENT_VERSION,
            "instruction_version": AGENT_INSTRUCTION_VERSION,
        },
        "config.json": config.redacted(),
        "evidence.json": evidence_dumps,
        "series.json": series_dumps,
        "claims.json": claim_dumps,
        "usage.json": usage.model_dump(),
    }
    raw_files = {
        f"{content_hash}.bin": raw for content_hash, raw in collector.all_artifacts().items()
    }

    finalized: dict[str, ResearchAnswer] = {}

    def finalize(run_id: str) -> tuple[dict[str, bytes], bytes]:
        answer = make_answer(run_id)
        finalized["answer"] = answer
        verified_ids = [
            c.claim_id
            for c in claims
            if c.verification.status is AgentVerificationStatus.VERIFIED
        ]
        manifest = {
            "mode": "agent_research",
            "run_id": run_id,
            "created_at": now.isoformat(),
            "model": config.model,
            "pricing_version": config.pricing.pricing_version,
            "instruction_version": AGENT_INSTRUCTION_VERSION,
            "verifier_version": VERIFIER_VERSION,
            "calculation_version": CALC_VERSION,
            "evidence_hash": canonical_hash(evidence_dumps),
            "series_hash": canonical_hash(series_dumps),
            "claims_hash": canonical_hash(claim_dumps),
            "verified_claim_ids": verified_ids,
            "verified_count": len(verified_ids),
            "usage": usage.model_dump(),
        }
        per_run = {
            "answer.json": pretty_json_bytes(answer.model_dump()),
            "answer.txt": render_answer(answer).encode("utf-8"),
        }
        return per_run, pretty_json_bytes(manifest)

    store = RunStore(state_dir)
    run_id, run_dir = store.persist_generic(
        json_artifacts=json_artifacts,
        raw_files=raw_files,
        finalize=finalize,
        today=now.date(),
    )
    return run_id, run_dir, finalized["answer"]
