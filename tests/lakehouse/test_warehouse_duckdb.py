"""End-to-end DuckDB warehouse tests (seeded Bronze -> Silver -> warehouse)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from tests.lakehouse.warehouse_fixtures import ingest_alpaca_revision, seed_lakehouse

from strix.lakehouse.warehouse.duckdb_warehouse import DuckDBWarehouse, WarehouseError

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _wh(root: Path) -> DuckDBWarehouse:
    return DuckDBWarehouse(root / "warehouse" / "wh.duckdb", root)


def test_init_creates_all_tables(tmp_path: Path) -> None:
    created = _wh(tmp_path).init_schema()
    assert "fact_market_bars" in created
    assert "dim_date" in created
    assert "fact_financial_ratios" in created  # schema-only placeholder still created


def test_load_and_reconcile(tmp_path: Path) -> None:
    seed_lakehouse(tmp_path)
    wh = _wh(tmp_path)
    result = wh.load_silver("alpaca_equity_bars_daily", now=_NOW)
    assert result.inserted == 2 and result.updated == 0 and not result.skipped
    rec = wh.reconcile("alpaca_equity_bars_daily")
    assert rec.balanced
    assert rec.silver_rows == rec.warehouse_rows == 2
    assert rec.duplicate_keys == 0
    assert rec.lineage_complete


def test_decimal_precision_preserved(tmp_path: Path) -> None:
    seed_lakehouse(tmp_path)
    wh = _wh(tmp_path)
    wh.load_silver("alpaca_equity_bars_daily", now=_NOW)
    _, rows = wh.query("SELECT close FROM fact_market_bars ORDER BY close")
    closes = {r[0] for r in rows}
    assert Decimal("102.25") in closes  # exact, from decimal128(18,6)


def test_idempotent_rerun_skips(tmp_path: Path) -> None:
    seed_lakehouse(tmp_path)
    wh = _wh(tmp_path)
    wh.load_silver("alpaca_equity_bars_daily", now=_NOW)
    again = wh.load_silver("alpaca_equity_bars_daily", now=_NOW)
    assert again.skipped
    # No duplicate rows from the rerun.
    assert wh.query("SELECT count(*) FROM fact_market_bars")[1][0][0] == 2


def test_incremental_revision_updates_not_duplicates(tmp_path: Path) -> None:
    seed_lakehouse(tmp_path)
    wh = _wh(tmp_path)
    wh.load_silver("alpaca_equity_bars_daily", now=_NOW)
    # A corrected bar (same natural key, different but valid close, later retrieval).
    ingest_alpaca_revision(tmp_path, close="102.90", when=datetime(2026, 11, 23, tzinfo=UTC))
    result = wh.load_silver("alpaca_equity_bars_daily", now=datetime(2026, 11, 23, 12, tzinfo=UTC))
    assert not result.skipped
    assert result.updated == 1  # revision updated, not inserted
    assert result.inserted == 0
    # Still 2 rows total — natural key uniqueness preserved.
    assert wh.query("SELECT count(*) FROM fact_market_bars")[1][0][0] == 2
    assert Decimal("102.90") in {r[0] for r in wh.query("SELECT close FROM fact_market_bars")[1]}


def test_rollback_on_failure_leaves_no_partial_data(tmp_path: Path) -> None:
    seed_lakehouse(tmp_path)
    wh = _wh(tmp_path)
    wh.init_schema()

    def boom() -> None:
        raise RuntimeError("interrupted mid-load")

    with pytest.raises(WarehouseError, match="rolled back"):
        wh.load_silver("alpaca_equity_bars_daily", now=_NOW, fail_hook=boom)
    # The fact table remains empty — no partial publication exposed.
    assert wh.query("SELECT count(*) FROM fact_market_bars")[1][0][0] == 0


def test_rejects_unbalanced_silver_publication(tmp_path: Path) -> None:
    seed_lakehouse(tmp_path)
    # Corrupt the Silver publication manifest to report an unbalanced reconciliation.
    pub = tmp_path / "silver" / "alpaca_equity_bars_daily" / "_publication.json"
    doc = json.loads(pub.read_text())
    doc["reconciliation"]["discrepancies"] = ["injected imbalance"]
    pub.write_text(json.dumps(doc))
    with pytest.raises(WarehouseError, match="did not balance"):
        _wh(tmp_path).load_silver("alpaca_equity_bars_daily", now=_NOW)


def test_lineage_resolves_to_bronze(tmp_path: Path) -> None:
    seed_lakehouse(tmp_path)
    wh = _wh(tmp_path)
    wh.load_silver("alpaca_equity_bars_daily", now=_NOW)
    nk = wh.query("SELECT silver_natural_key FROM fact_market_bars LIMIT 1")[1][0][0]
    record = wh.lineage("fact_market_bars", nk)
    assert record is not None
    assert record.bronze_artifact_present and record.bronze_hash_ok
    assert record.complete
    assert record.bronze_artifact_id.startswith("RAW-")


def test_point_in_time_uses_filed_date(tmp_path: Path) -> None:
    from strix.lakehouse.warehouse.queries import WarehouseQueries

    seed_lakehouse(tmp_path)
    wh = _wh(tmp_path)
    wh.load_silver("sec_company_facts", now=_NOW)
    q = WarehouseQueries(wh)
    # The fixture filing is filed 2025-10-31; a cutoff before it sees nothing.
    before = q.point_in_time_financials("CIK0000320193", "Revenues", "2025-01-01")
    after = q.point_in_time_financials("CIK0000320193", "Revenues", "2026-01-01")
    assert before.row_count == 0
    assert after.row_count == 1
    assert after.as_of == "2026-01-01"


def test_read_only_connection_blocks_writes(tmp_path: Path) -> None:
    seed_lakehouse(tmp_path)
    wh = _wh(tmp_path)
    wh.init_schema()
    con = wh.connect(read_only=True)
    try:
        with pytest.raises(Exception):  # noqa: B017 - duckdb raises on write in RO mode
            con.execute("INSERT INTO fact_market_bars (silver_natural_key) VALUES ('x')")
    finally:
        con.close()
