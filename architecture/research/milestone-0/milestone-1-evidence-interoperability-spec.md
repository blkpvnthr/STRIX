# Milestone 1 — Evidence Interoperability Specification (§8)

**Audit commit of record:** `3dc70eac6b6b178d51156185113beb70d7c899e4`
**Work branch:** `feat/milestone-0b`
**Gap:** GAP-003 — Interoperable Financial Evidence Verification
**Companions:** [`requirements-baseline.yaml`](./requirements-baseline.yaml),
[`engineering-audit.md`](./engineering-audit.md),
[`comparative-experiment-design.md`](./comparative-experiment-design.md).

> **Claim discipline.** This spec records what to BUILD and which existing
> primitives to REUSE. It separates ESTABLISHED IMPLEMENTATION FACTS (what the
> audit commit already contains) from the DESIGN PROPOSAL (new work). It asserts
> no novelty, performance, patentability, or readiness. Hypothesis H3 in the
> experiment design is the falsifiable claim; this spec is the construction plan.
> Implementation-ready but honest about unknowns (see Open Questions).

---

## 1. Goal

Make heterogeneous financial evidence **interoperable**: normalize records from
different sources into one canonical, immutable, provenance-preserving evidence
representation; reconcile the same fact across sources through **one shared
interface**; represent conflicts as a **typed, first-class** result; and
**abstain explicitly** when a conflict is unresolvable — all while preserving
byte-level provenance and STRIX requirements traceability.

This milestone unifies today's fragmented reality: **three duplicated evidence
vocabularies** and **four independent reconcilers** (audit §3) behind a single
canonical schema and reconciliation interface. It is the foundation GAP-003
requires; deterministic claim verification (already strong) is necessary but, per
the authoritative GAP-003 definition, **not sufficient** alone.

---

## 2. In-scope / Out-of-scope

**In-scope**
- Canonical financial evidence schema spanning sources (SEC/EDGAR, market data,
  lakehouse marts, agent web/research evidence, engineering artifacts).
- Source normalization adapters producing canonical evidence from raw bytes.
- Provenance preservation (byte-exact raw + content hash + lineage + source
  identity) through normalization and reconciliation.
- A single `Reconciler` interface and a typed `Discrepancy` / reconciliation
  outcome unifying the four existing reconcilers.
- First-class, typed **abstention** as a reconciliation outcome.
- Cross-source verification: compare independent representations of one fact
  under documented tolerance; never silently prefer one.
- Requirements traceability: every canonical fact and reconciliation outcome
  carries the STRIX requirement id(s) it serves.

**Out-of-scope (later milestones / explicitly not here)**
- Execution-time authorization, certificates, freshness *gating* (→ M2 /
  STRIX-004/006).
- Decision→action→outcome ledger and outcome observation (→ M3).
- Cryptographic signing / hash-chaining of the audit log (→ M2/M3 / STRIX-014).
- Any new financial *calculation*; reconciliation reuses existing calculators.
- Live data fetching policy changes; M1 consumes already-collected evidence.

---

## 3. Requirements covered (STRIX IDs)

| Requirement | How M1 addresses it | Current status (baseline) |
|---|---|---|
| **STRIX-012** Heterogeneous evidence reconciliation | New `Reconciler` interface + canonical schema unify the 4 reconcilers; preserve provenance/traceability through reconciliation. | partial |
| **STRIX-013** Explicit abstention | Abstention becomes a first-class cross-source reconciliation outcome, not just per-claim. | partial |
| **STRIX-003** Contradictory evidence detection | Shared typed `Discrepancy`; never silently accept; preserve both values + lineage. | partial |
| **STRIX-001** Immutable evidence preservation | New schema is built on `StrixModel` (frozen, extra-forbid, Decimal-only) + `run_store` raw preservation. | implemented (reused) |

---

## 4. Proposed modules / files (new `src` paths)

> New code lives under a new `src/strix/evidence/` package so it can be adopted
> incrementally without destabilizing the four existing reconcilers (which are
> refactored to *implement* the new interface, not deleted wholesale).

```
src/strix/evidence/
  __init__.py
  canonical_evidence.py     # CanonicalEvidence, SourceRef, Provenance, FactKey
  vocabulary.py             # unified VerificationStatus / ReconcileOutcome / FailureCode
  normalize/
    __init__.py
    base.py                 # SourceNormalizer protocol
    edgar.py                # EDGAR/SEC -> CanonicalEvidence
    market.py               # market bars -> CanonicalEvidence
    lakehouse.py            # dbt marts -> CanonicalEvidence (wraps WarehouseCrossValidator inputs)
    agent.py                # AgentEvidence -> CanonicalEvidence
    engineering.py          # EngineeringEvidence -> CanonicalEvidence
  reconcile/
    __init__.py
    interface.py            # Reconciler protocol, ReconciliationResult, Discrepancy, Abstention
    numeric.py              # tolerance-based numeric reconciliation (wraps agent.calculations)
    record.py               # presence/key reconciliation (missing-record, stale-vs-fresh)
    adapters.py             # shims: WarehouseCrossValidator / verifier / diff / eng-verifier -> Reconciler
  traceability.py           # RequirementRef binding + coverage over canonical evidence
```

**Refactor (not rewrite) targets** — made to implement `Reconciler`:
- `lakehouse/transform/verification.py:WarehouseCrossValidator`
- `agent/verifier.py:_verify_numeric`
- `corpus/diff.py:compute_diff`
- `engineering/verifier.py:_verify_configuration`

---

## 5. Data contracts (sketch)

All models subclass `strix.models.StrixModel` (frozen, `extra="forbid"`,
`DecimalValue` float-reject) and derive ids via `strix.canonical.make_id`.

```python
# vocabulary.py — the ONE vocabulary (replaces the 3 duplicated ones over time)
class ReconcileOutcome(StrEnum):
    CONFIRMED      = "confirmed"       # independent representations agree
    DISCREPANCY    = "discrepancy"     # disagree beyond tolerance (both kept)
    MISSING_RECORD = "missing_record"  # a source lacks the fact
    ABSTAINED      = "abstained"       # unresolvable / insufficient admissible evidence
    INSUFFICIENT   = "insufficient_evidence"

# canonical_evidence.py
class SourceRef(StrixModel):
    source_kind: str            # open validated vocab (edgar|market|lakehouse|agent|engineering|...)
    provider: str
    source_id: str              # accession / symbol+date / mart row key / EV-id / ART-id
    content_hash: str           # sha256 of preserved raw bytes (integrity, not veracity)
    retrieved_at: AwareDatetime
    published_at: AwareDatetime | None = None

class Provenance(StrixModel):
    source_ref: SourceRef
    raw_artifact_ref: str       # run_store raw/ reference; byte-exact preserved
    lineage_ids: tuple[str, ...]  # upstream fact/evidence ids (backward lineage)

class FactKey(StrixModel):
    """Identity of the real-world fact, independent of which source reports it."""
    subject: str                # cik / symbol / part_id
    concept: str                # revenue / close / max_drawdown / revision
    period: str                 # ISO date or period label
    unit: str
    # fact_key id = make_id("FK", {...}); the join key across sources.

class CanonicalEvidence(StrixModel):
    evidence_id: str            # make_id("CEV", payload)
    fact_key_id: str
    value: DecimalValue | None  # None for non-numeric / attributed records
    text: str | None = None
    provenance: Provenance
    requirement_refs: tuple[str, ...] = ()   # STRIX-/project requirement ids served

# reconcile/interface.py
class Discrepancy(StrixModel):
    fact_key_id: str
    left: CanonicalEvidence
    right: CanonicalEvidence
    difference: DecimalValue | None
    tolerance: DecimalValue | None
    note: str

class Abstention(StrixModel):
    fact_key_id: str
    reason: str                 # why unresolvable (conflicting, incomplete lineage, ...)
    considered: tuple[str, ...] # evidence ids weighed

class ReconciliationResult(StrixModel):
    fact_key_id: str
    outcome: ReconcileOutcome
    agreed_value: DecimalValue | None = None
    discrepancy: Discrepancy | None = None
    abstention: Abstention | None = None
    inputs: tuple[str, ...]           # contributing canonical evidence ids
    requirement_refs: tuple[str, ...] = ()
    reconciler_version: str

class Reconciler(Protocol):
    version: str
    def reconcile(self, facts: Sequence[CanonicalEvidence]) -> ReconciliationResult: ...
```

**Reuse, do not reinvent:**
- Hashing/ids: `canonical.make_id`, `canonical_hash`, `sha256_hex`.
- Numeric reconciliation core: `agent.calculations.recompute` and the existing
  tolerances (`agent.verifier.DEFAULT_TOLERANCE`,
  `lakehouse/transform/calculations.STAT_TOLERANCE`/`DECIMAL_TOLERANCE`).
- Raw preservation: `run_store.RunStore._preserve_raw_files` (hash re-verify).
- Two-engine corroboration pattern: `WarehouseCrossValidator._finish`
  (confirmed/discrepancy) generalized into `reconcile/numeric.py`.

---

## 6. State machine / sequence

**Per fact lifecycle:**
```
raw bytes --normalize--> CanonicalEvidence(+Provenance) --group by FactKey-->
  [1 source]  -> ReconciliationResult(INSUFFICIENT or single-source confirmed-by-policy)
  [>=2 agree] -> CONFIRMED
  [>=2 disagree, resolvable-by-freshness/policy?] -> DISCREPANCY (both preserved)
  [disagree, unresolvable] -> ABSTAINED (both preserved, reason recorded)
  [a source missing the fact] -> MISSING_RECORD
```
Transitions are **monotonic toward caution**: an ABSTAINED/DISCREPANCY result is
never upgraded to CONFIRMED without *new admissible evidence* (mirrors STRIX-013
failure_behavior: "never upgrade an abstention to acceptance").

**Reconciliation sequence (one FactKey):**
1. Collect all `CanonicalEvidence` sharing `fact_key_id`.
2. Verify every input's provenance resolves to preserved raw bytes (else
   `INSUFFICIENT`/`ABSTAINED` with `INCOMPLETE_LINEAGE`-style reason).
3. Select the `Reconciler` by fact kind (numeric vs record/text).
4. Numeric: recompute/compare under tolerance (two-engine where available);
   emit CONFIRMED or DISCREPANCY.
5. Attach `requirement_refs` (union of inputs') and `reconciler_version`.
6. Persist the result alongside inputs via `run_store.persist_generic`.

---

## 7. Dependencies & assumptions

- **Depends on** existing: `canonical.py`, `models.py:StrixModel`/`DecimalValue`,
  `run_store.py`, `agent/calculations.py`, and the four reconcilers.
- **Assumes** raw bytes for every source are already preserved/preservable
  (STRIX-001 holds today). M1 does not change collection policy.
- **Assumes** a stable `FactKey` can be derived per source (the hardest
  modeling problem — see Open Questions). Where it cannot, the correct behavior
  is explicit abstention, not a guessed join.
- **No dependency** on AFIIS, BLKPVNTHR.OS, M2, or M3. M1 is independently
  deployable and independently testable.

---

## 8. Security boundaries & threat model

- **Integrity ≠ veracity (preserved doctrine).** `content_hash` proves bytes are
  unaltered, never that the source is correct — carried verbatim from
  `canonical.py` and `AgentEvidence` docstrings.
- **Normalization is untrusted-input parsing.** Each normalizer treats raw bytes
  as hostile: no `eval`, bounded sizes, schema-validated output, float rejected
  at the type boundary. Malformed input → explicit rejection, never a silent
  default.
- **No silent source preference.** The reconciler may not pick a "winner" by
  source reputation; disagreement is surfaced (STRIX-003). Any
  resolution-by-policy (e.g. prefer fresher) must be an explicit, recorded,
  auditable rule — not hidden in code paths.
- **Traceability tamper-evidence.** Reconciliation results are content-addressed
  and persisted via the atomic, hash-verified `run_store`; replay recomputes
  them. (Cryptographic signing/chaining is STRIX-014, deferred to M2/M3.)
- **Handling markings** propagate from engineering/agent evidence as
  source metadata only (no enforcement added here) — consistent with
  `engineering/models.py` doctrine.

---

## 9. Acceptance tests (named)

Deterministic, no LLM in the verification/reconciliation path (reuses the
existing LLM-free discipline).

- `test_canonical_evidence_immutable` — `CanonicalEvidence` is frozen; float
  rejected; id changes iff content changes; status/requirement_refs excluded
  from identity where specified (mirrors STRIX-001 tests).
- `test_normalize_roundtrip_preserves_provenance` — each normalizer yields
  provenance that resolves back to byte-exact raw (hash re-verified).
- `test_factkey_join_across_sources` — two sources reporting the same fact map
  to one `fact_key_id`; two different facts never collide.
- `test_reconcile_agreement_confirmed` — agreeing representations → CONFIRMED
  (positive control; must not regress existing `test_transform_dbt.py`).
- `test_reconcile_numeric_discrepancy` — forced mismatch beyond tolerance →
  DISCREPANCY with both values + lineage (generalizes
  `test_transform_reconciliation_discrepancy.py`).
- `test_reconcile_missing_record` — a source lacking the fact → MISSING_RECORD.
- `test_reconcile_unresolvable_abstains` — irreconcilable conflict → ABSTAINED;
  and `test_abstention_never_upgraded` — ABSTAINED stays abstained without new
  evidence.
- `test_traceability_coverage` — every reconciled output carries ≥1 requirement
  ref; coverage metric computed deterministically.
- `test_reconciler_adapters_equivalence` — the four refactored reconcilers,
  invoked through the `Reconciler` interface, reproduce their pre-refactor
  verdicts on existing fixtures (behavior-preservation).
- `test_reconcile_persists_and_replays` — results persist via
  `run_store.persist_generic` and pass a three-way replay hash check.

---

## 10. Open questions

1. **FactKey derivation.** How robustly can a stable cross-source `FactKey` be
   derived (e.g. CIK+concept+period alignment, symbol+session) without a guessed
   join? Where ambiguous, is explicit abstention the right default (proposed:
   yes)?
2. **Tolerance unification.** The four reconcilers use different tolerances
   (`DEFAULT_TOLERANCE` 1e-4 vs `STAT_TOLERANCE`/`DECIMAL_TOLERANCE`). Should the
   canonical layer keep per-concept tolerances in a contract table, or impose
   one? (Proposed: per-concept contract, recorded in the result.)
3. **Vocabulary migration.** Can the three duplicated `VerificationStatus`/
   `FailureCode` enums (`strix.models`, `agent.models`, `engineering.models`) be
   unified without breaking persisted historical runs? Likely needs a
   compatibility mapping, not a hard cutover.
4. **Single-source facts.** When only one source reports a fact, is "confirmed"
   ever appropriate, or only "insufficient/attributed"? (Lean: never auto-confirm
   from a single source.)
5. **Non-numeric reconciliation.** Textual/attributed facts currently use
   verbatim-substring attribution (`agent/verifier._verify_textual`); how far
   should cross-source textual reconciliation go before abstaining?
