"""Content-addressed, atomically-published Parquet datasets (§7).

A typed Arrow table is written to ``<dir>/<name>-v<version>.parquet`` via a temp
file + atomic rename, and described by a :class:`DatasetManifest` carrying the row
count, a canonical schema digest, and the SHA-256 of the Parquet bytes. The manifest
lets any reader independently validate the dataset's integrity. Decimal columns
(Arrow ``decimal128``) round-trip exactly — money never becomes a float.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from strix.canonical import canonical_hash
from strix.errors import StrixError
from strix.models import StrixModel


class DatasetError(StrixError):
    """Raised on a missing, unreadable, or malformed Parquet dataset."""


class DatasetManifest(StrixModel):
    """The content-addressed description of one published Parquet dataset."""

    name: str
    version: int
    row_count: int
    schema_digest: str
    content_hash: str
    columns: tuple[str, ...]


def _schema_digest(schema: pa.Schema) -> str:
    return canonical_hash([[f.name, str(f.type)] for f in schema])


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataset_path(directory: Path | str, name: str, version: int) -> Path:
    return Path(directory) / f"{name}-v{version}.parquet"


def write_dataset(
    *, name: str, table: pa.Table, directory: Path | str, version: int
) -> DatasetManifest:
    """Atomically publish ``table`` as a content-addressed Parquet dataset."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    final = dataset_path(directory, name, version)

    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{name}-v{version}-", suffix=".tmp")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        # Deterministic bytes: no writer timestamp/padding so the content hash is stable.
        pq.write_table(table, tmp_path, write_statistics=False, store_schema=True)
        with tmp_path.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp_path, final)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    return DatasetManifest(
        name=name,
        version=version,
        row_count=table.num_rows,
        schema_digest=_schema_digest(table.schema),
        content_hash=_sha256_file(final),
        columns=tuple(table.schema.names),
    )


def read_dataset(directory: Path | str, name: str, version: int) -> pa.Table:
    """Read a published dataset back as an Arrow table."""
    path = dataset_path(directory, name, version)
    if not path.is_file():
        raise DatasetError(f"dataset {name!r} v{version} not found at {path}")
    try:
        return pq.read_table(path)
    except Exception as exc:  # malformed / truncated parquet
        raise DatasetError(f"cannot read dataset {name!r} v{version}: {exc}") from exc


def validate_dataset(path: Path | str, manifest: DatasetManifest) -> bool:
    """True iff the Parquet file at ``path`` matches ``manifest`` (hash + schema + rows)."""
    path = Path(path)
    if not path.is_file():
        return False
    if _sha256_file(path) != manifest.content_hash:
        return False
    try:
        table = pq.read_table(path)
    except Exception:
        return False
    return (
        table.num_rows == manifest.row_count
        and _schema_digest(table.schema) == manifest.schema_digest
        and tuple(table.schema.names) == manifest.columns
    )
