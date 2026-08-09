"""Typed domain models for the STRIX research pipeline.

The lineage contract:

    SourceArtifact -> SourceFact -> CalculationResult -> Evidence -> Claim

All models are frozen (immutable). Status transitions produce copies via
``model_copy(update=...)``. Monetary and ratio values are ``Decimal`` and
may never be supplied as ``float``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field

# --------------------------------------------------------------------------
# Bounded vocabularies
# --------------------------------------------------------------------------


class SourceType(StrEnum):
    SYNTHETIC_FIXTURE = "synthetic_fixture"
    SEC_EDGAR_COMPANYFACTS = "sec_edgar_companyfacts"


class Concept(StrEnum):
    REVENUE = "revenue"
    OPERATING_INCOME = "operating_income"


class Unit(StrEnum):
    USD = "USD"
    RATIO = "ratio"
    PERCENTAGE_POINTS = "percentage_points"


class ValidationStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


class EvidenceType(StrEnum):
    CALCULATION = "calculation"


class Metric(StrEnum):
    OPERATING_MARGIN = "operating_margin"
    OPERATING_MARGIN_CHANGE_PP = "operating_margin_change_pp"


class EvidenceStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ClaimType(StrEnum):
    PROFITABILITY_CHANGE = "profitability_change"


class ClaimStatus(StrEnum):
    PROPOSED = "proposed"
    VERIFIED = "verified"
    REJECTED = "rejected"


class Direction(StrEnum):
    INCREASED = "increased"
    DECREASED = "decreased"
    UNCHANGED = "unchanged"


class VerificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class FailureCode(StrEnum):
    UNKNOWN_EVIDENCE = "unknown_evidence"
    SUBJECT_MISMATCH = "subject_mismatch"
    EVIDENCE_AFTER_AS_OF = "evidence_after_as_of"
    ASSERTION_VALUE_MISMATCH = "assertion_value_mismatch"
    ASSERTION_UNIT_MISMATCH = "assertion_unit_mismatch"
    ASSERTION_EVIDENCE_NOT_CITED = "assertion_evidence_not_cited"
    MISSING_ASSERTION = "missing_assertion"
    UNSUPPORTED_UNIT = "unsupported_unit"
    MISSING_COMPARISON_EVIDENCE = "missing_comparison_evidence"
    EVIDENCE_NOT_VERIFIED = "evidence_not_verified"
    UNKNOWN_CALCULATION = "unknown_calculation"
    MISSING_SOURCE_FACT = "missing_source_fact"
    ARTIFACT_MISMATCH = "artifact_mismatch"
    EVIDENCE_CALC_MISMATCH = "evidence_calc_mismatch"
    INCOMPLETE_LINEAGE = "incomplete_lineage"
    DIRECTION_MISMATCH = "direction_mismatch"
    STATEMENT_MISMATCH = "statement_mismatch"
    NO_CLAIMS = "no_claims"


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------


def _reject_float(value: object) -> object:
    """Forbid binary floating point on Decimal fields (str/int/Decimal only)."""
    if isinstance(value, float):
        raise ValueError("float values are forbidden; supply Decimal, str, or int")
    return value


DecimalValue = Annotated[Decimal, BeforeValidator(_reject_float)]


class StrixModel(BaseModel):
    """Base for all STRIX domain models: frozen, closed schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------
# Domain models
# --------------------------------------------------------------------------


class ResearchSpec(StrixModel):
    """Validated description of one research request (pure user input)."""

    company_id: str
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,9}$")
    company_name: str
    question: str = Field(min_length=1)
    as_of_date: date
    #: Role-ordered: (previous_period, current_period).
    historical_periods: tuple[str, str]
    pipeline_version: str


class SourceArtifact(StrixModel):
    """A preserved raw source input, identified by its content hash."""

    artifact_id: str
    source_type: SourceType
    #: Plain file name of the preserved raw copy — never a path.
    source_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")
    #: Content-derived version label (fixture version or filed-through date).
    source_version: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    known_at: AwareDatetime
    #: Path of the preserved copy *relative to the run directory* (portable
    #: and deterministic; absolute paths never enter hashed content).
    local_path: str
    byte_size: int = Field(ge=1)


class SourceFact(StrixModel):
    """One validated observation extracted from a source artifact."""

    fact_id: str
    subject_id: str
    concept: Concept
    value: DecimalValue
    unit: Unit
    observation_period: str
    known_at: AwareDatetime
    source_artifact_id: str
    #: Locator of the fact inside the source artifact (JSON pointer).
    source_locator: str
    validation_status: ValidationStatus


class CalculationResult(StrixModel):
    """Output of one deterministic, versioned calculation."""

    calculation_id: str
    calculation_name: Metric
    calculation_version: str
    subject_id: str
    value: DecimalValue
    unit: Unit
    observation_period: str
    #: Role-ordered input facts (e.g. [numerator, denominator]).
    input_fact_ids: tuple[str, ...]
    #: Role-ordered upstream calculations (e.g. [current, previous]); empty
    #: for calculations computed directly from source facts.
    input_calculation_ids: tuple[str, ...] = ()


class Evidence(StrixModel):
    """A citable, typed result carrying its full lineage."""

    evidence_id: str
    subject_id: str
    evidence_type: EvidenceType
    metric: Metric
    value: DecimalValue
    #: Presentation-only rendering of ``value`` (excluded from hashes).
    display_value: str
    unit: Unit
    observation_period: str
    calculation_id: str
    #: All source facts this evidence ultimately rests on (role-ordered).
    source_fact_ids: tuple[str, ...]
    known_at: AwareDatetime
    status: EvidenceStatus


class NumericAssertion(StrixModel):
    """A number a claim asserts, bound to the evidence that must support it."""

    metric: Metric
    asserted_value: DecimalValue
    unit: Unit
    evidence_id: str


class Claim(StrixModel):
    """A structured statement whose every number must cite evidence."""

    claim_id: str
    subject_id: str
    statement: str
    claim_type: ClaimType
    direction: Direction
    evidence_ids: tuple[str, ...]
    numeric_assertions: tuple[NumericAssertion, ...]
    status: ClaimStatus


class VerificationFailure(StrixModel):
    """One concrete reason a claim (or its evidence) was rejected."""

    code: FailureCode
    message: str
    claim_id: str | None = None
    evidence_id: str | None = None


class VerificationResult(StrixModel):
    """Outcome of the deterministic verification pass."""

    status: VerificationStatus
    verified_claim_ids: tuple[str, ...]
    rejected_claim_ids: tuple[str, ...]
    failures: tuple[VerificationFailure, ...]
    #: Wall clock — excluded from deterministic hashes and replay comparison.
    checked_at: AwareDatetime
    verifier_version: str


class ResearchReport(StrixModel):
    """The publishable result. Contains only verified structured content."""

    run_id: str
    title: str
    summary: str
    claims: tuple[Claim, ...]
    evidence_ids: tuple[str, ...]
    verification_status: VerificationStatus
    disclaimer: str


class RunManifest(StrixModel):
    """Integrity record for one research run.

    Deterministic (replay-compared) fields: pipeline_version, source_type,
    source_name, source_version, source_hashes, calculation_versions,
    input_hash, facts_hash, calculations_hash, evidence_hash, claims_hash,
    verification_hash, final_status.

    Execution-specific (excluded from replay comparison): run_id, created_at.
    """

    run_id: str
    created_at: AwareDatetime
    pipeline_version: str
    source_type: SourceType
    #: Plain file name under ``raw/`` — validated so a tampered manifest can
    #: never steer replay outside the run directory.
    source_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")
    source_version: str
    #: source file name -> SHA-256 of the preserved raw bytes.
    source_hashes: dict[str, str]
    #: calculation name -> version used in this run.
    calculation_versions: dict[str, str]
    input_hash: str
    facts_hash: str
    calculations_hash: str
    evidence_hash: str
    claims_hash: str
    verification_hash: str
    final_status: VerificationStatus


class ResearchResult(StrixModel):
    """Everything produced by one confirmed research run."""

    spec: ResearchSpec
    artifact: SourceArtifact
    facts: tuple[SourceFact, ...]
    calculations: tuple[CalculationResult, ...]
    evidence: tuple[Evidence, ...]
    claims: tuple[Claim, ...]
    verification: VerificationResult
    report: ResearchReport
    manifest: RunManifest
    run_directory: Path
