# Mathematical Specification (R1)

**Milestone:** R1 — Resource-Bounded Typed Evidence Verification for Trustworthy Autonomous AI
**Branch:** `research/formal-evidence-verification` (uncommitted; not merged; not deployed)
**Baselines:** STRIX `849018d`; C-engine `3a23b13` (read-only extraction source)
**Date:** 2026-11-24

**Status key (per `milestone-r1-report.md` §37):**
IMPLEMENTED · TESTED · NOT_IMPLEMENTED · NOT_EVALUATED · BLOCKED.

---

## 0. Scope and honesty preface

This document **formalizes what R1 actually implements** in the Python reference
layer. It is a specification of the typed structures, predicates, and composition
rules that are present and unit/integration-tested in
`src/strix/evidence_graph/`, `src/strix/assurance/`, `src/strix/reconciliation/`,
`src/strix/answering/`, and `src/strix/native/`.

Non-negotiable caveats, which apply to every statement below:

- **These are tested properties, not machine-checked proofs.** No theorem prover,
  model checker, or formal-methods toolchain was applied. Each "invariant" named
  here is a property for which executable tests exist; it is not a verified
  mathematical theorem over all inputs (R1 §11 caveat).
- **No empirical claims.** No benchmark, accuracy, speedup, detection-rate, or
  statistical-significance result is asserted. Hypotheses **H1–H12 are
  NOT_EVALUATED**. Any threshold appearing in the R1 spec (e.g. reduction rates,
  replay-agreement rates) is an *experimental objective*, not a measured outcome.
- **No novelty / patentability / endorsement / funding / solicitation-eligibility
  claims.** The underlying mathematical and statistical methods (covariance,
  EWMA, regression, GPU computing, deterministic policy enforcement) are
  **established and not independently novel**. The proposed contribution is their
  **composition** into independently-verified, resource-bounded research and
  execution assurance (R1 §33) — and that contribution is proposed and
  partially implemented, not empirically validated.
- **The §15 acquisition-optimization objective is PROPOSED / NOT_IMPLEMENTED.**
  It is stated below in §7 for completeness and is explicitly marked as not built.
- The C++/Metal backends, the live agent/API/frontend integration, the
  1,200-question benchmark, and the genuine-source demonstrations are **not done**;
  where the formalism references them, they are marked accordingly.

Notation: `∧` logical conjunction; `Σ` summation; `|·|` absolute value; `τ` a
typing function; `π` a provenance/attribute function. All authoritative numeric
quantities are exact `Decimal` or exact integers unless a `float64` contract class
is stated (§6).

---

## 1. The typed evidence graph `G = (V, E, τ, π)`

**Status: IMPLEMENTED / TESTED** (`src/strix/evidence_graph/`).

The verification substrate is a typed directed graph

```
G = (V, E, τ, π)
```

where:

- `V` — the set of **nodes** (evidence objects). Each node is a frozen,
  content-addressed `StrixModel` with an identity derived by `canonical_hash`
  over its deterministic fields. Node types (the range of `τ`) include:
  - `SourceArtifact` — a preserved, raw source document/record;
  - `SourceObservation` / `SourceFact` — an extracted observation or fact;
  - `Evidence` — an attesting evidence item (value, unit, metric, entity, interval);
  - `ComputationResult` / `CalculationResult` — a typed analytical output (§6, §5);
  - `CandidateClaim` — an **untrusted** claim proposed by the research agent.
- `E ⊆ V × V` — the set of **directed edges** encoding relations, notably the
  **derivation / provenance** relations (an assertion derives from a computation;
  a computation derives from observations; an observation derives from an
  artifact) and the `CONTRADICTED_BY` relation.
- `τ : V → Type` — the **typing function** assigning each node its evidence type.
- `π : V → Attributes` — the **attribute/provenance function** exposing a node's
  deterministic attributes (unit, metric, entity, observation interval, applicable
  knowledge cutoff, backend id, numerical contract, lineage references, etc.).

### 1.1 Structural properties (IMPLEMENTED / TESTED)

- **Referential integrity.** Every edge endpoint and every referenced node id
  resolves to a node present in `G`.
- **Acyclic derivation subgraph.** The derivation/provenance subgraph is a DAG;
  acyclicity is checked by an **iterative DFS** (converted from a recursive form
  that raised `RecursionError` on deep chains — see `claim-admission-invariants.md`
  §2).
- **Deterministic graph hashing.** `G` has a deterministic content hash over its
  normalized nodes and edges, excluding nondeterministic metadata.
- **Closure traversal.** For any node, its full upstream **evidence closure**
  (all transitive derivation/provenance ancestors) is computable; predicates that
  must reason about lineage scan the *entire* closure, not a single hop.

---

## 2. The admission function `A(c, G, P)`

**Status: IMPLEMENTED / TESTED** (`evidence_graph` predicates + `admit`;
see `claim-admission-invariants.md`).

A candidate claim `c` (an untrusted `CandidateClaim`) is admitted into the
verified graph `G` under a **trusted, versioned verification policy `P`** iff all
five independent admission predicates hold:

```
A(c, G, P) = I(c, G) ∧ T(c, G, P) ∧ P_rov(c, G, P) ∧ D(c, G, P) ∧ S(c, G, P)
```

| Symbol | Predicate (R1 §) | Returns |
|---|---|---|
| `I`  | Integrity (§10.1)        | PASS / FAIL / UNKNOWN / NOT_APPLICABLE |
| `T`  | Type–temporal (§10.2)    | PASS / FAIL / UNKNOWN / NOT_APPLICABLE |
| `P_rov` | Provenance (§10.3)    | PASS / FAIL / UNKNOWN / NOT_APPLICABLE |
| `D`  | Derivation (§10.4)       | PASS / FAIL / UNKNOWN / NOT_APPLICABLE |
| `S`  | Support (§10.5)          | PASS / FAIL / UNKNOWN / NOT_APPLICABLE |

Each predicate is an **independent pure function** of `(c, G, P)` (or a subset),
returning one of the four **tri-plus-one valued** results below. The five are
evaluated in a fixed order and every result is recorded (fully auditable).

### 2.1 Four-valued predicate semantics

- **PASS** — the predicate is satisfied.
- **FAIL** — the predicate is violated (a counter-fact exists).
- **UNKNOWN** — the predicate can neither be established nor refuted from `G`
  and `P`. **UNKNOWN is never treated as PASS and never treated as FALSE**
  (R1 §10.6) — it forces abstention (§3).
- **NOT_APPLICABLE** — the predicate does not apply to this claim shape (e.g. a
  claim with no numeric assertion has no derivation obligation). NOT_APPLICABLE
  composes as satisfied (it cannot block admission).

### 2.2 Mandatory-predicate composition (`admit`)

A predicate is **mandatory** iff it appears in `P.mandatory_predicates`. The
composition rule (R1 §10.6 / §10.7), implemented in `admit`, is:

```
  if  ∃ mandatory predicate with result FAIL:
        verdict = REJECTED        (mapped to the most severe terminal verdict)
  elif ∃ mandatory predicate with result UNKNOWN:
        verdict = ABSTAINED       (UNVERIFIABLE)
  else  (every mandatory predicate is PASS or NOT_APPLICABLE):
        verdict = ADMITTED        (VERIFIED)
```

Equivalently, admission requires every mandatory predicate to resolve to
`PASS ∨ NOT_APPLICABLE`; a single mandatory `FAIL` rejects; a single mandatory
`UNKNOWN` (absent any `FAIL`) abstains. Non-mandatory predicate results are
recorded but do not gate the verdict.

### 2.3 Determinism (tested property, not a proof)

For identical **normalized** inputs `(G, c, P)` the verdict is deterministic:
fixed predicate order, sorted reason codes, and a severity-ranked verdict
mapping. This is the property exercised by the §11 invariant-10 tests; it is a
tested property, not a machine-checked theorem.

### 2.4 Trust boundary (R1 §10.6; §11 invariant 7)

The agent controls only the untrusted surface of `c` (its assertions, cited
evidence ids, and proposed `knowledge_cutoff`). The agent **cannot**:

- assign a verdict (`CandidateClaim`/`Assertion` carry no status field);
- declare a predicate NOT_APPLICABLE (only predicate logic + `P` decide);
- relax the point-in-time as-of (the trusted `P.as_of_cutoff` governs; a claim's
  own cutoff may only *tighten* it — see §4.2);
- re-label evidence (an assertion's `metric` must match the cited evidence's
  attested metric — see §4.5).

---

## 3. Verification outcomes

**Status: IMPLEMENTED / TESTED.** The admission verdict maps to one of the typed
outcomes (R1 §10.7), kept **separate from research-termination states** so that
resource exhaustion never implies an unsupported assertion is false:

```
VERIFIED, CONTRADICTED, INSUFFICIENT_EVIDENCE, UNVERIFIABLE, STALE,
INVALID_EVIDENCE, INTEGRITY_FAILURE, UNRESOLVED_CONFLICT
```

ADMITTED → `VERIFIED`; mandatory-UNKNOWN → `UNVERIFIABLE`; a mandatory-FAIL maps
to the most severe applicable terminal verdict for the failing predicate
(e.g. `INTEGRITY_FAILURE`, `CONTRADICTED`, `INSUFFICIENT_EVIDENCE`, `STALE`,
`INVALID_EVIDENCE`).

---

## 4. Predicate semantics (formal)

All five are **IMPLEMENTED / TESTED** and were adversarially hardened (the
CRITICAL/MAJOR fixes are recorded in `claim-admission-invariants.md` §2 and
`milestone-r1-report.md` §4).

### 4.1 Integrity `I(c, G)` — §10.1

`I = PASS` iff every node referenced by `c` and by its upstream links resolves in
`G`, **and** every factory-built node (`SourceObservation`, `CandidateClaim`) is
content-hash consistent (its stored id equals the recomputed `canonical_hash` of
its deterministic fields). On any unresolved reference or hash mismatch → FAIL
(`integrity_failure`).

**Documented limitation (trust model, R1 §9.4).** Integrity hash-checks only the
factory-built node types. Backend-produced nodes (`SourceFact`, `Evidence`,
`CalculationResult`, `ComputationResult`, `SourceArtifact`) are *trusted* under
the stated trust model: a valid content hash establishes integrity, **not truth**.
Cryptographic signing of backend-produced nodes is **future work (NOT_IMPLEMENTED)**.

### 4.2 Type–temporal `T(c, G, P)` — §10.2

`T = PASS` iff, for each assertion of `c`:

1. **Unit, entity, and metric match** between the assertion and its cited
   evidence (metric-match is load-bearing — see §4.5);
2. **Point-in-time (as-of) holds.** The effective as-of cutoff is governed by the
   **trusted** `P.as_of_cutoff`. A claim's own proposed `knowledge_cutoff` may
   only *tighten* (earliest-of) the trusted cutoff, never extend it. No
   information whose availability time is **after** the effective cutoff may
   establish point-in-time knowledge. The availability time is taken from the
   **latest availability across the provenance closure** (temporal walks the
   closure, not a single node).
3. **Freshness holds.** Freshness is anchored on the **identity-protected**
   `applicable_temporal_cutoff` (not on an identity-excluded `issued_at`, which
   was revivable by tamper — fixed defect). Strong freshness requires signed
   certificates and is a documented limitation (§13.5; NOT_IMPLEMENTED).

Failure maps to `invalid_evidence` or `stale` as applicable. Insufficient
temporal information → UNKNOWN (abstain), never silent pass.

### 4.3 Provenance `P_rov(c, G, P)` — §10.3

`P_rov = PASS` iff each assertion has a **complete lineage** from its cited
evidence back to at least one **preserved `SourceArtifact`**, with every link in
the chain resolving in `G`. **Source independence** is an optional, policy-gated
sub-check: when `P` requires it, the attesting evidence must trace to the
required number of **independent** sources (independence determined by source
identity/anchor, not by mere record distinctness). Incomplete lineage → FAIL
(`invalid_evidence`); undeterminable independence under a required policy → UNKNOWN.

### 4.4 Derivation `D(c, G, P)` — §10.4

`D = PASS` iff **each numeric assertion is independently re-derived**. The
verifier does **not** trust the agent-asserted number: it locates the backing
computation(s) in the evidence closure and **re-executes / re-reads the upstream
`ComputationResult`** via the `recompute()`-style verifier entry, then checks

```
within_tolerance(asserted_value, recomputed_value, contract) = TRUE
```

under the backing operation's `NumericalContract` (§6). The backing-computation
search scans the **full evidence closure** (a longer-than-one-hop backing path is
not ignored — fixed §11.16 defect). A mismatch, or a backing computation whose
own numerical-validation status is invalid, → FAIL (`contradicted`). An invalid
numerical contract backing a dependent finding blocks that finding (§11 inv. 16).
If no numeric assertion exists → NOT_APPLICABLE.

### 4.5 Support `S(c, G, P)` — §10.5

`S = PASS` iff **each assertion cites evidence that actually attests it**: the
cited evidence must match the assertion on **value, unit, metric, and entity**.
The **metric-match requirement is mandatory and load-bearing**: an assertion's
`metric` must equal the cited evidence's attested metric
(`assertion.metric == _metric_of(evidence)`). This closes the **metric-relabeling
forgery** (citing real `operating_margin` evidence under a false
`net_profit_margin` label) that previously ADMITTED — mismatch now yields
`metric_mismatch` → FAIL (`insufficient_evidence`). Unrelated evidence cannot
satisfy support (§11 inv. 4).

---

## 5. GAP-001 evidence-bound authorization `Auth(a, G, P)`

**Status: IMPLEMENTED / TESTED** (`src/strix/assurance/`). **External execution
is disabled by default**; a sandbox executor and independent outcome
reconciliation (§20) are implemented.

An action `a` is authorized against the evidence graph `G` under policy `P` iff
all six ordered, deterministic conditions hold:

```
Auth(a, G, P) = Iₐ(a,G) ∧ Vₐ(a,G,P) ∧ Cₐ(a,G,P) ∧ Fₐ(a,G,P) ∧ Bₐ(a,P) ∧ Rₐ(a,G,P)
```

| Symbol | Condition | Meaning |
|---|---|---|
| `Iₐ` | Integrity     | the action and its referenced evidence are well-formed and resolve in `G` |
| `Vₐ` | Verification  | the evidence the action relies on is **admitted** (VERIFIED), not merely present |
| `Cₐ` | Constraints   | ordered constraint evaluation passes (reused/generalized from C-engine `risk_engine` ordered constraint eval + typed reason codes) |
| `Fₐ` | Freshness     | the backing evidence is fresh, anchored on the **identity-protected** `applicable_temporal_cutoff` |
| `Bₐ` | Budget        | the action is within remaining resource/exposure budget |
| `Rₐ` | Reconciliation / replay | the authorization is reproducible and parameter-bound |

Properties (IMPLEMENTED / TESTED):

- **Ordered, deterministic conditions** with **typed reject codes**.
- **Idempotency / duplicate-action guard** prevents re-execution of the same
  action.
- **Parameter-bound certificates**: an authorization certificate binds the exact
  action parameters; `reauthorize` is **TOCTOU-aware** (a change requires
  re-authorization).
- **Outcome certification (§20):** the reconciler performs an **independent
  certificate↔request digest check** rather than trusting executor-reported ids
  (fixed defect).

No backend (LLM, CPU, Metal) may assign a claim verdict or self-authorize; the
authorization layer consumes admitted evidence only.

---

## 6. Numerical contract classes `within_tolerance`

**Status: IMPLEMENTED / TESTED** (`src/strix/native/contracts.py`; see
`numerical-contracts.md`). Every native operation declares a `NumericalContract`
of one of **five classes** (R1 §7.1):

| Class | Meaning | Reproducibility criterion |
|---|---|---|
| `exact` | exact integer / exact Decimal | bitwise identical (equality required) |
| `deterministic_fp` | deterministic FP under a pinned environment | bitwise under pinned env — **reserved for C++/Metal CPU kernels (NOT_IMPLEMENTED)** |
| `tolerance` | reproducible within stated tolerance | `|observed − expected| ≤ abs_tol + rel_tol·|expected|` |
| `approximate` | approximate statistical computation | within documented error (float64) |
| `stochastic` | stochastic under recorded parameters | identical given the recorded seed |

Agreement is decided by `within_tolerance(observed, expected, contract)`:

```
exact            →  observed == expected                         (exact equality)
otherwise        →  |observed − expected| ≤ abs_tol + rel_tol·|expected|
```

"Tolerance-based agreement" is explicitly **not** represented as bitwise
reproducibility (R1 §7.1). Exact financial Decimals are **never** converted to
binary float for GPU compatibility. Working precision `ARITH_PRECISION = 50`;
statistical summaries quantize to `STAT_QUANTUM = 1e-12`. The derivation
predicate `D` (§4.4) invokes `within_tolerance` under the backing operation's
declared class.

Backend applicability (as implemented): `exact` → checked arithmetic / exact
sums; `tolerance` → descriptive / time-series / multivariate statistics;
`approximate` → confidence intervals, t-tests, effect sizes; `stochastic` →
percentile bootstrap. `deterministic_fp` is declared but unused pending the
C++/Metal backends (NOT_IMPLEMENTED).

---

## 7. GAP-003 reconciliation residual

**Status: IMPLEMENTED / TESTED** (`src/strix/reconciliation/`).

For a reported aggregate `observed` claimed to be a known function `f` of its
components, the **reconciliation residual** is

```
r = observed − f(components)
```

computed in **exact Decimal** using `checked_sum` / `checked_sub` (the
precision-28 reconstruction that misclassified large exact sums was fixed).
Reconciliation **passes** iff

```
|r| ≤ abs_tol + rel_tol · |observed|
```

i.e. the residual lies within the same absolute+relative tolerance band used by
`within_tolerance`. Alongside the residual check, GAP-003 implements
**integrity checks** (duplicate / missing / temporal / skew / coverage / unit)
and **anomaly screening** (IQR and z-score) that **flag for investigation and
never auto-reject** — anomaly flags are advisory inputs to review, not verdicts.

---

## 8. Answer coverage (R1 §17.6)

**Status: IMPLEMENTED / TESTED** (`src/strix/answering/`).

The answer-first synthesis layer renders a natural-language answer in which every
material factual assertion binds to an **admitted** `ClaimCertificate`
(independent `validate_response` is fail-closed; `strip_unsupported` removes any
assertion lacking an admitted binding). The **answer-coverage score** over the
answered sub-questions `i` is the weighted ratio

```
coverage = ( Σ_i w_i · s_i ) / ( Σ_i w_i )
```

where `w_i ≥ 0` is the weight of sub-question `i` and `s_i ∈ [0,1]` is its
per-sub-question support/satisfaction score. The scalar `coverage` drives the
discrete classification

```
COMPLETE · PARTIAL · INSUFFICIENT · UNANSWERABLE
```

This is the §16 **deterministic** answer path and requires **no language model**.
Numeric thresholds separating the four classes are policy parameters, not
empirically tuned constants, and no accuracy of the classification is claimed
(NOT_EVALUATED).

---

## 9. GAP-002 decision ledger (supporting structure)

**Status: IMPLEMENTED / TESTED** (`src/strix/audit/`). Not an equation but part
of the assurance algebra: a durable, append-only, **hash-chained** ledger over
27 lifecycle event types with idempotent insert and a `verify_chain` predicate
that detects tamper, gaps, and broken links; crash recovery and replay are
implemented. The chain-linking payload split is on `\n` only (U+2028/U+0085/U+2029
corruption fixed). The C-engine's lossy in-memory decision-events sink was **not**
reused as the system of record; the durable ledger was reimplemented.

---

## 10. §15 adaptive acquisition optimization — PROPOSED / NOT_IMPLEMENTED

**Status: NOT_IMPLEMENTED.** The R1 §15 adaptive acquisition-optimization layer
chooses the next evidence-acquisition action to maximize a utility/objective
subject to the resource budget — informally, selecting the action that maximizes
expected reduction in answer uncertainty (or expected gain in admissible
coverage) per unit of budget spent. **This objective and its utility function are
PROPOSED only and were not built.** The existing agent's bounded, budgeted loop
remains in place. No optimizer, no objective evaluation, and no acquisition policy
from §15 exist in R1. Any formula one might write here would be a design target,
not implemented behavior; it is therefore intentionally left unspecified beyond
this statement.

---

## 11. Property status summary

| Formal object | Where | Status |
|---|---|---|
| Typed graph `G=(V,E,τ,π)`, integrity, acyclic DAG, hashing, closure | `evidence_graph` | IMPLEMENTED / TESTED |
| Admission `A = I∧T∧P∧D∧S`, 4-valued predicates, mandatory/UNKNOWN/NOT_APPLICABLE composition | `evidence_graph` | IMPLEMENTED / TESTED |
| Predicate semantics (I, T incl. trusted as-of, P incl. independence, D incl. independent recompute, S incl. metric match) | `evidence_graph` | IMPLEMENTED / TESTED |
| Determinism of admission | `evidence_graph` | TESTED property (not a proof) |
| GAP-001 `Auth = Iₐ∧Vₐ∧Cₐ∧Fₐ∧Bₐ∧Rₐ` + sandbox + §20 outcome check | `assurance` | IMPLEMENTED / TESTED |
| Five numerical-contract classes + `within_tolerance` | `native/contracts` | IMPLEMENTED / TESTED |
| GAP-003 residual `r = observed − f(components)`, `|r| ≤ abs_tol+rel_tol·|observed|` | `reconciliation` | IMPLEMENTED / TESTED |
| §17.6 coverage `Σ wᵢsᵢ / Σ wᵢ` + 4-way classification | `answering` | IMPLEMENTED / TESTED |
| GAP-002 hash-chained ledger + `verify_chain` | `audit` | IMPLEMENTED / TESTED |
| `deterministic_fp` contract class (pinned-env C++/Metal) | — | NOT_IMPLEMENTED |
| Cryptographic signing (freshness/authenticity) | — | NOT_IMPLEMENTED |
| §15 acquisition-optimization objective/utility | — | PROPOSED / NOT_IMPLEMENTED |
| H1–H12 evaluation of any property above | — | NOT_EVALUATED |

All IMPLEMENTED / TESTED entries are backed by executable unit/integration tests
(the R1 suite reports `1430 passed, 2 skipped, 2 xfailed`, 0 regressions vs the
`862 passed` baseline — an **engineering** measurement, not validation of any
research hypothesis). None of the above is a machine-checked proof, and none has
been evaluated against a benchmark corpus.
