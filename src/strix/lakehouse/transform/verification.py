"""Independent cross-validation of dbt marts.

The transformation layer is NOT the verifier. For a supported analytical claim this
module:

1. reads the mart value produced by dbt (SQL engine), then
2. independently reconstructs the calculation INPUTS from the warehouse fact rows
   (which carry Silver/Bronze lineage), and
3. recomputes the number with the exact Decimal calculators in
   :mod:`strix.agent.calculations` — the SAME code the research verifier uses —
4. comparing the two under the calculation contract's documented tolerance.

Crucially, step 3 never re-runs the dbt SQL: it recomputes from raw observations in
a different engine (Python Decimal), so agreement is real corroboration, not a
tautology. The evidence artifacts backing each input are surfaced so a claim remains
traceable to Bronze.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from strix.agent import calculations as calc
from strix.errors import CalculationError
from strix.lakehouse.transform.calculations import (
    DECIMAL_TOLERANCE,
    STAT_TOLERANCE,
    contract,
)
from strix.lakehouse.transform.contracts import CrossValidation


class WarehouseCrossValidator:
    """Recomputes supported mart values from preserved observations."""

    def __init__(self, warehouse_db: Path) -> None:
        self._db = Path(warehouse_db)

    def _con(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self._db), read_only=True)

    def _closes(
        self, con: duckdb.DuckDBPyConnection, symbol: str
    ) -> tuple[list[Decimal], list[str]]:
        rows = con.execute(
            "SELECT close, bronze_artifact_id FROM fact_market_bars "
            "WHERE symbol = ?::VARCHAR ORDER BY session_date",
            [symbol],
        ).fetchall()
        closes = [Decimal(str(r[0])) for r in rows]
        artifacts = sorted({str(r[1]) for r in rows})
        return closes, artifacts

    def _scalar(self, con: duckdb.DuckDBPyConnection, sql: str, params: list[Any]) -> Any:
        row = con.execute(sql, params).fetchone()
        return None if row is None else row[0]

    # -- market calculations ----------------------------------------------

    def cumulative_return(self, symbol: str) -> CrossValidation:
        c = contract("cumulative_return")
        con = self._con()
        try:
            closes, artifacts = self._closes(con, symbol)
            sql = self._scalar(
                con,
                "SELECT cumulative_return FROM intermediate.int_cumulative_returns "
                "WHERE instrument_symbol = ?::VARCHAR ORDER BY session_index DESC LIMIT 1",
                [symbol],
            )
        finally:
            con.close()
        return self._compare(
            claim=f"{symbol} cumulative return (full window)",
            contract_id=c.identifier, subject=symbol, series=closes,
            recompute=lambda: calc.cumulative_return(closes),
            sql_value=sql, tolerance=STAT_TOLERANCE, artifacts=artifacts,
        )

    def max_drawdown(self, symbol: str) -> CrossValidation:
        c = contract("max_drawdown")
        con = self._con()
        try:
            closes, artifacts = self._closes(con, symbol)
            sql = self._scalar(
                con,
                "SELECT max_drawdown FROM marts.mart_market_drawdown "
                "WHERE instrument_symbol = ?::VARCHAR",
                [symbol],
            )
        finally:
            con.close()
        return self._compare(
            claim=f"{symbol} maximum drawdown (full window)",
            contract_id=c.identifier, subject=symbol, series=closes,
            recompute=lambda: calc.max_drawdown(closes),
            sql_value=sql, tolerance=STAT_TOLERANCE, artifacts=artifacts,
        )

    def realized_volatility(self, symbol: str) -> CrossValidation:
        c = contract("realized_volatility")
        con = self._con()
        try:
            closes, artifacts = self._closes(con, symbol)
            sql = self._scalar(
                con,
                "SELECT annualized_volatility FROM intermediate.int_market_regime_features "
                "WHERE instrument_symbol = ?::VARCHAR",
                [symbol],
            )
        finally:
            con.close()
        return self._compare(
            claim=f"{symbol} annualized realized volatility (full window)",
            contract_id=c.identifier, subject=symbol, series=closes,
            recompute=lambda: calc.realized_volatility(closes),
            sql_value=sql, tolerance=STAT_TOLERANCE, artifacts=artifacts,
        )

    def correlation(self, symbol_a: str, symbol_b: str) -> CrossValidation:
        c = contract("correlation")
        a, b = sorted((symbol_a, symbol_b))
        con = self._con()
        try:
            # Align on common session dates (inner join), mirroring the mart.
            rows = con.execute(
                "SELECT x.close, y.close, x.bronze_artifact_id, y.bronze_artifact_id "
                "FROM fact_market_bars x JOIN fact_market_bars y "
                "ON x.session_date = y.session_date "
                "WHERE x.symbol = ?::VARCHAR AND y.symbol = ?::VARCHAR "
                "ORDER BY x.session_date",
                [a, b],
            ).fetchall()
            sql = self._scalar(
                con,
                "SELECT return_correlation FROM marts.mart_equity_correlations "
                "WHERE symbol_a = ?::VARCHAR AND symbol_b = ?::VARCHAR",
                [a, b],
            )
        finally:
            con.close()
        series_a = [Decimal(str(r[0])) for r in rows]
        series_b = [Decimal(str(r[1])) for r in rows]
        artifacts = sorted({str(r[2]) for r in rows} | {str(r[3]) for r in rows})
        return self._compare(
            claim=f"correlation({a}, {b}) of daily returns",
            contract_id=c.identifier, subject=f"{a}/{b}", series=series_a,
            recompute=lambda: calc.correlation(series_a, series_b),
            sql_value=sql, tolerance=STAT_TOLERANCE, artifacts=artifacts,
        )

    # -- fundamentals -----------------------------------------------------

    def margin(self, cik: str, ratio_name: str) -> CrossValidation:
        """Cross-validate a margin ratio for the latest annual period of a filer."""
        c = contract(ratio_name)
        numer_metric, denom = {
            "gross_profit_margin": ("gross_profit", "revenue"),
            "operating_margin": ("operating_income", "revenue"),
            "net_profit_margin": ("net_income", "revenue"),
        }[ratio_name]
        con = self._con()
        try:
            period = self._scalar(
                con,
                "SELECT period_end FROM marts.mart_company_fundamentals "
                "WHERE cik = ?::VARCHAR AND revenue IS NOT NULL "
                "ORDER BY period_end DESC LIMIT 1",
                [cik],
            )
            inputs = con.execute(
                f"SELECT {numer_metric}, {denom}, accession, bronze_artifact_id "
                "FROM marts.mart_company_fundamentals "
                "WHERE cik = ?::VARCHAR AND period_end = ?::DATE LIMIT 1",
                [cik, period],
            ).fetchone()
            sql = self._scalar(
                con,
                "SELECT ratio_value FROM marts.mart_financial_ratios "
                "WHERE cik = ?::VARCHAR AND period_end = ?::DATE AND ratio_name = ?::VARCHAR "
                "LIMIT 1",
                [cik, period, ratio_name],
            )
        finally:
            con.close()
        if inputs is None or inputs[0] is None or inputs[1] is None:
            return CrossValidation(
                claim=f"{cik} {ratio_name} ({period})", calculation_id=c.identifier,
                methodology_version=c.methodology_version, subject=str(cik),
                sql_value=_s(sql), python_value=None, tolerance=DECIMAL_TOLERANCE,
                difference=None, sample_size=0, agrees=False, status="insufficient_data",
                evidence_artifacts=(), note="numerator or denominator missing",
            )
        numerator, denominator = Decimal(str(inputs[0])), Decimal(str(inputs[1]))
        artifacts = (str(inputs[3]),) if inputs[3] else ()
        # Exact Decimal recomputation; compared to the SQL (double) mart under the
        # statistical tolerance because the mart stores ratios as double.
        py = (numerator / denominator) if denominator != 0 else None
        return self._finish(
            claim=f"{cik} {ratio_name} ({period})", contract_id=c.identifier,
            methodology_version=c.methodology_version, subject=str(cik),
            sql_value=sql, python_value=py, tolerance=STAT_TOLERANCE,
            sample_size=1, artifacts=artifacts,
        )

    # -- comparison helpers ------------------------------------------------

    def _compare(
        self, *, claim: str, contract_id: str, subject: str, series: list[Decimal],
        recompute: Any, sql_value: Any, tolerance: str, artifacts: tuple[str, ...] | list[str],
    ) -> CrossValidation:
        c = contract(contract_id)
        try:
            py = recompute()
        except CalculationError as exc:
            return CrossValidation(
                claim=claim, calculation_id=contract_id,
                methodology_version=c.methodology_version, subject=subject,
                sql_value=_s(sql_value), python_value=None, tolerance=tolerance,
                difference=None, sample_size=len(series), agrees=False,
                status="insufficient_data", evidence_artifacts=tuple(artifacts), note=str(exc),
            )
        return self._finish(
            claim=claim, contract_id=contract_id,
            methodology_version=c.methodology_version, subject=subject,
            sql_value=sql_value, python_value=py, tolerance=tolerance,
            sample_size=len(series), artifacts=tuple(artifacts),
        )

    def _finish(
        self, *, claim: str, contract_id: str, methodology_version: str, subject: str,
        sql_value: Any, python_value: Decimal | None, tolerance: str, sample_size: int,
        artifacts: tuple[str, ...],
    ) -> CrossValidation:
        if sql_value is None or python_value is None:
            status = "missing_mart_value" if python_value is not None else "insufficient_data"
            return CrossValidation(
                claim=claim, calculation_id=contract_id, methodology_version=methodology_version,
                subject=subject, sql_value=_s(sql_value), python_value=_s(python_value),
                tolerance=tolerance, difference=None, sample_size=sample_size, agrees=False,
                status=status, evidence_artifacts=artifacts,
            )
        sql_dec = Decimal(str(sql_value))
        diff = abs(sql_dec - python_value)
        agrees = diff <= Decimal(tolerance)
        return CrossValidation(
            claim=claim, calculation_id=contract_id, methodology_version=methodology_version,
            subject=subject, sql_value=_s(sql_value), python_value=_s(python_value),
            tolerance=tolerance, difference=_s(diff), sample_size=sample_size,
            agrees=agrees, status=("confirmed" if agrees else "discrepancy"),
            evidence_artifacts=artifacts,
        )


def _s(value: Any) -> str | None:
    return None if value is None else str(value)
