"""SQLite-backed durable transactional outbox (§4/§6).

Events are persisted to a SQLite file (WAL mode) and survive process restarts.
``publish`` is idempotent on ``idempotency_key``; ``claim`` leases a FIFO batch so
concurrent consumers never double-claim; ``ack`` completes an event; ``fail`` retries
up to ``max_attempts`` then dead-letters; ``recover_expired_leases`` returns
crash-abandoned events to PENDING (at-least-once). A SQLite row lock + IMMEDIATE
transactions make claim/fail atomic. The event id is content-addressed, so the same
logical event always gets the same id (deterministic, idempotent indexing).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from strix.canonical import make_id
from strix.models import StrixModel

OUTBOX_SCHEMA_VERSION = "1"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DELIVERED = "delivered"
    DEAD = "dead"


class OutboxEvent(StrixModel):
    """One durable outbox event."""

    seq: int
    event_id: str
    topic: str
    tenant: str
    payload: dict[str, str]
    schema_version: str
    idempotency_key: str
    status: OutboxStatus
    attempts: int
    max_attempts: int
    error: str | None = None


class OutboxReconciliation(StrixModel):
    """Counts of events by status (per-tenant when scoped)."""

    pending: int
    in_flight: int
    delivered: int
    dead: int


@dataclass(frozen=True)
class DeliveryReport:
    """Outcome of one :func:`deliver_batch` pass."""

    delivered: int
    failed: int


_DDL = """
CREATE TABLE IF NOT EXISTS outbox_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    tenant TEXT NOT NULL,
    payload TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL,
    lease_owner TEXT,
    lease_until TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox_events (status, seq);
"""


class SqliteOutbox:
    """A durable transactional outbox persisted to a SQLite file."""

    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_DDL)

    # -- publish -----------------------------------------------------------

    def publish(
        self,
        *,
        topic: str,
        payload: Mapping[str, str],
        idempotency_key: str,
        tenant: str = "default",
        schema_version: str = OUTBOX_SCHEMA_VERSION,
        max_attempts: int = 5,
    ) -> OutboxEvent:
        """Durably enqueue an event; idempotent on ``idempotency_key``."""
        event_id = make_id(
            "OBX", {"tenant": tenant, "idempotency_key": idempotency_key, "topic": topic}
        )
        payload_json = json.dumps(dict(payload), sort_keys=True)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self._conn.execute(
                    "SELECT * FROM outbox_events WHERE idempotency_key = ?", (idempotency_key,)
                ).fetchone()
                if existing is not None:
                    self._conn.execute("COMMIT")
                    return _row_to_event(existing)
                self._conn.execute(
                    "INSERT INTO outbox_events "
                    "(event_id, topic, tenant, payload, schema_version, idempotency_key, "
                    " status, attempts, max_attempts) "
                    "VALUES (?,?,?,?,?,?,?,0,?)",
                    (event_id, topic, tenant, payload_json, schema_version, idempotency_key,
                     OutboxStatus.PENDING.value, max_attempts),
                )
                row = self._conn.execute(
                    "SELECT * FROM outbox_events WHERE event_id = ?", (event_id,)
                ).fetchone()
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return _row_to_event(row)

    # -- claim / ack / fail ------------------------------------------------

    def claim(
        self,
        *,
        consumer: str,
        now: datetime,
        batch: int = 10,
        lease_seconds: int = 60,
        tenant: str | None = None,
    ) -> tuple[OutboxEvent, ...]:
        """Lease up to ``batch`` PENDING events (FIFO) to ``consumer``."""
        lease_until = _iso(now.timestamp() + lease_seconds)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                sql = (
                    "SELECT * FROM outbox_events WHERE status = ? "
                    + ("AND tenant = ? " if tenant is not None else "")
                    + "ORDER BY seq ASC LIMIT ?"
                )
                params: tuple[object, ...] = (
                    (OutboxStatus.PENDING.value, tenant, batch)
                    if tenant is not None
                    else (OutboxStatus.PENDING.value, batch)
                )
                rows = self._conn.execute(sql, params).fetchall()
                for row in rows:
                    self._conn.execute(
                        "UPDATE outbox_events SET status=?, lease_owner=?, lease_until=? "
                        "WHERE event_id=?",
                        (OutboxStatus.IN_FLIGHT.value, consumer, lease_until, row["event_id"]),
                    )
                claimed = [
                    _row_to_event(
                        self._conn.execute(
                            "SELECT * FROM outbox_events WHERE event_id=?", (row["event_id"],)
                        ).fetchone()
                    )
                    for row in rows
                ]
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return tuple(claimed)

    def ack(self, event_id: str, *, consumer: str) -> bool:
        """Mark an event DELIVERED — only if ``consumer`` still holds its lease.

        Returns ``True`` if it transitioned; ``False`` if the lease was lost (the
        event was recovered and re-claimed by another consumer), so a stale worker
        can never resurrect a DELIVERED/DEAD event.
        """
        with self._lock:
            cur = self._conn.execute(
                "UPDATE outbox_events SET status=?, lease_owner=NULL, lease_until=NULL "
                "WHERE event_id=? AND status=? AND lease_owner=?",
                (OutboxStatus.DELIVERED.value, event_id, OutboxStatus.IN_FLIGHT.value, consumer),
            )
            return cur.rowcount == 1

    def fail(self, event_id: str, *, error: str, now: datetime, consumer: str) -> OutboxEvent:
        """Record a failed attempt by the lease holder; retry or dead-letter.

        Lease-fenced: a stale consumer (lease lost) is a no-op that returns the
        current row unchanged. Raises :class:`KeyError` for an unknown event.
        """
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM outbox_events WHERE event_id=?", (event_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown event {event_id!r}")
                owns = (
                    row["status"] == OutboxStatus.IN_FLIGHT.value
                    and row["lease_owner"] == consumer
                )
                if not owns:
                    # Lease was lost/stolen; do not mutate another holder's state.
                    self._conn.execute("COMMIT")
                    return _row_to_event(row)
                attempts = row["attempts"] + 1
                status = (
                    OutboxStatus.DEAD if attempts >= row["max_attempts"] else OutboxStatus.PENDING
                )
                self._conn.execute(
                    "UPDATE outbox_events SET status=?, attempts=?, error=?, "
                    "lease_owner=NULL, lease_until=NULL "
                    "WHERE event_id=? AND status=? AND lease_owner=?",
                    (status.value, attempts, error, event_id,
                     OutboxStatus.IN_FLIGHT.value, consumer),
                )
                updated = self._conn.execute(
                    "SELECT * FROM outbox_events WHERE event_id=?", (event_id,)
                ).fetchone()
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return _row_to_event(updated)

    # -- recovery / inspection --------------------------------------------

    def recover_expired_leases(self, *, now: datetime) -> int:
        """Reclaim IN_FLIGHT events whose lease expired; return how many.

        A lease expiry counts as a delivery attempt (SQS-style receive count), so a
        poison event that hard-crashes its worker before ``fail`` is still bounded:
        once ``attempts`` would reach ``max_attempts`` the event is dead-lettered
        instead of being redelivered forever.
        """
        cutoff = _iso(now.timestamp())
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                expired = (
                    "status=? AND lease_until IS NOT NULL AND lease_until <= ?"
                )
                dead = self._conn.execute(
                    "UPDATE outbox_events SET status=?, attempts=attempts+1, "
                    "lease_owner=NULL, lease_until=NULL "
                    f"WHERE {expired} AND attempts + 1 >= max_attempts",
                    (OutboxStatus.DEAD.value, OutboxStatus.IN_FLIGHT.value, cutoff),
                ).rowcount
                requeued = self._conn.execute(
                    "UPDATE outbox_events SET status=?, attempts=attempts+1, "
                    "lease_owner=NULL, lease_until=NULL "
                    f"WHERE {expired} AND attempts + 1 < max_attempts",
                    (OutboxStatus.PENDING.value, OutboxStatus.IN_FLIGHT.value, cutoff),
                ).rowcount
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return dead + requeued

    def _by_status(self, status: OutboxStatus, tenant: str | None) -> tuple[OutboxEvent, ...]:
        with self._lock:
            if tenant is not None:
                rows = self._conn.execute(
                    "SELECT * FROM outbox_events WHERE status=? AND tenant=? ORDER BY seq",
                    (status.value, tenant),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM outbox_events WHERE status=? ORDER BY seq", (status.value,)
                ).fetchall()
        return tuple(_row_to_event(r) for r in rows)

    def pending(self, tenant: str | None = None) -> tuple[OutboxEvent, ...]:
        return self._by_status(OutboxStatus.PENDING, tenant)

    def dead_letters(self, tenant: str | None = None) -> tuple[OutboxEvent, ...]:
        return self._by_status(OutboxStatus.DEAD, tenant)

    def reconcile(self, tenant: str | None = None) -> OutboxReconciliation:
        with self._lock:
            if tenant is not None:
                rows = self._conn.execute(
                    "SELECT status, COUNT(*) c FROM outbox_events WHERE tenant=? GROUP BY status",
                    (tenant,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT status, COUNT(*) c FROM outbox_events GROUP BY status"
                ).fetchall()
        counts = {r["status"]: r["c"] for r in rows}
        return OutboxReconciliation(
            pending=counts.get(OutboxStatus.PENDING.value, 0),
            in_flight=counts.get(OutboxStatus.IN_FLIGHT.value, 0),
            delivered=counts.get(OutboxStatus.DELIVERED.value, 0),
            dead=counts.get(OutboxStatus.DEAD.value, 0),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _iso(epoch_seconds: float) -> str:
    # Zero-padded fixed-width seconds so lexical comparison equals time order.
    return f"{epoch_seconds:020.6f}"


def _row_to_event(row: sqlite3.Row) -> OutboxEvent:
    return OutboxEvent(
        seq=row["seq"],
        event_id=row["event_id"],
        topic=row["topic"],
        tenant=row["tenant"],
        payload=json.loads(row["payload"]),
        schema_version=row["schema_version"],
        idempotency_key=row["idempotency_key"],
        status=OutboxStatus(row["status"]),
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        error=row["error"],
    )


def deliver_batch(
    outbox: SqliteOutbox,
    *,
    consumer: str,
    handler: Callable[[OutboxEvent], object],
    now: datetime,
    batch: int = 10,
    lease_seconds: int = 60,
    tenant: str | None = None,
) -> DeliveryReport:
    """Claim a batch and run ``handler`` on each; ack on success, fail on error.

    At-least-once: ``handler`` must be idempotent, since a crash between a
    successful handler call and ``ack`` leaves the event to be redelivered.
    """
    claimed = outbox.claim(
        consumer=consumer, now=now, batch=batch, lease_seconds=lease_seconds, tenant=tenant
    )
    delivered = 0
    failed = 0
    for event in claimed:
        try:
            handler(event)
        except Exception as exc:  # handler failures are recorded, never propagated
            outbox.fail(
                event.event_id, error=f"{type(exc).__name__}: {exc}", now=now, consumer=consumer
            )
            failed += 1
        else:
            outbox.ack(event.event_id, consumer=consumer)
            delivered += 1
    return DeliveryReport(delivered=delivered, failed=failed)
