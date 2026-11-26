# STRIX Master SBIR Phase I Specification

**Resource-Bounded, Independently-Verified Evidence Intelligence for Trustworthy Autonomous Research**

**Repository:** `blkpvnthr/STRIX` · **Development branch:** `feature/sbir-phase-i-evidence-intelligence`
**Document status:** AUTHORITATIVE — this is the single specification of record. All other
research documents in `research/` are companion/detail documents subordinate to this one.
**Last reconciled:** 2026-11-25.

---

## 0. How to read this document

### 0.1 Status vocabulary (used throughout; never conflated)

| Tag | Meaning |
|---|---|
| `NOT_STARTED` | Designed/named here but no code written. |
| `IMPLEMENTED` | Code exists. |
| `OFFLINE_TESTED` | Exercised by unit/integration tests with measured pass results, no external service. |
| `INTEGRATION_TESTED` | Exercised across module boundaries end-to-end (still offline). |
| `LIVE_VALIDATED` | Exercised against a real external service/credential. |
| `EXPERIMENTALLY_EVALUATED` | A pre-registered scientific experiment was run and reported. |
| `NOT_EVALUATED` | No measurement/benchmark has been run (distinct from NOT_IMPLEMENTED). |
| `EXTERNALLY_BLOCKED(reason)` | Cannot proceed without a named external dependency. |

> **Honesty mandate (CLAUDE.md Principle 1 — Falsification First).** Every quantitative
> figure in §30 and §9-equivalents is a **TARGET**, never a measurement, unless a results
> document explicitly reports it as `EXPERIMENTALLY_EVALUATED` with the measured value and
> its confidence interval. Reporting a target as an outcome is fabrication and is prohibited.
> All of H1–H12 are `NOT_EVALUATED` at the time of writing; the live comparative arms
> (A/B and the live portions of C–E) are `EXTERNALLY_BLOCKED` on model credentials and budget.

### 0.2 Measured engineering baseline (reproduced 2026-11-25)

- Python suite: **2233 passed, 2 skipped, 2 xfailed** — 0 regressions vs the `862` R1 baseline.
- `ruff check src/` — clean.
- `mypy --strict src/strix` — clean across **239 source files**.
- Frontend (`web/`): `vitest` green, `tsc --noEmit` clean, `vite build` succeeds (per prior session).
- Adversarial defects found & fixed to date: **45+** (incl. several CRITICAL), each with a
  permanent regression test (§32).

These are **engineering** facts. They are *not* scientific evaluation of H1–H12 (§28).

### 0.3 Companion documents (subordinate detail)

| Topic | Document |
|---|---|
| Formal mathematics | `research/mathematical-specification.md` |
| Evidence system design | `research/formal-evidence-system.md` |
| Admission invariants | `research/claim-admission-invariants.md`, `research/numerical-contracts.md` |
| Experimental protocol | `research/experimental-protocol.md` |
| Hypothesis registry (H1–H12) | `research/hypothesis-registry.md` |
| Comparative experiment design (H1–H3, arms) | `docs/research/milestone-0/comparative-experiment-design.md` |
| Native computation | `research/native-computing-architecture.md` |
| Threat model | `research/threat-model.md` |
| Limitations / negative findings | `research/limitations.md` |
| IP / prior-art inventory | `research/intellectual-property-inventory.md` |
| NSF premise draft | `research/nsf-project-pitch.md` |
| Requirements traceability | `research/requirements-traceability.md` |
| Milestone tracker | `research/milestone-tracker.md` |
| Persistent execution ledger | `research/execution-state.md` |
| Honest status report | `research/final-completion-report.md` |
| C-Engine extraction audit (kept SEPARATE) | `research/cengine-extraction-audit.md` |
| FALCON alignment (kept SEPARATE) | `research/falcon-alignment-assessment.md` |

---

## 1. Executive technical overview

STRIX is a **model-independent, evidence-grounded research and assurance platform**. A user
submits one natural-language research question (CLI, API, or web). STRIX autonomously
retrieves and acquires authoritative evidence, performs required computations, constructs a
formal typed evidence graph, independently verifies every material claim and calculation,
enforces mandatory assurance and authorization policy, synthesizes **one intelligible answer**,
independently verifies that final answer, binds each material claim to a genuine citation,
persists replayable artifacts, and returns the answer with its supporting documentation below
it (§2, §7). The internal complexity (evidence graphs, verifiers, certificates, ledgers)
culminates in **external simplicity**: the answer is the deliverable.

The central architectural thesis (R1 §33, `nsf-project-pitch.md`): the entity that *generates*
a claim must not be the entity that *admits* it. STRIX separates an **untrusted candidate
surface** (any LLM or deterministic generator) from a **trusted, typed, versioned admission
function** evaluated independently of the generator. A claim is admitted only when a fixed set
of typed predicates all hold (§9). No language model may override a mandatory assurance
requirement (R2).

The individual building blocks (statistics, content addressing, hash-chained logs,
deterministic policy enforcement, BM25/vector retrieval) are **established methods, not asserted
as independently novel** (§33). The proposed intellectual contribution is their **composition**
into a single falsification-first, resource-bounded, independently-verified assurance pipeline,
and the empirical characterization of that composition — which is the SBIR research (§28–§30).

One **STRIX Core** serves four profiles — Research, Enterprise, Finance, Federal — through
shared retrieval, verification, federation, temporal reasoning, authorization, and replay.

## 2. Scientific research problem statement & operational outcome

### 2.1 Research question
*Can an autonomous AI research system be constrained so that every material factual assertion
it emits is independently verifiable, resource-bounded, temporally correct, and auditable —
such that unsupported or fabricated claims are rejected before they reach a human
decision-maker, rather than detected afterward — and does this composition measurably improve
factual reliability, temporal correctness, reproducibility, computational accuracy, security,
and research usefulness relative to conventional LLM and RAG architectures?*

### 2.2 The gap (`nsf-project-pitch.md` §3)
Conventional autonomous research systems bind claims to evidence only post-hoc; the generator
grades itself; "unknown" collapses into "acceptable"; resource exhaustion relaxes checks
(fails open); numeric assertions are trusted rather than recomputed. STRIX addresses the
absence of a **composed, independently-enforced, resource-bounded admission discipline**.

### 2.3 Primary operational outcome (the 17-step pipeline)
The user submits one question; STRIX autonomously: (1) interprets intent; (2) determines
domains + temporal requirements; (3) retrieves existing evidence; (4) identifies gaps;
(5) acquires authorized documentation; (6) normalizes + indexes; (7) performs analytical/
computational operations; (8) constructs the formal evidence graph; (9) reconciles
heterogeneous/contradictory sources; (10) generates candidate findings; (11) independently
verifies material claims + calculations; (12) applies assurance + authorization policy;
(13) synthesizes admitted findings into one answer; (14) independently verifies the final
answer; (15) binds material claims to genuine citations; (16) persists evidence, certificates,
manifests, replay artifacts; (17) returns one intelligible answer with documentation below it.

**The final answer — not the databases, agents, graphs, engines, or certificates — is the
principal deliverable.** The user need not understand STRIX's architecture to receive a
reliable result. Where only part of a question is verifiable, STRIX returns the verified part
with explicit limitations; where evidence is insufficient, it abstains rather than fabricate.

## 3. STRIX Core, profiles, and the model-independence boundary

**STRIX Core** is one substrate: `native` (computation), `evidence_graph` (typed evidence +
admission), `assurance` (six pillars + gateway + signing), `audit` (ledger), `reconciliation`,
`answering` (synthesis + validation), `retrieval`, `datastore`, `outbox`, `orchestration`,
`institutional`, `security`, `auth`. Profiles (Research, Enterprise, Finance, Federal) are
configurations over the same Core, never forks.

**Model independence / trust boundary** (R2; `agent/governed.py`, `agent/verifier.py`):
the agent proposer path (`agent/openai_provider.py`, `agent/orchestrator.py`) is *untrusted*;
it produces only candidate claims. The assurance path admits them independently. The boundary
is enforced by construction — the gateway (§13) is not reachable-around. `strix ask` is governed
by default; `--no-assurance` is a gated experimental baseline (§27). State: `OFFLINE_TESTED`.

## 4. Native computation layer (R4, part 1)

Portable, CPU-first, exact-arithmetic quantitative layer (`native/`): descriptive / time-series /
multivariate / inference statistics, checked exact arithmetic, typed `NumericalContract`
tolerances, a content-addressed `ComputationResult`, and a `PythonReferenceBackend` (27 ops)
as the validation baseline. Authoritative financial `Decimal`s are never converted to binary
float (`numerical-contracts.md`).

| Backend | State |
|---|---|
| `PythonReferenceBackend` (REFERENCE) | `OFFLINE_TESTED` |
| Native **C** CPU backend via ctypes + parity certification | `OFFLINE_TESTED` (parity-certified, max \|Δ\|=4.8e-13 vs reference; `strix compute parity`) |
| **C++** CPU backend | `NOT_STARTED` — interfaces writable; no runtime blocker (design in `native-computing-architecture.md`) |
| **Apple Metal** GPU backend | `EXTERNALLY_BLOCKED(GPU runtime)` — kernel source writable; execution/validation needs a GPU host |

Determinism: identical inputs → identical content-addressed result ids (exact/deterministic
classes) or within-tolerance agreement (tolerance/approximate), stochastic ops reproducible
from a recorded seed.

## 5. Formal evidence graph & typed relationships (R1)

Typed evidence graph (`evidence_graph/`): nodes for evidence artifacts, claims, computations;
typed relationships (supports / contradicts / derives-from / revises / cites). Content-addressed
identity (`canonical.make_id`) distinct from anchors — **anchors ≠ identity** (design-review
preference). Cryptographic *integrity* by content hashing; *authenticity* by Ed25519 signing
of certificates (§14). State: `OFFLINE_TESTED`.

Evidence carries: source, preserved bytes (hash), point-in-time validity window, provenance
lineage, independence metadata. Claims carry: subject, metric, value (Decimal), unit,
temporal as-of, and the evidence that attests (and does not attest) them.

## 6. Evidence & claim schemas

All models are frozen, closed-schema `StrixModel`s; every numeric field is an exact `Decimal`
that rejects `float` (`DecimalValue`); content-derived ids via `canonical.make_id`
(`answering/models.py`, `evidence_graph/*`). Claim certificates (§14) are the only admitted
carrier of a material factual claim. State: `OFFLINE_TESTED`.

## 7. The five admission predicates (I ∧ T ∧ P ∧ D ∧ S)

A candidate claim `c` is admitted against graph `G` under versioned policy `P` iff:

```
A(c, G, P) = I(c,G) ∧ T(c,G,P) ∧ P_rov(c,G,P) ∧ D(c,G,P) ∧ S(c,G,P)
```

- **I — Integrity:** references resolve; content hashes consistent.
- **T — Type/Temporal:** unit + entity + metric match; point-in-time as-of; freshness.
- **P — Provenance:** complete lineage to a preserved source artifact.
- **D — Derivation:** each numeric assertion independently re-derived against its backend
  computation within tolerance (never trust the stated number).
- **S — Support:** each assertion cites evidence that actually attests it.

Predicates are independent pure functions → PASS / FAIL / UNKNOWN / NOT_APPLICABLE. A mandatory
FAIL → `REJECTED`; a mandatory UNKNOWN → `ABSTAINED` (never treated as pass). Deterministic for
identical normalized inputs. Detail: `claim-admission-invariants.md`. State: `OFFLINE_TESTED`.

## 8. Admission, reconciliation & contradiction detection (R1)

Deterministic admission (§7) feeds reconciliation (`reconciliation/`, GAP-003): exact-Decimal
cross-source reconciliation `r = observed − f(components)`, integrity checks, IQR/z-score
anomaly screening that **flags for investigation and never auto-rejects or asserts fraud**.
Contradiction detection across heterogeneous sources with a first-class **typed abstention**
when conflicts are unresolvable (H3). State: `OFFLINE_TESTED`.

## 9. Compositional invariants & conclusion-level validity (R1)

Individual claim verification does **not** establish conclusion validity. STRIX independently
verifies relationships, applicability, procedural dependencies, and the final synthesis:
full-closure provenance scanning (not 1-hop; §11.16 fix), resource-exhaustion invariant
(exhaustion → ABSTAIN, never weakened admission; §11.9), and final-answer re-verification
(§16). Invariants are **tested, not machine-proved** (honest limitation, `limitations.md`).
State: `OFFLINE_TESTED`.

## 10. Independent AI assurance — the six pillars (R2)

All six pillars operate together across the whole lifecycle (acquisition → retrieval →
computation → admission → synthesis → citation binding → persistence → delivery):

| # | Pillar | Module | State |
|---|---|---|---|
| 1 | Evidence verification | `evidence_graph` (predicates, admission) | `OFFLINE_TESTED` |
| 2 | Policy enforcement | `evidence_graph` policies + `assurance/authorization` | `OFFLINE_TESTED` |
| 3 | Behavior monitoring | `assurance/monitoring` (independent, non-overridable) | `OFFLINE_TESTED` |
| 4 | Uncertainty scoring | `assurance/uncertainty` (ordinal; no fabricated probabilities) | `OFFLINE_TESTED` |
| 5 | Adversarial testing | per-subsystem reviews + regression suites (§32) | `OFFLINE_TESTED` |
| 6 | Decision traceability | `audit` ledger + `assurance/lifecycle` + `assurance/inspector` | `OFFLINE_TESTED` |

Plus the authorization gateway (§13) and Ed25519 signing (§14) as permanent core.

## 11. Authorization gateway & five dispositions (R2)

Six-pillar authorization gateway (`assurance/gateway.py`): five outcomes —
**AUTHORIZED · QUALIFIED · REVIEW_REQUIRED · ABSTAIN · REJECTED** — fail-closed, whitelist-based,
adversarially reviewed (1080-combination sweep). GAP-001 evidence-bound deterministic
authorization (`Auth = Iₐ ∧ Vₐ ∧ Cₐ ∧ Fₐ ∧ Bₐ ∧ Rₐ`): versioned-policy binding, exact
action-parameter certificates, atomic single-use consumption (replay → 0), execution-time
revalidation, external execution **disabled by default**, sandbox executor, independent outcome
reconciliation. State: `OFFLINE_TESTED`. Live external execution: `NOT enabled` by design.

## 12. Signed certificates, policy versioning & decision traceability (R2)

Ed25519 signed certificates (`assurance/signing.py`): domain-separated, keyring/rotate/revoke;
four certificate classes. Policy versioning + id on every `VerificationPolicy`. GAP-002 durable
append-only **hash-chained ledger** (`audit/`): idempotent insert, `verify_chain`
tamper/gap/broken-link detection, crash recovery, deterministic replay (`replay.py`,
`agent/replay.py`, `engineering/replay.py`). Assurance inspector (`assurance/inspector.py`)
independently re-verifies the chain + signatures and renders a typed `AssuranceReport`.
State: `OFFLINE_TESTED`. **Caveat:** pre-registration manifests are content-addressed, **not yet
cryptographically signed** — documented trust-model limitation (`limitations.md`), future work.

## 13. Adaptive assurance (R4, part 2)

Deterministic, auditable, fail-closed policy adaptation (`assurance/adaptive.py`): fast-tighten /
slow-relax over tier bounds, with a **hard safety floor** — never tolerate HIGH/INSUFFICIENT,
tier bounded, never bypass the gateway. Adaptive behavior **never weakens** a mandatory
assurance requirement. State: `OFFLINE_TESTED` (core). **Live wiring of the adaptive tier into
the gateway acceptance bar is the Wave-4 integration task (§21).**

## 14. Answer-first synthesis & final-answer verification (R1)

Deterministic synthesis from **admitted findings only** (`answering/synthesize.py`): every
`FACTUAL` `AnswerAssertion` must carry a `claim_certificate_id` binding it to an admitted
`ClaimCertificate` (`answering/models.py`); analytical inferences and hypotheses are explicitly
non-factual and need none. Independent fail-closed response validation (`answering/validate.py`,
`agent/response_validator.py`) strips any unsupported assertion before release — the synthesized
answer **must not introduce unsupported assertions after verification**. The end-to-end proof
(native compute → graph → admission → certificate → verified NL answer, with a fabricated figure
rejected) is an integration test over synthetic fixtures. State: `OFFLINE_TESTED`.

## 15. Unified research response contract & citation integrity (§7)

One versioned, governed response contract (`answering/models.py::VerifiedResearchResponse`;
surfaced across CLI/API/React/workers) presenting: **(a) Direct answer** — one coherent
conclusion; **(b) Supporting analysis** — findings/calculations/comparisons/tables; **(c) Material
limitations** — uncertainty, conflicts, insufficiency, stale info, assumptions; **(d) Supporting
documentation** — genuine numbered references below the answer (titles, authors, dates, DOIs,
URLs, PDF refs, pages/sections, official records, dataset ids, timestamps, methodologies);
**(e) Research assurance** — a concise disposition + run id, with full evidence graphs /
certificates / policy decisions / uncertainty / calculations / replay available on optional
inspection. Inline numbered citations resolve to the documentation section; every consequential
claim is traceable to its supporting evidence. Internal logs / competing agent outputs / DB
details are **not** surfaced to the user.

State: core typed contract `OFFLINE_TESTED`; **single shared contract across all four surfaces
(CLI/API/React/workers) + rich citation metadata is the §7 integration task (§21, WS-A).**

## 16. Retrieval & knowledge infrastructure (R1/§5)

| Capability | Module | State |
|---|---|---|
| Content-addressed inverted index | `retrieval/index` | `OFFLINE_TESTED` |
| Exact-Decimal BM25 (pinned precision, no float) | `retrieval/bm25` | `OFFLINE_TESTED` |
| Index↔corpus reconciliation (forged-digest + scalar-tamper detection) | `retrieval/reconcile` | `OFFLINE_TESTED` |
| Reproducibility contract (versions/params/precision/digest) | `retrieval/contracts` | `OFFLINE_TESTED` |
| Pluggable backends (BM25 baseline + external adapter + fallback) | `retrieval/backends` | `OFFLINE_TESTED` |
| Reciprocal Rank Fusion + evidence-aware rerank (auth/integrity hard-gated) | `retrieval/fusion` | `OFFLINE_TESTED` |
| Deterministic embeddings + vector index + hybrid (dense+lexical) | `retrieval/vector` | `OFFLINE_TESTED` |
| Real BGE-M3 embeddings / pgvector / OpenSearch cluster | — | `EXTERNALLY_BLOCKED(torch/model download + cluster infra)` — adapter contracts in place |

Search indexes are reproducible derivatives of authoritative evidence stores.

## 17. Data engineering platform (DE-1 … DE-9, §5)

| Milestone | Scope | State |
|---|---|---|
| DE-1 | Lakehouse foundation / config | `OFFLINE_TESTED` |
| DE-2 | Multi-provider ingestion (5 providers) | `OFFLINE_TESTED` |
| DE-3 | Silver normalization (path-traversal fix landed) | `OFFLINE_TESTED` |
| DE-4 | Analytical warehouse (DuckDB + Snowflake dimensional model) | `OFFLINE_TESTED` |
| DE-5 | dbt transformations (38 models; 2022–2026 live sample) | `OFFLINE_TESTED` (dbt-run gated: dbt not installed here) |
| DE-6 | Airflow orchestration | `NOT_STARTED` — scheduler-independent DAG core done (`orchestration/`, Wave 11); Airflow adapter `EXTERNALLY_BLOCKED(Airflow infra)` |
| DE-7 | OpenSearch / pgvector semantic layer | `EXTERNALLY_BLOCKED(cluster infra)` — adapter contracts in place |
| DE-8 | Private object storage + immutable Bronze | `OFFLINE_TESTED` (Bronze); live object store `EXTERNALLY_BLOCKED` |
| DE-9 | Governed analytical interfaces + lineage | `OFFLINE_TESTED` (`datastore/duckdb_query` parameterized, column-whitelisted) |

Typed Decimal-safe Parquet/Arrow datasets (`datastore/parquet_dataset`), governed DuckDB
(no arbitrary SQL). **Validate existing implementations; do not duplicate.** DE-1..DE-5 are
ancestors of `main` (do **not** re-merge).

## 18. Autonomous scholarly intelligence (§6)

Scholarly pipeline over **authorized** sources: Crossref, OpenAlex, arXiv, PubMed, Europe PMC,
Semantic Scholar, NASA NTRS, government publications, institutional repositories. Autonomous
discovery, acquisition, hashing, indexing, metadata + citation extraction, evidence
reconciliation, retraction awareness, contradiction discovery, historical retrieval.

| Piece | State |
|---|---|
| Source adapter contracts + fixture-backed connectors (`sources/`, `agent/connectors`) | `OFFLINE_TESTED` (where fixtures exist) |
| Live scholarly-API ingestion | `EXTERNALLY_BLOCKED(network/rate-limit/keys)` — offline adapters + fixtures the path |
| Scheduled enrichment (pre-market / open / 10:30 / 14:00 / after-hours ET) | `NOT_STARTED` (scheduler-independent core done; cron binding infra-gated) |

## 19. Secure multi-format ingestion (§6)

Secure ingestion of PDF, DOCX, XLSX, CSV, JSON, XML, HTML, Markdown, plain text, Parquet,
ReqIF, and applicable engineering documents, with hash-on-ingest and point-in-time preservation.
State: CSV/OFX/QFX/JSON/Parquet/ReqIF-class `OFFLINE_TESTED`; binary office formats (DOCX/XLSX/
PDF extraction) partially covered — remaining parsers `NOT_STARTED` (offline-implementable).

## 20. Financial intelligence (R3)

STRIX is **read-only** w.r.t. external financial accounts and **must not execute trades,
payments, or transfers** (§17 constraint).

| Capability | Module | State |
|---|---|---|
| Double-entry ledger (decimal-safe, invariants) | `finance/ledger` | `OFFLINE_TESTED` |
| Canonical transaction model; CSV + OFX/QFX import | `finance/transactions,imports,imports_ofx` | `OFFLINE_TESTED` |
| Accounts + ownership + status | `finance/accounts` | `OFFLINE_TESTED` |
| Categorization + merchant normalization | `finance/categorize` | `OFFLINE_TESTED` |
| Transfer / CC-repayment matching (max bipartite, no double-count) | `finance/transfers` | `OFFLINE_TESTED` |
| Budgets + goals + variance + projection | `finance/budgets` | `OFFLINE_TESTED` |
| Bills: recurring detection, calendar, reminders | `finance/bills` | `OFFLINE_TESTED` |
| Spending anomaly detection | `finance/anomaly` | `OFFLINE_TESTED` |
| Portfolio: allocation/concentration/TWR/MWR/drift/rebalancing | `finance/portfolio` | `OFFLINE_TESTED` |
| Monthly accounting + statements + reconciliation + period close | `finance/accounting` | `OFFLINE_TESTED` |
| Technical indicators (SMA/EMA/RSI/MACD/ATR/DMI/ADX/vol/drawdown/corr) | `market/indicators` | `OFFLINE_TESTED` |
| Market universe (indexes vs ETF proxies) | `market/universe` | `OFFLINE_TESTED` |
| Read-only provider adapters (Plaid/Teller/SnapTrade/Alpaca) | `finance/connectors` | `OFFLINE_TESTED`; `LIVE_VALIDATED EXTERNALLY_BLOCKED(credentials+PII consent)` |
| Finance HTTP API (accounts/txns/net-worth/income-expense) | `finance/service`, `webapi/finance_api` | `OFFLINE_TESTED` (exact-Decimal, money-as-string) |
| Alpaca / SEC EDGAR / FRED / BLS / Treasury live integrations | — | `EXTERNALLY_BLOCKED(keys/network)` — EDGAR fixtures + adapters in place |
| **Governed financial assistant tools** | — | `NOT_STARTED` (offline-implementable; §21 WS-C) |
| Evidence-grounded financial recommendation (point-in-time) | — | `NOT_STARTED` (depends on assistant tools + response contract) |

## 21. Integration workstreams (the remaining unblocked implementation)

Per §12 of the goal, 11 workstreams; the coordinating agent owns shared contracts, integration,
conflict resolution, traceability, and acceptance. The **genuinely unblocked** remaining work:

- **WS-A — Unified governed response contract (§15/§7).** One shared `ResearchResponse` across
  CLI/API/React/workers + rich citation metadata. State: `NOT_STARTED`.
- **WS-B — Wave-4 adaptive-tier → gateway wiring (§13).** State: `NOT_STARTED`.
- **WS-C — Governed financial assistant tools (§20).** State: `NOT_STARTED`.
- **WS-D — Deployment config, offline (§25).** Dockerfiles/Compose/migrations/health checks;
  **no deploy**. State: `NOT_STARTED`.
- **WS-E — React dashboard pages (§31 demos 8–13).** State: `IN_PROGRESS` (infra + first page done).
- **WS-F — Remaining ingestion parsers (§19).** State: `NOT_STARTED`.
- **WS-G — Cross-boundary adversarial review sweep (§32).** State: `IN_PROGRESS`.
- **WS-H — SBIR feasibility package (§34).** State: `IN_PROGRESS`.

## 22. Federal spending integrity (R5, part 1)

Federal Spending Integrity Platform demonstration (`federal/`): typed award models with
**six distinct money kinds, never conflated**; read-only USAspending/SAM/Treasury/GAO
connectors (fixture-backed); procurement analytics (contractor resolution, graph, concentration);
obligation reconciliation + duplicate-reporting + anomaly screening. **Anomalies are flagged for
REVIEW, NEVER asserted as fraud or regulatory violation.** State: `OFFLINE_TESTED`; live
ingestion `EXTERNALLY_BLOCKED(network/keys)`.

## 23. Institutional isolation & multi-tenancy (R5, part 2)

Per-institution isolation (`institutional/`): content-addressed institution identity
(id↔slug invariant), per-institution scoped context (isolated ledger root + keyring + namespaced
ids), durable uniqueness-enforcing registry (fail-closed reload, atomic+exclusive write),
fail-closed cross-tenant access rejection. Role-based authorization + evidence-level permissions +
private research workspaces + institutional auditability. State: `OFFLINE_TESTED` (1 CRITICAL
cross-tenant-takeover-on-reload defect found & fixed). RBAC/ABAC over the live data infra:
`NOT_STARTED` (needs the live data infrastructure).

Separate catalogs, indexes, evidence stores, permissions, revisions, and verification policies
per institution; authorized federation under temporal + organizational applicability.

## 24. Governed deployment & reproducibility runtime (R6)

One authoritative research runtime; durable research jobs; transactional outbox; atomic job
submission; idempotency; lease fencing; worker recovery; independent heartbeats; bounded
retries; cancellation; checkpoints; crash recovery; budget enforcement; durable evidence +
result persistence; authentication + authorization; Docker/OCI/Vercel deployment **preparation**;
reproducible local execution. **No ordinary execution path may bypass independent assurance.**

| Piece | Module | State |
|---|---|---|
| SQLite transactional outbox (idempotent publish, lease claim, retry/dead-letter, recovery) | `outbox/sqlite_outbox` | `OFFLINE_TESTED` (3 MAJOR fixed) |
| Durable run store + replay artifacts | `run_store.py`, `replay.py` | `OFFLINE_TESTED` |
| Supabase JWT auth (trusted issuer, instance binding, fail-closed); wired into API | `auth/*`, `webapi/app` | `OFFLINE_TESTED` (adversarially reviewed) |
| research_jobs RLS (client cannot forge status/result/cost/lease) | `supabase/migrations/0001` | `IMPLEMENTED`; `EXTERNALLY_BLOCKED(PG server)` for integration test |
| PostgreSQL outbox + durable cloud job store | — | `EXTERNALLY_BLOCKED(PG/Supabase service)` |
| Docker/OCI/Vercel deploy config (offline-authorable) | — | `NOT_STARTED` (§21 WS-D); deploy itself `EXTERNALLY_BLOCKED(cloud auth)` |
| GitHub Actions CI (ruff/mypy/pytest/vitest/tsc/build/smokes) | `.github/workflows/ci.yml` | `IMPLEMENTED` (gates green locally; GH-run gated) |

## 25. Security operating modes & default-deny (§10 security)

Four operating modes + default-deny capability policy, fail-closed (`security/modes`); the
`--no-assurance` escape is refused outside open-research mode. State: `OFFLINE_TESTED`.
Threat model: `research/threat-model.md`.

## 26. Durable jobs, outbox & worker recovery

See §24. The scheduler-independent DAG orchestration (`orchestration/{dag,executor}`) gives
topological order, skip-on-failure, retries, checkpoint/resume without Airflow. State:
`OFFLINE_TESTED`.

## 27. Governed execution modes & the experimental baseline

`strix ask` and the web research API route every run through the independent six-pillar gateway
by default; the `--no-assurance` flag is the isolated experimental baseline (Arm toggling for
§29), gated to open-research mode. Live GPT-6 Luna evidence collection is the only live-blocked
piece of the governed path. State: `OFFLINE_TESTED`.

## 28. Scientific evaluation program — hypotheses H1–H12 (§8)

**Authoritative recovery (do not invent / do not silently redefine):**
- **H1, H2, H3** are authoritatively specified with full falsifiable statements, variables, and
  rejection criteria in `docs/research/milestone-0/comparative-experiment-design.md`
  (H1 = evidence-bound execution assurance / GAP-001; H2 = closed-loop outcome certification /
  GAP-002; H3 = interoperable evidence verification / GAP-003).
- **H4–H12 were referenced as a planned set in the R1 spec but were never authored** in the
  repository. They are therefore **formalized transparently** in `research/hypothesis-registry.md`
  from (a) the R1 spec's stated intent and (b) the goal's enumerated experiments — each clearly
  marked as *newly formalized*, never as pre-existing.
- The milestone-0B scheme uses **four arms (A–D)**; the SBIR goal uses **five arms (A–E:
  Unassured LLM / Conventional RAG / Pre-formal STRIX / Formal STRIX / Complete STRIX)**. The
  registry **reconciles** the two schemes rather than silently replacing either.

**Every hypothesis is `NOT_EVALUATED`.** No benchmark has been run; no threshold has been
observed. Full detail: §29, `experimental-protocol.md`, `hypothesis-registry.md`.

## 29. Experimental protocol, arms A–E & benchmarks (§8)

Pre-registration discipline: corpus split, baselines, ablations, metrics, and thresholds are
frozen (content-addressed) before the held-out seal is opened (CLAUDE.md Principle 3).

**Arms (SBIR five-arm scheme):** A — Unassured LLM; B — Conventional RAG (no provenance/
admission); C — Pre-formal STRIX (retrieval + synthesis, no formal admission); D — Formal STRIX
(full I∧T∧P∧D∧S admission); E — Complete STRIX (D + adaptive assurance + gateway + full
response contract). Arms map onto the milestone-0B A–D methodology arms in `hypothesis-registry.md`.

**Benchmarks:** 120-question pilot; 1,200-question full (dev 25% / validation 25% / held-out
~42% / adversarial ~8%); 900-question institutional benchmark. Question taxonomy: direct lookup /
single-step derivation / multi-step multi-source / point-in-time / unanswerable-by-design /
trap-falsification. Statistics: paired design (McNemar / Wilcoxon), bootstrap 95% CIs
(`native.inference`, `OFFLINE_TESTED`), Benjamini–Hochberg FDR, stratified reporting, synthetic
vs genuine separated, **negative findings preserved**.

| Element | State |
|---|---|
| Benchmark dataset + ground-truth schema (`research_eval/dataset`) | `OFFLINE_TESTED` |
| Metric scoring offline (`research_eval/scoring`) | `OFFLINE_TESTED` |
| Statistical analysis — bootstrap/paired/BH (`research_eval/analysis`) | `OFFLINE_TESTED` |
| Run harness + cost accounting + checkpoint/recovery (`research_eval/runner`) | `OFFLINE_TESTED` |
| 120/1200/900-q corpora built | `NOT_STARTED` |
| Ten research baselines + A1–A9 ablation harness | `NOT_STARTED` |
| Live execution of H1–H12 across arms A–E | `EXTERNALLY_BLOCKED(GPT-6 Luna credentials + approved budget)` |

**If live experiments remain blocked, report experimental readiness, not empirical validation.**

## 30. Quantitative success criteria & measurement procedures (§9)

All values below are **pre-registration TARGETS**, `NOT_EVALUATED`. Thresholds recovered from
the goal §9; where the R1 spec supersedes, the registry records the source. Denominators,
workloads, controls, and measurement procedures are defined in `experimental-protocol.md`
before any run.

| Metric | Target | State |
|---|---|---|
| Unsupported-claim reduction | ≥50% vs strongest applicable baseline | TARGET / `NOT_EVALUATED` |
| Material-claim accuracy | ≥95% | TARGET / `NOT_EVALUATED` |
| Citation precision | ≥95% | TARGET / `NOT_EVALUATED` |
| Evidence-retrieval recall | ≥90% | TARGET / `NOT_EVALUATED` |
| Numerical-verification accuracy | ≥99% | TARGET / `NOT_EVALUATED` |
| Useful-answer coverage | ≥85% | TARGET / `NOT_EVALUATED` |
| Final-synthesis faithfulness | 100% for authorized material claims | TARGET / `NOT_EVALUATED` |
| Material-claim traceability | 100% for authorized outputs | TARGET / `NOT_EVALUATED` |
| Required citation / documentation / mapping / provenance / replay completeness | 100% | TARGET / `NOT_EVALUATED` |
| Unauthorized disclosures / temporal leakage | Zero observed | TARGET / `NOT_EVALUATED` |
| Invalid-action detection / heterogeneous-inconsistency detection | ≥95% | TARGET / `NOT_EVALUATED` |
| Retrieval latency p95 | ≤500 ms (defined conditions) | TARGET / `NOT_EVALUATED` |
| Interactive research runtime | ≤120 s (defined budgets) | TARGET / `NOT_EVALUATED` |
| Native C++ acceleration | ≥2× on designated workloads | TARGET / `EXTERNALLY_BLOCKED` |
| Apple Metal acceleration | ≥1.5× on designated workloads | TARGET / `EXTERNALLY_BLOCKED(GPU)` |
| Regression failures | Zero | **MET** (2233 passed, 0 regressions) |
| Unresolved critical security defects (release) | Zero | tracked (§32) |
| Unaccounted requirements | Zero | tracked (`requirements-traceability.md`) |

Failure to meet a target is a **legitimate scientific finding** and will be reported accurately.

## 31. Demonstrations (17) (§10)

| # | Demonstration | Backing state |
|---|---|---|
| 1 | Scientific literature research | deterministic path `OFFLINE_TESTED`; live scholarly `EXTERNALLY_BLOCKED` |
| 2 | Historical research | `OFFLINE_TESTED` (fixtures) |
| 3 | Current research | `EXTERNALLY_BLOCKED(live sources)` |
| 4 | Quantitative financial research | `OFFLINE_TESTED` (market/indicators + EDGAR fixtures) |
| 5 | Contradictory-evidence handling | `OFFLINE_TESTED` (reconciliation/contradiction) |
| 6 | Insufficient-evidence abstention | `OFFLINE_TESTED` (typed abstention) |
| 7 | Adversarial-evidence rejection | `OFFLINE_TESTED` (admission predicates; integration proof) |
| 8 | Personal financial dashboard | `IN_PROGRESS` (WS-E) |
| 9 | Financial transaction ingestion | `OFFLINE_TESTED` (imports) + UI `IN_PROGRESS` |
| 10 | Monthly accounting & reconciliation | `OFFLINE_TESTED` + UI `IN_PROGRESS` |
| 11 | Bill & subscription monitoring | `OFFLINE_TESTED` + UI `IN_PROGRESS` |
| 12 | Portfolio analysis | `OFFLINE_TESTED` + UI `IN_PROGRESS` |
| 13 | Evidence-grounded portfolio recommendation | `NOT_STARTED` (WS-C dependency) |
| 14 | Federal spending research | `OFFLINE_TESTED` (fixtures) |
| 15 | Institutional isolation | `OFFLINE_TESTED` |
| 16 | Deterministic replay | `OFFLINE_TESTED` |
| 17 | Hosted-compatible authenticated research execution | `IMPLEMENTED` (auth); hosted run `EXTERNALLY_BLOCKED(cloud)` |

Each research demonstration culminates in one intelligible answer with documentation (§15).
**No mock interface is presented as integrated functionality.**

## 32. Independent adversarial review & threat model (§11)

Every security/numeric/accounting/integration-critical subsystem is adversarially reviewed by an
independent multi-agent workflow; every confirmed defect is fixed TDD with a permanent
regression. Attack surfaces evaluated: evidence poisoning, fabricated citations, prompt
injection, temporal manipulation, unauthorized retrieval, cross-tenant disclosure, privileged
DB mutation, certificate forgery, replay manipulation, unsupported synthesis, execution bypass,
resource exhaustion, concurrency failures, budget violations. **45+ defects fixed** (CRITICALs
include: native correlation fail-open; BM25 scalar-tamper score corruption; institutional
cross-tenant takeover on reload; unwired-auth anonymous-endpoint defect). Demonstrated
vulnerabilities are separated from theoretical attack surfaces and residual risks
(`threat-model.md`). A **full cross-boundary sweep** remains (§21 WS-G).

## 33. Intellectual contribution, prior-art framing & claim discipline (R1 §33)

The building blocks are **established methods, NOT asserted as independently novel**. The
proposed contribution is their **composition** into an independently-verified, resource-bounded
assurance architecture, plus its empirical characterization. **No claim** is made of established
novelty, patentability, prior-art clearance, NSF eligibility, commercialization success, or
scientific superiority without adequate supporting evidence. Pre-award engineering is identified
as **preliminary research**. Detail: `intellectual-property-inventory.md`, `nsf-project-pitch.md`.

## 34. Commercialization, SBIR feasibility, roadmap & definition of done

**Feasibility package (§16 of the goal)** — reconcile/produce: executive overview (§1); problem
statement (§2); mathematical spec (`mathematical-specification.md`); innovation + prior-art
assessment (§33); architecture (§3–§27); response/citation contracts (§15); requirements matrix
(`requirements-traceability.md`); H1–H12 registry (`hypothesis-registry.md`); experimental
protocol (§29); benchmark/ground-truth methodology; comparative results (blocked → readiness);
statistical analysis + ablations; adversarial report (§32); native performance report (blocked →
readiness); cross-domain evaluation (federal proves domain-independence, offline); final-answer
quality evaluation; risk register; illustrative Phase I plan; Phase II roadmap; reproducibility
package; deployment/recovery docs; final technical feasibility report. State: `IN_PROGRESS` (many
companion docs exist; gaps tracked in `execution-state.md`).

**Commercialization framing:** APL is a **prospective customer, not a dependency**. Research,
demonstrations, prior-art analysis, customer discovery, and NSF SBIR preparation continue
regardless of APL participation. Only authorized public + synthetic data; former-employer code
and restricted information excluded; independent provenance maintained. The separate
`blkpvnthr/STRIX-Enterprise-Demo` repository (version-pinned consumer of STRIX, no reverse
dependency, no duplicated core) is scaffolded locally; **remote repo creation + package publish
are `EXTERNALLY_BLOCKED(GitHub/registry auth)`.**

### Definition of done (goal §18) — tracked in `execution-state.md`
1–20 per goal §18: all 34 sections accounted for (this document); six initiatives integrated;
nine DE milestones reconciled (§17); six pillars govern the lifecycle (§10); one orchestrator;
one answer per question with documentation (§2, §15); claims bound to citations; shared response
contract across surfaces (WS-A); H1–H12 recovered + mapped (§28); authorized experiments executed
(live `EXTERNALLY_BLOCKED` → readiness); pilot/full benchmark evaluated where authorized; findings
from actual measurements; demonstrations executable; engineering gates pass (§0.2); critical
defects corrected or explicitly block release; blockers have precise resolution + validation
procedures (§14 of goal; `execution-state.md`); deliverables complete; committed + pushed where
permitted; PR to main where permitted (**no merge without authorization**).

### Terminal execution condition (goal §19)
Terminate only when every locally-implementable requirement is complete/integrated/reviewed/
tested/documented/committed with all authorized experiments executed, OR every remaining item is
genuinely externally blocked with no meaningful independent work left. Intermediate milestone
completion is never terminal. Live-blocked experiments → report readiness, not empirical
validation. Negative findings are reported. **No fabrication of completion, measurements,
citations, documentation, or verification outcomes.**
