"""Environment-driven settings for the hosted research API.

Every knob the deployment spec requires — per-user rate limit, concurrent-job
cap, per-user and global spend ceilings, bounded retries, execution-lease and
absolute-deadline windows, the internal-trigger and cron secrets, the
self-invocation base URL, and CORS origins — is read here, once, with safe
defaults. Nothing secret is logged.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class CloudSettings:
    # Abuse / cost controls.
    rate_limit_per_minute: int = 10
    max_concurrent_jobs_per_user: int = 3
    user_daily_cost_usd: float = 1.00
    global_daily_cost_usd: float = 25.00
    max_job_attempts: int = 2

    # Execution windows (must exceed the engine's max_research_seconds).
    lease_seconds: int = 180
    deadline_seconds: int = 240

    # Internal wiring.
    internal_secret: str | None = None
    cron_secret: str | None = None
    self_base_url: str | None = None

    # CORS: production is same-origin; extra origins are opt-in.
    allowed_origins: tuple[str, ...] = ()

    # Offline-dev auth bypass (explicit, off by default).
    auth_dev_mode: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> CloudSettings:
        e = env if env is not None else os.environ
        return cls(
            rate_limit_per_minute=_int(e, "STRIX_RATE_LIMIT_PER_MINUTE", 10),
            max_concurrent_jobs_per_user=_int(e, "STRIX_MAX_CONCURRENT_JOBS_PER_USER", 3),
            user_daily_cost_usd=_float(e, "STRIX_USER_DAILY_COST_USD", 1.00),
            global_daily_cost_usd=_float(e, "STRIX_GLOBAL_DAILY_COST_USD", 25.00),
            max_job_attempts=_int(e, "STRIX_MAX_JOB_ATTEMPTS", 2),
            lease_seconds=_int(e, "STRIX_LEASE_SECONDS", 180),
            deadline_seconds=_int(e, "STRIX_DEADLINE_SECONDS", 240),
            internal_secret=_opt(e, "STRIX_INTERNAL_SECRET"),
            cron_secret=_opt(e, "CRON_SECRET"),
            self_base_url=_self_base_url(e),
            allowed_origins=_origins(e),
            auth_dev_mode=(e.get("STRIX_AUTH_MODE", "").strip().lower() == "dev"),
        )


def _opt(env: Mapping[str, str], name: str) -> str | None:
    value = (env.get(name) or "").strip()
    return value or None


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = (env.get(name) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = (env.get(name) or "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _origins(env: Mapping[str, str]) -> tuple[str, ...]:
    raw = (env.get("STRIX_ALLOWED_ORIGINS") or "").strip()
    if not raw:
        return ()
    return tuple(o.strip() for o in raw.split(",") if o.strip())


def _self_base_url(env: Mapping[str, str]) -> str | None:
    explicit = (env.get("STRIX_SELF_BASE_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    vercel = (env.get("VERCEL_URL") or "").strip()
    if vercel:
        return f"https://{vercel}"
    return None
