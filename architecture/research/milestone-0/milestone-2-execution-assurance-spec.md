# Milestone 2 — Dynamic Execution Assurance Specification (§8)

**Audit commit of record:** `3dc70eac6b6b178d51156185113beb70d7c899e4`
**Work branch:** `feat/milestone-0b`
**Gap:** GAP-001 — Dynamic Evidence-Bound Execution Assurance
**Companions:** [`requirements-baseline.yaml`](./requirements-baseline.yaml),
[`engineering-audit.md`](./engineering-audit.md),
[`comparative-experiment-design.md`](./comparative-experiment-design.md),
[`milestone-1-evidence-interoperability-spec.md`](./milestone-1-evidence-interoperability-spec.md).

> **Claim discipline.** Build plan + reuse map. ESTABLISHED FACTS vs DESIGN
> PROPOSAL kept separate. No novelty/performance/patent/readiness claims. The
> falsifiable claim is H1 in the experiment design. **Per the authoritative
> GAP-001 definition, signed manifests alone do NOT establish execution
> assurance** — and the audit confirms STRIX does not even sign manifests yet.
> No live payments/trades/external execution: the gateway drives
> simulated/sandboxed adapters only.

---

## 1. Goal

Prevent a previously-authorized action from executing when its supporting
evidence has become **stale, contradictory, or invalid**, when its **parameters**
differ from what was authorized, when the **governing policy** has been
superseded, or when the authorization is **replayed**. Do this with an
**independent** verification engine that **fails closed**, **re-validates at the
moment of execution** (closing time-of-check/time-of-use gaps), and consumes each
authorization **atomically and exactly once**.

The audit shows the current foundation (STRIX-005/006/007 **missing**;
STRIX-002/004/008 **partial**): there is no action/authorization abstraction, no
execution gateway, no cryptographic certificate, no execution-time freshness
gate, and the verifier boundary is independent-by-construction but unsigned. M2
builds exactly these.

---

## 2. In-scope / Out-of-scope

**In-scope**
- Persistent, versioned **requirements registry** (cross-run, addressable).
- Versioned, content-addressed **authorization policies**.
- Configurable **freshness rules** (per source/evidence class), enforced at
  execution time.
- **Evidence-bound action proposals** (action + exact parameters + required
  evidence set).
- **Scoped authorization certificates** bound to policy version, parameter hash,
  and evidence set; single-use nonce.
- **Key management & trust roots** for signing certificates (the missing crypto).
- **Execution-time revalidation** of evidence freshness/validity/contradiction.
- **Atomic authorization consumption** (exactly-once) + **replay protection**.
- **Fail-closed execution gateway** fronting all effectful adapters.
- **TOCTOU mitigation** with a concrete mechanism + test matrix.

**Out-of-scope**
- Canonical evidence schema / cross-source reconciliation (→ M1, consumed here).
- Decision→action→outcome ledger, outcome observation (→ M3).
- Any real external execution; adapters are simulated/sandboxed.
- Alpha/trading logic. The gateway is domain-independent; payments would be one
  future adapter (and are not a dependency).

---

## 3. Requirements covered (STRIX IDs)

| Requirement | How M2 addresses it | Baseline status |
|---|---|---|
| **STRIX-002** Versioned requirements & authorization policies | Persistent registry + content-addressed versioned policies; policy version recorded on every authorization. | partial |
| **STRIX-004** Evidence freshness enforcement | Per-source/class configurable freshness rules; execution-time gate (not just VERIFIED→STALE downgrade). | partial |
| **STRIX-005** Exact action-parameter binding | Certificate bound to `canonical_hash(parameters)`; mismatch → fail closed. | missing |
| **STRIX-006** Execution-time authorization revalidation | Gateway re-runs evidence/policy validation immediately before execution. | missing |
| **STRIX-007** Replay-resistant authorization | Single-use nonce; atomic consume-or-reject. | missing |
| **STRIX-008** Independent certification boundaries | Verifier/gateway import no LLM; add a signed trust root over the existing independent boundary. | partial |
| (supports STRIX-014) | Authorization/consumption events feed the ordered, signable audit log. | partial |

---

## 4. Proposed modules / files (new `src` paths)

```
src/strix/assurance/
  __init__.py
  registry.py          # RequirementsRegistry: persistent, versioned, addressable
  policy.py            # AuthorizationPolicy (versioned, content-addressed), PolicyStore
  freshness.py         # FreshnessRule, FreshnessPolicy (per source/class); reuses classify_freshness
  action.py            # ActionProposal, ActionParameters (typed, canonical-hashed)
  certificate.py       # AuthorizationCertificate, Nonce, signing/verification
  keys.py              # KeyStore, TrustRoot (ed25519), rotation, key ids
  consume.py           # NonceLedger: atomic single-use consumption (replay protection)
  gateway.py           # ExecutionGateway: fail-closed, execution-time revalidation
  revalidate.py        # pre-execution evidence/policy re-check (TOCTOU close point)
  adapters/
    __init__.py
    base.py            # EffectfulAdapter protocol (simulated/sandboxed only)
    simulated.py       # in-memory adapter for tests/experiments
```

**Reuse, do not reinvent:**
- Hashing/ids/parameter binding: `canonical.canonical_hash` (parameter hash),
  `make_id`, `sha256_hex`.
- Freshness classification core: `agent/evidence_collector.classify_freshness`
  (generalized to configurable `max_age_days` per class — the function already
  accepts `max_age_days`).
- Atomic, crash-safe persistence for registry/policy/nonce state:
  `run_store.RunStore` commit protocol and `ingest/checkpoints.CheckpointStore`
  (mutable, atomic temp+fsync+replace) as the pattern for the mutable nonce
  ledger and watermarks.
- Independent-verifier discipline: `agent/verifier.py` /
  `verification/claims.py` (no LLM imports) — the gateway inherits this rule.
- Evidence validity/contradiction signal: M1 reconciliation
  (`ReconciliationResult.outcome`) is the execution-time "is this evidence still
  valid?" input.

---

## 5. Data contracts (sketch)

All frozen `StrixModel`, Decimal-only, ids via `canonical`.

```python
# registry.py
class RegisteredRequirement(StrixModel):
    requirement_id: str          # e.g. STRIX-005 or project req
    version: str                 # semver; (id, version) is addressable
    text: str
    policy_ids: tuple[str, ...]  # authorization policies that reference it
    content_hash: str

# policy.py
class AuthorizationPolicy(StrixModel):
    policy_id: str               # make_id("POL", payload)
    version: str
    requirement_refs: tuple[str, ...]
    required_evidence: tuple[str, ...]      # fact_key_ids / concepts that must be CONFIRMED
    freshness_policy_id: str
    predicate: str               # declarative, auditable condition (no eval)
    content_hash: str

# freshness.py
class FreshnessRule(StrixModel):
    source_kind: str
    max_age_days: int            # per-class; replaces single hard-coded 45
class FreshnessPolicy(StrixModel):
    freshness_policy_id: str
    rules: tuple[FreshnessRule, ...]
    default_max_age_days: int

# action.py
class ActionParameters(StrixModel):
    # fully typed per adapter; canonical_hash(params) is the binding key
    adapter: str
    operation: str
    args: dict[str, str | int | Decimal]   # JSON-safe, float-forbidden
class ActionProposal(StrixModel):
    proposal_id: str
    parameters: ActionParameters
    parameter_hash: str          # canonical_hash(parameters)
    policy_id: str
    policy_version: str
    evidence_refs: tuple[str, ...]          # reconciled evidence ids this rests on
    proposed_at: AwareDatetime

# certificate.py
class AuthorizationCertificate(StrixModel):
    certificate_id: str
    proposal_id: str
    parameter_hash: str          # binds EXACT parameters (STRIX-005)
    policy_id: str
    policy_version: str          # binds EXACT policy in force (STRIX-002)
    evidence_snapshot_hash: str  # hash of the evidence set + its validity at auth time
    nonce: str                   # single-use (STRIX-007)
    not_after: AwareDatetime     # hard expiry
    key_id: str                  # which trust-root key signed
    signature: str               # ed25519 over canonical_bytes(cert sans signature)

# consume.py
class ConsumptionRecord(StrixModel):
    nonce: str
    certificate_id: str
    consumed_at: AwareDatetime
    result: Literal["executed", "rejected_stale", "rejected_param_mismatch",
                    "rejected_policy_superseded", "rejected_replay", "abstained"]
```

---

## 6. State machine / sequence

**Certificate lifecycle:**
```
PROPOSED --(verify evidence CONFIRMED + policy current + sign)--> AUTHORIZED
AUTHORIZED --(present at gateway)--> REVALIDATING
REVALIDATING --ok--> CONSUMED(executed)        # nonce atomically burned, then execute
REVALIDATING --stale/contradicted/invalid--> REJECTED(fail-closed, abstain+record)
REVALIDATING --param mismatch--> REJECTED
REVALIDATING --policy superseded / expired--> REJECTED
CONSUMED --(re-presented)--> REJECTED(replay)  # nonce already burned
```

**Execution sequence (fail-closed throughout):**
1. Gateway receives `(certificate, actual ActionParameters)`.
2. **Verify signature** against the trust root (`keys.py`); unknown/!valid →
   REJECT.
3. **Parameter binding:** `canonical_hash(actual_params) == cert.parameter_hash`?
   No → REJECT (STRIX-005).
4. **Policy currency:** resolve `cert.policy_id@policy_version`; if the registry's
   *current* policy for the requirement differs → REJECT (STRIX-002).
5. **Expiry:** `now <= cert.not_after`? No → REJECT.
6. **Atomic nonce consume (STRIX-007):** attempt to burn `cert.nonce` in the
   `NonceLedger` *before* execution; if already consumed → REJECT(replay).
   This is the single serialization point.
7. **Execution-time revalidation (STRIX-006, TOCTOU close):** *after* burning the
   nonce and *immediately before* the effectful call, re-read the evidence,
   recompute freshness under the certificate's `FreshnessPolicy`, and re-check
   M1 reconciliation validity. Any stale/contradicted/invalid → REJECT, record
   abstention, and mark the (already-burned) nonce `rejected_stale` so it can
   never be retried.
8. Only if all pass: invoke the simulated adapter exactly once; record
   `executed`.

> **Default is refusal.** Any error, timeout, unresolved evidence, or unknown
> condition yields REJECT, never execute.

---

## 7. TOCTOU: the core vulnerability and its mitigation

**The hazard.** A naive design checks freshness/validity, *then* executes. Between
the check (time-of-check) and the effectful call (time-of-use) the evidence can
go stale, be contradicted, be withdrawn, or the policy can change — and the
action executes on now-invalid grounds. This is the central GAP-001 failure mode
and the reason "authorize once, execute later" is unsafe.

**Concrete mitigation (defense in depth):**
1. **Consume-then-revalidate-then-execute ordering** (sequence steps 6→7→8). The
   single-use nonce is burned atomically *first* (one serialization point), so no
   two executions can race the same certificate; revalidation then runs in the
   narrowest possible window immediately before the call.
2. **Evidence snapshot binding.** The certificate carries
   `evidence_snapshot_hash` (the evidence set + validity *at authorization*).
   Revalidation recomputes the current snapshot hash; **any** change forces a
   fresh validity decision rather than trusting the authorization-time result.
3. **Monotonic validity via a generation/version counter.** Evidence and policy
   carry a monotonically increasing generation. Revalidation requires the
   *current* generation to still satisfy the policy; a bumped generation
   (new/withdrawn/contradicted evidence, superseded policy) invalidates the
   certificate deterministically — no reliance on wall-clock races alone.
4. **Short, bounded `not_after`.** Certificates expire quickly; Δ between auth and
   use is bounded, shrinking the TOCTOU window and making stale-evidence
   execution structurally unlikely even before revalidation.
5. **Atomic ledger operations.** Nonce consumption and generation reads use the
   atomic temp+fsync+replace discipline (`run_store`/`CheckpointStore`), so a
   crash cannot leave a half-consumed nonce or a torn read.

### TOCTOU test matrix (acceptance-mandatory)

Each row is a test: evidence/policy transitions **between** the check point and
the use point; expected result is always "no unsafe execution."

| # | State at check | Mutation injected between check & use | Expected gateway result |
|---|---|---|---|
| T1 | fresh, valid | none | EXECUTE once |
| T2 | fresh, valid | evidence becomes **stale** (age > rule) | REJECT (rejected_stale) |
| T3 | fresh, valid | evidence **contradicted** (M1 → DISCREPANCY) | REJECT |
| T4 | fresh, valid | evidence **withdrawn/invalidated** | REJECT |
| T5 | fresh, valid | **policy superseded** (new version) | REJECT (policy_superseded) |
| T6 | fresh, valid | **parameters altered** at use | REJECT (param_mismatch) |
| T7 | fresh, valid | **certificate re-presented** (replay) | REJECT (replay) |
| T8 | fresh, valid | **concurrent** second presentation (race) | exactly one EXECUTE, other REJECT |
| T9 | fresh, valid | **generation bumped** then reverted | REJECT (generation changed) |
| T10 | fresh, valid | crash **after nonce burn, before execute** | on recovery: nonce consumed, action NOT executed, recorded rejected/aborted |
| T11 | stale at check | (already stale) | REJECT at check |
| T12 | valid, expired `not_after` | time advances past expiry | REJECT (expired) |

---

## 8. Security boundaries & threat model

- **Independent, LLM-free gateway (STRIX-008).** `assurance/*` imports no LLM; the
  LLM remains only a *proposer* (it may emit `ActionProposal`s, never
  certificates or executions). CI test asserts no LLM import in the package.
- **Trust root & key management.** Certificates are signed (ed25519) by keys in a
  `KeyStore` with a defined `TrustRoot`; `key_id` recorded; rotation supported;
  verification requires a key chaining to the trust root. This is the
  cryptographic layer the audit found **absent** ("certificate" today is an
  unsigned SHA-256 manifest).
- **Confused-deputy / privilege.** The gateway is the *only* path to effectful
  adapters; adapters refuse calls not arriving with a verified, consumed
  certificate.
- **Replay & double-spend.** Single-use nonce + atomic consume is the sole
  serialization point; concurrency test T8 guards it.
- **Tamper evidence.** Authorization + consumption events are content-addressed
  and persisted atomically, feeding the ordered audit log (STRIX-014; full
  hash-chaining/signing of the *log* is shared with M3).
- **Fail-closed invariant.** Every unhandled condition maps to REJECT. No code
  path executes an adapter without passing all of §6.
- **Key compromise (acknowledged residual).** A stolen signing key lets an
  attacker mint certificates; mitigations are rotation, short expiry, and
  execution-time revalidation (a forged cert still can't execute on stale/invalid
  evidence). Hardware key custody is an open question (§11).

---

## 9. Acceptance tests (named)

- `test_registry_addressable_versioned` — `(id, version)` resolves; duplicate id
  within a source rejected (mirrors ReqIF duplicate rejection, STRIX-002).
- `test_policy_content_addressed` — policy id changes iff content changes;
  in-force version recorded on authorization.
- `test_freshness_rule_per_class` — different `max_age_days` per source kind;
  default applies otherwise; future-dated/absent → UNKNOWN (reuse
  `classify_freshness` semantics).
- `test_parameter_binding_mismatch_rejected` — altered parameters → REJECT
  (STRIX-005).
- `test_certificate_signature_required` — unsigned/forged/wrong-key cert →
  REJECT; valid chain → accept (STRIX-008 crypto layer).
- `test_nonce_single_use` and `test_nonce_concurrent_race` — exactly-once
  consumption; concurrency yields one execute (STRIX-007; matrix T7/T8).
- `test_execution_time_revalidation_blocks_stale` — authorized-then-stale is
  blocked at execution (STRIX-006; matrix T2).
- `test_toctou_matrix[T1..T12]` — the full §7 matrix; every non-T1/T8-execute
  row must NOT execute.
- `test_fail_closed_on_error` — injected error/timeout/unresolved evidence →
  REJECT, recorded abstention.
- `test_crash_after_consume_no_execute` — crash between burn and execute leaves
  nonce consumed and no effect (matrix T10).
- `test_gateway_no_llm_import` — package imports no LLM library.
- `test_authorization_persists_and_replays` — authorization/consumption records
  persist atomically and survive a three-way replay hash check.

---

## 10. Dependencies & assumptions

- **Depends on** M1 (`ReconciliationResult` as the execution-time validity
  signal) and existing `canonical.py`, `run_store.py`,
  `evidence_collector.classify_freshness`, `CheckpointStore` pattern.
- **Assumes** a monotonic generation counter can be maintained for
  evidence/policy (mutable state, atomically written like checkpoints).
- **Assumes** adapters are simulated/sandboxed; real execution is out of scope
  and gated behind future, separately-reviewed adapters.
- **No AFIIS/BLKPVNTHR.OS dependency.** Independently deployable.

---

## 11. Open questions

1. **Key custody.** Software `KeyStore` for the research phase vs HSM/KMS later —
   what trust-root model is adequate for the experiment, and what is deferred?
2. **Generation counter scope.** Per-fact, per-source, or global? Finer scope =
   fewer false invalidations but more bookkeeping.
3. **Nonce ledger durability vs performance.** fsync-per-consume is safe but
   slow; is a batched/WAL approach acceptable while preserving exactly-once under
   crash (T10)?
4. **Policy predicate language.** How expressive can `predicate` be while staying
   declarative, auditable, and `eval`-free?
5. **Freshness for sources without timestamps.** Corpus/lakehouse lack an age
   concept today (audit §2.5). Do they get synthetic observation timestamps, or
   are actions resting on them forced to abstain?
6. **Revalidation cost.** Re-reading/reconciling evidence at every execution may
   be expensive; what caching is safe without reintroducing a TOCTOU gap?
