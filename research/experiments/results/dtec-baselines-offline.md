# Offline DTEC comparative baselines — results (synthetic, deterministic)

**Harness:** `src/strix/research_eval/dtec_baselines.py` · **Run:** deterministic (fixed
timestamps; no live model) · **Date:** 2026-11-26.

> **Status: OFFLINE SYNTHETIC MEASUREMENT — NOT live validation.** An adversarial review of the
> first version of this harness correctly found that a benchmark whose ground-truth labels are
> defined by the same structural criteria an engine uses **cannot measure that engine** — a
> perfect DTEC score is then tautological. This version is explicit about that: the **DTEC-vs-label
> numbers are a consistency/regression check** (does the engine correctly recover the structure it
> was handed). The **informative** content is (1) the baseline failure rates and (2) whether DTEC
> **separates from the strongest FAIR baseline** on cases that require machinery the baseline lacks.
> Live comparative arms, real corpora, and a fitted production calibration model remain
> `EXTERNALLY_BLOCKED` (model credentials + budget). No figure here is a demonstrated §8 outcome.

This artifact complements `dtec-ablation-offline.md` (marginal contribution `Δ_i`/`Δ_ij`); here
each engine is measured **against named, steelmanned baselines** per §5/§7/§8.

## R-N1 — Evidence dependency detection (7-pair benchmark)

Positive class = *dependent*. The benchmark adds a `same_hash_diff_artifact_id` case: two
artifacts with **identical content bytes** (same `content_hash`) under different ids and different
semantics — genuinely dependent (same source), recoverable only by content-hash canonicalization.

| Method | F1 | TP/FP/FN/TN | Role |
|---|---|---|---|
| **DTEC `estimate_dependence`** | **1.00** | 5/0/0/2 | consistency check (recovers all structural labels) |
| null_floor (constant-False) | 0.00 | 0/0/5/2 | lower-bound reference only (not a steelman) |
| value-only dedup | 0.667 | 3/1/2/1 | FP on `disjoint_same_value`, FN on diff-value/lineage |
| artifact-id match | 0.75 | 3/0/2/2 | FN on `semantic_duplicate`, `same_hash_diff_artifact_id` |
| semantic-tuple dedup | 0.571 | 2/0/3/2 | fair dedup; no provenance, misses shared-origin cases |
| **composite (artifact-id ∨ semantic-tuple)** | **0.889** | 4/0/1/2 | **strongest fair baseline** |

**Honest result.** The strongest fair composite baseline **nearly ties DTEC (0.889 vs 1.00)**. DTEC's
*only* separation on this benchmark is the `same_hash_diff_artifact_id` case (the composite's single
FN), which DTEC catches via content-hash canonicalization. So the defensible claim is narrow: *no
single simple heuristic suffices, a strong composite comes close, and DTEC's measurable advantage
here is hash-canonicalized shared-origin detection* — **not** a general F1≥0.90 capability claim.

## R-N2 — Bitemporal evidence selection (6-case benchmark)

Two single-axis baselines are compared, not one: validity-only and availability/as-of-only (the
canonical anti-lookahead filter, which is STRIX's own pre-existing knowledge-axis predicate).

| Method | Accuracy | Future-info leaks | Meets joint (acc≥0.95 ∧ 0 leaks)? |
|---|---|---|---|
| **DTEC two-axis `is_admissible`** | **1.00** | **0** | **yes (consistency check)** |
| validity-only | 0.67 | 2 | no (leaks) |
| availability-only | 0.67 | 0 | no (admits expired validity) |

**Honest result.** The earlier framing ("single-axis baseline leaks") was unfair — it used only the
leaky axis. The real, non-circular finding is that **neither single axis meets the joint objective**:
validity-only leaks; availability-only is leak-free but loses accuracy on expired validity. The
two-axis design is justified by the *joint* accuracy∧zero-leak objective, not by a cherry-picked axis.

## R-N4 — Calibration (metric validation, NOT a comparative-method arm)

| Supplied source | ECE |
|---|---|
| well-calibrated (per-level empirical accuracy ≈ p̂) | 0.00 |
| overconfident (predicts 0.95, correct ~60%) | 0.35 |

**Honest scope.** This is **metric validation**, not DTEC-vs-a-competitor: it shows the exact ECE
computation scores a calibrated source ≤ 0.05 and flags a miscalibrated one. The calibrated 0.00 is
constructed by placing `round(10·p)` positives per bin (and is binning-sensitive). It does **not**
claim STRIX produces calibrated `p̂` — fitting a reliability model on independent real labels is
`EXTERNALLY_BLOCKED` (model credentials + budget).

## R-N3 — Compositional unsupported-claim admission (5 conclusions; 3 unsupported)

Two baselines: naive individual-claim (RAG-like) and a stronger contradiction-aware composer (admits
iff all premises admitted AND no flagged substantive opposition).

| Method | Unsupported-conclusion admit rate | Misses |
|---|---|---|
| individual-claim (RAG-like) | 3/3 = 1.00 | entailment, context, contradiction |
| contradiction-aware | 2/3 = 0.667 | entailment (R), context (K) |
| **DTEC `admit_conclusion` (A_C)** | **0/3 = 0.00** | — (consistency check) |

**Honest result.** DTEC rejecting all three is a consistency check (each case trips one A_C
predicate). The informative finding is that **even the stronger contradiction-aware baseline admits
the R (not-entailed) and K (missing-context) failures it cannot see** — a reduction of 2/2 = 100% of
*its* admitted-unsupported set. Of those, the not-entailed case has a **genuine external oracle**
(propositional entailment is objectively defined); the missing-context / faithfulness cases do not,
so they count as regression coverage, not an externally-validated capability.

## Honest reading

- **DTEC-vs-label is a consistency/regression check, not a §8 measurement.** Labels are structurally
  defined; a perfect DTEC score is tautological and is reported as such.
- **Baselines are steelmanned.** The strongest fair dependency baseline ties DTEC to within one case;
  the availability-only temporal baseline is leak-free; the contradiction-aware composer catches the
  faithfulness failure. DTEC's genuine, narrow separations are stated explicitly, not inflated.
- **These are comparative-methodology evidence, not H1–H12 validation.** Moving the hypotheses off
  `NOT_EVALUATED` requires real corpora + live arms (blocker: model credentials + budget).
- Negative/limiting findings (strong baselines nearly tie DTEC; no oracle for K/F cases; calibration
  is metric-validation only; hidden non-structural dependence, CE-N1-1, is out of scope) are stated,
  not hidden.

Reproduce: `python -c "from strix.research_eval.dtec_baselines import run_dtec_baselines; print(run_dtec_baselines())"`.
