# Provenance

Provenance is the property that lets you take any number in a STRIX report and
walk it, step by step, back to the exact bytes STRIX read — with a
cryptographic hash confirming those bytes have not changed. This page traces
that path end to end and shows how to audit it by hand from the real
`RUN-20260809-001` artifacts.

## Raw bytes are preserved verbatim

When a run acquires source data, the exact bytes are copied into `raw/` inside
the run directory and their SHA-256 is recorded in the manifest. The demo run
preserves the bundled fixture; an EDGAR run preserves the fetched
`companyfacts` JSON. Parsing always happens **from the preserved bytes**, so
the same run replays offline and byte-identically.

The copy is not trusted blindly. `RunStore._preserve_raw`
(`src/strix/run_store.py`) re-reads the file it just wrote and re-hashes it:

```python
original_hash = sha256_hex(raw_bytes)
target = raw_dir / sanitize_artifact_name(raw_name)
self._write_atomic(target, raw_bytes)
preserved_hash = sha256_hex(target.read_bytes())
if preserved_hash != original_hash:
    raise RunStoreError(...)   # the run is aborted, nothing is committed
```

The manifest then records that hash under `source_hashes`:

```json
"source_hashes": {
  "demo-company-facts.json": "1c7cf5bba8aaa5bb9111fea1941ae53b79eb11de54e668315e450d4c70aaade7"
},
"source_name": "demo-company-facts.json",
"source_type": "synthetic_fixture"
```

For the AAPL run the same fields name the preserved EDGAR response:

```json
"source_hashes": {
  "companyfacts-CIK0000320193.json": "73a86c6aedc31f77cac2ea4df5f80f0b3bd7e6eb58bb4e01444fbedf3afb9c43"
},
"source_name": "companyfacts-CIK0000320193.json",
"source_type": "sec_edgar_companyfacts"
```

## Every fact carries a `source_locator`

A `SourceFact` is not just a value — it records **where inside the raw
artifact** the value came from, as a JSON pointer in `source_locator`. That
pointer is part of the fact's hashed identity (it feeds the `FACT-` id), so the
locator cannot drift from the value without changing the id.

### Demo fixture locators

The fixture is a small hand-authored JSON document, so its locators point at
array positions inside `periods`. From the ground-truth `facts.json`:

| Fact | `value` | `source_locator` |
| --- | --- | --- |
| `FACT-fde4b197a83c` revenue 2025-Q2 | `1000000000` | `/periods/0/facts/0` |
| `FACT-59fc3cdc0b33` operating_income 2025-Q2 | `84000000` | `/periods/0/facts/1` |
| `FACT-984d1189dc7a` revenue 2026-Q2 | `1000000000` | `/periods/1/facts/0` |
| `FACT-9cff5a7d197e` operating_income 2026-Q2 | `101000000` | `/periods/1/facts/1` |

Following `/periods/0/facts/1` into the preserved `raw/demo-company-facts.json`
lands exactly on the `84000000` operating-income entry.

### EDGAR locators

For SEC EDGAR sources the locator points into the XBRL `companyfacts`
structure. `parse_companyfacts` (`src/strix/sources/edgar.py`) builds each
locator as:

```
/facts/us-gaap/<tag>/units/USD/<index>
```

where `<tag>` is the us-gaap concept tag and `<index>` is the position in that
tag's `units.USD` array. Revenue is drawn from the first matching tag in a
fixed priority order, and both compared quarters must use the *same* revenue
tag (a comparability rule):

```
RevenueFromContractWithCustomerExcludingAssessedTax
Revenues
SalesRevenueNet
RevenueFromContractWithCustomerIncludingAssessedTax
```

Operating income always uses `OperatingIncomeLoss`. For the AAPL run the
manifest's `source_version` records which revenue tag won and the filing
horizon:

```
RevenueFromContractWithCustomerExcludingAssessedTax@filed-through-2026-07-31
```

so that run's revenue locators are of the form
`/facts/us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax/units/USD/<index>`
and its operating-income locators are
`/facts/us-gaap/OperatingIncomeLoss/units/USD/<index>`.

## The point-in-time model

STRIX answers *"what was knowable as of a date"*, not *"what do we know now"*.
Two dates govern this:

- **`as_of_date`** — the research cut-off, taken from the spec.
- **`known_at`** — when each fact became knowable.

For EDGAR, `known_at` is the fact's SEC `filed` date (at UTC midnight, via
`_utc`). Only facts with `filed <= as_of_date` are considered
(`_quarterly_facts` skips anything filed later). Any evidence that would rest on
a fact knowable only after the as-of date is rejected downstream with
`evidence_after_as_of`.

### Earliest-filed-wins on restatements

Companies restate. When several filings report the same fiscal quarter (same
exact period **end** date), STRIX keeps the **earliest-filed** value — the
number the market first learned — and lets later restatements be ignored for
that quarter:

```python
# earliest filed wins; the numeric array index breaks same-day ties
if existing is None or (candidate.filed, candidate.index) < (existing.filed, existing.index):
    best[end] = candidate
```

This is a deliberate epistemic choice: point-in-time research should reflect the
information set that existed at the as-of date, not a later, revised view. The
array index is used only to break exact same-day filing ties, in favor of the
earlier entry.

### Quarter identification and YoY pairing

Quarters are identified by their **exact period end date**, not by a calendar
label, so two distinct fiscal quarters that happen to share a `YYYY-QN` label
stay distinct. A value counts as a quarter only if its duration is 80–100 days.
The comparison pair is the latest available quarter and the quarter ending
350–378 days earlier (target 364 = 52 weeks), which pairs off-calendar and
52/53-week fiscal years correctly. The `YYYY-QN` label shown to users is derived
from the end date's calendar quarter and is **display naming only**.

## Auditing a finding by hand

Suppose the demo report says:

```
Finding:
  Operating margin increased from 8.4% to 10.1%, an improvement of 1.7
  percentage points.
  Evidence: EV-9d33ded8a427, EV-649d8a693225, EV-d1e9faaf6787
```

You can verify every number without trusting STRIX, using only the files in
`research_runs/RUN-20260809-001/`.

**Step 1 — from the report to a claim.** The report cites three evidence ids.
Open `claims.json`; the single claim `CL-03d483aef9c0` cites exactly those ids
and asserts `0.084`, `0.101`, and `1.7`.

**Step 2 — from claim assertions to evidence.** Each `numeric_assertion` names
an `evidence_id`. Open `evidence.json` and confirm the asserted values match:
`EV-9d33ded8a427` holds `value: "0.084"` (`display_value: "8.4%"`),
`EV-649d8a693225` holds `0.101` (`10.1%`), `EV-d1e9faaf6787` holds `1.7`
(`1.7 percentage points`).

**Step 3 — from evidence to calculations.** Each evidence record names a
`calculation_id` and lists `source_fact_ids`. `EV-9d33ded8a427` points to
`CALC-cf3c3f6a4f26`. Open `calculations.json`: that calculation is
`operating_margin`, `value: "0.084"`, `unit: "ratio"`, built from
`input_fact_ids: ["FACT-59fc3cdc0b33", "FACT-fde4b197a83c"]`.

**Step 4 — from calculations to source facts.** Open `facts.json` and read
those two facts: operating income `84000000` and revenue `1000000000` for
`2025-Q2`. Confirm the arithmetic yourself: `84000000 / 1000000000 = 0.084`.

**Step 5 — from facts to raw bytes.** Each fact carries a `source_locator` and a
`source_artifact_id`. Follow `FACT-59fc3cdc0b33`'s locator `/periods/0/facts/1`
into `raw/demo-company-facts.json` and read `"value": "84000000"` at exactly
that position.

**Step 6 — confirm the bytes are original.** Hash the preserved file and
compare it to the manifest:

```console
$ shasum -a 256 research_runs/RUN-20260809-001/raw/demo-company-facts.json
1c7cf5bba8aaa5bb9111fea1941ae53b79eb11de54e668315e450d4c70aaade7  ...
```

That digest equals `source_hashes["demo-company-facts.json"]` in
`manifest.json`. The raw bytes are exactly what STRIX read.

**Step 7 — let STRIX recompute the whole chain for you.** `strix replay
RUN-20260809-001` re-runs the deterministic pipeline over those raw bytes and
compares every stage hash to the manifest. See
[Replaying a run](usage/replay.md) for the full walkthrough; the storage and
integrity mechanics are in [Storage](storage.md).

## The agent (conversational) evidence path

The walkthrough above traces the **v1 core pipeline** (`RUN-20260809-001`). The
conversational agent subsystem collects evidence differently — from live web and
data sources rather than a single bundled fixture — but rests on the same
hash-anchored identity and atomic-persistence foundations.

### Evidence collection and content-addressed identity

`EvidenceCollector.register` (`src/strix/agent/evidence_collector.py`) takes the
raw bytes of a source, computes their SHA-256 (`content_hash = sha256_hex(raw)`),
and derives the evidence id from that hash via
`AgentEvidence.make_id(content_hash, source_url, anchor)`
(`src/strix/agent/models.py`). Identical sources therefore deduplicate: if the
derived id already exists, the existing record is returned unchanged. Raw bytes
are kept in an **in-memory** artifact store keyed by content hash
(`artifact_path = "artifacts/<content_hash>.bin"`) until the run is persisted.

Derived numeric series are bound to their source: `add_series` requires a
`source_evidence_id` that is already registered and raises `KeyError` otherwise,
so a series can never cite evidence that was never preserved.

Content-derived ids across the agent models use the same construction as the rest
of STRIX — `canonical.make_id(prefix, payload)` (`src/strix/canonical.py`) hashes
a canonical JSON payload to `PREFIX-<sha256[:12]>`.

### Citation handles vs canonical evidence identity

The hosted web-search tool hands the model provider-native citation handles, not
STRIX evidence ids. `resolve_claim_citations` (`src/strix/agent/citations.py`)
rewrites each claim's `evidence_ids` to canonical, resolvable ids: a known handle
or URL is mapped to the evidence id the collector preserved, and an
**unresolvable handle is dropped and recorded** (never surfaced as if it were
verified). The mapping is established by `EvidenceCollector.register_alias`
(`src/strix/agent/evidence_collector.py`), which is **first-writer-wins** and
never shadows a real evidence id — it is a no-op when the alias is empty, when the
target evidence is unknown, or when the alias string collides with an existing
evidence id. A stable citation marker therefore never flips to a different source
mid-run.

### Source artifacts and persistence

Agent runs are written through the same atomic machinery as core runs.
`src/strix/agent/persistence.py` assembles the manifest, claims, evidence, and
preserved raw artifacts and commits them via `src/strix/run_store.py`, which
writes each file with a temp-file + `fsync` + `os.replace` sequence
(`_write_atomic`) and commits the staging directory with a single atomic rename.
Preserved raw bytes are re-read and their SHA-256 **re-verified** against the
original before the run is committed (`RunStore._preserve_raw`); a mismatch aborts
the run and nothing is committed.

### What agent replay does — and does not — prove

`src/strix/agent/replay.py` re-opens a persisted agent run and **re-runs the
independent verifier** over the recorded claims (`verify_claims`), then checks
three integrity properties: that preserved artifact hashes still match, that
citations still resolve, and that epistemic classifications have not collapsed
into verdicts (`hash_matches`, `citation_integrity`, `classification_integrity`).

Two limits are deliberate:

- Replay does **not** regenerate the model's stochastic wording. It proves the
  numbers, citations, and classifications hold — not that the exact prose
  reappears.
- Replay recomputes using the **current** code plus the **recorded version
  strings** from the manifest (`verifier_version`, `calculation_version`,
  `agent_version`, and so on, written by `persistence.py`). It therefore detects
  tampering, nondeterminism, and contract drift — but it is **not** an
  adversarial, independent re-implementation of the pipeline.

## What provenance does and does not establish

- It **does** establish that each reported number was computed from a specific
  location in specific, unmodified source bytes, and that the same computation
  reproduces the same result.
- It **does** establish, for EDGAR, which filing (by `filed` date) each figure
  came from and that only information knowable by the as-of date was used.

!!! warning "Provenance is not veracity"
    A complete, hash-verified provenance chain proves faithful traceability from
    report to source. It does **not** prove the source was truthful, complete,
    or free of error. STRIX preserves and reproduces what the source said; it
    does not audit the source itself.

!!! warning "Hashes are unsigned — integrity, not identity attestation"
    STRIX run manifests record **unsigned** SHA-256 content hashes. They
    establish *reproducibility and integrity from the preserved bytes* — that the
    bytes STRIX read have not changed and recompute to the same result. They do
    **not** constitute a cryptographic attestation of authorship or identity.
    There is no digital signature, trust root, external timestamp authority, or
    keyed MAC (HMAC/ed25519/etc.) anywhere in the pipeline at this commit — a
    party who can rewrite both the raw bytes and the recorded manifest hash can
    produce a self-consistent run. Hash verification proves the archive is
    internally consistent, not that it originated from a particular source or
    signer.

!!! warning "Synthetic data / not investment advice"
    "Demonstration Company" (DEMO) is fictional and its figures are synthetic.
    EDGAR output reflects filings as reported, is a research prototype result,
    and is not investment advice.
