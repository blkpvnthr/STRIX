"""Tests for the durable SQLite transactional outbox (§4/§6).

Covers durability across reopen, idempotent publish, FIFO ordering, lease-based
claim (no double-claim), ack/retry/dead-letter with bounded retries, expired-lease
recovery (restart/interruption), tenant isolation, and reconciliation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from strix.outbox.sqlite_outbox import OutboxStatus, SqliteOutbox, deliver_batch

T0 = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def _ob(tmp_path: Path, name: str = "ob.db") -> SqliteOutbox:
    return SqliteOutbox(tmp_path / name)


def test_publish_is_idempotent_on_idempotency_key(tmp_path: Path) -> None:
    ob = _ob(tmp_path)
    a = ob.publish(topic="index", payload={"doc": "1"}, idempotency_key="k1")
    b = ob.publish(topic="index", payload={"doc": "1"}, idempotency_key="k1")
    assert a.event_id == b.event_id
    assert ob.reconcile().pending == 1  # not duplicated


def test_event_id_is_deterministic(tmp_path: Path) -> None:
    a = _ob(tmp_path, "a.db").publish(topic="t", payload={"x": "1"}, idempotency_key="k")
    b = _ob(tmp_path, "b.db").publish(topic="t", payload={"x": "1"}, idempotency_key="k")
    assert a.event_id == b.event_id


def test_claim_returns_fifo_and_marks_in_flight(tmp_path: Path) -> None:
    ob = _ob(tmp_path)
    for i in range(3):
        ob.publish(topic="t", payload={"n": str(i)}, idempotency_key=f"k{i}")
    claimed = ob.claim(consumer="w1", now=T0, batch=2, lease_seconds=60)
    assert [e.payload["n"] for e in claimed] == ["0", "1"]  # FIFO
    assert all(e.status is OutboxStatus.IN_FLIGHT for e in claimed)
    # A second claimer cannot re-claim the leased events; it gets the remaining one.
    again = ob.claim(consumer="w2", now=T0, batch=10, lease_seconds=60)
    assert [e.payload["n"] for e in again] == ["2"]


def test_ack_marks_delivered(tmp_path: Path) -> None:
    ob = _ob(tmp_path)
    ob.publish(topic="t", payload={}, idempotency_key="k")
    (claimed,) = ob.claim(consumer="w", now=T0, batch=1, lease_seconds=60)
    ob.ack(claimed.event_id, consumer="w")
    assert ob.reconcile().delivered == 1
    assert ob.reconcile().pending == 0


def test_fail_retries_then_dead_letters_at_max(tmp_path: Path) -> None:
    ob = _ob(tmp_path)
    ob.publish(topic="t", payload={}, idempotency_key="k", max_attempts=2)
    # Attempt 1: claim + fail -> back to pending.
    (e1,) = ob.claim(consumer="w", now=T0, batch=1, lease_seconds=60)
    after1 = ob.fail(e1.event_id, error="boom", now=T0, consumer="w")
    assert after1.status is OutboxStatus.PENDING
    assert after1.attempts == 1
    # Attempt 2: claim + fail -> reaches max_attempts -> DEAD.
    (e2,) = ob.claim(consumer="w", now=T0, batch=1, lease_seconds=60)
    after2 = ob.fail(e2.event_id, error="boom again", now=T0, consumer="w")
    assert after2.status is OutboxStatus.DEAD
    assert ob.reconcile().dead == 1
    assert [e.event_id for e in ob.dead_letters()] == [after2.event_id]


def test_expired_lease_is_recovered(tmp_path: Path) -> None:
    ob = _ob(tmp_path)
    ob.publish(topic="t", payload={}, idempotency_key="k")
    ob.claim(consumer="w", now=T0, batch=1, lease_seconds=60)
    # The worker crashed before ack; its lease expires.
    recovered = ob.recover_expired_leases(now=T0 + timedelta(seconds=61))
    assert recovered == 1
    # The event is claimable again (at-least-once).
    again = ob.claim(consumer="w2", now=T0 + timedelta(seconds=62), batch=1, lease_seconds=60)
    assert len(again) == 1


def test_durability_across_reopen(tmp_path: Path) -> None:
    _ob(tmp_path).publish(topic="t", payload={"v": "1"}, idempotency_key="k")
    # A fresh handle on the same file sees the persisted event (not in-memory only).
    reopened = _ob(tmp_path)
    assert reopened.reconcile().pending == 1


def test_tenant_isolation(tmp_path: Path) -> None:
    ob = _ob(tmp_path)
    ob.publish(topic="t", payload={}, idempotency_key="a", tenant="inst-a")
    ob.publish(topic="t", payload={}, idempotency_key="b", tenant="inst-b")
    claimed = ob.claim(consumer="w", now=T0, batch=10, lease_seconds=60, tenant="inst-a")
    assert [e.tenant for e in claimed] == ["inst-a"]
    assert {e.tenant for e in ob.pending()} == {"inst-b"}  # inst-a now in-flight


def test_deliver_batch_acks_on_success_and_retries_on_failure(tmp_path: Path) -> None:
    ob = _ob(tmp_path)
    ob.publish(topic="t", payload={"ok": "1"}, idempotency_key="good")
    ob.publish(topic="t", payload={"ok": "0"}, idempotency_key="bad")
    seen: list[str] = []

    def handler(ev) -> None:  # type: ignore[no-untyped-def]
        seen.append(ev.event_id)
        if ev.payload.get("ok") == "0":
            raise RuntimeError("handler failed")

    report = deliver_batch(ob, consumer="w", handler=handler, now=T0, batch=10, lease_seconds=60)
    assert report.delivered == 1
    assert report.failed == 1
    assert len(seen) == 2
    assert ob.reconcile().delivered == 1
    assert ob.reconcile().pending == 1  # the failed one retries


def test_duplicate_delivery_is_safe_with_idempotent_consumer(tmp_path: Path) -> None:
    ob = _ob(tmp_path)
    ob.publish(topic="t", payload={}, idempotency_key="k")
    applied: set[str] = set()

    def idempotent_handler(ev) -> None:  # type: ignore[no-untyped-def]
        applied.add(ev.event_id)  # set() makes re-application a no-op

    # First delivery: claim + apply, but the worker CRASHES before ack.
    (first,) = ob.claim(consumer="w", now=T0, batch=1, lease_seconds=1)
    idempotent_handler(first)
    # Lease expires; the event is recovered and redelivered (at-least-once).
    ob.recover_expired_leases(now=T0 + timedelta(seconds=5))
    (again,) = ob.claim(consumer="w2", now=T0 + timedelta(seconds=6), batch=1, lease_seconds=60)
    idempotent_handler(again)
    ob.ack(again.event_id, consumer="w2")
    assert first.event_id == again.event_id
    assert len(applied) == 1  # idempotent consumer: applied exactly once despite redelivery


# --- adversarial-review regressions ----------------------------------------


def test_stale_consumer_ack_cannot_resurrect_after_reclaim(tmp_path: Path) -> None:
    ob = _ob(tmp_path)
    ob.publish(topic="t", payload={}, idempotency_key="k")
    (a,) = ob.claim(consumer="A", now=T0, batch=1, lease_seconds=1)
    ob.recover_expired_leases(now=T0 + timedelta(seconds=5))
    (b,) = ob.claim(consumer="B", now=T0 + timedelta(seconds=6), batch=1, lease_seconds=60)
    # Stale A acks the event it no longer holds -> no-op; B still owns it in-flight.
    assert ob.ack(a.event_id, consumer="A") is False
    rec = ob.reconcile()
    assert rec.delivered == 0 and rec.in_flight == 1
    # The rightful owner B can still complete it.
    assert ob.ack(b.event_id, consumer="B") is True
    assert ob.reconcile().delivered == 1


def test_stale_consumer_fail_cannot_requeue_delivered(tmp_path: Path) -> None:
    ob = _ob(tmp_path)
    ob.publish(topic="t", payload={}, idempotency_key="k")
    (a,) = ob.claim(consumer="A", now=T0, batch=1, lease_seconds=1)
    ob.recover_expired_leases(now=T0 + timedelta(seconds=5))
    (b,) = ob.claim(consumer="B", now=T0 + timedelta(seconds=6), batch=1, lease_seconds=60)
    assert ob.ack(b.event_id, consumer="B") is True  # B delivers it
    # Stale A now fails the already-delivered event -> must be a no-op.
    result = ob.fail(a.event_id, error="late", now=T0 + timedelta(seconds=7), consumer="A")
    assert result.status is OutboxStatus.DELIVERED  # not resurrected to PENDING
    assert ob.reconcile().delivered == 1
    assert ob.reconcile().pending == 0


def test_fail_unknown_event_raises_keyerror(tmp_path: Path) -> None:
    ob = _ob(tmp_path)
    with pytest.raises(KeyError):
        ob.fail("OBX-does-not-exist", error="x", now=T0, consumer="w")


def test_poison_pill_dead_letters_via_repeated_lease_expiry(tmp_path: Path) -> None:
    # A handler that hard-crashes the process (never calls fail) must not redeliver
    # forever: each lease expiry counts as an attempt, so it dead-letters.
    ob = _ob(tmp_path)
    ob.publish(topic="t", payload={}, idempotency_key="k", max_attempts=2)
    now = T0
    for _ in range(5):
        ob.claim(consumer="w", now=now, batch=1, lease_seconds=1)
        ob.recover_expired_leases(now=now + timedelta(seconds=5))
        now = now + timedelta(seconds=10)
    assert ob.reconcile().dead == 1
    assert ob.reconcile().pending == 0

