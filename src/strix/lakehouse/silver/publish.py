"""Atomic, partitioned Parquet publication for Silver datasets.

A dataset is published by writing all partition files plus the publication manifest
into a staging directory, then swapping it into place — so a failed or interrupted
transformation can never expose a partially published dataset. Financial values are
coerced to their declared ``decimal128`` scale (exact; never via float). Each
Parquet file is content-hashed for integrity verification.

Transforms are a deterministic full recompute from the immutable Bronze layer, so
reruns are idempotent and previously referenced data stays reproducible (same
Bronze -> same Silver).
"""

from __future__ import annotations

import shutil
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pyarrow as pa
import pyarrow.parquet as pq

from strix.canonical import sha256_hex
from strix.lakehouse.silver import SILVER_VERSION
from strix.lakehouse.silver.models import (
    ParquetFile,
    PublicationManifest,
    ReconciliationReport,
)
from strix.lakehouse.silver.schemas import DatasetSchema

_COMPRESSION: Final = "zstd"
_DATE_FIELDS_FOR_YEAR = ("date", "observation_date", "session_date", "period_end", "filed_date")


def publish_dataset(
    root: Path,
    schema: DatasetSchema,
    rows: list[dict[str, Any]],
    reconciliation: ReconciliationReport,
    *,
    now: datetime,
) -> PublicationManifest:
    """Publish ``rows`` as partitioned Parquet + manifest, atomically."""
    dataset_dir = root / "silver" / schema.name
    staging = root / "silver" / f".staging-{schema.name}-{int(now.timestamp() * 1000)}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    partitions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        partitions[_partition_value(schema, row)].append(row)

    files: list[ParquetFile] = []
    try:
        for partition, part_rows in sorted(partitions.items()):
            table = _to_table(schema, part_rows)
            rel = f"{partition}/data.parquet"
            path = staging / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(table, path, compression=_COMPRESSION)
            data = path.read_bytes()
            files.append(
                ParquetFile(
                    partition=partition,
                    relative_path=f"silver/{schema.name}/{rel}",
                    rows=table.num_rows,
                    byte_size=len(data),
                    content_hash=sha256_hex(data),
                )
            )
        manifest = PublicationManifest(
            dataset=schema.name,
            schema_version=schema.schema_version,
            silver_version=SILVER_VERSION,
            published_at=now,
            row_count=len(rows),
            natural_key_count=len({r["natural_key"] for r in rows}),
            files=tuple(files),
            reconciliation=reconciliation,
        )
        from strix.canonical import pretty_json_bytes

        (staging / "_publication.json").write_bytes(pretty_json_bytes(manifest.model_dump()))
        _swap(staging, dataset_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return manifest


def _swap(staging: Path, final: Path) -> None:
    """Replace ``final`` with ``staging`` as atomically as the FS allows."""
    backup = final.with_name(final.name + f".old-{staging.name}")
    if final.exists():
        final.rename(backup)
    try:
        staging.rename(final)
    except OSError:
        if backup.exists():  # restore prior state on failure
            backup.rename(final)
        raise
    finally:
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)


def _partition_value(schema: DatasetSchema, row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in schema.partition_keys:
        if key == "year":
            parts.append(str(_year_of(row)))
        else:
            parts.append(str(row.get(key, "unknown")))
    return "_".join(parts)


def _year_of(row: dict[str, Any]) -> int:
    for field_name in _DATE_FIELDS_FOR_YEAR:
        value = row.get(field_name)
        if isinstance(value, date):
            return value.year
    return 0


def _to_table(schema: DatasetSchema, rows: list[dict[str, Any]]) -> pa.Table:
    arrays = []
    for field in schema.arrow_schema:
        values = [_coerce(field.type, r.get(field.name)) for r in rows]
        arrays.append(pa.array(values, type=field.type))
    return pa.Table.from_arrays(arrays, schema=schema.arrow_schema)


def _coerce(arrow_type: pa.DataType, value: Any) -> Any:
    if value is None:
        return None
    if pa.types.is_decimal(arrow_type) and isinstance(value, Decimal):
        quantum = Decimal(1).scaleb(-arrow_type.scale)
        return value.quantize(quantum)
    return value
