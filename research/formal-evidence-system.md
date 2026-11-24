# Formal Typed Evidence System (R1 §9)

**Milestone:** R1 — Resource-Bounded Typed Evidence Verification
**Status key:** IMPLEMENTED / TESTED / NOT_IMPLEMENTED / NOT_EVALUATED / BLOCKED
**Source:** `src/strix/evidence_graph/` (`nodes.py`, `graph.py`, `certificates.py`,
`predicates.py`, `invariants.py`)
**Baselines:** STRIX `849018d`; C-engine `3a23b13` (read-only extraction source).

> Scope note (honesty mandate). This document describes the **implemented and
> tested** typed evidence graph and its certificate layer. It makes **no claim**
> of novelty, patentability, statistical significance, endorsement, or funding
> eligibility. The individual building blocks (typed DAGs, content addressing,
> topological traversal) are established computer-science methods and are **not**
> independently novel; the proposed R1 contribution is their **composition** into
> an independently verifiable, resource-bounded research-assurance substrate
> (R1 §33). Certificate integrity here is **content-addressing, not cryptographic
> signatures** (§5). The hypotheses H1–H12 concerning this subsystem are
> **NOT_EVALUATED** (no benchmark corpus was built; see
> `milestone-r1-report.md` §6).

---

## 1. What the evidence system is (§9)

The evidence system is a **typed, content-addressed, directed graph**
`G = (V, E, τ, π)` in which every node is an identity-bearing, frozen record and
every edge is a typed, directed relationship. It is the single data structure
over which the five admission predicates (§10, see `claim-admission-invariants.md`)
and the four certificate classes (§13) operate.

- `V` — the node set, keyed by each node's **content-derived identity** (`*_id`).
- `E` — the edge set, keyed by each edge's content-derived `edge_id`
  (deduplicated).
- `τ` — the node-typing function: each node is exactly one of the R1 node types
  below, recovered from its concrete `StrixModel` subclass.
- `π` — the identity function (`node_identity`), which maps a node to its
  content-derived id via an explicit per-type registry
  (`_NODE_ID_FIELDS`), falling back to the first `*_id` field for any other
  `StrixModel`.

`EvidenceGraph` (`graph.py`) is a **mutable builder**: `add_node`/`add_edge`
mutate internal state, but every read accessor returns immutable copies
(tuples / fresh sets), so callers can never reach the internal containers. An
immutable, hashable `GraphSnapshot` is produced for certificate references.

**Status: IMPLEMENTED/TESTED** — 128 tests across the `strix.evidence_graph`
package (per `milestone-r1-report.md` §3).

---

## 2. Node types (§9.1) — IMPLEMENTED/TESTED

The graph admits two families of node, unified under the frozen
`StrixModel` base (`extra='forbid'`). **Reuse-first:** the four existing STRIX
lineage models are reused unchanged; the R1 layer adds the new pre-verification,
policy, and result types.

### 2.1 Existing (reused) lineage nodes

| Node | Origin | Identity field | Role |
|---|---|---|---|
| `SourceArtifact` | `strix.models` | `artifact_id` | A preserved raw source document/record — the root of any admissible provenance chain. |
| `SourceFact` | `strix.models` | `fact_id` | A **validated** fact extracted from an artifact (carries validation status; typed concept/unit). |
| `CalculationResult` | `strix.models` | `calculation_id` | An existing STRIX analytical result with a `recompute()` verifier entry point. |
| `Evidence` | `strix.models` | `evidence_id` | An evidentiary record binding a fact/result to what it attests. |

### 2.2 New R1 nodes

| Node | Module | Identity field | Role |
|---|---|---|---|
| `SourceObservation` | `nodes.py` | `observation_id` | A **raw, pre-validation** observation extracted from an artifact. Distinct from `SourceFact`: no validation status; `concept`/`unit` are free-form; its own temporal metadata (`observed_at`, `publication_at`, `available_at`) is part of its content identity — describing *when the observed fact was known in the world*, not process wall-clock. |
| `CandidateClaim` | `nodes.py` | `candidate_claim_id` | A **pre-verification** claim about a subject. Distinct from the verified `Claim`: carries **no** verification status or direction; `claim_type` free-form; records the `knowledge_cutoff` under which it was proposed; holds `evidence_ids` and typed `Assertion`s. This is the sole **untrusted** surface the research agent controls (R1 §10.6). |
| `VerificationPolicy` | `nodes.py` | `policy_id` | The **trusted, versioned** policy governing admission: `mandatory_predicates`, `temporal_mode`, exact `Decimal` tolerances, freshness bound, source-independence flag, and the authoritative point-in-time `as_of_cutoff`. Provider/agent output can never substitute for it. |
| `ComputationResult` | `strix.native.results` | `computation_id` | The typed, content-addressed result of a native numerical operation (R1 §7.2), carrying its `NumericalContract`, input digest, and backend id. It is evidence-compatible; the backend never assigns a factual verdict. |

> `Assertion` (a `metric`/`asserted_value`/`unit`/`evidence_id` tuple inside a
> `CandidateClaim`) is a structural member, not a free-standing graph node.

### 2.3 The four certificate classes (§13) — IMPLEMENTED/TESTED

Certificates are frozen, content-addressed records that attest *a specific policy
was satisfied against preserved inputs* (see §4). They are produced from the
graph rather than stored as ordinary traversable nodes:

| Certificate | §13 | Attests |
|---|---|---|
| `ComputationCertificate` | §13.1 | A numerical operation met its `NumericalContract` against an independent reference. |
| `ClaimCertificate` | §13.2 | A candidate claim passed the mandatory predicates under a named policy, over a preserved `GraphSnapshot`. |
| `AuthorizationCertificate` | §13.3 | An action was authorized (or denied) under a named authorization policy, bounded by a time window. |
| `OutcomeCertificate` | §13.4 | A dispatched action's reported results were reconciled against independently observed post-execution state. |

---

## 3. The 13 relationship kinds (§9.2) — IMPLEMENTED/TESTED

Every edge carries exactly one `RelationshipKind` (`nodes.py`,
`RelationshipKind` StrEnum), a directed `source_id → target_id`, optional
`evidence_ids`, and a non-identifying `note` (excluded from the edge's content
identity). The 13 kinds:

| # | Kind | Semantics (`source → target`) | Derivation subgraph? |
|---|---|---|---|
| 1 | `derived_from` | source is derived from the ancestor target | yes |
| 2 | `extracted_from` | source was extracted from the target artifact | yes |
| 3 | `calculated_from` | source was computed from the target inputs | yes |
| 4 | `depends_on` | source structurally depends on the target | yes |
| 5 | `supported_by` | source assertion is supported by target evidence | no |
| 6 | `contradicted_by` | source is contradicted by the target | no (may cycle) |
| 7 | `attributed_to` | source is attributed to the target source | no |
| 8 | `verified_by` | source was verified by the target record | no |
| 9 | `supersedes` | source supersedes the target (revision) | no |
| 10 | `satisfies_requirement` | source satisfies the target requirement | no |
| 11 | `authorized_by` | source action is authorized by the target | no |
| 12 | `resulted_in` | source action resulted in the target outcome | no |
| 13 | `reconciled_with` | source is reconciled with the target observation | no |

**Derivation / provenance subgraph.** Exactly four kinds induce the acyclic
derivation subgraph used by ancestry, closure, topological ordering, and the
acyclicity check: `DERIVED_FROM`, `EXTRACTED_FROM`, `CALCULATED_FROM`,
`DEPENDS_ON` (`DERIVATION_KINDS` in `graph.py`). The other kinds — notably
`CONTRADICTED_BY`, which may legitimately form cycles — are **excluded** from
that subgraph so that contradiction links never break acyclicity or traversal.

Edge direction convention: `(source --DERIVED_FROM--> target)` reads "source is
derived from target"; the **target is the ancestor** (provenance) and the source
is the descendant.

---

## 4. Structural guarantees — IMPLEMENTED/TESTED

### 4.1 Referential integrity

`add_edge` rejects any edge whose `source_id` or `target_id` is not already a
known node (raises `EvidenceGraphError`). `add_node` rejects a **different** node
that collides on an existing id (hash collision / corruption signal) while
treating re-adding an identical node as a no-op. Thus the graph can never hold a
dangling edge or two distinct nodes under one identity.

### 4.2 Acyclic derivation subgraph

`assert_acyclic_derivation` enforces that the four derivation kinds form a DAG.
It uses an **iterative three-colour DFS** (white/grey/black) — a deliberate fix
replacing an earlier recursive form that raised `RecursionError` on deep chains
(see `claim-admission-invariants.md` §2) — and names the detected cycle in the
error. Non-derivation edges are ignored, so contradiction links cannot trigger a
false cycle.

### 4.3 Traversal and closure

- `ancestors(id)` — all nodes `id` is transitively derived from (follows
  outgoing derivation edges).
- `descendants(id)` — all nodes transitively derived from `id` (follows incoming
  derivation edges).
- `evidence_closure(id)` — `{id} ∪ ancestors(id)`: the full body of evidence
  supporting a node (R1 §9.3). This closure is what admission predicates scan —
  the §11.16 regression fix required `support`/derivation to traverse the **full
  closure**, not a single hop, so a failed numerical contract reached via a
  longer path can no longer be ignored.
- `topological_order()` — a dependencies-first (parent-before-child) ordering of
  the entire node set, deterministic (ties broken by sorted id), and guarded by
  the acyclicity check.
- `find_contradictions()` — the `(source, target)` pairs linked by
  `CONTRADICTED_BY`, used to trigger re-evaluation (§11 invariant 8).

Reachability uses an explicit iterative stack (`_reachable`), consistent with the
no-deep-recursion discipline.

### 4.4 Deterministic graph hashing

`graph_hash()` returns a deterministic, **order-independent** digest of the whole
graph via `strix.canonical.canonical_hash` over a canonical payload: nodes sorted
by id (each as `{id, type, data}` with `type` = the model class name and `data` =
`model_dump()`), and edges sorted by `canonical_bytes`. Consequences:

- Logically identical graphs hash identically **regardless of insertion order**.
- Any change to a node's content, an edge, or the node/edge set changes the hash.

`snapshot()` packages this into an immutable, hashable `GraphSnapshot`
(`graph_hash` + sorted `node_ids` + sorted `edge_ids`), which is the content-
addressed reference a `ClaimCertificate` records for the evidence state it was
admitted over.

---

## 5. Certificate integrity: content-addressing, not signatures

Every certificate has a content-derived `certificate_id` computed (via
`strix.canonical.make_id`) over its **deterministic content only**. The process
wall-clock of issuance (`issued_at`) is recorded for audit but **excluded** from
the id, from `certificate_hash`, and from the `validate_*` comparison — so
reissuing the same logical certificate at a different time yields the same id.
`validate_*` recomputes the id from content and returns `False` if it no longer
matches the stored id, **detecting tampering with any deterministic field**. For
`AuthorizationCertificate`, the authorization and expiration timestamps *are*
part of identity (they bound the authorization), distinct from the non-identity
issuance wall-clock.

**Honest trust-model limitation.** This integrity is **content-addressing, not a
cryptographic signature.** A matching digest proves a record has not been
*altered* relative to its own content; it does **not** prove *who* produced it or
that the producer was authentic. Cryptographic signing of certificates and of
backend-produced nodes is explicitly **future work (NOT_IMPLEMENTED)**, and the
freshness/authenticity gaps this leaves are documented in
`milestone-r1-report.md` §10 and §11.5. Integrity hash-checking of *node* content
currently covers only the factory-built node types (`SourceObservation`,
`CandidateClaim`); backend-produced nodes (`SourceFact`, `Evidence`,
`CalculationResult`, `ComputationResult`, `SourceArtifact`) are trusted under the
stated trust model.

---

## 6. The §9.4 trust distinctions — the core discipline

The evidence system is built around three **independent** properties that are
routinely conflated and that R1 §9.4 insists on keeping separate. Collapsing any
two of them is the failure mode the whole design exists to prevent:

1. **Artifact integrity** — "the bytes have not been altered." Established by
   content-addressing (`*_id` = hash of content). This says **nothing** about
   where the bytes came from or whether their contents are true.
2. **Source authenticity** — "this artifact genuinely came from the claimed
   source." A valid content hash does **not** establish this; it requires a
   cryptographic signature or an authenticated channel, which is **not yet
   implemented** (§5). An attacker-fabricated document can have a perfectly valid
   integrity hash.
3. **Factual truth** — "the assertion is true of the world." This is **never**
   established by a hash or a certificate. A `ComputationCertificate` attests
   that a division reproduced its reference to tolerance — not that the dividend
   was the right number. A `ClaimCertificate` attests that a claim survived the
   policy's predicates over the **recorded** evidence — not that the claim is
   unconditionally true. Certificates are **falsifiable, auditable receipts, not
   oracles** (R1 §13).

This separation is enforced structurally: `SourceObservation` is deliberately
distinct from the validated `SourceFact`; `CandidateClaim` carries no verdict
field and the agent cannot assign one; and admission verdicts
(`VerificationOutcome`: `VERIFIED`, `CONTRADICTED`, `INSUFFICIENT_EVIDENCE`,
`UNVERIFIABLE`, `STALE`, `INVALID_EVIDENCE`, `INTEGRITY_FAILURE`,
`UNRESOLVED_CONFLICT`) are kept **separate from research-termination states**, so
that resource exhaustion never implies an unsupported assertion is false
(R1 §10.7). Invariant §11.6 ("content integrity ≠ semantic truth") is
implemented and tested in `invariants.py`.

---

## 7. Status summary

| Item | Status |
|---|---|
| Node types (4 reused + `SourceObservation`, `CandidateClaim`, `VerificationPolicy`, `ComputationResult`, 4 certificates) | IMPLEMENTED/TESTED |
| 13 relationship kinds; 4-kind derivation subgraph | IMPLEMENTED/TESTED |
| Referential integrity; identity-collision rejection | IMPLEMENTED/TESTED |
| Acyclic derivation subgraph (iterative 3-colour DFS) | IMPLEMENTED/TESTED |
| Traversal: ancestors/descendants/closure/topo-order/contradictions | IMPLEMENTED/TESTED |
| Deterministic order-independent graph hashing + `GraphSnapshot` | IMPLEMENTED/TESTED |
| Certificate content-addressed ids + tamper-detecting `validate_*` | IMPLEMENTED/TESTED |
| §9.4 trust distinctions enforced structurally | IMPLEMENTED/TESTED |
| Cryptographic signing of certificates / backend-produced nodes | NOT_IMPLEMENTED (future work) |
| H1–H12 hypotheses touching this subsystem | NOT_EVALUATED |
| Live agent/API/frontend integration of the graph | NOT_IMPLEMENTED (see report §8) |

Test evidence: the `strix.evidence_graph` package contributes **128 tests**
within the R1 suite total of **1430 passed, 2 skipped, 2 xfailed** (baseline
`862 passed`), `mypy --strict` clean and `ruff` zero on R1 modules
(`milestone-r1-report.md` §3, §5). These are **engineering** (unit/integration)
validations of the implemented mechanisms — **not** scientific validation of the
R1 research hypotheses, which remain NOT_EVALUATED.

See also: `claim-admission-invariants.md` (the five predicates and §11
compositional invariants that run over this graph), `numerical-contracts.md`
(the `ComputationResult`/`NumericalContract` node contract), and
`milestone-r1-report.md` (authoritative milestone status and classification).
