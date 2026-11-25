"""Assurance inspector: independently re-verify and summarize a governed run (§4).

The decision-traceability pillar made inspectable. Given a
:class:`GovernedResearchResult` and the audit ledger it was written to, the
inspector RE-VERIFIES the audit hash chain and (when the signed certificates are
supplied) the certificate signatures, and summarizes the gateway decision into an
:class:`AssuranceReport`. Nothing is trusted on its word — the chain and signatures
are checked from scratch, so tampering surfaces rather than passing silently.

This is a read-only reporting surface over the existing governed lifecycle; it
assigns no factual verdict and performs no live execution.
"""

from __future__ import annotations

from collections.abc import Sequence

from strix.assurance.gateway import GatewayOutcome
from strix.assurance.lifecycle import GovernedResearchResult
from strix.assurance.signing import verify_signature
from strix.audit.ledger import EventLedger
from strix.models import StrixModel

#: Default domain the governed lifecycle signs claim certificates under.
CLAIM_SIGNING_DOMAIN = "strix.claim"

#: Gateway outcomes under which an answer is released to the caller.
_RELEASED_OUTCOMES = frozenset({GatewayOutcome.AUTHORIZED, GatewayOutcome.QUALIFIED})


class AssuranceReport(StrixModel):
    """An independently re-verified summary of one governed run."""

    run_id: str
    gateway_outcome: str
    answer_released: bool
    answer_status: str
    uncertainty_level: str
    reason_codes: tuple[str, ...]
    audit_event_count: int
    audit_chain_verified: bool
    audit_chain_issue_count: int
    signatures_present: int
    #: ``True``/``False`` when certificates were supplied and re-verified; ``None``
    #: when signatures are present but were not independently checked.
    signatures_verified: bool | None


def inspect_governed_result(
    result: GovernedResearchResult,
    ledger: EventLedger,
    run_id: str,
    *,
    signed_certificates: Sequence[StrixModel] = (),
    signing_domain: str = CLAIM_SIGNING_DOMAIN,
) -> AssuranceReport:
    """Re-verify ``result`` against ``ledger`` and summarize it.

    ``signed_certificates`` must be the certificates that were signed, in the same
    order as ``result.signatures``; when supplied (and a keyring is present) every
    signature is re-verified pairwise. Omit them to skip signature checking
    (``signatures_verified`` is then ``None``).
    """
    chain = ledger.verify_chain(run_id)

    signatures_verified: bool | None = None
    if signed_certificates and result.signatures and result.keyring is not None:
        if len(signed_certificates) == len(result.signatures):
            signatures_verified = all(
                verify_signature(
                    certificate, signature, result.keyring, expected_domain=signing_domain
                )
                for certificate, signature in zip(
                    signed_certificates, result.signatures, strict=True
                )
            )
        else:
            # A count mismatch cannot be reconciled → fail closed.
            signatures_verified = False

    return AssuranceReport(
        run_id=run_id,
        gateway_outcome=result.gateway_decision.outcome.value,
        answer_released=result.gateway_decision.outcome in _RELEASED_OUTCOMES,
        answer_status=result.response.answer_status.value,
        uncertainty_level=result.uncertainty.level.value,
        reason_codes=tuple(result.gateway_decision.reason_codes),
        audit_event_count=chain.event_count,
        audit_chain_verified=chain.ok,
        audit_chain_issue_count=len(chain.issues),
        signatures_present=len(result.signatures),
        signatures_verified=signatures_verified,
    )


def render_assurance_report(report: AssuranceReport) -> str:
    """Render an :class:`AssuranceReport` as human-readable text."""
    if report.signatures_verified is None:
        sig_line = f"{report.signatures_present} present (not independently checked)"
    else:
        verdict = "VERIFIED" if report.signatures_verified else "FAILED"
        sig_line = f"{report.signatures_present} present, re-verification {verdict}"
    chain_line = "VERIFIED" if report.audit_chain_verified else (
        f"FAILED ({report.audit_chain_issue_count} issue(s))"
    )
    lines = [
        f"Assurance report for run {report.run_id}",
        f"  gateway outcome:   {report.gateway_outcome}",
        f"  answer released:   {report.answer_released}",
        f"  answer status:     {report.answer_status}",
        f"  uncertainty level: {report.uncertainty_level}",
        f"  reason codes:      {', '.join(report.reason_codes) or '(none)'}",
        f"  audit events:      {report.audit_event_count}",
        f"  audit chain:       {chain_line}",
        f"  signatures:        {sig_line}",
    ]
    return "\n".join(lines)
