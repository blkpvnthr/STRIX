# Milestone R1 — Intellectual-Property & Licensing Inventory

**Status:** Draft engineering inventory · **Baseline:** STRIX @ `849018d` (branch `feat/milestone-0b`), C-engine @ `3a23b13` (branch `feature/m9-runtime-microstructure-execution-learning`)
**Scope:** R1 §33 IP distinction classes applied to the C-engine component inventories and STRIX subsystem inventories compiled for Milestone R1.

---

## 1. Disclaimer

> **This is an engineering IP inventory, NOT a legal opinion and NOT a patentability determination.**
>
> - Nothing here establishes ownership, inventorship, prior art, freedom-to-operate, patentability, or any legal conclusion.
> - "IP owner," "license," and "reuse decision" fields record **engineering observations** (what the source tree and git history show, what license files exist or are absent), not legal facts.
> - A formal **prior-art search and IP/legal review remain OUTSTANDING** and are prerequisites before any public release, patent filing, or external distribution.
> - Where ownership or license could not be established from the inventories, the entry is marked **UNKNOWN / needs-confirmation**. These are NOT guesses and must be resolved by the owner and/or counsel in writing.
> - A recurring, material fact across the C-engine tree: **no `LICENSE`/`COPYING`/`NOTICE` file exists at the C-engine repo root** (only a vendored `iex/LICENSE` governing an unrelated third-party subcomponent). Absence of a license defaults to "all rights reserved"; same-owner reuse is presumed but **not documented**. An explicit internal license/ownership grant must be recorded before any C-engine code enters the STRIX tree.

---

## 2. C-Engine Component Inventory

This is the **complete** nine-component inventory of the C-engine tree evaluated for R1 reuse. The C-engine repo and STRIX share the same owner (Asmaa Abdul-Amin / blkpvnthr / Quantum Quant), but no C-engine file carries a license grant, so every line is marked **UNKNOWN / needs-confirmation** pending an explicit written grant.

Legend — **Public-repo-safe?**: can the artifact (or its generalized extraction) sit in a public repo without leaking a trading edge or violating a license. **Trading-specific (must not leak)**: whether the artifact embeds proprietary trading vocabulary/policy/alpha that must stay private. **Reuse decision** records the classification and the generalization target under `native/`.

| # | Component | IP owner | License | Public-repo-safe? | Trading-specific (must not leak) | Reuse decision (classification) |
|---|-----------|----------|---------|-------------------|----------------------------------|---------------------------------|
| C-1 | **Deterministic risk engine** — `risk/risk_engine.{hpp,cpp}`, `orderbook/orderbook.hpp`, `bindings/python_bindings.cpp`, `docs/optimization/native_risk_authority.md` | `github.com/blkpvnthr/C-engine` (same owner as STRIX; Asmaa Abdul-Amin) | **UNKNOWN / needs-confirmation** — no LICENSE file; README has no license grant | **No** — trading vocabulary and enums are load-bearing in the current form | **Yes** — order/notional/position/exposure vocabulary; `Side::Buy/Sell` enum dependency; price-collar bps-from-midpoint; buying-power cash model; long/short position netting; market-data staleness rules; `RiskRejectReason` trading enum | **reusable_after_generalization** → `constraints/` + `arithmetic/` + `integrity/` (cpu backend; bindings; reference). Integer-only checked-arithmetic + ordered short-circuit constraint evaluator with typed deterministic reason codes + atomic duplicate-action guard — the exact mechanism GAP-001 needs, once stripped of trading names. |
| C-2 | **Portfolio allocator** — `risk/portfolio_allocator.{cpp,hpp}`, `bindings/portfolio_bindings.cpp`, `tests/test_portfolio_allocator_native.py`, `CMakeLists.txt:60` | C-engine/STRIX owner (proprietary, same party) | **UNKNOWN / needs-confirmation** — no root LICENSE; treat as all-rights-reserved | **No** (as-is); the pure-math core is safe only after the policy layer is split out | **Partly** — `namespace trading::portfolio` + §3/§7/§25 refs; long-only clamp + 'cash'/'do not invent exposure' policy; covariance/variance/volatility naming over a generic quadratic form; float32-covariance convention tied to the Metal cov kernel; fallback-when-no-expected-returns (§7) policy; gross/per-asset cap binding fields as finance semantics | **reusable_after_generalization** → `matrices/` + `statistics/` + `constraints/` + `optimization/`. Clean STL-only, thread-safe quadratic-form/matvec/Euler-risk/inverse-vol/box-budget-projection primitives; split out of trading vocab into `native/`. |
| C-3 | **Volatility & freshness** — `volatility/volatility.{cpp,hpp}`, `orderbook/orderbook.hpp`, `CMakeLists.txt:62`, `statArb/stat-arb.hpp` | Proprietary, same owner as STRIX (user); no LICENSE file present | **UNKNOWN / needs-confirmation** | **No** | **Yes** — VIX/VXN symbol whitelist; price 'ticks' + `vxn_minus_vix` spread; `orderbook.hpp` `ObservedMarketSnapshot` coupling; QQQ/SQQQ StatArb policy bounds; feed sequence/provider gate; `namespace trading` | **reference_only** → `integrity/` (freshness + timestamp-skew), `backends/cpu`. No EWMA/vol math exists here; only O(1) integer freshness/skew predicates worth reimplementing natively as a §10.2 reference. |
| C-4 | **Statistical features & time-series** — `analytics/features.{cpp,hpp}`, `CMakeLists.txt:56` | STRIX principal (Asmaa Abdul-Amin / Quantum Quant) — same author as repo | **UNKNOWN / needs-confirmation** — no LICENSE file, no SPDX header; treat as proprietary, owner-controlled | **Yes** (the kernels are domain-neutral once de-coupled from OHLCV) | **Yes** — `trading::analytics` namespace; Bar/OHLCV + microstructure (VWAP, microprice, depth imbalance); OHLC validity constraints (high≥low, price>0); float-only outputs + fixed indicator periods; GPU/Metal flattening types; monotonic tick-timestamp assumption | **reusable_after_generalization** → `statistics/` + `timeseries/` (backends/cpu reference; `arithmetic/`, `integrity/` helpers). Sound STL-only SMA/EMA/rolling-std/returns/ROC kernels, but float-only, OHLCV-coupled, untested, and missing R1 CAGR/autocorrelation/trend/anomaly. |
| C-5 | **Metal covariance/EWMA/regression kernels** — `metal/covariance.metal`, `cengine/metal_covariance.py`, `cengine/metal_cpu_ref.py`, `cengine/metal_backend.py`, `tests/test_metal_hardware.py`, `tests/test_native_metal_runtime.py` | C-engine repo owner (Asmaa Abdul-Amin); same owner as STRIX | **UNKNOWN / needs-confirmation** — no LICENSE file; no header; treat proprietary | **No** (Tier B stat-arb kernels); safe only after stripping and float64 hardening | **Yes** — QQQ/SQQQ StatArb pair regression; VIX/VXN volatility factor kernel; long/short normalized pair weights + `PairRiskGate`; `StatArbStatus` enum + zscore/residual field names; min-abs-correlation signal gate; CPU-is-execution-authority framing | **reusable_after_generalization** → `statistics/` (covariance+EWMA), `matrices/`, `timeseries/`, `optimization/` regression; `backends/cpu`+`metal`, `reference/`. Parity-validated float32 covariance+EWMA Metal kernels are reusable after stripping StatArb/VIX trading coupling and adding stable float64 numerics. |
| C-6 | **Obj-C++ Metal runtime + CPU reference** — `opportunity_discovery/metal_runtime.{mm,hpp}`, `opportunity_discovery/cpu_reference.{hpp,cpp}`, `opportunity_discovery/metal_buffers.{mm,hpp}`, `opportunity_discovery/screening_types.hpp`, `CMakeLists.txt` | STRIX owner (blkpvnthr / QuantumQuant) — same author as C-engine | **UNKNOWN / needs-confirmation** — no LICENSE file; all-rights-reserved | **No** (as-is); harness is safe only after the embedded screening/ranking logic is split out | **Yes** — `trading::` namespace + `gme::` kernel prefix; `screen_market`/`ScreeningInput`/`ScreenFlag` entry contract; `rank_scores`/`RankInput`/`RankParams` scoring; `technical_features` DMI/ADX/VWAP + `market_breadth`/compact; `portfolio_scenario_returns` + `minimum_variance` hook; vocab: ticks/prices/`session_vwap`/addv/`spy_qqq` | **reusable_after_generalization** → `backends/metal` + `backends/cpu` + `reference` + `statistics` + `arithmetic` + `integrity`. Generic Metal dispatch harness + buffer pool + int/float numeric kernels are reusable once split from the embedded trading screening/ranking logic and renamed. |
| C-7 | **Decision-event contracts** — `cengine/decision_events.py`, `tests/test_decision_events.py`, `tests/test_decision_event_integrity.py`, `tests/test_execution_decision_events.py`, `tests/test_portfolio_decision_events.py` | C-engine project owner (QuantumQuant); no license file, treat proprietary | **UNKNOWN / needs-confirmation** — no LICENSE at repo root | **No** | **Yes** — 38-value trading `DecisionEventType` enum; strategy/regime/feature/symbol attribution header; tick/bps/notional + `correlation_id` vocab; `from order_manager import OrderStatus`; silently-lossy best-effort-journal design value (violates GAP-002 durable-ack) | **reference_only** → `integrity/` (durable event-contract + outcome traceability; `certification/` consumes). Trading-domain event schema + bounded in-memory lossy sink; reuse the contract/drain pattern only, reimplement durable persistence. |
| C-8 | **Data integrity + failure injection** — `cengine/certification/data_integrity.py`, `cengine/certification/failure_injection.py`, `cengine/certification/datasource.py`, `cengine/certification/contracts.py`, `cengine/runtime/calendar.py` | C-engine project author (Asmaa Abdul-Amin) | **UNKNOWN / needs-confirmation** — no LICENSE file; pyproject has no license field | **No** | **Yes** — fixed `price_scale=10000` ticks + `bar_*_ticks` columns; NYSE trading calendar baked into coverage; OHLC bar semantics; 1Min/5Min/1Hour timeframe vocab + hardcoded 5-min bucket; `availability_timestamp_ns` look-ahead/backtest framing; lakehouse bronze/`symbol_id`/historical_replay coupling; entire `failure_injection` runtime (supervisor P0/P1, protective-exit, broker, GPU/Metal) | **reusable_after_generalization** → `integrity/` (+ `timeseries/`, `certification/`). Standard data-quality checks (dup/missing, temporal, coverage, cross-resolution reconciliation, point-in-time) plus a fault-injection/graceful-degradation pattern — clean-room reimplement over a backend-neutral table abstraction. |
| C-9 | **CMake build + pybind11 bindings + packaging** — `CMakeLists.txt`, `pyproject.toml`, `bindings/python_bindings.cpp`, `bindings/discovery_bindings.cpp`, `bindings/portfolio_bindings.cpp`, `native_adapters.py`, `build-metal/` | Asmaa Abdul-Amin / blkpvnthr (first-party, same owner as STRIX) | **UNKNOWN / needs-confirmation** — no LICENSE file; all-rights-reserved by default | **No** (files); the *pattern* is safe to re-author independently | **Yes** — `trading::` / discovery / metal / portfolio namespaces; `RiskEngine`/`LimitOrderBook`/`DiscoveryEngine` binding targets; integer-tick price domain (`*_ticks`); screening flags: VWAP/DMI/ADX/momentum/order-flow; `native_adapters.py` coupled to Alpaca/order_manager; trading kernels: imbalance/opportunity_screening/ranking/market_breadth; module name `_cengine_native` | **reference_only** → `backends/{cpu,metal}` + `bindings` + `certification` (integrity) + packaging. Glue layer with no generic numerics; port the CMake Metal-degrade backend abstraction, `register_<domain>` pybind11 seam, scikit-build packaging, and kernel-registry/CPU-parity patterns rather than copying trading-coupled files. |

**C-engine cross-cutting actions (all nine components):**
- Obtain an **explicit written ownership/license grant** from the C-engine owner before any line enters the STRIX tree (no LICENSE file = ambiguous rights; every row above is UNKNOWN / needs-confirmation).
- Add an explicit license/copyright/SPDX header to every extracted file.
- Do **not** inherit C-engine's numpy-parity or 1e-4 FP32 tolerances as correctness; build STRIX-owned FP64 references and independently justified tolerances.
- CI grep-gate every extraction for residual trading identifiers (`statarb`, `QQQ`, `SQQQ`, `VIX`, `VXN`, `trading::`, `StatArbStatus`, `gme`, `cash_weight`, `Side::`, `RiskRejectReason`, `*_ticks`, `session_vwap`, `spy_qqq`, `order_manager`, `_cengine_native`, etc.).
- Treat the two **`reference_only`** components (C-3 volatility/freshness, C-7 decision-event contracts) and the two reference-only glue items (C-9 build/bindings) as **designs to re-author**, not code to copy. The six **`reusable_after_generalization`** components (C-1, C-2, C-4, C-5, C-6, C-8) may be extracted only after generalization + grep-gate + license header + a written grant.

---

## 3. STRIX-Owned IP Summary

All STRIX subsystems below are **first-party to the STRIX owner** (`contact@quantumquant.trade`), authored in-repo. Third-party *dependencies* (Pydantic, DuckDB, PyArrow, FastAPI, React, Vite, Tailwind, dbt, h5py, numpy, websockets, etc.) remain under their own upstream licenses and are used as dependencies, not vendored source. STRIX's own license status for public release is **UNKNOWN / needs-confirmation** (no explicit repo LICENSE verified in the inventories; manifests are unsigned — integrity without authenticity).

STRIX-owned original mechanisms worth cataloguing as existing IP:

- **Canonical serialization & content-addressing** (`src/strix/canonical.py`) — Decimal-only, float-forbidden, representation-normalized, tz-aware UTC, sorted-key JSON; SHA-256 content digests; `make_id` = `PREFIX-sha256[:12]`. Clean, dependency-light, reusable as-is.
- **Frozen typed-lineage data models** (`src/strix/models.py`) — `StrixModel` (frozen, `extra='forbid'`), the `SourceArtifact→SourceFact→CalculationResult→Evidence→Claim` chain, bounded StrEnum vocabularies, 17-member `FailureCode` taxonomy, `RunManifest`.
- **Independent verification + deterministic replay** — pipeline verifier (`verification/claims.py`, `replay.py`) and agent verifier (`agent/verifier.py`, `agent/replay.py`): recompute independently of any LLM, compare against stored results, fail-closed publication gate. (Two non-unified stacks — see §6.)
- **Multi-dimensional resource accounting** (`agent/budget.py`) — `BudgetTracker`/`BudgetSnapshot` enforcing calls/tokens/time/USD with versioned pricing, pre-call checks, fail-soft, injectable clock.
- **Typed tool registry & trust boundary** (`agent/tool_registry.py`, `research/pipeline/propose.py`) — JSON-schema-validated tools; capability-restricted proposer seam that cannot set a verdict; `VerificationStatusInjectionError`.
- **Deterministic financial calculators** (`agent/calculations.py`, `analytics/profitability.py`) — exact Decimal, shared `recompute()` used by both tool and verifier.
- **Medallion lakehouse** (`src/strix/lakehouse/`) — immutable content-addressed Bronze + append-only provenance, quality-gated/reconciled Silver (decimal128 Parquet), DuckDB star-schema warehouse + offline Snowflake adapter, dbt marts, independent cross-validation harness, crash-safe atomic `run_store`.
- **Source connectors & SSRF-hardened acquisition** (`src/strix/sources/`, `corpus/acquisition/`, `lakehouse/ingest/`) — pure point-in-time EDGAR parser; layered SSRF/content-validation PDF downloader; five live §22 extractors (Alpaca, SEC EDGAR, Treasury, BLS, FRED) with credential redaction.
- **Engineering traceability vertical** (`src/strix/engineering/`) — discriminated typed-edge graph, evidence-cited nodes/edges, independent re-derivation verifier, temporal knowability enforcement, quarantine of rejected candidates, XXE-hardened adapters, deterministic three-way replay.
- **CLI / Web API / React SPA** (`src/strix/cli.py`, `webapi/`, `service.py`, `web/`) — `ask`/`replay`, canonical-JSON API, answer-first conversational UI with inline citations and evidence inspector.
- **0B requirements baseline & eval design** (`docs/research/milestone-0/`) — machine-readable `requirements-baseline.yaml` (STRIX-001..015), traceability/gap matrices, falsification-first comparative-experiment design.

---

## 4. §33 Seven-Class Classification

### Class 1 — Existing STRIX IP (first-party, already built)
- `canonical.py` (Decimal-only canonical serialization, SHA-256 digests, `make_id` content-addressing).
- `StrixModel` frozen/closed-schema base and the typed lineage chain + `FailureCode` taxonomy (`models.py`).
- Pipeline and agent independent verifiers + deterministic replay (`verification/claims.py`, `replay.py`, `agent/verifier.py`, `agent/replay.py`).
- `BudgetTracker`/`BudgetSnapshot` multi-dimensional resource accounting (`agent/budget.py`).
- Typed tool registry + capability-restricted proposer seam (`agent/tool_registry.py`, `research/pipeline/propose.py`).
- Deterministic calculators with shared `recompute()` (`agent/calculations.py`, `analytics/profitability.py`).
- Medallion lakehouse (Bronze/Silver/warehouse/dbt), `run_store`, cross-validation harness.
- Connectors + SSRF-hardened acquisition pipeline; pure point-in-time EDGAR parser.
- Engineering traceability vertical (typed-edge graph, re-derivation verifier, XXE hardening, replay).
- CLI/Web API/React SPA; 0B requirements baseline, matrices, and experiment design.

### Class 2 — Existing C-Engine IP (first-party to C-engine owner; reuse pending written grant)
All nine C-engine components inventoried in §2 (same owner as STRIX; every one UNKNOWN / needs-confirmation on license):
- **C-1 Deterministic risk engine** — integer-only checked-arithmetic + ordered short-circuit constraint evaluator with typed reason codes + atomic duplicate-action guard (*reusable_after_generalization* → `constraints/` + `arithmetic/` + `integrity/`).
- **C-2 Portfolio allocator** — STL-only thread-safe quadratic-form / matvec / Euler-risk / inverse-vol / box-budget-projection primitives (*reusable_after_generalization* → `matrices/` + `statistics/` + `constraints/` + `optimization/`).
- **C-3 Volatility & freshness** — O(1) integer freshness/skew predicates only; **no** EWMA/vol math despite the name (*reference_only* → `integrity/`).
- **C-4 Statistical features & time-series** — STL-only SMA/EMA/rolling-std/returns/ROC kernels, float-only and OHLCV-coupled (*reusable_after_generalization* → `statistics/` + `timeseries/`).
- **C-5 Metal covariance/EWMA/regression kernels** — parity-validated float32 covariance+EWMA (Tier A) + stat-arb kernels (Tier B, leave behind) (*reusable_after_generalization* → `statistics/`, `matrices/`, `timeseries/`, `optimization/`; `backends/cpu`+`metal`).
- **C-6 Obj-C++ Metal runtime + CPU reference** — generic Metal dispatch harness + buffer pool + int/float kernels under embedded trading screening (*reusable_after_generalization* → `backends/metal`+`cpu` + `reference`).
- **C-7 Decision-event contracts** — trading event schema + bounded lossy in-memory sink; reuse the contract/drain pattern only (*reference_only* → `integrity/`).
- **C-8 Data integrity + failure injection** — standard data-quality + fault-injection/graceful-degradation patterns; clean-room reimplement over a backend-neutral table (*reusable_after_generalization* → `integrity/` + `timeseries/` + `certification/`).
- **C-9 CMake build + pybind11 bindings + packaging** — glue with no generic numerics; port the Metal-degrade backend abstraction + `register_<domain>` pybind11 seam + scikit-build packaging as a *pattern* (*reference_only* → `backends/{cpu,metal}` + `bindings` + packaging).

### Class 3 — Established mathematical / statistical methods (NOT novel — do not claim)
- Sample covariance (Bessel-corrected), column/arithmetic means.
- EWMA / RiskMetrics-style exponentially-weighted covariance.
- Ordinary least squares / linear regression; Pearson correlation; residual z-scores.
- Quadratic form `wᵀΣw`, marginal risk `Σw`, Euler risk-contribution identity.
- Inverse-volatility weighting; (naive) risk-parity-flavored allocation.
- GPU/SIMD parallel numerical computing; deterministic sequential CPU reduction.
- SHA-256 hashing; content-addressed storage; Merkle/content digests.
- Deterministic policy enforcement; monotonic-timestamp/sequence validation; freshness/staleness checks.
- Decimal fixed-precision arithmetic; bootstrap/CI, hypothesis tests, descriptive/time-series/multivariate statistics (the R1 §6 target methods).

### Class 4 — General engineering techniques (common practice; not claimable as novel)
- Atomic write via temp-file + fsync + single `os.replace`/rename.
- Path-traversal containment; filename/run-id sanitization.
- Pydantic frozen/closed-schema models; `extra='forbid'`.
- pybind11 FFI; scikit-build-core PEP-517 builds; GPU-toolchain auto-detect-and-degrade.
- SSRF defense (private/loopback/metadata address rejection); HTTPS-only + port allowlist + redirect SSRF re-check; XXE/DOCTYPE rejection.
- Rate limiting + bounded exponential backoff; injectable clock/transport for deterministic tests.
- Background job workers, idempotency keys, bounded-concurrency semaphores, restart recovery.
- Star-schema dimensional modeling; medallion (Bronze/Silver/Gold) data architecture.
- Data-quality checks (duplicate/missing detection, temporal ordering, coverage, cross-resolution reconciliation, point-in-time availability); fault-injection / graceful-degradation harnesses.
- React SPA with polling; inline-citation UI; slide-over inspector pattern.
- `target=_blank` + `rel=noreferrer`; secret redaction in URLs/logs.

### Class 5 — Newly implemented mechanisms (to be BUILT in R1)
- Four certificate node types: **ComputationCertificate, ClaimCertificate, AuthorizationCertificate, OutcomeCertificate** (entirely greenfield).
- **Resource-bounded verification**: per-predicate/per-sub-goal budget accounting, bounded-work guarantees, declared-vs-consumed cost fields, resource-bound attestation.
- Explicit typed **admission-predicate layer** (Integrity, Type-Temporal, Provenance, Derivation, Support) with a uniform result and composition operator.
- **Cryptographic signing/authenticity** of manifests and certificates (keys, principals, capabilities) — closing the current integrity-without-authenticity gap.
- `SourceObservation` node (distinct from validated `SourceFact`); first-class `CandidateClaim`; model-level temporal invariants (`known_at ≤ as_of`, bitemporal `valid_from/valid_until`); status-transition state machines.
- Generic/extensible **graph edge model + traversal/query layer** (paths, reachability, cycles, orphans); decision/outcome entities and decision→outcome closed-loop verification.
- Durable **assurance layer** (4th medallion) + append-only, hash-chained **decision ledger**; persisted verification results & resource accounting; bitemporal/as-of queries.
- **Research objective decomposition (§14)** and **resource-constrained acquisition strategy (§15)**: sub-goal graph, value-of-information prioritization, coverage/gap tracking, principled stopping, per-sub-goal sub-budgets; unified trust boundary across live-tool and typed-evidence paths.
- STRIX-owned `native/` numerics stack (`constraints/`, `arithmetic/`, `matrices/`, `statistics/`, `timeseries/`, `optimization/`, `integrity/`, `backends/{cpu,metal}`, `reference/`, `certification/`, `bindings`) — CMake + pybind11 + optional GPU — backed by the generalized C-1 risk-constraint evaluator, C-2 allocator primitives, C-4/C-5 statistics kernels, C-6 Metal harness, and C-8 data-integrity checks, with STRIX-owned FP64 references.
- Durable decision-event + data-integrity layer re-authored from the C-7 contract/drain pattern and C-8 quality/fault-injection patterns, replacing the silently-lossy best-effort journal with a durable-ack design (closing GAP-002).
- New §22 connectors (USAspending, SAM.gov, USGS) + SSRF guard wired into the lakehouse ingestion path; unified connector contract.
- New CLI/API surface: `compute`, `graph`, `verify`, `audit`, `certificate`, `authorization`, `outcome`, `research benchmark`; durable web-API jobs; unified typed response envelope.
- Frontend: Markdown/table/chart rendering (with sanitization), graph inspector, certificate inspector.
- §29 benchmark/eval infrastructure **as code** (4-arm harness, blind scorer, seeded generators, bootstrap CI).
- New requirements STRIX-016+ (resource-bounded typed-evidence verification) under the existing baseline schema.

### Class 6 — Proposed research contributions (hypotheses / designs, not yet validated)
- The **composition** of established methods (Class 3) into **independently verified, resource-bounded research & execution assurance** — i.e., certificates that bind a claim to its evidence AND to a bounded, independently-reproducible verification budget.
- Resource-bounded admission predicates as a unifying verification abstraction.
- Closed-loop decision→outcome certification with temporal (bitemporal) correctness.
- Falsification-first comparative-experiment design (H1/H2/H3, arms A/B/C/D) — a *design*, with **zero results** to date.
- Unified evidence vocabulary resolving the documented triple-duplication (GAP-003).

### Class 7 — Empirically validated findings
- **None yet.** No experimental results exist. The comparative-experiment design is design-only; the v0.2.0 benchmark is a single hand-transcribed run, not a repeatable harness; coverage is unmeasured (pytest-cov absent). Any "validated" claim is **premature** until the §29 harness runs and produces results.

---

## 5. "Do-Not-Claim-Novel" List vs. the Actual Proposed Contribution

### 5.1 Do NOT claim as novel (established prior art — Class 3/4)
These are well-established and must be described as *applied*, never *invented*, by STRIX or C-engine:

- Covariance (sample/Bessel-corrected), column means.
- EWMA / exponentially-weighted / RiskMetrics covariance.
- Regression (OLS), correlation, residual z-scores, beta.
- Quadratic form / marginal risk / Euler risk-contribution; inverse-volatility and risk-parity allocation.
- GPU / parallel / SIMD numerical computing.
- Deterministic policy enforcement; monotonic timestamp/sequence and freshness/staleness validation.
- SHA-256 hashing, content-addressed storage, Merkle-style digests.
- Decimal arithmetic; descriptive/time-series/multivariate/inferential statistics; bootstrap CIs.
- Atomic file writes, path containment, SSRF/XXE defenses, rate limiting/backoff, medallion/star-schema data modeling, data-quality/reconciliation checks, fault-injection harnesses, pybind11/CMake/scikit-build packaging.

### 5.2 The ACTUAL proposed contribution
> STRIX's claimable contribution is **not any individual algorithm** — every statistical and systems primitive above is prior art. The contribution is their **composition into an independently verified, resource-bounded research and execution assurance system**:
>
> 1. **Typed, provenance-bound evidence** flowing through content-addressed lineage.
> 2. **Independent-by-construction verification** (the verifier shares no trust with, and re-derives independently of, the proposer/LLM) expressed as **typed admission predicates** (Integrity, Type-Temporal, Provenance, Derivation, Support).
> 3. **Resource bounds as a first-class, accounted, attestable property** of every verification and computation — declared, consumed, and certified.
> 4. **Signed certificates** (Computation/Claim/Authorization/Outcome) that make the above **tamper-evident and authentic**, not merely integrity-hashed.
> 5. **Closed-loop decision→outcome certification** with **bitemporal** temporal correctness, persisted in a durable append-only assurance ledger.
>
> Novelty, if any, is in this *architecture and composition under resource bounds and independent verification* — a claim that remains a **Class 6 proposal** until the §29 benchmark produces Class 7 results, and until the outstanding prior-art/IP review is completed.

---

## 6. Public-vs-Private Handling

If the STRIX repository (or any extracted numerical library) is made public, the following **must stay in a private/local-only branch** and must never appear in public history:

### 6.1 Must stay private — trading edge / proprietary policy
- **C-1 risk-engine trading surface**: order/notional/position/exposure vocabulary, `Side::Buy/Sell`, price-collar bps-from-midpoint, buying-power cash model, long/short netting, market-data staleness rules, `RiskRejectReason`. (Keep only the generalized integer-checked-arithmetic constraint evaluator.)
- **C-2 allocation policy layer** (as opposed to the neutral math): long-only clamp, `cash_weight`/`gross_weight` semantics, inverse-vol fallback *as a mandated allocation policy*, per-asset/gross caps as risk-mandate parameters, the `trading::portfolio` naming and §3/§7/§25 policy refs.
- **C-3 trading composite**: `StatArbMarketSnapshot`/Builder, OrderBookRegistry / `ObservedMarketSnapshot` coupling, VIX/VXN whitelist, `vxn_minus_vix` spread, tick-scale conventions, QQQ/SQQQ StatArb bounds, feed sequence/provider gate.
- **C-4 microstructure surface**: `trading::analytics` namespace, OHLCV + VWAP/microprice/depth-imbalance, OHLC validity constraints, fixed indicator periods. (Keep only the de-coupled SMA/EMA/rolling-std/returns/ROC kernels.)
- **C-5 Tier B stat-arb kernels**: `statarb_pair_regression`, `statarb_residual_series`, `volatility_factor_features`, `statarb_normalized_weights`, `StatArbStatus`, QQQ/SQQQ pair semantics, VIX/VXN factor set, −beta hedge-weight logic, correlation-gate/`PairRiskGate` heuristics. (Keep only Tier A covariance+EWMA.)
- **C-6 screening/ranking logic**: `gme::` kernels, `screen_market`/`ScreeningInput`/`ScreenFlag`, `rank_scores`/`RankInput`/`RankParams`, `technical_features` DMI/ADX/VWAP, `market_breadth`, `portfolio_scenario_returns`, `minimum_variance` hook, `session_vwap`/addv/`spy_qqq` vocab. (Keep only the generic Metal dispatch harness + buffer pool + numeric kernels.)
- **C-7 trading event taxonomy**: the 38-value `DecisionEventType` enum, strategy/regime/feature/symbol attribution header, tick/bps/notional + `correlation_id` vocab, `order_manager`/`OrderStatus` coupling. (Keep only the durable contract/drain *pattern*.)
- **C-8 trading-coupled integrity details**: fixed `price_scale=10000` ticks and `bar_*_ticks` columns, baked-in NYSE calendar, OHLC bar semantics, 1Min/5Min/1Hour + hardcoded 5-min bucketing, `availability_timestamp_ns` backtest framing, lakehouse bronze/`symbol_id`/historical-replay coupling, and the **entire `failure_injection` runtime** (supervisor P0/P1, protective-exit, broker, GPU/Metal). (Keep only backend-neutral data-quality checks.)
- **C-9 `native_adapters.py`** and the trading binding surface: Alpaca/IEX execution, `order_manager`, reservations, kill-switch, buying-power/gross-exposure risk policy, `Side`/`RiskDecision`/`RiskRejectReason`, `LimitOrderBook`, `DiscoveryEngine`, integer-tick (`*_ticks`) price domain, the trading Metal shader set (imbalance, monte-carlo, opportunity screening/ranking, market breadth), and the `_cengine_native` module name.
- Any CLAUDE.md "Mission"/alpha-mining content, strategy parameters, or research that reveals a deployable edge.

### 6.2 Must stay private — secrets, credentials, and untrusted/unvetted artifacts
- API keys and credentials (OpenAI, Alpaca, FRED, Snowflake). `AgentConfig.SecretStr`, `.env`, `dbt/profiles.yml` (confirm it is gitignored and not committed), `STRIX_INTERNAL_TOKEN`.
- Live research runs, `research_runs/`, `service/jobs.json`, and any run manifests containing non-synthetic or non-PUBLIC data.
- `docs/FALCON/faq-dpa26bz04-dv-016.pdf` — **untracked, unvetted binary of unknown provenance**; do NOT publish or add to mkdocs nav without review and a confirmed license.

### 6.3 Safe for a public repo (only after the stated conditions)
- STRIX first-party Class 1 code (canonical serialization, models, verifiers, budget, lakehouse scaffolding, connectors with SSRF hardening, engineering vertical, CLI/API/UI) — **conditional on an explicit STRIX repo LICENSE being added** (currently UNKNOWN / needs-confirmation).
- The **six `reusable_after_generalization` C-engine components** (C-1, C-2, C-4, C-5 Tier A, C-6 harness, C-8 checks) — only after (a) a written ownership/license grant from the C-engine owner, (b) generalization/renaming removing all trading vocabulary, (c) a CI grep-gate confirming no residual trading identifiers, and (d) an added SPDX/license header.
- The **three `reference_only` items** (C-3, C-7, and the C-9 build pattern) re-authored independently as designs — not copied.

### 6.4 Gating preconditions before ANY public release
1. Explicit written STRIX repository license decided and added.
2. Written C-engine ownership/license grant for every extracted file (all nine §2 components are UNKNOWN / needs-confirmation).
3. Prior-art search and IP/legal review completed (currently OUTSTANDING).
4. CI grep-gate for trading identifiers on all extracted numerical artifacts.
5. Secret-scanning of full git history; confirm `profiles.yml`/`.env`/tokens never committed.
6. Review and license-clear or remove the untracked FALCON PDF and other untracked binaries (`assets/`, empty `research/`).
7. Resolve all **UNKNOWN / needs-confirmation** entries in §2 and §3 in writing.

---

*End of inventory. All "UNKNOWN / needs-confirmation" markers require resolution by the owner and/or counsel before relying on any reuse or release decision recorded above.*
