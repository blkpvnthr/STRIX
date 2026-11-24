"""The persisted research-job record and its state machine.

A :class:`JobRecord` is the single durable unit of work. It is written *before*
execution begins (so a browser close or serverless recycle never loses the
request), updated transactionally as the engine runs, and ends in exactly one
terminal state. The state set is fixed by the deployment spec:

``queued`` → ``running`` → one of ``completed`` / ``partial`` / ``failed`` /
``cancelled`` / ``timed_out``.

``partial`` means the engine produced *independently verified* findings but hit
a budget/time bound before finishing — never that unverified claims were
promoted. ``timed_out`` means the execution lease expired past the absolute
deadline with no recoverable verified result. The distinction is enforced by the
executor, not guessed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class JobState(StrEnum):
    """The lifecycle states of a research job (persisted as the string value)."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


#: States from which no further execution happens.
_TERMINAL = frozenset(
    {
        JobState.COMPLETED,
        JobState.PARTIAL,
        JobState.FAILED,
        JobState.CANCELLED,
        JobState.TIMED_OUT,
    }
)

#: Terminal states that a bounded retry is allowed to re-open.
_RETRIABLE = frozenset({JobState.FAILED, JobState.TIMED_OUT})


def terminal_states() -> frozenset[JobState]:
    """Return the set of terminal job states (no further execution)."""
    return _TERMINAL


def is_terminal(state: JobState) -> bool:
    """True if ``state`` is terminal."""
    return state in _TERMINAL


def is_retriable(state: JobState) -> bool:
    """True if a bounded retry may re-queue a job in ``state``."""
    return state in _RETRIABLE


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class JobRecord:
    """One durable research job.

    Datetimes are timezone-aware UTC. ``progress`` is an append-only event log
    for the UI; ``checkpoint`` holds engine-independent recovery metadata (never
    a promoted-claim cache). ``result`` holds the serialized final answer, usage,
    and claims once a terminal, successful-ish state is reached.
    """

    id: str
    user_id: str
    question: str
    as_of: str | None = None
    status: JobState = JobState.QUEUED

    # Idempotency + bounded retry.
    idempotency_key: str | None = None
    attempt: int = 0
    max_attempts: int = 2

    # Cooperative cancellation.
    cancel_requested: bool = False

    # Execution lease (duplicate-execution protection + stale detection).
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    deadline_at: datetime | None = None

    # Progress + recovery + output.
    progress: list[str] = field(default_factory=list)
    checkpoint: dict[str, Any] | None = None
    run_id: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    cost_usd: str | None = None

    # Timestamps.
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    # -- derived -----------------------------------------------------------

    @property
    def is_terminal(self) -> bool:
        return is_terminal(self.status)

    @property
    def is_retriable(self) -> bool:
        return is_retriable(self.status) and self.attempt < self.max_attempts

    def lease_is_active(self, *, now: datetime | None = None) -> bool:
        """True if a non-expired execution lease is held."""
        if self.lease_expires_at is None:
            return False
        return self.lease_expires_at > (now or _now())

    def deadline_passed(self, *, now: datetime | None = None) -> bool:
        """True if the absolute wall-clock deadline has elapsed."""
        if self.deadline_at is None:
            return False
        return (now or _now()) >= self.deadline_at

    # -- serialization -----------------------------------------------------

    def public(self) -> dict[str, Any]:
        """A client-safe view. Never leaks lease internals or raw tracebacks."""
        return {
            "research_id": self.id,
            "question": self.question,
            "as_of": self.as_of,
            "status": self.status.value,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "cancel_requested": self.cancel_requested,
            "events": list(self.progress),
            "run_id": self.run_id,
            "result": self.result,
            "error": self.error,
            "cost_usd": self.cost_usd,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
        }

    def summary(self) -> dict[str, Any]:
        """A compact history-list view (no full result payload)."""
        return {
            "research_id": self.id,
            "question": self.question,
            "status": self.status.value,
            "run_id": self.run_id,
            "cost_usd": self.cost_usd,
            "created_at": _iso(self.created_at),
            "finished_at": _iso(self.finished_at),
        }

    def copy(self) -> JobRecord:
        """A deep-ish copy safe to hand to callers (lists/dicts duplicated)."""
        return replace(
            self,
            progress=list(self.progress),
            checkpoint=None if self.checkpoint is None else dict(self.checkpoint),
            result=None if self.result is None else dict(self.result),
        )


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()
