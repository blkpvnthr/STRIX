"""Seed a rich lakehouse (Bronze -> Silver -> warehouse) for DE-5 dbt tests.

Generates enough real-shaped data across all five sources that the full dbt DAG
(staging -> intermediate -> marts) produces non-trivial, independently checkable
results: multiple instruments (index + sector ETFs), two annual SEC fiscal years for
one filer, a Treasury curve on two dates, and a FRED CPI series with a revision.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from strix.lakehouse.bronze import BronzeIngestor
from strix.lakehouse.contracts import DatasetRef, DataSource
from strix.lakehouse.silver.engine import SilverTransformer
from strix.lakehouse.storage import LocalObjectStore
from strix.lakehouse.warehouse.duckdb_warehouse import DuckDBWarehouse

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)

# close-price paths (6 sessions) per symbol
_PRICES: dict[str, list[float]] = {
    "SPY": [500.0, 505.0, 498.0, 510.0, 507.0, 515.0],
    "QQQ": [430.0, 435.0, 428.0, 440.0, 437.0, 445.0],
    "XLK": [200.0, 203.0, 199.0, 206.0, 204.0, 210.0],
    "XLF": [40.0, 40.2, 39.8, 40.5, 40.3, 40.6],
}
_SESSIONS = [
    "2026-11-13", "2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20",
]


def _alpaca_payload(prices: list[float]) -> bytes:
    bars = []
    for day, close in zip(_SESSIONS, prices, strict=True):
        o = close
        hi = round(o * 1.006, 4)
        lo = round(o * 0.994, 4)
        bars.append({
            "t": f"{day}T05:00:00Z", "o": o, "h": hi, "l": lo, "c": close,
            "v": 1_000_000, "n": 5000, "vw": round((hi + lo) / 2, 4),
        })
    return json.dumps({"bars": bars, "next_page_token": None}).encode()


def _sec_payload() -> bytes:
    def ann(concept: str, fy24: int, fy25: int) -> dict:
        return {
            "units": {"USD": [
                {"start": "2023-10-01", "end": "2024-09-28", "val": fy24,
                 "accn": "0000320193-24-000100", "fy": 2024, "fp": "FY",
                 "form": "10-K", "filed": "2024-11-01"},
                {"start": "2024-09-29", "end": "2025-09-27", "val": fy25,
                 "accn": "0000320193-25-000100", "fy": 2025, "fp": "FY",
                 "form": "10-K", "filed": "2025-10-31"},
            ]}
        }
    return json.dumps({
        "cik": 320193, "entityName": "Apple Inc.",
        "facts": {"us-gaap": {
            "Revenues": ann("Revenues", 391_035_000_000, 416_000_000_000),
            "GrossProfit": ann("GrossProfit", 180_683_000_000, 190_000_000_000),
            "OperatingIncomeLoss": ann("OperatingIncomeLoss", 123_216_000_000, 130_000_000_000),
            "NetIncomeLoss": ann("NetIncomeLoss", 93_736_000_000, 99_000_000_000),
        }},
    }).encode()


def _treasury_xml() -> bytes:
    def entry(d: str, two: str, three_m: str, ten: str, thirty: str) -> bytes:
        return (
            b"<entry><content><m:properties>"
            + f"<d:NEW_DATE>{d}T00:00:00</d:NEW_DATE>".encode()
            + f"<d:BC_2YEAR>{two}</d:BC_2YEAR>".encode()
            + f"<d:BC_3MONTH>{three_m}</d:BC_3MONTH>".encode()
            + f"<d:BC_10YEAR>{ten}</d:BC_10YEAR>".encode()
            + f"<d:BC_30YEAR>{thirty}</d:BC_30YEAR>".encode()
            + b"</m:properties></content></entry>"
        )
    return (
        b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" '
        b'xmlns:d="x" xmlns:m="y">'
        + entry("2026-11-19", "4.30", "4.80", "4.20", "4.40")  # inverted 10y-2y
        + entry("2026-11-20", "4.12", "4.75", "4.45", "4.60")  # steeper
        + b"</feed>"
    )


def _fred_payload() -> bytes:
    obs = []
    # 13 monthly CPI observations (for YoY), value rising ~0.3%/mo from 300.
    months = [
        ("2025-11-01", "2025-12-01"), ("2025-12-01", "2026-01-01"),
        ("2026-01-01", "2026-02-01"), ("2026-02-01", "2026-03-01"),
        ("2026-03-01", "2026-04-01"), ("2026-04-01", "2026-05-01"),
        ("2026-05-01", "2026-06-01"), ("2026-06-01", "2026-07-01"),
        ("2026-07-01", "2026-08-01"), ("2026-08-01", "2026-09-01"),
        ("2026-09-01", "2026-10-01"), ("2026-10-01", "2026-11-01"),
        ("2026-11-01", "2026-12-01"),
    ]
    for i, (date, rt) in enumerate(months):
        obs.append({"date": date, "value": f"{300.0 + i:.3f}",
                    "realtime_start": rt, "realtime_end": "9999-12-31"})
    # A revision of the 2026-05-01 value with a LATER vintage (should win PIT).
    obs.append({"date": "2026-05-01", "value": "305.900",
                "realtime_start": "2026-08-01", "realtime_end": "9999-12-31"})
    return json.dumps({"observations": obs}).encode()


def seed_rich_warehouse(root: Path, *, when: datetime = NOW) -> Path:
    """Ingest Bronze, publish Silver, load the warehouse; return the DuckDB path."""
    store = LocalObjectStore(root)
    bronze = BronzeIngestor(store)

    for symbol, prices in _PRICES.items():
        bronze.ingest(
            DatasetRef(source=DataSource.ALPACA, dataset="equity_bars_daily",
                       entity=symbol, partition="2026-11"),
            _alpaca_payload(prices), endpoint="https://example", retrieved_at=when, producer="t",
        )
    bronze.ingest(
        DatasetRef(source=DataSource.SEC_EDGAR, dataset="company_facts",
                   entity="CIK0000320193", partition="full"),
        _sec_payload(), endpoint="https://example", retrieved_at=when, producer="t",
    )
    bronze.ingest(
        DatasetRef(source=DataSource.US_TREASURY, dataset="daily_treasury_yield_curve",
                   entity=None, partition="2026-11"),
        _treasury_xml(), endpoint="https://example", retrieved_at=when, producer="t",
        media_type="application/xml",
    )
    bronze.ingest(
        DatasetRef(source=DataSource.FRED, dataset="series_observations",
                   entity="CPIAUCSL", partition="full"),
        _fred_payload(), endpoint="https://example", retrieved_at=when, producer="t",
        request_params={"series_id": "CPIAUCSL"},
    )

    transformer = SilverTransformer(root, clock=lambda: when)
    datasets = [
        "alpaca_equity_bars_daily", "sec_company_facts",
        "treasury_yield_curve", "fred_observations",
    ]
    for ds in datasets:
        transformer.transform(ds)

    db = root / "warehouse" / "strix.duckdb"
    wh = DuckDBWarehouse(db, root)
    for ds in datasets:
        wh.load_silver(ds, now=when)
    return db
