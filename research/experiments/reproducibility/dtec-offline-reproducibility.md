# DTEC offline evaluation — reproducibility manifest

Pins the exact commands, environment, and expected outputs for the **offline, deterministic**
DTEC evaluation harnesses so any reviewer can reproduce the reported numbers bit-for-bit. Live
arms are `EXTERNALLY_BLOCKED` and are **not** covered here. **Date:** 2026-11-26.

## Environment

| Item | Value |
|---|---|
| Python | 3.11.8 |
| Determinism | no live model, no network, no RNG, fixed timestamps (`_T0 = 2024-01-01Z`); exact `Decimal`/`Fraction` arithmetic throughout |
| Within-env check | `run_dtec_baselines()` and `run_ablation()` are byte-identical across repeated runs (verified) |
| Source commits | ablation `80fad50`; comparative baselines `548cebc` (+ hardening) and `d70a362` (R-N5) |
| Harness modules | `src/strix/research_eval/dtec_ablation.py`, `src/strix/research_eval/dtec_baselines.py` |
| Tests | `tests/test_dtec_baselines.py` (17), `tests/research_eval/test_dtec_ablation.py` (6) |

## Commands

```bash
# Engine ablation (Δ_i / Δ_ij)
python -c "from strix.research_eval.dtec_ablation import run_ablation; print(run_ablation())"
# Comparative baselines (all five measurable engines)
python -c "from strix.research_eval.dtec_baselines import run_dtec_baselines; print(run_dtec_baselines())"
# Gates
ruff check src/ tests/ ; mypy --strict src/strix ; python -m pytest tests/ -o addopts="" -q
```

## Expected outputs (content-addressed by value — the scientific record)

**Ablation** (`dtec-ablation-offline.md`): full `A_DTEC` 12/12 = 1.000; core-only 4/12 = 0.333;
`Δ` dependency = temporal = institutional = +0.167; `Δ` budget = 0 (honest null);
interaction(dependency, temporal) = 0.

**Comparative baselines** (`dtec-baselines-offline.md`):

| Engine | DTEC | Strongest fair baseline | Other baselines |
|---|---|---|---|
| R-N1 dependency (F1) | 1.00 (consistency) | composite_match 0.889 | artifact-id 0.75; value-dedup 0.667; semantic-tuple 0.571; null_floor 0.00 |
| R-N2 temporal (acc / leaks) | 1.00 / 0 | availability-only 0.667 / 0 | validity-only 0.667 / 2 · `no_single_axis_meets_joint = True` |
| R-N4 calibration (ECE) | — | — | calibrated 0.00; overconfident 0.35 (metric validation only) |
| R-N3 compositional (unsupported admit) | 0.00 | contradiction-aware 0.667 | individual-claim 1.00 · `reduction_vs_strongest = 1.00` |
| R-N5 planning (mean yield-fraction) | 0.9375 | cost_ascending 0.900 | utility-first 0.844; FIFO 0.619 · suboptimality `knapsack_suboptimal` · mandatory-safe = True |

**Gates:** ruff clean · mypy --strict clean (255 source files) · pytest **2446 passed, 2 skipped,
2 xfailed, 0 regressions**.

## Reproduction criterion

The run reproduces iff (a) every value in the table above matches exactly, and (b) the gate
results match. Any divergence is a regression to investigate, not a tolerance. Values are exact
rationals rendered as `Decimal`; the long repeating forms (e.g. 0.888…) are the exact
`checked_div` results of the stated fractions (composite F1 = 8/9, etc.).
