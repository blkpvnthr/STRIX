# Installation

STRIX installs as an editable Python package into a virtual environment. The
steps below are copy-pasteable. Before you start, confirm you meet the
[Requirements](requirements.md) (Python 3.11+).

## macOS and Linux

Run these from the repository root. **Substitute your own clone path** for
`/Users/blkpvnthr/STRIX` on the first line.

```bash
cd /Users/blkpvnthr/STRIX          # substitute your own clone path
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
strix --help
```

- `python3 -m venv .venv` creates an isolated environment in `.venv/`
  (gitignored).
- `source .venv/bin/activate` activates it; your shell prompt shows `(.venv)`.
- `python -m pip install -e ".[dev]"` installs STRIX in editable mode with the
  development extras (`pytest`, `ruff`, `mypy`). For a runtime-only install,
  drop the extra: `python -m pip install -e .`.
- The quotes around `".[dev]"` matter in zsh, which otherwise treats the square
  brackets as a glob.

## Windows (PowerShell)

The commands are identical apart from virtual-environment activation.
**Substitute your own clone path** on the first line.

```powershell
cd C:\path\to\STRIX
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
strix --help
```

If PowerShell blocks the activation script, allow it for the current user with
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then run
`.venv\Scripts\Activate.ps1` again.

## Verify the install

`strix --help` confirms the console entry point is on your `PATH`. It prints:

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

The same program is also reachable as a module:

```bash
python -m strix --help
```

Check the version:

```bash
strix --version
# strix 0.1.0
```

!!! note "Where runs are stored"
    By default, research runs are written to `./research_runs` in the current
    working directory (gitignored). You can change this per command or via an
    environment variable — see [Configuration](configuration.md).

## Documentation tooling (optional)

The docs site is built with MkDocs Material. Its dependencies are separate from
the application and are listed in `requirements-docs.txt`:

```bash
python -m pip install -r requirements-docs.txt
mkdocs serve
```

`mkdocs serve` builds the site and serves it locally at
<http://127.0.0.1:8000> with live reload.

## Next steps

Run your first research and replay it end to end in the
[Quickstart](quickstart.md).
