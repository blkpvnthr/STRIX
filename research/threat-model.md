# STRIX R1 — Threat Model & Trust Boundaries (R1 §27)

**Milestone:** R1 — Resource-Bounded Typed Evidence Verification for Trustworthy
Autonomous AI
**Branch:** `research/formal-evidence-verification` (cut from `feat/milestone-0b`
`849018d`; **uncommitted**, not merged, not deployed)
**Date:** 2026-11-24

**Classification key (§37):** IMPLEMENTED · TESTED · NOT_IMPLEMENTED ·
NOT_EVALUATED · BLOCKED.

> This document describes the trust architecture **as built** in R1 and the
> attacks that were **actually run** by independent adversarial review. It does
> not claim universal correctness, completeness, novelty, patentability,
> statistical significance, government endorsement, solicitation eligibility, or
> funding. Hypotheses H1–H12 are **NOT_EVALUATED**. The C++/Metal backends, the
> live agent/API/frontend integration, the 1,200-question benchmark, and the
> genuine-source demonstrations are **NOT done** (see `milestone-r1-report.md`
> §7–§9); claims below are scoped accordingly.
>
> The contribution is not any single mathematical method. Covariance, EWMA,
> regression, GPU computing, and deterministic policy enforcement are
> established and are **not independently novel**. The proposed contribution is
> their **composition** into independently-verified, resource-bounded research
> and execution assurance (R1 §33) — and that composition is argued here, not
> empirically demonstrated.

---

## 1. Purpose and scope

The adversary of interest is **the agent's own reasoning**: a large language
model that may hallucinate figures, mislabel metrics, cite the wrong evidence,
use future information to answer point-in-time questions, or request actions it
should not be authorized to take. R1's design premise (R1 §4, §9.4, §21) is that
the LLM is **untrusted for anything load-bearing** — it may *propose* but may
never *decide*.

This threat model therefore documents:

1. the trust boundaries that separate proposal from decision (§2–§3);
2. the exact untrusted surface the agent controls (§4);
3. the attacks adversarial review actually executed, the defects found, and the
   fixes applied (§5);
4. the residual risks that remain **by design** or **by omission** (§6).

Out of scope for R1 (and therefore for this model, except as named residual
gaps): network/host hardening, secrets management beyond "no secrets
committed," multi-tenant isolation, and any live external execution (disabled by
default — §6.3).

---

## 2. Trust boundaries (R1 §27)

R1 separates the pipeline into layers of **decreasing trust-in-the-model** and
**increasing authority**. A value may only *gain* authority by crossing a
boundary that an independent, trusted component controls.

```
 UNTRUSTED                                                           TRUSTED
┌───────────────┐   proposes   ┌───────────────┐   emits   ┌──────────────────┐
│  LLM          │─────────────▶│ Native        │──────────▶│ Independent       │
│  reasoning    │  (claims,    │ computation   │ typed     │ verification      │
│  (agent)      │   action     │ (strix.native)│ Computa-  │ (evidence_graph:  │
│               │   requests)  │               │ tionResult│  5 predicates +   │
└───────────────┘              └───────────────┘           │  admit + §11 inv.)│
   can propose,                 computes, cannot            └────────┬─────────┘
   cannot decide                 assign verdicts                     │ admitted
                                                                     │ claim cert
                                                        ┌────────────▼─────────┐
                                                        │ Authorization        │
                                                        │ (GAP-001 assurance)  │
                                                        │ Auth = Iₐ∧Vₐ∧Cₐ∧     │
                                                        │       Fₐ∧Bₐ∧Rₐ       │
                                                        └────────────┬─────────┘
                                                                     │ auth cert
                                                        ┌────────────▼─────────┐
                                                        │ Execution (sandbox;  │
                                                        │ external OFF by      │
                                                        │ default) + outcome   │
                                                        │ certification (§20)  │
                                                        └────────────┬─────────┘
                                                                     │ events
                                                        ┌────────────▼─────────┐
                                                        │ Persistence          │
                                                        │ (GAP-002 hash-chained │
                                                        │  ledger) + GAP-003    │
                                                        │  reconciliation       │
                                                        └──────────────────────┘
```

| # | Boundary | Trusted side owns | The model/agent may NOT | Status |
|---|---|---|---|---|
| B1 | **LLM reasoning → native computation** | the computation itself; numbers come from the backend, not the prompt | supply the numeric result of a computation; the backend recomputes | IMPLEMENTED/TESTED (`strix.native`) |
| B2 | **Native computation → independent verification** | the five admission predicates + `admit` under a trusted, versioned `VerificationPolicy` | assign a verdict, mark a predicate `NOT_APPLICABLE`, or relax the as-of | IMPLEMENTED/TESTED (`strix.evidence_graph`) |
| B3 | **Verification → authorization** | GAP-001 deterministic conditions bound to admitted claim certificates | authorize on self-asserted evidence; only admitted claims back an action | IMPLEMENTED/TESTED (`strix.assurance`) |
| B4 | **Authorization → execution** | sandbox executor; external execution disabled by default; outcome certification (§20) | execute without a valid, fresh, parameter-bound authorization cert | IMPLEMENTED/TESTED (sandbox only; live execution NOT_IMPLEMENTED) |
| B5 | **Execution → persistence** | GAP-002 append-only hash-chained ledger; GAP-003 reconciliation | rewrite history; tamper is detectable by `verify_chain` | IMPLEMENTED/TESTED (`strix.audit`, `strix.reconciliation`) |

The defining property across B1–B5: **the untrusted side can only move a value
forward by producing an artifact the trusted side independently checks.** No
boundary accepts a verdict, authorization, or ledger entry on the agent's word.

---

## 3. Who assigns verdicts (the decision monopoly)

Verdict assignment is the crux of the trust model (R1 §10.6, §11 invariant 7).

- A `CandidateClaim` and its `Assertion`s **carry no status field** — there is
  structurally no place for the agent to write a verdict.
- Only predicate logic + the trusted `VerificationPolicy` produce
  PASS/FAIL/UNKNOWN/NOT_APPLICABLE, and only `admit` maps those to a terminal
  verdict (ADMITTED / REJECTED / ABSTAINED).
- UNKNOWN is **never** treated as pass or as false (ABSTAINED → `UNVERIFIABLE`).
- Admission is **deterministic** for identical normalized `(G, c, P)`.

This is implemented and tested (see `claim-admission-invariants.md`), and the
"self-asserted verdict injection" attack was confirmed **non-breaking** by
review.

---

## 4. Untrusted surface (the attack surface the agent controls)

Everything the LLM emits is untrusted input. Concretely, the agent controls
exactly two typed request surfaces:

### 4.1 `CandidateClaim` (into the verifier)

The agent may set only:

- the **assertions** (metric, entity, value, unit, observation interval);
- the **cited evidence ids** it believes support each assertion;
- a **`knowledge_cutoff`** it claims to have respected.

It explicitly **cannot**: assign a verdict; set a predicate to
`NOT_APPLICABLE`; relax the point-in-time as-of (the trusted
`policy.as_of_cutoff` governs; a claim's cutoff may only *tighten* it,
earliest-of); or relabel evidence (an assertion's `metric` must match the cited
evidence's attested metric/concept).

Because `value` is agent-controllable, it is **not trusted**: predicate **D
(derivation)** independently re-derives every numeric assertion against the
backend computation, and predicate **S (support)** requires the cited evidence
to actually attest the value/unit/metric/entity. A fabricated figure fails D
and/or S and is REJECTED — this is the path exercised by the end-to-end
integration test (fabricated figure proven rejected, never answered).

### 4.2 `ActionRequest` (into authorization)

For any action, the agent proposes parameters and the evidence it believes
justifies the action. GAP-001 then evaluates
`Auth = Iₐ ∧ Vₐ ∧ Cₐ ∧ Fₐ ∧ Bₐ ∧ Rₐ` in a fixed deterministic order with typed
reject codes. The agent cannot authorize itself: the authorization certificate
is bound to the **admitted** claim evidence and to the **exact** action
parameters (TOCTOU-aware `reauthorize`), and external execution is **disabled by
default**.

Everything else (policy, as-of cutoff, backend numerics, predicate logic,
certificate issuance, ledger, reconciliation) is on the trusted side and is
**not** agent-controllable.

---

## 5. Attacks actually run, defects found, and fixes (falsification evidence)

Independent, findings-only adversarial review workflows treated the agent as
untrusted and tried to break each subsystem. Every confirmed defect was fixed
TDD-style with a permanent regression test. These are **real executed reviews
with real fixes**, not hypotheticals. (Cross-reference: `milestone-r1-report.md`
§4; `claim-admission-invariants.md` §2.)

### 5.1 Verification-bypass attacks (CRITICAL)

| Attack | What it attempted | Outcome before fix | Fix | Regression test |
|---|---|---|---|---|
| **Metric relabeling** | cite real `operating_margin` evidence under a false `net_profit_margin` label | ADMITTED (forged metric) | `support`/`type_temporal` require `assertion.metric == _metric_of(evidence)`; mismatch → `metric_mismatch` → REJECTED | `tests/evidence_graph/test_eg_review_regressions.py` |
| **Untrusted point-in-time cutoff** | omit or set a far-future `knowledge_cutoff` to defeat the as-of check and answer with future information | bypassed point-in-time | cutoff taken from trusted `policy.as_of_cutoff`; claim may only tighten (earliest-of) | same file |
| **§11.16 multi-hop contract blocker** | back a claim through a **failed numerical contract** reached via a path longer than one hop, which the 1-hop check ignored | failed contract ignored → admissible | `_backing_computations` scans the **full evidence closure** | same file |

### 5.2 Numeric / durability attacks

| Subsystem | Severity | Defect | Fix |
|---|---|---|---|
| native `arithmetic.quantize` | CRITICAL | global decimal-context overflow → untyped crash on values ≥~1e16 (market-cap variance, wei, ns timestamps) | sized **local** context + typed error |
| native `inference._dec` | MINOR | same overflow ≥1e19 | same root fix |
| native `multivariate.ewma_covariance` | MAJOR | `0**0` crash at `alpha=1` | explicit newest-weight = 1 |
| GAP-002 **ledger unicode corruption** | MAJOR | `splitlines()` splits payloads on U+2028 / U+0085 / U+2029, corrupting hash-chained records | split on `\n` only |
| GAP-003 **reconciliation precision** | MAJOR | precision-28 reconstruction misclassifies large exact sums | exact `checked_sum` / `checked_sub` |

### 5.3 Authorization / outcome attacks

| Subsystem | Severity | Defect | Fix |
|---|---|---|---|
| GAP-001 **authorization freshness tamper** | MAJOR | freshness gated on the identity-**excluded** `issued_at`, so a stale authorization could be revived by tampering with that field | anchor freshness on the identity-**protected** `applicable_temporal_cutoff` |
| GAP-001 **outcome binding** | MINOR | outcome reconciler trusted executor-reported ids | independent certificate ↔ request digest check |

### 5.4 Attacks that could NOT be broken (confirmed robust by review)

Determinism of admission; self-asserted verdict injection; unknown-mandatory
never treated as pass; derivation re-reading the upstream computation rather than
the model-asserted number; and certificate tamper-detection on every
deterministic field. The certificates review was **clean**.

**Scope honesty.** These results are **engineering validation** against the
executed review workflows and the regression suite (`1430 passed, 2 skipped,
2 xfailed`; `+568 R1 tests`; `0 regressions`). They are **not** a proof of
universal soundness, **not** a measured adversarial-detection rate (that would
require the §29 benchmark — **NOT_EVALUATED**), and **not** a security
certification. "The review could not break X" means *this* review did not; it
does not mean X is unbreakable.

---

## 6. Residual risks (what remains, by design or omission)

These are stated plainly so no reader over-trusts the system.

### 6.1 Content-addressing is NOT signing

Certificate and result integrity is **content-addressing** (SHA-256 canonical
hashing), not cryptographic **signing**. Consequences:

- A content hash establishes *this content hashes to this id* — it does **not**
  establish authorship, authenticity, or truth (R1 §9.4: a valid content hash
  does not establish truth).
- Fields that are **excluded from identity** (e.g. timestamps and other
  nondeterministic metadata) are **forgeable** without detection, because they
  do not participate in the hash. The authorization-freshness fix (§5.3)
  specifically moved the freshness anchor *onto* an identity-protected field for
  this reason; strong freshness guarantees still require **signed** certificates.
- There is no key, no signature, and no non-repudiation. An actor who can write
  to storage can fabricate a well-formed, hash-consistent record.

**Status:** cryptographic signing of certificates/manifests is **NOT_IMPLEMENTED**
and is explicitly future work (R1 §13.5; `milestone-r1-report.md` §11.5).

### 6.2 Integrity hash-checking covers only factory-built node types

Predicate **I (integrity)** content-hash-verifies only the **factory-built**
node types (`SourceObservation`, `CandidateClaim`). Backend-produced nodes
(`SourceFact`, `Evidence`, `CalculationResult`, `ComputationResult`,
`SourceArtifact`) are **trusted under the stated trust model** — a valid content
hash on them does not establish truth, and they are not independently
re-verified at the integrity layer. If a backend-produced node were tampered or
wrong, the derivation/support predicates provide defense for *numeric* claims,
but there is no content-integrity guarantee on those node types themselves.

**Status:** signing of backend-produced nodes is **NOT_IMPLEMENTED** (future
work). See `claim-admission-invariants.md` §3 "Limits."

### 6.3 No live external execution

External execution is **disabled by default**. The execution boundary (B4) is
validated only through the **sandbox** executor and synthetic fixtures; no live
broker, API, or side-effecting action was wired or run in R1. The §20 outcome
certification exists and is tested against the sandbox, but outcome binding
against a **real** external effect is **NOT_EVALUATED**.

**Status:** live agent/API/frontend integration and live execution are
**NOT_IMPLEMENTED** (`milestone-r1-report.md` §8).

### 6.4 Other scope-limited assurances

- **Tested properties, not proofs.** The §11 compositional invariants are
  *tested properties*, not machine-checked proofs (R1 §11 caveat). Coverage is
  bounded by the test corpus.
- **Policy is trusted and unsigned.** `VerificationPolicy` (including
  `as_of_cutoff` and `mandatory_predicates`) is on the trusted side; its
  integrity depends on repository/deployment controls, not on any in-band
  cryptographic guarantee.
- **No benchmark-measured efficacy.** H1–H12, the 1,200-question benchmark,
  baselines, and ablations are **NOT_EVALUATED**. Any adversarial-detection or
  unsupported-claim-reduction rate is unmeasured; do not cite one.
- **Genuine-source demonstrations not executed.** The end-to-end proof uses
  synthetic fixtures; demonstrations A–G against live authoritative sources are
  **NOT done** (`milestone-r1-report.md` §7).
- **Computation-backed assertions trust claim-declared entity/metric.** A bare
  `ComputationResult` attests a *value* but no entity or metric; the `support`/
  `type_temporal` predicates therefore rest the entity/metric *labels* of a
  computation-backed assertion on the (untrusted) claim's declared `subject_id`/
  `metric`, not on independent attestation. An adversary can relabel a correct
  computed value under a wrong entity/metric. Closing this requires binding
  computations to entity-attesting provenance; it is scheduled as an **additive**
  institutional-admissibility check (requirement `DTEC-R-N6-BIND`) that never weakens
  the base predicate. Until then this is a known residual risk for computation-backed
  claims. (Confirmed by independent adversarial review; detail in the confidential
  research record.)

---

## 7. Summary

R1 implements a layered trust architecture (B1–B5) in which the LLM may propose
but never decide: numeric values are recomputed by the native layer, verdicts
are monopolized by an independent verifier under a trusted policy, actions are
gated by evidence-bound deterministic authorization, execution is sandboxed and
external effects are off by default, and history is hash-chained and reconciled.
Independent adversarial review **ran real attacks** against this architecture and
found **real defects** — two critical verification bypasses, three
numeric/durability bugs, and two authorization/outcome defects — all fixed with
permanent regression tests. The principal residual risks are that
**content-addressing is not signing** (identity-excluded fields are forgeable;
no authenticity/non-repudiation), that **integrity hashing covers only
factory-built node types**, and that **there is no live external execution yet**.
Signing, live integration, and the §29 benchmark-based efficacy evaluation are
future work and must not be reported as done.
