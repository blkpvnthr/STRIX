# Neuro-symbolic platform

!!! warning "Phase 1 of 16 — architecture record only"
    This page records the baseline architecture and the target design for
    turning STRIX into a scholarly-document-grounded neuro-symbolic research
    platform. As of this page's last update, only this record and the
    `mkdocs.yml`/navigation fixes it required exist. No `strix.corpus`,
    `strix.inference`, or `strix.research` code has been written yet.

## Governing principle

> ML and LLM components may propose. Deterministic code calculates,
> verifies, enforces policy, and controls publication.

Every phase below is designed so a non-deterministic component (statistical
model, ML model, or LLM) can only ever *propose* — the same rule the
existing [deterministic boundary](../deterministic-boundary.md) and
[LLM boundary](../llm-boundary.md) already enforce for the financial
vertical's reasoner seam.

## Current architecture (baseline)

STRIX today is three independent verticals sharing a small set of
primitives — not yet a unified research platform:

| Vertical | Modules | Claim/output types | Reasoning |
|---|---|---|---|
| Financial | `strix.models`, `strix.pipeline`, `strix.verification`, `strix.reasoning` | one claim type (`profitability_change`) | `DeterministicDemoReasoner` — fixed Python, not an LLM |
| Engineering | `strix.engineering.*` | candidate elements/relationships from requirements/CSV/XML/ReqIF | deterministic builder + verifier with quarantine semantics |
| Market research | `strix.market.*`, `strix.service` | hypotheses/experiment results | deterministic feature/hypothesis engine; not wired into any Evidence/Claim/Verifier chain |

Shared across all three, and reused unchanged by the new work below:

- `strix.canonical` — float-free canonical JSON and SHA-256 content-derived
  IDs (`make_id`, `canonical_hash`).
- `strix.run_store` — atomic staging-directory commit, crash-safe, replay-safe.
- `strix.errors` — typed exception hierarchy with machine-readable codes.

Nothing else is shared; each vertical has its own model namespace. There is
no LLM call anywhere in the codebase today, no document corpus, and no
retrieval of any kind.

## Target architecture: the scholarly-research vertical

A **fourth vertical** adds the pieces STRIX has never had, as a new package
set that reuses the three shared primitives above exactly as the other
verticals do. It does not retrofit the financial, engineering, or market
pipelines — they have no document corpus and no reasoning gap to fill.

```
src/strix/
  corpus/          # acquisition, parsing, corpus/anchor models, scanning, snapshots
  inference/       # provider-neutral LLM proposal layer: schemas, fake/stored/router, policy
  research/        # typed request model, retrieval, prepare()/propose()/finalize(), verification
```

### Evidence root

`STRIX_EVIDENCE_ROOT` (same override precedence pattern as
`STRIX_STATE_DIR`/`resolve_state_dir`) defaults to
`/Users/blkpvnthr/STRIX/docs`, structured as:

```
docs/
  acquired/   # written only by the acquisition subsystem
  imported/   # user-supplied documents
```

`docs/` is never mutated or deleted by STRIX code. Only the acquisition
subsystem writes to `docs/acquired/`. Generated indexes, chunks, manifests,
reports, and run artifacts live outside `docs/`; every analyzed corpus is
snapshotted immutably, and replay reads the snapshot, never the live
directory.

### Workflow

```
Research request
  -> search plan -> scholarly source discovery -> candidate review
  -> authorized download into docs/acquired/
  -> recursive corpus scan -> immutable preservation and hashing
  -> deterministic parsing -> anchored chunks and records
  -> reproducible retrieval -> statistical/ML analysis
  -> structured LLM proposals -> deterministic verification
  -> cited report -> interactive follow-up
```

### `prepare()` / `propose()` / `finalize()`

```
prepare()   preserved inputs -> facts -> calculations/ML results -> evidence   (deterministic)
propose()   curated evidence -> deterministic proposer or LLM -> recorded proposals
finalize()  evidence + recorded proposals -> deterministic verification -> report (deterministic)
```

`propose()` is the only non-deterministic seam. Replay always loads the
recorded proposal set from the run directory instead of invoking a model; a
separate *regeneration* operation may repeat inference and report drift
without altering the original run.

### Verification outcomes

Every finding is classified as one of: `VERIFIED`, `SUPPORTED`,
`CONFLICTING`, `INSUFFICIENT_EVIDENCE`, `REJECTED`,
`REQUIRES_HUMAN_REVIEW`. A citation proves provenance, not truth; conflicting
sources are surfaced explicitly and never silently resolved to a preferred
source.

## Phase plan

1. **Baseline + architecture record** — this page; `mkdocs.yml` repointed at
   `architecture/` as the docs source now that `docs/` is reserved for
   evidence.
2. **Safe recursive scanning of `docs/`** — stable ordering, traversal/
   symlink rejection, no mutation; reports discovery, containment, file-type,
   and readability failures (malformed-*content* classification is deferred
   to the parser phase, since that requires actually parsing the file).
3. **Corpus manifests and immutable snapshots** — content-derived corpus ID
   from the ordered document inventory; replay reads the snapshot.
4. **Search and acquisition contracts** — provider-neutral `SearchConnector`,
   `SearchPlan`/`SearchResult` models, fake connector only (no live network).
5. **Secure download** — SSRF-safe destination policy, redirect/size/time
   limits, MIME/signature validation, deterministic filenames into
   `docs/acquired/`; tested with `httpx.MockTransport` (no real sockets, no
   local fixture server — the test suite's network guard blocks sockets
   outright).
6. **Parser registry and source anchors** — TXT/Markdown first; a format is
   not claimed as supported until fixtures and tests exist for it.
7. **Corpus versioning and rescans** — diff against the prior snapshot;
   report which documents are new/modified/removed and how findings changed.
8. **Typed research requests and deterministic retrieval** — budgeted
   request model; lexical retrieval only, to start.
9. **`prepare()`/`propose()`/`finalize()` refactor** for this vertical.
10. **Fake and stored inference providers** — still no live LLM calls.
11. **Verification and replay** for the new vertical's claims/findings.
12. **Market, engineering, and ML integration** — shared `fit()/predict()/
    explain()/evaluate()` contracts the existing market engine can implement
    without rewriting its own verified logic.
13. **Interactive sessions and decision policy.**
14. **Evaluation harness and security hardening.**
15. **GPT-6.1 Sol integration checkpoint** — design review and the sponsor's
    checklist answered in writing; no credentials requested, no API call
    made.
16. **Live integration** — only after explicit approval following phase 15.

Each phase is implemented, tested (`pytest`, `ruff format --check`,
`ruff check`, `mypy`, plus phase-specific offline tests), and reported
(files changed, behavior added, tests run, limitations, next step, required
approvals) before the next phase begins. No phase makes a live search,
download, or LLM call without separate, explicit approval.
