# STRIX — Phase 9 consolidation & Ubuntu synchronization runbook

**Prepared:** 2026-11-26 · **Branch:** `feature/sbir-phase-i-evidence-intelligence` @ `7b24aa5`
· **origin/main / local main:** `5d8720f` (clean fast-forward, 22 ahead, 0 behind).

> **Why this runbook exists.** The validation, security/disclosure audit, and reconciliation
> (goal Steps 1–3) are **complete and green** locally. The push / PR / merge / Ubuntu-sync
> actions (Steps 4–9) are **blocked by this environment's command classifier** — `git push`,
> the `gh` CLI, and SSH are all denied here, independent of the B-PUSH authorization. Run the
> commands below (or grant the corresponding Bash permission rules) to finish the sequence.

## Pre-flight status (reproduced locally)

| Gate | Result |
|---|---|
| Python regression (`pytest`) | **2466 passed, 2 skipped, 2 xfailed, 0 regressions** |
| `ruff check src/ tests/` | clean |
| `mypy --strict src/strix` | clean (258 source files) |
| DTEC demonstrations | **13/13 demonstrate** |
| Frontend `vitest` | 15 passed (4 files) |
| Frontend `tsc --noEmit` | clean |
| Frontend `vite build` | ✓ built (dist generated) |
| Security/disclosure audit | **CLEAN** — no secrets/keys/tokens (only env-var refs + labeled `unit-test-secret` fixtures); no confidential research docs (git-ignored, none in diff); no binaries/artifacts; `.gitignore` strengthens `_confidential/` protection |
| Divergence from origin/main | 22 ahead, **0 behind** → clean fast-forward, no conflicts |

## Step 0 — SAFETY GATE (do this first)

Confirm the repository is **private** before pushing (B-VIS remains active). Could not be verified
here (`gh` denied):

```bash
gh repo view blkpvnthr/STRIX --json isPrivate -q .isPrivate   # must print: true
```

If it prints `false`, **STOP** — do not push; the branch carries the "DTEC"-branded research
docs (`research/execution-state.md`, `research/experiments/results/dtec-*.md`) and commit
messages. (The genuinely confidential suite in `research/dtec/_confidential/` is git-ignored and
will NOT be pushed regardless.)

## Steps 4–5 — push, PR, merge

```bash
cd /Users/blkpvnthr/STRIX
git push origin feature/sbir-phase-i-evidence-intelligence

gh pr create \
  --repo blkpvnthr/STRIX --base main --head feature/sbir-phase-i-evidence-intelligence \
  --title "STRIX — DTEC Mathematical Foundation, Governed Research Integration, and Phase I Feasibility Readiness" \
  --body-file docs/phase-9-consolidation-pr-body.md

# After required checks pass + required human approval (respect branch protection):
gh pr merge --repo blkpvnthr/STRIX feature/sbir-phase-i-evidence-intelligence --merge
#   (use --squash or --rebase per repo policy; do NOT bypass failed/required checks)
```

Record: PR number + URL, feature SHA (`7b24aa5` unless advanced), merge commit SHA.

## Step 6 — local main sync (fast-forward only)

```bash
cd /Users/blkpvnthr/STRIX
git checkout main
git pull --ff-only origin main
git rev-parse main    # must equal origin/main after merge
git checkout feature/sbir-phase-i-evidence-intelligence   # restore working branch
# Re-run gates against merged main:
python -m pytest tests/ -o addopts="" -q && ruff check src/ tests/ && mypy --strict src/strix
```

## Steps 7–9 — OCI Ubuntu synchronization

```bash
ssh ubuntu@strix-vnic
cd /opt/strix/app
# --- pre-update capture (rollback point) ---
git rev-parse HEAD | tee /tmp/strix-rollback-commit.txt   # RECORD THIS
git status --short                                        # must be clean; stash/commit server changes first
systemctl --user status strix 2>/dev/null || systemctl status strix 2>/dev/null   # inspect service
# --- fetch + fast-forward only (never reset the working tree) ---
git fetch origin
git log --oneline HEAD..origin/main | head              # review incoming
git merge --ff-only origin/main
git rev-parse HEAD                                       # must equal GitHub origin/main SHA
# --- runtime deps (reuse existing venv if compatible) ---
source .venv/bin/activate        # or the venv path in use
pip install -e '.[dev,formal]'   # match pyproject optional groups actually declared
# --- import / smoke validation (no paid live calls) ---
python -c "import strix; from strix.agent.orchestrator import run_research_question; \
from strix.evidence_graph.unified import admit_dtec; \
from strix.research_eval.dtec_demonstrations import run_demonstrations as r; \
print('demos:', all(d.demonstrates for d in r().demonstrations))"
python -m pytest tests/ -o addopts="" -q               # deterministic offline suite
ruff check src/ tests/ && mypy --strict src/strix
# --- service restart only if required (drain in-flight work first) ---
# systemctl --user restart strix ; journalctl --user -u strix -n 50
```

Confirm **GitHub origin/main SHA == local main SHA == Ubuntu main SHA**.

**Linux note:** Apple Metal is unavailable on Ubuntu — the native layer must use the CPU
reference backend. Do **not** report GPU acceleration on Ubuntu (B2/Metal remains blocked).

## Step 10 — Phase 10 baseline (after sync verified)

```bash
cd /Users/blkpvnthr/STRIX && git checkout main && git pull --ff-only origin main
git checkout -b feature/phase-10-governed-frontend-preview
```

## Rollback

- **Local/Ubuntu:** `git merge --ff-only` only advances; to revert Ubuntu: `git reset --hard <rollback-commit from /tmp/strix-rollback-commit.txt>` (only if no server-local commits).
- **main (if a bad merge landed):** `git revert -m 1 <merge-sha>` via a new PR (never force-push main).
- The feature branch is preserved until sync is verified (do not delete it before then).

## Active external blockers (unchanged)

B-VIS (repo-visibility confirmation), B-PATENT (counsel), B-DEMO (demo repo), B-LIVE
(credentials + budget for live H1–H12). Plus: this environment's classifier blocks
`git push`/`gh`/`ssh` — grant Bash permission rules or run the above manually.
