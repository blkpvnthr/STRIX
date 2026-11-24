"""End-to-end HTTP tests for the hosted research API (in-process, no network)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import jwt
from fastapi.testclient import TestClient

from strix.jobs.executor import NullArtifactSink, execute_job
from strix.jobs.local_store import LocalJobStore
from strix.webapi.cloud_app import create_cloud_app
from strix.webapi.cloud_settings import CloudSettings

SECRET = "unit-test-secret-at-least-32-bytes-long!!"


def _tok(sub: str) -> str:
    return jwt.encode(
        {
            "sub": sub,
            "aud": "authenticated",
            "email": f"{sub}@x.com",
            "exp": int(time.time()) + 3600,
        },
        SECRET,
        algorithm="HS256",
    )


@dataclass
class _U:
    exhausted_reason: str | None = None
    estimated_cost_usd: Decimal = Decimal("0.01")
    tool_cost_usd: Decimal = Decimal("0.0")

    def model_dump(self) -> dict[str, Any]:
        return {"estimated_cost_usd": "0.01", "exhausted_reason": self.exhausted_reason}


@dataclass
class _Outcome:
    run_id: str = "RUN-20261124-001"
    run_dir: Path = Path("/nonexistent")
    usage: _U = None  # type: ignore[assignment]
    answer: Any = None
    claims: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        self.usage = self.usage or _U()
        self.answer = self.answer or type("A", (), {"model_dump": lambda self: {"summary": "up"}})()


class _StubTrigger:
    def __init__(self, store: LocalJobStore) -> None:
        self._store = store

    def trigger(self, job_id: str) -> None:
        execute_job(
            job_id,
            store=self._store,
            config=object(),
            runner=lambda *a, **k: _Outcome(),
            artifact_sink=NullArtifactSink(),
        )


def _dev_client() -> tuple[TestClient, LocalJobStore]:
    store = LocalJobStore(":memory:")
    settings = CloudSettings(
        auth_dev_mode=True, rate_limit_per_minute=100, max_concurrent_jobs_per_user=10
    )
    app = create_cloud_app(
        store=store, settings=settings, verifier=None, trigger=_StubTrigger(store)
    )
    return TestClient(app), store


def _auth_client() -> tuple[TestClient, LocalJobStore]:
    from strix.auth.supabase_jwt import JWTVerifier

    store = LocalJobStore(":memory:")
    settings = CloudSettings(
        auth_dev_mode=False, rate_limit_per_minute=100, max_concurrent_jobs_per_user=10
    )
    app = create_cloud_app(
        store=store,
        settings=settings,
        verifier=JWTVerifier(hs256_secret=SECRET),
        trigger=_StubTrigger(store),
    )
    return TestClient(app), store


def test_health_is_public() -> None:
    client, _ = _dev_client()
    assert client.get("/api/health").json()["status"] == "ok"


def test_security_headers_present() -> None:
    client, _ = _dev_client()
    resp = client.get("/api/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"


def test_submit_runs_and_persists() -> None:
    client, _ = _dev_client()
    resp = client.post("/api/research", json={"question": "How is the market?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] is True
    rid = body["research_id"]
    status = client.get(f"/api/research/{rid}").json()
    assert status["status"] == "completed"
    assert status["run_id"] == "RUN-20261124-001"


def test_submission_is_idempotent() -> None:
    client, _ = _dev_client()
    first = client.post("/api/research", json={"question": "repeat"}).json()
    second = client.post("/api/research", json={"question": "repeat"}).json()
    assert first["research_id"] == second["research_id"]
    assert second["created"] is False


def test_history_and_run_detail_and_evidence() -> None:
    client, _ = _dev_client()
    client.post("/api/research", json={"question": "q1"})
    assert len(client.get("/api/history").json()["runs"]) == 1
    detail = client.get("/api/runs/RUN-20261124-001")
    assert detail.status_code == 200
    assert detail.json()["answer"]["summary"] == "up"
    evidence = client.get("/api/runs/RUN-20261124-001/evidence")
    assert evidence.status_code == 200


def test_unconfigured_auth_returns_503() -> None:
    store = LocalJobStore(":memory:")
    app = create_cloud_app(
        store=store,
        settings=CloudSettings(auth_dev_mode=False),
        verifier=None,
        trigger=_StubTrigger(store),
    )
    client = TestClient(app)
    assert client.post("/api/research", json={"question": "q"}).status_code == 503


def test_missing_and_bad_tokens_rejected() -> None:
    client, _ = _auth_client()
    assert client.post("/api/research", json={"question": "q"}).status_code == 401
    bad = {"Authorization": "Bearer not-a-jwt"}
    assert client.post("/api/research", json={"question": "q"}, headers=bad).status_code == 401


def test_user_isolation() -> None:
    client, _ = _auth_client()
    a = client.post(
        "/api/research", json={"question": "qA"}, headers={"Authorization": f"Bearer {_tok('A')}"}
    )
    rid = a.json()["research_id"]
    assert (
        client.get(
            f"/api/research/{rid}", headers={"Authorization": f"Bearer {_tok('A')}"}
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/research/{rid}", headers={"Authorization": f"Bearer {_tok('B')}"}
        ).status_code
        == 404
    )


def test_internal_and_cron_disabled_without_secret() -> None:
    client, _ = _dev_client()
    assert client.post("/api/jobs/execute", json={"job_id": "RQ-x"}).status_code == 404
    assert client.post("/api/jobs/sweep").status_code == 404


def test_rate_limit_enforced() -> None:
    store = LocalJobStore(":memory:")
    settings = CloudSettings(
        auth_dev_mode=True, rate_limit_per_minute=1, max_concurrent_jobs_per_user=10
    )
    app = create_cloud_app(
        store=store, settings=settings, verifier=None, trigger=_StubTrigger(store)
    )
    client = TestClient(app)
    assert client.post("/api/research", json={"question": "a"}).status_code == 200
    resp = client.post("/api/research", json={"question": "b"})
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
