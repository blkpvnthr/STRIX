"""Tests for scheduler-independent DAG definitions (Wave 11 / §7)."""

from __future__ import annotations

import pytest

from strix.errors import CalculationError
from strix.orchestration.dag import Dag, Task


def _dag() -> Dag:
    return Dag(
        tasks=(
            Task(task_id="ingest"),
            Task(task_id="normalize", depends_on=("ingest",)),
            Task(task_id="warehouse", depends_on=("normalize",)),
            Task(task_id="index", depends_on=("normalize",)),
        )
    )


def test_topological_order_respects_dependencies() -> None:
    order = _dag().topological_order()
    assert order.index("ingest") < order.index("normalize")
    assert order.index("normalize") < order.index("warehouse")
    assert order.index("normalize") < order.index("index")


def test_topological_order_is_deterministic() -> None:
    # Ties are broken by task_id so the order is reproducible.
    assert _dag().topological_order() == _dag().topological_order()
    order = _dag().topological_order()
    assert order == ("ingest", "normalize", "index", "warehouse")


def test_cycle_is_rejected() -> None:
    with pytest.raises(CalculationError):
        Dag(tasks=(
            Task(task_id="a", depends_on=("b",)),
            Task(task_id="b", depends_on=("a",)),
        )).topological_order()


def test_unknown_dependency_is_rejected() -> None:
    with pytest.raises(CalculationError):
        Dag(tasks=(Task(task_id="a", depends_on=("ghost",)),))


def test_duplicate_task_id_is_rejected() -> None:
    with pytest.raises(CalculationError):
        Dag(tasks=(Task(task_id="a"), Task(task_id="a")))


def test_empty_dag_is_rejected() -> None:
    with pytest.raises(CalculationError):
        Dag(tasks=())


def test_dag_digest_is_content_addressed() -> None:
    assert _dag().digest() == _dag().digest()
    other = Dag(tasks=(Task(task_id="solo"),))
    assert _dag().digest() != other.digest()


def test_dependents_of() -> None:
    dag = _dag()
    assert set(dag.dependents_of("normalize")) == {"warehouse", "index"}
    assert dag.dependents_of("warehouse") == ()
