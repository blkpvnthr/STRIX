"""Typed models for corpus discovery and immutable snapshots.

Discovery (Phase 2): a scan of the evidence root produces
:class:`DiscoveredEntry` records, each either ``DISCOVERED`` (a candidate
evidence file) or ``REJECTED`` (with a typed reason). No content is parsed
beyond a one-byte readability probe — see :mod:`strix.corpus.scanner`.

Snapshot (Phase 3): :class:`CorpusManifest` records one immutable,
content-addressed preservation of a scan's discovered documents — see
:mod:`strix.corpus.snapshot`.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class CorpusModel(BaseModel):
    """Base for all strix.corpus models: frozen, closed schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class DiscoveryStatus(StrEnum):
    DISCOVERED = "discovered"
    REJECTED = "rejected"


class DiscoveryFailureCode(StrEnum):
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    UNREADABLE = "unreadable"
    SYMLINK_SKIPPED = "symlink_skipped"
    OUTSIDE_EVIDENCE_ROOT = "outside_evidence_root"
    DEPTH_LIMIT_EXCEEDED = "depth_limit_exceeded"
    FILE_SIZE_LIMIT_EXCEEDED = "file_size_limit_exceeded"
    TOTAL_SIZE_LIMIT_EXCEEDED = "total_size_limit_exceeded"
    FILE_COUNT_LIMIT_EXCEEDED = "file_count_limit_exceeded"


#: Extensions (lowercase, with leading dot) treated as candidate evidence.
#: Recognizing an extension here is a discovery-time classification only —
#: it is not a claim that a parser exists yet (the parser registry in a
#: later phase enforces that separately).
DEFAULT_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".txt",
        ".md",
        ".markdown",
        ".csv",
        ".json",
        ".xml",
        ".html",
        ".htm",
        ".pdf",
        ".docx",
        ".xlsx",
    }
)


class DiscoveredEntry(CorpusModel):
    """One file (or skipped directory) encountered during a corpus scan."""

    #: POSIX-style path relative to the evidence root — never absolute,
    #: never containing the evidence root's own filesystem location.
    relative_path: str
    status: DiscoveryStatus
    #: ``None`` for rejected entries where size could not be determined.
    byte_size: int | None = None
    #: Lowercase extension including the leading dot, or ``None``/``""`` if
    #: the name has no extension.
    extension: str | None = None
    failure_code: DiscoveryFailureCode | None = None
    detail: str | None = None

    @model_validator(mode="after")
    def _status_matches_failure_code(self) -> DiscoveredEntry:
        if self.status is DiscoveryStatus.DISCOVERED and self.failure_code is not None:
            raise ValueError("a discovered entry must not carry a failure code")
        if self.status is DiscoveryStatus.REJECTED and self.failure_code is None:
            raise ValueError("a rejected entry must carry a failure code")
        return self


class ScanLimits(CorpusModel):
    """Configurable bounds on one corpus scan."""

    #: Maximum directory levels below the evidence root that may be
    #: descended into; deeper directories are rejected (not explored),
    #: sibling branches continue normally.
    max_depth: int = Field(default=64, ge=1)
    #: Maximum number of file entries examined before the whole scan stops.
    max_files: int = Field(default=100_000, ge=1)
    #: A single file larger than this is rejected; the scan continues.
    max_file_size_bytes: int = Field(default=200 * 1024 * 1024, ge=1)
    #: Running total of discovered file bytes above which the whole scan
    #: stops.
    max_total_size_bytes: int = Field(default=5 * 1024 * 1024 * 1024, ge=1)


class ScanResult(CorpusModel):
    """Outcome of one recursive discovery scan."""

    #: Resolved, absolute evidence root the scan was run against.
    evidence_root: str
    scanner_version: str
    #: The limits this scan was configured and run with.
    limits: ScanLimits
    #: Stable, lexically ordered by ``relative_path``; discovered and
    #: rejected entries are distinguished by ``status``/``failure_code``.
    entries: tuple[DiscoveredEntry, ...]
    #: True only when a scan-wide limit (file count or total size) stopped
    #: the scan before the full tree was visited.
    truncated: bool
    truncation_reason: DiscoveryFailureCode | None = None


class DocumentArtifact(CorpusModel):
    """One document preserved into an immutable corpus snapshot.

    Carries no wall-clock field — identity is purely content-derived.
    """

    document_id: str
    #: POSIX-style path relative to the evidence root, as recorded at scan
    #: time; also relative to the snapshot's ``documents/`` directory.
    relative_path: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)
    extension: str | None = None


class CorpusManifest(CorpusModel):
    """Integrity record for one immutable corpus snapshot.

    ``corpus_id`` is derived solely from the canonically ordered
    ``documents`` inventory (see
    :func:`strix.corpus.snapshot.compute_corpus_id`) — it does not depend on
    ``created_at``, ``rejected_entries``, ``limits``, or ``truncated``, so
    incidental scan noise (an extra rejected file, a wider size limit) never
    changes the identity of otherwise-identical preserved evidence.
    """

    corpus_id: str
    schema_version: str
    scanner_version: str
    #: Where the originating scan ran, for audit/human reference only.
    #: Never resolved by CorpusStore to locate bytes — every read goes
    #: through the preserved snapshot (see strix.corpus.snapshot.CorpusStore).
    evidence_root: str
    limits: ScanLimits
    truncated: bool
    truncation_reason: DiscoveryFailureCode | None = None
    #: Preserved documents, canonically ordered by relative_path.
    documents: tuple[DocumentArtifact, ...]
    #: Scanner-rejected entries, recorded for visibility only — never
    #: preserved under ``documents/``.
    rejected_entries: tuple[DiscoveredEntry, ...]
    #: Wall clock — excluded from corpus_id and from any reproducibility
    #: comparison; present for human/audit purposes only.
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _collections_are_ordered_and_consistent(self) -> CorpusManifest:
        doc_paths = [doc.relative_path for doc in self.documents]
        if doc_paths != sorted(doc_paths):
            raise ValueError("documents must be canonically ordered by relative_path")
        rejected_paths = [entry.relative_path for entry in self.rejected_entries]
        if rejected_paths != sorted(rejected_paths):
            raise ValueError("rejected_entries must be canonically ordered by relative_path")
        if any(entry.status is not DiscoveryStatus.REJECTED for entry in self.rejected_entries):
            raise ValueError("rejected_entries must all carry REJECTED status")
        return self


class DocumentChangeType(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    RENAMED = "renamed"
    UNCHANGED = "unchanged"


class DocumentChange(CorpusModel):
    """One document's change between two CorpusManifests.

    Field presence is a function of ``change_type``, enforced below:
    ADDED carries only ``new_*`` fields, REMOVED only ``old_*``, and
    MODIFIED/RENAMED/UNCHANGED all carry both. MODIFIED requires the same
    path with a different hash; RENAMED requires a different path with
    the same hash — the two are mutually exclusive by construction, so a
    same-path content change can never be classified as a rename.
    """

    change_type: DocumentChangeType
    old_relative_path: str | None = None
    new_relative_path: str | None = None
    old_document_id: str | None = None
    new_document_id: str | None = None
    old_content_hash: str | None = None
    new_content_hash: str | None = None
    old_byte_size: int | None = None
    new_byte_size: int | None = None

    @model_validator(mode="after")
    def _fields_match_change_type(self) -> DocumentChange:
        old_fields = (
            self.old_relative_path,
            self.old_document_id,
            self.old_content_hash,
            self.old_byte_size,
        )
        new_fields = (
            self.new_relative_path,
            self.new_document_id,
            self.new_content_hash,
            self.new_byte_size,
        )
        has_old = all(field is not None for field in old_fields)
        has_new = all(field is not None for field in new_fields)
        no_old = all(field is None for field in old_fields)
        no_new = all(field is None for field in new_fields)

        if self.change_type is DocumentChangeType.ADDED:
            if not (no_old and has_new):
                raise ValueError("ADDED must carry only new_* fields, all of them set")
        elif self.change_type is DocumentChangeType.REMOVED:
            if not (no_new and has_old):
                raise ValueError("REMOVED must carry only old_* fields, all of them set")
        else:
            if not (has_old and has_new):
                raise ValueError(f"{self.change_type.value} must carry both old_* and new_* fields")
            if self.change_type is DocumentChangeType.MODIFIED:
                if self.old_relative_path != self.new_relative_path:
                    raise ValueError("MODIFIED requires the same relative_path on both sides")
                if self.old_content_hash == self.new_content_hash:
                    raise ValueError(
                        "MODIFIED requires a different content_hash "
                        "(same path and hash is UNCHANGED)"
                    )
            elif self.change_type is DocumentChangeType.RENAMED:
                if self.old_relative_path == self.new_relative_path:
                    raise ValueError("RENAMED requires a different relative_path on each side")
                if self.old_content_hash != self.new_content_hash:
                    raise ValueError(
                        "RENAMED requires the same content_hash on both sides "
                        "(a different hash is not a pure rename)"
                    )
            elif self.change_type is DocumentChangeType.UNCHANGED and (
                self.old_relative_path != self.new_relative_path
                or self.old_content_hash != self.new_content_hash
            ):
                raise ValueError("UNCHANGED requires identical relative_path and content_hash")
        return self


class RejectedEntryChangeType(StrEnum):
    NEWLY_REJECTED = "newly_rejected"
    NO_LONGER_REJECTED = "no_longer_rejected"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


class RejectedEntryChange(CorpusModel):
    """One rejected scanner entry's change between two CorpusManifests.

    Compared by relative_path only — rejected entries are not
    content-addressed (byte_size/hash are not reliably available for
    them) — and never conflated with a preserved document: this model
    has no document_id or content_hash field at all.
    """

    change_type: RejectedEntryChangeType
    relative_path: str
    old_failure_code: DiscoveryFailureCode | None = None
    new_failure_code: DiscoveryFailureCode | None = None
    old_detail: str | None = None
    new_detail: str | None = None

    @model_validator(mode="after")
    def _fields_match_change_type(self) -> RejectedEntryChange:
        if self.change_type is RejectedEntryChangeType.NEWLY_REJECTED:
            if self.old_failure_code is not None or self.new_failure_code is None:
                raise ValueError("NEWLY_REJECTED must carry only a new_failure_code")
        elif self.change_type is RejectedEntryChangeType.NO_LONGER_REJECTED:
            if self.new_failure_code is not None or self.old_failure_code is None:
                raise ValueError("NO_LONGER_REJECTED must carry only an old_failure_code")
        else:
            if self.old_failure_code is None or self.new_failure_code is None:
                raise ValueError(f"{self.change_type.value} must carry both failure codes")
            same = (self.old_failure_code, self.old_detail) == (
                self.new_failure_code,
                self.new_detail,
            )
            if self.change_type is RejectedEntryChangeType.UNCHANGED and not same:
                raise ValueError("UNCHANGED requires an identical failure code and detail")
            if self.change_type is RejectedEntryChangeType.CHANGED and same:
                raise ValueError("CHANGED requires a different failure code or detail")
        return self


class CompatibilityWarningCode(StrEnum):
    SCANNER_VERSION_CHANGED = "scanner_version_changed"
    LIMITS_CHANGED = "limits_changed"
    INCOMPLETE_DUE_TO_TRUNCATION = "incomplete_due_to_truncation"


class CompatibilityWarning(CorpusModel):
    code: CompatibilityWarningCode
    message: str


class CorpusDiff(CorpusModel):
    """A deterministic, pure comparison between two CorpusManifests.

    Makes no claim about what any change means for a prior finding —
    that requires retrieval and verification lineage from later phases.
    ``affected_document_ids``/``affected_relative_paths`` exist so a
    later phase can map a finding's citations onto this diff without
    this phase asserting anything about the result.
    """

    old_corpus_id: str
    new_corpus_id: str
    old_scanner_version: str
    new_scanner_version: str
    old_limits: ScanLimits
    new_limits: ScanLimits
    #: Stable order: by new_relative_path (or old_relative_path for a
    #: REMOVED change, which has no new path) — see the validator below.
    document_changes: tuple[DocumentChange, ...]
    #: Stable order: by relative_path.
    rejected_entry_changes: tuple[RejectedEntryChange, ...]
    compatibility_warnings: tuple[CompatibilityWarning, ...]
    #: True if either manifest was truncated. When true, ADDED/REMOVED
    #: claims for the affected side(s) are suppressed rather than risking
    #: a false claim about a document the truncated scan never reached —
    #: see strix.corpus.diff.compute_diff.
    incomplete: bool
    affected_document_ids: tuple[str, ...]
    affected_relative_paths: tuple[str, ...]

    @model_validator(mode="after")
    def _changes_are_ordered(self) -> CorpusDiff:
        def document_key(change: DocumentChange) -> str:
            return change.new_relative_path or change.old_relative_path or ""

        document_keys = [document_key(change) for change in self.document_changes]
        if document_keys != sorted(document_keys):
            raise ValueError("document_changes must be ordered by path")

        rejected_keys = [change.relative_path for change in self.rejected_entry_changes]
        if rejected_keys != sorted(rejected_keys):
            raise ValueError("rejected_entry_changes must be ordered by relative_path")
        return self

    @model_validator(mode="after")
    def _affected_ids_are_ordered_and_consistent(self) -> CorpusDiff:
        if tuple(sorted(set(self.affected_document_ids))) != self.affected_document_ids:
            raise ValueError("affected_document_ids must be sorted and de-duplicated")
        if tuple(sorted(set(self.affected_relative_paths))) != self.affected_relative_paths:
            raise ValueError("affected_relative_paths must be sorted and de-duplicated")
        return self


class RescanResult(CorpusModel):
    """The outcome of one rescan: the freshly scanned/snapshotted manifest
    plus its deterministic diff against the selected prior manifest."""

    manifest: CorpusManifest
    diff: CorpusDiff
