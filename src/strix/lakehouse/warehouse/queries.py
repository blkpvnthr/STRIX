"""Parameterized, read-only analytical queries returning typed results.

No raw SQL is accepted from callers (and none is ever exposed to the language
model) — only these fixed, parameterized templates. Each result carries units,
source references, observation dates, dataset versions, and explicit limitations,
so a consumer always knows the provenance and point-in-time caveats of a number.
"""

from __future__ import annotations

from typing import Any

from strix.lakehouse.warehouse.contracts import QueryResult
from strix.lakehouse.warehouse.duckdb_warehouse import DuckDBWarehouse

_PIT_CAVEAT = (
    "Point-in-time uses only vintage-aware fields where available (SEC filed_date, "
    "FRED realtime_start); sources without vintage metadata (Alpaca/Treasury/BLS) "
    "fall back to observation date and may reflect later corrections."
)


class WarehouseQueries:
    def __init__(self, warehouse: DuckDBWarehouse) -> None:
        self._wh = warehouse

    def _result(
        self, name: str, sql: str, params: list[Any], **meta: Any
    ) -> QueryResult:
        columns, raw = self._wh.query(sql, params)
        rows = tuple(
            {col: (None if v is None else str(v)) for col, v in zip(columns, r, strict=True)}
            for r in raw
        )
        return QueryResult(
            name=name, columns=tuple(columns), rows=rows, row_count=len(rows), **meta
        )

    def ohlcv(self, symbol: str, start: str, end: str) -> QueryResult:
        sql = (
            "SELECT session_date, open, high, low, close, volume FROM fact_market_bars "
            "WHERE symbol = ?::VARCHAR AND session_date BETWEEN ?::DATE AND ?::DATE "
            "ORDER BY session_date"
        )
        return self._result(
            "ohlcv", sql, [symbol.upper(), start, end],
            units={"open": "USD", "high": "USD", "low": "USD", "close": "USD",
                   "volume": "shares"},
            source_refs=("alpaca",), dataset_versions={"alpaca_equity_bars_daily": "0.1.0"},
        )

    def company_financials(self, cik: str, concept: str, limit: int = 50) -> QueryResult:
        sql = (
            "SELECT period_end, fiscal_period, value, unit, filed_date, accession "
            "FROM fact_company_financials WHERE cik = ?::VARCHAR AND concept = ?::VARCHAR "
            "ORDER BY period_end DESC, filed_date DESC LIMIT ?"
        )
        return self._result(
            "company_financials", sql, [cik, concept, limit],
            units={"value": "per-unit column"}, source_refs=("sec_edgar",),
            dataset_versions={"sec_company_facts": "0.1.0"},
            limitations=("restatements appear as multiple rows (distinct accession)",),
        )

    def economic_history(self, series_id: str, limit: int = 120) -> QueryResult:
        sql = (
            "SELECT observation_date, value, frequency, realtime_start FROM "
            "fact_economic_observations WHERE series_id = ?::VARCHAR "
            "ORDER BY observation_date DESC LIMIT ?"
        )
        return self._result(
            "economic_history", sql, [series_id, limit],
            units={"value": "series native unit"}, source_refs=("bls", "fred"),
            limitations=("FRED vintages distinguished by realtime_start; BLS has no vintage",),
        )

    def treasury_yields(self, tenors: list[str], start: str, end: str) -> QueryResult:
        placeholders = ",".join("?::VARCHAR" for _ in tenors)
        sql = (
            "SELECT observation_date, tenor, yield_pct FROM fact_treasury_yields "
            f"WHERE tenor IN ({placeholders}) AND observation_date BETWEEN ?::DATE AND ?::DATE "
            "ORDER BY observation_date, tenor"
        )
        return self._result(
            "treasury_yields", sql, [*tenors, start, end],
            units={"yield_pct": "percent"}, source_refs=("us_treasury",),
        )

    def point_in_time_financials(self, cik: str, concept: str, as_of: str) -> QueryResult:
        # Only observations filed on or before the cutoff (true vintage filter).
        sql = (
            "SELECT period_end, value, filed_date, accession FROM ("
            "  SELECT period_end, value, filed_date, accession, "
            "    row_number() OVER (PARTITION BY period_end ORDER BY filed_date DESC) AS rn "
            "  FROM fact_company_financials "
            "  WHERE cik = ?::VARCHAR AND concept = ?::VARCHAR AND filed_date <= ?::DATE"
            ") WHERE rn = 1 ORDER BY period_end DESC"
        )
        return self._result(
            "point_in_time_financials", sql, [cik, concept, as_of],
            as_of=as_of, source_refs=("sec_edgar",),
            limitations=("as-of uses SEC filed_date (true vintage)",),
        )

    def dataset_freshness(self) -> QueryResult:
        sql = (
            "SELECT 'fact_market_bars' AS fact, max(session_date)::VARCHAR AS latest, "
            "count(*) AS rows FROM fact_market_bars "
            "UNION ALL SELECT 'fact_company_financials', max(period_end)::VARCHAR, count(*) "
            "FROM fact_company_financials "
            "UNION ALL SELECT 'fact_economic_observations', max(observation_date)::VARCHAR, "
            "count(*) FROM fact_economic_observations "
            "UNION ALL SELECT 'fact_treasury_yields', max(observation_date)::VARCHAR, count(*) "
            "FROM fact_treasury_yields"
        )
        return self._result("dataset_freshness", sql, [])
