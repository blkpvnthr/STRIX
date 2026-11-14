# Requirements

STRIX is a self-contained Python CLI. A default DEMO run needs nothing beyond
the interpreter and the package itself — no database, no API key, no cloud
account, and no network connection. Network access is used only when you
research a real ticker against SEC EDGAR.

## Python

STRIX requires **Python 3.11 or newer** (`requires-python = ">=3.11"` in
`pyproject.toml`). The code uses 3.11-era typing and standard-library features
and is type-checked under `mypy --strict`.

The only runtime dependency is **`pydantic>=2.5`**. The optional `dev`
extra adds `pytest`, `ruff`, and `mypy`; documentation builds add `mkdocs` and
`mkdocs-material` (see [Installation](installation.md)). Nothing else is pulled
in — there is no database driver, HTTP framework, or cloud SDK, because STRIX
does not use any of those.

## Operating systems

| Platform | Status | Notes |
|---|---|---|
| macOS | Fully supported | Primary development platform. |
| Linux | Fully supported | |
| Windows | Supported | The `strix` commands work in PowerShell. Virtual-environment activation differs (see below). |

### Windows notes

All STRIX commands (`strix`, `strix replay ...`, `python -m strix`) run
unchanged in PowerShell. The only platform difference is how you activate the
virtual environment:

```powershell
.venv\Scripts\Activate.ps1
```

On Windows the interpreter is usually invoked as `python` rather than
`python3`. See [Installation](installation.md) for a complete PowerShell block.

## Git

Git is **optional**. You need it only to clone the repository or to work on
STRIX itself. Once you have the source on disk, installation and every command
work without git.

## Network

| Activity | Network required? |
|---|---|
| Installing the package | Yes — to download `pydantic` (and dev/docs tools) from PyPI. |
| Running the **DEMO** ticker | **No** — DEMO uses a bundled synthetic fixture and runs fully offline. |
| Researching a **real ticker** (e.g. `AAPL`) | Yes — STRIX fetches company facts from SEC EDGAR at fetch time. |
| **Replaying** any run (`strix replay ...`) | **No** — replay recomputes from raw bytes preserved in the run directory and never touches the network. |

SEC EDGAR is a public API. No credentials or API key are used; STRIX sends the
fair-access `User-Agent` header the SEC requests. The bytes fetched for a real
ticker are preserved inside that run's directory, which is why replay is always
offline — even for real-data runs.

!!! warning "Synthetic data"
    The DEMO ticker resolves to a bundled fixture for a fictional
    "Demonstration Company." Its figures are invented and must never be
    presented as real financial data. STRIX produces no investment advice and
    cannot place trades.

## Disk

STRIX is small, but a real-ticker run preserves the full source document it
fetched, so run directories vary in size.

| Item | Approximate size |
|---|---|
| Package source | Small (a few tens of KB). |
| Virtual environment (with `pydantic`) | A few tens of MB. |
| A **DEMO** run directory | A few KB — the bundled fixture is ~1.4 KB, plus small JSON artifacts. |
| An **EDGAR** run directory | Larger — it preserves the full SEC company-facts JSON, typically **1–10 MB per run**. |

Run directories accumulate under the state directory (`./research_runs` by
default; see [Configuration](configuration.md)). If you run many real-ticker
researches, each keeps its own copy of the fetched filing document, so plan
disk accordingly.

## What is *not* required

STRIX in this version has no database, no object storage, no message queue, no
web server, and no LLM API integration. You do not need to provision or
configure any external service to install or use it.

!!! note "Future production features"
    Some capabilities on the [roadmap](../development/roadmap.md) — persistent
    storage in a database, object storage for preserved documents, and a
    schema-constrained LLM reasoner adapter — *would* eventually require
    external services (a database, object storage, and an LLM API,
    respectively). None of that is implemented or required today, and those are
    documented only as future work.
