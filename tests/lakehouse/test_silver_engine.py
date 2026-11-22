"""End-to-end Bronze->Silver transform tests (real BronzeIngestor + Parquet)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
from tests.lakehouse.silver_fixtures import ALPACA_BARS, BLS_PAYLOAD

from strix.lakehouse.bronze import BronzeIngestor
from strix.lakehouse.contracts import DatasetRef, DataSource
from strix.lakehouse.silver.engine import SilverTransformer
from strix.lakehouse.storage import LocalObjectStore

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _ingest(tmp_path: Path, ref: DatasetRef, raw: bytes, *, when: datetime = _NOW) -> str:
    bronze = BronzeIngestor(LocalObjectStore(tmp_path))
    result = bronze.ingest(ref, raw, endpoint="https://example", retrieved_at=when, producer="t")
    return result.manifest.artifact.artifact_id


def test_transform_publishes_and_reconciles(tmp_path: Path) -> None:
    artifact_id = _ingest(
        tmp_path,
        DatasetRef(source=DataSource.ALPACA, dataset="equity_bars_daily", entity="SPY",
                   partition="2026-11"),
        ALPACA_BARS,
    )
    result = SilverTransformer(tmp_path, clock=lambda: _NOW).transform("alpaca_equity_bars_daily")

    assert result.published
    rec = result.reconciliation
    assert rec.balanced
    assert rec.extracted_observations == 2
    assert rec.accepted == 2
    assert rec.published_rows == 2

    parquet = tmp_path / "silver" / "alpaca_equity_bars_daily" / "SPY" / "data.parquet"
    assert parquet.is_file()
    table = pq.read_table(parquet)
    assert table.num_rows == 2
    cols = set(table.column_names)
    assert {"close", "natural_key", "bronze_artifact_id", "source_locator"} <= cols
    # Evidence reconstruction: the published row traces back to its Bronze artifact.
    assert table.column("bronze_artifact_id")[0].as_py() == artifact_id
    # Decimal preserved exactly (stored at the schema's decimal128(18,6) scale).
    from decimal import Decimal

    assert Decimal("102.25") in table.column("close").to_pylist()


def test_transform_is_idempotent(tmp_path: Path) -> None:
    ref = DatasetRef(source=DataSource.ALPACA, dataset="equity_bars_daily", entity="SPY",
                     partition="2026-11")
    _ingest(tmp_path, ref, ALPACA_BARS)
    t = SilverTransformer(tmp_path, clock=lambda: _NOW)
    first = t.transform("alpaca_equity_bars_daily")
    second = t.transform("alpaca_equity_bars_daily")
    assert first.reconciliation.accepted == second.reconciliation.accepted == 2
    assert second.reconciliation.balanced and second.published


def test_bls_volatile_envelope_dedups_at_observation_level(tmp_path: Path) -> None:
    # Two BLS artifacts: identical observations, different response envelopes.
    envelope_a = BLS_PAYLOAD
    doc = json.loads(BLS_PAYLOAD)
    doc["status"] = "REQUEST_SUCCEEDED"  # volatile envelope field, same observations
    envelope_b = json.dumps(doc).encode()
    assert envelope_a != envelope_b

    for i, raw in enumerate((envelope_a, envelope_b)):
        _ingest(
            tmp_path,
            DatasetRef(source=DataSource.BLS, dataset="timeseries", entity="CUUR0000SA0",
                       partition="full"),
            raw,
            when=datetime(2026, 11, 22, 12 + i, tzinfo=UTC),
        )

    result = SilverTransformer(tmp_path, clock=lambda: _NOW).transform("bls_observations")
    rec = result.reconciliation
    assert rec.extracted_observations == 4  # 2 obs x 2 artifacts
    assert rec.accepted == 2  # deduped to canonical observations
    assert rec.duplicates == 2
    assert rec.balanced


def test_verify_detects_parquet_tampering(tmp_path: Path) -> None:
    import io

    from strix.lakehouse.silver.cli import _load_manifest, _verify

    _ingest(
        tmp_path,
        DatasetRef(source=DataSource.ALPACA, dataset="equity_bars_daily", entity="SPY",
                   partition="2026-11"),
        ALPACA_BARS,
    )
    SilverTransformer(tmp_path, clock=lambda: _NOW).transform("alpaca_equity_bars_daily")
    assert _verify(tmp_path, io.StringIO(), as_json=False) == 0

    manifest = _load_manifest(tmp_path, "alpaca_equity_bars_daily")
    assert manifest is not None
    (tmp_path / manifest.files[0].relative_path).write_bytes(b"CORRUPT")
    assert _verify(tmp_path, io.StringIO(), as_json=False) == 1  # integrity failure detected
