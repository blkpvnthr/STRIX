"""Typed research tool registry.

Tools are the only way the model can touch data. Each has a JSON-schema
signature (validated before execution), a handler, and a permission/cost note.
Data tools preserve evidence and build observation series; ``calculate`` runs a
deterministic calculator; ``submit_claim`` records a *candidate* claim with
``verification.status == PENDING`` — it can never set a verdict. Independent
verification happens after the research loop, outside the model's control.

Tool *data* unavailability (no credentials, no rows) is returned as a structured
result, not raised. Malformed arguments return a structured error so the model
can correct itself within budget; they never crash the run.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from strix.agent.calculations import CALC_VERSION, recompute
from strix.agent.config import AgentConfig
from strix.agent.connectors.market_data import AlpacaConnector
from strix.agent.connectors.sec import SecConnector
from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import (
    AgentCalculation,
    AgentClaim,
    AgentClaimType,
    CalculationMethod,
    Observation,
    SourceKind,
)
from strix.agent.sources import UnavailableSource


@dataclass
class ToolContext:
    """Mutable state shared by tool handlers during one research run."""

    config: AgentConfig
    collector: EvidenceCollector
    alpaca: AlpacaConnector
    as_of: date
    now: datetime
    sec_fetch: Any = None  # injectable EDGAR fetch for tests
    candidate_claims: list[AgentClaim] = field(default_factory=list)

    def sec(self) -> SecConnector:
        if self.sec_fetch is not None:
            return SecConnector(as_of=self.as_of, fetch=self.sec_fetch)
        return SecConnector(as_of=self.as_of)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------


def _handle_get_historical_prices(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    symbol = str(args["symbol"]).upper()
    lookback = int(args.get("lookback_days", 60))
    end = ctx.as_of
    start = end - timedelta(days=max(lookback, 2))
    result = ctx.alpaca.get_historical_bars(
        symbol, start=start.isoformat(), end=end.isoformat(), timeframe="1Day"
    )
    if isinstance(result, UnavailableSource):
        return _unavailable(result)
    observations = tuple(Observation(at=p.at, value=p.close) for p in result.points)
    evidence = ctx.collector.register(
        source_type=SourceKind.MARKET_DATA,
        provider=result.provider,
        source_title=f"{symbol} daily closes {result.start}..{result.end}",
        raw=result.raw,
        retrieved_at=result.retrieved_at,
        published_at=_date_to_dt(observations[-1].at),
        source_url=result.source_url,
    )
    series = ctx.collector.add_series(
        subject=symbol,
        concept="close",
        unit="USD",
        observations=observations,
        source_evidence_id=evidence.evidence_id,
    )
    return {
        "available": True,
        "symbol": symbol,
        "series_id": series.series_id,
        "evidence_id": evidence.evidence_id,
        "count": len(observations),
        "first": {"at": observations[0].at, "close": str(observations[0].value)},
        "last": {"at": observations[-1].at, "close": str(observations[-1].value)},
    }


def _handle_get_market_quote(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    symbol = str(args["symbol"]).upper()
    result = ctx.alpaca.get_latest_quote(symbol)
    if isinstance(result, UnavailableSource):
        return _unavailable(result)
    evidence = ctx.collector.register(
        source_type=SourceKind.MARKET_DATA,
        provider=result.provider,
        source_title=f"{symbol} latest trade",
        raw=result.raw,
        retrieved_at=result.retrieved_at,
        source_url=result.source_url,
    )
    return {
        "available": True,
        "symbol": symbol,
        "price": str(result.price),
        "at": result.at,
        "evidence_id": evidence.evidence_id,
    }


def _handle_get_sec_financials(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    ticker = str(args["ticker"]).upper()
    concept = str(args["concept"])
    result = ctx.sec().get_concept_series(ticker, concept)
    if isinstance(result, UnavailableSource):
        return _unavailable(result)
    observations = tuple(Observation(at=p.at, value=p.close) for p in result.points)
    evidence = ctx.collector.register(
        source_type=SourceKind.SEC_EDGAR,
        provider=result.provider,
        source_title=f"{ticker} {concept} (SEC EDGAR companyfacts)",
        raw=result.raw,
        retrieved_at=result.retrieved_at,
        published_at=_date_to_dt(observations[-1].at),
        source_url=result.source_url,
    )
    series = ctx.collector.add_series(
        subject=ticker,
        concept=concept,
        unit="USD",
        observations=observations,
        source_evidence_id=evidence.evidence_id,
    )
    return {
        "available": True,
        "ticker": ticker,
        "concept": concept,
        "series_id": series.series_id,
        "evidence_id": evidence.evidence_id,
        "periods": [{"at": o.at, "value": str(o.value)} for o in observations],
    }


def _handle_get_economic_series(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    # No FRED/economic API key is configured; report transparently.
    return {
        "available": False,
        "source": "economic_data_api",
        "reason": "no_credentials",
        "detail": (
            "No economic-data API key is configured. Use web_search to find the "
            "latest release from a primary source (BLS, Federal Reserve, FRED, "
            "Treasury) and cite it; numeric values from search are attribution-only "
            "unless the primary release can be retrieved."
        ),
    }


def _handle_calculate(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        method = CalculationMethod(str(args["method"]))
    except ValueError:
        return {"error": f"unknown method {args.get('method')!r}", "ok": False}
    series_ids = list(args.get("series_ids", []))
    parameters = {str(k): str(v) for k, v in (args.get("parameters") or {}).items()}
    values: list[tuple[Decimal, ...]] = []
    for sid in series_ids:
        series = ctx.collector.series(str(sid))
        if series is None:
            return {"error": f"unknown series_id {sid!r}", "ok": False}
        values.append(series.values)
    try:
        computed = recompute(method, values, parameters)
    except Exception as exc:  # calculator rejects bad inputs with CalculationError
        return {"error": str(exc), "ok": False}
    return {
        "ok": True,
        "method": method.value,
        "series_ids": series_ids,
        "parameters": parameters,
        "value": str(computed),
        "units": "ratio",
    }


def _handle_submit_claim(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        claim_type = AgentClaimType(str(args["claim_type"]))
    except ValueError:
        return {"error": f"unknown claim_type {args.get('claim_type')!r}", "recorded": False}
    statement = str(args["statement"]).strip()
    if not statement:
        return {"error": "statement must not be empty", "recorded": False}
    evidence_ids = tuple(str(e) for e in args.get("evidence_ids", []))

    calculation: AgentCalculation | None = None
    method_raw = args.get("method")
    if method_raw:
        try:
            method = CalculationMethod(str(method_raw))
            claimed = Decimal(str(args["claimed_value"]))
        except (ValueError, InvalidOperation, KeyError):
            return {"error": "invalid calculation method/claimed_value", "recorded": False}
        calculation = AgentCalculation(
            method=method,
            calculation_version=CALC_VERSION,
            parameters={str(k): str(v) for k, v in (args.get("parameters") or {}).items()},
            input_series_ids=tuple(str(s) for s in args.get("series_ids", [])),
            claimed_value=claimed,
            units=str(args.get("units", "ratio")),
        )

    claim = AgentClaim(
        claim_id=AgentClaim.make_id(claim_type, statement, evidence_ids),
        claim_type=claim_type,
        statement=statement,
        evidence_ids=evidence_ids,
        calculation=calculation,
        attributed_to=(str(args["attributed_to"]) if args.get("attributed_to") else None),
    )
    ctx.candidate_claims.append(claim)
    # Deliberately does NOT return a verdict: verification is independent.
    return {"recorded": True, "claim_id": claim.claim_id, "status": "pending_independent_review"}


def _date_to_dt(iso_date: str) -> datetime | None:
    """Parse an ISO date (YYYY-MM-DD) to a UTC midnight datetime, or None."""
    try:
        return datetime.fromisoformat(iso_date).replace(tzinfo=UTC)
    except ValueError:
        return None


def _unavailable(result: UnavailableSource) -> dict[str, Any]:
    return {
        "available": False,
        "source": result.source,
        "reason": result.reason,
        "detail": result.detail,
    }


# --------------------------------------------------------------------------
# Specs
# --------------------------------------------------------------------------


def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="get_historical_prices",
        description=(
            "Fetch real daily closing prices for a stock/ETF symbol from the "
            "market-data provider. Preserves the data as evidence and returns a "
            "series_id usable with `calculate`."
        ),
        parameters=_obj(
            {
                "symbol": {"type": "string", "description": "Ticker, e.g. SPY, AAPL, XLK"},
                "lookback_days": {
                    "type": "integer",
                    "description": "Calendar days of history to fetch (default 60)",
                },
            },
            ["symbol"],
        ),
        handler=_handle_get_historical_prices,
    ),
    ToolSpec(
        name="get_market_quote",
        description="Fetch the latest trade price for a symbol (preserved as evidence).",
        parameters=_obj({"symbol": {"type": "string"}}, ["symbol"]),
        handler=_handle_get_market_quote,
    ),
    ToolSpec(
        name="get_sec_financials",
        description=(
            "Fetch a company's quarterly us-gaap financial concept series from SEC "
            "EDGAR (e.g. revenue, operating_income, net_income). Returns a series_id."
        ),
        parameters=_obj(
            {
                "ticker": {"type": "string"},
                "concept": {
                    "type": "string",
                    "description": "revenue | operating_income | net_income | us-gaap tag",
                },
            },
            ["ticker", "concept"],
        ),
        handler=_handle_get_sec_financials,
    ),
    ToolSpec(
        name="get_economic_series",
        description=(
            "Fetch an economic series (CPI, Treasury yields, etc.). Reports "
            "unavailable when no economic-data key is configured."
        ),
        parameters=_obj({"series_id": {"type": "string"}}, ["series_id"]),
        handler=_handle_get_economic_series,
    ),
    ToolSpec(
        name="calculate",
        description=(
            "Run a deterministic calculation over preserved series. Methods: "
            "period_return, cumulative_return, max_drawdown, realized_volatility "
            "(parameters.periods_per_year), moving_average (parameters.window), "
            "relative_performance (two series), correlation (two series)."
        ),
        parameters=_obj(
            {
                "method": {"type": "string"},
                "series_ids": {"type": "array", "items": {"type": "string"}},
                "parameters": {"type": "object"},
            },
            ["method", "series_ids"],
        ),
        handler=_handle_calculate,
    ),
    ToolSpec(
        name="submit_claim",
        description=(
            "Record a CANDIDATE claim for independent verification. You cannot set "
            "its verdict. For a quantitative claim, supply method, series_ids, "
            "parameters, and claimed_value (a string) so it can be recomputed. "
            "Every claim must cite evidence_ids that support that specific claim."
        ),
        parameters=_obj(
            {
                "claim_type": {
                    "type": "string",
                    "description": (
                        "quantitative | observation | historical_comparison | "
                        "attributed_statement | interpretation | hypothesis | forecast"
                    ),
                },
                "statement": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "method": {"type": "string"},
                "series_ids": {"type": "array", "items": {"type": "string"}},
                "parameters": {"type": "object"},
                "claimed_value": {"type": "string"},
                "units": {"type": "string"},
                "attributed_to": {"type": "string"},
            },
            ["claim_type", "statement", "evidence_ids"],
        ),
        handler=_handle_submit_claim,
    ),
)


class ToolRegistry:
    """Holds tool specs; validates arguments; dispatches to handlers."""

    def __init__(self, specs: tuple[ToolSpec, ...] = _SPECS) -> None:
        self._specs = {spec.name: spec for spec in specs}

    def function_schemas(self) -> list[dict[str, Any]]:
        """Responses-API function tool definitions."""
        return [
            {
                "type": "function",
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            }
            for spec in self._specs.values()
        ]

    def names(self) -> tuple[str, ...]:
        return tuple(self._specs)

    def execute(self, name: str, arguments: str, context: ToolContext) -> dict[str, Any]:
        spec = self._specs.get(name)
        if spec is None:
            return {"error": f"unknown tool {name!r}", "ok": False}
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError as exc:
            return {"error": f"arguments are not valid JSON: {exc}", "ok": False}
        if not isinstance(args, dict):
            return {"error": "arguments must be a JSON object", "ok": False}
        error = _validate_args(spec.parameters, args)
        if error is not None:
            return {"error": error, "ok": False}
        try:
            return spec.handler(context, args)
        except KeyError as exc:  # missing required field slipped through
            return {"error": f"missing argument {exc}", "ok": False}


def _validate_args(schema: dict[str, Any], args: dict[str, Any]) -> str | None:
    """Minimal JSON-schema check: required keys present and basic types match."""
    for key in schema.get("required", []):
        if key not in args:
            return f"missing required argument {key!r}"
    properties = schema.get("properties", {})
    for key, value in args.items():
        prop = properties.get(key)
        if prop is None:
            continue
        expected = prop.get("type")
        if not _type_ok(expected, value):
            return f"argument {key!r} must be of type {expected}"
    return None


def _type_ok(expected: str | None, value: Any) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True
