"""End-to-end orchestration test with a scripted provider (no network).

The scripted provider mimics a real model: it fetches prices, runs a
calculation, and submits a quantitative claim, reading each tool's output to
drive the next step. This exercises the full loop + independent verification +
fail-closed assembly + persistence deterministically.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from tests.agent.agent_fixtures import build_config

from strix.agent.connectors.market_data import AlpacaConnector
from strix.agent.contracts import ModelResponse, TokenUsage, ToolCall, estimate_cost
from strix.agent.models import AgentVerificationStatus
from strix.agent.orchestrator import run_research_question

# Six recent (within the freshness window) wobbling closes so vol > 0 and the
# backing evidence is CURRENT at the test's as-of date.
_BARS = {
    "symbol": "SPY",
    "bars": [
        {"t": f"2026-11-{d}T05:00:00Z", "c": c}
        for d, c in zip([13, 16, 17, 18, 19, 20], [100, 110, 99, 105, 102, 108], strict=True)
    ],
}
_BARS_JSON = json.dumps(_BARS).encode("utf-8")
_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _fake_alpaca() -> AlpacaConnector:
    return AlpacaConnector(key_id="k", secret_key="s", http_get=lambda u, h: _BARS_JSON)


def _mr(config: Any, *, text: str = "", tool_calls: tuple[ToolCall, ...] = ()) -> ModelResponse:
    usage = TokenUsage(input_tokens=50, output_tokens=20, total_tokens=70)
    return ModelResponse(
        response_id="resp_x",
        model=config.model,
        status="completed",
        output_text=text,
        tool_calls=tool_calls,
        usage=usage,
        cost=estimate_cost(usage, config.pricing),
    )


class ScriptedProvider:
    """A provider that drives fetch -> calculate -> submit_claim -> finish."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self.series_id: str | None = None
        self.evidence_id: str | None = None

    def create_response(self, *, input: Any, instructions: str, tools: Any, previous_response_id=None) -> ModelResponse:  # noqa: E501
        if isinstance(input, list) and input and input[0].get("role") == "user":
            return _mr(
                self.config,
                tool_calls=(
                    ToolCall(
                        call_id="c1",
                        name="get_historical_prices",
                        arguments=json.dumps({"symbol": "SPY", "lookback_days": 40}),
                    ),
                ),
            )
        out = json.loads(input[0]["output"])
        if "series_id" in out and "count" in out:
            self.series_id = out["series_id"]
            self.evidence_id = out["evidence_id"]
            return _mr(
                self.config,
                tool_calls=(
                    ToolCall(
                        call_id="c2",
                        name="calculate",
                        arguments=json.dumps(
                            {
                                "method": "realized_volatility",
                                "series_ids": [self.series_id],
                                "parameters": {"periods_per_year": "252"},
                            }
                        ),
                    ),
                ),
            )
        if out.get("ok") and "value" in out:
            return _mr(
                self.config,
                tool_calls=(
                    ToolCall(
                        call_id="c3",
                        name="submit_claim",
                        arguments=json.dumps(
                            {
                                "claim_type": "quantitative",
                                "statement": "SPY realized volatility over the window.",
                                "evidence_ids": [self.evidence_id],
                                "method": "realized_volatility",
                                "series_ids": [self.series_id],
                                "parameters": {"periods_per_year": "252"},
                                "claimed_value": out["value"],
                            }
                        ),
                    ),
                ),
            )
        return _mr(self.config, text="Done.")


def test_end_to_end_verified_claim(tmp_path: Path) -> None:
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
    answer = outcome.answer
    assert len(answer.verified_claims) == 1
    claim = answer.verified_claims[0]
    assert claim.verification.status is AgentVerificationStatus.VERIFIED
    assert claim.verification.computed_value is not None
    assert len(answer.evidence) == 1
    assert answer.evidence[0].source_url.startswith("https://data.alpaca.markets")
    # Persisted and replayable.
    assert (outcome.run_dir / "manifest.json").exists()
    assert (outcome.run_dir / "answer.txt").exists()
    manifest = json.loads((outcome.run_dir / "manifest.json").read_text())
    assert manifest["mode"] == "agent_research"
    assert manifest["verified_count"] == 1
    # Usage/cost recorded.
    assert outcome.usage.model_calls == 4
    assert outcome.usage.tool_calls == 3
    assert outcome.usage.estimated_cost_usd > 0


def test_wrong_claimed_value_is_not_verified(tmp_path: Path) -> None:
    config = build_config()

    class LyingProvider(ScriptedProvider):
        def create_response(self, **kwargs: Any) -> ModelResponse:
            resp = super().create_response(**kwargs)
            for tc in resp.tool_calls:
                if tc.name == "submit_claim":
                    args = json.loads(tc.arguments)
                    args["claimed_value"] = "0.999999"  # deliberately wrong
                    return _mr(
                        self.config,
                        tool_calls=(
                            ToolCall(call_id=tc.call_id, name=tc.name, arguments=json.dumps(args)),
                        ),
                    )
            return resp

    outcome = run_research_question(
        "What is SPY's recent realized volatility?",
        config=config,
        state_dir=tmp_path,
        provider=LyingProvider(config),  # type: ignore[arg-type]
        alpaca=_fake_alpaca(),
        as_of=date(2026, 11, 22),
        clock=lambda: _NOW,
    )
    assert len(outcome.answer.verified_claims) == 0
    assert len(outcome.answer.unresolved_claims) == 1
    assert outcome.answer.unresolved_claims[0].verification.status is (
        AgentVerificationStatus.CONTRADICTED
    )


_DANGLING_HANDLE = "turn874423news19"


class DanglingCitationProvider:
    """Submits one attributed claim citing an unresolvable web handle, then stops."""

    def __init__(self, config: Any) -> None:
        self.config = config

    def create_response(self, *, input: Any, instructions: str, tools: Any, previous_response_id=None) -> ModelResponse:  # noqa: E501
        if isinstance(input, list) and input and input[0].get("role") == "user":
            return _mr(
                self.config,
                tool_calls=(
                    ToolCall(
                        call_id="c1",
                        name="submit_claim",
                        arguments=json.dumps(
                            {
                                "claim_type": "attributed_statement",
                                "statement": (
                                    "An AP report described an AI-stock sell-off that pulled "
                                    "the S&P 500 down 3.7%."
                                ),
                                "evidence_ids": [_DANGLING_HANDLE],
                                "attributed_to": "Associated Press",
                            }
                        ),
                    ),
                ),
            )
        return _mr(self.config, text="Done.")


def test_dangling_web_handle_is_excluded_and_never_leaks(tmp_path: Path) -> None:
    config = build_config()
    outcome = run_research_question(
        "should i expect bearish or bullish conditions?",
        config=config,
        state_dir=tmp_path,
        provider=DanglingCitationProvider(config),  # type: ignore[arg-type]
        alpaca=_fake_alpaca(),
        as_of=date(2026, 11, 22),
        clock=lambda: _NOW,
    )
    # The attributed claim is disclosed as unresolved, not verified.
    assert len(outcome.answer.verified_claims) == 0
    assert len(outcome.answer.unresolved_claims) == 1
    # A limitation discloses the excluded citation.
    assert any("could not be resolved" in lim for lim in outcome.answer.limitations)
    # The raw handle must appear nowhere in the persisted or rendered artifacts.
    assert _DANGLING_HANDLE not in outcome.answer.model_dump_json()
    rendered = (outcome.run_dir / "answer.txt").read_text()
    assert _DANGLING_HANDLE not in rendered
    claims_json = (outcome.run_dir / "claims.json").read_text()
    assert _DANGLING_HANDLE not in claims_json
