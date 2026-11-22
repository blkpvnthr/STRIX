# STRIX OpenAI Research Agent — Design

Date: 2026-11-22
Status: Approved (user directive: "Both, CLI then web"; proceed without routine approval gates)

## 1. Objective

Add an evidence-grounded, OpenAI-powered research agent to STRIX so users can ask
natural-language questions about markets, economic conditions, securities, and
historical behaviour, and receive **independently verified, cited** answers. Two
interfaces over **one shared research engine**:

```
CLI     -> STRIX Research Engine
Web UI  -> Research API (FastAPI) -> STRIX Research Engine
```

Both must produce equivalent verified research artifacts.

## 2. Verified facts (checked against the live API/SDK, not assumed)

- Key authenticates. **The `.env` var is `OPEN_AI_API_KEY`, not `OPENAI_API_KEY`** —
  config maps it explicitly; the SDK will not auto-read it.
- All four candidate models exist on this key. `gpt-6-luna` is present and is the
  **cheapest**: $0.10 / $0.01 / $0.50 per 1M (input / cached-input / output) —
  matching the spec's assumptions exactly. Pricing verified at
  developers.openai.com/api/docs/pricing.
- Live Responses API call to `gpt-6-luna` with `reasoning={"effort":"low"}`
  succeeded (`status=completed`). Usage fields: `usage.input_tokens`,
  `usage.input_tokens_details.cached_tokens` / `.cache_write_tokens`,
  `usage.output_tokens`, `usage.output_tokens_details.reasoning_tokens`,
  `usage.total_tokens`. SDK: `openai==3.57.0`.
- Test baseline: **507 passed / 3 failed**. The 3 failures pre-exist and are
  environmental — `test_nothing_in_this_module_touches_the_real_evidence_root`
  hardcodes `/Users/blkpvnthr/STRIX/docs` and asserts it is empty, but that dir
  now holds the mkdocs docs + `.DS_Store`. Not caused by this work.

## 3. Key design decisions

- **Parallel contracts, shared discipline.** The existing `Evidence`/`Claim`/
  `VerificationResult` models are bound to one domain (operating-margin-change).
  The agent gets its own broader typed contracts in `strix.agent.contracts`
  (per spec §9–11: `AgentEvidence`, `AgentClaim`, `ClaimVerification`, verdicts
  VERIFIED/CONTRADICTED/INSUFFICIENT_EVIDENCE/UNVERIFIABLE/STALE). They **reuse**
  `strix.canonical` (hashing, `make_id`, Decimal-only), frozen pydantic models,
  and the "model proposes → independent verifier decides" separation.
- **Reuse, don't rebuild.** EDGAR connector (`sources/edgar.py`), `RunStore`
  atomic persistence, `canonical` hashing, deterministic-analytics style, the
  `Reasoner` seam philosophy. New deterministic calculators (return, drawdown,
  realized vol, moving average, relative performance, correlation) follow
  `analytics/profitability.py` exactly (local Decimal context, versioned,
  content-ID'd).
- **The LLM never assigns verification status.** It proposes candidate claims
  with calculations+parameters; the independent engine recomputes from preserved
  observations and sets the verdict. Numerical verifier never compares one
  model-produced value to another.
- **Fail closed.** Final answer is validated: every citation must resolve, every
  number must match an accepted calculation, rejected claims never render as fact.
  If generated prose can't be checked, render verified claims via deterministic
  templates instead.
- **Budget is enforced in code**, not advisory. `BudgetTracker` caps model calls,
  tool calls, output tokens, wall-clock seconds, and USD cost (priced from a
  versioned pricing table). A tool whose cost can't be bounded is disabled under
  strict budget.
- **Security.** Key is loaded from `.env`, never logged/printed/committed/returned
  to the frontend. `.env` is gitignored (confirmed). External documents are
  untrusted data, not instructions (prompt-injection defense in system prompt +
  tests). Internal artifact paths never exposed to unauthorized users.

## 4. Module layout (`src/strix/agent/`)

```
config.py            AgentConfig + .env loader (maps OPEN_AI_API_KEY), limits, pricing
contracts.py         AgentEvidence, AgentClaim, Calculation, ClaimVerification, usage/cost
budget.py            BudgetTracker — usage accounting + limit enforcement
openai_provider.py   OpenAIProvider — Responses API, timeouts, bounded retries, typed usage
prompts/market_research.md   versioned system instructions (spec §6)
diagnostics.py       developer connectivity/status check (no secrets)
tool_registry.py     typed tools, arg validation, permissions, budgets   (Phase 2)
evidence_collector.py  register_evidence, content hashing, persistence    (Phase 2)
calculators.py       deterministic return/drawdown/vol/MA/relperf/corr    (Phase 2)
connectors/          market data (Alpaca), economic (FRED/BLS), web search (Phase 2)
planner.py           question -> structured research plan                 (Phase 3)
orchestrator.py      bounded research loop (budget/step limits)           (Phase 3)
claim_builder.py     candidate claim construction                         (Phase 3)
verifier.py          independent claim verification engine                (Phase 3)
response_builder.py  grounded answer assembly (deterministic rendering)   (Phase 3)
response_validator.py final-answer validation (fail closed)               (Phase 3)
run_store.py         agent-run persistence via RunStore.persist_generic   (Phase 3)
```

Central `errors.py` gains an `AgentError` subtree (consistent with the repo's
single-hierarchy convention).

## 5. Config (env, with spec defaults)

`STRIX_LLM_PROVIDER=openai`, `STRIX_LLM_MODEL=gpt-6-luna`,
`STRIX_LLM_REASONING_EFFORT=low`, `STRIX_LLM_MAX_OUTPUT_TOKENS=4096`;
agent caps: `MAX_MODEL_CALLS=8`, `MAX_TOOL_CALLS=16`, `MAX_RESEARCH_SECONDS=120`,
`MAX_INPUT_TOKENS=100000`, `MAX_TOTAL_OUTPUT_TOKENS=16000`, `MAX_COST_USD=0.05`;
flags `ALLOW_MODEL_ESCALATION=false`, `REQUIRE_VERIFIED_CLAIMS=true`,
`REQUIRE_CITATIONS=true`, `OPENAI_WEB_SEARCH_ENABLED=true`. Unavailable model →
config error (no silent escalation). `.env.example` created with non-secret
placeholders.

## 6. Phase plan

1. OpenAI integration (config, contracts, budget, provider, prompt, diagnostics) + tests + live connectivity. ← in progress
2. Typed research tools + evidence collection + deterministic calculators + connectors.
3. Orchestration (plan → tools → evidence → claims → independent verify → grounded answer → validate → persist).
4. CLI `strix ask "…"`.
5. FastAPI Research API + React/TS/Vite/Tailwind dark web UI (chat, inline citations, evidence inspector, follow-ups, history, cost, cancel).
6. Tests (spec §17), live demos (spec §18) within budget, docs.

## 7. Verification scope honesty

Numerical + source-integrity + bounded textual (direct attribution, field-value)
verification only. No general NL entailment; ambiguous causal/interpretive claims
stay explicitly labelled unverified. Cryptographic artifact integrity is kept
distinct from factual/numerical verification.
