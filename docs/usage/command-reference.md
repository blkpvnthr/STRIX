# Command reference

This page documents every command and option that STRIX actually implements,
generated from the argparse parser in `cli.py` and the program's own `--help`
output. There are exactly two invocations: the root command (interactive
research) and the `replay` subcommand. Planned commands are not documented
here — see the [roadmap](../development/roadmap.md).

Two entry points invoke the same code:

```bash
strix           # console-script entry point
python -m strix # module entry point
```

## `strix` (root command)

### Synopsis

```text
strix [-h] [--version] [--state-dir PATH] {replay} ...
```

Run with no subcommand to start the [interactive research flow](interactive-mode.md).

### Verbatim help

```text
usage: strix [-h] [--version] [--state-dir PATH] {replay} ...

STRIX — Structured Traceability, Retrieval, and Intelligence eXtraction.
Evidence-grounded research CLI.

positional arguments:
  {replay}
    replay          replay a preserved run and verify its deterministic hashes

options:
  -h, --help        show this help message and exit
  --version         show program's version number and exit
  --state-dir PATH  directory for research run artifacts (default:
                    ./research_runs, or the STRIX_STATE_DIR environment
                    variable)

The DEMO ticker runs entirely offline on bundled synthetic data. Real tickers
fetch public filings from SEC EDGAR (no credentials; network needed at fetch
time only). STRIX produces no investment advice and cannot place trades.
```

### Options

| Option | Argument | Default | Purpose |
| --- | --- | --- | --- |
| `-h`, `--help` | — | — | Print help and exit `0`. |
| `--version` | — | — | Print `strix <version>` and exit `0`. |
| `--state-dir` | `PATH` | `./research_runs`, or `$STRIX_STATE_DIR` | Directory that holds run artifacts. |

`--state-dir` is optional. Its precedence is: the flag value, then the
`STRIX_STATE_DIR` environment variable, then the default `./research_runs`
(relative to the working directory). See
[Configuration](../getting-started/configuration.md) and
[Environment variables](../reference/environment-variables.md).

### `--version`

```console
$ strix --version
strix 0.1.0
```

### Example: an offline research run

```console
$ strix
STRIX — Structured Traceability, Retrieval, and Intelligence eXtraction
Evidence-grounded research prototype

Ticker [DEMO]:
> Research question [Is operating profitability improving?]:
> As-of date [2026-08-09]:
> 
Research scope

  Company: Demonstration Company
  Ticker: DEMO
  ...

Proceed? [Y/n]: 
[1/6] Preserving source artifact........ complete
...
[6/6] Verifying claim................... passed

Finding

Operating margin increased from 8.4% to 10.1%, an
improvement of 1.7 percentage points.
[EV-9d33ded8a427, EV-649d8a693225, EV-d1e9faaf6787]

Verification: Passed
Research run: RUN-20260809-001

Synthetic demonstration data — not investment advice.
```

The full transcript, including the EDGAR variant, is in
[Interactive mode](interactive-mode.md).

### Exit behavior

| Exit code | Meaning |
| --- | --- |
| `0` | Run completed and verification passed; or the user cancelled (`n`/`no` or EOF at a prompt). |
| `1` | Verification failed, or a `StrixError` was raised (bad source, unreachable network, invalid/unknown run, calculation error). |
| `130` | Interrupted with Ctrl-C. |
| `2` | argparse usage error (unknown flag, missing argument). Emitted by argparse itself, before STRIX runs. |

A verification failure still produces a completed (failed) run directory. Hard
errors (`StrixError` and its subclasses) print `Error: <message>` to stderr,
persist nothing, and exit `1`.

## `strix replay`

Recompute a preserved run from its stored spec and raw source bytes, then
compare every deterministic hash against the run's manifest. Replay never
touches the network. See [Replay](replay.md) for the full explanation of what
is compared.

### Synopsis

```text
strix replay [-h] [--state-dir PATH] RUN-ID
```

### Verbatim help

```text
usage: strix replay [-h] [--state-dir PATH] RUN-ID

Recompute a preserved research run from its stored spec and raw source bytes,
then compare every deterministic hash with the run's manifest. Replay never
touches the network.

positional arguments:
  RUN-ID            run identifier, e.g. RUN-20260808-001

options:
  -h, --help        show this help message and exit
  --state-dir PATH  directory containing the run (same default as the root
                    command)
```

### Arguments

| Argument | Required | Purpose |
| --- | --- | --- |
| `RUN-ID` | yes | The run to replay, e.g. `RUN-20260809-001`. Must match `RUN-YYYYMMDD-NNN`. |
| `--state-dir PATH` | no | Directory containing the run (same default as the root command). |

### Example: a passing replay

```console
$ strix replay RUN-20260809-001
Replay verification

  Source artifact hash........ matched
  Input hash.................. matched
  Source facts hash........... matched
  Calculations hash........... matched
  Evidence hash............... matched
  Claims hash................. matched
  Verification status......... matched

Result: Deterministic replay passed
```

### Exit behavior

| Exit code | Meaning |
| --- | --- |
| `0` | Every stage matched — deterministic replay passed. |
| `1` | One or more stages mismatched (`Result: Deterministic replay FAILED`), or the run could not be loaded (invalid run ID, unknown run, unreadable manifest/spec). |
| `2` | argparse usage error (e.g. `RUN-ID` omitted). |

## Common errors

STRIX surfaces expected failures as a single line on stderr in the form
`Error: <message>` (never a traceback) and exits `1`. The messages below are
the exact strings the program emits.

### Unknown ticker

Raised by the EDGAR connector when a symbol is not in the SEC ticker map:

```text
Error: ticker 'ZZZZ' was not found in the SEC EDGAR ticker map
```

### Network failure

Raised when an SEC endpoint cannot be reached or returns an HTTP error:

```text
Error: could not reach SEC EDGAR (https://www.sec.gov/files/company_tickers.json): <urllib reason>
Error: SEC EDGAR returned HTTP 403 for https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json
```

The SEC fair-access policy requires a descriptive `User-Agent`; STRIX sends
one automatically. The network is used only at fetch time — once the raw bytes
are preserved in the run directory, replay and re-analysis are fully offline.

### No comparable quarters

Raised by the EDGAR parser when it cannot find two year-over-year comparable
quarters (both revenue and operating income) as of the chosen date:

```text
Error: could not find two year-over-year comparable quarters with both revenue and operating income for Apple Inc. as of 2020-01-01
```

Recovery: rerun with a later as-of date so more filings are available.

### Invalid run ID (replay)

Raised when a run ID does not match `RUN-YYYYMMDD-NNN`:

```text
Error: invalid run ID 'run-1'; expected the form RUN-YYYYMMDD-NNN
```

### Unknown run (replay)

Raised when no completed run directory with that ID exists under the state
directory:

```text
Error: no completed run named 'RUN-20260809-009' in /path/to/research_runs
```

See [Interpreting results](interpreting-results.md) for verification-failure
codes and their recovery, and [Research runs](research-runs.md) for the layout
of a run directory.
