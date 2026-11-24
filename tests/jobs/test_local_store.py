"""LocalJobStore: idempotency, atomic leasing, retries, recovery, accounting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from strix.jobs.local_store import LocalJobStore
from strix.jobs.models import JobState
from strix.jobs.store import derive_idempotency_key, new_worker_id


@pytest.fixture
def store() -> LocalJobStore:
    return LocalJobStore(":memory:")


def _make(store: LocalJobStore, question: str = "q", key: str | None = None) -> str:
    key = key or derive_idempotency_key("u1", question, None)
    job, _ = store.create_job(
        user_id="u1", question=question, as_of=None, idempotency_key=key, max_attempts=2
    )
    return job.id


def test_create_is_idempotent(store: LocalJobStore) -> None:
    key = derive_idempotency_key("u1", "same", None)
    first, created1 = store.create_job(
        user_id="u1", question="same", as_of=None, idempotency_key=key, max_attempts=2
    )
    second, created2 = store.create_job(
        user_id="u1", question="same", as_of=None, idempotency_key=key, max_attempts=2
    )
    assert created1 is True
    assert created2 is False
    assert first.id == second.id


def test_claim_is_atomic_and_blocks_duplicates(store: LocalJobStore) -> None:
    job_id = _make(store)
    w1 = new_worker_id()
    leased = store.claim_for_execution(
        job_id, worker_id=w1, lease_seconds=60, deadline_seconds=180
    )
    assert leased is not None
    assert leased.status is JobState.RUNNING
    assert leased.attempt == 1
    # A second worker cannot claim a live lease.
    assert (
        store.claim_for_execution(
            job_id, worker_id=new_worker_id(), lease_seconds=60, deadline_seconds=180
        )
        is None
    )


def test_progress_and_finish_require_lease(store: LocalJobStore) -> None:
    job_id = _make(store)
    worker = new_worker_id()
    store.claim_for_execution(job_id, worker_id=worker, lease_seconds=60, deadline_seconds=180)
    store.append_progress(job_id, "step 1", worker_id=worker)
    # A non-holder cannot append progress or finish the job.
    store.append_progress(job_id, "intruder", worker_id="other")
    assert store.get_job(job_id).progress == ["step 1"]
    assert store.finish_job(job_id, worker_id="other", status=JobState.COMPLETED) is None
    finished = store.finish_job(
        job_id, worker_id=worker, status=JobState.COMPLETED, run_id="RUN-20261124-001"
    )
    assert finished is not None
    assert finished.status is JobState.COMPLETED
    assert finished.lease_owner is None


def test_requeue_is_bounded(store: LocalJobStore) -> None:
    job_id = _make(store)
    worker = new_worker_id()
    store.claim_for_execution(job_id, worker_id=worker, lease_seconds=60, deadline_seconds=180)
    # attempt==1, max==2 -> requeue allowed
    assert store.requeue_for_retry(job_id, worker_id=worker, error="x") is not None
    worker2 = new_worker_id()
    store.claim_for_execution(job_id, worker_id=worker2, lease_seconds=60, deadline_seconds=180)
    # attempt==2, max==2 -> no more retries
    assert store.requeue_for_retry(job_id, worker_id=worker2, error="x") is None


def test_reopen_grants_exactly_one_more_attempt(store: LocalJobStore) -> None:
    job_id = _make(store)
    worker = new_worker_id()
    store.claim_for_execution(job_id, worker_id=worker, lease_seconds=60, deadline_seconds=180)
    store.finish_job(job_id, worker_id=worker, status=JobState.FAILED, error="boom")
    reopened = store.reopen_for_retry(job_id, user_id="u1")
    assert reopened is not None
    assert reopened.status is JobState.QUEUED
    assert reopened.max_attempts == reopened.attempt + 1
    # Another user cannot reopen it.
    assert store.reopen_for_retry(job_id, user_id="someone-else") is None


def test_cancel_queued_is_immediate(store: LocalJobStore) -> None:
    job_id = _make(store)
    assert store.request_cancel(job_id, user_id="u1") is True
    assert store.get_job(job_id).status is JobState.CANCELLED
    # Wrong user cannot cancel.
    other = _make(store, question="other")
    assert store.request_cancel(other, user_id="intruder") is False


def test_find_stale_surfaces_queued_and_expired(store: LocalJobStore) -> None:
    queued = _make(store, question="queued")
    expired = _make(store, question="expired")
    worker = new_worker_id()
    # Lease it, then look into the future past the lease expiry.
    store.claim_for_execution(expired, worker_id=worker, lease_seconds=1, deadline_seconds=300)
    future = datetime.now(UTC) + timedelta(seconds=120)
    stale_ids = {j.id for j in store.find_stale(now=future)}
    assert queued in stale_ids
    assert expired in stale_ids


def test_usage_and_concurrency_accounting(store: LocalJobStore) -> None:
    job_id = _make(store)
    worker = new_worker_id()
    store.claim_for_execution(job_id, worker_id=worker, lease_seconds=60, deadline_seconds=180)
    assert store.count_active(user_id="u1") == 1
    store.finish_job(
        job_id, worker_id=worker, status=JobState.COMPLETED, cost_usd="0.02"
    )
    assert store.count_active(user_id="u1") == 0
    since = datetime.now(UTC) - timedelta(hours=1)
    count, cost = store.usage_since(user_id="u1", since=since)
    assert count == 1
    assert cost == pytest.approx(0.02)
    gcount, gcost = store.usage_since(user_id=None, since=since)
    assert gcount == 1
    assert gcost == pytest.approx(0.02)
