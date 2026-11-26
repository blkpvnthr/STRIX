# STRIX Research Experiments

Pre-registration-first experiment workspace for the unified-calculus research program
(master spec §1.1, §28–§30; hypotheses H1–H12 + UC1–UC5). **Discipline:** corpus splits,
baselines, ablations, metrics, and thresholds are frozen (content-addressed) **before** any sealed
held-out partition is opened (CLAUDE.md Principle 3). **Every figure produced here is a measurement
reported with its confidence interval and limitations — targets are never reported as outcomes.**
Negative findings and rejected formulations are preserved.

| Directory | Contents |
|---|---|
| `preregistration/` | Frozen pre-registration manifests (content-addressed): hypotheses, arms, metrics, thresholds, splits, seeds — sealed before evaluation. |
| `datasets/` | Offline **synthetic** corpora + independent ground truth (dependency / temporal / calculus / calibration / institutional benchmarks). No live/PII data. Dependency-aware partitioning prevents leakage across related origins / revision families / institutions. |
| `baselines/` | Strong comparative baselines (A–E arms + specialized per-engine baselines: source-dependence estimation, temporal reasoning, provenance-aware retrieval, formal inference, calibration, verification optimization). |
| `ablations/` | Engine ablation configurations `Δ_i = M(F) − M(F₋ᵢ)` and interaction `Δ_ij`, restricted to isolated experimental environments (never releasing unassured output as governed). |
| `results/` | Raw + aggregated experimental outputs with CIs. Live arms are `EXTERNALLY_BLOCKED` (B-LIVE) → report **readiness**, not validation, until credentials + budget exist. |
| `negative-findings/` | Preserved refutations, rejected formulations, and failed hypotheses — first-class scientific output. |
| `reproducibility/` | Manifests, seeds, configs, model versions, source snapshots needed to reproduce any reported result. |

Harness: `src/strix/research_eval/{dataset,scoring,analysis,runner}` (OFFLINE_TESTED) + the
engine benchmarks + ablation runner added under workstream **WS-EV**. Statistics: paired
(McNemar/Wilcoxon), cluster bootstrap 95% CIs, Benjamini–Hochberg FDR, risk-coverage, stratified
reporting, synthetic-vs-genuine separation.
