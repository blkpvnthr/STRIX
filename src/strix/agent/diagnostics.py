"""Developer-facing agent diagnostics.

Prints the resolved (redacted) configuration and, unless ``--offline`` is given,
performs a minimal-cost live connectivity check: a free model-availability
lookup plus one tiny Responses-API call. Reports status, token usage, and the
exact estimated cost. The API key is never printed.

Run:  ``python -m strix.agent.diagnostics [--offline]``
"""

from __future__ import annotations

import sys
from typing import TextIO

from strix.agent import AGENT_VERSION
from strix.agent.budget import BudgetTracker
from strix.agent.config import DEFAULT_PRICING, AgentConfig
from strix.agent.contracts import TokenUsage
from strix.agent.openai_provider import OpenAIProvider
from strix.errors import AgentError


def run_diagnostics(
    *,
    offline: bool = False,
    out: TextIO | None = None,
    config: AgentConfig | None = None,
    provider: OpenAIProvider | None = None,
) -> int:
    """Run diagnostics; return a process exit code (0 ok, 1 on error).

    ``config`` and ``provider`` are injectable for tests; when omitted,
    configuration is loaded from the environment and a real provider is built.
    """
    stream = out if out is not None else sys.stdout
    if config is None:
        try:
            config = AgentConfig.load()
        except AgentError as exc:
            stream.write(f"Configuration error: {exc}\n")
            return 1

    stream.write(f"STRIX agent diagnostics (agent v{AGENT_VERSION})\n\n")
    stream.write("Configuration:\n")
    for key, value in sorted(config.redacted().items()):
        stream.write(f"  {key}: {value}\n")

    cheapest = min(DEFAULT_PRICING, key=lambda m: _combined(m))
    stream.write(f"\nCheapest permitted model: {cheapest}\n")
    if config.model != cheapest and not config.allow_model_escalation:
        stream.write(
            f"  note: configured model {config.model} is not the cheapest; "
            f"escalation is disabled.\n"
        )

    if offline:
        stream.write("\nOffline mode: skipped live connectivity check.\n")
        return 0

    stream.write("\nLive connectivity check:\n")
    try:
        if provider is None:
            provider = OpenAIProvider(config)
        available = provider.check_model_available()
        stream.write(f"  model available: {available}\n")
        budget = BudgetTracker(config)
        response = provider.create_response(
            input="Reply with exactly: STRIX connectivity OK",
            max_output_tokens=64,
        )
        cost = budget.record_model_call(response.usage)
        stream.write(f"  response status: {response.status}\n")
        stream.write(f"  output: {response.output_text!r}\n")
        stream.write(f"  tokens: {_usage_line(response.usage)}\n")
        stream.write(
            f"  estimated cost: ${cost.total_cost_usd} "
            f"(pricing {cost.pricing_version})\n"
        )
    except AgentError as exc:
        stream.write(f"  FAILED: {exc}\n")
        return 1
    stream.write("\nOK\n")
    return 0


def _combined(model: str) -> float:
    inp, _cached, out = DEFAULT_PRICING[model]
    return float(inp) + float(out)


def _usage_line(usage: TokenUsage) -> str:
    return (
        f"input={usage.input_tokens} cached={usage.cached_input_tokens} "
        f"output={usage.output_tokens} reasoning={usage.reasoning_tokens} "
        f"total={usage.total_tokens}"
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    return run_diagnostics(offline="--offline" in args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
