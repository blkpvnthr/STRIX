# Native Quantitative Computing Architecture (R1 §5, §7, §8)

**Milestone:** R1 — Resource-Bounded Typed Evidence Verification
**Status key:** IMPLEMENTED / TESTED / PARTIAL / PLANNED / BLOCKED
**Baselines:** STRIX `849018d`; C-engine `3a23b13` (extraction source, read-only).

## 1. Goal and non-goals

A portable, **CPU-first** numerical/statistical foundation the research agent can
call directly, producing evidence-compatible results that the independent
verifier may admit. Per R1 §35 the priority is a *complete CPU-backed answering
system before hardware optimization*; Metal is the last, optional layer.

The library MUST NOT depend on brokerage execution, trading-account state,
market-order routing, trading strategies, C-engine's full runtime, or Apple
hardware for core functionality (R1 §5.1). The CPU path is portable across Linux
and macOS.

No backend (LLM, CPU, Metal) may assign an authoritative claim verdict (R1 §4,
§21). This layer emits `ComputationResult` evidence only.

## 2. Reuse-first foundation (what already existed)

The audit (`repository-baseline-audit.md`) established that STRIX already embodies
the exact-arithmetic discipline R1 needs. The native layer **extends** it rather
than rebuilding:

| Reused from STRIX | Where | Native-layer use |
|---|---|---|
| `make_id`, `canonical_hash`, `canonical_bytes`, `encode_decimal`, `sha256_hex` | `strix.canonical` | content-addressed `ComputationResult` ids + input digests |
| `StrixModel` (frozen, `extra='forbid'`) | `strix.models` | base for every native result/contract model |
| `DecimalValue` (`_reject_float`) | `strix.models` | float-forbidden numeric fields |
| exact-Decimal + `localcontext` + `ROUND_HALF_EVEN` + `InvalidOperation→CalculationError` | `strix.analytics.profitability`, `strix.agent.calculations` | the numerical discipline generalized to all §6 statistics |
| `recompute()` verifier-entry pattern | `strix.agent.calculations` | the model for independent re-derivation (R1 §10.4) |

## 3. Module layout (implemented)

Adapted to the existing repo (not the greenfield `native/` C++ tree in R1 §5.2,
which is reserved for the C++ port — see §6):

```
src/strix/native/
├── __init__.py          # package contract + rules (IMPLEMENTED)
├── arithmetic.py        # checked exact arithmetic, §7            (IMPLEMENTED, TESTED)
├── statistics.py        # descriptive statistics, §6.1            (IMPLEMENTED, TESTED)
├── timeseries.py        # time-series analytics, §6.2             (IMPLEMENTED, TESTED)
├── multivariate.py      # covariance/correlation/regression, §6.3 (IMPLEMENTED, TESTED)
├── inference.py         # CIs/t-test/bootstrap/FDR, §6.4          (IMPLEMENTED, TESTED)
├── contracts.py         # numerical-contract + backend abstraction (IMPLEMENTED, TESTED)
├── results.py           # typed ComputationResult, §7.2            (IMPLEMENTED, TESTED)
└── backends/
    ├── python_reference.py  # PythonReferenceBackend + 27-op registry (IMPLEMENTED, TESTED)
    ├── cpu/                 # pybind11 → C++ NativeCPUBackend       (PLANNED)
    └── metal/               # Obj-C++ MetalComputeBackend           (PLANNED)
```

The `PythonReferenceBackend` exposes 27 operations (descriptive/time-series/
multivariate/inference) under stable names, each producing a typed
`ComputationResult` with its `NumericalContract`, content-derived id, and input
digest. It is the independent-validation baseline (`BackendValidation.REFERENCE`).

## 4. Numerical contract classes (R1 §7.1) — as applied

Every operation declares a `NumericalContract` (`contracts.py`) with one of five
classes:

| Class | Native operations | Representation |
|---|---|---|
| `exact` | checked integer arithmetic; exact Decimal sums | int / Decimal |
| `deterministic_fp` | — (reserved for pinned-env C++/Metal) | — |
| `tolerance` | descriptive/time-series/multivariate statistics | Decimal (prec 50 → quantized 1e-12) |
| `approximate` | confidence intervals, t-tests, effect sizes | float64 |
| `stochastic` | percentile bootstrap (recorded seed) | float64 + seed |

Descriptive/multivariate statistics are computed in exact Decimal at precision 50
and quantized to `STAT_QUANTUM = 1e-12`; they are classified `tolerance` (not
`exact`) because a floating-point backend will only match within tolerance. The
Python reference is the independent validation baseline; `within_tolerance()`
decides parity.

Exact financial quantities are **never** converted to binary float for GPU
compatibility (R1 §7). GPU workloads operate on derived statistical inputs, not
authoritative monetary amounts.

## 5. Backend abstraction (R1 §5.3)

`BackendKind` ∈ {`python_reference`, `native_cpu`, `metal`}. Each backend
publishes a `BackendInfo` (supported operations, precision, `BackendValidation`
status, platform, hardware requirements). Selection accounts for operation type,
input size, numerical requirements, hardware availability, remaining budget, and
**certification status** — never silently substituting an approximate result for
one that requires exact arithmetic (R1 §5.3). CPU fallback is always valid and
default.

## 6. C-engine extraction mapping (from `cengine-extraction-audit.md`)

The CPU-first Python reference is implemented first and natively. The C++/Metal
layers reuse C-engine numerics *after generalization* (strip trading vocabulary;
do not modify C-engine):

| C-engine component | Classification | Native target | Notes |
|---|---|---|---|
| `analytics/features.cpp` | reusable_after_generalization | `backends/cpu` statistics/timeseries | STL-only SMA/EMA/rolling-std/returns/ROC; float-only, OHLCV-coupled; add CAGR/autocorr/trend |
| `risk/portfolio_allocator.cpp` | reusable_after_generalization | `backends/cpu` matrices/optimization | quadratic-form/matvec/Euler-risk/box-projection; STL-only, thread-safe |
| `metal/covariance.metal` | reusable_after_generalization | `backends/metal` | parity-validated float32 covariance/EWMA kernels |
| `opportunity_discovery/metal_runtime.mm` + `cpu_reference.hpp` | reusable_after_generalization | `backends/metal` + `backends/cpu` | Metal dispatch harness, buffer pool, CPU parity reference |
| `risk/risk_engine.cpp` | reusable_after_generalization | GAP-001 `constraints/` | ordered constraint eval + typed reason codes + duplicate guard |
| `volatility/volatility.cpp` | reference_only | GAP-003 `integrity/` | only O(1) freshness/skew predicates (no vol math) |
| `cengine/decision_events.py` | reference_only | GAP-002 `integrity/` | bounded/lossy in-memory sink — **reimplement durably** |
| `cengine/certification/data_integrity.py` | (see extraction audit) | GAP-003 reconciliation | duplicate/temporal/coverage/cross-resolution |

IP: all components share STRIX's owner; no LICENSE file present → treated
proprietary. Most are **not public-repo-safe** (trading coupling); sensitive
specifications stay on the local research branch (R1 §33).

## 7. CPU/Metal parity plan (R1 §8.3) — PLANNED

For every accelerated operation: generate representative + adversarial inputs,
run the Python reference, the native CPU, and the Metal implementation, compare
under the operation's `NumericalContract` tolerance, record max abs/rel error and
failing cases, and set `BackendValidation`. A result violating its contract
cannot support an admitted claim (R1 §8.3). Linux operation never depends on
Metal (R1 §26.2).

## 8. Current test status

- `tests/native/`: arithmetic, inference, statistics, time-series, multivariate,
  contracts, results, backend — **276 tests, all passing** (cross-checked against
  Python stdlib `statistics` with relative tolerance < 1e-9 and hand-computed
  values).
- **Full repository regression suite: 1138 passed, 2 skipped, 2 xfailed** — no
  regressions versus the `862 passed` baseline (`849018d`).
- `mypy --strict`: clean on the native package (10 source modules).
- `ruff`: zero findings on `src/strix/native/` and `tests/native/`.
- **Adversarial numerical review** (independent, findings-only) found 3 real bugs
  that the modules' own tests missed — a critical `quantize` global-context
  overflow (crashed `mean`/`variance` on market-cap-scale values, wei, ns
  timestamps), the same overflow in inference `_dec`, and an `ewma_covariance`
  `0**0` crash at `alpha=1` — all fixed TDD-style with regression tests in
  `tests/native/test_native_review_regressions.py`.

See `numerical-contracts.md` for the per-operation contract table and the
`ComputationResult` schema once `results.py` lands.
