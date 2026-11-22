"""Tests for the `strix warehouse` CLI."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

from tests.lakehouse.warehouse_fixtures import seed_lakehouse

from strix.lakehouse.warehouse.cli import run_warehouse


def _ns(command: str, tmp_path: Path, **kw: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "warehouse_command": command, "lakehouse_dir": str(tmp_path), "db_path": None,
        "backend": "duckdb", "json": False, "dataset": "all", "dry_run": False,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def _run(command: str, tmp_path: Path, **kw: object) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run_warehouse(_ns(command, tmp_path, **kw), out=out, err=err)
    return code, out.getvalue() + err.getvalue()


def test_init_load_reconcile_status(tmp_path: Path) -> None:
    seed_lakehouse(tmp_path)
    assert _run("init", tmp_path)[0] == 0

    code, text = _run("load", tmp_path)
    assert code == 0 and "fact_market_bars" in text

    code, text = _run("reconcile", tmp_path)
    assert code == 0 and "balanced=True" in text

    code, text = _run("status", tmp_path)
    assert code == 0 and "fact_market_bars" in text

    code, text = _run("profile", tmp_path)
    assert code == 0 and "schema-only" in text  # placeholders flagged


def test_load_json_output(tmp_path: Path) -> None:
    seed_lakehouse(tmp_path)
    out, err = io.StringIO(), io.StringIO()
    run_warehouse(
        _ns("load", tmp_path, dataset="alpaca_equity_bars_daily", json=True), out=out, err=err
    )
    payload = json.loads(out.getvalue())
    assert payload[0]["fact_table"] == "fact_market_bars"
    assert payload[0]["inserted"] == 2


def test_lineage_cli(tmp_path: Path) -> None:
    seed_lakehouse(tmp_path)
    _run("load", tmp_path)
    # Grab a natural key from the warehouse.
    from strix.lakehouse.warehouse.duckdb_warehouse import DuckDBWarehouse

    wh = DuckDBWarehouse(tmp_path / "warehouse" / "strix.duckdb", tmp_path)
    nk = wh.query("SELECT silver_natural_key FROM fact_market_bars LIMIT 1")[1][0][0]
    code, text = _run("lineage", tmp_path, dataset="alpaca_equity_bars_daily", key=nk)
    assert code == 0 and "complete=True" in text


def test_snowflake_init_prints_ddl_offline(tmp_path: Path) -> None:
    code, text = _run("init", tmp_path, backend="snowflake")
    assert code == 0
    assert "CREATE DATABASE IF NOT EXISTS STRIX" in text
    assert "NUMBER(" in text


def test_dry_run_rolls_back(tmp_path: Path) -> None:
    seed_lakehouse(tmp_path)
    _run("load", tmp_path, dataset="alpaca_equity_bars_daily", dry_run=True)
    from strix.lakehouse.warehouse.duckdb_warehouse import DuckDBWarehouse

    wh = DuckDBWarehouse(tmp_path / "warehouse" / "strix.duckdb", tmp_path)
    assert wh.query("SELECT count(*) FROM fact_market_bars")[1][0][0] == 0
