"""Tests for agent configuration loading, validation, and pricing."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from tests.agent.agent_fixtures import build_config

from strix.agent.config import (
    DEFAULT_MODEL,
    DEFAULT_PRICING,
    AgentConfig,
    PricingConfig,
    parse_dotenv,
)
from strix.errors import AgentConfigError

_NO_DOTENV = Path("/nonexistent/.env")


def test_defaults_match_spec() -> None:
    cfg = build_config()
    assert cfg.model == "gpt-6-luna"
    assert cfg.reasoning_effort == "low"
    assert cfg.max_output_tokens == 4096
    assert cfg.max_model_calls == 8
    assert cfg.max_tool_calls == 16
    assert cfg.max_research_seconds == 120
    assert cfg.max_input_tokens == 100_000
    assert cfg.max_total_output_tokens == 16_000
    assert cfg.max_cost_usd == Decimal("0.05")
    assert cfg.allow_model_escalation is False
    assert cfg.require_verified_claims is True
    assert cfg.require_citations is True
    assert cfg.web_search_enabled is True


def test_openai_api_key_takes_precedence_over_open_ai_api_key() -> None:
    cfg = AgentConfig.load(
        environ={"OPENAI_API_KEY": "sk-primary", "OPEN_AI_API_KEY": "sk-secondary"},
        dotenv_path=_NO_DOTENV,
    )
    assert cfg.api_key.get_secret_value() == "sk-primary"


def test_open_ai_api_key_alias_is_accepted() -> None:
    cfg = AgentConfig.load(environ={"OPEN_AI_API_KEY": "sk-alias"}, dotenv_path=_NO_DOTENV)
    assert cfg.api_key.get_secret_value() == "sk-alias"


def test_missing_key_raises() -> None:
    with pytest.raises(AgentConfigError, match="no OpenAI API key"):
        AgentConfig.load(environ={}, dotenv_path=_NO_DOTENV)


def test_unknown_model_cannot_be_priced() -> None:
    with pytest.raises(AgentConfigError, match="no pricing is configured"):
        build_config(STRIX_LLM_MODEL="gpt-7-nonexistent")


def test_invalid_reasoning_effort_raises() -> None:
    with pytest.raises(AgentConfigError, match="invalid reasoning effort"):
        build_config(STRIX_LLM_REASONING_EFFORT="turbo")


def test_unsupported_provider_raises() -> None:
    with pytest.raises(AgentConfigError, match="unsupported provider"):
        build_config(STRIX_LLM_PROVIDER="anthropic")


def test_non_integer_limit_raises() -> None:
    with pytest.raises(AgentConfigError, match="must be an integer"):
        build_config(STRIX_AGENT_MAX_MODEL_CALLS="eight")


def test_non_positive_cost_raises() -> None:
    with pytest.raises(AgentConfigError):
        build_config(STRIX_AGENT_MAX_COST_USD="0")


def test_zero_model_calls_rejected() -> None:
    with pytest.raises(AgentConfigError):
        build_config(STRIX_AGENT_MAX_MODEL_CALLS="0")


def test_bool_parsing() -> None:
    cfg = build_config(
        STRIX_AGENT_ALLOW_MODEL_ESCALATION="true",
        STRIX_OPENAI_WEB_SEARCH_ENABLED="0",
    )
    assert cfg.allow_model_escalation is True
    assert cfg.web_search_enabled is False


def test_redacted_hides_key_and_is_serializable() -> None:
    cfg = build_config()
    redacted = cfg.redacted()
    assert redacted["api_key"] == "***redacted***"
    assert "sk-test-key" not in str(redacted)


def test_secret_not_in_repr() -> None:
    cfg = build_config()
    assert "sk-test-key" not in repr(cfg)
    assert "sk-test-key" not in str(cfg)


def test_process_env_overrides_dotenv(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("STRIX_LLM_MODEL=gpt-6-astra\nOPEN_AI_API_KEY=sk-file\n")
    cfg = AgentConfig.load(
        environ={"STRIX_LLM_MODEL": "gpt-6-luna"}, dotenv_path=dotenv
    )
    assert cfg.model == "gpt-6-luna"  # process env wins
    assert cfg.api_key.get_secret_value() == "sk-file"  # from dotenv


def test_pricing_for_default_model() -> None:
    pricing = PricingConfig.for_model(DEFAULT_MODEL)
    assert pricing.input_usd_per_1m == Decimal("0.10")
    assert pricing.cached_input_usd_per_1m == Decimal("0.01")
    assert pricing.output_usd_per_1m == Decimal("0.50")


def test_default_model_is_cheapest_permitted() -> None:
    def combined(model: str) -> Decimal:
        inp, _cached, out = DEFAULT_PRICING[model]
        return Decimal(inp) + Decimal(out)

    cheapest = min(DEFAULT_PRICING, key=combined)
    assert cheapest == DEFAULT_MODEL


def test_parse_dotenv_handles_comments_quotes_export() -> None:
    parsed = parse_dotenv(
        "\n".join(
            [
                "# a comment",
                "",
                "export FOO=bar",
                'QUOTED="hello world"',
                "SINGLE='x'",
                "NOEQ",
                "EMPTY=",
            ]
        )
    )
    assert parsed["FOO"] == "bar"
    assert parsed["QUOTED"] == "hello world"
    assert parsed["SINGLE"] == "x"
    assert "NOEQ" not in parsed
    assert parsed["EMPTY"] == ""
