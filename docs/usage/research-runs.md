# Research runs

Every confirmed research request produces one **run**: a self-contained,
atomically-written directory holding the research spec, the preserved raw
source bytes, every intermediate artifact of the lineage, the verification
result, a human-readable report, and an integrity manifest. A run captures
everything needed to reproduce and audit its finding offline.

## What a run is

A run is one execution of the deterministic pipeline over a single source
document. It is the unit of persistence, the unit of [replay](replay.md), and
the smallest thing you can cite. The pipeline core is a pure function of the
research spec and the preserved raw bytes, so a run's artifacts are fully
determined by its inputs.

## Run IDs

Run IDs have the form `RUN-YYYYMMDD-NNN` — for example `RUN-20260809-001`. The
date is the run's creation date and `NNN` is a zero-padded per-day sequence
number starting at `001`.

!!! note "Run IDs identify an execution, not content"
    A run ID names *when* a run happened, not *what* it contains. It is not
    derived from the run's content. Content identity lives in the
    content-derived IDs inside the run (`ART-`, `FACT-`, `CALC-`, `EV-`, `CL-`,
    each a 12-hex-character prefix of a SHA-256 over canonical JSON) and in the
    manifest's per-stage hashes. Two runs over the same input produce identical
    content IDs and stage hashes but different run IDs.

The ID pattern is validated ASCII-only. A completed `RUN-*` directory is never
overwritten: if the chosen sequence number is already taken, the next number
is used.

## Where runs live

Runs are written under the **state directory**, resolved with this precedence:

1. the `--state-dir PATH` flag,
2. the `STRIX_STATE_DIR` environment variable,
3. the default `./research_runs` (relative to the working directory).

The default `research_runs/` directory is gitignored. To keep runs elsewhere:

```bash
strix --state-dir /data/strix-runs      # this run and its replays
export STRIX_STATE_DIR=/data/strix-runs # every command in the shell
```

Replay reads from the same location, so pass the matching `--state-dir` (or set
the same environment variable) when replaying a run stored outside the default.
See [Configuration](../getting-started/configuration.md) and
[Environment variables](../reference/environment-variables.md).

## Run directory contents

A completed run directory contains the following. The raw source lives under
`raw/`; everything else is at the top level:

```text
RUN-20260809-001
RUN-20260809-001/calculations.json
RUN-20260809-001/claims.json
RUN-20260809-001/evidence.json
RUN-20260809-001/facts.json
RUN-20260809-001/manifest.json
RUN-20260809-001/raw
RUN-20260809-001/raw/demo-company-facts.json
RUN-20260809-001/report.txt
RUN-20260809-001/spec.json
RUN-20260809-001/verification.json
```

| File | Contents |
| --- | --- |
| `spec.json` | The validated `ResearchSpec` — the exact request that was run. |
| `raw/<source file>` | The preserved raw source bytes, byte-for-byte. For DEMO this is `demo-company-facts.json`; for EDGAR it is `companyfacts-CIK##########.json`. |
| `facts.json` | The `SourceFact` records extracted from the source. |
| `calculations.json` | The `CalculationResult` records (operating margins and the change). |
| `evidence.json` | The `Evidence` records — citable, typed results carrying full lineage. |
| `claims.json` | The `Claim` records the reasoner produced, with their verified status. |
| `verification.json` | The `VerificationResult` — pass/fail, verified and rejected claim IDs, and any failures. |
| `report.txt` | The human-readable report (title, run ID, finding, evidence IDs, disclaimer). |
| `manifest.json` | The integrity record: source identity, per-stage hashes, and final status. |

!!! note "Atomic writes"
    A run is assembled in a hidden `.staging-*` directory inside the state
    directory and committed with a single rename. `manifest.json` is always
    written last. A visible `RUN-*` directory therefore always contains a
    complete run; a crash leaves only an ignorable hidden staging directory.

## Reading a run end to end

The finding cites evidence IDs. You can follow any one of them down the full
lineage — `Evidence → Calculation → Source facts → raw source` — using the IDs
recorded in the artifacts. The example below traces the first evidence ID from
the DEMO run's finding.

The finding was:

```text
Operating margin increased from 8.4% to 10.1%, an
improvement of 1.7 percentage points.
[EV-9d33ded8a427, EV-649d8a693225, EV-d1e9faaf6787]
```

### Step 1 — evidence

Open `evidence.json` and find `EV-9d33ded8a427`:

```json
{
  "calculation_id": "CALC-cf3c3f6a4f26",
  "display_value": "8.4%",
  "evidence_id": "EV-9d33ded8a427",
  "evidence_type": "calculation",
  "known_at": "2025-07-15T00:00:00+00:00",
  "metric": "operating_margin",
  "observation_period": "2025-Q2",
  "source_fact_ids": [
    "FACT-59fc3cdc0b33",
    "FACT-fde4b197a83c"
  ],
  "status": "verified",
  "subject_id": "demo-company-000001",
  "unit": "ratio",
  "value": "0.084"
}
```

This evidence is the 2025-Q2 operating margin, `0.084` (displayed `8.4%`). It
points to one calculation and two source facts. Its `display_value` is
presentation-only and is excluded from the hashes — the authoritative number is
`value`.

### Step 2 — calculation

Follow `calculation_id` into `calculations.json`, entry `CALC-cf3c3f6a4f26`:

```json
{
  "calculation_id": "CALC-cf3c3f6a4f26",
  "calculation_name": "operating_margin",
  "calculation_version": "1.0.0",
  "input_calculation_ids": [],
  "input_fact_ids": [
    "FACT-59fc3cdc0b33",
    "FACT-fde4b197a83c"
  ],
  "observation_period": "2025-Q2",
  "subject_id": "demo-company-000001",
  "unit": "ratio",
  "value": "0.084"
}
```

Operating margin is `operating_income / revenue`. Its `input_fact_ids` are
role-ordered: `[numerator, denominator]` — the operating-income fact first,
then the revenue fact.

### Step 3 — source facts

Follow the fact IDs into `facts.json`. `FACT-59fc3cdc0b33` is the numerator:

```json
{
  "concept": "operating_income",
  "fact_id": "FACT-59fc3cdc0b33",
  "known_at": "2025-07-15T00:00:00+00:00",
  "observation_period": "2025-Q2",
  "source_artifact_id": "ART-f2b516c96247",
  "source_locator": "/periods/0/facts/1",
  "subject_id": "demo-company-000001",
  "unit": "USD",
  "validation_status": "valid",
  "value": "84000000"
}
```

`FACT-fde4b197a83c` is the denominator (revenue, `1000000000`, locator
`/periods/0/facts/0`). Each fact records the artifact it came from
(`source_artifact_id`) and a JSON-pointer `source_locator` into the raw bytes.

### Step 4 — the raw source

The `source_locator` `/periods/0/facts/1` points into
`raw/demo-company-facts.json`:

```json
{
  "period": "2025-Q2",
  "known_at": "2025-07-15T00:00:00+00:00",
  "facts": [
    { "concept": "revenue",          "value": "1000000000", "unit": "USD", "locator": "/periods/0/facts/0" },
    { "concept": "operating_income", "value": "84000000",   "unit": "USD", "locator": "/periods/0/facts/1" }
  ]
}
```

The trace closes: the finding's `8.4%` is `84,000,000 / 1,000,000,000`, both
values read directly from the preserved raw source at the recorded locators.
The change evidence `EV-d1e9faaf6787` (`1.7 percentage points`) resolves the
same way, through the change calculation whose `input_calculation_ids` are the
two margin calculations.

## The claim and its assertions

`claims.json` records the structured claim behind the finding. Every number in
its `statement` is bound to evidence by a numeric assertion:

```json
{
  "claim_id": "CL-03d483aef9c0",
  "claim_type": "profitability_change",
  "direction": "increased",
  "evidence_ids": [
    "EV-9d33ded8a427",
    "EV-649d8a693225",
    "EV-d1e9faaf6787"
  ],
  "numeric_assertions": [
    { "asserted_value": "0.084", "evidence_id": "EV-9d33ded8a427", "metric": "operating_margin", "unit": "ratio" },
    { "asserted_value": "0.101", "evidence_id": "EV-649d8a693225", "metric": "operating_margin", "unit": "ratio" },
    { "asserted_value": "1.7",   "evidence_id": "EV-d1e9faaf6787", "metric": "operating_margin_change_pp", "unit": "percentage_points" }
  ],
  "statement": "Operating margin increased from 8.4% to 10.1%, an improvement of 1.7 percentage points.",
  "status": "verified"
}
```

Each assertion's `asserted_value`/`unit` must match the cited evidence exactly,
and the prose `statement` must equal the deterministic re-rendering of the
structured values. The verifier enforces both — see
[Interpreting results](interpreting-results.md).

## The verification record

`verification.json` records the outcome. A passing run cites the verified claim
and lists no failures:

```json
{
  "checked_at": "2026-08-09T05:46:40.882636+00:00",
  "failures": [],
  "rejected_claim_ids": [],
  "status": "passed",
  "verified_claim_ids": [
    "CL-03d483aef9c0"
  ],
  "verifier_version": "1.0.0"
}
```

`checked_at` is a wall-clock timestamp; it is excluded from the deterministic
hashes and from replay comparison.

## The manifest

`manifest.json` is the integrity record replay checks against. It names the
source, records the per-stage hashes, and stores the final status:

```json
{
  "calculation_versions": {
    "operating_margin": "1.0.0",
    "operating_margin_change_pp": "1.0.0"
  },
  "calculations_hash": "909f4511e46516c55de571abefeeebe6a4b7b4bddfe147c725c4903617df8142",
  "claims_hash": "5123f08dc100ec656c608d26b1752670097f3183d9082a4181cc3c29fabce9f0",
  "created_at": "2026-08-09T05:46:40.883059+00:00",
  "evidence_hash": "58227f746c75a12d45d11664a6ef3e3697e25a5bc67e33d79e910d581b4f901d",
  "facts_hash": "a1cd41ebfaf9dd4315a73acc56a72d8d161797a6aa7cf256848eb6e0a889b3e9",
  "final_status": "passed",
  "input_hash": "f2cb65fe4dbb01b63704cec2a432ea624664663f95203568ae57602e869b0a0f",
  "pipeline_version": "0.1.0",
  "run_id": "RUN-20260809-001",
  "source_hashes": {
    "demo-company-facts.json": "1c7cf5bba8aaa5bb9111fea1941ae53b79eb11de54e668315e450d4c70aaade7"
  },
  "source_name": "demo-company-facts.json",
  "source_type": "synthetic_fixture",
  "source_version": "1.0.0",
  "verification_hash": "df9b4d4502cffb9b3d9c6c457f1babe49d802b0116dad953db67c7ada1c93514"
}
```

For an EDGAR run the source identity differs: `source_type` is
`sec_edgar_companyfacts`, `source_name` is `companyfacts-CIK##########.json`,
and `source_version` records the chosen revenue tag and the filed-through date,
e.g. `RevenueFromContractWithCustomerExcludingAssessedTax@filed-through-2026-07-31`.

`created_at` and `run_id` are execution-specific and are excluded from replay
comparison; every hash field is compared. See [Replay](replay.md) for exactly
what is and is not compared.

## Related pages

- [Replay](replay.md) — recomputing a run and checking its hashes.
- [Interpreting results](interpreting-results.md) — reading the finding and
  verification status.
- [Artifact formats](../reference/artifact-formats.md) — field-by-field schema
  of each file.
