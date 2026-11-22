"""Shared helpers for warehouse tests: seed a lakehouse with Bronze + Silver."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.lakehouse.silver_fixtures import ALPACA_BARS, SEC_FACTS

from strix.lakehouse.bronze import BronzeIngestor
from strix.lakehouse.contracts import DatasetRef, DataSource
from strix.lakehouse.silver.engine import SilverTransformer
from strix.lakehouse.storage import LocalObjectStore

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def seed_lakehouse(root: Path, *, with_sec: bool = True, when: datetime = NOW) -> Path:
    """Ingest Bronze fixtures and publish Silver; return the lakehouse root."""
    bronze = BronzeIngestor(LocalObjectStore(root))
    bronze.ingest(
        DatasetRef(source=DataSource.ALPACA, dataset="equity_bars_daily", entity="SPY",
                   partition="2026-11"),
        ALPACA_BARS, endpoint="https://example", retrieved_at=when, producer="t",
    )
    datasets = ["alpaca_equity_bars_daily"]
    if with_sec:
        bronze.ingest(
            DatasetRef(source=DataSource.SEC_EDGAR, dataset="company_facts", entity="CIK0000320193",
                       partition="full"),
            SEC_FACTS, endpoint="https://example", retrieved_at=when, producer="t",
        )
        datasets.append("sec_company_facts")
    transformer = SilverTransformer(root, clock=lambda: when)
    for ds in datasets:
        transformer.transform(ds)
    return root


def ingest_alpaca_revision(root: Path, *, close: str, when: datetime) -> None:
    """Ingest a corrected SPY bar (same session_date, different close) + re-publish."""
    bars = json.loads(ALPACA_BARS)
    bars["bars"][-1]["c"] = float(close)  # change the latest bar's close
    bronze = BronzeIngestor(LocalObjectStore(root))
    bronze.ingest(
        DatasetRef(source=DataSource.ALPACA, dataset="equity_bars_daily", entity="SPY",
                   partition="2026-11"),
        json.dumps(bars).encode(), endpoint="https://example", retrieved_at=when, producer="t",
    )
    SilverTransformer(root, clock=lambda: when).transform("alpaca_equity_bars_daily")
