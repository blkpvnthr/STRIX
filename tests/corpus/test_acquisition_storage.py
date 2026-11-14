"""Tests for AcquiredDocumentStore and the acquire_pdf orchestration:
deterministic content-addressed storage, dedup/reuse, tamper detection,
atomic cleanup, secret redaction, and real-evidence-root isolation.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from tests.corpus.acquisition_fixtures import (
    PDF_BYTES,
    SAFE_HOST,
    SAFE_IPV4,
    make_plan,
    make_result,
)

from strix.corpus.acquisition.downloader import PdfDownloader
from strix.corpus.acquisition.network_safety import StaticResolver
from strix.corpus.acquisition.policy import AcquisitionPolicy
from strix.corpus.acquisition.storage import AcquiredDocumentStore, acquire_pdf
from strix.errors import AcquiredDocumentIntegrityError


def _downloader(handler: object, evidence_root: Path | None = None) -> PdfDownloader:
    return PdfDownloader(
        AcquisitionPolicy(),
        resolver=StaticResolver({SAFE_HOST: (SAFE_IPV4,)}),
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


def _pdf_handler(body: bytes = PDF_BYTES) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf", "content-length": str(len(body))},
            content=body,
        )

    return handler


# --------------------------------------------------------------------------
# AcquiredDocumentStore.commit: deterministic filenames, dedup, tamper
# --------------------------------------------------------------------------


def test_commit_uses_a_deterministic_content_addressed_filename(tmp_path: Path) -> None:
    store = AcquiredDocumentStore(tmp_path)
    relative_path, absolute_path = store.commit(PDF_BYTES)

    import hashlib

    expected_hash = hashlib.sha256(PDF_BYTES).hexdigest()
    assert relative_path == f"{expected_hash}.pdf"
    assert absolute_path == tmp_path / "acquired" / relative_path
    assert absolute_path.read_bytes() == PDF_BYTES


def test_different_content_produces_a_different_filename(tmp_path: Path) -> None:
    store = AcquiredDocumentStore(tmp_path)
    path1, _ = store.commit(PDF_BYTES)
    path2, _ = store.commit(PDF_BYTES + b"\x00")
    assert path1 != path2


def test_duplicate_content_is_reused_not_rewritten(tmp_path: Path) -> None:
    store = AcquiredDocumentStore(tmp_path)
    _relative, absolute1 = store.commit(PDF_BYTES)
    recorded_mtime = absolute1.stat().st_mtime_ns

    _relative, absolute2 = store.commit(PDF_BYTES)

    assert absolute1 == absolute2
    assert absolute2.stat().st_mtime_ns == recorded_mtime


def test_a_different_file_at_the_same_content_address_is_never_overwritten(tmp_path: Path) -> None:
    store = AcquiredDocumentStore(tmp_path)
    _relative_path, absolute_path = store.commit(PDF_BYTES)

    # Simulate collision/corruption: different bytes at the same name.
    absolute_path.write_bytes(b"%PDF-tampered")

    with pytest.raises(AcquiredDocumentIntegrityError):
        store.commit(PDF_BYTES)

    # Not silently repaired or overwritten.
    assert absolute_path.read_bytes() == b"%PDF-tampered"


def test_interrupted_commit_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AcquiredDocumentStore(tmp_path)

    import strix.corpus.acquisition.storage as storage_module

    def flaky_write_atomic(path: Path, data: bytes) -> None:
        raise RuntimeError("simulated crash mid-write")

    monkeypatch.setattr(storage_module, "_write_atomic", flaky_write_atomic)

    with pytest.raises(RuntimeError):
        store.commit(PDF_BYTES)

    acquired_dir = tmp_path / "acquired"
    # No completed file, no leftover staging directory.
    assert list(acquired_dir.iterdir()) == []


def test_commit_writes_only_beneath_acquired_subdirectory(tmp_path: Path) -> None:
    store = AcquiredDocumentStore(tmp_path)
    store.commit(PDF_BYTES)
    # Nothing was written directly under evidence_root itself.
    assert {p.name for p in tmp_path.iterdir()} == {"acquired"}


# --------------------------------------------------------------------------
# acquire_pdf: orchestration, deterministic IDs, record-after-commit
# --------------------------------------------------------------------------


def test_acquire_pdf_produces_a_deterministic_acquisition_id(tmp_path: Path) -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    downloader = _downloader(_pdf_handler())
    store = AcquiredDocumentStore(tmp_path)

    record1 = acquire_pdf(downloader, store, result, plan)
    record2 = acquire_pdf(
        PdfDownloader(
            AcquisitionPolicy(),
            resolver=StaticResolver({SAFE_HOST: (SAFE_IPV4,)}),
            transport=httpx.MockTransport(_pdf_handler()),  # type: ignore[arg-type]
        ),
        AcquiredDocumentStore(tmp_path),
        result,
        plan,
    )

    assert record1.acquisition_id == record2.acquisition_id
    assert record1.stored_relative_path == record2.stored_relative_path
    assert record1.acquisition_id.startswith("ACQUISITION-")


def test_acquire_pdf_record_is_only_produced_after_a_successful_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    downloader = _downloader(_pdf_handler())
    store = AcquiredDocumentStore(tmp_path)

    def failing_commit(self: AcquiredDocumentStore, data: bytes) -> tuple[str, Path]:
        raise RuntimeError("simulated storage failure")

    monkeypatch.setattr(AcquiredDocumentStore, "commit", failing_commit)

    with pytest.raises(RuntimeError):
        acquire_pdf(downloader, store, result, plan)


def test_acquire_pdf_record_matches_the_stored_document(tmp_path: Path) -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    downloader = _downloader(_pdf_handler())
    store = AcquiredDocumentStore(tmp_path)

    record = acquire_pdf(downloader, store, result, plan)

    stored_path = tmp_path / "acquired" / record.stored_relative_path
    assert stored_path.read_bytes() == PDF_BYTES
    assert record.byte_size == len(PDF_BYTES)
    assert record.result_id == result.result_id
    assert record.plan_id == plan.plan_id


# --------------------------------------------------------------------------
# Secret redaction
# --------------------------------------------------------------------------


def test_signed_query_parameters_are_redacted_from_the_record(tmp_path: Path) -> None:
    secret = "super-secret-signature-value"
    document_url = f"https://{SAFE_HOST}/doc.pdf?X-Signature={secret}&page=1"
    plan = make_plan()
    result = make_result(plan, document_url=document_url)
    downloader = _downloader(_pdf_handler())
    store = AcquiredDocumentStore(tmp_path)

    record = acquire_pdf(downloader, store, result, plan)

    assert secret not in record.original_url
    assert secret not in record.final_url
    assert "page=1" in record.original_url  # non-sensitive params are preserved
    assert "REDACTED" in record.original_url


def test_redaction_does_not_affect_the_actual_request() -> None:
    """The real (unredacted) URL is what the transport actually receives."""
    secret = "needed-for-the-real-request"
    document_url = f"https://{SAFE_HOST}/doc.pdf?token={secret}"
    plan = make_plan()
    result = make_result(plan, document_url=document_url)
    received = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["url"] = str(request.url)
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf", "content-length": str(len(PDF_BYTES))},
            content=PDF_BYTES,
        )

    downloader = PdfDownloader(
        AcquisitionPolicy(),
        resolver=StaticResolver({SAFE_HOST: (SAFE_IPV4,)}),
        transport=httpx.MockTransport(handler),
    )
    downloader.fetch(result, plan)
    assert secret in received["url"]


# --------------------------------------------------------------------------
# Zero writes to the real evidence root
# --------------------------------------------------------------------------


def test_nothing_in_this_module_touches_the_real_evidence_root() -> None:
    real_acquired = Path("/Users/blkpvnthr/STRIX/docs/acquired")
    assert not real_acquired.exists()
