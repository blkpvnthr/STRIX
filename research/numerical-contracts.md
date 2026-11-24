# Numerical Contracts & Exact-Arithmetic Safeguards (R1 §7)

Every native operation declares a `NumericalContract`
(`strix.native.contracts.NumericalContract`) so an independent backend can be
certified for parity and so the verifier knows how to re-derive a value.

## 1. The five contract classes (R1 §7.1)

| Class | Meaning | Reproducibility | Used by |
|---|---|---|---|
| `exact` | exact integer / exact Decimal | bitwise identical | checked arithmetic, exact sums |
| `deterministic_fp` | deterministic FP under a pinned environment | bitwise under pinned env | reserved for C++/Metal CPU kernels |
| `tolerance` | reproducible within stated tolerance | within abs+rel tolerance | descriptive/time-series/multivariate statistics |
| `approximate` | approximate statistical computation | within documented error | CIs, t-tests, effect sizes |
| `stochastic` | stochastic under recorded parameters | identical given seed | percentile bootstrap |

Agreement is decided by `within_tolerance(observed, expected, contract)`:
exact classes require equality; otherwise the admissible deviation is
`abs_tol + rel_tol·|expected|`. "Tolerance-based agreement" is explicitly **not**
represented as bitwise reproducibility (R1 §7.1).

## 2. Exact-arithmetic safeguards (R1 §7) — IMPLEMENTED/TESTED

`strix.native.arithmetic` enforces:

- **Float forbidden** at every boundary (`as_decimal`, `require_finite`): a
  `float` argument raises `NumericalContractError` (a `CalculationError`).
- **NaN/Inf rejected** (`require_finite`).
- **Division-by-zero** raised (`checked_div`), never silently producing Inf/NaN.
- **Integer overflow/underflow** detected against explicit signed/unsigned bit
  ranges (`checked_int_add`, `checked_int_mul`).
- **Exact sums** of finite Decimals (`checked_sum`) — e.g. `0.1 + 0.2 == 0.3`.
- **Banker's rounding** with negative-zero collapse (`quantize`,
  `ROUND_HALF_EVEN`).
- **Local decimal context only** — the global context is never mutated
  (regression-tested).

Authoritative financial Decimals are never converted to binary float for GPU
compatibility (R1 §7). Working precision is `ARITH_PRECISION = 50`; statistical
summaries quantize to `STAT_QUANTUM = 1e-12`.

## 3. Per-operation contract table (implemented operations)

| Operation (module) | Class | Representation | Precision | Reference method |
|---|---|---|---|---|
| `arithmetic.checked_sum/div`, `checked_int_*` | exact | int / Decimal | arbitrary | exact Decimal/int |
| `statistics.mean/median/variance/stdev/quantile/mad/iqr/skewness/kurtosis` | tolerance | Decimal | 50→1e-12 | Python `statistics` + hand values |
| `timeseries.pct_change/growth/cagr/moving_average/rolling_stdev/ewma/volatility/autocorrelation/linear_trend` | tolerance | Decimal | 50→1e-12 | Decimal recompute + `statistics.linear_regression` |
| `multivariate.covariance/correlation/*_matrix/weighted_covariance/ewma_covariance/linear_regression` | tolerance | Decimal | 50→1e-12 | `statistics.covariance/correlation/linear_regression` |
| `inference.mean_confidence_interval` | approximate | float64 | ieee754 | Student-t via regularized incomplete beta |
| `inference.welch_t_test/cohens_d` | approximate | float64 | ieee754 | hand-computed (t=−1.897, d=−1.2) |
| `inference.student_t_sf/two_sided_p` | approximate | float64 | ieee754 | Numerical Recipes `betai` continued fraction |
| `inference.bootstrap_mean_ci` | stochastic | float64 + seed | ieee754 | deterministic given recorded seed |
| `inference.benjamini_hochberg/bonferroni` | exact | float decisions | — | classic worked examples |

## 4. Typed computation result (R1 §7.2) — IMPLEMENTED/TESTED (`results.py`)

Every analytical operation produces an evidence-compatible
`ComputationResult` carrying (R1 §7.2): computation id (content-derived),
algorithm id + version, input observation ids + artifact refs + **input digest**,
the typed result (scalar/vector/matrix/structured), output units, observation
interval, applicable knowledge cutoff, backend id, numerical precision +
tolerance, statistical assumptions, missing-value policy, sample size, random
seed (where applicable), execution duration, software/build versions, and
numerical-validation status. Nondeterministic fields (duration, wall-clock) are
excluded from the content hash, mirroring the existing `RunManifest`/
`VerificationResult` convention. The result enters STRIX's existing evidence
graph; the backend never assigns a factual claim verdict.

## 5. Validation status

Arithmetic, statistics, time-series, multivariate, inference, contracts, results,
and the `PythonReferenceBackend` are IMPLEMENTED and TESTED: **276 native tests**,
cross-checked vs. Python stdlib with relative tolerance < 1e-9 and hand-computed
reference values; `mypy --strict` clean; `ruff` zero; **1138 passed total** with
no regression vs. the `862 passed` baseline. An independent adversarial review
found and fixed 3 real overflow/`0**0` crashes (see
`native-computing-architecture.md` §8).
