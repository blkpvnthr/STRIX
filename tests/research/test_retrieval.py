"""End-to-end tests for strix.research.retrieval.retrieve(): the full
selection pipeline, budgets, truncation propagation, tamper detection,
and isolation from the live evidence root and the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.research.research_fixtures import (
    NOW,
    make_corpus,
    make_failed_parse_result,
    make_request,
)

from strix.corpus.parsers.registry import default_registry, parse_corpus
from strix.corpus.scanner import DEFAULT_EVIDENCE_ROOT, scan_corpus
from strix.corpus.snapshot import CorpusStore
from strix.errors import CandidatePoolTooLargeError, CorpusMismatchError, RetrievalIntegrityError
from strix.research.models import DocumentFilter, ExclusionReason, RetrievalBudget
from strix.research.retrieval import retrieve


def _candidates_by_path(trace):
    out: dict[str, list] = {}
    for candidate in trace.candidates:
        out.setdefault(candidate.relative_path, []).append(candidate)
    return out


# --------------------------------------------------------------------------
# Basic end-to-end scoring/selection
# --------------------------------------------------------------------------


def test_matching_chunk_is_selected_and_non_matching_is_not() -> None:
    manifest, results = make_corpus(
        {
            "a.txt": b"the quick brown fox\n\nunrelated filler text\n",
            "b.txt": b"completely different weather report\n",
        }
    )
    request = make_request(manifest.corpus_id, ("fox",))
    trace = retrieve(request, manifest, results)

    by_path = _candidates_by_path(trace)
    assert by_path["a.txt"][0].selected is True
    assert by_path["a.txt"][1].exclusion_reason is ExclusionReason.NO_QUERY_MATCH
    assert by_path["b.txt"][0].exclusion_reason is ExclusionReason.NO_QUERY_MATCH


def test_zero_match_query_excludes_everything() -> None:
    manifest, results = make_corpus({"a.txt": b"some unrelated content\n"})
    request = make_request(manifest.corpus_id, ("xylophone",))
    trace = retrieve(request, manifest, results)
    assert trace.selected_chunk_ids == ()
    assert all(c.exclusion_reason is ExclusionReason.NO_QUERY_MATCH for c in trace.candidates)


def test_stable_trace_id_and_repeated_retrieval_is_identical() -> None:
    manifest, results = make_corpus({"a.txt": b"the fox and the hound\n"})
    request = make_request(manifest.corpus_id, ("fox",))
    trace1 = retrieve(request, manifest, results, created_at=NOW)
    trace2 = retrieve(request, manifest, results, created_at=NOW)
    assert trace1.trace_id.startswith("TRACE-")
    assert trace1 == trace2


def test_output_is_independent_of_parse_result_input_order() -> None:
    manifest, results = make_corpus(
        {"a.txt": b"the fox\n", "b.txt": b"the hound\n", "c.txt": b"another fox\n"}
    )
    request = make_request(manifest.corpus_id, ("fox",))
    forward = retrieve(request, manifest, results, created_at=NOW)
    reversed_trace = retrieve(request, manifest, tuple(reversed(results)), created_at=NOW)
    assert forward == reversed_trace


def test_deterministic_tie_breaking_by_path_then_position() -> None:
    # Two chunks with identical scores; the tie must break by path.
    manifest, results = make_corpus({"z.txt": b"fox\n", "a.txt": b"fox\n"})
    request = make_request(manifest.corpus_id, ("fox",))
    trace = retrieve(request, manifest, results)
    assert trace.selected_chunk_ids[0] != trace.selected_chunk_ids[1]
    # a.txt sorts before z.txt, so it must be ranked first among equal scores.
    first_selected = next(c for c in trace.candidates if c.chunk_id == trace.selected_chunk_ids[0])
    assert first_selected.relative_path == "a.txt"


# --------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------


def test_allowed_document_ids_filter_excludes_others() -> None:
    manifest, results = make_corpus({"a.txt": b"fox\n", "b.txt": b"fox\n"})
    keep_id = next(d.document_id for d in manifest.documents if d.relative_path == "a.txt")
    request = make_request(
        manifest.corpus_id,
        ("fox",),
        document_filter=DocumentFilter(allowed_document_ids=(keep_id,)),
    )
    trace = retrieve(request, manifest, results)
    by_path = _candidates_by_path(trace)
    assert by_path["a.txt"][0].selected is True
    assert by_path["b.txt"][0].exclusion_reason is ExclusionReason.FILTERED_DOCUMENT


def test_excluded_relative_path_filter() -> None:
    manifest, results = make_corpus({"a.txt": b"fox\n", "b.txt": b"fox\n"})
    request = make_request(
        manifest.corpus_id,
        ("fox",),
        document_filter=DocumentFilter(excluded_relative_paths=("b.txt",)),
    )
    trace = retrieve(request, manifest, results)
    by_path = _candidates_by_path(trace)
    assert by_path["a.txt"][0].selected is True
    assert by_path["b.txt"][0].exclusion_reason is ExclusionReason.FILTERED_PATH_OR_EXTENSION


def test_excluded_extension_filter() -> None:
    manifest, results = make_corpus({"a.txt": b"fox\n", "b.md": b"fox\n"})
    request = make_request(
        manifest.corpus_id,
        ("fox",),
        document_filter=DocumentFilter(excluded_extensions=(".md",)),
    )
    trace = retrieve(request, manifest, results)
    by_path = _candidates_by_path(trace)
    assert by_path["a.txt"][0].selected is True
    assert by_path["b.md"][0].exclusion_reason is ExclusionReason.FILTERED_PATH_OR_EXTENSION


# --------------------------------------------------------------------------
# Cutoff, caps, budgets (selection steps 3, 5, 6, 7)
# --------------------------------------------------------------------------


def test_minimum_score_cutoff_excludes_weak_matches() -> None:
    from decimal import Decimal

    manifest, results = make_corpus({"a.txt": b"fox\n\nfox fox fox fox fox fox fox\n"})
    request = make_request(
        manifest.corpus_id, ("fox",), budget=RetrievalBudget(minimum_score=Decimal(3))
    )
    trace = retrieve(request, manifest, results)
    by_path = _candidates_by_path(trace)
    weak, strong = sorted(by_path["a.txt"], key=lambda c: c.anchor_start_line)
    assert weak.exclusion_reason is ExclusionReason.BELOW_CUTOFF
    assert strong.selected is True


def test_per_document_cap_limits_chunks_selected_from_one_document() -> None:
    text = "\n\n".join(f"fox paragraph {i}" for i in range(5))
    manifest, results = make_corpus({"a.txt": text.encode()})
    request = make_request(
        manifest.corpus_id, ("fox",), budget=RetrievalBudget(max_chunks_per_document=2)
    )
    trace = retrieve(request, manifest, results)
    assert len(trace.selected_chunk_ids) == 2
    capped = [c for c in trace.candidates if c.exclusion_reason is ExclusionReason.PER_DOCUMENT_CAP]
    assert len(capped) == 3


def test_chunk_count_budget_limits_total_selected_across_documents() -> None:
    manifest, results = make_corpus({f"doc{i}.txt": b"fox\n" for i in range(5)})
    request = make_request(
        manifest.corpus_id, ("fox",), budget=RetrievalBudget(max_selected_chunks=2)
    )
    trace = retrieve(request, manifest, results)
    assert len(trace.selected_chunk_ids) == 2
    budgeted = [
        c for c in trace.candidates if c.exclusion_reason is ExclusionReason.CHUNK_COUNT_BUDGET
    ]
    assert len(budgeted) == 3


def test_character_budget_excludes_a_chunk_that_does_not_fit() -> None:
    manifest, results = make_corpus({"a.txt": b"fox " + b"x" * 100 + b"\n\nfox small\n"})
    # The budget fits the small chunk but not the big one; the ranked walk
    # should skip the oversized one and still select the smaller fit.
    big_len = len("fox " + "x" * 100)
    request = make_request(
        manifest.corpus_id, ("fox",), budget=RetrievalBudget(max_selected_characters=big_len - 1)
    )
    trace = retrieve(request, manifest, results)
    by_path = _candidates_by_path(trace)
    big, small = sorted(by_path["a.txt"], key=lambda c: c.char_count, reverse=True)
    assert big.exclusion_reason is ExclusionReason.CHARACTER_BUDGET
    assert small.selected is True


def test_oversized_chunk_is_excluded_not_truncated() -> None:
    manifest, results = make_corpus({"a.txt": b"fox " + b"y" * 500})
    request = make_request(
        manifest.corpus_id, ("fox",), budget=RetrievalBudget(max_selected_characters=10)
    )
    trace = retrieve(request, manifest, results)
    candidate = trace.candidates[0]
    assert candidate.exclusion_reason is ExclusionReason.CHARACTER_BUDGET
    assert trace.selected_chunk_ids == ()
    # Nothing in the model ever represents a "partial" or "truncated" chunk.
    assert not hasattr(candidate, "truncated_text")


def test_candidate_pool_exceeding_max_candidate_chunks_raises() -> None:
    manifest, results = make_corpus({f"doc{i}.txt": b"fox\n" for i in range(5)})
    request = make_request(
        manifest.corpus_id,
        ("fox",),
        budget=RetrievalBudget(max_candidate_chunks=3, max_selected_chunks=3),
    )
    with pytest.raises(CandidatePoolTooLargeError):
        retrieve(request, manifest, results)


# --------------------------------------------------------------------------
# Duplicate content: not counted as independent evidence
# --------------------------------------------------------------------------


def test_duplicate_content_documents_do_not_inflate_independent_count() -> None:
    manifest, results = make_corpus({"a.txt": b"the fox ran\n", "copy_of_a.txt": b"the fox ran\n"})
    request = make_request(manifest.corpus_id, ("fox",))
    trace = retrieve(request, manifest, results)

    assert trace.distinct_selected_document_count == 2
    assert trace.distinct_selected_content_hashes == 1
    assert any("byte-identical" in warning for warning in trace.warnings)


def test_distinct_content_documents_are_not_flagged_as_duplicates() -> None:
    manifest, results = make_corpus(
        {"a.txt": b"the fox ran\n", "b.txt": b"a different fox story\n"}
    )
    request = make_request(manifest.corpus_id, ("fox",))
    trace = retrieve(request, manifest, results)
    assert trace.distinct_selected_document_count == trace.distinct_selected_content_hashes == 2
    assert not any("byte-identical" in warning for warning in trace.warnings)


# --------------------------------------------------------------------------
# Failed parses, mismatched corpus, tampering
# --------------------------------------------------------------------------


def test_failed_parse_result_is_recorded_as_unavailable_not_zero_relevance() -> None:
    manifest, results = make_corpus({"a.txt": b"the fox ran\n"})
    failing_document_id = "DOC-doesnotexist000"
    request = make_request(manifest.corpus_id, ("fox",))
    trace = retrieve(
        request, manifest, (*results, make_failed_parse_result(failing_document_id, "bad encoding"))
    )
    assert len(trace.unavailable_documents) == 1
    assert trace.unavailable_documents[0].document_id == failing_document_id
    assert trace.unavailable_documents[0].reason == "bad encoding"
    # No candidate anywhere represents the unavailable document.
    assert all(c.document_id != failing_document_id for c in trace.candidates)


def test_mismatched_corpus_id_is_rejected() -> None:
    manifest, results = make_corpus({"a.txt": b"the fox ran\n"})
    request = make_request("CORPUS-" + "0" * 12, ("fox",))
    with pytest.raises(CorpusMismatchError):
        retrieve(request, manifest, results)


def test_tampered_chunk_hash_is_detected() -> None:
    manifest, results = make_corpus({"a.txt": b"the fox ran\n"})
    result = results[0]
    tampered_chunk = result.chunks[0].model_copy(update={"text": "tampered content entirely"})
    tampered_result = result.model_copy(update={"chunks": (tampered_chunk,)})
    request = make_request(manifest.corpus_id, ("fox",))
    with pytest.raises(RetrievalIntegrityError):
        retrieve(request, manifest, (tampered_result,))


def test_tampered_anchor_document_id_is_detected() -> None:
    manifest, results = make_corpus({"a.txt": b"the fox ran\n"})
    result = results[0]
    chunk = result.chunks[0]
    tampered_anchor = chunk.anchor.model_copy(update={"document_id": "DOC-" + "9" * 12})
    tampered_chunk = chunk.model_copy(update={"anchor": tampered_anchor})
    tampered_result = result.model_copy(update={"chunks": (tampered_chunk,)})
    request = make_request(manifest.corpus_id, ("fox",))
    with pytest.raises(RetrievalIntegrityError):
        retrieve(request, manifest, (tampered_result,))


# --------------------------------------------------------------------------
# Truncated corpus propagation
# --------------------------------------------------------------------------


def test_truncated_corpus_marks_retrieval_incomplete() -> None:
    manifest, results = make_corpus({"a.txt": b"the fox ran\n"}, truncated=True)
    request = make_request(manifest.corpus_id, ("fox",))
    trace = retrieve(request, manifest, results)
    assert trace.incomplete is True
    assert any("not an exhaustive search" in warning for warning in trace.warnings)


def test_non_truncated_corpus_is_not_marked_incomplete() -> None:
    manifest, results = make_corpus({"a.txt": b"the fox ran\n"}, truncated=False)
    request = make_request(manifest.corpus_id, ("fox",))
    trace = retrieve(request, manifest, results)
    assert trace.incomplete is False


# --------------------------------------------------------------------------
# No floats in serialized traces
# --------------------------------------------------------------------------


def test_no_float_values_anywhere_in_the_serialized_trace() -> None:
    manifest, results = make_corpus({"a.txt": b"the fox ran and the fox jumped\n"})
    request = make_request(manifest.corpus_id, ("fox",))
    trace = retrieve(request, manifest, results)

    from strix.canonical import pretty_json_bytes

    raw = pretty_json_bytes(trace)
    parsed = json.loads(raw)

    def assert_no_float(value: object) -> None:
        assert not isinstance(value, float)
        if isinstance(value, dict):
            for item in value.values():
                assert_no_float(item)
        elif isinstance(value, list):
            for item in value:
                assert_no_float(item)

    assert_no_float(parsed)


# --------------------------------------------------------------------------
# Real end-to-end integration + isolation
# --------------------------------------------------------------------------


def test_end_to_end_through_real_scan_snapshot_and_parse(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    (evidence_root / "a.txt").write_text("the quick fox jumps\n")

    scan = scan_corpus(evidence_root)
    store = CorpusStore(tmp_path / "snapshots")
    manifest, _directory = store.snapshot(scan)
    results = parse_corpus(store, manifest, default_registry())

    request = make_request(manifest.corpus_id, ("fox",))
    trace = retrieve(request, manifest, results)
    assert len(trace.selected_chunk_ids) == 1


# Contents of the real default evidence root at import time. The corpus
# subsystem's default root happens to be the repository docs directory, so it may
# legitimately contain documentation; the guard below tolerates that and instead
# asserts these tests ADD nothing to it (they must use tmp_path only).
_EVIDENCE_BASELINE = (
    set(DEFAULT_EVIDENCE_ROOT.iterdir()) if DEFAULT_EVIDENCE_ROOT.exists() else set()
)


def test_nothing_in_this_module_touches_the_real_evidence_root() -> None:
    current = set(DEFAULT_EVIDENCE_ROOT.iterdir()) if DEFAULT_EVIDENCE_ROOT.exists() else set()
    assert current <= _EVIDENCE_BASELINE, "tests must not write into the real evidence root"
