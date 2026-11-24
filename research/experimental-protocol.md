# Experimental Protocol (R1 §29) — PLANNED / NOT_EVALUATED

**Milestone:** R1 — Resource-Bounded Typed Evidence Verification for Trustworthy
Autonomous AI
**Status key (§37):** IMPLEMENTED · TESTED · NOT_IMPLEMENTED · NOT_EVALUATED · BLOCKED
**Document status:** This is a **design specification only**. Nothing described
here has been executed. No corpus has been built, no baseline has been run, no
ablation has been measured, and **no threshold has been observed**.

---

> **Honesty mandate.** This document specifies the *intended* experimental
> protocol for evaluating STRIX's R1 hypotheses (H1–H12, §28/§30). Every
> hypothesis is **NOT_EVALUATED**. Every number that appears here is a *target*
> drawn from the R1 spec, never a measurement. The 1,200-question corpus does not
> exist yet; the ten research baselines, the computational baselines, the
> acquisition-policy comparisons, and the ablation removals are **NOT_IMPLEMENTED**
> and **NOT_EVALUATED**. Reporting any of the quantities below as achieved would be
> fabrication. The genuine-source demonstrations (§31) are **NOT_EXECUTED**.
>
> The verification substrate the protocol would exercise (native compute, the
> typed evidence graph, the five admission predicates, the four certificate
> classes, the GAP cores, and the answer-first synthesis + response validation)
> is IMPLEMENTED and unit/integration TESTED (see `milestone-r1-report.md` §5),
> but that is **engineering validation**, not scientific evaluation of the
> hypotheses.

---

## 1. Purpose and scope

The protocol defines how R1's claims would be *falsified or supported* under the
project's falsification-first discipline (CLAUDE.md Principle 1). The burden of
proof is on STRIX: each hypothesis begins as **false** and is admitted only if a
pre-registered, out-of-sample, cost-aware comparison survives.

Nothing in this document should be read as a result. It is the test plan that a
future milestone (R2) would execute. Until then every outcome is NOT_EVALUATED.

### 1.1 Pre-registration discipline

Before any run:

- The corpus split, baseline set, ablation set, metrics, and decision thresholds
  are frozen in version control (content-addressed) **prior** to touching the
  held-out partition.
- The held-out and adversarial partitions are sealed. They are opened exactly once,
  at final evaluation, after all development and tuning are complete.
- Any post-hoc change to metrics or thresholds invalidates the held-out result and
  requires a fresh seal. This is the out-of-sample-is-king rule (CLAUDE.md
  Principle 3) applied to a verification benchmark rather than a trading backtest.

---

## 2. The 1,200-question corpus (PLANNED, NOT built)

**Status: NOT_IMPLEMENTED.** No questions have been authored or labelled. The
target is a corpus of **1,200 research questions** answerable from preserved,
point-in-time authoritative sources, each carrying an independently established
ground-truth answer and a ground-truth support set (the evidence that does — and
does not — attest each assertion).

### 2.1 Intended partitioning

| Partition | Target share | Target count | Purpose |
|---|---|---|---|
| Development (dev) | 25% | ~300 | Prompt/pipeline iteration, debugging, error analysis. Freely inspectable. |
| Validation | 25% | ~300 | Model/policy selection, acquisition-policy tuning, threshold calibration. Inspectable only in aggregate. |
| Held-out | ~42% | ~500 | Final, single-shot evaluation of H1–H12. Sealed until pre-registration is frozen. |
| Adversarial | ~8% | ~100 | Deliberately falsifiable items: fabricated figures, metric-relabeled claims, post-cutoff leakage, stale evidence, unsupported numerics. |

Counts are **design targets**, not a built artifact. The adversarial partition is
further split into *organic* (adversarial items sourced from genuine ambiguous or
contested real material) and *synthetic* (constructed fixtures). Synthetic items
MUST be labelled as synthetic and **reported separately** (see §8); they are never
pooled into the genuine-source headline numbers.

### 2.2 Question taxonomy (intended coverage)

To avoid a corpus that is accidentally easy, the design targets a stratified mix:

- **Direct lookup** — a single preserved figure from one source.
- **Single-step derivation** — one native computation over cited inputs
  (e.g., a ratio, a growth rate).
- **Multi-step / multi-source** — composition across ≥2 preserved artifacts,
  requiring full-closure provenance and derivation checks.
- **Point-in-time** — the correct answer depends on an as-of cutoff; post-cutoff
  information must not be admissible.
- **Unanswerable-by-design** — no preserved evidence supports any answer; the
  correct behaviour is ABSTAIN / INSUFFICIENT_EVIDENCE, not a guess.
- **Trap / falsification** — the adversarial partition's class; the correct
  behaviour is rejection of the fabricated or relabeled claim.

Each item records: the question, the as-of cutoff, the authoritative source(s),
the ground-truth answer (or "unanswerable"), the ground-truth support set, the
category, and a labelling provenance record (who/what established the label and
how it was adjudicated). **None of these records exist yet.**

### 2.3 Labelling and inter-rater integrity (PLANNED)

The design calls for independent labelling with adjudication of disagreements and
a recorded inter-rater agreement statistic. No labelling has been performed; the
agreement statistic is **NOT_EVALUATED**. Survivorship and point-in-time integrity
would be enforced by using only sources preserved *as of* each question's cutoff.

---

## 3. The ten research baselines (PLANNED, NOT built)

**Status: NOT_IMPLEMENTED / NOT_EVALUATED.** STRIX's verified-answer pipeline would
be compared against a ladder of baselines, each ablating a layer of assurance so
that any measured benefit is attributable to a specific mechanism rather than to
the language model alone. The intended ten:

1. **Raw LLM, no retrieval** — the model answers from parametric memory only.
2. **LLM + naive retrieval (RAG)** — retrieval with no provenance preservation or
   admission control.
3. **LLM + retrieval + self-critique** — the model is asked to check its own
   answer (self-grading; no independent verifier).
4. **LLM + retrieval + citation requirement** — answers must cite, but citations
   are not independently verified against the cited evidence.
5. **LLM + retrieval + numeric recomputation only** — derivation checked, but no
   support/provenance/temporal predicates.
6. **LLM + retrieval + support check only** — support predicate only.
7. **LLM + retrieval + provenance check only** — provenance predicate only.
8. **LLM + retrieval + temporal/point-in-time check only** — temporal predicate only.
9. **STRIX full admission (all five predicates), LLM-mediated synthesis** — the
   complete I∧T∧P∧D∧S admission gate feeding the §16 synthesis.
10. **STRIX full admission, deterministic synthesis (no LLM in the answer path)** —
    the §16 deterministic answer path already proven by the integration test,
    evaluated at corpus scale.

Baselines 1–8 isolate the marginal contribution of each predicate; 9 vs 10
isolates whether an LLM in the synthesis path changes faithfulness. All ten are
**design artifacts only** — none have been implemented for the benchmark or run.

### 3.1 Primary research metrics (targets, not measured)

For each baseline the protocol would record, per partition:

- **Unsupported-claim rate** — fraction of material factual assertions in the
  rendered answer not backed by an admitted claim certificate. (H-target: STRIX
  reduces this ≥70% vs the strongest non-STRIX baseline — **NOT_EVALUATED**.)
- **Faithfulness / fabrication rate** on the adversarial partition — fraction of
  fabricated/relabeled claims that are (incorrectly) answered. (H-target: ≥95%
  adversarial detection — **NOT_EVALUATED**.)
- **Answer accuracy** vs ground truth, conditioned on the system choosing to answer.
- **Abstention correctness** — on unanswerable-by-design items, the rate of correct
  ABSTAIN/INSUFFICIENT_EVIDENCE vs. incorrect guessing.
- **Coverage** — fraction of answerable items the system actually answers
  (to expose any accuracy-via-silence trade-off).
- **Calibration** — agreement between the COMPLETE/PARTIAL/INSUFFICIENT/
  UNANSWERABLE classification and realized correctness.

Every number above is currently **NOT_EVALUATED**.

---

## 4. Computational baselines (PLANNED, NOT built)

**Status: NOT_IMPLEMENTED / NOT_EVALUATED.** These evaluate the native computing
layer (§6–§8), not the answering quality.

- **Reference parity:** the `PythonReferenceBackend` (IMPLEMENTED/TESTED) is the
  `REFERENCE` validation baseline. A future **C++ NativeCPUBackend** and
  **Metal backend** (both NOT_IMPLEMENTED) would be compared against it via the
  CPU/GPU parity harness (§29 / native-computing-architecture §7): representative
  + adversarial inputs, max abs/rel error recorded per operation, agreement decided
  by each operation's `NumericalContract` tolerance. No parity numbers exist.
- **Throughput / speedup targets** (H-targets for the accelerated backends) are
  **NOT_EVALUATED** — there is nothing to benchmark until the C++/Metal backends
  are built. Linux operation never depends on Metal (satisfied trivially).
- **Determinism / reproducibility:** repeated runs of the same operation on the
  same inputs must yield identical content-addressed `ComputationResult` ids
  (exact/deterministic classes) or within-tolerance agreement (tolerance/
  approximate classes), with stochastic operations identical given a recorded seed.
  This is designed and unit-tested at the operation level but **NOT_EVALUATED** at
  benchmark scale.

---

## 5. Acquisition-policy comparisons (PLANNED, NOT built)

**Status: NOT_IMPLEMENTED / NOT_EVALUATED.** The adaptive acquisition optimizer
(§15, WS5) was **not built** as a new strategy layer; the existing agent's bounded,
budgeted loop remains (`milestone-r1-report.md` §7). The protocol therefore
specifies a comparison it cannot yet run:

- **Fixed-budget baseline** — the current bounded loop with a static evidence budget.
- **Uniform acquisition** — equal effort per candidate source.
- **Value-of-information / adaptive acquisition** — allocate the next retrieval to
  the source expected to most change the admission outcome.

Intended metrics: answer accuracy and unsupported-claim rate **at matched cost**
(retrieval calls, tokens, wall-clock, and remaining-budget respected), plotted as
accuracy-vs-cost frontiers. The claim under test would be that adaptive acquisition
reaches equivalent faithfulness at lower cost — **NOT_EVALUATED**, and currently
not implementable without WS5.

Resource-exhaustion behaviour is a hard constraint, not a tunable: running out of
budget must yield an ABSTAIN-class termination state, never a weakened admission
requirement (evidence-graph invariant §11.9, IMPLEMENTED/TESTED). The protocol
would verify this holds under every acquisition policy.

---

## 6. Ablation removals (PLANNED, NOT built)

**Status: NOT_IMPLEMENTED / NOT_EVALUATED.** Starting from the full STRIX pipeline
(baseline 10), each ablation removes exactly one mechanism to measure its marginal
contribution to faithfulness and to confirm no single component is load-bearing by
accident:

| Ablation | Remove | Expected direction (hypothesis, NOT measured) |
|---|---|---|
| A1 | Integrity predicate (I) | unresolved/forged references leak in |
| A2 | Type/temporal predicate (T) | metric-relabeling + post-cutoff leakage admitted |
| A3 | Provenance predicate (P) | claims without lineage to a preserved artifact admitted |
| A4 | Derivation predicate (D) | model-asserted numbers accepted without recomputation |
| A5 | Support predicate (S) | assertions citing non-attesting evidence admitted |
| A6 | Independent response validation (§17) | unsupported sentences survive into the rendered answer |
| A7 | Full-closure scanning (revert §11.16 fix to 1-hop) | failed numerical contract via a longer path ignored |
| A8 | Durable hash-chained ledger → in-memory sink | tamper/gap/replay guarantees lost |
| A9 | Content-addressed identity on certificates | tamper detection weakened |

Each ablation would be re-run on the validation partition (for selection) and, for
the final reported set, on the sealed held-out and adversarial partitions. The
adversarial regressions that originally motivated several of these mechanisms are
already captured as unit tests (see `claim-admission-invariants.md` §2), but their
*benchmark-scale* effect sizes are **NOT_EVALUATED**.

---

## 7. Reproducibility anchors (R1 §29.6) — PLANNED

**Status: NOT_EVALUATED** as a benchmark artifact; the underlying anchoring
mechanisms are IMPLEMENTED in the substrate. Every reported run would be
reconstructible from:

- **Content-addressed corpus:** each question, label, source artifact, and split
  assignment addressed by canonical hash (`strix.canonical`), so the exact corpus
  state is pinned.
- **Pinned configuration:** the `VerificationPolicy` (version + id), backend
  selection, tolerances, and all thresholds recorded as content-addressed inputs.
- **Recorded seeds:** every stochastic operation (e.g., bootstrap) records its seed
  in the `ComputationResult`; the evaluation driver records its own RNG seed.
- **Software/build provenance:** software versions, build ids, and environment are
  captured per result (mirroring `RunManifest`/`VerificationResult` convention),
  with nondeterministic fields (wall-clock, duration) excluded from content hashes.
- **Decision ledger:** the GAP-002 durable, hash-chained ledger records the run's
  lifecycle events; `verify_chain` detects tamper/gap/broken-link, and replay
  reconstructs the decision trace.
- **Sealed-partition manifest:** a pre-registration manifest (frozen before the
  held-out seal is opened) fixing corpus hash, baselines, ablations, metrics, and
  thresholds. **Caveat:** manifests are currently content-addressed, **not
  cryptographically signed** — this is a documented trust-model limitation
  (`milestone-r1-report.md` §10); signing is future work.

A full reproduction package (corpus hash, policy hash, seeds, driver, environment)
would accompany any published result. No such package exists because no run exists.

---

## 8. Statistics: paired comparison and confidence intervals (PLANNED)

**Status: NOT_EVALUATED.** The design prioritizes statistical validity over
headline performance (CLAUDE.md Principle, "statistical validity over backtest
performance"). Intended analysis:

- **Paired design.** STRIX and each baseline answer the *same* items, so all
  comparisons are **paired** (per-question). Primary comparisons use paired tests:
  McNemar's test for the paired binary outcomes (answered-correctly,
  unsupported-claim-present, fabrication-detected) and a paired test (e.g.,
  Wilcoxon signed-rank) for per-question continuous scores.
- **Effect sizes with intervals.** Every reported difference carries a
  **bootstrap confidence interval** (percentile bootstrap, recorded seed — using
  `inference.bootstrap_mean_ci`, IMPLEMENTED/TESTED) in addition to a p-value. A
  difference is reported as supported only if its CI excludes the null and the
  pre-registered minimum effect size.
- **Multiple-comparison control.** With ten baselines, nine ablations, and several
  metrics, the family-wise error is controlled via **Benjamini–Hochberg** FDR (or
  Bonferroni where strict FWER control is required) — both IMPLEMENTED/TESTED in
  `strix.native.inference`. The correction family is declared in the
  pre-registration manifest.
- **Stratified reporting.** Results are reported overall and per question category
  (§2.2) and per partition, so a gain concentrated in one easy stratum cannot be
  presented as a global result.
- **Synthetic vs genuine separation.** Synthetic adversarial fixtures are analyzed
  and reported **separately** from genuine-source items and never pooled into the
  headline faithfulness figures. Synthetic results are clearly labelled as
  constructed stress tests, not evidence of real-world performance.
- **Negative findings preserved.** Any hypothesis whose pre-registered threshold is
  not met is reported as EXPERIMENTALLY_UNSUPPORTED or INCONCLUSIVE, never quietly
  dropped (falsification-first; CLAUDE.md "prefer rejection over false confidence").

All statistics above would operate on data that **does not exist yet**; every
resulting p-value, CI, and effect size is **NOT_EVALUATED**.

---

## 9. Decision rule (per hypothesis)

For each of H1–H12 the pre-registered rule would be:

- **EXPERIMENTALLY_SUPPORTED** — the held-out paired comparison meets the
  pre-registered effect-size threshold, its bootstrap CI excludes the null after
  FDR control, and the adversarial partition shows no contradicting failure mode.
- **EXPERIMENTALLY_UNSUPPORTED** — the threshold is not met, or the CI includes the
  null, or an adversarial failure contradicts the claim.
- **INCONCLUSIVE** — insufficient power or unresolved confound.
- **NOT_EVALUATED** — the run was not performed. **This is the status of all of
  H1–H12 today.**

---

## 10. What exists vs. what this protocol requires

| Protocol element | Status |
|---|---|
| Verification substrate (predicates, certificates, GAP cores, synthesis) | IMPLEMENTED / TESTED |
| Native reference backend + inference statistics used by §8 analysis | IMPLEMENTED / TESTED |
| Reproducibility anchoring mechanisms (content-addressing, ledger, seeds) | IMPLEMENTED |
| 1,200-question corpus (dev/validation/held-out/adversarial) | NOT_IMPLEMENTED |
| Ten research baselines | NOT_IMPLEMENTED |
| C++/Metal computational baselines + parity harness | NOT_IMPLEMENTED |
| Adaptive acquisition optimizer (needed for §5 comparisons) | NOT_IMPLEMENTED |
| Ablation harness (A1–A9) | NOT_IMPLEMENTED |
| Benchmark execution of H1–H12 | NOT_EVALUATED |
| Genuine-source demonstrations A–G (§31) | NOT_EXECUTED |
| Cryptographic signing of the pre-registration manifest | future work |

This protocol is the test plan for a future milestone (R2, see
`milestone-r1-report.md` §11). As of 2026-11-24 it has **not been executed**, and
no threshold reported in the R1 spec has been measured.
