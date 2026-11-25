"""Deterministic, exact-Decimal offline evaluation metrics (R1 §30).

Each metric is computed over a :class:`~strix.answering.models.VerifiedResearchResponse`
against a supplied :class:`~strix.research_eval.dataset.GroundTruth`. Every metric
is a **count ratio** — an integer ``numerator`` over an integer ``denominator`` —
so the score is exactly reproducible by hand and micro-averages cleanly by
pooling the raw counts (:func:`aggregate_scores`). Scoring is fully deterministic
and performs no model call; it never fabricates a benchmark number.

The six metrics (stable ``MetricResult.name`` values):

- ``verified_factual_precision`` — of the response's factual assertions, the
  fraction whose normalized text matches an expected claim.
- ``reference_claim_coverage`` — of the ground-truth expected claims, the
  fraction covered by some factual assertion.
- ``unsupported_claim_escape`` — of the factual assertions, the fraction flagged
  unsupported by the response's own validation (lower is better).
- ``citation_support_accuracy`` — of the factual assertions, the fraction that
  are *grounded*: they carry at least one citation and every cited evidence id
  is present in the response's citation set.
- ``answer_requirement_coverage`` — of the response's per-requirement coverage
  entries, the fraction marked satisfied.
- ``appropriate_abstention`` — a single 0/1 judgement: did the response's
  abstention behaviour match ``ground_truth.must_abstain``.

Text matching is normalization-insensitive: strings are compared after case
folding, punctuation removal, and whitespace collapse (via
:func:`strix.research.normalize.tokenize`).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from pydantic import Field

from strix.answering.models import AnswerStatus, VerifiedResearchResponse
from strix.errors import StrixError
from strix.models import DecimalValue, StrixModel
from strix.research.normalize import tokenize
from strix.research_eval.dataset import GroundTruth

__all__ = [
    "METRIC_NAMES",
    "SCORING_POLICY_VERSION",
    "EvalScoringError",
    "MetricResult",
    "aggregate_scores",
    "score_response",
]

SCORING_POLICY_VERSION = "1.0.0"

#: Statuses that count as the response having declined to answer.
_ABSTAINED_STATUSES: frozenset[AnswerStatus] = frozenset(
    {AnswerStatus.INSUFFICIENT_EVIDENCE, AnswerStatus.UNANSWERABLE}
)

#: The fixed metric order emitted by :func:`score_response`.
METRIC_NAMES: tuple[str, ...] = (
    "verified_factual_precision",
    "reference_claim_coverage",
    "unsupported_claim_escape",
    "citation_support_accuracy",
    "answer_requirement_coverage",
    "appropriate_abstention",
)


class EvalScoringError(StrixError):
    """A response could not be scored against its ground truth."""


class MetricResult(StrixModel):
    """One metric as an exact count ratio ``numerator / denominator``.

    ``value`` is the exact :class:`~decimal.Decimal` quotient (``0`` when the
    denominator is ``0``). Keeping the raw counts alongside the value is what
    lets :func:`aggregate_scores` micro-average by pooling numerators and
    denominators rather than averaging already-divided fractions.
    """

    name: str = Field(min_length=1)
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: DecimalValue = Field(ge=Decimal(0), le=Decimal(1))

    @classmethod
    def from_counts(cls, name: str, numerator: int, denominator: int) -> MetricResult:
        """Build a :class:`MetricResult`, computing ``value`` exactly.

        Raises :class:`EvalScoringError` if the counts are negative or the
        numerator exceeds the denominator (which would put ``value`` above 1).
        """
        if numerator < 0 or denominator < 0:
            raise EvalScoringError(
                f"metric {name!r} counts must be non-negative; "
                f"got {numerator}/{denominator}"
            )
        if numerator > denominator:
            raise EvalScoringError(
                f"metric {name!r} numerator {numerator} exceeds "
                f"denominator {denominator}"
            )
        value = Decimal(numerator) / Decimal(denominator) if denominator else Decimal(0)
        return cls(
            name=name,
            numerator=numerator,
            denominator=denominator,
            value=value,
        )


def _norm(text: str) -> str:
    """Normalization-insensitive key: case-folded, de-punctuated token join."""
    return " ".join(tokenize(text))


def _norm_set(texts: Sequence[str]) -> frozenset[str]:
    """The set of normalized keys for *texts* (empty entries dropped)."""
    return frozenset(_norm(t) for t in texts if _norm(t))


def score_response(
    response: VerifiedResearchResponse, ground_truth: GroundTruth
) -> tuple[MetricResult, ...]:
    """Score *response* against *ground_truth* as a fixed tuple of metrics.

    The returned tuple always contains the six metrics named in
    :data:`METRIC_NAMES`, in that order. The computation is deterministic and
    makes no model call.
    """
    factual = response.factual_assertions
    expected_claim_keys = _norm_set(ground_truth.expected_claims)
    factual_keys = [_norm(a.text) for a in factual]
    citation_set = frozenset(response.citations)
    unsupported_keys = _norm_set(response.validation.unsupported_assertions)

    # verified_factual_precision: factual assertions that match an expected claim.
    precision_num = sum(1 for k in factual_keys if k in expected_claim_keys)
    precision = MetricResult.from_counts(
        "verified_factual_precision", precision_num, len(factual)
    )

    # reference_claim_coverage: expected claims covered by some factual assertion.
    present_factual_keys = frozenset(factual_keys)
    coverage_num = sum(1 for k in expected_claim_keys if k in present_factual_keys)
    coverage = MetricResult.from_counts(
        "reference_claim_coverage", coverage_num, len(expected_claim_keys)
    )

    # unsupported_claim_escape: factual assertions flagged unsupported.
    escape_num = sum(1 for k in factual_keys if k in unsupported_keys)
    escape = MetricResult.from_counts(
        "unsupported_claim_escape", escape_num, len(factual)
    )

    # citation_support_accuracy: factual assertions that are grounded.
    grounded_num = sum(
        1
        for a in factual
        if a.citation_evidence_ids
        and all(eid in citation_set for eid in a.citation_evidence_ids)
    )
    citation = MetricResult.from_counts(
        "citation_support_accuracy", grounded_num, len(factual)
    )

    # answer_requirement_coverage: satisfied per-requirement coverage entries.
    per_req = response.coverage.per_requirement
    req_num = sum(1 for rc in per_req if rc.satisfied)
    requirement = MetricResult.from_counts(
        "answer_requirement_coverage", req_num, len(per_req)
    )

    # appropriate_abstention: did abstention behaviour match the requirement.
    abstained = response.answer_status in _ABSTAINED_STATUSES
    appropriate = abstained == ground_truth.must_abstain
    abstention = MetricResult.from_counts(
        "appropriate_abstention", 1 if appropriate else 0, 1
    )

    return (
        precision,
        coverage,
        escape,
        citation,
        requirement,
        abstention,
    )


def aggregate_scores(
    per_question: Sequence[tuple[MetricResult, ...]]
) -> dict[str, MetricResult]:
    """Micro-average per-question metric tuples by pooling raw counts.

    For each metric name the numerators and denominators are summed across all
    questions and re-divided, so a metric's aggregate reflects per-item counts
    (a micro-average) rather than an average of per-question fractions. The
    result is keyed by metric name; iteration order follows :data:`METRIC_NAMES`.
    """
    num_totals: dict[str, int] = dict.fromkeys(METRIC_NAMES, 0)
    den_totals: dict[str, int] = dict.fromkeys(METRIC_NAMES, 0)
    seen: list[str] = []
    for results in per_question:
        for metric in results:
            if metric.name not in num_totals:
                num_totals[metric.name] = 0
                den_totals[metric.name] = 0
                seen.append(metric.name)
            num_totals[metric.name] += metric.numerator
            den_totals[metric.name] += metric.denominator

    ordered_names = [*METRIC_NAMES, *seen]
    return {
        name: MetricResult.from_counts(name, num_totals[name], den_totals[name])
        for name in ordered_names
    }
