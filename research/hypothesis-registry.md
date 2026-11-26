# STRIX H1–H12 Hypothesis Registry

**Authoritative registry of the SBIR research hypotheses.** Subordinate to
`research/MASTER_SBIR_SPECIFICATION.md` §28–§30. Companion: the full falsifiable statements for
H1–H3 live in `docs/research/milestone-0/comparative-experiment-design.md`; the protocol that
would test all twelve lives in `research/experimental-protocol.md`.

> **Status (unconditional): every hypothesis below is `NOT_EVALUATED`.** No benchmark corpus has
> been built, no arm has been run, no threshold has been observed. Every numeric figure is a
> **pre-registration TARGET**, never a measurement. The live arms (A/B and the live portions of
> C–E) are `EXTERNALLY_BLOCKED(GPT-6 Luna credentials + approved budget)`. Reporting any figure
> here as an outcome is fabrication (CLAUDE.md Principle 1).

---

## 1. Provenance of this registry (§8: "recover; do not invent or silently redefine")

Honest accounting of where each hypothesis comes from:

| Hypothesis | Provenance | Status of the *statement* |
|---|---|---|
| **H1, H2, H3** | **RECOVERED** verbatim-in-intent from `comparative-experiment-design.md` (§2–§4), each mapped 1:1 to GAP-001/002/003 with full variables and rejection criteria. | Authoritative, pre-existing. |
| **H4–H12** | **NEWLY FORMALIZED** here from (a) the R1 spec's stated intent that a set "H1–H12" would be evaluated (referenced in `nsf-project-pitch.md`, `experimental-protocol.md`, `threat-model.md`) and (b) the enumerated experiments in the SBIR goal §8. The R1 spec **named** a count of twelve but **never authored** statements for H4–H12. | **Newly formalized — not pre-existing.** Flagged as such wherever used. |

This registry does **not** overwrite H1–H3. It preserves them and adds H4–H12 as explicitly new,
so no original hypothesis is silently redefined.

## 2. Reconciliation of the two experimental-arm schemes

Two arm schemes exist in the repository and the goal. Both are preserved; neither is silently
replaced.

**Scheme α — milestone-0B assurance-methodology arms (authoritative for H1–H3)**
(`comparative-experiment-design.md` §1):
- A: Conventional deterministic rules. B: Ungoverned autonomous agent. C: Competent conventional
  runtime policy enforcement (realistic baseline). D: Proposed STRIX assurance methodology.

**Scheme β — SBIR reliability-vs-LLM arms (authoritative for H4–H12)** (goal §8):
- A: Unassured LLM. B: Conventional RAG. C: Pre-formal STRIX (retrieval + synthesis, no formal
  admission). D: Formal STRIX (full I∧T∧P∧D∧S admission). E: Complete STRIX (D + adaptive
  assurance + gateway + unified response contract).

**Mapping (the comparison that makes each result meaningful):**

| Concept | Scheme α | Scheme β |
|---|---|---|
| "Trust the model, no verification" | B (ungoverned agent) | A (unassured LLM) |
| "Competent conventional baseline" | C (TTL + idempotency + reconciliation) | B (conventional RAG) |
| "STRIX without its specific contribution" | A (static rules) | C (pre-formal STRIX) |
| "STRIX methodology under test" | D | D (formal) and E (complete) |

The decisive comparison in **both** schemes is *STRIX vs the strongest competent baseline*
(α: D vs C; β: {D,E} vs B), never STRIX vs a strawman.

---

## 3. The twelve hypotheses

Each entry: statement (alternative H), null (H₀), primary arms, primary metrics (§30),
ground-truth mechanism, and the falsification criterion (what REJECTS it). All `NOT_EVALUATED`.

### H1 — Dynamic Evidence-Bound Execution Assurance (GAP-001) · RECOVERED
- **H:** An independent execution-time verifier binding each authorization to (a) a versioned
  policy, (b) exact action parameters, and (c) the freshness/validity of the specific supporting
  evidence, consuming each authorization atomically exactly once, blocks a materially larger
  fraction of stale/contradictory/invalid/parameter-tampered actions than arms α-A/B/C, without
  materially raising the valid-action-block rate.
- **H₀:** Arm D's unsafe-execution rate is not lower than min(A,B,C), or any reduction is bought
  only by over-blocking valid actions.
- **Arms:** α (A–D). **Metrics:** unsafe-execution rate, stale-action-block recall,
  false-authorization rate, valid-action-block rate, replay-acceptance rate (target 0).
- **Ground truth:** seeded synthetic action/evidence stream recording true validity at check and
  use time. **Rejects if:** D not strictly below min(A,B,C) beyond margin+CI; or over-block
  exceeds tolerance; or any replay accepted; or any TOCTOU cell executes on check-valid/use-invalid
  evidence.

### H2 — Closed-Loop Execution & Outcome Certification (GAP-002) · RECOVERED
- **H:** A domain-independent decision→action→outcome ledger with correlation ids, independent
  outcome observation, and idempotent retry/duplicate handling attributes outcomes more
  accurately and mis-certifies fewer incomplete outcomes than α-A/B/C, under injected
  retries/partial failures/missing evidence, across ≥2 domains.
- **H₀:** No higher attribution accuracy / no lower mis-certification than best of A/B/C, or works
  in only one domain.
- **Arms:** α. **Metrics:** outcome-attribution accuracy, mis-certification rate,
  duplicate-suppression rate, abstention-correctness-on-outcomes, orphan-detection recall.
- **Ground truth:** seeded simulator recording true linkage + completion out-of-band.
  **Rejects if:** D not strictly above min(A,B,C); or any double-counted/incomplete outcome
  certified complete; or behavior domain-coupled; or C matches D within CI on every metric.

### H3 — Interoperable Heterogeneous Evidence Verification (GAP-003) · RECOVERED
- **H:** A canonical cross-source schema + single reconciliation interface + first-class typed
  abstention detects conflicts and abstains on unresolvable conflicts more accurately than
  α-A/B/C while preserving provenance + requirements traceability end-to-end.
- **H₀:** No higher discrepancy F1 / abstention correctness within CI, or detection gains cost
  broken traceability.
- **Arms:** α. **Metrics:** discrepancy precision/recall/F1, abstention correctness,
  silent-resolution rate (lower better), traceability-preservation rate.
- **Ground truth:** seeded conflict injection over agreeing sources + a human-adjudicated real
  public-fixture subset. **Rejects if:** D's F1 not strictly above min(A,B,C); or silent-resolution
  not strictly lower; or abstention correctness ≤ best conventional; or traceability drops below
  conventional.

### H4 — Unsupported-claim reduction · NEWLY FORMALIZED
- **H:** Full STRIX admission (arm D/E) reduces the unsupported material-claim rate in the
  rendered answer by ≥50% relative to the strongest applicable baseline (β-B).
- **H₀:** Reduction < 50% or CI includes the null after FDR.
- **Arms:** β (A–E). **Metric:** unsupported-claim rate (§30). **Ground truth:** per-item material
  claims labelled against admitted certificates. **Rejects if:** target not met at held-out with
  CI excluding null.

### H5 — Independent claim-verification accuracy · NEWLY FORMALIZED
- **H:** The independent verifier admits correct material claims and rejects fabricated/relabeled
  ones such that material-claim accuracy ≥95% and adversarial fabrication detection is materially
  higher than β-A/B.
- **H₀:** Accuracy < 95% or detection not above baselines within CI.
- **Arms:** β. **Metrics:** material-claim accuracy, adversarial detection rate. **Ground truth:**
  labelled claims + adversarial partition. **Rejects if:** target not met or baselines match within CI.

### H6 — Temporal correctness / zero leakage · NEWLY FORMALIZED
- **H:** Point-in-time admission (predicate T) yields **zero** post-cutoff evidence leakage on the
  point-in-time partition, materially below β-A/B/C.
- **H₀:** Any observed temporal leakage, or leakage not below baselines.
- **Arms:** β. **Metric:** temporal-leakage count (target 0). **Ground truth:** as-of-labelled
  items with post-cutoff distractors. **Rejects if:** any leakage observed for arm D/E.

### H7 — Citation integrity · NEWLY FORMALIZED
- **H:** Every material claim in an authorized answer binds to a genuine attesting citation;
  citation precision ≥95% and required citation coverage = 100% for authorized outputs.
- **H₀:** Precision < 95% or any authorized material claim uncited.
- **Arms:** β. **Metrics:** citation precision, required-citation coverage. **Ground truth:**
  attesting-evidence labels. **Rejects if:** target not met on held-out.

### H8 — Final-synthesis faithfulness · NEWLY FORMALIZED
- **H:** After independent final-answer verification, the synthesized answer introduces **no**
  unsupported assertions — faithfulness = 100% for authorized material claims (arm E).
- **H₀:** Any unsupported assertion survives into an authorized answer.
- **Arms:** β (E vs C/D with validation ablated). **Metric:** post-verification unsupported-sentence
  rate (target 0). **Ground truth:** sentence-level support labels. **Rejects if:** any authorized
  answer carries an unsupported material assertion.

### H9 — Independent numerical verification · NEWLY FORMALIZED
- **H:** Derivation predicate D recomputes each numeric assertion against the native backend
  within its `NumericalContract`; numerical-verification accuracy ≥99%, and model-stated numbers
  that disagree beyond tolerance are rejected.
- **H₀:** Accuracy < 99% or disagreeing numbers admitted.
- **Arms:** β (D/E vs A/B). **Metric:** numerical-verification accuracy. **Ground truth:**
  recomputable numeric items with known answers + tampered-number adversarial items.
  **Rejects if:** target not met or any out-of-tolerance number admitted.

### H10 — Abstention & resource-bounded fail-safety · NEWLY FORMALIZED
- **H:** Treating UNKNOWN → ABSTAIN and resource exhaustion → ABSTAIN improves selective risk
  (abstention correctness) vs β-A/B without reducing useful-answer coverage below 85%.
- **H₀:** No selective-risk improvement, or coverage drops below 85% to achieve it.
- **Arms:** β + exhaustion stress. **Metrics:** abstention correctness, coverage, selective risk.
  **Ground truth:** unanswerable-by-design items + budget-pressure scenarios. **Rejects if:** no
  improvement within CI, or exhaustion ever weakens admission (hard invariant, also unit-tested).

### H11 — Cross-domain generalization · NEWLY FORMALIZED
- **H:** The same STRIX Core verifies across research, finance, federal, and institutional domains
  with no domain-specific verification logic (domain-independence), matching within-domain
  reliability across ≥3 domains.
- **H₀:** Reliability is domain-coupled (materially worse outside the primary domain) or requires
  domain-specific admission logic.
- **Arms:** β across domains. **Metric:** per-domain reliability deltas. **Ground truth:**
  per-domain labelled subsets (federal offline already demonstrates core domain-independence).
  **Rejects if:** materially worse outside primary domain, or hidden domain coupling found.

### H12 — Adaptive assurance + native acceleration · NEWLY FORMALIZED
- **H:** Adaptive assurance (arm E) reduces research cost/latency at matched faithfulness vs
  fixed-budget (arm D) **without ever weakening** a mandatory requirement; native C++/Metal
  backends accelerate designated workloads (≥2× C++, ≥1.5× Metal) with results identical within
  tolerance to the reference.
- **H₀:** No cost/latency gain at matched faithfulness, or adaptation weakens any requirement, or
  acceleration targets unmet / results diverge beyond tolerance.
- **Arms:** β (E vs D) + computational-parity harness. **Metrics:** cost/latency at matched
  faithfulness; speedup; max abs/rel parity error. **Ground truth:** matched-faithfulness
  frontier + reference parity. **Status note:** the C++/Metal speedup portion is
  `EXTERNALLY_BLOCKED` (C++ backend not built; Metal needs a GPU host); the adaptive-vs-fixed
  portion is blocked only on live model budget. **Rejects if:** any safety-floor violation, or
  targets unmet with CI excluding the favorable direction.

---

## 4. Experiment → hypothesis → code map

| Goal §8 experiment | Hypothesis | Harness module (all `OFFLINE_TESTED`) |
|---|---|---|
| Comparative reliability | H4 | `research_eval/{dataset,scoring,analysis,runner}` |
| Claim verification | H5 | `evidence_graph`, `research_eval/scoring` |
| Temporal correctness | H6 | predicate T (`evidence_graph`), `research_eval/scoring` |
| Citation integrity | H7 | `answering/validate`, `agent/citations` |
| Final synthesis faithfulness | H8 | `answering/{synthesize,validate}` |
| Independent numerical verification | H9 | predicate D (`evidence_graph`), `native/*` |
| Authorization | H1 | `assurance/{authorization,gateway,executor,outcome}` |
| Institutional isolation | H11 | `institutional/*` |
| Adversarial evaluations | H5/H6/H9 (adversarial partition) | `research_eval`, per-subsystem suites |
| Cross-domain generalization | H11 | `federal/*`, `finance/*`, `research/*` |
| Adaptive assurance | H12 | `assurance/adaptive` |
| Native C++ / Apple Metal performance | H12 | `native/backends/*`, `native/_c/*` (parity done; C++/Metal blocked) |
| Component ablation (A1–A9) | all | ablation harness `NOT_STARTED` |
| Statistical significance & effect size | all | `research_eval/analysis` (bootstrap/paired/BH) |

## 5. What is required to move any hypothesis off NOT_EVALUATED

1. Build the 120/1200/900-question corpora with independent ground truth (offline-authorable;
   `NOT_STARTED`).
2. Build the ten research baselines + A1–A9 ablation harness (offline-authorable; `NOT_STARTED`).
3. Obtain GPT-6 Luna credentials + an approved budget for the live arms (`EXTERNALLY_BLOCKED`).
4. For H12 acceleration: build the C++ backend (offline-authorable) and obtain a GPU host for
   Metal (`EXTERNALLY_BLOCKED`).

Until 1–4, the honest report is **experimental readiness**, not empirical validation.

---

## 6. Unified-calculus research hypotheses (UC1–UC5) · NEWLY FORMALIZED

The DTEC reorientation (master spec §1.1) adds six research engines composing into a unified
conclusion-level admission calculus. The following hypotheses are **registered separately** and do
**not** overwrite or redefine H1–H12 (which are preserved verbatim). They are stated here at the
**capability level** using neutral terminology; the detailed algorithmic formulations, the internal
methodology designation, and the manuscript cross-references (DH1–DH5) are held in the confidential
research companion (§33 disclosure policy). **All are `NOT_EVALUATED`; every figure is a
pre-registration TARGET, never a measurement.** Arms use the SBIR five-arm scheme (β: A unassured
LLM · B conventional RAG · C pre-formal STRIX · D formal STRIX · E complete STRIX), extended so
arm E includes the unified calculus; strong specialized baselines are added per engine
(source-dependence estimation, temporal reasoning, provenance-aware retrieval, formal inference,
calibration, verification optimization).

| ID | Alternative hypothesis (H) | Null (H₀) | Primary engine | Primary metric (target) | Falsifies if |
|---|---|---|---|---|---|
| **UC1** | Dependency-aware independent-evidence admission reduces unsupported material claims vs duplicate-detection + naive source counting at comparable useful coverage | no reduction beyond baseline within CI | R-N1 | dependency-detection F1 (≥0.90); unsupported-claim reduction (≥50%) | F1 not ≥ strong baseline, or reduction CI includes null after FDR, or coverage collapses |
| **UC2** | Two-axis bitemporal admission reduces incorrect revision selection and future-information leakage vs publication-date filtering | no reduction; or any observed leakage for arm D/E | R-N2 | temporal-selection accuracy (≥0.95); temporal leakage (**0**) | any leakage observed for D/E, or accuracy not above baseline within CI |
| **UC3** | Compositional conclusion admission reduces invalid conclusions vs independent premise checking at equal evidence access | no reduction within CI | R-N3 | conclusion accuracy (≥0.95); certificate coverage (100% of admitted material claims) | accuracy not above independent-premise baseline within CI, or any admitted conclusion lacks required closure/certificate |
| **UC4** | Calibrated selection improves selective risk at matched coverage, and adaptive scheduling improves verified yield at matched budget — **without ever weakening a mandatory predicate** | no selective-risk or yield improvement; or any mandatory weakening | R-N4, R-N5 | ECE (≤0.05, label-gated); abstention recall (≥0.90); verified yield at equal budget | no improvement within CI, or any exhaustion/confidence path weakens a mandatory predicate (hard invariant, also unit-tested) |
| **UC5** | The integrated calculus improves reliability beyond isolated components (positive interaction `Δ_ij`) while preserving institutional isolation in the registered threat model | no interaction benefit beyond components; or any unauthorized disclosure | unified + R-N6 | composition vs best single-engine; unauthorized disclosures (**0 observed**) | integration ≤ best component within CI, or any unauthorized disclosure in the registered threat model |

**Ground truth & method (shared):** offline synthetic corpora with independent ground truth
(dependency / temporal / calculus / calibration / institutional benchmarks), paired comparisons,
cluster bootstrap 95% CIs, risk-coverage analysis, Benjamini–Hochberg FDR, dependency-aware
dataset partitioning (no leakage across related evidence origins / revision families / institutional
environments), engine ablations `Δ_i = M(F) − M(F₋ᵢ)` and interactions `Δ_ij`. Live arms remain
`EXTERNALLY_BLOCKED` (GPT-6 Luna credentials + budget, blocker B-LIVE) → until then the honest
report is **experimental readiness**, not validation. Negative findings are preserved.

**Mapping to the preserved registry (reconcile, don't replace):** UC1↔H4 (unsupported-claim
reduction) + H5; UC2↔H6 (temporal/leakage); UC3↔H7/H8/H9 (citation/synthesis/numerical) at the
conclusion level; UC4↔H10 (abstention) + H12 (adaptive/native); UC5↔H11 (cross-domain) + the
composition thesis. The UC hypotheses are the conclusion-level and dependency/temporal/institutional
extensions of the claim-level H-series; both schemes are retained.
