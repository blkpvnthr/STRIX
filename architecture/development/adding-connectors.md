# Adding connectors

A **connector** teaches STRIX where to get raw source bytes and how to turn
them into a normalized document. Two connectors exist today — the offline
demo fixture and SEC EDGAR company facts — and both implement the same small
contract in `sources/`.

!!! warning "Only two connectors exist"
    This page describes the extension seam. As of this version the only
    implemented connectors are `sources/demo.py` and `sources/edgar.py`.
    Additional connectors are future work (see [Roadmap](roadmap.md)); do not
    read this page as a claim that any others exist.

## The contract

Everything a connector touches is defined in `sources/base.py`. Three frozen
models and one protocol:

**`SourceConnector`** — the protocol a connector satisfies. It has exactly one
method:

```python
class SourceConnector(Protocol):
    def fetch(self, ticker: str) -> FetchedSource: ...
```

`fetch` **acquires** raw bytes. It is the only place a connector may do I/O.
Parsing happens elsewhere, as a pure function.

**`FetchedSource`** — raw bytes plus the identity needed to preserve and
describe them:

| Field | Meaning |
| --- | --- |
| `raw: bytes` | The exact bytes to preserve under `raw/` in the run directory. |
| `source_type: SourceType` | Which parser branch handles these bytes. |
| `source_name: str` | File name of the preserved copy (validated: no separators, no traversal). |
| `description: str` | One line for the CLI scope summary. |
| `disclaimer: str` | The report disclaimer appropriate to this source. |

**`SourceDocument`** — the connector's normalized view of one company: its
`company_id`, `ticker`, `company_name`, `source_type`, a content-derived
`source_version`, a `synthetic` flag, a `created_at` (deterministic, derived
from content), the role-ordered `periods` tuple `(previous, current)`, and the
tuple of `NormalizedFact`s.

**`NormalizedFact`** — one observation before fact-ID assignment: `concept`,
`value` (a `Decimal`; `float` is rejected by a `BeforeValidator`), `unit`,
`observation_period`, `known_at` (an aware datetime — a fixture timestamp or a
filing date, never a wall clock), and a `locator` (a JSON pointer into the raw
source).

## Fetch versus parse: why they are separate

The pipeline is split deliberately:

- **Fetch** (`SourceConnector.fetch`) may use the network, credentials, files
  — whatever it takes to obtain bytes. It runs once, before the deterministic
  core.
- **Parse** (`parse_source`) is a **pure function of the preserved bytes plus
  the research parameters**. Identical `(source_type, raw, ticker, as_of_date)`
  always yields an identical `SourceDocument`.

`sources/__init__.py` wires the two together:

```python
def parse_source(source_type, raw, *, ticker, as_of_date) -> SourceDocument:
    if source_type is SourceType.SYNTHETIC_FIXTURE:
        return parse_demo_fixture(raw)
    if source_type is SourceType.SEC_EDGAR_COMPANYFACTS:
        return parse_companyfacts(raw, ticker=ticker, as_of_date=as_of_date)
    raise SourceError(f"unsupported source type: {source_type}")


def connector_for(ticker: str) -> SourceConnector:
    if ticker.upper() == DEMO_TICKER:
        return DemoConnector()
    return EdgarConnector()
```

This split is what makes **replay always offline**. Replay never calls
`fetch`; it reads the preserved bytes back and calls `parse_source` again. If
parsing were not a pure function of those bytes, a replayed run could diverge
from the original.

## Walk-through: the EDGAR connector

`sources/edgar.py` is the reference implementation of a networked connector.

### Fetch (`EdgarConnector.fetch`)

`fetch` resolves the ticker to a CIK via the SEC ticker map, then downloads
the company-facts JSON. Both requests go through `fetch_url`, which is the
**only** networked function in the codebase. It sends the SEC fair-access
`User-Agent` (`STRIX/0.1 research prototype (contact@quantumquant.trade)`) —
no API key is used. `fetch` returns a `FetchedSource` carrying the raw
company-facts bytes and a `source_name` like `companyfacts-CIK0001234567.json`.

### Parse (`parse_companyfacts`)

`parse_companyfacts(raw, *, ticker, as_of_date)` is pure. Its important
disciplines are exactly what a new connector must reproduce:

- **No floats.** JSON is decoded with `parse_float=Decimal`, so numeric values
  become `Decimal` and never pass through binary floating point.
- **`known_at` discipline.** Each fact's `known_at` is its SEC `filed` date.
  Only facts filed on or before `as_of_date` are considered, which is what
  makes the point-in-time guarantee hold.
- **Earliest-filed wins.** When several filings restate the same quarter, the
  first-known value is kept; a same-day tie breaks by the numeric array index.
- **Content-derived identity.** `source_version` encodes the chosen revenue
  tag and the filed-through date; `created_at` is the max `known_at` of the
  chosen facts. Nothing here depends on the wall clock.
- **Validation.** Missing `entityName`/`cik`, absent `us-gaap` facts, no
  quarterly operating income, or no year-over-year comparable pair each raise
  a typed `SourceError` rather than returning a malformed document.

The comparability rule is worth calling out: both quarters must come from the
**same** revenue tag, tried in priority order
(`RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`,
`SalesRevenueNet`, `RevenueFromContractWithCustomerIncludingAssessedTax`) plus
`OperatingIncomeLoss`. See [Provenance](../provenance.md) for the
full point-in-time semantics.

### Selection

`connector_for` routes `DEMO` to the offline fixture and every other ticker to
EDGAR. The demo connector (`sources/demo.py`) shows the offline end of the
contract: its `fetch` reads bundled bytes with no network, and its parser
refuses any fixture that does not declare `synthetic: true`.

## Checklist for a new connector

To add a connector for a new source type, in order:

1. **Add a `SourceType` value** in `models.py` (the enum is a bounded
   vocabulary; every source type is explicit).
2. **Write the parser** as a pure function `parse_<source>(raw, …) ->
   SourceDocument`. Decode JSON with `parse_float=Decimal` (or otherwise
   guarantee no `float` ever reaches a model). Assign each `NormalizedFact` a
   content-derived `known_at` and a `locator`; never read the wall clock.
3. **Add a branch to `parse_source`** in `sources/__init__.py` for the new
   `SourceType`.
4. **Write the connector** implementing `SourceConnector.fetch`, returning a
   `FetchedSource` with a safe `source_name`, a `description`, and a
   `disclaimer`. Confine all I/O to `fetch`.
5. **Route to it** — either extend `connector_for`, or (as the CLI does for
   EDGAR) select it where the ticker is acquired.
6. **Write offline tests with canned bytes.** Follow `tests/test_edgar.py`:
   store a small sample under `tests/data/`, monkeypatch the transport, and
   assert the parser output. The suite-wide socket guard will fail any test
   that accidentally reaches the network.

### Rules a connector must not break

- **No `float` in content.** Values are `Decimal`; the models reject floats,
  and canonical serialization forbids them entirely.
- **No wall clock in content.** `known_at`, `created_at`, and `source_version`
  must be derived from the source, not from "now" — otherwise the artifact ID
  and stage hashes would change on every run and replay would fail.
- **Parsing must be a pure function of the preserved bytes** (plus the fixed
  research parameters). This is the property replay depends on.

Once these hold, the rest of the pipeline — fact IDs, calculations, evidence,
claims, verification, persistence, and replay — works unchanged, because it
only ever sees a `SourceDocument`.
