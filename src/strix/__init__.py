"""STRIX — Structured Traceability, Retrieval, and Intelligence eXtraction.

An evidence-grounded research pipeline prototype. Every reported number
traces through a typed lineage:

    SourceArtifact -> SourceFact -> CalculationResult -> Evidence -> Claim

This first version is a fully offline synthetic demonstration: no real
financial data is collected, no LLM is called, no investment advice is
produced, and no trades can be placed.
"""

__version__ = "0.1.0"

# Version of the deterministic research pipeline contract. Recorded in every
# ResearchSpec and RunManifest so replays can detect contract drift.
PIPELINE_VERSION = "0.1.0"
