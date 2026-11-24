"""The answer-first synthesis loop and its Markdown surface (R1 §16, §17.5).

This is the deterministic answer path's top level: given a question, the things
the question demands be addressed, and the admitted findings, produce a
:class:`~strix.answering.models.VerifiedResearchResponse` that *actually answers*
the question in natural language and in which **every** material factual
assertion maps to an admitted claim (R1 §17.4).

The loop (R1 §17.5):

1. :func:`~strix.answering.synthesize.synthesize` a draft answer from the
   admitted findings.
2. Build the admitted certificate-id set and the ``certificate_id -> finding``
   map the validator checks against.
3. :func:`~strix.answering.validate.validate_response` the draft, independently
   of how it was built.
4. If it is not ``ok``, :func:`~strix.answering.validate.strip_unsupported` the
   offending assertions, drop their backing findings, and re-synthesize so
   coverage, status, and limitations reflect the corrected set — bounded to at
   most :data:`_MAX_CORRECTION_PASSES` passes.
5. Attach the final :class:`~strix.answering.models.AnswerValidationResult`.
6. Return the response.

The returned response never contains an unsupported factual assertion, and it
always presents a substantive answer — including a deterministic
``insufficient_evidence`` answer that states what is missing when coverage is
empty, rather than falling back to an evidence dump (R1 §16).

:func:`render_markdown` renders that response as the clean answer-first Markdown
surface used by the CLI and API: a lead answer, finding bullets with inline
numbered citations, a Limitations section, and an unresolved-requirements note.
"""

from __future__ import annotations

from strix.answering.models import (
    AnswerAssertion,
    AnswerRequirement,
    VerifiedResearchResponse,
)
from strix.answering.synthesize import AdmittedFinding, synthesize
from strix.answering.validate import strip_unsupported, validate_response

__all__ = [
    "answer_question",
    "render_markdown",
]

#: Maximum number of correction passes after the initial synthesis. Each pass
#: removes the findings whose assertions failed validation and re-synthesizes; a
#: small bound keeps the loop terminating while giving independent mismatches
#: room to be cleared.
_MAX_CORRECTION_PASSES = 2


# --------------------------------------------------------------------------
# Validation inputs
# --------------------------------------------------------------------------


def _validation_inputs(
    findings: tuple[AdmittedFinding, ...],
) -> tuple[frozenset[str], dict[str, AdmittedFinding]]:
    """Build the admitted certificate-id set and ``cert_id -> finding`` map.

    Only *admitted* findings may back a factual assertion, so only they are
    offered to the validator.
    """
    cert_ids: set[str] = set()
    by_cert_id: dict[str, AdmittedFinding] = {}
    for finding in findings:
        if not finding.is_usable():
            continue
        cert_id = finding.certificate.certificate_id
        cert_ids.add(cert_id)
        by_cert_id[cert_id] = finding
    return frozenset(cert_ids), by_cert_id


def _unsupported_certificate_ids(
    assertions: tuple[AnswerAssertion, ...],
    unsupported_texts: tuple[str, ...],
) -> set[str]:
    """Collect the certificate ids backing the assertions that failed validation."""
    dropped = set(unsupported_texts)
    offending: set[str] = set()
    for assertion in assertions:
        if assertion.text in dropped and assertion.claim_certificate_id is not None:
            offending.add(assertion.claim_certificate_id)
    return offending


# --------------------------------------------------------------------------
# Answer-first synthesis loop
# --------------------------------------------------------------------------


def answer_question(
    question: str,
    requirements: tuple[AnswerRequirement, ...],
    findings: tuple[AdmittedFinding, ...],
) -> VerifiedResearchResponse:
    """Produce a validated, answer-first research response (R1 §17.5).

    Synthesizes a draft answer from the admitted *findings*, validates that every
    factual assertion maps to an admitted claim, and — if any does not — strips it
    and re-synthesizes on the corrected set so coverage, status, and limitations
    stay truthful, bounded to :data:`_MAX_CORRECTION_PASSES` correction passes.
    The returned :class:`~strix.answering.models.VerifiedResearchResponse` never
    contains an unsupported factual assertion and always presents a substantive
    answer, including a deterministic ``insufficient_evidence`` answer that states
    what is missing when no admitted finding supports the question (R1 §16, §17.4).
    """
    current = findings
    response = synthesize(question, requirements, current)
    cert_ids, by_cert_id = _validation_inputs(current)
    validation = validate_response(response, cert_ids, by_cert_id)

    passes = 0
    while not validation.ok and passes < _MAX_CORRECTION_PASSES:
        passes += 1
        offending = _unsupported_certificate_ids(
            response.factual_assertions, validation.unsupported_assertions
        )
        # Re-synthesize on the corrected set so coverage/status/limitations are
        # recomputed for exactly the findings that remain valid.
        current = tuple(
            f for f in current if f.certificate.certificate_id not in offending
        )
        response = synthesize(question, requirements, current)
        cert_ids, by_cert_id = _validation_inputs(current)
        validation = validate_response(response, cert_ids, by_cert_id)

    if not validation.ok:
        # Fail-closed guarantee: if anything unsupported still survives the bounded
        # loop, strip it outright and re-validate the survivors.
        response = strip_unsupported(response, validation)
        validation = validate_response(response, cert_ids, by_cert_id)

    return response.model_copy(update={"validation": validation})


# --------------------------------------------------------------------------
# Markdown rendering
# --------------------------------------------------------------------------


def _citation_marker(
    assertion: AnswerAssertion, cite_index: dict[str, int]
) -> str:
    """Render an assertion's citations as inline ``[n]`` markers, order-stable."""
    markers = [
        f"[{cite_index[evidence_id]}]"
        for evidence_id in assertion.citation_evidence_ids
        if evidence_id in cite_index
    ]
    return "".join(markers)


def render_markdown(response: VerifiedResearchResponse) -> str:
    """Render *response* as the clean, answer-first Markdown surface.

    Produces a lead answer, finding bullets with inline numbered ``[n]``
    citations, a Limitations section, an unresolved-requirements note, and a
    numbered citation list. The lead is the prose answer with its inline
    limitations tail removed (those appear under their own heading), so the page
    reads as an answer rather than an evidence dump (R1 §17.1).
    """
    cite_index = {
        evidence_id: position
        for position, evidence_id in enumerate(response.citations, start=1)
    }

    lines: list[str] = ["## Answer", ""]
    lead = response.answer_text.split(" Limitations:")[0].strip()
    lines.append(lead)
    lines.append("")

    if response.factual_assertions:
        lines.append("### Findings")
        for assertion in response.factual_assertions:
            marker = _citation_marker(assertion, cite_index)
            suffix = f" {marker}" if marker else ""
            lines.append(f"- {assertion.text}{suffix}")
        lines.append("")

    if response.analytical_inferences:
        lines.append("### Interpretation")
        for assertion in response.analytical_inferences:
            lines.append(f"- {assertion.text}")
        lines.append("")

    if response.hypotheses:
        lines.append("### Hypotheses")
        for assertion in response.hypotheses:
            lines.append(f"- {assertion.text}")
        lines.append("")

    lines.append("### Limitations")
    if response.limitations:
        lines.extend(f"- {note}" for note in response.limitations)
    else:
        lines.append("- None noted.")
    lines.append("")

    lines.append("### Unresolved requirements")
    if response.unresolved_requirements:
        lines.extend(
            f"- {requirement_id}" for requirement_id in response.unresolved_requirements
        )
    else:
        lines.append("- None; every requirement was addressed by admitted evidence.")

    if cite_index:
        lines.append("")
        lines.append("### Citations")
        lines.extend(
            f"{position}. {evidence_id}"
            for evidence_id, position in cite_index.items()
        )

    return "\n".join(lines) + "\n"
