"""Deterministic replay of a preserved research run.

Replay re-executes the pipeline from a run's preserved inputs and checks two
independent properties per stage:

- **Integrity** — the artifacts stored in the run directory still hash to
  what the manifest recorded (detects tampering with stored files).
- **Reproducibility** — recomputing everything from the preserved spec and
  raw fixture yields the same deterministic hashes (detects nondeterminism
  or contract drift). Stored calculations are never reused as if they were
  newly computed.

Compared content: input hash (spec + raw SHA-256), facts, calculations,
evidence, and claims hashes, plus the verification hash and final status.
Excluded (execution-specific, documented in the manifest model): the run ID,
``created_at``/``checked_at`` wall-clock timestamps, the run directory path,
and ``report.txt`` (it embeds the run ID). ``known_at`` timestamps come from
the fixture and ARE compared.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from strix.canonical import sha256_hex
from strix.errors import ReplayError, StrixError
from strix.models import (
    CalculationResult,
    Claim,
    Evidence,
    ResearchSpec,
    RunManifest,
    SourceFact,
    VerificationResult,
)
from strix.pipeline import (
    DeterministicOutcome,
    calculations_hash,
    claims_hash,
    compute,
    evidence_hash,
    facts_hash,
    verification_hash,
)
from strix.reasoning.base import Reasoner
from strix.reasoning.deterministic_demo import DeterministicDemoReasoner
from strix.run_store import RunStore

_ModelT = TypeVar("_ModelT", bound=BaseModel)

#: Fixed timestamp for replay verification results; ``checked_at`` is
#: excluded from every deterministic hash, so any value works. Using a
#: constant keeps replay itself fully deterministic.
_REPLAY_CHECKED_AT = datetime(2000, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class ReplayStage:
    """One compared stage: matched only if stored and recomputed agree."""

    name: str
    matched: bool
    detail: str = ""


@dataclass(frozen=True)
class ReplayOutcome:
    run_id: str
    stages: tuple[ReplayStage, ...]

    @property
    def passed(self) -> bool:
        return all(stage.matched for stage in self.stages)


def replay_run(
    run_id: str,
    state_dir: Path,
    *,
    reasoner: Reasoner | None = None,
) -> ReplayOutcome:
    """Replay one preserved run and compare it stage by stage."""
    store = RunStore(state_dir)
    store.run_dir(run_id)  # validates format, containment, existence

    try:
        manifest = RunManifest.model_validate(store.load_json(run_id, "manifest.json"))
        spec = ResearchSpec.model_validate(store.load_json(run_id, "spec.json"))
    except ValidationError as exc:
        raise ReplayError(f"run {run_id} has an unreadable manifest or spec: {exc}") from exc

    raw = store.read_raw(run_id, manifest.source_name)
    stages: list[ReplayStage] = []

    # -- integrity + reproducibility of the raw artifact -------------------
    stored_raw_hash = manifest.source_hashes.get(manifest.source_name, "")
    raw_hash = sha256_hex(raw)
    raw_ok = raw_hash == stored_raw_hash
    stages.append(
        ReplayStage(
            "Source artifact hash",
            raw_ok,
            "" if raw_ok else "preserved raw bytes differ from manifest",
        )
    )

    # -- recompute from preserved inputs ------------------------------------
    outcome: DeterministicOutcome | None = None
    recompute_error = ""
    try:
        outcome = compute(
            spec,
            raw,
            source_type=manifest.source_type,
            source_name=manifest.source_name,
            reasoner=reasoner or DeterministicDemoReasoner(),
            checked_at=_REPLAY_CHECKED_AT,
        )
    except StrixError as exc:
        recompute_error = f"recompute failed: {exc}"

    input_expected = manifest.input_hash
    if outcome is not None:
        input_ok = outcome.hashes["input"] == input_expected
        stages.append(
            ReplayStage(
                "Input hash",
                input_ok,
                "" if input_ok else "spec or raw fixture differs from original input",
            )
        )
    else:
        stages.append(ReplayStage("Input hash", False, recompute_error))

    stages.append(
        _stage(
            "Source facts hash",
            manifest.facts_hash,
            _stored_stage_hash(store, run_id, "facts.json", SourceFact, facts_hash),
            outcome.hashes["facts"] if outcome else None,
            recompute_error,
        )
    )
    stages.append(
        _stage(
            "Calculations hash",
            manifest.calculations_hash,
            _stored_stage_hash(
                store, run_id, "calculations.json", CalculationResult, calculations_hash
            ),
            outcome.hashes["calculations"] if outcome else None,
            recompute_error,
        )
    )
    stages.append(
        _stage(
            "Evidence hash",
            manifest.evidence_hash,
            _stored_stage_hash(store, run_id, "evidence.json", Evidence, evidence_hash),
            outcome.hashes["evidence"] if outcome else None,
            recompute_error,
        )
    )
    stages.append(
        _stage(
            "Claims hash",
            manifest.claims_hash,
            _stored_stage_hash(store, run_id, "claims.json", Claim, claims_hash),
            outcome.hashes["claims"] if outcome else None,
            recompute_error,
        )
    )

    stored_verification_hash: str | None
    try:
        stored_verification = VerificationResult.model_validate(
            store.load_json(run_id, "verification.json")
        )
        stored_verification_hash = verification_hash(stored_verification)
    except (StrixError, ValidationError):
        stored_verification_hash = None
    verification_matched = (
        outcome is not None
        and stored_verification_hash == manifest.verification_hash
        and outcome.hashes["verification"] == manifest.verification_hash
        and outcome.verification.status == manifest.final_status
    )
    stages.append(
        ReplayStage(
            "Verification status",
            verification_matched,
            "" if verification_matched else recompute_error or "verification outcome differs",
        )
    )

    return ReplayOutcome(run_id=run_id, stages=tuple(stages))


def _stage(
    name: str,
    expected: str,
    stored: str | None,
    recomputed: str | None,
    recompute_error: str,
) -> ReplayStage:
    """Combine the integrity and reproducibility checks for one stage."""
    if stored is None:
        return ReplayStage(name, False, "stored artifact unreadable")
    if stored != expected:
        return ReplayStage(name, False, "stored artifact differs from manifest")
    if recomputed is None:
        return ReplayStage(name, False, recompute_error or "recompute unavailable")
    if recomputed != expected:
        return ReplayStage(name, False, "recomputed hash differs from manifest")
    return ReplayStage(name, True)


def _stored_stage_hash(
    store: RunStore,
    run_id: str,
    artifact_name: str,
    model_type: type[_ModelT],
    hash_fn: Callable[[tuple[_ModelT, ...]], str],
) -> str | None:
    """Hash the models currently stored in a run artifact, or None if unreadable."""
    try:
        payload = store.load_json(run_id, artifact_name)
        items = tuple(model_type.model_validate(item) for item in payload)
        return hash_fn(items)
    except (StrixError, ValidationError, TypeError):
        return None
