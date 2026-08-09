# Roadmap

This page is the single place where **planned, not-yet-implemented** work is
described. Nothing here exists in the current version. The
[command reference](../usage/command-reference.md) and the rest of this site
document only what is implemented today; treat anything on this page as intent,
not capability.

!!! warning "Everything below is unbuilt"
    None of these items are present in the code. They are recorded here so the
    architecture's seams are legible, not to imply availability.

## Current scope (for contrast)

Today STRIX answers **one** question — "Is operating profitability
improving?" — over **one** claim type (`profitability_change`), from **two**
connectors (the offline `DEMO` fixture and SEC EDGAR company facts), and
persists runs as local JSON that can be replayed offline. There is no LLM, no
database, no user accounts, and no trading. STRIX is research and decision
support only; it produces no investment advice.

## Planned work

### Schema-constrained LLM reasoner

A future reasoner would call a schema-constrained LLM behind the existing
`Reasoner` protocol (`analyze(spec, evidence) -> list[Claim]`). It would sit
behind the **unchanged** verifier: its output would be treated as untrusted,
every asserted number would still have to be copied verbatim from cited,
verified evidence, and a failed verification would still publish nothing. See
[Adding reasoners](adding-reasoners.md) for the seam it would occupy. No LLM
is called anywhere today.

### More calculations and claim types

Additional calculations in `analytics/` (beyond operating margin and its
percentage-point change) and the new claim types they would support. Each new
claim type needs its own verifier rules — an independent re-derivation
analogous to the current direction-sign and prose-rendering checks — before it
could be certified. See
[Adding calculations](adding-calculations.md#calculations-are-not-claims-the-verifier-boundary).

### More connectors

Further `SourceConnector` implementations behind the existing fetch/parse
split — for example filings **text** (beyond XBRL company facts) and market
data. Each would follow the [connector checklist](adding-connectors.md):
network confined to `fetch`, parsing a pure function of preserved bytes, no
floats, no wall clock in content.

### Durable storage mapping

A mapping of the local JSON run store onto **PostgreSQL** plus **object
storage** for preserved raw artifacts, while keeping the same content-derived
IDs and stage hashes so runs remain replayable. Today the run store is local
JSON files only; no PostgreSQL, object store, or vector/search index is
implemented.

### Multi-company comparison

Research spanning more than one subject in a single run (the current pipeline
is single-subject: one `company_id`, one comparison pair).

### Additional report formats

Output beyond the current plain-text `report.txt` and the terminal finding
block.

### BLKPVNTHR.OS web route

A hosted `/strix` route within BLKPVNTHR.OS. Mentioned only as a future
surface; there is no web application in this repository.

## Known limitations (current, by design)

These are properties of the shipping version, several of them deliberate:

- **One question type.** Only `profitability_change` over operating margin is
  supported end to end.
- **Calendar-quarter labels are display naming.** For EDGAR sources, quarters
  are identified by their exact period **end date** and paired year-over-year
  by date distance (350–378 days). The `YYYY-QN` label is derived from the end
  date's calendar quarter for display only; an off-calendar fiscal year can
  therefore show, for example, `2024-Q4` paired with `2026-Q1`.
- **Earliest-filed values win.** On a restatement, the first-known value is
  kept (the value the market learned first), not the latest amendment. A
  same-day tie breaks by numeric array index. This is intentional
  point-in-time behavior, not a bug.
- **Same-revenue-tag comparability.** Both compared quarters must come from the
  same us-gaap revenue tag; STRIX will not mix, say, `Revenues` in one period
  with `SalesRevenueNet` in the other.
- **No caching of EDGAR data.** Each real-ticker run fetches the full company
  facts document afresh at fetch time. The bytes are preserved per run for
  offline replay, but there is no shared cache across runs.

For the point-in-time semantics behind the EDGAR limitations, see
[Provenance](../architecture/provenance.md).
