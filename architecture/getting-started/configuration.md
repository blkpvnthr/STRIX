# Configuration

STRIX has exactly one thing to configure: **where research runs are stored** —
the *state directory*. There are no configuration files and no other
environment variables. Everything else about a run is derived from your inputs
and the source data.

## The state directory

Each research run is written as a `RUN-YYYYMMDD-NNN` directory inside the state
directory. Replay reads runs from the same place. The state directory is
resolved once, at startup, from three sources in strict order of precedence.

| Precedence | Surface | Example |
|---|---|---|
| 1 (highest) | `--state-dir PATH` flag | `strix --state-dir ./runs` |
| 2 | `STRIX_STATE_DIR` environment variable | `export STRIX_STATE_DIR=/data/strix-runs` |
| 3 (default) | Built-in default | `./research_runs` |

This is exactly the logic in `run_store.resolve_state_dir`: a non-empty
`--state-dir` wins; otherwise a non-empty `STRIX_STATE_DIR` is used; otherwise
the path falls back to `research_runs` relative to the current working
directory.

!!! note "Empty values fall through"
    An empty string does not count as "set." If `--state-dir` is empty the
    environment variable is consulted, and if that is empty too the default
    applies.

### The `--state-dir` flag

`--state-dir` is accepted both on the root command (before the run starts) and
on the `replay` subcommand, with the same default described in `strix --help`:

```bash
# Write a DEMO/EDGAR run into ./runs
strix --state-dir ./runs

# Replay a run stored in ./runs
strix replay RUN-20260809-001 --state-dir ./runs
```

To replay a run, point `--state-dir` at the directory that *contains* the
`RUN-...` directory — the same directory you wrote it to.

### The `STRIX_STATE_DIR` environment variable

Set the environment variable to change the default for every command in the
shell session without repeating the flag:

```bash
export STRIX_STATE_DIR=/data/strix-runs
strix                     # writes into /data/strix-runs
strix replay RUN-20260809-001   # reads from /data/strix-runs
```

A `--state-dir` flag still overrides the variable for that single invocation.

### The default: `./research_runs`

With neither the flag nor the variable set, runs land in `./research_runs`
relative to your current working directory. This directory is gitignored, so
runs are never committed. It is created automatically the first time a run is
persisted.

## What is *not* configurable

- **No config files.** STRIX reads no `.strixrc`, `config.toml`,
  `pyproject.toml` section, or dotfile at runtime.
- **No other environment variables.** `STRIX_STATE_DIR` is the only variable
  STRIX consults.
- **No credentials or keys.** SEC EDGAR needs none; there is nothing to store.

For a reference entry on the variable and flag, see
[Environment variables](../reference/environment-variables.md). For how runs
are named, written, and located inside the state directory, see
[Research runs](../usage/research-runs.md).
