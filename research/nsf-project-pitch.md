# NSF Project Pitch — PRELIMINARY DRAFT PREMISE

**Resource-Bounded Typed Evidence Verification for Trustworthy Autonomous AI**

---

> ## ⚠ DRAFT STATUS — READ FIRST
>
> **This document is a preliminary, internal DRAFT premise. It is NOT a
> submission, NOT a proposal, and NOT a solicitation response.**
>
> Nothing in this document should be read as a claim of any of the following:
>
> - **No eligibility claim.** We do not assert that STRIX, its authors, or any
>   associated entity are eligible for any NSF program, solicitation, or funding
>   mechanism. Program eligibility must be independently determined against the
>   governing solicitation.
> - **No prior-art or patentability claim.** We do not assert novelty, prior-art
>   clearance, patentability, or any intellectual-property position. The
>   contribution described here is a *composition* of established methods (R1 §33),
>   not an assertion that any component is independently novel.
> - **No funding or award claim.** No funding has been sought, offered, or
>   received. No government endorsement exists or is implied.
> - **No statistical-significance claim.** The research hypotheses (H1–H12) are
>   **NOT_EVALUATED**. No benchmark has been run; no measured outcome supports any
>   performance assertion.
>
> This draft exists to articulate a research *premise* — the question, the gap,
> and the proposed approach — in a form that could later be refined if and only if
> a genuine opportunity and eligibility are independently established.

---

## 1. Classification key

Per the Milestone R1 report (§37), every material item below is classified:

| Tag | Meaning |
|---|---|
| **IMPLEMENTED** | Code exists in the R1 branch. |
| **TESTED** | Exercised by unit/integration tests with measured pass results. |
| **NOT_IMPLEMENTED** | Designed/scaffolded but not built. |
| **NOT_EVALUATED** | No measurement or benchmark has been run. |
| **BLOCKED** | Cannot proceed without an external dependency. |

The research hypotheses this pitch would test (H1–H12) are **NOT_EVALUATED**
without exception. The C++/Metal native backends, the live agent/API/frontend
integration, the 1,200-question benchmark, and the genuine-source demonstrations
are **NOT_IMPLEMENTED** or **NOT_EVALUATED**. This is stated plainly wherever
those items are relevant.

---

## 2. Research question

**Can an autonomous AI research system be constrained so that every material
factual assertion it emits is independently verifiable, resource-bounded, and
auditable — such that unsupported or fabricated claims are rejected before they
reach a human decision-maker, rather than detected afterward?**

Sub-questions that would structure the proposed program:

1. Can *typed admission predicates*, evaluated independently of the generating
   agent, reduce the rate of unsupported assertions relative to an
   agent-self-report baseline? *(Proposed; H1-class; NOT_EVALUATED.)*
2. Can a *content-addressed, hash-chained decision ledger* provide
   deterministic replay agreement, so that a verification outcome can be
   reproduced bit-for-bit from recorded inputs? *(Proposed; NOT_EVALUATED.)*
3. Can *resource bounds* (compute/time/budget) be enforced without ever
   weakening a verification requirement — i.e., does exhaustion yield "abstain",
   never "accept"? *(Proposed; the mechanism is IMPLEMENTED/TESTED as an
   invariant; its behavior at benchmark scale is NOT_EVALUATED.)*

---

## 3. The gap

Contemporary autonomous AI research and analysis systems generate fluent
natural-language answers whose factual assertions are **not** bound to
independently checkable evidence. The dominant assurance pattern is *post-hoc*:
generate first, then attempt to detect hallucination or unsupported claims after
the fact. This is structurally fragile because:

- The entity that generates the claim is often the same entity trusted to grade
  it, collapsing the trust boundary.
- "Unknown" and "unverifiable" are frequently conflated with "false" or silently
  treated as "acceptable", so abstention is not a first-class outcome.
- Resource exhaustion (timeouts, budget caps) tends to *relax* checks rather than
  trigger a safe abstention, so the system fails open.
- Numeric assertions are rarely re-derived from their underlying computation;
  the model's *stated* number is trusted rather than *recomputed*.

The gap this premise addresses is the absence of a **composed, independently
enforced, resource-bounded admission discipline** in which the generating agent
controls only an untrusted candidate surface, and a separate verifier admits a
claim only when a fixed set of typed predicates all hold under a trusted policy.

**Important framing (R1 §33):** The individual building blocks — covariance,
EWMA, regression, bootstrap, GPU/accelerated numerical computing, content
addressing, deterministic policy enforcement, hash-chained logs — are
**established methods and are NOT asserted to be independently novel.** The
proposed intellectual contribution is their *composition* into an
independently-verified, resource-bounded assurance architecture for autonomous
research and execution. No patentability or prior-art position is claimed.

---

## 4. Proposed approach — composition of implemented mechanisms

The approach composes five mechanisms. Each is reported below with its *actual*
R1 implementation status. The **composition into a validated, hypothesis-tested
system is the proposed research** and is **NOT_EVALUATED**.

### 4.1 Typed evidence graph with five independent admission predicates
**Status: IMPLEMENTED / TESTED** (`src/strix/evidence_graph/`).

A candidate claim is admitted only if all five predicates hold under a trusted,
versioned policy:

```
A(c, G, P) = I(c,G) ∧ T(c,G,P) ∧ P_rov(c,G,P) ∧ D(c,G,P) ∧ S(c,G,P)
```

where **I** = integrity (references resolve, content hashes consistent),
**T** = type/temporal (unit + entity + metric match; point-in-time as-of;
freshness), **P** = provenance (complete lineage to a preserved source artifact),
**D** = derivation (each numeric assertion independently re-derived against its
backend computation within tolerance), **S** = support (each assertion cites
evidence that actually attests it). Predicates are independent pure functions
returning PASS/FAIL/UNKNOWN/NOT_APPLICABLE; a mandatory FAIL → REJECTED, a
mandatory UNKNOWN → ABSTAINED (never treated as pass). The outcome is
deterministic for identical normalized inputs. See `claim-admission-invariants.md`.

### 4.2 Native, CPU-first, exact-arithmetic quantitative layer
**Status: IMPLEMENTED / TESTED** for the Python reference backend
(`src/strix/native/`); **C++ and Metal backends are NOT_IMPLEMENTED.**

A portable CPU quantitative layer (descriptive/time-series/multivariate/inference
statistics, checked exact arithmetic, numerical contracts, a typed
content-addressed `ComputationResult`, and a `PythonReferenceBackend` exposing 27
operations as the validation baseline). Authoritative financial Decimals are
never converted to binary float. The C++/pybind11 and Objective-C++/Metal
backends and the CPU/GPU parity harness are **designed but not built**
(`native-computing-architecture.md`).

### 4.3 Evidence-bound deterministic authorization (GAP-001)
**Status: IMPLEMENTED / TESTED.** Ordered deterministic conditions
(`Auth = Iₐ∧Vₐ∧Cₐ∧Fₐ∧Bₐ∧Rₐ`), typed reject codes, idempotency/duplicate-action
guard, parameter-bound certificates, **external execution disabled by default**,
a sandbox executor, and independent outcome reconciliation. Live external
execution is **NOT enabled**.

### 4.4 Durable, hash-chained decision ledger (GAP-002)
**Status: IMPLEMENTED / TESTED.** Append-only, hash-chained ledger with
idempotent insert, `verify_chain` tamper/gap/broken-link detection, crash
recovery, and replay. Deterministic replay *agreement at benchmark scale* is a
proposed measurement and is **NOT_EVALUATED.**

### 4.5 Cross-resolution reconciliation, integrity, and anomaly screening (GAP-003)
**Status: IMPLEMENTED / TESTED.** Exact-Decimal reconciliation
(`r = observed − f(components)`), integrity checks, and IQR/z-score anomaly
screening that *flags for investigation* and never auto-rejects.

### 4.6 Answer-first synthesis + independent response validation
**Status: IMPLEMENTED / TESTED (deterministic path); live integration
NOT_IMPLEMENTED.** Deterministic synthesis from admitted findings only; every
factual assertion binds to an admitted claim certificate; independent
fail-closed response validation strips unsupported assertions. The end-to-end
pipeline (native compute → evidence graph → admission → certificate → verified
NL answer) is proven by a synthetic-fixture integration test in which a
fabricated figure is shown to be rejected and never answered. **It is not wired
into the live agent, API, or frontend.**

---

## 5. What would be evaluated (and is NOT yet)

The proposed research program would, if pursued, construct and run the
evaluation that R1 explicitly did **not** perform:

| Item | R1 status |
|---|---|
| 1,200-question benchmark corpus | **NOT_IMPLEMENTED** |
| Baselines + ablations (§29) | **NOT_EVALUATED** |
| Hypotheses H1–H12 (e.g., unsupported-claim reduction, replay agreement, adversarial-detection rate, throughput/speedup) | **NOT_EVALUATED** |
| Genuine-source demonstrations A–G against live authoritative sources | **NOT_IMPLEMENTED / NOT_EVALUATED** |
| C++ NativeCPUBackend + CPU/GPU parity harness; Metal backend | **NOT_IMPLEMENTED** |
| Live agent / API / frontend integration of the verified-answer pipeline | **NOT_IMPLEMENTED** |

No numeric target in this document has been measured. Any figure appearing in the
R1 spec as an objective (e.g., a claim-reduction percentage or a replay-agreement
rate) is an **experimental objective**, not a result, and is reported as
**NOT_EVALUATED**. Reporting such a target as an outcome would be fabrication.

---

## 6. Proposed intellectual merit (framed as PROPOSED)

The following are *proposed* lines of inquiry. They are hypotheses to be tested,
not findings.

- **Independent verification as an architectural primitive.** The premise
  proposes evaluating whether *separating* the untrusted generating surface from
  a trusted, typed admission function measurably improves the reliability of
  autonomous research output, versus agent self-grading. *(PROPOSED;
  NOT_EVALUATED.)*
- **Abstention as a first-class outcome.** The premise proposes measuring whether
  treating UNKNOWN as ABSTAINED — never as pass or false — reduces confident-but-
  wrong assertions without unacceptably lowering coverage. *(PROPOSED;
  NOT_EVALUATED.)*
- **Resource-bounded fail-safety.** The premise proposes testing whether an
  explicit invariant ("exhaustion never weakens a requirement") holds under
  adversarial budget pressure at scale. *(The invariant is IMPLEMENTED/TESTED in
  unit form; its behavior at benchmark scale is NOT_EVALUATED.)*
- **Reproducibility via content addressing + hash chaining.** The premise
  proposes quantifying deterministic replay agreement across a full corpus.
  *(PROPOSED; NOT_EVALUATED.)*

The methodological contribution — again, *proposed*, not claimed as novel — is
the **composition** of these established techniques into a single, falsification-
first, auditable assurance pipeline, and the empirical characterization of that
composition under adversarial conditions.

## 7. Proposed broader impacts (framed as PROPOSED)

- **Trustworthy AI for high-stakes analysis.** If the hypotheses were supported,
  the approach could inform how autonomous systems in evidence-sensitive
  domains bind claims to verifiable provenance. *(PROPOSED; NOT_EVALUATED.)*
- **Open, reproducible evaluation artifacts.** The proposed benchmark and
  ablation harness, if built, would be designed for independent reproduction;
  negative findings would be preserved, consistent with falsification-first
  practice. *(PROPOSED; the benchmark is NOT_IMPLEMENTED.)*
- **Auditability as a public good.** A durable, tamper-evident decision ledger
  is proposed as a pattern for after-the-fact scrutiny of autonomous decisions.
  *(PROPOSED.)*

No claim is made that these impacts have been realized, demonstrated, or
measured.

## 8. Known limitations and trust-model boundaries (honest)

- **Content addressing ≠ cryptographic authenticity.** Integrity is established
  by content hashing, not digital signatures. A valid content hash does **not**
  establish truth. Cryptographic signing of backend-produced nodes and manifests
  is **future work** (R1 §13.5, §10 limits).
- **Tested properties ≠ machine-checked proofs.** The compositional invariants
  (§11) are *tested*, not formally verified (R1 §11 caveat).
- **No live demonstration.** The integration test uses synthetic fixtures. No
  live authoritative-source demonstration has been executed.
- **Falsification record.** Independent adversarial review found and fixed real
  defects during R1 (including two critical verification bypasses — metric
  relabeling and an untrusted point-in-time cutoff). This is reported as evidence
  of the falsification-first process, not as proof of correctness.

## 9. Status summary

| Component | Status |
|---|---|
| Typed evidence graph + 5 predicates + 4 certificate classes + §11 invariants | IMPLEMENTED / TESTED |
| Native CPU quantitative layer (Python reference, 27 ops) | IMPLEMENTED / TESTED |
| GAP-001 authorization (external execution disabled) | IMPLEMENTED / TESTED |
| GAP-002 hash-chained decision ledger | IMPLEMENTED / TESTED |
| GAP-003 reconciliation / integrity / anomaly screening | IMPLEMENTED / TESTED |
| Answer synthesis + independent response validation (deterministic path) | IMPLEMENTED / TESTED |
| End-to-end pipeline proof (synthetic fixtures) | IMPLEMENTED / TESTED |
| C++ NativeCPUBackend / Metal backend / parity harness | NOT_IMPLEMENTED |
| Live agent / API / frontend integration | NOT_IMPLEMENTED |
| 1,200-question benchmark + baselines + ablations | NOT_IMPLEMENTED |
| Hypotheses H1–H12 | NOT_EVALUATED |
| Genuine-source demonstrations A–G | NOT_IMPLEMENTED / NOT_EVALUATED |
| Eligibility / prior-art / patentability / funding | NO CLAIM MADE |

---

*End of preliminary draft premise. This document makes no eligibility, prior-art,
patentability, novelty, statistical-significance, endorsement, solicitation, or
funding claim. Experimental validation (H1–H12) is outstanding and NOT_EVALUATED.*
