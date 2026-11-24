# Milestone R1 — C-engine Extraction Audit

**Purpose.** Determine which C-engine numerical components can seed STRIX's general-purpose native-numerics library (`native/`) for Milestone R1, and under what terms (reuse, generalize, reference, reimplement). Each of the nine components below was audited at the pinned C-engine baseline and classified, with its full component analysis reproduced verbatim in §§1–9.

## Pinned baselines

- **STRIX:** `849018d` (branch `feat/milestone-0b`).
- **C-engine:** `3a23b13` (branch `feature/m9-runtime-microstructure-execution-learning`).

## Extraction principles

1. **Reuse general-purpose numerics only.** Extract the mathematical/mechanistic core (checked arithmetic, constraint evaluation, covariance/EWMA, data-quality checks, GPU dispatch harness); leave trading semantics behind.
2. **Do NOT couple STRIX to trading.** No order/notional/position/side/VIX/VXN/StatArb/OHLC/broker vocabulary, namespaces, or policy may leak into `native/`. Trading concepts become application-supplied inputs in a downstream consumer, never library code.
3. **Do NOT modify C-engine.** All audits are read-only against the pinned baseline; extraction is clean-room reimplementation or owner-authorized lift, never an in-place edit of C-engine.
4. **CPU-first; Metal gated on CPU parity.** The CPU backend is the correctness authority and reference oracle. Any Metal/GPU path ships only after it demonstrates documented parity with the CPU reference (R1 §8.3). GPU is an optimization, never the source of truth.

> **Licensing note (applies to all nine components).** C-engine has **no LICENSE/COPYING file** at its root and no per-file SPDX/copyright headers; `pyproject.toml` has no `license` field. License status is therefore **UNKNOWN / all-rights-reserved by default**. The IP owner (Asmaa Abdul-Amin / blkpvnthr / Quantum Quant) is the same party that owns STRIX, so internal reuse is an owner decision rather than a third-party-license blocker — but **no component is safe to copy verbatim into a public STRIX repo** until an explicit license is added to C-engine, or the algorithm is clean-room reimplemented from its documented spec.

---

## Classification summary

| # | Component | Actual source paths | Classification | Proposed `native/` target | IP owner / License / Public-safe | One-line reuse rationale |
|---|-----------|---------------------|----------------|---------------------------|----------------------------------|--------------------------|
| 1 | Deterministic risk engine | `risk/risk_engine.hpp`, `risk/risk_engine.cpp`, `orderbook/orderbook.hpp`, `bindings/python_bindings.cpp`, `docs/optimization/native_risk_authority.md` | reusable_after_generalization | `constraints/` + `arithmetic/` + `integrity/` (cpu backend; bindings; reference) | github.com/blkpvnthr/C-engine (same owner as STRIX; Asmaa Abdul-Amin) / UNKNOWN (no LICENSE file; README has no license grant) / **no** | Integer-only checked-arithmetic + ordered short-circuit constraint evaluator with typed deterministic reason codes + atomic duplicate-action guard — the exact mechanism GAP-001 needs, once stripped of trading names. |
| 2 | Portfolio allocator | `risk/portfolio_allocator.cpp`, `risk/portfolio_allocator.hpp`, `bindings/portfolio_bindings.cpp`, `tests/test_portfolio_allocator_native.py`, `CMakeLists.txt:60` | reusable_after_generalization | `matrices/` + `statistics/` + `constraints/` + `optimization/` | C-engine/STRIX owner (proprietary, same party) / UNKNOWN (no root LICENSE; treat as all-rights-reserved) / **no** | Clean STL-only, thread-safe quadratic-form/matvec/Euler-risk/inverse-vol/box-budget-projection primitives; split out of trading vocab into native/. |
| 3 | Volatility & freshness | `volatility/volatility.cpp`, `volatility/volatility.hpp`, `orderbook/orderbook.hpp`, `CMakeLists.txt:62`, `statArb/stat-arb.hpp` | reference_only | `integrity/` (freshness + timestamp-skew), backends/cpu | Proprietary, same owner as STRIX (user); no LICENSE file present / UNKNOWN / **no** | No EWMA/vol math exists here; only O(1) integer freshness/skew predicates worth reimplementing natively as §10.2 reference. |
| 4 | Statistical features & time-series | `analytics/features.cpp`, `analytics/features.hpp`, `CMakeLists.txt:56` | reusable_after_generalization | `statistics/` + `timeseries/` (backends/cpu reference; arithmetic/, integrity/ helpers) | STRIX principal (Asmaa Abdul-Amin / Quantum Quant) — same author as repo / UNKNOWN (no LICENSE file, no SPDX header; treat as proprietary, owner-controlled) / **yes** | Sound STL-only SMA/EMA/rolling-std/returns/ROC kernels, but float-only, OHLCV-coupled, untested, and missing R1 CAGR/autocorrelation/trend/anomaly. |
| 5 | Metal covariance/EWMA/regression kernels | `metal/covariance.metal`, `cengine/metal_covariance.py`, `cengine/metal_cpu_ref.py`, `cengine/metal_backend.py`, `tests/test_metal_hardware.py`, `tests/test_native_metal_runtime.py` | reusable_after_generalization | `statistics/` (covariance+EWMA), `matrices/`, `timeseries/`, `optimization/` regression; backends/cpu+metal, reference/ | C-engine repo owner (Asmaa Abdul-Amin); same owner as STRIX / UNKNOWN (no LICENSE file; no header; treat proprietary) / **no** | Parity-validated float32 covariance+EWMA Metal kernels are reusable after stripping StatArb/VIX trading coupling and adding stable float64 numerics. |
| 6 | Obj-C++ Metal runtime + CPU reference | `opportunity_discovery/metal_runtime.mm`, `opportunity_discovery/metal_runtime.hpp`, `opportunity_discovery/cpu_reference.hpp`, `opportunity_discovery/cpu_reference.cpp`, `opportunity_discovery/metal_buffers.mm`, `opportunity_discovery/metal_buffers.hpp`, `opportunity_discovery/screening_types.hpp`, `CMakeLists.txt` | reusable_after_generalization | backends/metal + backends/cpu + reference + statistics + arithmetic + integrity | STRIX owner (blkpvnthr / QuantumQuant) — same author as C-engine / UNKNOWN (no LICENSE file; all-rights-reserved) / **no** | Generic Metal dispatch harness + buffer pool + int/float numeric kernels are reusable once split from the embedded trading screening/ranking logic and renamed. |
| 7 | Decision-event contracts | `cengine/decision_events.py`, `tests/test_decision_events.py`, `tests/test_decision_event_integrity.py`, `tests/test_execution_decision_events.py`, `tests/test_portfolio_decision_events.py` | reference_only | `integrity/` (durable event-contract + outcome traceability; certification/ consumes) | C-engine project owner (QuantumQuant); no license file, treat proprietary / UNKNOWN (no LICENSE at repo root) / **no** | Trading-domain event schema + bounded in-memory lossy sink; reuse the contract/drain pattern only, reimplement durable persistence. |
| 8 | Data integrity + failure injection | `cengine/certification/data_integrity.py`, `cengine/certification/failure_injection.py`, `cengine/certification/datasource.py`, `cengine/certification/contracts.py`, `cengine/runtime/calendar.py` | reusable_after_generalization | `integrity/` (+ `timeseries/`, `certification/`) | C-engine project author (Asmaa Abdul-Amin) / UNKNOWN (no LICENSE file; pyproject has no license field) / **no** | Standard data-quality checks (dup/missing, temporal, coverage, cross-resolution reconciliation, point-in-time) plus a fault-injection/graceful-degradation pattern — clean-room reimplement over a backend-neutral table abstraction. |
| 9 | CMake build + pybind11 bindings + packaging | `CMakeLists.txt`, `pyproject.toml`, `bindings/python_bindings.cpp`, `bindings/discovery_bindings.cpp`, `bindings/portfolio_bindings.cpp`, `native_adapters.py`, `build-metal/` | reference_only | backends/{cpu,metal} + bindings + certification (integrity) + packaging | Asmaa Abdul-Amin / blkpvnthr (first-party, same owner as STRIX) / UNKNOWN (no LICENSE file; all-rights-reserved by default) / **no** | Glue layer with no generic numerics; port the CMake Metal-degrade backend abstraction, register_<domain> pybind11 seam, scikit-build packaging, and kernel-registry/CPU-parity patterns rather than copying trading-coupled files. |

---

## 1. Deterministic risk engine

### Deterministic risk engine

Audited at C-engine pinned baseline `3a23b13` (branch `feature/m9-runtime-microstructure-execution-learning`). This component is the pre-trade authorization boundary that STRIX R1 §18 GAP-001 ("deterministic execution authorization") maps onto. The analysis below separates the *general-purpose deterministic authorization machinery* (reusable) from the *trading-domain semantics* (must not leak into a STRIX-owned native library).

---

#### Actual source paths

- `/Users/blkpvnthr/C-engine/risk/risk_engine.hpp` (596 lines) — all public/private types + `RiskEngine` class declaration.
- `/Users/blkpvnthr/C-engine/risk/risk_engine.cpp` (1702 lines) — full implementation.
- Dependency header: `/Users/blkpvnthr/C-engine/orderbook/orderbook.hpp` (only for `enum class Side { Buy, Sell }`, defined at line 72; `risk_engine.hpp` line 3 `#include "orderbook/orderbook.hpp"`).
- Build integration: `/Users/blkpvnthr/C-engine/CMakeLists.txt` line 59 lists `risk/risk_engine.cpp` as a source of `cengine_core`. C++ standard = C++20 (CMakeLists lines 4-5).
- Python binding surface: `/Users/blkpvnthr/C-engine/bindings/python_bindings.cpp` lines 5, 47-61 (binds `RiskRequest`, `RiskResult`, `RiskEngine.evaluate`, kill-switch; NOTE: `evaluate_amendment`, `reserve_order_id`, `release_order_id`, `snapshot`, `set_limits`, and custom `RiskLimits` are NOT bound — only default-constructed engine is reachable from Python).
- Design/authority doc: `/Users/blkpvnthr/C-engine/docs/optimization/native_risk_authority.md` (declares `RiskEngine` the "sole financial authority"; hard limits explicitly excluded from any optimizer search space).
- No dedicated C++ unit-test file exists (see Existing tests). No `LICENSE`/`COPYING` file in repo; `README.md` has no license/copyright text.

---

#### Algorithm & math assumptions

Two public evaluation entry points, both returning a typed `RiskResult { decision, reason, message, calculated_notional_ticks, projected_position, projected_gross_exposure_ticks }`.

`evaluate(RiskRequest)` (cpp 118-281) runs an ordered, short-circuiting gauntlet; each stage returns on first failure with a deterministic `RiskRejectReason`:
1. Kill switch (123-130).
2. Duplicate order-id pre-check against `seen_order_ids_` set (132-143).
3. Field validation (order_id!=0, symbol charset/length, quantity>0, price_ticks>0) — `validate_order_fields` (1321-1353).
4. Market validation — `validate_market` (1160-1215): symbol presence + match, bid/ask validity (`RiskMarketState::valid()` requires `bid>0 && ask>0 && bid<ask`), timestamp presence, future-timestamp rejection, staleness (`age = now_ns - ts_ns > max_market_data_age_ns`), then price collar.
5. Price collar — `validate_price_collar` (1222-1314): reference = midpoint = `bid + (ask-bid)/2`; checks `|order - ref|/ref <= bps/10000` using integer quotient/remainder decomposition (whole=ref/10000, remainder=ref%10000) to avoid FP and overflow; bps==0 disables; overflow in threshold → conservatively accepts (treated as unreachable distance).
6. Notional = `quantity * price_ticks` via checked `safe_notional`/`safe_mul_u64` (962-977, 54-74).
7. Projected position via `safe_project_position` (998-1146) — signed position arithmetic with full INT64 range guarding across buy/sell × long/short/flip quadrants, including the `INT64_MIN` edge via `max_negative_magnitude = I64_MAX + 1`.
8. Per-order limits (qty, notional, long/short/gross position) — `validate_order_limits` (1360-1426).
9. Open-order aggregate limits (count, summed remaining qty) — `validate_open_order_limits` (1433-1473).
10. Gross exposure projection (checked add) — `validate_exposure` (1480-1515).
11. Buying power (buys only; sells skip; negative BP rejected) — `validate_buying_power` (1522-1558).
12. Atomic reserve: insert order_id into `seen_order_ids_` only after all checks pass (254-272); double-guards duplicate.

`evaluate_amendment(AmendmentRiskRequest)` (288-671) is a replace-semantics variant: validates against *proposed total* state, requires the order_id to already be reserved, rejects reducing total below `filled_quantity`, and computes incremental position/exposure/buying-power deltas (only the change in remaining quantity moves projected position; existing resting remainder assumed already represented in `open_orders`). Has a documented fallback (548-602) when the account's `gross_exposure_ticks` does not include open-order exposure.

Math assumptions: all prices/monies are **integer ticks** (no floating point anywhere in the decision path — a deliberate determinism choice, header lines 68-72). All arithmetic is overflow-checked. `abs_i64_to_u64` (25-36) avoids UB on `INT64_MIN`. BPS denominator is fixed 10000 (line 17).

---

#### Dependencies

- Standard library only: `<chrono> <cstddef> <cstdint> <mutex> <optional> <string> <string_view> <unordered_map> <unordered_set> <vector>` (header) and `<algorithm> <cctype> <limits> <stdexcept> <utility>` (cpp). `<unordered_map>` and `<vector>` are included but appear unused in the risk types.
- Single intra-repo dependency: `orderbook/orderbook.hpp` **solely for `enum class Side`**. This is a trivial 2-value enum — not a real coupling to the matching engine. Easily replaced by a STRIX-local `enum`.
- `std::isupper`/`isalnum` (cctype) used in `valid_symbol` (935-955) — locale-sensitive (see Numerical/determinism caveat).
- No third-party libs, no OS-specific calls, no allocator customization beyond std containers.

---

#### Existing tests (do NOT establish correctness for STRIX usage)

- **No C++ unit test exists** for `RiskEngine`. `find`/grep for `*risk*test*` and for `RiskEngine` in any `.cpp` test target returns nothing except the binding + source.
- Coverage is indirect, via Python integration tests through pybind11: `tests/test_native.py::test_native_risk_kill_switch_is_authoritative` (only asserts kill-switch rejects), and references in `tests/test_protective_exit.py`, `test_execution_mock_certification.py`, `test_mock_execution_fullpath.py`, `test_portfolio_mock_execution.py`, `test_optimization_exits.py`.
- These tests exercise a **default-constructed** engine only (no custom `RiskLimits`, no `evaluate_amendment`, no order-id lifecycle, no collar/staleness/overflow paths — none of which are even bound in Python).
- Conclusion: existing tests give essentially **zero** verification of the arithmetic-safety core, the collar integer math, the position-projection quadrants, the amendment replace-semantics, or determinism. For STRIX these are the exact behaviors we would depend on. Treat as **unverified** — STRIX must build its own exhaustive test suite (see Independent validation).

---

#### Numerical precision

- Entirely integer / fixed-point (ticks). No floating point in the decision path → bit-for-bit deterministic across platforms and runs, independent of FP rounding mode or `-ffast-math`. This is the single most valuable property for STRIX R1 GAP-001.
- Collar comparison is exact integer inequality via quotient/remainder; it is a *conservative* approximation (drops a sub-unit remainder term), so it can accept an order marginally (<1 tick) beyond the exact bps boundary — acceptable for a guardrail, must be documented if reused.
- Overflow is detected, not wrapped; `INT64_MIN` handled explicitly.
- Determinism caveat: `valid_symbol` uses `std::isalnum` which is **locale-dependent**; under a non-C locale classification could differ. For STRIX, replace with an explicit ASCII check to guarantee determinism.

---

#### Computational complexity

- `evaluate`: O(1) arithmetic + O(1) average hash-set lookup/insert into `seen_order_ids_` (`std::unordered_set<uint64_t>`), plus O(len) symbol scan (len ≤ 32). Effectively constant-time.
- `evaluate_amendment`: O(1) + one hash lookup.
- Memory: `seen_order_ids_` grows unboundedly unless `release_order_id` is called — a lifecycle responsibility on the caller (header 360-363 warns to prefer never reusing IDs). For STRIX this is a potential unbounded-growth concern that needs an eviction/retirement policy.

---

#### Thread-safety

- A single `mutable std::mutex mutex_` (header 469) guards every public method via `std::scoped_lock` (evaluate 121, amendment 291, kill switch 679/685/691, limits 709/715, id lifecycle 727/741/755, snapshot 765). Duplicate-check + reserve is atomic within the evaluate critical section (comment cpp 254-256).
- Coarse-grained but correct: all shared mutable state (`seen_order_ids_`, counters, kill switch, limits) is lock-protected. Copy/move deleted (header 370-374) — single-instance ownership.
- Contention: one global lock serializes all evaluations; fine for a single authorization gate, a bottleneck under high parallel throughput. STRIX could keep the coarse lock (simplicity/determinism) or shard.

---

#### Platform requirements

- C++20, standard library only. No SIMD, no GPU, no OS APIs, no endianness assumptions in logic (integers compared, not serialized). Compiles anywhere with a conforming C++20 toolchain; the repo builds it under both a CPU and a `build-metal` (Apple) configuration, but the component itself is platform-agnostic. No Metal/CPU-backend split needed — this is pure control-flow + integer arithmetic.

---

#### IP ownership & licensing

- Owner: repository `github.com/blkpvnthr/C-engine` (user: blkpvnthr / Asmaa Abdul-Amin). No `LICENSE`/`COPYING` file present; `README.md` contains no copyright or license grant → license status is **UNKNOWN / all-rights-reserved by default**.
- Same owner as STRIX, so internal reuse is an ownership/consent question, not a third-party-license question. For a **public** STRIX repo this is NOT safe to copy verbatim without an explicit license being added to C-engine (or a clean reimplementation from the documented spec). Public-repo-safe = false until license is clarified.

---

#### Trading-specific assumptions that must NOT leak into STRIX

- Domain vocabulary: `RiskEngine`, "order", "notional", "position" (long/short), "gross exposure", "buying power", "price collar", "kill switch", `Side::Buy/Sell`, "market data staleness", bid/ask/midpoint.
- `safe_notional` hard-codes `notional = quantity * price` (a trading identity).
- Price-collar semantics (bps deviation from bid/ask midpoint) is a market-data concept.
- Buying-power model: "buys consume buying power, sells don't; short margin out of scope" (cpp 1530-1534) — a trading cash-risk simplification.
- Position-projection quadrants encode long/short netting rules.
- Market-data freshness / future-timestamp rules assume a live quote feed.
- `RiskRejectReason` enum is entirely trading-flavored (NotionalLimitExceeded, PriceCollarExceeded, InsufficientBuyingPower, …).
- None of these belong in a general-purpose STRIX numerics library; only the *mechanisms* underneath them generalize.

---

#### Necessary generalizations

To extract the reusable kernel for STRIX GAP-001 ("constraint evaluation, duplicate-action prevention, checked arithmetic, deterministic rejection reasons"):
1. **Checked integer arithmetic** (`safe_mul_u64`, `safe_add_u64`, `safe_sub_u64`, `abs_i64_to_u64`, `safe_project_position`-style signed accumulation) → generalize to a standalone `native/arithmetic/` checked-integer module with generic names (checked_mul/add/sub, abs_to_unsigned, signed_accumulate_with_clamp). Drop the `notional`/`position` naming.
2. **Ordered short-circuit constraint evaluator** → generalize to a `native/constraints/` engine: a sequence of named predicates over a typed request, returning a typed `{decision, reason_code, message, diagnostics}` on first failure. Replace `RiskRejectReason` with a domain-neutral reason-code registry.
3. **Duplicate-action prevention** (`seen_order_ids_` set + atomic check-then-reserve + release/lifecycle) → generalize to a `native/integrity/` idempotency/dedup guard keyed on an opaque `uint64 action_id`, with a pluggable retirement/eviction policy (fix the unbounded-growth gap).
4. **Deterministic bps/ratio-threshold comparison via quotient/remainder** → generalize to `native/arithmetic/` exact fixed-point ratio comparison helper.
5. **Thread-safety wrapper** → keep as an optional synchronized facade; the core evaluator should be a pure function for testability/determinism.
6. Strip `Side`, bid/ask, buying power, collar → those become *application-supplied predicates* in the trading consumer, not library code.

---

#### Proposed STRIX integration (native/ layout)

- `native/arithmetic/` — checked integer ops (mul/add/sub/abs/signed-accumulate) + exact fixed-point ratio comparison (from `safe_*` helpers + collar math). **Primary target.** CPU-only; no `backends/metal` needed (scalar control flow).
- `native/constraints/` — generic ordered short-circuit constraint evaluator with typed decision/reason-code result (from the `evaluate` gauntlet structure + `RiskResult`/`reject_result`/`accept_result` pattern). **Primary target.**
- `native/integrity/` — idempotency / duplicate-action guard with bounded retirement policy (from `seen_order_ids_` + reserve/release). **Primary target.**
- `native/certification/` — the determinism guarantee (integer-only, reproducible decisions) is a certifiable property; expose golden-vector certification here.
- `bindings/` — pybind11 wrapper mirroring the existing binding style, but exposing the *generalized* API (not trading types); fix the current gap where amendment/limits/lifecycle are unbound.
- `reference/` — a pure-Python reference implementation of the constraint evaluator + checked arithmetic for cross-validation against the native path (none exists today).
- `backends/cpu` only. **No `backends/metal`** — nothing here is data-parallel.
- NOT targets: statistics, timeseries, matrices, optimization — none applicable to this component.

---

#### Independent validation requirements

Because existing tests verify almost nothing of the reusable core, STRIX must, before depending on any extracted code:
1. Exhaustive unit tests for checked arithmetic at all boundaries: `0`, `1`, `UINT64_MAX`, `INT64_MAX`, `INT64_MIN`, `INT64_MIN+1`, multiply/add/sub overflow, `abs_i64_to_u64(INT64_MIN)`.
2. Full-quadrant tests for signed position/accumulator projection (buy/sell × flat/long/short, exact flip-to-zero, flip-to-INT64_MIN, overflow).
3. Exact-vs-approximate tests for the quotient/remainder ratio comparison (prove the conservative-accept direction and bound the sub-unit error).
4. Ordered short-circuit tests: assert the *first* failing constraint's reason code is returned deterministically; property test that reason is a function only of inputs.
5. Idempotency/dedup concurrency tests: TSan under parallel check-then-reserve; verify atomicity and the retirement policy bounds memory.
6. Determinism / golden-vector tests: same inputs → identical decision + reason across OS, compiler, and optimization level; replace `std::isalnum` with explicit ASCII to remove locale dependence and prove it.
7. Differential test native vs the new `reference/` Python implementation over randomized inputs.
8. Clarify/obtain a license on C-engine OR reimplement from this spec before any public-repo use.

---

#### Classification

**reusable_after_generalization.** The deterministic authorization *mechanism* — overflow-checked integer arithmetic, an ordered short-circuit constraint evaluator with typed deterministic reason codes, and an atomic duplicate-action guard — is exactly what R1 §18 GAP-001 calls for and is cleanly separable from the trading domain (its only code dependency is a 2-value `Side` enum, trivially removable). It is pure, integer-only, deterministic, and platform-agnostic. However it cannot be lifted verbatim: (a) every type and reason code is trading-named and must be genericized into `native/arithmetic` + `native/constraints` + `native/integrity`; (b) existing tests establish essentially no correctness for the parts STRIX would rely on, so a full independent validation suite is mandatory; (c) licensing is UNKNOWN (no LICENSE in C-engine), so for a public STRIX repo a clean reimplementation from the documented algorithm is the safer path. Not "directly_reusable" (naming + IP), not "reference_only" (the algorithms genuinely transfer), not "requires_reimplementation" (the design is sound and portable).

---

## 2. Portfolio allocator

### Portfolio allocator

Audit of C-engine component "Portfolio allocator" for STRIX Milestone R1 native-numerics extraction. Baseline: C-engine `3a23b13`. Do NOT modify C-engine.

#### Actual source paths
- `risk/portfolio_allocator.hpp` (91 lines) — public API + `AllocationResult` struct.
- `risk/portfolio_allocator.cpp` (187 lines) — full implementation, namespace `trading::portfolio`.
- `bindings/portfolio_bindings.cpp` — pybind11 surface exposing all 6 functions as `_cengine_native.*`.
- `tests/test_portfolio_allocator_native.py` (114 lines) — parity + constraint tests via the native binding.
- `CMakeLists.txt:60` — `risk/portfolio_allocator.cpp` compiled into `cengine_core`.
- Consumers (context, not extraction targets): `cengine/portfolio_optimizer.py`, `cengine/certification/portfolio_cert.py`, `tools/portfolio_economic_comparison.py`.
- Covariance producer (upstream, separate component): `metal/covariance.metal`, `cengine/metal_covariance.py`.

#### Algorithm & math assumptions
Six pure functions, all `[[nodiscard]]`, no state, no I/O:
1. `marginal_variance(w, Σ, n)` → `Σw` (matrix-vector product, row-major n×n × n). cpp:31-49.
2. `portfolio_variance(w, Σ, n)` → `wᵀΣw` (quadratic form via `w · (Σw)`). cpp:51-64. Returns NaN on shape mismatch.
3. `risk_contributions(w, Σ, n)` → component risk `c_i = w_i·(Σw)_i / sqrt(wᵀΣw)`, with Σc_i = portfolio vol (Euler allocation). Zero-vol guard returns zero vector (never divides by 0). cpp:66-87.
4. `inverse_volatility_weights(variances)` → `w_i ∝ 1/sqrt(var_i)` normalized to sum 1; non-positive/non-finite variance → weight 0; all-invalid → all zeros. cpp:89-109.
5. `project_long_only_capped(raw, per_asset_cap, gross_cap)` → clamps negatives to 0 (long-only), caps each weight at `per_asset_cap`, proportionally scales down so `Σw ≤ gross_cap` (never scales up — residual stays "cash"), sets binding flags. cpp:111-157.
6. `allocate_risk_based(variances, Σ, n, caps)` → composition: inverse-vol → long-only projection → fills portfolio variance/vol/risk-contributions from Σ. cpp:159-184.
Assumptions: Σ is symmetric PSD covariance, row-major, length n·n; weights length n. No matrix inversion, no linear solve, no iterative optimizer — this is NOT a true constrained QP solver; it is a heuristic projection (inverse-vol + clamp + proportional rescale). Shape validation via `shapes_ok` (cpp:16-27). All finiteness-guarded.

#### Dependencies
STL only: `<vector>`, `<cmath>` (`std::sqrt`, `std::isfinite`), `<limits>`, `<cstdint>`, `<cstddef>`. No Eigen/BLAS/LAPACK, no external libs, no C-engine internal headers except its own hpp. Zero coupling to risk_engine/order path (header explicitly states: no order placement, no broker, no risk approval — advisory only). Binding layer adds pybind11 (`pybind11/stl.h`) — not part of the core numerics.

#### Existing tests (do they establish correctness for STRIX usage? NO by default)
`tests/test_portfolio_allocator_native.py` — 11 tests: numpy parity for `portfolio_variance`/`marginal_variance`/`risk_contributions` (atol 1e-6..1e-9), inverse-vol parity + zero-variance handling, long-only/cap/gross-binding semantics, invalid-caps-all-cash, assets=0 all-cash. Coverage is good for the happy path and the stated edge cases. NOT sufficient for STRIX: (a) tests run through the pybind layer, not the C++ unit directly; (b) covariance inputs are random well-conditioned float32 — no near-singular/ill-conditioned Σ, no large-n accumulation-error tests, no non-PSD Σ, no NaN/Inf propagation tests, no denormal/overflow; (c) no determinism/bit-reproducibility assertions across platforms; (d) float32 Σ upcast parity vs a float64 reference oracle is not bounded. STRIX must author independent C++-level tests against a double-precision reference.

#### Numerical precision
Σ stored/passed as `float32`, upcast to `double` on entry (cpp:43); all accumulation in `double`. Naive (non-pairwise, non-Kahan) summation in the n-loops — acceptable for small n, error grows ~O(n·eps) for large n. Zero-vol and negative-variance-under-sqrt guarded (`variance > 0.0 ? variance : 0.0`). Quiet-NaN returned on shape mismatch. No condition-number checks (no inversion, so less critical, but risk_contributions divides by portfolio vol).

#### Computational complexity
`marginal_variance`/`portfolio_variance`/`risk_contributions`: O(n²) time, O(n) extra space. `inverse_volatility_weights`/`project_long_only_capped`: O(n). `allocate_risk_based`: O(n²) dominated by the variance/contribution fills. Single-threaded, no SIMD, no blocking. Fine for small portfolios (n ~ tens to low hundreds); no GPU path in this file (covariance GPU kernel is a separate upstream component).

#### Thread-safety
Fully thread-safe: all functions are pure, no shared mutable state, no globals, inputs by const-ref, outputs by value. Safe to call concurrently on distinct arguments.

#### Platform requirements
C++20 (CMakeLists:4). Portable ISO C++ + STL only; no OS/arch/Apple/Metal dependency in this file (Metal in the repo is only the separate covariance kernel). Compiles anywhere with a C++20 toolchain.

#### IP ownership & licensing
No root LICENSE/COPYING file in C-engine (only `iex/LICENSE` for a vendored third-party dep, unrelated). Repo is the user's own proprietary C-engine. License: UNKNOWN (treat as all-rights-reserved proprietary, owned by the C-engine/STRIX owner = same party). Public-repo publishing not safe until an explicit license is assigned by the owner. No third-party code embedded in this file (STL only) — the algorithms (quadratic form, Euler risk contributions, inverse-vol weighting) are standard textbook finance/linear-algebra, not independently copyrightable, but the concrete implementation is owner IP.

#### Trading-specific assumptions that must NOT leak into STRIX
- Namespace `trading::portfolio`; directive refs §3/§7/§25, "Milestone 3".
- `AllocationResult` fields `gross_weight`, `cash_weight`, `per_asset_cap_binding`, `gross_cap_binding`, `portfolio_variance`, `portfolio_volatility` — portfolio/finance vocabulary.
- Long-only assumption (negatives clamped to 0) and "excess stays in cash / do not invent exposure" — a trading policy, not general numerics.
- "variance"/"volatility"/"covariance"/"risk contribution" naming — domain labels over generic quadratic-form / matrix-vector operations.
- float32 covariance input convention tied to the trading GPU/Metal covariance kernel's output format.
- Fallback-when-no-expected-returns policy (§7) is a trading decision rule.

#### Necessary generalizations
- Split pure linear algebra (quadratic form `xᵀAx`, matrix-vector `Ax`) from finance semantics: expose `quadratic_form`, `matvec` as generic primitives; keep "portfolio variance" as a thin finance-named wrapper outside the native core.
- Generalize `risk_contributions` as "Euler / gradient contribution of a quadratic form" (`x_i·(Ax)_i / sqrt(xᵀAx)`) — reusable for any quadratic objective decomposition.
- Parameterize scalar precision (template or dual float32/float64 entry) instead of hardcoded float32-in/double-accumulate.
- Make the projection (`project_long_only_capped`) a generic "simplex/box-capped L1-budget projection" with sign constraints as a parameter, not hardwired long-only.
- Replace naive summation with Kahan/pairwise for large-n robustness; add condition/PSD validation hooks.
- Rename namespace to STRIX, drop directive-section comments, remove "cash" concept from the generic core (express as budget residual).

#### Proposed STRIX integration (native/ layout)
- `native/matrices/` — `matvec` (row-major A·x) and `quadratic_form` (xᵀAx) as the reusable primitives underlying marginal_variance/portfolio_variance.
- `native/statistics/` — inverse-volatility / inverse-std weighting as a generic precision-weighting utility.
- `native/constraints/` — the long-only/box-cap/L1-budget projection generalized (sign + per-element cap + aggregate-budget projection with binding flags).
- `native/optimization/` — `allocate_risk_based` composition belongs here as a reference heuristic allocator (NOT a QP solver; R1 §6.5 true constrained/quadratic allocation would need a real solver — this is only the heuristic projection, flag the gap).
- `native/certification/` — risk-contribution decomposition (Σc_i == vol invariant) as a certifiable property.
- `backends/cpu` — direct port (scalar, portable). `backends/metal` — only the upstream covariance kernel is GPU; these O(n²) ops are optional Metal/SIMD candidates for large n, low priority.
- `bindings/` — re-expose via STRIX's own pybind surface (do not reuse `_cengine_native` naming).
- `reference/` — numpy/double-precision oracle for parity (quadratic form, matvec, Euler contributions, inverse-std, box/budget projection).

#### Independent validation requirements
- C++-level unit tests (not just via bindings) against a float64 reference oracle with bounded error for: ill-conditioned and near-singular Σ, large n (accumulation error), non-PSD Σ behavior, NaN/Inf propagation, denormals.
- Determinism / cross-platform bit-reproducibility assertions (R1 requires deterministic CPU parity).
- Verify Σc_i == portfolio vol invariant to tight tolerance across random PSD matrices.
- Verify projection invariants: Σw ≤ gross_cap, max w ≤ per_asset_cap, w ≥ 0, binding flags correct; property-based/fuzz testing.
- float32-in vs float64-in parity bound documented.
- Explicitly document that `allocate_risk_based` is a heuristic, not the R1 §6.5 constrained-QP solver.

#### Classification
**reusable_after_generalization.** Justification: the file is clean, self-contained (STL-only), thread-safe, portable C++20 with zero coupling to the trading execution/order/broker path (explicitly advisory). The core math (matrix-vector, quadratic form, Euler risk decomposition, inverse-std weighting, box/budget projection) is exactly the general-purpose numerics R1 §6.3 targets. It is NOT directly reusable because it is wrapped in trading vocabulary and policy (long-only, "cash", covariance/variance naming, directive refs, `trading::portfolio` namespace, float32-covariance convention) that must be stripped and the primitives split into `native/matrices`, `native/statistics`, `native/constraints`, `native/optimization`. The existing tests do not establish STRIX correctness. Note for R1 §6.5: this provides the heuristic constrained allocator and risk primitives but NOT a true quadratic-program solver — that remains a gap.

---

## 3. Volatility & freshness

### Volatility & freshness

**Audit baseline:** C-engine @ `3a23b13` (feature/m9-runtime-microstructure-execution-learning). STRIX @ `849018d`.

> **Headline finding:** Despite the directory name, `volatility/volatility.cpp` contains **no volatility computation and no EWMA/variance math**. It is a VIX/VXN *index-value ingestion book* plus **evidence-freshness and timestamp-skew validation** over a composite multi-source market snapshot. The R1 §6.2 "volatility/EWMA" need finds **nothing reusable** here; the R1 §10.2 "evidence freshness & timestamp-skew validation" need finds a **conceptually relevant reference pattern** (not drop-in code).

#### Actual source paths
- `volatility/volatility.cpp` (483 lines) — implementation.
- `volatility/volatility.hpp` (245 lines) — public types.
- Build wiring: `CMakeLists.txt:62` (`volatility/volatility.cpp` compiled into `cengine_core`).
- Dependency header: `orderbook/orderbook.hpp` (`MarketDataStatus` @ L86, `ObservedMarketSnapshot` @ L182-190, `OrderBookRegistry` @ L991).
- Sole consumer: `statArb/stat-arb.hpp:4` (`#include "volatility/volatility.hpp"`), `statArb/stat-arb.cpp`.
- No separate C++ unit-test file references these types (see Existing tests).

#### Algorithm & math assumptions
There is essentially **no numerical algorithm**. The logic is bookkeeping + predicate checks:
- `abs_diff(a,b)` (`volatility.cpp:11-18`): unsigned symmetric difference, overflow-safe (branch on `>=`).
- `market_timestamp(snapshot)` (L20-31): `max(last_quote_ts, last_trade_ts)`.
- `market_fresh(snapshot, now_ns, max_age_ns)` (L33-52): status must be `Valid`; rejects `timestamp==0` and **future timestamps** (`now_ns < timestamp`); accepts iff `now_ns - timestamp <= max_age_ns`.
- `VolatilityFactorState::age_ns(now_ns)` (L75-86): returns `UINT64_MAX` sentinel if `timestamp==0` or clock is behind; else `now_ns - timestamp`.
- `usable()` (L65-72): `Valid` status AND value present AND `age_ns <= max_age_ns`.
- `VolatilityFactorSnapshot::source_skew_ns()` (L118-130): `abs_diff(vix.ts, vxn.ts)`, sentinel if incomplete.
- `vxn_minus_vix_ticks()` (L104-115): integer subtraction of two tick values (a trading spread, not a statistic).
- `on_update()` monotonicity gate (L182-227): rejects updates with `timestamp_ns` older than stored, or non-increasing `sequence` (when both non-zero); increments accepted/rejected/out-of-sequence counters; bumps a global atomic `version_`.
- `StatArbMarketSnapshot::ready(policy)` (L396-440): composite AND of: captured_ns!=0, equity markets valid, factors valid, both equities fresh, factors fresh, equity_skew <= bound, factor source_skew <= bound, cross_asset_skew <= bound.
Assumptions: all timestamps are **nanoseconds, uint64, same monotonic clock domain**; values carried as **integer "ticks"** (fixed-point), never floats; "complete" factor set is hard-wired to exactly {VIX, VXN}.

#### Dependencies
- Standard library only: `<algorithm>`, `<limits>`, `<mutex>`, `<atomic>`, `<cstdint>`, `<optional>`, `<shared_mutex>`, `<string>`, `<string_view>`, `<unordered_map>`.
- **Hard coupling** to `orderbook/orderbook.hpp` for `ObservedMarketSnapshot`, `MarketDataStatus`, `OrderBookRegistry` (used by `StatArbMarketSnapshotBuilder`).
- Namespace `trading`. No third-party libs, no GPU/Metal, no network.

#### Existing tests (do NOT establish correctness for STRIX by default)
- **No C++ unit test exists** for `VolatilityFactorBook`, `market_fresh`, `source_skew_ns`, or `StatArbMarketSnapshot::ready`. Searches across `tests/` and all `*.cpp` test files returned zero references to these symbols.
- The `tests/` directory is Python (strategy/certification/portfolio), none exercising this translation unit.
- Conclusion: freshness/skew logic is **effectively untested**; even if tests existed they would validate trading-domain behavior, not STRIX's integrity semantics. STRIX must author independent tests from scratch.

#### Numerical precision
- Entirely **integer** (`std::uint64_t` for ns, `std::int64_t` for ticks). No floating point, so no rounding/catastrophic-cancellation concerns.
- Overflow safety: `abs_diff` avoids underflow; `age_ns`/`market_fresh` guard the `now < ts` case before subtracting. `UINT64_MAX` used as an explicit "unknown/invalid" sentinel — a convention STRIX must preserve or replace with `optional`.

#### Computational complexity
- All predicates O(1). `on_update`/`get` are O(1) hash lookups on a 2-entry map. `snapshot()` does 2 fixed lookups. `ready()` is a constant number of comparisons. No loops over data.

#### Thread-safety
- `VolatilityFactorBook` is explicitly concurrent: `mutable std::shared_mutex mutex_`, `unique_lock` on writes (`on_update`, `clear`), `shared_lock` on reads (`get`, `snapshot`). `std::atomic<uint64_t> version_` with acq/rel ordering (`on_update` L220-224, `version()` L124-128).
- Copy/assign deleted (L101-107). The free functions and the snapshot/state structs are plain value types (thread-safe by immutability once produced).

#### Platform requirements
- Portable C++17 (shared_mutex, string_view, optional, inline atomics). No OS/arch/Metal dependency. Builds on any conforming toolchain.

#### IP ownership & licensing
- **No LICENSE/COPYING file** found at C-engine root. README identifies it as a proprietary internal trading engine. Default posture: **proprietary, all rights reserved; owner = the C-engine/STRIX project owner (user).** Since both repos are owned by the same party, relicensing into STRIX-native is an owner decision, not a third-party blocker. Not safe to assume open-source terms.

#### Trading-specific assumptions that must NOT leak into STRIX
- Symbol whitelist hard-coded to `"VIX"`/`"VXN"` (`supported()` L133-138) and the "complete = VIX+VXN" rule.
- Value semantics as **price "ticks"** and `vxn_minus_vix_ticks` (a vol-spread signal).
- `MarketDataStatus::Valid`, `ObservedMarketSnapshot`, quote/trade timestamps, `OrderBookRegistry`, QQQ/SQQQ equity legs, `StatArbSnapshotPolicy` default bounds (1s/2s equity/factor age, 250ms/500ms/1s skews) — all execution-domain.
- `sequence`/`provider` fields model a market-data feed; the monotonic-timestamp + sequence gate is a feed de-dup/replay guard, not a general integrity primitive.
- Namespace `trading`, and the entire `StatArb*` composite layer.

#### Necessary generalizations
To serve R1 §10.2 STRIX needs the *shape*, not the trading specifics:
- Replace fixed {VIX,VXN} with a generic N-source evidence set keyed by an opaque source id.
- Replace tick/price value types with a generic payload/value parameter (or leave values out of the integrity layer entirely).
- Keep and generalize the **freshness predicate** (`now - ts <= max_age`, with future-timestamp rejection) and the **pairwise/multi-source skew** (`max abs_diff over source timestamps`) as pure, dependency-free functions over `(timestamp_ns, now_ns, bounds)`.
- Replace `UINT64_MAX` sentinels with `std::optional`/typed results for STRIX clarity.
- Drop `orderbook.hpp` coupling; the integrity functions should take plain timestamp tuples.
- Monotonicity/sequence gate → generalize into an optional "ordered-ingest guard" but treat as separate from freshness.

#### Proposed STRIX integration (native/ layout)
- Primary target: **`native/integrity/`** — evidence freshness, timestamp-skew validation, and ingest monotonicity guards (maps directly to R1 §10.2). Pure integer functions: `is_fresh(ts, now, max_age)`, `skew(ts_a, ts_b)`, `max_skew(span)`, `reject_future_or_zero`.
- Secondary: a thin **`native/timeseries/`** touchpoint only if STRIX wants the "composite snapshot readiness" aggregation pattern; otherwise keep it in the consuming layer.
- Backend: **`backends/cpu`** only (scalar, O(1)); no `metal` kernel warranted.
- **bindings**: expose freshness/skew to Python (STRIX §10.2 evidence validation path).
- **reference**: pure-Python/NumPy reference for the freshness+skew predicates to anchor cross-impl tests.
- **Not** `statistics`/`arithmetic`/`optimization` — there is no actual statistic or EWMA to extract. R1 §6.2 EWMA must be sourced/implemented elsewhere (greenfield in `native/statistics/`), not from this file.

#### Independent validation requirements
- Author fresh unit tests (none inherited): boundary cases at `age == max_age`, `age == max_age+1`, `ts == 0`, `now < ts` (clock skew / future ts), `UINT64_MAX` sentinel behavior, multi-source skew with 2 and N sources.
- Property tests: `abs_diff` symmetry & no-underflow; freshness monotonic in `now`.
- Concurrency tests if the stateful book pattern is ported (shared_mutex reader/writer, atomic version ordering).
- Cross-check CPU vs Python reference for identical bool/int outputs.
- Confirm clock-domain assumption (single monotonic ns source) holds in STRIX before reuse.

#### Classification
**reference_only.** Justification: (1) The file delivers none of R1 §6.2's volatility/EWMA math — that need is unmet here and must be built greenfield. (2) The §10.2-relevant freshness/skew logic is genuinely useful but is (a) trivial O(1) integer predicates, (b) deeply entangled with trading types (VIX/VXN whitelist, ticks, `orderbook.hpp`, `StatArb` policy), and (c) completely untested. The cheapest, cleanest path is to reimplement the handful of predicates natively in `native/integrity/` using this file as a design reference, rather than lift-and-generalize coupled code.

---

## 4. Statistical features & time-series

### Statistical features & time-series

Audit of C-engine's `FeatureEngine` numerics for STRIX R1 (§6.1/§6.2 descriptive statistics, growth/CAGR, moving/rolling stats, autocorrelation, trend, anomaly). C-engine baseline `3a23b13`, STRIX baseline `849018d`. Do NOT modify C-engine.

#### Actual source paths
- `analytics/features.cpp` (1595 lines) — `trading::analytics::FeatureEngine` CPU reference implementation.
- `analytics/features.hpp` (782 lines) — types (`Bar`, `MarketSample`, `DepthSample`, `FeatureConfig`, `L1Features`, `L2Features`, `TechnicalFeatures`, `FeatureVector`, `GpuFeatureRow`, `GpuDepthBatch`, `FeatureBatch`), `FeatureEngine`, `BookFeatureAdapter`, and the as-yet-unimplemented `MetalFeatureEngine` contract.
- Build wiring: `CMakeLists.txt:56` compiles `analytics/features.cpp` into the `cengine_core` STATIC library. No test target, no `enable_testing()`/`add_test` anywhere in `CMakeLists.txt`.
- Header dependency: `analytics/features.hpp:3` `#include "orderbook/orderbook.hpp"` (for `BookSnapshot` used only by `BookFeatureAdapter`).
- NOTE: the general-statistics routines of interest to R1 live only in this file. A SEPARATE, unrelated implementation `cpu_ref::technical_features` (in `opportunity_discovery/cpu_reference.cpp`) is what the Python bindings expose (`bindings/discovery_bindings.cpp:218` `technical_features_cpu`); `FeatureEngine` itself is NOT bound to Python and NOT referenced outside `analytics/`.

#### Algorithm & math assumptions
R1-relevant general numerics present in `features.cpp`:
- SMA (`sma`, L791): trailing-window arithmetic mean of `close` over `period`; double accumulator; NaN if `size < period`.
- EMA (`ema`, L818; `ema_values`, L851): seeds with SMA of first `period` samples, then recursion `v = alpha*x + (1-alpha)*v`, `alpha = 2/(period+1)`. `ema_values` propagates NaN if any input is non-finite.
- Rolling std / realized volatility (`realized_volatility`, L1110): sample standard deviation (Bessel `period-1` denominator) of log-returns over the window; requires `period >= 2` and `size >= period+1`; NaN on non-positive prices; clamps variance to >=0 before sqrt. This is the generalizable rolling-std / dispersion kernel.
- Returns: `simple_return` (L1218) `current/prev - 1`; `log_return` (L1239) `ln(current/prev)`. These are the growth primitives; CAGR/compound-growth is NOT implemented (would be a generalization).
- ROC (`roc`, L972): percentage change over `period` lag — a lagged growth-rate statistic.
- RSI (`rsi`, L893) and `rsi_series` (L1339): Wilder smoothed average gain/loss; edge conventions (all-gain -> 100, all-loss -> 0, flat -> 50).
- MACD (`macd_line` L1270, `macd_signal` L1300, `macd_series` L1442): EMA differences; `macd_series` recomputes EMA per prefix window (O(n^2), intentionally kept identical to `macd_line` as a "Metal oracle", see comment L1464-1466).
- CCI (`cci`, L1001), Stochastic RSI (`stoch_rsi`, L1055), VWAP (`vwap`, L1175): typical-price `(H+L+C)/3` based; domain-specific but built on mean/min-max/weighted-mean primitives.
- Trend: only implicit via MA crossovers / MACD; NO explicit linear-regression slope/OLS trend estimator. Autocorrelation: NOT present. Anomaly detection: NOT present (only validity gating). These three R1 items require net-new implementation.
- Min/max rolling reduction appears inline in `stoch_rsi` (L1078-1091) — a reusable rolling-extrema primitive.

#### Dependencies
- Standard library only: `<algorithm>`, `<cmath>`, `<limits>`, `<stdexcept>`, `<utility>`, `<span>`, `<vector>`, `<optional>`, `<cstdint>`. No third-party math/BLAS libraries.
- Intra-repo coupling: `features.hpp` pulls in `orderbook/orderbook.hpp` for `BookSnapshot`. This coupling is confined to `BookFeatureAdapter`; the pure statistical helpers (SMA/EMA/std/returns/ROC/RSI/MACD) have NO orderbook dependency and operate on `std::span<const Bar>` or `std::span<const float>`.
- `Bar` is a plain POD (`timestamp_ns`, OHLC floats, volume) — easy to generalize to a timestamp+value series.

#### Existing tests (do they establish correctness for STRIX usage? NO)
- There are NO C++ unit tests for `FeatureEngine`. No `tests/*.cpp`, no gtest/catch target in `CMakeLists.txt`, `enable_testing()`/`add_test` absent.
- `tests/test_confirmation_features.py` and `tests/test_portfolio_analytics.py` exercise Python code (`cengine.gpu_discovery._confirmation_features`, portfolio analytics), NOT `analytics/features.cpp`.
- The Python-bound `technical_features_cpu` maps to a DIFFERENT implementation (`opportunity_discovery/cpu_reference.cpp`), so even indirect coverage of this file is absent.
- Conclusion: zero test coverage establishing correctness. STRIX cannot rely on any existing test; every extracted routine needs fresh reference-validated tests.

#### Numerical precision
- Public API returns `float` (single precision); internal accumulation is `double` for SMA/EMA/RSI/variance/VWAP (good practice), then narrowed to float on return — lossy final cast.
- `kNaN`/`quiet_nan()` sentinel used for insufficient-data / invalid conditions; callers must NaN-check.
- Variance uses two-pass mean-then-deviation (numerically stable), clamped to >=0 before sqrt.
- `float` output precision (~7 significant digits) is INSUFFICIENT for STRIX's statistics tier where double is expected; generalization should template on `T`/return double.

#### Computational complexity
- SMA/EMA/RSI/ROC/CCI/VWAP/returns/volatility: O(n) or O(period), single pass.
- `rsi_series`: O(n). `macd_series`: O(n^2) because EMA is recomputed per prefix (deliberate oracle fidelity, L1464-1466) — a performance trap if reused as-is at scale; STRIX must replace with an incremental O(n) streaming EMA.
- `stoch_rsi` builds a full `rsi_series` then scans last `stoch_period` — O(n).

#### Thread-safety
- `FeatureEngine` holds only immutable `config_` after construction; all compute methods are `const` and the numeric helpers are `static`. No shared mutable state, no globals. => Safe for concurrent read-only use across threads on distinct inputs. Each call allocates its own output / temporary `std::vector` (in `*_series`).

#### Platform requirements
- Portable ISO C++20 (uses `std::span`, `std::span::first`, designated struct init). Compiles under the repo's strict-warning C++ TUs (CMake note L? "Strict warnings for C++ TUs").
- No Metal/Apple dependency in the CPU path; `MetalFeatureEngine` is a declared-but-unimplemented contract (header only) — not part of this component's shippable numerics.
- Requires a C++20 toolchain; no OS-specific calls.

#### IP ownership & licensing
- Author (git): `Asmaa Abdul-Amin <contact@blkpvnthr.com>`, first/only commit of file Sep 2026 — the same principal who owns STRIX (`contact@quantumquant.trade`). IP owner = project owner (STRIX / Quantum Quant).
- NO license file in repo (`LICENSE*`/`COPYING*` absent), no SPDX/copyright header in `features.cpp`/`features.hpp`, no `license` field in `pyproject.toml`. License status is UNKNOWN/unstated = treat as all-rights-reserved proprietary, owned by the STRIX principal.
- Because owner == STRIX owner, relicensing/relocation into STRIX is an internal decision; a clear SPDX header should be added at extraction time.

#### Trading-specific assumptions that must NOT leak into STRIX
- `namespace trading::analytics` and the whole `Bar`/OHLCV/`MarketSample`/`DepthSample`/microstructure vocabulary.
- OHLCV semantics: `Bar::valid()` enforces `high>=low`, positive prices, `open/high/low/close>0` — domain constraints inappropriate for generic series.
- `typical_price = (H+L+C)/3`, VWAP, microprice, depth imbalance, spread_bps, liquidity pressure — all market-microstructure, out of scope for R1 general statistics.
- "Metal oracle" / `GpuFeatureRow` / `GpuDepthBatch` flattening is a GPU-handoff concern, not a statistics concept.
- `float`-only outputs and the fixed `FeatureConfig` indicator periods (RSI 14, MACD 12/26/9, etc.) are trading presets, not general config.
- Timestamp monotonicity check (`bars_valid`) assumes strictly increasing `timestamp_ns` tick bars.

#### Necessary generalizations
- Strip to value-series primitives operating on `std::span<const double>` (plus optional `timestamps`), decoupled from `Bar`/orderbook; move accumulation and return type to `double`.
- Extract reusable kernels: rolling mean (SMA), EWMA (streaming O(1) update), rolling sample/population std & variance, simple/log returns, lagged ROC, rolling min/max extrema, and a generic weighted mean.
- ADD missing R1 items absent here: CAGR/compound growth, autocorrelation (ACF at lag k), linear-trend/OLS slope & R^2, and anomaly flags (e.g. rolling z-score / MAD). These are NEW, not ports.
- Replace O(n^2) `macd_series` pattern with incremental streaming computation.
- Parameterize NaN/insufficient-data policy; expose explicit min-sample requirements rather than silent NaN.
- Remove all domain validation (OHLC relationships, positive-price gates) or make it opt-in policy.

#### Proposed STRIX integration (native/ layout)
- `native/statistics/` : descriptive stats (mean/variance/std/skew/kurtosis), weighted mean, rolling std/variance kernels (from `realized_volatility`, `sma`). PRIMARY target.
- `native/timeseries/` : moving/rolling windows (SMA), EWMA/EMA (from `ema`/`ema_values`), returns & ROC & CAGR/growth (from `simple_return`/`log_return`/`roc`), autocorrelation (NEW), trend/OLS slope (NEW), rolling extrema (from `stoch_rsi` min/max), anomaly z-score (NEW). SECONDARY/CO-PRIMARY target.
- `native/arithmetic/` : safe-ratio / finite-guard helpers (from `safe_ratio`, `finite`).
- `native/integrity/` : input-validation policy (finiteness, min-sample, monotonic-timestamp) refactored as generic, opt-in checks.
- `native/backends/cpu/` : these double-precision reference kernels become the CPU reference/oracle.
- `native/backends/metal/` : future parallel backend; the existing "CPU is the oracle" discipline (header L480-507) transfers directly, but NO Metal code exists yet to port.
- `native/reference/` : golden fixtures for cross-validating CPU vs. future Metal.
- `native/bindings/` : Python bindings for the extracted statistics (none exist for this file today).
- NOT applicable here: `native/matrices/`, `native/constraints/`, `native/optimization/`, `native/certification/` (no linear algebra, solvers, or cert logic in this component).

#### Independent validation requirements
- Reimplement in STRIX as double-precision; do NOT copy `float` returns.
- Validate each kernel against an independent reference: SMA/std/returns vs. NumPy/pandas; EMA vs. pandas `ewm(span=...).mean()` (note C-engine seeds EMA with an SMA of the first `period`, differing from pandas default adjust=True — must document/choose a convention explicitly).
- Property tests: NaN propagation, insufficient-sample behavior, variance clamp, min/max extrema ties.
- RSI/MACD are NOT R1 statistics deliverables; if reused, validate against TA-Lib, but they are domain indicators and should likely stay out of the general `native/` statistics surface.
- Since there are zero existing tests, treat correctness as unestablished and build a full golden-vector suite.

#### Classification
`reusable_after_generalization`. Justification: the core descriptive/rolling/EWMA/returns/variance math is sound, STL-only, header-light, and thread-safe, and is owned by the STRIX principal (no third-party license risk). But it is single-precision, wrapped in `trading::analytics` with heavy OHLCV/microstructure coupling, has ZERO tests, uses an O(n^2) series pattern, and is MISSING three R1 items (CAGR, autocorrelation, trend/OLS, anomaly). It cannot be lifted as-is; it must be re-expressed as double-precision, series-generic kernels under `native/statistics` + `native/timeseries`, with net-new routines added and a fresh reference-validated test suite.

---

## 5. Metal covariance/EWMA/regression kernels

### Metal covariance/EWMA/regression kernels

**Audit target (R1 §8 accelerated covariance/EWMA/regression GPU kernels; §8.3 CPU/GPU parity).** C-engine pinned baseline 3a23b13.

#### Actual source paths
- `metal/covariance.metal` (1027 lines) — the Metal Shading Language kernels (namespace `gme`). PRIMARY target.
- `cengine/metal_covariance.py` (74 lines) — Python host interface `MetalCovariance` for `column_means` + `covariance_matrix` + `ewma_covariance_matrix` only (StatArb/volatility kernels are NOT wired here).
- `cengine/metal_cpu_ref.py` (lines 61-110) — CPU float oracle: `column_means`, `covariance_matrix`, `ewma_covariance_matrix`. (StatArb/volatility/weights kernels have NO CPU reference.)
- `cengine/metal_backend.py` (lines 96-160) — kernel registry entries; marks StatArb/volatility/normalized_weights as `host_interface=None`, `cpu_reference=None`, "research-only, not yet wired".
- Native C++/ObjC runtime: `cengine/metal_runtime` (pybind11), compiled artifact `build-metal/covariance.air` → `cengine.metallib`.
- Tests: `tests/test_metal_hardware.py` (83-109), `tests/test_native_metal_runtime.py` (106-128), `tests/test_metal_portfolio_consumer.py`.
- Build: `build-metal/CMakeCache.txt` (CMake, `CENGINE_COMPILE_METAL=ON`).

#### Algorithm & math assumptions
Eight kernels, all one-thread-per-output-element, no parallel reductions (deterministic parity-first):
1. `column_means` — one thread/asset; arithmetic mean over observations; NaN-propagating. Input obs×assets row-major with `row_stride`.
2. `covariance_matrix` — one thread/cell (i,j); sample covariance, divisor `(obs-1)` (Bessel); requires precomputed means buffer; obs<2 → NaN.
3. `ewma_covariance_matrix` — one thread/cell; exponential weights newest=1, older=λ,λ²,…, normalized by weight sum (divisor = weight_sum, NOT weight_sum-1, i.e. biased EWMA); computes weighted means internally; diagonal floored at `minimum_variance`; requires 0<λ≤1.
4. `statarb_pair_regression` — one thread/window; OLS y=α+βx (QQQ/SQQQ returns); computes β=Sxy/Sxx, α, Pearson correlation, residual mean/std (divisor n-1), latest residual z-score, validity gate on min correlation.
5. `statarb_residual_series` — one thread/(window,sample); full residual vector from regression output.
6. `volatility_factor_features` — one thread/window; VIX/VXN levels, changes, z-scores, VXN-VIX spread stats (requires strictly positive inputs).
7. `statarb_normalized_weights` — pure weight transform (dependent=±1, hedge=∓β), gross-normalized to |w_y|+|w_x|=1.
8. Helpers: `safe_sqrt` (clamps negatives to 0), `finite_value` (isfinite), `kEpsilon=1e-12`.
Assumptions: finite inputs (NaN → NaN/early-out); contiguous float32 row-major; host ABI structs must byte-mirror Metal structs; CPU/C++ is the correctness oracle and sole execution authority.

#### Dependencies
- `metal_stdlib` (Apple Metal); float2 type; `isfinite/sqrt/max/fabs`.
- Host: `cengine.metal_backend.MetalBackend` → `MetalRuntime`/`MetalBuffers` (pybind11 native ObjC++ runtime), `cengine.metallib`.
- Python stdlib `struct` for ABI packing. No third-party numerics in the kernel path. Tests use numpy-free pure-Python CPU reference.

#### Existing tests (do they establish correctness for STRIX usage? NO by default)
- `test_covariance_matrix_gpu_cpu_parity` and `test_ewma_covariance_gpu_cpu_parity` (test_metal_hardware.py): single 6×3 hardcoded returns matrix, tolerance <1e-6; symmetry check. Hardware-gated (skipped if no Metal).
- `test_native_metal_runtime.py`: random 24×5 Gaussian matrix, covariance + EWMA parity tol <1e-4; `has_kernel` presence checks.
- `test_metal_portfolio_consumer.py`: end-to-end optimizer consumes GPU covariance.
- GAPS for STRIX: only 2 kernels (covariance, EWMA) tested; `statarb_pair_regression`, `statarb_residual_series`, `volatility_factor_features`, `statarb_normalized_weights`, `column_means` (indirectly) have NO dedicated parity tests and NO CPU reference. No edge cases (NaN, zero variance, singular, large N, condition number, negative-definite detection). Tiny fixed universes; no property/fuzz tests. Tests establish smoke-level parity only, NOT correctness for STRIX production use.

#### Numerical precision
- GPU path is float32 throughout; CPU reference is Python float (float64). Parity tolerances 1e-6 (small inputs) / 1e-4 (random). Naive two-pass sum-of-products accumulation — susceptible to catastrophic cancellation / precision loss for large N or large-magnitude / poorly-centered data (no Welford/Kahan/compensated summation). EWMA uses biased normalization (÷weight_sum). float32 covariance will NOT meet STRIX tight determinism/precision requirements without validation; README itself notes GPU is "not yet faster than numpy BLAS".

#### Computational complexity
- `covariance_matrix`: O(assets²·obs) work, assets² threads each O(obs) — no reduction sharing (redundant mean reuse acceptable). `ewma`: two passes O(obs) per cell. `statarb_pair_regression`: O(n) per window, four sequential passes. One-thread-per-cell is correctness-first, not throughput-optimal (README: slower than BLAS at tested sizes; GPU disabled below unreached crossover).

#### Thread-safety
- Kernels are embarrassingly parallel, each thread writes a disjoint output element; no inter-thread shared/atomic state → data-race-free by construction. `covariance_matrix` requires `means` buffer fully populated first (host enforces ordering via separate dispatch). Host `MetalBackend` dispatch ordering is the serialization point.

#### Platform requirements
- Apple Metal GPU (macOS / Apple Silicon). Requires Metal toolchain (xcrun) + CMake (`CENGINE_COMPILE_METAL=ON`) to compile `.metal`→`.air`→`.metallib`. NOT portable to CUDA/ROCm/CPU-SIMD without rewrite. Host degrades gracefully to CPU when Metal unavailable (`backend.available==False`).

#### IP ownership & licensing
- No LICENSE/COPYING file in C-engine repo root. README has no explicit license/SPDX header; `covariance.metal` has no license header. Default: all-rights-reserved, owner = C-engine author (Asmaa Abdul-Amin / repo owner). Treat as proprietary/UNKNOWN until owner confirms. Same owner expected to own STRIX, so internal reuse is plausibly permitted but must be explicitly confirmed before any public-repo use.

#### Trading-specific assumptions that must NOT leak into STRIX
- QQQ/SQQQ pair semantics, "StatArb", α/β pair regression framed as leveraged-ETF arbitrage (comments reference -1/3, -3 leverage).
- VIX/VXN volatility-factor kernel (`volatility_factor_features`) and its ABI are trading-specific.
- `statarb_normalized_weights` encodes long/short residual position weighting and "PairRiskGate"/order-translation comments.
- Status enum `StatArbStatus`, field names (`zscore`, `latest_y_return`, `residual`, `hedge`, `beta`) carry trading intent.
- "minimum_abs_correlation" validity gate, residual z-score signal logic — these are strategy heuristics, not general statistics.
- The "CPU is execution authority / no order placement" framing is a trading-engine contract irrelevant to STRIX.

#### Necessary generalizations
- Rename/strip to pure linear algebra: covariance(X), EWMA-covariance(X,λ), OLS-regression(X,y) returning (coef, intercept, R², residuals, std-errors) — drop StatArb/VIX/pair/weight kernels (reference-only).
- Add numerically stable accumulation (Welford/pairwise/Kahan), optional float64 path, configurable ddof (population vs sample, biased vs unbiased EWMA).
- Replace hardcoded ABI structs with STRIX typed payloads; decouple from `gme`/Metal-only; add CPU reference backend as first-class, not just test oracle.
- Generalize NaN policy (propagate vs skip vs error) and condition-number / positive-semidefinite diagnostics for covariance.

#### Proposed STRIX integration (native/ layout)
- `native/statistics/` — covariance (sample + EWMA), column means, Pearson correlation. PRIMARY home.
- `native/matrices/` — covariance matrix storage, symmetry/PSD helpers.
- `native/timeseries/` — EWMA weighting (newest=1,λ,λ²), rolling-window machinery.
- `native/optimization/` or `native/statistics/regression/` — OLS linear regression (α/β, residuals, R²).
- `backends/cpu/` — port `metal_cpu_ref` as the authoritative stable-accumulation reference.
- `backends/metal/` — port covariance + EWMA kernels (the two parity-validated ones) behind the CPU/GPU parity contract (§8.3).
- `bindings/` — typed Python/host ABI replacing struct-packed params.
- `reference/` — CPU oracle + golden fixtures; `integrity/` for CPU/GPU parity assertions; `certification/` for parity evidence.
- Exclude from native/: StatArb pair regression, residual series, volatility factor, normalized weights (trading-specific → reference_only).

#### Independent validation requirements
- CPU/GPU parity (§8.3) across float32 and float64, many universe sizes (2..1000+ assets), long windows, tolerance-bounded with documented float32 error envelope.
- Correctness vs numpy/BLAS covariance and sklearn/statsmodels regression on broad random + pathological inputs (near-singular, constant columns, large magnitude, NaN/Inf, negative-definite).
- Numerical-stability tests (catastrophic cancellation) proving stable-accumulation generalization.
- EWMA bias/normalization documented and tested against a reference.
- Property/fuzz tests (symmetry, PSD, scale/shift invariance); determinism across runs/thread-counts.
- Performance crossover measurement (GPU vs BLAS) before enabling GPU path.

#### Classification (justification)
- **reusable_after_generalization.** The two parity-validated general kernels (`covariance_matrix`, `ewma_covariance_matrix`) + `column_means` are genuinely general numerics with a working CPU oracle and a CPU/GPU parity harness directly serving R1 §8/§8.3 — strong reuse value. But they ship as float32 naive-accumulation, Metal-only, with trading-coupled file/namespace/ABI, no LICENSE, and the regression/volatility/weight kernels are trading-specific and untested (those are reference_only). Reuse requires: strip trading semantics, add stable/float64 numerics, decouple from `gme`/Metal ABI, confirm licensing, and build independent validation. Not directly_reusable (precision + coupling + licensing gaps); not requires_reimplementation (math + parity harness are sound starting points).

---

## 6. Obj-C++ Metal runtime + CPU reference

### Obj-C++ Metal runtime + CPU reference

Component for Milestone R1 extraction audit: the single native Objective-C++ Metal
compute runtime and its matching CPU reference/parity oracle in C-engine's
`opportunity_discovery/` layer. Audited at C-engine pinned baseline `3a23b13`
(branch `feature/m9-runtime-microstructure-execution-learning`). **No modification
to C-engine was made.**

#### Actual source paths

Both specified paths exist exactly as given (relative to C-engine root):

- `opportunity_discovery/metal_runtime.mm` (625 lines) — Obj-C++ Metal runtime implementation.
- `opportunity_discovery/cpu_reference.hpp` (83 lines) — CPU oracle declarations.

Tightly-coupled files that MUST be read/extracted together (they form one unit):

- `opportunity_discovery/metal_runtime.hpp` (168 lines) — pure-C++ PIMPL interface (`MetalRuntime`, `MetalError`).
- `opportunity_discovery/cpu_reference.cpp` (464 lines) — CPU oracle implementation (the actual math).
- `opportunity_discovery/metal_buffers.hpp` (77 lines) / `opportunity_discovery/metal_buffers.mm` (132 lines) — persistent shared-storage buffer pool (`BufferPool`, `GpuBuffer`); the runtime depends on it directly.
- `opportunity_discovery/screening_types.hpp` (291 lines) — all POD contracts (`RuntimeTelemetry`, `GpuBuffer` consumers, `ScreeningInput/Output`, `TechFeatures`, `RankInput/Output`, `BreadthCounters`, enums).

Build wiring: `CMakeLists.txt` lines 17-50 (Metal toolchain detection, `CENGINE_COMPILE_METAL`/`CENGINE_METAL_ENABLED`), 55-81 (`cengine_core` static lib; `.mm` files only appended when `CENGINE_METAL_ENABLED`), 106-136 (shader compile: `xcrun metal -c` → `.air` → `xcrun metallib` → `cengine.metallib`). The `.metal` kernel sources themselves (e.g. `metal/indicators.metal`, `metal/covariance.metal`, `metal/monte-carlo.metal`) are a SEPARATE component and are NOT part of this fragment, but the runtime loads them at runtime from a `.metallib` path.

#### Algorithm & math assumptions

Two layers:

1. **Runtime/infrastructure (metal_runtime.mm, metal_buffers.mm)** — no numerical algorithm of its own; it is a GPU dispatch harness:
   - One `MTLDevice` (`MTLCreateSystemDefaultDevice`), one `MTLCommandQueue`, one loaded `MTLLibrary`, an `unordered_map` pipeline cache keyed by resolved kernel name (metal_runtime.mm:28-49).
   - Namespace-aware kernel resolution: tries bare name, then `"gme::"+name` (`Impl::resolve`, lines 43-48).
   - Generic 1-D dispatch (`dispatch`, lines 151-237): binds buffers at indices 0..n-1, computes threadgroup width as `min(grid_size, maxTotalThreadsPerThreadgroup)`, `dispatchThreads` (non-uniform threadgroups), installs a real `addCompletedHandler` that records GPU time (`GPUEndTime-GPUStartTime`), completions, failures, then blocks on a `dispatch_semaphore` to make the call synchronous/deterministic for parity.
   - `create()` NEVER throws on "Metal unavailable" — returns an object with `available()==false` + `reason()` (lines 63-104) so callers fall back to CPU.
   - BufferPool: best-fit size-class reuse of `MTLResourceStorageModeShared` buffers (metal_buffers.mm:42-77); on Apple-Silicon unified memory the same allocation is host- and GPU-visible with no copy.

2. **The numeric kernels wrapped + the CPU oracle (cpu_reference.cpp)** — the actual math, mostly generic:
   - `trunc_div` (cpu_reference.cpp:13-19): signed integer division truncating toward zero, to match Metal `long /`.
   - `sma_ticks`: integer rolling mean over `window`, truncating division. `ema_ticks`: integer recurrence `out[i]=trunc_div(num*p[i]+(den-num)*out[i-1], den)`, seeded `out[0]=prices[0]`. `apo_ticks`: elementwise `fast-slow`. `true_range_ticks`: `max(h-l, |h-prevClose|, |l-prevClose|)`.
   - `column_means`/`covariance_matrix`: population mean (double accum), sample covariance divided by `(observations-1)`; `<2 obs` → NaN matrix. `ewma_covariance_matrix`: exponentially-weighted mean & covariance with decay `lambda∈(0,1]`, newest weight 1.
   - `technical_features` (cpu_reference.cpp:236-363): Wilder DMI/ADX/ATR (sum-form smoothing), SMA, Bollinger bands (population stddev, ±2σ), session VWAP (typical-price·volume).
   - `screen_market` (161-234), `market_breadth` (365-384), `compact_entry_candidates` (386-398), `rank_scores` (407-461): trading screening/ranking logic (NOT generic — see leakage section).

Key assumption: the CPU oracle and GPU kernel are written to agree bit-for-bit (integer) or within float32 tolerance; "parity" means GPU==CPU, NOT that either is independently correct.

#### Dependencies

- System frameworks: `<Metal/Metal.h>`, `<Foundation/Foundation.h>` (Apple only). Obj-C runtime (manual retain/release — compiled WITHOUT ARC).
- `libdispatch` (`dispatch_semaphore_t`).
- C++20 stdlib only: `<algorithm> <cstring> <mutex> <unordered_map> <utility> <vector> <memory> <cmath> <cstdint> <cstdlib>`.
- Internal headers: `metal_runtime.hpp`, `metal_buffers.hpp`, `screening_types.hpp`, `cpu_reference.hpp`. No third-party libs.
- cpu_reference.cpp (pure C++) has NO Metal/Obj-C dependency — compiles & runs on any platform.

#### Existing tests (do they establish correctness for STRIX? NO)

- `tests/test_native_metal_runtime.py` (439 lines) — Python, via pybind11 `_cengine_native`. Guarded `skipif` macOS+arm64+Metal-built (lines 23-27); **skips entirely off Apple-Silicon hardware**. Tests: init/device name, 50 entry points present, namespace resolution, SMA/EMA/APO/TR exact integer parity vs `cengine.metal_cpu_ref` (Python), covariance/EWMA within `1e-4`, telemetry, pipeline cache, buffer reuse, registry coverage.
- `tests/test_metal_hardware.py` (109 lines), `tests/test_gpu_discovery.py`, `tests/test_metal_portfolio_consumer.py` — also hardware-gated.
- **No pure-C++/CTest unit tests** for `cpu_reference.cpp`; it is exercised only indirectly through the Python bindings on hardware.
- These tests establish GPU==CPU-oracle AND oracle==legacy-PyObjC Python reference. They do NOT establish: (a) independent numerical correctness of the math for STRIX, (b) any coverage off Apple Silicon, (c) any CPU-path unit test runnable in STRIX CI. For STRIX, correctness must be re-established from scratch with independent oracles.

#### Numerical precision

- Integer indicators (sma/ema/apo/true_range): exact `int64`, truncating-toward-zero division — bit-reproducible, platform-independent.
- Covariance/means: `double` accumulation, `float` stored result; parity tolerance `1e-4` in tests.
- technical_features/rank/screen: `float32` throughout (matches GPU); order-of-operations sensitive (Wilder smoothing, VWAP sums). NaN sentinels for invalid inputs.
- GPU float results depend on Metal's fp rounding; "strict parity" is only as strict as the `1e-4` tolerance for floats and exact for ints.

#### Computational complexity

- Runtime harness: O(1) device/queue setup; pipeline build amortized O(1) via cache; dispatch O(grid) on GPU + O(buffers) binding; synchronous (one semaphore wait per dispatch — serializes, kills GPU pipelining).
- sma_ticks: O(n·window) (naive, not sliding-window). ema/apo/true_range: O(n). column_means: O(obs·assets). covariance: O(assets²·obs). ewma_covariance: O(assets²·obs). technical_features: O(symbols·window). BufferPool.acquire: O(free_buffers) best-fit linear scan.

#### Thread-safety

- `MetalRuntime`: a single `std::mutex impl_->mtx` guards the pipeline cache + telemetry (metal_runtime.mm:39). Dispatch is made synchronous via semaphore. Mutable `ok` is captured by `__block` in the completion handler — safe only because the semaphore serializes. Copy/assign deleted.
- `BufferPool`: **NOT thread-safe** — no internal lock on `free_buffers`/`live` (metal_buffers.mm). Concurrent acquire/release would corrupt. The runtime does not lock around pool use inside its high-level methods, so concurrent high-level calls on one runtime are unsafe despite the mutex.
- cpu_reference.cpp functions: pure/stateless → reentrant & thread-safe.

#### Platform requirements

- Runtime (`.mm` files): macOS + Apple Metal framework; Apple Silicon assumed (unified-memory shared storage is the whole point). Requires `xcrun metal` toolchain to build the `.metallib`. Obj-C++ (OBJCXX), C++20, no-ARC.
- cpu_reference.cpp + screening_types.hpp: fully portable C++20 (any OS/arch).
- Build gracefully degrades: non-Apple or missing toolchain → `.mm` excluded, CPU-only build (CMakeLists.txt:48-50, 67-71).

#### IP ownership & licensing

- Repo `github.com/blkpvnthr/C-engine` (private); author `Asmaa Abdul-Amin <contact@blkpvnthr.com>` — same owner as STRIX (user `contact@quantumquant.trade`). **IP owner: the STRIX project owner (blkpvnthr / QuantumQuant).**
- **No LICENSE / COPYING / NOTICE file anywhere in the repo; no per-file copyright headers.** License: UNKNOWN (all-rights-reserved by default). Self-owned → reuse into STRIX is an internal IP transfer, permissible, but NOT safe for a public repo until an explicit license is added and trading semantics are stripped.

#### Trading-specific assumptions that must NOT leak into STRIX

- Namespace `trading::metal` — rename to STRIX-neutral (`strix::native`/`strix::backend`).
- `screen_market` / `ScreeningInput` / `ScreeningOutput` / `ScreenFlag` (kEntryQualified, kTechnicalExit, kBullishDirection, VWAP/SMA/BB gates) — the "mandatory shared entry contract" (directive §28). Pure alpha/trading logic. EXCLUDE.
- `rank_scores` / `RankInput` / `RankParams` / `RankOutput` — composite candidate scoring (rel-strength vs SPY/QQQ, order-flow, regime align, liquidity/ADDV/spread weights). Pure trading. EXCLUDE.
- `technical_features` / `TechFeatures` / `TechValid` — DMI/ADX/ATR/Bollinger/VWAP; trading-indicator-specific (though Bollinger=mean±kσ and VWAP are generalizable primitives). EXCLUDE as-is; optionally re-derive generic stat primitives.
- `market_breadth` / `compact_entry_candidates` / `BreadthCounters` — screen-flag reductions. EXCLUDE.
- `portfolio_scenario_returns`, `ewma_covariance_matrix`'s `minimum_variance`, MonteCarlo `PortfolioParams`/`gross_notional` — portfolio/risk framing. The covariance/MC MATH is generic; the portfolio wrappers are not.
- Field/comment vocabulary: "ticks" (price ticks), `prices`, `session_vwap`, `previous_close_1m`, `addv`, `spy_score`/`qqq_score`, "entry contract". Strip.
- Kernel resolution prefix `"gme::"` is C-engine-shader-specific.

#### Necessary generalizations

- Split cleanly into: (a) **generic GPU runtime harness** (device/queue/library/pipeline-cache/dispatch/telemetry) — directly reusable; (b) **generic buffer pool** — reusable (but add thread-safety); (c) **generic numeric kernels** (int rolling mean, EMA recurrence, covariance/EWMA-covariance, means) — reusable math; (d) **trading screening/ranking** — leave behind.
- Make `dispatch` buffer binding more flexible (offsets, N-D grids) and optionally async (the forced semaphore wait is a parity crutch that defeats batching).
- Add thread-safety to `BufferPool`.
- Generalize `trunc_div`/integer-indicator path into a STRIX arithmetic module; float covariance into statistics.
- Remove the "GPU must bit-match a hand-written CPU oracle" coupling as the sole correctness bar; add independent references.
- Parameterize library discovery; drop `gme::` assumption or make the namespace prefix configurable.

#### Proposed STRIX integration (native/ layout)

- `native/backends/metal/` — the Obj-C++ runtime (device/queue/library/pipeline cache/dispatch/telemetry) from `metal_runtime.mm`/`.hpp`. Maps to R1 §8.1 (device/pipeline/buffers/sync/error).
- `native/backends/metal/buffers.*` — the `BufferPool`/`GpuBuffer` from `metal_buffers.*` (add locking).
- `native/backends/cpu/` + `native/reference/` — the CPU oracle harness pattern: the CPU-fallback + independent-reference pair (R1 §8.3 parity harness).
- `native/arithmetic/` — `trunc_div`, integer rolling mean/EMA/diff/true-range primitives (strip trading names).
- `native/statistics/` — `column_means`, `covariance_matrix`, `ewma_covariance_matrix` (generic; drop `minimum_variance` portfolio hook).
- `native/timeseries/` — rolling-window + Bollinger/VWAP-style primitives IF re-derived generically from `technical_features`.
- `native/integrity/` — `RuntimeTelemetry` counters pattern (dispatch/cache/bytes) as backend health/attestation.
- `bindings/` — pybind11 pattern from `bindings/discovery_bindings.cpp` (re-authored, trading-free).
- NOT mapped: screening/ranking/breadth/portfolio-scenario (constraints/optimization/certification get nothing reusable here; this component is numerics+backend, not solver/cert).

#### Independent validation requirements

- Do NOT trust C-engine's "GPU==CPU-oracle" parity as correctness. Build independent references in STRIX: NumPy/SciPy for covariance/EWMA/means; pure-Python integer models for sma/ema/true_range; compare to Metal AND CPU backends.
- Add CPU-path unit tests runnable in STRIX CI on non-Apple platforms (C-engine has none).
- Cross-validate Metal vs CPU backend within documented tolerances on hardware; add CI skip/xfail off Apple Silicon.
- Fuzz/property tests (random sizes incl. n<window, empty, NaN/Inf inputs, single-observation covariance → NaN).
- Concurrency stress test for the buffer pool once locking is added.
- Verify no information leakage / lookahead in any rolling primitive retained.

#### Classification

**reusable_after_generalization.** The infrastructure (Metal runtime harness, buffer pool) and the generic numeric kernels (integer indicators, covariance/EWMA/means) are high-value, well-structured, and directly aligned with R1 §8.1/§8.3 — but they are embedded in a `trading::metal` namespace alongside non-extractable trading logic (screen_market/rank/technical_features/breadth/portfolio), carry trading vocabulary throughout, have NO portable C++ tests, NO license, and a thread-unsafe buffer pool and a parity-only correctness bar. Reuse requires splitting out the generic layers, renaming, adding independent validation + portable tests, and fixing the buffer-pool concurrency — i.e. generalization before reuse, not drop-in.

---

## 7. Decision-event contracts

### Decision-event contracts

Audit for STRIX Milestone R1. C-engine pinned baseline `3a23b13`. Component: the decision-event
contract/schema and its nonblocking in-memory sink. R1 relevance: §19 GAP-002 (event contracts &
outcome traceability; whether persistence is in-memory/bounded/lossy vs. durable acknowledged).

#### Actual source paths
- `cengine/decision_events.py` (501 lines) — the entire component. Confirmed present at the pinned path.
- Tests:
  - `tests/test_decision_events.py` (92 lines) — core sink behavior.
  - `tests/test_decision_event_integrity.py` (161 lines) — execution-lifecycle emitters, overflow, recovery.
  - `tests/test_execution_decision_events.py` (140 lines).
  - `tests/test_portfolio_decision_events.py` (148 lines).
- Consumers (grep `decision_event`/`DecisionEvent`): `trade.py`, `cengine/regime_strategy_pipeline.py`,
  `cengine/portfolio_pipeline.py`, `cengine/strategy_execution_bridge.py`, `cengine/certification/audit.py`
  (module listed as a certification subject at `audit.py:126`), `cengine/lakehouse/*` (parquet/duckdb landing).
- Reports (runtime artifacts, not source): `reports/decision_event_integrity.json`,
  `reports/portfolio_decision_event_validation.json`.
- Note: an identical copy exists under `.claude/worktrees/dynamic-universe/` (ignore; dev worktree).

#### Algorithm & math assumptions
- There is essentially **no numerics** here. This is a *data contract* + *bounded ring buffer*, not a
  computational kernel.
- `DecisionEventType(str, Enum)` — a closed vocabulary of 38 event kinds spanning regime/strategy/risk/
  order/fill/exit/outcome, portfolio, intelligent-execution, and adaptive-learning milestones.
- `DecisionEvent` dataclass — flat attribution header (event_type, `timestamp_ns` point-in-time,
  decision_id, symbol_id, strategy/regime/feature versions) + free-form `payload: dict` + `schema_version`
  string (`"decision-events-1.0.0"`). `to_row()` = `asdict()` with the enum coerced to its `.value`.
- `DecisionEventSink` — bounded buffer over `collections.deque(maxlen=capacity)` (default 100_000).
  - `emit` (decision_events.py:102) is the only write path: O(1) append; counts `emitted`/`dropped`;
    optionally mirrors to an injected `journal.append(kind, ts_ns, obj)`; wrapped in blanket
    `try/except Exception: pass` so it is **totally nonblocking and never raises** (explicit design
    guarantee, module docstring lines 10-12).
  - Overflow policy: silent oldest-eviction via deque maxlen; `dropped` counter is the only signal.
  - `drain()` returns+clears rows; `peek()` snapshots; `rehydrate()`/`events_from_rows()` rebuild events
    from flat rows, tolerant of extra keys, skipping unknown `event_type` (never fabricates).
- Attribution convenience emitters (~25 `record_*` methods) just shape caller domain objects into payloads.
- Math assumption worth noting: timestamps are integer nanoseconds; no floating-point computation.

#### Dependencies
- **Stdlib only**: `collections.deque`, `dataclasses`, `enum`, `typing`. No numpy/pandas/pyarrow/duckdb
  imported in the module (verified by grep).
- Runtime coupling to the trading engine via **duck-typed** emitter arguments (assessment, rec, order,
  plan, features, outcome, state objects) — those types live in sibling cengine modules but are NOT imported
  at module top level. One lazy local import inside `record_fill`: `from order_manager import OrderStatus`
  (decision_events.py:207) to avoid an import cycle — the sole hard code dependency, and only on the
  partial/complete fill path.
- The `journal` is an injected duck-typed object (any `.append(kind, ts_ns, obj)`); no concrete persistence
  dependency is baked in.

#### Existing tests (do they establish correctness for STRIX usage? NO)
- Coverage is real and meaningful for C-engine's contract: emit/drain/attribution preservation; bounded
  overflow accounting + oldest-eviction order (`["7","8","9"]`); `emit` never raises on a throwing journal;
  best-effort mirror; partial-vs-complete fill classification; unknown-event-type skipping; rehydrate/
  recovery round-trip; realized-outcome traceability. Deterministic, offline, no network.
- They do NOT establish correctness for STRIX usage because: (1) they assert the *lossy* behavior as
  correct (drops are expected and silent) — the opposite of R1's durable-acknowledged requirement;
  (2) no test covers durability, fsync, acknowledgement, crash recovery, or at-least-once delivery;
  (3) no concurrency/thread-safety test; (4) they bind to trading domain objects and trading vocab.
  For STRIX these are a useful *behavioral spec of the contract shape*, not a correctness guarantee.

#### Numerical precision
- Not applicable to computation. Only representational concerns: `timestamp_ns` and tick fields are plain
  Python `int` (unbounded, exact). Float payload fields (returns, bps, confidences) are passed through
  verbatim — the module performs no arithmetic, so no rounding/accumulation error is introduced here.

#### Computational complexity
- `emit` O(1) amortized (deque append + optional single journal call). `drain`/`peek` O(n) in buffer size.
- `rehydrate`/`events_from_rows` O(n) in rows. Memory bounded by `capacity` events (default 100k).

#### Thread-safety
- **Not thread-safe.** `deque.append` under maxlen is individually GIL-atomic, but the emit sequence
  (len check → append → increment counters → journal append) is a non-atomic read-modify-write; concurrent
  emitters can corrupt `emitted`/`dropped` counts and interleave journal writes. No lock anywhere.
  Designed for single-threaded decision-path use. STRIX must not assume it is safe for concurrent writers.

#### Platform requirements
- None. Pure Python 3 (repo runs 3.11). Platform-agnostic; no OS/GPU/Metal dependency (unlike most of
  C-engine). No build step.

#### IP ownership & licensing
- **No LICENSE file** at C-engine repo root (verified; `ls LICENSE*` no match, no license in pyproject/
  setup). Treat as proprietary / all-rights-reserved by the C-engine owner. `ip_owner`: C-engine project
  owner (user/QuantumQuant). **Not safe to copy into a public STRIX repo as-is** absent an explicit grant.
  The *pattern* (event enum + bounded nonblocking sink + drain) is generic and independently reimplementable
  without copying this file.

#### Trading-specific assumptions that must NOT leak into STRIX
- The entire 38-value `DecisionEventType` enum is trading-domain (regime, strategy_family, risk approval,
  broker_ack, partial/complete fill, slippage/microstructure, portfolio optimization, model promotion).
- Attribution header fields `strategy_family`, `strategy_version`, `regime_version`, `symbol_id` are trading.
- Tick/bps/notional payload vocabulary; `correlation_id` convention `"SYMBOL:n:strategy"`.
- Hard import `from order_manager import OrderStatus`.
- **Design-value leakage to reject**: the "lossy is acceptable, drops are silent" stance. R1 §19 GAP-002
  requires *durable acknowledged* persistence; this component is explicitly in-memory, bounded, and lossy
  (oldest silently evicted; journal mirror is best-effort and swallows failures). That philosophy must NOT
  carry into STRIX's integrity/event layer.

#### Necessary generalizations
- Replace the trading enum with a STRIX-owned, open/extensible event-kind registry (or generic tag) so the
  contract is domain-neutral.
- Drop the trading attribution header; keep only generic provenance (event_kind, monotonic timestamp,
  correlation/lineage id, schema_version, opaque payload).
- Remove the `order_manager` import and all `record_*` trading emitters; expose only the generic
  emit/drain/rehydrate core.
- **Invert the durability model**: STRIX needs durable, acknowledged, at-least-once persistence (append to
  a fsync'd/WAL-backed store, ack before returning, backpressure or explicit lossy-mode flag instead of
  silent eviction). The bounded deque can remain only as an in-process staging buffer in front of a durable
  sink, with overflow surfaced (counted AND reported), never silently dropped.
- Add thread-safety (lock or single-writer queue) if multi-producer.

#### Proposed STRIX integration (native/ layout)
- Primary target: **`native/integrity/`** — a STRIX-owned durable event-contract / outcome-traceability
  module (append-only log with acknowledgement, schema versioning, lineage ids, replay/rehydrate). This is
  the GAP-002 home.
- `native/certification/` — consume the durable log for audit/replay validation (mirrors C-engine's
  `certification/audit.py` relationship).
- Not `arithmetic|statistics|timeseries|matrices|constraints|optimization` — no numerics.
- `backends/cpu|metal` — N/A (no compute kernel).
- `bindings` — define the event-contract schema (versioned) as the stable binding surface; a language-
  neutral record (dataclass/struct + schema_version) is the reusable artifact.
- `reference` — the drain/rehydrate round-trip and the unknown-kind-skipping tolerance make good reference
  conformance cases for a STRIX durable-log implementation.

#### Independent validation requirements
- Durability tests absent here and REQUIRED for STRIX: crash/kill-before-drain recovery; fsync/ack semantics;
  at-least-once (no loss) under overflow; idempotent rehydrate; monotonic-timestamp enforcement.
- Concurrency tests (multi-producer correctness of counters and ordering).
- Schema-evolution/round-trip property tests (already partially modeled by `events_from_rows` tolerance).
- Confirm no trading vocabulary remains in the generalized contract.

#### Classification
- **reference_only.** Justification: (1) licensing — no license grant, proprietary, not copy-safe into a
  public repo; (2) it is a trading-domain data contract, not general-purpose numerics (outside R1's stated
  "general-purpose numerics" goal); (3) its core design value (bounded, in-memory, silently-lossy,
  best-effort journal) is the *opposite* of R1 §19 GAP-002's durable-acknowledged-persistence requirement,
  so STRIX must reimplement the persistence model rather than reuse this one. The emit/drain/rehydrate
  *shape* and the event-enum+sink *pattern* are valuable design references and a behavioral spec, but the
  code itself should be independently reimplemented in `native/integrity/` with inverted durability
  guarantees. (Could be argued `requires_reimplementation`; chose `reference_only` because what transfers
  is the contract shape/pattern, not the implementation, and nothing is copied.)

---

## 8. Data integrity + failure injection

### Data integrity + failure injection

Audit for STRIX Milestone R1 — extracting general-purpose data-integrity numerics into a STRIX-owned native library without coupling STRIX to the C-engine trading engine. Pinned C-engine baseline: `3a23b13`. Do NOT modify C-engine.

#### Actual source paths
- `cengine/certification/data_integrity.py` (15,924 bytes, 340 lines) — M7B historical data-integrity certification. Confirmed present at pinned baseline.
- `cengine/certification/failure_injection.py` (9,005 bytes, 197 lines) — §24 failure/fault-injection certification. Confirmed present.
- Direct dependency: `cengine/certification/datasource.py` (read-only DuckDB/Parquet lakehouse wrapper; defines `TS_COL`, `AVAIL_COL`, `SYMBOL_COL`, `DEFAULT_PRICE_SCALE`, `BarInventory`, `bar_inventory`, `connect`, `market_bars_glob`, `_escape`, `safe_ticker` re-export).
- Transitive deps: `cengine/certification/contracts.py` (`CertificationResult`, `CertificationVerdict`, `safe_ticker`), `cengine/runtime/calendar.py` (`is_trading_day`, NYSE `holidays(year)`), `cengine/runtime/supervisor.py` (RuntimeSupervisor, Priority, SingleInstanceLock, checkpoint I/O), `cengine/learning/hardware.py` (DevicePolicy), `cengine/metal_cpu_ref.py` (`ema_ticks`), `protective_exit` (ProtectiveExitCoordinator), `cengine/lakehouse/config.py` (LakehouseConfig).
- Related (NOT the same module): `cengine/integrity.py` + `tests/test_integrity.py` are **source/git-manifest** integrity (SHA verification of source files), unrelated to data integrity. `tests/test_decision_event_integrity.py` is decision-event integrity, also unrelated.
- Docs/reports exist: `docs/certification/data_integrity.md`, `docs/certification/failure_injection.md`, `reports/certification/*.json`.

#### Algorithm & math assumptions
`data_integrity.py` runs 8 independent checks, each returning a `CertificationResult`. All heavy lifting is pushed into **aggregated DuckDB SQL over Parquet** (no row materialization), except one bounded Python loop:
1. **inventory/reconciliation** — sum of per-timeframe bar counts; gate = total ≥ `_MIN_BARS_FOR_CERT` (100,000). Reports per-timeframe {bars, symbols, start/end date}.
2. **duplicates** — `GROUP BY (symbol_id, timeframe, event_timestamp_ns) HAVING count(*)>1`; gate = zero duplicate key groups (`_MAX_DUP_FRACTION = 0.0`, zero tolerance).
3. **monotonicity** — window `lag(ts) OVER (PARTITION BY symbol_id,timeframe ORDER BY ts)`; count rows where `ts <= prev`; gate = zero non-increasing steps (strictly increasing).
4. **OHLC validity** — `low <= least(open,close)`, `high >= greatest(open,close)`, `high >= low`, all prices > 0, `volume >= 0`; gate = zero violations. Prices are integer *ticks* (`bar_*_ticks`).
5. **point-in-time (look-ahead guard)** — count `availability_timestamp_ns < event_timestamp_ns` (hard fail) and NULL availability (→ INSUFFICIENT_DATA, weaker gap). Core no-look-ahead invariant.
6. **price scale** — `DISTINCT price_scale` must equal exactly `[10000]` (uniform fixed-point tick scale).
7. **session coverage** — per (symbol,timeframe): `count(distinct trade_date)` / expected NYSE trading days in [min,max]; expected computed by `_expected_trading_days` looping day-by-day calling `is_trading_day`; gate = all series ≥ `_MIN_SESSION_COVERAGE` (0.90). Also reports bars/day (thin-day signal).
8. **1m/5m timeframe alignment (cross-resolution reconciliation)** — floor 1Min `event_timestamp_ns` to a 5-min grid via integer modulo `ts - (ts % (5*60*1e9))`; aggregate with `arg_min(open,ts)`, `max(high)`, `min(low)`, `arg_max(close,ts)`, `sum(volume)`; JOIN to stored 5Min bars on bucket; gate = ≥99% of matched buckets have **exact** high/low/close equality (volume reported, not gated). Bounded to one eligible symbol (first in sorted 1m∩5m intersection) over ~`sample_days`=20 recent trading days (window = `sample_days*3` calendar days back from max 5m ts).

Math assumptions: timestamps are integer nanoseconds since epoch; prices are integer ticks at fixed scale 10000; timeframes labeled with Alpaca-style strings (`"1Min"`, `"5Min"`, `"15Min"`, `"1Hour"`, `"1Day"`); exact equality (not tolerance) is used for cross-resolution OHLC reconciliation; DST-correct ET (`America/New_York`) used only for ns→date in reporting.

`failure_injection.py` is **not numeric** — it is 6 fault-isolation integration assertions (worker isolation, GPU→CPU degradation, empty-lakehouse graceful degrade, protective-exit per-symbol isolation, single-instance lock, durable checkpoint round-trip). Only the empty-lakehouse check (`_certify_empty_lakehouse_degrades`) touches data_integrity, via monkey-patching `bar_inventory`. The rest are trading-engine-specific orchestration behaviors.

#### Dependencies
- **External**: DuckDB (SQL engine over Parquet; the entire data_integrity compute path depends on it), Python stdlib (`datetime`, `zoneinfo`, `glob`, `asyncio`, `os`, `tempfile`, `dataclasses`, `functools`). Arrow via DuckDB `to_arrow_table`.
- **Internal C-engine**: lakehouse schema + config, certification contracts, NYSE calendar, runtime supervisor, device policy, metal_cpu_ref, protective_exit coordinator.
- Build system: scikit-build-core + pybind11 + CMake (native kernels exist, e.g. metal_cpu_ref), but data_integrity/failure_injection themselves are **pure Python**, no native compilation.

#### Existing tests (do NOT establish correctness for STRIX usage)
- `tests/test_certification_operational.py`: `test_failure_injection_all_certified` (asserts all 6 failure_injection checks CERTIFIED), `test_protective_exit_isolation_swallows_broker_failure`, `test_worker_isolation_keeps_protection_independent`. These are **end-to-end "did it certify" assertions against the real lakehouse/runtime**, not unit tests of the integrity algorithms.
- There is **NO dedicated unit test for `data_integrity.py`'s checks** (duplicates/monotonic/OHLC/point-in-time/coverage/alignment) with crafted inputs. Coverage of its logic is only indirect via the empty-lakehouse injection (which only exercises the `available=False` early return) and via whatever the live lakehouse happens to contain.
- `tests/test_integrity.py` is source-code SHA integrity — unrelated, do not credit.
- Verdict: **tests do NOT establish correctness for STRIX usage.** No property tests, no golden-input tests, no edge-case tests (empty partitions, single-bar partitions, DST boundary buckets, tick-scale mismatch, volume-dedup behavior). STRIX must author its own validation corpus.

#### Numerical precision
- Integer-exact throughout: timestamps (int ns), prices (int ticks), volumes (int). Duplicate/monotonic/OHLC/alignment comparisons are exact integer equality/ordering — no floating tolerance, deterministic.
- Floating point appears only in reporting (`cov = days/expected`, `bars/day`, `_date` via `ns/1e9`) and in the coverage gate (0.90) and alignment gate (0.99 fraction). The `ns/1e9` float division for date derivation is lossy near epoch-scale ns but adequate for date extraction; STRIX should use integer `divmod` if porting.
- Alignment 5-min bucketing uses integer modulo (exact, no drift). Window `arg_min/arg_max` tie-breaking relies on DuckDB semantics.

#### Computational complexity
- Each check is one aggregated pass over the Parquet dataset: O(N) bars for duplicates/OHLC/point-in-time/inventory; monotonic adds a window sort O(N log N) per partition; session_coverage groups by (symbol,tf) then loops expected-day computation O(symbols × days). Alignment is bounded O(window bars) for a single symbol.
- `_expected_trading_days` is a per-day Python loop — O(days) per symbol-series; fine for years but naive (recomputes `holidays(year)` set each call in `is_trading_day`).
- No row materialization in Python except the alignment aggregate fetch — memory-light. Throughput bounded by DuckDB/Parquet scan.

#### Thread-safety
- `connect()` opens a **fresh in-memory DuckDB connection per call** — no shared mutable DB state; each check is independent. Safe for concurrent check execution in principle.
- `datasource.cached_inventory` uses `@lru_cache(maxsize=1)` — process-global cache, not thread-safe to populate concurrently but idempotent.
- `failure_injection._certify_empty_lakehouse_degrades` **monkey-patches module global `di.bar_inventory`** and restores in `finally` — **NOT thread-safe / not reentrant**; concurrent cert runs would race. A STRIX port must use dependency injection instead of global mutation.
- No locks around the integrity checks themselves; DuckDB connections are per-call so OK.

#### Platform requirements
- Pure Python 3.11 (`target-version = py311`; `.pyc` is cpython-311). Requires `zoneinfo` tz database (IANA `America/New_York`).
- DuckDB must be installed and able to read Parquet with `union_by_name=true`.
- No OS/arch lock-in for data_integrity (CPU-only, pure Python). failure_injection references Metal/GPU device policy and `metal_cpu_ref` but only to assert CPU-fallback — those parts are macOS/Metal-flavored and trading-specific.

#### IP ownership & licensing
- IP owner: the C-engine project author (repo `/Users/blkpvnthr/C-engine`, git author "Asmaa Abdul-Amin"). Per STRIX memory, STRIX and C-engine share ownership context but are to remain decoupled.
- **License: UNKNOWN / unlicensed.** No `LICENSE` file present; `pyproject.toml` (`name="cengine"`, `version="0.1.0"`) has **no `license` field**. Treat as proprietary/all-rights-reserved absent an explicit grant.
- Public-repo safe: **NO** — no license grant, and the code is laced with trading-engine identifiers and lakehouse schema. Extraction must be a clean-room reimplementation of the *algorithms* (which are standard data-quality checks), not a copy of this source.

#### Trading-specific assumptions that must NOT leak into STRIX
- Fixed-point **`price_scale == 10000` ticks** and `bar_*_ticks` / OHLC column names — market-data-specific; STRIX integrity must be schema-agnostic (generic numeric columns).
- **NYSE trading calendar** (`is_trading_day`, US market holidays) baked into coverage expectation — STRIX needs a pluggable calendar/expected-cadence abstraction.
- **OHLC bar semantics** (open/high/low/close/volume ordering invariants) — specific to financial bars; generalize to "ordered aggregate record" constraints or keep as an optional OHLC validator.
- **Timeframe vocabulary** (`1Min`/`5Min`/`1Hour`/`1Day`) and the hard-coded 5-min bucket in alignment — generalize to arbitrary (fine, coarse) resolution pairs with a configurable bucket width.
- **`availability_timestamp_ns` point-in-time / look-ahead** semantics — this is a backtest no-look-ahead trading concern; STRIX can keep it as a generic "record-not-available-before-its-event-time" causal check but must decouple from trading framing.
- **`historical_replay` provenance**, lakehouse bronze/silver layout, `symbol_id` partitioning, Alpaca feed/volume-dedup caveats — all trading-pipeline coupling.
- Entire `failure_injection.py` payload (RuntimeSupervisor priorities P0_PROTECTION/P1_MARKET_EXEC, ProtectiveExitCoordinator, broker/venue failure, single-trade-instance lock, GPU→CPU) is **trading-operations-specific** and must not leak; only the abstract pattern "fault isolation / graceful degradation to INSUFFICIENT_DATA" is reusable.

#### Necessary generalizations
- Replace lakehouse/DuckDB-Parquet binding with a backend-neutral table/column abstraction (Arrow table or columnar view); make column names, key columns, timestamp column, and value columns configurable.
- Turn each check into a pure function over a generic dataset descriptor returning a typed result (duplicates, monotonicity, ordered-field validity, causal/point-in-time, uniform-categorical, cadence-coverage, cross-resolution reconciliation).
- Abstract the calendar into an injected "expected-cadence provider"; abstract OHLC invariants into a declarative constraint spec.
- Replace monkey-patch-based degradation with dependency injection; replace the single-symbol bounded alignment with a configurable sampler.
- Drop fixed tick scale; support both integer and float value columns with explicit tolerance for reconciliation (currently exact-only).

#### Proposed STRIX integration (native/ layout)
- Primary home: **`native/integrity/`** — core STRIX data-integrity kernels: duplicate detection, temporal/monotonicity validation, ordered-field (optional OHLC) validity, point-in-time/causal guard, coverage vs expected cadence, cross-resolution reconciliation. Directly serves R1 §12 GAP-003.
- **`native/certification/`** — the fault/failure-injection + graceful-degradation harness pattern (R1 §29.5), reimplemented as generic "inject fault → assert isolation/degradation", with no trading components.
- **`native/timeseries/`** — the resolution-bucketing + aggregation (floor-to-grid, OHLC-style rollup) reused by cross-resolution reconciliation.
- **`native/statistics/`** — coverage ratios / thin-record detection if promoted to generic quality metrics.
- **backends/cpu** — reference pure-Python/NumPy implementation first; **backends/metal** only if the duplicate/monotonic/reconciliation passes become hot (optional, deferred).
- **bindings** — expose integrity checks over Arrow tables.
- **reference** — port the algorithm descriptions + author a golden-input test corpus (STRIX-owned, since C-engine tests do not transfer).

#### Independent validation requirements
- Author STRIX-owned unit/property tests with crafted inputs for every check: injected duplicates, flat/decreasing timestamps, OHLC-order violations, non-positive prices, negative volume, look-ahead (availability < event) and NULL availability, mixed price scales, partial coverage vs a known synthetic calendar, and 1m→5m reconciliation including DST-boundary buckets and deliberate mismatches.
- Validate exact-equality reconciliation vs tolerance-based (decide STRIX semantics; financial exactness assumption must be justified or relaxed).
- Property tests: duplicate/monotonic checks must be order-invariant and partition-correct; coverage must handle single-day and empty spans.
- Cross-check against an independent implementation (e.g. pandas/Polars groupby) on the same corpus.
- Verify thread-safety of the ported degradation harness (no global mutation).
- Confirm no C-engine source copied verbatim (clean-room, given UNKNOWN license).

#### Classification
**reusable_after_generalization.** The underlying checks (duplicate/missing detection, temporal/monotonicity validation, coverage vs calendar, cross-resolution reconciliation, point-in-time guard) are exactly the general-purpose numerics R1 §12 GAP-003 wants, and the §29.5 fault-injection/graceful-degradation pattern maps cleanly to `native/certification`. But the source is **not directly reusable**: it is pure algorithm logic bound tightly to DuckDB/Parquet lakehouse schema, NYSE calendar, fixed tick scale, OHLC/timeframe trading vocabulary, and (in failure_injection) the whole trading runtime — plus UNKNOWN license forbids copying. Extraction = clean-room reimplementation of the algorithms into `native/integrity` (+ `native/timeseries`, `native/certification`) over a backend-neutral table abstraction, with STRIX-authored tests, since existing C-engine tests do not establish correctness for STRIX usage.

---

## 9. CMake build + pybind11 bindings + packaging

### CMake build + pybind11 bindings + packaging

Audit of the C-engine build/bindings/packaging layer for STRIX Milestone R1 (§5 CMake native build, pybind11 bindings, native packaging, backend abstraction). Baseline: C-engine `3a23b13` (feature/m9-runtime-microstructure-execution-learning). This component is the *mechanism* that compiles the native C++/Objective-C++ core, wraps it as a single Python extension module, selects CPU vs Metal backend, and packages the wheel. It is reusable for STRIX, but every current binding target is trading-domain; only the build/packaging/backend-selection *machinery* generalizes.

#### Actual source paths
All paths relative to C-engine root (`/Users/blkpvnthr/C-engine`):
- `CMakeLists.txt` (137 lines) — top-level build. Defines: Metal toolchain auto-detection (L17-50), `cengine_core` STATIC lib (L55-81), `_cengine_native` pybind11 module (L86-101), Metal shader `.air`→`.metallib` custom build (L106-136).
- `pyproject.toml` (59 lines) — packaging. `scikit-build-core` backend (L1-3), wheel packages `["cengine","market_data"]` (L32), optional-dependency extras incl. `metal` pyobjc guard (L16), ruff/mypy/pytest config.
- `bindings/python_bindings.cpp` (214 lines) — `PYBIND11_MODULE(_cengine_native,...)` entry point; registers Side/RiskDecision/RiskEngine/LimitOrderBook/DiscoveryEngine + market-state obs types; forward-declares `register_discovery`/`register_portfolio`.
- `bindings/discovery_bindings.cpp` (338 lines) — Metal runtime + kernel-registry + screening/ranking/breadth/technical-feature surface, gated on `CENGINE_WITH_METAL`; provides a no-op `register_discovery` for non-Metal builds (L330-337).
- `bindings/portfolio_bindings.cpp` (44 lines) — native portfolio allocator / portfolio-risk math surface.
- `native_adapters.py` (159 lines) — Python-side composition adapter: `import _cengine_native as native`, wraps `RiskEngine.evaluate` behind `NativeRiskAdapter` with an `RLock`, marshals Python dataclasses ↔ native request/result structs.
- `build-metal/` — a checked-in *build output* dir (CMakeCache.txt, Makefile, `_cengine_native.cpython-311-darwin.so` [1.95 MB], `cengine.metallib` [285 KB], `libcengine_core.a` [3 MB], per-kernel `.air` files). This is a build artifact tree, not source; it pins the dev config (Python 3.11 venv, `CENGINE_COMPILE_METAL=ON`, pybind11 from venv site-packages).
- Consumed headers (dependencies of the bindings, NOT part of this component but load-bearing): `opportunity_discovery/{discovery_engine,cpu_reference,kernel_registry,metal_runtime,metal_buffers,screening_types}.hpp`, `risk/{risk_engine,portfolio_allocator,protective_exit_candidate}.hpp`, `orderbook/orderbook.hpp`.
- No `setup.py`/`setup.cfg`/`MANIFEST.in` — packaging is entirely declarative via scikit-build-core.

#### Algorithm & math assumptions
The build/bindings component contains **no numerical algorithms of its own** — it is glue. The math lives in the `cengine_core` TUs and Metal shaders it compiles. Structural assumptions worth noting:
- Single-module assumption: all native capability is exposed through one extension module `_cengine_native`; `register_discovery`/`register_portfolio` are called from the one `PYBIND11_MODULE` so there is exactly one import surface.
- Backend-selection assumption: `CENGINE_WITH_METAL` compile-define forks the binding surface; the module always links (Metal path vs documented no-op stub). A `metal_available` bool attr is published so Python can branch to CPU fallback.
- GIL assumption: every on-device/compute-heavy call uses `py::call_guard<py::gil_scoped_release>()` (discovery ingest, Metal dispatch, covariance, ranking) — see python_bindings L196-208 and discovery_bindings L245-284. Pure/cheap calls (risk evaluate, orderbook) hold the GIL.
- Fixed-point assumption leaks into the type system: nearly every bound struct field is `*_ticks` / integer price (QuoteObs, RiskRequest, etc.), encoding an integer-tick price domain.

#### Dependencies
Build-time: CMake ≥3.24; a C++20 compiler; pybind11 ≥2.12 (CONFIG package, resolved from venv); Python ≥3.11 with Development.Module; scikit-build-core ≥0.10 (PEP-517 backend). Apple-only optional: `xcrun` + Metal toolchain (`xcrun metal`/`metallib`), Objective-C++ (OBJCXX), `-framework Metal -framework Foundation`.
Runtime (pyproject): numpy≥1.26, h5py, websockets, pyarrow, duckdb (core); extras `metal` (pyobjc-framework-Metal, Darwin-guarded), `research` (cvxpy, scikit-learn), `learning` (mlx arm64-Darwin-guarded, sklearn, scipy), `scan` (alpaca-py, pandas), `nosql` (pymongo), `dev` (pytest, ruff, mypy).
Internal: bindings depend on `cengine_core` static lib and ~9 trading-domain headers. `native_adapters.py` depends on `cengine.*`, `market_data.alpaca_stream`, `order_manager` — i.e., it is coupled to the trading runtime, not reusable.

#### Existing tests (and whether they establish correctness for STRIX usage — they do NOT by default)
Binding-touching tests exist: `tests/test_native.py` (kill-switch + orderbook crossing), `test_native_metal_runtime.py`, `test_metal_hardware.py`, `test_discovery_engine.py`, `test_portfolio_allocator_native.py`, `test_portfolio.py`, `test_native_execution_bridge.py`, `test_gpu_discovery.py`, +~15 more. These validate that the *trading* bindings behave (e.g. `test_native.py` asserts kill-switch rejects and book matches crossing orders). They do **NOT** establish correctness of the build/packaging machinery for STRIX because: (1) they import `_cengine_native` and exercise trading semantics, not the generic build/backend-abstraction contract STRIX needs; (2) they assume the Metal/CPU parity harness around *these specific kernels*; (3) there is no test of the packaging path itself (wheel build, install layout, metallib-beside-module discovery) — install correctness is asserted only implicitly by CMake `install()` rules. For STRIX, none of these are reusable as-is; the build/backend-selection pattern must get its own tests against STRIX's own kernels.

#### Numerical precision
Not applicable to the build layer itself. Observed precision contracts flowing *through* the bindings: Metal/screening/ranking/technical-feature path is `float` (fp32) — see ScreeningInput/RankInput/TechFeatures all `float`; covariance/EWMA/scenario APIs take/return fp32 vectors. Price/size domain is integer ticks (`std::int64_t`/`std::uint64_t`). The build component imposes no precision policy; it merely compiles whatever the kernels declare. For STRIX, fp32-on-Metal vs fp64-on-CPU parity is an independent concern owned by the numerics, not the build.

#### Computational complexity
Build layer: N/A at runtime. Compile/link cost: one static lib + one shared module + (Apple) 9 Metal shader compiles (`.metal`→`.air`) then one `metallib` link (CMakeLists L116-130). Binding call overhead: pybind11 marshals std::vector↔list by *copy* (`pybind11/stl.h`), so every `ingest_quotes`/`screen`/`covariance_matrix` call is O(n) copy in + O(n) copy out on top of the kernel cost — relevant for STRIX if it pushes large arrays per call (prefer buffer-protocol/numpy zero-copy in a generalized binding).

#### Thread-safety
- Bindings release the GIL around heavy/device work (`gil_scoped_release`), so true parallelism is possible — which means the underlying C++/Metal objects must be internally thread-safe; the binding layer provides **no** locking of its own.
- `native_adapters.NativeRiskAdapter` serializes `evaluate()` with an `RLock` (L50,53) — evidence the native `RiskEngine` is treated as **not** concurrency-safe and is protected on the Python side.
- `MetalRuntime`/`DiscoveryEngine` are bound as mutable objects with GIL released on dispatch; concurrency correctness is delegated to the C++ impl (out of scope here, but STRIX must not assume binding-level safety).

#### Platform requirements
- Portable path: any OS with CMake≥3.24, C++20, Python≥3.11, pybind11 — builds `cengine_core` + `_cengine_native` with `CENGINE_COMPILE_METAL=OFF` and the no-op discovery stub. CPU-only.
- Accelerated path: Apple (macOS) + Apple Silicon implied by the committed artifact `_cengine_native.cpython-311-darwin.so` and MLX arm64-Darwin guard. Requires `xcrun metal` toolchain; CMake auto-detects and degrades to CPU with a warning if absent (L34-46). Metal frameworks linked only on Apple.
- Committed `build-metal/` pins: Python 3.11, darwin, `CMAKE_OSX_ARCHITECTURES` empty (host arch), no explicit build type.

#### IP ownership & licensing
- Owner: Asmaa Abdul-Amin / `blkpvnthr` (git authors: `contact@blkpvnthr.com`, `96803476+blkpvnthr@users.noreply.github.com`). Repo `github.com/blkpvnthr/C-engine` (private origin). Same owner as STRIX (user `contact@quantumquant.trade` / blkpvnthr) — first-party IP, extraction is self-authorized.
- **No LICENSE / COPYING file in the repo** → license UNKNOWN (all-rights-reserved by default). Third-party: pybind11 (BSD-3), scikit-build-core (Apache-2.0), CMake — all permissive, fine to depend on. `iex/` is a vendored third-party nested git repo (pyproject L49-51), explicitly excluded — must NOT be dragged into STRIX.
- Public-repo safety: the build/bindings *mechanism* (CMake structure, pybind11 patterns, scikit-build config) is generic and safe to reimplement in STRIX. The committed binary artifacts in `build-metal/` and any trading kernel source are NOT safe to copy into a public STRIX repo (contain compiled trading IP + absolute local paths in CMakeCache).

#### Trading-specific assumptions that must NOT leak into STRIX
- Every concrete binding target is trading: `RiskEngine`, `RiskRequest`/`RiskResult`, kill-switch, `LimitOrderBook`/`Execution`, `DiscoveryEngine`, `QuoteObs`/`TradeObs`/`BarObs`, screening flags (`SCREEN_ENTRY_QUALIFIED`, VWAP, DMI/ADX, momentum), `RankInput` (rel-strength/order-flow/regime), portfolio allocator (long-only capped, gross cap). None of these belong in a general numerics library.
- The integer-tick price domain (`*_ticks` everywhere) is a market-microstructure convention, not a general numerics convention.
- Module name `_cengine_native`, `trading::` / `trading::discovery` / `trading::metal` / `trading::portfolio` namespaces.
- `native_adapters.py` hard-couples to Alpaca execution, order_manager, reservations — this is pure trading runtime glue and is explicitly out of scope / must not be extracted.
- Metal shader set (`covariance imbalance indicators monte-carlo opportunity_screening technical_indicators market_breadth opportunity_ranking reductions`, CMakeLists L116-118) mixes generic (covariance, reductions, indicators, monte-carlo) with trading-specific (imbalance, opportunity_screening/ranking, market_breadth) kernels.

#### Necessary generalizations
1. Rename/retheme the module (e.g. `_strix_native`) and namespace (`strix::`) — drop `trading::`.
2. Split the monolithic binding into per-domain registration TUs mapped to STRIX `native/` subdomains (arithmetic/statistics/timeseries/matrices/...), each with its own `register_*` like the existing `register_discovery`/`register_portfolio` seam — that pattern generalizes cleanly.
3. Generalize backend selection: the `CENGINE_WITH_METAL` compile-fork + `metal_available` flag + no-op stub is a good backend-abstraction skeleton; lift it to a STRIX `backends/{cpu,metal}` structure with a declared capability-flag convention, and make the "degrade to CPU with warning" logic a first-class backend registry rather than a single boolean.
4. Replace std::vector copy marshaling with numpy buffer-protocol (`py::array_t`) for zero-copy on large arrays.
5. Make metallib install path + discovery explicit/configurable (currently "install beside module", CMakeLists L133-135) so STRIX controls artifact provenance.
6. Strip the trading kernel list down to the generic kernels; trading kernels stay in C-engine.
7. Add a real license (currently UNKNOWN) before any extraction into a public repo.

#### Proposed STRIX integration (map to native/ layout)
- `native/backends/cpu` + `native/backends/metal`: lift the CMake Metal auto-detect/degrade block (CMakeLists L17-50) and the `CENGINE_WITH_METAL` fork as STRIX's backend-abstraction + shader-compile pipeline (L106-136). This is the single most reusable piece.
- `native/bindings`: adopt the `PYBIND11_MODULE` + forward-declared `register_<domain>(py::module_&)` composition pattern (python_bindings L14-18,212-213; portfolio_bindings as the minimal template) — one registration TU per native subdomain.
- `native/matrices` + `native/statistics`: generic math currently surfaced via MetalRuntime (`covariance_matrix`, `ewma_covariance_matrix`, `column_means`) and portfolio-risk (`portfolio_variance`, `risk_contributions`, `inverse_volatility_weights`) — the *math* belongs here; bindings follow.
- `native/timeseries`: `sma`/`ema`/`apo`/`true_range` + technical-feature windowing (as neutral indicators, stripped of trading semantics).
- `native/optimization` / `native/constraints`: `project_long_only_capped`, `allocate_risk_based` → generic constrained-projection / weight-allocation primitives (remove long-only/gross-cap trading framing).
- `native/integrity` / `native/certification`: the `KernelRegistry` + `Coverage` + `reconcile_with_device` + `to_json` (discovery_bindings L286-325) is a reusable build-provenance/kernel-certification mechanism — strong fit for a STRIX integrity/certification layer.
- `native/reference`: the `*_cpu` oracles (`screen_market_cpu`, `rank_scores_cpu`, `technical_features_cpu`, `market_breadth_cpu`) are a reusable *CPU-reference-vs-accelerator parity* harness pattern; the specific functions are trading, the pattern is not.
- Packaging: reuse the scikit-build-core `pyproject.toml` shape (build-system + `[tool.scikit-build]` wheel.packages + platform-guarded extras) as STRIX's packaging template.

#### Independent validation requirements
- Build matrix: verify clean build on (a) non-Apple CPU-only (`CENGINE_COMPILE_METAL=OFF`, confirm no-op stub links and `metal_available==False`) and (b) Apple Silicon with Metal — the committed `build-metal/` is host-specific and must not be trusted as evidence.
- Packaging: actually build a wheel via scikit-build-core and assert the install layout (module + metallib co-located) in a fresh venv; no existing test covers this.
- Binding ABI: Python 3.11 is pinned by the committed `.so`; validate against STRIX's target Python(s) — rebuild, don't reuse the artifact.
- Parity: for any extracted generic kernel, run the CPU-oracle-vs-Metal parity harness on real hardware with STRIX-owned fixtures (existing parity tests assume trading kernels).
- GIL/thread-safety: independently verify that GIL-released calls are safe under concurrent invocation in STRIX's usage (the binding layer adds no locking; C-engine relies on Python-side RLock in native_adapters which STRIX will not inherit).
- License/provenance gate: confirm a license is added and no C-engine absolute paths / binary artifacts are carried over.

#### Classification
**reference_only** (borderline reusable_after_generalization for the build skeleton specifically). Justification: the build/bindings/packaging layer contains zero general-purpose numerics of its own — it is glue whose every concrete target is trading-domain (risk engine, order book, discovery, screening, portfolio allocator) and whose Python adapter (`native_adapters.py`) is hard-wired to Alpaca/order_manager. What is genuinely valuable to STRIX is the *architecture/patterns*: (1) the CMake Metal auto-detect-and-degrade backend abstraction, (2) the single-module `register_<domain>` pybind11 composition seam, (3) the scikit-build-core packaging shape, (4) the KernelRegistry certification + CPU-reference parity harness patterns. These should be **re-implemented** fresh in STRIX's `native/` layout rather than file-copied — the source is too entangled with `trading::` types, integer-tick domain, committed host-specific build artifacts, and an UNKNOWN license to lift directly. Hence reference_only: study it, port the patterns, do not depend on or copy the files.

---

## Extraction-order recommendation (CPU-first; Metal last)

The ordering follows the extraction principles: build the deterministic CPU core and its reference/validation harness first, then the data-parallel statistics, then the accelerator backend only once CPU parity is provable.

**Phase 1 — CPU scalar foundations (no GPU, highest determinism value).**
1. **`native/arithmetic/`** — checked integer ops + exact fixed-point ratio comparison (from Component 1; also feeds Components 4 and 6). Pure, integer-only, platform-agnostic; the determinism bedrock for everything else.
2. **`native/constraints/`** — ordered short-circuit constraint evaluator with typed reason codes (Component 1, GAP-001), plus the box/budget/sign projection (Component 2). Depends only on arithmetic.
3. **`native/integrity/`** — idempotency/dedup guard (Component 1); evidence freshness + timestamp-skew predicates (Component 3); data-quality checks: duplicate/monotonicity/ordered-field/point-in-time/coverage/cross-resolution reconciliation (Component 8, GAP-003); durable acknowledged event-contract + outcome traceability (Component 7, GAP-002, reimplemented with inverted durability).

**Phase 2 — CPU numerics + reference oracles.**
4. **`native/statistics/` + `native/timeseries/`** — descriptive/rolling/EWMA/returns/variance kernels re-expressed as double-precision, series-generic (Component 4), plus the net-new R1 items (CAGR, autocorrelation, OLS trend, anomaly z-score). CPU covariance/EWMA/OLS reference oracle ported from `metal_cpu_ref` with stable accumulation (Component 5 CPU side, Component 6 CPU oracle).
5. **`native/matrices/` + `native/optimization/`** — matvec/quadratic-form primitives and the heuristic risk-based allocator (Component 2); OLS regression (Component 5). Flag the true constrained-QP solver as a remaining gap (R1 §6.5).
6. **`native/reference/` + `native/certification/`** — golden fixtures and certifiable-property harness for every Phase-1/Phase-2 kernel (all components). This is the CPU parity authority that Phase 4 must satisfy.

**Phase 3 — Bindings + build skeleton (CPU-only first).**
7. **`native/bindings/` + CMake/packaging skeleton** — the `register_<domain>` pybind11 composition seam, scikit-build-core packaging, and the backend-abstraction CMake block built CPU-only (`metal_available==False` path) and validated end-to-end before any GPU code (Component 9).

**Phase 4 — Metal acceleration, gated on CPU parity (LAST).**
8. **`native/backends/metal/`** — the Obj-C++ Metal runtime harness + buffer pool (Component 6, with buffer-pool locking fixed), then the two parity-validated kernels `covariance_matrix` + `ewma_covariance_matrix` (Component 5). Each Metal kernel ships only after it demonstrates documented tolerance-bounded parity against its Phase-2 CPU reference (R1 §8.3). No Metal path becomes a source of truth; GPU is enabled only past a measured performance crossover.

---

## Consolidated trading-assumption leakage risk list

Aggregated across all nine components. None of the following may appear in STRIX `native/` code, types, names, or policy; each becomes an application-supplied input in a downstream (non-STRIX-core) consumer, or is dropped entirely.

**Namespaces & module identity.**
- `trading::`, `trading::portfolio`, `trading::analytics`, `trading::metal`, `trading::discovery` namespaces (Components 1, 2, 3, 4, 6, 9).
- `gme::` Metal kernel namespace prefix; module name `_cengine_native` (Components 5, 6, 9).
- Directive-section comments (§3/§7/§25/§28, "Milestone 3") embedded in source (Components 2, 6).

**Order / execution / position vocabulary.**
- Order, notional, position (long/short), gross exposure, buying power, price collar, kill switch, `Side::Buy/Sell`, bid/ask/midpoint, market-data staleness, `RiskRejectReason` enum (Component 1).
- Buying-power cash model; long/short position netting; `safe_notional = quantity * price` identity (Component 1).
- `from order_manager import OrderStatus`; broker_ack / partial-vs-complete fill; `correlation_id` convention `"SYMBOL:n:strategy"` (Component 7).
- `native_adapters.py` coupling to Alpaca execution + order_manager + reservations (Component 9).

**Portfolio / allocation policy.**
- Long-only clamp + "excess stays in cash / do not invent exposure" policy; `cash_weight`, `gross_cap_binding`, `per_asset_cap_binding` (Component 2).
- "variance"/"volatility"/"covariance"/"risk contribution" naming over generic quadratic-form/matvec ops (Component 2).
- Fallback-when-no-expected-returns (§7) decision rule; float32-covariance convention tied to the Metal cov kernel (Components 2, 5).
- `portfolio_scenario_returns`, `minimum_variance` diagonal floor, MonteCarlo `PortfolioParams`/`gross_notional` wrappers (Component 6).

**Market-data / microstructure vocabulary.**
- VIX/VXN symbol whitelist + "complete = VIX+VXN" rule; `vxn_minus_vix_ticks` spread; QQQ/SQQQ equity legs; `StatArb*` composite layer; `StatArbSnapshotPolicy` bounds; feed `sequence`/`provider` gate (Components 3, 5).
- QQQ/SQQQ StatArb pair regression, leveraged-ETF arbitrage framing; `StatArbStatus` enum; `zscore`/`residual`/`hedge`/`beta` field names; min-abs-correlation signal gate; `statarb_normalized_weights`/PairRiskGate (Component 5).
- `Bar`/OHLCV, `MarketSample`/`DepthSample`, VWAP, microprice, depth imbalance, spread_bps, typical-price `(H+L+C)/3`, liquidity pressure (Component 4).
- `screen_market`/`ScreeningInput`/`ScreenFlag` entry contract; `rank_scores`/`RankInput`/`RankParams` scoring; `technical_features` DMI/ADX/VWAP; `market_breadth`/`compact_entry_candidates` (Components 6, 9).
- Screening flags `SCREEN_ENTRY_QUALIFIED`, VWAP, DMI/ADX, momentum, order-flow; rel-strength vs SPY/QQQ; `spy_score`/`qqq_score`/`addv`/`session_vwap`/`previous_close_1m` (Components 6, 9).

**Fixed-point / tick-domain assumptions.**
- Integer-tick price domain (`*_ticks` everywhere); fixed BPS denominator 10000 (Components 1, 2, 3, 4, 6, 9).
- Fixed `price_scale == 10000` + `bar_*_ticks` columns; OHLC validity constraints (high>=low, price>0, volume>=0) (Components 4, 8).

**Calendar / data-pipeline coupling.**
- NYSE trading calendar baked into coverage expectation; Alpaca-style timeframe vocabulary (`1Min`/`5Min`/`15Min`/`1Hour`/`1Day`) + hardcoded 5-min alignment bucket (Component 8).
- `availability_timestamp_ns` look-ahead / backtest no-look-ahead framing; `historical_replay` provenance; lakehouse bronze/silver + `symbol_id` partitioning; Alpaca feed/volume-dedup caveats (Component 8).
- Monotonic tick-timestamp assumption in series validity (`bars_valid`) (Components 4, 8).

**Event-contract domain.**
- 38-value trading `DecisionEventType` enum; attribution header `strategy_family`/`strategy_version`/`regime_version`/`symbol_id`; tick/bps/notional payload vocabulary (Component 7).

**Design-value / philosophy leakage (not vocabulary but must be rejected).**
- The "lossy is acceptable, drops are silent, best-effort journal" durability stance (Component 7) — directly contradicts GAP-002's durable-acknowledged requirement; STRIX must invert it.
- "CPU is sole execution authority / GPU must bit-match a hand-written CPU oracle as the only correctness bar" framing (Components 5, 6) — STRIX needs independent references, not parity-as-correctness.
- Trading screening/ranking/breadth logic and the whole `failure_injection.py` trading-ops orchestration (supervisor P0/P1 priorities, protective-exit, broker/venue failure, single-trade-instance lock, GPU→CPU degrade) — only the abstract fault-isolation/graceful-degradation pattern is reusable (Components 6, 8).

**Cross-cutting IP/provenance risk (all components).**
- UNKNOWN license on C-engine (no LICENSE file, no SPDX headers, no `pyproject` license field) — nothing is public-repo-safe to copy verbatim; prefer clean-room reimplementation from these specs. Do NOT drag in the vendored `iex/` third-party repo, committed `build-metal/` binary artifacts, or absolute local paths from `CMakeCache` (Components 1–9; esp. 9).
