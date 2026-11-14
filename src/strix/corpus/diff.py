"""Pure, deterministic comparison between two corpus manifests.

:func:`compute_diff` never touches the filesystem, the network, or the
wall clock -- it is a pure function of two already-loaded
:class:`~strix.corpus.models.CorpusManifest` objects. It makes no claim
about what a change means for any prior finding (see
:class:`~strix.corpus.models.CorpusDiff`'s docstring) -- that boundary is
deliberate and belongs to a later phase with retrieval and verification
lineage.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from strix.corpus.models import (
    CompatibilityWarning,
    CompatibilityWarningCode,
    CorpusDiff,
    CorpusManifest,
    DiscoveredEntry,
    DocumentArtifact,
    DocumentChange,
    DocumentChangeType,
    RejectedEntryChange,
    RejectedEntryChangeType,
)
from strix.errors import IncompatibleSchemaVersionError


def compute_diff(old: CorpusManifest, new: CorpusManifest) -> CorpusDiff:
    """Compare *old* against *new*; raises on an incompatible schema.

    Comparison is keyed on relative paths, document IDs, content hashes,
    and byte sizes -- never on anything content-addressed being equal by
    coincidence alone (document_id itself is derived from path + hash +
    size, so it can't disagree with them).
    """
    if old.schema_version != new.schema_version:
        raise IncompatibleSchemaVersionError(
            f"old manifest schema_version {old.schema_version!r} is incompatible with "
            f"new manifest schema_version {new.schema_version!r}; refusing to compare"
        )

    warnings: list[CompatibilityWarning] = []
    if old.scanner_version != new.scanner_version:
        warnings.append(
            CompatibilityWarning(
                code=CompatibilityWarningCode.SCANNER_VERSION_CHANGED,
                message=(
                    f"scanner_version changed from {old.scanner_version!r} "
                    f"to {new.scanner_version!r}"
                ),
            )
        )
    if old.limits != new.limits:
        warnings.append(
            CompatibilityWarning(
                code=CompatibilityWarningCode.LIMITS_CHANGED,
                message=f"scan limits changed from {old.limits!r} to {new.limits!r}",
            )
        )

    incomplete = old.truncated or new.truncated
    if incomplete:
        warnings.append(
            CompatibilityWarning(
                code=CompatibilityWarningCode.INCOMPLETE_DUE_TO_TRUNCATION,
                message=(
                    "old and/or new manifest was truncated; ADDED/REMOVED claims for "
                    "documents the truncated scan(s) may not have reached are suppressed"
                ),
            )
        )

    document_changes = _diff_documents(
        old.documents, new.documents, old_truncated=old.truncated, new_truncated=new.truncated
    )
    rejected_entry_changes = _diff_rejected(old.rejected_entries, new.rejected_entries)

    affected_document_ids = sorted(
        {
            document_id
            for change in document_changes
            if change.change_type is not DocumentChangeType.UNCHANGED
            for document_id in (change.old_document_id, change.new_document_id)
            if document_id is not None
        }
    )
    affected_relative_paths = sorted(
        {
            relative_path
            for change in document_changes
            if change.change_type is not DocumentChangeType.UNCHANGED
            for relative_path in (change.old_relative_path, change.new_relative_path)
            if relative_path is not None
        }
    )

    return CorpusDiff(
        old_corpus_id=old.corpus_id,
        new_corpus_id=new.corpus_id,
        old_scanner_version=old.scanner_version,
        new_scanner_version=new.scanner_version,
        old_limits=old.limits,
        new_limits=new.limits,
        document_changes=document_changes,
        rejected_entry_changes=rejected_entry_changes,
        compatibility_warnings=tuple(warnings),
        incomplete=incomplete,
        affected_document_ids=tuple(affected_document_ids),
        affected_relative_paths=tuple(affected_relative_paths),
    )


def _diff_documents(
    old_documents: Iterable[DocumentArtifact],
    new_documents: Iterable[DocumentArtifact],
    *,
    old_truncated: bool,
    new_truncated: bool,
) -> tuple[DocumentChange, ...]:
    old_by_path = {document.relative_path: document for document in old_documents}
    new_by_path = {document.relative_path: document for document in new_documents}

    old_by_hash: dict[str, list[DocumentArtifact]] = defaultdict(list)
    for document in old_by_path.values():
        old_by_hash[document.content_hash].append(document)
    new_by_hash: dict[str, list[DocumentArtifact]] = defaultdict(list)
    for document in new_by_path.values():
        new_by_hash[document.content_hash].append(document)

    changes: list[DocumentChange] = []
    handled_old: set[str] = set()
    handled_new: set[str] = set()

    # Renames: only when exactly one old-only and one new-only path share
    # a content hash. Anything ambiguous (more candidates on either side)
    # is left for the plain added/removed handling below -- never guessed.
    for content_hash, old_candidates in old_by_hash.items():
        old_only = [doc for doc in old_candidates if doc.relative_path not in new_by_path]
        new_only = [
            doc for doc in new_by_hash.get(content_hash, ()) if doc.relative_path not in old_by_path
        ]
        if len(old_only) == 1 and len(new_only) == 1:
            old_doc, new_doc = old_only[0], new_only[0]
            changes.append(
                DocumentChange(
                    change_type=DocumentChangeType.RENAMED,
                    old_relative_path=old_doc.relative_path,
                    new_relative_path=new_doc.relative_path,
                    old_document_id=old_doc.document_id,
                    new_document_id=new_doc.document_id,
                    old_content_hash=old_doc.content_hash,
                    new_content_hash=new_doc.content_hash,
                    old_byte_size=old_doc.byte_size,
                    new_byte_size=new_doc.byte_size,
                )
            )
            handled_old.add(old_doc.relative_path)
            handled_new.add(new_doc.relative_path)

    # Same path on both sides: UNCHANGED or MODIFIED.
    for path in sorted(set(old_by_path) & set(new_by_path)):
        old_doc, new_doc = old_by_path[path], new_by_path[path]
        change_type = (
            DocumentChangeType.UNCHANGED
            if old_doc.content_hash == new_doc.content_hash
            else DocumentChangeType.MODIFIED
        )
        changes.append(
            DocumentChange(
                change_type=change_type,
                old_relative_path=path,
                new_relative_path=path,
                old_document_id=old_doc.document_id,
                new_document_id=new_doc.document_id,
                old_content_hash=old_doc.content_hash,
                new_content_hash=new_doc.content_hash,
                old_byte_size=old_doc.byte_size,
                new_byte_size=new_doc.byte_size,
            )
        )
        handled_old.add(path)
        handled_new.add(path)

    # Remaining old-only paths: REMOVED, unless the new scan was
    # truncated and so may simply not have reached this path again.
    if not new_truncated:
        for path in sorted(set(old_by_path) - handled_old):
            old_doc = old_by_path[path]
            changes.append(
                DocumentChange(
                    change_type=DocumentChangeType.REMOVED,
                    old_relative_path=old_doc.relative_path,
                    old_document_id=old_doc.document_id,
                    old_content_hash=old_doc.content_hash,
                    old_byte_size=old_doc.byte_size,
                )
            )

    # Remaining new-only paths: ADDED, unless the old scan was truncated
    # and so this path might have existed, just unreached, back then.
    if not old_truncated:
        for path in sorted(set(new_by_path) - handled_new):
            new_doc = new_by_path[path]
            changes.append(
                DocumentChange(
                    change_type=DocumentChangeType.ADDED,
                    new_relative_path=new_doc.relative_path,
                    new_document_id=new_doc.document_id,
                    new_content_hash=new_doc.content_hash,
                    new_byte_size=new_doc.byte_size,
                )
            )

    def sort_key(change: DocumentChange) -> str:
        return change.new_relative_path or change.old_relative_path or ""

    return tuple(sorted(changes, key=sort_key))


def _diff_rejected(
    old_entries: Iterable[DiscoveredEntry], new_entries: Iterable[DiscoveredEntry]
) -> tuple[RejectedEntryChange, ...]:
    old_by_path = {entry.relative_path: entry for entry in old_entries}
    new_by_path = {entry.relative_path: entry for entry in new_entries}

    changes: list[RejectedEntryChange] = []
    for path in sorted(set(old_by_path) | set(new_by_path)):
        old_entry = old_by_path.get(path)
        new_entry = new_by_path.get(path)
        if old_entry is not None and new_entry is None:
            changes.append(
                RejectedEntryChange(
                    change_type=RejectedEntryChangeType.NO_LONGER_REJECTED,
                    relative_path=path,
                    old_failure_code=old_entry.failure_code,
                    old_detail=old_entry.detail,
                )
            )
        elif old_entry is None and new_entry is not None:
            changes.append(
                RejectedEntryChange(
                    change_type=RejectedEntryChangeType.NEWLY_REJECTED,
                    relative_path=path,
                    new_failure_code=new_entry.failure_code,
                    new_detail=new_entry.detail,
                )
            )
        elif old_entry is not None and new_entry is not None:
            same = (old_entry.failure_code, old_entry.detail) == (
                new_entry.failure_code,
                new_entry.detail,
            )
            changes.append(
                RejectedEntryChange(
                    change_type=(
                        RejectedEntryChangeType.UNCHANGED
                        if same
                        else RejectedEntryChangeType.CHANGED
                    ),
                    relative_path=path,
                    old_failure_code=old_entry.failure_code,
                    new_failure_code=new_entry.failure_code,
                    old_detail=old_entry.detail,
                    new_detail=new_entry.detail,
                )
            )
    return tuple(changes)
