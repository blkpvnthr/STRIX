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

## R4 adaptive assurance (§11)

| Requirement | Module | State |
|---|---|---|
| Deterministic, auditable, fail-closed policy adaptation (fast-tighten/slow-relax) | `assurance/adaptive` | OFFLINE_TESTED |
| Hard safety floor (never tolerate HIGH/INSUFFICIENT; tier bounded; never bypass gateway) | `assurance/adaptive` | OFFLINE_TESTED |
| Live wiring of the adaptive tier into the gateway acceptance bar | — | NOT_STARTED (Wave 4 integration) |

## R2 operational assurance (§7/E) + governed lifecycle (§4)

| Requirement | State |
|---|---|
| Six pillars + gateway + signing + uncertainty + monitoring | OFFLINE_TESTED |
| Governed lifecycle (request→…→audit) over admitted findings | OFFLINE_TESTED |
| Assurance inspector (independent re-verify of chain + signatures; report render) | `assurance/inspector` | OFFLINE_TESTED |
| Adaptive-assurance tier adaptation (deterministic, fail-closed) | `assurance/adaptive` | OFFLINE_TESTED |
| Governed envelope over the research agent (gateway+audit+signing+monitor) | `agent/governed` | OFFLINE_TESTED |
| `strix ask` governed by default (+ `--no-assurance` escape) | `cli` | OFFLINE_TESTED |
| Web research API attaches independent assurance verdict to every job | `webapi/service` | OFFLINE_TESTED |
| Live-model evidence collection into the governed path (§7) | — | LIVE_VALIDATED EXTERNALLY_BLOCKED (GPT-6 Luna credentials) |

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
| Finance HTTP API (accounts/transactions/net-worth/income-expense) | `finance/service` + `webapi/finance_api` | OFFLINE_TESTED (exact-Decimal, money-as-string, adversarially reviewed) |
| Frontend test infra (Vitest+RTL+jsdom) + AssuranceVerdict component | `web/` | OFFLINE_TESTED (Wave 7a) |
| Finance frontend client + Overview panel (net worth + balances) | `web/finance.ts`, `web/FinanceOverview.tsx` | OFFLINE_TESTED |
| React dashboard pages (remaining finance + federal + DE) | `web/` | IN_PROGRESS — API + first page + pattern established; remaining pages follow |
| Governed financial assistant tools | — | NOT_STARTED |

## Phase V — Vercel/cloud branch reconciliation (§1/§2/§5)

Reconciled `feat/vercel-cloud-deployment` (single commit, 61 behind main) — selectively
integrated the self-contained, offline-valuable, security-critical pieces; the rest is
service-gated with a documented plan. NOT blindly merged; newer architecture preserved.

| Requirement | Module | State |
|---|---|---|
| Supabase JWT auth integrated + HARDENED (trusted issuer, instance binding from signed app_metadata, fail-closed) | `auth/supabase_jwt`, `auth/dependencies` | OFFLINE_TESTED (adversarially reviewed) |
| Auth WIRED into the API — no endpoint reachable anonymously (CRITICAL fix) | `webapi/app`, `webapi/finance_api` | OFFLINE_TESTED |
| research_jobs RLS hardened (client cannot forge status/result/cost/lease; column-GRANT) | `supabase/migrations/0001` | IMPLEMENTED; integration-test gated (no PG server) |
| GitHub Actions CI for the current app (ruff/mypy/pytest/vitest/tsc/build/smokes) | `.github/workflows/ci.yml` | IMPLEMENTED (gates verified green locally; GH-Actions-run gated) |
| Durable cloud job store + cloud_app + rate/spend limits (governed-routing + outbox reconciliation) | `jobs/*`, `webapi/cloud_app` (on branch) | NOT_INTEGRATED — Supabase/PG service-gated; requires executor↔outbox reconciliation + governed-runtime routing |
| DE-5 dbt transformations | (ancestor of main) | PRESENT (do not re-merge); dbt-run validation gated (dbt not installed) |
| Vercel/OCI/Supabase live deploy | — | NOT_STARTED (unauthorized; interactive cloud auth) |

## Phase S — Security operating modes (§10)

| Requirement | Module | State |
|---|---|---|
| Four operating modes + default-deny capability policy (fail-closed) | `security/modes` | OFFLINE_TESTED |
| `--no-assurance` escape gated (refused outside open-research mode) | `cli` + `security/modes` | OFFLINE_TESTED |
| RBAC/ABAC/document-level enforcement over the data infra | — | NOT_STARTED (needs the data infrastructure) |

## Phase C — Retrieval infrastructure (§6.C)

| Requirement | Module | State |
|---|---|---|
| Deterministic content-addressed inverted index | `retrieval/index` | OFFLINE_TESTED |
| Exact-Decimal BM25 ranking (pinned precision, no float) | `retrieval/bm25` | OFFLINE_TESTED |
| Index reconciliation (index↔corpus integrity, forged-digest + scalar-tamper detection) | `retrieval/reconcile` | OFFLINE_TESTED |
| Reproducibility contract (versions/params/precision/digest) | `retrieval/contracts` | OFFLINE_TESTED |
| Pluggable search backends (BM25 baseline + external adapter, BM25 fallback) | `retrieval/backends` | OFFLINE_TESTED |
| Live OpenSearch/Elasticsearch cluster behind the external adapter | `retrieval/backends` (adapter ready) | LIVE_VALIDATED EXTERNALLY_BLOCKED (cluster infra) |

## Phase T — Analytical datastore + hybrid retrieval (§5/§7/§8)

| Requirement | Module | State |
|---|---|---|
| Typed Decimal-safe Parquet datasets (content-addressed, atomic, integrity-validatable) | `datastore/parquet_dataset` (pyarrow) | OFFLINE_TESTED |
| Governed DuckDB analytics (parameterized, column-whitelisted, no arbitrary SQL) | `datastore/duckdb_query` (duckdb) | OFFLINE_TESTED |
| Reciprocal Rank Fusion + evidence-aware rerank (auth/integrity hard-gated) | `retrieval/fusion` | OFFLINE_TESTED |
| Deterministic embeddings + vector index + hybrid (dense+lexical) search | `retrieval/vector` | OFFLINE_TESTED |
| Real BGE-M3 embeddings / pgvector / OpenSearch cluster | — | NOT_STARTED (torch/model-download + service-gated; deterministic provider + adapter contracts in place) |

## Phase D — Durable transactional infrastructure (§4/§6)

| Requirement | Module | State |
|---|---|---|
| SQLite transactional outbox (idempotent publish, lease claim, retry/dead-letter, recovery) | `outbox/sqlite_outbox` | OFFLINE_TESTED (adversarially reviewed; 3 MAJOR fixed) |
| PostgreSQL outbox backend (same contract) | — | NOT_STARTED (PostgreSQL service-gated) |

## Phase B — DE orchestration (§7)

| Requirement | Module | State |
|---|---|---|
| Scheduler-independent DAG definitions + executor (no Airflow) | `orchestration/{dag,executor}` | OFFLINE_TESTED |
| Topological order, skip-on-failure, retries, checkpoint/resume | `orchestration/executor` | OFFLINE_TESTED |
| Airflow DAG adapter (maps the same Dag onto operators) | — | NOT_STARTED (Airflow infra-gated; core is scheduler-independent) |

## Phase K — Institutional instance isolation (§13)

| Requirement | Module | State |
|---|---|---|
| Content-addressed institution identity (id↔slug invariant) | `institutional/models` | OFFLINE_TESTED |
| Per-institution scoped context (isolated ledger root + keyring + namespaced ids) | `institutional/isolation` | OFFLINE_TESTED |
| Durable uniqueness-enforcing registry (fail-closed reload, atomic+exclusive write) | `institutional/registry` | OFFLINE_TESTED |
| Cross-institution access rejection (fail-closed) | `institutional/isolation` | OFFLINE_TESTED |

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
| C/§6.C | Retrieval infra (lexical/BM25 offline, contracts, index reconciliation) | **OFFLINE_TESTED (Wave 9 done)** |
| K/§13 | Institutional instance isolation | **OFFLINE_TESTED (Wave 10a done)** |
| I/§11 | Adaptive assurance (R4) | **OFFLINE_TESTED (Wave 10b done)** |
| B/DE | DE orchestration (DAGs + scheduler-independent entry points) | Wave 11 |

## Measured baseline (updated each wave)
- Full suite: **2233 passed, 2 skipped, 2 xfailed** (0 regressions vs `862` baseline).
- ruff zero; `mypy --strict` clean across native (+ native/backends + _c kernels),
  evidence_graph, assurance (+ adaptive), audit, reconciliation, answering, finance,
  market, research_eval, federal, retrieval, institutional.
- Adversarial defects found & fixed to date: 17 (R1) + 3 (R2) + 3 (R3) + 4 (Wave 6
  native backend) + 5 (Wave 9 retrieval, incl. 1 CRITICAL) + 4 (Wave 10a
  institutional, incl. 1 CRITICAL cross-tenant takeover) = 36. (Wave 10b adaptive
  assurance: reviewed, 0 confirmed defects — the 1 MAJOR raised was refuted.)

## Unified-calculus engine extensions (DTEC reorientation, master spec §1.1)

New requirement IDs for the six research engines + unified integration. Each **extends** the
preserved core above; the STRIX-00x / GAP-00x scheme (`docs/research/milestone-0/`) remains
authoritative for the core (S6 reconciliation: this block is the DTEC overlay, not a replacement).
Detailed algorithm specs/proof obligations are confidential (§33). All `NOT_STARTED` at authoring;
all research code is committed locally only (no push, blocker B-PUSH/B-VIS).

| Req ID | Engine / capability | ALG IDs | Module(s) (neutral) | Verifying tests | State |
|---|---|---|---|---|---|
| DTEC-R-N1 | Evidence dependency intelligence (`A_ind`, N_eff, conservative bound) | ALG-N1-1..6 | `evidence_graph/{dependency,lineage}.py` | `tests/evidence_graph/test_eg_dependency.py` (planned) | NOT_STARTED |
| DTEC-R-N2 | Bitemporal reasoning (`(V_i,K_i)`, two-axis `T`, leak-freedom) | ALG-N2-1..3 | `evidence_graph/temporal.py` | `tests/evidence_graph/test_eg_temporal.py` (planned) | NOT_STARTED |
| DTEC-R-N3 | Compositional calculus (`A_C`, closure, ref + Z3 entailment, counterexamples) | ALG-N3-1..6 | `evidence_graph/{calculus,inference,counterexamples}.py` | `tests/evidence_graph/test_eg_calculus.py` (planned) | NOT_STARTED |
| DTEC-R-N4 | Calibrated uncertainty & selective admission | ALG-N4-1..4 | `assurance/{calibration,abstention}.py` | `tests/assurance/test_calibration.py` (planned) | NOT_STARTED |
| DTEC-R-N5 | Resource-bounded verification (`M_B`, planner, yield) | ALG-N5-1..4 | `assurance/{verification_planner,resource_optimizer}.py` | `tests/assurance/test_verification_planner.py` (planned) | NOT_STARTED |
| DTEC-R-N6 | Institutional admissibility (`A_inst`, precedence, federation, noninterference) | ALG-N6-1..4 | `institutional/{admissibility,applicability,policy_reasoner,federation}.py` | `tests/institutional/test_admissibility.py` (planned) | NOT_STARTED |
| DTEC-R-N6-BIND | Entity binding for computation-backed assertions (additive; *refutes* relabels, never admits on untrusted provenance) | — | `institutional/applicability.py::assess_entity_binding` | `tests/institutional/test_admissibility.py` (binding tests) | OFFLINE_TESTED (sound-by-refutation; full confirm needs DTEC-NATIVE-PROV) |
| DTEC-NATIVE-PROV | Value-bound computation provenance (native `input_digest` covering input-observation values) — the real closure of TBF-INFRA-1, enabling entity binding to *confirm* | — | `native/results.py` (future) | — | NOT_STARTED (native-layer data-model change; Phase II candidate) |
| DTEC-U | Unified admission `A★`/`A_DTEC` + certificate + gateway wiring + replay | ALG-U-1,2 | `evidence_graph/calculus.py::admit_conclusion` + `assurance/gateway` + `evidence_graph/certificates` | `tests/test_dtec_integration.py` (planned) | NOT_STARTED |
| DTEC-EV | Scientific evaluation + ablations (engine benchmarks, `Δ_i`/`Δ_ij`) | — | `research_eval/*` + `research/experiments/*` | `tests/research_eval/*` (planned) | NOT_STARTED |
