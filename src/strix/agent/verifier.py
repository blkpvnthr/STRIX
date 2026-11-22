"""Independent verification of agent claims.

This is the trusted component. It is deliberately independent of the language
model: for a quantitative claim it recomputes the number from the preserved
observation series using :mod:`strix.agent.calculations` and accepts the claim
only if the recomputation reproduces the asserted value within tolerance. It
never compares one model-produced value against another.

Honesty about scope:

- Quantitative / historical-comparison claims with a calculation: fully
  recomputed -> VERIFIED, CONTRADICTED, or INSUFFICIENT_EVIDENCE.
- Observation / attributed-statement claims: a *bounded* textual check only —
  the asserted text (or anchor) must appear in a cited, preserved source
  excerpt. This verifies the source was retrieved and contains the text, not
  that the underlying assertion is objectively true.
- Interpretation / hypothesis / forecast claims: never VERIFIED. They are
  marked UNVERIFIABLE by type (they may still be well-formed and cited).

A claim with no resolvable citation is INSUFFICIENT_EVIDENCE. A VERIFIED claim
whose backing evidence is stale is downgraded to STALE.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from strix.agent.calculations import recompute
from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import (
    AgentClaim,
    AgentClaimType,
    AgentVerificationStatus,
    ClaimVerification,
    FreshnessStatus,
    ObservationSeries,
)
from strix.errors import CalculationError

#: Version stamped on every verdict; bump when verification logic changes.
VERIFIER_VERSION = "agent-verify-1.0.0"

#: Default absolute tolerance for recomputed vs asserted numeric values.
DEFAULT_TOLERANCE = Decimal("0.0001")


def verify_claim(
    claim: AgentClaim,
    collector: EvidenceCollector,
    *,
    now: datetime,
    tolerance: Decimal = DEFAULT_TOLERANCE,
) -> AgentClaim:
    """Return a copy of ``claim`` with an independent verification verdict."""
    verdict = _decide(claim, collector, now=now, tolerance=tolerance)
    return claim.model_copy(update={"verification": verdict})


def verify_claims(
    claims: tuple[AgentClaim, ...] | list[AgentClaim],
    collector: EvidenceCollector,
    *,
    now: datetime,
    tolerance: Decimal = DEFAULT_TOLERANCE,
) -> tuple[AgentClaim, ...]:
    return tuple(verify_claim(c, collector, now=now, tolerance=tolerance) for c in claims)


# --------------------------------------------------------------------------
# Decision logic
# --------------------------------------------------------------------------


def _decide(
    claim: AgentClaim,
    collector: EvidenceCollector,
    *,
    now: datetime,
    tolerance: Decimal,
) -> ClaimVerification:
    # 1. Citations must resolve.
    if not claim.evidence_ids:
        return _verdict(AgentVerificationStatus.INSUFFICIENT_EVIDENCE, now, reason="no citations")
    unknown = [eid for eid in claim.evidence_ids if collector.evidence(eid) is None]
    if unknown:
        return _verdict(
            AgentVerificationStatus.INSUFFICIENT_EVIDENCE,
            now,
            reason=f"cites unknown evidence: {', '.join(unknown)}",
        )

    # 2. Interpretive types are never independently verified.
    if claim.claim_type in (
        AgentClaimType.INTERPRETATION,
        AgentClaimType.HYPOTHESIS,
        AgentClaimType.FORECAST,
    ):
        return _verdict(
            AgentVerificationStatus.UNVERIFIABLE,
            now,
            reason=f"{claim.claim_type.value} claims are not independently verifiable",
            method="type_policy",
        )

    # 3. Quantitative / comparison claims: recompute from preserved series.
    if claim.calculation is not None:
        return _verify_numeric(claim, collector, now=now, tolerance=tolerance)

    # 4. A quantitative claim with no calculation cannot be recomputed.
    if claim.claim_type in (
        AgentClaimType.QUANTITATIVE,
        AgentClaimType.HISTORICAL_COMPARISON,
    ):
        return _verdict(
            AgentVerificationStatus.INSUFFICIENT_EVIDENCE,
            now,
            reason="quantitative claim provides no calculation to recompute",
        )

    # 5. Observation / attributed statement: bounded textual presence check.
    return _verify_textual(claim, collector, now=now)


def _verify_numeric(
    claim: AgentClaim,
    collector: EvidenceCollector,
    *,
    now: datetime,
    tolerance: Decimal,
) -> ClaimVerification:
    calc = claim.calculation
    assert calc is not None
    series: list[ObservationSeries] = []
    for series_id in calc.input_series_ids:
        found = collector.series(series_id)
        if found is None:
            return _verdict(
                AgentVerificationStatus.INSUFFICIENT_EVIDENCE,
                now,
                reason=f"missing observation series {series_id}",
                method=calc.method.value,
            )
        series.append(found)

    # Every backing series must trace to evidence the claim actually cites.
    for s in series:
        if s.source_evidence_id not in claim.evidence_ids:
            return _verdict(
                AgentVerificationStatus.INSUFFICIENT_EVIDENCE,
                now,
                reason=f"series {s.series_id} rests on uncited evidence "
                f"{s.source_evidence_id}",
                method=calc.method.value,
            )

    try:
        computed = recompute(calc.method, [s.values for s in series], calc.parameters)
    except CalculationError as exc:
        return _verdict(
            AgentVerificationStatus.INSUFFICIENT_EVIDENCE,
            now,
            reason=f"recomputation failed: {exc}",
            method=calc.method.value,
        )

    if abs(computed - calc.claimed_value) > tolerance:
        return _verdict(
            AgentVerificationStatus.CONTRADICTED,
            now,
            reason=f"recomputed {computed} differs from claimed {calc.claimed_value} "
            f"(tolerance {tolerance})",
            method=calc.method.value,
            computed_value=computed,
            tolerance=tolerance,
        )

    # Verified — but a stale source downgrades the verdict to STALE.
    if _has_stale_evidence(claim, collector):
        return _verdict(
            AgentVerificationStatus.STALE,
            now,
            reason="recomputed value matches, but backing evidence is stale",
            method=calc.method.value,
            computed_value=computed,
            tolerance=tolerance,
        )
    return _verdict(
        AgentVerificationStatus.VERIFIED,
        now,
        method=calc.method.value,
        computed_value=computed,
        tolerance=tolerance,
    )


def _verify_textual(
    claim: AgentClaim, collector: EvidenceCollector, *, now: datetime
) -> ClaimVerification:
    needle = (claim.attributed_to or claim.statement).strip().lower()
    for eid in claim.evidence_ids:
        evidence = collector.evidence(eid)
        if evidence is None or not evidence.excerpt:
            continue
        if _text_present(needle, evidence.excerpt.lower()):
            status = (
                AgentVerificationStatus.STALE
                if evidence.freshness_status is FreshnessStatus.STALE
                else AgentVerificationStatus.VERIFIED
            )
            return _verdict(
                status,
                now,
                reason="asserted text appears in the preserved source excerpt "
                "(attribution only; not a claim the statement is objectively true)",
                method="source_attribution",
            )
    return _verdict(
        AgentVerificationStatus.INSUFFICIENT_EVIDENCE,
        now,
        reason="asserted text was not found in any cited preserved excerpt",
        method="source_attribution",
    )


def _text_present(needle: str, haystack: str) -> bool:
    """Strict attribution check: the asserted phrase must appear verbatim in the
    preserved excerpt (whitespace-normalized). No fuzzy/keyword matching — an
    attribution is accepted only when the source demonstrably contains the text,
    never on mere keyword overlap, so the verdict cannot over-claim."""
    needle = " ".join(needle.split())
    haystack = " ".join(haystack.split())
    return bool(needle) and needle in haystack


def _has_stale_evidence(claim: AgentClaim, collector: EvidenceCollector) -> bool:
    for eid in claim.evidence_ids:
        evidence = collector.evidence(eid)
        if evidence is not None and evidence.freshness_status is FreshnessStatus.STALE:
            return True
    return False


def _verdict(
    status: AgentVerificationStatus,
    now: datetime,
    *,
    reason: str | None = None,
    method: str | None = None,
    computed_value: Decimal | None = None,
    tolerance: Decimal | None = None,
) -> ClaimVerification:
    return ClaimVerification(
        status=status,
        computed_value=computed_value,
        method=method,
        reason=reason,
        tolerance=tolerance,
        verifier_version=VERIFIER_VERSION,
        verified_at=now,
    )
