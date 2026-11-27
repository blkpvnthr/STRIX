# Offline DTEC engine ablation — results (synthetic, deterministic)

**Harness:** `src/strix/research_eval/dtec_ablation.py` · **Run:** deterministic (fixed seed/
timestamps; no live model) · **Date:** 2026-11-26.

> **Status: OFFLINE SYNTHETIC MEASUREMENT — NOT live validation.** These are real, exact,
> reproducible measurements of each engine's marginal contribution on a **synthetic,
> ground-truth-labelled** adversarial benchmark run through the unified `admit_dtec`. They are
> **not** the H1–H12 / UC1–UC5 scientific validation: the live comparative arms (A–E) are
> `EXTERNALLY_BLOCKED` on GPT-6 Luna credentials + an approved budget, and no real-corpus
> benchmark (120/1200/900-q) has been built. No figure here is a pre-registration target. This
> artifact demonstrates the **ablation methodology** (`Δ_i`, `Δ_ij`) and that each engine
> catches its designed attack class; it does **not** establish real-world efficacy.

## Benchmark
12 items spanning 6 classes (2 each): `valid`, `fabricated_value`, `dependency_inflated`,
`temporal_leak`, `institutional_violation`, `entity_relabel`. Ground truth: `should_admit` is True
only for `valid`. Each attack is constructed so the **core** `admit()` would admit it (except
`fabricated_value`, which the core's support predicate catches), isolating the responsible
extension engine.

## Measured results
| Configuration | Detection accuracy (admit/reject vs ground truth) |
|---|---|
| **Full `A_DTEC`** (all engines) | **12/12 = 1.000** |
| Core only (`admit`, no DTEC extensions) | 4/12 = 0.333 |

**Engine marginal contribution `Δ_i = M(F) − M(F₋ᵢ)`** (removing the engine → its attack class slips through):

| Engine (option-gated) | `Δ_i` | Interpretation |
|---|---|---|
| dependency (`A_ind`) | +0.167 (2/12) | removing it admits the `dependency_inflated` items |
| temporal (`T` bitemporal) | +0.167 (2/12) | removing it admits the `temporal_leak` items |
| institutional (`A_inst`) | +0.167 (2/12) | removing it admits the `institutional_violation` items |
| budget (`M_B`) | 0 | no budget-infeasibility items in this benchmark (honest null) |

Entity-binding (always-on, not option-gated) accounts for the `entity_relabel` gap between core
(misses) and full (catches): the full-vs-core delta of 0.667 (8/12) is attributable to the four
extension classes the core misses — dependency, temporal, institutional, and entity-relabel.

**Interaction `Δ_ij` (dependency, temporal):** 0 — the two engines catch disjoint attack classes,
so their contributions are independent (no interaction effect on this benchmark).

## Honest reading
- The composition is **strictly stronger than the core** on this benchmark (1.000 vs 0.333), and
  each engine's contribution is localized to its designed attack class — consistent with the
  intended design, **measured offline on synthetic data**.
- This is **methodology evidence**, not hypothesis validation. Moving UC1–UC5 / H1–H12 off
  `NOT_EVALUATED` requires the real corpora + strong baselines + the live arms (blocker B-LIVE).
- Negative/null results (budget `Δ=0`; zero interaction) are reported as-is, not hidden.

Reproduce: `python -c "from strix.research_eval.dtec_ablation import run_ablation; print(run_ablation())"`.
