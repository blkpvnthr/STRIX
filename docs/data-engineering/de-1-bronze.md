# DE-1 — Data Contracts, Storage, and Immutable Bronze Ingestion

The foundation of the v0.3.0 Financial Intelligence Lakehouse: typed data
contracts, a pluggable storage abstraction, and an immutable, provenance-tracked
Bronze layer. Nothing here fetches from live sources yet (that is DE-2); DE-1 is
the mechanism that preserves whatever raw bytes a connector hands it.

## Design principles (shared with the rest of STRIX)

- Frozen pydantic contracts, closed schemas, Decimal-only values.
- Content-addressed identity + integrity via `strix.canonical` (SHA-256,
  `make_id`), the same hashing the research evidence model uses.
- Atomic, crash-safe writes; **immutability** — raw bytes are never mutated or
  overwritten.
- Every byte is traceable to its origin, so downstream Silver/Gold datasets and
  research observations retain provenance back to the source evidence.

## Modules (`src/strix/lakehouse/`)

| Module | Responsibility |
|---|---|
| `contracts.py` | `DataSource`, `Layer`, `DatasetRef`, `RawArtifact`, `ProvenanceManifest`, `IngestionResult` |
| `storage.py` | `ObjectStore` protocol + `LocalObjectStore` (atomic, immutable, traversal-safe) |
| `bronze.py` | `BronzeIngestor` — preserve raw bytes immutably + write append-only provenance |

## Immutability & provenance model

- A **raw artifact** is content-addressed by `sha256(bytes)` → identical payloads
  deduplicate; writing different bytes to an existing path raises
  `LakehouseIntegrityError`; every write is read-back-verified.
- A **provenance manifest** records one ingestion *event*, keyed by its
  parameters including retrieval time. Re-fetching identical bytes later writes a
  **new** manifest (append-only ledger) while the raw object deduplicates — so the
  history of "when did we see this, from where" is preserved without duplicating
  storage.

## On-disk layout (under the lakehouse root, gitignored)

```
bronze/<source>/<dataset>/<entity>/<partition>/<sha256>.<ext>      # immutable raw
bronze/_manifests/<source>/<dataset>/<ingestion_id>.manifest.json  # append-only
```

Example: `bronze/alpaca/equity_bars_daily/SPY/2026-11-20/<sha256>.json`.

## Idempotency (DE-6/DE-9 acceptance)

Re-running the same ingestion event is a full no-op
(`artifact_written=False, manifest_written=False`); re-fetching at a later time
deduplicates the raw bytes and appends exactly one new provenance entry. No
unexplained duplicate natural keys.

## Tests

`tests/lakehouse/` (14): store idempotency/immutability/traversal, contract
validation + deterministic ids, ingestion write/dedup/re-fetch provenance,
media-type and naive-datetime rejection, and manifest persistence/reload.

## Next (DE-2)

Historical backfill + incremental connectors (Alpaca, SEC EDGAR, FRED, BLS, US
Treasury) that produce the raw bytes this layer preserves.
