"""Tests for the OpenAI provider: response mapping, retries, error mapping."""

from __future__ import annotations

import httpx
import pytest
from openai import (
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
)
from tests.agent.agent_fixtures import (
    FakeClient,
    FakeFunctionCall,
    FakeMessage,
    FakeResponse,
    FakeUsage,
    build_config,
)

from strix.agent.openai_provider import OpenAIProvider
from strix.errors import (
    ModelUnavailableError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

_REQ = httpx.Request("POST", "https://api.openai.com/v1/responses")


def _resp(status: int) -> httpx.Response:
    return httpx.Response(status, request=_REQ)


def _no_sleep(_seconds: float) -> None:
    return None


def test_create_response_maps_usage_and_cost() -> None:
    fake = FakeResponse(
        id="resp_1",
        output_text="hello",
        usage=FakeUsage(input_tokens=1_000_000, output_tokens=1_000_000),
    )
    provider = OpenAIProvider(build_config(), client=FakeClient(responses_behavior=fake))
    result = provider.create_response(input="hi")
    assert result.response_id == "resp_1"
    assert result.output_text == "hello"
    assert result.is_complete is True
    assert str(result.cost.total_cost_usd) == "0.60000000"


def test_create_response_extracts_tool_calls() -> None:
    fake = FakeResponse(
        output=[
            FakeFunctionCall(
                call_id="call_1", name="get_market_quote", arguments='{"symbol":"SPY"}'
            )
        ]
    )
    provider = OpenAIProvider(build_config(), client=FakeClient(responses_behavior=fake))
    result = provider.create_response(input="quote SPY")
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_market_quote"
    assert result.tool_calls[0].call_id == "call_1"


def test_create_response_detects_refusal() -> None:
    refusal_part = type("Part", (), {"type": "refusal", "refusal": "cannot help"})()
    fake = FakeResponse(output=[FakeMessage([refusal_part])])
    provider = OpenAIProvider(build_config(), client=FakeClient(responses_behavior=fake))
    result = provider.create_response(input="bad")
    assert result.incomplete_reason == "refusal"
    assert result.output_text == "cannot help"


def test_incomplete_response_reports_reason() -> None:
    fake = FakeResponse(status="incomplete", incomplete_reason="max_output_tokens")
    provider = OpenAIProvider(build_config(), client=FakeClient(responses_behavior=fake))
    result = provider.create_response(input="hi")
    assert result.is_complete is False
    assert result.incomplete_reason == "max_output_tokens"


def test_retries_then_succeeds() -> None:
    def behavior(call_number: int, _kwargs: object) -> object:
        if call_number == 1:
            raise RateLimitError("slow down", response=_resp(429), body=None)
        return FakeResponse(output_text="ok")

    client = FakeClient(responses_behavior=behavior)
    provider = OpenAIProvider(
        build_config(STRIX_LLM_MAX_RETRIES="2"), client=client, sleep_fn=_no_sleep
    )
    result = provider.create_response(input="hi")
    assert result.output_text == "ok"
    assert len(client.responses.calls) == 2


def test_rate_limit_exhausts_retries() -> None:
    def behavior(_n: int, _kwargs: object) -> object:
        raise RateLimitError("slow down", response=_resp(429), body=None)

    provider = OpenAIProvider(
        build_config(STRIX_LLM_MAX_RETRIES="1"),
        client=FakeClient(responses_behavior=behavior),
        sleep_fn=_no_sleep,
    )
    with pytest.raises(ProviderRateLimitError):
        provider.create_response(input="hi")


def test_timeout_maps_to_provider_timeout() -> None:
    def behavior(_n: int, _kwargs: object) -> object:
        raise APITimeoutError(request=_REQ)

    provider = OpenAIProvider(
        build_config(STRIX_LLM_MAX_RETRIES="0"),
        client=FakeClient(responses_behavior=behavior),
        sleep_fn=_no_sleep,
    )
    with pytest.raises(ProviderTimeoutError):
        provider.create_response(input="hi")


def test_auth_error_maps_to_provider_error() -> None:
    def behavior(_n: int, _kwargs: object) -> object:
        raise AuthenticationError("bad key", response=_resp(401), body=None)

    provider = OpenAIProvider(
        build_config(), client=FakeClient(responses_behavior=behavior), sleep_fn=_no_sleep
    )
    with pytest.raises(ProviderError, match="authentication failed"):
        provider.create_response(input="hi")


def test_not_found_maps_to_model_unavailable() -> None:
    def behavior(_n: int, _kwargs: object) -> object:
        raise NotFoundError("no model", response=_resp(404), body=None)

    provider = OpenAIProvider(
        build_config(), client=FakeClient(responses_behavior=behavior), sleep_fn=_no_sleep
    )
    with pytest.raises(ModelUnavailableError):
        provider.create_response(input="hi")


def test_server_error_is_retried() -> None:
    def behavior(call_number: int, _kwargs: object) -> object:
        if call_number == 1:
            raise InternalServerError("boom", response=_resp(503), body=None)
        return FakeResponse(output_text="recovered")

    client = FakeClient(responses_behavior=behavior)
    provider = OpenAIProvider(
        build_config(STRIX_LLM_MAX_RETRIES="2"), client=client, sleep_fn=_no_sleep
    )
    result = provider.create_response(input="hi")
    assert result.output_text == "recovered"
    assert len(client.responses.calls) == 2


def test_check_model_available_success() -> None:
    model_obj = type("Model", (), {"id": "gpt-6-luna"})()
    provider = OpenAIProvider(build_config(), client=FakeClient(models_result=model_obj))
    assert provider.check_model_available() == "gpt-6-luna"


def test_check_model_available_not_found() -> None:
    err = NotFoundError("no model", response=_resp(404), body=None)
    provider = OpenAIProvider(build_config(), client=FakeClient(models_result=err))
    with pytest.raises(ModelUnavailableError):
        provider.check_model_available()


def test_tools_forwarded_to_client() -> None:
    client = FakeClient(responses_behavior=FakeResponse(output_text="x"))
    provider = OpenAIProvider(build_config(), client=client)
    provider.create_response(input="hi", tools=[{"type": "web_search"}])
    assert client.responses.calls[0]["tools"] == [{"type": "web_search"}]
    assert client.responses.calls[0]["tool_choice"] == "auto"
    assert client.responses.calls[0]["reasoning"] == {"effort": "low"}
