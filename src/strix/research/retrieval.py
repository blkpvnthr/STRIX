"""The deterministic lexical retrieval pipeline.

:func:`retrieve` turns a :class:`~strix.research.models.ResearchRequest`
plus a corpus's preserved :class:`~strix.corpus.parsers.models.ParseResult`
objects into a :class:`~strix.research.models.RetrievalTrace`, applying,
in order:

1. request filters (document_filter: allowed/excluded document_id, path,
   extension);
2. lexical scoring;
3. minimum-score cutoff;
4. stable ranking (score descending, ties broken by path, anchor
   position, chunk_id);
5. per-document cap;
6. selected-chunk cap;
7. selected-character budget.

Every candidate chunk gets exactly one :class:`RetrievalCandidate` entry
-- selected, or excluded with a specific typed reason -- and a document
whose ParseResult did not succeed gets its own
:class:`~strix.research.models.UnavailableDocument` entry instead of a
zero-relevance chunk. Nothing is read from the live evidence directory,
nothing is reparsed, and nothing calls the network.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from strix.canonical import canonical_hash, sha256_hex
from strix.corpus.models import CorpusManifest
from strix.corpus.parsers.models import DocumentChunk, ParseResult, ParseStatus
from strix.errors import CandidatePoolTooLargeError, CorpusMismatchError, RetrievalIntegrityError
from strix.research.models import (
    DocumentFilter,
    ExclusionReason,
    ResearchRequest,
    RetrievalBudget,
    RetrievalCandidate,
    RetrievalTrace,
    ScoreComponents,
    UnavailableDocument,
    compute_trace_id,
)
from strix.research.normalize import NORMALIZATION_POLICY_VERSION, TOKENIZATION_POLICY_VERSION
from strix.research.scoring import SCORING_POLICY_VERSION, PreparedQuery, prepare_query, score_chunk

RETRIEVAL_POLICY_VERSION = "1.0.0"

#: Version of the deterministic character-based token-count ESTIMATE
#: below. Explicitly labeled as a heuristic, not a real tokenizer count --
#: no language-model tokenizer is used anywhere in this phase.
ESTIMATED_TOKEN_HEURISTIC_VERSION = "1.0.0"


def estimate_token_count(char_count: int) -> int:
    """A labeled, versioned, deterministic ESTIMATE only.

    ceil(char_count / 4) -- the commonly-cited rough ratio for English
    text -- computed with integer arithmetic (ceiling division), never a
    float and never a real tokenizer's count.
    """
    return -(-char_count // 4)


def compute_chunk_inventory_hash(ordered_chunks: Sequence[DocumentChunk]) -> str:
    """SHA-256 over the canonically ordered (document_id, chunk_id) pairs
    of every chunk supplied to retrieval."""
    payload = [
        {"document_id": chunk.document_id, "chunk_id": chunk.chunk_id} for chunk in ordered_chunks
    ]
    return canonical_hash(payload)


def retrieve(
    request: ResearchRequest,
    manifest: CorpusManifest,
    parse_results: Sequence[ParseResult],
    *,
    created_at: datetime | None = None,
) -> RetrievalTrace:
    """Run deterministic lexical retrieval; see the module docstring for
    the exact selection order. Raises :class:`CorpusMismatchError` if
    *request.corpus_id* does not match *manifest.corpus_id*,
    :class:`RetrievalIntegrityError` if any supplied chunk or ParseResult
    fails independent re-verification, and
    :class:`CandidatePoolTooLargeError` if the supplied chunk inventory
    exceeds ``request.budget.max_candidate_chunks``.

    Every field of the returned trace except ``created_at`` (and hence
    ``trace_id``, which excludes it) is a pure function of the inputs —
    repeated calls with the same arguments and an explicit *created_at*
    produce an identical trace.
    """
    if request.corpus_id != manifest.corpus_id:
        raise CorpusMismatchError(
            f"request corpus_id {request.corpus_id!r} does not match the supplied "
            f"parsed corpus {manifest.corpus_id!r}"
        )

    path_by_document_id = {
        document.document_id: document.relative_path for document in manifest.documents
    }
    content_hash_by_document_id = {
        document.document_id: document.content_hash for document in manifest.documents
    }

    unavailable_documents: list[UnavailableDocument] = []
    all_chunks: list[DocumentChunk] = []
    for result in parse_results:
        relative_path = path_by_document_id.get(result.document_id, result.document_id)
        if result.status is not ParseStatus.SUCCEEDED:
            reason = result.failure.message if result.failure is not None else "parse unavailable"
            unavailable_documents.append(
                UnavailableDocument(
                    document_id=result.document_id, relative_path=relative_path, reason=reason
                )
            )
            continue
        _revalidate_parse_result(result)
        all_chunks.extend(result.chunks)

    if len(all_chunks) > request.budget.max_candidate_chunks:
        raise CandidatePoolTooLargeError(
            f"supplied {len(all_chunks)} candidate chunks exceeds "
            f"budget.max_candidate_chunks={request.budget.max_candidate_chunks}"
        )

    all_chunks.sort(
        key=lambda chunk: (
            path_by_document_id.get(chunk.document_id, chunk.document_id),
            chunk.anchor.start_line,
            chunk.chunk_id,
        )
    )
    chunk_inventory_hash = compute_chunk_inventory_hash(all_chunks)

    query = prepare_query(request.query_terms, max_query_terms=request.budget.max_query_terms)
    normalized_query_terms = tuple(sorted(query.tokens))

    candidates = _build_candidates(
        all_chunks, path_by_document_id, content_hash_by_document_id, request, query
    )
    _apply_ranking(candidates)
    _apply_budgets(candidates, request.budget)

    frozen_candidates = tuple(candidate.to_model() for candidate in candidates)
    selected = [candidate for candidate in frozen_candidates if candidate.selected]
    selected_ranked = sorted(selected, key=lambda c: c.rank if c.rank is not None else 0)
    selected_chunk_ids = tuple(candidate.chunk_id for candidate in selected_ranked)
    selected_document_ids = tuple(sorted({candidate.document_id for candidate in selected}))
    distinct_content_hashes = {candidate.document_content_hash for candidate in selected}
    total_selected_characters = sum(candidate.char_count for candidate in selected)
    total_estimated_selected_tokens = sum(candidate.estimated_token_count for candidate in selected)

    incomplete = manifest.truncated
    warnings: list[str] = []
    if len(distinct_content_hashes) < len(selected_document_ids):
        warnings.append(
            "two or more selected documents are byte-identical copies at different "
            "paths; distinct_selected_content_hashes is the number to treat as the "
            "ceiling on independent evidence, not distinct_selected_document_count"
        )
    if incomplete:
        warnings.append(
            "the corpus snapshot came from a truncated scan; this is not an "
            "exhaustive search over the full evidence root"
        )

    trace_id = compute_trace_id(
        request_id=request.request_id,
        corpus_id=manifest.corpus_id,
        retrieval_policy_version=RETRIEVAL_POLICY_VERSION,
        normalization_policy_version=NORMALIZATION_POLICY_VERSION,
        tokenization_policy_version=TOKENIZATION_POLICY_VERSION,
        scoring_policy_version=SCORING_POLICY_VERSION,
        token_estimate_heuristic_version=ESTIMATED_TOKEN_HEURISTIC_VERSION,
        chunk_inventory_hash=chunk_inventory_hash,
        document_filter=request.document_filter,
        normalized_query_terms=normalized_query_terms,
        candidates=frozen_candidates,
        unavailable_documents=tuple(unavailable_documents),
        selected_chunk_ids=selected_chunk_ids,
        selected_document_ids=selected_document_ids,
        applied_budget=request.budget,
        total_selected_characters=total_selected_characters,
        total_estimated_selected_tokens=total_estimated_selected_tokens,
        distinct_selected_document_count=len(selected_document_ids),
        distinct_selected_content_hashes=len(distinct_content_hashes),
        incomplete=incomplete,
        warnings=tuple(warnings),
    )

    return RetrievalTrace(
        trace_id=trace_id,
        request_id=request.request_id,
        corpus_id=manifest.corpus_id,
        retrieval_policy_version=RETRIEVAL_POLICY_VERSION,
        normalization_policy_version=NORMALIZATION_POLICY_VERSION,
        tokenization_policy_version=TOKENIZATION_POLICY_VERSION,
        scoring_policy_version=SCORING_POLICY_VERSION,
        token_estimate_heuristic_version=ESTIMATED_TOKEN_HEURISTIC_VERSION,
        chunk_inventory_hash=chunk_inventory_hash,
        document_filter=request.document_filter,
        normalized_query_terms=normalized_query_terms,
        candidates=frozen_candidates,
        unavailable_documents=tuple(unavailable_documents),
        selected_chunk_ids=selected_chunk_ids,
        selected_document_ids=selected_document_ids,
        applied_budget=request.budget,
        total_selected_characters=total_selected_characters,
        total_estimated_selected_tokens=total_estimated_selected_tokens,
        distinct_selected_document_count=len(selected_document_ids),
        distinct_selected_content_hashes=len(distinct_content_hashes),
        incomplete=incomplete,
        warnings=tuple(warnings),
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )


def _revalidate_parse_result(result: ParseResult) -> None:
    """Independently re-verify ordering, document_id consistency, and
    content hashes before any chunk from *result* is used for scoring --
    catches a chunk/anchor tampered via model_copy, which bypasses the
    models' own construction-time validators."""
    for index, chunk in enumerate(result.chunks):
        if chunk.sequence_index != index:
            raise RetrievalIntegrityError(
                f"chunk ordering invalid for document {result.document_id!r}: "
                f"expected sequence_index {index}, found {chunk.sequence_index}"
            )
        if chunk.document_id != result.document_id:
            raise RetrievalIntegrityError(
                f"chunk {chunk.chunk_id!r} document_id {chunk.document_id!r} does not "
                f"match its ParseResult's document_id {result.document_id!r}"
            )
        if chunk.anchor.document_id != chunk.document_id:
            raise RetrievalIntegrityError(
                f"chunk {chunk.chunk_id!r} anchor document_id {chunk.anchor.document_id!r} "
                f"does not match the chunk's own document_id {chunk.document_id!r}"
            )
        expected_hash = sha256_hex(chunk.text.encode("utf-8"))
        if (
            expected_hash != chunk.normalized_content_hash
            or expected_hash != chunk.anchor.normalized_content_hash
        ):
            raise RetrievalIntegrityError(
                f"chunk {chunk.chunk_id!r} failed anchor-hash revalidation"
            )
    for previous, current in zip(result.chunks, result.chunks[1:], strict=False):
        if current.anchor.start_line <= previous.anchor.end_line:
            raise RetrievalIntegrityError(
                f"chunks overlap or are out of order in document {result.document_id!r}: "
                f"chunk ending at line {previous.anchor.end_line} is followed by one "
                f"starting at line {current.anchor.start_line}"
            )


def _filter_exclusion(
    document_id: str, relative_path: str, document_filter: DocumentFilter
) -> ExclusionReason | None:
    if (
        document_filter.allowed_document_ids
        and document_id not in document_filter.allowed_document_ids
    ):
        return ExclusionReason.FILTERED_DOCUMENT
    if document_id in document_filter.excluded_document_ids:
        return ExclusionReason.FILTERED_DOCUMENT
    if (
        document_filter.allowed_relative_paths
        and relative_path not in document_filter.allowed_relative_paths
    ):
        return ExclusionReason.FILTERED_PATH_OR_EXTENSION
    if relative_path in document_filter.excluded_relative_paths:
        return ExclusionReason.FILTERED_PATH_OR_EXTENSION
    extension = Path(relative_path).suffix.lower()
    if document_filter.allowed_extensions and extension not in document_filter.allowed_extensions:
        return ExclusionReason.FILTERED_PATH_OR_EXTENSION
    if extension in document_filter.excluded_extensions:
        return ExclusionReason.FILTERED_PATH_OR_EXTENSION
    return None


class _CandidateState:
    """Mutable staging for one candidate while selection runs; converted
    to a frozen RetrievalCandidate once every field is final."""

    __slots__ = (
        "anchor_end_line",
        "anchor_start_line",
        "char_count",
        "chunk_id",
        "document_content_hash",
        "document_id",
        "estimated_token_count",
        "exclusion_reason",
        "rank",
        "relative_path",
        "score",
        "selected",
    )

    def __init__(
        self, chunk: DocumentChunk, relative_path: str, document_content_hash: str
    ) -> None:
        self.chunk_id = chunk.chunk_id
        self.document_id = chunk.document_id
        self.relative_path = relative_path
        self.document_content_hash = document_content_hash
        self.anchor_start_line = chunk.anchor.start_line
        self.anchor_end_line = chunk.anchor.end_line
        self.char_count = chunk.char_count
        self.estimated_token_count = estimate_token_count(chunk.char_count)
        self.score: ScoreComponents | None = None
        self.rank: int | None = None
        self.selected = False
        self.exclusion_reason: ExclusionReason | None = None

    def to_model(self) -> RetrievalCandidate:
        return RetrievalCandidate(
            chunk_id=self.chunk_id,
            document_id=self.document_id,
            relative_path=self.relative_path,
            document_content_hash=self.document_content_hash,
            anchor_start_line=self.anchor_start_line,
            anchor_end_line=self.anchor_end_line,
            char_count=self.char_count,
            estimated_token_count=self.estimated_token_count,
            score=self.score,
            rank=self.rank,
            selected=self.selected,
            exclusion_reason=self.exclusion_reason,
        )


def _build_candidates(
    chunks: Sequence[DocumentChunk],
    path_by_document_id: dict[str, str],
    content_hash_by_document_id: dict[str, str],
    request: ResearchRequest,
    query: PreparedQuery,
) -> list[_CandidateState]:
    candidates: list[_CandidateState] = []
    for chunk in chunks:
        relative_path = path_by_document_id.get(chunk.document_id, chunk.document_id)
        document_content_hash = content_hash_by_document_id.get(chunk.document_id, "0" * 64)
        state = _CandidateState(chunk, relative_path, document_content_hash)

        filter_reason = _filter_exclusion(chunk.document_id, relative_path, request.document_filter)
        if filter_reason is not None:
            state.exclusion_reason = filter_reason
            candidates.append(state)
            continue

        score = score_chunk(chunk.text, query)
        state.score = score
        if score.total_score == 0:
            state.exclusion_reason = ExclusionReason.NO_QUERY_MATCH
        elif score.total_score < request.budget.minimum_score:
            state.exclusion_reason = ExclusionReason.BELOW_CUTOFF
        # else: tentatively selected, pending ranking/budget steps below.
        candidates.append(state)
    return candidates


def _ranking_key(candidate: _CandidateState) -> tuple[object, ...]:
    assert candidate.score is not None  # guaranteed by the pool filter below
    return (
        -candidate.score.total_score,
        candidate.relative_path,
        candidate.anchor_start_line,
        candidate.chunk_id,
    )


def _apply_ranking(candidates: list[_CandidateState]) -> None:
    """Step 4: stable ranking among candidates that passed the cutoff."""
    pool = [c for c in candidates if c.score is not None and c.exclusion_reason is None]
    ranked = sorted(pool, key=_ranking_key)
    for index, candidate in enumerate(ranked, start=1):
        candidate.rank = index


def _apply_budgets(candidates: list[_CandidateState], budget: RetrievalBudget) -> None:
    """Steps 5-7: per-document cap, selected-chunk cap, character budget.

    Walks the ranked pool in rank order; a candidate that doesn't fit is
    excluded (never split or truncated) and the walk continues to the
    next-ranked candidate, so a smaller lower-ranked chunk can still be
    selected if a larger higher-ranked one didn't fit.
    """
    ranked = sorted(
        (c for c in candidates if c.rank is not None),
        key=lambda c: c.rank if c.rank is not None else 0,
    )
    per_document_selected: dict[str, int] = {}
    selected_count = 0
    remaining_characters = budget.max_selected_characters

    for candidate in ranked:
        if per_document_selected.get(candidate.document_id, 0) >= budget.max_chunks_per_document:
            candidate.exclusion_reason = ExclusionReason.PER_DOCUMENT_CAP
            continue
        if selected_count >= budget.max_selected_chunks:
            candidate.exclusion_reason = ExclusionReason.CHUNK_COUNT_BUDGET
            continue
        if candidate.char_count > remaining_characters:
            candidate.exclusion_reason = ExclusionReason.CHARACTER_BUDGET
            continue

        candidate.selected = True
        per_document_selected[candidate.document_id] = (
            per_document_selected.get(candidate.document_id, 0) + 1
        )
        selected_count += 1
        remaining_characters -= candidate.char_count
