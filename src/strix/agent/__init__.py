"""STRIX OpenAI research-agent subsystem.

An evidence-grounded research agent layered on the existing STRIX core. The
model proposes candidate claims; an independent verifier (never the model)
recomputes numbers from preserved observations and assigns verdicts. The
subsystem reuses :mod:`strix.canonical` hashing, :class:`strix.run_store.RunStore`
persistence, the SEC EDGAR connector, and the frozen-pydantic / Decimal-only
discipline of the rest of the codebase.
"""

from __future__ import annotations

#: Version stamped on agent research runs and reported by diagnostics.
AGENT_VERSION = "0.2.0"

#: Identifier of the versioned system-instruction file (prompts/market_research.md).
AGENT_INSTRUCTION_VERSION = "market_research/1.0.0"

__all__ = ["AGENT_INSTRUCTION_VERSION", "AGENT_VERSION"]
