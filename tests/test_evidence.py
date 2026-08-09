"""Evidence construction: stability, lineage completeness, display values."""

from __future__ import annotations

from decimal import Decimal

from strix.canonical import sha256_hex
from strix.models import EvidenceStatus, Metric, ResearchSpec
from strix.pipeline import DeterministicOutcome
from tests.conftest import compute_demo


class TestArtifact:
    def test_artifact_hash_matches_raw_bytes(
        self, outcome: DeterministicOutcome, raw_fixture: bytes
    ) -> None:
        assert outcome.artifact.content_hash == sha256_hex(raw_fixture)
        assert outcome.artifact.byte_size == len(raw_fixture)

    def test_artifact_id_is_content_derived(self, spec: ResearchSpec, raw_fixture: bytes) -> None:
        again = compute_demo(spec, raw_fixture)
        assert again.artifact.artifact_id.startswith("ART-")

    def test_modified_bytes_change_artifact_identity(
        self, spec: ResearchSpec, raw_fixture: bytes, outcome: DeterministicOutcome
    ) -> None:
        tampered = raw_fixture.replace(b"101000000", b"999000000")
        again = compute_demo(spec, tampered)
        assert again.artifact.artifact_id != outcome.artifact.artifact_id
        assert again.artifact.content_hash != outcome.artifact.content_hash


class TestEvidence:
    def test_three_evidence_records(self, outcome: DeterministicOutcome) -> None:
        metrics = [item.metric for item in outcome.evidence]
        assert metrics.count(Metric.OPERATING_MARGIN) == 2
        assert metrics.count(Metric.OPERATING_MARGIN_CHANGE_PP) == 1

    def test_display_values(self, outcome: DeterministicOutcome) -> None:
        displays = {
            (item.metric, item.observation_period): item.display_value for item in outcome.evidence
        }
        assert displays[(Metric.OPERATING_MARGIN, "2025-Q2")] == "8.4%"
        assert displays[(Metric.OPERATING_MARGIN, "2026-Q2")] == "10.1%"
        assert (
            displays[(Metric.OPERATING_MARGIN_CHANGE_PP, "2025-Q2..2026-Q2")]
            == "1.7 percentage points"
        )

    def test_ids_are_stable_across_recomputes(
        self, spec: ResearchSpec, raw_fixture: bytes, outcome: DeterministicOutcome
    ) -> None:
        again = compute_demo(spec, raw_fixture)
        assert [item.evidence_id for item in again.evidence] == [
            item.evidence_id for item in outcome.evidence
        ]
        assert [fact.fact_id for fact in again.facts] == [fact.fact_id for fact in outcome.facts]
        assert [calc.calculation_id for calc in again.calculations] == [
            calc.calculation_id for calc in outcome.calculations
        ]

    def test_status_change_does_not_change_evidence_id(self, outcome: DeterministicOutcome) -> None:
        # The verifier flips status; the identifier must not move.
        verified = outcome.evidence[0]
        assert verified.status is EvidenceStatus.VERIFIED
        unverified = verified.model_copy(update={"status": EvidenceStatus.UNVERIFIED})
        assert unverified.evidence_id == verified.evidence_id

    def test_complete_lineage_to_source_artifact(self, outcome: DeterministicOutcome) -> None:
        facts_by_id = {fact.fact_id: fact for fact in outcome.facts}
        calcs_by_id = {calc.calculation_id: calc for calc in outcome.calculations}
        for item in outcome.evidence:
            calc = calcs_by_id[item.calculation_id]
            assert item.source_fact_ids == calc.input_fact_ids
            assert item.value == calc.value
            assert item.unit is calc.unit
            for fact_id in calc.input_fact_ids:
                fact = facts_by_id[fact_id]
                assert fact.source_artifact_id == outcome.artifact.artifact_id

    def test_known_at_is_latest_input_fact(self, outcome: DeterministicOutcome) -> None:
        facts_by_id = {fact.fact_id: fact for fact in outcome.facts}
        for item in outcome.evidence:
            expected = max(facts_by_id[f].known_at for f in item.source_fact_ids)
            assert item.known_at == expected

    def test_values_are_decimal(self, outcome: DeterministicOutcome) -> None:
        for item in outcome.evidence:
            assert isinstance(item.value, Decimal)
            assert not isinstance(item.value, float)


class TestHashMembershipContract:
    """Pins exactly what feeds evidence IDs and stage hashes."""

    def test_display_value_is_excluded_from_id_and_stage_hash(
        self, outcome: DeterministicOutcome
    ) -> None:
        from strix.pipeline import evidence_hash

        original = outcome.evidence
        redisplayed = tuple(
            item.model_copy(update={"display_value": "999.9% (tampered display)"})
            for item in original
        )
        # display_value is presentation-only: same identity, same stage hash.
        assert [item.evidence_id for item in redisplayed] == [item.evidence_id for item in original]
        assert evidence_hash(redisplayed) == evidence_hash(original)

    def test_known_at_is_included_in_ids_and_hashes(
        self, spec, raw_fixture: bytes, outcome: DeterministicOutcome
    ) -> None:
        from strix.pipeline import facts_hash

        # Shifting a known_at timestamp in the source must change fact
        # identity and the facts stage hash: known_at is deterministic
        # content, not a wall-clock timestamp.
        shifted_raw = raw_fixture.replace(
            b"2025-07-15T00:00:00+00:00", b"2025-07-16T00:00:00+00:00"
        )
        shifted = compute_demo(spec, shifted_raw)
        assert facts_hash(shifted.facts) != facts_hash(outcome.facts)
        assert {fact.fact_id for fact in shifted.facts} != {fact.fact_id for fact in outcome.facts}
        assert {item.evidence_id for item in shifted.evidence} != {
            item.evidence_id for item in outcome.evidence
        }
