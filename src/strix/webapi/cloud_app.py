"""The hosted STRIX research API (Vercel Functions + Supabase).

This is the cloud variant of :mod:`strix.webapi.app`. It keeps the same public
research surface but makes every part durable and authenticated:

- research is persisted as a :class:`~strix.jobs.models.JobRecord` *before* it
  runs and executed by the Vercel-agnostic :func:`~strix.jobs.executor.execute_job`;
- every research route requires a verified Supabase user and is ownership-scoped;
- submission is rate-, concurrency-, and spend-limited from durable counters;
- an internal ``/api/jobs/execute`` route runs one job on a fresh invocation, and
  a cron ``/api/jobs/sweep`` route recovers stale/stuck jobs (and marks genuinely
  timed-out ones ``timed_out`` — never fabricating verified claims).

The research engine itself is untouched; this module only orchestrates around it.
"""

from __future__ import annotations

import hmac
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from strix.agent import AGENT_VERSION
from strix.agent.config import AgentConfig
from strix.auth.dependencies import require_user
from strix.auth.supabase_jwt import AuthConfigError, AuthUser, JWTVerifier
from strix.errors import AgentError, error_code
from strix.jobs.executor import execute_job
from strix.jobs.factory import build_artifact_sink, build_job_store
from strix.jobs.models import JobState
from strix.jobs.store import JobStore, derive_idempotency_key
from strix.webapi.cloud_settings import CloudSettings
from strix.webapi.limits import check_submission
from strix.webapi.trigger import HttpSelfTrigger, ThreadTrigger, Trigger


class ResearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    as_of: str | None = None


class ExecuteRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=64)


def create_cloud_app(
    *,
    store: JobStore | None = None,
    settings: CloudSettings | None = None,
    verifier: JWTVerifier | None = None,
    trigger: Trigger | None = None,
    config_loader: Callable[[], AgentConfig] = AgentConfig.load,
    artifact_sink: Any = None,
    env: Mapping[str, str] | None = None,
) -> FastAPI:
    settings = settings or CloudSettings.from_env(env)
    store = store or build_job_store(env)
    sink = artifact_sink if artifact_sink is not None else build_artifact_sink(env)
    verifier = verifier or _verifier_from_env(env)
    trigger = trigger or _default_trigger(store, settings, sink, config_loader)

    app = FastAPI(title="STRIX Research API (cloud)", version=AGENT_VERSION)
    app.state.verifier = verifier
    app.state.auth_dev_mode = settings.auth_dev_mode
    app.state.config_cache = None

    _configure_cors(app, settings)
    _install_security_headers(app)

    def load_config() -> AgentConfig:
        cached: AgentConfig | None = app.state.config_cache
        if cached is None:
            cached = config_loader()
            app.state.config_cache = cached
        return cached

    # -- public ------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "agent_version": AGENT_VERSION}

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        try:
            config = load_config()
        except AgentError as exc:
            return {"configured": False, "error": f"[{error_code(exc)}] {exc}"}
        return {
            "configured": True,
            "model": config.model,
            "pricing_version": config.pricing.pricing_version,
            "max_cost_usd": str(config.max_cost_usd),
            "web_search_enabled": config.web_search_enabled,
            "agent_version": AGENT_VERSION,
            "auth_required": verifier is not None,
        }

    # -- research (authenticated, ownership-scoped) ------------------------

    @app.post("/api/research")
    def submit(
        request: ResearchRequest,
        user: AuthUser = Depends(require_user),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        decision = check_submission(store, settings, user_id=user.id)
        if not decision.allowed:
            headers = (
                {"Retry-After": str(decision.retry_after_seconds)}
                if decision.retry_after_seconds
                else None
            )
            raise HTTPException(status_code=429, detail=decision.reason, headers=headers)

        key = (idempotency_key or "").strip() or derive_idempotency_key(
            user.id, request.question, request.as_of
        )
        job, created = store.create_job(
            user_id=user.id,
            question=request.question,
            as_of=request.as_of,
            idempotency_key=key,
            max_attempts=settings.max_job_attempts,
        )
        if created:
            trigger.trigger(job.id)
        return JSONResponse(
            content={"research_id": job.id, "status": job.status.value, "created": created}
        )

    @app.get("/api/research/{research_id}")
    def status(research_id: str, user: AuthUser = Depends(require_user)) -> JSONResponse:
        job = store.get_job(research_id, user_id=user.id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown research id")
        return JSONResponse(content=job.public())

    @app.post("/api/research/{research_id}/cancel")
    def cancel(research_id: str, user: AuthUser = Depends(require_user)) -> dict[str, bool]:
        return {"cancelled": store.request_cancel(research_id, user_id=user.id)}

    @app.post("/api/research/{research_id}/retry")
    def retry(research_id: str, user: AuthUser = Depends(require_user)) -> JSONResponse:
        job = store.reopen_for_retry(research_id, user_id=user.id)
        if job is None:
            existing = store.get_job(research_id, user_id=user.id)
            if existing is None:
                raise HTTPException(status_code=404, detail="unknown research id")
            raise HTTPException(status_code=409, detail="job is not in a retryable state")
        trigger.trigger(job.id)
        return JSONResponse(content={"research_id": job.id, "status": job.status.value})

    @app.get("/api/history")
    def history(user: AuthUser = Depends(require_user)) -> JSONResponse:
        jobs = store.list_jobs(user_id=user.id, limit=50)
        return JSONResponse(content={"runs": [j.summary() for j in jobs]})

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str, user: AuthUser = Depends(require_user)) -> JSONResponse:
        job = store.get_job_by_run_id(run_id, user_id=user.id)
        if job is None or job.result is None:
            raise HTTPException(status_code=404, detail="unknown run id")
        return JSONResponse(
            content={
                "run_id": run_id,
                "answer": job.result.get("answer"),
                "usage": job.result.get("usage"),
                "created_at": job.public()["created_at"],
            }
        )

    @app.get("/api/runs/{run_id}/evidence")
    def run_evidence(run_id: str, user: AuthUser = Depends(require_user)) -> JSONResponse:
        job = store.get_job_by_run_id(run_id, user_id=user.id)
        if job is None or job.result is None:
            raise HTTPException(status_code=404, detail="unknown run id")
        return JSONResponse(
            content={
                "run_id": run_id,
                "evidence": job.result.get("evidence", []),
                "claims": job.result.get("claims", []),
                "manifest": job.result.get("manifest"),
            }
        )

    @app.get("/api/runs/{run_id}/replay")
    def run_replay(run_id: str, user: AuthUser = Depends(require_user)) -> JSONResponse:
        job = store.get_job_by_run_id(run_id, user_id=user.id)
        if job is None or job.result is None:
            raise HTTPException(status_code=404, detail="unknown run id")
        return JSONResponse(content=_replay(run_id, job.result, sink))

    # -- internal execution (shared-secret) -------------------------------

    @app.post("/api/jobs/execute")
    def jobs_execute(
        body: ExecuteRequest,
        x_strix_internal: str | None = Header(default=None, alias="x-strix-internal"),
    ) -> dict[str, Any]:
        _require_internal(settings, x_strix_internal)
        try:
            config = load_config()
        except AgentError:
            config = None
        outcome = execute_job(
            body.job_id,
            store=store,
            config=config,
            config_loader=config_loader,
            artifact_sink=sink,
            lease_seconds=settings.lease_seconds,
            deadline_seconds=settings.deadline_seconds,
        )
        return {
            "job_id": outcome.job_id,
            "claimed": outcome.claimed,
            "status": outcome.status.value if outcome.status else None,
        }

    # -- cron recovery sweeper (cron-secret) ------------------------------

    @app.get("/api/jobs/sweep")
    @app.post("/api/jobs/sweep")
    def jobs_sweep(request: Request) -> dict[str, Any]:
        _require_cron(settings, request)
        return _sweep(store, trigger, now=datetime.now(UTC))

    _mount_static(app)
    return app


# -- replay / sweep helpers ------------------------------------------------


def _replay(run_id: str, result: Mapping[str, Any], sink: Any) -> dict[str, Any]:
    """Re-verify a run's claims. Full byte-level replay requires the stored
    bundle; otherwise the recorded verdicts are reported (reverified=false)."""
    ref = result.get("artifact_ref")
    if ref and hasattr(sink, "download_run"):
        try:
            from strix.agent.replay import replay_agent_run

            with tempfile.TemporaryDirectory(prefix="strix-replay-") as tmp:
                state_dir = Path(tmp)
                restored = sink.download_run(ref, state_dir)
                outcome = replay_agent_run(restored, state_dir)
                return {
                    "run_id": run_id,
                    "reverified": True,
                    "passed": outcome.passed,
                    "claims": [
                        {
                            "claim_id": c.claim_id,
                            "stored_status": c.stored_status,
                            "recomputed_status": c.recomputed_status,
                            "matches": c.matches,
                        }
                        for c in outcome.claims
                    ],
                }
        except Exception as exc:
            return _recorded_verdicts(
                run_id, result, note=f"replay unavailable: {type(exc).__name__}"
            )
    return _recorded_verdicts(
        run_id, result, note="raw bundle not stored; recorded verdicts only"
    )


def _recorded_verdicts(run_id: str, result: Mapping[str, Any], *, note: str) -> dict[str, Any]:
    claims = result.get("claims", []) or []
    return {
        "run_id": run_id,
        "reverified": False,
        "note": note,
        "manifest": result.get("manifest"),
        "claims": [
            {
                "claim_id": c.get("claim_id") or c.get("id"),
                "stored_status": (c.get("verification") or {}).get("status"),
            }
            for c in claims
            if isinstance(c, dict)
        ],
    }


def _sweep(store: JobStore, trigger: Trigger, *, now: datetime) -> dict[str, Any]:
    """Recover queued-but-untriggered and stale-running jobs; time out the stuck.

    A ``running`` job whose lease expired *and* whose absolute deadline passed is
    marked ``timed_out`` — no verified claims are invented. One whose lease
    expired but is still within deadline is re-triggered for a bounded retry.
    """
    stale = store.find_stale(now=now, limit=20)
    retriggered = 0
    timed_out = 0
    for job in stale:
        if job.status is JobState.RUNNING and job.deadline_passed(now=now):
            # Reclaim the expired lease so we can set a terminal state, then
            # time it out if retries are exhausted (else leave queued to retry).
            from strix.jobs.store import new_worker_id

            worker = new_worker_id()
            claimed = store.claim_for_execution(
                job.id, worker_id=worker, lease_seconds=30, deadline_seconds=30
            )
            if claimed is None:
                continue
            if claimed.attempt >= claimed.max_attempts:
                store.finish_job(
                    job.id,
                    worker_id=worker,
                    status=JobState.TIMED_OUT,
                    error="execution exceeded its deadline",
                )
                timed_out += 1
            else:
                store.requeue_for_retry(
                    job.id, worker_id=worker, error="recovered after stale lease"
                )
                trigger.trigger(job.id)
                retriggered += 1
        else:
            trigger.trigger(job.id)
            retriggered += 1
    return {"swept": len(stale), "retriggered": retriggered, "timed_out": timed_out}


# -- construction helpers --------------------------------------------------


def _verifier_from_env(env: Mapping[str, str] | None) -> JWTVerifier | None:
    import os

    source = env if env is not None else os.environ
    try:
        return JWTVerifier.from_env(source)
    except AuthConfigError:
        return None


def _default_trigger(
    store: JobStore,
    settings: CloudSettings,
    sink: Any,
    config_loader: Callable[[], AgentConfig],
) -> Trigger:
    if settings.self_base_url and settings.internal_secret:
        return HttpSelfTrigger(
            base_url=settings.self_base_url, internal_secret=settings.internal_secret
        )
    return ThreadTrigger(
        store=store,
        config_loader=config_loader,
        artifact_sink=sink,
        lease_seconds=settings.lease_seconds,
        deadline_seconds=settings.deadline_seconds,
    )


def _require_internal(settings: CloudSettings, presented: str | None) -> None:
    if not settings.internal_secret:
        raise HTTPException(status_code=404, detail="not found")
    if not presented or not hmac.compare_digest(presented, settings.internal_secret):
        raise HTTPException(status_code=401, detail="unauthorized")


def _require_cron(settings: CloudSettings, request: Request) -> None:
    if not settings.cron_secret:
        raise HTTPException(status_code=404, detail="not found")
    header = request.headers.get("authorization", "")
    expected = f"Bearer {settings.cron_secret}"
    if not hmac.compare_digest(header, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


def _configure_cors(app: FastAPI, settings: CloudSettings) -> None:
    origins = list(settings.allowed_origins)
    if settings.auth_dev_mode:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
            allow_methods=["*"],
            allow_headers=["*"],
        )
    elif origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        )
    # Same-origin production needs no CORS middleware at all.


def _install_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        return response


def _mount_static(app: FastAPI) -> None:
    import os

    dist = Path(os.environ.get("STRIX_WEB_DIST", "web/dist"))
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="web")


# Module-level app for uvicorn / the Vercel entrypoint. Built lazily-safe: no
# config or network access happens at import time.
app = create_cloud_app()
