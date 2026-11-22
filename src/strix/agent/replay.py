"""Deterministic replay of a persisted agent research run.

Replay reloads the preserved claims, evidence, and observation series from a run
directory and re-runs the independent verifier — recomputing every supported
calculation from the preserved observations with no model and no network. It
then compares the recomputed verdicts against the ones stored at research time.

Replay does not regenerate the model's stochastic wording; it proves the
*verifiable* content (numbers and verdicts) reproduces exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import AgentClaim, AgentEvidence, ObservationSeries
from strix.agent.verifier import verify_claims
from strix.errors import ReplayError
from strix.run_store import RunStore


@dataclass(frozen=True)
class ClaimReplay:
    claim_id: str
    stored_status: str
    recomputed_status: str
    stored_value: str | None
    recomputed_value: str | None
    matches: bool


@dataclass(frozen=True)
class AgentReplayOutcome:
    run_id: str
    passed: bool
    claims: tuple[ClaimReplay, ...]


def replay_agent_run(run_id: str, state_dir: Path) -> AgentReplayOutcome:
    """Reload a run and verify its claims reproduce the stored verdicts."""
    store = RunStore(state_dir)
    manifest = store.load_json(run_id, "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("mode") != "agent_research":
        raise ReplayError(f"run {run_id} is not an agent_research run")

    try:
        claims = tuple(AgentClaim(**c) for c in store.load_json(run_id, "claims.json"))
        evidence = [AgentEvidence(**e) for e in store.load_json(run_id, "evidence.json")]
        series = [ObservationSeries(**s) for s in store.load_json(run_id, "series.json")]
    except (TypeError, ValueError) as exc:
        raise ReplayError(f"run {run_id} has malformed agent artifacts: {exc}") from exc

    collector = EvidenceCollector()
    for ev in evidence:
        collector.put_evidence(ev)
    for s in series:
        collector.put_series(s)

    now = _created_at(manifest)
    recomputed = verify_claims(claims, collector, now=now)

    results: list[ClaimReplay] = []
    for original, replayed in zip(claims, recomputed, strict=True):
        stored_status = original.verification.status.value
        new_status = replayed.verification.status.value
        stored_value = _value(original)
        new_value = _value(replayed)
        results.append(
            ClaimReplay(
                claim_id=original.claim_id,
                stored_status=stored_status,
                recomputed_status=new_status,
                stored_value=stored_value,
                recomputed_value=new_value,
                matches=(stored_status == new_status and stored_value == new_value),
            )
        )
    return AgentReplayOutcome(
        run_id=run_id,
        passed=all(r.matches for r in results),
        claims=tuple(results),
    )


def _value(claim: AgentClaim) -> str | None:
    value = claim.verification.computed_value
    return str(value) if value is not None else None


def _created_at(manifest: dict[str, object]) -> datetime:
    raw = manifest.get("created_at")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    return datetime.now(UTC)
