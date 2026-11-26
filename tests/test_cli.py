"""CLI: happy paths, cancellation, replay command, safety, purity."""

from __future__ import annotations

import builtins
import io
from pathlib import Path

import pytest

from strix.cli import main
from strix.models import Metric
from strix.pipeline import DeterministicOutcome
from strix.reasoning.deterministic_demo import DeterministicDemoReasoner
from strix.sources import edgar
from tests.conftest import FixedClock

DATA_DIR = Path(__file__).parent / "data"


def feeder(lines: list[str]):
    """Injected input function: yields lines, then behaves like EOF."""
    iterator = iter(lines)

    def read() -> str:
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError from None

    return read


def run_cli(
    inputs: list[str],
    state_dir: Path,
    clock: FixedClock,
    argv: list[str] | None = None,
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(
        argv if argv is not None else ["--state-dir", str(state_dir)],
        input_fn=feeder(inputs),
        stdout=out,
        stderr=err,
        clock=clock,
        environ={},
    )
    return code, out.getvalue(), err.getvalue()


def run_dirs(state_dir: Path) -> list[str]:
    if not state_dir.is_dir():
        return []
    return sorted(p.name for p in state_dir.iterdir() if p.name.startswith("RUN-"))


class TestHappyPath:
    def test_demo_defaults_produce_verified_finding(
        self, state_dir: Path, clock: FixedClock
    ) -> None:
        code, out, err = run_cli(["", "", "", ""], state_dir, clock)
        assert code == 0, err
        assert "STRIX" in out
        assert "Demonstration Company" in out
        assert "Synthetic bundled fixture" in out
        assert "[6/6] Verifying claim" in out
        assert (
            "Operating margin increased from 8.4% to 10.1%, an\n"
            "improvement of 1.7 percentage points." in out
        )
        assert "Verification: Passed" in out
        assert "Research run: RUN-20260808-001" in out
        assert "Synthetic demonstration data — not investment advice." in out
        assert run_dirs(state_dir) == ["RUN-20260808-001"]

    def test_finding_cites_evidence_ids(self, state_dir: Path, clock: FixedClock) -> None:
        code, out, _ = run_cli(["", "", "", ""], state_dir, clock)
        assert code == 0
        assert "[EV-" in out

    def test_invalid_then_valid_inputs_reprompt(self, state_dir: Path, clock: FixedClock) -> None:
        code, out, _ = run_cli(
            ["$$$", "DEMO", "", "not-a-date", "2026-08-08", ""], state_dir, clock
        )
        assert code == 0
        assert "Please enter a ticker symbol" in out
        assert "Please enter a date as YYYY-MM-DD." in out


class TestCancellation:
    def test_decline_confirmation_exits_zero_without_run(
        self, state_dir: Path, clock: FixedClock
    ) -> None:
        code, out, _ = run_cli(["", "", "", "n"], state_dir, clock)
        assert code == 0
        assert "Cancelled. No research run was created." in out
        assert run_dirs(state_dir) == []
        assert "Finding" not in out

    def test_eof_during_prompts_cancels_cleanly(self, state_dir: Path, clock: FixedClock) -> None:
        code, out, _ = run_cli([], state_dir, clock)
        assert code == 0
        assert "Cancelled" in out
        assert not state_dir.exists() or run_dirs(state_dir) == []


class TestReplayCommand:
    def test_replay_of_fresh_run_passes(self, state_dir: Path, clock: FixedClock) -> None:
        code, _, _ = run_cli(["", "", "", ""], state_dir, clock)
        assert code == 0
        code, out, _ = run_cli(
            [],
            state_dir,
            clock,
            argv=["replay", "RUN-20260808-001", "--state-dir", str(state_dir)],
        )
        assert code == 0
        assert "Replay verification" in out
        assert "Result: Deterministic replay passed" in out
        assert "MISMATCH" not in out

    def test_replay_detects_tampered_raw(self, state_dir: Path, clock: FixedClock) -> None:
        run_cli(["", "", "", ""], state_dir, clock)
        raw = state_dir / "RUN-20260808-001" / "raw" / "demo-company-facts.json"
        raw.write_bytes(raw.read_bytes().replace(b"101000000", b"888000000"))
        code, out, _ = run_cli(
            [],
            state_dir,
            clock,
            argv=["replay", "RUN-20260808-001", "--state-dir", str(state_dir)],
        )
        assert code == 1
        assert "MISMATCH" in out
        assert "Result: Deterministic replay FAILED" in out

    def test_traversal_run_id_is_rejected(self, state_dir: Path, clock: FixedClock) -> None:
        code, _, err = run_cli(
            [],
            state_dir,
            clock,
            argv=["replay", "../../etc", "--state-dir", str(state_dir)],
        )
        assert code == 1
        assert "Error:" in err
        assert "invalid run ID" in err

    def test_unknown_run_id_fails_cleanly(self, state_dir: Path, clock: FixedClock) -> None:
        state_dir.mkdir(parents=True)
        code, _, err = run_cli(
            [],
            state_dir,
            clock,
            argv=["replay", "RUN-19990101-001", "--state-dir", str(state_dir)],
        )
        assert code == 1
        assert "no completed run" in err


class TestStateDirSelection:
    def test_environ_variable_respected(self, tmp_path: Path, clock: FixedClock) -> None:
        env_dir = tmp_path / "env-runs"
        out = io.StringIO()
        code = main(
            [],
            input_fn=feeder(["", "", "", ""]),
            stdout=out,
            stderr=io.StringIO(),
            clock=clock,
            environ={"STRIX_STATE_DIR": str(env_dir)},
        )
        assert code == 0
        assert run_dirs(env_dir) == ["RUN-20260808-001"]


class TestEdgarPath:
    def test_real_ticker_uses_edgar_connector(
        self, state_dir: Path, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        companyfacts = (DATA_DIR / "edgar-companyfacts-sample.json").read_bytes()
        ticker_map = (DATA_DIR / "edgar-company-tickers-sample.json").read_bytes()

        def fake_fetch(url: str, *, user_agent: str = edgar.USER_AGENT) -> bytes:
            return ticker_map if url == edgar.TICKER_MAP_URL else companyfacts

        monkeypatch.setattr(edgar, "fetch_url", fake_fetch)
        code, out, err = run_cli(["XMPL", "", "", ""], state_dir, clock)
        assert code == 0, err
        assert "Fetching SEC EDGAR company facts for XMPL" in out
        assert "Example Filer Inc." in out
        assert "Operating margin increased from 30.0% to 31.0%" in out
        assert "Source: SEC EDGAR company facts, as filed." in out
        assert run_dirs(state_dir) == ["RUN-20260808-001"]

    def test_unknown_ticker_fails_cleanly(
        self, state_dir: Path, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ticker_map = (DATA_DIR / "edgar-company-tickers-sample.json").read_bytes()
        monkeypatch.setattr(
            edgar, "fetch_url", lambda url, *, user_agent=edgar.USER_AGENT: ticker_map
        )
        code, _, err = run_cli(["NOPE", "", "", ""], state_dir, clock)
        assert code == 1
        assert "not found in the SEC EDGAR ticker map" in err
        assert run_dirs(state_dir) == []


class TestReasonerIsolation:
    def test_reasoner_reads_no_files_or_terminal(
        self,
        outcome: DeterministicOutcome,
        spec,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The reasoner must work with every file-open and stdin read blocked:
        # its only inputs are the spec and the evidence bundle.
        def no_open(*args: object, **kwargs: object):
            raise AssertionError("the reasoner must not open files")

        def no_stdin(*args: object, **kwargs: object):
            raise AssertionError("the reasoner must not read the terminal")

        monkeypatch.setattr(builtins, "open", no_open)
        monkeypatch.setattr(builtins, "input", no_stdin)
        claims = DeterministicDemoReasoner().analyze(spec, list(outcome.evidence))
        assert len(claims) == 1
        assert claims[0].evidence_ids == tuple(item.evidence_id for item in outcome.evidence)
        assert {a.metric for a in claims[0].numeric_assertions} == {
            Metric.OPERATING_MARGIN,
            Metric.OPERATING_MARGIN_CHANGE_PP,
        }


def test_render_ask_assurance_withholds_on_rejected_conclusion() -> None:
    """Step 8: the CLI enforcement decision is False (withhold) for a non-released run and
    True (release) for an authorized one — so the body is withheld when the gateway rejects."""
    import io as _io
    from decimal import Decimal

    from strix.agent.budget import BudgetSnapshot
    from strix.agent.contracts import TokenUsage
    from strix.agent.models import (
        AgentClaim,
        AgentClaimType,
        AgentVerificationStatus,
        ClaimVerification,
        ConclusionVerification,
        ResearchAnswer,
    )
    from strix.agent.orchestrator import ResearchOutcome
    from strix.cli import _render_ask_assurance

    def _outcome(cv: ConclusionVerification) -> ResearchOutcome:
        claim = AgentClaim(
            claim_id="CL-1", claim_type=AgentClaimType.OBSERVATION, statement="f",
            evidence_ids=("E1",),
            verification=ClaimVerification(status=AgentVerificationStatus.VERIFIED),
        )
        answer = ResearchAnswer(
            run_id="RUN-X", question="q", data_as_of=None, summary="s",
            verified_claims=(claim,), unresolved_claims=(), evidence=(),
            limitations=(), disclaimer="d", conclusion_verification=cv,
        )
        usage = BudgetSnapshot(
            model_calls=1, tool_calls=0, usage=TokenUsage(), estimated_cost_usd=Decimal("0"),
            tool_cost_usd=Decimal("0"), pricing_version="v1", elapsed_seconds=Decimal("0"),
            exhausted=False, exhausted_reason=None,
        )
        return ResearchOutcome(
            answer=answer, run_id="RUN-X", run_dir=Path("/tmp/none"), usage=usage, claims=(claim,)
        )

    rejected = _render_ask_assurance(
        _outcome(ConclusionVerification(outcome="rejected")), _io.StringIO()
    )
    admitted = _render_ask_assurance(
        _outcome(ConclusionVerification(outcome="admitted")), _io.StringIO()
    )
    assert rejected is False
    assert admitted is True
