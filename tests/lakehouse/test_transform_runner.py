"""Unit tests for the dbt runner: argument validation, profile generation,
manifest parsing, and warehouse publication lookup (no dbt execution)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strix.lakehouse.transform.runner import DbtError, DbtRunner, find_dbt_command


def _runner(tmp_path: Path) -> DbtRunner:
    return DbtRunner(tmp_path / "proj", tmp_path / "wh.duckdb", dbt_command=["dbt"])


def test_find_dbt_command_returns_list() -> None:
    cmd = find_dbt_command()
    assert isinstance(cmd, list) and cmd


def test_rejects_unknown_subcommand(tmp_path: Path) -> None:
    with pytest.raises(DbtError, match="unsupported"):
        _runner(tmp_path).invoke("rm -rf /")


def test_rejects_unknown_backend(tmp_path: Path) -> None:
    with pytest.raises(DbtError, match="backend"):
        DbtRunner(tmp_path, tmp_path / "x.duckdb", backend="postgres")


@pytest.mark.parametrize("bad", ["foo; rm -rf /", "a && b", "x`y`", "$(whoami)", "a|b"])
def test_rejects_shell_metacharacters_in_select(tmp_path: Path, bad: str) -> None:
    with pytest.raises(DbtError, match="selection"):
        _runner(tmp_path).invoke("run", select=bad)


def test_rejects_bad_var_name(tmp_path: Path) -> None:
    with pytest.raises(DbtError, match="var name"):
        _runner(tmp_path).invoke("run", variables={"bad name": 1})


def test_accepts_valid_selection_syntax(tmp_path: Path) -> None:
    # Validation only — no execution (dbt_command points at a missing binary path).
    r = DbtRunner(tmp_path / "proj", tmp_path / "wh.duckdb",
                  dbt_command=[str(tmp_path / "no_such_dbt")])
    with pytest.raises(DbtError, match="not installed"):
        r.invoke("build", select="staging.int_market_daily+ tag:marts")


def test_write_profile_uses_env_var_only(tmp_path: Path) -> None:
    path = _runner(tmp_path).write_profile()
    text = path.read_text()
    assert "env_var('STRIX_WAREHOUSE_DB')" in text
    # No literal secrets committed to the generated profile.
    assert "password" in text and "env_var('SNOWFLAKE_PASSWORD'" in text


def test_model_inventory_parses_manifest(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    (proj / "target").mkdir(parents=True)
    manifest = {
        "nodes": {
            "model.strix_transform.stg_market_bars": {
                "resource_type": "model", "name": "stg_market_bars",
                "fqn": ["strix_transform", "staging", "stg_market_bars"],
                "schema": "staging", "config": {"materialized": "view"},
                "depends_on": {"nodes": ["source.strix_transform.warehouse.fact_market_bars"]},
            },
            "model.strix_transform.mart_yield_curve": {
                "resource_type": "model", "name": "mart_yield_curve",
                "fqn": ["strix_transform", "marts", "macroeconomics", "mart_yield_curve"],
                "schema": "marts", "config": {"materialized": "table"},
                "depends_on": {"nodes": ["model.strix_transform.int_treasury_maturity_alignment"]},
            },
        }
    }
    (proj / "target" / "manifest.json").write_text(json.dumps(manifest))
    inv = {m.name: m for m in DbtRunner(proj, tmp_path / "wh.duckdb").model_inventory()}
    assert inv["stg_market_bars"].layer == "staging"
    assert inv["stg_market_bars"].materialization == "view"
    assert inv["mart_yield_curve"].layer == "marts"
    assert inv["mart_yield_curve"].materialization == "table"


def test_source_publications_reads_load_state(tmp_path: Path) -> None:
    import duckdb

    db = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE _load_state (dataset VARCHAR, silver_publication_id VARCHAR)"
    )
    con.execute("INSERT INTO _load_state VALUES ('alpaca_equity_bars_daily', 'PUB123')")
    con.close()
    pubs = DbtRunner(tmp_path / "proj", db).source_publications()
    assert pubs == {"alpaca_equity_bars_daily": "PUB123"}


def test_source_publications_missing_db_is_empty(tmp_path: Path) -> None:
    assert DbtRunner(tmp_path / "proj", tmp_path / "absent.duckdb").source_publications() == {}
