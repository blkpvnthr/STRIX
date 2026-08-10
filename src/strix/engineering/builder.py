"""Candidate model builder - the reasoner-boundary analogue.

``propose(spec, evidence)`` is a pure function of exactly those two
arguments. It copies every value verbatim from evidence payloads, cites
every supporting evidence id (including every matching bridging ECN), and
invents nothing. No file, environment, network, or terminal access. The
verifier independently re-derives and checks everything proposed here.
"""

from __future__ import annotations

from strix.canonical import make_id
from strix.engineering.models import (
    AllocatedToAttributes,
    AllocationFact,
    CandidateElement,
    CandidateRelationship,
    CandidateStatus,
    ComponentFact,
    ConnectionFact,
    ConnectsAttributes,
    DescriptionFact,
    ElementType,
    EngineeringEvidence,
    EngineeringSpec,
    HandlingMarking,
    InterfaceFact,
    NumericProperty,
    NumericPropertyFact,
    RelationshipAttributes,
    RelationshipType,
    RequirementFact,
    RevisionChangeFact,
    SupersedesAttributes,
)


def _union_handling(
    *groups: tuple[HandlingMarking, ...],
) -> tuple[HandlingMarking, ...]:
    merged: set[str] = set()
    for group in groups:
        merged.update(group)
    return tuple(sorted(merged))


def _element(
    element_type: ElementType,
    identity_key: str,
    name: str,
    revision: str | None,
    properties: tuple[NumericProperty, ...],
    handling: tuple[HandlingMarking, ...],
    evidence_ids: tuple[str, ...],
) -> CandidateElement:
    element_id = make_id(
        "EL",
        {
            "element_type": element_type,
            "identity_key": identity_key,
            "name": name,
            "revision": revision,
            "properties": [prop.model_dump() for prop in properties],
            "evidence_ids": list(evidence_ids),
        },
    )
    return CandidateElement(
        element_id=element_id,
        element_type=element_type,
        identity_key=identity_key,
        name=name,
        revision=revision,
        properties=properties,
        handling=handling,
        evidence_ids=evidence_ids,
        status=CandidateStatus.PROPOSED,
    )


def _relationship(
    relationship_type: RelationshipType,
    from_ref: str,
    to_ref: str,
    attributes: RelationshipAttributes,
    handling: tuple[HandlingMarking, ...],
    evidence_ids: tuple[str, ...],
) -> CandidateRelationship:
    relationship_id = make_id(
        "REL",
        {
            "relationship_type": relationship_type,
            "from_ref": from_ref,
            "to_ref": to_ref,
            "attributes": attributes.model_dump(),
            "evidence_ids": list(evidence_ids),
        },
    )
    return CandidateRelationship(
        relationship_id=relationship_id,
        relationship_type=relationship_type,
        from_ref=from_ref,
        to_ref=to_ref,
        attributes=attributes,
        handling=handling,
        evidence_ids=evidence_ids,
        status=CandidateStatus.PROPOSED,
    )


class DeterministicModelBuilder:
    """Builds candidate elements/relationships from typed evidence only."""

    def propose(
        self, spec: EngineeringSpec, evidence: tuple[EngineeringEvidence, ...]
    ) -> tuple[tuple[CandidateElement, ...], tuple[CandidateRelationship, ...]]:
        components = [e for e in evidence if isinstance(e.payload, ComponentFact)]
        requirements = [e for e in evidence if isinstance(e.payload, RequirementFact)]
        numerics = [e for e in evidence if isinstance(e.payload, NumericPropertyFact)]
        descriptions = [e for e in evidence if isinstance(e.payload, DescriptionFact)]
        connections = [e for e in evidence if isinstance(e.payload, ConnectionFact)]
        allocations = [e for e in evidence if isinstance(e.payload, AllocationFact)]
        changes = [e for e in evidence if isinstance(e.payload, RevisionChangeFact)]

        component_revision: dict[str, str] = {}
        elements: list[CandidateElement] = []

        for item in sorted(components, key=lambda e: e.payload.part_id):  # type: ignore[union-attr]
            payload = item.payload
            assert isinstance(payload, ComponentFact)
            part_numerics = sorted(
                (
                    e
                    for e in numerics
                    if isinstance(e.payload, NumericPropertyFact)
                    and e.payload.subject_id == payload.part_id
                ),
                key=lambda e: e.payload.property_name,  # type: ignore[union-attr]
            )
            part_descriptions = sorted(
                (
                    e
                    for e in descriptions
                    if isinstance(e.payload, DescriptionFact)
                    and e.payload.part_id == payload.part_id
                ),
                key=lambda e: e.evidence_id,
            )
            properties = tuple(
                NumericProperty(
                    name=e.payload.property_name,
                    value=e.payload.value,
                    unit=e.payload.unit,
                    original_value=e.payload.original_value,
                    original_unit=e.payload.original_unit,
                )
                for e in part_numerics
                if isinstance(e.payload, NumericPropertyFact)
            )
            cited = (
                item.evidence_id,
                *(e.evidence_id for e in part_numerics),
                *(e.evidence_id for e in part_descriptions),
            )
            handling = _union_handling(
                item.handling,
                *(e.handling for e in part_numerics),
                *(e.handling for e in part_descriptions),
            )
            component_revision.setdefault(payload.part_id, payload.revision)
            elements.append(
                _element(
                    ElementType.COMPONENT,
                    payload.part_id,
                    payload.name,
                    payload.revision,
                    properties,
                    handling,
                    cited,
                )
            )

        for item in sorted(requirements, key=lambda e: e.payload.requirement_id):  # type: ignore[union-attr]
            payload = item.payload
            assert isinstance(payload, RequirementFact)
            elements.append(
                _element(
                    ElementType.REQUIREMENT,
                    payload.requirement_id,
                    payload.text,
                    None,
                    (),
                    _union_handling(item.handling),
                    (item.evidence_id,),
                )
            )

        relationships: list[CandidateRelationship] = []

        for item in sorted(connections, key=lambda e: e.payload.interface_id):  # type: ignore[union-attr]
            payload = item.payload
            assert isinstance(payload, ConnectionFact)
            interface_evidence = self._interface_evidence_for(payload.interface_id, evidence)
            bridging: list[EngineeringEvidence] = []
            for endpoint_part, endpoint_revision in (
                (payload.from_part, payload.from_revision),
                (payload.to_part, payload.to_revision),
            ):
                current = component_revision.get(endpoint_part)
                if current is not None and current != endpoint_revision:
                    bridging.extend(
                        e
                        for e in changes
                        if isinstance(e.payload, RevisionChangeFact)
                        and e.payload.part_id == endpoint_part
                        and e.payload.from_revision == endpoint_revision
                        and e.payload.to_revision == current
                    )
            bridging.sort(key=lambda e: e.evidence_id)
            ecn_ids: list[str] = []
            for e in bridging:
                assert isinstance(e.payload, RevisionChangeFact)
                if e.payload.ecn_id not in ecn_ids:
                    ecn_ids.append(e.payload.ecn_id)
            # Role-ordered citations: connection record, interface record
            # (source of the medium attribute), then every bridging ECN.
            cited = (item.evidence_id,)
            handling_groups = [item.handling]
            medium = "unspecified"
            if interface_evidence is not None:
                cited += (interface_evidence.evidence_id,)
                handling_groups.append(interface_evidence.handling)
                assert isinstance(interface_evidence.payload, InterfaceFact)
                medium = interface_evidence.payload.medium
            cited += tuple(e.evidence_id for e in bridging)
            handling_groups.extend(e.handling for e in bridging)
            relationships.append(
                _relationship(
                    RelationshipType.CONNECTS,
                    payload.from_part,
                    payload.to_part,
                    ConnectsAttributes(
                        medium=medium,
                        from_revision=payload.from_revision,
                        to_revision=payload.to_revision,
                        bridging_ecn_ids=tuple(ecn_ids),
                    ),
                    _union_handling(*handling_groups),
                    cited,
                )
            )

        for item in sorted(
            allocations,
            key=lambda e: (e.payload.requirement_id, e.payload.part_id),  # type: ignore[union-attr]
        ):
            payload = item.payload
            assert isinstance(payload, AllocationFact)
            relationships.append(
                _relationship(
                    RelationshipType.ALLOCATED_TO,
                    payload.requirement_id,
                    payload.part_id,
                    AllocatedToAttributes(),
                    _union_handling(item.handling),
                    (item.evidence_id,),
                )
            )

        for item in sorted(changes, key=lambda e: e.payload.ecn_id):  # type: ignore[union-attr]
            payload = item.payload
            assert isinstance(payload, RevisionChangeFact)
            relationships.append(
                _relationship(
                    RelationshipType.SUPERSEDES,
                    payload.part_id,
                    payload.part_id,
                    SupersedesAttributes(
                        ecn_id=payload.ecn_id,
                        from_revision=payload.from_revision,
                        to_revision=payload.to_revision,
                        approved_date=payload.approved_date,
                    ),
                    _union_handling(item.handling),
                    (item.evidence_id,),
                )
            )

        return tuple(elements), tuple(relationships)

    @staticmethod
    def _interface_evidence_for(
        interface_id: str, evidence: tuple[EngineeringEvidence, ...]
    ) -> EngineeringEvidence | None:
        for item in evidence:
            if (
                isinstance(item.payload, InterfaceFact)
                and item.payload.interface_id == interface_id
            ):
                return item
        return None
