"""Select the job-store and artifact-storage backends from the environment.

Backend resolution is explicit and fail-safe:

- ``STRIX_PERSISTENCE_BACKEND=supabase`` (or any ``STRIX_DATABASE_URL`` being
  set) selects the PostgreSQL store.
- otherwise the SQLite :class:`LocalJobStore` is used — the default for offline
  development, the CLI, and tests, so nothing requires a cloud project to run.

The artifact sink is the Supabase Storage sink when a service key + URL are
present, else a no-op sink (artifacts stay on the local filesystem).
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from strix.jobs.executor import ArtifactSink, NullArtifactSink
from strix.jobs.local_store import LocalJobStore
from strix.jobs.store import JobStore


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return env if env is not None else os.environ


def database_url(env: Mapping[str, str] | None = None) -> str | None:
    e = _env(env)
    for name in ("STRIX_DATABASE_URL", "SUPABASE_DB_URL", "DATABASE_URL"):
        value = (e.get(name) or "").strip()
        if value:
            return value
    return None


def use_supabase(env: Mapping[str, str] | None = None) -> bool:
    e = _env(env)
    backend = (e.get("STRIX_PERSISTENCE_BACKEND") or "").strip().lower()
    if backend == "supabase":
        return True
    if backend == "local":
        return False
    return database_url(e) is not None


def build_job_store(env: Mapping[str, str] | None = None) -> JobStore:
    """Construct the configured :class:`JobStore`."""
    e = _env(env)
    if use_supabase(e):
        dsn = database_url(e)
        if not dsn:
            raise RuntimeError(
                "STRIX_PERSISTENCE_BACKEND=supabase but no STRIX_DATABASE_URL is set"
            )
        from strix.jobs.supabase_store import SupabaseJobStore

        return SupabaseJobStore(dsn)
    path = (e.get("STRIX_JOBS_DB") or "research_runs/jobs.db").strip()
    return LocalJobStore(path)


def build_artifact_sink(env: Mapping[str, str] | None = None) -> ArtifactSink:
    """Construct the configured artifact sink (Supabase Storage or no-op)."""
    e = _env(env)
    url = (e.get("SUPABASE_URL") or "").strip()
    service_key = (
        e.get("SUPABASE_SERVICE_ROLE_KEY") or e.get("SUPABASE_SERVICE_KEY") or ""
    ).strip()
    bucket = (e.get("STRIX_EVIDENCE_BUCKET") or "strix-evidence").strip()
    if url and service_key:
        from strix.jobs.storage import SupabaseStorageSink

        return SupabaseStorageSink(base_url=url, service_key=service_key, bucket=bucket)
    return NullArtifactSink()
