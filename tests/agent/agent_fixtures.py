"""Shared helpers and fake OpenAI SDK objects for agent unit tests (no network)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strix.agent.config import AgentConfig


def build_config(**overrides: str) -> AgentConfig:
    """A valid config built from an explicit env dict (never reads repo .env)."""
    env = {"OPEN_AI_API_KEY": "sk-test-key", **overrides}
    # A dotenv_path that does not exist keeps the real project .env out of tests.
    return AgentConfig.load(environ=env, dotenv_path=Path("/nonexistent/.env"))


# -- fake OpenAI SDK objects ------------------------------------------------


class FakeUsage:
    def __init__(
        self,
        *,
        input_tokens: int = 0,
        cached_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
        total_tokens: int | None = None,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = (
            total_tokens if total_tokens is not None else input_tokens + output_tokens
        )
        self.input_tokens_details = type(
            "InputDetails", (), {"cached_tokens": cached_tokens, "cache_write_tokens": 0}
        )()
        self.output_tokens_details = type(
            "OutputDetails", (), {"reasoning_tokens": reasoning_tokens}
        )()


class FakeMessage:
    type = "message"

    def __init__(self, content: list[Any]) -> None:
        self.content = content


class FakeFunctionCall:
    type = "function_call"

    def __init__(self, *, call_id: str, name: str, arguments: str) -> None:
        self.call_id = call_id
        self.name = name
        self.arguments = arguments


class FakeResponse:
    def __init__(
        self,
        *,
        id: str = "resp_test",
        status: str = "completed",
        output_text: str = "",
        output: list[Any] | None = None,
        usage: FakeUsage | None = None,
        model: str = "gpt-6-luna",
        incomplete_reason: str | None = None,
    ) -> None:
        self.id = id
        self.status = status
        self.output_text = output_text
        self.output = output or []
        self.usage = usage or FakeUsage(input_tokens=10, output_tokens=5)
        self.model = model
        if incomplete_reason is not None:
            self.incomplete_details = type("Details", (), {"reason": incomplete_reason})()


class FakeResponses:
    def __init__(self, behavior: Any) -> None:
        self._behavior = behavior
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if callable(self._behavior):
            return self._behavior(len(self.calls), kwargs)
        return self._behavior


class FakeModels:
    def __init__(self, result: Any) -> None:
        self._result = result

    def retrieve(self, model: str) -> Any:
        if isinstance(self._result, Exception):
            raise self._result
        if callable(self._result):
            return self._result(model)
        return self._result


class FakeClient:
    def __init__(self, *, responses_behavior: Any = None, models_result: Any = None) -> None:
        self.responses = FakeResponses(responses_behavior)
        self.models = FakeModels(models_result)
