"""Immutable Bronze ingestion with append-only provenance.

The Bronze layer preserves raw source payloads byte-exact and content-addressed,
so identical bytes are stored once and every downstream dataset can trace back to
the exact source evidence. Each ingestion *event* also writes an append-only
:class:`ProvenanceManifest` (keyed by the event's parameters, including retrieval
time), so re-fetching identical bytes later records a new provenance entry while
the raw object deduplicates.

Layout under the lakehouse root::

    bronze/<source>/<dataset>/<entity>/<partition>/<sha256>.<ext>   # raw (immutable)
    bronze/_manifests/<source>/<dataset>/<ingestion_id>.manifest.json

Ingestion never mutates or overwrites: a content-hash collision with different
bytes, or a read-back hash mismatch, raises :class:`LakehouseIntegrityError`.
"""

from __future__ import annotations

from datetime import datetime

from strix.canonical import pretty_json_bytes, sha256_hex, to_jsonable
from strix.errors import IngestionError, LakehouseIntegrityError
from strix.lakehouse.contracts import (
    MEDIA_EXTENSIONS,
    DatasetRef,
    IngestionResult,
    ProvenanceManifest,
    RawArtifact,
)
from strix.lakehouse.storage import ObjectStore

_ENTITY_SHARED = "_shared"


class BronzeIngestor:
    """Writes immutable raw artifacts and append-only provenance manifests."""

    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def ingest(
        self,
        ref: DatasetRef,
        raw: bytes,
        *,
        endpoint: str,
        retrieved_at: datetime,
        producer: str,
        request_params: dict[str, str] | None = None,
        media_type: str = "application/json",
        record_count: int | None = None,
    ) -> IngestionResult:
        """Preserve ``raw`` immutably and record one provenance manifest."""
        if media_type not in MEDIA_EXTENSIONS:
            raise IngestionError(f"unsupported media_type {media_type!r}")
        if retrieved_at.tzinfo is None:
            raise IngestionError("retrieved_at must be timezone-aware")
        params = {str(k): str(v) for k, v in (request_params or {}).items()}

        content_hash = sha256_hex(raw)
        ext = MEDIA_EXTENSIONS[media_type]
        artifact_rel = self._artifact_path(ref, content_hash, ext)
        artifact = RawArtifact(
            artifact_id=RawArtifact.make_id(ref.source, ref.dataset, content_hash),
            source=ref.source,
            dataset=ref.dataset,
            entity=ref.entity,
            partition=ref.partition,
            content_hash=content_hash,
            byte_size=len(raw),
            media_type=media_type,
            relative_path=artifact_rel,
        )
        artifact_written = self._store.put_immutable(artifact_rel, raw)
        # Independent read-back integrity check.
        if sha256_hex(self._store.get(artifact_rel)) != content_hash:
            raise LakehouseIntegrityError(
                f"preserved artifact {artifact_rel} failed read-back hash verification"
            )

        ingestion_id = ProvenanceManifest.make_id(
            ref.source,
            ref.dataset,
            content_hash,
            to_jsonable(retrieved_at),
            endpoint,
            params,
        )
        manifest = ProvenanceManifest(
            ingestion_id=ingestion_id,
            source=ref.source,
            dataset=ref.dataset,
            entity=ref.entity,
            partition=ref.partition,
            endpoint=endpoint,
            request_params=params,
            retrieved_at=retrieved_at,
            artifact=artifact,
            record_count=record_count,
            producer=producer,
        )
        manifest_rel = self._manifest_path(ref, ingestion_id)
        manifest_written = self._store.put_immutable(
            manifest_rel, pretty_json_bytes(manifest.model_dump())
        )
        return IngestionResult(
            manifest=manifest,
            artifact_written=artifact_written,
            manifest_written=manifest_written,
        )

    def read_artifact(self, artifact: RawArtifact) -> bytes:
        """Read preserved bytes and verify their content hash."""
        data = self._store.get(artifact.relative_path)
        if sha256_hex(data) != artifact.content_hash:
            raise LakehouseIntegrityError(
                f"artifact {artifact.artifact_id} failed hash verification on read"
            )
        return data

    # -- path construction (deterministic, filesystem-safe) ----------------

    @staticmethod
    def _artifact_path(ref: DatasetRef, content_hash: str, ext: str) -> str:
        entity = ref.entity or _ENTITY_SHARED
        prefix = f"bronze/{ref.source.value}/{ref.dataset}/{entity}/{ref.partition}"
        return f"{prefix}/{content_hash}.{ext}"

    @staticmethod
    def _manifest_path(ref: DatasetRef, ingestion_id: str) -> str:
        return f"bronze/_manifests/{ref.source.value}/{ref.dataset}/{ingestion_id}.manifest.json"
