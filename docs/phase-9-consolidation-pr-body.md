# STRIX — DTEC Mathematical Foundation, Governed Research Integration, and Phase I Feasibility Readiness

Consolidates DTEC Phases 1–9 (22 commits, clean fast-forward from `main` @ `5d8720f`).

## Honest status up front

This PR delivers **preliminary pre-award engineering**, not empirical scientific validation.
The unified eleven-predicate `A_DTEC` is a complete **reference** evaluator; on the **live
research lifecycle** it is **not** yet enforced per-claim end-to-end (see Limitations). All
scientific hypotheses (H1–H12 / UC1–UC5) remain **NOT_EVALUATED** — the live comparative arms and
real corpora are externally blocked (model credentials + budget, B-LIVE). No results are fabricated.

## What's included

**DTEC Phases 1–9**
- **Six mathematical research engines** (reference implementations, property-tested): R-N1 evidence
  dependency (`A_ind`, N_eff), R-N2 bitemporal (`V_i`/`K_i`, two-axis `T`), R-N3 compositional
  calculus (`R∧K∧F`, SAT/UNSAT), R-N4 uncertainty/calibration, R-N5 resource-bounded (`M_B`), R-N6
  institutional (`A_inst`).
- **Unified eleven-predicate reference admission calculus** `A_DTEC = I∧T∧P_rov∧D_num∧S∧R∧K∧F∧A_inst∧A_ind∧M_B`
  (`evidence_graph/unified.py::admit_dtec`), fail-closed, extends-not-weakens the preserved core
  (Prop 3 / INV-ALG-3).
- **Conclusion-level operational integration** (`agent/conclusion_check`): the COMPLETE synthesized
  answer is independently evaluated (DTEC `A_C`) at the authoritative chokepoint
  `run_research_question`, surfaced on `ResearchAnswer.conclusion_verification`, fail-closed in
  `validate_answer`, and **unskippable** by `--no-assurance`.
- **Dependency-aware evidence projection** (`agent/dependency_check`): content-hash origin
  canonicalization (R-N1 projection) flags artificial corroboration on the live path.
- **Authorization gateway enforcement**: the six-pillar gateway now authorizes on the **real**
  conclusion verdict (not a fabricated signal), and the serving boundary (CLI + webapi)
  **withholds** non-released answers (closes the advisory-gateway bypass).
- **Comparative baselines** (`research_eval/dtec_baselines`): steelmanned baselines for all five
  measurable engines with honest findings (the strongest fair dependency baseline ties DTEC to
  within one case; greedy-ratio planning is not optimal).
- **Negative findings & counterexamples** (`research/experiments/negative-findings/`) — first-class
  output (structural-benchmark tautology, strong-baseline near-tie, no single-axis temporal win,
  greedy suboptimality, calibration-is-metric-validation).
- **Reproducibility manifests** (`research/experiments/reproducibility/`) with content-addressed
  expected values.
- **Thirteen offline demonstrations** (`research_eval/dtec_demonstrations`) covering all twelve §4
  capabilities — every `demonstrates` flag **computed** from the harnesses / core calculus.
- **Independent adversarial review + remediation**: multiple multi-agent reviews (circularity,
  strawman, metric, overclaim, correctness, bypass, regression) found real defects; **all
  confirmed findings were remediated before their commits** (e.g. contradiction-first rejection,
  reason-code filtering, replay-hash `exclude_none`, honest docstrings, computed demonstrations).

## Validation (reproduced on this branch)

- Python: **2466 passed, 2 skipped, 2 xfailed, 0 regressions**.
- `ruff` clean · `mypy --strict` clean (258 source files).
- Frontend: vitest 15 passed · `tsc --noEmit` clean · `vite build` ✓.
- DTEC demonstrations: 13/13.
- Security/disclosure audit: clean (no secrets; confidential research suite git-ignored and absent
  from the diff).

## Limitations — remaining engineering (explicitly separated from completed work)

- **Full per-claim eleven-predicate enforcement is NOT on the live path.** `admit_dtec` is called
  by the offline harness + tests, not per live claim. `AgentClaim` is calculation-centric while the
  5-core `admit` is observation/computation-centric; a faithful `AgentClaim→EvidenceGraph` bridge is
  low-fidelity (a representation-unification question). Live enforcement = conclusion-level `A_C` +
  dependency projection + the recompute verifier. **Do not read this PR as complete operational
  eleven-predicate DTEC enforcement.**
- **Outstanding legacy execution + read-path enforcement**: campaign / legacy-pipeline / market
  answer paths (Step 11) and read-path verdict surfacing (Step 9) are not yet gated; response-schema
  versioning for pre-field legacy replay is deferred.

## Phase 10 readiness

Backend conclusion-level governance + enforcing serving boundary are in place for a governed
frontend preview (`feature/phase-10-governed-frontend-preview`). No frontend production deployment
in this PR.

## External blockers (active)

B-VIS (repo-visibility confirmation), B-PATENT (counsel), B-DEMO (separate demo repo), B-LIVE
(credentials + budget for live validation). GPU/Metal remains CPU-only on Linux.
