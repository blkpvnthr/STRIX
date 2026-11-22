# DE-5 — dbt Financial Intelligence Transformation Layer

Transforms the DE-4 analytical warehouse into analyst-ready **marts** with dbt
(**staging → intermediate → marts**). **DuckDB** is the operational backend;
**Snowflake** is an optional, offline-compiled target. dbt is invoked only through a
controlled runner (fixed executable, allow-listed subcommand, validated selection,
no shell) — the language model never gets raw SQL or shell. The transformation layer
is **not** the verifier: a mart value receives no verdict automatically; the
independent verifier recomputes supported claims from preserved Silver/Bronze
evidence with the same Decimal calculators the research agent uses.

## Architecture

```
warehouse facts/dims (DuckDB)                      [DE-4]
  -> staging/     typed, standardized views (lineage preserved)
  -> intermediate/ returns, volatility, drawdown, PIT selection, concept mapping, …
  -> marts/       markets · fundamentals · macroeconomics · research  (materialized tables)
  -> strix transform validate  -> independent Decimal recompute (cross-validation)
```

dbt sources read the warehouse `main` schema (`database = target.database`, so the
project is portable across warehouse files). Staging/intermediate materialize as
views; marts as tables in dedicated schemas (`staging`, `intermediate`, `marts`).

## Project layout

```
dbt/
├── dbt_project.yml          profile "strix"; schemas staging/intermediate/marts
├── profiles.example.yml     DuckDB + Snowflake outputs (env_var only; no secrets)
├── packages.yml             empty (offline); packages.example.yml adds dbt_utils
├── models/{staging,intermediate,marts/{markets,fundamentals,macroeconomics,research}}
├── macros/                  generate_schema_name, cross_db dispatch, custom tests
├── seeds/                   sec_concept_map.csv, economic_series_map.csv
└── analyses/ snapshots/ tests/
```

`strix transform init` writes a gitignored `dbt/profiles.yml` from env, prepares the
warehouse schema, seeds, and parses. `dbt/target/`, `dbt_packages/`, `logs/`, and
`profiles.yml` are gitignored (no generated artifacts or credentials committed).

## Models

**Staging (10, views)** — `stg_market_bars`, `stg_company_financials`,
`stg_economic_observations`, `stg_treasury_yields`, `stg_pipeline_runs`,
`stg_instruments`, `stg_companies`, `stg_economic_series`, `stg_sources`,
`stg_evidence`. Standardize names/types and preserve every lineage identifier
(`silver_natural_key`, `bronze_artifact_id`, `source_locator`,
`silver_publication_id`). Units are never silently changed; period kind
(instant/duration) is made explicit.

**Intermediate (16, views)** — session alignment & returns (`int_market_daily`,
`int_daily_returns`, `int_cumulative_returns`), `int_rolling_volatility`,
`int_rolling_drawdown`, `int_benchmark_relative_returns`; SEC
`int_financial_facts_ranked` (restatement rank), `int_sec_concept_mapping`,
`int_financial_period_selection` (first-filed, period_type), `int_financial_statement_alignment`;
`int_economic_revisions`, `int_economic_pit`; `int_treasury_maturity_alignment`;
`int_sector_etf_performance`; `int_cross_asset_correlation`; `int_market_regime_features`.
Each documents its grain in `_intermediate.yml`.

**Marts (12, tables)**

| Mart | Grain | Notes |
|---|---|---|
| `mart_market_overview` | index ETF proxy | SPY/QQQ/DIA/IWM; **proxy, not breadth** |
| `mart_instrument_performance` | instrument | weekly/monthly/quarterly/YTD/annual; split+dividend-adjusted basis labeled |
| `mart_market_volatility` | instrument | rolling 5/10/20/60 annualized vol + sample sizes |
| `mart_market_drawdown` | instrument | current/max drawdown, duration, recovery |
| `mart_sector_rotation` | sector ETF | absolute + SPY-relative; `is_complete_ranking` flag |
| `mart_company_fundamentals` | cik·FY·FP·period_end·period_type | first-filed SEC metrics; no summing of overlapping durations |
| `mart_financial_ratios` | …·ratio_name | long form with numerator/denominator/formula/version/unit/accession/evidence/status |
| `mart_macro_conditions` | series·date | per-series; SA/NSA + concept; period vs vintage distinct; series never combined |
| `mart_yield_curve` | date | 10y-2y / 10y-3m / 30y-10y spreads (pp **and** bps), inversion, changes |
| `mart_historical_regimes` | instrument | descriptive features; **no prediction/causality**; `covers_2022` gated on data |
| `mart_equity_correlations` | symbol pair | aligned Pearson corr + methodology metadata |
| `mart_research_quality` | summary | warehouse-resident counts only; **deferred to DE-7** |

## Calculation contracts & independent verification

Versioned contracts (`strix.lakehouse.transform.calculations`) pin each calculation's
formula, methodology version (= `CALC_VERSION` 1.0.0), inputs, unit, precision, min
sample size, null handling, historical-availability rule, and evidence requirement.
`strix transform validate` (`WarehouseCrossValidator`) **reads mart inputs from the
warehouse facts, recomputes with the Decimal calculators, and compares to the SQL
mart** under the contract tolerance — it never re-runs the dbt SQL, so agreement is
real corroboration. Financial-statement ratios match exactly (Decimal); statistical
calculations use a documented absolute tolerance of `5e-7`. Every check surfaces the
Bronze `evidence_artifacts` backing its inputs.

## Historical revisions & point-in-time

SEC restatements are retained (first-filed vs latest-filed rank); marts use
**first-filed** values for point-in-time honesty. FRED vintages (`realtime_start`)
are retained; `int_economic_pit` selects the latest vintage ≤ cutoff. **Strict** PIT
excludes vintage-less series (BLS/Treasury) rather than treating observation date as
proof of availability; non-strict mode includes them flagged as
`observation_date_fallback`. A `strix_no_lookahead` test enforces `filed_date >=
period_end`.

## Data quality tests

dbt schema tests (`unique`, `not_null`, `relationships`, `accepted_values`) plus
custom generics in `macros/tests.sql`: `strix_in_range` (business ranges — negative
accounting values / rates / returns are **not** rejected), `strix_no_lookahead`,
`strix_unique_fiscal_period`, `strix_unique_combination`, `strix_single_unit_per_metric`.
Seeds carry deterministic, independently-checkable mappings.

## DuckDB / Snowflake compatibility

Dialect differences live behind `macros/cross_db.sql` (`strix_stddev_samp`,
`strix_ln`, `strix_date_diff_days`, `strix_safe_divide`, `strix_annualize_vol`) via
`adapter.dispatch`. DuckDB is validated end to end. Snowflake is offline-validated
(`dbt parse --target snowflake`) when `dbt-snowflake` is installed; live run requires
`SNOWFLAKE_*` credentials and is never auto-provisioned.

## CLI

```bash
strix transform init [--with-deps]          # profile + schema + seed + parse
strix transform run|build|test [--select S] [--full-refresh]
strix transform docs                        # catalog.json + manifest.json + index.html
strix transform status | profile
strix transform lineage --select MODEL      # upstream dependency chain
strix transform validate --symbol SPY --pair SPY,QQQ --cik CIK0000320193
```

`--full-refresh` is the destructive rebuild (documented); all runs record the
warehouse `silver_publication_id` set they executed against.

## Live pilot & benchmarks (actual)

Config: Darwin 27.0.0 arm64 · Python 3.11.8 · dbt-core 1.12.7 · dbt-duckdb 1.11.1 ·
DuckDB 2.0.1 · single process. Live ingestion window **2022-01-01 → 2026-11-20**.

**Coverage ingested (live):** Alpaca 22 symbols × 1,227 daily bars = 26,994 (SPY,
QQQ, DIA, IWM; 11 SPDR sectors; AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA; adjustment
= all). SEC 7 filers = 180,373 observations (85,303 restatements retained). FRED 5
series (CPIAUCSL, UNRATE, FEDFUNDS monthly; DGS10, DGS2 daily) = 2,722. Treasury
curve = 1,221 dates / 15,674 tenor observations. BLS CUUR0000SA0 = 35 (keyless tier
≈ 3 years — documented limitation). **Warehouse total: 225,798 fact rows.**

| Metric | Value |
|---|---|
| Models | 38 (10 staging views, 16 intermediate views, 12 mart tables) |
| dbt data tests | 63 (0 failures) |
| Seeds | 2 |
| Published mart rows | 20,860 (ratios 15,040 · macro 2,760 · yield_curve 1,221 · correlations 231 · fundamentals 1,504 · per-instrument marts 22 each · sectors 11) |
| Initial `build` | ~2.9 s (103 nodes) |
| Incremental rebuild (no data change) | ~2.8 s |
| `test` only | ~1.9 s (63 tests) |
| Warehouse load (DE-4) | ~1.0 s (225,798 rows) |
| DB footprint (warehouse + marts) | 62.9 MB |
| Mart query latency (warm) | 0.25–1.6 ms |
| Independent cross-validation discrepancies | 0 |
| Evidence lineage | every mart row resolves to Bronze (re-hash verified) |

**Cross-validation (live, SQL mart vs Decimal recompute):** SPY cumulative return
0.5404 (Δ 4.9e-7), max drawdown −0.2451 (Δ 4.3e-7), annualized vol 0.1719 (Δ 2.5e-7),
corr(SPY,QQQ) 0.9518 (Δ 9.4e-8); AAPL gross/operating/net margin 0.4879/0.3301/0.2760
(Δ ~1e-17, exact Decimal). All agree within contract tolerance.

### v0.2.0 question categories now analytically supported

The four previously-unsupported categories are now answerable from warehouse-backed
marts (the agent *integration* lands in DE-7; this is data availability, not agent wiring):

- **Inflation** — `mart_macro_conditions` CPIAUCSL (SA): YoY 3.72% (2026-09), MoM/YoY,
  vintage-aware.
- **Treasury yields** — `mart_yield_curve`: 10y-2y spread + inversion; 541 of 1,221
  sessions inverted over 2022–2026.
- **Apple operating margin** — `mart_financial_ratios`: annual history incl. FY2026
  33.0%, with numerator/denominator/accession/evidence.
- **Sector-relative performance** — `mart_sector_rotation`: complete 11-sector ranking
  vs SPY (XLE +95.2%, XLRE −56.7%), `is_complete_ranking = true`.

The other four (market returns, volatility, drawdown, cross-asset correlation) were
already supported and are now mart-materialized and cross-validated.

## Remaining limitations

- **Research integration is DE-7.** `mart_research_quality` exposes only
  warehouse-resident counts (0 today) and reports the deferral; schema-only research
  facts are never populated with fabricated rows.
- **BLS keyless tier** returns ≈ 3 years; use an API key for deeper history.
- **PIT vintage accuracy** holds for SEC/FRED; BLS/Treasury/market fall back to
  observation date (strict PIT excludes them).
- Very old SEC comparative periods can yield multiple annual rows per fiscal year
  (distinct `period_end`); recent years are clean. Marts never sum overlapping
  quarterly/YTD durations.
- Snowflake is offline-validated; live execution requires credentials.
- Marts are full-refresh materializations; true dbt incremental models and dbt
  snapshots are available in the project layout but not yet the default for marts.
