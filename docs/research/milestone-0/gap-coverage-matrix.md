# STRIX Research Gap Coverage Matrix — Milestone 0B

**Audit commit of record:** `3dc70eac6b6b178d51156185113beb70d7c899e4`
**Branch:** `feat/milestone-0b`

Ties the ten audited infrastructure components and the fifteen formal requirements
(STRIX-001…015) to the three **authoritative** research gaps. See
[`engineering-audit.md`](./engineering-audit.md) for component evidence and
[`requirements-traceability.md`](./requirements-traceability.md) for per-requirement
detail.

> The gap definitions below are the authoritative ones. The original commit audit's
> inferred definitions were superseded (recorded in `engineering-audit.md §1`).

---

## 1. Component × gap matrix

Status: ✅ implemented-and-tested · 🟡 partial · ❌ missing. A ✓ marks that the gap
depends on the component.

| Component | GAP-001 | GAP-002 | GAP-003 | Status | Governing reqs |
|-----------|:------:|:------:|:------:|--------|----------------|
| Evidence contracts | ✓ | | ✓ | ✅ | STRIX-001 |
| Provenance tracking | ✓ | ✓ | ✓ | ✅ | STRIX-001, 014 |
| Deterministic claim verification | | | ✓ | ✅ | STRIX-008, 013 |
| Requirements registry | ✓ | | | 🟡 | STRIX-002 |
| Evidence freshness monitoring | ✓ | | | 🟡 | STRIX-004 |
| Execution certification | ✓ | | | 🟡 | STRIX-006, 008 |
| Event & outcome correlation | | ✓ | | ❌ | STRIX-009, 010, 011 |
| Reconciliation engine | | ✓ | ✓ | 🟡 | STRIX-003, 012 |
| Replay infrastructure | ✓ | ✓ | ✓ | ✅ | STRIX-015 |
| Independent audit trail | ✓ | ✓ | ✓ | 🟡 | STRIX-014 |

---

## 2. GAP-001 — Dynamic Evidence-Bound Execution Assurance

**Question.** Can an independent verification engine *prevent previously authorized
actions from executing* when supporting evidence becomes stale, contradictory, or
invalid?

| Capability (scope item) | Requirement | Status |
|--------------------------|-------------|--------|
| Versioned requirements & authorization policies | STRIX-002 | 🟡 (requirements only; no policy/version/standing registry) |
| Evidence freshness & validity | STRIX-004 | 🟡 (classify + downgrade; no execution-time gate, no re-fetch/expiry) |
| Exact action-parameter binding | STRIX-005 | ❌ |
| Execution-time revalidation | STRIX-006 | ❌ |
| Cryptographic authorization certificates | STRIX-007, 008 | ❌ (manifests are unsigned hashes) |
| Replay prevention (authorization) | STRIX-007 | ❌ |
| Deterministic enforcement | STRIX-008, 015 | ✅ substrate / ❌ enforcement layer |
| Independent verification & abstention | STRIX-008, 013 | 🟡 |

**Readiness: NOT MET — largest build.** The verification/replay *substrate* is strong,
but there is **no action, no authorization, and no execution gateway** at this commit.
Per the gap's own wording, "signed manifests alone do not establish execution
assurance" — and STRIX does not yet even sign manifests. Closing GAP-001 is the subject
of Milestone 2 (`milestone-2-execution-assurance-spec.md`), including explicit TOCTOU
handling.

## 3. GAP-002 — Closed-Loop Execution and Outcome Certification

**Question.** Can authorized decisions, executed actions, and independently verified
outcomes be reliably linked despite retries, partial failures, and incomplete outcome
evidence — as a **domain-independent** capability?

| Capability | Requirement | Status |
|------------|-------------|--------|
| Decision→action→outcome correlation | STRIX-009 | ❌ |
| Independent outcome observation & verification | STRIX-010 | ❌ |
| Retry / duplicate / partial-failure handling | STRIX-011 | ❌ (adjacent ingest idempotency only) |
| Signed/anchored audit checkpoints | STRIX-014 | 🟡 (hashes, no chain/signature) |
| Provenance & replay support | STRIX-001, 015 | ✅ |

**Readiness: NOT MET — defining capability absent.** The supporting substrate
(provenance, replay, audit records) exists, but the *defining* capability — a
domain-independent decision/execution/outcome event ledger with correlation ids and
independent outcome verification — **does not exist**. The original audit correctly
found it missing; the correction is that it must be built domain-independently (payments
via AFIIS are an optional external testbed only). Subject of Milestone 3
(`milestone-3-outcome-certification-spec.md`).

## 4. GAP-003 — Interoperable Financial Evidence Verification

**Question.** Can conflicting records be reconciled across heterogeneous sources while
preserving requirements traceability, provenance, and appropriate abstention?

| Capability | Requirement | Status |
|------------|-------------|--------|
| Immutable evidence + provenance | STRIX-001, 014 | ✅ / 🟡 |
| Deterministic claim verification (foundation) | STRIX-008 | ✅ |
| Contradictory-evidence detection | STRIX-003 | 🟡 (discrepancy path tested in 0B) |
| Heterogeneous cross-source reconciliation | STRIX-012 | 🟡 (per-metric; no unified interface/schema) |
| Requirements traceability preserved through reconciliation | STRIX-002, 012 | 🟡 |
| Explicit abstention | STRIX-013 | 🟡 |
| Deterministic replay | STRIX-015 | ✅ |

**Readiness: PARTIAL — closest, but not met.** Deterministic verification is strong and
is explicitly *foundational but not sufficient*. The missing piece is a canonical
heterogeneous financial evidence schema plus a unified reconciliation interface that
preserves traceability and abstains correctly across *different source types* (today's
`WarehouseCrossValidator` reconciles two engines over one homogeneous warehouse).
Subject of Milestone 1 (`milestone-1-evidence-interoperability-spec.md`).

---

## 5. Overall readiness

| Gap | Substrate present | Defining capability | Verdict |
|-----|-------------------|---------------------|---------|
| GAP-001 | ✅ strong (verify/replay/evidence) | ❌ no action/authorization/execution gate | **NOT MET** |
| GAP-002 | ✅ provenance/replay/audit | ❌ no event-outcome ledger | **NOT MET** |
| GAP-003 | ✅ verification/provenance | 🟡 reconciliation partial, no canonical cross-source schema | **PARTIAL** |

**Sequencing implication.** GAP-003 (Milestone 1) is the natural first build: it unifies
the fragmented evidence/reconciliation surfaces that GAP-001 and GAP-002 both consume.
GAP-001 (Milestone 2) then adds the execution-assurance layer on the unified evidence
substrate; GAP-002 (Milestone 3) adds the outcome-certification loop on top. This matrix
and the milestone specs assume that order.

> **Claim discipline.** "Readiness" here describes *implementation coverage of the
> stated scope*, verified against source at the audit commit. It is **not** a claim of
> correctness-under-adversary, performance, or novelty. Those are the subject of the
> falsifiable experiments in `comparative-experiment-design.md` and have **not** been
> run.
