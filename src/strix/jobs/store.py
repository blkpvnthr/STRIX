"""The backend-agnostic job store contract.

Both the SQLite (:mod:`strix.jobs.local_store`) and PostgreSQL
(:mod:`strix.jobs.supabase_store`) implementations satisfy :class:`JobStore`.
The executor, request handlers, cron sweeper, and any future queue worker depend
only on this interface, so swapping the trigger mechanism (self-invoke → durable
queue) never touches the research engine.

The contract is deliberately small and **atomic where it matters**:

- :meth:`JobStore.create_job` is idempotent on ``(user_id, idempotency_key)``.
- :meth:`JobStore.claim_for_execution` is an atomic compare-and-set that grants
  an execution lease to exactly one caller — this is the duplicate-execution
  guard and the queue seam.
- :meth:`JobStore.find_stale` surfaces jobs whose lease expired (worker died) or
  that were enqueued but never leased — the recovery/sweeper input.
"""

from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from strix.jobs.models import JobRecord, JobState


class LeaseError(RuntimeError):
    """Raised when a lease-protected mutation is attempted without the lease."""


def new_job_id() -> str:
    """A fresh, URL-safe research-job id."""
    return "RQ-" + uuid.uuid4().hex[:16]


def new_worker_id() -> str:
    """A fresh execution-worker id (lease owner)."""
    return "W-" + uuid.uuid4().hex[:12]


def derive_idempotency_key(user_id: str, question: str, as_of: str | None) -> str:
    """Deterministic fallback key when a client omits an Idempotency-Key.

    Collapses identical ``(user, question, as_of)`` submissions so a double-click
    or a retried network request does not spend a second research budget.
    """
    digest = hashlib.sha256()
    digest.update(user_id.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(question.strip().encode("utf-8"))
    digest.update(b"\x00")
    digest.update((as_of or "").encode("utf-8"))
    return "auto-" + digest.hexdigest()[:32]


class JobStore(ABC):
    """Durable persistence + leasing for research jobs."""

    # -- creation / lookup -------------------------------------------------

    @abstractmethod
    def create_job(
        self,
        *,
        user_id: str,
        question: str,
        as_of: str | None,
        idempotency_key: str,
        max_attempts: int,
    ) -> tuple[JobRecord, bool]:
        """Insert a queued job, or return the existing one for a repeat key.

        Returns ``(job, created)`` where ``created`` is ``False`` when an
        existing job matched ``(user_id, idempotency_key)``.
        """

    @abstractmethod
    def get_job(self, job_id: str, *, user_id: str | None = None) -> JobRecord | None:
        """Fetch a job. If ``user_id`` is given, enforce ownership (else None)."""

    @abstractmethod
    def list_jobs(self, *, user_id: str, limit: int = 50) -> list[JobRecord]:
        """List a user's jobs, newest first."""

    # -- cancellation ------------------------------------------------------

    @abstractmethod
    def request_cancel(self, job_id: str, *, user_id: str) -> bool:
        """Flag a job for cooperative cancellation. False if not cancellable."""

    @abstractmethod
    def is_cancel_requested(self, job_id: str) -> bool:
        """Cheap poll used by the engine's ``cancel_check`` hook."""

    # -- lease lifecycle (atomic) -----------------------------------------

    @abstractmethod
    def claim_for_execution(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
        deadline_seconds: int,
    ) -> JobRecord | None:
        """Atomically grant the execution lease for one attempt.

        Succeeds only if the job is ``queued`` (or ``running`` with an expired
        lease — recovery). Transitions it to ``running``, stamps the lease owner,
        lease expiry, absolute deadline, ``started_at``, and increments
        ``attempt``. Returns the leased record, or ``None`` if another worker
        already holds a live lease (duplicate-execution protection).
        """

    @abstractmethod
    def renew_lease(self, job_id: str, *, worker_id: str, lease_seconds: int) -> bool:
        """Extend the lease during a long run (heartbeat). False if lost."""

    # -- progress / checkpoint --------------------------------------------

    @abstractmethod
    def append_progress(self, job_id: str, message: str, *, worker_id: str) -> None:
        """Append one progress event (lease holder only)."""

    @abstractmethod
    def save_checkpoint(
        self, job_id: str, checkpoint: dict[str, Any], *, worker_id: str
    ) -> None:
        """Persist engine-independent recovery metadata (lease holder only)."""

    # -- terminal transitions ---------------------------------------------

    @abstractmethod
    def finish_job(
        self,
        job_id: str,
        *,
        worker_id: str,
        status: JobState,
        run_id: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        cost_usd: str | None = None,
    ) -> JobRecord | None:
        """Atomically move a leased job to a terminal state and clear the lease.

        Only the lease holder may finish the job; a lost lease returns ``None``
        (the caller must discard its work — another worker owns the job now).
        """

    @abstractmethod
    def requeue_for_retry(self, job_id: str, *, worker_id: str, error: str) -> JobRecord | None:
        """Return a failed/timed-out leased job to ``queued`` for a bounded retry.

        No-op returning ``None`` once ``attempt >= max_attempts``; the caller then
        finishes the job in its terminal failure state instead.
        """

    @abstractmethod
    def reopen_for_retry(self, job_id: str, *, user_id: str) -> JobRecord | None:
        """User-initiated retry of a terminally-failed job.

        Allowed only from ``failed`` / ``timed_out`` / ``partial`` and only for
        the owner. Grants exactly one more attempt (``max_attempts = attempt + 1``)
        and returns the job to ``queued`` with no lease. Returns ``None`` if the
        job is not owned by ``user_id`` or is not in a reopenable state.
        """

    @abstractmethod
    def get_job_by_run_id(self, run_id: str, *, user_id: str) -> JobRecord | None:
        """Find a user's completed job by its persisted engine run id."""

    # -- recovery / limits -------------------------------------------------

    @abstractmethod
    def find_stale(self, *, now: datetime, limit: int = 20) -> list[JobRecord]:
        """Jobs needing a sweeper pass: queued-but-never-triggered, or running
        with an expired lease. Ordered oldest first."""

    @abstractmethod
    def count_active(self, *, user_id: str) -> int:
        """Count a user's non-terminal jobs (queued + running) for concurrency
        limiting."""

    @abstractmethod
    def usage_since(self, *, user_id: str | None, since: datetime) -> tuple[int, float]:
        """Return ``(job_count, total_cost_usd)`` created since ``since``.

        ``user_id=None`` aggregates globally (for the platform-wide spend cap).
        """
