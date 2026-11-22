# DE-2 — Historical & Incremental Ingestion

Production ingestion pipelines that land authoritative source data in the
immutable DE-1 Bronze layer, with checkpoints, incremental watermarks, idempotent
reruns, rate limiting, bounded retries, partial-failure recovery, missing-window
detection, and source-to-Bronze reconciliation.

## Architecture

```
SourceExtractor (per provider)  --raw bytes-->  IngestionRunner
     |  rate-limited, retrying HttpFetcher             |
     v                                                 v
authoritative endpoint                         BronzeIngestor (DE-1)
                                               + CheckpointStore (watermarks)
                                               + reconciliation / gap detection
```

- **Extractors** (`ingest/extractors.py`) reuse the existing connectors'
  authoritative endpoints/parsers and yield `RawBatch` payloads. Pagination
  (Alpaca `next_page_token`) and per-period batching (Treasury per year) are
  handled here.
- **HttpFetcher** (`ingest/rate_limit.py`) applies a minimum-interval rate limit
  (SEC fair-access safe) and bounded exponential-backoff retries on 429/5xx and
  transient transport errors; transport is injectable for offline tests.
- **IngestionRunner** (`ingest/runner.py`) preserves each batch via the immutable
  Bronze ingestor, advances a persistent checkpoint watermark, recovers from
  partial failures (what was ingested stays; the checkpoint does **not** advance
  so a rerun retries the window), computes coverage/gaps, and reconciles batches
  fetched vs written+deduped.
- **CheckpointStore** (`ingest/checkpoints.py`) holds mutable incremental
  watermarks (outside the immutable object store).

### Raw dedup ≠ observation dedup

Bronze deduplicates **identical raw bytes** (content-addressed). This is *not*
observation-level uniqueness: a provider that returns a volatile response
envelope (e.g. BLS v1) yields new raw bytes on re-fetch and is preserved as a new
immutable snapshot. Observation-level uniqueness (zero duplicate natural keys) is
validated during Silver normalization (DE-3).

## Source coverage

| Source | Dataset | Endpoint | Credentials | Pagination/batching |
|---|---|---|---|---|
| Alpaca | `equity_bars_daily` | Market Data v2 bars | key in headers | `next_page_token` |
| SEC EDGAR | `company_facts` | companyfacts JSON | none (public) | snapshot |
| US Treasury | `daily_treasury_yield_curve` | par-yield XML | none (public) | per year |
| BLS | `timeseries` | public API v1 | none (public) | per series |
| FRED | `series_observations` | fred/series/observations | `FRED_API_KEY` | per series |

FRED's API key is sent only in the live request URL and is **never** written into
provenance (endpoint/params are redacted). Missing optional credentials make only
that provider unavailable (reported), never blocking the others.

## CLI

```bash
strix ingest backfill --start 2020-01-01 [--end YYYY-MM-DD] \
    [--source alpaca|sec_edgar|us_treasury|bls|fred|all] \
    [--symbols SPY,QQQ] [--tickers AAPL] [--series CPIAUCSL,DGS10]
strix ingest incremental [--source ...] [--symbols ...]   # resume from watermark
strix ingest status      # incremental checkpoints / watermarks
strix ingest coverage    # per-dataset manifests, unique artifacts, records, bytes
strix ingest verify      # re-verify every Bronze artifact hash
```

Lakehouse root: `--lakehouse-dir` / `STRIX_LAKEHOUSE_DIR` / `./lakehouse` (gitignored).

## Measured pilot (live, 2026-11-10 .. 2026-11-20)

Small cross-provider pilot before larger backfills:

| Source / dataset | Entities | Records | Raw bytes | Notes |
|---|---|---|---|---|
| alpaca/equity_bars_daily | SPY, QQQ | 18 | 2,076 | 9 trading days each |
| sec_edgar/company_facts | AAPL | — | 3,859,564 | full XBRL snapshot |
| us_treasury/daily_treasury_yield_curve | 2026 | 223 | 345,208 | XML feed entries |
| bls/timeseries | CUUR0000SA0 | 36 | 3,379 | CPI-U |
| fred/series_observations | CPIAUCSL, DGS10, DGS2 | 16 | 2,333 | CPIAUCSL=0 (monthly; window too short) |
| **Total** | **8 entities** | **293** | **~4.2 MB** | 8 raw artifacts, 33 files |

- **Integrity:** `verify` → checked 8, ok 8, failures 0.
- **Idempotent rerun:** 7/8 batches deduped (new=0); BLS re-wrote a new snapshot
  because its v1 response bytes are non-deterministic (observation dedup is DE-3).
- **Incremental:** from watermark 2026-11-20 fetched nothing (2026-11-21/22 are a
  weekend — no trading data), correctly leaving the watermark unchanged.
- **Recovery:** a simulated mid-stream failure preserves already-ingested batches
  and does not advance the checkpoint (covered by unit tests).

## Tests

`tests/lakehouse/test_ingest_*` (26): rate-limit/retry, runner idempotency /
incremental / partial-failure / gap detection, all five extractors (incl. FRED
key redaction), catalog coverage + integrity (incl. corruption detection), and
the CLI. Full suite: 674 passed.
