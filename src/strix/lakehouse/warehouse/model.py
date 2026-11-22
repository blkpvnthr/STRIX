"""Dimensional warehouse model: dimension/fact table specs + dialect DDL.

Logical column types are rendered per backend (DuckDB / Snowflake). Facts carry
the Silver ``natural_key`` as their primary key (deduplicated upstream) plus the
distinct temporal fields point-in-time research needs and the lineage columns that
resolve a row back to its Bronze artifact. Tables marked ``populated_from=None``
are schema-only placeholders for future datasets — created but never populated, and
reported as such (never falsely claimed operational).
"""

from __future__ import annotations

from dataclasses import dataclass

# Lineage + load-bookkeeping columns on every fact.
_LINEAGE_COLS = (
    ("source_code", "str", False),
    ("silver_schema_version", "str", False),
    ("bronze_artifact_id", "str", False),
    ("source_locator", "str", False),
    ("retrieved_at", "ts", False),
    ("silver_publication_id", "str", False),
    ("load_execution_id", "str", False),
    ("warehouse_loaded_at", "ts", False),
    ("row_signature", "str", False),
)


@dataclass(frozen=True)
class Column:
    name: str
    type: str  # int|bigint|date|date_key|ts|str|bool|dec:P,S
    nullable: bool = True


@dataclass(frozen=True)
class Table:
    name: str
    kind: str  # "dimension" | "fact"
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...]
    grain: str
    populated_from: tuple[str, ...] | None  # Silver dataset name(s) or None
    note: str = ""

    @property
    def schema_only(self) -> bool:
        return self.populated_from is None


def _cols(*specs: tuple[str, str, bool]) -> tuple[Column, ...]:
    return tuple(Column(n, t, nz) for n, t, nz in specs)


def _fact(core: tuple[tuple[str, str, bool], ...]) -> tuple[Column, ...]:
    return _cols(*core, *_LINEAGE_COLS)


# --------------------------------------------------------------------------
# Dimensions
# --------------------------------------------------------------------------

_DIMENSIONS = (
    Table(
        "dim_date", "dimension",
        _cols(
            ("date_key", "date_key", False), ("full_date", "date", False),
            ("year", "int", False), ("quarter", "int", False), ("month", "int", False),
            ("day", "int", False), ("day_of_week", "int", False), ("is_weekday", "bool", False),
        ),
        ("date_key",), "one row per calendar date present in any fact", ("__derived__",),
    ),
    Table(
        "dim_source", "dimension",
        _cols(
            ("source_code", "str", False), ("source_name", "str", False),
            ("category", "str", False),
        ),
        ("source_code",), "one row per data source", ("__static__",),
    ),
    Table(
        "dim_instrument", "dimension",
        _cols(
            ("symbol", "str", False), ("instrument_sk", "bigint", False),
            ("asset_class", "str", False), ("name", "str", True),
        ),
        ("symbol",), "one row per traded instrument", ("alpaca_equity_bars_daily",),
        note="asset_class='equity'; name NULL/unknown unless an authoritative source provides it",
    ),
    Table(
        "dim_company", "dimension",
        _cols(
            ("cik", "str", False), ("company_sk", "bigint", False),
            ("company_name", "str", True),
        ),
        ("cik",), "one row per SEC filer (CIK)", ("sec_company_facts",),
        note="company_name from SEC companyfacts entityName when available, else NULL",
    ),
    Table(
        "dim_economic_series", "dimension",
        _cols(
            ("series_id", "str", False), ("series_sk", "bigint", False),
            ("source_code", "str", False), ("frequency", "str", True),
        ),
        ("series_id", "source_code"), "one row per economic series",
        ("bls_observations", "fred_observations"),
    ),
    Table(
        "dim_evidence", "dimension",
        _cols(
            ("evidence_id", "str", False), ("source_code", "str", False),
            ("content_hash", "str", True), ("retrieved_at", "ts", False),
        ),
        ("evidence_id",), "one row per Bronze artifact referenced by facts",
        ("__derived__",),
    ),
    Table(
        "dim_pipeline_run", "dimension",
        _cols(
            ("run_id", "str", False), ("run_type", "str", False),
            ("dataset", "str", False), ("created_at", "ts", True),
        ),
        ("run_id",), "one row per Silver publication (load) referenced by facts",
        ("__derived__",),
    ),
    Table(
        "dim_exchange", "dimension",
        _cols(("exchange_code", "str", False), ("exchange_name", "str", False)),
        ("exchange_code",), "one row per exchange", ("__static__",),
        note="authoritative exchange metadata is not in current feeds; populated with "
        "an explicit UNKNOWN row",
    ),
    Table(
        "dim_sector", "dimension",
        _cols(("sector_code", "str", False), ("sector_name", "str", False)),
        ("sector_code",), "one row per GICS-style sector", ("__static__",),
        note="SPDR sector mapping used as authoritative for known sector ETFs",
    ),
)

# --------------------------------------------------------------------------
# Facts (populated)
# --------------------------------------------------------------------------

_FACTS = (
    Table(
        "fact_market_bars", "fact",
        _fact((
            ("silver_natural_key", "str", False), ("date_key", "date_key", False),
            ("symbol", "str", False), ("session_date", "date", False),
            ("observation_ts", "ts", False),
            ("open", "dec:18,6", False), ("high", "dec:18,6", False),
            ("low", "dec:18,6", False), ("close", "dec:18,6", False),
            ("volume", "bigint", False), ("trade_count", "bigint", True),
            ("vwap", "dec:18,6", True),
        )),
        ("silver_natural_key",), "one daily bar per (symbol, session_date)",
        ("alpaca_equity_bars_daily",),
    ),
    Table(
        "fact_company_financials", "fact",
        _fact((
            ("silver_natural_key", "str", False), ("cik", "str", False),
            ("taxonomy", "str", False), ("concept", "str", False), ("unit", "str", False),
            ("period_start", "date", True), ("period_end", "date", False),
            ("filed_date", "date", False), ("fiscal_year", "int", True),
            ("fiscal_period", "str", True), ("form", "str", True),
            ("accession", "str", True), ("frame", "str", True),
            ("value", "dec:28,4", False),
        )),
        ("silver_natural_key",), "one reported financial observation (nested, by filing)",
        ("sec_company_facts",),
    ),
    Table(
        "fact_economic_observations", "fact",
        _fact((
            ("silver_natural_key", "str", False), ("series_id", "str", False),
            ("observation_date", "date", False), ("frequency", "str", True),
            ("period", "str", True), ("value", "dec:28,10", True),
            ("realtime_start", "date", True), ("realtime_end", "date", True),
        )),
        ("silver_natural_key",), "one economic observation (BLS/FRED, with vintage where present)",
        ("bls_observations", "fred_observations"),
    ),
    Table(
        "fact_treasury_yields", "fact",
        _fact((
            ("silver_natural_key", "str", False), ("date_key", "date_key", False),
            ("observation_date", "date", False), ("tenor", "str", False),
            ("yield_pct", "dec:9,4", False),
        )),
        ("silver_natural_key",), "one par yield per (date, tenor)",
        ("treasury_yield_curve",),
    ),
    Table(
        "fact_pipeline_runs", "fact",
        _cols(
            ("silver_publication_id", "str", False), ("dataset", "str", False),
            ("source_code", "str", False), ("row_count", "int", False),
            ("published_at", "ts", False), ("load_execution_id", "str", False),
            ("warehouse_loaded_at", "ts", False),
        ),
        ("silver_publication_id",), "one row per Silver publication loaded",
        ("__derived__",),
    ),
)

# Schema-only facts for future datasets (created, never populated).
_FUTURE_FACTS = tuple(
    Table(
        name, "fact",
        _fact((("silver_natural_key", "str", False), ("placeholder", "str", True))),
        ("silver_natural_key",), note, None,
    )
    for name, note in (
        ("fact_market_quotes", "future: intraday quotes"),
        ("fact_corporate_actions", "future: splits/dividends"),
        ("fact_sector_performance", "future: sector analytics (DE-5)"),
        ("fact_financial_ratios", "future: financial ratios (DE-5)"),
        ("fact_research_claims", "future: research claims (DE-7)"),
        ("fact_verification_results", "future: verification results (DE-7)"),
    )
)

WAREHOUSE_TABLES: tuple[Table, ...] = (*_DIMENSIONS, *_FACTS, *_FUTURE_FACTS)
TABLES_BY_NAME: dict[str, Table] = {t.name: t for t in WAREHOUSE_TABLES}

#: Silver dataset -> fact table it populates.
SILVER_TO_FACT: dict[str, str] = {
    "alpaca_equity_bars_daily": "fact_market_bars",
    "sec_company_facts": "fact_company_financials",
    "bls_observations": "fact_economic_observations",
    "fred_observations": "fact_economic_observations",
    "treasury_yield_curve": "fact_treasury_yields",
}

# --------------------------------------------------------------------------
# Dialect DDL
# --------------------------------------------------------------------------

_DUCKDB_TYPES = {
    "int": "INTEGER", "bigint": "BIGINT", "date": "DATE", "date_key": "INTEGER",
    "ts": "TIMESTAMP", "str": "VARCHAR", "bool": "BOOLEAN",
}
_SNOWFLAKE_TYPES = {
    "int": "NUMBER(10,0)", "bigint": "NUMBER(19,0)", "date": "DATE", "date_key": "NUMBER(10,0)",
    "ts": "TIMESTAMP_NTZ", "str": "VARCHAR", "bool": "BOOLEAN",
}


def render_type(logical: str, dialect: str) -> str:
    if logical.startswith("dec:"):
        p, s = logical[4:].split(",")
        return f"DECIMAL({p},{s})" if dialect == "duckdb" else f"NUMBER({p},{s})"
    types = _DUCKDB_TYPES if dialect == "duckdb" else _SNOWFLAKE_TYPES
    return types[logical]


def create_table_sql(table: Table, dialect: str = "duckdb") -> str:
    lines = []
    for col in table.columns:
        null = "" if col.nullable else " NOT NULL"
        lines.append(f"  {col.name} {render_type(col.type, dialect)}{null}")
    pk = f",\n  PRIMARY KEY ({', '.join(table.primary_key)})" if table.primary_key else ""
    return f"CREATE TABLE IF NOT EXISTS {table.name} (\n" + ",\n".join(lines) + pk + "\n)"
