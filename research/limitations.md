# Limitations & Scope Boundaries — Milestone R1

**Milestone:** R1 — Resource-Bounded Typed Evidence Verification for Trustworthy Autonomous AI
**Branch:** `research/formal-evidence-verification` (cut from `feat/milestone-0b` `849018d`; **uncommitted**, not merged, not deployed)
**Date:** 2026-11-24
**Classification key (§37):** IMPLEMENTED · TESTED · NOT_IMPLEMENTED · NOT_EVALUATED · BLOCKED.

> **Read this first.** This document is the authoritative statement of what R1 does
> **not** establish. It exists to prevent the engineering outcome from being
> misread as a scientific, legal, or eligibility outcome. Where a reader needs a
> single sentence: **R1 is a tested software substrate, not a validated scientific
> result.** Nothing in R1 demonstrates a research hypothesis, proves novelty or
> patentability, establishes statistical significance, or confers any government
> endorsement, solicitation eligibility, or funding status.

---

## 0. The one limitation that governs all others

**A successful software implementation is not scientific validation.**

R1 shipped working, well-tested code. That is an *engineering* fact. It is **not**
evidence that:

- the research hypotheses (H1–H12) are true — they were **NOT_EVALUATED**;
- the approach is **novel** or **patentable** — no novelty or prior-art analysis
  was performed, and none is claimed;
- any result is **statistically significant** — no benchmark was run, so there is
  no sample, no effect size, and no confidence interval to report;
- the work is **endorsed by, eligible for, or funded by** any government program —
  no such relationship exists or is implied (see §11).

Passing tests measure internal consistency against the behaviors we specified.
They do not measure whether those behaviors improve trustworthiness on real
research tasks. That measurement requires the §29 benchmark, which was not built.

---

## 1. Hypotheses H1–H12 — NOT_EVALUATED

**Status: NOT_EVALUATED (no benchmark run).**

- No benchmark corpus was constructed. The planned **1,200-question benchmark**
  (§29), its baselines, and its ablations were **not built and not executed**.
- Every quantitative target in the R1 spec — e.g. unsupported-claim-reduction
  rates, replay-agreement rates, adversarial-detection rates, throughput and
  speedup figures — remains an **experimental objective**, not a measured outcome.
- The *mechanisms* the hypotheses concern are implemented and unit/integration
  tested, but a tested mechanism is not a confirmed hypothesis. Reporting any
  H1–H12 number as achieved would be fabrication.

No hypothesis in R1 is EXPERIMENTALLY_SUPPORTED or EXPERIMENTALLY_UNSUPPORTED.
All twelve are NOT_EVALUATED.

---

## 2. Native compute backends — C++/Metal NOT_IMPLEMENTED

**Status: NOT_IMPLEMENTED.**

- Only the **CPU-first `PythonReferenceBackend`** exists. It is complete, tested,
  and serves as the `REFERENCE` validation baseline — but it is the *only* backend.
- The **C++ `NativeCPUBackend`** (pybind11) and the **Objective-C++/Metal
  `MetalComputeBackend`** are **designed only** (`native-computing-architecture.md`
  §6), not built. The `backends/cpu/` and `backends/metal/` trees are placeholders.
- Consequently, the **CPU/GPU parity harness** (§8.3) has **nothing to compare**:
  no `deterministic_fp` kernels exist, no max abs/rel error has been measured, and
  no backend other than the reference has a `BackendValidation` status.
- Any performance, throughput, or speedup claim tied to native/accelerated
  backends is **NOT_EVALUATED** — there is no accelerated code to benchmark.
- Note: Linux operation never depending on Metal is satisfied *trivially* (there
  is no Metal), not by demonstrated cross-platform parity.

---

## 3. Live integration (agent / API / frontend) — NOT_IMPLEMENTED

**Status: NOT_IMPLEMENTED for the live path; the R1 pipeline is proven only by the
integration test, not by the default live path.**

- The end-to-end R1 pipeline (native compute → evidence graph → admission →
  certificate → verified NL answer) is exercised **only** by
  `tests/test_r1_integration.py`. That is a test harness, **not** the running
  product.
- The **live research agent** does not use the R1 verified-answer pipeline. The
  existing `strix ask` (v0.2.0) path is **unchanged**;
  `strix.answering.pipeline.answer_question` is **not the default live path**.
- The **FastAPI API** and **React frontend** do **not** surface R1 verified
  answers, certificates, evidence graphs, or ledgers.
- **CLI:** only `strix compute backends` / `strix compute operations` are wired.
  The RUN_ID-scoped inspection commands (`graph` / `verify` / `audit` /
  `certificate` / `authorization` / `outcome`) are **not wired**, because the
  research loop does not yet persist R1 evidence graphs/ledgers per run.
- **Durable replay:** R1 evidence-graph/ledger replay is unit-tested inside
  `strix.audit` but is **not wired** to the job lifecycle. Existing STRIX replay
  is unchanged.

The takeaway: a reader must not infer that STRIX, as a running system, currently
answers user questions through the verified pipeline. It does not yet.

---

## 4. Genuine-source demonstrations (§31) — NOT_EVALUATED / NOT_IMPLEMENTED

**Status: demonstrations A–G NOT executed; §22 connectors NOT added.**

- Demonstrations **A–G** were **not run against live authoritative sources**. The
  integration test uses **synthetic fixtures** — it is a *pipeline* proof, not a
  *live-data* demonstration.
- No new **§22 connectors** (e.g. USAspending, SAM, USGS) were added. The system
  cannot currently pull from those genuine sources.
- Therefore no claim about real-world data coverage, source freshness on live
  feeds, or behavior on authentic adversarial documents is supported. All such
  behavior is **NOT_EVALUATED** on genuine data.

**Synthetic-fixture caveat (applies throughout R1):** every demonstration of the
pipeline to date runs on fabricated, hand-controlled inputs chosen to exercise
specific code paths (including a deliberately fabricated figure shown to be
rejected). This proves the *mechanism behaves as specified on those fixtures*. It
does **not** establish behavior, accuracy, or robustness on real-world inputs.

---

## 5. Content-addressing is not cryptographic signing

**Status: IMPLEMENTED as content-addressing; signing is NOT_IMPLEMENTED.**

Certificate and result integrity in R1 is **content-addressing** (SHA-256 content
hashes), **not** cryptographic signatures. This has concrete, documented
consequences:

- **No authenticity / origin guarantee.** A content hash proves *what* the bytes
  are, not *who* produced them. Nothing in R1 cryptographically binds a
  certificate or node to an authenticated issuer. An attacker who can write nodes
  can produce internally-consistent, correctly-hashed content.
- **Freshness is best-effort, not provable.** Strong point-in-time freshness
  requires signed, timestamped certificates. R1 anchors freshness on the
  identity-protected `applicable_temporal_cutoff` (falling back to best-effort
  `issued_at`); this resists one tampering class but is **not** a cryptographic
  freshness proof (R1 §13.5).
- Cryptographic signing of certificates and manifests is **explicitly future
  work**. Until then, the trust model must be read with the content-addressing
  caveat in force.

---

## 6. Predicate integrity trusts backend-produced nodes

**Status: known trust-model boundary.**

The integrity predicate **hash-checks only the factory-built node types**
(`SourceObservation`, `CandidateClaim`). **Backend-produced nodes**
(`SourceFact`, `Evidence`, `CalculationResult`, `ComputationResult`,
`SourceArtifact`) are **trusted** under the stated trust model (R1 §9.4).

Implications:

- A valid content hash **does not establish truth** — content integrity ≠ semantic
  truth (R1 §11 inv. 6). The system verifies structure and consistency, not that a
  backend told the truth about the world.
- The verifier's guarantees are **conditional on the honesty of the compute
  backends** that emit those node types. A compromised or buggy backend that emits
  well-formed, correctly-hashed nodes is **within** the trusted perimeter and is
  **not** caught by integrity checks.
- Closing this gap (cryptographic attestation of backend-produced nodes) is future
  work and is tied to §5 above.

---

## 7. Tolerance-based agreement is not bitwise reproducibility

**Status: by design; a reproducibility limitation to state plainly.**

- Descriptive / time-series / multivariate statistics are classified `tolerance`,
  **not** `exact`. Agreement is decided by
  `within_tolerance(observed, expected, contract)` = `abs_tol + rel_tol·|expected|`.
- **Tolerance-based agreement is explicitly NOT bitwise reproducibility**
  (R1 §7.1). Two conforming backends may produce *different* bit patterns that both
  pass the contract. Only the `exact` class (checked integer / exact Decimal sums)
  is bitwise identical.
- The `deterministic_fp` class (bitwise under a pinned environment) is **reserved**
  for the C++/Metal kernels that **do not exist yet** (see §2) — so no
  deterministic-FP reproducibility has been demonstrated.
- Cross-checks against Python stdlib (`rel-tol < 1e-9`) and hand-computed values
  are **engineering validation of the Python reference**, not a cross-backend
  reproducibility result and not scientific validation.

---

## 8. What the tests do and do not establish

**Measured engineering outcome (real):** `1430 passed, 2 skipped, 2 xfailed`
(from an `862 passed` baseline → **+568 R1 tests**), **0 regressions**, `ruff`
zero, `mypy --strict` clean on the 31 R1 source modules. Independent adversarial
review found and fixed **11 real defects** (including 2 critical verification
bypasses).

**What that establishes:** the implemented mechanisms behave as specified on their
test inputs and the specified security properties hold against the attacks that
were tried; the exact-arithmetic layer agrees with an independent reference within
tolerance.

**What it does NOT establish:**

- that the mechanisms improve real-world research trustworthiness (needs §29);
- that the hypotheses hold (H1–H12 NOT_EVALUATED, §1);
- universal correctness — adversarial review tried specific attacks and cannot
  enumerate all of them; "could not break" means "was not broken by the attempts
  made," not "is unbreakable";
- that the §11 invariants are **proven** — they are **tested properties**, not
  machine-checked proofs (R1 §11 caveat).

---

## 9. Scope items not built

- **Adaptive acquisition optimizer (§15, WS5)** — NOT_IMPLEMENTED as a new
  strategy layer; the existing agent's bounded budgeted loop remains.
- **Research docs** — PARTIAL (8 documents); not the complete §12 documentation set.
- **FALCON alignment / NSF pitch (§21/§33)** — NOT_PRODUCED. Any such material, if
  later written, is **proposed alignment only** and must never be stated as
  endorsement, eligibility, or funding (see §11).

---

## 10. Established methods are not independently novel

The building blocks R1 composes — covariance, EWMA, regression, confidence
intervals, bootstrap, GPU/accelerated numerical computing, content-addressing,
hash-chained logs, and deterministic policy enforcement — are **standard,
well-established** mathematical, statistical, and computing methods. **None is
claimed as independently novel.**

The *proposed* contribution is their **composition** into independently-verified,
resource-bounded research and execution assurance (R1 §33). Even that
composition's value is a **proposal under evaluation**, not a demonstrated or
established result: it has not been benchmarked (§1), and no novelty or prior-art
search has been performed. No patentability is claimed or implied.

---

## 11. No legal, scientific, or government status

To be unambiguous, R1 does **not** confer or imply any of the following, and none
may be represented on the basis of this work:

- **Scientific validation** — see §0, §1, §8. The hypotheses are unevaluated.
- **Novelty or patentability** — see §10. No prior-art or novelty analysis exists.
- **Statistical significance** — no benchmark, no sample, no significance test.
- **Government endorsement** — no government body has reviewed or endorsed this work.
- **Solicitation / program eligibility** — no eligibility determination exists; any
  alignment language is proposed only.
- **Funding** — no funding is associated with R1.

Any external communication derived from R1 must preserve these boundaries verbatim.

---

## 12. Repository status (for honest attribution)

- Branch `research/formal-evidence-verification`, **all work uncommitted**, not
  merged, not deployed.
- No secrets committed; no live external execution enabled; no production deploy.
- The results above describe a local research branch, not a released system.

---

### Summary table

| Item | Status |
|---|---|
| H1–H12 hypotheses | **NOT_EVALUATED** |
| 1,200-question benchmark / baselines / ablations | **NOT_EVALUATED** |
| C++ NativeCPUBackend / Metal backend / parity harness | **NOT_IMPLEMENTED** |
| Live agent / API / frontend R1 integration | **NOT_IMPLEMENTED** (test-only proof) |
| RUN_ID-scoped CLI inspection commands | **NOT_IMPLEMENTED** |
| Genuine-source demonstrations A–G | **NOT_EVALUATED** |
| New §22 connectors | **NOT_IMPLEMENTED** |
| Cryptographic signing of certificates/nodes | **NOT_IMPLEMENTED** (content-addressing only) |
| Backend-produced node integrity | **Trusted** (not verified) |
| Bitwise cross-backend reproducibility | **Not established** (tolerance-based) |
| Adaptive acquisition optimizer (§15) | **NOT_IMPLEMENTED** |
| Native CPU reference + evidence graph + GAP cores + answering | IMPLEMENTED/TESTED (engineering only) |
| Scientific validation / novelty / significance / gov eligibility / funding | **None — not claimed** |

## R2/R3 limitations (added after R2 assurance + R3 ledger core)

- **Transfer matching false positives (R3, `finance/transfers.py`):** internal-transfer
  matching uses only amount magnitude, opposite sign, a different owned account,
  and the date window. With no corroborating signal (counterparty/memo), two
  *unrelated* genuine transactions of equal magnitude within the window can be
  wrongly matched as a transfer, hiding both from income/expense. A `TransferMatch`
  is a **candidate for review**, not a confirmed transfer; production use must
  corroborate. (The greedy-vs-maximum-matching bug is fixed; this is an inherent
  heuristic limitation, not a bug.)
- **Live account aggregation (R3-app):** Plaid/Teller/SnapTrade connectors, the
  React dashboard, monthly-automation scheduling, portfolio intelligence, and the
  conversational assistant are **NOT_IMPLEMENTED** — they require real credentials
  and real financial PII. Only the offline ledger engine (double-entry, CSV import,
  transfer matching, anomaly) is built and tested on synthetic data.
- **Cryptographic freshness (R2-E):** certificate signing is Ed25519 (implemented);
  but certificate *freshness* under content-addressing still anchors on an
  identity-protected field, and full key lifecycle (HSM/KMS custody) is deployment
  work, not implemented here.
- **Governed lifecycle live wiring (R2-A):** the governed lifecycle composes all
  six pillars + audit over *already-admitted findings*; wiring the live research
  agent's evidence collection into that seam is **NOT_IMPLEMENTED**.
- **C++/Metal backends, live-LLM benchmark (H1–H12), FSIP integration, hosted
  deployment:** **NOT done** — toolchain/credentials/infra-gated; see
  `milestone-tracker.md`.
