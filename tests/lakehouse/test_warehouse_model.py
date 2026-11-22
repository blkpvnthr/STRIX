"""Tests for the warehouse dimensional model + dialect DDL."""

from __future__ import annotations

from strix.lakehouse.warehouse.model import (
    SILVER_TO_FACT,
    TABLES_BY_NAME,
    WAREHOUSE_TABLES,
    create_table_sql,
    render_type,
)


def test_duckdb_and_snowflake_decimal_types() -> None:
    assert render_type("dec:18,6", "duckdb") == "DECIMAL(18,6)"
    assert render_type("dec:18,6", "snowflake") == "NUMBER(18,6)"
    assert render_type("ts", "snowflake") == "TIMESTAMP_NTZ"


def test_fact_market_bars_ddl_has_decimal_and_pk() -> None:
    sql = create_table_sql(TABLES_BY_NAME["fact_market_bars"], "duckdb")
    assert "close DECIMAL(18,6) NOT NULL" in sql
    assert "PRIMARY KEY (silver_natural_key)" in sql


def test_schema_only_facts_marked() -> None:
    future = [t for t in WAREHOUSE_TABLES if t.schema_only]
    names = {t.name for t in future}
    assert "fact_financial_ratios" in names
    assert "fact_research_claims" in names
    # Populated facts are not schema-only.
    assert not TABLES_BY_NAME["fact_market_bars"].schema_only


def test_every_silver_dataset_maps_to_a_fact() -> None:
    for fact in SILVER_TO_FACT.values():
        assert fact in TABLES_BY_NAME
