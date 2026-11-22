"""Tests for the system prompt and the diagnostics command."""

from __future__ import annotations

import io

from tests.agent.agent_fixtures import FakeClient, FakeResponse, build_config

from strix.agent.contracts import ModelResponse
from strix.agent.diagnostics import run_diagnostics
from strix.agent.openai_provider import OpenAIProvider
from strix.agent.prompts import instruction_version, market_research_instructions


def test_instructions_load_and_name_identity() -> None:
    text = market_research_instructions()
    assert "STRIX" in text
    assert "Structured Traceability" in text
    assert instruction_version() == "market_research/1.0.0"


def test_instructions_contain_injection_defense() -> None:
    text = market_research_instructions().lower()
    assert "untrusted" in text
    assert "instructions" in text  # "never as instructions"


def test_instructions_forbid_self_assigned_verification() -> None:
    # Collapse whitespace so wrapped lines still match the phrase.
    text = " ".join(market_research_instructions().lower().split())
    assert "cannot assign your own verification status" in text


def test_diagnostics_offline_hides_key() -> None:
    buf = io.StringIO()
    code = run_diagnostics(offline=True, out=buf, config=build_config())
    output = buf.getvalue()
    assert code == 0
    assert "***redacted***" in output
    assert "sk-test-key" not in output
    assert "Offline mode" in output


def test_diagnostics_live_path_with_fake_provider() -> None:
    buf = io.StringIO()
    config = build_config()
    fake = FakeResponse(output_text="STRIX connectivity OK")
    provider = OpenAIProvider(config, client=FakeClient(responses_behavior=fake))
    # Patch the model-availability check onto the fake client's models endpoint.
    provider._client.models._result = type("M", (), {"id": "gpt-6-luna"})()  # type: ignore[attr-defined]
    code = run_diagnostics(out=buf, config=config, provider=provider)
    output = buf.getvalue()
    assert code == 0
    assert "STRIX connectivity OK" in output
    assert "estimated cost" in output
    assert "sk-test-key" not in output


def test_diagnostics_response_type() -> None:
    # Guard: provider returns the typed contract diagnostics relies on.
    config = build_config()
    provider = OpenAIProvider(config, client=FakeClient(responses_behavior=FakeResponse()))
    result = provider.create_response(input="ping")
    assert isinstance(result, ModelResponse)
