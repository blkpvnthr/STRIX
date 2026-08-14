"""Versioned contracts for bounded autonomous market research."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LifecycleState(StrEnum):
    PROPOSED = "PROPOSED"
    QUEUED = "QUEUED"
    TESTING = "TESTING"
    FALSIFIED = "FALSIFIED"
    INCONCLUSIVE = "INCONCLUSIVE"
    PROVISIONAL = "PROVISIONAL"
    VERIFIED_RESEARCH_EDGE = "VERIFIED_RESEARCH_EDGE"
    DEGRADED = "DEGRADED"
    RETIRED = "RETIRED"


class CostModel(StrictModel):
    commission_bps: Decimal = Field(ge=0, le=100)
    slippage_bps: Decimal = Field(ge=0, le=200)


class ResearchThresholds(StrictModel):
    minimum_observations: int = Field(default=40, ge=20)
    minimum_net_sharpe: Decimal = Decimal("0.50")
    minimum_benchmark_excess: Decimal = Decimal("0")
    maximum_adjusted_p_value: Decimal = Decimal("0.10")
    minimum_stability_score: Decimal = Decimal("0.50")
    maximum_oos_degradation: Decimal = Decimal("0.60")


class ResearchMandate(StrictModel):
    mandate_id: str = Field(pattern=r"^MANDATE-[A-Z0-9-]{3,64}$")
    version: int = Field(default=1, ge=1)
    universe: tuple[str, ...] = Field(min_length=2, max_length=100)
    allowed_datasets: tuple[str, ...] = ("OFFLINE_DAILY_BARS",)
    start_date: date
    end_date: date
    holding_period_range: tuple[int, int] = (1, 10)
    maximum_turnover: Decimal = Field(default=Decimal("1"), gt=0, le=2)
    minimum_daily_dollar_volume: Decimal = Field(default=Decimal("1000000"), gt=0)
    cost_model: CostModel = CostModel(commission_bps=Decimal("1"), slippage_bps=Decimal("4"))
    benchmark: str = "SPY"
    maximum_drawdown: Decimal = Field(default=Decimal("0.35"), gt=0, le=1)
    thresholds: ResearchThresholds = ResearchThresholds()
    maximum_hypotheses: int = Field(default=6, ge=1, le=50)
    maximum_parameter_trials: int = Field(default=24, ge=1, le=500)
    compute_budget_seconds: int = Field(default=60, ge=1, le=86400)
    seed: int = Field(default=7, ge=0)
    permitted_feature_families: tuple[str, ...] = (
        "momentum",
        "reversal",
        "volatility",
    )
    prohibited_behaviors: tuple[str, ...] = (
        "future_data_access",
        "real_money_trading",
        "broker_order_submission",
        "holdout_reuse",
    )
    cadence: str = "manual"
    stopping_conditions: tuple[str, ...] = ("hypothesis_budget_exhausted", "time_budget_exhausted")

    @model_validator(mode="after")
    def validate_ranges(self) -> ResearchMandate:
        if self.start_date >= self.end_date:
            raise ValueError("start_date must precede end_date")
        low, high = self.holding_period_range
        if low < 1 or high < low:
            raise ValueError("holding_period_range is invalid")
        if self.benchmark not in self.universe:
            raise ValueError("benchmark must be included in universe")
        return self


class DatasetManifest(StrictModel):
    dataset_id: str
    schema_version: str = "market-bars-v1"
    source: str
    source_identifier: str
    retrieved_at: datetime
    license_notes: str
    point_in_time: bool
    survivorship_bias_controlled: bool
    corporate_action_adjusted: bool
    limitations: tuple[str, ...]
    row_count: int
    symbols: tuple[str, ...]
    first_date: date
    last_date: date
    sha256: str


class Hypothesis(StrictModel):
    hypothesis_id: str
    statement: str
    mechanism: str
    feature_family: str
    required_features: tuple[str, ...]
    universe: tuple[str, ...]
    signal: str
    entry_condition: str
    exit_condition: str
    holding_period: int
    expected_direction: str
    benchmark: str
    known_confounders: tuple[str, ...]
    falsification_criteria: tuple[str, ...]
    parent_hypothesis_id: str | None = None
    creation_source: str = "deterministic_generator_v1"
    status: LifecycleState = LifecycleState.PROPOSED


class ExperimentSpec(StrictModel):
    experiment_id: str
    hypothesis_id: str
    dataset_sha256: str
    feature_definition: str
    parameters: dict[str, int | str]
    train_period: tuple[date, date]
    validation_period: tuple[date, date]
    test_period: tuple[date, date]
    embargo_days: int
    purge_days: int
    benchmark: str
    cost_model: CostModel
    evaluation_metrics: tuple[str, ...]
    acceptance_thresholds: ResearchThresholds
    falsification_tests: tuple[str, ...]
    random_seed: int
    strix_version: str
    git_commit: str
    environment_manifest: dict[str, str]
    final_holdout_consumed: bool = True


class Metrics(StrictModel):
    gross_cumulative_return: Decimal
    net_cumulative_return: Decimal
    annualized_return: Decimal
    volatility: Decimal
    sharpe: Decimal
    sortino: Decimal
    maximum_drawdown: Decimal
    calmar: Decimal
    hit_rate: Decimal
    profit_factor: Decimal
    turnover: Decimal
    exposure: Decimal
    average_holding_period: Decimal
    observation_count: int
    benchmark_return: Decimal
    benchmark_relative_return: Decimal
    alpha: Decimal
    beta: Decimal
    raw_p_value: Decimal
    adjusted_p_value: Decimal
    parameter_stability: Decimal
    cost_sensitivity: dict[str, Decimal]
    performance_by_year: dict[str, Decimal]
    performance_by_regime: dict[str, Decimal]
    oos_degradation: Decimal


class FalsificationResult(StrictModel):
    test_name: str
    passed: bool
    value: Decimal | str
    threshold: Decimal | str
    detail: str


class ExperimentResult(StrictModel):
    spec: ExperimentSpec
    status: LifecycleState
    execution_status: str
    metrics: Metrics
    falsification: tuple[FalsificationResult, ...]
    warnings: tuple[str, ...]
    equity_curve: tuple[tuple[str, Decimal], ...]
    benchmark_curve: tuple[tuple[str, Decimal], ...]
    evidence_ids: tuple[str, ...]
    verification_version: str = "market-verification-v1"


class CampaignResult(StrictModel):
    campaign_id: str
    mandate: ResearchMandate
    dataset: DatasetManifest
    hypotheses: tuple[Hypothesis, ...]
    experiments: tuple[ExperimentResult, ...]
    created_at: datetime
    completed_at: datetime
    code_version: str
    run_id: str
    artifact_directory: str
    replay_verified: bool
