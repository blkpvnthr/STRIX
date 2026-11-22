"""Offline tests for the Snowflake adapter (SQL generation; no live connection)."""

from __future__ import annotations

from strix.lakehouse.warehouse.snowflake_warehouse import SnowflakeProfile, SnowflakeWarehouse


def _sf(**env: str) -> SnowflakeWarehouse:
    return SnowflakeWarehouse(SnowflakeProfile.from_env(env))


def test_unavailable_without_credentials() -> None:
    sf = _sf()
    assert sf.available() is False
    assert "missing credentials" in sf.unavailable_reason()


def test_ddl_uses_snowflake_types() -> None:
    sql = "\n".join(_sf().ddl_statements())
    assert "CREATE DATABASE IF NOT EXISTS STRIX" in sql
    assert "NUMBER(18,6)" in sql  # decimal rendered as NUMBER
    assert "TIMESTAMP_NTZ" in sql
    assert "fact_market_bars" in sql


def test_warehouse_setup_has_autosuspend_and_least_privilege() -> None:
    setup = "\n".join(_sf().warehouse_setup_sql())
    assert "AUTO_SUSPEND = 60" in setup and "AUTO_RESUME = TRUE" in setup
    assert "CREATE ROLE IF NOT EXISTS STRIX_RESEARCH" in setup
    assert "GRANT SELECT ON ALL TABLES" in setup  # research role is read-only


def test_merge_sql_is_upsert_keyed_on_pk() -> None:
    merge = _sf().merge_sql("alpaca_equity_bars_daily")
    assert merge.startswith("MERGE INTO fact_market_bars")
    assert "ON t.silver_natural_key = s.silver_natural_key" in merge
    assert "WHEN MATCHED AND t.row_signature <> s.row_signature THEN UPDATE" in merge
    assert "WHEN NOT MATCHED THEN INSERT" in merge


def test_copy_into_sql_parquet() -> None:
    copy = _sf().copy_into_sql("fact_market_bars", "@my_stage/path")
    assert "COPY INTO fact_market_bars_stage" in copy
    assert "TYPE = PARQUET" in copy


def test_available_with_creds_but_no_connector_reports_reason() -> None:
    sf = _sf(SNOWFLAKE_ACCOUNT="a", SNOWFLAKE_USER="u", SNOWFLAKE_PASSWORD="p")
    # snowflake-connector-python is not installed in the test env.
    if not sf.available():
        assert "not installed" in sf.unavailable_reason()
