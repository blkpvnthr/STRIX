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
from strix.agent.models import (
    AgentClaim,
    AgentEvidence,
    AgentVerificationStatus,
    EpistemicClass,
    ObservationSeries,
    ResearchResponse,
)
from strix.agent.verifier import verify_claims
from strix.canonical import canonical_hash
from strix.errors import ReplayError
from strix.run_store import RunStore

#: Epistemic classes permitted in each response bucket (classification integrity).
_SUPPORTING_CLASSES = frozenset(
    {EpistemicClass.VERIFIED_FACT, EpistemicClass.ATTRIBUTED_REPORT}
)
_INFERENCE_CLASSES = frozenset(
    {EpistemicClass.ANALYTICAL_INFERENCE, EpistemicClass.FORECAST}
)


@dataclass(frozen=True)
class ClaimReplay:
    claim_id: str
    stored_status: str
    recomputed_status: str
    stored_value: str | None
    recomputed_value: str | None
    matches: bool


@dataclass(frozen=True)
class ResponseReplay:
    """Validation of the persisted conversational response (spec §13)."""

    present: bool
    hash_matches: bool
    citation_integrity: bool
    classification_integrity: bool
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return (not self.present) or (
            self.hash_matches and self.citation_integrity and self.classification_integrity
        )


@dataclass(frozen=True)
class AgentReplayOutcome:
    run_id: str
    passed: bool
    claims: tuple[ClaimReplay, ...]
    response: ResponseReplay | None = None


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
        stored_dec = original.verification.computed_value
        new_dec = replayed.verification.computed_value
        # Compare values NUMERICALLY, not as strings: canonical persistence strips
        # trailing zeros (-0.107510 -> -0.10751), which is numerically identical.
        values_match = stored_dec == new_dec
        results.append(
            ClaimReplay(
                claim_id=original.claim_id,
                stored_status=stored_status,
                recomputed_status=new_status,
                stored_value=_value(original),
                recomputed_value=_value(replayed),
                matches=(stored_status == new_status and values_match),
            )
        )
    response_replay = _replay_response(
        run_id, store, manifest, collector, recomputed
    )

    claims_pass = all(r.matches for r in results)
    return AgentReplayOutcome(
        run_id=run_id,
        passed=claims_pass and response_replay.ok,
        claims=tuple(results),
        response=response_replay,
    )


def _replay_response(
    run_id: str,
    store: RunStore,
    manifest: dict[str, object],
    collector: EvidenceCollector,
    recomputed: tuple[AgentClaim, ...],
) -> ResponseReplay:
    """Validate the persisted response's integrity against the re-verified claims."""
    try:
        data = store.load_json(run_id, "response.json")
    except Exception:
        return ResponseReplay(
            present=False,
            hash_matches=True,
            citation_integrity=True,
            classification_integrity=True,
            problems=(),
        )

    problems: list[str] = []
    try:
        response = ResearchResponse(**data)
    except (TypeError, ValueError) as exc:
        raise ReplayError(f"run {run_id} has a malformed response.json: {exc}") from exc

    # 1. Hash integrity — reconstruct the model and re-hash as persistence did.
    stored_hash = manifest.get("response_hash")
    recomputed_hash = canonical_hash(response.model_dump())
    hash_matches = stored_hash == recomputed_hash
    if not hash_matches:
        problems.append("response_hash does not match the persisted response")

    # 2. Citation integrity — every referenced evidence id resolves; supporting
    #    facts map to a re-verified VERIFIED claim with the same recomputed value.
    verified_now = {
        c.claim_id: c
        for c in recomputed
        if c.verification.status is AgentVerificationStatus.VERIFIED
    }
    citation_ok = True
    for ev in response.sources:
        if collector.evidence(ev.evidence_id) is None:
            citation_ok = False
            problems.append(f"source {ev.evidence_id} does not resolve to preserved evidence")
    for fact in response.supporting_facts:
        for eid in fact.evidence_ids:
            if collector.evidence(eid) is None:
                citation_ok = False
                problems.append(f"supporting fact {fact.claim_id} cites unresolved {eid}")
        claim = verified_now.get(fact.claim_id)
        if claim is None:
            citation_ok = False
            problems.append(
                f"supporting fact {fact.claim_id} is not a re-verified VERIFIED claim"
            )
        elif fact.computed_value is not None and (
            fact.computed_value != claim.verification.computed_value
        ):
            citation_ok = False
            problems.append(
                f"supporting fact {fact.claim_id} value diverges from recomputation"
            )

    # 3. Classification integrity — epistemic buckets never collapse into verdicts.
    class_ok = True
    for fact in response.supporting_facts:
        if fact.epistemic_class not in _SUPPORTING_CLASSES:
            class_ok = False
            problems.append(f"supporting fact {fact.claim_id} has non-factual class")
    for inf in response.analytical_inferences:
        if inf.epistemic_class not in _INFERENCE_CLASSES:
            class_ok = False
            problems.append(f"inference {inf.inference_id} is not an inference/forecast class")
        for cid in inf.supporting_claim_ids:
            if cid not in verified_now:
                class_ok = False
                problems.append(f"inference {inf.inference_id} cites unknown claim {cid}")
    for fact in response.unresolved_findings:
        if fact.epistemic_class is not EpistemicClass.UNRESOLVED:
            class_ok = False
            problems.append(f"unresolved finding {fact.claim_id} is misclassified")

    return ResponseReplay(
        present=True,
        hash_matches=hash_matches,
        citation_integrity=citation_ok,
        classification_integrity=class_ok,
        problems=tuple(problems),
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
