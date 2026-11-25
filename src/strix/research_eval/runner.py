"""Offline experiment run harness for the research benchmark (R1 §29, SBIR §15.1).

The harness runs each benchmark question through one or more *arms* — a
standalone LLM, a RAG pipeline, or the full STRIX pipeline — all hidden behind
the :class:`Baseline` protocol, scores each response against the question's
ground truth (:func:`strix.research_eval.scoring.score_response`), and records a
:class:`RunRecord` per (question, arm). It then :func:`aggregate`\\ s per-arm,
per-metric micro-averages.

Two concrete baselines bracket the trust boundary:

- :class:`FixtureBaseline` — a **deterministic, offline** arm that replays a
  pre-provided response per ``question_id``. It proves the harness end to end
  without any model call, and is what the tests and reproducibility checks use.
- :class:`LiveModelBaseline` — the **documented live-validation stub**. Its
  :meth:`~LiveModelBaseline.answer` raises :class:`RunnerError` demanding budget
  and model access; it makes **no network call**. The hypotheses H1-H12 remain
  ``NOT_EVALUATED`` until a real run is performed under budget and credentials.

Design guarantees:

- **Determinism** — questions are iterated in inventory order and arms in
  ``config.arms`` order; every reported number is an exact :class:`~decimal.Decimal`.
- **Budget safety** — the per-question cost is checked *before* the arm is
  invoked, so a run raises :class:`RunnerError` the moment the next question
  would exceed ``config.max_cost`` — it never overspends.
- **Checkpoint / resume** — an optional ``completed`` set of ``(question_id,
  arm)`` pairs is skipped, so an interrupted run resumes without recomputation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Protocol, runtime_checkable

from pydantic import Field

from strix.answering.models import VerifiedResearchResponse
from strix.errors import StrixError
from strix.models import DecimalValue, StrixModel
from strix.research_eval.dataset import BenchmarkQuestion, QuestionInventory
from strix.research_eval.scoring import MetricResult, score_response

__all__ = [
    "AggregatedMetric",
    "Baseline",
    "ExperimentConfig",
    "FixtureBaseline",
    "LiveModelBaseline",
    "RunRecord",
    "RunnerError",
    "aggregate",
    "run_experiment",
]

#: Quantum for reported aggregate means — keeps division deterministic.
_QUANTUM = Decimal("0.0001")


class RunnerError(StrixError):
    """An experiment run could not proceed (budget, config, or missing arm)."""


# --------------------------------------------------------------------------
# Baseline protocol + concrete arms
# --------------------------------------------------------------------------


@runtime_checkable
class Baseline(Protocol):
    """One experiment arm: names itself and answers a benchmark question.

    Implementations may be a standalone LLM, a RAG pipeline, or the full STRIX
    pipeline; the harness treats them all uniformly through this protocol.
    """

    name: str

    def answer(self, question: BenchmarkQuestion) -> VerifiedResearchResponse:
        """Return the arm's response to *question* (no scoring here)."""
        ...


class FixtureBaseline:
    """A deterministic offline arm that replays a pre-provided response.

    It holds a ``question_id -> VerifiedResearchResponse`` table and returns the
    matching response, proving the harness without any model call. Asking for a
    question absent from the table raises :class:`RunnerError` (fail-closed).
    """

    def __init__(
        self, *, name: str, responses: Mapping[str, VerifiedResearchResponse]
    ) -> None:
        self.name = name
        self._responses: dict[str, VerifiedResearchResponse] = dict(responses)

    def answer(self, question: BenchmarkQuestion) -> VerifiedResearchResponse:
        """Return the pre-provided response for *question* or fail closed."""
        try:
            return self._responses[question.question_id]
        except KeyError as exc:
            raise RunnerError(
                f"FixtureBaseline {self.name!r} has no response for "
                f"question {question.question_id!r}"
            ) from exc


class LiveModelBaseline:
    """The documented live-validation stub — raises instead of calling a model.

    This records the exact step required to run a *real* arm: provision budget
    and model access. :meth:`answer` makes **no network call**; it always raises
    :class:`RunnerError` so a live benchmark cannot be run accidentally or faked.
    """

    def __init__(self, *, name: str) -> None:
        self.name = name

    def answer(self, question: BenchmarkQuestion) -> VerifiedResearchResponse:
        """Always raise: a live arm needs budget and credentials (no network)."""
        raise RunnerError(
            "live model + budget required; set STRIX_BENCHMARK_BUDGET and "
            "provide model access "
            f"(arm {self.name!r}, question {question.question_id!r})"
        )


# --------------------------------------------------------------------------
# Config + records
# --------------------------------------------------------------------------


class ExperimentConfig(StrixModel):
    """Reproducibility-complete description of one experiment run."""

    experiment_id: str = Field(min_length=1)
    #: The exact benchmark inventory version this run must be scored against.
    inventory_version: str = Field(min_length=1)
    seed: int
    #: Hard cap on total accumulated cost; the run never exceeds it.
    max_cost: DecimalValue = Field(ge=Decimal(0))
    arms: tuple[str, ...] = Field(min_length=1)


class RunRecord(StrixModel):
    """The scored outcome of running one question through one arm."""

    question_id: str
    arm: str
    scores: tuple[MetricResult, ...]
    cost: DecimalValue = Decimal(0)


class AggregatedMetric(StrixModel):
    """A per-arm, per-metric micro-average over a set of run records."""

    arm: str
    metric_name: str
    #: Micro-averaged (equal-weighted) mean of the metric value across records.
    mean: DecimalValue = Field(ge=Decimal(0), le=Decimal(1))
    #: Number of records contributing to the mean.
    n: int = Field(ge=1)


# --------------------------------------------------------------------------
# Run + aggregate
# --------------------------------------------------------------------------


def run_experiment(
    config: ExperimentConfig,
    inventory: QuestionInventory,
    baselines: Mapping[str, Baseline],
    *,
    cost_per_question: Mapping[str, Decimal] | None = None,
    completed: frozenset[tuple[str, str]] | set[tuple[str, str]] | None = None,
) -> tuple[RunRecord, ...]:
    """Run every (question, arm) pair and return the scored records.

    Pairs are produced in deterministic order: each question in *inventory*
    order, and within it each arm in ``config.arms`` order. For every arm the
    per-question cost (``cost_per_question[arm]``, default ``0``) is charged; the
    check happens *before* the arm is invoked, so the run raises
    :class:`RunnerError` the moment the next pair would push accumulated cost
    above ``config.max_cost`` — it never overspends.

    *completed* is an optional set of ``(question_id, arm)`` pairs already
    persisted by an earlier run; those pairs are skipped (checkpoint/resume) and
    their cost is not re-charged.

    Raises :class:`RunnerError` if the inventory version does not match the
    config, if ``config.arms`` references an unknown baseline, or on budget
    overrun.
    """
    if config.inventory_version != inventory.version:
        raise RunnerError(
            f"inventory version mismatch: config expects "
            f"{config.inventory_version!r} but inventory is {inventory.version!r}"
        )

    missing = [arm for arm in config.arms if arm not in baselines]
    if missing:
        raise RunnerError(f"no baseline registered for arm(s): {sorted(missing)}")

    costs: Mapping[str, Decimal] = cost_per_question or {}
    done: frozenset[tuple[str, str]] = frozenset(completed or ())

    records: list[RunRecord] = []
    accumulated = Decimal(0)
    for question in inventory.questions:
        for arm in config.arms:
            if (question.question_id, arm) in done:
                continue
            unit_cost = costs.get(arm, Decimal(0))
            # Enforce the budget BEFORE invoking the arm so we never overspend.
            if accumulated + unit_cost > config.max_cost:
                raise RunnerError(
                    f"cost budget exceeded: running {arm!r} on "
                    f"{question.question_id!r} would bring cost to "
                    f"{accumulated + unit_cost} > max_cost {config.max_cost}"
                )
            baseline = baselines[arm]
            response = baseline.answer(question)
            scores = score_response(response, question.ground_truth)
            accumulated += unit_cost
            records.append(
                RunRecord(
                    question_id=question.question_id,
                    arm=arm,
                    scores=scores,
                    cost=unit_cost,
                )
            )
    return tuple(records)


def aggregate(records: tuple[RunRecord, ...]) -> tuple[AggregatedMetric, ...]:
    """Micro-average each metric per arm across *records*.

    For every (arm, metric_name) pair the value is the equal-weighted mean of
    the metric across all records that reported it — the standard micro-average,
    computed in exact :class:`~decimal.Decimal` and quantized deterministically.
    The result is sorted by ``(arm, metric_name)``.
    """
    sums: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal(0))
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for record in records:
        for metric in record.scores:
            key = (record.arm, metric.name)
            sums[key] += metric.value
            counts[key] += 1

    out: list[AggregatedMetric] = []
    for key in sorted(sums):
        arm, metric_name = key
        n = counts[key]
        mean = (sums[key] / Decimal(n)).quantize(
            _QUANTUM, rounding=ROUND_HALF_EVEN
        )
        out.append(
            AggregatedMetric(arm=arm, metric_name=metric_name, mean=mean, n=n)
        )
    return tuple(out)
