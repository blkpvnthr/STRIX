"""Tests for tool-argument validation and selected handlers."""

from __future__ import annotations

from datetime import UTC, date, datetime

from tests.agent.agent_fixtures import build_config

from strix.agent.connectors.market_data import AlpacaConnector
from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import AgentClaimType
from strix.agent.tool_registry import ToolContext, ToolRegistry

_NOW = datetime(2026, 11, 22, tzinfo=UTC)


def _ctx() -> ToolContext:
    return ToolContext(
        config=build_config(),
        collector=EvidenceCollector(),
        alpaca=AlpacaConnector(key_id=None, secret_key=None),
        as_of=date(2026, 11, 22),
        now=_NOW,
    )


def test_unknown_tool_returns_error() -> None:
    result = ToolRegistry().execute("does_not_exist", "{}", _ctx())
    assert result["ok"] is False
    assert "unknown tool" in result["error"]


def test_missing_required_argument_rejected() -> None:
    result = ToolRegistry().execute("get_market_quote", "{}", _ctx())
    assert "missing required argument 'symbol'" in result["error"]


def test_bad_argument_type_rejected() -> None:
    result = ToolRegistry().execute("get_market_quote", '{"symbol": 123}', _ctx())
    assert "must be of type string" in result["error"]


def test_invalid_json_arguments_rejected() -> None:
    result = ToolRegistry().execute("get_market_quote", "{not json}", _ctx())
    assert "not valid JSON" in result["error"]


def test_economic_series_reports_unavailable() -> None:
    result = ToolRegistry().execute("get_economic_series", '{"series_id": "CPIAUCSL"}', _ctx())
    assert result["available"] is False
    assert result["reason"] == "no_credentials"


def test_market_quote_unavailable_without_creds() -> None:
    result = ToolRegistry().execute("get_market_quote", '{"symbol": "SPY"}', _ctx())
    assert result["available"] is False


def test_submit_claim_records_pending_candidate() -> None:
    ctx = _ctx()
    result = ToolRegistry().execute(
        "submit_claim",
        '{"claim_type": "observation", "statement": "x", "evidence_ids": ["EV-1"]}',
        ctx,
    )
    assert result["recorded"] is True
    assert result["status"] == "pending_independent_review"
    assert len(ctx.candidate_claims) == 1
    assert ctx.candidate_claims[0].claim_type is AgentClaimType.OBSERVATION
    # The handler must not expose a verdict.
    assert "verified" not in str(result).lower()


def test_calculate_unknown_series_errors() -> None:
    result = ToolRegistry().execute(
        "calculate", '{"method": "period_return", "series_ids": ["SER-x"]}', _ctx()
    )
    assert result["ok"] is False
    assert "unknown series_id" in result["error"]
