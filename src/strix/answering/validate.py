"""Independent, fail-closed validation of a rendered response (R1 §17.4).

Every *material factual* assertion STRIX makes must map to an **admitted** claim
certificate, and the number it states must be the number that claim was certified
for (R1 §17.4). This module re-checks that binding independently of whoever built
the response, treating anything it cannot positively confirm as unsupported:

- :class:`AdmittedFinding` bundles, for one admitted claim, the
  :class:`~strix.evidence_graph.certificates.ClaimCertificate`, the
  :class:`~strix.evidence_graph.nodes.CandidateClaim` it certifies, and the
  :class:`~strix.evidence_graph.predicates.AdmissionDecision` that admitted it.
- :func:`validate_response` checks each factual assertion against its backing
  finding and returns an :class:`~strix.answering.models.AnswerValidationResult`.
- :func:`strip_unsupported` removes the assertions that failed (and their
  sentences from the prose), re-labels, and returns a corrected response.

Analytical inferences and hypotheses are explicitly non-factual: they are allowed
without a certificate, but — enforced by the model layer — they may not be
labelled ``FACTUAL``. Only ``FACTUAL`` assertions are subjected to support
validation here.
"""

from __future__ import annotations

from decimal import Decimal

from strix.answering.models import (
    AnswerAssertion,
    AnsweringError,
    AnswerSection,
    AnswerValidationResult,
    AssertionKind,
    VerifiedResearchResponse,
)
from strix.answering.synthesize import AdmittedFinding
from strix.evidence_graph.certificates import (
    validate_claim_certificate,
)
from strix.evidence_graph.nodes import AdmissionOutcome

__all__ = [
    "AdmittedFinding",
    "strip_unsupported",
    "validate_response",
]


def _values_match(asserted: Decimal, certified: Decimal, tolerance: Decimal) -> bool:
    """True iff *asserted* equals *certified* within an exact/epsilon band.

    Comparison is exact :class:`~decimal.Decimal` arithmetic; ``tolerance`` is
    the certificate's numerical tolerance (``0`` means an exact match is
    required). No ``float`` ever participates.
    """
    return abs(asserted - certified) <= tolerance


def _assertion_support_issue(
    assertion: AnswerAssertion,
    admitted_certificate_ids: frozenset[str],
    findings_by_cert_id: dict[str, AdmittedFinding],
) -> str | None:
    """Return a reason *assertion* is unsupported, or ``None`` if it is supported.

    Fail-closed: any absent, unknown, non-admitted, tampered, mismatched, or
    mis-cited binding yields a reason string; only a fully confirmed binding
    returns ``None``.
    """
    cert_id = assertion.claim_certificate_id
    if not cert_id:
        return "factual assertion carries no claim_certificate_id"
    if cert_id not in admitted_certificate_ids:
        return f"claim_certificate_id {cert_id!r} is not in the admitted set"
    finding = findings_by_cert_id.get(cert_id)
    if finding is None:
        return f"no admitted finding backs claim_certificate_id {cert_id!r}"

    # The finding's certificate must be untampered and self-consistent.
    if finding.certificate.certificate_id != cert_id:
        return f"backing certificate id does not match {cert_id!r}"
    if not validate_claim_certificate(finding.certificate):
        return f"backing certificate {cert_id!r} fails integrity validation"
    if finding.decision.outcome is not AdmissionOutcome.ADMITTED:
        return (
            f"backing finding for {cert_id!r} was not admitted "
            f"(outcome={finding.decision.outcome.value})"
        )

    # The asserted (subject, metric, value, unit) must all be present.
    if assertion.subject_id is None:
        return "factual assertion names no subject"
    if assertion.metric is None:
        return "factual assertion names no metric"
    if assertion.value is None:
        return "factual assertion carries no value"
    if assertion.unit is None:
        return "factual assertion carries no unit"

    claim = finding.claim
    if assertion.subject_id != claim.subject_id:
        return (
            f"subject {assertion.subject_id!r} does not match the certified "
            f"subject {claim.subject_id!r}"
        )

    tolerance = finding.certificate.numerical_tolerance or Decimal(0)
    metric_unit_matches = [
        a
        for a in claim.assertions
        if a.metric == assertion.metric and a.unit == assertion.unit
    ]
    if not metric_unit_matches:
        return (
            f"no certified assertion for metric {assertion.metric!r} in "
            f"unit {assertion.unit!r}"
        )
    if not any(
        _values_match(assertion.value, a.asserted_value, tolerance)
        for a in metric_unit_matches
    ):
        return (
            f"value {assertion.value} does not match the certified value "
            f"for metric {assertion.metric!r}"
        )

    # Every cited evidence id must be part of the backing claim's evidence.
    backing_evidence = set(claim.evidence_ids)
    for evidence_id in assertion.citation_evidence_ids:
        if evidence_id not in backing_evidence:
            return (
                f"cited evidence {evidence_id!r} is not among the backing "
                f"claim's evidence"
            )
    return None


def validate_response(
    response: VerifiedResearchResponse,
    admitted_certificate_ids: frozenset[str],
    findings_by_cert_id: dict[str, AdmittedFinding],
) -> AnswerValidationResult:
    """Confirm every factual assertion maps to an admitted, matching finding.

    For each ``FACTUAL`` assertion in *response*, require that its
    ``claim_certificate_id`` is present, in *admitted_certificate_ids*, and backed
    by an :class:`AdmittedFinding` whose certificate is untampered and admitted,
    whose claim asserts the same ``(subject, metric, value, unit)`` (within the
    certificate's numerical tolerance), and which backs every cited evidence id.
    Non-factual assertions are not checked. Returns ``ok=False`` with the
    offending assertion texts and human-readable issues when any factual
    assertion is unsupported. Fail-closed: anything not positively confirmed is
    treated as unsupported.
    """
    unsupported: list[str] = []
    issues: list[str] = []
    for assertion in response.factual_assertions:
        if assertion.kind is not AssertionKind.FACTUAL:
            # The response partitions by kind; a non-factual assertion filed under
            # factual_assertions is itself a fail-closed violation.
            unsupported.append(assertion.text)
            issues.append(
                f"assertion {assertion.text!r} is filed as factual but labelled "
                f"{assertion.kind.value}"
            )
            continue
        reason = _assertion_support_issue(
            assertion, admitted_certificate_ids, findings_by_cert_id
        )
        if reason is not None:
            unsupported.append(assertion.text)
            issues.append(f"{assertion.text!r}: {reason}")
    return AnswerValidationResult(
        ok=not unsupported,
        unsupported_assertions=tuple(unsupported),
        issues=tuple(issues),
    )


def _scrub_sentence(text: str, sentence: str) -> str:
    """Remove *sentence* from *text* and collapse the resulting whitespace."""
    cleaned = text.replace(sentence, " ")
    return " ".join(cleaned.split())


def strip_unsupported(
    response: VerifiedResearchResponse,
    validation: AnswerValidationResult,
) -> VerifiedResearchResponse:
    """Return *response* with its unsupported factual assertions removed.

    Drops every factual assertion whose text appears in
    ``validation.unsupported_assertions`` — from ``factual_assertions``, from each
    section, and (its sentence) from ``answer_text`` — recomputes the citation
    list from the survivors, and re-labels the response with a fresh ``ok=True``
    :class:`~strix.answering.models.AnswerValidationResult`. When nothing is
    unsupported the response is returned with a clean validation stamp unchanged.
    """
    if validation.ok:
        return response.model_copy(
            update={
                "validation": AnswerValidationResult(
                    ok=True, unsupported_assertions=(), issues=()
                )
            }
        )

    dropped = set(validation.unsupported_assertions)

    def _keep(assertion: AnswerAssertion) -> bool:
        # Only factual assertions are ever stripped; non-factual ones survive even
        # if (defensively) their text collides with a dropped sentence.
        if assertion.kind is not AssertionKind.FACTUAL:
            return True
        return assertion.text not in dropped

    kept_factual = tuple(a for a in response.factual_assertions if _keep(a))
    kept_sections = tuple(
        AnswerSection(
            heading=section.heading,
            assertions=tuple(a for a in section.assertions if _keep(a)),
        )
        for section in response.sections
    )

    answer_text = response.answer_text
    for sentence in dropped:
        answer_text = _scrub_sentence(answer_text, sentence)

    # Re-derive citations (order-stable, de-duplicated) from the survivors.
    citations: list[str] = []
    seen: set[str] = set()
    for assertion in kept_factual:
        for evidence_id in assertion.citation_evidence_ids:
            if evidence_id not in seen:
                seen.add(evidence_id)
                citations.append(evidence_id)

    corrected = response.model_copy(
        update={
            "answer_text": answer_text,
            "sections": kept_sections,
            "factual_assertions": kept_factual,
            "citations": tuple(citations),
            "validation": AnswerValidationResult(
                ok=True, unsupported_assertions=(), issues=()
            ),
        }
    )
    # Guard the invariant: after stripping, nothing unsupported may remain.
    if corrected.factual_assertions and any(
        a.text in dropped for a in corrected.factual_assertions
    ):  # pragma: no cover - defensive
        raise AnsweringError("strip_unsupported left an unsupported factual assertion")
    return corrected
