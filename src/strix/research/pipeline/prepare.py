"""prepare(): immutable snapshot + request -> parsing -> retrieval ->
PreparedResearch. Deterministic end to end; the only I/O here is reading
an already-verified, preserved corpus snapshot -- never the live
evidence root, never a re-parse outside the registered parser registry.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from strix.canonical import canonical_hash, sha256_hex
from strix.corpus.models import CorpusManifest
from strix.corpus.parsers.models import DocumentChunk, ParseResult, ParseStatus
from strix.corpus.parsers.registry import ParserRegistry, parse_corpus
from strix.corpus.snapshot import CorpusStore
from strix.errors import EvidencePacketMismatchError, IncompleteCorpusPolicyError
from strix.research.models import ResearchRequest, RetrievalTrace
from strix.research.pipeline.models import (
    EvidenceItem,
    ParseResultIdentity,
    ParserVersionInfo,
    PreparationPolicy,
    PreparedResearch,
    compute_prepared_id,
)
from strix.research.retrieval import retrieve


def prepare(
    request: ResearchRequest,
    store: CorpusStore,
    registry: ParserRegistry,
    *,
    policy: PreparationPolicy | None = None,
    created_at: datetime | None = None,
) -> PreparedResearch:
    """Run the full deterministic prepare stage.

    1. Loads and fully re-verifies the snapshot named by
       *request.corpus_id* (``CorpusStore.verify_and_load`` — raises
       :class:`~strix.errors.CorpusSnapshotIntegrityError` on tamper;
       never trusted blindly).
    2. Parses every document through *registry*
       (``strix.corpus.parsers.registry.parse_corpus``) — the live
       evidence root is never touched.
    3. Runs deterministic lexical retrieval
       (``strix.research.retrieval.retrieve`` — raises
       :class:`~strix.errors.CorpusMismatchError` if *request.corpus_id*
       disagrees with the loaded manifest).
    4. If the corpus snapshot is incomplete (truncated) and *policy* does
       not explicitly permit that, raises
       :class:`~strix.errors.IncompleteCorpusPolicyError` rather than
       silently proceeding.
    5. Builds the bounded evidence packet from exactly the retrieval
       trace's selected candidates — no unselected corpus content.

    Every field of the result except ``created_at`` is a pure function
    of the preserved snapshot and *request*: repeating this call with the
    same arguments and an explicit *created_at* produces an identical
    ``PreparedResearch``.
    """
    resolved_policy = policy if policy is not None else PreparationPolicy()

    manifest = store.verify_and_load(request.corpus_id)
    parse_results = parse_corpus(store, manifest, registry)
    retrieval_trace = retrieve(request, manifest, parse_results)

    if retrieval_trace.incomplete and not resolved_policy.allow_incomplete_corpus:
        raise IncompleteCorpusPolicyError(
            f"corpus {manifest.corpus_id!r} came from a truncated scan and "
            "policy.allow_incomplete_corpus is False; refusing to prepare "
            "research from an incomplete corpus"
        )

    evidence_packet = _build_evidence_packet(retrieval_trace, parse_results, manifest)
    parser_versions = _collect_parser_versions(parse_results)
    parse_result_identities = _collect_parse_result_identities(parse_results)
    manifest_content_hash = canonical_hash(manifest.model_dump(exclude={"created_at"}))

    warnings = tuple(retrieval_trace.warnings)

    prepared_id = compute_prepared_id(
        request_id=request.request_id,
        corpus_id=manifest.corpus_id,
        manifest_content_hash=manifest_content_hash,
        parser_versions=parser_versions,
        parse_result_identities=parse_result_identities,
        retrieval_trace_id=retrieval_trace.trace_id,
        evidence_packet=evidence_packet,
        warnings=warnings,
        incomplete=retrieval_trace.incomplete,
    )

    return PreparedResearch(
        prepared_id=prepared_id,
        request=request,
        corpus_id=manifest.corpus_id,
        manifest_content_hash=manifest_content_hash,
        parser_versions=parser_versions,
        parse_result_identities=parse_result_identities,
        retrieval_trace=retrieval_trace,
        evidence_packet=evidence_packet,
        warnings=warnings,
        incomplete=retrieval_trace.incomplete,
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )


def _collect_parser_versions(parse_results: Sequence[ParseResult]) -> tuple[ParserVersionInfo, ...]:
    seen: dict[tuple[str | None, str | None, str | None, str | None], ParserVersionInfo] = {}
    for result in parse_results:
        if result.parser_name is None:
            continue
        info = ParserVersionInfo(
            parser_name=result.parser_name,
            parser_version=result.parser_version or "",
            normalization_policy_version=result.normalization_policy_version,
            chunking_policy_version=result.chunking_policy_version,
        )
        key = (
            info.parser_name,
            info.parser_version,
            info.normalization_policy_version,
            info.chunking_policy_version,
        )
        seen[key] = info
    return tuple(sorted(seen.values(), key=lambda info: (info.parser_name, info.parser_version)))


def _collect_parse_result_identities(
    parse_results: Sequence[ParseResult],
) -> tuple[ParseResultIdentity, ...]:
    identities = [
        ParseResultIdentity(
            document_id=result.document_id,
            status=result.status.value,
            source_content_hash=result.source_content_hash,
            result_hash=canonical_hash(result),
        )
        for result in parse_results
    ]
    return tuple(sorted(identities, key=lambda identity: identity.document_id))


def _build_evidence_packet(
    retrieval_trace: RetrievalTrace,
    parse_results: Sequence[ParseResult],
    manifest: CorpusManifest,
) -> tuple[EvidenceItem, ...]:
    """Build the evidence packet from exactly the trace's selected
    candidates, cross-checking each against the real chunk it claims to
    be. Never includes a chunk the retrieval trace did not select."""
    chunks_by_id: dict[str, DocumentChunk] = {}
    for result in parse_results:
        if result.status is ParseStatus.SUCCEEDED:
            for parsed_chunk in result.chunks:
                chunks_by_id[parsed_chunk.chunk_id] = parsed_chunk
    content_hash_by_document_id = {
        document.document_id: document.content_hash for document in manifest.documents
    }

    selected = sorted(
        (candidate for candidate in retrieval_trace.candidates if candidate.selected),
        key=lambda candidate: (
            candidate.relative_path,
            candidate.anchor_start_line,
            candidate.chunk_id,
        ),
    )

    items: list[EvidenceItem] = []
    for candidate in selected:
        chunk = chunks_by_id.get(candidate.chunk_id)
        if chunk is None:
            raise EvidencePacketMismatchError(
                f"selected candidate {candidate.chunk_id!r} has no corresponding chunk "
                "in the supplied parse results"
            )
        if chunk.document_id != candidate.document_id:
            raise EvidencePacketMismatchError(
                f"chunk {chunk.chunk_id!r} document_id {chunk.document_id!r} does not "
                f"match the selected candidate's document_id {candidate.document_id!r}"
            )
        if candidate.score is None or candidate.rank is None:
            raise EvidencePacketMismatchError(
                f"selected candidate {candidate.chunk_id!r} is missing its score or rank"
            )
        actual_hash = sha256_hex(chunk.text.encode("utf-8"))
        if actual_hash != chunk.normalized_content_hash:
            raise EvidencePacketMismatchError(
                f"chunk {chunk.chunk_id!r} text does not match its own recorded hash"
            )

        items.append(
            EvidenceItem(
                document_id=chunk.document_id,
                relative_path=candidate.relative_path,
                chunk_id=chunk.chunk_id,
                anchor=chunk.anchor,
                text=chunk.text,
                content_hash=actual_hash,
                document_content_hash=content_hash_by_document_id.get(
                    chunk.document_id, candidate.document_content_hash
                ),
                score=candidate.score,
                rank=candidate.rank,
            )
        )
    return tuple(items)
