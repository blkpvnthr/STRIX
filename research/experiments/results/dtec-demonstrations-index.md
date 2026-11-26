# DTEC capability demonstrations — §4 index (offline, reproducible)

**Harness:** `src/strix/research_eval/dtec_demonstrations.py::run_demonstrations` · **Date:** 2026-11-26.

> **Status: OFFLINE SYNTHETIC DEMONSTRATIONS — NOT empirical validation.** Each capability is
> demonstrated deterministically against a fair naive comparator. The numbers are recomputed by
> calling the offline harnesses (not quoted). The live comparative arms and real corpora are
> `EXTERNALLY_BLOCKED` (model credentials + budget); nothing here moves a hypothesis off
> `NOT_EVALUATED`.

`run_demonstrations()` returns 13 `Demonstration` records (the 12 §4 capabilities + an overall
dependency-detection summary), each with the capability, scenario, DTEC result, fair-comparator
result, a `demonstrates` flag, and the reproducible artifact. All 13 currently demonstrate.

| § | §4 capability | DTEC vs fair comparator | Reproducible artifact |
|---|---|---|---|
| 1 | Detection of circular corroboration | DTEC flags a derived-from chain as dependent; naive citation-count treats each cite as independent | `dtec_baselines.dependency_benchmark` (lineage) |
| 2 | Detection of shared-origin evidence | DTEC catches two observations from one artifact (differing values); value-dedup misses | `dtec_baselines.dependency_benchmark` (shared_origin_diff_value) |
| 3 | Prevention of artificial evidence independence | DTEC rejects coincidentally-equal values from disjoint origins; value-dedup false-positives. On the live path `agent/dependency_check` flags cite-collapse-to-one-origin | `dtec_baselines` + `tests/agent/test_dependency_check.py` |
| 4 | Prevention of future-information leakage | DTEC two-axis gate: 0 leaks; validity-only single axis leaks | `dtec_baselines.evaluate_temporal_selection` |
| 5 | Historical evidence reconstruction | As-of a past knowledge time, later-available evidence is excluded; naive "use all current" leaks | `dtec_demonstrations.demo_historical_reconstruction` |
| 6 | Rejection of unsupported compositional conclusions | A_C rejects premises-valid-but-unsupported conclusions the individual-claim composer admits | `dtec_baselines.evaluate_compositional_support` |
| 7 | Detection of inconsistent premises | A_C rejects `p ∧ ¬p` premises; naive composer accepts | `dtec_demonstrations.demo_inconsistent_premises` |
| 8 | Appropriate uncertainty and abstention | ECE discriminates calibrated (0.00) from overconfident (0.35) | `dtec_baselines.evaluate_calibration` |
| 9 | Resource-bounded verification | Greedy ratio leads on mean yield-fraction AND never drops a mandatory op; pure yield-maximizer does | `dtec_baselines.evaluate_resource_planning` |
| 10 | Institutional evidence admissibility | Removing `A_inst` lets an unauthorized-org item through (Δ>0) | `dtec_ablation.run_ablation` |
| 11 | Independently verified final-answer synthesis | The complete synthesized answer gets a conclusion-level verdict (admitted/abstained/rejected); a recompute-contradicted run rejects | `tests/agent/test_conclusion_check.py` (live path: `agent/conclusion_check`) |
| 12 | Citation integrity | Every material assertion maps to an admitted, untampered claim certificate (§7/§30) | `agent/documentation` + `answering/validate.validate_response` |

Fair comparators and negative findings are preserved in `dtec-baselines-offline.md` and
`negative-findings/dtec-offline-negative-findings.md` (e.g. the strongest fair dependency baseline
nearly ties DTEC; greedy-ratio planning is not optimal).

Reproduce: `python -c "from strix.research_eval.dtec_demonstrations import run_demonstrations; print(run_demonstrations())"`.
