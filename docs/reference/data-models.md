# Data models

Every value that moves through STRIX is a **frozen** [Pydantic](https://docs.pydantic.dev/) model
defined in [`src/strix/models.py`](../development/project-structure.md). The models encode the
lineage contract:

```
SourceArtifact -> SourceFact -> CalculationResult -> Evidence -> Claim -> verified report
```

All domain models inherit from `StrixModel`:

```python
class StrixModel(BaseModel):
    """Base for all STRIX domain models: frozen, closed schema."""
    model_config = ConfigDict(frozen=True, extra="forbid")
```

Two consequences follow from that config and apply to **every** model on this page:

- **Frozen (immutable).** Instances cannot be mutated in place. A status transition
  (for example `proposed -> verified`) produces a *copy* via `model_copy(update=...)`, never an
  edit. This is what lets a content-derived ID stay stable while status changes.
- **Closed schema (`extra="forbid"`).** An unknown field is a validation error, not a silently
  ignored extra. A tampered or drifted artifact fails to load rather than loading partially.

## Decimal values, never floats

Monetary and ratio quantities are `Decimal`. A dedicated annotated type rejects binary
floating point **at the model boundary**:

```python
def _reject_float(value: object) -> object:
    """Forbid binary floating point on Decimal fields (str/int/Decimal only)."""
    if isinstance(value, float):
        raise ValueError("float values are forbidden; supply Decimal, str, or int")
    return value

DecimalValue = Annotated[Decimal, BeforeValidator(_reject_float)]
```

Any field typed `DecimalValue` below accepts a `Decimal`, `str`, or `int` and raises on a
`float`. The same prohibition is enforced again during
[canonical serialization](../architecture/provenance.md) and during source parsing, so a float can
never reach a hash. See [Artifact formats](artifact-formats.md) for how `Decimal` values are stored
on disk (as JSON strings).

---

## Enumerations

STRIX uses closed vocabularies (`StrEnum`). A value outside the enum fails validation. Each is
serialized by its string value.

### `SourceType`

| Value | Meaning |
| --- | --- |
| `synthetic_fixture` | Bundled offline synthetic fixture (the `DEMO` ticker). |
| `sec_edgar_companyfacts` | Live SEC EDGAR company-facts filing data (any real ticker). |

### `Concept`

Raw observed quantities extracted from a source.

| Value | Meaning |
| --- | --- |
| `revenue` | Period revenue. |
| `operating_income` | Period operating income. |

### `Unit`

| Value | Meaning |
| --- | --- |
| `USD` | United States dollars. |
| `ratio` | Dimensionless ratio (e.g. an operating margin of `0.084`). |
| `percentage_points` | Arithmetic difference between two percentages (see [percentage point](glossary.md#percentage-point)). |

### `ValidationStatus`

| Value | Meaning |
| --- | --- |
| `valid` | The source fact passed extraction validation. |
| `invalid` | The source fact failed extraction validation. |

### `EvidenceType`

| Value | Meaning |
| --- | --- |
| `calculation` | The evidence is backed by a deterministic calculation result. |

### `Metric`

| Value | Meaning |
| --- | --- |
| `operating_margin` | `operating_income / revenue`, a ratio. |
| `operating_margin_change_pp` | Year-over-year change of operating margin, in percentage points. |

### `EvidenceStatus`

| Value | Meaning |
| --- | --- |
| `unverified` | Evidence produced but not yet checked by the verifier. |
| `verified` | Evidence confirmed by the verifier. |
| `rejected` | Evidence rejected by the verifier. |

### `ClaimType`

| Value | Meaning |
| --- | --- |
| `profitability_change` | A claim about a change in profitability. |

### `ClaimStatus`

| Value | Meaning |
| --- | --- |
| `proposed` | Claim proposed by the reasoner, not yet verified. |
| `verified` | Claim confirmed by the verifier and eligible for the report. |
| `rejected` | Claim rejected by the verifier. |

### `Direction`

| Value | Meaning |
| --- | --- |
| `increased` | The subject metric increased. |
| `decreased` | The subject metric decreased. |
| `unchanged` | The subject metric did not change. |

### `VerificationStatus`

| Value | Meaning |
| --- | --- |
| `passed` | Verification succeeded. |
| `failed` | Verification failed; no claims are published. |

### `FailureCode`

One code accompanies each verification failure. The full set:

| Value | Raised when |
| --- | --- |
| `unknown_evidence` | An assertion or claim cites an evidence ID that does not exist. |
| `subject_mismatch` | Evidence or a fact belongs to a different subject than the claim. |
| `evidence_after_as_of` | Evidence is known after the research as-of date (a look-ahead). |
| `assertion_value_mismatch` | A claim's asserted value differs from its cited evidence value. |
| `assertion_unit_mismatch` | A claim's asserted unit differs from its cited evidence unit. |
| `assertion_evidence_not_cited` | An assertion's evidence is not in the claim's `evidence_ids`. |
| `missing_assertion` | A required numeric assertion is absent from the claim. |
| `unsupported_unit` | A unit outside the supported vocabulary appears. |
| `missing_comparison_evidence` | A change claim lacks one of the two period evidences it compares. |
| `evidence_not_verified` | A claim cites evidence that did not itself verify. |
| `unknown_calculation` | Evidence references a calculation ID that does not exist. |
| `missing_source_fact` | A calculation references a source fact ID that does not exist. |
| `artifact_mismatch` | A source fact's artifact does not match the run's source artifact. |
| `evidence_calc_mismatch` | Evidence value or unit disagrees with its backing calculation. |
| `incomplete_lineage` | The source-fact-to-claim lineage cannot be fully reconstructed. |
| `direction_mismatch` | The claim's stated direction disagrees with the numbers. |
| `statement_mismatch` | The claim prose differs from the re-rendered statement (drift). |
| `no_claims` | The reasoner proposed no claims to verify. |

A failed verification publishes **no** claims in the report and the CLI exits `1`. See
[Interpreting results](../usage/interpreting-results.md) and [Replay](../usage/replay.md).

---

## Domain models

### `ResearchSpec`

The validated description of one research request. Pure user input — no derived values.

| Field | Type | Meaning |
| --- | --- | --- |
| `company_id` | `str` | Internal subject identifier (e.g. `demo-company-000001`, or `CIK0000320193` for EDGAR). |
| `ticker` | `str`, pattern `^[A-Z][A-Z0-9.\-]{0,9}$` | Uppercase ticker; 1–10 chars, starts with a letter. |
| `company_name` | `str` | Human-readable company name. |
| `question` | `str`, `min_length=1` | The research question (non-empty). |
| `as_of_date` | `date` | Point-in-time cutoff; only facts known on or before this date are used. |
| `historical_periods` | `tuple[str, str]` | Role-ordered `(previous_period, current_period)`, e.g. `("2025-Q2", "2026-Q2")`. |
| `pipeline_version` | `str` | Version of the pipeline that produced the run. |

### `SourceArtifact`

A preserved raw source input, identified by its content hash. One per run.

| Field | Type | Meaning |
| --- | --- | --- |
| `artifact_id` | `str` | Content-derived ID, `ART-<sha256[:12]>`. |
| `source_type` | `SourceType` | Which source produced the bytes. |
| `source_name` | `str`, pattern `^[A-Za-z0-9][A-Za-z0-9._\-]*$` | Plain file name of the preserved raw copy — **never a path**. |
| `source_version` | `str` | Content-derived version label (fixture version, or EDGAR revenue tag + filed-through date). |
| `content_hash` | `str`, pattern `^[0-9a-f]{64}$` | SHA-256 hex of the preserved raw bytes. |
| `known_at` | `AwareDatetime` | When the source content became known (timezone-aware, stored as UTC). |
| `local_path` | `str` | Path of the preserved copy **relative to the run directory** (absolute paths never enter hashed content). |
| `byte_size` | `int`, `ge=1` | Size of the preserved raw bytes. |

### `SourceFact`

One validated observation extracted from a source artifact.

| Field | Type | Meaning |
| --- | --- | --- |
| `fact_id` | `str` | Content-derived ID, `FACT-<sha256[:12]>`. |
| `subject_id` | `str` | The subject (company) the fact describes. |
| `concept` | `Concept` | `revenue` or `operating_income`. |
| `value` | `DecimalValue` | The observed quantity (float rejected). |
| `unit` | `Unit` | Unit of `value`. |
| `observation_period` | `str` | The period the fact describes, e.g. `2025-Q2`. |
| `known_at` | `AwareDatetime` | When the fact became known (fixture `known_at` or SEC `filed` date). |
| `source_artifact_id` | `str` | The `SourceArtifact` this fact was extracted from. |
| `source_locator` | `str` | JSON-pointer locator of the fact inside the source artifact. |
| `validation_status` | `ValidationStatus` | Extraction validation outcome. |

### `CalculationResult`

The output of one deterministic, versioned calculation.

| Field | Type | Meaning |
| --- | --- | --- |
| `calculation_id` | `str` | Content-derived ID, `CALC-<sha256[:12]>`. |
| `calculation_name` | `Metric` | Which metric was computed. |
| `calculation_version` | `str` | Version of the calculation (e.g. `1.0.0`). |
| `subject_id` | `str` | The subject the calculation is about. |
| `value` | `DecimalValue` | The computed value (float rejected). |
| `unit` | `Unit` | Unit of `value` (`ratio` or `percentage_points`). |
| `observation_period` | `str` | Period or period range, e.g. `2025-Q2` or `2025-Q2..2026-Q2`. |
| `input_fact_ids` | `tuple[str, ...]` | Role-ordered input source facts (e.g. `[numerator, denominator]`). |
| `input_calculation_ids` | `tuple[str, ...]` (default `()`) | Role-ordered upstream calculations (e.g. `[current, previous]`); empty when computed directly from facts. |

### `Evidence`

A citable, typed result carrying its full lineage. This is what a claim must cite.

| Field | Type | Meaning |
| --- | --- | --- |
| `evidence_id` | `str` | Content-derived ID, `EV-<sha256[:12]>`. |
| `subject_id` | `str` | The subject the evidence is about. |
| `evidence_type` | `EvidenceType` | Backing type (`calculation`). |
| `metric` | `Metric` | Which metric the evidence carries. |
| `value` | `DecimalValue` | The evidence value (float rejected). |
| `display_value` | `str` | Presentation-only rendering of `value` (e.g. `8.4%`). **Excluded from hashes and replay comparison.** |
| `unit` | `Unit` | Unit of `value`. |
| `observation_period` | `str` | Period or period range the evidence covers. |
| `calculation_id` | `str` | The `CalculationResult` this evidence rests on. |
| `source_fact_ids` | `tuple[str, ...]` | All source facts this evidence ultimately rests on (role-ordered). |
| `known_at` | `AwareDatetime` | When the evidence became known. |
| `status` | `EvidenceStatus` | `unverified`, `verified`, or `rejected`. |

!!! note
    `display_value` is the **only** presentation-only field. Because it is excluded from the
    canonical hash, changing how a number is displayed never changes an evidence ID or a stored
    hash. See [Artifact formats](artifact-formats.md#what-replay-compares).

### `NumericAssertion`

A number a claim asserts, bound to the evidence that must support it. Not a top-level artifact —
it appears only nested inside a `Claim`.

| Field | Type | Meaning |
| --- | --- | --- |
| `metric` | `Metric` | Which metric is asserted. |
| `asserted_value` | `DecimalValue` | The value the claim asserts (float rejected). |
| `unit` | `Unit` | Unit of `asserted_value`. |
| `evidence_id` | `str` | The evidence that must support this exact value and unit. |

### `Claim`

A structured statement whose every number must cite evidence.

| Field | Type | Meaning |
| --- | --- | --- |
| `claim_id` | `str` | Content-derived ID, `CL-<sha256[:12]>`. |
| `subject_id` | `str` | The subject the claim is about. |
| `statement` | `str` | The human-readable prose. Must equal the verifier's re-rendered statement. |
| `claim_type` | `ClaimType` | `profitability_change`. |
| `direction` | `Direction` | `increased`, `decreased`, or `unchanged`. |
| `evidence_ids` | `tuple[str, ...]` | Every evidence the claim cites. |
| `numeric_assertions` | `tuple[NumericAssertion, ...]` | Each number in the statement, bound to its evidence. |
| `status` | `ClaimStatus` | `proposed`, `verified`, or `rejected`. |

### `VerificationFailure`

One concrete reason a claim (or its evidence) was rejected.

| Field | Type | Meaning |
| --- | --- | --- |
| `code` | `FailureCode` | The failure category (see table above). |
| `message` | `str` | Human-readable detail. |
| `claim_id` | `str \| None` (default `None`) | The claim the failure applies to, if any. |
| `evidence_id` | `str \| None` (default `None`) | The evidence the failure applies to, if any. |

### `VerificationResult`

The outcome of the deterministic verification pass.

| Field | Type | Meaning |
| --- | --- | --- |
| `status` | `VerificationStatus` | `passed` or `failed`. |
| `verified_claim_ids` | `tuple[str, ...]` | Claims that passed. |
| `rejected_claim_ids` | `tuple[str, ...]` | Claims that failed. |
| `failures` | `tuple[VerificationFailure, ...]` | Every failure recorded during the pass. |
| `checked_at` | `AwareDatetime` | Wall-clock time of the check. **Excluded from deterministic hashes and replay comparison.** |
| `verifier_version` | `str` | Version of the verifier (e.g. `1.0.0`). |

### `ResearchReport`

The publishable result. Contains only verified structured content.

| Field | Type | Meaning |
| --- | --- | --- |
| `run_id` | `str` | The run this report belongs to (`RUN-YYYYMMDD-NNN`). |
| `title` | `str` | Report title. |
| `summary` | `str` | Short summary line. |
| `claims` | `tuple[Claim, ...]` | Only verified claims. Empty when verification failed. |
| `evidence_ids` | `tuple[str, ...]` | Evidence cited by the report's claims. |
| `verification_status` | `VerificationStatus` | `passed` or `failed`. |
| `disclaimer` | `str` | Source disclaimer (synthetic-data notice, or the EDGAR "not investment advice" notice). |

!!! warning
    A report with `verification_status = failed` carries **no** claims. The report never
    publishes an unverified number.

### `RunManifest`

The integrity record for one research run. Its fields split into two groups.

| Field | Type | Meaning |
| --- | --- | --- |
| `run_id` | `str` | Execution ID, `RUN-YYYYMMDD-NNN`. **Excluded from replay comparison.** |
| `created_at` | `AwareDatetime` | When the run was committed. **Excluded from replay comparison.** |
| `pipeline_version` | `str` | Pipeline version. |
| `source_type` | `SourceType` | Source that produced the run. |
| `source_name` | `str`, pattern `^[A-Za-z0-9][A-Za-z0-9._\-]*$` | Plain file name under `raw/`; validated so a tampered manifest cannot steer replay outside the run directory. |
| `source_version` | `str` | Content-derived source version. |
| `source_hashes` | `dict[str, str]` | Source file name → SHA-256 of the preserved raw bytes. |
| `calculation_versions` | `dict[str, str]` | Calculation name → version used in this run. |
| `input_hash` | `str` | Hash of the run input (spec + raw source hash). |
| `facts_hash` | `str` | Hash of the source facts. |
| `calculations_hash` | `str` | Hash of the calculation results. |
| `evidence_hash` | `str` | Hash of the evidence. |
| `claims_hash` | `str` | Hash of the claims. |
| `verification_hash` | `str` | Hash of the verification result (excludes `checked_at`). |
| `final_status` | `VerificationStatus` | `passed` or `failed`. |

The deterministic (replay-compared) fields are `pipeline_version`, `source_type`, `source_name`,
`source_version`, `source_hashes`, `calculation_versions`, `input_hash`, `facts_hash`,
`calculations_hash`, `evidence_hash`, `claims_hash`, `verification_hash`, and `final_status`.
`run_id` and `created_at` are execution-specific and excluded. See [Replay](../usage/replay.md).

### `ResearchResult`

Everything produced by one confirmed research run. This is the in-memory aggregate returned by
the pipeline; each field corresponds to an on-disk artifact except `run_directory`.

| Field | Type | Meaning |
| --- | --- | --- |
| `spec` | `ResearchSpec` | The request. Persisted as `spec.json`. |
| `artifact` | `SourceArtifact` | The preserved source. Raw bytes under `raw/`. |
| `facts` | `tuple[SourceFact, ...]` | Persisted as `facts.json`. |
| `calculations` | `tuple[CalculationResult, ...]` | Persisted as `calculations.json`. |
| `evidence` | `tuple[Evidence, ...]` | Persisted as `evidence.json`. |
| `claims` | `tuple[Claim, ...]` | Persisted as `claims.json`. |
| `verification` | `VerificationResult` | Persisted as `verification.json`. |
| `report` | `ResearchReport` | Rendered to `report.txt`. |
| `manifest` | `RunManifest` | Persisted as `manifest.json`. |
| `run_directory` | `Path` | Path of the committed run directory, `state_dir / RUN-YYYYMMDD-NNN` — absolute only when the state directory is absolute; relative under the default `research_runs` (not a stored artifact). |

See [Artifact formats](artifact-formats.md) for the on-disk representation of each field, and the
[Glossary](glossary.md) for term definitions.
