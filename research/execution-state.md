# STRIX SBIR Phase I — Persistent Execution State

**Purpose (goal §13).** The compaction-surviving execution ledger. Survives context resets,
agent handoffs, and worktree integration. The requirements registry accounts for every master
specification requirement, its dependencies, implementation references, status, tests,
experimental evidence, blockers, and **next executable action**.

**Branch:** `feature/sbir-phase-i-evidence-intelligence` · **Last updated:** 2026-11-25.

---

## 1. Verified baseline (reproduced this session)

- Python: **2233 passed, 2 skipped, 2 xfailed** (0 regressions vs `862` R1 baseline).
- `ruff check src/`: clean. `mypy --strict src/strix`: clean across **239 source files**.
- Frontend: vitest green / tsc clean / vite build OK (prior session).

## 2. Continuous-execution loop (goal §12)

`Inspect → Plan → Implement → Test → Independently review → Remediate → Integrate → Validate →
Commit → Continue`. Do not stop at milestones; do not stop merely because tests pass. Terminal
condition = goal §19 (all locally-implementable work done OR all remainder genuinely externally
blocked).

## 3. Session ledger (append-only)

| # | Action | Outcome |
|---|---|---|
| S1 | Establish ground truth: git state, spec location, baseline | Master spec never existed; baseline 2233 verified |
| S2 | Recover H1–H12 | H1–H3 authored; H4–H12 never authored → formalized transparently (`hypothesis-registry.md`) |
| S3 | Author `research/MASTER_SBIR_SPECIFICATION.md` (34 sections) | DONE — the authoritative anchor |
| S4 | Author `research/hypothesis-registry.md` | DONE |
| S5 | Author `research/execution-state.md` (this file) | DONE |
| S6 | Reconcile `requirements-traceability.md` to master-spec IDs | pending |
| S7 | Commit anchor documents | DONE (c846f42) |
| S8 | WS-A: unified governed response contract (§7/§15) | DONE — `agent/documentation.py` (BibliographicMetadata, ReferenceDocument, SupportingDocumentation, CitationMappingIntegrity, build_supporting_documentation); shared by webapi (`documentation` in result), CLI renderer (refactored to the contract), React (`SupportingDocumentationPanel` + types). TDD: 8 unit + 2 webapi + 2 renderer + 4 vitest. Suite 2245 passed; vitest 15; tsc/build clean. |
| S9+ | Workstreams WS-B..WS-J (see §4) | pending |

## 4. Requirements registry / workstream backlog

Status ∈ {NOT_STARTED, IN_PROGRESS, OFFLINE_TESTED, EXTERNALLY_BLOCKED, DONE}. "Next action" is
the single next executable step; a dependency-ready task is one whose deps are all satisfied.

| WS | Requirement (spec §) | Deps | Status | Next executable action |
|---|---|---|---|---|
| — | Anchor docs (spec §0, §13) | — | IN_PROGRESS | reconcile traceability; commit |
| WS-A | Unified governed response contract (§15/§7) | answering, webapi, web | **OFFLINE_TESTED** | DONE (S8). Shared supporting-documentation + citation-mapping contract across CLI/API/React; rich reference metadata; §30 integrity signals surfaced. |
| WS-B | Adaptive-tier → gateway wiring (§13) | assurance/adaptive, assurance/gateway | NOT_STARTED | TDD: gateway consults adaptive tier for the acceptance bar; prove safety floor never relaxes |
| WS-C | Governed financial assistant tools (§20) | finance/*, assurance/gateway, WS-A | NOT_STARTED | TDD deterministic read-only finance tools (net-worth, budget-variance, portfolio-drift, bill-forecast) behind the gateway; evidence-grounded recommendation |
| WS-D | Deployment config, offline (§24/§25) | webapi, outbox, supabase migrations | NOT_STARTED | Dockerfile(s) + docker-compose + migration runner + /health + /ready endpoints; validate build locally; **no deploy** |
| WS-E | React dashboard pages demos 8–12 (§31) | finance_api, web/ | IN_PROGRESS | build Budgets/Portfolio/Bills/Accounting pages against finance API; Vitest/RTL each |
| WS-F | Remaining ingestion parsers (§19) | sources | NOT_STARTED | DOCX/XLSX/PDF-text extractors with hash-on-ingest; offline fixtures |
| WS-G | Cross-boundary adversarial sweep (§32) | all | IN_PROGRESS | multi-agent refutation across trust boundaries; fix confirmed defects TDD |
| WS-H | SBIR feasibility package (§34) | all docs | IN_PROGRESS | produce final technical feasibility report + benchmark-readiness report; reconcile companion docs |
| WS-I | Benchmark corpora + baselines + ablations (§29) | research_eval | NOT_STARTED | author 120-q pilot corpus + 10 baselines + A1–A9 ablation harness (offline); live run blocked |
| WS-J | STRIX-Enterprise-Demo scaffold (§34) | version-pinned STRIX | NOT_STARTED | local scaffold (3 governed instances) consuming pinned STRIX; remote repo + publish blocked |

## 5. Blocker register (goal §14 format)

Each blocker: blocked requirement · external dependency · attempted resolution · completed
implementation · remaining validation · required authorization · acceptance criteria ·
reproduction procedure.

### B1 — Live comparative experiments (H1–H12, arms A/B + live C–E)
- **Blocked requirement:** EXPERIMENTALLY_EVALUATED status for any hypothesis (§28–§30).
- **External dependency:** GPT-6 Luna model credentials + an approved spend budget.
- **Attempted resolution:** none possible without credentials; no unauthorized spend (§17).
- **Completed implementation:** scoring/analysis/runner harness `OFFLINE_TESTED`; deterministic
  arms (C–E structured outputs) runnable offline.
- **Remaining validation:** build corpora (WS-I) then run live arms.
- **Required authorization:** user-provided credentials + budget approval.
- **Acceptance criteria:** pre-registered thresholds (§30) met with CIs excluding null after FDR.
- **Reproduction:** freeze pre-registration manifest → seal held-out → run `research_eval.runner`.

### B2 — Apple Metal GPU acceleration (H12, §4)
- **Dependency:** a macOS GPU host with the Metal runtime.
- **Completed:** C native CPU backend parity-certified (max |Δ|=4.8e-13); Metal kernel source
  writable. **Remaining:** build + parity-validate on a GPU host.
- **Authorization:** access to a GPU host. **Acceptance:** ≥1.5× speedup, parity within contract.
- **Reproduction:** `strix compute parity` extended to the Metal backend.

### B3 — Cloud deployment (Vercel / OCI / Supabase / PG / OpenSearch)
- **Dependency:** interactive cloud auth + provisioned services. **No deploy / no unauthorized
  spend (§17).**
- **Completed:** offline config authorable (WS-D); auth + RLS migrations `IMPLEMENTED`; adapters
  in place. **Remaining:** apply migrations against a live PG; deploy.
- **Authorization:** cloud credentials + explicit deploy approval.
- **Acceptance:** health/ready green; RLS integration tests pass against live PG.

### B4 — Live data sources (scholarly APIs, Alpaca/EDGAR/FRED/BLS/Treasury, bank connectors)
- **Dependency:** network access + API keys; for bank connectors, real-PII consent.
- **Completed:** fixture-backed adapters + contracts `OFFLINE_TESTED`.
- **Authorization:** keys + (for finance) PII consent. **Acceptance:** live LIVE_VALIDATED runs.

### B5 — git push / PR (network)
- **Dependency:** push permission in this environment (prior sessions: network action denied).
- **Completed:** all work committed locally. **Required authorization:** push permission or the
  user runs `git push`. **No merge to main without authorization (§17).**

### B6 — STRIX-Enterprise-Demo remote repository + package publish
- **Dependency:** GitHub repo creation auth + a package registry.
- **Completed (planned):** local scaffold (WS-J). **Authorization:** repo + registry creds.

## 6. Invariants to preserve (do not regress)

- Zero test regressions; ruff + mypy-strict clean.
- AFIIS and C-Engine kept **separate** from STRIX (§17).
- Read-only finance; no trades/payments/transfers (§17).
- No credential exposure; no unauthorized spend/deploy; no merge to main without authorization.
- Preserve README graphics/assets, FALCON docs, unrelated changes.
- No fabrication; every target stays a target until EXPERIMENTALLY_EVALUATED.
