# DTEC offline evaluation — negative findings & limitations (first-class output)

**Scope:** negative, null, and limiting findings from the offline synthetic evaluation
(`dtec_ablation`, `dtec_baselines`) and the adversarial review of the baseline harness.
Preserved as first-class scientific output per the mandate (§5 "negative findings and
limitations"; §6 "negative-findings repository"). **Date:** 2026-11-26.

> These are honest limits of the *offline synthetic* evaluation. They do not describe failures
> of the engines on real corpora (which are `EXTERNALLY_BLOCKED` on model credentials + budget,
> and therefore neither confirmed nor refuted here).

## NF-1 — Structural benchmarks make DTEC-vs-label scores tautological (methodology limit)

The dependency/temporal/compositional benchmarks define ground-truth labels by the same
structural criteria the engines use, so a perfect DTEC score is **not a measurement** — it is a
consistency/regression check. Surfaced by the adversarial review (circularity lens, 3 MAJOR
findings) and corrected by reframing every result and foregrounding the *baseline* failure rates
and *separation* cases instead. Consequence: the §8 capability targets (F1≥0.90, temporal
accuracy≥0.95, etc.) are **not** established by these artifacts.

## NF-2 — A strong fair baseline nearly ties DTEC on dependency detection

The strongest fair composite baseline (artifact-id ∨ semantic-tuple record linkage) reaches
**F1 = 0.889** vs DTEC's 1.00 on the 7-pair benchmark. DTEC's *only* measured separation is the
`same_hash_diff_artifact_id` case (content-hash canonicalization). So DTEC's measurable advantage
over a competent simple baseline is **narrow**, not the "strictly dominates" the first cut claimed.

## NF-3 — No single temporal axis advantage; the win is the *joint* objective

An availability-only ("as-of") single-axis baseline achieves **zero leakage** (0.67 accuracy).
The validity-only axis leaks. The two-axis gate's advantage is meeting the *joint* accuracy∧
zero-leak objective — **not** a leakage advantage over a fair single axis (the first cut's
"availability gate is exactly the discriminator" framing was an artifact of the leaky axis).

## NF-4 — Greedy value/cost-ratio verification planning is not optimal

On the `knapsack_suboptimal` instance the greedy-ratio planner reaches **3/4 of the optimum**
while cheapest-first reaches it (equal-ratio items make greedy waste budget). Greedy-ratio leads
on *mean* yield-fraction (0.9375) but is a heuristic; its decisive, defensible advantage is
**mandatory-safety**, not yield optimality.

## NF-5 — Calibration result is metric-validation only, not a production claim

The ECE arm shows the metric scores a (constructed) calibrated source at 0.00 and an overconfident
one at 0.35. It does **not** demonstrate STRIX produces calibrated probabilities — fitting a
reliability model on independent real labels is blocked. The calibrated 0.00 is binning-sensitive
and constructed.

## NF-6 — Null ablation contributions (reported, not hidden)

The engine ablation measured `Δ(budget) = 0` (no budget-infeasibility items in that benchmark)
and `interaction(dependency, temporal) = 0` (disjoint attack classes). Honest nulls.

## NF-7 — Out-of-scope by construction

Hidden non-structural shared origin (CE-N1-1), natural-language faithfulness, multi-hop lineage
not sharing an artifact, and partial-Jaccard dependence are **not** in these benchmarks; DTEC's
scores do not generalize to them. These are open research, not demonstrated capabilities.

## Standing limitation — no live validation

All H1–H12 / UC1–UC5 hypotheses remain `NOT_EVALUATED`. The real corpora (120/1200/900-q), the
≥10 comparative baselines under controlled budgets, and the five live arms require model
credentials + an approved budget (blocker). Nothing here moves a hypothesis off `NOT_EVALUATED`.
