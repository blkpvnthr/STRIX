from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from strix.market import MarketResearchEngine, ResearchMandate


def write_bars(path: Path, *, future_multiplier: Decimal = Decimal("1")) -> None:
    lines = ["date,symbol,open,high,low,close,adj_close,volume"]
    start = date(2024, 1, 2)
    for index in range(120):
        day = start + timedelta(days=index)
        for symbol, drift in (
            ("AAA", Decimal("0.002")),
            ("BBB", Decimal("-0.001")),
            ("SPY", Decimal("0.0005")),
        ):
            price = Decimal("100") * (Decimal("1") + drift) ** index
            if index == 119:
                price *= future_multiplier
            lines.append(f"{day},{symbol},{price},{price + 1},{price - 1},{price},{price},1000000")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mandate() -> ResearchMandate:
    return ResearchMandate(
        mandate_id="MANDATE-DEMO-001",
        universe=("AAA", "BBB", "SPY"),
        start_date=date(2024, 1, 2),
        end_date=date(2024, 5, 1),
        benchmark="SPY",
        maximum_hypotheses=3,
        seed=11,
    )


def test_campaign_is_bounded_replayable_and_never_claims_execution_is_verification(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "bars.csv"
    write_bars(dataset)
    engine = MarketResearchEngine(tmp_path / "state")
    result = engine.run_offline_campaign(
        mandate(), dataset, retrieved_at=datetime(2026, 8, 14, tzinfo=UTC)
    )
    assert len(result.hypotheses) <= mandate().maximum_hypotheses
    assert result.replay_verified
    assert engine.replay(result.run_id)
    assert all(item.execution_status == "COMPLETED" for item in result.experiments)
    assert all(
        item.status.value in {"FALSIFIED", "PROVISIONAL", "VERIFIED_RESEARCH_EDGE"}
        for item in result.experiments
    )
    assert all(item.spec.final_holdout_consumed for item in result.experiments)


def test_dataset_hash_stable_and_future_holdout_value_does_not_change_prior_features(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    write_bars(first)
    write_bars(second, future_multiplier=Decimal("9"))
    engine = MarketResearchEngine(tmp_path / "state")
    bars_a, manifest_a = engine._load_dataset(
        first.read_bytes(), first.name, datetime(2026, 8, 14, tzinfo=UTC)
    )
    bars_b, manifest_b = engine._load_dataset(
        first.read_bytes(), first.name, datetime(2026, 8, 14, tzinfo=UTC)
    )
    bars_future, _ = engine._load_dataset(
        second.read_bytes(), second.name, datetime(2026, 8, 14, tzinfo=UTC)
    )
    assert manifest_a.sha256 == manifest_b.sha256
    assert bars_a["AAA"][-2] == bars_future["AAA"][-2]
    assert bars_a == bars_b


def test_duplicate_observation_rejected(tmp_path: Path) -> None:
    dataset = tmp_path / "bars.csv"
    write_bars(dataset)
    lines = dataset.read_text().splitlines()
    dataset.write_text("\n".join([*lines, lines[1]]) + "\n")
    with pytest.raises(ValueError, match="duplicate observation"):
        MarketResearchEngine(tmp_path / "state")._load_dataset(
            dataset.read_bytes(), dataset.name, datetime.now(UTC)
        )


def test_mandate_rejects_benchmark_outside_universe() -> None:
    with pytest.raises(ValueError, match="benchmark"):
        ResearchMandate(
            mandate_id="MANDATE-BAD",
            universe=("AAA", "BBB"),
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 1),
            benchmark="SPY",
        )
