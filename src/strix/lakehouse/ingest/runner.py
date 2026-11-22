"""Ingestion orchestration: backfill, incremental, idempotent reruns, recovery.

The runner drives a :class:`SourceExtractor` into the immutable Bronze layer:
each raw batch is preserved via :class:`BronzeIngestor` (dedup + provenance),
the incremental watermark is advanced in a persistent checkpoint, partial
failures are caught per entity (what was ingested stays ingested), coverage/gaps
are computed for missing-window detection, and source batches are reconciled
against what Bronze actually wrote.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime, timedelta

from strix.errors import StrixError
from strix.lakehouse import LAKEHOUSE_VERSION
from strix.lakehouse.bronze import BronzeIngestor
from strix.lakehouse.ingest.checkpoints import CheckpointStore
from strix.lakehouse.ingest.contracts import (
    Checkpoint,
    ExtractionWindow,
    IngestionStats,
    SourceExtractor,
)

#: Default earliest date for a backfill when none is supplied.
DEFAULT_BACKFILL_START = date(2015, 1, 1)


class IngestionRunner:
    """Runs extractors into Bronze with checkpoints, recovery, reconciliation."""

    def __init__(
        self,
        bronze: BronzeIngestor,
        checkpoints: CheckpointStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._bronze = bronze
        self._checkpoints = checkpoints
        self._clock = clock or (lambda: datetime.now(UTC))

    # -- public API --------------------------------------------------------

    def backfill(
        self,
        extractor: SourceExtractor,
        window: ExtractionWindow,
        *,
        entities: Sequence[str | None] | None = None,
    ) -> list[IngestionStats]:
        window.validate_order()
        return [
            self._run_entity(extractor, entity, window)
            for entity in (entities if entities is not None else extractor.entities())
        ]

    def incremental(
        self,
        extractor: SourceExtractor,
        *,
        now: date | None = None,
        default_start: date = DEFAULT_BACKFILL_START,
        entities: Sequence[str | None] | None = None,
    ) -> list[IngestionStats]:
        today = now or self._clock().date()
        results: list[IngestionStats] = []
        for entity in entities if entities is not None else extractor.entities():
            cp = self._checkpoints.load(extractor.source, extractor.dataset, entity)
            start = _next_day(cp.watermark) if cp.watermark else default_start
            if start > today:
                results.append(
                    self._empty_stats(extractor, entity, cp.watermark)
                )  # already current
                continue
            results.append(
                self._run_entity(extractor, entity, ExtractionWindow(start=start, end=today))
            )
        return results

    # -- core --------------------------------------------------------------

    def _run_entity(
        self, extractor: SourceExtractor, entity: str | None, window: ExtractionWindow
    ) -> IngestionStats:
        started = self._clock()
        if not extractor.available():
            return IngestionStats(
                source=extractor.source,
                dataset=extractor.dataset,
                entity=entity,
                failures=(f"unavailable: {extractor.unavailable_reason()}",),
                reconciled=True,
                started_at=started,
                finished_at=self._clock(),
            )

        batches_fetched = batches_written = batches_deduped = 0
        records = bytes_in = artifacts_written = 0
        covered: list[tuple[str, str]] = []
        failures: list[str] = []
        watermark = self._checkpoints.load(
            extractor.source, extractor.dataset, entity
        ).watermark

        try:
            for batch in extractor.extract(entity, window):
                retrieved_at = self._clock()
                result = self._bronze.ingest(
                    batch.ref,
                    batch.raw,
                    endpoint=batch.endpoint,
                    retrieved_at=retrieved_at,
                    producer=f"{extractor.source.value}_extractor/{LAKEHOUSE_VERSION}",
                    request_params=batch.request_params,
                    media_type=batch.media_type,
                    record_count=batch.record_count,
                )
                batches_fetched += 1
                if result.artifact_written:
                    batches_written += 1
                    artifacts_written += 1
                else:
                    batches_deduped += 1
                records += batch.record_count or 0
                bytes_in += len(batch.raw)
                if batch.observation_window:
                    covered.append(batch.observation_window)
                watermark = _max_watermark(watermark, batch.watermark)
        except StrixError as exc:
            # Partial-failure recovery: keep everything already ingested.
            failures.append(f"extraction aborted: {exc}")

        finished = self._clock()
        merged = _merge_ranges(covered)
        gaps = _subtract(window, merged) if merged else ()
        reconciled = batches_fetched == (batches_written + batches_deduped)

        if not failures:
            self._advance_checkpoint(extractor, entity, watermark, batches_fetched, records)

        return IngestionStats(
            source=extractor.source,
            dataset=extractor.dataset,
            entity=entity,
            batches_fetched=batches_fetched,
            batches_written=batches_written,
            batches_deduped=batches_deduped,
            records_ingested=records,
            bytes_ingested=bytes_in,
            raw_artifacts_written=artifacts_written,
            watermark=watermark,
            coverage=merged,
            gaps=gaps,
            failures=tuple(failures),
            reconciled=reconciled,
            started_at=started,
            finished_at=finished,
        )

    def _advance_checkpoint(
        self,
        extractor: SourceExtractor,
        entity: str | None,
        watermark: str | None,
        batches: int,
        records: int,
    ) -> None:
        cp = self._checkpoints.load(extractor.source, extractor.dataset, entity)
        self._checkpoints.save(
            Checkpoint(
                source=extractor.source,
                dataset=extractor.dataset,
                entity=entity,
                watermark=_max_watermark(cp.watermark, watermark),
                last_run_at=self._clock(),
                batches_ingested=cp.batches_ingested + batches,
                records_ingested=cp.records_ingested + records,
            )
        )

    def _empty_stats(
        self, extractor: SourceExtractor, entity: str | None, watermark: str | None
    ) -> IngestionStats:
        ts = self._clock()
        return IngestionStats(
            source=extractor.source,
            dataset=extractor.dataset,
            entity=entity,
            watermark=watermark,
            started_at=ts,
            finished_at=ts,
        )


# --------------------------------------------------------------------------
# Date-range helpers (ISO date strings)
# --------------------------------------------------------------------------


def _next_day(iso: str) -> date:
    return date.fromisoformat(iso) + timedelta(days=1)


def _max_watermark(a: str | None, b: str | None) -> str | None:
    candidates = [x for x in (a, b) if x]
    return max(candidates) if candidates else None


def _merge_ranges(ranges: Iterable[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    items = sorted(
        (date.fromisoformat(s), date.fromisoformat(e)) for s, e in ranges if s and e
    )
    if not items:
        return ()
    merged: list[tuple[date, date]] = [items[0]]
    for start, end in items[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + timedelta(days=1):
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return tuple((s.isoformat(), e.isoformat()) for s, e in merged)


def _subtract(
    window: ExtractionWindow, covered: tuple[tuple[str, str], ...]
) -> tuple[tuple[str, str], ...]:
    """Requested window minus covered ranges → uncovered gaps (whole-day)."""
    gaps: list[tuple[str, str]] = []
    cursor = window.start
    for s, e in covered:
        cs, ce = date.fromisoformat(s), date.fromisoformat(e)
        if cs > cursor:
            gaps.append((cursor.isoformat(), (cs - timedelta(days=1)).isoformat()))
        cursor = max(cursor, ce + timedelta(days=1))
        if cursor > window.end:
            break
    if cursor <= window.end:
        gaps.append((cursor.isoformat(), window.end.isoformat()))
    return tuple(gaps)
