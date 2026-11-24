"""Tests for conversational memory threads (spec §10)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from strix.agent.memory import (
    MAX_CONTEXT_TURNS,
    ConversationTurn,
    ThreadStore,
    turn_from_response,
)
from strix.agent.models import (
    MarketAssessment,
    MarketStance,
    ResearchAnswer,
    ResearchResponse,
)

_NOW = datetime(2026, 11, 23, tzinfo=UTC)


def _turn(i: int, *, stance: str | None = None) -> ConversationTurn:
    return ConversationTurn(
        run_id=f"RUN-{i}",
        question=f"question {i}",
        intent="predictive",
        direct_answer=f"answer {i}",
        stance=stance,
        horizon="next session",
        securities=("SPY",),
        created_at=_NOW.isoformat(),
    )


def test_empty_thread_has_no_prior_context(tmp_path: Path) -> None:
    store = ThreadStore(tmp_path)
    thread = store.load("TH-abc")
    assert thread.turns == ()
    assert thread.context().has_prior is False


def test_append_persists_and_reloads(tmp_path: Path) -> None:
    store = ThreadStore(tmp_path)
    store.append("TH-abc", _turn(1, stance="bearish"))
    reloaded = store.load("TH-abc")
    assert len(reloaded.turns) == 1
    assert reloaded.turns[0].run_id == "RUN-1"
    assert reloaded.turns[0].stance == "bearish"


def test_context_carries_securities_and_last_stance(tmp_path: Path) -> None:
    store = ThreadStore(tmp_path)
    store.append("TH-abc", _turn(1, stance="bearish"))
    store.append("TH-abc", _turn(2, stance="mixed"))
    ctx = store.load("TH-abc").context()
    assert ctx.has_prior is True
    assert ctx.securities == ("SPY",)
    assert ctx.last_stance == "mixed"
    assert ctx.last_horizon == "next session"
    assert "PRIOR CONVERSATION" in ctx.summary
    assert "never cite as evidence" in ctx.summary


def test_context_is_bounded(tmp_path: Path) -> None:
    store = ThreadStore(tmp_path)
    for i in range(MAX_CONTEXT_TURNS + 4):
        store.append("TH-abc", _turn(i))
    recent = store.load("TH-abc").context()
    # The summary only reflects the most recent MAX_CONTEXT_TURNS questions.
    assert recent.summary.count("question ") == MAX_CONTEXT_TURNS


def test_invalid_thread_id_rejected(tmp_path: Path) -> None:
    store = ThreadStore(tmp_path)
    with pytest.raises(ValueError):
        store.load("../escape")
    with pytest.raises(ValueError):
        store.load("not-a-thread")


def test_turn_from_response_reduces_assessment(tmp_path: Path) -> None:
    answer = ResearchAnswer(
        run_id="RUN-9",
        question="how will the market perform tomorrow?",
        data_as_of=_NOW,
        summary="s",
        verified_claims=(),
        unresolved_claims=(),
        evidence=(),
        limitations=(),
        disclaimer="d",
    )
    response = ResearchResponse(
        run_id="RUN-9",
        question=answer.question,
        question_intent="predictive",
        direct_answer="No single session can be predicted.",
        analysis="",
        market_assessment=MarketAssessment(
            stance=MarketStance.BEARISH,
            horizon="next session",
            analysis_timestamp=_NOW,
        ),
        verified_answer=answer,
    )
    turn = turn_from_response(response, securities=("SPY", "QQQ"), now=_NOW)
    assert turn.stance == "bearish"
    assert turn.horizon == "next session"
    assert turn.securities == ("SPY", "QQQ")
    assert turn.run_id == "RUN-9"


def test_prior_context_makes_followup_recognized_end_to_end(tmp_path: Path) -> None:
    from datetime import date

    from tests.agent.agent_fixtures import build_config
    from tests.agent.test_orchestrator import (
        _NOW as ORCH_NOW,
    )
    from tests.agent.test_orchestrator import (
        ConversationalProvider,
        _fake_alpaca,
    )

    from strix.agent.orchestrator import run_research_question

    store = ThreadStore(tmp_path)
    store.append("TH-xyz", _turn(1, stance="bearish"))
    ctx = store.load("TH-xyz").context()
    config = build_config()
    outcome = run_research_question(
        "what about that?",
        config=config,
        state_dir=tmp_path,
        provider=ConversationalProvider(config),  # type: ignore[arg-type]
        alpaca=_fake_alpaca(),
        as_of=date(2026, 11, 22),
        clock=lambda: ORCH_NOW,
        prior_context=ctx,
    )
    assert outcome.response is not None
    # The short pronoun question is understood as a follow-up because a thread exists.
    assert outcome.response.question_intent == "follow_up"
