"""Regression fixtures for the two observed response failures (spec §14).

These encode the exact symptoms seen in the two recorded runs so they cannot
recur:

- RUN-20261123-001: "how can i expect the market to perform tomorrow?" was
  answered by echoing a trailing return — no direct answer, no assessment.
- RUN-20261123-002: a finding cited the raw web-search handle
  ``turn874423news19`` ("cites unknown evidence"), and an ~11-18% weekly index
  move was presented with no data-quality caveat.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from tests.agent.agent_fixtures import build_config

from strix.agent.connectors.market_data import AlpacaConnector
from strix.agent.contracts import ModelResponse, TokenUsage, ToolCall, estimate_cost
from strix.agent.orchestrator import run_research_question

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
_AS_OF = date(2026, 11, 22)
_HANDLE = "turn874423news19"

# A SPY series with a large (~-11%) fall over six sessions — the RUN-002 shape.
_FALLING_BARS = {
    "symbol": "SPY",
    "bars": [
        {"t": f"2026-11-{d}T05:00:00Z", "c": c}
        for d, c in zip(
            [13, 16, 17, 18, 19, 20], [100, 98, 96, 94, 92, 88.7], strict=True
        )
    ],
}


def _falling_alpaca() -> AlpacaConnector:
    payload = json.dumps(_FALLING_BARS).encode("utf-8")
    return AlpacaConnector(key_id="k", secret_key="s", http_get=lambda u, h: payload)


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


class _SellOffProvider:
    """Reproduces RUN-002: a large verified index drop + a dangling-cited AP report."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self.series_id: str | None = None
        self.evidence_id: str | None = None

    def create_response(self, **kwargs: Any) -> ModelResponse:
        if kwargs.get("tools") is None:  # synthesis call
            payload = {
                "direct_answer": (
                    "Current conditions are bearish on the weight of evidence; no single "
                    "session can be predicted."
                ),
                "analysis": "Trailing momentum is sharply negative.",
                "analytical_inferences": [],
                "conditional_scenarios": [],
                "invalidation_conditions": [],
                "monitoring_indicators": [],
            }
            usage = TokenUsage(input_tokens=120, output_tokens=90, total_tokens=210)
            return ModelResponse(
                response_id="resp_syn",
                model=self.config.model,
                status="completed",
                output_text=json.dumps(payload),
                usage=usage,
                cost=estimate_cost(usage, self.config.pricing),
            )
        model_input = kwargs["input"]
        if isinstance(model_input, list) and model_input and model_input[0].get("role") == "user":
            return _mr(
                self.config,
                tool_calls=(
                    ToolCall(
                        call_id="c1",
                        name="get_historical_prices",
                        arguments=json.dumps({"symbol": "SPY", "lookback_days": 10}),
                    ),
                ),
            )
        out = json.loads(model_input[0]["output"])
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
                                "method": "period_return",
                                "series_ids": [self.series_id],
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
                                "statement": "SPY period return over the window.",
                                "evidence_ids": [self.evidence_id],
                                "method": "period_return",
                                "series_ids": [self.series_id],
                                "claimed_value": out["value"],
                            }
                        ),
                    ),
                    ToolCall(
                        call_id="c4",
                        name="submit_claim",
                        arguments=json.dumps(
                            {
                                "claim_type": "attributed_statement",
                                "statement": (
                                    "An AP report described an AI-stock sell-off that pulled "
                                    "the S&P 500 down 3.7%."
                                ),
                                "evidence_ids": [_HANDLE],
                                "attributed_to": "Associated Press",
                            }
                        ),
                    ),
                ),
            )
        return _mr(self.config, text="Done.")


class _TrailingReturnProvider(_SellOffProvider):
    """Reproduces RUN-001: only a trailing-return finding, no news claim."""

    def create_response(self, **kwargs: Any) -> ModelResponse:
        resp = super().create_response(**kwargs)
        # Drop the dangling AP claim so this run mirrors RUN-001 exactly.
        if resp.tool_calls and any(tc.name == "submit_claim" for tc in resp.tool_calls):
            kept = tuple(
                tc
                for tc in resp.tool_calls
                if not (tc.name == "submit_claim" and _HANDLE in tc.arguments)
            )
            if kept != resp.tool_calls:
                return _mr(self.config, tool_calls=kept)
        return resp


def test_run001_forward_question_is_not_a_trailing_return_echo(tmp_path: Path) -> None:
    config = build_config()
    outcome = run_research_question(
        "how can i expect the market to perform tomorrow?",
        config=config,
        state_dir=tmp_path,
        provider=_TrailingReturnProvider(config),  # type: ignore[arg-type]
        alpaca=_falling_alpaca(),
        as_of=_AS_OF,
        clock=lambda: _NOW,
    )
    response = outcome.response
    assert response is not None
    # The ORIGINAL failure: direct answer == a bare finding restatement. Must not recur.
    assert response.direct_answer != response.verified_answer.summary
    assert "period return over the window" not in response.direct_answer.lower()
    # A directional assessment is produced for the forward-looking question.
    assert response.market_assessment is not None
    assert response.question_intent == "predictive"


def test_run002_handle_never_leaks_and_anomaly_is_flagged(tmp_path: Path) -> None:
    config = build_config()
    outcome = run_research_question(
        "should i expect bearish or bullish conditions?",
        config=config,
        state_dir=tmp_path,
        provider=_SellOffProvider(config),  # type: ignore[arg-type]
        alpaca=_falling_alpaca(),
        as_of=_AS_OF,
        clock=lambda: _NOW,
    )
    # The raw web-search handle must not appear in ANY persisted artifact.
    for name in ("answer.json", "answer.txt", "claims.json", "response.json", "response.txt"):
        assert _HANDLE not in (outcome.run_dir / name).read_text()
    # The anomalous ~-11% weekly move is flagged as a data-quality concern.
    assert any("anomalous_short_horizon_return" in lim for lim in outcome.answer.limitations)
    # The verified drop is present; the AP attribution is disclosed but unresolved.
    assert len(outcome.answer.verified_claims) == 1
    assert len(outcome.answer.unresolved_claims) == 1
