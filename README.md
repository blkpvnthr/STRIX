# STRIX
## Structured Traceability, Retrieval, and Intelligence eXtraction

It sounds like a serious intelligence system, and Strix is associated with owls—observation, knowledge, and seeing what others miss.

STRIX is an evidence-grounded research pipeline prototype. Every number it
reports traces through a typed, hash-verified lineage:

```
SourceArtifact -> SourceFact -> CalculationResult -> Evidence -> Claim -> Verified report
```

An interactive CLI turns a research question into a validated specification,
extracts facts from a preserved source artifact, runs deterministic Decimal
calculations, builds citable evidence, constructs a structured claim, verifies
every citation and number, renders a terminal report, and persists a fully
replayable run directory.

**What STRIX is not:** it is a research and decision-support prototype — not an
automated trading system, not a source of investment advice, and (in this
version) not an LLM application. The current reasoner is deterministic Python.

## Data sources

| Ticker | Source | Network |
|---|---|---|
| `DEMO` | Bundled synthetic fixture (fictional "Demonstration Company") | None — fully offline |
| Any real ticker (e.g. `AAPL`) | SEC EDGAR company facts (XBRL, as filed) | Fetch time only |

No API keys or credentials are required. SEC EDGAR is a public API; STRIX
sends the fair-access `User-Agent` header. The fetched raw bytes are preserved
inside each run directory, so **replay never touches the network** — even for
real-data runs.

The DEMO fixture is clearly synthetic and must never be presented as real
financial data.

## Installation

Requires Python 3.11+.

```bash
cd /Users/blkpvnthr/STRIX     # or wherever you cloned the repository
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
strix --help
```

## Usage

Interactive research run (accept the defaults for the offline demo):

```bash
strix                 # or: python -m strix
```

```
Ticker [DEMO]:
> 
Research question [Is operating profitability improving?]:
> 
As-of date [2026-08-08]:
> 
...
Finding

Operating margin increased from 8.4% to 10.1%, an
improvement of 1.7 percentage points.
[EV-..., EV-..., EV-...]

Verification: Passed
Research run: RUN-20260808-001

Synthetic demonstration data — not investment advice.
```

Replay a preserved run (recomputes everything and compares hashes):

```bash
strix replay RUN-20260808-001
```

Run artifacts live in `./research_runs/` by default (gitignored). Override
with `--state-dir PATH` or the `STRIX_STATE_DIR` environment variable.

## How verification works

- All financial math uses `Decimal` — binary floating point is rejected at
  every boundary (models, canonical serialization, JSON parsing).
- Facts, calculations, evidence, and claims carry content-derived IDs
  (`FACT-`, `CALC-`, `EV-`, `CL-` + SHA-256 prefix): identical inputs always
  produce identical IDs.
- The deterministic verifier rejects claims with unknown or unverified
  evidence, wrong subjects, values not knowable by the as-of date, numeric or
  unit mismatches, broken lineage, or a direction that contradicts the
  calculated change. Report prose is re-rendered from verified structured
  values, so the sentence cannot silently disagree with the numbers.
- A hash proves content identity and integrity — not that the content is true.

## The reasoning boundary

`strix.reasoning.base.Reasoner` is a protocol that receives only the research
spec and the curated evidence bundle. The current implementation
(`DeterministicDemoReasoner`) is fixed, auditable Python — **not an LLM**. A
future schema-constrained LLM adapter will plug in behind the same protocol
and the same verifier; no reasoner can bypass verification, calculate
authoritative ratios, or override a failed check.

## Development

```bash
python -m pytest          # test suite (offline; sockets are blocked)
python -m ruff format .   # formatting
python -m ruff check .    # linting
python -m mypy            # strict type checking
```

Documentation (MkDocs Material):

```bash
python -m pip install -r requirements-docs.txt
mkdocs serve              # http://127.0.0.1:8000
```

## Current limitations

- One research question type: operating-margin change between two
  year-over-year quarters.
- EDGAR quarter labels use the calendar quarter of the period end date, an
  approximation for off-calendar fiscal years.
- Restated figures: STRIX deliberately uses the earliest-filed value (the
  first-known figure) for point-in-time honesty.
- No database, object storage, web interface, portfolio integration,
  forecasting, or trading — see the roadmap in `docs/development/roadmap.md`.

Future BLKPVNTHR.OS route name: `/strix`.
# STRIX
