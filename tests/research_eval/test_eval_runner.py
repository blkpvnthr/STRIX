"""Tests for the offline experiment run harness (R1 §29, SBIR §15.1).

These exercise the deterministic *offline* path end to end (the
:class:`~strix.research_eval.runner.FixtureBaseline`), the budget enforcement,
checkpoint/resume, micro-averaging aggregation, determinism, and the documented
live-model stub — without any network call or fabricated benchmark number.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from strix.answering.models import (
    AnswerCoverage,
    AnswerStatus,
    AnswerValidationResult,
    VerifiedResearchResponse,
)
from strix.errors import StrixError
from strix.research_eval.dataset import (
    SAMPLE_INVENTORY,
    BenchmarkQuestion,
    GroundTruth,
)
from strix.research_eval.runner import (
    Baseline,
    ExperimentConfig,
    FixtureBaseline,
    LiveModelBaseline,
    RunnerError,
    RunRecord,
    aggregate,
    run_experiment,
)
from strix.research_eval.scoring import MetricResult, score_response

# --------------------------------------------------------------------------
# Helpers — build minimal, valid VerifiedResearchResponse fixtures offline.
# --------------------------------------------------------------------------


def _response(
    question: BenchmarkQuestion,
    *,
    answer_text: str,
    status: AnswerStatus,
) -> VerifiedResearchResponse:
    """A minimal valid response (no assertions, no certificates needed)."""
    return VerifiedResearchResponse(
        question=question.question,
        answer_text=answer_text,
        sections=(),
        factual_assertions=(),
        analytical_inferences=(),
        hypotheses=(),
        citations=(),
        coverage=AnswerCoverage(
            score=Decimal("1"),
            per_requirement=(),
            status=status,
        ),
        answer_status=status,
        limitations=(),
        unresolved_requirements=(),
        validation=AnswerValidationResult(
            ok=True, unsupported_assertions=(), issues=()
        ),
    )


def _responses_for_inventory() -> dict[str, VerifiedResearchResponse]:
    """One plausible response per SAMPLE_INVENTORY question keyed by id."""
    out: dict[str, VerifiedResearchResponse] = {}
    for q in SAMPLE_INVENTORY.questions:
        gt: GroundTruth = q.ground_truth
        if gt.must_abstain:
            out[q.question_id] = _response(
                q,
                answer_text=(
                    "I decline to answer: the premise is unreliable or the "
                    "question is beyond the available evidence."
                ),
                status=AnswerStatus.UNANSWERABLE,
            )
        else:
            # Echo the requirement/claim text so the lexical scorer matches.
            body = " ".join(gt.expected_answer_requirements) + " " + " ".join(
                gt.expected_claims
            )
            out[q.question_id] = _response(
                q,
                answer_text=body or "an answer",
                status=AnswerStatus.COMPLETE_ANSWER,
            )
    return out


def _config(arms: tuple[str, ...], max_cost: Decimal) -> ExperimentConfig:
    return ExperimentConfig(
        experiment_id="EXP-offline-0",
        inventory_version=SAMPLE_INVENTORY.version,
        seed=7,
        max_cost=max_cost,
        arms=arms,
    )


# --------------------------------------------------------------------------
# Baseline protocol conformance
# --------------------------------------------------------------------------


def test_fixturebaseline_is_a_baseline() -> None:
    fb = FixtureBaseline(name="fixture", responses={})
    assert isinstance(fb, Baseline)


def test_fixturebaseline_answers_from_table() -> None:
    responses = _responses_for_inventory()
    fb = FixtureBaseline(name="fixture", responses=responses)
    q = SAMPLE_INVENTORY.questions[0]
    assert fb.answer(q) is responses[q.question_id]


def test_fixturebaseline_missing_response_raises() -> None:
    fb = FixtureBaseline(name="fixture", responses={})
    with pytest.raises(RunnerError):
        fb.answer(SAMPLE_INVENTORY.questions[0])


# --------------------------------------------------------------------------
# run_experiment — offline path
# --------------------------------------------------------------------------


def test_run_experiment_one_record_per_question_arm() -> None:
    responses = _responses_for_inventory()
    arms = ("fixtureA", "fixtureB")
    baselines = {
        "fixtureA": FixtureBaseline(name="fixtureA", responses=responses),
        "fixtureB": FixtureBaseline(name="fixtureB", responses=responses),
    }
    config = _config(arms, max_cost=Decimal("0"))
    records = run_experiment(config, SAMPLE_INVENTORY, baselines)

    n_q = len(SAMPLE_INVENTORY.questions)
    assert len(records) == n_q * len(arms)
    # every record carries at least one scored metric
    assert all(len(r.scores) >= 1 for r in records)
    # exactly one record per (question_id, arm)
    pairs = {(r.question_id, r.arm) for r in records}
    assert len(pairs) == n_q * len(arms)


def test_run_experiment_deterministic_ordering_and_values() -> None:
    responses = _responses_for_inventory()
    arms = ("fixtureA", "fixtureB")
    baselines: dict[str, Baseline] = {
        "fixtureA": FixtureBaseline(name="fixtureA", responses=responses),
        "fixtureB": FixtureBaseline(name="fixtureB", responses=responses),
    }
    config = _config(arms, max_cost=Decimal("0"))
    first = run_experiment(config, SAMPLE_INVENTORY, baselines)
    second = run_experiment(config, SAMPLE_INVENTORY, baselines)
    assert first == second
    # ordering is (question order in inventory) x (arm order in config)
    expected_order = [
        (q.question_id, arm)
        for q in SAMPLE_INVENTORY.questions
        for arm in arms
    ]
    assert [(r.question_id, r.arm) for r in first] == expected_order


def test_run_experiment_unknown_arm_raises() -> None:
    config = _config(("ghost",), max_cost=Decimal("0"))
    with pytest.raises(RunnerError):
        run_experiment(config, SAMPLE_INVENTORY, {})


def test_run_experiment_inventory_version_mismatch_raises() -> None:
    responses = _responses_for_inventory()
    baselines = {"a": FixtureBaseline(name="a", responses=responses)}
    config = ExperimentConfig(
        experiment_id="EXP-x",
        inventory_version="not-the-sample",
        seed=1,
        max_cost=Decimal("0"),
        arms=("a",),
    )
    with pytest.raises(RunnerError):
        run_experiment(config, SAMPLE_INVENTORY, baselines)


# --------------------------------------------------------------------------
# Budget enforcement
# --------------------------------------------------------------------------


def test_run_experiment_budget_overrun_raises_before_exceeding() -> None:
    responses = _responses_for_inventory()
    baselines = {"a": FixtureBaseline(name="a", responses=responses)}
    # one unit per question, budget only covers two questions
    config = _config(("a",), max_cost=Decimal("2"))
    with pytest.raises(RunnerError):
        run_experiment(
            config,
            SAMPLE_INVENTORY,
            baselines,
            cost_per_question={"a": Decimal("1")},
        )


def test_run_experiment_within_budget_accumulates_cost() -> None:
    responses = _responses_for_inventory()
    baselines = {"a": FixtureBaseline(name="a", responses=responses)}
    n_q = len(SAMPLE_INVENTORY.questions)
    config = _config(("a",), max_cost=Decimal(n_q))
    records = run_experiment(
        config,
        SAMPLE_INVENTORY,
        baselines,
        cost_per_question={"a": Decimal("1")},
    )
    assert sum((r.cost for r in records), Decimal("0")) == Decimal(n_q)
    assert all(r.cost == Decimal("1") for r in records)


# --------------------------------------------------------------------------
# Checkpoint / resume
# --------------------------------------------------------------------------


def test_run_experiment_resume_skips_completed_pairs() -> None:
    responses = _responses_for_inventory()
    baselines = {"a": FixtureBaseline(name="a", responses=responses)}
    config = _config(("a",), max_cost=Decimal("0"))
    first_qid = SAMPLE_INVENTORY.questions[0].question_id
    completed = {(first_qid, "a")}
    records = run_experiment(
        config, SAMPLE_INVENTORY, baselines, completed=completed
    )
    pairs = {(r.question_id, r.arm) for r in records}
    assert (first_qid, "a") not in pairs
    assert len(records) == len(SAMPLE_INVENTORY.questions) - 1


# --------------------------------------------------------------------------
# Live model stub — documented, no network
# --------------------------------------------------------------------------


def test_live_model_baseline_raises_documented_error() -> None:
    live = LiveModelBaseline(name="gpt-live")
    q = SAMPLE_INVENTORY.questions[0]
    with pytest.raises(RunnerError) as exc:
        live.answer(q)
    msg = str(exc.value)
    assert "budget" in msg.lower()
    assert "STRIX_BENCHMARK_BUDGET" in msg
    # It is a StrixError subclass.
    assert isinstance(exc.value, StrixError)


# --------------------------------------------------------------------------
# Aggregation — micro-average
# --------------------------------------------------------------------------


def test_aggregate_micro_averages_per_arm_and_metric() -> None:
    records = (
        RunRecord(
            question_id="BQ-000000000001",
            arm="a",
            scores=(
                MetricResult.from_counts("m", 1, 1),
                MetricResult.from_counts("n", 0, 1),
            ),
        ),
        RunRecord(
            question_id="BQ-000000000002",
            arm="a",
            scores=(
                MetricResult.from_counts("m", 0, 1),
                MetricResult.from_counts("n", 1, 1),
            ),
        ),
        RunRecord(
            question_id="BQ-000000000001",
            arm="b",
            scores=(MetricResult.from_counts("m", 1, 2),),
        ),
    )
    agg = aggregate(records)
    table = {(a.arm, a.metric_name): a for a in agg}
    assert table[("a", "m")].mean == Decimal("0.5")
    assert table[("a", "m")].n == 2
    assert table[("a", "n")].mean == Decimal("0.5")
    assert table[("b", "m")].mean == Decimal("0.5")
    assert table[("b", "m")].n == 1
    # deterministic sorted ordering by (arm, metric_name)
    assert [(a.arm, a.metric_name) for a in agg] == sorted(
        (a.arm, a.metric_name) for a in agg
    )


def test_aggregate_empty_is_empty() -> None:
    assert aggregate(()) == ()


# --------------------------------------------------------------------------
# score_response sanity (the offline scorer the runner invokes)
# --------------------------------------------------------------------------


def test_score_response_returns_bounded_metrics() -> None:
    responses = _responses_for_inventory()
    q = SAMPLE_INVENTORY.questions[0]
    scores = score_response(responses[q.question_id], q.ground_truth)
    assert len(scores) >= 1
    for m in scores:
        assert Decimal("0") <= m.value <= Decimal("1")
