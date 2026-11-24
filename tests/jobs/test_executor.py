"""execute_job: state mapping, bounded retry, duplicate protection, checkpoints."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from strix.errors import AgentConfigError, ProviderTimeoutError
from strix.jobs.executor import execute_job
from strix.jobs.local_store import LocalJobStore
from strix.jobs.models import JobState
from strix.jobs.store import derive_idempotency_key


@dataclass
class _Usage:
    exhausted_reason: str | None
    estimated_cost_usd: Decimal = Decimal("0.01")
    tool_cost_usd: Decimal = Decimal("0.002")

    def model_dump(self) -> dict[str, Any]:
        return {"estimated_cost_usd": str(self.estimated_cost_usd),
                "exhausted_reason": self.exhausted_reason}


@dataclass
class _Answer:
    def model_dump(self) -> dict[str, Any]:
        return {"summary": "the market rose"}


@dataclass
class _Claim:
    def model_dump(self) -> dict[str, Any]:
        return {"claim_id": "C1", "verification": {"status": "VERIFIED"}}


@dataclass
class _Outcome:
    run_id: str
    run_dir: Path
    usage: _Usage
    answer: _Answer
    claims: tuple[_Claim, ...]


def _outcome(run_dir: Path, reason: str | None = None) -> _Outcome:
    return _Outcome(
        run_id="RUN-20261124-001",
        run_dir=run_dir,
        usage=_Usage(reason),
        answer=_Answer(),
        claims=(_Claim(),),
    )


@pytest.fixture
def store() -> LocalJobStore:
    return LocalJobStore(":memory:")


def _job(store: LocalJobStore, q: str = "q") -> str:
    key = derive_idempotency_key("u1", q, None)
    job, _ = store.create_job(
        user_id="u1", question=q, as_of=None, idempotency_key=key, max_attempts=2
    )
    return job.id


def test_completed_run(store: LocalJobStore, tmp_path: Path) -> None:
    job_id = _job(store)
    result = execute_job(
        job_id, store=store, config=object(), runner=lambda *a, **k: _outcome(tmp_path)
    )
    assert result.status is JobState.COMPLETED
    job = store.get_job(job_id)
    assert job.status is JobState.COMPLETED
    assert job.cost_usd == "0.012"
    assert job.result is not None and job.result["answer"]["summary"] == "the market rose"


def test_budget_exhaustion_is_partial(store: LocalJobStore, tmp_path: Path) -> None:
    job_id = _job(store)
    execute_job(
        job_id,
        store=store,
        config=object(),
        runner=lambda *a, **k: _outcome(tmp_path, "model-call budget reached"),
    )
    assert store.get_job(job_id).status is JobState.PARTIAL


def test_cancel_reason_is_cancelled(store: LocalJobStore, tmp_path: Path) -> None:
    job_id = _job(store)
    execute_job(
        job_id,
        store=store,
        config=object(),
        runner=lambda *a, **k: _outcome(tmp_path, "cancelled by user"),
    )
    assert store.get_job(job_id).status is JobState.CANCELLED


def test_transient_failure_retries_then_fails(store: LocalJobStore) -> None:
    job_id = _job(store)

    def flaky(*_a: Any, **_k: Any) -> Any:
        raise ProviderTimeoutError("timeout")

    first = execute_job(job_id, store=store, config=object(), runner=flaky)
    assert first.status is JobState.QUEUED  # requeued
    assert store.get_job(job_id).status is JobState.QUEUED
    execute_job(job_id, store=store, config=object(), runner=flaky)
    assert store.get_job(job_id).status is JobState.FAILED


def test_deterministic_failure_does_not_retry(store: LocalJobStore) -> None:
    job_id = _job(store)

    def bad(*_a: Any, **_k: Any) -> Any:
        raise AgentConfigError("unknown model")

    execute_job(job_id, store=store, config=object(), runner=bad)
    job = store.get_job(job_id)
    assert job.status is JobState.FAILED
    assert job.attempt == 1  # only one attempt, no retry


def test_duplicate_execution_is_noop(store: LocalJobStore, tmp_path: Path) -> None:
    job_id = _job(store)
    execute_job(job_id, store=store, config=object(), runner=lambda *a, **k: _outcome(tmp_path))
    second = execute_job(
        job_id, store=store, config=object(), runner=lambda *a, **k: _outcome(tmp_path)
    )
    assert second.claimed is False


def test_embeds_structured_evidence_and_manifest(store: LocalJobStore, tmp_path: Path) -> None:
    run_dir = tmp_path / "RUN-20261124-001"
    run_dir.mkdir()
    (run_dir / "evidence.json").write_text(json.dumps([{"evidence_id": "E1"}]))
    (run_dir / "manifest.json").write_text(json.dumps({"verified_count": 1}))
    job_id = _job(store)
    execute_job(
        job_id, store=store, config=object(), runner=lambda *a, **k: _outcome(run_dir)
    )
    job = store.get_job(job_id)
    assert job.result is not None
    assert job.result["evidence"] == [{"evidence_id": "E1"}]
    assert job.result["manifest"] == {"verified_count": 1}


def test_config_error_fails_job(store: LocalJobStore) -> None:
    job_id = _job(store)

    def bad_loader() -> Any:
        raise AgentConfigError("no api key")

    execute_job(job_id, store=store, config=None, config_loader=bad_loader)
    assert store.get_job(job_id).status is JobState.FAILED
