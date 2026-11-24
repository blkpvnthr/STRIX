"""Rate, concurrency, and spend enforcement for research submission.

All checks read from the durable :class:`~strix.jobs.store.JobStore`, so they hold
across independent serverless invocations (no in-memory counters that reset on a
cold start). The goal the spec states plainly: no caller can exceed their request
rate, run too many jobs at once, or push per-user or platform-wide OpenAI spend
past the configured ceilings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from strix.jobs.store import JobStore
from strix.webapi.cloud_settings import CloudSettings


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    reason: str | None = None
    retry_after_seconds: int | None = None


def check_submission(
    store: JobStore,
    settings: CloudSettings,
    *,
    user_id: str,
    now: datetime | None = None,
) -> LimitDecision:
    """Return whether ``user_id`` may submit a new research job right now."""
    current = now or datetime.now(UTC)

    # 1. Per-user request rate (sliding one-minute window).
    minute_ago = current - timedelta(minutes=1)
    recent_count, _ = store.usage_since(user_id=user_id, since=minute_ago)
    if recent_count >= settings.rate_limit_per_minute:
        return LimitDecision(
            False,
            f"rate limit exceeded ({settings.rate_limit_per_minute}/min)",
            retry_after_seconds=60,
        )

    # 2. Concurrent (queued or running) jobs.
    active = store.count_active(user_id=user_id)
    if active >= settings.max_concurrent_jobs_per_user:
        return LimitDecision(
            False,
            f"too many concurrent research jobs ({settings.max_concurrent_jobs_per_user})",
            retry_after_seconds=30,
        )

    # 3. Per-user daily spend.
    day_ago = current - timedelta(days=1)
    _, user_cost = store.usage_since(user_id=user_id, since=day_ago)
    if user_cost >= settings.user_daily_cost_usd:
        return LimitDecision(
            False, f"daily spend limit reached (${settings.user_daily_cost_usd:.2f})"
        )

    # 4. Platform-wide daily spend.
    _, global_cost = store.usage_since(user_id=None, since=day_ago)
    if global_cost >= settings.global_daily_cost_usd:
        return LimitDecision(
            False, "platform research spend limit reached; try again later"
        )

    return LimitDecision(True)
