"""Research pipeline orchestration.

``run_research`` is the single entry point used by the CLI:

    CLI -> ResearchSpec -> run_research(spec) -> ResearchResult -> renderer

The deterministic core (:func:`compute`) is a pure function of the research
spec and the preserved raw source bytes; replay uses the exact same function,
so a replayed run recomputes results the way the original run did.

Design rules enforced here:
- Financial values are calculated only in :mod:`strix.analytics`.
- The reasoner receives only ``(spec, evidence)``.
- Network access happens only inside source connectors, before this
  pipeline's deterministic core runs.
- Wall-clock timestamps (``created_at``, ``checked_at``) never enter
  deterministic hashes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from strix import PIPELINE_VERSION
from strix.analytics.profitability import (
    CALCULATION_VERSION,
    operating_margin,
    operating_margin_change_pp,
)
from strix.canonical import canonical_hash, make_id, sha256_hex
from strix.errors import SourceError
from strix.formatting import display_value
from strix.models import (
    CalculationResult,
    Claim,
    Concept,
    Evidence,
    EvidenceStatus,
    EvidenceType,
    ResearchReport,
    ResearchResult,
    ResearchSpec,
    RunManifest,
    SourceArtifact,
    SourceFact,
    SourceType,
    ValidationStatus,
    VerificationResult,
    VerificationStatus,
)
from strix.reasoning.base import Reasoner
from strix.reasoning.deterministic_demo import DeterministicDemoReasoner
from strix.run_store import RunStore
from strix.sources import parse_source
from strix.sources.base import FetchedSource, SourceDocument
from strix.sources.demo import DemoConnector
from strix.verification.claims import verify

#: Progress steps reported to the CLI, in order.
PROGRESS_STEPS = (
    "Preserving source artifact",
    "Validating source facts",
    "Calculating operating margins",
    "Building evidence",
    "Constructing structured claim",
    "Verifying claim",
)

ProgressFn = Callable[[int, int, str, str], None]


class Clock(Protocol):
    """Injectable time source (kept out of all deterministic content)."""

    def now(self) -> datetime: ...


class SystemClock:
    """Wall clock in UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)


# --------------------------------------------------------------------------
# Deterministic core (shared by run and replay)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DeterministicOutcome:
    """Everything reproducible about a run (no run ID, no wall clock)."""

    artifact: SourceArtifact
    facts: tuple[SourceFact, ...]
    calculations: tuple[CalculationResult, ...]
    evidence: tuple[Evidence, ...]
    claims: tuple[Claim, ...]
    verification: VerificationResult
    hashes: dict[str, str]


def compute(
    spec: ResearchSpec,
    raw: bytes,
    *,
    source_type: SourceType,
    source_name: str,
    reasoner: Reasoner,
    checked_at: datetime,
    progress: ProgressFn | None = None,
) -> DeterministicOutcome:
    """Run the deterministic pipeline over preserved raw source bytes.

    ``checked_at`` stamps the verification result only; it is excluded from
    every deterministic hash, so replay may pass any value.
    """
    total = len(PROGRESS_STEPS)

    def step(index: int, status: str = "complete") -> None:
        if progress is not None:
            progress(index + 1, total, PROGRESS_STEPS[index], status)

    document = parse_source(source_type, raw, ticker=spec.ticker, as_of_date=spec.as_of_date)
    if document.ticker != spec.ticker:
        raise SourceError(
            f"source describes ticker {document.ticker!r}, spec requests {spec.ticker!r}"
        )
    if document.company_id != spec.company_id:
        raise SourceError("source company_id does not match the research spec")
    if tuple(spec.historical_periods) != tuple(document.periods):
        raise SourceError(
            f"spec periods {spec.historical_periods} do not match source periods {document.periods}"
        )

    artifact = SourceArtifact(
        artifact_id=make_id(
            "ART",
            {
                "source_type": source_type,
                "source_name": source_name,
                "source_version": document.source_version,
                "content_hash": sha256_hex(raw),
            },
        ),
        source_type=source_type,
        source_name=source_name,
        source_version=document.source_version,
        content_hash=sha256_hex(raw),
        known_at=document.created_at,
        local_path=f"raw/{source_name}",
        byte_size=len(raw),
    )
    step(0)

    facts = _build_facts(document, artifact)
    step(1)

    calculations = _build_calculations(spec, facts)
    step(2)

    evidence = tuple(_build_evidence(calc, facts) for calc in calculations)
    step(3)

    claims = tuple(reasoner.analyze(spec, list(evidence)))
    step(4)

    verification, verified_evidence, verified_claims = verify(
        spec=spec,
        artifact=artifact,
        facts=list(facts),
        calculations=list(calculations),
        evidence=list(evidence),
        claims=list(claims),
        checked_at=checked_at,
    )
    step(5, "passed" if verification.status is VerificationStatus.PASSED else "failed")

    evidence = tuple(verified_evidence)
    claims = tuple(verified_claims)
    hashes = {
        "input": canonical_hash({"spec": spec, "raw_sha256": artifact.content_hash}),
        "facts": facts_hash(facts),
        "calculations": calculations_hash(calculations),
        "evidence": evidence_hash(evidence),
        "claims": claims_hash(claims),
        "verification": verification_hash(verification),
    }
    return DeterministicOutcome(
        artifact=artifact,
        facts=facts,
        calculations=calculations,
        evidence=evidence,
        claims=claims,
        verification=verification,
        hashes=hashes,
    )


def _build_facts(document: SourceDocument, artifact: SourceArtifact) -> tuple[SourceFact, ...]:
    facts: list[SourceFact] = []
    for fact in document.facts:
        payload = {
            "artifact_id": artifact.artifact_id,
            "subject_id": document.company_id,
            "concept": fact.concept,
            "value": fact.value,
            "unit": fact.unit,
            "observation_period": fact.observation_period,
            "known_at": fact.known_at,
            "source_locator": fact.locator,
        }
        facts.append(
            SourceFact(
                fact_id=make_id("FACT", payload),
                subject_id=document.company_id,
                concept=fact.concept,
                value=fact.value,
                unit=fact.unit,
                observation_period=fact.observation_period,
                known_at=fact.known_at,
                source_artifact_id=artifact.artifact_id,
                source_locator=fact.locator,
                validation_status=ValidationStatus.VALID,
            )
        )
    return tuple(facts)


def _build_calculations(
    spec: ResearchSpec, facts: tuple[SourceFact, ...]
) -> tuple[CalculationResult, ...]:
    previous_period, current_period = spec.historical_periods

    def fact_for(concept: Concept, period: str) -> SourceFact:
        matches = [
            fact for fact in facts if fact.concept is concept and fact.observation_period == period
        ]
        if len(matches) != 1:
            raise SourceError(
                f"expected exactly one {concept.value} fact for {period}, found {len(matches)}"
            )
        return matches[0]

    previous_margin = operating_margin(
        operating_income=fact_for(Concept.OPERATING_INCOME, previous_period),
        revenue=fact_for(Concept.REVENUE, previous_period),
    )
    current_margin = operating_margin(
        operating_income=fact_for(Concept.OPERATING_INCOME, current_period),
        revenue=fact_for(Concept.REVENUE, current_period),
    )
    change = operating_margin_change_pp(current=current_margin, previous=previous_margin)
    return (previous_margin, current_margin, change)


def _build_evidence(calc: CalculationResult, facts: tuple[SourceFact, ...]) -> Evidence:
    facts_by_id = {fact.fact_id: fact for fact in facts}
    known_at = max(facts_by_id[fact_id].known_at for fact_id in calc.input_fact_ids)
    payload = {
        "calculation_id": calc.calculation_id,
        "subject_id": calc.subject_id,
        "evidence_type": EvidenceType.CALCULATION,
        "metric": calc.calculation_name,
        "value": calc.value,
        "unit": calc.unit,
        "observation_period": calc.observation_period,
        "known_at": known_at,
        "source_fact_ids": list(calc.input_fact_ids),
    }
    return Evidence(
        evidence_id=make_id("EV", payload),
        subject_id=calc.subject_id,
        evidence_type=EvidenceType.CALCULATION,
        metric=calc.calculation_name,
        value=calc.value,
        display_value=display_value(calc.calculation_name, calc.unit, calc.value),
        unit=calc.unit,
        observation_period=calc.observation_period,
        calculation_id=calc.calculation_id,
        source_fact_ids=calc.input_fact_ids,
        known_at=known_at,
        status=EvidenceStatus.UNVERIFIED,
    )


# --------------------------------------------------------------------------
# Stage hashes (the exact content replay compares)
# --------------------------------------------------------------------------
#
# Excluded from all stage hashes and replay comparison: run_id, created_at,
# checked_at (wall clock), run_directory, and Evidence.display_value
# (presentation-only). Included: known_at (fixture/filing-derived,
# deterministic).


def facts_hash(facts: tuple[SourceFact, ...]) -> str:
    return canonical_hash(sorted(facts, key=lambda fact: fact.fact_id))


def calculations_hash(calculations: tuple[CalculationResult, ...]) -> str:
    return canonical_hash(sorted(calculations, key=lambda calc: calc.calculation_id))


def evidence_hash(evidence: tuple[Evidence, ...]) -> str:
    dumps = [
        item.model_dump(exclude={"display_value"})
        for item in sorted(evidence, key=lambda item: item.evidence_id)
    ]
    return canonical_hash(dumps)


def claims_hash(claims: tuple[Claim, ...]) -> str:
    return canonical_hash(sorted(claims, key=lambda claim: claim.claim_id))


def verification_hash(verification: VerificationResult) -> str:
    return canonical_hash(verification.model_dump(exclude={"checked_at"}))


# --------------------------------------------------------------------------
# Full run
# --------------------------------------------------------------------------


def run_research(
    spec: ResearchSpec,
    *,
    state_dir: Path,
    fetched: FetchedSource | None = None,
    clock: Clock | None = None,
    reasoner: Reasoner | None = None,
    fixture_path: Path | None = None,
    progress: ProgressFn | None = None,
) -> ResearchResult:
    """Execute one confirmed research run and persist it atomically.

    ``fetched`` carries the already-acquired raw source bytes (from the demo
    or EDGAR connector); when omitted, the bundled demo fixture is used. A
    verification failure still produces a completed (failed) run directory;
    hard errors (bad source, calculation errors) raise ``StrixError`` and
    persist nothing.
    """
    clock = clock or SystemClock()
    reasoner = reasoner or DeterministicDemoReasoner()
    if fetched is None:
        fetched = DemoConnector(fixture_path).fetch(spec.ticker)

    outcome = compute(
        spec,
        fetched.raw,
        source_type=fetched.source_type,
        source_name=fetched.source_name,
        reasoner=reasoner,
        checked_at=clock.now(),
        progress=progress,
    )

    manifest_template = {
        "pipeline_version": PIPELINE_VERSION,
        "source_type": fetched.source_type,
        "source_name": fetched.source_name,
        "source_version": outcome.artifact.source_version,
        "source_hashes": {fetched.source_name: outcome.artifact.content_hash},
        "calculation_versions": {
            calc.calculation_name.value: CALCULATION_VERSION for calc in outcome.calculations
        },
        "input_hash": outcome.hashes["input"],
        "facts_hash": outcome.hashes["facts"],
        "calculations_hash": outcome.hashes["calculations"],
        "evidence_hash": outcome.hashes["evidence"],
        "claims_hash": outcome.hashes["claims"],
        "verification_hash": outcome.hashes["verification"],
        "final_status": outcome.verification.status,
    }

    store = RunStore(state_dir)
    created_at = clock.now()

    def build_report(run_id: str) -> ResearchReport:
        # A failed verification publishes NO findings at all — not even the
        # verified subset — so a failed report can never read as approved.
        published = (
            tuple(
                claim
                for claim in outcome.claims
                if claim.claim_id in outcome.verification.verified_claim_ids
            )
            if outcome.verification.status is VerificationStatus.PASSED
            else ()
        )
        summary = (
            published[0].statement
            if published
            else "No verified finding. One or more claims failed verification."
        )
        return ResearchReport(
            run_id=run_id,
            title=f"Operating profitability of {spec.company_name} ({spec.ticker})",
            summary=summary,
            claims=published,
            evidence_ids=tuple(item.evidence_id for item in outcome.evidence),
            verification_status=outcome.verification.status,
            disclaimer=fetched.disclaimer,
        )

    def build_manifest(run_id: str) -> RunManifest:
        return RunManifest(run_id=run_id, created_at=created_at, **manifest_template)

    _run_id, run_directory, manifest, report = store.persist_run(
        spec=spec,
        raw_name=fetched.source_name,
        raw_bytes=fetched.raw,
        outcome=outcome,
        build_manifest=build_manifest,
        build_report=build_report,
        today=created_at.date(),
    )
    return ResearchResult(
        spec=spec,
        artifact=outcome.artifact,
        facts=outcome.facts,
        calculations=outcome.calculations,
        evidence=outcome.evidence,
        claims=outcome.claims,
        verification=outcome.verification,
        report=report,
        manifest=manifest,
        run_directory=run_directory,
    )
