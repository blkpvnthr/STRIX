"""`strix ingest` command implementations.

Subcommands: backfill, incremental, status, coverage, verify. All operate on a
lakehouse root directory (``--lakehouse-dir`` / ``STRIX_LAKEHOUSE_DIR`` /
``./lakehouse``). Network is touched only during backfill/incremental.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TextIO

from strix.agent.config import merged_environment
from strix.lakehouse.bronze import BronzeIngestor
from strix.lakehouse.ingest.catalog import coverage, verify_integrity
from strix.lakehouse.ingest.checkpoints import CheckpointStore
from strix.lakehouse.ingest.contracts import ExtractionWindow, IngestionStats, SourceExtractor
from strix.lakehouse.ingest.factory import build_extractors, build_fetcher
from strix.lakehouse.ingest.rate_limit import HttpFetcher
from strix.lakehouse.ingest.runner import IngestionRunner
from strix.lakehouse.storage import LocalObjectStore


def resolve_lakehouse_dir(cli_value: str | None, environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    return Path(cli_value or env.get("STRIX_LAKEHOUSE_DIR") or "lakehouse")


def run_ingest(
    args: argparse.Namespace,
    *,
    out: TextIO,
    err: TextIO,
    environ: Mapping[str, str] | None = None,
    clock: datetime | None = None,
    fetcher: HttpFetcher | None = None,
) -> int:
    root = resolve_lakehouse_dir(getattr(args, "lakehouse_dir", None), environ)
    store = LocalObjectStore(root)
    command = args.ingest_command

    if command == "status":
        return _status(root, out)
    if command == "coverage":
        return _coverage(store, out)
    if command == "verify":
        return _verify(store, out)

    # backfill / incremental need extractors + network.
    env = merged_environment(environ)
    http = fetcher or build_fetcher()
    overrides = _universe_overrides(args)
    extractors = build_extractors(env, http, **overrides)
    selected = _select(extractors, getattr(args, "source", None), err)
    if selected is None:
        return 1

    bronze = BronzeIngestor(store)
    checkpoints = CheckpointStore(root)
    runner = IngestionRunner(bronze, checkpoints, clock=(lambda: clock) if clock else None)

    all_stats: list[IngestionStats] = []
    for name, extractor in selected.items():
        if not extractor.available():
            out.write(f"- {name}: skipped ({extractor.unavailable_reason()})\n")
            continue
        out.write(f"- {name}: {command}...\n")
        if command == "backfill":
            window = _window(args, err)
            if window is None:
                return 1
            stats = runner.backfill(extractor, window)
        else:
            stats = runner.incremental(extractor)
        all_stats.extend(stats)
        for s in stats:
            _print_stat(s, out)

    _print_totals(all_stats, out)
    return 0 if all(s.ok for s in all_stats) else 1


# -- subcommands -----------------------------------------------------------


def _status(root: Path, out: TextIO) -> int:
    checkpoints = CheckpointStore(root).all_checkpoints()
    if not checkpoints:
        out.write("No ingestion checkpoints yet.\n")
        return 0
    out.write("Ingestion checkpoints (incremental watermarks):\n")
    for cp in checkpoints:
        out.write(
            f"  {cp.key():<48} watermark={cp.watermark or '-':<12} "
            f"batches={cp.batches_ingested} records={cp.records_ingested}\n"
        )
    return 0


def _coverage(store: LocalObjectStore, out: TextIO) -> int:
    rows = coverage(store)
    if not rows:
        out.write("No Bronze data ingested yet.\n")
        return 0
    out.write("Dataset coverage (Bronze):\n")
    for c in rows:
        windows = ", ".join(f"{s}..{e}" for s, e in c.windows) or "-"
        out.write(
            f"  {c.source}/{c.dataset}: {c.manifest_count} manifests, "
            f"{c.unique_artifacts} unique artifacts, {c.records} records, "
            f"{c.bytes_total} bytes\n      windows: {windows}\n"
        )
    return 0


def _verify(store: LocalObjectStore, out: TextIO) -> int:
    report = verify_integrity(store)
    out.write(
        f"Integrity: checked {report.checked}, ok {report.ok}, "
        f"failures {len(report.failures)}\n"
    )
    for f in report.failures:
        out.write(f"  FAIL: {f}\n")
    return 0 if report.passed else 1


# -- helpers ---------------------------------------------------------------


def _universe_overrides(args: argparse.Namespace) -> dict[str, tuple[str, ...]]:
    overrides: dict[str, tuple[str, ...]] = {}
    if getattr(args, "symbols", None):
        overrides["symbols"] = tuple(
            s.strip().upper() for s in args.symbols.split(",") if s.strip()
        )
    if getattr(args, "tickers", None):
        overrides["tickers"] = tuple(
            t.strip().upper() for t in args.tickers.split(",") if t.strip()
        )
    if getattr(args, "series", None):
        series = tuple(s.strip() for s in args.series.split(",") if s.strip())
        overrides["fred_series"] = series
        overrides["bls_series"] = series
    return overrides


def _select(
    extractors: dict[str, SourceExtractor], source: str | None, err: TextIO
) -> dict[str, SourceExtractor] | None:
    if not source or source == "all":
        return extractors
    picked = {
        name: ex
        for name, ex in extractors.items()
        if name == source or name.split(".", 1)[0] == source
    }
    if not picked:
        err.write(
            f"Error: unknown source {source!r}. Choices: all, "
            + ", ".join(sorted({n.split('.', 1)[0] for n in extractors}))
            + "\n"
        )
        return None
    return picked


def _window(args: argparse.Namespace, err: TextIO) -> ExtractionWindow | None:
    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end) if args.end else datetime.now(UTC).date()
    except ValueError as exc:
        err.write(f"Error: invalid date: {exc}\n")
        return None
    if start > end:
        err.write("Error: --start is after --end\n")
        return None
    return ExtractionWindow(start=start, end=end)


def _print_stat(s: IngestionStats, out: TextIO) -> None:
    status = "ok" if s.ok else "FAIL"
    entity = s.entity or "-"
    out.write(
        f"    [{status}] {entity:<14} batches={s.batches_fetched} "
        f"(new={s.batches_written}, dedup={s.batches_deduped}) "
        f"records={s.records_ingested} bytes={s.bytes_ingested} wm={s.watermark or '-'}\n"
    )
    for f in s.failures:
        out.write(f"        ! {f}\n")
    if s.gaps:
        gaps = ", ".join(f"{a}..{b}" for a, b in s.gaps)
        out.write(f"        gaps: {gaps}\n")


def _print_totals(stats: list[IngestionStats], out: TextIO) -> None:
    if not stats:
        return
    out.write(
        f"\nTotals: {sum(s.batches_written for s in stats)} new artifacts, "
        f"{sum(s.batches_deduped for s in stats)} deduped, "
        f"{sum(s.records_ingested for s in stats)} records, "
        f"{sum(s.bytes_ingested for s in stats)} bytes; "
        f"{sum(1 for s in stats if not s.ok)} entities with issues.\n"
    )
