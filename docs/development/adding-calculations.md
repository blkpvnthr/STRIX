# Adding calculations

A **calculation** is the only kind of code allowed to produce an authoritative
financial number. All of them live in `analytics/`. Today there is one module,
`analytics/profitability.py`, with two calculations: operating margin and the
margin change in percentage points. This page dissects that module and states
what a new calculation must do to keep lineage and replay intact.

!!! warning "Authoritative arithmetic is confined to `analytics`"
    No other layer computes financial values. The reasoner copies numbers
    verbatim; the verifier re-derives only a direction sign and the display
    prose. If a new number is needed, it belongs in a calculation here.

## Anatomy of `profitability.py`

### Exact input validation

`operating_margin(*, operating_income, revenue)` rejects anything it cannot
compute meaningfully, each with a typed `CalculationError`:

- the numerator must be `operating_income` and the denominator `revenue`
  (wrong concepts are rejected);
- both inputs must be `USD`;
- both must share one `subject_id` and one `observation_period`;
- revenue must be non-zero and positive.

`operating_margin_change_pp(*, current, previous)` similarly requires two
operating-margin ratios for the **same** subject across **two distinct**
periods.

### Local decimal context

All arithmetic runs inside a `localcontext()` block that sets
`prec = 34` and `rounding = ROUND_HALF_EVEN`. The global decimal context is
never mutated, so calculations cannot perturb each other or the rest of the
process.

### Quantization policy

Each result is quantized to an authoritative quantum:

- **Operating margin** is a *ratio*: `operating_income / revenue`, quantized to
  six decimal places (`RATIO_QUANTUM = 0.000001`) — e.g. `0.084000`.
- **Margin change** is in *percentage points*: `(current - previous) * 100`,
  quantized to four decimal places (`PP_QUANTUM = 0.0001`) — e.g. `1.7000`.

Percentage **points** are the arithmetic difference between two percentages
(`10.1% - 8.4% = 1.7 pp`), which STRIX deliberately reports instead of the
relative percentage change (`(10.1 - 8.4) / 8.4 ≈ 20.2%`). The distinct
`Unit.PERCENTAGE_POINTS` exists to keep the two from being confused.

### Range guard

The `quantize` call is wrapped so a `decimal.InvalidOperation` (for a value
outside the working precision) becomes a typed `CalculationError` reading "out
of the supported numeric range", never a raw traceback.

### Role-ordered lineage inputs

Every `CalculationResult` records the exact inputs it consumed, in a fixed
order:

- `input_fact_ids` — role-ordered source facts. For a margin this is
  `(operating_income.fact_id, revenue.fact_id)` (numerator, then denominator).
  For the change it is `current.input_fact_ids + previous.input_fact_ids`
  (current period's facts, then previous period's).
- `input_calculation_ids` — role-ordered upstream calculations, empty for a
  calculation built directly from facts. The change records
  `(current.calculation_id, previous.calculation_id)`.

Role ordering matters: the ID is derived from these lists, so the order is
part of the content.

### Content-derived `CALC` identity

The `calculation_id` is `make_id("CALC", {...})` over the calculation name,
version, subject, ordered input IDs (and, for derived calculations, the input
calculation IDs), value, unit, and observation period. Because the ID is a
hash of the inputs and the result, recomputing the same calculation yields the
same ID — the property `tests/test_profitability.py` and `test_evidence.py`
pin. See [Provenance](../architecture/provenance.md) for the ID scheme.

### `CALCULATION_VERSION`

Every result carries `calculation_version` (currently `"1.0.0"`), and the run
manifest records the version used per calculation name. Because the version is
part of the hashed payload, bumping it deliberately changes calculation IDs —
which is how a genuine formula change is made visible to replay rather than
hidden.

## How evidence is built from a calculation

`pipeline._build_evidence(calc, facts)` turns a `CalculationResult` into a
citable `Evidence` record. It:

- computes `known_at` as the **max** `known_at` across the calculation's input
  facts (so evidence is only "knowable" once its latest input was);
- copies `value`, `unit`, `observation_period`, and `calculation_id`
  straight from the calculation;
- carries `source_fact_ids = calc.input_fact_ids` (the full role-ordered
  lineage);
- sets `display_value = display_value(calc.calculation_name, calc.unit,
  calc.value)` — a presentation-only string excluded from the evidence ID and
  every stage hash;
- derives the `evidence_id` via `make_id("EV", …)` over the lineage fields
  (not the display string).

The verifier's first pass then re-checks that lineage end to end:
`Evidence -> CalculationResult -> SourceFact -> SourceArtifact`, with value and
unit matching the calculation exactly. Any mismatch marks the evidence
`rejected`.

## Adding an evidence type

Every evidence record today has `evidence_type: EvidenceType.CALCULATION` —
the only member of the `EvidenceType` enum in `models.py`, because the only
way STRIX currently produces a citable number is through a deterministic
calculation. A future evidence kind (for example, a value quoted directly
from a filing without arithmetic) would be introduced by:

1. **Adding an enum value** to `EvidenceType` in `src/strix/models.py`
   (e.g. `DIRECT_OBSERVATION = "direct_observation"`). Enum values serialize
   by value in canonical JSON, so the new string becomes part of every
   evidence ID and stage hash that uses it — added values never change
   existing IDs.
2. **Building it in the pipeline**, alongside `pipeline._build_evidence`.
   The new builder must still populate the full lineage contract:
   a `calculation_id` **or** an equivalent traceable anchor, role-ordered
   `source_fact_ids`, a content-derived `known_at`, and an `EV-` ID computed
   over lineage fields only (never `status` or `display_value`).
3. **Teaching the verifier about it** — `_verify_evidence_lineage` in
   `src/strix/verification/claims.py` currently assumes every evidence is
   backed by a calculation. A non-calculation evidence type needs its own
   lineage rule there; without one, verification rejects it (which is the
   safe default).
4. **Extending the tests**: stable-ID tests, lineage-completeness tests, and
   a replay round-trip that includes the new type.

Until such a need exists, keep the single `calculation` type — an enum value
with no producer or verifier rule would be dead vocabulary.

## What a new calculation must do

To add a calculation while keeping lineage and replay intact:

1. **Compute exactly with `Decimal`** inside a `localcontext()`; never use
   `float`, and never mutate the global context.
2. **Choose and document an authoritative quantum** and the correct `Unit`.
3. **Validate inputs** and raise `CalculationError` on anything unsupported;
   wrap `quantize` so range failures surface as `CalculationError`.
4. **Record role-ordered `input_fact_ids`** (and `input_calculation_ids` if it
   derives from other calculations) so the lineage remains complete.
5. **Derive the `calculation_id` with `make_id("CALC", …)`** over those inputs
   plus the value/unit/period, and set `calculation_version`.
6. **Wire it into `pipeline._build_calculations`** so the result flows into
   evidence and the manifest's `calculation_versions`.
7. **Add exactness tests** (like `test_profitability.py`) that assert the
   quantized value, the role-ordered lineage, and ID stability across
   recomputes.

## Calculations are not claims — the verifier boundary

A new calculation gives you a new **number**, not a new **finding**. The
verifier deliberately performs no independent financial recomputation; its
only independent checks are the **direction sign** and the **prose
re-rendering**, and those are wired specifically to the
`profitability_change` claim type in `verification/claims.py`.

So if a new calculation is meant to support a new *kind* of claim, that claim
type needs its own verifier rules:

- a `ClaimType` (and, if needed, `Metric`) value in `models.py`;
- supported-unit and completeness checks for the new claim type;
- whatever independent re-derivation makes the claim falsifiable (the analogue
  of the direction + statement checks).

Adding a calculation without those rules gives you traceable evidence, but the
existing verifier will only ever certify `profitability_change` claims. See
[Adding reasoners](adding-reasoners.md) for how claims are constructed and
[the evidence model](../architecture/evidence-model.md) for the full contract.
