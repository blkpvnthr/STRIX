"""Deterministic answer synthesis from admitted findings (R1 §16, §17.2/§17.5).

This is the *deterministic answer path* — the R1 §16 fallback that renders a
substantive, natural-language research answer from admitted structured findings
with **no** language model in the loop. It must actually answer the question:
state what was found, the magnitude and direction, and the limitations; it must
never return an evidence dump or a bare list of record ids (R1 §1.1, §17.1).

The guarantee this module upholds (R1 §17.4): every *material factual* assertion
in the response maps to an admitted claim. :func:`synthesize` therefore emits a
``FACTUAL`` :class:`~strix.answering.models.AnswerAssertion` only for a finding
whose :class:`~strix.evidence_graph.predicates.AdmissionDecision` outcome is
:attr:`~strix.evidence_graph.nodes.AdmissionOutcome.ADMITTED`, and binds each one
to that finding's :class:`~strix.evidence_graph.certificates.ClaimCertificate`.
Non-admitted findings contribute nothing.

Final fail-closed validation (that no factual assertion is unsupported) is the
pipeline's responsibility; the response carries a placeholder
:class:`~strix.answering.models.AnswerValidationResult` here (R1 §17.5).
"""

from __future__ import annotations

import re
from decimal import Decimal

from strix.answering.models import (
    AnswerAssertion,
    AnswerCoverage,
    AnswerRequirement,
    AnswerSection,
    AnswerStatus,
    AnswerValidationResult,
    AssertionKind,
    RequirementCoverage,
    VerifiedResearchResponse,
)
from strix.evidence_graph.certificates import ClaimCertificate
from strix.evidence_graph.nodes import AdmissionOutcome, CandidateClaim
from strix.evidence_graph.predicates import AdmissionDecision
from strix.models import StrixModel

__all__ = [
    "AdmittedFinding",
    "synthesize",
]

#: Coverage at or above this threshold counts as a complete answer. Exact
#: full coverage yields ``score == 1``; the threshold tolerates only rounding.
_COMPLETE_THRESHOLD = Decimal("0.999")

#: Minimum token length for keyword-based requirement matching (drop stopwords
#: like "the", "was", "of" that would match almost anything).
_MIN_KEYWORD_LEN = 3


# --------------------------------------------------------------------------
# Finding
# --------------------------------------------------------------------------


class AdmittedFinding(StrixModel):
    """A candidate claim paired with its admission decision and certificate.

    A finding is *usable* for answer synthesis iff its decision admitted the
    claim; only then may its assertions become material factual statements
    bound to its :class:`ClaimCertificate` (R1 §17.4).
    """

    claim: CandidateClaim
    decision: AdmissionDecision
    certificate: ClaimCertificate

    def is_usable(self) -> bool:
        """Whether this finding was admitted and may back factual assertions."""
        return self.decision.outcome is AdmissionOutcome.ADMITTED


# --------------------------------------------------------------------------
# Value rendering
# --------------------------------------------------------------------------


def _plain_decimal(value: Decimal) -> str:
    """Render *value* in fixed-point form with no trailing zeros or exponent."""
    return format(value.normalize(), "f")


def _render_value(value: Decimal, unit: str | None) -> str:
    """Render a numeric assertion's value for prose.

    Ratios are rendered as percentages; percentage-point changes carry an
    explicit sign; everything else is the plain value followed by its unit.
    """
    if unit is None:
        return _plain_decimal(value)
    normalized_unit = unit.strip().lower()
    if normalized_unit == "ratio":
        return f"{_plain_decimal(value * Decimal(100))}%"
    if normalized_unit in ("percentage_points", "percentage_point", "pp"):
        sign = "+" if value >= 0 else ""
        return f"{sign}{_plain_decimal(value)} percentage points"
    return f"{_plain_decimal(value)} {unit}"


def _humanize(metric: str) -> str:
    """Render a snake_case metric name as spaced words for prose."""
    return metric.replace("_", " ").strip()


def _sentence(subject_id: str, metric: str, value: Decimal, unit: str | None) -> str:
    """Build a readable factual sentence for one assertion."""
    rendered = _render_value(value, unit)
    return f"{subject_id} {_humanize(metric)} was {rendered}."


# --------------------------------------------------------------------------
# Factual assertion extraction
# --------------------------------------------------------------------------


def _factual_assertions(findings: tuple[AdmittedFinding, ...]) -> tuple[AnswerAssertion, ...]:
    """Build one certificate-backed factual assertion per admitted assertion.

    Only admitted findings contribute; every emitted assertion is ``FACTUAL``
    and bound to its finding's certificate id (R1 §17.4).
    """
    out: list[AnswerAssertion] = []
    for finding in findings:
        if not finding.is_usable():
            continue
        claim = finding.claim
        certificate_id = finding.certificate.certificate_id
        for assertion in claim.assertions:
            out.append(
                AnswerAssertion(
                    text=_sentence(
                        claim.subject_id,
                        assertion.metric,
                        assertion.asserted_value,
                        assertion.unit,
                    ),
                    kind=AssertionKind.FACTUAL,
                    claim_certificate_id=certificate_id,
                    subject_id=claim.subject_id,
                    metric=assertion.metric,
                    value=assertion.asserted_value,
                    unit=assertion.unit,
                    citation_evidence_ids=claim.evidence_ids,
                )
            )
    return tuple(out)


# --------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------


def _requirement_addressed(
    requirement: AnswerRequirement, assertions: tuple[AnswerAssertion, ...]
) -> bool:
    """Whether some factual assertion addresses *requirement*.

    When the requirement names a ``subject_id`` and/or ``metric``, match on
    those fields (all named fields must agree). Otherwise fall back to a
    case-insensitive keyword from the requirement text appearing in an
    assertion's metric or subject.
    """
    if requirement.subject_id is not None or requirement.metric is not None:
        for assertion in assertions:
            subject_ok = (
                requirement.subject_id is None
                or assertion.subject_id == requirement.subject_id
            )
            metric_ok = requirement.metric is None or assertion.metric == requirement.metric
            if subject_ok and metric_ok:
                return True
        return False

    tokens = [
        token
        for token in re.split(r"\W+", requirement.text.lower())
        if len(token) >= _MIN_KEYWORD_LEN
    ]
    for assertion in assertions:
        haystack = f"{assertion.metric or ''} {assertion.subject_id or ''}".lower()
        haystack = haystack.replace("_", " ")
        if any(token in haystack for token in tokens):
            return True
    return False


def _coverage(
    requirements: tuple[AnswerRequirement, ...],
    assertions: tuple[AnswerAssertion, ...],
) -> tuple[Decimal, tuple[RequirementCoverage, ...], tuple[str, ...]]:
    """Compute the weighted coverage score, per-requirement rows, and unresolved ids."""
    per_requirement: list[RequirementCoverage] = []
    unresolved: list[str] = []
    numerator = Decimal(0)
    denominator = Decimal(0)
    for requirement in requirements:
        addressed = _requirement_addressed(requirement, assertions)
        satisfaction = Decimal(1) if addressed else Decimal(0)
        per_requirement.append(
            RequirementCoverage(
                requirement_id=requirement.requirement_id,
                satisfaction=satisfaction,
                satisfied=addressed,
            )
        )
        numerator += requirement.weight * satisfaction
        denominator += requirement.weight
        if not addressed:
            unresolved.append(requirement.requirement_id)
    score = (numerator / denominator) if denominator > 0 else Decimal(0)
    return score, tuple(per_requirement), tuple(unresolved)


def _status(
    requirements: tuple[AnswerRequirement, ...],
    assertions: tuple[AnswerAssertion, ...],
    score: Decimal,
) -> AnswerStatus:
    """Map requirements, available findings, and coverage to a response status."""
    if not requirements:
        return AnswerStatus.UNANSWERABLE
    if not assertions:
        return AnswerStatus.INSUFFICIENT_EVIDENCE
    if score >= _COMPLETE_THRESHOLD:
        return AnswerStatus.COMPLETE_ANSWER
    return AnswerStatus.PARTIAL_ANSWER


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def _sections(assertions: tuple[AnswerAssertion, ...]) -> tuple[AnswerSection, ...]:
    """Group factual assertions into headed sections by subject, order-stable."""
    order: list[str] = []
    groups: dict[str, list[AnswerAssertion]] = {}
    for assertion in assertions:
        heading = assertion.subject_id or "Findings"
        if heading not in groups:
            groups[heading] = []
            order.append(heading)
        groups[heading].append(assertion)
    return tuple(
        AnswerSection(heading=heading, assertions=tuple(groups[heading]))
        for heading in order
    )


def _citations(assertions: tuple[AnswerAssertion, ...]) -> tuple[str, ...]:
    """Collect the cited evidence ids across all assertions, order-stable, deduped."""
    seen: set[str] = set()
    ordered: list[str] = []
    for assertion in assertions:
        for evidence_id in assertion.citation_evidence_ids:
            if evidence_id not in seen:
                seen.add(evidence_id)
                ordered.append(evidence_id)
    return tuple(ordered)


def _limitations(
    requirements: tuple[AnswerRequirement, ...],
    assertions: tuple[AnswerAssertion, ...],
    unresolved: tuple[str, ...],
) -> tuple[str, ...]:
    """Build the limitations notes describing what the answer could not cover."""
    notes: list[str] = []
    if requirements and not assertions:
        notes.append("No admitted findings were available to answer the question.")
    if unresolved:
        by_id = {req.requirement_id: req.text for req in requirements}
        unresolved_texts = [by_id[rid] for rid in unresolved if rid in by_id]
        if unresolved_texts:
            notes.append(
                "Not addressed by admitted evidence: " + "; ".join(unresolved_texts) + "."
            )
    return tuple(notes)


def _answer_text(
    question: str,
    assertions: tuple[AnswerAssertion, ...],
    limitations: tuple[str, ...],
) -> str:
    """Compose the prose answer: a lead, the finding sentences, then limitations.

    The text must read as an answer — it opens by addressing the question, then
    states each finding in words (magnitude and direction), and closes with a
    limitations note when coverage is incomplete. It is never a list of ids.
    """
    question_text = question.strip()
    if assertions:
        lead = (
            f"In response to the question “{question_text}”, "
            "the verified evidence shows the following."
        )
        body = " ".join(assertion.text for assertion in assertions)
        text = f"{lead} {body}"
    else:
        text = (
            f"The question “{question_text}” could not be answered from the "
            "admitted evidence; no verified findings were available."
        )
    if limitations:
        text = f"{text} Limitations: {' '.join(limitations)}"
    return text


def synthesize(
    question: str,
    requirements: tuple[AnswerRequirement, ...],
    findings: tuple[AdmittedFinding, ...],
) -> VerifiedResearchResponse:
    """Render a deterministic natural-language answer from admitted findings.

    Builds one certificate-backed ``FACTUAL`` assertion per assertion of each
    *admitted* finding (non-admitted findings are ignored), groups them into
    sections, computes weighted requirement coverage, and assembles a
    substantive prose answer with coverage, status, and limitations. No language
    model is used (R1 §16). Final fail-closed validation is applied by the
    pipeline; ``validation`` here is a placeholder ``ok`` result (R1 §17.5).
    """
    factual = _factual_assertions(findings)
    score, per_requirement, unresolved = _coverage(requirements, factual)
    status = _status(requirements, factual, score)
    limitations = _limitations(requirements, factual, unresolved)
    coverage = AnswerCoverage(
        score=score,
        per_requirement=per_requirement,
        status=status,
    )
    return VerifiedResearchResponse(
        question=question,
        answer_text=_answer_text(question, factual, limitations),
        sections=_sections(factual),
        factual_assertions=factual,
        analytical_inferences=(),
        hypotheses=(),
        citations=_citations(factual),
        coverage=coverage,
        answer_status=status,
        limitations=limitations,
        unresolved_requirements=unresolved,
        validation=AnswerValidationResult(ok=True, unsupported_assertions=(), issues=()),
    )
