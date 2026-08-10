"""Deterministic verification of candidate engineering models.

Two passes: elements, then relationships (endpoint checks see element
outcomes). Semantic failures quarantine individual candidates; the run
continues. Integrity failures raise and abort. The verifier independently
re-derives candidate content from the cited evidence (a candidate cannot
carry fabricated or drifted content while holding valid citations), never
auto-picks the newest revision, and inspects ALL applicable ECN evidence -
not just what the builder cited - when judging configuration consistency.
"""

from __future__ import annotations

from datetime import datetime

from strix.engineering.models import (
    AllocationFact,
    AnchoredFact,
    CandidateElement,
    CandidateRelationship,
    CandidateStatus,
    ComponentFact,
    ConnectionFact,
    ConnectsAttributes,
    DescriptionFact,
    ElementType,
    EngineeringArtifact,
    EngineeringEvidence,
    EngineeringFailureCode,
    EngineeringSpec,
    EngineeringVerification,
    EngineeringVerificationFailure,
    InterfaceFact,
    ModelStatus,
    NumericPropertyFact,
    RelationshipType,
    RequirementFact,
    RevisionChangeFact,
    SupersedesAttributes,
)

VERIFIER_VERSION = "1.0.0"


class _Context:
    """Resolved lookup tables shared by both verification passes."""

    def __init__(
        self,
        spec: EngineeringSpec,
        artifacts: tuple[EngineeringArtifact, ...],
        facts: tuple[AnchoredFact, ...],
        evidence: tuple[EngineeringEvidence, ...],
    ) -> None:
        self.spec = spec
        self.artifacts_by_id = {a.artifact_id: a for a in artifacts}
        self.facts_by_id = {f.fact_id: f for f in facts}
        self.evidence_by_id = {e.evidence_id: e for e in evidence}
        #: ALL revision-change evidence, for independent configuration checks.
        self.changes = tuple(e for e in evidence if isinstance(e.payload, RevisionChangeFact))

    def anchors_for(self, evidence_ids: tuple[str, ...]) -> tuple[str, ...]:
        rendered: list[str] = []
        for evidence_id in evidence_ids:
            item = self.evidence_by_id.get(evidence_id)
            if item is None:
                continue
            for fact_id in item.source_fact_ids:
                fact = self.facts_by_id.get(fact_id)
                if fact is None:
                    continue
                artifact = self.artifacts_by_id.get(fact.artifact_id)
                file = artifact.source_name if artifact else "<missing-artifact>"
                text = fact.anchor.render(file)
                if text not in rendered:
                    rendered.append(text)
        return tuple(rendered)


def verify_model(
    *,
    spec: EngineeringSpec,
    artifacts: tuple[EngineeringArtifact, ...],
    facts: tuple[AnchoredFact, ...],
    evidence: tuple[EngineeringEvidence, ...],
    elements: tuple[CandidateElement, ...],
    relationships: tuple[CandidateRelationship, ...],
    checked_at: datetime,
) -> tuple[
    EngineeringVerification,
    tuple[CandidateElement, ...],
    tuple[CandidateRelationship, ...],
]:
    """Verify all candidates; return the result plus status-updated copies."""
    ctx = _Context(spec, artifacts, facts, evidence)
    failures: list[EngineeringVerificationFailure] = []

    element_failures: dict[str, list[EngineeringVerificationFailure]] = {}
    for element in elements:
        found = _verify_common(ctx, element.element_id, element.evidence_ids)
        found += _verify_element_content(ctx, element)
        found += _verify_handling(ctx, element.element_id, element.handling, element.evidence_ids)
        element_failures[element.element_id] = found
    _verify_duplicate_identity(elements, element_failures, ctx)

    verified_elements: list[CandidateElement] = []
    for element in elements:
        found = element_failures[element.element_id]
        failures.extend(found)
        status = CandidateStatus.VERIFIED if not found else CandidateStatus.REJECTED
        verified_elements.append(element.model_copy(update={"status": status}))
    elements_by_key = {
        e.identity_key: e for e in verified_elements if e.element_type is ElementType.COMPONENT
    }
    elements_by_key.update(
        {e.identity_key: e for e in verified_elements if e.element_type is ElementType.REQUIREMENT}
    )

    verified_relationships: list[CandidateRelationship] = []
    for relationship in relationships:
        found = _verify_common(ctx, relationship.relationship_id, relationship.evidence_ids)
        found += _verify_handling(
            ctx, relationship.relationship_id, relationship.handling, relationship.evidence_ids
        )
        found += _verify_endpoints(ctx, relationship, elements_by_key)
        found += _verify_relationship_content(ctx, relationship, elements_by_key)
        failures.extend(found)
        status = CandidateStatus.VERIFIED if not found else CandidateStatus.REJECTED
        verified_relationships.append(relationship.model_copy(update={"status": status}))

    any_rejected = any(e.status is CandidateStatus.REJECTED for e in verified_elements) or any(
        r.status is CandidateStatus.REJECTED for r in verified_relationships
    )
    verified_element_count = sum(
        1 for e in verified_elements if e.status is CandidateStatus.VERIFIED
    )
    if verified_element_count == 0:
        status_overall = ModelStatus.FAILED_MODEL
    elif any_rejected:
        status_overall = ModelStatus.COMPLETED_WITH_REJECTIONS
    else:
        status_overall = ModelStatus.PASSED

    verification = EngineeringVerification(
        status=status_overall,
        verified_element_ids=tuple(
            e.element_id for e in verified_elements if e.status is CandidateStatus.VERIFIED
        ),
        rejected_element_ids=tuple(
            e.element_id for e in verified_elements if e.status is CandidateStatus.REJECTED
        ),
        verified_relationship_ids=tuple(
            r.relationship_id
            for r in verified_relationships
            if r.status is CandidateStatus.VERIFIED
        ),
        rejected_relationship_ids=tuple(
            r.relationship_id
            for r in verified_relationships
            if r.status is CandidateStatus.REJECTED
        ),
        failures=tuple(failures),
        checked_at=checked_at,
        verifier_version=VERIFIER_VERSION,
    )
    return verification, tuple(verified_elements), tuple(verified_relationships)


# --------------------------------------------------------------------------
# Shared checks
# --------------------------------------------------------------------------


def _fail(
    code: EngineeringFailureCode,
    message: str,
    candidate_id: str,
    ctx: _Context,
    evidence_ids: tuple[str, ...] = (),
    evidence_id: str | None = None,
    conflicting: tuple[str, ...] = (),
) -> EngineeringVerificationFailure:
    return EngineeringVerificationFailure(
        code=code,
        message=message,
        candidate_id=candidate_id,
        evidence_id=evidence_id,
        anchors=ctx.anchors_for(evidence_ids or ((evidence_id,) if evidence_id else ())),
        conflicting_refs=conflicting,
    )


def _verify_common(
    ctx: _Context, candidate_id: str, evidence_ids: tuple[str, ...]
) -> list[EngineeringVerificationFailure]:
    """Citation resolution, lineage completeness, and as-of knowability."""
    found: list[EngineeringVerificationFailure] = []
    for evidence_id in evidence_ids:
        item = ctx.evidence_by_id.get(evidence_id)
        if item is None:
            found.append(
                _fail(
                    EngineeringFailureCode.UNKNOWN_EVIDENCE,
                    f"candidate {candidate_id} cites unknown evidence {evidence_id}",
                    candidate_id,
                    ctx,
                    evidence_id=evidence_id,
                )
            )
            continue
        broken = [
            fact_id
            for fact_id in item.source_fact_ids
            if fact_id not in ctx.facts_by_id
            or ctx.facts_by_id[fact_id].artifact_id not in ctx.artifacts_by_id
        ]
        if broken or not item.source_fact_ids:
            found.append(
                _fail(
                    EngineeringFailureCode.INCOMPLETE_LINEAGE,
                    f"evidence {evidence_id} cited by {candidate_id} does not "
                    f"resolve to preserved facts/artifacts ({broken or 'no facts'})",
                    candidate_id,
                    ctx,
                    evidence_id=evidence_id,
                    conflicting=tuple(broken),
                )
            )
        if item.known_at > ctx.spec.as_of_date:
            found.append(
                _fail(
                    EngineeringFailureCode.EVIDENCE_AFTER_AS_OF,
                    f"evidence {evidence_id} cited by {candidate_id} became "
                    f"knowable {item.known_at.isoformat()}, after the as-of "
                    f"date {ctx.spec.as_of_date.isoformat()}",
                    candidate_id,
                    ctx,
                    evidence_id=evidence_id,
                )
            )
    return found


def _verify_handling(
    ctx: _Context,
    candidate_id: str,
    handling: tuple[str, ...],
    evidence_ids: tuple[str, ...],
) -> list[EngineeringVerificationFailure]:
    """Candidate handling must equal the sorted union of cited evidence markings."""
    expected: set[str] = set()
    for evidence_id in evidence_ids:
        item = ctx.evidence_by_id.get(evidence_id)
        if item is not None:
            expected.update(item.handling)
    if not expected:
        return []  # unknown-evidence failures already reported
    if tuple(sorted(expected)) != tuple(handling):
        return [
            _fail(
                EngineeringFailureCode.HANDLING_MISMATCH,
                f"candidate {candidate_id} handling {list(handling)} differs "
                f"from the union of its evidence markings {sorted(expected)}",
                candidate_id,
                ctx,
                evidence_ids=evidence_ids,
            )
        ]
    return []


# --------------------------------------------------------------------------
# Element checks
# --------------------------------------------------------------------------


def _verify_element_content(
    ctx: _Context, element: CandidateElement
) -> list[EngineeringVerificationFailure]:
    """Re-derive element content from cited evidence; reject any drift."""
    found: list[EngineeringVerificationFailure] = []
    cited = [ctx.evidence_by_id[eid] for eid in element.evidence_ids if eid in ctx.evidence_by_id]
    if not cited:
        return found

    def mismatch(detail: str) -> None:
        found.append(
            _fail(
                EngineeringFailureCode.CANDIDATE_EVIDENCE_MISMATCH,
                f"element {element.element_id} ({element.identity_key}): {detail}",
                element.element_id,
                ctx,
                evidence_ids=element.evidence_ids,
            )
        )

    # A candidate may cite only evidence kinds its element type consumes -
    # unrelated citations are padding the verifier cannot vouch for.
    allowed_kinds = (
        {"component", "numeric_property", "description"}
        if element.element_type is ElementType.COMPONENT
        else {"requirement"}
    )
    unrelated = sorted({e.payload.kind for e in cited} - allowed_kinds)
    if unrelated:
        mismatch(f"cites unrelated evidence kinds {unrelated}")

    if element.element_type is ElementType.COMPONENT:
        records = [e for e in cited if isinstance(e.payload, ComponentFact)]
        if len(records) != 1:
            mismatch(f"expected exactly one cited component record, found {len(records)}")
            return found
        record = records[0].payload
        assert isinstance(record, ComponentFact)
        if element.identity_key != record.part_id:
            mismatch(f"identity_key differs from cited part_id {record.part_id!r}")
        if element.name != record.name:
            mismatch(f"name differs from cited component name {record.name!r}")
        if element.revision != record.revision:
            mismatch(f"revision differs from cited revision {record.revision!r}")
        cited_numeric = {
            e.payload.property_name: e.payload
            for e in cited
            if isinstance(e.payload, NumericPropertyFact)
        }
        if len(element.properties) != len(cited_numeric):
            mismatch(
                f"{len(element.properties)} properties vs "
                f"{len(cited_numeric)} cited numeric records"
            )
        for prop in element.properties:
            source = cited_numeric.get(prop.name)
            if source is None:
                mismatch(f"property {prop.name!r} has no cited numeric evidence")
                continue
            if source.subject_id != record.part_id:
                mismatch(
                    f"property {prop.name!r} cites evidence for subject "
                    f"{source.subject_id!r}, not {record.part_id!r}"
                )
            if (
                prop.value != source.value
                or prop.unit != source.unit
                or prop.original_value != source.original_value
                or prop.original_unit != source.original_unit
            ):
                mismatch(f"property {prop.name!r} differs from cited evidence")
        for e in cited:
            if isinstance(e.payload, DescriptionFact) and e.payload.part_id != record.part_id:
                mismatch(f"cited description evidence belongs to {e.payload.part_id!r}")
            if isinstance(e.payload, RequirementFact):
                mismatch("component cites requirement evidence")
    else:
        records = [e for e in cited if isinstance(e.payload, RequirementFact)]
        if len(records) != 1:
            mismatch(f"expected exactly one cited requirement record, found {len(records)}")
            return found
        record_req = records[0].payload
        assert isinstance(record_req, RequirementFact)
        if element.identity_key != record_req.requirement_id:
            mismatch(
                f"identity_key differs from cited requirement id {record_req.requirement_id!r}"
            )
        if element.name != record_req.text:
            mismatch("text differs from cited requirement text")
        if element.revision is not None:
            mismatch("requirement elements carry no revision")
        if element.properties:
            mismatch("requirement elements carry no numeric properties")
    return found


def _verify_duplicate_identity(
    elements: tuple[CandidateElement, ...],
    element_failures: dict[str, list[EngineeringVerificationFailure]],
    ctx: _Context,
) -> None:
    """Same identity_key with conflicting content rejects the whole group."""
    by_key: dict[str, list[CandidateElement]] = {}
    for element in elements:
        by_key.setdefault(element.identity_key, []).append(element)
    for key, group in by_key.items():
        if len(group) < 2:
            continue
        names = {e.name for e in group}
        revisions = {e.revision for e in group}
        if len(names) > 1 or len(revisions) > 1:
            ids = tuple(e.element_id for e in group)
            for element in group:
                element_failures[element.element_id].append(
                    _fail(
                        EngineeringFailureCode.DUPLICATE_IDENTITY,
                        f"identity {key!r} appears {len(group)} times with "
                        f"conflicting name/revision",
                        element.element_id,
                        ctx,
                        evidence_ids=element.evidence_ids,
                        conflicting=tuple(i for i in ids if i != element.element_id),
                    )
                )


# --------------------------------------------------------------------------
# Relationship checks
# --------------------------------------------------------------------------


def _verify_endpoints(
    ctx: _Context,
    relationship: CandidateRelationship,
    elements_by_key: dict[str, CandidateElement],
) -> list[EngineeringVerificationFailure]:
    found: list[EngineeringVerificationFailure] = []
    for role, ref in (("from", relationship.from_ref), ("to", relationship.to_ref)):
        element = elements_by_key.get(ref)
        if element is None:
            code = (
                EngineeringFailureCode.DANGLING_ALLOCATION
                if relationship.relationship_type is RelationshipType.ALLOCATED_TO and role == "to"
                else EngineeringFailureCode.DANGLING_ENDPOINT
            )
            found.append(
                _fail(
                    code,
                    f"{relationship.relationship_type.value} relationship "
                    f"{relationship.relationship_id} {role}-endpoint {ref!r} "
                    f"matches no candidate element (v2 supports no external "
                    f"references)",
                    relationship.relationship_id,
                    ctx,
                    evidence_ids=relationship.evidence_ids,
                )
            )
        elif element.status is CandidateStatus.REJECTED:
            found.append(
                _fail(
                    EngineeringFailureCode.REJECTED_ELEMENT_CITED,
                    f"relationship {relationship.relationship_id} {role}-endpoint "
                    f"{ref!r} resolves to a rejected element",
                    relationship.relationship_id,
                    ctx,
                    evidence_ids=relationship.evidence_ids,
                    conflicting=(element.element_id,),
                )
            )
    return found


def _verify_relationship_content(
    ctx: _Context,
    relationship: CandidateRelationship,
    elements_by_key: dict[str, CandidateElement],
) -> list[EngineeringVerificationFailure]:
    """Type-specific re-derivation from cited evidence + configuration rules."""
    found: list[EngineeringVerificationFailure] = []
    cited = [
        ctx.evidence_by_id[eid] for eid in relationship.evidence_ids if eid in ctx.evidence_by_id
    ]
    if not cited:
        return found

    def mismatch(detail: str, code: EngineeringFailureCode) -> None:
        found.append(
            _fail(
                code,
                f"relationship {relationship.relationship_id} "
                f"({relationship.relationship_type.value} {relationship.from_ref} "
                f"-> {relationship.to_ref}): {detail}",
                relationship.relationship_id,
                ctx,
                evidence_ids=relationship.evidence_ids,
            )
        )

    evidence_code = EngineeringFailureCode.CANDIDATE_EVIDENCE_MISMATCH

    # A relationship may cite only the evidence kinds its type consumes.
    allowed_by_type = {
        RelationshipType.CONNECTS: {"connection", "interface", "revision_change"},
        RelationshipType.ALLOCATED_TO: {"allocation"},
        RelationshipType.SUPERSEDES: {"revision_change"},
    }
    unrelated = sorted(
        {e.payload.kind for e in cited} - allowed_by_type[relationship.relationship_type]
    )
    if unrelated:
        mismatch(f"cites unrelated evidence kinds {unrelated}", evidence_code)

    if relationship.relationship_type is RelationshipType.CONNECTS:
        connection_records = [e for e in cited if isinstance(e.payload, ConnectionFact)]
        if len(connection_records) != 1:
            mismatch(
                f"expected exactly one cited connection record, found {len(connection_records)}",
                evidence_code,
            )
            return found
        connection_evidence = connection_records[0]
        connection = connection_evidence.payload
        assert isinstance(connection, ConnectionFact)
        attributes = relationship.attributes
        if not isinstance(attributes, ConnectsAttributes):
            mismatch("attributes are not connects attributes", evidence_code)
            return found
        if relationship.from_ref != connection.from_part:
            mismatch(
                f"from_ref differs from cited from_part {connection.from_part!r}",
                evidence_code,
            )
        if relationship.to_ref != connection.to_part:
            mismatch(
                f"to_ref differs from cited to_part {connection.to_part!r}",
                evidence_code,
            )
        if attributes.from_revision != connection.from_revision:
            mismatch(
                f"from_revision differs from cited {connection.from_revision!r}",
                evidence_code,
            )
        if attributes.to_revision != connection.to_revision:
            mismatch(
                f"to_revision differs from cited {connection.to_revision!r}",
                evidence_code,
            )
        interface_records = [
            e
            for e in cited
            if isinstance(e.payload, InterfaceFact)
            and e.payload.interface_id == connection.interface_id
        ]
        if not interface_records:
            mismatch("medium attribute has no cited interface record", evidence_code)
        else:
            payload = interface_records[0].payload
            assert isinstance(payload, InterfaceFact)
            if attributes.medium != payload.medium:
                mismatch(
                    f"medium differs from cited interface medium {payload.medium!r}",
                    evidence_code,
                )
        found += _verify_configuration(
            ctx, relationship, connection_evidence, attributes, elements_by_key
        )
    elif relationship.relationship_type is RelationshipType.ALLOCATED_TO:
        records = [e for e in cited if isinstance(e.payload, AllocationFact)]
        if len(records) != 1:
            mismatch(
                f"expected exactly one cited allocation record, found {len(records)}",
                evidence_code,
            )
            return found
        allocation = records[0].payload
        assert isinstance(allocation, AllocationFact)
        if relationship.from_ref != allocation.requirement_id:
            mismatch(
                f"from_ref differs from cited requirement {allocation.requirement_id!r}",
                evidence_code,
            )
        if relationship.to_ref != allocation.part_id:
            mismatch(
                f"to_ref differs from cited part {allocation.part_id!r}",
                evidence_code,
            )
    else:  # SUPERSEDES
        records = [e for e in cited if isinstance(e.payload, RevisionChangeFact)]
        if len(records) != 1:
            mismatch(
                f"expected exactly one cited change notice, found {len(records)}",
                evidence_code,
            )
            return found
        change = records[0].payload
        assert isinstance(change, RevisionChangeFact)
        attributes_s = relationship.attributes
        if not isinstance(attributes_s, SupersedesAttributes):
            mismatch("attributes are not supersedes attributes", evidence_code)
            return found
        if relationship.from_ref != change.part_id or relationship.to_ref != change.part_id:
            mismatch(f"endpoints differ from cited part {change.part_id!r}", evidence_code)
        if (
            attributes_s.ecn_id != change.ecn_id
            or attributes_s.from_revision != change.from_revision
            or attributes_s.to_revision != change.to_revision
            or attributes_s.approved_date != change.approved_date
        ):
            mismatch("attributes differ from cited change notice", evidence_code)
        if change.from_revision == change.to_revision:
            mismatch(
                f"change notice {change.ecn_id} records a no-op revision "
                f"transition {change.from_revision!r} -> {change.to_revision!r}",
                EngineeringFailureCode.CONFIGURATION_AMBIGUITY,
            )
    return found


def _verify_configuration(
    ctx: _Context,
    relationship: CandidateRelationship,
    connection_evidence: EngineeringEvidence,
    attributes: ConnectsAttributes,
    elements_by_key: dict[str, CandidateElement],
) -> list[EngineeringVerificationFailure]:
    """Revision/configuration consistency for a connects relationship.

    Never auto-picks the newest revision. An endpoint revision differing from
    the component's evidenced revision needs a coherent, UNIQUE bridging
    path: an exact (part, from, to) change notice that became knowable AFTER
    the connection record (a change documented later). An ECN knowable at or
    before the connection record means the record referenced an
    already-superseded revision (stale reference -> revision_conflict);
    multiple conflicting applicable paths are configuration ambiguity. The
    verifier inspects ALL applicable ECN evidence, not just citations.
    """
    connection = connection_evidence.payload
    assert isinstance(connection, ConnectionFact)
    found: list[EngineeringVerificationFailure] = []
    required_bridges: set[str] = set()
    for part, recorded in (
        (connection.from_part, connection.from_revision),
        (connection.to_part, connection.to_revision),
    ):
        element = elements_by_key.get(part)
        if element is None or element.revision is None:
            continue  # dangling endpoints are handled elsewhere
        current = element.revision
        if recorded == current:
            continue
        applicable = [
            e
            for e in ctx.changes
            if isinstance(e.payload, RevisionChangeFact)
            and e.payload.part_id == part
            and e.payload.from_revision == recorded
            and e.payload.to_revision == current
        ]
        distinct_ecns: dict[str, RevisionChangeFact] = {}
        conflicting = False
        for e in applicable:
            payload = e.payload
            assert isinstance(payload, RevisionChangeFact)
            existing = distinct_ecns.get(payload.ecn_id)
            if existing is not None and existing != payload:
                conflicting = True
            distinct_ecns[payload.ecn_id] = payload
        anchors_from = (
            connection_evidence.evidence_id,
            *(e.evidence_id for e in applicable),
        )
        if not applicable:
            found.append(
                _fail(
                    EngineeringFailureCode.REVISION_CONFLICT,
                    f"connection records {part} at revision {recorded!r} but the "
                    f"component evidence establishes {current!r}, with no "
                    f"change notice bridging {recorded!r} -> {current!r}",
                    relationship.relationship_id,
                    ctx,
                    evidence_ids=anchors_from,
                    conflicting=(elements_by_key[part].element_id,),
                )
            )
            continue
        if conflicting or len(distinct_ecns) > 1:
            found.append(
                _fail(
                    EngineeringFailureCode.CONFIGURATION_AMBIGUITY,
                    f"{len(applicable)} change-notice records for {part} "
                    f"{recorded!r} -> {current!r} do not establish a unique "
                    f"valid configuration",
                    relationship.relationship_id,
                    ctx,
                    evidence_ids=anchors_from,
                    conflicting=tuple(e.evidence_id for e in applicable),
                )
            )
            continue
        bridge = applicable[0]
        if bridge.known_at <= connection_evidence.known_at:
            found.append(
                _fail(
                    EngineeringFailureCode.REVISION_CONFLICT,
                    f"connection records {part} at revision {recorded!r} although "
                    f"the change to {current!r} was already knowable on "
                    f"{bridge.known_at.isoformat()} (stale reference)",
                    relationship.relationship_id,
                    ctx,
                    evidence_ids=anchors_from,
                    conflicting=(bridge.evidence_id,),
                )
            )
            continue
        bridge_payload = bridge.payload
        assert isinstance(bridge_payload, RevisionChangeFact)
        required_bridges.add(bridge_payload.ecn_id)
        if bridge_payload.ecn_id not in attributes.bridging_ecn_ids:
            found.append(
                _fail(
                    EngineeringFailureCode.CANDIDATE_EVIDENCE_MISMATCH,
                    f"bridging change notice {bridge_payload.ecn_id} for {part} "
                    f"is not recorded in bridging_ecn_ids",
                    relationship.relationship_id,
                    ctx,
                    evidence_ids=anchors_from,
                )
            )
    # Exact-set re-derivation: bridging_ecn_ids may contain nothing beyond
    # the independently derived required bridges - a candidate cannot carry
    # fabricated ECN references (least of all on a connection whose
    # revisions already agree and need no bridge at all).
    fabricated = [
        ecn_id for ecn_id in attributes.bridging_ecn_ids if ecn_id not in required_bridges
    ]
    if fabricated:
        found.append(
            _fail(
                EngineeringFailureCode.CANDIDATE_EVIDENCE_MISMATCH,
                f"bridging_ecn_ids lists {fabricated} which the evidence does "
                f"not establish as required bridges for this connection",
                relationship.relationship_id,
                ctx,
                evidence_ids=relationship.evidence_ids,
            )
        )
    return found


def rejected_summary(
    candidate_id: str, failures: tuple[EngineeringVerificationFailure, ...]
) -> tuple[EngineeringFailureCode, str]:
    """Primary rule + human summary for a rejected candidate."""
    own = [f for f in failures if f.candidate_id == candidate_id]
    primary = own[0].code if own else EngineeringFailureCode.UNKNOWN_EVIDENCE
    return primary, "; ".join(f.message for f in own[:3])


__all__ = ["VERIFIER_VERSION", "rejected_summary", "verify_model"]
