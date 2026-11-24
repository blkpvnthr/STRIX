"""PostgreSQL-backed :class:`JobStore` for the hosted Supabase deployment.

Connects to the Supabase Postgres through the Supavisor transaction pooler (the
serverless-friendly endpoint). Every lease transition is a single atomic
``UPDATE ... RETURNING`` evaluated server-side with ``now()`` — so leasing,
duplicate-execution protection, and stale detection are correct even across
independent Vercel Function invocations that share no memory. Timestamps are
``timestamptz``; progress is a ``jsonb`` array appended with the ``||`` operator;
``checkpoint`` and ``result`` are ``jsonb``.

The schema is owned by the SQL migrations in ``supabase/migrations`` (which also
define foreign keys, indexes, the ``(user_id, idempotency_key)`` uniqueness
constraint, and row-level security). This store assumes those objects exist.

Connections are opened per operation against the pooler (which multiplexes them);
the service-role connection runs as a privileged role, so this layer enforces
ownership explicitly in every query rather than relying on RLS alone. RLS remains
as defense-in-depth for any direct Data-API access.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from strix.jobs.models import JobRecord, JobState
from strix.jobs.store import JobStore, new_job_id

_TABLE = "research_jobs"

_COLUMNS = (
    "id, user_id, question, as_of, status, idempotency_key, attempt, max_attempts, "
    "cancel_requested, lease_owner, lease_expires_at, deadline_at, progress, "
    "checkpoint, run_id, result, error, cost_usd, created_at, updated_at, "
    "started_at, finished_at"
)


class SupabaseJobStore(JobStore):
    """A durable job store backed by Supabase PostgreSQL."""

    def __init__(self, dsn: str, *, connect_timeout: int = 10) -> None:
        self._dsn = dsn
        self._connect_timeout = connect_timeout

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(
            self._dsn,
            autocommit=True,
            connect_timeout=self._connect_timeout,
            row_factory=dict_row,
        )

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
        job_id = new_job_id()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {_TABLE}
                    (id, user_id, question, as_of, status, idempotency_key,
                     attempt, max_attempts, cancel_requested, progress,
                     created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'queued', %s, 0, %s, false, '[]'::jsonb,
                        now(), now())
                ON CONFLICT (user_id, idempotency_key) DO NOTHING
                RETURNING {_COLUMNS}
                """,
                (job_id, user_id, question, as_of, idempotency_key, max_attempts),
            )
            row = cur.fetchone()
            if row is not None:
                return _row_to_record(row), True
            cur.execute(
                f"SELECT {_COLUMNS} FROM {_TABLE} "
                "WHERE user_id = %s AND idempotency_key = %s",
                (user_id, idempotency_key),
            )
            existing = cur.fetchone()
        if existing is None:  # pragma: no cover - race lost then row vanished
            raise RuntimeError("idempotent insert conflicted but no row found")
        return _row_to_record(existing), False

    def get_job(self, job_id: str, *, user_id: str | None = None) -> JobRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            if user_id is None:
                cur.execute(f"SELECT {_COLUMNS} FROM {_TABLE} WHERE id = %s", (job_id,))
            else:
                cur.execute(
                    f"SELECT {_COLUMNS} FROM {_TABLE} WHERE id = %s AND user_id = %s",
                    (job_id, user_id),
                )
            row = cur.fetchone()
        return None if row is None else _row_to_record(row)

    def list_jobs(self, *, user_id: str, limit: int = 50) -> list[JobRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUMNS} FROM {_TABLE} WHERE user_id = %s "
                "ORDER BY created_at DESC LIMIT %s",
                (user_id, limit),
            )
            rows = cur.fetchall()
        return [_row_to_record(r) for r in rows]

    # -- cancellation ------------------------------------------------------

    def request_cancel(self, job_id: str, *, user_id: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {_TABLE}
                   SET cancel_requested = true,
                       status = CASE WHEN status = 'queued' THEN 'cancelled' ELSE status END,
                       finished_at = CASE WHEN status = 'queued' THEN now() ELSE finished_at END,
                       updated_at = now()
                 WHERE id = %s AND user_id = %s AND status IN ('queued', 'running')
                RETURNING id
                """,
                (job_id, user_id),
            )
            return cur.fetchone() is not None

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT cancel_requested FROM {_TABLE} WHERE id = %s", (job_id,)
            )
            row = cur.fetchone()
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
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {_TABLE}
                   SET status = 'running',
                       lease_owner = %s,
                       lease_expires_at = now() + make_interval(secs => %s),
                       deadline_at = now() + make_interval(secs => %s),
                       started_at = COALESCE(started_at, now()),
                       attempt = attempt + 1,
                       updated_at = now()
                 WHERE id = %s
                   AND cancel_requested = false
                   AND (
                        status = 'queued'
                        OR (status = 'running'
                            AND (lease_expires_at IS NULL OR lease_expires_at < now()))
                   )
                RETURNING {_COLUMNS}
                """,
                (worker_id, lease_seconds, deadline_seconds, job_id),
            )
            row = cur.fetchone()
        return None if row is None else _row_to_record(row)

    def renew_lease(self, job_id: str, *, worker_id: str, lease_seconds: int) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {_TABLE}
                   SET lease_expires_at = now() + make_interval(secs => %s), updated_at = now()
                 WHERE id = %s AND lease_owner = %s AND status = 'running'
                RETURNING id
                """,
                (lease_seconds, job_id, worker_id),
            )
            return cur.fetchone() is not None

    # -- progress / checkpoint --------------------------------------------

    def append_progress(self, job_id: str, message: str, *, worker_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {_TABLE}
                   SET progress = progress || %s::jsonb, updated_at = now()
                 WHERE id = %s AND lease_owner = %s
                """,
                (json.dumps([message]), job_id, worker_id),
            )

    def save_checkpoint(
        self, job_id: str, checkpoint: dict[str, Any], *, worker_id: str
    ) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {_TABLE}
                   SET checkpoint = %s::jsonb, updated_at = now()
                 WHERE id = %s AND lease_owner = %s
                """,
                (json.dumps(checkpoint), job_id, worker_id),
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
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {_TABLE}
                   SET status = %s, run_id = %s,
                       result = %s::jsonb, error = %s, cost_usd = %s,
                       lease_owner = NULL, lease_expires_at = NULL,
                       finished_at = now(), updated_at = now()
                 WHERE id = %s AND lease_owner = %s
                RETURNING {_COLUMNS}
                """,
                (
                    status.value,
                    run_id,
                    None if result is None else json.dumps(result),
                    error,
                    cost_usd,
                    job_id,
                    worker_id,
                ),
            )
            row = cur.fetchone()
        return None if row is None else _row_to_record(row)

    def requeue_for_retry(
        self, job_id: str, *, worker_id: str, error: str
    ) -> JobRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {_TABLE}
                   SET status = 'queued', lease_owner = NULL, lease_expires_at = NULL,
                       deadline_at = NULL, error = %s, updated_at = now()
                 WHERE id = %s AND lease_owner = %s AND attempt < max_attempts
                RETURNING {_COLUMNS}
                """,
                (error, job_id, worker_id),
            )
            row = cur.fetchone()
        return None if row is None else _row_to_record(row)

    def reopen_for_retry(self, job_id: str, *, user_id: str) -> JobRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {_TABLE}
                   SET status = 'queued', max_attempts = attempt + 1,
                       cancel_requested = false, lease_owner = NULL,
                       lease_expires_at = NULL, deadline_at = NULL,
                       error = NULL, finished_at = NULL, updated_at = now()
                 WHERE id = %s AND user_id = %s
                   AND status IN ('failed', 'timed_out', 'partial')
                RETURNING {_COLUMNS}
                """,
                (job_id, user_id),
            )
            row = cur.fetchone()
        return None if row is None else _row_to_record(row)

    def get_job_by_run_id(self, run_id: str, *, user_id: str) -> JobRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUMNS} FROM {_TABLE} "
                "WHERE run_id = %s AND user_id = %s LIMIT 1",
                (run_id, user_id),
            )
            row = cur.fetchone()
        return None if row is None else _row_to_record(row)

    # -- recovery / limits -------------------------------------------------

    def find_stale(self, *, now: datetime, limit: int = 20) -> list[JobRecord]:
        # ``now`` is accepted for interface parity; the server clock is used.
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLUMNS} FROM {_TABLE}
                 WHERE cancel_requested = false
                   AND (
                        status = 'queued'
                        OR (status = 'running'
                            AND (lease_expires_at IS NULL OR lease_expires_at < now()))
                   )
                 ORDER BY created_at ASC
                 LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [_row_to_record(r) for r in rows]

    def count_active(self, *, user_id: str) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS n FROM {_TABLE} "
                "WHERE user_id = %s AND status IN ('queued', 'running')",
                (user_id,),
            )
            row = cur.fetchone()
        return int(row["n"]) if row else 0

    def usage_since(
        self, *, user_id: str | None, since: datetime
    ) -> tuple[int, float]:
        with self._connect() as conn, conn.cursor() as cur:
            if user_id is None:
                cur.execute(
                    f"SELECT COUNT(*) AS n, COALESCE(SUM(cost_usd::numeric), 0) AS c "
                    f"FROM {_TABLE} WHERE created_at >= %s",
                    (since,),
                )
            else:
                cur.execute(
                    f"SELECT COUNT(*) AS n, COALESCE(SUM(cost_usd::numeric), 0) AS c "
                    f"FROM {_TABLE} WHERE user_id = %s AND created_at >= %s",
                    (user_id, since),
                )
            row = cur.fetchone()
        if row is None:  # pragma: no cover - COUNT always returns a row
            return 0, 0.0
        return int(row["n"]), float(row["c"])


def _row_to_record(row: dict[str, Any]) -> JobRecord:
    return JobRecord(
        id=row["id"],
        user_id=row["user_id"],
        question=row["question"],
        as_of=row["as_of"],
        status=JobState(row["status"]),
        idempotency_key=row["idempotency_key"],
        attempt=row["attempt"],
        max_attempts=row["max_attempts"],
        cancel_requested=bool(row["cancel_requested"]),
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        deadline_at=row["deadline_at"],
        progress=list(row["progress"] or []),
        checkpoint=row["checkpoint"],
        run_id=row["run_id"],
        result=row["result"],
        error=row["error"],
        cost_usd=row["cost_usd"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )
