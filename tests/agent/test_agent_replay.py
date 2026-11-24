"""Deterministic replay of a persisted agent run reproduces its verdicts."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from tests.agent.agent_fixtures import build_config
from tests.agent.test_orchestrator import (
    _NOW,
    ConversationalProvider,
    ScriptedProvider,
    _fake_alpaca,
)

from strix.agent.replay import replay_agent_run
from strix.errors import ReplayError, RunNotFoundError, RunStoreError

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


def _make_conversational_run(tmp_path: Path) -> tuple[str, Path]:
    config = build_config()
    outcome = run_research_question(
        "how can i expect the market to perform tomorrow?",
        config=config,
        state_dir=tmp_path,
        provider=ConversationalProvider(config),  # type: ignore[arg-type]
        alpaca=_fake_alpaca(),
        as_of=date(2026, 11, 22),
        clock=lambda: _NOW,
    )
    return outcome.run_id, outcome.run_dir


def test_replay_reproduces_verdicts(tmp_path: Path) -> None:
    run_id = _make_run(tmp_path)
    outcome = replay_agent_run(run_id, tmp_path)
    assert outcome.passed is True
    assert len(outcome.claims) == 1
    claim = outcome.claims[0]
    assert claim.recomputed_status == "verified"
    assert claim.matches is True
    assert claim.recomputed_value == claim.stored_value


def test_replay_validates_persisted_response(tmp_path: Path) -> None:
    run_id, _ = _make_conversational_run(tmp_path)
    outcome = replay_agent_run(run_id, tmp_path)
    assert outcome.passed is True
    assert outcome.response is not None
    assert outcome.response.present is True
    assert outcome.response.hash_matches is True
    assert outcome.response.citation_integrity is True
    assert outcome.response.classification_integrity is True
    assert outcome.response.problems == ()


def test_replay_detects_tampered_response_hash(tmp_path: Path) -> None:
    run_id, run_dir = _make_conversational_run(tmp_path)
    path = run_dir / "response.json"
    data = json.loads(path.read_text())
    data["direct_answer"] = data["direct_answer"] + " (tampered)"
    path.write_text(json.dumps(data))
    outcome = replay_agent_run(run_id, tmp_path)
    assert outcome.response is not None
    assert outcome.response.hash_matches is False
    assert outcome.passed is False


def test_replay_detects_misclassified_response(tmp_path: Path) -> None:
    run_id, run_dir = _make_conversational_run(tmp_path)
    path = run_dir / "response.json"
    data = json.loads(path.read_text())
    # Promote a verified supporting fact to a forecast class — must be rejected.
    assert data["supporting_facts"], "expected at least one supporting fact"
    data["supporting_facts"][0]["epistemic_class"] = "forecast"
    path.write_text(json.dumps(data))
    outcome = replay_agent_run(run_id, tmp_path)
    assert outcome.response is not None
    assert outcome.response.classification_integrity is False
    assert outcome.passed is False


def test_replay_tolerates_trailing_zero_difference(tmp_path: Path) -> None:
    # Canonical persistence strips trailing zeros (0.100000 -> 0.1); replay must
    # compare values numerically, not as strings, or it would falsely FAIL.
    from datetime import UTC, datetime
    from decimal import Decimal

    from strix.agent.models import (
        AgentCalculation,
        AgentClaim,
        AgentClaimType,
        AgentEvidence,
        AgentVerificationStatus,
        CalculationMethod,
        ClaimVerification,
        FreshnessStatus,
        Observation,
        ObservationSeries,
        SourceKind,
    )
    from strix.canonical import pretty_json_bytes

    now = datetime(2026, 11, 22, tzinfo=UTC)
    ev = AgentEvidence(
        evidence_id="EV-abc",
        source_type=SourceKind.MARKET_DATA,
        provider="Alpaca",
        source_title="X daily closes",
        retrieved_at=now,
        content_hash="a" * 64,
        freshness_status=FreshnessStatus.CURRENT,
    )
    obs = (
        Observation(at="2026-11-19", value=Decimal("100")),
        Observation(at="2026-11-20", value=Decimal("110")),
    )
    series = ObservationSeries(
        series_id="SER-xyz",
        subject="X",
        concept="close",
        unit="USD",
        observations=obs,
        source_evidence_id=ev.evidence_id,
    )
    claim = AgentClaim(
        claim_id="CL-1",
        claim_type=AgentClaimType.QUANTITATIVE,
        statement="X period return.",
        evidence_ids=(ev.evidence_id,),
        calculation=AgentCalculation(
            method=CalculationMethod.PERIOD_RETURN,
            calculation_version="1.0.0",
            input_series_ids=(series.series_id,),
            claimed_value=Decimal("0.1"),
            units="ratio",
        ),
        # Stored with a trailing zero that canonical encoding will strip to "0.1".
        verification=ClaimVerification(
            status=AgentVerificationStatus.VERIFIED,
            computed_value=Decimal("0.100000"),
            method="period_return",
            verifier_version="agent-verify-1.0.0",
            verified_at=now,
        ),
    )
    run_dir = tmp_path / "RUN-20261122-050"
    (run_dir / "raw").mkdir(parents=True)
    (run_dir / "evidence.json").write_bytes(pretty_json_bytes([ev.model_dump()]))
    (run_dir / "series.json").write_bytes(pretty_json_bytes([series.model_dump()]))
    (run_dir / "claims.json").write_bytes(pretty_json_bytes([claim.model_dump()]))
    (run_dir / "manifest.json").write_bytes(
        pretty_json_bytes({"mode": "agent_research", "created_at": now.isoformat()})
    )

    outcome = replay_agent_run("RUN-20261122-050", tmp_path)
    assert outcome.passed is True
    assert outcome.claims[0].matches is True


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


# --------------------------------------------------------------------------
# Negative paths: missing, malformed, and non-reproducible agent artifacts.
# These exercise the error branches in replay_agent_run / _replay_response that
# the happy-path and single-field tamper tests above do not reach.
# --------------------------------------------------------------------------


def _run_dir_for(run_id: str, tmp_path: Path) -> Path:
    return tmp_path / run_id


def test_replay_missing_claims_artifact_raises_not_found(tmp_path: Path) -> None:
    # A required agent artifact that is absent is a hard failure, not a silent
    # pass: store.load_json surfaces RunNotFoundError (uncaught by replay).
    run_id = _make_run(tmp_path)
    (_run_dir_for(run_id, tmp_path) / "claims.json").unlink()
    with pytest.raises(RunNotFoundError, match=r"missing artifact claims\.json"):
        replay_agent_run(run_id, tmp_path)


def test_replay_malformed_claims_json_text_raises_store_error(tmp_path: Path) -> None:
    # Non-JSON bytes in a core artifact are reported as an invalid-JSON store
    # error before any model reconstruction is attempted.
    run_id = _make_run(tmp_path)
    (_run_dir_for(run_id, tmp_path) / "claims.json").write_text("not json at all")
    with pytest.raises(RunStoreError, match="not valid JSON"):
        replay_agent_run(run_id, tmp_path)


def test_replay_structurally_invalid_claims_raise_replay_error(tmp_path: Path) -> None:
    # Valid JSON but a claim that violates the model contract (missing required
    # fields) must raise a ReplayError flagging malformed agent artifacts.
    run_id = _make_run(tmp_path)
    path = _run_dir_for(run_id, tmp_path) / "claims.json"
    path.write_text(json.dumps([{"claim_id": "CL-broken"}]))
    with pytest.raises(ReplayError, match="malformed agent artifacts"):
        replay_agent_run(run_id, tmp_path)


def test_replay_naive_timestamp_in_evidence_rejected(tmp_path: Path) -> None:
    # Evidence timestamps are AwareDatetime: a naive (no-timezone) retrieved_at
    # fails model validation and surfaces as a malformed-artifact ReplayError.
    run_id = _make_run(tmp_path)
    path = _run_dir_for(run_id, tmp_path) / "evidence.json"
    evidence = json.loads(path.read_text())
    assert evidence, "expected at least one evidence record"
    evidence[0]["retrieved_at"] = "2026-11-22T12:00:00"  # naive: no offset
    path.write_text(json.dumps(evidence))
    with pytest.raises(ReplayError, match="malformed agent artifacts"):
        replay_agent_run(run_id, tmp_path)


def test_replay_reproducibility_failure_when_stored_value_diverges(tmp_path: Path) -> None:
    # Tamper the stored computed_value. Recomputation from the preserved series
    # is unaffected, so the recomputed value no longer matches what was stored:
    # the claim must FAIL replay even though its status is still 'verified'.
    run_id = _make_run(tmp_path)
    path = _run_dir_for(run_id, tmp_path) / "claims.json"
    claims = json.loads(path.read_text())
    claims[0]["verification"]["computed_value"] = "9.999999"
    path.write_text(json.dumps(claims))
    outcome = replay_agent_run(run_id, tmp_path)
    assert outcome.passed is False
    claim = outcome.claims[0]
    assert claim.matches is False
    assert claim.stored_value != claim.recomputed_value
    # The verdict itself is unchanged; only the value reproduces differently.
    assert claim.recomputed_status == "verified"


def test_replay_structurally_invalid_response_raises_replay_error(tmp_path: Path) -> None:
    # A response.json that is valid JSON but not a well-formed ResearchResponse
    # (missing required fields) is a malformed-response ReplayError, not a
    # silently-absent response.
    run_id, run_dir = _make_conversational_run(tmp_path)
    (run_dir / "response.json").write_text(json.dumps({"run_id": run_id}))
    with pytest.raises(ReplayError, match=r"malformed response\.json"):
        replay_agent_run(run_id, tmp_path)


def test_replay_detects_response_citing_unresolved_evidence(tmp_path: Path) -> None:
    # A supporting fact that cites an evidence id with no preserved record must
    # fail citation integrity (and thus the run), distinct from hash tampering.
    run_id, run_dir = _make_conversational_run(tmp_path)
    path = run_dir / "response.json"
    data = json.loads(path.read_text())
    assert data["supporting_facts"], "expected at least one supporting fact"
    data["supporting_facts"][0]["evidence_ids"] = [
        *data["supporting_facts"][0]["evidence_ids"],
        "EV-does-not-exist",
    ]
    path.write_text(json.dumps(data))
    outcome = replay_agent_run(run_id, tmp_path)
    assert outcome.response is not None
    assert outcome.response.citation_integrity is False
    assert any("unresolved" in p for p in outcome.response.problems)
    assert outcome.passed is False
