"""Execution triggers: how a persisted job gets picked up for running.

The job is always written durably *before* it is triggered, so a dropped trigger
is never data loss — the cron sweeper re-triggers anything left queued or stale.
This is the seam the spec calls "queue-ready": swap one trigger for a real queue
producer and nothing else changes.

Two implementations:

- :class:`HttpSelfTrigger` (hosted) — fires a non-blocking HTTP call to the
  internal ``/api/jobs/execute`` endpoint, which runs on a *fresh* serverless
  invocation with its own full ``maxDuration``. The caller does not await the
  research; it returns the job id immediately.
- :class:`ThreadTrigger` (local/offline) — runs :func:`execute_job` on a daemon
  thread in-process, so the SQLite-backed local app behaves end-to-end without a
  second host to call.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import httpx

from strix.agent.config import AgentConfig
from strix.jobs.executor import ArtifactSink, execute_job
from strix.jobs.store import JobStore


class Trigger(Protocol):
    def trigger(self, job_id: str) -> None: ...


class HttpSelfTrigger:
    """Fire-and-forget self-invocation of the internal execute endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        internal_secret: str,
        connect_timeout: float = 2.0,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/api/jobs/execute"
        self._secret = internal_secret
        # Short read timeout: we only need the request to *reach* Vercel and spawn
        # the execute invocation; we deliberately do not await the research.
        self._timeout = httpx.Timeout(connect_timeout, read=0.5, write=2.0, pool=2.0)

    def trigger(self, job_id: str) -> None:
        try:
            httpx.post(
                self._url,
                json={"job_id": job_id},
                headers={"x-strix-internal": self._secret},
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            # Expected: the execute invocation keeps running after we stop reading.
            pass
        except httpx.HTTPError:
            # Trigger lost; the cron sweeper will pick the queued job up.
            pass


class ThreadTrigger:
    """Runs execution on a background daemon thread (local/offline)."""

    def __init__(
        self,
        *,
        store: JobStore,
        config_loader: Callable[[], AgentConfig] = AgentConfig.load,
        artifact_sink: ArtifactSink | None = None,
        lease_seconds: int = 180,
        deadline_seconds: int = 240,
        state_dir_root: Path | None = None,
    ) -> None:
        self._store = store
        self._config_loader = config_loader
        self._sink = artifact_sink
        self._lease_seconds = lease_seconds
        self._deadline_seconds = deadline_seconds
        self._state_dir_root = state_dir_root

    def trigger(self, job_id: str) -> None:
        thread = threading.Thread(target=self._run, args=(job_id,), daemon=True)
        thread.start()

    def _run(self, job_id: str) -> None:
        # execute_job claims the lease first, so a config/engine failure is
        # recorded on the job rather than silently lost on this thread.
        execute_job(
            job_id,
            store=self._store,
            config_loader=self._config_loader,
            artifact_sink=self._sink,
            lease_seconds=self._lease_seconds,
            deadline_seconds=self._deadline_seconds,
            state_dir_root=self._state_dir_root,
        )
