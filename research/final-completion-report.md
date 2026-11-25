# STRIX — Continuous Implementation: Status Report (interrupted session, not final completion)

**Branch:** `research/formal-evidence-verification` — **48 scoped commits** on top of
baseline `849018d` (the uncommitted README/assets/`docs/FALCON` are intentionally
excluded: pre-existing/unattributed content preserved, never committed).

**Measured gate (reproduced):** Python `2210 passed, 2 skipped, 2 xfailed` — **0
regressions** vs the `862` baseline; `ruff` zero; `mypy --strict` clean across all
packages. Frontend: `web/` `vitest` 11/11 green, `tsc --noEmit` clean, `vite build`
succeeds. **45 adversarial defects found & fixed** (3 CRITICAL), each with a
permanent regression test.

**Latest increments:** Finance HTTP API (§3), finance frontend slice + budgets/
categorization (§5/§9), security operating modes (§10), durable SQLite transactional
outbox (§4/§6, adversarially reviewed — 3 MAJOR fixed), typed Parquet/Arrow datasets
+ governed DuckDB analytics (§7), Reciprocal Rank Fusion + evidence-aware rerank +
deterministic-embedding vector/hybrid retrieval (§5/§7/§8).

**Classification:** ENGINEERING_COMPLETE/OFFLINE_TESTED · PARTIAL · LIVE_BLOCKED ·
NOT_EVALUATED. This is an **interrupted session**, not a completion claim: §5/7/8/9
items remain implementable and are listed in §4 with continuation pointers. No
deployment, live benchmark, hardware acceleration, or provider validation is
claimed.

---

## 1. Delivered this session (OFFLINE_TESTED, committed)

| Area | Modules | Commit |
|---|---|---|
| Phase-M experimental program | `research_eval/*` | `64ef406` |
| Phase-N federal integrity (6 money kinds; never "fraud") | `federal/*` | `c45d378` |
| Native-CPU C backend via ctypes + parity (max \|Δ\|=4.8e-13) + CLI | `native/_c`, `native/backends/*` | `216ceb9` |
| Offline BM25 retrieval + index reconciliation | `retrieval/{index,bm25,reconcile,contracts}` | `d3323c8` |
| Institutional instance isolation | `institutional/*` | `90874fe` |
| R4 adaptive assurance (deterministic, fail-closed) | `assurance/adaptive` | `89dbf50` |
| Assurance inspector (independent re-verify) | `assurance/inspector` | `e801895` |
| **Wave 4** govern the research agent (CLI+webapi default-on) | `agent/governed`, `webapi/service`, `cli` | `bab9f23` |
| **Wave 7a** frontend test infra + AssuranceVerdict UI | `web/*` | `75978eb` |
| **§8** pluggable search backends (BM25 baseline + external adapter) | `retrieval/backends` | `6077438` |
| **Wave 11** scheduler-independent DAG orchestration (no Airflow) | `orchestration/{dag,executor}` | `6233d42` |

Plus the prior-session R1/R2/R3 substrate (native reference layer, typed evidence
graph + 5 predicates + 4 certs, GAP-001/002/003, answer synthesis, six pillars +
gateway + signing + uncertainty + monitoring, governed lifecycle, finance ledger,
market indicators) — all OFFLINE_TESTED.

## 2. Falsification-first evidence

Every security/numeric/accounting/integration-critical subsystem was adversarially
reviewed by an independent multi-agent workflow; every confirmed defect was fixed
TDD with a permanent regression. Highlights this session:
- Native correlation overflow fabricated `0.0` (fail-open) → scale-before-multiply +
  finite guards.
- Parity self-certification loophole → trusted independent tolerance.
- BM25 **CRITICAL**: tampered derived scalars evaded reconciliation AND corrupted
  scores → scorer derives from authoritative `doc_lengths`; digest covers scalars.
- Institutional **CRITICAL**: manifest id trusted on reload → cross-tenant takeover
  → fail-closed reload (id↔slug + id==dirname + dup rejection) + atomic/exclusive write.
- Wave 4: behavior-monitoring pillar was inert → seeded from real run signals;
  run_id↔stale-ledger collision → ledger inside the run dir.

## 3. Default governed execution (Wave 4)

`strix ask` and the web research API now route every agent run through the
INDEPENDENT six-pillar gateway by default: admission/uncertainty/behavior-monitor
signals are derived from the agent's own verification results, a hash-chained audit
trail is persisted (inside the run dir), a run certificate is minted/signed, and the
answer is released only on AUTHORIZED/QUALIFIED. A documented `--no-assurance` flag
is the isolated experimental baseline. Live GPT-6 Luna evidence collection is the
only LIVE_BLOCKED piece of this path.

## 4. Remaining implementable work (continuation state)

| Item | State | Exact remaining action / blocker |
|---|---|---|
| Finance HTTP API (§5) | NOT_STARTED (offline-implementable) | Add FastAPI routes over existing `strix.finance.*` + persistence; unblocks the 18 finance React pages. No external dep. |
| React pages: 18 finance + federal + DE (§4.2–4.5) | PARTIAL (test infra + AssuranceVerdict done) | Build pages against the finance/federal/DE HTTP APIs; reuse `web/src/ui.tsx` design system + Vitest/RTL. |
| Governed financial assistant tools | NOT_STARTED | Depends on finance HTTP API. |
| Deployment config (Wave 8) | NOT_STARTED (writable) | Dockerfiles/Compose/PG migrations/CI/health checks; validate locally where docker present; **do not deploy** (explicit). |
| Native C++/Metal (§9) | PARTIAL (ctypes C CPU backend done) | C++ interfaces writable; Metal kernel SOURCE writable but **GPU runtime-gated** for execution/validation. |
| Airflow DAG adapter (§7) | NOT_STARTED | Map `orchestration.Dag` onto operators; **Airflow infra-gated** (scheduler-independent core is done + tested). |
| Semantic/hybrid retrieval + live cluster (§8) | PARTIAL (lexical + external adapter contract done) | Embedding lifecycle writable; live OpenSearch/ES **cluster infra-gated**. |
| H1–H12 benchmark execution (§11) | NOT_EVALUATED | Harness + fixtures done; live runs need **GPT-6 Luna budget**; keep hypotheses NOT_EVALUATED. |
| Cross-boundary integration adversarial review (§12) | PARTIAL | Per-wave + Wave-4 integration reviews done; a full cross-boundary sweep remains. |

## 5. Operations requiring your authorization / credentials

1. `git push` + PR (network classifier denies in this environment — all 36 commits are local & validated).
2. GPT-6 Luna credentials + an approved $ budget for the 120/1200-q H1–H12 runs.
3. GPU runtime for Metal execution/validation.
4. A reachable OpenSearch/Elasticsearch cluster for the external search adapter.
5. Financial provider credentials + real-PII consent (Plaid/Teller/SnapTrade/Alpaca).
6. Cloud auth (Vercel/OCI/Supabase) for hosted deployment.

**Everything built is tested, adversarially reviewed where security/numeric/
integration-critical, honestly classified, and committed locally. No live external
execution, no deployment, no secrets committed, no fabricated results.**
