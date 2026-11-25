"""Tests for the typed, content-addressed Parquet dataset layer (§7)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pytest

from strix.datastore.parquet_dataset import (
    DatasetError,
    read_dataset,
    validate_dataset,
    write_dataset,
)

_SCHEMA = pa.schema([("category", pa.string()), ("amount", pa.decimal128(18, 2))])


def _table() -> pa.Table:
    return pa.table(
        {"category": ["groceries", "dining"], "amount": [Decimal("10.50"), Decimal("20.25")]},
        schema=_SCHEMA,
    )


def test_write_and_read_round_trips_decimal_exactly(tmp_path: Path) -> None:
    manifest = write_dataset(name="spend", table=_table(), directory=tmp_path, version=1)
    assert manifest.row_count == 2
    assert manifest.columns == ("category", "amount")
    table = read_dataset(tmp_path, "spend", version=1)
    amounts = table.column("amount").to_pylist()
    assert amounts == [Decimal("10.50"), Decimal("20.25")]  # exact Decimal, no float


def test_manifest_is_content_addressed_and_deterministic(tmp_path: Path) -> None:
    m1 = write_dataset(name="spend", table=_table(), directory=tmp_path / "a", version=1)
    m2 = write_dataset(name="spend", table=_table(), directory=tmp_path / "b", version=1)
    assert m1.content_hash == m2.content_hash
    assert m1.schema_digest == m2.schema_digest


def test_validate_detects_tampering(tmp_path: Path) -> None:
    manifest = write_dataset(name="spend", table=_table(), directory=tmp_path, version=1)
    path = tmp_path / "spend-v1.parquet"
    assert validate_dataset(path, manifest) is True
    # Corrupt the file.
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))
    assert validate_dataset(path, manifest) is False


def test_atomic_write_leaves_no_temp_files(tmp_path: Path) -> None:
    write_dataset(name="spend", table=_table(), directory=tmp_path, version=1)
    leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp" or ".tmp" in p.name]
    assert leftovers == []


def test_version_in_filename_and_manifest(tmp_path: Path) -> None:
    m = write_dataset(name="spend", table=_table(), directory=tmp_path, version=3)
    assert m.version == 3
    assert (tmp_path / "spend-v3.parquet").is_file()


def test_read_missing_dataset_raises(tmp_path: Path) -> None:
    with pytest.raises(DatasetError):
        read_dataset(tmp_path, "nope", version=1)
