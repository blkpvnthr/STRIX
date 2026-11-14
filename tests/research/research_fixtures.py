"""Shared helpers for strix.research tests: build a CorpusManifest plus
real, self-consistent ParseResults directly, without touching the
filesystem or the real evidence root."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from strix.corpus.models import CorpusManifest, DocumentArtifact, ScanLimits
from strix.corpus.parsers.models import (
    ParseFailure,
    ParseFailureCode,
    ParseLimits,
    ParseRequest,
    ParseResult,
    ParseStatus,
)
from strix.corpus.parsers.text_parser import TextParser
from strix.corpus.scanner import SCANNER_VERSION
from strix.corpus.snapshot import (
    CORPUS_MANIFEST_SCHEMA_VERSION,
    compute_corpus_id,
    compute_document_id,
)
from strix.research.models import (
    DateConstraint,
    DocumentFilter,
    RetrievalBudget,
    build_research_request,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_corpus(
    documents: dict[str, bytes],
    *,
    truncated: bool = False,
    schema_version: str = CORPUS_MANIFEST_SCHEMA_VERSION,
) -> tuple[CorpusManifest, tuple[ParseResult, ...]]:
    """Build a CorpusManifest and real, successful ParseResults for
    *documents* ({relative_path: raw_bytes}) using the actual TextParser
    -- genuine, self-consistent chunks, not hand-rolled fakes."""
    artifacts = []
    for relative_path, raw in documents.items():
        content_hash = hashlib.sha256(raw).hexdigest()
        artifacts.append(
            DocumentArtifact(
                document_id=compute_document_id(relative_path, content_hash, len(raw)),
                relative_path=relative_path,
                content_hash=content_hash,
                byte_size=len(raw),
                extension=None,
            )
        )
    ordered_artifacts = tuple(sorted(artifacts, key=lambda document: document.relative_path))
    corpus_id = compute_corpus_id(ordered_artifacts)

    manifest = CorpusManifest(
        corpus_id=corpus_id,
        schema_version=schema_version,
        scanner_version=SCANNER_VERSION,
        evidence_root="/fake/evidence/root",
        limits=ScanLimits(),
        truncated=truncated,
        truncation_reason=None,
        documents=ordered_artifacts,
        rejected_entries=(),
        created_at=NOW,
    )

    parser = TextParser()
    results = []
    for document in ordered_artifacts:
        raw = documents[document.relative_path]
        request = ParseRequest(
            corpus_id=corpus_id,
            document_id=document.document_id,
            relative_path=document.relative_path,
            content_hash=document.content_hash,
            limits=ParseLimits(),
        )
        results.append(parser.parse(request, raw))
    return manifest, tuple(results)


def make_failed_parse_result(document_id: str, message: str = "simulated failure") -> ParseResult:
    return ParseResult(
        document_id=document_id,
        parser_name="text",
        parser_version="1.0.0",
        source_content_hash="0" * 64,
        status=ParseStatus.FAILED,
        total_lines=0,
        chunks=(),
        failure=ParseFailure(code=ParseFailureCode.INVALID_ENCODING, message=message),
    )


def make_request(
    corpus_id: str,
    query_terms: tuple[str, ...],
    *,
    question: str = "What does the evidence say?",
    document_filter: DocumentFilter | None = None,
    budget: RetrievalBudget | None = None,
    date_constraint: DateConstraint | None = None,
):
    return build_research_request(
        corpus_id=corpus_id,
        question=question,
        query_terms=query_terms,
        created_at=NOW,
        document_filter=document_filter if document_filter is not None else DocumentFilter(),
        budget=budget if budget is not None else RetrievalBudget(),
        date_constraint=date_constraint if date_constraint is not None else DateConstraint(),
    )
