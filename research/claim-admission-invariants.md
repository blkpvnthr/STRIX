# Claim Admission & Compositional Invariants (R1 §10, §11)

**Status:** IMPLEMENTED/TESTED in `src/strix/evidence_graph/` (predicates, invariants);
adversarially reviewed and hardened. These are *tested properties*, not
machine-checked proofs (R1 §11 caveat).

## 1. The admission function

A candidate claim `c` is admitted into the verified graph `G` only if all five
independent predicates hold under a trusted, versioned policy `P`:

```
A(c, G, P) = I(c,G) ∧ T(c,G,P) ∧ P_rov(c,G,P) ∧ D(c,G,P) ∧ S(c,G,P)
```

| Predicate | Function | Checks | On failure |
|---|---|---|---|
| **I** integrity (§10.1) | `integrity` | every referenced node + upstream link resolves; factory-built nodes are content-hash consistent | `integrity_failure` |
| **T** type/temporal (§10.2) | `type_temporal` | unit + entity + **metric** match; point-in-time as-of; freshness | `invalid_evidence` / `stale` |
| **P** provenance (§10.3) | `provenance` | complete lineage to a preserved `SourceArtifact`; optional source independence | `invalid_evidence` |
| **D** derivation (§10.4) | `derivation` | each numeric assertion independently re-derived against its backend computation within tolerance | `contradicted` |
| **S** support (§10.5) | `support` | each assertion cites evidence that actually attests it (value/unit/metric/entity) | `insufficient_evidence` |

### 1.1 Composition (`admit`, §10.6/§10.7)

All five predicates run in a fixed order and are recorded (fully auditable). A
predicate is **mandatory** iff listed in `policy.mandatory_predicates`.

- Every mandatory predicate `PASS` (or `NOT_APPLICABLE`) → **ADMITTED** / `VERIFIED`.
- Any mandatory `FAIL` → **REJECTED** (mapped to the most severe terminal verdict).
- Any mandatory `UNKNOWN`, no `FAIL` → **ABSTAINED** / `UNVERIFIABLE` — *unknown is
  never treated as pass or as false* (R1 §10.6).

The outcome is **deterministic** for identical normalized `(G, c, P)` (sorted
reason codes, fixed predicate order, severity-ranked verdict mapping).

### 1.2 Trust boundary (R1 §10.6, §11 inv. 7)

The research agent controls only the untrusted `CandidateClaim` surface
(assertions, cited evidence ids, knowledge_cutoff). It **cannot**:

- assign a verdict — `CandidateClaim`/`Assertion` carry no status field;
- mark a predicate `NOT_APPLICABLE` — only the predicate logic + policy decide;
- relax the point-in-time as-of — the **trusted** `VerificationPolicy.as_of_cutoff`
  governs; a claim's own cutoff may only *tighten* it;
- re-label evidence — an assertion's `metric` must match the cited evidence's
  attested metric/concept.

## 2. Adversarial hardening (falsification-first)

An independent adversarial review (workflow `wf_f7c8fe10-269`) treated the agent
as untrusted and tried to admit false claims. It found — and we fixed, each with a
permanent regression test in `tests/evidence_graph/test_eg_review_regressions.py`:

| Severity | Bypass found | Fix |
|---|---|---|
| CRITICAL | **Metric relabeling** — cite real `operating_margin` evidence under a false `net_profit_margin` label → ADMITTED | `support` now requires `assertion.metric == _metric_of(evidence)`; mismatch → `metric_mismatch` → REJECTED |
| CRITICAL | **Untrusted as-of** — omit/far-future `knowledge_cutoff` to bypass point-in-time | cutoff now comes from the trusted `policy.as_of_cutoff`; claim may only tighten (earliest-of) |
| CRITICAL | **§11.16 1-hop blocker** — a failed numerical contract backing the claim via a longer path was ignored | `_backing_computations` now scans the full evidence closure |
| MAJOR/MINOR | temporal ignored upstream provenance; recursive acyclicity `RecursionError` on deep chains | temporal walks the provenance closure for the latest availability; acyclicity converted to iterative DFS |

What the review could **not** break (confirmed robust): determinism; self-asserted
verdict injection; unknown-mandatory never treated as pass; derivation re-reads the
upstream computation (not the model-asserted number); certificate tamper-detection
on every deterministic field.

## 3. Compositional invariants (§11)

`invariants.py` implements and tests the R1 §11 properties, e.g.: invalid mandatory
dependency blocks admission (1); evidence must resolve to preserved artifacts (2);
invalidating an upstream node flips a prior admission (3); unrelated evidence cannot
satisfy support (4); post-cutoff information cannot establish point-in-time knowledge
(5); content integrity ≠ semantic truth (6); the LLM cannot assign verdicts (7); new
`CONTRADICTED_BY` triggers reevaluation (8); resource exhaustion never weakens
requirements (9); identical inputs → reproducible decision (10); an invalid numerical
contract blocks dependent findings (16).

**Limits:** integrity hash-checks only the factory-built node types
(`SourceObservation`/`CandidateClaim`); backend-produced nodes
(`SourceFact`/`Evidence`/`CalculationResult`/`ComputationResult`/`SourceArtifact`)
are trusted under the stated trust model (R1 §9.4: a valid content hash does not
establish truth). Cryptographic signing of backend-produced nodes is future work.

## 4. Verification outcomes (§10.7)

`VERIFIED, CONTRADICTED, INSUFFICIENT_EVIDENCE, UNVERIFIABLE, STALE,
INVALID_EVIDENCE, INTEGRITY_FAILURE, UNRESOLVED_CONFLICT` — kept separate from
research-termination states, so resource exhaustion never implies an unsupported
assertion is false (R1 §10.7).
