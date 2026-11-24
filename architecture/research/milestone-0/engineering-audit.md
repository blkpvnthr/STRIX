# STRIX Engineering Audit — Milestone 0

**Audit commit of record:** `3dc70eac6b6b178d51156185113beb70d7c899e4`
**Branch audited:** `feat/conversational-intelligence`
**Remediation branch:** `feat/milestone-0b`
**Audit date:** 2026-11-24

> **Method.** Every classification below was verified against source at the audit
> commit (file:symbol), not against README/docs claims. Where documentation
> diverged from code, the divergence is recorded in §4. Baseline test state at the
> audit commit: **828 tests collected, 827 passed, 1 skipped, 0 failed**
> (`research_runs/milestone-0b/baseline_fulltest.txt`).

> **Claim discipline.** This document records *established implementation facts* and
> *explicit non-implementation*. It makes **no** claims of novelty, performance
> superiority, patentability, or deployment readiness. Falsifiable research
> hypotheses are stated separately in
> [`comparative-experiment-design.md`](./comparative-experiment-design.md).

---

## 1. Corrected research gap definitions

The original commit audit inferred the three gaps from their component groupings.
Those inferences were **superseded** by the authoritative definitions below. The
original inferences are preserved for traceability, each followed by the correction.

### GAP-001 — Dynamic Evidence-Bound Execution Assurance

**Authoritative definition.** Investigate whether an independent verification engine
can prevent previously authorized actions from executing when supporting evidence
becomes stale, contradictory, or invalid. Scope: versioned requirements and
authorization policies; evidence freshness and validity; exact action-parameter
binding; execution-time revalidation; cryptographic authorization certificates;
replay prevention; deterministic enforcement; independent verification and
abstention. **Signed manifests alone do not establish execution assurance.**

*Original audit inference (superseded):* "coverage completeness & certified
freshness." **Correction:** the gap is about *execution-time assurance* — gating
actions against live evidence validity — not merely proving coverage of answered
questions. The audit undercounted the action/authorization dimension entirely
(STRIX-005/006/007 are **missing**, not partial).

### GAP-002 — Closed-Loop Execution and Outcome Certification

**Authoritative definition.** Investigate reliable linkage between authorized
decisions, executed actions, and independently verified outcomes despite retries,
partial failures, and incomplete outcome evidence. Implement as a
**domain-independent** research capability, not a trading-specific subsystem.
Financial payments serve as the initial experimental application through AFIIS
(an *optional external client/testbed*; STRIX takes no AFIIS dependency).

*Original audit inference (superseded):* "outcome attribution (trading)."
**Correction:** the gap is domain-independent decision→action→outcome certification.
The original audit was right that the capability is **missing**, but wrong to frame
it as trading-specific — it must be built as a general ledger/outcome-contract
capability (STRIX-009/010/011).

### GAP-003 — Interoperable Financial Evidence Verification

**Authoritative definition.** Investigate methods for reconciling conflicting
records across heterogeneous sources while preserving requirements traceability,
provenance, and appropriate abstention. **Deterministic claim verification is
foundational infrastructure but does not independently satisfy this objective.**

*Original audit inference (superseded):* "claim-verification integrity."
**Correction:** deterministic verification (strong at this commit) is necessary but
not sufficient. The gap additionally requires heterogeneous cross-source
reconciliation with preserved traceability and first-class abstention
(STRIX-012/013), where coverage is currently **partial** and the discrepancy path
was **untested** pre-0B.

---

## 2. Component audit (10 components)

Classification vocabulary: **implemented-and-tested · partially-implemented ·
missing · requiring-redesign**. Test counts are from the audit commit.

### 2.1 Evidence contracts — ✅ implemented-and-tested · GAP-001, GAP-003

- Frozen, closed-schema base: `src/strix/models.py` `StrixModel`
  (`ConfigDict(frozen=True, extra="forbid")`), mirrored in `corpus/models.py`,
  `lakehouse/contracts.py`.
- Type-level float rejection: `DecimalValue = Annotated[Decimal, BeforeValidator(_reject_float)]`
  (`models.py`); re-forbidden in `canonical.py`.
- Four parallel contract families: core pipeline (`models.py`), agent research
  (`agent/models.py`: `AgentEvidence`, `Observation`, `AgentClaim`,
  `ClaimVerification`), conversational response (`agent/models.py`:
  `ResearchResponse`, `EpistemicClass`, `MarketAssessment`), provider
  (`agent/contracts.py`), engineering (`engineering/models.py`: discriminated-union
  `Anchor`/`FactPayload`), lakehouse, corpus.
- Fail-closed contract validation: `agent/response_validator.py::validate_answer`,
  wired at `orchestrator.py`.
- **Tests:** `test_contracts.py` (7), `test_agent_models.py` (9),
  `test_response_contracts.py` (8), `test_lakehouse_contracts.py` (4), plus
  engineering/core contract tests — all assert behavior.
- **Gaps:** `validate_answer`'s fail-closed branches had **no direct unit test**
  pre-0B (closed this milestone — §5 / STRIX-008); triple-duplicated
  `Claim`/`Evidence`/`VerificationStatus` vocabularies (maintenance smell, §3).

### 2.2 Provenance tracking — ✅ implemented-and-tested · GAP-001, GAP-002, GAP-003

- Content-derived identity + hashing: `canonical.py::make_id` =
  `PREFIX-sha256(canonical_json)[:12]`; `sha256_hex` for raw bytes. Explicit
  doctrine **hash = integrity, not veracity**.
- Anchors ≠ identity: `engineering/models.py` `XmlPathAnchor.element_fingerprint`,
  `TextRangeAnchor.paragraph_hash`; module invariant "a logical anchor alone is
  never sufficient evidence identity."
- Evidence collection/preservation: `agent/evidence_collector.py::register`
  (SHA-256 raw bytes, dedup, lineage enforced at insertion).
- Citation handles ≠ identity: `agent/citations.py::resolve_claim_citations`
  (rewrites provider web handles to canonical ids, drops/records dangling handles);
  `register_alias` first-writer-wins, never shadows a real id.
- Lineage verification: `verification/claims.py::_verify_evidence_lineage`
  (`INCOMPLETE_LINEAGE`); `agent/verifier.py` requires every backing series to trace
  to cited evidence.
- **Tests:** `test_citations.py` (6, incl.
  `test_dangling_handle_never_reaches_rendered_answer`),
  `test_evidence_collector.py` (6), `test_verifier.py` (13), `test_evidence.py`
  (12), replay/tamper matrices.
- **Caveats:** traceability ≠ veracity (textual attribution is a verbatim substring
  check — can over-attribute); agent artifact bytes are **in-memory**
  (`EvidenceCollector._artifacts`), durability depends on `persistence.py`/`run_store.py`;
  `architecture/provenance.md` lagged the agent path (corrected §4 / this milestone).

### 2.3 Deterministic claim verification — ✅ implemented-and-tested · GAP-003

- Two independent verifiers: `verification/claims.py` (exact value/unit + statement
  re-render equality; "performs no new financial calculation") and
  `agent/verifier.py::_verify_numeric` (re-derives via
  `agent/calculations.py::recompute` on preserved series, `DEFAULT_TOLERANCE=1e-4`,
  `CONTRADICTED` on breach). Engineering verifier re-derives candidate content
  field-by-field (`engineering/verifier.py`).
- **Verification path is genuinely LLM-free** — `claims.py`, `agent/verifier.py`,
  `agent/calculations.py`, `engineering/verifier.py` import no LLM library. An LLM
  exists (`agent/openai_provider.py`, `orchestrator.py`) strictly as a **proposer**;
  `verify_claims(...)` runs **after** the provider loop. The model may only emit
  `verification.status == PENDING`.
- Advisory-only sanity layer (`agent/sanity.py`) never changes a verdict.
- **Tests:** `test_verification.py` (23), `test_verifier.py` (13),
  `test_calculations.py` (17), engineering builder/verifier (32),
  `TestReasonerIsolation`.
- **Gaps:** `architecture/llm-boundary.md` falsely asserted "no external LLM API is
  called anywhere" — **false** against the agent path (corrected §4 / this
  milestone). Two divergent verifiers (smell). `claims.py` handles only the single
  hard-coded `profitability_change` shape.

### 2.4 Requirements registry — ⚠️ partially-implemented · GAP-001

- Real in engineering: `engineering/models.py` `RequirementFact`, `AllocationFact`,
  `RelationshipType.ALLOCATED_TO`; `adapters/reqif.py` parses ReqIF `SPEC-OBJECT`
  keyed by `IDENTIFIER` with duplicate-ID rejection; coverage computed in
  `engineering/metrics.py` (`traceability_coverage`, `allocation_coverage`).
- **Not** a registry on the agent/research side: `agent/question.py::classify_question`
  is a deterministic keyword classifier returning ephemeral `ResearchQuestion`
  (`evidence_requirements` are category labels — no IDs, no status, no persistence,
  no later satisfaction check). `agent/contracts.py` is token-cost billing, unrelated.
- **Tests:** `test_manifest_and_adapters.py` (23), `test_builder_and_verifier.py`
  (32), `test_export_metrics_determinism.py` (11), `test_question.py` (11, classifier
  only).
- **Gaps:** no persistent cross-run registry; requirements re-derived per compile;
  `RequirementFact` has no status/version field; `traceability_coverage` measures
  export-resolvability, not "fraction of requirements answered."

### 2.5 Evidence freshness monitoring — ⚠️ partially-implemented · GAP-001

- `agent/evidence_collector.py::classify_freshness` (CURRENT/STALE/UNKNOWN vs
  `DEFAULT_MAX_AGE_DAYS=45`), consumed by `agent/verifier.py` (VERIFIED→STALE
  downgrade), surfaced in `response_builder.py`.
- Corpus side is **change detection, not freshness**: `scanner.py` records no
  timestamps; `diff.py` classifies by path+hash+size; `rescan.py` has "no watcher,
  no background/automatic triggering." `lakehouse/ingest/checkpoints.py` are
  resumability watermarks, not freshness. `agent/sources.py` carries `retrieved_at`
  but nothing evaluates its age.
- **Tests:** `test_evidence_collector.py::test_classify_freshness`,
  `test_verifier.py::test_verified_but_stale_is_downgraded`,
  `test_agent_models.py::test_evidence_freshness_default`.
- **Gaps:** no re-fetch/expiry/alert trigger; single hard-coded threshold; no
  execution-time freshness gate; corpus & lakehouse have no age concept. This is a
  core GAP-001 shortfall.

### 2.6 Execution certification — ⚠️ partially-implemented · GAP-001

- Hash-manifest + atomic persistence + attestation-by-replay are
  implemented-and-tested: `EngineeringRunManifest` per-stage hashes
  (`models.py`), agent manifest in `persistence.py`, `run_store.py` atomic/fsync/
  hash-re-verified raw, three replay engines.
- **Missing:** cryptographic signing / attestation. Repo-wide search for
  `sign|signature|attest|certificate|hmac|ed25519|rsa|private_key|x509` yields only
  false positives. The "certificate" is an **unsigned** SHA-256 manifest; integrity
  rests on recomputation, not a key/identity. No binary/environment attestation.
- **Tests:** `test_cli_replay_tamper.py` (21), `test_replay.py` (10),
  `test_run_store.py` (16), `test_canonical.py` (17), `test_agent_replay.py` (6).
- **Gaps:** per the GAP-001 definition, **signed manifests alone do not establish
  execution assurance** — and STRIX does not even sign them yet (STRIX-005/006/007
  missing).

### 2.7 Event & outcome correlation — ❌ missing · GAP-002

- The decision→action→outcome concept does **not exist**. Only: statistical
  Pearson `correlation()` (`agent/calculations.py`), HTTP `X-Correlation-ID` echo
  (`service.py`), and backward data-lineage (`input_fact_ids`). `market/engine.py`
  is explicitly "a research engine only … no brokerage capability." `memory.py`
  links conversation turns by thread (context hints only, not outcome linkage).
- **Tests:** none for event-outcome correlation (it does not exist).
- **Gaps:** entire capability absent. Per corrected GAP-002, this must be built
  **domain-independent** (STRIX-009/010/011), not trading-specific.

### 2.8 Reconciliation engine — ⚠️ partially-implemented · GAP-002, GAP-003

- Genuine two-source reconciliation exists:
  `lakehouse/transform/verification.py::WarehouseCrossValidator` reconciles a
  dbt/SQL mart value against an independent Python-Decimal recompute under tolerance
  (`confirmed`/`discrepancy`). Also `agent/verifier.py::_verify_numeric`,
  `corpus/diff.py::compute_diff`, `engineering/verifier.py::_verify_configuration`.
- **Critical pre-0B gap:** the **discrepancy branch — the engine's whole purpose —
  was untested**; all tests asserted the `agrees`/`confirmed` happy path. Closed
  this milestone (§5 / STRIX-003, STRIX-012).
- **Tests:** `test_transform_dbt.py` (22, agreement controls),
  `test_transform_reconciliation_discrepancy.py` (0B: forced discrepancies),
  `test_diff.py` (20), engineering conflict paths.
- **Gaps:** no unified reconciliation interface/discrepancy type (4 fragmented
  modules); heavyweight (requires a built warehouse); no canonical heterogeneous
  financial evidence schema (Milestone 1).

### 2.9 Replay infrastructure — ✅ implemented-and-tested · GAP-001, GAP-002, GAP-003

- Three engines (`replay.py`, `agent/replay.py`, `engineering/replay.py`), each a
  three-way comparison (manifest hash vs stored-artifact hash vs recomputed hash),
  separating integrity from reproducibility, excluding wall-clock fields; CLI
  dispatch by manifest `mode`.
- **Tests (~37):** `test_replay.py` (10), `test_agent_replay.py` (6),
  `test_cli_replay_tamper.py` (21 — full tamper matrix incl. anchor drift, row
  reorder, ground-truth isolation).
- **Caveats:** recomputes with current code + recorded versions (not an adversarial
  re-implementation); manifest itself unsigned; agent replay does not reproduce LLM
  wording (by design).

### 2.10 Independent audit trail — ⚠️ partially-implemented · GAP-001, GAP-002, GAP-003

- Strong canonical hashing (`canonical.py`), integrity records (`RunManifest`,
  `EngineeringRunManifest`), crash-safe atomic persistence (`run_store.py`,
  manifest written last), append-only content-addressed lakehouse provenance
  (`lakehouse/bronze.py`, per-ingestion).
- **Missing:** an append-only **ordered per-run event log**; **hash chaining /
  Merkle linkage** (`previous_hash` absent); **digital signatures / external
  anchoring**. Tamper-evidence currently requires recompute via replay — not
  standalone third-party verifiable.
- **Tests (~67):** `test_canonical.py` (17), `test_run_store.py` (16),
  `test_manifest_and_adapters.py` (23), `test_export_metrics_determinism.py` (11),
  plus replay tamper matrices.
- **Gaps:** "independent" is qualified — verification re-derives with the same code.
  STRIX-014 covers the chain/signature/ordered-log work.

---

## 3. Architectural smells (redesign candidates, not whole-component failures)

1. **Triple-duplicated vocabularies** — `Claim`/`Evidence`/`VerificationStatus`/
   `FailureCode` across `strix.models`, `strix.agent.models`,
   `strix.engineering.models` (two distinct `FORECAST` enums). A unification target
   for Milestone 1's canonical evidence schema.
2. **Two divergent verifiers** — `verification/claims.py` (hard-coded
   `profitability_change`) vs `agent/verifier.py` (series recompute); duplicated
   lineage/as-of/version concepts.
3. **Fragmented reconciliation** — four reconcilers with no shared interface or
   discrepancy type (STRIX-012 unification target).

## 4. Documentation discrepancies corrected this milestone

- `architecture/llm-boundary.md` (+ `docs/architecture/` mirror): the blanket
  "no external LLM API is called anywhere" was **false** against the agent path
  (`openai_provider.py`, `orchestrator.py`). Rewritten to describe the real boundary
  (LLM proposes; deterministic verifier is the authoritative acceptance boundary;
  LLM cannot bypass admissibility/certification).
- `architecture/provenance.md` (+ mirror): extended to cover agent/conversational
  evidence collection, citation handles vs canonical identity, persistence, and
  replay limitations; corrected any text equating an unsigned SHA-256 manifest with
  cryptographic identity attestation.

## 5. Test-coverage deficiencies closed this milestone

- **Reconciliation discrepancy path** (`WarehouseCrossValidator`): added forced
  numeric-mismatch, missing-record, invalid-precision, conflicting-evidence,
  missing-provenance, invalid-hash, empty-dataset, and positive-control tests.
- **`response_validator.validate_answer`**: added direct unit tests for every
  fail-closed branch.
- **Integrity & replay negative paths**: expanded coverage of missing/modified
  artifacts, inconsistent hashes, malformed evidence, invalid timestamps, and
  reproducibility failures.

See [`remediation-report.md`](./remediation-report.md) for the exact files, test
counts, and any unresolved failures (preserved, not hidden).
