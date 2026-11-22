"""End-to-end dbt transformation tests against a seeded DuckDB warehouse.

Builds the full DAG once (module scope) and asserts mart correctness across every
analytical area, then independently cross-validates SQL marts against the Decimal
calculators. A separate test exercises incremental correction propagation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pytest
from tests.lakehouse.transform_fixtures import seed_rich_warehouse

from strix.lakehouse.transform.contracts import DbtRunResult
from strix.lakehouse.transform.runner import DbtRunner, resolve_project_dir
from strix.lakehouse.transform.verification import WarehouseCrossValidator


def _scalar(db: Path, sql: str, params: list[Any] | None = None) -> Any:
    con = duckdb.connect(str(db), read_only=True)
    try:
        row = con.execute(sql, params or []).fetchone()
        return None if row is None else row[0]
    finally:
        con.close()


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, DbtRunResult]:
    root = tmp_path_factory.mktemp("rich_lh")
    db = seed_rich_warehouse(root)
    runner = DbtRunner(resolve_project_dir(None), db)
    runner.write_profile()
    assert runner.invoke("seed").success
    result = runner.invoke("build")
    assert result.success, result.stderr_tail or result.stdout_tail
    return db, result


# -- build health ---------------------------------------------------------

def test_build_succeeds_with_no_failures(built: tuple[Path, DbtRunResult]) -> None:
    _, result = built
    assert result.error_count == 0
    assert result.fail_count == 0
    assert result.pass_count > 50  # models + tests + seeds
    assert result.source_publications  # ran against known warehouse publications


# -- market return / volatility / drawdown --------------------------------

def test_weekly_return_matches_manual(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    # SPY closes end 515; 5 sessions back = 500 -> 0.03.
    val = _scalar(db, "SELECT weekly_return FROM marts.mart_instrument_performance "
                      "WHERE instrument_symbol = 'SPY'")
    assert abs(Decimal(str(val)) - Decimal("0.03")) < Decimal("0.000001")


def test_return_basis_is_labeled_adjusted(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    basis = _scalar(db, "SELECT DISTINCT return_basis FROM marts.mart_instrument_performance")
    assert "adjust" in basis.lower()  # never silently 'total return' without basis


def test_max_drawdown_spy(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    dd = _scalar(db, "SELECT max_drawdown FROM marts.mart_market_drawdown "
                     "WHERE instrument_symbol = 'SPY'")
    # peak 505 then 498 -> 498/505 - 1 = -0.013861...
    assert abs(Decimal(str(dd)) - Decimal("-0.013861")) < Decimal("0.00001")


def test_volatility_has_sample_sizes(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    row = _scalar(db, "SELECT vol_5_samples FROM marts.mart_market_volatility "
                      "WHERE instrument_symbol = 'SPY'")
    assert row >= 2  # 6 sessions -> 5 log returns available


# -- sector-relative performance ------------------------------------------

def test_sector_relative_and_partial_coverage(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    xlk_rel = _scalar(db, "SELECT relative_return FROM marts.mart_sector_rotation "
                          "WHERE sector_code = 'XLK'")
    assert abs(Decimal(str(xlk_rel)) - Decimal("0.02")) < Decimal("0.000001")
    complete = _scalar(db, "SELECT DISTINCT is_complete_ranking FROM marts.mart_sector_rotation")
    assert complete is False  # only 2 of 11 sectors present — not a complete ranking


# -- fundamentals: ratios, alignment, growth, zero/insufficient -----------

def test_operating_margin_fy2025(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    val = _scalar(db, "SELECT ratio_value FROM marts.mart_financial_ratios "
                      "WHERE ratio_name = 'operating_margin' AND fiscal_year = 2025")
    assert abs(Decimal(str(val)) - Decimal("0.3125")) < Decimal("0.000001")


def test_revenue_growth_first_year_is_insufficient(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    status = _scalar(db, "SELECT calculation_status FROM marts.mart_financial_ratios "
                         "WHERE ratio_name = 'revenue_growth' AND fiscal_year = 2024")
    val = _scalar(db, "SELECT ratio_value FROM marts.mart_financial_ratios "
                      "WHERE ratio_name = 'revenue_growth' AND fiscal_year = 2024")
    assert status == "insufficient_data"
    assert val is None  # no prior year -> never a fabricated number


def test_revenue_growth_fy2025(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    val = _scalar(db, "SELECT ratio_value FROM marts.mart_financial_ratios "
                      "WHERE ratio_name = 'revenue_growth' AND fiscal_year = 2025")
    assert abs(Decimal(str(val)) - Decimal("0.063843")) < Decimal("0.00001")


def test_fiscal_period_alignment_is_annual_and_unique(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    rows = _scalar(db, "SELECT count(*) FROM marts.mart_company_fundamentals "
                       "WHERE period_type = 'annual'")
    assert rows == 2  # FY2024 + FY2025, no double counting
    dup = _scalar(db, "SELECT count(*) FROM (SELECT cik, fiscal_year, fiscal_period, "
                      "period_end, period_type, count(*) n FROM marts.mart_company_fundamentals "
                      "GROUP BY 1,2,3,4,5 HAVING count(*) > 1)")
    assert dup == 0


# -- macro: inflation + yield spreads + vintage ---------------------------

def test_cpi_yoy_inflation(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    yoy = _scalar(db, "SELECT yoy_pct FROM marts.mart_macro_conditions "
                      "WHERE concept = 'cpi_index' AND observation_date = '2026-11-01'")
    assert abs(Decimal(str(yoy)) - Decimal("0.04")) < Decimal("0.000001")


def test_cpi_series_is_seasonally_adjusted(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    sa = _scalar(db, "SELECT DISTINCT seasonal_adjustment FROM marts.mart_macro_conditions "
                     "WHERE series_id = 'CPIAUCSL'")
    assert sa == "SA"


def test_yield_spreads_and_units(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    row = duckdb.connect(str(db), read_only=True).execute(
        "SELECT spread_10y_2y_pp, spread_10y_2y_bps, is_inverted_10y_2y "
        "FROM marts.mart_yield_curve WHERE observation_date = '2026-11-20'"
    ).fetchone()
    assert abs(Decimal(str(row[0])) - Decimal("0.33")) < Decimal("0.0001")
    assert abs(Decimal(str(row[1])) - Decimal("33")) < Decimal("0.01")  # bps = pp * 100
    assert row[2] is False


def test_yield_curve_inversion_flag(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    inv = _scalar(db, "SELECT is_inverted_10y_2y FROM marts.mart_yield_curve "
                      "WHERE observation_date = '2026-11-19'")
    assert inv is True  # 4.20 - 4.30 < 0


def test_historical_vintage_selection_picks_latest(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    # 2026-05-01 has an original and a later-vintage revision (305.9) -> revision wins.
    val = _scalar(db, "SELECT value FROM intermediate.int_economic_pit "
                      "WHERE observation_date = '2026-05-01'")
    assert Decimal(str(val)) == Decimal("305.9")


# -- research marts (honest deferral) -------------------------------------

def test_research_quality_reports_deferral(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    status = _scalar(db, "SELECT integration_status FROM marts.mart_research_quality")
    assert status == "deferred_to_de7_no_warehouse_records"


def test_regimes_does_not_claim_2022(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    covers = _scalar(db, "SELECT bool_or(covers_2022) FROM marts.mart_historical_regimes")
    assert covers is False  # no 2022 data ingested -> no 2022 claim


# -- independent cross-validation (SQL vs Decimal) ------------------------

def test_cross_validation_drawdown_agrees(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    cv = WarehouseCrossValidator(db).max_drawdown("SPY")
    assert cv.agrees and cv.status == "confirmed"
    assert cv.evidence_artifacts and cv.evidence_artifacts[0].startswith("RAW-")


def test_cross_validation_cumulative_return_agrees(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    cv = WarehouseCrossValidator(db).cumulative_return("QQQ")
    assert cv.agrees and cv.sql_value is not None and cv.python_value is not None


def test_cross_validation_correlation_agrees(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    cv = WarehouseCrossValidator(db).correlation("SPY", "QQQ")
    assert cv.agrees, (cv.sql_value, cv.python_value, cv.difference)


def test_cross_validation_margin_agrees(built: tuple[Path, DbtRunResult]) -> None:
    db, _ = built
    cv = WarehouseCrossValidator(db).margin("CIK0000320193", "operating_margin")
    assert cv.agrees, (cv.sql_value, cv.python_value)
    assert cv.evidence_artifacts  # source lineage preserved


# -- incremental correction propagation -----------------------------------

def test_historical_correction_recomputes_rolling_windows(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    from tests.lakehouse.transform_fixtures import _PRICES, _alpaca_payload

    from strix.lakehouse.bronze import BronzeIngestor
    from strix.lakehouse.contracts import DatasetRef, DataSource
    from strix.lakehouse.silver.engine import SilverTransformer
    from strix.lakehouse.storage import LocalObjectStore
    from strix.lakehouse.warehouse.duckdb_warehouse import DuckDBWarehouse

    root = tmp_path_factory.mktemp("incr_lh")
    db = seed_rich_warehouse(root)
    runner = DbtRunner(resolve_project_dir(None), db)
    runner.write_profile()
    runner.invoke("seed")
    runner.invoke("build")
    before = _scalar(db, "SELECT max_drawdown FROM marts.mart_market_drawdown "
                         "WHERE instrument_symbol = 'SPY'")

    # Correct a historical SPY bar: deepen the dip at session index 2 (498 -> 470),
    # a valid in-range change, then re-ingest, re-normalize, reload, rebuild.
    corrected = list(_PRICES["SPY"])
    corrected[2] = 470.0
    when = datetime(2026, 11, 24, tzinfo=UTC)
    BronzeIngestor(LocalObjectStore(root)).ingest(
        DatasetRef(source=DataSource.ALPACA, dataset="equity_bars_daily",
                   entity="SPY", partition="2026-11"),
        _alpaca_payload(corrected), endpoint="https://example", retrieved_at=when, producer="t",
    )
    SilverTransformer(root, clock=lambda: when).transform("alpaca_equity_bars_daily")
    DuckDBWarehouse(db, root).load_silver("alpaca_equity_bars_daily", now=when)
    assert runner.invoke("build", select="int_market_daily+").success

    after = _scalar(db, "SELECT max_drawdown FROM marts.mart_market_drawdown "
                        "WHERE instrument_symbol = 'SPY'")
    # The deeper historical dip must propagate: max drawdown becomes more negative.
    assert Decimal(str(after)) < Decimal(str(before))
    # Independent recompute agrees with the rebuilt mart.
    cv = WarehouseCrossValidator(db).max_drawdown("SPY")
    assert cv.agrees
