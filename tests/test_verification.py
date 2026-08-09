"""Verifier: every rejection rule, plus verified publication behavior."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from strix.models import (
    Claim,
    ClaimStatus,
    Direction,
    EvidenceStatus,
    FailureCode,
    ResearchSpec,
    Unit,
    VerificationStatus,
)
from strix.pipeline import DeterministicOutcome
from strix.verification.claims import verify
from tests.conftest import FIXED_NOW


def reverify(spec: ResearchSpec, outcome: DeterministicOutcome, **overrides):
    """Re-run verification with selectively tampered inputs."""
    kwargs = {
        "spec": spec,
        "artifact": outcome.artifact,
        "facts": list(outcome.facts),
        "calculations": list(outcome.calculations),
        "evidence": [
            item.model_copy(update={"status": EvidenceStatus.UNVERIFIED})
            for item in outcome.evidence
        ],
        "claims": [
            claim.model_copy(update={"status": ClaimStatus.PROPOSED}) for claim in outcome.claims
        ],
        "checked_at": FIXED_NOW,
    }
    kwargs.update(overrides)
    return verify(**kwargs)


def codes(result) -> set[FailureCode]:
    return {failure.code for failure in result.failures}


def tampered_claim(claim: Claim, **updates) -> Claim:
    return claim.model_copy(update=updates)


class TestHappyPath:
    def test_all_claims_verify(self, spec, outcome) -> None:
        result, evidence, claims = reverify(spec, outcome)
        assert result.status is VerificationStatus.PASSED
        assert not result.failures
        assert all(item.status is EvidenceStatus.VERIFIED for item in evidence)
        assert all(claim.status is ClaimStatus.VERIFIED for claim in claims)
        assert result.verified_claim_ids == tuple(c.claim_id for c in claims)

    def test_verifier_version_recorded(self, spec, outcome) -> None:
        result, _, _ = reverify(spec, outcome)
        assert result.verifier_version == "1.0.0"


class TestClaimRejections:
    def test_unknown_evidence_id(self, spec, outcome) -> None:
        claim = outcome.claims[0]
        bad = tampered_claim(claim, evidence_ids=(*claim.evidence_ids[:-1], "EV-000000000000"))
        result, _, claims = reverify(spec, outcome, claims=[bad])
        assert FailureCode.UNKNOWN_EVIDENCE in codes(result)
        assert result.status is VerificationStatus.FAILED
        assert claims[0].status is ClaimStatus.REJECTED

    def test_wrong_subject(self, spec, outcome) -> None:
        claim = tampered_claim(outcome.claims[0], subject_id="other-company-999")
        result, _, _ = reverify(spec, outcome, claims=[claim])
        assert FailureCode.SUBJECT_MISMATCH in codes(result)

    def test_evidence_after_as_of_date(self, outcome, spec) -> None:
        # As-of before the current period became knowable: point-in-time
        # correctness must reject the claim.
        early_spec = spec.model_copy(update={"as_of_date": date(2026, 1, 1)})
        result, _, _ = reverify(early_spec, outcome)
        assert FailureCode.EVIDENCE_AFTER_AS_OF in codes(result)
        assert result.status is VerificationStatus.FAILED

    def test_assertion_value_mismatch(self, spec, outcome) -> None:
        claim = outcome.claims[0]
        assertions = list(claim.numeric_assertions)
        assertions[0] = assertions[0].model_copy(update={"asserted_value": Decimal("0.999")})
        bad = tampered_claim(claim, numeric_assertions=tuple(assertions))
        result, _, _ = reverify(spec, outcome, claims=[bad])
        assert FailureCode.ASSERTION_VALUE_MISMATCH in codes(result)

    def test_assertion_unit_mismatch(self, spec, outcome) -> None:
        claim = outcome.claims[0]
        assertions = list(claim.numeric_assertions)
        # The change assertion in ratio units instead of percentage points:
        # the pp-vs-percent confusion the unit system exists to catch.
        assertions[2] = assertions[2].model_copy(update={"unit": Unit.RATIO})
        bad = tampered_claim(claim, numeric_assertions=tuple(assertions))
        result, _, _ = reverify(spec, outcome, claims=[bad])
        assert FailureCode.ASSERTION_UNIT_MISMATCH in codes(result)

    def test_unsupported_unit(self, spec, outcome) -> None:
        claim = outcome.claims[0]
        assertions = list(claim.numeric_assertions)
        assertions[0] = assertions[0].model_copy(update={"unit": Unit.USD})
        bad = tampered_claim(claim, numeric_assertions=tuple(assertions))
        result, _, _ = reverify(spec, outcome, claims=[bad])
        assert FailureCode.UNSUPPORTED_UNIT in codes(result)

    def test_missing_comparison_evidence(self, spec, outcome) -> None:
        claim = outcome.claims[0]
        bad = tampered_claim(claim, evidence_ids=claim.evidence_ids[:2])
        result, _, _ = reverify(spec, outcome, claims=[bad])
        assert FailureCode.MISSING_COMPARISON_EVIDENCE in codes(result)

    def test_direction_mismatch(self, spec, outcome) -> None:
        claim = tampered_claim(outcome.claims[0], direction=Direction.DECREASED)
        result, _, _ = reverify(spec, outcome, claims=[claim])
        assert FailureCode.DIRECTION_MISMATCH in codes(result)

    def test_statement_cannot_drift_from_structured_values(self, spec, outcome) -> None:
        claim = tampered_claim(
            outcome.claims[0],
            statement="Operating margin increased from 8.4% to 99.9%, an "
            "improvement of 91.5 percentage points.",
        )
        result, _, _ = reverify(spec, outcome, claims=[claim])
        assert FailureCode.STATEMENT_MISMATCH in codes(result)

    def test_no_claims_fails_verification(self, spec, outcome) -> None:
        result, _, _ = reverify(spec, outcome, claims=[])
        assert FailureCode.NO_CLAIMS in codes(result)
        assert result.status is VerificationStatus.FAILED


class TestLineageRejections:
    def test_missing_calculation(self, spec, outcome) -> None:
        result, evidence, _ = reverify(spec, outcome, calculations=[])
        assert FailureCode.UNKNOWN_CALCULATION in codes(result)
        assert all(item.status is EvidenceStatus.REJECTED for item in evidence)
        # Claims citing rejected evidence must also fail.
        assert FailureCode.EVIDENCE_NOT_VERIFIED in codes(result)
        assert result.status is VerificationStatus.FAILED

    def test_calculation_with_missing_source_facts(self, spec, outcome) -> None:
        result, _, _ = reverify(spec, outcome, facts=[])
        assert FailureCode.MISSING_SOURCE_FACT in codes(result)
        assert result.status is VerificationStatus.FAILED

    def test_fact_referencing_wrong_artifact(self, spec, outcome) -> None:
        facts = [
            fact.model_copy(update={"source_artifact_id": "ART-ffffffffffff"})
            for fact in outcome.facts
        ]
        result, _, _ = reverify(spec, outcome, facts=facts)
        assert FailureCode.ARTIFACT_MISMATCH in codes(result)

    def test_evidence_value_diverging_from_calculation(self, spec, outcome) -> None:
        evidence = [
            item.model_copy(
                update={
                    "status": EvidenceStatus.UNVERIFIED,
                    "value": item.value + Decimal("0.001"),
                }
            )
            for item in outcome.evidence
        ]
        result, _, _ = reverify(spec, outcome, evidence=evidence)
        assert FailureCode.EVIDENCE_CALC_MISMATCH in codes(result)
        # Downstream, assertions no longer match the (tampered) evidence.
        assert result.status is VerificationStatus.FAILED

    def test_incomplete_lineage_empty_source_facts(self, spec, outcome) -> None:
        evidence = [
            item.model_copy(update={"status": EvidenceStatus.UNVERIFIED, "source_fact_ids": ()})
            for item in outcome.evidence
        ]
        result, _, _ = reverify(spec, outcome, evidence=evidence)
        assert FailureCode.INCOMPLETE_LINEAGE in codes(result)


class TestAssertionGates:
    def test_assertion_citing_uncited_evidence_rejected(self, spec, outcome) -> None:
        # An assertion must not smuggle in evidence the claim does not cite —
        # uncited evidence would skip the subject/as-of/status trust gates.
        claim = outcome.claims[0]
        bad = tampered_claim(claim, evidence_ids=claim.evidence_ids[:2])
        result, _, _ = reverify(spec, outcome, claims=[bad])
        assert FailureCode.ASSERTION_EVIDENCE_NOT_CITED in codes(result)
        assert result.status is VerificationStatus.FAILED

    def test_claim_with_no_assertions_rejected(self, spec, outcome) -> None:
        claim = tampered_claim(outcome.claims[0], numeric_assertions=())
        result, _, _ = reverify(spec, outcome, claims=[claim])
        assert FailureCode.MISSING_ASSERTION in codes(result)
        assert result.status is VerificationStatus.FAILED

    def test_partially_asserted_claim_rejected(self, spec, outcome) -> None:
        claim = outcome.claims[0]
        bad = tampered_claim(claim, numeric_assertions=claim.numeric_assertions[:1])
        result, _, _ = reverify(spec, outcome, claims=[bad])
        assert FailureCode.MISSING_ASSERTION in codes(result)


class TestPublicationGuard:
    def test_failed_claims_prevent_verified_publication(self, spec, outcome) -> None:
        claim = tampered_claim(outcome.claims[0], direction=Direction.DECREASED)
        result, _, claims = reverify(spec, outcome, claims=[claim])
        assert result.status is VerificationStatus.FAILED
        assert claims[0].claim_id in result.rejected_claim_ids
        assert not result.verified_claim_ids

    def test_checked_at_recorded(self, spec, outcome) -> None:
        stamp = datetime(2001, 2, 3, tzinfo=UTC)
        result, _, _ = reverify(spec, outcome, checked_at=stamp)
        assert result.checked_at == stamp

    def test_failed_run_report_publishes_no_claims(self, spec, outcome, tmp_path) -> None:
        # Even a verified claim is withheld from the report when the overall
        # verification fails: a failed report must never read as approved.
        from strix.models import Evidence
        from strix.pipeline import run_research
        from tests.conftest import FixedClock

        good = outcome.claims[0]
        bad = good.model_copy(
            update={"direction": Direction.DECREASED, "claim_id": "CL-000000000bad"}
        )

        class TwoClaimReasoner:
            def analyze(self, spec: ResearchSpec, evidence: list[Evidence]) -> list[Claim]:
                return [good, bad]

        result = run_research(
            spec,
            state_dir=tmp_path / "runs",
            clock=FixedClock(),
            reasoner=TwoClaimReasoner(),
        )
        assert result.verification.status is VerificationStatus.FAILED
        assert good.claim_id in result.verification.verified_claim_ids
        assert result.report.claims == ()
        assert "No verified finding" in result.report.summary
        report_text = (result.run_directory / "report.txt").read_text()
        assert "increased from" not in report_text
