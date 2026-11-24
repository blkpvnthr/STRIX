"""Submission limits: rate, concurrency, per-user and global spend."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from strix.jobs.local_store import LocalJobStore
from strix.jobs.models import JobState
from strix.jobs.store import new_worker_id
from strix.webapi.cloud_settings import CloudSettings
from strix.webapi.limits import check_submission


def _store_with_finished(cost: str, n: int = 1) -> LocalJobStore:
    store = LocalJobStore(":memory:")
    for i in range(n):
        job, _ = store.create_job(
            user_id="u1", question=f"q{i}", as_of=None, idempotency_key=f"k{i}", max_attempts=1
        )
        w = new_worker_id()
        store.claim_for_execution(job.id, worker_id=w, lease_seconds=60, deadline_seconds=180)
        store.finish_job(job.id, worker_id=w, status=JobState.COMPLETED, cost_usd=cost)
    return store


def test_allows_fresh_user() -> None:
    store = LocalJobStore(":memory:")
    decision = check_submission(store, CloudSettings(), user_id="new")
    assert decision.allowed is True


def test_rate_limit() -> None:
    store = _store_with_finished("0.00", n=5)
    settings = CloudSettings(rate_limit_per_minute=3)
    decision = check_submission(store, settings, user_id="u1")
    assert decision.allowed is False
    assert decision.retry_after_seconds == 60


def test_concurrency_limit() -> None:
    store = LocalJobStore(":memory:")
    for i in range(2):
        job, _ = store.create_job(
            user_id="u1", question=f"q{i}", as_of=None, idempotency_key=f"k{i}", max_attempts=1
        )
        store.claim_for_execution(
            job.id, worker_id=new_worker_id(), lease_seconds=60, deadline_seconds=180
        )
    settings = CloudSettings(rate_limit_per_minute=100, max_concurrent_jobs_per_user=2)
    assert check_submission(store, settings, user_id="u1").allowed is False


def test_user_daily_spend_cap() -> None:
    store = _store_with_finished("0.60", n=1)
    settings = CloudSettings(rate_limit_per_minute=100, user_daily_cost_usd=0.50)
    assert check_submission(store, settings, user_id="u1").allowed is False


def test_global_daily_spend_cap() -> None:
    store = _store_with_finished("5.00", n=1)
    settings = CloudSettings(
        rate_limit_per_minute=100,
        user_daily_cost_usd=100.0,
        global_daily_cost_usd=1.0,
    )
    assert check_submission(store, settings, user_id="u2").allowed is False


def test_old_usage_does_not_count() -> None:
    store = _store_with_finished("1.00", n=1)
    # A window starting in the future sees no usage.
    future = datetime.now(UTC) + timedelta(days=2)
    count, cost = store.usage_since(user_id="u1", since=future)
    assert count == 0
    assert cost == 0.0
