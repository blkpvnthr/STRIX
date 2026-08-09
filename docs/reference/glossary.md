# Glossary

Crisp definitions of the terms STRIX uses. Each links to the page that covers it in full.

## Source artifact

The preserved raw source input for a run, identified by the SHA-256 of its exact bytes. One per
run, stored under `raw/` and recorded as a [`SourceArtifact`](data-models.md#sourceartifact). For
`DEMO` it is the bundled synthetic fixture; for a real ticker it is the SEC EDGAR company-facts
JSON. Preserving it is what makes [replay](#replay) offline.

## Source fact

One validated observation extracted from a source artifact — a `revenue` or `operating_income`
value for one period, with a JSON-pointer locator back into the source and a
[`known_at`](#known_at) timestamp. Modeled as [`SourceFact`](data-models.md#sourcefact).

## Calculation result

The output of one deterministic, versioned calculation over source facts (and, for the change
metric, over upstream calculations). Exact `Decimal` arithmetic; no floats. Modeled as
[`CalculationResult`](data-models.md#calculationresult). See
[operating margin](#operating-margin).

## Evidence

A citable, typed result that carries its full lineage from source facts through a calculation. It
is the only thing a [claim](#claim) may cite. Modeled as [`Evidence`](data-models.md#evidence); see
the [Evidence model](../architecture/evidence-model.md). Its `display_value` is presentation-only
and never hashed.

## Numeric assertion

A single number a claim asserts, bound to the evidence that must support that exact value and unit.
The verifier rejects any assertion whose value, unit, or citation does not match its evidence.
Modeled as [`NumericAssertion`](data-models.md#numericassertion).

## Claim

A structured statement whose every number is a [numeric assertion](#numeric-assertion) citing
evidence. A claim starts `proposed` and only reaches `verified` if it survives the verifier.
Modeled as [`Claim`](data-models.md#claim).

## Verification

The deterministic pass that either confirms every claim (and its evidence and lineage) or rejects
it with a typed [`FailureCode`](data-models.md#failurecode). The verifier re-renders each claim's
statement from its verified values and rejects any drift. A failed verification publishes **no**
claims and the CLI exits `1`. Modeled as
[`VerificationResult`](data-models.md#verificationresult); see
[Interpreting results](../usage/interpreting-results.md).

## Research run

One execution of the pipeline, committed atomically as a `RUN-YYYYMMDD-NNN` directory under the
[state directory](#state-directory). A run ID identifies an *execution*, not content — two runs over
identical inputs get different run IDs but identical content hashes. See
[Research runs](../usage/research-runs.md).

## Run manifest

The integrity record for a run: source hashes, calculation versions, and one hash per pipeline
stage, plus the final status. Modeled as [`RunManifest`](data-models.md#runmanifest) and stored as
`manifest.json`. It is the reference [replay](#replay) compares against.

## Replay

Re-execution of a preserved run from its stored spec and raw bytes, comparing every deterministic
hash — both the stored artifact (integrity) and a freshly recomputed value (reproducibility) —
against the manifest. Replay never touches the network. See [Replay](../usage/replay.md) and
[Artifact formats](artifact-formats.md#what-replay-compares).

## Canonical JSON

The strict serialization every hash and content-derived ID flows through: sorted keys, compact
separators, UTF-8, `Decimal` encoded as exact normalized plain strings, datetimes normalized to UTC
ISO 8601, enums by value, floats forbidden. Distinct from the pretty, indented form written to
disk. See [Provenance](../architecture/provenance.md) and
[Artifact formats](artifact-formats.md#on-disk-encoding-rules).

## Content-derived ID

An identifier of the form `PREFIX-<sha256(canonical JSON)[:12]>` — `ART-`, `FACT-`, `CALC-`, `EV-`,
`CL-`. Identical logical content always yields the identical ID. A matching ID or hash proves
content **identity and integrity, not factual truth**. See
[Provenance](../architecture/provenance.md).

## known_at

The point in time at which a fact became known. For the `DEMO` fixture it is the fixture's
`known_at`; for EDGAR it is the SEC `filed` date. Because it is source content (not wall clock), it
**is** compared during replay. Carried on [`SourceFact`](data-models.md#sourcefact) and
[`Evidence`](data-models.md#evidence).

## As-of date

The point-in-time cutoff for a research request: only facts with [`known_at`](#known_at) on or
before this date are used. Set on [`ResearchSpec`](data-models.md#researchspec). Enforcing it is
what prevents look-ahead.

## Point-in-time correctness

The property that a run uses only information available on its [as-of date](#as-of-date). The EDGAR
connector uses each fact's SEC `filed` date as its `known_at`, considers only facts filed on or
before the as-of date, and applies the [earliest-filed rule](#earliest-filed-rule) to restatements.
See [Provenance](../architecture/provenance.md).

## Percentage point

The arithmetic difference between two percentages: `10.1% − 8.4% = 1.7` percentage points. STRIX
reports profitability change in percentage points (`percentage_points`), which is deliberately
distinct from *percentage change* (`(10.1 − 8.4) / 8.4 ≈ 20.2%`), a figure STRIX does not report
here. See [Interpreting results](../usage/interpreting-results.md).

## Operating margin

`operating_income / revenue`, computed as a `ratio` quantized to six decimal places (e.g.
`0.084000`, displayed as `8.4%`). Its year-over-year change is reported in
[percentage points](#percentage-point). One of the two values in
[`Metric`](data-models.md#metric).

## Restatement

A later filing that revises a previously reported figure for a quarter. In STRIX's EDGAR handling
the [earliest-filed rule](#earliest-filed-rule) keeps the first-known value; a later restatement
never replaces it. See [Provenance](../architecture/provenance.md).

## Earliest-filed rule

When several EDGAR filings report the same quarter, STRIX keeps the **earliest-filed** value — the
value the market learned first — breaking exact same-day ties by the numeric position in the source
array. See [Provenance](../architecture/provenance.md).

## Synthetic fixture

The bundled, fully offline dataset behind the `DEMO` ticker: a fictional "Demonstration Company"
whose figures are not real financial data. Preserved per run as `raw/demo-company-facts.json`. See
[Artifact formats](artifact-formats.md).

!!! warning "Synthetic data"
    `Demonstration Company` is fictional. Its figures must never be presented as real financial
    data.

## EDGAR companyfacts

The public SEC endpoint (`data.sec.gov/api/xbrl/companyfacts/CIK##########.json`) providing all
XBRL facts a company has filed. STRIX fetches it for real tickers with no credentials, using a
fair-access `User-Agent`, and preserves the raw response per run. See
[Adding connectors](../development/adding-connectors.md).

## Deterministic reasoner

The fixed-logic Python component that proposes claims from `(spec, evidence)` — the
`DeterministicDemoReasoner`. It is **not** an LLM and calls no model API. A future
schema-constrained LLM adapter will sit behind the same reasoner protocol and the same verifier.
See the [LLM boundary](../architecture/llm-boundary.md).

## Connector

A data source adapter that fetches raw bytes and normalizes them into facts — the synthetic-fixture
source and the SEC EDGAR source. See [Adding connectors](../development/adding-connectors.md).

## State directory

The directory that holds all run artifacts, defaulting to `./research_runs` (gitignored). Set it
with `--state-dir` or the [`STRIX_STATE_DIR`](environment-variables.md) environment variable. See
[Environment variables](environment-variables.md) and
[Configuration](../getting-started/configuration.md).
