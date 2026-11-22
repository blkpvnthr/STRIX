"""Deterministic replay of a persisted agent run reproduces its verdicts."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from tests.agent.agent_fixtures import build_config
from tests.agent.test_orchestrator import _NOW, ScriptedProvider, _fake_alpaca

from strix.agent.replay import replay_agent_run
from strix.errors import ReplayError

from strix.agent.orchestrator import run_research_question  # isort: skip


def _make_run(tmp_path: Path) -> str:
    config = build_config()
    outcome = run_research_question(
        "What is SPY's recent realized volatility?",
        config=config,
        state_dir=tmp_path,
        provider=ScriptedProvider(config),  # type: ignore[arg-type]
        alpaca=_fake_alpaca(),
        as_of=date(2026, 11, 22),
        clock=lambda: _NOW,
    )
    return outcome.run_id


def test_replay_reproduces_verdicts(tmp_path: Path) -> None:
    run_id = _make_run(tmp_path)
    outcome = replay_agent_run(run_id, tmp_path)
    assert outcome.passed is True
    assert len(outcome.claims) == 1
    claim = outcome.claims[0]
    assert claim.recomputed_status == "verified"
    assert claim.matches is True
    assert claim.recomputed_value == claim.stored_value


def test_replay_rejects_non_agent_run(tmp_path: Path) -> None:
    # A run whose manifest is not mode=agent_research must be refused.
    run_dir = tmp_path / "RUN-20260101-001"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text('{"mode": "engineering"}', encoding="utf-8")
    try:
        replay_agent_run("RUN-20260101-001", tmp_path)
    except ReplayError as exc:
        assert "not an agent_research run" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ReplayError")
