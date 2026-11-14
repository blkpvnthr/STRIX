# Environment variables

STRIX reads **exactly one** environment variable. It is optional, holds no secret, and only
controls where run artifacts are written.

| Variable | Purpose | Default | Precedence |
| --- | --- | --- | --- |
| `STRIX_STATE_DIR` | Directory for research run artifacts (the [state directory](glossary.md#state-directory)). | `./research_runs` (relative to the working directory; gitignored) | Below the `--state-dir` flag, above the built-in default. |

## Resolution order

The state directory is chosen by `run_store.resolve_state_dir` in this order:

1. The `--state-dir PATH` command-line flag, if given.
2. The `STRIX_STATE_DIR` environment variable, if set and non-empty.
3. The built-in default, `research_runs`, in the current working directory.

```python
def resolve_state_dir(cli_value: str | None, environ: Mapping[str, str] | None = None) -> Path:
    """State directory precedence: --state-dir flag, STRIX_STATE_DIR, default."""
    if cli_value:
        return Path(cli_value)
    env = os.environ if environ is None else environ
    from_env = env.get(STATE_DIR_ENV_VAR)  # "STRIX_STATE_DIR"
    if from_env:
        return Path(from_env)
    return DEFAULT_STATE_DIR  # Path("research_runs")
```

So a `--state-dir` argument always wins over `STRIX_STATE_DIR`, and either wins over the default.
The same resolution applies to `strix replay`, so a run must be replayed against the state directory
that holds it. See [Configuration](../getting-started/configuration.md) and
[Command reference](../usage/command-reference.md).

```console
$ export STRIX_STATE_DIR=/data/strix-runs
$ strix                     # writes runs under /data/strix-runs
$ strix --state-dir ./tmp   # --state-dir overrides the variable; writes under ./tmp
```

## No other variables, no secrets

- `STRIX_STATE_DIR` is the **only** environment variable STRIX reads. No other variable changes any
  behavior.
- **No environment variable holds a secret.** STRIX has no API keys, tokens, credentials, or
  passwords. The SEC EDGAR connector needs no credentials, and the bundled `DEMO` fixture is fully
  offline.

!!! note "The SEC User-Agent is a code constant, not an environment variable"
    The SEC fair-access policy requires a descriptive `User-Agent` header on requests to EDGAR. In
    STRIX that header is a **constant in the source code** — `USER_AGENT` in
    [`src/strix/sources/edgar.py`](../development/adding-connectors.md):

    ```python
    USER_AGENT = "STRIX/0.1 research prototype (contact@quantumquant.trade)"
    ```

    It is not read from the environment and cannot be overridden by one. Changing it means editing
    the source.

## Related

- [Configuration](../getting-started/configuration.md) — the `--state-dir` flag and default layout.
- [Artifact formats](artifact-formats.md) — what lives inside the state directory.
- [Glossary: state directory](glossary.md#state-directory).
