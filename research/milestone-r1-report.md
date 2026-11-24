# Milestone R1 — Engineering & Scientific Report

**Milestone:** R1 — Resource-Bounded Typed Evidence Verification for Trustworthy Autonomous AI
**Branch:** `research/formal-evidence-verification` (cut from `feat/milestone-0b` `849018d`; **uncommitted**, not merged, not deployed)
**C-engine baseline:** `3a23b13` (read-only extraction source)
**Date:** 2026-11-24

**Classification key (§37):** IMPLEMENTED · TESTED · EXPERIMENTALLY_SUPPORTED · EXPERIMENTALLY_UNSUPPORTED · INCONCLUSIVE · NOT_EVALUATED · BLOCKED.

> This report distinguishes *proposed targets* from *measured outcomes* and does
> not claim universal correctness, novelty, or patentability. Thresholds in the
> R1 spec (H1–H12, §30) are **experimental objectives**, evaluated below as
> **NOT_EVALUATED** unless a measurement is cited.

---

## 1. Executive summary

R1 built, from the ground up and reuse-first, the **core trustworthy-research
substrate** and proved it works end-to-end:

- A portable **native CPU quantitative layer** (§6/§7) — descriptive/time-series/
  multivariate/inference statistics + checked exact arithmetic + numerical
  contracts + a typed, content-addressed `ComputationResult` + a reference backend.
- A **formal typed evidence graph** with the **five independent admission
  predicates** (I/T/P/D/S), the **four certificate classes**, and the §11
  compositional invariants.
- The three **GAP cores**: GAP-001 evidence-bound deterministic authorization
  (+ sandbox executor + outcome certification §20), GAP-002 a durable, hash-chained
  decision ledger, GAP-003 cross-resolution reconciliation + integrity + anomaly
  screening.
- An **answer-first synthesis + independent response-validation** layer (§16/§17):
  STRIX renders a substantive natural-language answer whose every material factual
  assertion maps to an admitted claim certificate.
- An **end-to-end integration test** (DoD §36.5): native compute → evidence graph
  → admission → certificate → verified NL answer, with a fabricated figure proven
  to be rejected and never answered.

Every subsystem was subjected to **independent adversarial review**, which found
and fixed **real defects** (2 critical verification bypasses, 3 numeric/durability
bugs, and more) — the falsification-first discipline in action.

**Measured engineering outcome:** `1430 passed, 2 skipped, 2 xfailed` (from the
`862 passed` baseline → **+568 R1 tests**), **0 regressions**, `ruff` zero and
`mypy --strict` clean on all 31 R1 source modules.

**Honest scope:** the C++/Metal native backends, the full live-agent/API/frontend
integration, the 1,200-question benchmark, the H1–H12 evaluation, and the
genuine-source demonstrations (§31) are **NOT done** — designed and/or scaffolded
but not built/executed. See §7–§9.

---

## 2. Baselines, reuse, and method

- STRIX baseline `849018d`; C-engine `3a23b13`. See `baseline-commits.md`.
- Dual-repository audit (`repository-baseline-audit.md`, `cengine-extraction-audit.md`,
  `intellectual-property-inventory.md`): STRIX already provided the canonical
  content-addressing + Decimal-exact core, frozen typed models, provenance/support
  verification kernels, atomic persistence, budgets, connectors, and an answer-first
  frontend shell — all **reused**, not rebuilt.
- C-engine mapping drove the GAP cores (risk_engine→GAP-001; the lossy in-memory
  decision-events sink→*reimplemented durably* for GAP-002; data_integrity→GAP-003).
  All C-engine components share STRIX's owner; no LICENSE file (treated proprietary);
  sensitive specs kept on this local branch.
- Method: strict TDD (RED→GREEN), ground-truth re-verification of every delegated
  result, and independent adversarial review of all security/numeric-critical code.

---

## 3. What was built — by workstream

| WS | Area | Package(s) | Status | Tests |
|---|---|---|---|---|
| 1 | Dual-repo audit + baselines | `research/` | IMPLEMENTED | n/a |
| 2 | Native CPU quantitative computing (§6/§7) | `strix.native` | IMPLEMENTED/TESTED | 278 |
| 3 | Typed evidence graph + 5 predicates + 4 certificates + §11 invariants | `strix.evidence_graph` | IMPLEMENTED/TESTED | 128 |
| 4/7/8 | GAP-001 authorization, GAP-002 ledger, GAP-003 reconciliation | `strix.assurance`, `strix.audit`, `strix.reconciliation` | IMPLEMENTED/TESTED | ~101 |
| 6 | Answer synthesis + response validation (§16/§17) | `strix.answering` | IMPLEMENTED/TESTED | 54 |
| 10 | Integration — end-to-end pipeline proof + `strix compute` CLI | `tests/test_r1_integration.py`, `strix.cli` | PARTIAL (see §8) | 4 |
| 5 | Adaptive acquisition optimization (§15) | — | NOT_IMPLEMENTED (design reused from existing agent loop) |
| 9 | Metal / C++ CPU backends (§8) | — | NOT_IMPLEMENTED |
| 11 | 1,200-q benchmark, ablations, H1–H12 (§29) | — | NOT_EVALUATED |
| 12 | Research docs + README | `research/` | PARTIAL (8 docs) |

### 3.1 Native quantitative computing (§36.1/§36.2) — IMPLEMENTED/TESTED
`arithmetic` (checked exact arithmetic, overflow/zero/NaN/float rejection, exact
`checked_sum`/`checked_sub`), `statistics` (§6.1), `timeseries` (§6.2),
`multivariate` (§6.3), `inference` (§6.4 — Student-t via regularized incomplete
beta, Welch, seeded bootstrap, BH/Bonferroni), `contracts` (§5.3/§7.1 taxonomy +
backend abstraction), `results` (typed `ComputationResult` §7.2), and a
`PythonReferenceBackend` exposing 27 operations as the `REFERENCE` validation
baseline. Cross-checked against Python stdlib `statistics` (rel-tol < 1e-9) and
hand-computed values. Exact Decimal preserved; float forbidden at every boundary.

### 3.2 Formal evidence verification (§36.3) — IMPLEMENTED/TESTED
Typed graph `G=(V,E,τ,π)` with referential integrity, acyclic derivation subgraph
(iterative DFS), traversal/closure, and deterministic graph hashing. The five
predicates are independent pure functions returning PASS/FAIL/UNKNOWN/NOT_APPLICABLE;
`admit` composes them under a trusted, versioned `VerificationPolicy` — mandatory
FAIL→REJECTED, mandatory UNKNOWN→ABSTAINED (never treated as pass). Four certificate
classes with content-addressed ids, tamper-detecting `validate_*`, and
nondeterministic metadata excluded from identity. §11 invariants implemented + tested.
See `claim-admission-invariants.md`.

### 3.3 GAP cores (§36.6/§36.7/§36.8) — IMPLEMENTED/TESTED
- **GAP-001** `Auth = Iₐ∧Vₐ∧Cₐ∧Fₐ∧Bₐ∧Rₐ`, ordered deterministic conditions, typed
  reject codes, idempotency/duplicate-action guard, parameter-bound certificates
  (TOCTOU-aware `reauthorize`), **external execution disabled by default**, sandbox
  executor, and independent outcome reconciliation (§20).
- **GAP-002** durable, append-only, hash-chained ledger (27 lifecycle event types);
  idempotent insert; `verify_chain` detects tamper/gap/broken-link; crash recovery;
  replay. The C-engine lossy in-memory sink was *not* reused as the record.
- **GAP-003** cross-resolution reconciliation (`r = observed − f(components)`,
  exact Decimal), integrity checks (duplicate/missing/temporal/skew/coverage/unit),
  and IQR/z-score anomaly screening that *flags for investigation*, never auto-rejects.

### 3.4 Answer-first question answering (§36.5) — IMPLEMENTED/TESTED
Deterministic synthesis from admitted findings only; every factual assertion binds
to an admitted `ClaimCertificate`; independent `validate_response` (fail-closed) +
`strip_unsupported`; answer-coverage scoring + COMPLETE/PARTIAL/INSUFFICIENT/
UNANSWERABLE classification; Markdown rendering. This is the §16 deterministic
answer path (no language model required).

---

## 4. Adversarial review — defects found and fixed (falsification evidence)

Independent, findings-only review workflows treated the agent as untrusted and
tried to break each subsystem. Every confirmed defect was fixed TDD-style with a
permanent regression test.

| Subsystem | Severity | Defect | Fix |
|---|---|---|---|
| native `arithmetic.quantize` | CRITICAL | global-context overflow → untyped crash on values ≥~1e16 (variance of market caps, wei, ns timestamps) | sized local context + typed error |
| native `inference._dec` | MINOR | same overflow ≥1e19 | (same root fix) |
| native `multivariate.ewma_covariance` | MAJOR | `0**0` crash at `alpha=1` | explicit newest-weight = 1 |
| predicates `support`/`type_temporal` | CRITICAL | **metric-relabeling forgery** — cite real evidence under a false metric → ADMITTED | metric must match cited evidence |
| predicates `type_temporal` | CRITICAL | **untrusted point-in-time cutoff** — omit/far-future `knowledge_cutoff` bypasses as-of | trusted `policy.as_of_cutoff`; claim may only tighten |
| invariants §11.16 | CRITICAL | failed numerical contract backing via >1 hop ignored | scan full evidence closure |
| predicates/graph | MAJOR/MINOR | temporal ignored upstream closure; recursive acyclicity `RecursionError` | closure traversal; iterative DFS |
| GAP-002 ledger | MAJOR | `splitlines()` corrupts payloads with U+2028/U+0085/U+2029 | split on `\n` only |
| GAP-003 reconcile | MAJOR | prec-28 reconstruction misclassifies large exact sums | exact `checked_sum`/`checked_sub` |
| GAP-001 authorization | MAJOR | freshness gated on identity-excluded `issued_at` (revivable by tamper) | anchor on identity-protected `applicable_temporal_cutoff` |
| GAP-001 outcome | MINOR | reconciler trusted executor-reported ids | independent cert↔request digest check |

Certificates review: **clean**. All fixes verified against the full suite with 0
regressions.

---

## 5. Measured results (engineering)

| Metric | Measured |
|---|---|
| Full test suite | **1430 passed, 2 skipped, 2 xfailed** (baseline 862 passed) |
| New R1 tests | +568 |
| Regressions vs baseline | **0** |
| `ruff` (31 R1 src + tests) | zero findings |
| `mypy --strict` | clean (31 R1 source modules) |
| Exact-arithmetic disagreement (native, vs stdlib + hand values) | 0 observed within contracts |
| End-to-end verified-answer pipeline | PASS (positive + tamper-rejection cases) |
| Adversarial defects found / fixed | 11 / 11 |

The native statistics were cross-checked against an independent reference
(Python stdlib) with relative tolerance < 1e-9. This is **engineering validation**,
not scientific validation of the research hypotheses.

---

## 6. H1–H12 (§28) — evaluation status

**All NOT_EVALUATED.** No benchmark corpus was built and no hypothesis was
measured. Mechanisms the hypotheses concern are implemented and unit/integration
tested, but their *claims* (e.g. ≥70% unsupported-claim reduction, 100% replay
agreement, ≥95% adversarial detection, throughput/speedup targets) require the
§29 benchmark + baselines + ablations, which were not executed. Reporting them as
anything other than NOT_EVALUATED would be fabrication.

---

## 7. Not implemented / not evaluated (honest gaps)

- **C++ NativeCPUBackend & Metal (§8, §9)** — NOT_IMPLEMENTED. The CPU-first Python
  reference is complete and is the validated baseline; the C++/pybind11 and
  Objective-C++/Metal backends (and CPU/GPU parity harness) are designed in
  `native-computing-architecture.md` but not built. Linux operation never depends
  on Metal (satisfied trivially — no Metal).
- **Adaptive acquisition optimizer (§15, WS5)** — NOT_IMPLEMENTED as a new strategy
  layer; the existing agent's bounded budgeted loop remains.
- **1,200-question benchmark, baselines, ablations (§29), H1–H12** — NOT_EVALUATED.
- **Genuine-source demonstrations A–G (§31)** — NOT_EXECUTED against live sources.
  The integration test is a synthetic-fixture *pipeline* proof, not a live
  demonstration. New connectors (USAspending/SAM/USGS, §22) were not added.
- **FALCON alignment / NSF pitch (§21/§33)** — NOT_PRODUCED; must be stated as
  proposed alignment only, never as endorsement or eligibility.

---

## 8. Platform integration (§36.10) — PARTIAL

- **CLI:** `strix compute backends` / `strix compute operations` wired and tested.
  The RUN_ID-scoped commands (`graph`/`verify`/`audit`/`certificate`/`authorization`/
  `outcome` inspect) are NOT wired — they require the research loop to persist R1
  evidence graphs/ledgers per run, which is not integrated.
- **Live research agent / API / frontend:** NOT integrated. The existing `strix ask`
  (v0.2.0 path) is unchanged; the R1 verified-answer pipeline
  (`strix.answering.pipeline.answer_question`) is proven by the integration test but
  is not yet the default live path, nor surfaced through the FastAPI/React frontend.
- **Offline replay / durable research jobs:** existing STRIX replay unchanged; R1
  evidence-graph/ledger replay is unit-tested within `audit` but not wired to the
  job lifecycle.

---

## 9. Repository status

- Branch `research/formal-evidence-verification`, **all work uncommitted** (per the
  no-commit-without-request rule). Not merged; not deployed.
- New source packages: `strix.native`, `strix.evidence_graph`, `strix.assurance`,
  `strix.audit`, `strix.reconciliation`, `strix.answering` (+ `strix.cli` extension).
- Research docs (8): baseline-commits, repository-baseline-audit,
  cengine-extraction-audit, intellectual-property-inventory,
  native-computing-architecture, numerical-contracts, claim-admission-invariants,
  milestone-r1-report (this file).
- No secrets committed. No live external execution enabled. No production deploy.

---

## 10. Implementation decisions made without explicit guidance

- Adapted the R1 §5.2 `native/` C++ tree into an in-repo Python-first
  `src/strix/native/` layout (CPU-first priority, §35), reserving C++/Metal for a
  later milestone.
- Branched R1 from `feat/milestone-0b` (it builds on the STRIX-001..015 baseline).
- Point-in-time as-of is governed by the trusted policy; a claim may only tighten it.
- Freshness anchors on the identity-protected `applicable_temporal_cutoff`, falling
  back to best-effort `issued_at` (strong freshness needs signed certs — §13.5).
- Certificate integrity is content-addressing, not signatures; documented as a
  trust-model limitation (cryptographic signing is future work).

---

## 11. Recommended next milestone (R2)

1. Wire the R1 pipeline into the live research agent + persist per-run evidence
   graphs/ledgers; surface verified answers through the API + answer-first frontend;
   complete the RUN_ID CLI commands.
2. Build the C++ NativeCPUBackend (pybind11) + CPU/GPU parity harness; then Metal.
3. Build the §29 pilot benchmark + baselines + ablations and evaluate H1–H12 on an
   independently labelled genuine-source corpus; preserve negative findings.
4. Execute demonstrations A–G against live authoritative sources; add the missing
   §22 connectors.
5. Introduce cryptographic signing where the trust model requires it (certificates,
   manifests) to close the content-addressing-only freshness/authenticity gaps.
