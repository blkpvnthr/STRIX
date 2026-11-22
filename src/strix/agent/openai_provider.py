"""Reusable OpenAI provider built on the Responses API.

Responsibilities:

- Construct the client from validated config (key read from
  :class:`~pydantic.SecretStr`, never logged), with a request timeout and the
  SDK's own retries disabled so retry policy lives in one place here.
- ``create_response`` issues one Responses-API call, applies bounded
  exponential-backoff retries to transient failures (rate limit, timeout,
  connection), maps every terminal failure to a typed :class:`ProviderError`,
  and returns a fully typed :class:`ModelResponse` with token usage priced to
  an exact :class:`CostBreakdown`.
- ``check_model_available`` validates the configured model against the account
  with a free metadata call; an unavailable model raises
  :class:`ModelUnavailableError` rather than falling back to a costlier model.

The client is injectable, so unit tests exercise the full mapping and retry
logic with a fake and never touch the network.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    OpenAI,
    RateLimitError,
)

from strix.agent.config import AgentConfig
from strix.agent.contracts import ModelResponse, TokenUsage, ToolCall, estimate_cost
from strix.errors import (
    ModelUnavailableError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

#: Base and cap (seconds) for exponential backoff between retries.
_BACKOFF_BASE = 0.5
_BACKOFF_CAP = 8.0


class OpenAIProvider:
    """A thin, typed, bounded-retry wrapper over ``client.responses``."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        client: Any | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._sleep = sleep_fn
        if client is not None:
            self._client = client
        else:
            self._client = OpenAI(
                api_key=config.api_key.get_secret_value(),
                timeout=config.request_timeout_seconds,
                max_retries=0,  # retries are handled here, not twice
            )

    # -- availability ------------------------------------------------------

    def check_model_available(self) -> str:
        """Confirm the configured model exists for this key (free metadata call).

        Returns the model id on success; raises :class:`ModelUnavailableError`
        if the model is unknown or :class:`ProviderError` on other failures.
        """
        try:
            model = self._client.models.retrieve(self._config.model)
        except NotFoundError as exc:
            raise ModelUnavailableError(
                f"model {self._config.model!r} is not available to this API key; "
                f"the agent does not escalate to a different model"
            ) from exc
        except AuthenticationError as exc:
            raise ProviderError("OpenAI authentication failed (check the API key)") from exc
        except APIError as exc:
            raise ProviderError(f"could not verify model availability: {exc}") from exc
        return str(getattr(model, "id", self._config.model))

    # -- generation --------------------------------------------------------

    def create_response(
        self,
        *,
        input: str | Sequence[Any],
        instructions: str | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        previous_response_id: str | None = None,
        max_output_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> ModelResponse:
        """Issue one Responses-API call and return a typed, priced result."""
        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "input": input,
            "reasoning": {"effort": reasoning_effort or self._config.reasoning_effort},
            "max_output_tokens": max_output_tokens or self._config.max_output_tokens,
        }
        if instructions is not None:
            kwargs["instructions"] = instructions
        if tools:
            kwargs["tools"] = list(tools)
            kwargs["tool_choice"] = tool_choice or "auto"
        if previous_response_id is not None:
            kwargs["previous_response_id"] = previous_response_id

        response = self._call_with_retries(kwargs)
        return self._to_model_response(response)

    def _call_with_retries(self, kwargs: dict[str, Any]) -> Any:
        attempt = 0
        while True:
            try:
                return self._client.responses.create(**kwargs)
            except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
                if attempt >= self._config.max_retries:
                    raise self._map_transient(exc) from exc
                self._sleep(min(_BACKOFF_BASE * (2**attempt), _BACKOFF_CAP))
                attempt += 1
            except AuthenticationError as exc:
                raise ProviderError("OpenAI authentication failed (check the API key)") from exc
            except NotFoundError as exc:
                raise ModelUnavailableError(
                    f"model {self._config.model!r} is not available to this API key"
                ) from exc
            except APIError as exc:
                # 5xx server errors are retryable; everything else is terminal.
                status = getattr(exc, "status_code", None)
                if isinstance(status, int) and status >= 500 and attempt < self._config.max_retries:
                    self._sleep(min(_BACKOFF_BASE * (2**attempt), _BACKOFF_CAP))
                    attempt += 1
                    continue
                raise ProviderError(f"OpenAI API error: {exc}") from exc

    @staticmethod
    def _map_transient(exc: Exception) -> ProviderError:
        if isinstance(exc, RateLimitError):
            return ProviderRateLimitError("OpenAI rate limit exceeded after retries")
        if isinstance(exc, APITimeoutError):
            return ProviderTimeoutError("OpenAI request timed out after retries")
        return ProviderError(f"OpenAI connection failed after retries: {exc}")

    def _to_model_response(self, response: Any) -> ModelResponse:
        usage = TokenUsage.from_response_usage(getattr(response, "usage", None))
        cost = estimate_cost(usage, self._config.pricing)
        status = str(getattr(response, "status", "completed") or "completed")
        tool_calls = _extract_tool_calls(response)
        refusal = _extract_refusal(response)
        incomplete_reason = _extract_incomplete_reason(response)
        if refusal and incomplete_reason is None:
            incomplete_reason = "refusal"
        return ModelResponse(
            response_id=str(getattr(response, "id", "")),
            model=str(getattr(response, "model", self._config.model)),
            status=status,
            output_text=refusal or (getattr(response, "output_text", "") or ""),
            tool_calls=tuple(tool_calls),
            usage=usage,
            cost=cost,
            incomplete_reason=incomplete_reason,
        )


def _extract_tool_calls(response: Any) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) == "function_call":
            calls.append(
                ToolCall(
                    call_id=str(getattr(item, "call_id", None) or getattr(item, "id", "")),
                    name=str(getattr(item, "name", "")),
                    arguments=str(getattr(item, "arguments", "") or ""),
                )
            )
    return calls


def _extract_refusal(response: Any) -> str | None:
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) != "message":
            continue
        for part in getattr(item, "content", None) or []:
            if getattr(part, "type", None) == "refusal":
                return str(getattr(part, "refusal", "") or "model refused the request")
    return None


def _extract_incomplete_reason(response: Any) -> str | None:
    if str(getattr(response, "status", "")) == "completed":
        return None
    details = getattr(response, "incomplete_details", None)
    if details is not None:
        reason = getattr(details, "reason", None)
        if reason:
            return str(reason)
    status = getattr(response, "status", None)
    return str(status) if status else None
