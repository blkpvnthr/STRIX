"""Access to versioned, file-backed agent system instructions.

Keeping the instruction text in a file (``prompts/market_research.md``) under
version control makes the prompt reviewable and stable, which also lets the
provider reuse it verbatim across calls for prompt caching.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from strix.agent import AGENT_INSTRUCTION_VERSION

_PROMPT_DIR = Path(__file__).parent / "prompts"
_MARKET_RESEARCH = _PROMPT_DIR / "market_research.md"


@lru_cache(maxsize=1)
def market_research_instructions() -> str:
    """Return the market-research system instructions (cached)."""
    return _MARKET_RESEARCH.read_text(encoding="utf-8")


def instruction_version() -> str:
    """The identifier recorded on every run for this instruction set."""
    return AGENT_INSTRUCTION_VERSION
