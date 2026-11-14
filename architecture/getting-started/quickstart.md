# Quickstart

This walkthrough runs one research end to end on bundled synthetic data,
inspects the run it produced, replays it to prove the result reproduces exactly,
and then shows the same flow against a real ticker from SEC EDGAR.

If you have not installed STRIX yet, start with [Installation](installation.md).
Activate your virtual environment first so the `strix` command is on your
`PATH`.

!!! warning "Synthetic data — not investment advice"
    The DEMO ticker resolves to a bundled fixture for a fictional
    "Demonstration Company." Every figure it reports is invented and must never
    be presented as real financial data. STRIX produces no investment advice
    and cannot place trades.

## 1. Run the DEMO research

Start the interactive CLI:

```bash
strix
```

STRIX prompts for a ticker, a research question, and an as-of date, each with a
default shown in brackets. Press **Enter** at every prompt to accept the
defaults (DEMO, the operating-profitability question, today's date), and **Y**
to proceed. A real session looks like this:

```text
STRIX — Structured Traceability, Retrieval, and Intelligence eXtraction
Evidence-grounded research prototype

Ticker [DEMO]:
> Research question [Is operating profitability improving?]:
> As-of date [2026-08-09]:
> 
Research scope

  Company: Demonstration Company
  Ticker: DEMO
  Question: Is operating profitability improving?
  As-of date: August 9, 2026
  Historical periods: 2025-Q2 and 2026-Q2
  Data source: Synthetic bundled fixture

Proceed? [Y/n]: 
[1/6] Preserving source artifact........ complete
[2/6] Validating source facts........... complete
[3/6] Calculating operating margins..... complete
[4/6] Building evidence................. complete
[5/6] Constructing structured claim..... complete
[6/6] Verifying claim................... passed

Finding

Operating margin increased from 8.4% to 10.1%, an
improvement of 1.7 percentage points.
[EV-9d33ded8a427, EV-649d8a693225, EV-d1e9faaf6787]

Verification: Passed
Research run: RUN-20260809-001

Synthetic demonstration data — not investment advice.
exit_code=0
```

A few things to read from that output:

- The six pipeline stages run in order; the last, **Verifying claim**, reports
  `passed`. A run whose verification fails publishes **no** finding and exits
  with status `1`.
- The finding cites three evidence IDs (`EV-...`). These are content-derived
  identifiers: the same inputs always produce the same IDs.
- **1.7 percentage points** is the change in the margin *level* (10.1% − 8.4%),
  not a percentage change. STRIX reports percentage points.
- **Research run: RUN-20260809-001** names the run directory that was just
  written. Run IDs identify an execution (`RUN-YYYYMMDD-NNN`), not content.

The trailing `exit_code=0` is the shell exit status, not text printed by STRIX;
`0` means the verification passed.

!!! note "Dates in this guide"
    The as-of date defaults to today, so your prompts and run ID will show the
    current date rather than the `2026-08-09` captured above. The finding for
    DEMO is fixed regardless of date.

## 2. Look at the run directory

Every run is persisted atomically under the state directory — `./research_runs`
by default. The DEMO run above created:

```text
research_runs/
└── RUN-20260809-001/
    ├── spec.json            # the validated research specification
    ├── manifest.json        # per-stage content hashes (written last)
    ├── raw/
    │   └── demo-company-facts.json   # exact preserved source bytes
    ├── facts.json           # extracted source facts
    ├── calculations.json    # deterministic Decimal calculations
    ├── evidence.json        # citable evidence
    ├── claims.json          # the structured claim
    ├── verification.json    # the verifier's decision
    └── report.txt           # the rendered terminal report
```

The `report.txt` is the finding as a standalone document:

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

The `raw/` copy is the source document exactly as it was obtained, which is what
makes replay possible offline. For a field-by-field tour of these files, see
[Research runs](../usage/research-runs.md) and
[Artifact formats](../reference/artifact-formats.md).

## 3. Replay the run

Replay recomputes the entire pipeline from the stored spec and preserved raw
bytes, then compares every deterministic hash against the run's manifest. It
never touches the network. Pass the run ID that STRIX reported:

```bash
strix replay RUN-20260809-001
```

```text
Replay verification

  Source artifact hash........ matched
  Input hash.................. matched
  Source facts hash........... matched
  Calculations hash........... matched
  Evidence hash............... matched
  Claims hash................. matched
  Verification status......... matched

Result: Deterministic replay passed
exit_code=0
```

All seven rows must match for a run to be reproducible. A mismatch on any row
means the stored artifacts and the recomputation disagree — replay then reports
a failure and exits `1`. A matched hash proves content **identity and
integrity**, not that the content is factually true. See
[Replay](../usage/replay.md) for the full comparison rules and what a tampered
run looks like.

## 4. Research a real ticker (SEC EDGAR)

Any ticker other than `DEMO` fetches public company facts from SEC EDGAR at run
time. No API key or account is needed; STRIX sends the fair-access `User-Agent`
header. Start `strix` again and enter a real ticker at the first prompt:

```text
$ strix
STRIX — Structured Traceability, Retrieval, and Intelligence eXtraction
Evidence-grounded research prototype

Ticker [DEMO]:
> AAPL
Research question [Is operating profitability improving?]:
> 
As-of date [2026-08-09]:
> 
Fetching SEC EDGAR company facts for AAPL...

Research scope

  Company: Apple Inc.
  Ticker: AAPL
  Question: Is operating profitability improving?
  As-of date: August 9, 2026
  Historical periods: 2025-Q2 and 2026-Q2
  Data source: SEC EDGAR company facts (live fetch, preserved per run)

Proceed? [Y/n]: 
[1/6] Preserving source artifact........ complete
[2/6] Validating source facts........... complete
[3/6] Calculating operating margins..... complete
[4/6] Building evidence................. complete
[5/6] Constructing structured claim..... complete
[6/6] Verifying claim................... passed

Finding

Operating margin increased from 30.0% to 32.6%, an
improvement of 2.6 percentage points.
[EV-b38554906baa, EV-efc0b9ba93b5, EV-b25cb97df239]

Verification: Passed
Research run: RUN-20260809-001

Source: SEC EDGAR company facts, as filed. Research prototype output — not investment advice.
```

!!! note "Live output varies"
    The numbers above are from one capture. Real-ticker output depends on the
    filings SEC EDGAR has published as of the date you run it. STRIX uses only
    facts filed on or before your as-of date and takes the earliest-filed value
    on restatements, so your figures for AAPL may differ from those shown here.

Because the fetched bytes are preserved in the run directory, replaying an
EDGAR run is identical to replaying the DEMO run — and equally offline:

```bash
strix replay RUN-20260809-001
```

## Where to go next

- [Interpreting results](../usage/interpreting-results.md) — how to read the
  finding, the evidence IDs, and percentage points.
- [Configuration](configuration.md) — choose where runs are stored.
- [Command reference](../usage/command-reference.md) — every command and option.
