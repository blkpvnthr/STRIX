"""SQLite-backed :class:`JobStore` for offline development, the CLI, and tests.

A single file database with one ``jobs`` table. All mutations run under a process
lock and use ``BEGIN IMMEDIATE`` so the lease compare-and-set is genuinely atomic
even under concurrent worker threads — the same guarantee the PostgreSQL store
gets from ``UPDATE ... RETURNING``. Timestamps are stored as timezone-normalized
ISO-8601 strings (``...+00:00``), which sort lexicographically for the lease and
deadline comparisons.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from strix.jobs.models import JobRecord, JobState
from strix.jobs.store import JobStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id                TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL,
    question          TEXT NOT NULL,
    as_of             TEXT,
    status            TEXT NOT NULL,
    idempotency_key   TEXT NOT NULL,
    attempt           INTEGER NOT NULL DEFAULT 0,
    max_attempts      INTEGER NOT NULL DEFAULT 2,
    cancel_requested  INTEGER NOT NULL DEFAULT 0,
    lease_owner       TEXT,
    lease_expires_at  TEXT,
    deadline_at       TEXT,
    progress          TEXT NOT NULL DEFAULT '[]',
    checkpoint        TEXT,
    run_id            TEXT,
    result            TEXT,
    error             TEXT,
    cost_usd          TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    started_at        TEXT,
    finished_at       TEXT,
    UNIQUE (user_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_jobs_user_created ON jobs (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
"""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def _parse(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


class LocalJobStore(JobStore):
    """A durable job store backed by one SQLite file."""

    def __init__(self, path: str | Path = "research_runs/jobs.db") -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self._path, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- creation / lookup -------------------------------------------------

    def create_job(
        self,
        *,
        user_id: str,
        question: str,
        as_of: str | None,
        idempotency_key: str,
        max_attempts: int,
    ) -> tuple[JobRecord, bool]:
        from strix.jobs.store import new_job_id

        now = _now()
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            existing = self._conn.execute(
                "SELECT * FROM jobs WHERE user_id = ? AND idempotency_key = ?",
                (user_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                return self._row_to_record(existing), False
            job_id = new_job_id()
            self._conn.execute(
                """
                INSERT INTO jobs (
                    id, user_id, question, as_of, status, idempotency_key,
                    attempt, max_attempts, cancel_requested, progress,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, 0, '[]', ?, ?)
                """,
                (
                    job_id,
                    user_id,
                    question,
                    as_of,
                    JobState.QUEUED.value,
                    idempotency_key,
                    max_attempts,
                    _iso(now),
                    _iso(now),
                ),
            )
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_record(row), True

    def get_job(self, job_id: str, *, user_id: str | None = None) -> JobRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        record = self._row_to_record(row)
        if user_id is not None and record.user_id != user_id:
            return None
        return record

    def list_jobs(self, *, user_id: str, limit: int = 50) -> list[JobRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    # -- cancellation ------------------------------------------------------

    def request_cancel(self, job_id: str, *, user_id: str) -> bool:
        now = _now()
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            cur = self._conn.execute(
                """
                UPDATE jobs
                   SET cancel_requested = 1,
                       status = CASE WHEN status = ? THEN ? ELSE status END,
                       finished_at = CASE WHEN status = ? THEN ? ELSE finished_at END,
                       updated_at = ?
                 WHERE id = ? AND user_id = ? AND status IN (?, ?)
                """,
                (
                    JobState.QUEUED.value,
                    JobState.CANCELLED.value,
                    JobState.QUEUED.value,
                    _iso(now),
                    _iso(now),
                    job_id,
                    user_id,
                    JobState.QUEUED.value,
                    JobState.RUNNING.value,
                ),
            )
            return cur.rowcount > 0

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return bool(row and row["cancel_requested"])

    # -- lease lifecycle (atomic) -----------------------------------------

    def claim_for_execution(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
        deadline_seconds: int,
    ) -> JobRecord | None:
        now = _now()
        lease = _iso(now + timedelta(seconds=lease_seconds))
        deadline = _iso(now + timedelta(seconds=deadline_seconds))
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            cur = self._conn.execute(
                """
                UPDATE jobs
                   SET status = ?,
                       lease_owner = ?,
                       lease_expires_at = ?,
                       deadline_at = ?,
                       started_at = COALESCE(started_at, ?),
                       attempt = attempt + 1,
                       updated_at = ?
                 WHERE id = ?
                   AND cancel_requested = 0
                   AND (
                        status = ?
                        OR (status = ? AND (lease_expires_at IS NULL OR lease_expires_at < ?))
                   )
                """,
                (
                    JobState.RUNNING.value,
                    worker_id,
                    lease,
                    deadline,
                    _iso(now),
                    _iso(now),
                    job_id,
                    JobState.QUEUED.value,
                    JobState.RUNNING.value,
                    _iso(now),
                ),
            )
            if cur.rowcount != 1:
                return None
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_record(row)

    def renew_lease(self, job_id: str, *, worker_id: str, lease_seconds: int) -> bool:
        now = _now()
        lease = _iso(now + timedelta(seconds=lease_seconds))
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            cur = self._conn.execute(
                """
                UPDATE jobs SET lease_expires_at = ?, updated_at = ?
                 WHERE id = ? AND lease_owner = ? AND status = ?
                """,
                (lease, _iso(now), job_id, worker_id, JobState.RUNNING.value),
            )
            return cur.rowcount == 1

    # -- progress / checkpoint --------------------------------------------

    def append_progress(self, job_id: str, message: str, *, worker_id: str) -> None:
        now = _now()
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT progress, lease_owner FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None or row["lease_owner"] != worker_id:
                return
            events = json.loads(row["progress"] or "[]")
            events.append(message)
            self._conn.execute(
                "UPDATE jobs SET progress = ?, updated_at = ? WHERE id = ? AND lease_owner = ?",
                (json.dumps(events), _iso(now), job_id, worker_id),
            )

    def save_checkpoint(
        self, job_id: str, checkpoint: dict[str, Any], *, worker_id: str
    ) -> None:
        now = _now()
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                "UPDATE jobs SET checkpoint = ?, updated_at = ? WHERE id = ? AND lease_owner = ?",
                (json.dumps(checkpoint), _iso(now), job_id, worker_id),
            )

    # -- terminal transitions ---------------------------------------------

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
        now = _now()
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            cur = self._conn.execute(
                """
                UPDATE jobs
                   SET status = ?, run_id = ?, result = ?, error = ?, cost_usd = ?,
                       lease_owner = NULL, lease_expires_at = NULL,
                       finished_at = ?, updated_at = ?
                 WHERE id = ? AND lease_owner = ?
                """,
                (
                    status.value,
                    run_id,
                    None if result is None else json.dumps(result),
                    error,
                    cost_usd,
                    _iso(now),
                    _iso(now),
                    job_id,
                    worker_id,
                ),
            )
            if cur.rowcount != 1:
                return None
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_record(row)

    def requeue_for_retry(
        self, job_id: str, *, worker_id: str, error: str
    ) -> JobRecord | None:
        now = _now()
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT attempt, max_attempts, lease_owner FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None or row["lease_owner"] != worker_id:
                return None
            if row["attempt"] >= row["max_attempts"]:
                return None
            self._conn.execute(
                """
                UPDATE jobs
                   SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                       deadline_at = NULL, error = ?, updated_at = ?
                 WHERE id = ? AND lease_owner = ?
                """,
                (JobState.QUEUED.value, error, _iso(now), job_id, worker_id),
            )
            result = self._conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_record(result)

    def reopen_for_retry(self, job_id: str, *, user_id: str) -> JobRecord | None:
        now = _now()
        reopenable = (
            JobState.FAILED.value,
            JobState.TIMED_OUT.value,
            JobState.PARTIAL.value,
        )
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT status, attempt, user_id FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None or row["user_id"] != user_id or row["status"] not in reopenable:
                return None
            self._conn.execute(
                """
                UPDATE jobs
                   SET status = ?, max_attempts = attempt + 1, cancel_requested = 0,
                       lease_owner = NULL, lease_expires_at = NULL, deadline_at = NULL,
                       error = NULL, finished_at = NULL, updated_at = ?
                 WHERE id = ? AND user_id = ?
                """,
                (JobState.QUEUED.value, _iso(now), job_id, user_id),
            )
            result = self._conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_record(result)

    def get_job_by_run_id(self, run_id: str, *, user_id: str) -> JobRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE run_id = ? AND user_id = ? LIMIT 1",
                (run_id, user_id),
            ).fetchone()
        return None if row is None else self._row_to_record(row)

    # -- recovery / limits -------------------------------------------------

    def find_stale(self, *, now: datetime, limit: int = 20) -> list[JobRecord]:
        now_iso = _iso(now)
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM jobs
                 WHERE cancel_requested = 0
                   AND (
                        status = ?
                        OR (status = ? AND (lease_expires_at IS NULL OR lease_expires_at < ?))
                   )
                 ORDER BY created_at ASC
                 LIMIT ?
                """,
                (JobState.QUEUED.value, JobState.RUNNING.value, now_iso, limit),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def count_active(self, *, user_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE user_id = ? AND status IN (?, ?)",
                (user_id, JobState.QUEUED.value, JobState.RUNNING.value),
            ).fetchone()
        return int(row["n"])

    def usage_since(
        self, *, user_id: str | None, since: datetime
    ) -> tuple[int, float]:
        since_iso = _iso(since)
        with self._lock:
            if user_id is None:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n, COALESCE(SUM(CAST(cost_usd AS REAL)), 0) AS c "
                    "FROM jobs WHERE created_at >= ?",
                    (since_iso,),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n, COALESCE(SUM(CAST(cost_usd AS REAL)), 0) AS c "
                    "FROM jobs WHERE user_id = ? AND created_at >= ?",
                    (user_id, since_iso),
                ).fetchone()
        return int(row["n"]), float(row["c"])

    # -- row mapping -------------------------------------------------------

    def _row_to_record(self, row: sqlite3.Row) -> JobRecord:
        status = JobState(row["status"])
        return JobRecord(
            id=row["id"],
            user_id=row["user_id"],
            question=row["question"],
            as_of=row["as_of"],
            status=status,
            idempotency_key=row["idempotency_key"],
            attempt=row["attempt"],
            max_attempts=row["max_attempts"],
            cancel_requested=bool(row["cancel_requested"]),
            lease_owner=row["lease_owner"],
            lease_expires_at=_parse(row["lease_expires_at"]),
            deadline_at=_parse(row["deadline_at"]),
            progress=json.loads(row["progress"] or "[]"),
            checkpoint=json.loads(row["checkpoint"]) if row["checkpoint"] else None,
            run_id=row["run_id"],
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            cost_usd=row["cost_usd"],
            created_at=_parse(row["created_at"]) or _now(),
            updated_at=_parse(row["updated_at"]) or _now(),
            started_at=_parse(row["started_at"]),
            finished_at=_parse(row["finished_at"]),
        )


__all__ = ["LocalJobStore"]
