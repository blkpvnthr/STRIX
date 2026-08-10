"""Deterministic replay of a preserved engineering run.

Replay reconstructs EVERYTHING from the preserved raw bytes and the
preserved project manifest via the exact compute path used by the original
run. Stored facts/evidence/candidates/verification/export/metrics are never
reused as fresh computation - they serve only the integrity leg of the
three-way comparison (manifest hash vs stored-artifact hash vs recomputed
hash).

Anchor-drift reporting: for stored facts with fingerprinted anchors, a
location that resolves to different content (or content found at a different
location) is called out explicitly - never silently accepted as equivalent
evidence. Parser-version deltas between the stored run and the current
adapters are appended to mismatch details.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from strix.canonical import canonical_hash, sha256_hex
from strix.engineering.adapters import parser_versions
from strix.engineering.manifest import MANIFEST_NAME
from strix.engineering.metrics import compute_metrics, load_expected_model
from strix.engineering.models import (
    AnchoredFact,
    CandidateElement,
    CandidateRelationship,
    CompileMetrics,
    EngineeringEvidence,
    EngineeringRunManifest,
    EngineeringVerification,
    TextRangeAnchor,
    XmlPathAnchor,
)
from strix.engineering.pipeline import (
    ModelOutcome,
    candidates_hash,
    compute_model,
    evidence_hash,
    facts_hash,
    metrics_hash,
    verification_hash,
)
from strix.errors import ReplayError, StrixError
from strix.replay import ReplayOutcome, ReplayStage
from strix.run_store import RunStore

#: Fixed timestamp for replay verification results; ``checked_at`` is
#: excluded from every deterministic hash.
_REPLAY_CHECKED_AT = datetime(2000, 1, 1, tzinfo=UTC)

_FACTS_ADAPTER = TypeAdapter(list[AnchoredFact])
_EVIDENCE_ADAPTER = TypeAdapter(list[EngineeringEvidence])
_ELEMENTS_ADAPTER = TypeAdapter(list[CandidateElement])
_RELATIONSHIPS_ADAPTER = TypeAdapter(list[CandidateRelationship])


def replay_engineering_run(run_id: str, state_dir: Path) -> ReplayOutcome:
    """Replay one preserved engineering run and compare stage by stage."""
    store = RunStore(state_dir)
    store.run_dir(run_id)

    try:
        manifest = EngineeringRunManifest.model_validate(store.load_json(run_id, "manifest.json"))
    except ValidationError as exc:
        raise ReplayError(f"run {run_id} has an unreadable manifest: {exc}") from exc

    stages: list[ReplayStage] = []

    # -- preserved raw bytes (analysis + evaluation) ------------------------
    raws: dict[str, bytes] = {}
    raw_mismatches: list[str] = []
    for name, expected_hash in sorted(
        {**manifest.analysis_source_hashes, **manifest.evaluation_source_hashes}.items()
    ):
        data = store.read_raw(run_id, name)
        raws[name] = data
        if sha256_hex(data) != expected_hash:
            kind = "evaluation" if name in manifest.evaluation_source_hashes else "analysis"
            raw_mismatches.append(f"{name} ({kind})")
    stages.append(
        ReplayStage(
            "Source artifacts hash",
            not raw_mismatches,
            "" if not raw_mismatches else f"preserved bytes differ: {raw_mismatches}",
        )
    )

    # -- recompute the deterministic core from preserved bytes --------------
    outcome: ModelOutcome | None = None
    recompute_error = ""
    manifest_raw = raws.get(MANIFEST_NAME, b"")
    source_raws = {
        name: data
        for name, data in raws.items()
        if name in manifest.analysis_source_hashes and name != MANIFEST_NAME
    }
    try:
        outcome = compute_model(
            project_id=manifest.project_id,
            as_of_date=manifest.as_of_date,
            manifest_raw=manifest_raw,
            source_raws=source_raws,
            checked_at=_REPLAY_CHECKED_AT,
        )
    except StrixError as exc:
        recompute_error = f"recompute failed: {exc}"

    version_note = _parser_version_note(manifest)

    def recomputed(stage_key: str) -> str | None:
        return outcome.hashes[stage_key] if outcome is not None else None

    input_ok = outcome is not None and outcome.hashes["input"] == manifest.input_hash
    stages.append(
        ReplayStage(
            "Input hash",
            input_ok,
            "" if input_ok else (recompute_error or "spec or sources differ"),
        )
    )

    stored_facts = _stored_hash(
        store, run_id, "facts.json", lambda p: facts_hash(tuple(_FACTS_ADAPTER.validate_python(p)))
    )
    stages.append(
        _stage(
            "Anchored facts hash",
            manifest.facts_hash,
            stored_facts,
            recomputed("facts"),
            recompute_error,
            extra=_anchor_drift_detail(store, run_id, outcome) + version_note,
        )
    )

    stages.append(
        _stage(
            "Evidence hash",
            manifest.evidence_hash,
            _stored_hash(
                store,
                run_id,
                "evidence.json",
                lambda p: evidence_hash(tuple(_EVIDENCE_ADAPTER.validate_python(p))),
            ),
            recomputed("evidence"),
            recompute_error,
            extra=version_note,
        )
    )

    def stored_candidates_hash(payload: Any) -> str:
        if not isinstance(payload, dict):
            raise ReplayError("candidates.json is not an object")
        return candidates_hash(
            tuple(_ELEMENTS_ADAPTER.validate_python(payload.get("elements", []))),
            tuple(_RELATIONSHIPS_ADAPTER.validate_python(payload.get("relationships", []))),
        )

    stages.append(
        _stage(
            "Candidates hash",
            manifest.candidates_hash,
            _stored_hash(store, run_id, "candidates.json", stored_candidates_hash),
            recomputed("candidates"),
            recompute_error,
        )
    )

    stored_verification = _stored_hash(
        store,
        run_id,
        "verification.json",
        lambda p: verification_hash(EngineeringVerification.model_validate(p)),
    )
    verification_ok = (
        outcome is not None
        and stored_verification == manifest.verification_hash
        and outcome.hashes["verification"] == manifest.verification_hash
        and outcome.verification.status == manifest.final_status
    )
    stages.append(
        ReplayStage(
            "Verification status",
            verification_ok,
            "" if verification_ok else (recompute_error or "verification outcome differs"),
        )
    )

    model_ok = outcome is not None and outcome.hashes["model"] == manifest.model_hash
    stages.append(
        ReplayStage(
            "Model hash",
            model_ok,
            "" if model_ok else (recompute_error or "recomputed model differs"),
        )
    )

    stages.append(
        _stage(
            "Export hash",
            manifest.export_hash,
            _stored_hash(store, run_id, "model.json", canonical_hash),
            recomputed("export"),
            recompute_error,
        )
    )

    stages.append(_metrics_stage(store, run_id, manifest, raws, outcome, recompute_error))

    return ReplayOutcome(run_id=run_id, stages=tuple(stages))


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _stage(
    name: str,
    expected: str,
    stored: str | None,
    recomputed: str | None,
    recompute_error: str,
    extra: str = "",
) -> ReplayStage:
    if stored is None:
        return ReplayStage(name, False, "stored artifact unreadable" + extra)
    if stored != expected:
        return ReplayStage(name, False, "stored artifact differs from manifest" + extra)
    if recomputed is None:
        return ReplayStage(name, False, (recompute_error or "recompute unavailable") + extra)
    if recomputed != expected:
        return ReplayStage(name, False, "recomputed hash differs from manifest" + extra)
    return ReplayStage(name, True)


def _stored_hash(store: RunStore, run_id: str, artifact_name: str, hash_fn: Any) -> str | None:
    try:
        payload = store.load_json(run_id, artifact_name)
        result = hash_fn(payload)
        return str(result)
    except (StrixError, ValidationError, ReplayError, TypeError):
        return None


def _parser_version_note(manifest: EngineeringRunManifest) -> str:
    current = parser_versions()
    deltas = [
        f"{fmt}: {stored} -> {current.get(fmt, 'absent')}"
        for fmt, stored in sorted(manifest.parser_versions.items())
        if current.get(fmt) != stored
    ]
    return f" [parser versions changed: {', '.join(deltas)}]" if deltas else ""


def _anchor_drift_detail(store: RunStore, run_id: str, outcome: ModelOutcome | None) -> str:
    """Explicit anchor-drift reporting for fingerprinted anchors.

    Compares the stored facts' fingerprinted anchors (location -> content
    fingerprint) with the recomputed ones. A location resolving to different
    content, or content found at a different location, is named explicitly.
    """
    if outcome is None:
        return ""
    try:
        payload = store.load_json(run_id, "facts.json")
        stored_facts = tuple(_FACTS_ADAPTER.validate_python(payload))
    except (StrixError, ValidationError):
        return ""

    def fingerprint_map(
        facts: tuple[AnchoredFact, ...],
    ) -> dict[tuple[str, str], str]:
        mapping: dict[tuple[str, str], str] = {}
        for fact in facts:
            anchor = fact.anchor
            if isinstance(anchor, XmlPathAnchor):
                mapping[("xpath", anchor.xpath)] = anchor.element_fingerprint
            elif isinstance(anchor, TextRangeAnchor):
                location = f"lines={anchor.start_line}-{anchor.end_line}"
                mapping[("text", location)] = anchor.paragraph_hash
        return mapping

    stored_map = fingerprint_map(stored_facts)
    recomputed_map = fingerprint_map(outcome.facts)
    drifts: list[str] = []
    for key, stored_fp in sorted(stored_map.items()):
        new_fp = recomputed_map.get(key)
        if new_fp is None:
            drifts.append(f"{key[1]} no longer resolves")
        elif new_fp != stored_fp:
            drifts.append(f"{key[1]} resolves to different content")
    for key in sorted(recomputed_map):
        if key not in stored_map:
            drifts.append(f"{key[1]} is new content at this location")
    if not drifts:
        return ""
    return f" [anchor drift: {'; '.join(drifts[:4])}]"


def _metrics_stage(
    store: RunStore,
    run_id: str,
    manifest: EngineeringRunManifest,
    raws: dict[str, bytes],
    outcome: ModelOutcome | None,
    recompute_error: str,
) -> ReplayStage:
    stored = _stored_hash(
        store,
        run_id,
        "metrics.json",
        lambda p: metrics_hash(CompileMetrics.model_validate(p)),
    )
    recomputed: str | None = None
    if outcome is not None:
        try:
            expected = None
            evaluation_names = sorted(manifest.evaluation_source_hashes)
            if evaluation_names:
                expected = load_expected_model(raws[evaluation_names[0]])
            recomputed = metrics_hash(
                compute_metrics(
                    model=outcome.model,
                    elements=outcome.elements,
                    relationships=outcome.relationships,
                    verification=outcome.verification,
                    resolvable_verified=outcome.resolvable_verified,
                    expected=expected,
                )
            )
        except StrixError as exc:
            recompute_error = recompute_error or f"metrics recompute failed: {exc}"
    return _stage("Metrics hash", manifest.metrics_hash, stored, recomputed, recompute_error)
