"""Agent configuration: environment loading, limits, and pricing.

The key is read from the project ``.env`` (whose variable is ``OPEN_AI_API_KEY``;
``OPENAI_API_KEY`` is also accepted) and held as a :class:`~pydantic.SecretStr`
so it never appears in ``repr``, logs, or model dumps. Every limit in the spec
is a real field enforced downstream (:mod:`strix.agent.budget`); unsupported or
out-of-range values raise :class:`~strix.errors.AgentConfigError` *before* any
network call, so misconfiguration fails loud rather than degrading silently.

Prices are treated as **versioned configuration**, not constants. The default
table is the published standard pricing verified 2026-11-22; only the four
permitted models are priced, so a model whose cost cannot be bounded is refused.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from strix.errors import AgentConfigError

# --------------------------------------------------------------------------
# Permitted models and versioned pricing (USD per 1,000,000 tokens)
# --------------------------------------------------------------------------

#: Pricing table version. Bump when any price below changes.
PRICING_VERSION = "2026-11-22"

#: model -> (input, cached_input, output) USD per 1M tokens. Verified against
#: developers.openai.com/api/docs/pricing on 2026-11-22. Only these four models
#: are permitted (spec §2); a model absent here cannot have its cost bounded.
DEFAULT_PRICING: dict[str, tuple[str, str, str]] = {
    "gpt-6-luna": ("0.10", "0.01", "0.50"),
    "gpt-6.1-terra": ("1.00", "0.05", "5.00"),
    "gpt-6.1-sol": ("2.00", "0.10", "10.00"),
    "gpt-6-astra": ("10.00", "1.00", "50.00"),
}

#: The default model: cheapest permitted by combined input+output price.
DEFAULT_MODEL = "gpt-6-luna"

#: Reasoning-effort values accepted by the Responses API for these models.
ALLOWED_REASONING_EFFORTS = frozenset({"minimal", "low", "medium", "high"})

#: Only the OpenAI provider is implemented.
SUPPORTED_PROVIDERS = frozenset({"openai"})

#: Environment variable names, in resolution order, for the API key.
_API_KEY_VARS = ("OPENAI_API_KEY", "OPEN_AI_API_KEY")


class PricingConfig(BaseModel):
    """Versioned per-token pricing for one model (exact Decimal, no floats)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pricing_version: str
    model: str
    input_usd_per_1m: Decimal
    cached_input_usd_per_1m: Decimal
    output_usd_per_1m: Decimal

    @classmethod
    def for_model(cls, model: str, *, version: str = PRICING_VERSION) -> PricingConfig:
        if model not in DEFAULT_PRICING:
            raise AgentConfigError(
                f"no pricing is configured for model {model!r}; cost cannot be "
                f"bounded. Permitted models: {', '.join(sorted(DEFAULT_PRICING))}"
            )
        inp, cached, out = DEFAULT_PRICING[model]
        return cls(
            pricing_version=version,
            model=model,
            input_usd_per_1m=Decimal(inp),
            cached_input_usd_per_1m=Decimal(cached),
            output_usd_per_1m=Decimal(out),
        )


class AgentConfig(BaseModel):
    """Validated runtime configuration for the research agent.

    Build via :meth:`load`, which reads ``.env`` and the process environment.
    ``api_key`` is a :class:`SecretStr`; :meth:`redacted` returns a dump safe
    to log or persist (no secret, pricing inlined).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    provider: str = "openai"
    model: str = DEFAULT_MODEL
    reasoning_effort: str = "low"
    max_output_tokens: int = Field(default=4096, ge=1)

    max_model_calls: int = Field(default=8, ge=1)
    max_tool_calls: int = Field(default=16, ge=0)
    max_research_seconds: int = Field(default=120, ge=1)
    max_input_tokens: int = Field(default=100_000, ge=1)
    max_total_output_tokens: int = Field(default=16_000, ge=1)
    max_cost_usd: Decimal = Field(default=Decimal("0.05"))

    allow_model_escalation: bool = False
    require_verified_claims: bool = True
    require_citations: bool = True
    web_search_enabled: bool = True

    request_timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=2, ge=0)

    pricing: PricingConfig
    api_key: SecretStr = Field(repr=False)

    # -- validators --------------------------------------------------------

    @field_validator("provider")
    @classmethod
    def _check_provider(cls, value: str) -> str:
        if value not in SUPPORTED_PROVIDERS:
            raise AgentConfigError(
                f"unsupported provider {value!r}; only {sorted(SUPPORTED_PROVIDERS)} "
                f"is implemented"
            )
        return value

    @field_validator("reasoning_effort")
    @classmethod
    def _check_effort(cls, value: str) -> str:
        if value not in ALLOWED_REASONING_EFFORTS:
            raise AgentConfigError(
                f"invalid reasoning effort {value!r}; expected one of "
                f"{sorted(ALLOWED_REASONING_EFFORTS)}"
            )
        return value

    @field_validator("max_cost_usd")
    @classmethod
    def _check_cost(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise AgentConfigError("STRIX_AGENT_MAX_COST_USD must be greater than 0")
        return value

    # -- construction ------------------------------------------------------

    @classmethod
    def load(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        dotenv_path: Path | None = None,
    ) -> AgentConfig:
        """Build config from ``.env`` + the process environment.

        Resolution order for every value: a real process environment variable
        wins over a ``.env`` file entry. The API key must resolve to a
        non-empty value under ``OPENAI_API_KEY`` or ``OPEN_AI_API_KEY`` or an
        :class:`AgentConfigError` is raised. The key is never logged.
        """
        env = _merged_env(environ, dotenv_path)

        api_key = _first_present(env, _API_KEY_VARS)
        if not api_key:
            raise AgentConfigError(
                "no OpenAI API key found; set OPENAI_API_KEY or OPEN_AI_API_KEY "
                "in the environment or .env"
            )

        provider = env.get("STRIX_LLM_PROVIDER", "openai")
        model = env.get("STRIX_LLM_MODEL", DEFAULT_MODEL)
        pricing = PricingConfig.for_model(model)

        try:
            return cls(
                provider=provider,
                model=model,
                reasoning_effort=env.get("STRIX_LLM_REASONING_EFFORT", "low"),
                max_output_tokens=_int(env, "STRIX_LLM_MAX_OUTPUT_TOKENS", 4096),
                max_model_calls=_int(env, "STRIX_AGENT_MAX_MODEL_CALLS", 8),
                max_tool_calls=_int(env, "STRIX_AGENT_MAX_TOOL_CALLS", 16),
                max_research_seconds=_int(env, "STRIX_AGENT_MAX_RESEARCH_SECONDS", 120),
                max_input_tokens=_int(env, "STRIX_AGENT_MAX_INPUT_TOKENS", 100_000),
                max_total_output_tokens=_int(env, "STRIX_AGENT_MAX_TOTAL_OUTPUT_TOKENS", 16_000),
                max_cost_usd=_decimal(env, "STRIX_AGENT_MAX_COST_USD", "0.05"),
                allow_model_escalation=_bool(env, "STRIX_AGENT_ALLOW_MODEL_ESCALATION", False),
                require_verified_claims=_bool(env, "STRIX_AGENT_REQUIRE_VERIFIED_CLAIMS", True),
                require_citations=_bool(env, "STRIX_AGENT_REQUIRE_CITATIONS", True),
                web_search_enabled=_bool(env, "STRIX_OPENAI_WEB_SEARCH_ENABLED", True),
                request_timeout_seconds=_float(env, "STRIX_LLM_REQUEST_TIMEOUT_SECONDS", 60.0),
                max_retries=_int(env, "STRIX_LLM_MAX_RETRIES", 2),
                pricing=pricing,
                api_key=SecretStr(api_key),
            )
        except AgentConfigError:
            raise
        except ValueError as exc:
            # Pydantic field-constraint violations (ge/gt) -> config error.
            raise AgentConfigError(f"invalid agent configuration: {exc}") from exc

    def redacted(self) -> dict[str, object]:
        """A dump safe to log/persist: no secret, no floats (canonical-safe)."""
        data = self.model_dump(exclude={"api_key"})
        # The canonical serializer forbids binary floats; stringify the one float.
        data["request_timeout_seconds"] = str(data["request_timeout_seconds"])
        data["api_key"] = "***redacted***"
        return data


# --------------------------------------------------------------------------
# .env parsing (dependency-free; os.environ always wins)
# --------------------------------------------------------------------------


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines. Ignores blanks, ``#`` comments, and an
    optional ``export`` prefix; strips one layer of matching quotes."""
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        line = line.removeprefix("export ").lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[key] = value
    return result


def merged_environment(
    environ: Mapping[str, str] | None = None, *, dotenv_path: Path | None = None
) -> dict[str, str]:
    """Public helper: ``.env`` merged with the process env (process env wins).

    Used by connectors that read their own credentials (e.g. Alpaca) so they see
    the same ``.env`` the agent config loads from.
    """
    return _merged_env(environ, dotenv_path)


def _default_dotenv_path() -> Path:
    return Path.cwd() / ".env"


def _merged_env(
    environ: Mapping[str, str] | None, dotenv_path: Path | None
) -> dict[str, str]:
    """Merge ``.env`` (base) with the process env (override)."""
    base = environ if environ is not None else os.environ
    path = dotenv_path if dotenv_path is not None else _default_dotenv_path()
    merged: dict[str, str] = {}
    if path.is_file():
        try:
            merged.update(parse_dotenv(path.read_text(encoding="utf-8")))
        except OSError as exc:  # pragma: no cover - unreadable .env is rare
            raise AgentConfigError(f"could not read {path}: {exc}") from exc
    merged.update(base)
    return merged


def _first_present(env: Mapping[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = env.get(name, "").strip()
        if value:
            return value
    return None


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise AgentConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise AgentConfigError(f"{name} must be a number, got {raw!r}") from exc


def _decimal(env: Mapping[str, str], name: str, default: str) -> Decimal:
    from decimal import InvalidOperation

    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return Decimal(default)
    try:
        return Decimal(raw.strip())
    except InvalidOperation as exc:
        raise AgentConfigError(f"{name} must be a decimal number, got {raw!r}") from exc


def _bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")
