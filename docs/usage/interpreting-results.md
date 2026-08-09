# Interpreting results

STRIX reports a single, narrow finding: whether a company's operating margin
improved between two comparable quarters, and by how many percentage points.
This page explains how to read that sentence, what the verification status
means, every way verification can fail, and the disclaimers attached to each
data source.

## The finding sentence

A passing run prints one sentence and the evidence that supports it:

```text
Operating margin increased from 8.4% to 10.1%, an
improvement of 1.7 percentage points.
[EV-9d33ded8a427, EV-649d8a693225, EV-d1e9faaf6787]
```

The sentence names three numbers: the previous margin (`from`), the current
margin (`to`), and the change (`difference`). All three are rendered at **one
decimal place**.

### The numbers always add up

The `from`, `to`, and `difference` are derived from a single rounding step, so
the displayed numbers are always internally consistent:

```
to − from == difference   (at one decimal place)
```

In the example, `10.1 − 8.4 = 1.7`. You never see a sentence where the two
percentages and the stated change disagree — the difference shown is exactly
the difference of the two one-decimal percentages.

### Direction and wording

The direction word (`increased`, `decreased`, `unchanged`) comes from the sign
of the authoritative, unrounded change, and the verifier re-derives it
independently. The sentence takes one of four forms:

| Case | Sentence form |
| --- | --- |
| Margin rose | `Operating margin increased from X% to Y%, an improvement of Z percentage points.` |
| Margin fell | `Operating margin decreased from X% to Y%, a decline of Z percentage points.` |
| Exactly no change | `Operating margin was unchanged at Y%.` |
| Real change smaller than 0.1 pp | `Operating margin was effectively unchanged at Y% (a change of less than 0.1 percentage points).` |

The last row matters: when a genuine but tiny change rounds below `0.1`
percentage points, STRIX does **not** claim "an improvement of 0.0 percentage
points." It says the margin was *effectively unchanged* and states that the
change is less than 0.1 pp. The direction word can never contradict the
authoritative sign — display rounding may shrink the magnitude to zero, but it
never flips the direction.

## Percentage points vs percent

STRIX reports the change in **percentage points (pp)** — the arithmetic
difference between the two margins:

```
10.1% − 8.4% = 1.7 percentage points
```

This is deliberately distinct from a **percentage change**, which would be the
relative change:

```
(10.1 − 8.4) / 8.4 ≈ 20.2 percent
```

The finding reports `1.7 percentage points`, not `20.2%`. Percentage points and
percent are different quantities; STRIX never conflates them.

## Verification: Passed vs Failed

Every run ends with a verification step whose outcome is either **Passed** or
**Failed**. The interactive `Finding` block and `report.txt` both show the
outcome.

**Passed.** At least one claim exists and every claim verified. The finding is
published with its citations, `Verification: Passed` is shown, and the run exits
`0`.

**Failed.** One or more claims failed verification (or the reasoner produced no
claims). In that case STRIX:

- publishes **no finding** — not even the claims that individually passed, so a
  failed report can never read as approved,
- prints the list of verification failures, each as
  `- [<code>] <message>`,
- exits `1`.

The stored `report.txt` for a failed run shows `Verification: failed` and the
summary `No verified finding. One or more claims failed verification.` instead
of a finding.

!!! note "What a passing run guarantees"
    A pass means the finding's every number traces through verified lineage to
    the preserved source, the prose matches the deterministic rendering of
    those numbers, and the direction matches the sign of the change. It does
    **not** mean the underlying figures are economically meaningful or that the
    finding is investment guidance — see the disclaimers below.

## Verification failure codes

The verifier emits typed failure codes. With the bundled deterministic reasoner
running over untampered inputs, verification passes; these codes exist to catch
tampering, contract or version drift, and a faulty or future reasoner. The one
routinely user-actionable code is `evidence_after_as_of`.

| Code | Meaning | Typical cause / recovery |
| --- | --- | --- |
| `evidence_after_as_of` | Cited evidence became knowable after the as-of date. | Your as-of date predates the filing that supports the finding. Rerun with a later as-of date. |
| `unknown_evidence` | A claim or assertion cites an evidence ID that does not exist in the run. | A reasoner referenced evidence it was not given; internal defect. |
| `subject_mismatch` | Cited evidence belongs to a different company than the claim/spec subject. | Evidence and claim describe different subjects; internal defect or tampering. |
| `evidence_not_verified` | Cited evidence failed lineage verification (it is not `verified`). | The evidence's own lineage broke; see the evidence-level codes below. |
| `assertion_value_mismatch` | A numeric assertion's value differs from the cited evidence value. | Claim asserts a number the evidence does not hold; tampering or a faulty reasoner. |
| `assertion_unit_mismatch` | An assertion's unit differs from the cited evidence unit. | Unit was changed on the claim but not the evidence. |
| `assertion_evidence_not_cited` | An assertion references evidence the claim's `evidence_ids` does not list. | Prevents smuggling in evidence that skips the subject/as-of/verified gates. |
| `missing_assertion` | A required comparison value (previous margin, current margin, or change) has no numeric assertion. | The claim omitted an assertion it must make; a claim cannot dodge value/unit checks by omission. |
| `unsupported_unit` | An assertion uses a unit not allowed for the claim type. | Profitability-change claims may assert only `ratio` or `percentage_points`. |
| `missing_comparison_evidence` | The claim is missing one of the required comparison evidences. | It must cite the previous margin, the current margin, and the change. |
| `direction_mismatch` | The claim's stated direction disagrees with the sign of the change evidence. | The direction word does not match the authoritative change; faulty reasoner or tampering. |
| `statement_mismatch` | The claim's prose differs from the deterministic re-rendering of its structured values. | Displayed text drifted from the verified numbers; the verifier re-renders and rejects drift. |
| `no_claims` | The reasoner produced no claims. | Nothing to publish; a faulty or empty reasoner. |
| `incomplete_lineage` | Evidence lacks a calculation or source facts, a calculation records no input facts, or the evidence's source facts differ from the calculation's inputs. | Broken lineage chain; internal defect or tampering. |
| `unknown_calculation` | Evidence cites a calculation ID not present in the run. | Dangling calculation reference. |
| `evidence_calc_mismatch` | Evidence value/unit differs from the calculation it cites. | Evidence was altered relative to its calculation. |
| `missing_source_fact` | A calculation references a fact ID that does not exist. | Dangling fact reference. |
| `artifact_mismatch` | A fact references a different source artifact than the run's. | Fact provenance points outside the run's artifact. |

The evidence-level codes (`incomplete_lineage`, `unknown_calculation`,
`evidence_calc_mismatch`, `missing_source_fact`, `artifact_mismatch`) are raised
during the lineage pass and mark the offending evidence `rejected`; any claim
that cites rejected evidence then also fails, typically with
`evidence_not_verified`.

## Expected errors and recovery

Some conditions are hard errors rather than verification failures: they stop the
run before it completes, print `Error: <message>` on stderr, persist nothing,
and exit `1`.

| Condition | What it means | Recovery |
| --- | --- | --- |
| Unknown ticker | The symbol is not in the SEC ticker map (`ticker '...' was not found in the SEC EDGAR ticker map`). | Check the symbol. Use `DEMO` for the offline example. |
| SEC unreachable | An SEC endpoint could not be reached or returned an HTTP error (`could not reach SEC EDGAR (...)` / `SEC EDGAR returned HTTP ...`). | Retry when connectivity is restored. Network is needed only at fetch time; existing runs replay offline. |
| No comparable quarters | No two year-over-year comparable quarters (with both revenue and operating income) exist as of the date (`could not find two year-over-year comparable quarters ...`). | Rerun with a later as-of date so more filings are available. |
| No quarterly operating income | The company filed no quarterly `OperatingIncomeLoss` facts on or before the date. | Choose a later as-of date, or a company that reports quarterly operating income. |
| Invalid run ID (replay) | The run ID does not match `RUN-YYYYMMDD-NNN`. | Correct the run ID format. |
| Unknown run (replay) | No completed run with that ID exists under the state directory. | Confirm the ID and the `--state-dir`/`STRIX_STATE_DIR` you are pointing at. |

## Disclaimers and what they mean

The finding block and `report.txt` end with a disclaimer whose wording depends
on the data source.

!!! warning "Synthetic (DEMO) runs"
    `Synthetic demonstration data — not investment advice.`

    The `DEMO` ticker resolves to a fictional company (`Demonstration Company`)
    whose figures live in a bundled fixture explicitly labelled synthetic. These
    numbers are not real financial data, do not describe any real company, and
    must never be presented as such.

!!! warning "SEC-sourced (EDGAR) runs"
    `Source: SEC EDGAR company facts, as filed. Research prototype output — not investment advice.`

    A real-ticker run reports figures a company actually filed with the SEC,
    taken as filed (earliest-filed value on restatements). The output is still
    research-prototype output and is **not** investment advice. STRIX makes no
    recommendation, places no trades, and offers no view on any security.

## Related pages

- [Interactive mode](interactive-mode.md) — the prompts and the finding block.
- [Research runs](research-runs.md) — following evidence IDs into the lineage.
- [Replay](replay.md) — proving a finding's integrity and reproducibility.
