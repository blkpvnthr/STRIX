"""Builder purity and every verifier rule, incl. adversarial content mutation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from strix.engineering.builder import DeterministicModelBuilder
from strix.engineering.models import (
    CandidateStatus,
    ConnectsAttributes,
    EngineeringFailureCode,
    ModelStatus,
    NumericProperty,
    RelationshipType,
    SupersedesAttributes,
)
from strix.engineering.pipeline import ModelOutcome
from strix.engineering.verifier import verify_model
from tests.conftest import FIXED_NOW


def reverify(outcome: ModelOutcome, **overrides):
    kwargs = {
        "spec": outcome.spec,
        "artifacts": outcome.artifacts,
        "facts": outcome.facts,
        "evidence": outcome.evidence,
        "elements": tuple(
            e.model_copy(update={"status": CandidateStatus.PROPOSED}) for e in outcome.elements
        ),
        "relationships": tuple(
            r.model_copy(update={"status": CandidateStatus.PROPOSED}) for r in outcome.relationships
        ),
        "checked_at": FIXED_NOW,
    }
    kwargs.update(overrides)
    return verify_model(**kwargs)


def codes(verification) -> set[EngineeringFailureCode]:
    return {f.code for f in verification.failures}


def one_verified_connects(outcome: ModelOutcome):
    return next(
        r
        for r in outcome.relationships
        if r.relationship_type is RelationshipType.CONNECTS
        and r.status is CandidateStatus.VERIFIED
        and isinstance(r.attributes, ConnectsAttributes)
        and not r.attributes.bridging_ecn_ids
    )


class TestBuilder:
    def test_pure_and_deterministic(self, triage_outcome: ModelOutcome) -> None:
        builder = DeterministicModelBuilder()
        first = builder.propose(triage_outcome.spec, triage_outcome.evidence)
        second = builder.propose(triage_outcome.spec, triage_outcome.evidence)
        assert [e.element_id for e in first[0]] == [e.element_id for e in second[0]]
        assert [r.relationship_id for r in first[1]] == [r.relationship_id for r in second[1]]

    def test_every_candidate_cites_evidence(self, triage_outcome: ModelOutcome) -> None:
        for candidate in (*triage_outcome.elements, *triage_outcome.relationships):
            assert candidate.evidence_ids

    def test_builder_invents_nothing(self, triage_outcome: ModelOutcome) -> None:
        # Every value a candidate carries must occur in some cited evidence
        # payload (verbatim copy, no fabrication).
        evidence_by_id = {e.evidence_id: e for e in triage_outcome.evidence}
        for element in triage_outcome.elements:
            cited_dumps = [evidence_by_id[eid].payload.model_dump() for eid in element.evidence_ids]
            cited_values = {str(v) for dump in cited_dumps for v in dump.values()}
            assert element.identity_key in cited_values
            assert element.name in cited_values
            if element.revision is not None:
                assert element.revision in cited_values

    def test_bridging_ecn_cited_on_stale_revision_references(
        self, triage_outcome: ModelOutcome
    ) -> None:
        # IF-3001 and IF-3004 (ICD known 2026-04-20) reference PT-0002 at
        # rev A; the BOM (2026-05-15) records B, bridged by ECN-9001 which
        # became knowable 2026-05-10 - AFTER the ICD (coherent history).
        bridged = [
            r
            for r in triage_outcome.relationships
            if isinstance(r.attributes, ConnectsAttributes) and r.attributes.bridging_ecn_ids
        ]
        assert len(bridged) == 2
        for relationship in bridged:
            assert relationship.to_ref == "PT-0002"
            assert relationship.attributes.bridging_ecn_ids == ("ECN-9001",)  # type: ignore[union-attr]
            assert relationship.status is CandidateStatus.VERIFIED
            # The bridging ECN evidence itself is cited, not just referenced.
            evidence_by_id = {e.evidence_id: e for e in triage_outcome.evidence}
            cited_kinds = {evidence_by_id[eid].payload.kind for eid in relationship.evidence_ids}
            assert "revision_change" in cited_kinds

    def test_handling_union_propagates(self, triage_outcome: ModelOutcome) -> None:
        for candidate in (*triage_outcome.elements, *triage_outcome.relationships):
            assert candidate.handling == ("PUBLIC", "SYNTHETIC")


class TestVerifierRules:
    def test_triage_fixture_quarantines_exactly_two(self, triage_outcome: ModelOutcome) -> None:
        verification = triage_outcome.verification
        assert verification.status is ModelStatus.COMPLETED_WITH_REJECTIONS
        assert len(verification.rejected_relationship_ids) == 2
        assert not verification.rejected_element_ids
        found = codes(verification)
        assert EngineeringFailureCode.DANGLING_ALLOCATION in found
        assert EngineeringFailureCode.REVISION_CONFLICT in found
        anchors = {a for f in verification.failures for a in f.anchors}
        assert "interfaces.xml#xpath=/interface-control/allocation[7]" in anchors
        assert "interfaces.xml#id=IF-3005" in anchors

    def test_clean_fixture_passes(self, clean_outcome: ModelOutcome) -> None:
        assert clean_outcome.verification.status is ModelStatus.PASSED
        assert not clean_outcome.verification.failures

    def test_unknown_evidence(self, triage_outcome: ModelOutcome) -> None:
        bad = triage_outcome.elements[0].model_copy(update={"evidence_ids": ("EV-000000000000",)})
        verification, _, _ = reverify(triage_outcome, elements=(bad, *triage_outcome.elements[1:]))
        assert EngineeringFailureCode.UNKNOWN_EVIDENCE in codes(verification)

    def test_incomplete_lineage(self, triage_outcome: ModelOutcome) -> None:
        verification, _, _ = reverify(triage_outcome, facts=())
        assert EngineeringFailureCode.INCOMPLETE_LINEAGE in codes(verification)

    def test_evidence_after_as_of(self, triage_outcome: ModelOutcome) -> None:
        early_spec = triage_outcome.spec.model_copy(update={"as_of_date": date(2026, 1, 1)})
        verification, _, _ = reverify(triage_outcome, spec=early_spec)
        assert EngineeringFailureCode.EVIDENCE_AFTER_AS_OF in codes(verification)

    def test_dangling_endpoint(self, triage_outcome: ModelOutcome) -> None:
        connects = one_verified_connects(triage_outcome)
        bad = connects.model_copy(update={"from_ref": "PT-4242"})
        verification, _, _ = reverify(triage_outcome, relationships=(bad,))
        assert EngineeringFailureCode.DANGLING_ENDPOINT in codes(verification)

    def test_dangling_allocation_from_fixture(self, triage_outcome: ModelOutcome) -> None:
        failures = [
            f
            for f in triage_outcome.verification.failures
            if f.code is EngineeringFailureCode.DANGLING_ALLOCATION
        ]
        assert len(failures) == 1
        assert "PT-0099" in failures[0].message

    def test_revision_conflict_no_ecn_from_fixture(self, triage_outcome: ModelOutcome) -> None:
        failures = [
            f
            for f in triage_outcome.verification.failures
            if f.code is EngineeringFailureCode.REVISION_CONFLICT
        ]
        assert len(failures) == 1
        assert "PT-0005" in failures[0].message

    def test_revision_conflict_stale_reference(self, triage_outcome: ModelOutcome) -> None:
        # Make the bridging ECN knowable BEFORE the connection record: the
        # interface then referenced an already-superseded revision.
        evidence = tuple(
            e.model_copy(update={"known_at": date(2026, 3, 1)})
            if e.payload.kind == "revision_change"
            else e
            for e in triage_outcome.evidence
        )
        verification, _, _ = reverify(triage_outcome, evidence=evidence)
        stale = [
            f
            for f in verification.failures
            if f.code is EngineeringFailureCode.REVISION_CONFLICT and "stale reference" in f.message
        ]
        assert stale

    def test_configuration_ambiguity_on_conflicting_paths(
        self, triage_outcome: ModelOutcome
    ) -> None:
        # A second, different ECN covering the same (part, from, to) makes
        # the bridge non-unique.
        ecn = next(
            e
            for e in triage_outcome.evidence
            if e.payload.kind == "revision_change" and e.payload.part_id == "PT-0002"  # type: ignore[union-attr]
        )
        clone_payload = ecn.payload.model_copy(update={"ecn_id": "ECN-9099"})
        clone = ecn.model_copy(update={"evidence_id": "EV-cloneddupecn0", "payload": clone_payload})
        verification, _, _ = reverify(triage_outcome, evidence=(*triage_outcome.evidence, clone))
        assert EngineeringFailureCode.CONFIGURATION_AMBIGUITY in codes(verification)

    def test_duplicate_identity_conflict_rejects_group(self, triage_outcome: ModelOutcome) -> None:
        original = triage_outcome.elements[0]
        clone = original.model_copy(
            update={"element_id": "EL-000000dupe00", "name": original.name + " MK2"}
        )
        verification, elements, _ = reverify(
            triage_outcome, elements=(*triage_outcome.elements, clone)
        )
        assert EngineeringFailureCode.DUPLICATE_IDENTITY in codes(verification)
        rejected = {e.element_id for e in elements if e.status is CandidateStatus.REJECTED}
        assert {original.element_id, "EL-000000dupe00"} <= rejected

    def test_relationship_citing_rejected_element_cascades(
        self, triage_outcome: ModelOutcome
    ) -> None:
        original = triage_outcome.elements[0]
        clone = original.model_copy(update={"element_id": "EL-000000dupe00", "revision": "Z"})
        verification, _, _relationships = reverify(
            triage_outcome, elements=(*triage_outcome.elements, clone)
        )
        assert EngineeringFailureCode.REJECTED_ELEMENT_CITED in codes(verification)

    def test_zero_verified_elements_is_failed_model(self, triage_outcome: ModelOutcome) -> None:
        verification, _, _ = reverify(triage_outcome, evidence=(), facts=())
        assert verification.status is ModelStatus.FAILED_MODEL


class TestAdversarialContentMutation:
    """candidate_evidence_mismatch: mutate each content type while keeping
    valid citations; every mutation must be rejected."""

    def _expect_mismatch(self, outcome: ModelOutcome, **kind) -> None:
        verification, _, _ = reverify(outcome, **kind)
        assert EngineeringFailureCode.CANDIDATE_EVIDENCE_MISMATCH in codes(verification)

    def test_element_name_mutation(self, triage_outcome: ModelOutcome) -> None:
        bad = triage_outcome.elements[0].model_copy(update={"name": "Fabricated Unit"})
        self._expect_mismatch(triage_outcome, elements=(bad, *triage_outcome.elements[1:]))

    def test_element_revision_mutation(self, triage_outcome: ModelOutcome) -> None:
        component = next(e for e in triage_outcome.elements if e.revision is not None)
        bad = component.model_copy(update={"revision": "Q"})
        others = tuple(e for e in triage_outcome.elements if e is not component)
        self._expect_mismatch(triage_outcome, elements=(bad, *others))

    def test_numeric_property_value_mutation(self, triage_outcome: ModelOutcome) -> None:
        component = next(e for e in triage_outcome.elements if e.properties)
        drifted = tuple(
            NumericProperty(
                name=p.name,
                value=p.value + Decimal("1"),
                unit=p.unit,
                original_value=p.original_value,
                original_unit=p.original_unit,
            )
            for p in component.properties
        )
        bad = component.model_copy(update={"properties": drifted})
        others = tuple(e for e in triage_outcome.elements if e is not component)
        self._expect_mismatch(triage_outcome, elements=(bad, *others))

    def test_numeric_property_unit_mutation(self, triage_outcome: ModelOutcome) -> None:
        component = next(e for e in triage_outcome.elements if e.properties)
        drifted = (
            component.properties[0].model_copy(update={"unit": "lb"}),
            *component.properties[1:],
        )
        bad = component.model_copy(update={"properties": drifted})
        others = tuple(e for e in triage_outcome.elements if e is not component)
        self._expect_mismatch(triage_outcome, elements=(bad, *others))

    def test_lexical_original_mutation(self, triage_outcome: ModelOutcome) -> None:
        component = next(e for e in triage_outcome.elements if e.properties)
        drifted = (
            component.properties[0].model_copy(update={"original_value": "999"}),
            *component.properties[1:],
        )
        bad = component.model_copy(update={"properties": drifted})
        others = tuple(e for e in triage_outcome.elements if e is not component)
        self._expect_mismatch(triage_outcome, elements=(bad, *others))

    def test_connects_endpoint_revision_mutation(self, triage_outcome: ModelOutcome) -> None:
        connects = one_verified_connects(triage_outcome)
        assert isinstance(connects.attributes, ConnectsAttributes)
        bad = connects.model_copy(
            update={"attributes": connects.attributes.model_copy(update={"from_revision": "Z"})}
        )
        self._expect_mismatch(triage_outcome, relationships=(bad,))

    def test_connects_medium_mutation(self, triage_outcome: ModelOutcome) -> None:
        connects = one_verified_connects(triage_outcome)
        assert isinstance(connects.attributes, ConnectsAttributes)
        bad = connects.model_copy(
            update={"attributes": connects.attributes.model_copy(update={"medium": "hydraulic"})}
        )
        self._expect_mismatch(triage_outcome, relationships=(bad,))

    def test_supersedes_attributes_mutation(self, triage_outcome: ModelOutcome) -> None:
        supersedes = next(
            r
            for r in triage_outcome.relationships
            if isinstance(r.attributes, SupersedesAttributes)
        )
        bad = supersedes.model_copy(
            update={"attributes": supersedes.attributes.model_copy(update={"to_revision": "Z"})}
        )
        self._expect_mismatch(triage_outcome, relationships=(bad,))

    def test_handling_mutation_rejected(self, triage_outcome: ModelOutcome) -> None:
        bad = triage_outcome.elements[0].model_copy(update={"handling": ("PUBLIC",)})
        verification, _, _ = reverify(triage_outcome, elements=(bad, *triage_outcome.elements[1:]))
        assert EngineeringFailureCode.HANDLING_MISMATCH in codes(verification)

    def test_fabricated_bridging_ecn_ids_rejected(self, triage_outcome: ModelOutcome) -> None:
        # A revision-matching connection needs no bridge; listing one anyway
        # is fabricated content the evidence does not establish.
        connects = one_verified_connects(triage_outcome)
        assert isinstance(connects.attributes, ConnectsAttributes)
        bad = connects.model_copy(
            update={
                "attributes": connects.attributes.model_copy(
                    update={"bridging_ecn_ids": ("ECN-9001",)}
                )
            }
        )
        self._expect_mismatch(triage_outcome, relationships=(bad,))

    def test_unrelated_evidence_kind_citation_rejected_for_element(
        self, triage_outcome: ModelOutcome
    ) -> None:
        allocation_ev = next(e for e in triage_outcome.evidence if e.payload.kind == "allocation")
        element = triage_outcome.elements[0]
        bad = element.model_copy(
            update={"evidence_ids": (*element.evidence_ids, allocation_ev.evidence_id)}
        )
        self._expect_mismatch(triage_outcome, elements=(bad, *triage_outcome.elements[1:]))

    def test_unrelated_evidence_kind_citation_rejected_for_relationship(
        self, triage_outcome: ModelOutcome
    ) -> None:
        component_ev = next(e for e in triage_outcome.evidence if e.payload.kind == "component")
        allocated = next(
            r
            for r in triage_outcome.relationships
            if r.relationship_type is RelationshipType.ALLOCATED_TO
            and r.status is CandidateStatus.VERIFIED
        )
        bad = allocated.model_copy(
            update={"evidence_ids": (*allocated.evidence_ids, component_ev.evidence_id)}
        )
        self._expect_mismatch(triage_outcome, relationships=(bad,))

    def test_no_op_revision_change_rejected(self, triage_outcome: ModelOutcome) -> None:
        # An ECN recording A -> A cannot establish a configuration change.
        supersedes = next(
            r
            for r in triage_outcome.relationships
            if isinstance(r.attributes, SupersedesAttributes)
        )
        ecn_ev = next(
            e
            for e in triage_outcome.evidence
            if e.payload.kind == "revision_change"
            and e.payload.ecn_id == supersedes.attributes.ecn_id  # type: ignore[union-attr]
        )
        noop_payload = ecn_ev.payload.model_copy(
            update={"to_revision": ecn_ev.payload.from_revision}  # type: ignore[union-attr]
        )
        noop_ev = ecn_ev.model_copy(update={"payload": noop_payload})
        evidence = tuple(
            noop_ev if e.evidence_id == ecn_ev.evidence_id else e for e in triage_outcome.evidence
        )
        noop_attrs = supersedes.attributes.model_copy(  # type: ignore[union-attr]
            update={"to_revision": supersedes.attributes.from_revision}  # type: ignore[union-attr]
        )
        bad = supersedes.model_copy(update={"attributes": noop_attrs})
        verification, _, _ = reverify(triage_outcome, evidence=evidence, relationships=(bad,))
        assert EngineeringFailureCode.CONFIGURATION_AMBIGUITY in codes(verification)


class TestQuarantineFirstClass:
    def test_rejected_candidates_fully_inspectable(self, triage_outcome: ModelOutcome) -> None:
        rejected = triage_outcome.model.rejected
        assert len(rejected) == 2
        for candidate in rejected:
            assert candidate.failures
            assert candidate.evidence_ids
            assert candidate.anchors
            assert candidate.rule in (
                EngineeringFailureCode.DANGLING_ALLOCATION,
                EngineeringFailureCode.REVISION_CONFLICT,
            )
        # Quarantined candidates never appear inside the verified model.
        verified_ids = {e.element_id for e in triage_outcome.model.elements} | {
            r.relationship_id for r in triage_outcome.model.relationships
        }
        assert not verified_ids & {c.candidate_id for c in rejected}
