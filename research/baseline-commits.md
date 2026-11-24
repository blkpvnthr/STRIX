# Milestone R1 — Pinned Baselines & Baseline Test Result

**Milestone:** R1 — Resource-Bounded Typed Evidence Verification for Trustworthy Autonomous AI
**Work branch:** `research/formal-evidence-verification` (cut from `feat/milestone-0b`)
**Date pinned:** 2026-11-24

## Pinned repository baselines

| Repository | Path | Baseline commit | Branch at pin |
|---|---|---|---|
| STRIX (primary) | `/Users/blkpvnthr/STRIX` | `849018d` | `feat/milestone-0b` |
| C-engine (extraction source) | `/Users/blkpvnthr/C-engine` | `3a23b13` | `feature/m9-runtime-microstructure-execution-learning` |

- STRIX `849018d` = *"docs(research): Milestone 0B — audit remediation + research requirements baseline"*.
- C-engine is read-only for this milestone (do not modify; extract general-purpose numerics only).

## Toolchain at baseline

| Component | Version |
|---|---|
| Python | 3.11.8 (`.venv`) |
| pytest | 9.1.1 |
| pydantic | 2.13.4 |
| fastapi | 0.165.0 |
| duckdb | 2.0.1 |
| openai | 3.57.0 |

Packaging: `hatchling`; package `strix` v`0.3.0.dev0`; entry points `strix`, `strix-service`, `strix-demo-fixture`, `strix-agent-diagnostics`.

## Baseline test suite (pre-change)

Command: `python -m pytest -q` (from repo root, in `.venv`).

**Result: 866 tests → 862 passed, 2 skipped, 2 xfailed, 0 failed, 0 errors. Exit code 0.**

Counts derived from the per-test progress stream (862 `.` + 2 `s` + 2 `x` = 866); the condensed summary line was lost to carriage-return overwrite in the redirected log, but the outcome characters are unambiguous. This is the regression gate: R1 changes must preserve **≥ 862 passed with 0 new failures**.

> This file records reproducibility anchors only. Audit findings live in `repository-baseline-audit.md`, `cengine-extraction-audit.md`, and `intellectual-property-inventory.md`.
