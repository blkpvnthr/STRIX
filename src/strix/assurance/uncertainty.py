"""R2-C honest uncertainty assessment (no fabricated probabilities).

Given an *admitted-evidence picture* — how many of the answer's required
evidence requirements were actually admitted, whether the supporting evidence
is fresh, whether the supporting nodes contradict one another, and whether any
cited inference carried a statistical confidence interval — this module derives
an **ordinal** :class:`UncertaintyLevel` together with explicit, independently
named :class:`UncertaintyComponents` and typed :class:`UncertaintyReasonCode`
codes.

Honesty mandate
---------------
No probability is ever emitted. There is deliberately no numeric
confidence/probability field anywhere in the schema (:class:`UncertaintyModel`
subtypes are ``extra="forbid"``, so one cannot be injected either). Uncertainty
is expressed as an ordinal level plus named components and reason codes. The
:data:`UncertaintyReasonCode.NO_CALIBRATED_PROBABILITY` code is emitted on every
assessment to record this explicitly. If a calibrated probability is ever added
later it MUST come from empirically-validated calibration data — not from a
model-invented number — and must be surfaced as a distinct, clearly-labelled
field rather than replacing this ordinal output.

Separation of dimensions (R1 §2-C)
----------------------------------
The five status dimensions — verification, evidence quality, answer
completeness, analytical uncertainty, and authorization — are kept as five
SEPARATE fields on :class:`StatusDimensions` and are never collapsed into a
single score. Cryptographic integrity/authenticity is a different property
from factual correctness; none of these dimensions asserts that an answer is
*true*.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from strix.errors import StrixError
from strix.models import DecimalValue, StrixModel

__all__ = [
    "StatusDimensions",
    "UncertaintyAssessment",
    "UncertaintyComponents",
    "UncertaintyError",
    "UncertaintyLevel",
    "UncertaintyReasonCode",
    "assess_uncertainty",
]

#: evidence_sufficiency strictly below this collapses the level to ``high``.
_HIGH_SUFFICIENCY_THRESHOLD = Decimal("0.5")
#: evidence_sufficiency at or above this counts as full requirement coverage.
_FULL_SUFFICIENCY = Decimal(1)


class UncertaintyError(StrixError):
    """An uncertainty assessment received invalid inputs and could not be
    performed. Raised for contract violations (negative counts/ages, an empty
    authorization status) — never to express a *high-uncertainty* outcome,
    which is a normal typed :class:`UncertaintyAssessment` result."""


class UncertaintyLevel(StrEnum):
    """Ordinal uncertainty level (never a probability)."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    INSUFFICIENT = "insufficient"


class UncertaintyReasonCode(StrEnum):
    """Typed deterministic reason codes explaining an assessment.

    Each code is a pure function of the inputs; the tuple ordering on an
    assessment is deterministic.
    """

    INSUFFICIENT_EVIDENCE = "insufficient_admitted_evidence_for_required"
    MISSING_REQUIREMENTS = "missing_requirements"
    LOW_EVIDENCE_SUFFICIENCY = "evidence_sufficiency_below_threshold"
    SOURCE_DISAGREEMENT = "source_disagreement_present"
    STALE_EVIDENCE = "evidence_stale"
    STATISTICAL_UNCERTAINTY = "statistical_uncertainty_present"
    PARTIAL_COVERAGE = "partial_requirement_coverage"
    FULL_COVERAGE = "full_coverage_fresh_consistent"
    ABSTENTION_RECOMMENDED = "abstention_recommended"
    #: Always emitted: records that no calibrated probability was fabricated.
    NO_CALIBRATED_PROBABILITY = "no_calibrated_probability_available"


class UncertaintyComponents(StrixModel):
    """The explicit, independently named inputs behind an uncertainty level.

    ``evidence_sufficiency`` is the exact ratio ``admitted_requirements /
    total_requirements`` in ``[0, 1]`` (a *coverage* ratio — never a confidence
    probability). The remaining components are discrete facts, not scores.
    """

    evidence_sufficiency: DecimalValue
    freshness_ok: bool
    source_disagreement_count: int
    missing_requirements: tuple[str, ...]
    statistical_uncertainty_present: bool
    abstention_recommended: bool


class StatusDimensions(StrixModel):
    """Five SEPARATE status dimensions (R1 §2-C), never collapsed to one score.

    Each is an ordinal/categorical label, not a probability. None of them
    asserts factual correctness — they describe the *standing* of the answer's
    evidence, verification, completeness, analytical uncertainty, and
    authorization independently.
    """

    verification_status: str
    evidence_quality: str
    answer_completeness: str
    analytical_uncertainty: str
    authorization_status: str


class UncertaintyAssessment(StrixModel):
    """The terminal, fully-diagnosed uncertainty assessment.

    ``level`` is the ordinal verdict; ``components`` carries the named inputs;
    ``dimensions`` keeps the five status dimensions separate; ``reason_codes``
    enumerates every typed reason that applied.
    """

    level: UncertaintyLevel
    components: UncertaintyComponents
    dimensions: StatusDimensions
    reason_codes: tuple[str, ...]


def _validate_inputs(
    *,
    total_requirements: int,
    contradiction_count: int,
    max_evidence_age_seconds: int | None,
    freshness_limit_seconds: int | None,
    authorization_status: str,
) -> None:
    """Reject inputs that cannot be coherently assessed (fail closed)."""
    if total_requirements < 0:
        raise UncertaintyError("total_requirements must be non-negative")
    if contradiction_count < 0:
        raise UncertaintyError("contradiction_count must be non-negative")
    if max_evidence_age_seconds is not None and max_evidence_age_seconds < 0:
        raise UncertaintyError("max_evidence_age_seconds must be non-negative")
    if freshness_limit_seconds is not None and freshness_limit_seconds < 0:
        raise UncertaintyError("freshness_limit_seconds must be non-negative")
    if not authorization_status.strip():
        raise UncertaintyError("authorization_status must be a non-empty label")


def _is_stale(
    max_evidence_age_seconds: int | None, freshness_limit_seconds: int | None
) -> bool:
    """True only when staleness is *provable*: both bounds known and exceeded.

    Absence of freshness information is reported as not-provably-stale rather
    than fabricated as fresh or stale; the ``evidence_quality`` dimension records
    the unknown case separately.
    """
    if max_evidence_age_seconds is None or freshness_limit_seconds is None:
        return False
    return max_evidence_age_seconds > freshness_limit_seconds


def _derive_level(
    *,
    total_requirements: int,
    covered_count: int,
    sufficiency: Decimal,
    contradiction_count: int,
    stale: bool,
) -> UncertaintyLevel:
    """Deterministically map the evidence picture onto an ordinal level.

    insufficient (no admitted evidence for required items) dominates; then high
    (sufficiency < 0.5, or contradictions, or stale); then moderate (partial
    coverage); otherwise low (full coverage, fresh, no contradictions).
    """
    if total_requirements <= 0 or covered_count == 0:
        return UncertaintyLevel.INSUFFICIENT
    if (
        sufficiency < _HIGH_SUFFICIENCY_THRESHOLD
        or contradiction_count > 0
        or stale
    ):
        return UncertaintyLevel.HIGH
    if sufficiency < _FULL_SUFFICIENCY:
        return UncertaintyLevel.MODERATE
    return UncertaintyLevel.LOW


def _evidence_quality(stale: bool, freshness_known: bool) -> str:
    """Ordinal evidence-quality label (kept separate from the overall level)."""
    if stale:
        return "stale"
    if not freshness_known:
        return "freshness_unknown"
    return "fresh"


def _answer_completeness(
    total_requirements: int, covered_count: int, sufficiency: Decimal
) -> str:
    """Ordinal completeness label derived from requirement coverage."""
    if total_requirements <= 0 or covered_count == 0:
        return "no_coverage"
    if sufficiency >= _FULL_SUFFICIENCY:
        return "complete"
    return "partial"


def _reason_codes(
    *,
    level: UncertaintyLevel,
    sufficiency: Decimal,
    has_missing: bool,
    contradiction_count: int,
    stale: bool,
    has_confidence_interval: bool,
    abstention_recommended: bool,
) -> tuple[str, ...]:
    """Build the deterministic, de-duplicated tuple of reason codes."""
    codes: list[UncertaintyReasonCode] = []
    if level is UncertaintyLevel.INSUFFICIENT:
        codes.append(UncertaintyReasonCode.INSUFFICIENT_EVIDENCE)
    if has_missing:
        codes.append(UncertaintyReasonCode.MISSING_REQUIREMENTS)
    if level is not UncertaintyLevel.INSUFFICIENT and sufficiency < _HIGH_SUFFICIENCY_THRESHOLD:
        codes.append(UncertaintyReasonCode.LOW_EVIDENCE_SUFFICIENCY)
    if contradiction_count > 0:
        codes.append(UncertaintyReasonCode.SOURCE_DISAGREEMENT)
    if stale:
        codes.append(UncertaintyReasonCode.STALE_EVIDENCE)
    if has_confidence_interval:
        codes.append(UncertaintyReasonCode.STATISTICAL_UNCERTAINTY)
    if level is UncertaintyLevel.MODERATE:
        codes.append(UncertaintyReasonCode.PARTIAL_COVERAGE)
    if level is UncertaintyLevel.LOW:
        codes.append(UncertaintyReasonCode.FULL_COVERAGE)
    if abstention_recommended:
        codes.append(UncertaintyReasonCode.ABSTENTION_RECOMMENDED)
    # Always last: no calibrated probability was fabricated.
    codes.append(UncertaintyReasonCode.NO_CALIBRATED_PROBABILITY)
    return tuple(code.value for code in codes)


def assess_uncertainty(
    *,
    total_requirements: int,
    admitted_requirement_ids: frozenset[str],
    required_requirement_ids: frozenset[str],
    contradiction_count: int,
    max_evidence_age_seconds: int | None,
    freshness_limit_seconds: int | None,
    has_confidence_interval: bool,
    authorization_status: str,
) -> UncertaintyAssessment:
    """Assess the uncertainty of an answer from its admitted-evidence picture.

    Derives an ordinal :class:`UncertaintyLevel` deterministically:

    - **insufficient** — no admitted evidence covers any required requirement
      (also when there are no requirements to go on); abstention is recommended;
    - **high** — ``evidence_sufficiency`` below ~0.5, OR contradictions among the
      supporting nodes, OR provably stale supporting evidence;
    - **moderate** — partial requirement coverage, fresh, no contradictions;
    - **low** — full coverage, fresh, no contradictions.

    ``evidence_sufficiency`` is the exact Decimal ratio of required requirements
    that were admitted to ``total_requirements``; it is a coverage ratio, never a
    confidence probability. The five status dimensions are populated separately
    and never collapsed (R1 §2-C). No probability is fabricated.

    Raises :class:`UncertaintyError` for incoherent inputs (negative counts or
    ages, an empty authorization status).
    """
    _validate_inputs(
        total_requirements=total_requirements,
        contradiction_count=contradiction_count,
        max_evidence_age_seconds=max_evidence_age_seconds,
        freshness_limit_seconds=freshness_limit_seconds,
        authorization_status=authorization_status,
    )

    covered = admitted_requirement_ids & required_requirement_ids
    covered_count = len(covered)
    missing_requirements = tuple(sorted(required_requirement_ids - admitted_requirement_ids))

    if total_requirements > 0:
        sufficiency = Decimal(covered_count) / Decimal(total_requirements)
    else:
        sufficiency = Decimal(0)

    stale = _is_stale(max_evidence_age_seconds, freshness_limit_seconds)
    freshness_known = (
        max_evidence_age_seconds is not None and freshness_limit_seconds is not None
    )

    level = _derive_level(
        total_requirements=total_requirements,
        covered_count=covered_count,
        sufficiency=sufficiency,
        contradiction_count=contradiction_count,
        stale=stale,
    )

    # Abstain when the picture is insufficient, or (defensively) when the level
    # is high yet no evidence was admitted at all. This control is derived here
    # and cannot be overridden by a favourable authorization status.
    abstention_recommended = level is UncertaintyLevel.INSUFFICIENT or (
        level is UncertaintyLevel.HIGH and not admitted_requirement_ids
    )

    components = UncertaintyComponents(
        evidence_sufficiency=sufficiency,
        freshness_ok=not stale,
        source_disagreement_count=contradiction_count,
        missing_requirements=missing_requirements,
        statistical_uncertainty_present=has_confidence_interval,
        abstention_recommended=abstention_recommended,
    )

    dimensions = StatusDimensions(
        verification_status=(
            "contradictions_present"
            if contradiction_count > 0
            else "no_contradictions_detected"
        ),
        evidence_quality=_evidence_quality(stale, freshness_known),
        answer_completeness=_answer_completeness(
            total_requirements, covered_count, sufficiency
        ),
        analytical_uncertainty=(
            "statistical_uncertainty_present"
            if has_confidence_interval
            else "no_statistical_uncertainty_flagged"
        ),
        authorization_status=authorization_status,
    )

    reason_codes = _reason_codes(
        level=level,
        sufficiency=sufficiency,
        has_missing=bool(missing_requirements),
        contradiction_count=contradiction_count,
        stale=stale,
        has_confidence_interval=has_confidence_interval,
        abstention_recommended=abstention_recommended,
    )

    return UncertaintyAssessment(
        level=level,
        components=components,
        dimensions=dimensions,
        reason_codes=reason_codes,
    )
