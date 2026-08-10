"""Engineering compilation orchestration.

:func:`compute_model` is the deterministic core: a pure function of the
preserved project-manifest bytes, the preserved declared source bytes, and
the compilation parameters. Replay calls exactly the same function, so a
replayed run recomputes the model the way the original run did. Evaluation
inputs (ground truth) are NOT part of this core - they are consumed only by
the metrics step.

:func:`compile_project` adds acquisition (reading the input directory) and
atomic persistence around the core.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from strix.canonical import canonical_hash, sha256_hex
from strix.engineering import ENGINEERING_PIPELINE_VERSION
from strix.engineering.adapters import adapter_for, parser_versions, schema_versions
from strix.engineering.builder import DeterministicModelBuilder
from strix.engineering.evidence import build_evidence
from strix.engineering.export import build_export, export_hash
from strix.engineering.manifest import (
    MANIFEST_NAME,
    enforce_v2_policy,
    load_project_manifest,
)
from strix.engineering.metrics import compute_metrics, load_expected_model
from strix.engineering.models import (
    AnchoredFact,
    CandidateElement,
    CandidateRelationship,
    CompileMetrics,
    CompileResult,
    EngineeringArtifact,
    EngineeringEvidence,
    EngineeringProjectManifest,
    EngineeringRunManifest,
    EngineeringSpec,
    EngineeringVerification,
    FailureRef,
    RejectedCandidate,
    VerifiedModel,
)
from strix.engineering.verifier import rejected_summary, verify_model
from strix.errors import EngineeringSourceError
from strix.pipeline import Clock, SystemClock
from strix.run_store import RunStore

#: Progress labels, in order, for the CLI ([n/7] display).
PROGRESS_LABELS = (
    "Validating project manifest",
    "Preserving source artifacts",
    "Anchoring engineering facts",
    "Building typed evidence",
    "Proposing candidate model",
    "Verifying candidates",
    "Exporting verified model",
)

StepFn = Callable[[str], None]


# --------------------------------------------------------------------------
# Deterministic core
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelOutcome:
    """Everything reproducible about a compilation (no run ID, no wall clock,
    no evaluation inputs)."""

    spec: EngineeringSpec
    project: EngineeringProjectManifest
    artifacts: tuple[EngineeringArtifact, ...]
    facts: tuple[AnchoredFact, ...]
    evidence: tuple[EngineeringEvidence, ...]
    elements: tuple[CandidateElement, ...]
    relationships: tuple[CandidateRelationship, ...]
    verification: EngineeringVerification
    model: VerifiedModel
    export: dict[str, Any]
    analysis_source_hashes: dict[str, str]
    resolvable_verified: int
    hashes: dict[str, str]


def compute_model(
    *,
    project_id: str,
    as_of_date: date,
    manifest_raw: bytes,
    source_raws: Mapping[str, bytes],
    checked_at: datetime,
    step: StepFn | None = None,
) -> ModelOutcome:
    """Run the deterministic engineering pipeline over preserved bytes."""

    def emit(label: str) -> None:
        if step is not None:
            step(label)

    project = load_project_manifest(manifest_raw)
    enforce_v2_policy(project)
    if project.project_id != project_id:
        raise EngineeringSourceError(
            f"manifest declares project {project.project_id!r}, command requested {project_id!r}"
        )
    declared = [source.file for source in project.sources]
    missing = [name for name in declared if name not in source_raws]
    if missing:
        raise EngineeringSourceError(f"declared source files missing from input: {missing}")
    extra = [name for name in source_raws if name not in declared]
    if extra:
        raise EngineeringSourceError(
            f"undeclared bytes supplied to the deterministic core: {sorted(extra)}"
        )

    analysis_source_hashes = {MANIFEST_NAME: sha256_hex(manifest_raw)}
    spec = EngineeringSpec(
        project_id=project.project_id,
        as_of_date=as_of_date,
        pipeline_version=ENGINEERING_PIPELINE_VERSION,
        manifest_hash=analysis_source_hashes[MANIFEST_NAME],
    )

    emit(PROGRESS_LABELS[2])
    artifacts: list[EngineeringArtifact] = []
    facts: list[AnchoredFact] = []
    sources_by_artifact: dict[str, Any] = {}
    for entry in project.sources:  # manifest order is authoritative
        raw = source_raws[entry.file]
        analysis_source_hashes[entry.file] = sha256_hex(raw)
        result = adapter_for(entry.format).parse(entry, raw)
        artifacts.append(result.artifact)
        facts.extend(result.facts)
        sources_by_artifact[result.artifact.artifact_id] = entry

    emit(PROGRESS_LABELS[3])
    evidence = build_evidence(tuple(facts), sources_by_artifact)

    emit(PROGRESS_LABELS[4])
    elements, relationships = DeterministicModelBuilder().propose(spec, evidence)

    emit(PROGRESS_LABELS[5])
    verification, verified_elements, verified_relationships = verify_model(
        spec=spec,
        artifacts=tuple(artifacts),
        facts=tuple(facts),
        evidence=evidence,
        elements=elements,
        relationships=relationships,
        checked_at=checked_at,
    )

    model = _build_verified_model(spec, verification, verified_elements, verified_relationships)

    emit(PROGRESS_LABELS[6])
    export = build_export(
        spec=spec,
        project=project,
        model=model,
        evidence=evidence,
        facts=tuple(facts),
        artifacts=tuple(artifacts),
        parser_versions=parser_versions(),
        schema_versions=schema_versions(),
        analysis_source_hashes=analysis_source_hashes,
    )

    resolvable = _resolvable_verified(model, evidence, tuple(facts), tuple(artifacts))

    hashes = {
        "input": canonical_hash({"spec": spec, "analysis_source_hashes": analysis_source_hashes}),
        "facts": facts_hash(tuple(facts)),
        "evidence": evidence_hash(evidence),
        "candidates": candidates_hash(verified_elements, verified_relationships),
        "verification": verification_hash(verification),
        "model": model_hash(model),
        "export": export_hash(export),
    }
    return ModelOutcome(
        spec=spec,
        project=project,
        artifacts=tuple(artifacts),
        facts=tuple(facts),
        evidence=evidence,
        elements=verified_elements,
        relationships=verified_relationships,
        verification=verification,
        model=model,
        export=export,
        analysis_source_hashes=analysis_source_hashes,
        resolvable_verified=resolvable,
        hashes=hashes,
    )


def _build_verified_model(
    spec: EngineeringSpec,
    verification: EngineeringVerification,
    elements: tuple[CandidateElement, ...],
    relationships: tuple[CandidateRelationship, ...],
) -> VerifiedModel:
    """Verified content only; quarantined candidates kept first-class."""
    from strix.engineering.models import CandidateStatus

    rejected: list[RejectedCandidate] = []
    for element in elements:
        if element.status is CandidateStatus.REJECTED:
            rejected.append(
                _rejected_candidate(element.element_id, "element", element, verification)
            )
    for relationship in relationships:
        if relationship.status is CandidateStatus.REJECTED:
            rejected.append(
                _rejected_candidate(
                    relationship.relationship_id, "relationship", relationship, verification
                )
            )
    return VerifiedModel(
        project_id=spec.project_id,
        as_of_date=spec.as_of_date,
        elements=tuple(e for e in elements if e.status is CandidateStatus.VERIFIED),
        relationships=tuple(r for r in relationships if r.status is CandidateStatus.VERIFIED),
        rejected=tuple(sorted(rejected, key=lambda r: r.candidate_id)),
    )


def _rejected_candidate(
    candidate_id: str,
    kind: str,
    candidate: CandidateElement | CandidateRelationship,
    verification: EngineeringVerification,
) -> RejectedCandidate:
    own = tuple(f for f in verification.failures if f.candidate_id == candidate_id)
    rule, summary = rejected_summary(candidate_id, verification.failures)
    anchors: list[str] = []
    conflicting: list[str] = []
    for failure in own:
        for anchor in failure.anchors:
            if anchor not in anchors:
                anchors.append(anchor)
        for ref in failure.conflicting_refs:
            if ref not in conflicting:
                conflicting.append(ref)
    assert kind in ("element", "relationship")
    return RejectedCandidate(
        candidate_id=candidate_id,
        kind=kind,
        summary=summary,
        failures=tuple(FailureRef(code=f.code, message=f.message) for f in own),
        evidence_ids=candidate.evidence_ids,
        anchors=tuple(anchors),
        conflicting_refs=tuple(conflicting),
        rule=rule,
    )


def _resolvable_verified(
    model: VerifiedModel,
    evidence: tuple[EngineeringEvidence, ...],
    facts: tuple[AnchoredFact, ...],
    artifacts: tuple[EngineeringArtifact, ...],
) -> int:
    """How many verified items have fully resolvable citation chains."""
    evidence_by_id = {e.evidence_id: e for e in evidence}
    facts_by_id = {f.fact_id: f for f in facts}
    artifact_ids = {a.artifact_id for a in artifacts}
    count = 0
    items: list[CandidateElement | CandidateRelationship] = [
        *model.elements,
        *model.relationships,
    ]
    for item in items:
        ok = True
        for evidence_id in item.evidence_ids:
            cited = evidence_by_id.get(evidence_id)
            if cited is None:
                ok = False
                break
            for fact_id in cited.source_fact_ids:
                fact = facts_by_id.get(fact_id)
                if fact is None or fact.artifact_id not in artifact_ids:
                    ok = False
                    break
            if not ok:
                break
        if ok:
            count += 1
    return count


# --------------------------------------------------------------------------
# Stage hashes (the exact content replay compares)
# --------------------------------------------------------------------------
#
# Excluded from all stage hashes and replay comparison: run_id, created_at,
# checked_at (wall clock), model-report.txt, and every evaluation input.
# Included: known_at (content-derived) and everything else.


def facts_hash(facts: tuple[AnchoredFact, ...]) -> str:
    return canonical_hash(sorted(facts, key=lambda f: f.fact_id))


def evidence_hash(evidence: tuple[EngineeringEvidence, ...]) -> str:
    return canonical_hash(sorted(evidence, key=lambda e: e.evidence_id))


def candidates_hash(
    elements: tuple[CandidateElement, ...],
    relationships: tuple[CandidateRelationship, ...],
) -> str:
    return canonical_hash(
        {
            "elements": sorted(elements, key=lambda e: e.element_id),
            "relationships": sorted(relationships, key=lambda r: r.relationship_id),
        }
    )


def verification_hash(verification: EngineeringVerification) -> str:
    return canonical_hash(verification.model_dump(exclude={"checked_at"}))


def model_hash(model: VerifiedModel) -> str:
    return canonical_hash(model)


def metrics_hash(metrics: CompileMetrics) -> str:
    return canonical_hash(metrics)


# --------------------------------------------------------------------------
# Full compilation
# --------------------------------------------------------------------------


def compile_project(
    input_dir: Path,
    *,
    project_id: str,
    as_of_date: date,
    state_dir: Path,
    clock: Clock | None = None,
    step: StepFn | None = None,
    on_ignored: Callable[[str], None] | None = None,
) -> CompileResult:
    """Compile one input directory into a persisted, replayable run."""
    clock = clock or SystemClock()

    def emit(label: str) -> None:
        if step is not None:
            step(label)

    emit(PROGRESS_LABELS[0])
    if not input_dir.is_dir():
        raise EngineeringSourceError(f"input directory {input_dir} does not exist")
    manifest_path = input_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise EngineeringSourceError(f"input directory {input_dir} has no {MANIFEST_NAME}")
    manifest_raw = manifest_path.read_bytes()
    project = load_project_manifest(manifest_raw)
    enforce_v2_policy(project)

    emit(PROGRESS_LABELS[1])
    declared = {source.file for source in project.sources}
    expected_names = declared | {MANIFEST_NAME}
    if project.ground_truth is not None:
        expected_names.add(project.ground_truth)
    for entry in sorted(p.name for p in input_dir.iterdir()):
        if entry not in expected_names and on_ignored is not None:
            on_ignored(entry)

    source_raws: dict[str, bytes] = {}
    for source in project.sources:
        path = input_dir / source.file
        if not path.is_file():
            raise EngineeringSourceError(
                f"declared source file {source.file!r} is missing from {input_dir}"
            )
        source_raws[source.file] = path.read_bytes()

    evaluation_raws: dict[str, bytes] = {}
    if project.ground_truth is not None:
        ground_truth_path = input_dir / project.ground_truth
        if not ground_truth_path.is_file():
            raise EngineeringSourceError(
                f"declared ground_truth file {project.ground_truth!r} is missing"
            )
        evaluation_raws[project.ground_truth] = ground_truth_path.read_bytes()

    outcome = compute_model(
        project_id=project_id,
        as_of_date=as_of_date,
        manifest_raw=manifest_raw,
        source_raws=source_raws,
        checked_at=clock.now(),
        step=step,
    )

    # Evaluation step: ground truth is read ONLY here, after the model and
    # export are fully built.
    expected = None
    if evaluation_raws:
        expected = load_expected_model(next(iter(evaluation_raws.values())))
    metrics = compute_metrics(
        model=outcome.model,
        elements=outcome.elements,
        relationships=outcome.relationships,
        verification=outcome.verification,
        resolvable_verified=outcome.resolvable_verified,
        expected=expected,
    )

    evaluation_source_hashes = {name: sha256_hex(raw) for name, raw in evaluation_raws.items()}
    created_at = clock.now()

    manifest_template: dict[str, Any] = {
        "created_at": created_at,
        "mode": "engineering",
        "pipeline_version": ENGINEERING_PIPELINE_VERSION,
        "parser_versions": parser_versions(),
        "schema_versions": schema_versions(),
        "project_id": outcome.spec.project_id,
        "as_of_date": outcome.spec.as_of_date,
        "analysis_source_hashes": outcome.analysis_source_hashes,
        "evaluation_source_hashes": evaluation_source_hashes,
        "input_hash": outcome.hashes["input"],
        "facts_hash": outcome.hashes["facts"],
        "evidence_hash": outcome.hashes["evidence"],
        "candidates_hash": outcome.hashes["candidates"],
        "verification_hash": outcome.hashes["verification"],
        "model_hash": outcome.hashes["model"],
        "export_hash": outcome.hashes["export"],
        "metrics_hash": metrics_hash(metrics),
        "final_status": outcome.verification.status,
    }

    from strix.canonical import pretty_json_bytes
    from strix.engineering.render import report_text

    store = RunStore(state_dir)
    committed: dict[str, EngineeringRunManifest] = {}
    result_holder: dict[str, CompileResult] = {}

    def finalize(run_id: str) -> tuple[Mapping[str, bytes], bytes]:
        run_manifest = EngineeringRunManifest(run_id=run_id, **manifest_template)
        committed["manifest"] = run_manifest
        partial = CompileResult(
            spec=outcome.spec,
            project=outcome.project,
            artifacts=outcome.artifacts,
            facts=outcome.facts,
            evidence=outcome.evidence,
            elements=outcome.elements,
            relationships=outcome.relationships,
            verification=outcome.verification,
            model=outcome.model,
            metrics=metrics,
            export=outcome.export,
            run_manifest=run_manifest,
            run_directory=state_dir / run_id,
        )
        result_holder["result"] = partial
        return (
            {"model-report.txt": report_text(partial).encode("utf-8")},
            pretty_json_bytes(run_manifest),
        )

    _run_id, run_directory = store.persist_generic(
        json_artifacts={
            "spec.json": outcome.spec,
            "artifacts.json": outcome.artifacts,
            "facts.json": outcome.facts,
            "evidence.json": outcome.evidence,
            "candidates.json": {
                "elements": outcome.elements,
                "relationships": outcome.relationships,
            },
            "verification.json": outcome.verification,
            "model.json": outcome.export,
            "metrics.json": metrics,
        },
        raw_files={
            MANIFEST_NAME: manifest_raw,
            **source_raws,
            **evaluation_raws,
        },
        finalize=finalize,
        today=created_at.date(),
    )
    result = result_holder["result"]
    if result.run_directory != run_directory:  # collision retry moved the id
        result = result.model_copy(
            update={
                "run_manifest": committed["manifest"],
                "run_directory": run_directory,
            }
        )
    return result
