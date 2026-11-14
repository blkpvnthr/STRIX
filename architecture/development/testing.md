# Testing

STRIX ships with a fast, fully offline test suite plus strict static
analysis. Everything runs from the project virtual environment created during
[installation](../getting-started/installation.md); the dev tools come from
the `[dev]` optional dependency group.

## Running the checks

### Test suite

```console
$ python -m pytest
........................................................................ [ 48%]
........................................................................ [ 96%]
.....                                                                    [100%]
149 passed in 0.40s
```

149 tests pass in well under a second because nothing hits the network or a
real clock. `pyproject.toml` sets `testpaths = ["tests"]` and `addopts = "-q"`,
so a bare `python -m pytest` runs the whole suite quietly.

### Linting and formatting

```console
$ python -m ruff check
All checks passed!

$ python -m ruff format --check
```

Ruff is configured in `pyproject.toml` with `line-length = 100` and the rule
set `E, F, W, I, UP, B, C4, SIM, RUF`. The only per-file ignore is `RUF001`
in `tests/test_run_store.py`, where Unicode-lookalike run IDs appear
deliberately to prove the ASCII-only run-ID regex holds.

### Type checking

```console
$ python -m mypy
Success: no issues found in 24 source files
```

mypy runs in `strict` mode with `warn_unreachable = true`, targets Python
3.11, and loads the `pydantic.mypy` plugin so the frozen models are checked
precisely.

## What the suite enforces

The tests are organized by module. Each group pins a specific guarantee.

### Canonical stability and Decimal exactness — `test_canonical.py`

- Key order does not change canonical bytes or hashes.
- `Decimal("84000000")`, `Decimal("84000000.00")`, and `Decimal("8.4E+7")`
  all encode to `"84000000"`; `1E-6` expands to `"0.000001"`; every zero form
  collapses to `"0"`.
- A `float` that "looks like" a `Decimal` raises `TypeError` — it never
  silently produces the same bytes.
- Timezone-aware datetimes normalize to UTC; naive datetimes are rejected;
  non-string mapping keys, `bytes`, and arbitrary objects are rejected.
- `make_id` produces a `PREFIX-<12 hex>` identifier that is stable across
  logically equal payloads.

### Deterministic calculations — `test_profitability.py`

- The demo margins are exactly `0.084000` and `0.101000`; the change is
  exactly `1.7000` percentage points.
- Percentage **points** are asserted to differ from the ~20.2% relative
  percentage change — the unit system exists to keep them distinct.
- Zero and negative revenue, swapped concepts, mismatched periods, and
  same-period change requests all raise `CalculationError`.
- A `float` assigned to a `SourceFact.value` is rejected by the model.
- An astronomical ratio surfaces as a typed `CalculationError`, never a raw
  `decimal.InvalidOperation`.

### Display consistency — `test_formatting.py`

- Rounding artifacts never render as `-0.0`.
- The displayed "from", "to", and difference always add up at one decimal:
  `0.084500 -> 0.101500` renders "from 8.4% to 10.2% … 1.8 percentage points".
- A real but sub-0.1pp change reads "effectively unchanged", never "increased
  … of 0.0 percentage points".

### Evidence and lineage — `test_evidence.py`

- Fact/calculation/evidence IDs are stable across recomputes and do not move
  when a status flips.
- `display_value` is excluded from the evidence ID and the evidence stage
  hash; `known_at` **is** included (shifting a fixture timestamp changes fact
  identity and the facts hash).
- Every evidence record's lineage resolves back to the source artifact, and
  its `known_at` equals the latest of its input facts.

### Verifier rejections — `test_verification.py`

Every `FailureCode` path has a test. This includes the assertion trust
gates that stop a claim from smuggling evidence past the subject / as-of /
verified-status checks:

- `ASSERTION_EVIDENCE_NOT_CITED` — an assertion references evidence the claim
  does not cite.
- `MISSING_ASSERTION` — a required comparison value is not asserted at all
  (including a claim with no assertions, and a partially-asserted claim).

It also covers `UNKNOWN_EVIDENCE`, `SUBJECT_MISMATCH`, `EVIDENCE_AFTER_AS_OF`,
`ASSERTION_VALUE_MISMATCH`, `ASSERTION_UNIT_MISMATCH`, `UNSUPPORTED_UNIT`,
`MISSING_COMPARISON_EVIDENCE`, `DIRECTION_MISMATCH`, `STATEMENT_MISMATCH`,
`NO_CLAIMS`, and the lineage codes `UNKNOWN_CALCULATION`,
`MISSING_SOURCE_FACT`, `ARTIFACT_MISMATCH`, `EVIDENCE_CALC_MISMATCH`,
`INCOMPLETE_LINEAGE`. The publication guard is tested directly: when overall
verification fails, the report publishes **no** claims — not even a
concurrently-verified one — and its summary reads "No verified finding."

### Persistence safety — `test_run_store.py`

- A committed run directory contains exactly the expected artifacts, and the
  raw fixture copy is byte-exact with a matching SHA-256.
- Sequential IDs on the same day (`-001`, `-002`); an existing completed run
  is never overwritten.
- A simulated crash while writing `manifest.json` (the last artifact) leaves
  no visible `RUN-*` directory — only an ignorable hidden staging directory.
- Path-safety: traversal run IDs, and crucially two **Unicode-digit** run IDs
  (`RUN-٢٠٢٦٠٨٠٨-٠٠١`, `RUN-２０２６０８０８-００１`) are rejected by the ASCII-only
  regex; artifact names containing separators or `..` are rejected before any
  filesystem access.

### Replay and tamper detection — `test_replay.py`

- An unmodified run replays with the seven stages all matched, in a fixed
  order.
- Replay is repeatable and ignores wall-clock timestamps (two runs created at
  different times share every deterministic hash and both replay clean).
- Tampering with the raw bytes, `evidence.json`, or `claims.json` is caught;
  an unreadable stage artifact is reported; a manifest whose `source_name` is
  turned into a path (`/etc/hosts`) fails model validation instead of steering
  replay outside the run directory.

### EDGAR parsing edge cases — `test_edgar.py`

All offline, against a committed schema sample with synthetic figures:

- Year-over-year quarter selection, `known_at` = filing date, Decimals never
  float (the sample deliberately contains a JSON float EPS to prove routing).
- Earliest-filed value wins over a later restatement; a **same-day**
  restatement tie-breaks by numeric array index, not lexical locator.
- Annual and YTD durations are excluded; only true ~quarter durations count.
- An **off-calendar** 4-4-5 filer pairs by date distance (a quarter ending
  `2026-01-02` pairs with one ending `2024-12-28`, 370 days earlier), which
  label-based matching would miss.
- Ticker resolution, dot/dash class-share aliases, and a canned-transport
  `fetch` test that asserts the fair-access `User-Agent`.

### Entry points — `test_entrypoints.py`

Both runtime entry points are launched as real subprocesses:
`python -m strix --version` and the installed `strix` console script must both
exit 0 and print `strix …`.

### Suite-wide isolation

`tests/conftest.py` installs an autouse `no_network` fixture that replaces
`socket.socket` and `socket.create_connection` with a guard that raises, so
any accidental network access fails loudly. The reasoner-isolation test
(`test_cli.py`) additionally blocks `open` and `input` while the reasoner
runs.

## Injection seams for deterministic tests

STRIX exposes explicit seams so tests never depend on a terminal, the
network, or the real clock. They are the same seams the CLI uses.

| Seam | Where | Purpose |
| --- | --- | --- |
| `clock` (`Clock` protocol) | `pipeline.run_research`, `cli.main` | Fixed timestamps; `FixedClock` in `conftest.py` pins `created_at`/`checked_at`. |
| `state_dir` | `pipeline.run_research`, `replay.replay_run`, `cli.main` | Writes runs under a `tmp_path`, never the default `./research_runs`. |
| `reasoner` (`Reasoner` protocol) | `pipeline.run_research`, `compute`, `replay_run`, `cli.main` | Substitute a stub reasoner (e.g. the two-claim reasoner in the publication-guard test). |
| `input_fn` | `cli.main` | Feed scripted input lines instead of reading a TTY. |
| `stdout` / `stderr` | `cli.main` | Capture output into `io.StringIO`. |
| `environ` | `cli.main` (and `resolve_state_dir`) | Supply an explicit environment mapping (e.g. `STRIX_STATE_DIR`) instead of the process environment. |
| `fixture_path` | `cli.main`, `run_research`, `DemoConnector` | Point the demo connector at a specific fixture file. |
| `fetched` (`FetchedSource`) | `run_research` | Hand `run_research` already-acquired raw bytes, so an EDGAR run persists and replays with no network (used by `test_edgar.py`). |
| `fetch_url` (monkeypatched) | `sources.edgar` | Canned SEC transport for connector tests. |

Because `compute` is a pure function of `(spec, raw, source_type, source_name,
reasoner, checked_at)`, the same call drives the live pipeline, replay, and
the tests — which is what makes the 149-test suite both fast and
deterministic.
