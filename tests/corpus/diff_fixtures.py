"""Shared helpers for building CorpusManifest objects directly, for pure
compute_diff() tests that don't need a real scan/snapshot."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from strix.corpus.models import (
    CorpusManifest,
    DiscoveredEntry,
    DiscoveryFailureCode,
    DiscoveryStatus,
    DocumentArtifact,
    ScanLimits,
)
from strix.corpus.scanner import SCANNER_VERSION
from strix.corpus.snapshot import (
    CORPUS_MANIFEST_SCHEMA_VERSION,
    compute_corpus_id,
    compute_document_id,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_document(relative_path: str, content: bytes) -> DocumentArtifact:
    content_hash = hashlib.sha256(content).hexdigest()
    return DocumentArtifact(
        document_id=compute_document_id(relative_path, content_hash, len(content)),
        relative_path=relative_path,
        content_hash=content_hash,
        byte_size=len(content),
        extension=None,
    )


def make_rejected(
    relative_path: str,
    code: DiscoveryFailureCode = DiscoveryFailureCode.UNSUPPORTED_FILE_TYPE,
    detail: str = "rejected",
) -> DiscoveredEntry:
    return DiscoveredEntry(
        relative_path=relative_path,
        status=DiscoveryStatus.REJECTED,
        failure_code=code,
        detail=detail,
    )


def make_manifest(
    documents: dict[str, bytes] | None = None,
    rejected: tuple[DiscoveredEntry, ...] = (),
    *,
    scanner_version: str = SCANNER_VERSION,
    schema_version: str = CORPUS_MANIFEST_SCHEMA_VERSION,
    limits: ScanLimits | None = None,
    truncated: bool = False,
    truncation_reason: DiscoveryFailureCode | None = None,
    created_at: datetime = NOW,
) -> CorpusManifest:
    docs = tuple(
        sorted(
            (make_document(path, content) for path, content in (documents or {}).items()),
            key=lambda document: document.relative_path,
        )
    )
    rejected_sorted = tuple(sorted(rejected, key=lambda entry: entry.relative_path))
    return CorpusManifest(
        corpus_id=compute_corpus_id(docs),
        schema_version=schema_version,
        scanner_version=scanner_version,
        evidence_root="/fake/evidence/root",
        limits=limits if limits is not None else ScanLimits(),
        truncated=truncated,
        truncation_reason=truncation_reason,
        documents=docs,
        rejected_entries=rejected_sorted,
        created_at=created_at,
    )
