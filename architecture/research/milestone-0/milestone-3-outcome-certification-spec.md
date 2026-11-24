# Milestone 3 — Closed-Loop Outcome Certification Specification (§8)

**Audit commit of record:** `3dc70eac6b6b178d51156185113beb70d7c899e4`
**Work branch:** `feat/milestone-0b`
**Gap:** GAP-002 — Closed-Loop Execution and Outcome Certification
**Companions:** [`requirements-baseline.yaml`](./requirements-baseline.yaml),
[`engineering-audit.md`](./engineering-audit.md),
[`comparative-experiment-design.md`](./comparative-experiment-design.md),
[`milestone-2-execution-assurance-spec.md`](./milestone-2-execution-assurance-spec.md).

> **Claim discipline.** Build plan + reuse map. ESTABLISHED FACTS vs DESIGN
> PROPOSAL separated. No novelty/performance/patent/readiness claims; the
> falsifiable claim is H2. **Domain-independent by construction: financial
> payments are ONE adapter, never a dependency.** STRIX takes no AFIIS or
> BLKPVNTHR.OS dependency and stays independently deployable. No live
> payments/trades/external execution; outcomes are observed from
> simulated/sandboxed sources.

---

## 1. Goal

Establish a reliable, independently-verifiable link between **authorized
decisions → executed actions → observed outcomes**, and **certify outcomes
correctly** even under retries, duplicates, partial failures, and incomplete
outcome evidence. The loop closes when an outcome observed from an **independent**
channel is reconciled against the expected outcome of the decision that
authorized it — or explicitly **abstains** when the outcome evidence is
insufficient.

The audit shows this capability is **entirely missing** (STRIX-009/010/011) and
the audit trail is **partial** (STRIX-014: no ordered per-run event log, no hash
chaining, no signatures). Today only statistical `correlation()`, an HTTP
`X-Correlation-ID` echo, and backward data-lineage exist — none of which link a
decision to its realized outcome.

---

## 2. In-scope / Out-of-scope

**In-scope**
- **Domain-independent** decision & execution **event ledger** (append-only,
  ordered).
- **Correlation identifiers** carried from decision → action → outcome.
- **Outcome evidence contracts** (typed, immutable, provenance-preserving).
- **Independent outcome observation** (observed from a channel distinct from the
  actor).
- **Retry & duplicate handling** (idempotent; never double-count).
- **Partial / failed execution** representation.
- **Outcome reconciliation** (observed vs expected) reusing M1 reconciliation.
- **Signed or externally anchored audit checkpoints** (hash-chained ordered log;
  completes STRIX-014).
- At least one non-payment adapter **and** a sandboxed payment adapter, to
  demonstrate domain-independence (H2 §3 ≥2 domains).

**Out-of-scope**
- Authorization/certificates/freshness gating (→ M2, consumed here via the
  certificate id on the decision event).
- Canonical evidence schema/reconciliation internals (→ M1, reused).
- Real money movement or trade execution. Payment adapter is sandboxed.
- Any brokerage capability (`market/engine.py` remains research-only).

---

## 3. Requirements covered (STRIX IDs)

| Requirement | How M3 addresses it | Baseline status |
|---|---|---|
| **STRIX-009** Decision-to-execution event correlation | Correlation id assigned at decision, carried through execution/outcome; join by id; orphan detection. | missing |
| **STRIX-010** Independent outcome verification | Outcome observed from an independent channel; reconciled vs expected (reuses M1). | missing |
| **STRIX-011** Retry & partial-failure handling | Idempotency keyed on correlation id; duplicate suppression; explicit partial/failed outcome states. | missing |
| **STRIX-014** Independently verifiable audit evidence | Append-only, ordered, hash-chained event log; signed/externally-anchored checkpoints. | partial |

---

## 4. Proposed modules / files (new `src` paths)

```
src/strix/closedloop/
  __init__.py
  ledger.py            # EventLedger: append-only, ordered, hash-chained (previous_hash)
  events.py            # DecisionEvent, ExecutionEvent, OutcomeEvent (typed, frozen)
  correlation.py       # CorrelationId allocation + join/orphan detection
  outcome.py           # OutcomeEvidence contract; ExpectedOutcome; OutcomeStatus
  observe/
    __init__.py
    base.py            # OutcomeObserver protocol (independent of the actor)
    simulated.py       # non-payment sandbox observer (e.g. compute-job result)
    payment_sandbox.py # ONE domain adapter — sandboxed payment outcome observer
  reconcile_outcome.py # observed vs expected via M1 Reconciler
  checkpoint.py        # AuditCheckpoint: signed / externally-anchored chain heads
  idempotency.py       # DedupLedger keyed on correlation id (atomic, exactly-once)
```

**Reuse, do not reinvent:**
- Hashing/ids/chaining: `canonical.canonical_hash`, `canonical_bytes`,
  `sha256_hex`, `make_id`.
- Append-only, content-addressed provenance pattern:
  `lakehouse/bronze.py` (append-only, per-ingestion) generalized into an ordered
  per-run `EventLedger` with `previous_hash`.
- Atomic mutable state (dedup/correlation watermarks): the
  `ingest/checkpoints.CheckpointStore` temp+fsync+replace pattern.
- Outcome reconciliation: **M1** `Reconciler`/`ReconciliationResult`
  (observed-outcome vs expected-outcome is just another two-source
  reconciliation — CONFIRMED / DISCREPANCY / ABSTAINED).
- Certificate linkage: **M2** `AuthorizationCertificate.certificate_id` and
  `nonce` are recorded on the `DecisionEvent` / `ExecutionEvent`.
- Signing/trust root: **M2** `keys.py` (shared) for `AuditCheckpoint` signatures.
- Persistence/replay: `run_store.RunStore`; three-way replay engines
  (`replay.py`) extended to verify the ledger chain.

---

## 5. Data contracts (sketch)

All frozen `StrixModel`, Decimal-only, ids via `canonical`. **No field is
payment-specific**; domain specifics live only inside adapter payloads.

```python
# correlation.py
class CorrelationId(StrixModel):
    value: str                 # make_id("COR", {decision identity}); assigned at decision time

# events.py  (domain-independent envelope)
class EventBase(StrixModel):
    event_id: str
    correlation_id: str
    sequence: int              # monotonic within the ledger
    previous_hash: str         # sha256 of prior event's canonical bytes (chain)
    recorded_at: AwareDatetime # wall-clock; EXCLUDED from replay comparison

class DecisionEvent(EventBase):
    kind: Literal["decision"] = "decision"
    certificate_id: str        # from M2 authorization
    policy_id: str
    policy_version: str
    expected_outcome: "ExpectedOutcome"

class ExecutionEvent(EventBase):
    kind: Literal["execution"] = "execution"
    certificate_nonce: str     # ties to the consumed M2 nonce (idempotency anchor)
    adapter: str
    attempt: int               # retries share correlation_id; attempt increments
    status: Literal["submitted", "partial", "failed", "completed"]

class OutcomeEvent(EventBase):
    kind: Literal["outcome"] = "outcome"
    observer: str              # which INDEPENDENT channel observed it
    evidence: "OutcomeEvidence"
    status: "OutcomeStatus"

# outcome.py
class OutcomeStatus(StrEnum):
    CERTIFIED_COMPLETE   = "certified_complete"    # observed == expected, reconciled
    CERTIFIED_FAILED     = "certified_failed"      # observed failure, reconciled
    PARTIAL              = "partial"               # incomplete; never "complete"
    DISCREPANT           = "discrepant"           # observed != expected
    UNVERIFIED           = "unverified"           # outcome evidence incomplete -> abstain
    DUPLICATE_SUPPRESSED = "duplicate_suppressed"

class ExpectedOutcome(StrixModel):
    concept: str               # domain-neutral (e.g. "job_result", "transfer_state")
    expected_value: DecimalValue | None = None
    expected_label: str | None = None

class OutcomeEvidence(StrixModel):
    evidence_id: str
    source_ref: "SourceRef"    # M1 provenance (independent channel)
    observed_value: DecimalValue | None = None
    observed_label: str | None = None
    content_hash: str          # preserved bytes

# checkpoint.py
class AuditCheckpoint(StrixModel):
    checkpoint_id: str
    ledger_head_sequence: int
    ledger_head_hash: str      # root of the chain so far
    key_id: str                # M2 trust root
    signature: str             # ed25519 over canonical_bytes(checkpoint sans signature)
    external_anchor: str | None = None   # optional out-of-band anchor reference
```

---

## 6. State machine / sequence

**Outcome lifecycle (per correlation id):**
```
DECISION recorded (expected_outcome set, certificate_id bound)
  -> EXECUTION submitted
       -> completed  -> observe -> reconcile(observed, expected)
                                    == -> CERTIFIED_COMPLETE
                                    != -> DISCREPANT
       -> partial    -> PARTIAL (never certified complete)
       -> failed     -> observe -> CERTIFIED_FAILED (if failure confirmed) | UNVERIFIED
  retry (same correlation_id, attempt+1):
       dedup on correlation_id+idempotency key -> DUPLICATE_SUPPRESSED (no new outcome)
  no OUTCOME within bound -> orphan(decision) flagged
  OUTCOME with no DECISION -> orphan(outcome) flagged
```

**Invariants:**
- An outcome is **never** certified complete without an independent observation
  reconciled to the expected outcome (STRIX-010).
- A retried/duplicated execution **never** yields a second certified outcome
  (STRIX-011); the first terminal outcome per correlation id wins; later matching
  observations are `DUPLICATE_SUPPRESSED`.
- Incomplete outcome evidence yields `UNVERIFIED` (abstain), never a guessed
  completion (STRIX-013 discipline carried into outcomes).
- The ledger is **append-only and ordered**; each event's `previous_hash` chains
  to its predecessor (STRIX-014).

**Certification sequence:**
1. Allocate `CorrelationId` at decision; append `DecisionEvent` (chained).
2. On execution, append `ExecutionEvent` with `attempt` and status; dedup via
   `idempotency.DedupLedger` keyed on `correlation_id` (+ M2 nonce) atomically.
3. Observe outcome via an **independent** `OutcomeObserver`; preserve bytes
   (M1 provenance).
4. Reconcile observed vs `expected_outcome` via the M1 `Reconciler`.
5. Map reconciliation outcome → `OutcomeStatus`; append `OutcomeEvent` (chained).
6. Periodically emit a signed/anchored `AuditCheckpoint` over the ledger head.

---

## 7. Domain-independence (design constraint, not a feature)

- The event envelope, ledger, correlation, reconciliation, and certification
  logic reference **no** payment/trading concept. Domain specifics appear only
  inside `observe/*` adapters and the opaque `ExpectedOutcome`/`OutcomeEvidence`
  value/label fields.
- The experiment (H2) **requires ≥2 adapters** — a non-payment sandbox observer
  and a sandboxed payment observer — and asserts identical ledger/certification
  behavior across both. A test (`test_domain_independence_two_adapters`) fails if
  any core module imports an adapter-specific symbol.
- Payments via AFIIS are an **optional external testbed/client**; this milestone
  depends on neither AFIIS nor BLKPVNTHR.OS and ships standalone.

---

## 8. Security boundaries & threat model

- **Independent observation (STRIX-010).** The outcome observer must be distinct
  from the actor that executed; the ledger records `observer` identity. A test
  forbids the executing adapter from also supplying its own outcome.
- **Append-only + hash chain (STRIX-014).** `previous_hash` makes reordering,
  omission, or mutation detectable; `AuditCheckpoint` signs the chain head
  (ed25519, M2 trust root) and optionally anchors it externally, so a third party
  verifies *what happened* without re-running the pipeline — the gap the audit
  flags (today tamper-evidence requires recompute via replay).
- **Idempotency / replay (STRIX-011).** Dedup ledger keyed on correlation id +
  M2 nonce; atomic temp+fsync+replace; a retried action cannot create a second
  certified outcome.
- **Integrity ≠ veracity.** Outcome `content_hash` proves the observed bytes are
  unaltered, not that the outcome is favorable — carried from existing doctrine.
- **Abstain over guess.** Missing/incomplete outcome evidence → `UNVERIFIED`;
  never upgraded without new admissible observation.
- **Orphan detection.** Decisions without outcomes and outcomes without decisions
  are flagged, not silently dropped.
- **Residual risks (acknowledged):** a compromised observer could report false
  outcomes (mitigation: multiple independent observers + reconciliation/abstain);
  external anchoring trust model is an open question (§11).

---

## 9. Acceptance tests (named)

- `test_correlation_join` — decision, execution, and outcome events join by
  correlation id (STRIX-009).
- `test_orphan_detection` — decision-without-outcome and outcome-without-decision
  both flagged.
- `test_independent_outcome_certified` — observed == expected via independent
  observer → CERTIFIED_COMPLETE (STRIX-010).
- `test_outcome_discrepancy` — observed != expected → DISCREPANT (both preserved).
- `test_retry_single_outcome` — a retried action yields exactly one certified
  outcome; duplicates → DUPLICATE_SUPPRESSED (STRIX-011).
- `test_partial_execution_not_certified_complete` — partial → PARTIAL, never
  complete.
- `test_incomplete_outcome_abstains` — missing outcome evidence → UNVERIFIED.
- `test_ledger_append_only_ordered` — out-of-order / mutated / omitted event
  breaks the `previous_hash` chain and is detected (STRIX-014).
- `test_checkpoint_signature_verifies` — `AuditCheckpoint` signature validates
  against the trust root; a tampered head fails verification **without recompute**.
- `test_domain_independence_two_adapters` — identical certification behavior for
  the non-payment and sandboxed-payment adapters; core modules import no
  adapter-specific symbol.
- `test_ledger_persists_and_replays` — ledger persists atomically and passes a
  three-way replay that also verifies chain linkage.

---

## 10. Dependencies & assumptions

- **Depends on** M2 (`AuthorizationCertificate`/`nonce` on decision/execution
  events; shared `keys.py` trust root) and M1 (`Reconciler` for observed-vs-
  expected). Also existing `canonical.py`, `run_store.py`, `bronze.py`
  (append-only pattern), `CheckpointStore` (atomic mutable state), `replay.py`.
- **Assumes** an independent outcome channel exists per adapter (the crux of
  STRIX-010); where it does not, the correct result is `UNVERIFIED`.
- **Assumes** sandboxed adapters only; no real execution or settlement.
- **No AFIIS / BLKPVNTHR.OS dependency.** Independently deployable.

---

## 11. Open questions

1. **External anchoring.** What anchor is acceptable for the research phase
   (internal signed checkpoint only) vs later (third-party timestamp/anchor)? The
   trust model for `external_anchor` is undefined.
2. **Observer trust.** How many independent observers are needed before an
   outcome is certified vs abstained? Single-observer certification may be too
   weak for some domains.
3. **Partial-outcome semantics.** How is "partial" defined per domain without
   leaking domain specifics into the core? (Likely an adapter-provided predicate
   over opaque labels.)
4. **Ledger scope.** One ledger per run vs a long-lived cross-run ledger? Chain
   verification and checkpoint cadence differ significantly between the two.
5. **Idempotency key.** Is correlation id + M2 nonce sufficient, or is an
   adapter-level idempotency key also required to catch duplicates the adapter
   itself generates?
6. **Late outcomes.** How long is the orphan window before a decision is declared
   outcome-less, and can a late outcome re-open a closed correlation id?
