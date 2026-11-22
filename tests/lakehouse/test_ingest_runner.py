"""Tests for the ingestion runner: idempotency, incremental, recovery, gaps."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

from strix.errors import IngestionError
from strix.lakehouse.bronze import BronzeIngestor
from strix.lakehouse.contracts import DatasetRef, DataSource
from strix.lakehouse.ingest.checkpoints import CheckpointStore
from strix.lakehouse.ingest.contracts import ExtractionWindow, RawBatch
from strix.lakehouse.ingest.runner import IngestionRunner
from strix.lakehouse.storage import LocalObjectStore

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _batch(entity: str, day: str, payload: bytes) -> RawBatch:
    return RawBatch(
        ref=DatasetRef(
            source=DataSource.ALPACA, dataset="equity_bars_daily", entity=entity, partition=day
        ),
        raw=payload,
        endpoint="https://example/bars",
        request_params={"d": day},
        record_count=1,
        observation_window=(day, day),
        watermark=day,
    )


class FakeExtractor:
    source = DataSource.ALPACA
    dataset = "equity_bars_daily"

    def __init__(
        self, batches: list[RawBatch], *, available: bool = True, raise_after: int | None = None
    ):
        self._batches = batches
        self._available = available
        self._raise_after = raise_after
        self.windows_seen: list[ExtractionWindow] = []

    def available(self) -> bool:
        return self._available

    def unavailable_reason(self) -> str:
        return "no creds"

    def entities(self) -> tuple[str | None, ...]:
        return ("SPY",)

    def extract(self, entity: str | None, window: ExtractionWindow) -> Iterator[RawBatch]:
        self.windows_seen.append(window)
        for i, b in enumerate(self._batches):
            if self._raise_after is not None and i == self._raise_after:
                raise IngestionError("simulated mid-stream failure")
            yield b


def _runner(tmp_path: Path) -> tuple[IngestionRunner, CheckpointStore]:
    cps = CheckpointStore(tmp_path)
    runner = IngestionRunner(
        BronzeIngestor(LocalObjectStore(tmp_path)), cps, clock=lambda: _NOW
    )
    return runner, cps


def test_backfill_writes_and_advances_checkpoint(tmp_path: Path) -> None:
    ex = FakeExtractor([_batch("SPY", "2026-11-20", b"a"), _batch("SPY", "2026-11-21", b"b")])
    runner, cps = _runner(tmp_path)
    window = ExtractionWindow(start=date(2026, 11, 20), end=date(2026, 11, 21))
    [stats] = runner.backfill(ex, window)
    assert stats.batches_written == 2
    assert stats.records_ingested == 2
    assert stats.watermark == "2026-11-21"
    assert stats.ok
    cp = cps.load(DataSource.ALPACA, "equity_bars_daily", "SPY")
    assert cp.watermark == "2026-11-21"


def test_rerun_is_idempotent(tmp_path: Path) -> None:
    batches = [_batch("SPY", "2026-11-20", b"a")]
    window = ExtractionWindow(start=date(2026, 11, 20), end=date(2026, 11, 20))
    runner, _ = _runner(tmp_path)
    runner.backfill(FakeExtractor(list(batches)), window)
    [again] = runner.backfill(FakeExtractor(list(batches)), window)
    assert again.batches_written == 0
    assert again.batches_deduped == 1
    assert again.ok


def test_incremental_resumes_from_watermark(tmp_path: Path) -> None:
    runner, _ = _runner(tmp_path)
    runner.backfill(
        FakeExtractor([_batch("SPY", "2026-11-20", b"a")]),
        ExtractionWindow(start=date(2026, 11, 20), end=date(2026, 11, 20)),
    )
    ex = FakeExtractor([_batch("SPY", "2026-11-21", b"b")])
    runner.incremental(ex, now=date(2026, 11, 22))
    # Window starts the day AFTER the stored watermark.
    assert ex.windows_seen[0].start == date(2026, 11, 21)


def test_incremental_noop_when_current(tmp_path: Path) -> None:
    runner, _ = _runner(tmp_path)
    runner.backfill(
        FakeExtractor([_batch("SPY", "2026-11-22", b"a")]),
        ExtractionWindow(start=date(2026, 11, 22), end=date(2026, 11, 22)),
    )
    ex = FakeExtractor([_batch("SPY", "2026-11-23", b"b")])
    [stats] = runner.incremental(ex, now=date(2026, 11, 22))  # already current
    assert ex.windows_seen == []  # extract not called
    assert stats.batches_fetched == 0


def test_partial_failure_preserves_prior_batches_and_holds_checkpoint(tmp_path: Path) -> None:
    ex = FakeExtractor(
        [_batch("SPY", "2026-11-20", b"a"), _batch("SPY", "2026-11-21", b"b")], raise_after=1
    )
    runner, cps = _runner(tmp_path)
    window = ExtractionWindow(start=date(2026, 11, 20), end=date(2026, 11, 21))
    [stats] = runner.backfill(ex, window)
    assert stats.batches_written == 1  # first batch preserved
    assert stats.failures  # failure recorded
    assert not stats.ok
    # Checkpoint must NOT advance on failure (so a rerun retries the window).
    assert cps.load(DataSource.ALPACA, "equity_bars_daily", "SPY").watermark is None


def test_unavailable_extractor_reports_without_crash(tmp_path: Path) -> None:
    runner, _ = _runner(tmp_path)
    [stats] = runner.backfill(
        FakeExtractor([], available=False),
        ExtractionWindow(start=date(2026, 11, 20), end=date(2026, 11, 20)),
    )
    assert stats.batches_fetched == 0
    assert any("unavailable" in f for f in stats.failures)


def test_missing_window_gap_detected(tmp_path: Path) -> None:
    # Cover 11-20 and 11-22 but request 11-20..11-22 -> 11-21 is a gap.
    ex = FakeExtractor([_batch("SPY", "2026-11-20", b"a"), _batch("SPY", "2026-11-22", b"c")])
    runner, _ = _runner(tmp_path)
    window = ExtractionWindow(start=date(2026, 11, 20), end=date(2026, 11, 22))
    [stats] = runner.backfill(ex, window)
    assert ("2026-11-21", "2026-11-21") in stats.gaps
