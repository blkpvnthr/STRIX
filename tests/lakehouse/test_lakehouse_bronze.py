"""Tests for immutable Bronze ingestion + provenance."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from strix.errors import IngestionError
from strix.lakehouse.bronze import BronzeIngestor
from strix.lakehouse.contracts import DatasetRef, DataSource
from strix.lakehouse.storage import LocalObjectStore

_T1 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
_T2 = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
_REF = DatasetRef(source=DataSource.ALPACA, dataset="equity_bars_daily", entity="SPY",
                  partition="2026-11-20")


def _ingestor(tmp_path: Path) -> BronzeIngestor:
    return BronzeIngestor(LocalObjectStore(tmp_path))


def test_ingest_writes_artifact_and_manifest(tmp_path: Path) -> None:
    ing = _ingestor(tmp_path)
    result = ing.ingest(
        _REF, b'{"bars":[1,2,3]}', endpoint="https://data.alpaca.markets/...",
        retrieved_at=_T1, producer="alpaca/1.0", record_count=3,
    )
    assert result.artifact_written is True
    assert result.manifest_written is True
    m = result.manifest
    assert m.artifact.content_hash == __import__("hashlib").sha256(b'{"bars":[1,2,3]}').hexdigest()
    assert m.artifact.relative_path.startswith("bronze/alpaca/equity_bars_daily/SPY/2026-11-20/")
    assert m.record_count == 3
    assert ing.read_artifact(m.artifact) == b'{"bars":[1,2,3]}'


def test_identical_event_is_fully_idempotent(tmp_path: Path) -> None:
    ing = _ingestor(tmp_path)
    ing.ingest(_REF, b"data", endpoint="u", retrieved_at=_T1, producer="p")
    again = ing.ingest(_REF, b"data", endpoint="u", retrieved_at=_T1, producer="p")
    assert again.artifact_written is False
    assert again.manifest_written is False  # same event -> same manifest id


def test_refetch_dedups_raw_but_records_new_provenance(tmp_path: Path) -> None:
    ing = _ingestor(tmp_path)
    first = ing.ingest(_REF, b"data", endpoint="u", retrieved_at=_T1, producer="p")
    later = ing.ingest(_REF, b"data", endpoint="u", retrieved_at=_T2, producer="p")
    # Raw bytes deduplicate (content-addressed)...
    assert later.artifact_written is False
    assert later.manifest.artifact.content_hash == first.manifest.artifact.content_hash
    # ...but the later re-fetch is a new append-only provenance entry.
    assert later.manifest_written is True
    assert later.manifest.ingestion_id != first.manifest.ingestion_id


def test_rejects_unsupported_media_type(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="unsupported media_type"):
        _ingestor(tmp_path).ingest(
            _REF, b"x", endpoint="u", retrieved_at=_T1, producer="p",
            media_type="application/pdf",
        )


def test_rejects_naive_datetime(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="timezone-aware"):
        _ingestor(tmp_path).ingest(
            _REF, b"x", endpoint="u", retrieved_at=datetime(2026, 11, 22, 12, 0), producer="p",
        )


def test_manifest_persisted_and_reloadable(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    ing = BronzeIngestor(store)
    result = ing.ingest(_REF, b"payload", endpoint="u", retrieved_at=_T1, producer="p")
    manifest_rel = (
        f"bronze/_manifests/alpaca/equity_bars_daily/{result.manifest.ingestion_id}.manifest.json"
    )
    assert store.exists(manifest_rel)
    import json

    loaded = json.loads(store.get(manifest_rel))
    assert loaded["ingestion_id"] == result.manifest.ingestion_id
    assert loaded["source"] == "alpaca"
