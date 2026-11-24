# STRIX
## Structured Traceability, Retrieval, and Intelligence eXtraction

It sounds like a serious intelligence system, and Strix is associated with owls—observation, knowledge, and seeing what others miss.

STRIX is an evidence-grounded research pipeline prototype. Every number it
reports traces through a typed, hash-verified lineage:

```
SourceArtifact -> SourceFact -> CalculationResult -> Evidence -> Claim -> Verified report
```

An interactive CLI turns a research question into a validated specification,
extracts facts from a preserved source artifact, runs deterministic Decimal
calculations, builds citable evidence, constructs a structured claim, verifies
every citation and number, renders a terminal report, and persists a fully
replayable run directory.

**What STRIX is not:** it is a research and decision-support prototype — not an
automated trading system and not a source of investment advice. Its original v1
pipeline reasoner is deterministic Python (no LLM); STRIX now *also* includes an
evidence-grounded **OpenAI research agent** (see below) in which the model only
proposes claims an independent verifier must confirm — the model can never mark
its own output verified.

## Data sources

| Ticker | Source | Network |
|---|---|---|
| `DEMO` | Bundled synthetic fixture (fictional "Demonstration Company") | None — fully offline |
| Any real ticker (e.g. `AAPL`) | SEC EDGAR company facts (XBRL, as filed) | Fetch time only |

No API keys or credentials are required. SEC EDGAR is a public API; STRIX
sends the fair-access `User-Agent` header. The fetched raw bytes are preserved
inside each run directory, so **replay never touches the network** — even for
real-data runs.

The DEMO fixture is clearly synthetic and must never be presented as real
financial data.

## Installation

Requires Python 3.11+.

```bash
cd /Users/blkpvnthr/STRIX     # or wherever you cloned the repository
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
strix --help
```

## Usage

Interactive research run (deterministic v1 pipeline):

```bash
strix   # Press Enter for offline DEMO, or enter AAPL for live SEC data
```

(`python -m strix` is equivalent.) For the OpenAI research agent and web app, see
the [OpenAI Research Agent](#openai-research-agent-strix-ask--web-app) section.

```
Ticker [DEMO]:
> 
Research question [Is operating profitability improving?]:
> 
As-of date [2026-08-08]:
> 
...
Finding

Operating margin increased from 8.4% to 10.1%, an
improvement of 1.7 percentage points.
[EV-..., EV-..., EV-...]

Verification: Passed
Research run: RUN-20260808-001

Synthetic demonstration data — not investment advice.
```

Replay a preserved run (recomputes everything and compares hashes):

```bash
strix replay RUN-20260808-001
```

Run artifacts live in `./research_runs/` by default (gitignored). Override
with `--state-dir PATH` or the `STRIX_STATE_DIR` environment variable.

## How verification works

- All financial math uses `Decimal` — binary floating point is rejected at
  every boundary (models, canonical serialization, JSON parsing).
- Facts, calculations, evidence, and claims carry content-derived IDs
  (`FACT-`, `CALC-`, `EV-`, `CL-` + SHA-256 prefix): identical inputs always
  produce identical IDs.
- The deterministic verifier rejects claims with unknown or unverified
  evidence, wrong subjects, values not knowable by the as-of date, numeric or
  unit mismatches, broken lineage, or a direction that contradicts the
  calculated change. Report prose is re-rendered from verified structured
  values, so the sentence cannot silently disagree with the numbers.
- A hash proves content identity and integrity — not that the content is true.

## The reasoning boundary

`strix.reasoning.base.Reasoner` is a protocol that receives only the research
spec and the curated evidence bundle. The current implementation
(`DeterministicDemoReasoner`) is fixed, auditable Python — **not an LLM**. A
future schema-constrained LLM adapter will plug in behind the same protocol
and the same verifier; no reasoner can bypass verification, calculate
authoritative ratios, or override a failed check.

---

## OpenAI Research Agent (`strix ask` + web app)

> **v0.2.0** (release candidate) — see [`CHANGELOG.md`](CHANGELOG.md), the
> [release notes](docs/releases/v0.2.0.md), the
> [release audit](docs/releases/v0.2.0-audit.md), and the
> [research benchmark](docs/releases/v0.2.0-benchmark.md).


STRIX now includes an **evidence-grounded OpenAI research agent** that answers
natural-language questions about markets, securities, and economic conditions —
and **independently recomputes every quantitative claim** before presenting it.
It plugs in behind the same trust boundary described above: the language model
proposes candidate claims, and a verifier the model cannot influence decides
what is true.

![STRIX web app — verified answer](docs/screenshots/strix-web-answer.png)

### Model and configuration

The agent uses **GPT-6 Luna** (`gpt-6-luna`) — the cheapest of the permitted
models (`gpt-6-luna`, `gpt-6.1-terra`, `gpt-6.1-sol`, `gpt-6-astra`) at
`$0.10 / $0.01 / $0.50` per 1M input / cached-input / output tokens. The agent
never silently escalates to a costlier model; an unavailable model is a
configuration error.

Configuration is read from `.env` (see `.env.example`). The key may be set as
either `OPENAI_API_KEY` or `OPEN_AI_API_KEY`; it is held as a `SecretStr` and is
never logged, persisted, committed, or sent to the browser. Every limit below is
enforced in code:

```dotenv
STRIX_LLM_MODEL=gpt-6-luna
STRIX_LLM_REASONING_EFFORT=low
STRIX_AGENT_MAX_MODEL_CALLS=8
STRIX_AGENT_MAX_TOOL_CALLS=16
STRIX_AGENT_MAX_RESEARCH_SECONDS=120
STRIX_AGENT_MAX_COST_USD=0.05
STRIX_OPENAI_WEB_SEARCH_ENABLED=true
```

### Startup

```bash
python -m pip install -e ".[dev,web]"      # installs openai + FastAPI stack
python -m strix.agent.diagnostics          # redacted config + live connectivity check

# CLI — ask a question and get a cited, verified answer
strix ask "What is the recent realized volatility of SPY?"
strix replay RUN-YYYYMMDD-NNN              # deterministically re-verify a run

# Web app (single command serves API + built UI at http://127.0.0.1:8000)
( cd web && npm install && npm run build )
strix-web                                  # or: python -m strix.webapi.app
```

For live frontend development with hot reload, run `strix-web` (port 8000) and,
in `web/`, `npm run dev` (port 5173, proxies `/api` to the backend).

### Research tools and data sources

| Tool | Source | Credentials |
|---|---|---|
| `get_historical_prices`, `get_market_quote` | Alpaca Market Data (live) | `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` |
| `get_sec_financials` | SEC EDGAR company facts | none (public) |
| `get_economic_series` | FRED/BLS | none configured → returns structured *unavailable* |
| `search_current_information` | OpenAI hosted web search | the OpenAI key |
| `calculate` | Deterministic calculators (return, drawdown, realized vol, moving average, relative performance, correlation) | — |
| `submit_claim` | Records a **candidate** claim (status `pending`); cannot set a verdict | — |

Connectors return real preserved data or a structured *unavailable* result —
they never fabricate values.

### Evidence-verification lifecycle

```
question -> bounded tool loop (fetch -> calculate -> submit_claim)
         -> preserve evidence (SHA-256) + observation series
         -> INDEPENDENT verifier recomputes every number
         -> VERIFIED | CONTRADICTED | INSUFFICIENT_EVIDENCE | UNVERIFIABLE | STALE
         -> deterministic, fail-closed answer -> persisted + replayable
```

- A quantitative claim is **VERIFIED** only if the verifier reproduces its value
  from the preserved observations within tolerance. A wrong number is
  **CONTRADICTED** and never shown as fact.
- Textual claims get a bounded *attribution* check against preserved excerpts —
  that verifies the source was retrieved and contains the text, **not** that the
  statement is objectively true. Interpretations, hypotheses, and forecasts are
  always **UNVERIFIABLE** by type.
- A citation alone never qualifies an assertion: each verified claim's evidence
  must resolve, and quantitative claims must carry an independent recomputation.
- Retrieved documents and web content are treated as **untrusted data**, never
  as instructions.

Every citation opens an **evidence inspector** (provider, source URL, published
and retrieved dates, freshness, SHA-256 integrity, related claims):

![Evidence inspector](docs/screenshots/strix-web-evidence.png)

### Cost, security, and verification limitations

- **Cost** is accounted per run (input / cached / output / reasoning tokens
  without double-counting, model + tool calls, USD) against a versioned pricing
  table, and enforced against `STRIX_AGENT_MAX_COST_USD`. The eight demonstration
  questions cost **~$0.015 total**; a typical run is a fraction of a cent.
- **Security**: the API key never reaches the frontend; `.env` is gitignored;
  prompt-injection from sources is defended in the system prompt and tests. The
  local web API binds `127.0.0.1` with localhost-only CORS and has **no
  authentication** — it is a single-user local tool; do not expose the port.
- **Verification is bounded and honest**: numerical recomputation and source
  integrity are strong; general natural-language entailment is *not* attempted.
  Without a FRED/BLS key, economic questions (CPI, Treasury yields) rely on web
  search and are reported as attribution-only or insufficient evidence rather
  than fabricated. Cryptographic artifact integrity is kept distinct from factual
  verification.

---

## Financial Intelligence Lakehouse (v0.3.0, in development)

STRIX is growing a persistent, warehouse-backed data platform behind the same
evidence and verification guarantees. Raw provider bytes are preserved
immutably (**Bronze**), normalized into typed Decimal Parquet (**Silver**), and
loaded into a dimensional analytical **warehouse** — **DuckDB** locally (no paid
infrastructure) with an optional, offline-tested **Snowflake** target. The
warehouse never *confers* verification: the independent verifier still recomputes
every claim, and every warehouse row resolves back to the Bronze artifact it came
from. See [`docs/data-engineering/`](docs/data-engineering/).

### Bronze → Silver → warehouse flow

```mermaid
flowchart LR
  subgraph Sources["External sources"]
    A["Alpaca"]; S["SEC EDGAR"]; F["FRED / BLS"]; T["US Treasury"]
  end
  Sources --> B
  subgraph Lakehouse["Medallion lakehouse"]
    B["Bronze<br/>immutable raw bytes<br/>SHA-256 + manifest"]
    V["Silver<br/>typed Decimal Parquet<br/>quality gates + dedup"]
    W["Warehouse<br/>dimensional model<br/>DuckDB · Snowflake"]
    B -- "normalize" --> V
    V -- "load_silver (txn)" --> W
  end
  W --> R["STRIX research + verifier"]
```

Loads are fail-closed: only a **balanced, hash-verified** Silver publication is
admitted, inside a single transaction that rolls back on any error — an
interrupted load never exposes partial data.

### DuckDB and Snowflake architecture

```mermaid
flowchart TB
  SP["Silver publication<br/>(Parquet + manifest)"]
  SP --> L["WarehouseLoader"]
  L -->|operational| D["DuckDB<br/>single file · single-writer<br/>read_parquet · read-only queries"]
  L -->|optional| SF["Snowflake<br/>COPY INTO + MERGE<br/>STRIX_INGEST / STRIX_RESEARCH roles<br/>auto-suspend"]
  D --> Q["WarehouseQueries<br/>parameterized · read-only"]
  SF -. credentials from SNOWFLAKE_* env .-> SF
```

### Fact and dimension relationships

```mermaid
erDiagram
  dim_date            ||--o{ fact_market_bars            : observed_on
  dim_instrument      ||--o{ fact_market_bars            : for_instrument
  dim_source          ||--o{ fact_market_bars            : from_source
  dim_evidence        ||--o{ fact_market_bars            : cites
  dim_company         ||--o{ fact_company_financials     : reports
  dim_date            ||--o{ fact_company_financials     : filed_on
  dim_economic_series ||--o{ fact_economic_observations  : measures
  dim_date            ||--o{ fact_treasury_yields        : observed_on
  dim_pipeline_run    ||--o{ fact_pipeline_runs          : records
  fact_market_bars {
    text  silver_natural_key PK
    date  session_date
    decimal open_high_low_close
    text  bronze_artifact_id
  }
  fact_company_financials {
    text  silver_natural_key PK
    text  concept
    decimal value
    date  filed_date
  }
```

Each fact's primary key is the upstream Silver `natural_key`, so reloads are
idempotent. Schema-only placeholder facts (quotes, corporate actions, sector
performance, ratios, research claims, verification results) are created but
reported as unpopulated — no invented rows.

### Incremental loading

```mermaid
flowchart TD
  P["New Silver publication"] --> C{"Already loaded?<br/>(silver_publication_id<br/>in _load_state)"}
  C -->|yes| SK["Skip (no-op)"]
  C -->|no| NK{"Per natural key"}
  NK -->|new key| INS["INSERT"]
  NK -->|"same key,<br/>changed row_signature"| UPD["UPDATE (revision)"]
  NK -->|"same key,<br/>same signature"| UNC["unchanged"]
  INS --> ST["record counts in _load_state → COMMIT"]
  UPD --> ST
  UNC --> ST
```

A revised observation (same natural key, changed `row_signature`) is an
**update**, not a duplicate; SEC restatements (distinct accession) and FRED
vintages (distinct `realtime_start`) are distinct keys, enabling true
point-in-time queries via `filed_date` / `realtime_start <= cutoff`.

### Source-to-claim lineage

```mermaid
flowchart LR
  CL["Verified claim"] --> EV["dim_evidence"]
  EV --> WR["Warehouse fact row"]
  WR --> SV["Silver publication<br/>(schema version)"]
  SV --> BR["Bronze artifact<br/>(re-hash verified)"]
  BR --> SL["Source-record locator<br/>(provider endpoint)"]
```

`strix warehouse lineage --dataset X --key NK` walks this chain end to end and
re-verifies the Bronze artifact's content hash; lineage completeness is part of
reconciliation.

### Warehouse integration with STRIX research

```mermaid
flowchart LR
  QN["Research question"] --> AG["Agent / tools"]
  AG --> WQ["WarehouseQueries<br/>(read-only, parameterized)"]
  WQ --> OBS["Observations + units<br/>+ source refs"]
  OBS --> VF["Independent verifier<br/>recomputes claims"]
  VF --> ANS["Verified answer"]
  AG -. no raw SQL, no verdicts .-> WQ
```

The model never executes raw SQL and never assigns a verdict; the warehouse
supplies observations that the verifier independently recomputes.

### Warehouse CLI

```bash
strix warehouse init [--backend duckdb|snowflake]   # create schema (DuckDB) / print DDL (Snowflake)
strix warehouse load [--dataset NAME|all] [--dry-run] [--json]
strix warehouse status | profile | reconcile | verify
strix warehouse lineage --dataset NAME --key NATURAL_KEY
```

### dbt transformation layer (DE-5)

A dbt project turns the warehouse into analyst-ready **marts** (staging →
intermediate → marts) with **DuckDB** operational and **Snowflake** optional. dbt is
invoked only through a controlled runner (fixed executable, allow-listed subcommand,
validated selection, **no shell**); the model never gets raw SQL. A mart value is
never "verified" by being published — `strix transform validate` independently
recomputes supported values from preserved evidence with the Decimal calculators. See
[`docs/data-engineering/de-5-dbt-transformations.md`](docs/data-engineering/de-5-dbt-transformations.md).

#### Warehouse → mart transformation flow

```mermaid
flowchart LR
  subgraph WH["DuckDB warehouse (DE-4)"]
    F["facts + dimensions"]
  end
  F --> STG["staging<br/>typed views<br/>lineage preserved"]
  STG --> INT["intermediate<br/>returns · vol · drawdown<br/>PIT · concept mapping"]
  INT --> M["marts (tables)"]
  subgraph M2["marts"]
    MK["markets"]; FU["fundamentals"]; MA["macroeconomics"]; RE["research"]
  end
  M --> M2
```

#### dbt model dependencies (excerpt)

```mermaid
flowchart TD
  src["source: warehouse.fact_*"] --> stg["stg_* (10)"]
  stg --> imd["int_market_daily"]
  imd --> idr["int_daily_returns"]
  imd --> ivol["int_rolling_volatility"]
  imd --> idd["int_rolling_drawdown"]
  idr --> icorr["int_cross_asset_correlation"]
  idr --> irel["int_benchmark_relative_returns"]
  stg --> isel["int_financial_period_selection"]
  seed["seed: sec_concept_map"] --> isel
  isel --> ialign["int_financial_statement_alignment"]
  ivol --> mvol["mart_market_volatility"]
  idd --> mdd["mart_market_drawdown"]
  icorr --> mcorr["mart_equity_correlations"]
  ialign --> mratio["mart_financial_ratios"]
```

#### Financial calculation lineage

```mermaid
flowchart LR
  BR["Bronze artifact<br/>(raw bytes, SHA-256)"] --> SV["Silver observation<br/>(typed Decimal)"]
  SV --> WF["warehouse fact row"]
  WF --> IN["intermediate inputs"]
  IN --> MV["mart value<br/>(SQL, versioned contract)"]
  MV -.carries.-> EV["numerator/denominator · formula_version · accession · bronze_artifact_id"]
```

#### Historical revision propagation

```mermaid
flowchart TD
  COR["corrected / restated source observation"] --> SILVER["Silver: new natural key<br/>(accession / realtime_start)"]
  SILVER --> LOAD["warehouse incremental load<br/>(update, not duplicate)"]
  LOAD --> REBUILD["dbt build --select int_market_daily+"]
  REBUILD --> WIN["all dependent rolling windows recomputed"]
  REBUILD --> RATIO["first-filed vs restated retained for PIT"]
```

#### Independent verification architecture

```mermaid
flowchart LR
  MART["dbt mart value (SQL engine)"] --> CMP{"compare<br/>within contract tolerance"}
  WF["warehouse fact inputs"] --> PY["Decimal recompute<br/>strix.agent.calculations"]
  PY --> CMP
  CMP -->|agree| OK["confirmed (+ evidence artifacts)"]
  CMP -->|differ| DIS["discrepancy (fail signal)"]
  MART -. never self-certifies .-> CMP
```

#### Mart → research-agent integration

```mermaid
flowchart LR
  QN["research question"] --> AG["agent / tools"]
  AG --> MARTS["marts (read-only)"]
  MARTS --> OBS["observations + units + evidence"]
  OBS --> VF["independent verifier recomputes"]
  VF --> ANS["verified answer"]
  AG -. no raw SQL · no verdicts .-> MARTS
```

#### Transform CLI

```bash
strix transform init [--with-deps]              # profile + schema + seed + parse
strix transform run | build | test [--select S] [--full-refresh]
strix transform docs                            # catalog + manifest + index.html
strix transform status | profile
strix transform lineage --select MODEL
strix transform validate --symbol SPY --pair SPY,QQQ --cik CIK0000320193
```

---

## Research & engineering audit

A commit-specific engineering audit and a formal research baseline live under
[`docs/research/milestone-0/`](docs/research/milestone-0/) (also served in the MkDocs
site under **Research → Milestone 0**):

- [Engineering audit](docs/research/milestone-0/engineering-audit.md) — the ten
  infrastructure components classified (implemented / partial / missing) against source
  at a pinned commit, with the corrected GAP-001/002/003 definitions.
- [Gap coverage matrix](docs/research/milestone-0/gap-coverage-matrix.md) and
  [requirements traceability](docs/research/milestone-0/requirements-traceability.md) —
  fifteen formal requirements (STRIX-001…015), each traced to source and tests; the
  machine-readable source of truth is
  [`requirements-baseline.yaml`](docs/research/milestone-0/requirements-baseline.yaml).
- [Remediation report](docs/research/milestone-0/remediation-report.md) — full test
  results, preserved known gaps, and a feasibility / go-no-go recommendation.
- [Comparative experiment design](docs/research/milestone-0/comparative-experiment-design.md)
  and the Milestone 1–3 specifications.

> These documents record established implementation facts and *falsifiable* research
> hypotheses separately. No novelty, performance, patentability, or deployment-readiness
> is claimed; the hypotheses are untested by design at this stage.

## Development

```bash
python -m pytest          # test suite (offline; sockets are blocked)
python -m ruff format .   # formatting
python -m ruff check .    # linting
python -m mypy            # strict type checking
```

Documentation (MkDocs Material):

```bash
python -m pip install -r requirements-docs.txt
mkdocs serve              # http://127.0.0.1:8000
```

## Current limitations

- One research question type: operating-margin change between two
  year-over-year quarters.
- EDGAR quarter labels use the calendar quarter of the period end date, an
  approximation for off-calendar fiscal years.
- Restated figures: STRIX deliberately uses the earliest-filed value (the
  first-known figure) for point-in-time honesty.
- The deterministic v1 pipeline (`strix`, no LLM) answers one question type:
  operating-margin change between two year-over-year quarters.
- The OpenAI research agent (`strix ask` / web app) verifies numerical claims it
  can recompute from preserved observations (returns, drawdown, realized
  volatility, moving average, relative performance, correlation); questions
  needing data sources not configured (e.g. FRED economic series) return honest
  insufficient-evidence results rather than fabricated numbers.
- No database or object storage, portfolio integration, forecasting, or trading
  — see the roadmap in `docs/development/roadmap.md`.

Future BLKPVNTHR.OS route name: `/strix`.

