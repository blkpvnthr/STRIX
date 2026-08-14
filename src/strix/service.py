"""Thin versioned STRIX service and durable single-process scheduler.

Authentication is intentionally delegated to the BLKPVNTHR.OS gateway. The
service requires a shared internal token and tenant/user headers supplied only
by that authenticated gateway; browsers must never call it directly.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from pydantic import ValidationError

from strix import __version__
from strix.canonical import pretty_json_bytes
from strix.market.engine import MarketResearchEngine
from strix.market.models import ResearchMandate


class JobRegistry:
    """Append-safe durable jobs with bounded concurrency and restart recovery."""

    def __init__(self, state_dir: Path, dataset_path: Path, concurrency: int = 1) -> None:
        self.state_dir = state_dir
        self.dataset_path = dataset_path
        self.path = state_dir / "service" / "jobs.json"
        self.lock = threading.Lock()
        self.semaphore = threading.BoundedSemaphore(concurrency)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._recover()

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        return cast(dict[str, dict[str, Any]], json.loads(self.path.read_text(encoding="utf-8")))

    def _write(self, jobs: dict[str, dict[str, Any]]) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(pretty_json_bytes(jobs))
        os.replace(temporary, self.path)

    def _recover(self) -> None:
        with self.lock:
            jobs = self._read()
            for job in jobs.values():
                if job["status"] == "RUNNING":
                    job["status"] = "QUEUED"
                    job["recovered_after_restart"] = True
            self._write(jobs)

    def submit(self, tenant_id: str, user_id: str, mandate: ResearchMandate) -> dict[str, Any]:
        idempotency = f"{tenant_id}:{mandate.mandate_id}:{mandate.version}"
        with self.lock:
            jobs = self._read()
            existing = next(
                (
                    job
                    for job in jobs.values()
                    if job["idempotency_key"] == idempotency
                    and job["status"] in {"QUEUED", "RUNNING", "COMPLETED"}
                ),
                None,
            )
            if existing:
                return existing
            job_id = "JOB-" + uuid.uuid4().hex[:16].upper()
            job = {
                "job_id": job_id,
                "campaign_id": None,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "status": "QUEUED",
                "stage": "mandate",
                "mandate": mandate.model_dump(mode="json"),
                "idempotency_key": idempotency,
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "attempts": 0,
                "safe_error_code": None,
            }
            jobs[job_id] = job
            self._write(jobs)
        threading.Thread(target=self._execute, args=(job_id,), daemon=True).start()
        return job

    def _execute(self, job_id: str) -> None:
        with self.semaphore:
            self._update(job_id, status="RUNNING", stage="data", attempts_delta=1)
            try:
                job = self.get_internal(job_id)
                result = MarketResearchEngine(self.state_dir / "runs").run_offline_campaign(
                    ResearchMandate.model_validate(job["mandate"]),
                    self.dataset_path,
                    retrieved_at=datetime.now(UTC),
                )
                self._update(
                    job_id,
                    status="COMPLETED",
                    stage="monitoring",
                    campaign_id=result.campaign_id,
                    result=result.model_dump(mode="json"),
                )
            except Exception:
                self._update(
                    job_id,
                    status="FAILED",
                    stage="failed",
                    safe_error_code="RESEARCH_EXECUTION_FAILED",
                )

    def _update(self, job_id: str, *, attempts_delta: int = 0, **changes: Any) -> None:
        with self.lock:
            jobs = self._read()
            jobs[job_id].update(changes)
            jobs[job_id]["attempts"] += attempts_delta
            jobs[job_id]["updated_at"] = datetime.now(UTC).isoformat()
            self._write(jobs)

    def get_internal(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            return self._read()[job_id]

    def list_for(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        with self.lock:
            return [
                job
                for job in self._read().values()
                if job["tenant_id"] == tenant_id and job["user_id"] == user_id
            ]

    def get_for(self, job_id: str, tenant_id: str, user_id: str) -> dict[str, Any] | None:
        job = self.get_internal(job_id) if job_id in self._read() else None
        return job if job and job["tenant_id"] == tenant_id and job["user_id"] == user_id else None

    def cancel(self, job_id: str, tenant_id: str, user_id: str) -> bool:
        job = self.get_for(job_id, tenant_id, user_id)
        if not job or job["status"] not in {"QUEUED"}:
            return False
        self._update(job_id, status="CANCELLED", stage="cancelled")
        return True


class StrixHandler(BaseHTTPRequestHandler):
    registry: JobRegistry
    internal_token: str
    research_enabled: bool
    scheduler_enabled: bool
    autonomous_enabled: bool
    paper_trading_enabled: bool
    server_version = "STRIX/" + __version__

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def _dispatch(self, method: str) -> None:
        correlation_id = self.headers.get("X-Correlation-ID", uuid.uuid4().hex)
        path = urlsplit(self.path).path
        if path == "/health":
            return self._json(HTTPStatus.OK, {"status": "ok", "correlation_id": correlation_id})
        if path == "/ready":
            status = HTTPStatus.OK if self.research_enabled else HTTPStatus.SERVICE_UNAVAILABLE
            return self._json(status, {"ready": self.research_enabled})
        identity = self._identity()
        if identity is None:
            return self._json(
                HTTPStatus.UNAUTHORIZED, {"error": "unauthorized", "correlation_id": correlation_id}
            )
        tenant_id, user_id, role = identity
        if path == "/v1/capabilities" and method == "GET":
            return self._json(
                HTTPStatus.OK,
                {
                    "version": __version__,
                    "research_enabled": self.research_enabled,
                    "scheduler_enabled": self.scheduler_enabled,
                    "autonomous_research_enabled": self.autonomous_enabled,
                    "paper_trading": self.paper_trading_enabled,
                    "real_trading": False,
                },
            )
        if path == "/v1/research/campaigns" and method == "GET":
            return self._json(
                HTTPStatus.OK, {"campaigns": self.registry.list_for(tenant_id, user_id)}
            )
        if path == "/v1/research/campaigns" and method == "POST":
            if not self.research_enabled:
                return self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "research_disabled"})
            body = self._body()
            try:
                mandate = ResearchMandate.model_validate(body.get("mandate", body))
            except (ValidationError, AttributeError):
                return self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": "invalid_mandate"})
            return self._json(
                HTTPStatus.ACCEPTED, self.registry.submit(tenant_id, user_id, mandate)
            )
        if path.startswith("/v1/research/campaigns/"):
            parts = path.split("/")
            job_id = parts[4]
            job = self.registry.get_for(job_id, tenant_id, user_id)
            if job is None:
                return self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            if len(parts) == 6 and parts[5] == "cancel" and method == "POST":
                return self._json(
                    HTTPStatus.OK
                    if self.registry.cancel(job_id, tenant_id, user_id)
                    else HTTPStatus.CONFLICT,
                    {"cancelled": job["status"] == "QUEUED"},
                )
            return self._json(HTTPStatus.OK, job)
        if path == "/v1/research/scheduler" and method == "GET":
            return self._json(
                HTTPStatus.OK,
                {"enabled": self.scheduler_enabled, "cadence": "manual", "bounded_concurrency": 1},
            )
        if path == "/v1/research/scheduler" and method == "PATCH":
            if role != "admin":
                return self._json(HTTPStatus.FORBIDDEN, {"error": "admin_required"})
            return self._json(HTTPStatus.CONFLICT, {"error": "restart_with_server_controlled_flag"})
        return self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _identity(self) -> tuple[str, str, str] | None:
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        tenant = self.headers.get("X-STRIX-Tenant")
        user = self.headers.get("X-STRIX-User")
        role = self.headers.get("X-STRIX-Role", "user")
        if not token or token != self.internal_token or not tenant or not user:
            return None
        return tenant, user, role

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 64_000:
            raise ValueError("payload too large")
        return json.loads(self.rfile.read(length)) if length else {}

    def _json(self, status: HTTPStatus, payload: object) -> None:
        body = pretty_json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def serve() -> None:
    state_dir = Path(os.environ.get("STRIX_STATE_DIR", "research_runs"))
    dataset = Path(os.environ.get("STRIX_OFFLINE_DATASET", "fixtures/daily-bars.csv"))
    token = os.environ.get("STRIX_INTERNAL_TOKEN")
    if not token:
        raise RuntimeError("STRIX_INTERNAL_TOKEN is required")
    StrixHandler.registry = JobRegistry(
        state_dir, dataset, int(os.environ.get("STRIX_MAX_CONCURRENCY", "1"))
    )
    StrixHandler.internal_token = token
    StrixHandler.research_enabled = (
        os.environ.get("STRIX_RESEARCH_ENABLED", "false").lower() == "true"
    )
    StrixHandler.scheduler_enabled = (
        os.environ.get("STRIX_RESEARCH_SCHEDULER_ENABLED", "false").lower() == "true"
    )
    StrixHandler.autonomous_enabled = (
        os.environ.get("STRIX_AUTONOMOUS_RESEARCH_ENABLED", "false").lower() == "true"
    )
    StrixHandler.paper_trading_enabled = (
        os.environ.get("STRIX_PAPER_TRADING_ENABLED", "false").lower() == "true"
    )
    address = (os.environ.get("STRIX_HOST", "127.0.0.1"), int(os.environ.get("STRIX_PORT", "8765")))
    ThreadingHTTPServer(address, StrixHandler).serve_forever()


if __name__ == "__main__":
    serve()
