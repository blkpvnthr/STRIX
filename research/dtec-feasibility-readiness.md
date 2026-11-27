# STRIX Unified-Calculus — Feasibility & Readiness Report

**Status of record for the DTEC reorientation.** Neutral, public-facing summary (the branded
methodology designation, detailed algorithms, and IP analysis are held confidentially per §33 of
`MASTER_SBIR_SPECIFICATION.md`). Date: 2026-11-26. Branch:
`feature/sbir-phase-i-evidence-intelligence` (local commits only; **not pushed** — see blockers).

> **Honesty mandate.** This reports **engineering completion and offline testing**, which are
> *distinct from* scientific validation, novelty, patentability, and NSF readiness. Every metric
> target remains a target (`NOT_EVALUATED`); the live comparative experiments are externally
> blocked. No fabrication of completion, measurements, novelty, or verification outcomes.

## What was built (reconcile-and-extend; the preserved core is untouched)

STRIX's implemented claim-level admission calculus `A(c)=I∧T∧P_rov∧D_num∧S` is extended into a
unified conclusion-level calculus
`A★ = I∧T∧P_rov∧D_num∧S∧R∧K∧F∧A_inst∧A_ind∧M_B`, evaluated under the four-valued admission
algebra and **provably fail-closed** (adding a mandatory predicate can only make admission
stricter — never weaker). Six research engines realize the added predicates; all are
reference-implemented, property-tested, and independently adversarially reviewed to convergence.

| Engine | Predicate(s) | Module | Offline status |
|---|---|---|---|
| Evidence dependency intelligence | `A_ind` (effective independent count) | `evidence_graph/dependency.py` | OFFLINE_TESTED |
| Bitemporal reasoning | extended `T` (validity + knowledge, leak-free) | `evidence_graph/temporal.py` | OFFLINE_TESTED |
| Compositional calculus | `R∧K∧F` (+ optional formal entailment) | `evidence_graph/{calculus,inference,counterexamples}.py` | OFFLINE_TESTED |
| Calibrated uncertainty & abstention | selective release (non-overriding) | `assurance/{calibration,abstention}.py` | OFFLINE_TESTED |
| Resource-bounded verification | `M_B` | `assurance/verification_planner.py` | OFFLINE_TESTED |
| Institutional admissibility | `A_inst` (+ policy precedence, federation, noninterference, entity binding) | `institutional/{admissibility,policy_reasoner,federation,applicability}.py` | OFFLINE_TESTED |
| Unified admission | `A★` composition + disposition + certificate digest | `evidence_graph/unified.py` | OFFLINE_TESTED |
| Engine ablation harness | `Δ_i`, `Δ_ij` | `research_eval/dtec_ablation.py` | OFFLINE_TESTED |

**Engineering gates (measured):** `ruff` clean; `mypy --strict` clean (254 source files); full
suite **2429 passed, 0 regressions** vs the 2245 pre-reorientation baseline (+184 net new tests).
**Independent adversarial review** found and remediated **10 confirmed defects (3 critical)** across
iterated passes, each with a permanent regression test; the compositional-calculus engine was clean
on every pass. One inherent core limitation (computation-backed assertions trust claim-declared
entity/metric) is documented with an additive, scheduled fix rather than a core weakening.

## Definition-of-Done (§24) status (honest)
| # | DoD item | Status |
|---|---|---|
| 1–4 | Methodology established as the principal direction; master spec updated; six engines have formal specs; every equation has assumptions/semantics/limitations | DONE (confidential formalization + public §1.1) |
| 5–8 | Reconcile existing impls (no duplication); reference algorithms implemented + integrated; mandatory invariants intact; unified path independently verified | DONE (offline) |
| 9–10 | H1–H12 preserved; additional hypotheses (UC1–UC5) registered | DONE |
| 11–12 | Benchmark datasets + ground-truth; strong comparative baselines | PARTIAL — synthetic ablation benchmark built; 120/1200/900-q corpora + 10 baselines `NOT_STARTED` (offline-authorable) |
| 13–15 | Authorized experiments + ablations executed; results with uncertainty; negative findings preserved | PARTIAL — offline ablation executed + reported; live arms **EXTERNALLY_BLOCKED** (B-LIVE); negatives preserved |
| 16 | Institutional demos reproducible | **EXTERNALLY_BLOCKED** — separate demo repo creation (B-DEMO) |
| 17–18 | Prior-art + IP inventories; novelty vs established separated | PARTIAL — inventories scaffolded; formal prior-art **search OUTSTANDING** (B-PATENT) |
| 19–21 | Material outputs traceable; regression gates pass; critical security resolved | DONE (offline; traceability matrix maintained) |
| 22–23 | Readiness/feasibility/release treated as separate gates; pre-award vs Phase-I boundary documented | DONE (this report + `_confidential/nsf-alignment.md`) |
| 24–25 | Blocked items have resolution procedures; work documented + committed, PR where authorized | DONE locally; **push/PR EXTERNALLY_BLOCKED** (B-PUSH/B-VIS) |

## External blockers (precise resolution procedures in `execution-state.md`)
- **B-LIVE** — live comparative arms: GPT-6 Luna credentials + approved budget.
- **B-VIS / B-PUSH** — confirm repo visibility / authorize a private repo before any remote push.
- **B-PATENT** — logged prior-art search + counsel review before novelty/patent claims or disclosure.
- **B-DEMO** — GitHub repo creation for the version-pinned institutional demo.
- **DTEC-NATIVE-PROV** — value-bound computation provenance (native data-model change) to fully
  close computation-backed entity binding.

## Honest conclusion
The unified calculus and its six engines are **implemented, hardened, and offline-tested** — a
substantiated *engineering* and *formalization* result, and demonstrated experimental **readiness**.
It is **not** scientific validation: the hypotheses remain `NOT_EVALUATED` pending the live arms and
real corpora. Novelty and patentability are **unestablished** pending prior-art search and counsel.
These separations are maintained deliberately.
