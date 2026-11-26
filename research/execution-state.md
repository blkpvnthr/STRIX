# STRIX SBIR Phase I — Persistent Execution State

**Purpose (goal §13).** The compaction-surviving execution ledger. Survives context resets,
agent handoffs, and worktree integration. The requirements registry accounts for every master
specification requirement, its dependencies, implementation references, status, tests,
experimental evidence, blockers, and **next executable action**.

**Branch:** `feature/sbir-phase-i-evidence-intelligence` · **Last updated:** 2026-11-25.

> **ACTIVE MANDATE (2026-11-25): DTEC reorientation.** STRIX is reoriented to be a computational
> evidence-science platform first, around a unified compositional evidence-admission calculus
> (internal confidential designation: **DTEC**; see git-ignored `research/dtec/_confidential/`).
> Six research engines (R-N1 dependency · R-N2 bitemporal · R-N3 compositional · R-N4
> uncertainty/calibration · R-N5 resource-bounded · R-N6 institutional) compose into
> `A_DTEC = I∧T∧P_rov∧D_num∧S∧R∧K∧F∧A_inst∧A_ind∧M_B`, extending — never weakening — the
> implemented `A(c)=I∧T∧P_rov∧D_num∧S` (Prop 3 / INV-ALG-3). Governing references: the
> confidential DTEC manuscript + `research/dtec/_confidential/unified-calculus.md` +
> `mathematical-invariants.md` + this master-spec family. Reconcile-not-duplicate; preserve all
> existing invariants, H1–H12, security controls. **8 mandatory amendments (approved 2026-11-25)**
> govern: (1) all new DTEC code/tests/docs confidential — **local commits OK, NO remote push**
> until repo-visibility/authorization established; (2) reconcile governing docs explicitly;
> (3) R-N3 is the principal contribution, demonstrate predicate interactions; (4) math proof
> obligations are first-class — tests/solver-success ≠ proof; (5) distinguish theory/empirical/
> engineering/targets, no validation from synthetic alone; (6) model-independence + exact-Decimal +
> replay + native-C + fail-closed, Python reference first; (7) independent review workstreams
> (math/integration/security/stats/IP); (8) continuous autonomous execution, phase boundaries are
> verification checkpoints not approval checkpoints.

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
| S17 | **DTEC Phase 8 — per-engine comparative baselines (§5/§7/§8) + adversarial hardening** | IN_PROGRESS. Gap found: the ablation harness measured only end-to-end composition `Δ_i`/`Δ_ij`, with **no comparative baselines** (§5 requires them for every algorithm; §8 states targets "vs the strongest applicable baseline"). New offline module `research_eval/dtec_baselines.py` (TDD, 13 tests). **Dispatched 5-lens adversarial review workflow** (circularity / strawman / metric / overclaim / determinism; 6 agents, 457k subagent tokens) → synthesis **confirmed 4 real MAJOR/minor findings — all legitimate, all remediated in-session BEFORE commit** (falsification-first did its job): (1) DTEC-vs-label scores are **tautological** (labels structurally defined) → reframed every result as a **consistency/regression check**, not a §8 measurement; (2) baselines were one-at-a-time strawmen → added the **strongest FAIR baselines** (composite record-linkage = artifact-id∨semantic-tuple; availability-only temporal = STRIX's own as-of axis; contradiction-aware RAG composer) + a genuine **separation case** (`same_hash_diff_artifact_id`, caught only by content-hash canonicalization); (3) `B-LIVE` internal blocker-code leaked into a public code note → public-safe phrasing; (4) added benchmark-integrity + no-blocker-code-leak guard tests. **Honest measured results (offline synthetic, NOT H1–H12):** R-N1 DTEC F1 1.00 (consistency) but **strongest fair composite baseline ties at 0.889**; DTEC separates **only** on hash-canonicalized shared origin. R-N2 **neither single axis** meets the joint acc≥0.95∧zero-leak objective (validity-only leaks; availability-only loses accuracy) — two-axis required. R-N3 even the contradiction-aware baseline admits the R/K failures A_C rejects (reduction_vs_strongest 1.00, of which not-entailed has a genuine external oracle). R-N4 calibration = **metric-validation only** (ECE 0.00 vs 0.35), not a method arm; production calibration blocked (model credentials + budget). **R-N5 resource-bounded verification** added (equal-budget yield vs FIFO/cheapest-first/utility-first/pure-yield-maximizer + brute-force optimum, 4 instances): greedy value/cost-ratio planner has the **highest mean yield-fraction 0.9375** (vs cheapest 0.90 / utility 0.844 / FIFO 0.619) but is **not optimal** (honest documented `knapsack_suboptimal` case where cheapest-first wins); decisive advantage is **mandatory-safety** — DTEC never drops a mandatory op (abstains per INV-N5-1) while a pure yield-maximizer does. Comparative baselines now cover all 5 measurable engines (R-N1/N2/N3/N4/N5); R-N6 institutional is a fail-closed policy predicate covered by the ablation's `institutional_violation` class. Results doc rewritten with per-section honest framing + negative findings. Gates: ruff + mypy --strict clean (255 files); suite **2446 passed, 0 regressions**. Committed `548cebc` (baselines + adversarial hardening); R-N5 follow-up commit pending. No push (B-PUSH). |
| S1 | Establish ground truth: git state, spec location, baseline | Master spec never existed; baseline 2233 verified |
| S2 | Recover H1–H12 | H1–H3 authored; H4–H12 never authored → formalized transparently (`hypothesis-registry.md`) |
| S3 | Author `research/MASTER_SBIR_SPECIFICATION.md` (34 sections) | DONE — the authoritative anchor |
| S4 | Author `research/hypothesis-registry.md` | DONE |
| S5 | Author `research/execution-state.md` (this file) | DONE |
| S6 | Reconcile `requirements-traceability.md` to master-spec IDs | pending |
| S7 | Commit anchor documents | DONE (c846f42) |
| S8 | WS-A: unified governed response contract (§7/§15) | DONE — `agent/documentation.py` (BibliographicMetadata, ReferenceDocument, SupportingDocumentation, CitationMappingIntegrity, build_supporting_documentation); shared by webapi (`documentation` in result), CLI renderer (refactored to the contract), React (`SupportingDocumentationPanel` + types). TDD: 8 unit + 2 webapi + 2 renderer + 4 vitest. Suite 2245 passed; vitest 15; tsc/build clean. |
| S9 | Pre-DTEC workstreams WS-B..WS-J | pending (reprioritized P3/P4 under DTEC mandate; §20) |
| S16 | **DTEC Phase 6/7 — Defensibility + NSF alignment; demos blocked** | IN_PROGRESS. **Phase 7 (achievable):** confidential `nsf-alignment.md` (six NSF objectives → DTEC engines/contributions/blockers/acceptance, honest; no eligibility/novelty/patent claims); enriched `novelty-assessment.md` with as-built NC-1..4 + hardening history; public `research/dtec-feasibility-readiness.md` (neutral §24 Definition-of-Done tracker: engineering DONE/offline, live/demos/prior-art BLOCKED). **Phase 6 (blocked):** 3-instance `STRIX-Enterprise-Demo` needs separate-repo creation — `EXTERNALLY_BLOCKED` (B-DEMO); documented with resolution procedure rather than a throwaway local scaffold. Prior-art SEARCH + patent = B-PATENT; live eval = B-LIVE. P5 committed `80fad50`. Next: commit P7 docs; remaining §24 items genuinely externally blocked (B-LIVE/B-DEMO/B-PATENT/B-PUSH/B-VIS). |
| S15 | **DTEC Phase 5 — Scientific evaluation (ablation harness)** | IN_PROGRESS. `research_eval/dtec_ablation.py`: deterministic OFFLINE SYNTHETIC ablation harness — 12-item ground-truth benchmark (valid + 5 attack classes), runs each through `admit_dtec` with engines ablated, computes `Δ_i` and interaction `Δ_ij` (exact Fraction internally). **Measured (offline, synthetic, real — NOT H1–H12 validation):** full `A_DTEC` 12/12=1.000; core-only 4/12=0.333; `Δ`(dependency)=`Δ`(temporal)=`Δ`(institutional)=+0.167 (each catches its own class); `Δ`(budget)=0 (no budget-attack items — honest null); interaction(dep,temp)=0 (independent). Results in `research/experiments/results/dtec-ablation-offline.md` with explicit "methodology evidence, not validation; live arms EXTERNALLY_BLOCKED (B-LIVE)" framing. P4 committed `57dd799`. 6 tests. Gates: ruff + mypy clean (254 files); suite **2429 passed, 0 regressions**. Note: real 120/1200/900-q corpora + 10 baselines + live arms remain `EXTERNALLY_BLOCKED` → readiness, not validation. Next: review → commit P5 → Phase 6/7 (demos + defensibility/NSF). |
| S14 | **DTEC Phase 4 — Unified `A_DTEC` integration** | IN_PROGRESS (pending P4 review gate). `evidence_graph/unified.py::admit_dtec` composes the preserved core (I/T/P_rov/D_num/S via `admit`) + all DTEC extension predicates (A_ind, entity-binding, bitemporal T, A_inst, M_B, conclusion R/K/F) under the four-valued algebra (fail-closed; A_DTEC = full conjunction, strictly ≥ core). `DTECOptions` configures which engines run (unconfigured ⇒ NOT_APPLICABLE); RC-3 guard refuses vacuous admission; disposition maps to gateway outcomes (PASS→AUTHORIZED, UNKNOWN→ABSTAIN, FAIL→REJECTED; QUALIFIED/REVIEW refined by the 6-pillar gateway); deterministic `decision_digest` (content hash over inputs+results+outcome) as certificate identity, signable via `assurance.signing`. **No-bypass integration test** (`tests/test_dtec_integration.py`, 9 tests): valid→ADMITTED/AUTHORIZED; fabricated value→REJECTED; dependency-inflation→not admitted; temporal leak→REJECTED; entity relabel→REJECTED by binding; Prop 3 (failing extension can't admit, passing extension preserves); deterministic digest; core-FAIL dominates all extensions. Gates: ruff + mypy clean (253 files); suite **2423 passed, 0 regressions**. P1 committed `da9ae11`. `dtec-p4-review` **CLEAN on first pass (0 surviving)** — unified composition sound. P4 gate SATISFIED. Committing P4 locally. Next: Phase 5 (scientific evaluation — synthetic benchmarks, baselines, `Δ_i`/`Δ_ij` ablations; live arms = readiness-not-validation). |
| S13 | **DTEC Phase 3 — P1 engines (R-N4, R-N5, R-N6)** | IN_PROGRESS (pending P1 review gate). **R-N5** `assurance/verification_planner.py` (v_i ops, greedy ratio planner, `M_B` predicate — infeasible mandatory ⇒ ABSTAIN never silent pass, verified_yield; upfront prereq-graph validation fail-closed; 16 tests + INV-N5-1 property test). **R-N4** `assurance/{calibration,abstention}.py` (exact Brier/ECE/reliability diagnostics over SUPPLIED samples — no fabricated probabilities; `Var≈∇ᵀΣ∇` propagation; selective classifier with non-overridable `g=1⇒A=PASS`, coverage, selective-risk=None-when-empty; 17 tests + INV-N4-1 property). **R-N6** `institutional/{admissibility,policy_reasoner,federation,applicability}.py` (`A_inst=O∧L∧J∧X` fail-closed on missing metadata; policy precedence partial-order with conflict/cycle/empty → deny; federation edge-aware projection + composition-leakage; noninterference checker; **`DTEC-R-N6-BIND` entity binding closes TBF-INFRA-1 additively** — EVILCORP-style computation relabel now FAILs; 22 tests). P0 committed `8534907`. Gates: ruff + mypy --strict clean (252 files); suite **2409 passed, 0 regressions**. `dtec-p1-review` found 3 MAJOR (TBF-R-N4-1 global-context rounding → exact `checked_mul`; TBF-R-N5-1 negative-cost netting fail-open → non-negativity/finiteness validators; TBF-R-N6-1 entity-binding any-match bypass → sound-by-refutation, never PASS on untrusted provenance + registered `DTEC-NATIVE-PROV` value-bound-provenance closure). **All remediated**; `dtec-p1-rereview` **CLEAN (0 surviving)**. P1 gate SATISFIED: suite **2414 passed, 0 regressions**; ruff + mypy clean (252 files). Cumulative P0+P1: 10 confirmed defects fixed (3 CRITICAL), R-N3 clean throughout. Committing P1 locally (no push). Next: Phase 4 — unified `A_DTEC` (11 predicates) + certificate + gateway integration. |
| S11 | **DTEC Phase 2 — P0 engines (R-N1, R-N2, R-N3)** | IN_PROGRESS (pending review gate). Deps installed (hypothesis, z3-solver). **R-N1** `evidence_graph/dependency.py` (N_eff, conservative `N̲_eff`, `A_ind`, Prop 1 property-tested) — independent review found 1 CRITICAL (spoofable primary-record exception) + 2 MAJOR (Decimal scale evasion, fabricated-origin false independence) + minors; **ALL remediated** with permanent adversarial regressions (strengthened per directive: validated-provenance primary exception, validated-disjoint-provenance independence, canonical Decimal, circular-provenance abstain, strict input validation); `trust-boundary-findings.md` logs root-cause+fix+test. **R-N2** `temporal.py` (two-axis `V_i`/`K_i`, availability leak gate, leak-freedom INV-N2-1 property-tested, contradiction, modes). **R-N3** `inference.py`+`calculus.py`+`counterexamples.py` (propositional entailment w/ exact reference checker + fail-safe z3 backend benchmarked vs reference, `A_C=(∧A)∧R∧K∧F`, closure/grounding, counterexample search, Prop 2 property-tested; headline: admitted-premises-but-unentailed-conclusion → REJECTED). `PredicateName` extended (+6 members). Tests: R-N1 31, R-N2 24, R-N3 38. Gates: ruff clean, mypy --strict clean (245 files), suite 2300 passed 0 regressions. **Ran `dtec-trust-boundary-sweep` workflow** (8 agents, directive points 7/9/10): **R-N3 clean**; 4 findings CONFIRMED + independently verified + **all remediated**: (CRIT) R-N1 ancestor/descendant scored independent → lineage check; (MAJ) R-N1 duplicate-document independence → content-hash canonicalization; (MAJ) R-N2 known-supersession fail-open → `superseded_at` + cohort resolution; (MAJ) **existing-core** `support`/`type_temporal` trust claim-declared entity/metric for computation-backed assertions → documented limitation TBF-INFRA-1 + scheduled additive fix `DTEC-R-N6-BIND` (preserve-not-weaken) + threat-model residual-risk note. +6 regressions. Suite 2344 passed, 0 regressions; ruff+mypy clean. **Iterated adversarial review to convergence** (point 10): 5 further passes found 5 more distinct real defects (R-N1 ancestor/descendant CRIT + duplicate-doc; R-N2 supersession: immediate-only CRIT → validity-dependence → recursion over-exclusion → non-recursive final) — **all remediated** with regressions; R-N3 clean every pass; existing-core `support` gap → documented `TBF-INFRA-1` + scheduled `DTEC-R-N6-BIND`. Final convergence re-review **CLEAN (0 surviving)**. P0 acceptance gate SATISFIED: suite **2354 passed, 0 regressions**; ruff + mypy clean; tests R-N1 33 / R-N2 38 / R-N3 38. WS-N1/N2/N3 → REF_IMPL/PROPERTY_TESTED. Committing P0 locally (no push). Next: Phase 3 (P1 engines R-N4/N5/N6). |
| S10 | **DTEC reorientation — Phase 1 Foundation** | IN_PROGRESS. Full 3-package code audit (reconcile-not-duplicate map confirmed: `A_ind`/N_eff NEW; bitemporal single-axis only; `A_C`/SAT-UNSAT absent; calibration deliberately ordinal; `A_inst` absent; verification planner absent). Governing DTEC manuscript located + read + **relocated to git-ignored `research/dtec/_confidential/`** (was untracked, never committed/pushed). Authored confidential suite: `unified-calculus.md`, `mathematical-invariants.md` (Prop 1/2/3 proved + obligation register), `algorithm-registry.md` (29 ALG IDs), `counterexample-registry.md` (16 CEs), `prior-art-matrix.md`, `novelty-assessment.md`, `research-risk-register.md`. Added dep groups (`dev`+=hypothesis, new `formal`=z3-solver) + z3 mypy override. Added `.gitignore` confidential path + scaffolded `research/experiments/`. Reconciliations: RC-1 D→D_num, RC-2 NA-semantics (Def 2 stricter for new predicates), RC-3 empty-mandatory guard, RC-5 arm-scheme preservation, RC-6 neutral code naming. Next: public neutral reorientation (master spec §, hypothesis registry UC1–UC5, traceability, protocol) → gate → local commit → Phase 2. |

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

### 4.1 DTEC research workstreams (active mandate; priorities per goal §20)

Status ∈ same enum + `REF_IMPL`/`BENCHMARKED` for research code. All code confidential (no push).

| WS | Engine / integration (priority) | Deps | Status | Next executable action |
|---|---|---|---|---|
| WS-FND | Phase 1 foundation (docs/deps/ledger/confidential infra) | — | **IN_PROGRESS (S10)** | finish public neutral reorientation; gate; local commit |
| WS-N1 | R-N1 Evidence dependency intelligence → `A_ind` (P0) | evidence_graph, native | NOT_STARTED | TDD `dependency.py`: `N_eff`, `N̲_eff`, `d_ij` ref estimator, `A_ind`; Prop 1 property test; synthetic dependency benchmark |
| WS-N3 | R-N3 Compositional calculus → `R∧K∧F` (P0, **principal IP**) | evidence_graph, invariants | NOT_STARTED | TDD conclusion `C=(φ,Φ,Γ,r)`, `A_C`, `Cl(C)`, deterministic ref entailment checker, Z3 backend (flagged, benchmarked), counterexample search; Prop 2 |
| WS-N2 | R-N2 Bitemporal reasoning → `T` ext. (P0) | evidence_graph | NOT_STARTED | TDD `temporal.py`: `(V_i,K_i)`, two-axis `T`, `G_{t_v,t_k,Ω}` filter, `L_temporal`, revision/supersession; leak property tests |
| WS-N4 | R-N4 Uncertainty/calibration (P1) | assurance/uncertainty | NOT_STARTED | TDD `calibration.py`/`abstention.py`: `x_c`, Brier/ECE harness, selective `g`, `g=1⇒A_DTEC=PASS`; keep ordinal default |
| WS-N5 | R-N5 Resource-bounded verification → `M_B` (P1) | agent/budget, assurance | NOT_STARTED | TDD `verification_planner.py`: `v_i` model, greedy ratio planner, `M_B` (infeasible⇒ABSTAIN), `Y_ver` |
| WS-N6 | R-N6 Institutional admissibility → `A_inst` (P1) | institutional, security/modes | NOT_STARTED | TDD `admissibility.py`/`policy_reasoner.py`/`federation.py`: `A_inst`, precedence `(𝒫,⪯)`, federation projection, noninterference |
| WS-UI | Unified `A_DTEC` integration (§10) | WS-N1..N6, gateway, certificates | NOT_STARTED | `admit_conclusion` over 11 predicates (INV-ALG-3), gateway wiring, DTEC certificate, orchestrator+replay, no-bypass |
| WS-EV | Scientific evaluation + ablations (supersedes/absorbs WS-I) | research_eval | NOT_STARTED | engine benchmarks + baselines + ablation runner (Δ_i, Δ_ij); offline only; live=B-LIVE |
| WS-DEMO | 3 governed institutional instances (absorbs WS-J) | WS-UI | NOT_STARTED | version-pinned demo consumer; isolation+federation+reproducibility |
| WS-DEF | Defensibility + NSF alignment (confidential) | all | NOT_STARTED | invention inventory, prior-art search, novelty vs established, NSF six-objective traceability, provisional-patent package |
| WS-REV | Independent review (math/integration/security/stats/IP) (amendment 7) | per engine | RECURRING | dispatch independent review per engine; fix defects TDD w/ regression |

**S6 resolution:** the two traceability schemes (`research/requirements-traceability.md` phase/
milestone letters; `docs/research/milestone-0/requirements-traceability.md` STRIX-001..015 →
GAP-001/002/003, YAML-governed) are reconciled by adding a DTEC requirement block
(DTEC-R-N1..N6, DTEC-U) to `research/requirements-traceability.md` that maps each engine to its
ALG IDs + modules + tests; the STRIX-00x/GAP scheme remains authoritative for the preserved core.

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

### B-VIS — Repository visibility & confidential-material disclosure posture (amendment 1)
- **Blocked requirement:** any remote push of DTEC-related material; the public/confidential
  repository split.
- **External dependency:** confirmation of `blkpvnthr/STRIX` remote visibility (public vs private)
  and, if public, authorization to create a separate private development repository. Could not be
  verified this session (visibility check denied; `gh` auth unknown).
- **Completed implementation:** fail-safe applied — DTEC brand/detail in git-ignored
  `research/dtec/_confidential/`; neutral code naming; `.gitignore` confidential path; all work
  committed **locally only**.
- **Remaining validation:** user runs `gh repo view --json visibility` (or confirms); if public,
  authorize/provision a private repo before any push of proprietary material.
- **Required authorization:** user confirmation + (if public) private-repo authorization.
- **Acceptance:** confirmed-private secured repo OR a provisioned private dev repo; disclosure
  gate green. **Reproduction:** `gh repo view`; inspect forks/branches/releases/CI artifacts.

### B-PATENT — External disclosure / provisional-patent filing (amendment 1/§12)
- **Blocked requirement:** publishing the DTEC paper, public novelty/patent claims, patent filing.
- **External dependency:** patent-counsel review + explicit authorization; a logged prior-art
  search (`prior-art-matrix.md`, currently SEARCH NOT_STARTED).
- **Completed:** confidential provisional-patent technical package scaffolded (WS-DEF); novelty
  framed as unverified Class-6 proposals.
- **Authorization:** user + counsel. **Acceptance:** counsel sign-off; nothing disclosed before.

## 5.1 Historical disclosure inventory (amendment 1 control #9)

What DTEC-related material exists and its disclosure state (verify push state when B-VIS resolves):

| Item | Location | Tracked? | Pushed? | Action taken |
|---|---|---|---|---|
| DTEC mathematical-framework manuscript (PDF) | `research/dtec/_confidential/DTEC-mathematical-framework-paper.pdf` | **No (git-ignored)** | No (was untracked; never committed) | Relocated from tracked `docs/` into confidential path 2026-11-25 |
| Confidential DTEC doc suite | `research/dtec/_confidential/*.md` | No (git-ignored) | No | Authored under confidential path |
| DTEC source code (neutral-named) | `src/strix/*` | Yes (local) | **No (B-PUSH)** | Committed locally only; no push |
| Pre-existing generic terms (`bitemporal`, `dependency-aware`) in public docs | `research/*.md`, `src/strix/orchestration` | Yes | Possibly (pre-DTEC) | Generic technical terms, not the DTEC brand; acceptable |

## 6. Invariants to preserve (do not regress)

- Zero test regressions; ruff + mypy-strict clean.
- AFIIS and C-Engine kept **separate** from STRIX (§17).
- Read-only finance; no trades/payments/transfers (§17).
- No credential exposure; no unauthorized spend/deploy; no merge to main without authorization.
- Preserve README graphics/assets, FALCON docs, unrelated changes.
- No fabrication; every target stays a target until EXPERIMENTALLY_EVALUATED.
