# STRIX Comparative Experiment Design — Milestone 0B (§7)

**Audit commit of record:** `3dc70eac6b6b178d51156185113beb70d7c899e4`
**Work branch:** `feat/milestone-0b`
**Companion documents:**
[`requirements-baseline.yaml`](./requirements-baseline.yaml),
[`engineering-audit.md`](./engineering-audit.md),
[`milestone-1-evidence-interoperability-spec.md`](./milestone-1-evidence-interoperability-spec.md),
[`milestone-2-execution-assurance-spec.md`](./milestone-2-execution-assurance-spec.md),
[`milestone-3-outcome-certification-spec.md`](./milestone-3-outcome-certification-spec.md).

> **No results claimed yet — design only.** This document specifies *how* the
> three research gaps would be tested. It reports **zero** measurements,
> **zero** outcomes, and makes **no** claim that any STRIX component outperforms
> any baseline. The hypotheses below are deliberately falsifiable: each names the
> result that would **reject** it. Per STRIX claim discipline, nothing here
> asserts novelty, performance superiority, patentability, government readiness,
> or commercial validation. No live payments, trades, or external execution are
> involved; all "execution" is against simulated/sandboxed adapters.

---

## 0. Purpose and framing

The engineering audit establishes what exists today (ESTABLISHED IMPLEMENTATION
FACTS). This document states the **RESEARCH HYPOTHESES** that the three
milestones are built to test, and the experiment that would confirm or falsify
each. The burden of proof is on the proposed methodology: every hypothesis
starts assumed false and must survive an attempt to destroy it.

Each hypothesis maps 1:1 to a gap:

| Hypothesis | Gap | Milestone under test | Primary requirements |
|---|---|---|---|
| H1 | GAP-001 Dynamic Evidence-Bound Execution Assurance | Milestone 2 | STRIX-002/004/005/006/007/008 |
| H2 | GAP-002 Closed-Loop Execution & Outcome Certification | Milestone 3 | STRIX-009/010/011/014 |
| H3 | GAP-003 Interoperable Financial Evidence Verification | Milestone 1 | STRIX-003/012/013 (001) |

---

## 1. The four experimental arms (common to all hypotheses)

Every hypothesis is evaluated across the **same four arms** so differences are
attributable to the governance methodology, not to incidental implementation
quality. Arm 3 is a **realistic, competent baseline**, not a strawman: it
implements the obvious engineering defenses a careful team would ship.

- **Arm A — Conventional deterministic rules.** Static, hand-written
  if/then rules evaluated once at decision time. No execution-time
  re-validation, no evidence-freshness concept, no outcome observation. Models
  the "scripted automation" status quo.
- **Arm B — Ungoverned autonomous agent.** An LLM-driven agent that proposes
  *and* executes actions with no independent verifier in the loop (i.e. the
  STRIX proposer path — `agent/openai_provider.py`, `agent/orchestrator.py` —
  with the deterministic acceptance boundary **removed**). Models "trust the
  model."
- **Arm C — Competent conventional runtime policy enforcement (realistic
  baseline).** A non-STRIX runtime that *does* enforce the obvious defenses:
  evidence time-to-live (TTL) freshness checks at execution time, idempotency
  keys for duplicate suppression, and record reconciliation by primary key. It
  lacks STRIX's specific contributions: versioned-policy binding, exact
  action-parameter certificates, atomic single-use authorization consumption,
  independent outcome observation, and typed cross-source abstention.
- **Arm D — Proposed STRIX assurance methodology.** The full stack per
  Milestones 1–3: canonical evidence + reconciliation (M1), evidence-bound
  authorization certificates + execution-time revalidation + fail-closed
  gateway (M2), and the decision→action→outcome ledger with independent outcome
  verification (M3).

> Arm C existing is what makes any positive result for Arm D meaningful: the
> interesting question is **not** "is STRIX better than doing nothing" (Arms A/B)
> but "does STRIX's specific methodology add assurance beyond competent
> conventional engineering" (Arm C).

---

## 2. Hypothesis H1 — Dynamic Evidence-Bound Execution Assurance (GAP-001)

### H1 statement (alternative hypothesis)
An independent, execution-time verification engine that binds each authorization
to (a) a versioned policy, (b) the exact action parameters, and (c) the
freshness/validity of the specific supporting evidence, and that consumes each
authorization atomically and exactly once, **blocks a materially larger fraction
of actions whose supporting evidence has become stale, contradictory, invalid,
or whose parameters were altered after authorization** than Arms A, B, and C —
without materially increasing the blocking of actions whose evidence remained
valid (false-authorization-withheld rate).

### H1 null hypothesis (H1₀)
Arm D's unsafe-execution rate is **not lower** than the best of Arms A/B/C on the
stale/contradictory/invalid/parameter-tamper scenario set (i.e. the difference
is ≤ 0 or within the pre-registered confidence interval), **or** Arm D achieves
any reduction only by also blocking valid actions at a materially higher rate
(no net assurance gain).

### Variables
- **Independent (manipulated):** arm (A/B/C/D); scenario class (fresh / stale /
  contradicted / invalidated / parameter-tampered / policy-superseded); the
  time gap Δ between authorization and execution; TOCTOU injection point
  (see M2 spec §TOCTOU matrix).
- **Dependent (measured):**
  - **Unsafe-execution rate** = fraction of actions that executed although
    their supporting evidence was stale/contradictory/invalid or their
    parameters differed from the authorized parameters (lower is better).
  - **Stale-action-block rate** = of actions that *should* have been blocked,
    the fraction actually blocked (recall; higher is better).
  - **False-authorization rate** = fraction of actions executed under an
    authorization that did not actually cover them (parameter/policy mismatch).
  - **Valid-action-block rate** = fraction of genuinely-valid actions wrongly
    blocked (over-blocking cost; lower is better).
  - **Replay-acceptance rate** = fraction of re-presented (already-consumed)
    authorizations that executed a second time (lower is better; target 0).
  - **Decision-to-block latency** (observational, not a hypothesis criterion).
- **Controlled:** identical action set, identical evidence corpus, identical
  policies, identical Δ distribution, identical random seed per scenario.

### H1 falsification criterion (what REJECTS H1)
H1 is **rejected** if, on the held-out scenario set, **any** of:
1. Arm D's unsafe-execution rate is not strictly lower than `min(A,B,C)` beyond
   the pre-registered margin and 95% bootstrap CI; or
2. Arm D's valid-action-block rate exceeds the best conventional arm by more
   than the pre-registered tolerance (assurance bought only by over-blocking);
   or
3. Arm D's replay-acceptance rate on consumed certificates is > 0 (any
   successful replay falsifies the "atomic single-use" claim outright); or
4. Any single TOCTOU cell in the M2 matrix shows Arm D executing on evidence
   that was valid at check time but invalid at use time.

---

## 3. Hypothesis H2 — Closed-Loop Execution & Outcome Certification (GAP-002)

### H2 statement
A domain-independent decision→action→outcome ledger with correlation
identifiers, independent outcome observation, and idempotent retry/duplicate
handling **attributes realized outcomes to the authorizing decision more
accurately, and certifies fewer incomplete/incorrect outcomes as complete,**
than Arms A/B/C, and does so **under injected retries, partial failures, and
missing outcome evidence** — remaining correct across at least two distinct
execution domains (demonstrating domain-independence).

### H2 null hypothesis (H2₀)
Arm D's outcome-attribution accuracy is **not higher** (and/or its
mis-certification rate **not lower**) than the best of Arms A/B/C under the
fault-injection regime, within the pre-registered CI; **or** the capability only
works in a single domain (fails the second-domain replication).

### Variables
- **Independent:** arm; fault class (clean / retry-duplicate / partial-failure /
  lost-outcome-evidence / delayed-outcome / orphaned-decision /
  orphaned-outcome); execution domain (≥2 adapters, e.g. a simulated
  compute-job adapter and a sandboxed payment adapter — payments are **one**
  adapter, never a dependency).
- **Dependent:**
  - **Outcome-attribution accuracy** = fraction of outcomes correctly linked to
    the decision that authorized them (vs ground-truth linkage).
  - **Mis-certification rate** = fraction of outcomes certified "complete &
    correct" that ground truth says were incomplete/failed (lower is better;
    double-counting a retried outcome counts here).
  - **Duplicate-suppression rate** = of injected duplicate executions, the
    fraction collapsed to a single certified outcome.
  - **Abstention correctness on outcomes** = when outcome evidence is missing,
    fraction correctly left `unverified/abstain` rather than guessed.
  - **Orphan-detection recall** = fraction of injected orphaned
    decisions/outcomes flagged.
- **Controlled:** identical decision stream, identical fault schedule per seed,
  identical outcome ground truth, identical correlation-id scheme offered to all
  arms that can use one.

### Ground truth for H2
Because the harness *generates* the decision/action/outcome stream, the true
linkage and true completion status of every action are known by construction
(the simulator records them out-of-band, never exposed to the arms). "Correct
attribution" is measured against this recorded ground truth.

### H2 falsification criterion (what REJECTS H2)
H2 is **rejected** if **any** of:
1. Arm D's outcome-attribution accuracy is not strictly higher than `min` over
   A/B/C beyond margin+CI; or
2. Arm D ever certifies a double-counted or incomplete outcome as complete
   (mis-certification rate > 0 on the partial-failure/retry classes); or
3. Arm D's behavior differs qualitatively between the two domains (i.e. the
   ledger/outcome contracts are secretly domain-coupled), falsifying
   domain-independence; or
4. Arm C matches Arm D within CI on every metric (no gain over competent
   conventional idempotency + reconciliation).

---

## 4. Hypothesis H3 — Interoperable Financial Evidence Verification (GAP-003)

### H3 statement
A canonical cross-source evidence schema with a single shared reconciliation
interface and a first-class typed abstention outcome **detects conflicts between
heterogeneous records, and correctly abstains when conflicts are unresolvable,
more accurately than** Arms A/B/C, **while preserving provenance and
requirements traceability end-to-end** (every reconciled value remains traceable
to each source's preserved bytes and to the STRIX requirement it serves).

### H3 null hypothesis (H3₀)
Arm D's discrepancy-detection F1 (and/or abstention correctness) is **not
higher** than the best of A/B/C within CI; **or** Arm D achieves detection gains
at the cost of broken provenance/traceability (traceability-preservation rate
not ≥ conventional).

### Variables
- **Independent:** arm; conflict class (agreement / numeric-mismatch /
  unit-mismatch / missing-record / stale-vs-fresh / revision-conflict /
  irreconcilable); number of heterogeneous sources (2…N); tolerance regime.
- **Dependent:**
  - **Discrepancy-detection precision / recall / F1** against injected
    conflicts.
  - **Abstention correctness** = fraction of *genuinely unresolvable* cases in
    which the arm emits explicit abstention (not a silent pick, not a guess),
    **minus** false abstentions on resolvable cases.
  - **Silent-resolution rate** = fraction of conflicts silently resolved to one
    value with no discrepancy emitted (lower is better; this is the classic
    failure mode).
  - **Traceability-preservation rate** = fraction of reconciled outputs that
    still resolve back to every contributing source's preserved bytes **and**
    the governing STRIX requirement id.
- **Controlled:** identical source records, identical injected conflicts,
  identical tolerances, identical seed.

### Ground truth for H3
Conflicts are **injected** into otherwise-agreeing source pairs/sets by a
generator that records, per fact, the true relationship (agree / which value is
correct / genuinely unresolvable). Detection and abstention are scored against
that record. A subset uses real heterogeneous public fixtures (e.g. the same
fundamental reported two ways) with human-adjudicated ground truth for external
validity.

### H3 falsification criterion (what REJECTS H3)
H3 is **rejected** if **any** of:
1. Arm D's discrepancy F1 is not strictly higher than `min(A,B,C)` beyond
   margin+CI; or
2. Arm D's silent-resolution rate is not strictly lower than the best
   conventional arm (fails the core "never silently prefer one" requirement,
   STRIX-003); or
3. Arm D's abstention correctness is ≤ the best conventional arm (the
   first-class-abstention contribution adds nothing); or
4. Arm D's traceability-preservation rate drops below the conventional arms
   (detection bought by losing provenance — violates GAP-003's core).

---

## 5. Ground-truth datasets (all hypotheses)

| Dataset | Used by | Ground-truth mechanism | Provenance |
|---|---|---|---|
| **Synthetic action/evidence stream** | H1 | Generator records, per action, true evidence validity at check and use time, true authorized parameters, and policy version in force. | Deterministic generator, seed-pinned. |
| **Synthetic decision→outcome stream** | H2 | Simulator records true decision↔outcome linkage and true completion status out-of-band; injects faults on a seeded schedule. | Deterministic simulator, seed-pinned; ≥2 adapters. |
| **Synthetic multi-source conflict set** | H3 | Conflict generator records, per fact, agree/which-correct/unresolvable. | Seeded injection over agreeing base pairs. |
| **Real heterogeneous public fixtures** | H3 (external validity) | Human adjudication of a held-out subset (same fact, ≥2 public sources). | Preserved byte-exact via `run_store._preserve_raw_files`; hashes recorded. |
| **STRIX regression fixtures** | all (controls) | Existing passing fixtures serve as positive controls (agreement must stay agreement). | Repo `src/strix/fixtures`, existing tests. |

Ground truth is **never** exposed to any arm during the run (mirrors the
existing engineering `ExpectedModel` discipline: ground truth yields no facts and
is read only by the post-run metrics step — `engineering/models.py:ExpectedModel`,
`EngineeringRunManifest.evaluation_source_hashes`).

---

## 6. Experimental controls

- **Identical inputs per cell.** All four arms see byte-identical evidence,
  actions, policies, and fault schedules for a given (scenario, seed). Enforced
  by preserving inputs once and replaying them into each arm.
- **Positive controls.** Agreement/clean/fresh scenarios must yield *no* blocks,
  *no* discrepancies, *no* abstentions in any arm; an arm that fails a positive
  control is disqualified for that run (guards against a trivially
  "block-everything" Arm D gaming the unsafe-execution metric — which is exactly
  why valid-action-block rate is a co-primary metric for H1).
- **Placebo / negative controls.** Scenarios with randomized (meaningless)
  "evidence" must not produce spurious confident authorizations or
  confirmations; expected behavior is abstention.
- **Arm-blind scoring.** Metrics are computed by a scorer that receives only
  (arm-output, ground-truth) and does not know which arm produced the output.
- **Pre-registration.** Hypotheses, metrics, margins, and CI method are frozen
  in this document before any arm is run; deviations are logged.

---

## 7. Reproducibility requirements

- **Seeds.** Every generator/simulator is seeded; the seed set is recorded in
  the run manifest. Re-running a seed reproduces the identical input stream.
- **Pinned versions.** Pipeline version, parser versions, schema versions, and
  verifier version are recorded exactly as the existing manifests already do
  (`models.py:RunManifest`, `engineering/models.py:EngineeringRunManifest` —
  `parser_versions`, `schema_versions`, `pipeline_version`).
- **Deterministic replay via existing engines.** Each arm's run is persisted via
  `run_store.RunStore.persist_generic` (atomic, hash-verified raw preservation)
  and must replay through the existing three-way engines
  (`replay.replay_run`, `agent/replay.replay_agent_run`,
  `engineering/replay.replay_engineering_run`) — stored vs manifest vs recomputed
  hashes must agree, separating integrity failure from reproducibility failure.
  Wall-clock fields are excluded from replay comparison, as today.
- **Canonical hashing.** All recorded values use `canonical.canonical_hash` /
  `canonical_bytes` (Decimal-only, float-forbidden), so cross-machine hashes
  match.
- **Caveat (honest).** Arm B (and the proposer path in Arm D) invokes an LLM
  whose wording is stochastic; as today, agent replay does **not** reproduce LLM
  wording (`agent/replay.py`). Reproducibility therefore covers the
  deterministic verification/authorization/ledger decisions and the *structured*
  outputs, **not** free-text model prose. Metrics are computed only over the
  deterministic structured outputs so this non-determinism does not contaminate
  results.

---

## 8. Required failure scenarios (the experiment MUST include)

The experiment is invalid if it omits any of these — they are the cases the gaps
exist to address:

**H1 (execution assurance):**
- Evidence fresh at authorization, **stale at execution** (Δ exceeds TTL).
- Evidence **contradicted** between authorization and execution (new record
  disagrees beyond tolerance).
- Evidence **invalidated/withdrawn** (source retraction) before execution.
- **Parameter tampering:** execution requested with parameters ≠ authorized
  parameters.
- **Policy supersession:** the governing policy version is replaced before
  execution.
- **Replay:** a consumed authorization certificate re-presented.
- **TOCTOU race:** evidence flips between the check and the use (full matrix in
  the M2 spec).

**H2 (outcome certification):**
- Retry producing a duplicate execution for one decision.
- Partial failure (action half-completed; outcome ambiguous).
- Lost / delayed / incomplete outcome evidence.
- Orphaned decision (no outcome) and orphaned outcome (no decision).
- Cross-domain replication (≥2 adapters).

**H3 (evidence interoperability):**
- Numeric mismatch beyond tolerance; unit mismatch.
- Missing record in one source; stale-vs-fresh disagreement.
- Revision conflict (two revisions of the same fact).
- Genuinely irreconcilable conflict (correct answer = abstain).
- Agreement positive control (must stay confirmed).

---

## 9. Statistical method

- Per metric, per hypothesis: point estimate + **bootstrap 95% CI** over
  scenarios (resampling scenarios, seed-stratified), mirroring the "bootstrap
  confidence intervals" standard in the project charter.
- Pre-registered **minimum effect margin** per metric (the smallest difference
  considered meaningful) is fixed before runs; a difference inside the margin or
  whose CI crosses zero is treated as "no effect" (favors the null).
- Multiple-arm comparison uses Arm D vs **best** competing arm (the hardest
  test), not the mean.
- Rejection of a hypothesis is reported as **REJECT**; survival is reported only
  as "not rejected under this design" — never as proof of superiority.

---

## 10. Threats to validity

**Construct validity.**
- *Metric gaming:* an arm could trivially minimize unsafe-execution by blocking
  everything, or maximize discrepancy recall by flagging everything. Mitigated
  by co-primary counter-metrics (valid-action-block rate; precision alongside
  recall; false-abstention inside abstention-correctness) and positive controls.
- *Operationalization gap:* "stale/contradictory/invalid" must be defined
  identically for all arms; defined once in the M1/M2 specs and injected
  uniformly.

**Internal validity.**
- *Baseline strawman risk:* if Arm C is under-built, Arm D wins trivially.
  Mitigated by specifying Arm C as *competent* (real TTL, idempotency,
  reconciliation) and by code-reviewing Arm C against that bar before runs.
- *Implementation-quality confound:* differences could reflect better
  engineering, not methodology. Mitigated by sharing all substrate (canonical
  hashing, persistence, replay) across arms and isolating only the governance
  logic.
- *Leakage:* ground truth must never reach an arm. Mitigated by the
  ground-truth-isolation discipline already used/tested in engineering replay
  (`test_cli_replay_tamper.py` ground-truth isolation).

**External validity.**
- *Synthetic-only risk:* generators may not reflect real conflict/fault
  distributions. Mitigated by the real-fixture subset with human adjudication
  for H3 and by reporting results separately for synthetic vs real.
- *Single-domain risk (H2):* mitigated by the mandatory ≥2-domain replication.
- *LLM-version drift:* Arm B/D proposer behavior depends on the model; the model
  id and methodology versions are recorded, and claims are scoped to the
  recorded configuration only.

**Statistical-conclusion validity.**
- *Multiple comparisons:* many metrics × hypotheses. Mitigated by
  pre-registering primary metrics per hypothesis and treating the rest as
  secondary/observational.
- *Seed sensitivity:* mitigated by seed-stratified bootstrap and reporting
  across a seed sweep.

---

## 11. Decision rule and reporting

For each hypothesis the experiment yields exactly one of:
**REJECT** (a falsification criterion was met), or **NOT REJECTED under this
design** (survived; reported with CIs and the exact margins used), or
**NEED MORE DATA** (CIs too wide to decide at the pre-registered power). No other
verdict is permitted, and "NOT REJECTED" is never rephrased as "proven,"
"superior," "patentable," or "deployment-ready."

> **Reminder: No results claimed yet — this is design only.** Running the
> experiment is out of scope for Milestone 0B.
