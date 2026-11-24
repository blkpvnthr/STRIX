"""Tests for the research API service + app wiring (offline; no sockets).

The HTTP transport layer is exercised live against the running uvicorn server in
the acceptance phase; here we test the service (threads, no sockets), the
request model's validation, and that the app registers the expected routes.
"""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from tests.agent.agent_fixtures import build_config

from strix.agent.budget import BudgetSnapshot
from strix.agent.contracts import TokenUsage
from strix.agent.models import ResearchAnswer
from strix.agent.orchestrator import ResearchOutcome
from strix.webapi.app import ResearchRequest, create_app
from strix.webapi.service import ResearchService


def _fake_outcome(question: str, run_dir: Path, *, cancelled: bool = False) -> ResearchOutcome:
    answer = ResearchAnswer(
        run_id="RUN-20261122-001",
        question=question,
        data_as_of=None,
        summary="A verified summary.",
        verified_claims=(),
        unresolved_claims=(),
        evidence=(),
        limitations=("example limitation",),
        disclaimer="not advice",
    )
    usage = BudgetSnapshot(
        model_calls=2,
        tool_calls=1,
        usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        estimated_cost_usd=Decimal("0.001"),
        tool_cost_usd=Decimal("0"),
        pricing_version="2026-11-22",
        elapsed_seconds=Decimal("1.5"),
        exhausted=cancelled,
        exhausted_reason="cancelled by user" if cancelled else None,
    )
    return ResearchOutcome(
        answer=answer, run_id="RUN-20261122-001", run_dir=run_dir, usage=usage, claims=()
    )


def _service(tmp_path: Path) -> ResearchService:
    def fake_runner(question: str, **kwargs: Any) -> ResearchOutcome:
        progress = kwargs.get("progress")
        if progress:
            progress("Researching")
            progress("Persisting research artifacts")
        return _fake_outcome(question, tmp_path)

    return ResearchService(tmp_path, config_loader=lambda: build_config(), runner=fake_runner)


def _poll(service: ResearchService, rid: str) -> Any:
    for _ in range(200):
        job = service.get(rid)
        assert job is not None
        if job.status in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_submit_runs_to_completion(tmp_path: Path) -> None:
    service = _service(tmp_path)
    job = service.submit("What is SPY volatility?")
    done = _poll(service, job.id)
    assert done.status == "completed"
    assert done.result is not None
    assert done.result["answer"]["summary"] == "A verified summary."
    assert "Researching" in done.events
    assert done.public()["research_id"] == job.id


def _fake_outcome_with_response(question: str, run_dir: Path) -> ResearchOutcome:
    from datetime import UTC, datetime

    from strix.agent.models import MarketAssessment, MarketStance, ResearchResponse

    base = _fake_outcome(question, run_dir)
    response = ResearchResponse(
        run_id=base.run_id,
        question=question,
        question_intent="predictive",
        direct_answer="No single session can be predicted.",
        analysis="",
        market_assessment=MarketAssessment(
            stance=MarketStance.BEARISH,
            horizon="next session",
            analysis_timestamp=datetime(2026, 11, 23, tzinfo=UTC),
        ),
        verified_answer=base.answer,
    )
    return ResearchOutcome(
        answer=base.answer,
        run_id=base.run_id,
        run_dir=run_dir,
        usage=base.usage,
        claims=(),
        response=response,
    )


def test_result_includes_response_and_thread(tmp_path: Path) -> None:
    def runner(question: str, **kwargs: Any) -> ResearchOutcome:
        return _fake_outcome_with_response(question, tmp_path)

    service = ResearchService(tmp_path, config_loader=lambda: build_config(), runner=runner)
    job = service.submit("how will the market perform tomorrow?")
    done = _poll(service, job.id)
    assert done.status == "completed"
    assert done.result is not None
    assert done.result["response"]["direct_answer"] == "No single session can be predicted."
    assert done.result["response"]["market_assessment"]["stance"] == "bearish"
    assert done.result["thread_id"] == job.thread_id


def test_thread_context_carries_into_followup(tmp_path: Path) -> None:
    seen: list[Any] = []

    def runner(question: str, **kwargs: Any) -> ResearchOutcome:
        seen.append(kwargs.get("prior_context"))
        return _fake_outcome_with_response(question, tmp_path)

    service = ResearchService(tmp_path, config_loader=lambda: build_config(), runner=runner)
    first = service.submit("how will the market perform tomorrow?")
    _poll(service, first.id)
    second = service.submit("what would invalidate that?", thread_id=first.thread_id)
    _poll(service, second.id)
    # The first run had no prior context; the second sees the recorded first turn.
    assert seen[0] is None or not getattr(seen[0], "has_prior", False)
    assert getattr(seen[1], "has_prior", False) is True
    assert seen[1].last_stance == "bearish"


def test_config_error_marks_job_failed(tmp_path: Path) -> None:
    from strix.errors import AgentConfigError

    def bad_loader() -> Any:
        raise AgentConfigError("no key")

    service = ResearchService(tmp_path, config_loader=bad_loader, runner=lambda *a, **k: None)
    job = service.submit("q")
    done = _poll(service, job.id)
    assert done.status == "failed"
    assert "no key" in (done.error or "")


def test_cancel_unknown_returns_false(tmp_path: Path) -> None:
    assert _service(tmp_path).cancel("RQ-missing") is False


def test_get_unknown_returns_none(tmp_path: Path) -> None:
    assert _service(tmp_path).get("RQ-missing") is None


def test_history_empty_on_fresh_state(tmp_path: Path) -> None:
    assert _service(tmp_path).history() == []


def test_run_detail_unknown_returns_none(tmp_path: Path) -> None:
    assert _service(tmp_path).run_detail("RUN-20200101-001") is None


def test_request_model_rejects_empty_question() -> None:
    with pytest.raises(ValidationError):
        ResearchRequest(question="")


def test_app_registers_expected_routes(tmp_path: Path) -> None:
    app = create_app(service=_service(tmp_path))
    paths = {getattr(r, "path", None) for r in app.routes}
    for expected in (
        "/api/health",
        "/api/meta",
        "/api/research",
        "/api/research/{research_id}",
        "/api/research/{research_id}/cancel",
        "/api/history",
        "/api/runs/{run_id}",
    ):
        assert expected in paths
