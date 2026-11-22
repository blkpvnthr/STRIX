"""Typed contracts for Silver quality, reconciliation, and publication."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import AwareDatetime, ConfigDict, Field

from strix.lakehouse.silver import SILVER_VERSION
from strix.models import StrixModel


class QuarantineReason(StrEnum):
    MISSING_REQUIRED_FIELD = "missing_required_field"
    SCHEMA_NONCONFORMITY = "schema_nonconformity"
    INVALID_OHLC = "invalid_ohlc_relationship"
    NEGATIVE_VOLUME = "negative_volume"
    INVALID_TIMESTAMP = "invalid_timestamp"
    TEMPORAL_INCONSISTENCY = "temporal_inconsistency"
    CONFLICTING_VALUE = "conflicting_value_same_natural_key"
    SUPERSEDED_REVISION = "superseded_by_later_retrieval"


class QuarantinedRow(StrixModel):
    """An observation withheld from publication, with a machine-readable reason."""

    dataset: str
    reason: QuarantineReason
    detail: str
    natural_key: str
    bronze_artifact_id: str
    source_locator: str


class ReconciliationReport(StrixModel):
    """Balances every extracted observation against the published dataset."""

    dataset: str
    source_artifacts: int
    extracted_observations: int
    accepted: int
    duplicates: int
    quarantined: int
    excluded: int
    published_rows: int
    revisions_retained: int
    discrepancies: tuple[str, ...] = ()

    @property
    def balanced(self) -> bool:
        accounted = self.accepted + self.duplicates + self.quarantined + self.excluded
        return accounted == self.extracted_observations and not self.discrepancies


class ParquetFile(StrixModel):
    partition: str
    relative_path: str
    rows: int
    byte_size: int
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class PublicationManifest(StrixModel):
    """Versioned record of one Silver dataset publication."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: str
    schema_version: str
    silver_version: str = SILVER_VERSION
    published_at: AwareDatetime
    row_count: int
    natural_key_count: int
    files: tuple[ParquetFile, ...]
    reconciliation: ReconciliationReport


class TransformResult(StrixModel):
    """Outcome of transforming one Silver dataset."""

    dataset: str
    published: bool
    manifest: PublicationManifest | None
    reconciliation: ReconciliationReport
    quarantined: tuple[QuarantinedRow, ...]
    blocked_reason: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
