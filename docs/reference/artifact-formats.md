# Artifact formats

Every research run commits a self-contained directory named `RUN-YYYYMMDD-NNN` under the
[state directory](environment-variables.md). The directory is written atomically (a hidden
`.staging-*` directory plus a single `os.rename`), so a visible `RUN-*` directory always contains a
complete run and a completed run is never overwritten. See [Research runs](../usage/research-runs.md)
and [Storage](../architecture/storage.md) for the commit protocol.

The excerpts below are real captures from a `DEMO` run (`RUN-20260809-001`), abridged with `...`
where long.

## Directory layout

```
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

## On-disk encoding rules

All JSON artifacts share one encoding, produced by `canonical.pretty_json_bytes`:

- **Pretty, sorted, UTF-8.** Keys are sorted; two-space indentation; a trailing newline. This is the
  human-readable form. It is **not** the form that is hashed.
- **`Decimal` values are JSON strings.** A revenue of one billion dollars is stored as
  `"1000000000"`, a ratio as `"0.084"`. Floats never appear — they are rejected at the model, at
  parse time, and during serialization.
- **Datetimes are UTC ISO 8601.** Timezone-aware, normalized to UTC, e.g.
  `"2025-07-15T00:00:00+00:00"`. Naive datetimes are forbidden. `date` values use plain ISO dates
  (`"2026-08-09"`).
- **Enums are stored by value** (`"revenue"`, `"passed"`, `"USD"`).

!!! note "Pretty on disk, canonical for hashing"
    Hashes and content-derived IDs are computed from a *different* serialization —
    `canonical.canonical_bytes`, which is compact (`separators=(",", ":")`, no indentation), with
    the identical value encoding (Decimals as normalized plain strings, UTC ISO datetimes, enums by
    value). The pretty on-disk file and the compact hashing form describe the same content; only the
    on-disk file has whitespace. Never hash the pretty form.

## `spec.json` — the request

The validated `ResearchSpec`. Pure user input, no derived values.

```json
{
  "as_of_date": "2026-08-09",
  "company_id": "demo-company-000001",
  "company_name": "Demonstration Company",
  "historical_periods": [
    "2025-Q2",
    "2026-Q2"
  ],
  "pipeline_version": "0.1.0",
  "question": "Is operating profitability improving?",
  "ticker": "DEMO"
}
```

## `raw/<source file>` — preserved source bytes

The exact bytes STRIX consumed, preserved byte-for-byte. For `DEMO` this is the bundled synthetic
fixture; for a real ticker it is the SEC EDGAR company-facts JSON named
`companyfacts-CIK##########.json`. On write, the copy is re-read and its SHA-256 re-verified against
the original bytes. **Because the raw source is preserved, [replay](../usage/replay.md) is always
offline** — it recomputes from these bytes and never touches the network.

```json
{
  "fixture_name": "demo-company-facts",
  "fixture_version": "1.0.0",
  "synthetic": true,
  "notice": "SYNTHETIC DEMONSTRATION DATA. Demonstration Company is a fictional entity created for the STRIX prototype. ...",
  "source_type": "synthetic_fixture",
  "created_at": "2026-07-15T00:00:00+00:00",
  "company": {
    "company_id": "demo-company-000001",
    "ticker": "DEMO",
    "name": "Demonstration Company"
  },
  "periods": [
    {
      "period": "2025-Q2",
      "known_at": "2025-07-15T00:00:00+00:00",
      "facts": [
        { "concept": "revenue", "value": "1000000000", "unit": "USD", "locator": "/periods/0/facts/0" },
        { "concept": "operating_income", "value": "84000000", "unit": "USD", "locator": "/periods/0/facts/1" }
      ]
    }
    ...
  ]
}
```

!!! warning "Synthetic data"
    `Demonstration Company` is a fictional entity. Figures in the bundled fixture are not real
    financial data and must never be presented as such.

## `facts.json` — extracted source facts

An array of `SourceFact`. `known_at` is the fixture `known_at` (for `DEMO`) or the SEC `filed` date
(for EDGAR); it is treated as source content and **is** replay-compared.

```json
[
  {
    "concept": "revenue",
    "fact_id": "FACT-fde4b197a83c",
    "known_at": "2025-07-15T00:00:00+00:00",
    "observation_period": "2025-Q2",
    "source_artifact_id": "ART-f2b516c96247",
    "source_locator": "/periods/0/facts/0",
    "subject_id": "demo-company-000001",
    "unit": "USD",
    "validation_status": "valid",
    "value": "1000000000"
  },
  ...
  {
    "concept": "operating_income",
    "fact_id": "FACT-9cff5a7d197e",
    "known_at": "2026-07-15T00:00:00+00:00",
    "observation_period": "2026-Q2",
    "source_artifact_id": "ART-f2b516c96247",
    "source_locator": "/periods/1/facts/1",
    "subject_id": "demo-company-000001",
    "unit": "USD",
    "validation_status": "valid",
    "value": "101000000"
  }
]
```

## `calculations.json` — deterministic calculations

An array of `CalculationResult`. Each ID is `CALC-<sha256[:12]>` derived from the calculation
inputs, so identical inputs always yield the identical ID.

```json
[
  {
    "calculation_id": "CALC-cf3c3f6a4f26",
    "calculation_name": "operating_margin",
    "calculation_version": "1.0.0",
    "input_calculation_ids": [],
    "input_fact_ids": [ "FACT-59fc3cdc0b33", "FACT-fde4b197a83c" ],
    "observation_period": "2025-Q2",
    "subject_id": "demo-company-000001",
    "unit": "ratio",
    "value": "0.084"
  },
  ...
  {
    "calculation_id": "CALC-bb36572ac2e1",
    "calculation_name": "operating_margin_change_pp",
    "calculation_version": "1.0.0",
    "input_calculation_ids": [ "CALC-fb3e8afffc03", "CALC-cf3c3f6a4f26" ],
    "input_fact_ids": [ "FACT-9cff5a7d197e", "FACT-984d1189dc7a", "FACT-59fc3cdc0b33", "FACT-fde4b197a83c" ],
    "observation_period": "2025-Q2..2026-Q2",
    "subject_id": "demo-company-000001",
    "unit": "percentage_points",
    "value": "1.7"
  }
]
```

## `evidence.json` — citable evidence

An array of `Evidence`. Note `display_value` (e.g. `"8.4%"`): a presentation-only field. It is
stored for convenience but is **excluded from every hash and from replay comparison** — the machine
value is `value`.

```json
[
  {
    "calculation_id": "CALC-cf3c3f6a4f26",
    "display_value": "8.4%",
    "evidence_id": "EV-9d33ded8a427",
    "evidence_type": "calculation",
    "known_at": "2025-07-15T00:00:00+00:00",
    "metric": "operating_margin",
    "observation_period": "2025-Q2",
    "source_fact_ids": [ "FACT-59fc3cdc0b33", "FACT-fde4b197a83c" ],
    "status": "verified",
    "subject_id": "demo-company-000001",
    "unit": "ratio",
    "value": "0.084"
  },
  ...
  {
    "calculation_id": "CALC-bb36572ac2e1",
    "display_value": "1.7 percentage points",
    "evidence_id": "EV-d1e9faaf6787",
    "evidence_type": "calculation",
    "known_at": "2026-07-15T00:00:00+00:00",
    "metric": "operating_margin_change_pp",
    "observation_period": "2025-Q2..2026-Q2",
    "source_fact_ids": [ "FACT-9cff5a7d197e", "FACT-984d1189dc7a", "FACT-59fc3cdc0b33", "FACT-fde4b197a83c" ],
    "status": "verified",
    "subject_id": "demo-company-000001",
    "unit": "percentage_points",
    "value": "1.7"
  }
]
```

## `claims.json` — structured claims

An array of `Claim`, each with its nested `numeric_assertions`. Every number in `statement` is
bound to an evidence ID that must support that exact value and unit.

```json
[
  {
    "claim_id": "CL-03d483aef9c0",
    "claim_type": "profitability_change",
    "direction": "increased",
    "evidence_ids": [ "EV-9d33ded8a427", "EV-649d8a693225", "EV-d1e9faaf6787" ],
    "numeric_assertions": [
      { "asserted_value": "0.084", "evidence_id": "EV-9d33ded8a427", "metric": "operating_margin", "unit": "ratio" },
      { "asserted_value": "0.101", "evidence_id": "EV-649d8a693225", "metric": "operating_margin", "unit": "ratio" },
      { "asserted_value": "1.7", "evidence_id": "EV-d1e9faaf6787", "metric": "operating_margin_change_pp", "unit": "percentage_points" }
    ],
    "statement": "Operating margin increased from 8.4% to 10.1%, an improvement of 1.7 percentage points.",
    "status": "verified",
    "subject_id": "demo-company-000001"
  }
]
```

## `verification.json` — verification result

The `VerificationResult`. `checked_at` is wall-clock time and is **excluded from the verification
hash and from replay comparison**; `known_at` timestamps (which come from source content) are not.

```json
{
  "checked_at": "2026-08-09T05:46:40.882636+00:00",
  "failures": [],
  "rejected_claim_ids": [],
  "status": "passed",
  "verified_claim_ids": [ "CL-03d483aef9c0" ],
  "verifier_version": "1.0.0"
}
```

When verification fails, `status` is `"failed"`, `failures` lists `VerificationFailure` entries (each
with a [`FailureCode`](data-models.md#failurecode)), and the report publishes no claims.

## `manifest.json` — integrity record

The `RunManifest`: source hashes, calculation versions, and one hash per pipeline stage.

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

For an EDGAR run, `source_type` is `"sec_edgar_companyfacts"`, `source_name` is
`companyfacts-CIK##########.json`, and `source_version` encodes the chosen revenue tag and the
filed-through date, e.g.
`"RevenueFromContractWithCustomerExcludingAssessedTax@filed-through-2026-07-31"`.

## `report.txt` — the publishable report

The rendered `ResearchReport`. Plain text, embedding the run ID and the source disclaimer. Because
it embeds the run ID (which varies per execution), `report.txt` is **not** replay-compared.

```text
Operating profitability of Demonstration Company (DEMO)
=======================================================

Run: RUN-20260809-001
Verification: passed

Finding:
  Operating margin increased from 8.4% to 10.1%, an improvement of 1.7
  percentage points.
  Evidence: EV-9d33ded8a427, EV-649d8a693225, EV-d1e9faaf6787

Synthetic demonstration data — not investment advice.
```

An EDGAR report ends with the EDGAR disclaimer instead:
`Source: SEC EDGAR company facts, as filed. Research prototype output — not investment advice.`

!!! warning "Not investment advice"
    STRIX is research and decision-support tooling. Every report ends with a disclaimer. STRIX
    produces no investment advice and cannot place trades.

## What replay compares

[Replay](../usage/replay.md) checks each stage against the manifest **twice**: the stored artifact
hash (integrity) and a hash recomputed from the preserved spec and raw bytes (reproducibility). The
seven compared stages:

| Stage | Backing artifact |
| --- | --- |
| Source artifact hash | `raw/<source file>` bytes |
| Input hash | `spec.json` + raw source SHA-256 |
| Source facts hash | `facts.json` |
| Calculations hash | `calculations.json` |
| Evidence hash | `evidence.json` |
| Claims hash | `claims.json` |
| Verification status | `verification.json` + `final_status` |

**Excluded from comparison:** `run_id`, `created_at` and `checked_at` (wall-clock), the run
directory path, `report.txt` (it embeds the run ID), and `Evidence.display_value`
(presentation-only). `known_at` **is** compared because it is fixture / filing content.

!!! note
    A matching hash proves **content identity and integrity** — that the bytes are exactly what
    produced the recorded hash. It does **not** prove the content is factually true. See the
    [Glossary](glossary.md#content-derived-id).
