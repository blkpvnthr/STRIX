"""STRIX — Structured Traceability, Retrieval, and Intelligence eXtraction.

An evidence-grounded research pipeline prototype. Every reported number
traces through a typed lineage:

    SourceArtifact -> SourceFact -> CalculationResult -> Evidence -> Claim

The v1 pipeline is a fully offline synthetic/SEC demonstration (no LLM). v0.2.0
adds the evidence-grounded OpenAI research agent (``strix.agent``) and a web app,
in which a language model only proposes claims an independent verifier must
confirm. No investment advice is produced and no trades can be placed.
"""

__version__ = "0.3.0.dev0"

# Version of the deterministic v1 research-pipeline *contract*. Recorded in every
# v1 ResearchSpec and RunManifest so replays can detect contract drift. This is
# intentionally independent of the release version (__version__): the v1 contract
# has not changed in v0.2.0.
PIPELINE_VERSION = "0.1.0"
