# DE-3 — Silver Normalization & Data Quality

Deterministic Bronze→Silver transformation: typed, Decimal-safe, partitioned
Parquet with full lineage, observation-level deduplication, financial data-quality
gates, and source-to-Silver reconciliation. Transforms are a **full recompute from
the immutable Bronze layer**, so reruns are idempotent and prior research stays
reproducible (same Bronze → same Silver).

## Architecture

```
Bronze artifacts + provenance (DE-1/DE-2)
   -> normalizer (per source)        typed observation rows + source_locator
   -> engine: attach lineage         natural_key, bronze_artifact_id, retrieved_at
   -> quality gates                  quarantine with machine-readable reason codes
   -> observation-level dedup        collapse identical, quarantine conflicts, keep revisions
   -> reconciliation                 extracted = accepted + duplicates + quarantined + excluded
   -> atomic publish (if balanced)   partitioned Parquet + versioned publication manifest
```

Modules (`src/strix/lakehouse/silver/`): `schemas.py`, `normalizers.py`,
`quality.py`, `dedup.py`, `publish.py`, `engine.py`, `models.py`, `cli.py`.
Treasury XML is parsed with `defusedxml` (XXE/billion-laughs hardening).

## Datasets & schemas (versioned PyArrow)

| Dataset | Grain | Natural key | Partition | Value type | Revision handling |
|---|---|---|---|---|---|
| `alpaca_equity_bars_daily` | 1 bar / (symbol, timeframe, session_date) | source_feed, symbol, timeframe, session_date | `symbol` | decimal128(18,6) | latest retrieval wins; prior quarantined |
| `sec_company_facts` | 1 nested financial obs / (cik, taxonomy, concept, unit, period, accession) | …+accession | `cik` | decimal128(28,4) | each accession distinct → restatements retained |
| `treasury_yield_curve` | 1 yield / (date, tenor) | source_feed, date, tenor | `year` | decimal128(9,4) | latest retrieval wins; prior quarantined |
| `bls_observations` | 1 obs / (series_id, year, period) | series_id, year, period | `series_id` | decimal128(28,6) | identical envelopes dedup; value change = revision |
| `fred_observations` | 1 obs / (series_id, obs_date, realtime_start) | …+vintage | `series_id` | decimal128(28,10) | FRED vintages are distinct rows |

Every row carries lineage: `natural_key` (hash surrogate), `source_feed`,
`bronze_artifact_id`, `source_locator`, `retrieved_at`, `schema_version`.
Timestamps are UTC; monthly economic data keeps month granularity (never daily);
nulls (FRED `.`) and negative economic/accounting values are valid.

## Partitioning

Partition keys are chosen for query patterns and to avoid small-file sprawl: one
file per symbol (bars), per company (SEC), per series (BLS/FRED), per year
(Treasury). Measured file sizes stay 8 KB–1.1 MB — no fragmentation.

## Data quality

Quarantine (with machine-readable reasons, never silent discard):
`missing_required_field`, `schema_nonconformity`, `invalid_ohlc_relationship`,
`negative_volume`, `invalid_timestamp`, `temporal_inconsistency`,
`conflicting_value_same_natural_key`, `superseded_by_later_retrieval`.
OHLCV: high ≥ low and brackets open/close, non-negative volume. Missing weekend
bars are **not** defects; negative rates/values are **not** rejected. Publication
is blocked if reconciliation does not balance (fail-closed).

## Observation-level dedup vs raw dedup

Rows with the same natural key and identical data → one canonical (counted as a
duplicate). Same key, different data → latest retrieval wins, prior **quarantined**
(not dropped). True revisions (SEC accessions, FRED vintages) have distinct natural
keys → retained and reported separately from duplicates.

## Reconciliation (pilot on the DE-2 ingestion, each ingested twice)

```
alpaca_equity_bars_daily  extracted=36     accepted=18     dup=18     rev=0      balanced
sec_company_facts         extracted=51196  accepted=25598  dup=25598  rev=12929  balanced
treasury_yield_curve      extracted=5798   accepted=2899   dup=2899   rev=0      balanced
bls_observations          extracted=70     accepted=35     dup=35     rev=0      balanced   (BLS volatile envelope collapsed)
fred_observations         extracted=32     accepted=16     dup=16     rev=0      balanced
```

SEC is reconciled at the **nested financial-observation** level (25,598 distinct
observations; 12,929 restatements of the same period retained as revisions).

## CLI

```bash
strix normalize run [--dataset NAME|all] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--json]
strix normalize status      # published datasets (rows, keys, partitions)
strix normalize verify      # re-verify Parquet file hashes
strix normalize profile     # per-dataset profile
strix normalize reconcile   # source-to-Silver reconciliation reports
strix normalize quarantine  # quarantined observations by reason
```

## Benchmark (actual)

Config: Darwin 27.0.0 arm64 · Python 3.11.8 · pyarrow 26.0.1 · single process.

Representative historical workload (backfill 2024-01-01 → 2026-11-20, universe
SPY/QQQ/XLK + AAPL + Treasury + FRED CPIAUCSL):

| Metric | Value |
|---|---|
| Bronze input | 4.9 MB (9 artifacts) |
| Silver published | ~37,196 rows in 8 Parquet files |
| Alpaca bars | 2,178 rows (726 trading days × 3 symbols) |
| SEC observations | 25,598 (12,929 revisions retained) |
| Treasury | 9,386 (date, tenor) rows across 3 year partitions |
| FRED | 34 rows |
| Duplicates / quarantined / unexplained discrepancies | 0 / 0 / 0 |
| Silver storage | 1.7 MB (≈ 2.9× compression vs Bronze; zstd) |
| Transform duration | 0.78 s (~47k obs/s) |
| Peak RSS | ~136 MB |
| Integrity verify | 8/8 files ok |
| Idempotent rerun | published, reconciliation balanced |

**Actual historical coverage:** Alpaca daily bars 2024-01-02 → 2026-11-20 (IEX
feed; earlier years not attempted in this bounded pilot). Treasury 2024–2026.
SEC AAPL full companyfacts snapshot. FRED CPIAUCSL monthly. (A `--series CPIAUCSL`
override also routed a non-existent id to BLS, which correctly returned 0 rows;
the BLS default series `CUUR0000SA0` normalizes as shown in the DE-2 pilot above.)

## Limitations / next

- Transforms are full-recompute (idempotent, reproducible); incremental-merge into
  existing partitions is a future optimization (DE-3.x).
- Full 2015-present backfill was not run (bounded pilot to respect request/disk
  budgets); coverage reported is actual, not claimed.
- DE-4 will mount these Parquet datasets in a DuckDB analytical warehouse
  (optional Snowflake target).
