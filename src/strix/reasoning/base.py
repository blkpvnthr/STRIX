"""The reasoner protocol — the seam where constrained reasoning plugs in.

A reasoner receives ONLY the research spec and the curated evidence bundle.
It must not read files, environment variables, the network, credentials, or
terminal state, and it must not compute new authoritative financial values —
every number in its claims must be copied from cited evidence.

A future PR may add a schema-constrained LLM adapter behind this protocol.
The current implementation (:class:`~strix.reasoning.deterministic_demo.
DeterministicDemoReasoner`) is plain deterministic code, not an LLM.
"""

from __future__ import annotations

from typing import Protocol

from strix.models import Claim, Evidence, ResearchSpec


class Reasoner(Protocol):
    """Turns a curated evidence bundle into structured, citable claims."""

    def analyze(self, spec: ResearchSpec, evidence: list[Evidence]) -> list[Claim]:
        """Construct claims that cite the supplied evidence by ID."""
        ...
