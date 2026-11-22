"""Tests for the Bronze catalog: coverage and integrity verification."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from strix.lakehouse.bronze import BronzeIngestor
from strix.lakehouse.contracts import DatasetRef, DataSource
from strix.lakehouse.ingest.catalog import coverage, load_manifests, verify_integrity
from strix.lakehouse.storage import LocalObjectStore

_NOW = datetime(2026, 11, 22, tzinfo=UTC)


def _seed(tmp_path: Path) -> LocalObjectStore:
    store = LocalObjectStore(tmp_path)
    bronze = BronzeIngestor(store)
    for day, payload in (("2026-11-20", b"a"), ("2026-11-21", b"b")):
        bronze.ingest(
            DatasetRef(
                source=DataSource.ALPACA, dataset="equity_bars_daily", entity="SPY", partition=day
            ),
            payload,
            endpoint="https://example/bars",
            retrieved_at=_NOW,
            producer="test",
            record_count=1,
        )
    return store


def test_coverage_summary(tmp_path: Path) -> None:
    store = _seed(tmp_path)
    [cov] = coverage(store)
    assert cov.source == "alpaca"
    assert cov.manifest_count == 2
    assert cov.unique_artifacts == 2
    assert cov.records == 2
    assert cov.windows == (("2026-11-20", "2026-11-21"),)


def test_verify_integrity_passes(tmp_path: Path) -> None:
    store = _seed(tmp_path)
    report = verify_integrity(store)
    assert report.passed
    assert report.checked == 2 and report.ok == 2


def test_verify_detects_corruption(tmp_path: Path) -> None:
    _seed(tmp_path)
    # Simulate on-disk corruption of a preserved artifact (bypassing the store).
    artifacts = [
        p
        for p in (tmp_path / "bronze" / "alpaca").rglob("*.json")
        if not p.name.endswith(".manifest.json")
    ]
    artifacts[0].write_bytes(b"CORRUPTED")
    report = verify_integrity(LocalObjectStore(tmp_path))
    assert not report.passed
    assert any("hash mismatch" in f for f in report.failures)


def test_load_manifests_filter_by_source(tmp_path: Path) -> None:
    store = _seed(tmp_path)
    assert len(load_manifests(store, source=DataSource.ALPACA)) == 2
    assert load_manifests(store, source=DataSource.FRED) == []
