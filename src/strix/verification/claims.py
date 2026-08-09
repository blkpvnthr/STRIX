"""Deterministic verification of evidence lineage and structured claims.

Two passes:

1. **Evidence lineage** — every evidence record must resolve through
   ``Evidence -> CalculationResult -> SourceFact -> SourceArtifact`` and its
   value/unit must match its calculation exactly. Evidence that fails any
   check is marked ``rejected``; the rest become ``verified``.

2. **Claim checks** — every cited evidence ID must exist, belong to the
   claim's subject, have been knowable by the as-of date, and be verified;
   every numeric assertion must match its evidence value and unit exactly;
   the required comparison evidence (previous margin, current margin,
   change) must all be cited; units must be supported for the claim type;
   the structured direction must match the sign of the change evidence; and
   the statement prose must equal the deterministic re-rendering from
   structured values (so displayed text can never drift from verified
   numbers).

The verifier performs no new financial calculation; its only independent
recomputations are the direction sign check and the prose re-rendering.
A report is publishable as verified only if at least one claim exists and
every claim verifies. No unrestricted natural-language entailment is
attempted.
"""

from __future__ import annotations

from datetime import UTC, datetime

from strix.formatting import direction_from_change, render_statement
from strix.models import (
    CalculationResult,
    Claim,
    ClaimStatus,
    ClaimType,
    Evidence,
    EvidenceStatus,
    FailureCode,
    Metric,
    ResearchSpec,
    SourceArtifact,
    SourceFact,
    Unit,
    VerificationFailure,
    VerificationResult,
    VerificationStatus,
)

#: Version recorded on every VerificationResult.
VERIFIER_VERSION = "1.0.0"

#: Units a profitability_change claim may assert.
_SUPPORTED_CLAIM_UNITS = frozenset({Unit.RATIO, Unit.PERCENTAGE_POINTS})


def verify(
    *,
    spec: ResearchSpec,
    artifact: SourceArtifact,
    facts: list[SourceFact],
    calculations: list[CalculationResult],
    evidence: list[Evidence],
    claims: list[Claim],
    checked_at: datetime,
) -> tuple[VerificationResult, list[Evidence], list[Claim]]:
    """Verify evidence lineage and claims; return result + updated statuses."""
    facts_by_id = {fact.fact_id: fact for fact in facts}
    calcs_by_id = {calc.calculation_id: calc for calc in calculations}

    failures: list[VerificationFailure] = []

    verified_evidence: list[Evidence] = []
    for item in evidence:
        item_failures = _verify_evidence_lineage(item, calcs_by_id, facts_by_id, artifact)
        failures.extend(item_failures)
        status = EvidenceStatus.VERIFIED if not item_failures else EvidenceStatus.REJECTED
        verified_evidence.append(item.model_copy(update={"status": status}))
    evidence_by_id = {item.evidence_id: item for item in verified_evidence}

    verified_claims: list[Claim] = []
    verified_ids: list[str] = []
    rejected_ids: list[str] = []
    for claim in claims:
        claim_failures = _verify_claim(claim, spec, evidence_by_id)
        failures.extend(claim_failures)
        if claim_failures:
            verified_claims.append(claim.model_copy(update={"status": ClaimStatus.REJECTED}))
            rejected_ids.append(claim.claim_id)
        else:
            verified_claims.append(claim.model_copy(update={"status": ClaimStatus.VERIFIED}))
            verified_ids.append(claim.claim_id)

    if not claims:
        failures.append(
            VerificationFailure(
                code=FailureCode.NO_CLAIMS,
                message="the reasoner produced no claims; nothing to publish",
            )
        )

    overall_status = (
        VerificationStatus.PASSED
        if claims and not rejected_ids and not failures
        else VerificationStatus.FAILED
    )
    result = VerificationResult(
        status=overall_status,
        verified_claim_ids=tuple(verified_ids),
        rejected_claim_ids=tuple(rejected_ids),
        failures=tuple(failures),
        checked_at=checked_at,
        verifier_version=VERIFIER_VERSION,
    )
    return result, verified_evidence, verified_claims


# --------------------------------------------------------------------------
# Pass 1: evidence lineage
# --------------------------------------------------------------------------


def _verify_evidence_lineage(
    item: Evidence,
    calcs_by_id: dict[str, CalculationResult],
    facts_by_id: dict[str, SourceFact],
    artifact: SourceArtifact,
) -> list[VerificationFailure]:
    failures: list[VerificationFailure] = []

    def fail(code: FailureCode, message: str) -> None:
        failures.append(
            VerificationFailure(code=code, message=message, evidence_id=item.evidence_id)
        )

    if not item.calculation_id or not item.source_fact_ids:
        fail(
            FailureCode.INCOMPLETE_LINEAGE,
            f"evidence {item.evidence_id} lacks a calculation or source facts",
        )
        return failures

    calc = calcs_by_id.get(item.calculation_id)
    if calc is None:
        fail(
            FailureCode.UNKNOWN_CALCULATION,
            f"evidence {item.evidence_id} cites unknown calculation {item.calculation_id}",
        )
        return failures

    if item.value != calc.value or item.unit is not calc.unit:
        fail(
            FailureCode.EVIDENCE_CALC_MISMATCH,
            f"evidence {item.evidence_id} value/unit differs from calculation "
            f"{calc.calculation_id}",
        )

    if not calc.input_fact_ids:
        fail(
            FailureCode.INCOMPLETE_LINEAGE,
            f"calculation {calc.calculation_id} records no input facts",
        )
        return failures

    if tuple(item.source_fact_ids) != tuple(calc.input_fact_ids):
        fail(
            FailureCode.INCOMPLETE_LINEAGE,
            f"evidence {item.evidence_id} source facts differ from calculation "
            f"{calc.calculation_id} inputs",
        )

    for fact_id in calc.input_fact_ids:
        fact = facts_by_id.get(fact_id)
        if fact is None:
            fail(
                FailureCode.MISSING_SOURCE_FACT,
                f"calculation {calc.calculation_id} references missing fact {fact_id}",
            )
            continue
        if fact.source_artifact_id != artifact.artifact_id:
            fail(
                FailureCode.ARTIFACT_MISMATCH,
                f"fact {fact_id} references artifact {fact.source_artifact_id}, "
                f"expected {artifact.artifact_id}",
            )
    return failures


# --------------------------------------------------------------------------
# Pass 2: claims
# --------------------------------------------------------------------------


def _verify_claim(
    claim: Claim,
    spec: ResearchSpec,
    evidence_by_id: dict[str, Evidence],
) -> list[VerificationFailure]:
    failures: list[VerificationFailure] = []

    def fail(code: FailureCode, message: str, evidence_id: str | None = None) -> None:
        failures.append(
            VerificationFailure(
                code=code, message=message, claim_id=claim.claim_id, evidence_id=evidence_id
            )
        )

    cited: list[Evidence] = []
    for evidence_id in claim.evidence_ids:
        item = evidence_by_id.get(evidence_id)
        if item is None:
            fail(
                FailureCode.UNKNOWN_EVIDENCE,
                f"claim {claim.claim_id} cites unknown evidence {evidence_id}",
                evidence_id,
            )
            continue
        cited.append(item)
        if item.subject_id != claim.subject_id or item.subject_id != spec.company_id:
            fail(
                FailureCode.SUBJECT_MISMATCH,
                f"evidence {evidence_id} belongs to subject {item.subject_id}, "
                f"not {spec.company_id}",
                evidence_id,
            )
        if item.known_at.astimezone(UTC).date() > spec.as_of_date:
            fail(
                FailureCode.EVIDENCE_AFTER_AS_OF,
                f"evidence {evidence_id} became known at {item.known_at.isoformat()}, "
                f"after the as-of date {spec.as_of_date.isoformat()}",
                evidence_id,
            )
        if item.status is not EvidenceStatus.VERIFIED:
            fail(
                FailureCode.EVIDENCE_NOT_VERIFIED,
                f"evidence {evidence_id} is {item.status.value}, not verified",
                evidence_id,
            )

    for assertion in claim.numeric_assertions:
        # Every asserted evidence must ALSO be cited by the claim, so it
        # passes the subject / as-of / verified-status gates above. Without
        # this, an assertion could smuggle in evidence that skips them.
        if assertion.evidence_id not in claim.evidence_ids:
            fail(
                FailureCode.ASSERTION_EVIDENCE_NOT_CITED,
                f"assertion on {assertion.metric.value} references evidence "
                f"{assertion.evidence_id} that the claim does not cite",
                assertion.evidence_id,
            )
            continue
        item = evidence_by_id.get(assertion.evidence_id)
        if item is None:
            fail(
                FailureCode.UNKNOWN_EVIDENCE,
                f"assertion on {assertion.metric.value} cites unknown evidence "
                f"{assertion.evidence_id}",
                assertion.evidence_id,
            )
            continue
        if assertion.unit not in _SUPPORTED_CLAIM_UNITS:
            fail(
                FailureCode.UNSUPPORTED_UNIT,
                f"unit {assertion.unit.value} is not supported for {claim.claim_type.value} claims",
                assertion.evidence_id,
            )
        if assertion.asserted_value != item.value:
            fail(
                FailureCode.ASSERTION_VALUE_MISMATCH,
                f"assertion on {assertion.metric.value} states "
                f"{assertion.asserted_value}, evidence {item.evidence_id} "
                f"holds {item.value}",
                item.evidence_id,
            )
        if assertion.unit is not item.unit:
            fail(
                FailureCode.ASSERTION_UNIT_MISMATCH,
                f"assertion on {assertion.metric.value} uses unit "
                f"{assertion.unit.value}, evidence {item.evidence_id} uses "
                f"{item.unit.value}",
                item.evidence_id,
            )

    if claim.claim_type is ClaimType.PROFITABILITY_CHANGE:
        failures.extend(_verify_comparison(claim, spec, cited))

    return failures


def _verify_comparison(
    claim: Claim,
    spec: ResearchSpec,
    cited: list[Evidence],
) -> list[VerificationFailure]:
    """Completeness, direction, and prose checks for a comparison claim."""
    failures: list[VerificationFailure] = []
    previous_period, current_period = spec.historical_periods

    def find(metric: Metric, period: str) -> Evidence | None:
        for item in cited:
            if item.metric is metric and item.observation_period == period:
                return item
        return None

    previous = find(Metric.OPERATING_MARGIN, previous_period)
    current = find(Metric.OPERATING_MARGIN, current_period)
    change = find(Metric.OPERATING_MARGIN_CHANGE_PP, f"{previous_period}..{current_period}")
    missing = [
        name
        for name, item in (
            (f"operating margin {previous_period}", previous),
            (f"operating margin {current_period}", current),
            ("operating margin change", change),
        )
        if item is None
    ]
    if missing:
        failures.append(
            VerificationFailure(
                code=FailureCode.MISSING_COMPARISON_EVIDENCE,
                message=f"claim {claim.claim_id} is missing required comparison "
                f"evidence: {', '.join(missing)}",
                claim_id=claim.claim_id,
            )
        )
        return failures
    assert previous is not None and current is not None and change is not None

    # Every required comparison value must be asserted numerically — a claim
    # cannot dodge the value/unit checks by simply omitting its assertions.
    asserted_ids = {assertion.evidence_id for assertion in claim.numeric_assertions}
    for role, item in (
        ("previous operating margin", previous),
        ("current operating margin", current),
        ("operating margin change", change),
    ):
        if item.evidence_id not in asserted_ids:
            failures.append(
                VerificationFailure(
                    code=FailureCode.MISSING_ASSERTION,
                    message=f"claim {claim.claim_id} asserts no numeric value "
                    f"for the {role} ({item.evidence_id})",
                    claim_id=claim.claim_id,
                    evidence_id=item.evidence_id,
                )
            )

    expected_direction = direction_from_change(change.value)
    if claim.direction is not expected_direction:
        failures.append(
            VerificationFailure(
                code=FailureCode.DIRECTION_MISMATCH,
                message=f"claim {claim.claim_id} states direction "
                f"{claim.direction.value}, but the change evidence implies "
                f"{expected_direction.value}",
                claim_id=claim.claim_id,
                evidence_id=change.evidence_id,
            )
        )

    expected_statement = render_statement(claim.direction, previous.value, current.value)
    if claim.statement != expected_statement:
        failures.append(
            VerificationFailure(
                code=FailureCode.STATEMENT_MISMATCH,
                message=f"claim {claim.claim_id} prose differs from the "
                f"deterministic rendering of its structured values",
                claim_id=claim.claim_id,
            )
        )
    return failures
