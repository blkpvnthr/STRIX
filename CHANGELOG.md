# Changelog

All notable changes to STRIX are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
semantic versioning.

## [Unreleased] — Evidence-grounded conversational intelligence

Transforms the agent from an evidence-retrieval interface into a conversational,
evidence-grounded research agent that directly answers the user's question while
preserving the deterministic verification, immutable evidence, SHA-256
provenance, and replay architecture. Independent verification remains the sole
authority for factual verdicts; GPT-6 Luna (`gpt-6-luna`) remains the exclusive
model and the `$0.05`/run cap is unchanged (synthesis reserves one model call).
Not merged to `main`.

### Added
- **Question classification** (`strix.agent.question`): deterministic intent
  (factual, current-market, analytical, comparative, historical, corporate
  fundamentals, macro, predictive, scenario, follow-up), entity/ticker, asset
  class, time horizon, objectives, and evidence-requirement extraction — no model
  call.
- **Analytical synthesis** (`strix.agent.synthesis`): after verification, a
  dedicated GPT-6 Luna call writes the direct answer, analysis, conditional
  scenarios, and monitoring indicators from a compact brief. A numeric guard
  strips any number not traceable to a verified claim; a probability guard strips
  fabricated odds; both fall back to a deterministic answer. The directional
  **market assessment** (bullish/bearish/neutral/mixed/insufficient + evidence
  strength) is computed deterministically from verified claims, never asserted by
  the model.
- **Epistemic classification** (spec §6), kept separate from verification
  verdicts: VERIFIED_FACT / ATTRIBUTED_REPORT / ANALYTICAL_INFERENCE /
  CONDITIONAL_SCENARIO / FORECAST / UNRESOLVED. A verified input never makes an
  inference or forecast itself "verified".
- **Structured response contract** (`ResearchResponse`) wrapping the verified
  `ResearchAnswer`: direct_answer, analysis, market_assessment, supporting_facts,
  analytical_inferences, conditional_scenarios, contradictory_evidence,
  unresolved_findings, monitoring_indicators, sources, limitations, diagnostics.
- **Citation resolution** (`strix.agent.citations`): web-search handles are
  aliased to preserved evidence and resolved before verification; unresolvable
  handles are stripped and disclosed — the raw `turn…news…` identifier can no
  longer leak into an answer.
- **Financial sanity checks** (`strix.agent.sanity`): anomalous short-horizon
  returns, price steps, volatility, inverted/future-dated windows, non-positive
  prices, incomplete/weekend sessions — advisory flags that never change a
  verdict.
- **Conversational memory** (`strix.agent.memory`): bounded, atomic conversation
  threads carrying discussed securities, last stance, and horizon as context
  hints only (never as source evidence).
- **Replay of the response** (spec §13): hash, citation, and classification
  integrity of `response.json` are re-validated with no model call.
- **Frontend**: response reorganized into the §11 section order (direct answer →
  assessment → analysis → scenarios → interpretation → verified findings →
  sources → unresolved → monitoring → limitations → diagnostics); thread
  continuity for follow-ups.

### Fixed
- **Answer relevance** (RUN-20261123-001): forward-looking questions ("how will
  the market perform tomorrow?") no longer answer with a trailing return; the
  direct answer distinguishes current conditions from a prediction.
- **Unresolved citations** (RUN-20261123-002): the raw web-search handle
  `turn874423news19` is resolved or excluded, never shown as "unknown evidence".

## [0.2.0] — 2026-11-22

First release of the **evidence-grounded OpenAI research agent** and a web
application, layered on the existing deterministic v1 pipeline. A language model
proposes candidate claims; an independent verifier the model cannot influence
recomputes every quantitative claim from preserved observations and assigns the
verdict. Release candidate; not yet merged to `main`.

### Added
- **OpenAI research agent** (`strix.agent`): bounded tool-calling orchestration
  over GPT-6 Luna (`gpt-6-luna`), the cheapest permitted model. Typed config with
  in-code budget enforcement (model/tool calls, tokens, wall-clock, USD),
  versioned pricing, and `SecretStr` key handling.
- **Independent verification engine** (`strix.agent.verifier`): recomputes
  quantitative claims from preserved observation series; verdicts VERIFIED /
  CONTRADICTED / INSUFFICIENT_EVIDENCE / UNVERIFIABLE / STALE. Never compares a
  model value to another model value.
- **Deterministic calculators**: period/cumulative return, max drawdown,
  annualized realized volatility, moving average, relative performance, Pearson
  correlation.
- **Research tools + connectors**: live Alpaca market data, SEC EDGAR concept
  series, OpenAI hosted web search, and deterministic `calculate` / `submit_claim`
  tools. Missing connectors return structured *unavailable* results.
- **Evidence preservation**: SHA-256 content hashing, dedup, freshness
  classification; replayable run persistence (`mode=agent_research`) via the
  existing atomic `RunStore`.
- **CLI**: `strix ask "<question>"` and agent-run `strix replay RUN-...`;
  `strix-agent-diagnostics` connectivity command.
- **Web application** (`strix.webapi` + `web/`): FastAPI research API and a
  dark-first React/TypeScript/Vite/Tailwind UI — conversational research, live
  progress, inline citations, expandable evidence inspector, verification
  verdicts, source timestamps, persistent history, follow-ups, and cancellation.
  One command (`strix-web`) serves the API and the built UI.

### Changed
- `__version__` and `AGENT_VERSION` bumped to `0.2.0`. The v1
  `PIPELINE_VERSION` stays `0.1.0` (the v1 contract is unchanged).
- Attribution verification hardened to require a **verbatim substring** match
  against the preserved excerpt (removed a fuzzy keyword-overlap fallback that
  could over-claim attribution).
- README updated with the agent + web app; intro/limitations reflect that STRIX
  now has both the deterministic v1 pipeline and the verified agent.

### Fixed
- Deterministic replay now compares recomputed values **numerically**, not as
  strings, so canonical trailing-zero normalization (`0.107510` → `0.10751`) no
  longer causes a false replay failure.
- Corpus/research evidence-root guard tests no longer assume the docs directory
  is empty; they assert the tests *add nothing* to the real evidence root
  (integrity intent preserved).

### Security
- API key is read only to construct the OpenAI client, held as `SecretStr`
  (`repr=False`), excluded from dumps/logs, and never sent to the browser.
- Retrieved documents and web content are treated as untrusted data; the
  independent verifier makes prompt injection unable to grant verification.
- Web API binds `127.0.0.1` with localhost-only CORS. **Known limitation:** it
  has no authentication — see the release notes.

## [0.1.0]

- Deterministic v1 research pipeline: evidence lineage, SEC EDGAR / synthetic
  fixture sources, deterministic operating-margin verification, offline replay,
  plus the engineering compiler and scholarly-corpus subsystems.
