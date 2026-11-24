"""Durable research-job orchestration.

This package adds a *durable* execution layer around the existing, untouched
research engine (:func:`strix.agent.orchestrator.run_research_question`). It is
the seam that makes STRIX cloud-deployable:

- :mod:`strix.jobs.models` — the persisted job record and its state machine.
- :mod:`strix.jobs.store` — the backend-agnostic :class:`JobStore` protocol plus
  the shared lease/idempotency semantics.
- :mod:`strix.jobs.local_store` — a SQLite implementation for offline
  development, the CLI, and the test-suite.
- :mod:`strix.jobs.supabase_store` — a PostgreSQL implementation (Supabase /
  Supavisor) for the hosted deployment.
- :mod:`strix.jobs.executor` — :func:`execute_job`, a Vercel-agnostic driver
  that a request handler, a cron sweeper, or a separate queue worker can all
  call identically.
- :mod:`strix.jobs.factory` — selects the store backend from the environment.

The research engine itself is never modified; this layer only persists, leases,
checkpoints, and recovers around it.
"""

from __future__ import annotations

from strix.jobs.models import JobRecord, JobState, terminal_states
from strix.jobs.store import JobStore, LeaseError

__all__ = [
    "JobRecord",
    "JobState",
    "JobStore",
    "LeaseError",
    "terminal_states",
]
