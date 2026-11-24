# STRIX Requirements Traceability Matrix — Milestone 0B

**Audit commit of record:** `3dc70eac6b6b178d51156185113beb70d7c899e4`
**Branch:** `feat/milestone-0b`
**Machine-readable source of truth:** [`requirements-baseline.yaml`](./requirements-baseline.yaml)

This matrix traces each formal requirement (STRIX-001…015) to its governing research
gap, its implementation in source, and its verifying test(s), with an honest status.
It is the human-readable projection of `requirements-baseline.yaml`; if the two ever
disagree, the YAML governs.

**Status legend:** ✅ implemented (code + passing test) · 🟡 partial · 🧪 untested
(code exists, no direct asserting test) · ❌ missing · 🔲 proposed (later milestone).

---

## 1. Requirement → gap → implementation → verification

| Req | Title | Gap | Status | Implementation (file:symbol) | Verification (test) |
|-----|-------|-----|--------|------------------------------|---------------------|
| STRIX-001 | Immutable evidence preservation | 003·001·002 | ✅ | `models.py:StrixModel`; `canonical.py:canonical_hash/make_id`; `run_store.py:_preserve_raw_files`; `evidence_collector.py:register` | `test_canonical.py`; `test_evidence.py::test_modified_bytes_change_artifact_identity`; `test_run_store.py` |
| STRIX-002 | Versioned requirements & authorization policies | 001 | 🟡 | `engineering/models.py:RequirementFact/AllocationFact`; `adapters/reqif.py:ReqIfAdapter.parse`; `engineering/metrics.py:allocation_coverage` | `test_manifest_and_adapters.py`; `test_builder_and_verifier.py` |
| STRIX-003 | Contradictory evidence detection | 003 | 🟡 | `lakehouse/transform/verification.py:WarehouseCrossValidator`; `agent/verifier.py:_verify_numeric` | `test_verifier.py` (CONTRADICTED); **`test_transform_reconciliation_discrepancy.py` (0B)** |
| STRIX-004 | Evidence freshness enforcement | 001 | 🟡 | `evidence_collector.py:classify_freshness`; `agent/verifier.py:_has_stale_evidence` | `test_evidence_collector.py::test_classify_freshness`; `test_verifier.py::test_verified_but_stale_is_downgraded` |
| STRIX-005 | Exact action-parameter binding | 001·002 | ❌ | none (reusable: `canonical.py:canonical_hash`) | 🔲 Milestone 2 spec |
| STRIX-006 | Execution-time authorization revalidation | 001 | ❌ | none | 🔲 Milestone 2 spec (TOCTOU matrix) |
| STRIX-007 | Replay-resistant authorization | 001 | ❌ | none (adjacent: `ingest/checkpoints.py` idempotency) | 🔲 Milestone 2 spec |
| STRIX-008 | Independent certification boundaries | 001 | 🟡 | `verification/claims.py`, `agent/verifier.py` (no LLM imports); `orchestrator.py` (verify after propose); `response_validator.py:validate_answer` | **`test_response_validator.py` (0B)**; `test_cli.py::TestReasonerIsolation` |
| STRIX-009 | Decision-to-execution event correlation | 002 | ❌ | none (adjacent only: `service.py` X-Correlation-ID; `memory.py` thread link) | 🔲 Milestone 3 spec |
| STRIX-010 | Independent outcome verification | 002 | ❌ | none | 🔲 Milestone 3 spec |
| STRIX-011 | Retry & partial-failure handling | 002 | ❌ | none for outcomes (adjacent: `ingest/checkpoints.py`) | 🔲 Milestone 3 spec |
| STRIX-012 | Heterogeneous evidence reconciliation | 003 | 🟡 | `lakehouse/transform/verification.py:WarehouseCrossValidator`; `engineering/verifier.py:_verify_configuration` | `test_transform_dbt.py`; **`test_transform_reconciliation_discrepancy.py` (0B)** |
| STRIX-013 | Explicit abstention | 003·001·002 | 🟡 | `agent/verifier.py` (INSUFFICIENT_EVIDENCE/UNVERIFIABLE); `verification/claims.py` (INCOMPLETE_LINEAGE) | `test_verifier.py`; `test_verification.py` |
| STRIX-014 | Independently verifiable audit evidence | 003·001·002 | 🟡 | `canonical.py`; `run_store.py`; `lakehouse/bronze.py` (append-only, per-ingestion) | `test_run_store.py`; `test_cli_replay_tamper.py` (via recompute) |
| STRIX-015 | Deterministic replay | 003·001·002 | ✅ | `replay.py`; `agent/replay.py`; `engineering/replay.py` | `test_replay.py`; `test_agent_replay.py`; `test_cli_replay_tamper.py` |

**Bold** entries are tests added or extended during Milestone 0B.

## 2. Status roll-up

| Status | Count | Requirements |
|--------|-------|--------------|
| ✅ implemented | 2 | STRIX-001, STRIX-015 |
| 🟡 partial | 7 | STRIX-002, 003, 004, 008, 012, 013, 014 |
| ❌ missing | 6 | STRIX-005, 006, 007, 009, 010, 011 |

> Tally: **implemented 2 · partial 7 · missing 6 · total 15.** No requirement is
> fully satisfied in the two areas (GAP-001 execution control, GAP-002 outcome
> certification) that the three research opportunities most depend on.

## 3. Gap coverage summary

- **GAP-003** (Interoperable Financial Evidence Verification): best covered — STRIX-001
  (✅), 003/012/013 (🟡), 014 (🟡), 015 (✅). Foundational verification is strong;
  heterogeneous cross-source reconciliation and first-class abstention are partial.
- **GAP-001** (Dynamic Evidence-Bound Execution Assurance): the assurance *substrate*
  (001 ✅, 002/004/008 🟡, 014/015) exists, but the **execution-control dimension is
  absent** — STRIX-005/006/007 are all ❌. Signed manifests are not even present yet
  (manifests are unsigned hashes).
- **GAP-002** (Closed-Loop Execution and Outcome Certification): **least covered** —
  the defining capability (STRIX-009/010/011) is entirely ❌ and must be built
  domain-independently.

## 4. Change control

Requirements are versioned individually (`version:` in the YAML). A status change,
new implementation reference, or new verification test is a version bump to the
affected requirement and an update to both this matrix and the YAML in the same
commit. New requirements take the next STRIX-0NN id and must declare a gap, rationale,
acceptance criteria, and verification method before moving past `proposed`.
