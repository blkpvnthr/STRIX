# STRIX Milestone 0B — Remediation & Verification Report

**Audit commit of record:** `3dc70eac6b6b178d51156185113beb70d7c899e4`
**Work branch:** `feat/milestone-0b` (cut from the audit commit; **not** merged to main)
**Report date:** 2026-11-24

This report records, with claim discipline, exactly what Milestone 0B changed, the full
test outcome (not a curated subset), the deficiencies closed, the deficiencies
**deliberately preserved as documented gaps**, and a feasibility / go-no-go
recommendation. It makes **no** claims of novelty, performance, patentability,
government readiness, or commercial validation.

---

## 1. Scope delivered

| # | Deliverable | Artifact |
|---|-------------|----------|
| 1 | Corrected engineering audit | [`engineering-audit.md`](./engineering-audit.md) |
| 2 | Research gap coverage matrix | [`gap-coverage-matrix.md`](./gap-coverage-matrix.md) |
| 3 | Formal requirements baseline (machine-readable) | [`requirements-baseline.yaml`](./requirements-baseline.yaml) |
| 4 | Requirements traceability matrix | [`requirements-traceability.md`](./requirements-traceability.md) |
| 5 | Documentation corrections | `architecture/llm-boundary.md`, `architecture/provenance.md` (+ `docs/architecture/` mirrors) |
| 6 | Expanded integrity & reconciliation tests | `tests/lakehouse/test_transform_reconciliation_discrepancy.py`, `tests/agent/test_response_validator.py`, `tests/agent/test_agent_replay.py`, `tests/test_replay.py` |
| 7 | Comparative experimental design | [`comparative-experiment-design.md`](./comparative-experiment-design.md) |
| 8 | Milestone 1–3 implementation specifications | [`milestone-1-evidence-interoperability-spec.md`](./milestone-1-evidence-interoperability-spec.md), [`milestone-2-execution-assurance-spec.md`](./milestone-2-execution-assurance-spec.md), [`milestone-3-outcome-certification-spec.md`](./milestone-3-outcome-certification-spec.md) |
| 9 | Full test & remediation report | *this document* |
| 10 | Feasibility & go/no-go recommendation | §7 below |

The three authoritative research gap definitions (GAP-001/002/003) are recorded in
`engineering-audit.md §1`, correcting the original audit's inferred definitions.

---

## 2. Test results (full suite, not a subset)

Run with `python -m pytest tests/ -o addopts="" -p no:cacheprovider` (the project's
`addopts="-q"` suppresses the summary line, so it was overridden for an auditable
count). Artifacts captured to `research_runs/milestone-0b/` (gitignored; numbers
transcribed here verbatim).

| Metric | Pre-0B baseline (commit 3dc70ea) | Post-0B (branch feat/milestone-0b) |
|--------|----------------------------------|------------------------------------|
| Collected | 828 | 866 |
| Executed | 828 | 866 |
| Passed | 827 | 862 |
| Failed | **0** | **0** |
| Skipped | 1 | 2 |
| xfailed | 0 | 2 |
| Exit code | 0 | 0 |

**Newly introduced tests: +38**, fully accounted for:

| New / extended test module | pass | skip | xfail | total |
|----------------------------|-----:|-----:|------:|------:|
| `tests/lakehouse/test_transform_reconciliation_discrepancy.py` (new) | 9 | 1 | 2 | 12 |
| `tests/agent/test_response_validator.py` (new) | 17 | 0 | 0 | 17 |
| `tests/agent/test_agent_replay.py` (+7) | 7 | 0 | 0 | 7 |
| `tests/test_replay.py` (+2) | 2 | 0 | 0 | 2 |
| **Total** | **35** | **1** | **2** | **38** |

**Existing vs newly introduced failures:** none, in either category. All 827
pre-existing tests still pass; the two new skips/xfails are the only non-passing
*new* outcomes and are intentional (see §4).

**Coverage results:** **not available** — `pytest-cov` is not installed in this
environment (import fails). No coverage percentage is claimed. (Recommend adding
`pytest-cov` to the dev extras to enable line/branch coverage in CI.)

**Dependency & environment limitations:**
- `pytest-cov` absent (above).
- Reconciliation tests build a local DuckDB warehouse via the existing dbt fixtures;
  no network or external warehouse is used.
- No OpenAI / network calls are exercised by the suite (provider is stubbed in tests).
- Determinism-sensitive tests exclude wall-clock fields, as in the pre-existing suite.

---

## 3. Deficiencies closed

### 3.1 Reconciliation discrepancy path (was: untested — the engine's core purpose)
`tests/lakehouse/test_transform_reconciliation_discrepancy.py` forces the two engines
(dbt/SQL mart vs Python-Decimal recompute) to disagree and asserts detection,
preservation, and reporting — never silent acceptance:
- numeric mismatch → `status=="discrepancy"`, `agrees=False`, `difference > tolerance`, lineage preserved;
- missing mart row → `status=="missing_mart_value"`, `sql_value is None`;
- sub-precision difference exceeding tolerance → `discrepancy` (caught at <1e-5);
- conflicting fact-vs-mart → `discrepancy`;
- empty fact / fundamentals → `status=="insufficient_data"`, `python_value is None` (no fabricated number);
- positive control → every metric `confirmed`/`agrees`.

### 3.2 `validate_answer` fail-closed branches (was: no direct unit test)
`tests/agent/test_response_validator.py` — 17 tests covering **every** fail-closed
branch enumerated from source (claim in both groups; verified group requires VERIFIED
status; verified claim without citations when required; verified claim citing
unresolvable evidence; verified recomputed claim missing computed_value or method;
unresolved claim marked VERIFIED), plus positive and aggregation tests.

### 3.3 Integrity & replay negative paths (expanded)
`tests/agent/test_agent_replay.py` (+7) and `tests/test_replay.py` (+2): missing stage
artifact, malformed/structurally-invalid JSON, naive (non-UTC) timestamp rejection,
reproducibility failure (recomputed value diverges → `passed False`), response citing
unresolved evidence, extra rows in a stage artifact. No pre-existing assertions
duplicated.

---

## 4. Deficiencies **preserved as documented gaps** (not hidden, not "fixed" by weakening)

Per the milestone's own rule — *do not modify acceptance conditions merely to make
tests pass; preserve negative results* — the following real gaps were encoded as
`xfail(strict=True)` (which will fail-to-xpass and force conversion once fixed) or as a
reasoned `skip`, and recorded in `requirements-baseline.yaml`:

| Preserved gap | Mechanism | Requirement |
|---------------|-----------|-------------|
| Cross-validator has **no duplicate-grain guard** (`fetchone()` collapses a past-grain duplicate to one row and still confirms; grain enforced only upstream by dbt `unique` at build time) | `xfail(strict)` `test_duplicate_mart_row_should_not_confirm` | STRIX-003 |
| **View-backed metrics** (`realized_volatility`, `cumulative_return`) read a dbt intermediate *view* recomputed from the same fact rows the Python side reads → fact corruption moves both sides together and is **not caught**; reconciliation there is engine-agreement only, not fact-integrity | pinned (passing) `test_view_backed_metric_does_not_catch_fact_duplicate` | STRIX-003, 012 |
| Cross-validator **does not validate provenance** — lineage is surfaced but an empty-string artifact id still yields `confirmed` | `xfail(strict)` `test_missing_provenance_should_not_confirm` | STRIX-012, 014 |
| Cross-validator has **no content-hash integrity check** at the reconciliation layer (`bronze_artifact_id` is an identifier, not a content hash; fact tables expose no hash column) | reasoned `skip` `test_invalid_artifact_hash_is_flagged` | STRIX-001, 014 |

No production source was changed to accommodate these — they are genuine coverage of
what the code does and does not do today.

---

## 5. Documentation corrections

- `architecture/llm-boundary.md` (+ `docs/architecture/` mirror): removed the false
  "No external LLM API is called anywhere" assertion; added an accurate section
  describing the two reasoning paths (LLM-free core pipeline vs. the agent subsystem's
  real `OpenAIProvider`), with four grounded reasons the boundary holds (LLM emits
  PENDING-only; `verify_claims` runs after the model loop; verification path imports no
  LLM; `validate_answer` is fail-closed).
- `architecture/provenance.md` (+ mirror): preserved v1 content; added the
  agent/conversational evidence path (collector, citation handles vs canonical
  identity, persistence, replay limitations); added a warning that run manifests are
  **unsigned** SHA-256 content hashes establishing reproducibility/integrity — **not**
  cryptographic identity attestation (no signature, trust root, or timestamp authority
  at this commit).

Existing Mermaid diagrams and graphics were preserved.

---

## 6. Constraints honoured

- No BLKPVNTHR.OS or AFIIS dependency introduced; STRIX remains independently
  deployable. AFIIS is referenced only as an optional external client/testbed in the
  Milestone 3 spec.
- No live payments, trades, external execution authority, or production financial
  integration.
- No claim of patentability, government readiness, novelty, or commercial validation.
- Milestones 1–3 are **specified only**; none implemented in 0B.

---

## 7. Feasibility & go/no-go recommendation (deliverable #10)

> This is an engineering-feasibility recommendation about *building* the capabilities.
> It is **not** a scientific result. The research hypotheses (H1/H2/H3 in
> `comparative-experiment-design.md`) are **untested**; no performance or superiority is
> claimed.

**Established facts (verified against source at the audit commit):**
- A deterministic, LLM-independent verification substrate exists and is well tested
  (STRIX-001 ✅, STRIX-008 🟡, STRIX-015 ✅): canonical hashing, immutable evidence
  contracts, independent recompute verifiers, three replay engines with tamper
  matrices.
- That substrate is the correct foundation to build on and should be **reused, not
  rebuilt**.

**Honest gaps (what is not there):**
- GAP-001 execution control (STRIX-005/006/007) — **missing**; there is no action,
  authorization, or execution gateway, and manifests are unsigned.
- GAP-002 outcome certification (STRIX-009/010/011) — **missing**; no event-outcome
  ledger exists.
- GAP-003 heterogeneous reconciliation (STRIX-003/012/013) — **partial**; reconciliation
  works per-metric over one homogeneous warehouse, with the four preserved gaps in §4.

**Recommendation: GO — proceed to Milestone 1 (Evidence Interoperability / GAP-003).**

Rationale and conditions:
1. **Sequence GAP-003 → GAP-001 → GAP-002** (Milestones 1 → 2 → 3). M1 unifies the
   fragmented evidence/reconciliation surfaces that M2 and M3 both consume; building
   M2/M3 first would compound the existing fragmentation.
2. **Entry conditions are met for M1:** the substrate is green (0 failures), the gaps
   are documented and mapped to requirements, and the M1 spec reuses existing
   primitives.
3. **M1 exit gate (proposed):** convert the two `xfail(strict)` reconciliation tests to
   passing positive assertions (duplicate-grain guard + provenance validation), add a
   content-hash integrity check at the reconciliation layer (removing the skip), and
   land the unified `Reconciler` interface + canonical evidence schema.
4. **Hold conditions:** M2 (execution assurance) must not begin until its TOCTOU
   mitigation and signed-authorization-certificate design pass review — signing is a
   hard prerequisite the current codebase lacks entirely.
5. **No-go for any live execution** in M2/M3 until the comparative experiments
   (`comparative-experiment-design.md`) have been run and the falsification criteria
   evaluated; feasibility-to-build does not imply validated-to-deploy.

**Net:** the engineering foundation is sound and the remediation is complete and green;
the three research opportunities are **feasible to implement** in the specified order.
Their scientific validity remains an open, falsifiable question to be settled by the
designed experiments — not by this report.
