"""Versioned calculation contracts for the transformation layer.

Each contract documents one analytical calculation's formula, methodology version,
inputs, units, precision, minimum sample size, null handling, historical-
availability rules, and evidence-lineage requirements. The methodology version is
pinned to :data:`strix.agent.calculations.CALC_VERSION` so SQL marts and the
independent Python verifier share one definition. Financial-statement ratios use
exact Decimal arithmetic; statistical calculations (volatility, correlation)
require floating point and are compared under an explicit tolerance.
"""

from __future__ import annotations

from strix.agent.calculations import CALC_VERSION
from strix.lakehouse.transform.contracts import CalculationContract

#: Absolute tolerance for statistical (float-bearing) cross-validation.
STAT_TOLERANCE = "0.0000005"
#: Exact Decimal match required for financial-statement ratios.
DECIMAL_TOLERANCE = "0"


def _c(**kw: object) -> CalculationContract:
    return CalculationContract(methodology_version=CALC_VERSION, **kw)


_CONTRACTS: tuple[CalculationContract, ...] = (
    _c(
        identifier="period_return",
        formula="last_close / first_close - 1",
        input_datasets=("alpaca_equity_bars_daily",),
        required_observations="ordered close prices over the window (>= 2)",
        output_unit="ratio",
        precision_policy="Decimal, 6dp (RATIO_QUANTUM)",
        min_sample_size=2,
        null_handling="skip null closes; require positive first close",
        historical_availability="session observation date; adjusted (Alpaca adjustment=all)",
        evidence_lineage="each bar resolves to its Bronze artifact via the warehouse",
    ),
    _c(
        identifier="cumulative_return",
        formula="last_close / first_close - 1",
        input_datasets=("alpaca_equity_bars_daily",),
        required_observations="ordered close prices from first session (>= 2)",
        output_unit="ratio",
        precision_policy="Decimal, 6dp",
        min_sample_size=2,
        null_handling="skip null closes; require positive first close",
        historical_availability="session observation date",
        evidence_lineage="bars resolve to Bronze via the warehouse",
    ),
    _c(
        identifier="max_drawdown",
        formula="min over t of (close_t / running_peak_t - 1)",
        input_datasets=("alpaca_equity_bars_daily",),
        required_observations="ordered close prices over the window (>= 2)",
        output_unit="ratio (non-positive)",
        precision_policy="Decimal, 6dp",
        min_sample_size=2,
        null_handling="skip null closes",
        historical_availability="session observation date",
        evidence_lineage="bars resolve to Bronze via the warehouse",
    ),
    _c(
        identifier="realized_volatility",
        formula="sample_stddev(ln(close_t/close_{t-1})) * sqrt(periods_per_year)",
        input_datasets=("alpaca_equity_bars_daily",),
        required_observations="ordered positive close prices (>= 3)",
        output_unit="annualized ratio",
        precision_policy="Decimal context prec=50; result 6dp; sqrt via Decimal",
        min_sample_size=3,
        null_handling="require positive consecutive prices for log returns",
        historical_availability="session observation date",
        evidence_lineage="bars resolve to Bronze via the warehouse",
    ),
    _c(
        identifier="correlation",
        formula="pearson(simple_returns(a), simple_returns(b))",
        input_datasets=("alpaca_equity_bars_daily",),
        required_observations="two equal-length aligned series (>= 3 each)",
        output_unit="correlation in [-1, 1]",
        precision_policy="Decimal context prec=50; result 6dp",
        min_sample_size=3,
        null_handling="inner-join aligned sessions; undefined for constant series",
        historical_availability="session observation date",
        evidence_lineage="both symbols' bars resolve to Bronze via the warehouse",
    ),
    _c(
        identifier="gross_profit_margin",
        formula="gross_profit / revenue",
        input_datasets=("sec_company_facts",),
        required_observations="first-filed gross_profit and revenue for one period",
        output_unit="ratio",
        precision_policy="exact Decimal; no rounding beyond storage scale",
        min_sample_size=1,
        null_handling="insufficient_data if either missing; undefined if revenue=0",
        historical_availability="SEC filed_date (point-in-time, first-filed)",
        evidence_lineage="period row carries accession + Bronze artifact id",
    ),
    _c(
        identifier="operating_margin",
        formula="operating_income / revenue",
        input_datasets=("sec_company_facts",),
        required_observations="first-filed operating_income and revenue for one period",
        output_unit="ratio",
        precision_policy="exact Decimal",
        min_sample_size=1,
        null_handling="insufficient_data if either missing; undefined if revenue=0",
        historical_availability="SEC filed_date (first-filed)",
        evidence_lineage="period row carries accession + Bronze artifact id",
    ),
    _c(
        identifier="net_profit_margin",
        formula="net_income / revenue",
        input_datasets=("sec_company_facts",),
        required_observations="first-filed net_income and revenue for one period",
        output_unit="ratio",
        precision_policy="exact Decimal",
        min_sample_size=1,
        null_handling="insufficient_data if either missing; undefined if revenue=0",
        historical_availability="SEC filed_date (first-filed)",
        evidence_lineage="period row carries accession + Bronze artifact id",
    ),
)

CALCULATION_CONTRACTS: dict[str, CalculationContract] = {c.identifier: c for c in _CONTRACTS}


def contract(identifier: str) -> CalculationContract:
    try:
        return CALCULATION_CONTRACTS[identifier]
    except KeyError as exc:  # pragma: no cover - defensive
        raise KeyError(f"no calculation contract named {identifier!r}") from exc
