"""Typed contracts for ingestion: windows, raw batches, checkpoints, stats."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from pydantic import AwareDatetime

from strix.lakehouse.contracts import DatasetRef, DataSource
from strix.models import StrixModel


class ExtractionWindow(StrixModel):
    """Inclusive observation date window to extract."""

    start: date
    end: date

    def validate_order(self) -> ExtractionWindow:
        if self.start > self.end:
            raise ValueError(f"window start {self.start} is after end {self.end}")
        return self


@dataclass(frozen=True)
class RawBatch:
    """One raw payload (often one page/period) ready for Bronze preservation."""

    ref: DatasetRef
    raw: bytes
    endpoint: str
    media_type: str = "application/json"
    request_params: dict[str, str] = field(default_factory=dict)
    record_count: int | None = None
    #: Observation window these records cover, as ISO strings (for coverage).
    observation_window: tuple[str, str] | None = None
    #: Max observation key in this batch (advances the incremental watermark).
    watermark: str | None = None


class Checkpoint(StrixModel):
    """Persistent incremental state for one (source, dataset, entity)."""

    source: DataSource
    dataset: str
    entity: str | None = None
    #: Last successfully ingested observation key (e.g. ISO date), or None.
    watermark: str | None = None
    last_run_at: AwareDatetime | None = None
    batches_ingested: int = 0
    records_ingested: int = 0

    def key(self) -> str:
        return f"{self.source.value}/{self.dataset}/{self.entity or '_shared'}"


class IngestionStats(StrixModel):
    """Measured outcome of one ingestion run for one (source, dataset, entity)."""

    source: DataSource
    dataset: str
    entity: str | None = None
    batches_fetched: int = 0
    batches_written: int = 0
    batches_deduped: int = 0
    records_ingested: int = 0
    bytes_ingested: int = 0
    raw_artifacts_written: int = 0
    watermark: str | None = None
    coverage: tuple[tuple[str, str], ...] = ()
    #: Requested sub-ranges with no observations (may be legitimate, e.g. holidays).
    gaps: tuple[tuple[str, str], ...] = ()
    failures: tuple[str, ...] = ()
    reconciled: bool = True
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None

    @property
    def ok(self) -> bool:
        return not self.failures and self.reconciled


class SourceExtractor(Protocol):
    """Acquires raw payloads for one dataset of one source."""

    source: DataSource
    dataset: str

    def available(self) -> bool:
        """True when any required credentials are present."""
        ...

    def entities(self) -> tuple[str | None, ...]:
        """Entities (symbols/tickers/series ids) to ingest; (None,) for shared."""
        ...

    def extract(self, entity: str | None, window: ExtractionWindow) -> Iterator[RawBatch]:
        """Yield raw batches covering ``window`` for ``entity``."""
        ...

    def unavailable_reason(self) -> str:
        """Human-readable reason when :meth:`available` is False."""
        ...
