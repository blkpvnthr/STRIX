# STRIX Milestone Tracker

Persistent tracker for the continuous-implementation directive. Status values:
DONE/TESTED · PARTIAL · NOT_STARTED · NOT_EVALUATED · BLOCKED(reason).

Branch: `research/formal-evidence-verification` (R1 baseline).

| ID | Milestone | Status | Acceptance / evidence | Blockers |
|---|---|---|---|---|
| R1 | Resource-bounded typed evidence verification | **DONE/TESTED** | 1430 passed, 0 regressions; ruff/mypy clean (31 mods); 11 adversarial defects fixed; e2e integration test | — |
| R1-commit | Commit R1 | **DONE** (8 scoped commits 593ccd3..1626429) | 79 files, 0 sensitive; README/assets/docs-FALCON excluded (unattributed/pre-existing) | — |
| R1-push | Push branch + open PR | **BLOCKED** | — | network action denied by auto-mode classifier; user must `git push -u origin research/formal-evidence-verification` + `gh pr create`, or grant Bash push permission |
| R2-E | Ed25519 signed certificates | **DONE/TESTED** | assurance/signing.py; domain-separated, keyring/rotate/revoke; 24+ tests; fail-closed fix | — |
| R2-B | Runtime behavior monitoring | **DONE/TESTED** | assurance/monitoring.py; independent non-overridable; neg-cost breaker fix; 21+ tests | — |
| R2-C | Uncertainty assessment | **DONE/TESTED** | assurance/uncertainty.py; ordinal (no fabricated probs); 5 separate dimensions; 22 tests | — |
| R2-gateway | Six-pillar authorization gateway | **DONE/TESTED** | assurance/gateway.py; 5 outcomes, fail-closed; whitelist fix; adversarially reviewed (1080-combo) | — |
| R2-A | Governed research lifecycle (§4) | **DONE/TESTED (offline)** | assurance/lifecycle.py; full lifecycle composed+signed+audited; test_r2_governed 3 tests | live-agent evidence-collection wiring (the `findings` seam) |
| R2-D | Answer-first conversational intelligence | DONE (deterministic path, R1) | — | live-agent wiring |
| R2-F | Experimental benchmark + H1–H12 | **harness OFFLINE_TESTED; H1–H12 NOT_EVALUATED** | research_eval/{dataset,scoring,analysis,runner}: ground-truth schema, deterministic metric scoring, bootstrap/paired/BH analysis, run harness w/ cost budget + checkpoint; 58 tests | live LLM budget/credentials for 120/1200-q runs (live arms unrun by design) |
| R5-core | Federal spending integrity (offline) | **DONE/TESTED** | federal/{models,connectors,analytics}: 6 distinct money kinds (never conflated), fixture read-only connectors, contractor resolution + procurement graph + obligation reconciliation + duplicate-reporting + anomaly screening (flags for REVIEW, never fraud); 64 tests | — |
| R2-G | Native C CPU backend (ctypes) + parity | **DONE/TESTED** | native/_c/{strix_native.c,.h,CMakeLists}; native/backends/{native_build,native_cpu,parity}; CMake-built libstrix_native via ctypes; TOLERANCE contract, parity-certified vs reference (max \|Δ\|=4.8e-13); `strix compute parity` CLI; 28 native-backend tests; 4 adversarial defects fixed TDD | — |
| R2-G2 | C++ / Metal GPU native backends | **BLOCKED** | design in native-computing-architecture.md | Metal needs GPU runtime. (pybind11 no longer a blocker — ctypes C ABI used for the CPU backend.) Supported alternative = PythonReferenceBackend + native-CPU ctypes backend |
| DE-1..9 | Financial data engineering platform | PARTIAL (Bronze/Silver/warehouse/dbt per prior memory) | existing lakehouse tests | Airflow orchestration; some connectors need keys |
| R3-core | Financial ledger engine (offline) | **DONE/TESTED** | finance/{transactions,ledger,imports,transfers,anomaly}; decimal-safe double-entry, CSV import, transfer/repayment matching (no double-count invariant), IQR/duplicate anomaly; 82 tests; one canonical txn model | — |
| R3-app | Live app: connectors, dashboard UI, monthly automation, portfolio, assistant | NOT_STARTED/BLOCKED | ledger core is the data+logic foundation | Plaid/Teller/SnapTrade credentials + REAL financial PII; React dashboard; deploy — all credential/infra-gated |
| C-retrieval | Offline BM25 retrieval (index + scoring + reconciliation) | **DONE/TESTED** | retrieval/{index,bm25,reconcile,contracts,_precision}; content-addressed inverted index, exact-Decimal BM25 (pinned prec-50), GAP-003-style index↔corpus reconciliation; reuses versioned tokenizer; 40 tests; 5 adversarial defects fixed TDD (1 CRITICAL scalar-tamper/score-corruption) | hosted OpenSearch/Elasticsearch engine (infra-gated) |
| K-isolation | Institutional instance isolation | **DONE/TESTED** | institutional/{models,isolation,registry}; content-addressed identity (id↔slug validator), per-institution ledger root + keyring + namespaced resource ids, fail-closed cross-tenant guard, durable registry (fail-closed reload incl. id==dirname + content-address checks, atomic+exclusive write); 30 tests; 4 adversarial defects fixed TDD (1 CRITICAL cross-tenant takeover on reload) | — |
| R4 | Adaptive assurance | NOT_STARTED | — | depends R2/R3 |
| R5 | FSIP cross-domain integration | PARTIAL (offline federal domain done; see R5-core) | offline federal analytics proves the core is domain-independent | live USAspending/SAM/Treasury/GAO ingestion; FSIP repo access |
| R6 | Hosted deployment (Vercel/OCI/Supabase) | NOT_STARTED | — | interactive cloud auth; branch protection; secrets |

## Protocol notes
- External-dependency items (bank connectors, cloud deploy, live-LLM benchmark, FSIP repo): per directive §12, isolate the dependency, build + test the offline alternative, document the blocker, continue unaffected work. Never fabricate success; never spend/deploy/disclose credentials without authorization.
- Full honest status per milestone lives in `milestone-r1-report.md` and this tracker (updated after each milestone).
