"""Typed domain models for the STRIX engineering compiler.

Contract chain:

    EngineeringArtifact -> AnchoredFact -> EngineeringEvidence
    -> CandidateElement / CandidateRelationship -> EngineeringVerification
    -> VerifiedModel -> export

Identity rules (binding):
- ``AnchoredFact.artifact_id`` — not the payload — binds a fact to its
  physical source artifact; the ART id embeds the raw-byte content hash.
  Fact payloads carry purely logical content; typed anchors carry the
  logical location. A logical anchor alone is never sufficient evidence
  identity.
- Numeric engineering properties are ``Decimal`` (float rejected) and keep
  both the parsed/normalized form and the original lexical spelling. No unit
  conversion is performed.
- Handling markings are propagated source metadata only (sorted unions).
  STRIX implements no CUI, classification, export-control, or CMMC
  enforcement. The marking vocabulary is an open, validated string type so
  future adapters can add markings without schema redesign.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints

from strix.models import DecimalValue, StrixModel

# --------------------------------------------------------------------------
# Open vocabularies and enums
# --------------------------------------------------------------------------

#: Open (extensible) marking vocabulary — validated shape, not a closed enum.
HandlingMarking = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_\-]{0,31}$")]

PUBLIC: str = "PUBLIC"
SYNTHETIC: str = "SYNTHETIC"

#: Markings the v2 command's synthetic-public-only POLICY accepts. This is
#: execution policy, not a schema capability limit.
V2_POLICY_MARKINGS: frozenset[str] = frozenset({PUBLIC, SYNTHETIC})


class SourceFormat(StrEnum):
    REQIF = "reqif"
    COMPONENT_CSV = "component_csv"
    INTERFACE_XML = "interface_xml"
    TEXT_DESCRIPTION = "text_description"
    CHANGE_NOTICE_CSV = "change_notice_csv"


class FactKind(StrEnum):
    REQUIREMENT = "requirement"
    COMPONENT = "component"
    NUMERIC_PROPERTY = "numeric_property"
    INTERFACE = "interface"
    CONNECTION = "connection"
    ALLOCATION = "allocation"
    REVISION_CHANGE = "revision_change"
    DESCRIPTION = "description"


class ElementType(StrEnum):
    COMPONENT = "component"
    REQUIREMENT = "requirement"


class RelationshipType(StrEnum):
    CONNECTS = "connects"
    ALLOCATED_TO = "allocated_to"
    SUPERSEDES = "supersedes"


class CandidateStatus(StrEnum):
    PROPOSED = "proposed"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ModelStatus(StrEnum):
    PASSED = "passed"
    COMPLETED_WITH_REJECTIONS = "completed_with_rejections"
    FAILED_MODEL = "failed_model"


class EngineeringFailureCode(StrEnum):
    UNKNOWN_EVIDENCE = "unknown_evidence"
    INCOMPLETE_LINEAGE = "incomplete_lineage"
    EVIDENCE_AFTER_AS_OF = "evidence_after_as_of"
    DANGLING_ENDPOINT = "dangling_endpoint"
    DANGLING_ALLOCATION = "dangling_allocation"
    REVISION_CONFLICT = "revision_conflict"
    CONFIGURATION_AMBIGUITY = "configuration_ambiguity"
    DUPLICATE_IDENTITY = "duplicate_identity"
    REJECTED_ELEMENT_CITED = "rejected_element_cited"
    CANDIDATE_EVIDENCE_MISMATCH = "candidate_evidence_mismatch"
    HANDLING_MISMATCH = "handling_mismatch"


# --------------------------------------------------------------------------
# Anchors (format-specific, discriminated)
# --------------------------------------------------------------------------


class ReqIfAnchor(StrixModel):
    """Anchor by ReqIF SPEC-OBJECT IDENTIFIER."""

    anchor_type: Literal["reqif_id"] = "reqif_id"
    identifier: str = Field(min_length=1)

    def render(self, file: str) -> str:
        return f"{file}#reqif-id={self.identifier}"


class XmlIdAnchor(StrixModel):
    """Anchor by an explicit XML element id attribute."""

    anchor_type: Literal["xml_id"] = "xml_id"
    id: str = Field(min_length=1)

    def render(self, file: str) -> str:
        return f"{file}#id={self.id}"


class XmlPathAnchor(StrixModel):
    """Anchor for an id-less XML element.

    The ordinal XPath is display/location only — it can shift when a sibling
    is inserted even though the element is unchanged. ``element_fingerprint``
    (canonical hash of tag + sorted attributes + normalized text) is the
    semantic identity; replay reports drift between the two as an integrity
    failure rather than accepting a shifted path as equivalent evidence.
    """

    anchor_type: Literal["xml_path"] = "xml_path"
    xpath: str = Field(min_length=1)
    element_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    def render(self, file: str) -> str:
        return f"{file}#xpath={self.xpath}"


class CsvAnchor(StrixModel):
    """Anchor by CSV primary key plus 1-based physical line number."""

    anchor_type: Literal["csv_row"] = "csv_row"
    key: str = Field(min_length=1)
    row: int = Field(ge=1)

    def render(self, file: str) -> str:
        return f"{file}#key={self.key}#row={self.row}"


class TextRangeAnchor(StrixModel):
    """Anchor by 1-based physical line range plus paragraph content hash.

    ``paragraph_hash`` is computed after line-ending normalization and
    per-line trailing-whitespace strip, making the anchor LF/CRLF-stable and
    content-verifiable.
    """

    anchor_type: Literal["text_range"] = "text_range"
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    paragraph_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    def render(self, file: str) -> str:
        return f"{file}#lines={self.start_line}-{self.end_line}"


Anchor = Annotated[
    ReqIfAnchor | XmlIdAnchor | XmlPathAnchor | CsvAnchor | TextRangeAnchor,
    Field(discriminator="anchor_type"),
]

# --------------------------------------------------------------------------
# Fact payloads (typed, discriminated — no generic dicts)
# --------------------------------------------------------------------------


class RequirementFact(StrixModel):
    kind: Literal["requirement"] = "requirement"
    requirement_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ComponentFact(StrixModel):
    kind: Literal["component"] = "component"
    part_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    revision: str = Field(min_length=1)


class NumericPropertyFact(StrixModel):
    """A numeric engineering property. ``value``/``unit`` are the parsed and
    normalized forms; ``original_value``/``original_unit`` preserve the exact
    lexical source spelling. No unit conversion is performed."""

    kind: Literal["numeric_property"] = "numeric_property"
    subject_id: str = Field(min_length=1)
    property_name: str = Field(min_length=1)
    value: DecimalValue
    unit: str = Field(min_length=1)
    original_value: str = Field(min_length=1)
    original_unit: str = Field(min_length=1)


class InterfaceFact(StrixModel):
    kind: Literal["interface"] = "interface"
    interface_id: str = Field(min_length=1)
    medium: str = Field(min_length=1)


class ConnectionFact(StrixModel):
    kind: Literal["connection"] = "connection"
    interface_id: str = Field(min_length=1)
    from_part: str = Field(min_length=1)
    from_revision: str = Field(min_length=1)
    to_part: str = Field(min_length=1)
    to_revision: str = Field(min_length=1)


class AllocationFact(StrixModel):
    kind: Literal["allocation"] = "allocation"
    requirement_id: str = Field(min_length=1)
    part_id: str = Field(min_length=1)


class RevisionChangeFact(StrixModel):
    kind: Literal["revision_change"] = "revision_change"
    ecn_id: str = Field(min_length=1)
    part_id: str = Field(min_length=1)
    from_revision: str = Field(min_length=1)
    to_revision: str = Field(min_length=1)
    approved_date: date


class DescriptionFact(StrixModel):
    kind: Literal["description"] = "description"
    part_id: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)


FactPayload = Annotated[
    RequirementFact
    | ComponentFact
    | NumericPropertyFact
    | InterfaceFact
    | ConnectionFact
    | AllocationFact
    | RevisionChangeFact
    | DescriptionFact,
    Field(discriminator="kind"),
]

# --------------------------------------------------------------------------
# Project manifest
# --------------------------------------------------------------------------


class ManifestSource(StrixModel):
    """One declared input file: identity, availability, and handling."""

    file: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")
    format: SourceFormat
    document_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    #: Date this document became available (evidence knowability floor).
    known_at: date
    handling: tuple[HandlingMarking, ...] = Field(min_length=1)


class EngineeringProjectManifest(StrixModel):
    """The declared compilation input set. Schema capability is broader than
    v2 execution policy: ``synthetic`` MAY be false in the schema; the v2
    command separately refuses anything but synthetic PUBLIC/SYNTHETIC data.
    """

    manifest_format: Literal["strix-engineering-project"]
    manifest_version: str = Field(min_length=1)
    project_id: str = Field(pattern=r"^[A-Z][A-Z0-9\-]{1,31}$")
    project_name: str = Field(min_length=1)
    synthetic: bool
    #: Validated notice string (JSON files carry no comments).
    notice: str = Field(min_length=1)
    #: Optional evaluation ground-truth file: preserved + hashed, yields no
    #: facts, read only by the post-compilation metrics step.
    ground_truth: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")
    sources: tuple[ManifestSource, ...] = Field(min_length=1)


class ExpectedModel(StrixModel):
    """Evaluation ground truth (metrics only — never analysis input)."""

    format: Literal["strix-expected-model"]
    format_version: str = Field(min_length=1)
    notice: str = Field(min_length=1)
    elements: tuple[str, ...]
    relationships: tuple[tuple[str, str, str], ...]


# --------------------------------------------------------------------------
# Core lineage models
# --------------------------------------------------------------------------


class EngineeringSpec(StrixModel):
    """Pure compilation input identity."""

    project_id: str = Field(pattern=r"^[A-Z][A-Z0-9\-]{1,31}$")
    as_of_date: date
    pipeline_version: str
    #: SHA-256 of the preserved project-manifest bytes.
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class EngineeringArtifact(StrixModel):
    """A preserved raw source file (physical identity)."""

    artifact_id: str
    source_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")
    source_format: SourceFormat
    document_id: str
    document_revision: str
    media_type: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=1)
    local_path: str
    handling: tuple[HandlingMarking, ...]


class AnchoredFact(StrixModel):
    """One extracted record: physical binding + logical anchor + payload."""

    fact_id: str
    #: The physical binding to the preserved source artifact.
    artifact_id: str
    anchor: Anchor
    payload: FactPayload


class EngineeringEvidence(StrixModel):
    """A citable typed record with explicit knowability and handling.

    known_at = max(source availability date, every record-level availability
    constraint) — it can never precede the document that carries the record.
    """

    evidence_id: str
    payload: FactPayload
    known_at: date
    handling: tuple[HandlingMarking, ...]
    source_fact_ids: tuple[str, ...] = Field(min_length=1)


class NumericProperty(StrixModel):
    name: str = Field(min_length=1)
    value: DecimalValue
    unit: str = Field(min_length=1)
    original_value: str = Field(min_length=1)
    original_unit: str = Field(min_length=1)


class CandidateElement(StrixModel):
    element_id: str
    element_type: ElementType
    identity_key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    revision: str | None
    properties: tuple[NumericProperty, ...]
    handling: tuple[HandlingMarking, ...]
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    status: CandidateStatus


class ConnectsAttributes(StrixModel):
    attribute_type: Literal["connects"] = "connects"
    medium: str = Field(min_length=1)
    from_revision: str = Field(min_length=1)
    to_revision: str = Field(min_length=1)
    #: Every matching bridging ECN id (empty when revisions agree). The
    #: verifier independently inspects ALL applicable ECN evidence and
    #: rejects conflicting or non-unique bridging paths.
    bridging_ecn_ids: tuple[str, ...] = ()


class AllocatedToAttributes(StrixModel):
    attribute_type: Literal["allocated_to"] = "allocated_to"


class SupersedesAttributes(StrixModel):
    attribute_type: Literal["supersedes"] = "supersedes"
    ecn_id: str = Field(min_length=1)
    from_revision: str = Field(min_length=1)
    to_revision: str = Field(min_length=1)
    approved_date: date


RelationshipAttributes = Annotated[
    ConnectsAttributes | AllocatedToAttributes | SupersedesAttributes,
    Field(discriminator="attribute_type"),
]


class CandidateRelationship(StrixModel):
    relationship_id: str
    relationship_type: RelationshipType
    from_ref: str = Field(min_length=1)
    to_ref: str = Field(min_length=1)
    attributes: RelationshipAttributes
    handling: tuple[HandlingMarking, ...]
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    status: CandidateStatus


# --------------------------------------------------------------------------
# Verification, model, metrics, manifest, result
# --------------------------------------------------------------------------


class EngineeringVerificationFailure(StrixModel):
    code: EngineeringFailureCode
    message: str
    candidate_id: str | None = None
    evidence_id: str | None = None
    anchors: tuple[str, ...] = ()
    #: Ids of conflicting facts/candidates involved in this failure.
    conflicting_refs: tuple[str, ...] = ()


class EngineeringVerification(StrixModel):
    status: ModelStatus
    verified_element_ids: tuple[str, ...]
    rejected_element_ids: tuple[str, ...]
    verified_relationship_ids: tuple[str, ...]
    rejected_relationship_ids: tuple[str, ...]
    failures: tuple[EngineeringVerificationFailure, ...]
    #: Wall clock — excluded from deterministic hashes and replay comparison.
    checked_at: AwareDatetime
    verifier_version: str


class FailureRef(StrixModel):
    code: EngineeringFailureCode
    message: str


class RejectedCandidate(StrixModel):
    """First-class quarantine record: fully inspectable, never dropped."""

    candidate_id: str
    kind: Literal["element", "relationship"]
    summary: str
    failures: tuple[FailureRef, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...]
    anchors: tuple[str, ...]
    conflicting_refs: tuple[str, ...]
    #: The primary rule that rejected this candidate.
    rule: EngineeringFailureCode


class VerifiedModel(StrixModel):
    project_id: str
    as_of_date: date
    #: Verified candidates only; quarantined candidates never appear here.
    elements: tuple[CandidateElement, ...]
    relationships: tuple[CandidateRelationship, ...]
    rejected: tuple[RejectedCandidate, ...]


class GroundTruthMetrics(StrixModel):
    element_precision: str
    element_recall: str
    relationship_precision: str
    relationship_recall: str
    note: str | None = None


class CompileMetrics(StrixModel):
    """Deterministic run metrics; ratios are Decimal strings (4 dp)."""

    elements_accepted: int
    elements_rejected: int
    relationships_accepted: int
    relationships_rejected: int
    conflict_count: int
    traceability_coverage: str
    allocation_coverage: str
    unsupported_export_count: int
    ground_truth: GroundTruthMetrics | None = None


class EngineeringRunManifest(StrixModel):
    """Integrity record for one engineering run.

    Deterministic (replay-compared): everything except run_id/created_at.
    ``analysis_source_hashes`` (manifest + declared sources) feed the model
    and export; ``evaluation_source_hashes`` (ground truth) feed metrics
    only and never influence model_hash or export_hash.
    """

    run_id: str
    created_at: AwareDatetime
    mode: Literal["engineering"]
    pipeline_version: str
    parser_versions: dict[str, str]
    schema_versions: dict[str, str]
    project_id: str
    as_of_date: date
    analysis_source_hashes: dict[str, str]
    evaluation_source_hashes: dict[str, str]
    input_hash: str
    facts_hash: str
    evidence_hash: str
    candidates_hash: str
    verification_hash: str
    model_hash: str
    export_hash: str
    metrics_hash: str
    final_status: ModelStatus


class CompileResult(StrixModel):
    """Everything produced by one engineering compilation."""

    spec: EngineeringSpec
    project: EngineeringProjectManifest
    artifacts: tuple[EngineeringArtifact, ...]
    facts: tuple[AnchoredFact, ...]
    evidence: tuple[EngineeringEvidence, ...]
    elements: tuple[CandidateElement, ...]
    relationships: tuple[CandidateRelationship, ...]
    verification: EngineeringVerification
    model: VerifiedModel
    metrics: CompileMetrics
    export: dict[str, object]
    run_manifest: EngineeringRunManifest
    run_directory: Path
