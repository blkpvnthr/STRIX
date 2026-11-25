"""Tests for the scheduler-independent DAG executor (Wave 11 / §7).

Runs a task DAG in-process without Airflow: topological order, dependency-aware
skipping on upstream failure, bounded retries, and checkpoint/resume.
"""

from __future__ import annotations

import pytest

from strix.errors import CalculationError
from strix.orchestration.dag import Dag, Task
from strix.orchestration.executor import TaskStatus, run_dag


def _dag() -> Dag:
    return Dag(
        tasks=(
            Task(task_id="a"),
            Task(task_id="b", depends_on=("a",)),
            Task(task_id="c", depends_on=("b",)),
        )
    )


def test_all_tasks_run_in_order_on_success() -> None:
    order: list[str] = []
    fns = {t: (lambda t=t: order.append(t)) for t in ("a", "b", "c")}
    report = run_dag(_dag(), fns)
    assert order == ["a", "b", "c"]
    assert report.all_succeeded
    assert all(r.status is TaskStatus.SUCCEEDED for r in report.results)


def test_failure_skips_downstream_dependents() -> None:
    def boom() -> None:
        raise RuntimeError("fail b")

    ran_c = []
    fns = {"a": lambda: None, "b": boom, "c": lambda: ran_c.append("c")}
    report = run_dag(_dag(), fns)
    assert report.all_succeeded is False
    status = {r.task_id: r.status for r in report.results}
    assert status["a"] is TaskStatus.SUCCEEDED
    assert status["b"] is TaskStatus.FAILED
    assert status["c"] is TaskStatus.SKIPPED
    assert ran_c == []  # c never ran


def test_retries_allow_a_flaky_task_to_succeed() -> None:
    attempts = {"n": 0}

    def flaky() -> None:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")

    dag = Dag(tasks=(Task(task_id="x", max_retries=2),))
    report = run_dag(dag, {"x": flaky})
    assert report.all_succeeded
    assert attempts["n"] == 3
    assert report.results[0].attempts == 3


def test_retries_exhausted_marks_failed() -> None:
    def always() -> None:
        raise RuntimeError("nope")

    dag = Dag(tasks=(Task(task_id="x", max_retries=1),))
    report = run_dag(dag, {"x": always})
    assert report.all_succeeded is False
    assert report.results[0].status is TaskStatus.FAILED
    assert report.results[0].attempts == 2  # initial + 1 retry


def test_checkpoint_resume_skips_completed_tasks() -> None:
    order: list[str] = []
    fns = {t: (lambda t=t: order.append(t)) for t in ("a", "b", "c")}
    report = run_dag(_dag(), fns, already_completed=frozenset({"a", "b"}))
    assert order == ["c"]  # only the remaining task runs
    status = {r.task_id: r.status for r in report.results}
    assert status["a"] is TaskStatus.SUCCEEDED  # reported as already-done
    assert status["c"] is TaskStatus.SUCCEEDED
    assert report.all_succeeded


def test_missing_task_fn_is_an_error() -> None:
    with pytest.raises(CalculationError):
        run_dag(_dag(), {"a": lambda: None})  # missing b, c


def test_report_lists_completed_ids_for_persistence() -> None:
    fns = {t: (lambda: None) for t in ("a", "b", "c")}
    report = run_dag(_dag(), fns)
    assert set(report.completed_ids) == {"a", "b", "c"}
