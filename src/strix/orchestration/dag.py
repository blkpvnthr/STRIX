"""DAG and task definitions for scheduler-independent orchestration (§7).

A :class:`Dag` is a content-addressed set of :class:`Task` nodes with declared
dependencies. It validates (unique ids, known deps, acyclic) and produces a
deterministic topological order (ties broken by ``task_id``) so a run is fully
reproducible. Task *callables* are supplied to the executor separately — the DAG
itself is pure data.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from strix.canonical import canonical_hash
from strix.errors import CalculationError
from strix.models import StrixModel


class Task(StrixModel):
    """One DAG node: an id, its upstream dependencies, and a retry budget."""

    task_id: str = Field(min_length=1)
    depends_on: tuple[str, ...] = ()
    #: Extra attempts after the first (0 = run once, no retry).
    max_retries: int = Field(default=0, ge=0)


class Dag(StrixModel):
    """An acyclic set of tasks with validated dependencies."""

    tasks: tuple[Task, ...]

    @model_validator(mode="after")
    def _validate(self) -> Dag:
        if not self.tasks:
            raise CalculationError("a DAG must contain at least one task")
        ids = [t.task_id for t in self.tasks]
        if len(set(ids)) != len(ids):
            raise CalculationError("duplicate task_id in DAG")
        known = set(ids)
        for task in self.tasks:
            for dep in task.depends_on:
                if dep not in known:
                    raise CalculationError(
                        f"task {task.task_id!r} depends on unknown task {dep!r}"
                    )
                if dep == task.task_id:
                    raise CalculationError(f"task {task.task_id!r} depends on itself")
        return self

    def _by_id(self) -> dict[str, Task]:
        return {t.task_id: t for t in self.tasks}

    def topological_order(self) -> tuple[str, ...]:
        """A deterministic dependency-respecting order (ties broken by task_id).

        Raises :class:`CalculationError` if the graph contains a cycle.
        """
        by_id = self._by_id()
        remaining = dict(by_id)
        done: list[str] = []
        done_set: set[str] = set()
        while remaining:
            ready = sorted(
                tid
                for tid, task in remaining.items()
                if all(dep in done_set for dep in task.depends_on)
            )
            if not ready:
                raise CalculationError(f"DAG has a cycle among {sorted(remaining)}")
            for tid in ready:
                done.append(tid)
                done_set.add(tid)
                del remaining[tid]
        return tuple(done)

    def dependents_of(self, task_id: str) -> tuple[str, ...]:
        """Tasks that directly depend on ``task_id`` (sorted)."""
        return tuple(
            sorted(t.task_id for t in self.tasks if task_id in t.depends_on)
        )

    def digest(self) -> str:
        """Content address over the canonical task set (order-independent)."""
        payload = [
            {
                "task_id": t.task_id,
                "depends_on": sorted(t.depends_on),
                "max_retries": t.max_retries,
            }
            for t in sorted(self.tasks, key=lambda task: task.task_id)
        ]
        return canonical_hash(payload)
