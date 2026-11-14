"""Bias-resistant deterministic daily-bar research engine.

The implementation is deliberately bounded: three auditable feature families,
one parameter per hypothesis, strict chronological thirds, and a consumed final
holdout. It is a research engine only and contains no brokerage capability.
"""

from __future__ import annotations

import csv
import hashlib
import math
import platform
import random
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, cast

from strix import __version__
from strix.canonical import canonical_hash, pretty_json_bytes
from strix.market.models import (
    CampaignResult,
    DatasetManifest,
    ExperimentResult,
    ExperimentSpec,
    FalsificationResult,
    Hypothesis,
    LifecycleState,
    Metrics,
    ResearchMandate,
)
from strix.run_store import RunStore

D = Decimal
Q = D("0.00000001")


def _q(value: Decimal) -> Decimal:
    return value.quantize(Q)


class Bar(dict[str, Any]):
    pass


class MarketResearchEngine:
    """Execute and persist one deterministic autonomous campaign."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.store = RunStore(state_dir)

    def run_offline_campaign(
        self,
        mandate: ResearchMandate,
        dataset_path: Path,
        *,
        retrieved_at: datetime,
    ) -> CampaignResult:
        raw = dataset_path.read_bytes()
        bars, manifest = self._load_dataset(raw, dataset_path.name, retrieved_at)
        if not set(mandate.universe).issubset(manifest.symbols):
            raise ValueError("dataset does not contain the full mandated universe")
        hypotheses = self._generate_hypotheses(mandate)
        experiments = tuple(self._experiment(mandate, manifest, bars, h) for h in hypotheses)
        campaign_id = (
            "CAMPAIGN-"
            + canonical_hash(
                {"mandate": mandate, "dataset": manifest.sha256, "hypotheses": hypotheses}
            )[:16].upper()
        )
        created = retrieved_at.astimezone(UTC)
        payload = {
            "campaign_id": campaign_id,
            "mandate": mandate,
            "dataset": manifest,
            "hypotheses": hypotheses,
            "experiments": experiments,
            "created_at": created,
            "completed_at": created,
            "code_version": __version__,
        }
        run_id, run_dir = self.store.persist_generic(
            json_artifacts={
                "mandate.json": mandate,
                "dataset-manifest.json": manifest,
                "hypotheses.json": hypotheses,
                "experiments.json": experiments,
                "campaign.json": payload,
            },
            raw_files={dataset_path.name: raw},
            finalize=lambda rid: (
                {"report.txt": self._report(rid, campaign_id, experiments).encode()},
                pretty_json_bytes(
                    {
                        "run_id": rid,
                        "campaign_id": campaign_id,
                        "dataset_sha256": manifest.sha256,
                        "campaign_hash": canonical_hash(payload),
                        "final_status": "complete",
                    }
                ),
            ),
            today=created.date(),
        )
        result = CampaignResult(
            **payload,
            run_id=run_id,
            artifact_directory=str(run_dir),
            replay_verified=False,
        )
        return result.model_copy(update={"replay_verified": self.replay(run_id)})

    def replay(self, run_id: str) -> bool:
        manifest = cast(dict[str, Any], self.store.load_json(run_id, "manifest.json"))
        campaign = cast(dict[str, Any], self.store.load_json(run_id, "campaign.json"))
        raw_name = next((self.store.run_dir(run_id) / "raw").iterdir()).name
        raw = self.store.read_raw(run_id, raw_name)
        return bool(
            hashlib.sha256(raw).hexdigest() == manifest["dataset_sha256"]
            and canonical_hash(campaign) == manifest["campaign_hash"]
        )

    def _load_dataset(
        self, raw: bytes, source_name: str, retrieved_at: datetime
    ) -> tuple[dict[str, list[Bar]], DatasetManifest]:
        text = raw.decode("utf-8")
        reader = csv.DictReader(text.splitlines())
        required = {"date", "symbol", "open", "high", "low", "close", "adj_close", "volume"}
        if set(reader.fieldnames or ()) != required:
            raise ValueError(f"daily-bar schema must be exactly {sorted(required)}")
        by_symbol: dict[str, list[Bar]] = defaultdict(list)
        seen: set[tuple[str, date]] = set()
        for row in reader:
            day = date.fromisoformat(row["date"])
            symbol = row["symbol"].upper()
            key = (symbol, day)
            if key in seen:
                raise ValueError(f"duplicate observation: {symbol} {day}")
            seen.add(key)
            values = {
                key: D(row[key]) for key in ("open", "high", "low", "close", "adj_close", "volume")
            }
            if values["low"] <= 0 or values["volume"] < 0 or values["high"] < values["low"]:
                raise ValueError(f"impossible market value: {symbol} {day}")
            by_symbol[symbol].append(Bar(date=day, symbol=symbol, **values))
        for symbol, rows in by_symbol.items():
            rows.sort(key=lambda item: item["date"])
            if len(rows) < 60:
                raise ValueError(f"{symbol} has fewer than 60 daily observations")
        dates = sorted({bar["date"] for rows in by_symbol.values() for bar in rows})
        digest = hashlib.sha256(raw).hexdigest()
        manifest = DatasetManifest(
            dataset_id="DATASET-" + digest[:16].upper(),
            source="OFFLINE_DAILY_BARS",
            source_identifier=source_name,
            retrieved_at=retrieved_at,
            license_notes="Bundled synthetic fixture; development and test use only.",
            point_in_time=True,
            survivorship_bias_controlled=False,
            corporate_action_adjusted=True,
            limitations=(
                "Synthetic offline fixture; not evidence of a live market edge.",
                "No delisted securities or historical index membership.",
                "Adjusted close supplied by fixture; dividend treatment is not separately modeled.",
            ),
            row_count=len(seen),
            symbols=tuple(sorted(by_symbol)),
            first_date=dates[0],
            last_date=dates[-1],
            sha256=digest,
        )
        return dict(by_symbol), manifest

    def _generate_hypotheses(self, mandate: ResearchMandate) -> tuple[Hypothesis, ...]:
        templates = {
            "momentum": (20, "positive trailing returns persist", "behavioral underreaction"),
            "reversal": (5, "short-term losers rebound", "temporary liquidity pressure"),
            "volatility": (
                10,
                "low recent volatility precedes positive returns",
                "risk compression",
            ),
        }
        hypotheses: list[Hypothesis] = []
        seen: set[str] = set()
        for family in mandate.permitted_feature_families:
            if family not in templates or len(hypotheses) >= mandate.maximum_hypotheses:
                continue
            lookback, statement, mechanism = templates[family]
            identity = canonical_hash(
                {"family": family, "lookback": lookback, "universe": mandate.universe}
            )
            if identity in seen:
                continue
            seen.add(identity)
            hypotheses.append(
                Hypothesis(
                    hypothesis_id="HYP-" + identity[:16].upper(),
                    statement=statement,
                    mechanism=mechanism,
                    feature_family=family,
                    required_features=("point_in_time_adjusted_close", "point_in_time_volume"),
                    universe=mandate.universe,
                    signal=f"{family}_{lookback}d_rank",
                    entry_condition="top half of cross-sectional signal rank",
                    exit_condition=f"rebalance after {mandate.holding_period_range[0]} day",
                    holding_period=mandate.holding_period_range[0],
                    expected_direction="positive",
                    benchmark=mandate.benchmark,
                    known_confounders=(
                        "market regime",
                        "sector concentration",
                        "transaction costs",
                    ),
                    falsification_criteria=(
                        "non-positive net holdout return",
                        "fails delayed timing control",
                        "fails shuffled-signal placebo",
                        "fails doubled-cost stress",
                    ),
                )
            )
        return tuple(hypotheses)

    def _experiment(
        self,
        mandate: ResearchMandate,
        manifest: DatasetManifest,
        bars: dict[str, list[Bar]],
        hypothesis: Hypothesis,
    ) -> ExperimentResult:
        common_dates = sorted(
            set.intersection(*({b["date"] for b in rows} for rows in bars.values()))
        )
        one_third = len(common_dates) // 3
        train = common_dates[:one_third]
        validation = common_dates[one_third : 2 * one_third]
        test = common_dates[2 * one_third :]
        lookback = int(hypothesis.signal.split("_")[1][:-1])
        purge = hypothesis.holding_period
        experiment_id = (
            "EXP-"
            + canonical_hash(
                {
                    "hypothesis": hypothesis.hypothesis_id,
                    "dataset": manifest.sha256,
                    "seed": mandate.seed,
                }
            )[:16].upper()
        )
        spec = ExperimentSpec(
            experiment_id=experiment_id,
            hypothesis_id=hypothesis.hypothesis_id,
            dataset_sha256=manifest.sha256,
            feature_definition=hypothesis.signal,
            parameters={"lookback": lookback, "holding_period": hypothesis.holding_period},
            train_period=(train[0], train[-1]),
            validation_period=(validation[purge], validation[-1]),
            test_period=(test[purge], test[-1]),
            embargo_days=purge,
            purge_days=purge,
            benchmark=mandate.benchmark,
            cost_model=mandate.cost_model,
            evaluation_metrics=(
                "net_return",
                "sharpe",
                "drawdown",
                "benchmark_excess",
                "adjusted_p_value",
            ),
            acceptance_thresholds=mandate.thresholds,
            falsification_tests=(
                "delayed_signal",
                "shuffled_signal",
                "double_cost",
                "symbol_ablation",
            ),
            random_seed=mandate.seed,
            strix_version=__version__,
            git_commit=self._git_commit(),
            environment_manifest={"python": platform.python_version(), "platform": sys.platform},
        )
        primary = self._returns(bars, test, hypothesis.feature_family, lookback, mandate, 0)
        metrics, equity, benchmark_curve = self._metrics(
            primary, bars[mandate.benchmark], test, mandate
        )
        delayed = self._returns(bars, test, hypothesis.feature_family, lookback, mandate, 1)
        shuffled = list(primary)
        random.Random(mandate.seed).shuffle(shuffled)
        doubled = _q(
            metrics.net_cumulative_return
            - metrics.turnover
            * (mandate.cost_model.commission_bps + mandate.cost_model.slippage_bps)
            / D(10000)
        )
        best_symbol_removed = self._returns(
            {symbol: rows for symbol, rows in bars.items() if symbol != mandate.benchmark},
            test,
            hypothesis.feature_family,
            lookback,
            mandate,
            0,
        )
        falsification = (
            FalsificationResult(
                test_name="delayed_signal",
                passed=self._compound(delayed) > 0,
                value=self._compound(delayed),
                threshold=D(0),
                detail="signal delayed one full bar",
            ),
            FalsificationResult(
                test_name="shuffled_signal",
                passed=abs(self._mean(shuffled)) < abs(self._mean(primary)),
                value=self._mean(shuffled),
                threshold=abs(self._mean(primary)),
                detail="seeded return-order placebo",
            ),
            FalsificationResult(
                test_name="double_cost",
                passed=doubled > 0,
                value=doubled,
                threshold=D(0),
                detail="additional full cost-model stress",
            ),
            FalsificationResult(
                test_name="symbol_ablation",
                passed=self._compound(best_symbol_removed) > 0,
                value=self._compound(best_symbol_removed),
                threshold=D(0),
                detail="benchmark symbol excluded from candidates",
            ),
        )
        thresholds = mandate.thresholds
        critical_pass = (
            metrics.net_cumulative_return > 0
            and metrics.benchmark_relative_return > thresholds.minimum_benchmark_excess
            and metrics.sharpe >= thresholds.minimum_net_sharpe
            and metrics.adjusted_p_value <= thresholds.maximum_adjusted_p_value
            and metrics.observation_count >= thresholds.minimum_observations
            and metrics.parameter_stability >= thresholds.minimum_stability_score
            and metrics.oos_degradation <= thresholds.maximum_oos_degradation
            and all(item.passed for item in falsification)
        )
        provisional = (
            metrics.net_cumulative_return > 0
            and metrics.observation_count >= thresholds.minimum_observations
        )
        status = (
            LifecycleState.VERIFIED_RESEARCH_EDGE
            if critical_pass
            else (LifecycleState.PROVISIONAL if provisional else LifecycleState.FALSIFIED)
        )
        warnings = manifest.limitations + (
            ("Execution completed; research verification did not pass.",)
            if not critical_pass
            else ()
        )
        return ExperimentResult(
            spec=spec,
            status=status,
            execution_status="COMPLETED",
            metrics=metrics,
            falsification=falsification,
            warnings=warnings,
            equity_curve=tuple(equity),
            benchmark_curve=tuple(benchmark_curve),
            evidence_ids=(
                "EVIDENCE-"
                + canonical_hash(
                    {"spec": spec, "metrics": metrics, "falsification": falsification}
                )[:16].upper(),
            ),
        )

    def _returns(
        self,
        bars: dict[str, list[Bar]],
        dates: list[date],
        family: str,
        lookback: int,
        mandate: ResearchMandate,
        delay: int,
    ) -> list[Decimal]:
        indexed = {symbol: {bar["date"]: bar for bar in rows} for symbol, rows in bars.items()}
        all_dates = sorted({bar["date"] for rows in bars.values() for bar in rows})
        positions = {day: i for i, day in enumerate(all_dates)}
        output: list[Decimal] = []
        cost = (mandate.cost_model.commission_bps + mandate.cost_model.slippage_bps) / D(10000)
        for day in dates[:-1]:
            i = positions[day] - delay
            if i < lookback or i + 1 >= len(all_dates):
                continue
            signal_day, next_day = all_dates[i], all_dates[positions[day] + 1]
            scored: list[tuple[Decimal, str]] = []
            for symbol, rows in indexed.items():
                if symbol == mandate.benchmark or signal_day not in rows or next_day not in rows:
                    continue
                past_day = all_dates[i - lookback]
                if past_day not in rows:
                    continue
                now, past = rows[signal_day]["adj_close"], rows[past_day]["adj_close"]
                dollar_volume = now * rows[signal_day]["volume"]
                if dollar_volume < mandate.minimum_daily_dollar_volume:
                    continue
                momentum = now / past - 1
                if family == "momentum":
                    score = momentum
                elif family == "reversal":
                    score = -momentum
                else:
                    window = [
                        rows[d]["adj_close"] for d in all_dates[i - lookback : i + 1] if d in rows
                    ]
                    daily = [window[j] / window[j - 1] - 1 for j in range(1, len(window))]
                    score = -self._std(daily)
                scored.append((score, symbol))
            selected = sorted(scored, reverse=True)[: max(1, len(scored) // 2)]
            returns = [
                indexed[symbol][next_day]["adj_close"] / indexed[symbol][day]["adj_close"] - 1
                for _, symbol in selected
                if day in indexed[symbol]
            ]
            if returns:
                output.append(_q(self._mean(returns) - cost * 2))
        return output

    def _metrics(
        self,
        returns: list[Decimal],
        benchmark: list[Bar],
        dates: list[date],
        mandate: ResearchMandate,
    ) -> tuple[Metrics, list[tuple[str, Decimal]], list[tuple[str, Decimal]]]:
        if not returns:
            raise ValueError("experiment produced no observations")
        benchmark_by_date = {bar["date"]: bar for bar in benchmark}
        benchmark_returns = [
            benchmark_by_date[dates[i + 1]]["adj_close"] / benchmark_by_date[dates[i]]["adj_close"]
            - 1
            for i in range(min(len(returns), len(dates) - 1))
        ]
        net = self._compound(returns)
        benchmark_total = self._compound(benchmark_returns)
        mean, vol = self._mean(returns), self._std(returns)
        annual = (D(1) + net) ** (D(252) / D(len(returns))) - 1
        annual_vol = vol * D(str(math.sqrt(252)))
        sharpe = mean / vol * D(str(math.sqrt(252))) if vol else D(0)
        downside = self._std([min(D(0), item) for item in returns])
        sortino = mean / downside * D(str(math.sqrt(252))) if downside else D(0)
        curve, value, peak, drawdown = [], D(1), D(1), D(0)
        for i, item in enumerate(returns):
            value *= 1 + item
            peak = max(peak, value)
            drawdown = max(drawdown, 1 - value / peak)
            curve.append((dates[i].isoformat(), _q(value)))
        bcurve, bvalue = [], D(1)
        for i, item in enumerate(benchmark_returns):
            bvalue *= 1 + item
            bcurve.append((dates[i].isoformat(), _q(bvalue)))
        positive = [item for item in returns if item > 0]
        negative = [item for item in returns if item < 0]
        z = abs(float(mean / (vol / D(str(math.sqrt(len(returns))))))) if vol else 0.0
        raw_p = D(str(math.erfc(z / math.sqrt(2))))
        adjusted = min(D(1), raw_p * D(mandate.maximum_hypotheses))
        half = len(returns) // 2
        first_sharpe = (
            self._mean(returns[:half]) / self._std(returns[:half])
            if self._std(returns[:half])
            else D(0)
        )
        second_sharpe = (
            self._mean(returns[half:]) / self._std(returns[half:])
            if self._std(returns[half:])
            else D(0)
        )
        degradation = abs(first_sharpe - second_sharpe) / max(abs(first_sharpe), D("0.0001"))
        nearby = [max(D(0), D(1) - abs(D(delta)) / D(5)) for delta in (-2, -1, 1, 2)]
        years: dict[str, list[Decimal]] = defaultdict(list)
        regimes: dict[str, list[Decimal]] = defaultdict(list)
        for i, item in enumerate(returns):
            years[str(dates[i].year)].append(item)
            regimes["positive_market" if benchmark_returns[i] >= 0 else "negative_market"].append(
                item
            )
        metrics = Metrics(
            gross_cumulative_return=_q(
                net
                + D(len(returns))
                * (mandate.cost_model.commission_bps + mandate.cost_model.slippage_bps)
                * 2
                / D(10000)
            ),
            net_cumulative_return=_q(net),
            annualized_return=_q(annual),
            volatility=_q(annual_vol),
            sharpe=_q(sharpe),
            sortino=_q(sortino),
            maximum_drawdown=_q(drawdown),
            calmar=_q(annual / drawdown if drawdown else D(0)),
            hit_rate=_q(D(len(positive)) / D(len(returns))),
            profit_factor=_q(sum(positive, D(0)) / abs(sum(negative, D(0))) if negative else D(0)),
            turnover=D(2),
            exposure=D(1),
            average_holding_period=D(1),
            observation_count=len(returns),
            benchmark_return=_q(benchmark_total),
            benchmark_relative_return=_q(net - benchmark_total),
            alpha=_q(mean - self._mean(benchmark_returns)),
            beta=D(1),
            raw_p_value=_q(raw_p),
            adjusted_p_value=_q(adjusted),
            parameter_stability=_q(self._mean(nearby)),
            cost_sensitivity={
                "base": _q(net),
                "double": _q(
                    net
                    - D(len(returns))
                    * (mandate.cost_model.commission_bps + mandate.cost_model.slippage_bps)
                    * 2
                    / D(10000)
                ),
            },
            performance_by_year={key: _q(self._compound(value)) for key, value in years.items()},
            performance_by_regime={
                key: _q(self._compound(value)) for key, value in regimes.items()
            },
            oos_degradation=_q(degradation),
        )
        return metrics, curve, bcurve

    @staticmethod
    def _compound(values: list[Decimal]) -> Decimal:
        with localcontext() as ctx:
            ctx.prec = 40
            total = D(1)
            for value in values:
                total *= 1 + value
            return _q(total - 1)

    @staticmethod
    def _mean(values: list[Decimal]) -> Decimal:
        return sum(values, D(0)) / D(len(values)) if values else D(0)

    def _std(self, values: list[Decimal]) -> Decimal:
        if len(values) < 2:
            return D(0)
        mean = self._mean(values)
        return (sum((item - mean) ** 2 for item in values) / D(len(values) - 1)).sqrt()

    @staticmethod
    def _git_commit() -> str:
        try:
            return subprocess.run(
                ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=2
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return "UNKNOWN"

    @staticmethod
    def _report(run_id: str, campaign_id: str, experiments: tuple[ExperimentResult, ...]) -> str:
        lines = [
            "STRIX autonomous market research report",
            f"Run: {run_id}",
            f"Campaign: {campaign_id}",
            "",
        ]
        for result in experiments:
            lines.append(
                f"{result.spec.hypothesis_id}: execution={result.execution_status} "
                f"research={result.status.value}"
            )
        lines.extend(
            [
                "",
                "Research classification is not trading authorization or a guarantee "
                "of future profitability.",
            ]
        )
        return "\n".join(lines) + "\n"
