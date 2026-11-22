# DE-4 — Financial Analytical Warehouse

Loads validated Silver Parquet publications into a dimensional analytical warehouse.
**DuckDB** is the operational local warehouse (no paid infrastructure); **Snowflake**
is an optional, fully-implemented, offline-tested cloud target. The warehouse never
confers verification — the STRIX verifier still recomputes claims from preserved
evidence, and every warehouse row resolves back to its Bronze artifact.

## Architecture

```
Silver publication (validated, balanced)  -- only balanced, hash-verified -->
  WarehouseLoader (transaction)
    -> staging projection (DuckDB read_parquet from the manifest's files)
    -> insert / update / unchanged accounting by natural key + row_signature
    -> fact upsert (delete+insert of staged keys) + dimension refresh
    -> _load_state (silver_publication_id, counts)  -> COMMIT (or ROLLBACK)
```

Single-writer: each load opens its own connection and wraps everything in one
transaction, rolled back on any error (an interrupted load never exposes partial
data). Read connections are opened `read_only=True`.

## Dimensional model

**Dimensions:** dim_date, dim_source, dim_instrument, dim_company,
dim_economic_series, dim_evidence, dim_pipeline_run, dim_exchange, dim_sector.
**Facts (populated):** fact_market_bars, fact_company_financials,
fact_economic_observations, fact_treasury_yields, fact_pipeline_runs.
**Facts (schema-only placeholders, created but never populated, reported as such):**
fact_market_quotes, fact_corporate_actions, fact_sector_performance,
fact_financial_ratios, fact_research_claims, fact_verification_results.

Each fact's primary key is the Silver `natural_key` (deduplicated upstream), so
reloads are idempotent. Facts carry the distinct temporal fields PIT needs
(observation date, trading timestamp, reporting period, filing date, revision
vintage, retrieval timestamp, warehouse load timestamp) plus lineage columns
(bronze_artifact_id, source_locator, silver_publication_id, silver_schema_version).
Financial values use `DECIMAL`/`NUMBER`; authoritative metadata is used where
available and explicit `UNKNOWN`/NULL otherwise (no invented identifiers).

## DuckDB configuration

Persistent file (default `lakehouse/warehouse/strix.duckdb`). `strix warehouse init`
creates the schema transactionally. Loads read Parquet directly from the Silver
publication's listed files (not a glob), handle empty publications, and verify the
publication's reconciliation + file hashes before touching the warehouse.

## Snowflake configuration (optional)

`SnowflakeWarehouse` generates DDL (`NUMBER`/`TIMESTAMP_NTZ`), `COPY INTO` (Parquet),
and transactional `MERGE` upserts keyed on `silver_natural_key` with a
`row_signature` change check, plus warehouse auto-suspend/auto-resume and
least-privilege `STRIX_INGEST` / read-only `STRIX_RESEARCH` roles. Credentials come
from `SNOWFLAKE_*` environment variables and are never committed. `strix warehouse
init --backend snowflake` prints the DDL (dry-run); live load runs when credentials
are configured.

## Incremental loading

Persistent `_load_state` records dataset, silver_publication_id, schema_version,
execution id, previous publication, counts (inserted/updated/unchanged/rejected).
Re-loading the same publication is a no-op (skipped). A revised observation (same
natural key, changed `row_signature`) is an **update**, not a duplicate; new keys
are inserts. Natural-key uniqueness is enforced by the fact primary key.

## Reconciliation

`strix warehouse reconcile` compares Silver row count (from the publication manifest)
to warehouse rows per source, checks natural-key cardinality, duplicate keys, null
values, observation-date coverage, and lineage completeness; `balanced` requires no
discrepancies. Loads of unbalanced or hash-mismatched Silver publications are
rejected (fail-closed).

## Historical revisions & point-in-time

SEC restatements (distinct accession) and FRED vintages (distinct realtime_start)
are distinct natural keys → retained as separate rows, enabling true PIT via
`filed_date` / `realtime_start <= cutoff`. **Limitation:** Alpaca/Treasury/BLS carry
no vintage metadata, so their PIT uses observation date and reflects the latest
correction; this is reported rather than claimed as full vintage correctness.

## Evidence lineage

`strix warehouse lineage --dataset X --key NK` resolves warehouse row → Silver
(schema version, publication) → Bronze artifact → source-record locator, and
re-verifies the Bronze artifact's content hash. Lineage completeness is part of
reconciliation.

## Analytical query interface

Parameterized, read-only typed queries (`WarehouseQueries`): OHLCV, company
financials, economic history, treasury yields, dataset freshness, point-in-time
financials. Results carry units, source refs, observation dates, dataset versions,
and limitations. No raw SQL is accepted from callers or exposed to the model.

## CLI

```bash
strix warehouse init [--backend duckdb|snowflake]
strix warehouse load [--dataset NAME|all] [--dry-run] [--json]
strix warehouse status | profile | reconcile | verify
strix warehouse lineage --dataset NAME --key NATURAL_KEY
```

## Benchmarks (actual)

Config: Darwin 27.0.0 arm64 · Python 3.11.8 · DuckDB 2.0.1 · single process.
Pilot = the DE-3 Silver (SPY/QQQ/XLK 2024–2026, AAPL facts, Treasury, FRED CPI).

| Metric | Value |
|---|---|
| Silver input rows | 37,196 |
| Warehouse fact rows | 37,196 (2,178 bars + 25,598 financials + 34 econ + 9,386 yields) |
| Unique natural keys / duplicates | all unique / 0 duplicates |
| Full load duration | ~0.55 s |
| Idempotent rerun | skipped (0 duplicate rows) |
| DB footprint | ~20 MB |
| Query latency (cold / warm) | 8–17 ms / ~8–9 ms (incl. per-query read-only connect) |
| Materialized table scan vs direct Parquet | 0.25 ms vs 3.33 ms (~13× faster) |
| Reconciliation | all datasets balanced |
| Lineage completeness | warehouse → Bronze verified (hash ok) |
| PIT validation | GrossProfit as-of 2020-06-30 → 49 periods; 2026-11-01 → 74 (vintage filter) |

The ~8 ms query floor is dominated by opening a fresh read-only DuckDB connection
per call (a deliberate safety choice); the materialized-vs-Parquet figure isolates
true query cost.

## Remaining limitations

- Loads are transactional full-publication upserts; a true streaming/CDC path is
  future work. DuckDB is single-writer (documented; do not run concurrent writers,
  e.g. parallel Airflow tasks, against one file).
- PIT is vintage-accurate only for SEC/FRED; others fall back to observation date.
- Snowflake is offline-validated (SQL generation + tests); live load is exercised
  only when credentials are present.
- dim_company name and dim_exchange/dim_sector richness are limited by current
  feed metadata (explicit UNKNOWN rather than invented values).
- Advanced ratios/marts are DE-5 (dbt); schema-only facts are placeholders.
