"""Typed answer/response models for the deterministic answer path (R1 §17.3).

STRIX must *actually answer* the research question in natural language — stating
what was found, its magnitude and direction, the relevant comparisons, and the
attendant uncertainty and limitations (R1 §1.1, §17.1). It must never return an
evidence dump or a list of record ids.

This module defines the typed vocabulary of that answer:

- :class:`AnswerRequirement` — one thing the question demands be addressed.
- :class:`AnswerAssertion` — one statement the answer makes. Every *factual*
  assertion is a material claim and MUST carry a ``claim_certificate_id``
  binding it to an admitted :class:`~strix.evidence_graph.certificates.ClaimCertificate`
  (R1 §17.4); analytical inferences and hypotheses are explicitly not factual
  and need no certificate.
- :class:`AnswerSection` — a headed group of assertions.
- :class:`AnswerCoverage` / :class:`RequirementCoverage` — how well the answer
  satisfies each requirement.
- :class:`AnswerValidationResult` — the fail-closed check that no factual
  assertion is unsupported.
- :class:`VerifiedResearchResponse` — the complete, rendered response.

Every model is frozen with a closed schema (:class:`~strix.models.StrixModel`);
every numeric field is an exact :class:`~decimal.Decimal` that rejects ``float``
(:data:`~strix.models.DecimalValue`). Content-derived ids flow through
:func:`strix.canonical.make_id`.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from strix.canonical import make_id
from strix.errors import StrixError
from strix.models import DecimalValue, StrixModel

__all__ = [
    "AnswerAssertion",
    "AnswerCoverage",
    "AnswerRequirement",
    "AnswerSection",
    "AnswerStatus",
    "AnswerValidationResult",
    "AnsweringError",
    "AssertionKind",
    "RequirementCoverage",
    "RequirementImportance",
    "VerifiedResearchResponse",
    "make_answer_requirement",
]


# --------------------------------------------------------------------------
# Exception
# --------------------------------------------------------------------------


class AnsweringError(StrixError):
    """The deterministic answer path could not build or validate a response."""


# --------------------------------------------------------------------------
# Bounded vocabularies
# --------------------------------------------------------------------------


class AssertionKind(StrEnum):
    """What epistemic weight an answer assertion carries.

    ``FACTUAL`` statements are material claims and must be certificate-backed;
    ``ANALYTICAL_INFERENCE`` and ``HYPOTHESIS`` statements are explicitly
    non-factual interpretation and need not be.
    """

    FACTUAL = "factual"
    ANALYTICAL_INFERENCE = "analytical_inference"
    HYPOTHESIS = "hypothesis"


class AnswerStatus(StrEnum):
    """How completely the response answers the question."""

    COMPLETE_ANSWER = "complete_answer"
    PARTIAL_ANSWER = "partial_answer"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNANSWERABLE = "unanswerable"


class RequirementImportance(StrEnum):
    """Relative importance of a requirement, mapped to a coverage weight."""

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"

    @property
    def weight(self) -> Decimal:
        """Exact positive coverage weight for this importance level."""
        return _IMPORTANCE_WEIGHTS[self]


_IMPORTANCE_WEIGHTS: dict[RequirementImportance, Decimal] = {
    RequirementImportance.CRITICAL: Decimal("1"),
    RequirementImportance.HIGH: Decimal("0.75"),
    RequirementImportance.NORMAL: Decimal("0.5"),
    RequirementImportance.LOW: Decimal("0.25"),
}


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------


class AnswerRequirement(StrixModel):
    """One discrete thing the question demands the answer address."""

    requirement_id: str
    text: str = Field(min_length=1)
    #: Strictly positive relative weight (see :class:`RequirementImportance`).
    weight: DecimalValue = Field(gt=Decimal(0))
    subject_id: str | None = None
    metric: str | None = None


def make_answer_requirement(
    *,
    text: str,
    weight: Decimal,
    subject_id: str | None = None,
    metric: str | None = None,
) -> AnswerRequirement:
    """Build an :class:`AnswerRequirement` with a content-derived ``REQ-`` id.

    The id is derived from the requirement's content only; the id field itself
    is excluded from the hashed payload (:func:`strix.canonical.make_id`).
    """
    draft = AnswerRequirement(
        requirement_id="",
        text=text,
        weight=weight,
        subject_id=subject_id,
        metric=metric,
    )
    payload = draft.model_dump()
    payload.pop("requirement_id", None)
    return draft.model_copy(update={"requirement_id": make_id("REQ", payload)})


class AnswerAssertion(StrixModel):
    """One statement the answer makes.

    A ``FACTUAL`` assertion is a material factual claim and MUST carry a
    ``claim_certificate_id`` binding it to an admitted claim certificate
    (R1 §17.4). Analytical inferences and hypotheses are explicitly non-factual
    and need no certificate.
    """

    text: str = Field(min_length=1)
    kind: AssertionKind
    claim_certificate_id: str | None = None
    subject_id: str | None = None
    metric: str | None = None
    value: DecimalValue | None = None
    unit: str | None = None
    citation_evidence_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _factual_is_certificate_backed(self) -> AnswerAssertion:
        if self.kind is AssertionKind.FACTUAL and self.claim_certificate_id is None:
            raise ValueError(
                "a factual assertion must carry a claim_certificate_id"
            )
        return self


class AnswerSection(StrixModel):
    """A headed group of assertions within the rendered answer."""

    heading: str = Field(min_length=1)
    assertions: tuple[AnswerAssertion, ...]


class RequirementCoverage(StrixModel):
    """How well one requirement was satisfied (0..1)."""

    requirement_id: str
    satisfaction: DecimalValue = Field(ge=Decimal(0), le=Decimal(1))
    satisfied: bool


class AnswerCoverage(StrixModel):
    """Aggregate coverage of the question's requirements (0..1)."""

    score: DecimalValue = Field(ge=Decimal(0), le=Decimal(1))
    per_requirement: tuple[RequirementCoverage, ...]
    status: AnswerStatus


class AnswerValidationResult(StrixModel):
    """Outcome of the fail-closed check that no factual assertion is unsupported."""

    ok: bool
    unsupported_assertions: tuple[str, ...]
    issues: tuple[str, ...]


class VerifiedResearchResponse(StrixModel):
    """The complete, rendered natural-language research response (R1 §17.3).

    Carries the prose answer plus the structured assertions it is built from,
    split by epistemic kind, with coverage, status, limitations, and the
    validation result that attests every factual assertion is certificate-backed.
    """

    question: str
    answer_text: str
    sections: tuple[AnswerSection, ...]
    factual_assertions: tuple[AnswerAssertion, ...]
    analytical_inferences: tuple[AnswerAssertion, ...]
    hypotheses: tuple[AnswerAssertion, ...]
    citations: tuple[str, ...]
    coverage: AnswerCoverage
    answer_status: AnswerStatus
    limitations: tuple[str, ...]
    unresolved_requirements: tuple[str, ...]
    validation: AnswerValidationResult
