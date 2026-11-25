# STRIX SBIR — Requirements-to-Implementation Traceability

Branch `research/formal-evidence-verification`. Classification states:
NOT_STARTED · IN_PROGRESS · IMPLEMENTED · OFFLINE_TESTED · INTEGRATION_TESTED ·
LIVE_VALIDATED · EXPERIMENTALLY_EVALUATED · DEPLOYED · EXTERNALLY_BLOCKED.

> A missing credential blocks LIVE_VALIDATED, not IMPLEMENTED/OFFLINE_TESTED.
> This matrix is updated continuously; see `milestone-tracker.md` for blockers
> and `final-completion-report.md` for the honest summary.

## Foundational six-pillar assurance (§4) — the permanent core

| Pillar | Module(s) | State |
|---|---|---|
| Evidence verification | `evidence_graph` (predicates, admission) | OFFLINE_TESTED |
| Policy enforcement | `evidence_graph` policies + `assurance/authorization` | OFFLINE_TESTED |
| Behavior monitoring | `assurance/monitoring` | OFFLINE_TESTED |
| Uncertainty scoring | `assurance/uncertainty` | OFFLINE_TESTED |
| Adversarial testing | per-subsystem reviews + regression suites | OFFLINE_TESTED |
| Decision traceability | `audit` ledger + `assurance/lifecycle` | OFFLINE_TESTED |
| Authorization gateway (5 outcomes) | `assurance/gateway` | OFFLINE_TESTED |
| Signed certificates (Ed25519) | `assurance/signing` | OFFLINE_TESTED |

## R1 evidence-verification substrate (§6–§13)

| Requirement | Module | State |
|---|---|---|
| Native CPU quant layer (§6/§7) | `native/*` + `backends/python_reference` | OFFLINE_TESTED |
| Typed evidence graph + 5 predicates + 4 certs + §11 invariants | `evidence_graph/*` | OFFLINE_TESTED |
| GAP-001 authorization + sandbox + §20 outcome | `assurance/{authorization,executor,outcome}` | OFFLINE_TESTED |
| GAP-002 durable hash-chained ledger | `audit/*` | OFFLINE_TESTED |
| GAP-003 reconciliation + anomaly screening | `reconciliation/*` | OFFLINE_TESTED |
| Answer-first synthesis + validation | `answering/*` | OFFLINE_TESTED |
| Native C CPU backend via ctypes + parity certification (§8/L/§35) | `native/_c/*` + `native/backends/{native_build,native_cpu,parity}` | OFFLINE_TESTED (parity-certified, max \|Δ\|=4.8e-13 vs reference) |
| C++ / Metal GPU native backends (§8/L) | design in `native-computing-architecture.md` | EXTERNALLY_BLOCKED (Metal GPU runtime; pybind11 not needed — ctypes used) |

## R2 operational assurance (§7/E) + governed lifecycle (§4)

| Requirement | State |
|---|---|
| Six pillars + gateway + signing + uncertainty + monitoring | OFFLINE_TESTED |
| Governed lifecycle (request→…→audit) over admitted findings | OFFLINE_TESTED |
| Live wiring into `strix ask`/API/frontend/scheduled research (§7) | IN_PROGRESS (Wave 4) |

## Phase G — Financial market intelligence (§9)

| Requirement | Module | State |
|---|---|---|
| Technical indicators (SMA/EMA/RSI/MACD/ATR/DMI/ADX/vol/drawdown/correlation) | `market/indicators` | OFFLINE_TESTED |
| Market universe (indexes vs ETF proxies, feed semantics) | `market/universe` | OFFLINE_TESTED |
| Scheduled market enrichment, news/sentiment, live sources | — | NOT_STARTED / live-source-gated |

## Phase H — STRIX Personal (§10)

| Requirement | Module | State |
|---|---|---|
| Double-entry ledger (decimal-safe, invariants) | `finance/ledger` | OFFLINE_TESTED |
| Canonical transaction model | `finance/transactions` | OFFLINE_TESTED |
| CSV import | `finance/imports` | OFFLINE_TESTED |
| OFX/QFX import | `finance/imports_ofx` | OFFLINE_TESTED |
| Account management + ownership + status | `finance/accounts` | OFFLINE_TESTED |
| Categorization + merchant normalization | `finance/categorize` | OFFLINE_TESTED |
| Transfer / credit-card-repayment matching (max bipartite) | `finance/transfers` | OFFLINE_TESTED |
| Budgets + savings goals + variance + projection | `finance/budgets` | OFFLINE_TESTED |
| Bills: recurring detection, calendar, reminders (offline adapter) | `finance/bills` | OFFLINE_TESTED |
| Spending anomaly detection | `finance/anomaly` | OFFLINE_TESTED |
| Portfolio: allocation/concentration/TWR/MWR/drift/rebalancing | `finance/portfolio` | OFFLINE_TESTED |
| Monthly accounting workflow + statements + reconciliation + period close | `finance/accounting` | OFFLINE_TESTED |
| Read-only provider adapters (Plaid/Teller/SnapTrade/Alpaca) | `finance/connectors` (fixture-backed) | OFFLINE_TESTED; LIVE_VALIDATED EXTERNALLY_BLOCKED (credentials) |
| React dashboard pages (18) | `web/` | NOT_STARTED (Wave 7) |
| Governed financial assistant tools | — | NOT_STARTED (Wave 4) |

## Phase M — Experimental program (§15)

| Requirement | Module | State |
|---|---|---|
| Benchmark dataset + ground-truth schema | `research_eval/dataset` | OFFLINE_TESTED |
| Metric scoring (offline) | `research_eval/scoring` | OFFLINE_TESTED |
| Statistical analysis (bootstrap/paired/BH) | `research_eval/analysis` | OFFLINE_TESTED |
| Run harness + cost accounting + checkpoint/recovery | `research_eval/runner` | OFFLINE_TESTED |
| Live 120/1200-q benchmark; H1–H12 | — | NOT_EVALUATED (budget/credentials) |

## Phase N — Federal spending integrity (§12)

| Requirement | Module | State |
|---|---|---|
| Typed award models (6 distinct money kinds, never conflated) | `federal/models` | OFFLINE_TESTED |
| Read-only connectors (USAspending/SAM/Treasury/GAO) | `federal/connectors` (fixture-backed) | OFFLINE_TESTED; LIVE_VALIDATED EXTERNALLY_BLOCKED (live ingestion) |
| Procurement analytics (contractor resolution, graph, concentration) | `federal/analytics` | OFFLINE_TESTED |
| Obligation reconciliation + duplicate-reporting + anomaly screening | `federal/analytics` | OFFLINE_TESTED |
| Anomalies flagged for REVIEW, NEVER asserted as fraud | `federal/*` (non-assertion documented) | OFFLINE_TESTED |

## Phases to come (planned waves)

| Phase | Requirement | State |
|---|---|---|
| E/§7 | Gateway wired into live CLI/API/frontend + assurance inspector + financial assistant | Wave 4 |
| N/§12 | Federal domain (USAspending/SAM/Treasury/GAO adapters + procurement analytics) | **OFFLINE_TESTED (Wave 5 done)** |
| F/L/§8 | Native C backend via ctypes + parity | **OFFLINE_TESTED (Wave 6 done)** |
| H/14/§10.3 | React dashboard pages | Wave 7 |
| O/§17 | Deployment config (Docker, migrations, CI, health checks) | Wave 8 |
| C/§6.C | Retrieval infra (lexical/BM25 offline, contracts, index reconciliation) | Wave 9 |
| I/K/§11/§13 | Adaptive assurance + institutional instance isolation | Wave 10 |
| B/DE | DE orchestration (DAGs + scheduler-independent entry points) | Wave 11 |

## Measured baseline (updated each wave)
- Full suite: **2005 passed, 2 skipped, 2 xfailed** (0 regressions vs `862` baseline).
- ruff zero; `mypy --strict` clean across native (+ native/backends + _c kernels),
  evidence_graph, assurance, audit, reconciliation, answering, finance, market,
  research_eval, federal.
- Adversarial defects found & fixed to date: 17 (R1) + 3 (R2) + 3 (R3) + 4 (Wave 6
  native backend) = 27.
