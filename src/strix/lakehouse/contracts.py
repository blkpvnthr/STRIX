"""Typed data contracts for the lakehouse.

All models are frozen, closed-schema, and content-id'd via
:mod:`strix.canonical`. A raw artifact is identified by the SHA-256 of its bytes
(so identical payloads deduplicate); a provenance manifest records one ingestion
*event* (which may re-fetch identical bytes at a different time) and is identified
by the event's parameters, so the manifest log is append-only while raw storage
stays deduplicated.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, ConfigDict, Field

from strix.canonical import make_id
from strix.lakehouse import LAKEHOUSE_VERSION
from strix.models import StrixModel


class DataSource(StrEnum):
    ALPACA = "alpaca"
    SEC_EDGAR = "sec_edgar"
    FRED = "fred"
    BLS = "bls"
    US_TREASURY = "us_treasury"


class Layer(StrEnum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


#: Permissible media types for a raw artifact, mapped to a file extension.
MEDIA_EXTENSIONS: dict[str, str] = {
    "application/json": "json",
    "text/csv": "csv",
    "text/plain": "txt",
    "application/xml": "xml",
    "application/octet-stream": "bin",
}


class DatasetRef(StrixModel):
    """Logical identity of a dataset partition within the lakehouse."""

    source: DataSource
    #: Logical dataset name, e.g. ``equity_bars_daily``, ``company_facts``, ``cpi``.
    dataset: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    #: Entity the partition is about (ticker, CIK, series id), or ``None`` for
    #: whole-dataset payloads. Restricted to a filesystem-safe token.
    entity: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$")
    #: Partition key — an ISO date, period label, or ``full`` for a snapshot.
    partition: str = Field(default="full", pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,31}$")


class RawArtifact(StrixModel):
    """An immutable, content-addressed raw source payload preserved in Bronze."""

    artifact_id: str
    source: DataSource
    dataset: str
    entity: str | None
    partition: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)
    media_type: str
    #: Path relative to the lakehouse root (portable; never absolute).
    relative_path: str

    @staticmethod
    def make_id(source: DataSource, dataset: str, content_hash: str) -> str:
        return make_id(
            "RAW", {"source": source, "dataset": dataset, "content_hash": content_hash}
        )


class ProvenanceManifest(StrixModel):
    """Append-only record of one Bronze ingestion event."""

    ingestion_id: str
    source: DataSource
    dataset: str
    entity: str | None
    partition: str
    #: The endpoint / locator the bytes were acquired from (no secrets).
    endpoint: str
    #: Request parameters that produced these bytes (no secrets), JSON-safe.
    request_params: dict[str, str] = Field(default_factory=dict)
    retrieved_at: AwareDatetime
    artifact: RawArtifact
    #: Number of logical records in the payload, when known.
    record_count: int | None = None
    #: What produced the ingestion (connector name + version).
    producer: str
    lakehouse_version: str = LAKEHOUSE_VERSION
    schema_version: str = "bronze-v1"

    model_config = ConfigDict(frozen=True, extra="forbid")

    @staticmethod
    def make_id(
        source: DataSource,
        dataset: str,
        content_hash: str,
        retrieved_at: str,
        endpoint: str,
        request_params: dict[str, str],
    ) -> str:
        return make_id(
            "ING",
            {
                "source": source,
                "dataset": dataset,
                "content_hash": content_hash,
                "retrieved_at": retrieved_at,
                "endpoint": endpoint,
                "request_params": request_params,
            },
        )


class IngestionResult(StrixModel):
    """Outcome of a Bronze ingestion call."""

    manifest: ProvenanceManifest
    #: True when the raw bytes were written now; False when deduplicated.
    artifact_written: bool
    #: True when this exact ingestion event's manifest was written now.
    manifest_written: bool
