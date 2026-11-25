"""In-process, scheduler-independent DAG executor (§7).

Runs a :class:`Dag` to completion without Airflow: tasks execute in topological
order; a task whose upstream failed (or was skipped) is SKIPPED rather than run;
failing tasks retry up to their budget; and ``already_completed`` lets a run resume
from a checkpoint. The report lists every task's terminal status and the set of
completed ids a caller can persist for the next resume.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum

from strix.errors import CalculationError
from strix.models import StrixModel
from strix.orchestration.dag import Dag

#: A unit of work for one task: performs its side effects, raising on failure.
TaskFn = Callable[[], object]


class TaskStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskResult(StrixModel):
    """The terminal outcome of one task in a run."""

    task_id: str
    status: TaskStatus
    attempts: int
    error: str | None = None


class RunReport(StrixModel):
    """The outcome of running a whole DAG."""

    dag_digest: str
    results: tuple[TaskResult, ...]

    @property
    def all_succeeded(self) -> bool:
        return all(r.status is TaskStatus.SUCCEEDED for r in self.results)

    @property
    def completed_ids(self) -> tuple[str, ...]:
        return tuple(r.task_id for r in self.results if r.status is TaskStatus.SUCCEEDED)


def run_dag(
    dag: Dag,
    task_fns: Mapping[str, TaskFn],
    *,
    already_completed: frozenset[str] = frozenset(),
) -> RunReport:
    """Execute ``dag`` deterministically and return a :class:`RunReport`.

    Every task not in ``already_completed`` must have a callable in ``task_fns``;
    a missing one is a :class:`CalculationError` (fail-closed, before any task runs).
    """
    order = dag.topological_order()
    by_id = {t.task_id: t for t in dag.tasks}

    missing = [tid for tid in order if tid not in already_completed and tid not in task_fns]
    if missing:
        raise CalculationError(f"no task function supplied for: {sorted(missing)}")

    succeeded: set[str] = set(already_completed)
    results: list[TaskResult] = []

    for tid in order:
        task = by_id[tid]
        if tid in already_completed:
            results.append(TaskResult(task_id=tid, status=TaskStatus.SUCCEEDED, attempts=0))
            continue
        if any(dep not in succeeded for dep in task.depends_on):
            results.append(TaskResult(task_id=tid, status=TaskStatus.SKIPPED, attempts=0))
            continue

        fn = task_fns[tid]
        attempts = 0
        last_error: str | None = None
        for _ in range(task.max_retries + 1):
            attempts += 1
            try:
                fn()
            except Exception as exc:
                # A task failure is recorded (and may retry), never propagated.
                last_error = f"{type(exc).__name__}: {exc}"
                continue
            last_error = None
            break
        if last_error is None:
            succeeded.add(tid)
            results.append(TaskResult(task_id=tid, status=TaskStatus.SUCCEEDED, attempts=attempts))
        else:
            results.append(
                TaskResult(
                    task_id=tid, status=TaskStatus.FAILED, attempts=attempts, error=last_error
                )
            )

    return RunReport(dag_digest=dag.digest(), results=tuple(results))
