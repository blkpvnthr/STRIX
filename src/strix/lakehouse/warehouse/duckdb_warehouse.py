"""DuckDB analytical warehouse: init, transactional incremental load, reconcile,
read-only queries, and evidence lineage.

DuckDB is single-writer: each write opens its own connection and wraps the load in
a transaction (rolled back on any error, so an interrupted load never leaves a
partial state). Only *validated* Silver publications (balanced reconciliation,
verified file hashes) are loaded; quarantined/unvalidated data is rejected. The
Silver ``natural_key`` is each fact's primary key, so reloading the same publication
is idempotent and never duplicates rows.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from strix.canonical import sha256_hex
from strix.errors import LakehouseError
from strix.lakehouse.silver.models import PublicationManifest
from strix.lakehouse.warehouse.contracts import (
    LineageRecord,
    LoadResult,
    WarehouseReconciliation,
)
from strix.lakehouse.warehouse.model import (
    SILVER_TO_FACT,
    WAREHOUSE_TABLES,
    create_table_sql,
)

_DIM_SOURCES = (
    ("alpaca", "Alpaca Market Data", "market_data"),
    ("sec_edgar", "SEC EDGAR", "filings"),
    ("us_treasury", "US Treasury", "rates"),
    ("bls", "Bureau of Labor Statistics", "economic"),
    ("fred", "Federal Reserve (FRED)", "economic"),
)
# Authoritative SPDR sector ETF mapping (used for dim_sector; explicit, not invented).
_DIM_SECTORS = (
    ("XLK", "Information Technology"), ("XLF", "Financials"), ("XLE", "Energy"),
    ("XLV", "Health Care"), ("XLY", "Consumer Discretionary"), ("XLP", "Consumer Staples"),
    ("XLI", "Industrials"), ("XLU", "Utilities"), ("XLB", "Materials"),
    ("XLRE", "Real Estate"), ("XLC", "Communication Services"), ("UNKNOWN", "Unknown"),
)


class WarehouseError(LakehouseError):
    """A warehouse operation could not be completed or trusted."""


def _ts_literal(dt: datetime) -> str:
    return f"TIMESTAMP '{dt.astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S')}'"


def _scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> Any:
    row = con.execute(sql, params or []).fetchone()
    assert row is not None
    return row[0]


class DuckDBWarehouse:
    def __init__(self, db_path: Path, silver_root: Path) -> None:
        self._path = Path(db_path)
        self._silver_root = Path(silver_root)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # -- connections -------------------------------------------------------

    def connect(self, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self._path), read_only=read_only)

    # -- schema ------------------------------------------------------------

    def init_schema(self) -> list[str]:
        created = []
        con = self.connect()
        try:
            con.execute("BEGIN")
            for table in WAREHOUSE_TABLES:
                con.execute(create_table_sql(table, "duckdb"))
                created.append(table.name)
            con.execute(
                "CREATE TABLE IF NOT EXISTS _load_state ("
                "dataset VARCHAR PRIMARY KEY, silver_publication_id VARCHAR, "
                "schema_version VARCHAR, input_manifest_hash VARCHAR, "
                "last_load_execution_id VARCHAR, previous_publication_id VARCHAR, "
                "loaded_at TIMESTAMP, inserted INTEGER, updated INTEGER, "
                "unchanged INTEGER, rejected INTEGER)"
            )
            self._seed_static_dims(con)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()
        return created

    def _seed_static_dims(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("DELETE FROM dim_source")
        con.executemany("INSERT INTO dim_source VALUES (?,?,?)", list(_DIM_SOURCES))
        con.execute("DELETE FROM dim_exchange")
        con.execute("INSERT INTO dim_exchange VALUES ('UNKNOWN','Unknown')")
        con.execute("DELETE FROM dim_sector")
        con.executemany("INSERT INTO dim_sector VALUES (?,?)", list(_DIM_SECTORS))

    # -- loading -----------------------------------------------------------

    def load_silver(
        self,
        dataset: str,
        *,
        now: datetime | None = None,
        dry_run: bool = False,
        fail_hook: Any = None,
    ) -> LoadResult:
        if dataset not in SILVER_TO_FACT:
            raise WarehouseError(f"no fact table maps from Silver dataset {dataset!r}")
        now = now or datetime.now(UTC)
        fact = SILVER_TO_FACT[dataset]
        manifest, pub_bytes = self._load_publication(dataset)
        pub_id = sha256_hex(pub_bytes)
        execution_id = "LOAD-" + uuid.uuid4().hex[:16]
        self.init_schema()  # idempotent: ensure tables exist before loading

        con = self.connect()
        in_txn = False
        try:
            existing = con.execute(
                "SELECT silver_publication_id FROM _load_state WHERE dataset = ?::VARCHAR",
                [dataset],
            ).fetchone()
            if existing and existing[0] == pub_id:
                return LoadResult(
                    dataset=dataset, fact_table=fact, silver_publication_id=pub_id,
                    load_execution_id=execution_id, schema_version=manifest.schema_version,
                    silver_rows=manifest.row_count, skipped=True,
                    reason="publication already loaded (idempotent no-op)",
                    started_at=now, finished_at=now,
                )

            source = self._parquet_source(manifest)

            con.execute("BEGIN")
            in_txn = True
            if source is None:
                # A published-but-empty dataset (0 rows): nothing to stage.
                con.execute("CREATE OR REPLACE TEMP TABLE _stg AS "
                            f"SELECT * FROM {fact} WHERE 1=0")
            else:
                projection = _PROJECTIONS[dataset](source, pub_id, execution_id, _ts_literal(now))
                con.execute(f"CREATE OR REPLACE TEMP TABLE _stg AS {projection}")
            silver_rows = _scalar(con, "SELECT count(*) FROM _stg")
            inserted = _scalar(
                con,
                f"SELECT count(*) FROM _stg s LEFT JOIN {fact} f "
                "USING(silver_natural_key) WHERE f.silver_natural_key IS NULL",
            )
            updated = _scalar(
                con,
                f"SELECT count(*) FROM _stg s JOIN {fact} f USING(silver_natural_key) "
                "WHERE s.row_signature <> f.row_signature",
            )
            unchanged = _scalar(
                con,
                f"SELECT count(*) FROM _stg s JOIN {fact} f USING(silver_natural_key) "
                "WHERE s.row_signature = f.row_signature",
            )

            if fail_hook is not None:
                fail_hook()  # test seam: raise mid-transaction to exercise rollback

            con.execute(
                f"DELETE FROM {fact} WHERE silver_natural_key IN "
                "(SELECT silver_natural_key FROM _stg)"
            )
            con.execute(f"INSERT INTO {fact} BY NAME SELECT * FROM _stg")
            self._record_pipeline_run(con, dataset, pub_id, execution_id, silver_rows,
                                      manifest, now)
            self._refresh_dimensions(con)
            self._upsert_load_state(
                con, dataset, pub_id, manifest, execution_id,
                previous=(existing[0] if existing else None),
                now=now, inserted=inserted, updated=updated, unchanged=unchanged,
            )

            if dry_run:
                con.execute("ROLLBACK")
            else:
                con.execute("COMMIT")
            in_txn = False
        except Exception as exc:
            if in_txn:
                con.execute("ROLLBACK")
            if isinstance(exc, WarehouseError):
                raise
            raise WarehouseError(f"load of {dataset} failed and was rolled back: {exc}") from exc
        finally:
            con.close()

        return LoadResult(
            dataset=dataset, fact_table=fact, silver_publication_id=pub_id,
            load_execution_id=execution_id, schema_version=manifest.schema_version,
            inserted=inserted, updated=updated, unchanged=unchanged, rejected=0,
            silver_rows=silver_rows, skipped=False,
            reason=("dry-run (rolled back)" if dry_run else None),
            started_at=now, finished_at=datetime.now(UTC),
        )

    def _parquet_source(self, manifest: PublicationManifest) -> str | None:
        """A ``read_parquet([...])`` expression over the manifest's files, or None
        when the published dataset has no files (0 rows)."""
        paths = [str(self._silver_root / f.relative_path) for f in manifest.files]
        if not paths:
            return None
        quoted = ", ".join(f"'{p}'" for p in paths)
        return f"read_parquet([{quoted}])"

    def has_publication(self, dataset: str) -> bool:
        return (self._silver_root / "silver" / dataset / "_publication.json").is_file()

    def _load_publication(self, dataset: str) -> tuple[PublicationManifest, bytes]:
        path = self._silver_root / "silver" / dataset / "_publication.json"
        if not path.is_file():
            raise WarehouseError(f"no published Silver for {dataset} (run `strix normalize run`)")
        pub_bytes = path.read_bytes()
        try:
            manifest = PublicationManifest.model_validate(json.loads(pub_bytes))
        except (ValueError, json.JSONDecodeError) as exc:
            raise WarehouseError(f"invalid Silver publication for {dataset}: {exc}") from exc
        if not manifest.reconciliation.balanced:
            raise WarehouseError(
                f"refusing to load {dataset}: Silver reconciliation did not balance"
            )
        for f in manifest.files:
            fp = self._silver_root / f.relative_path
            if not fp.is_file() or sha256_hex(fp.read_bytes()) != f.content_hash:
                raise WarehouseError(
                    f"refusing to load {dataset}: Silver file integrity check failed "
                    f"({f.relative_path})"
                )
        return manifest, pub_bytes

    def _record_pipeline_run(
        self, con: duckdb.DuckDBPyConnection, dataset: str, pub_id: str, execution_id: str,
        rows: int, manifest: PublicationManifest, now: datetime,
    ) -> None:
        source = _dataset_source(dataset)
        con.execute(
            "DELETE FROM fact_pipeline_runs WHERE silver_publication_id = ?::VARCHAR", [pub_id]
        )
        con.execute(
            "INSERT INTO fact_pipeline_runs BY NAME SELECT ? AS silver_publication_id, "
            "? AS dataset, ? AS source_code, ? AS row_count, "
            f"{_ts_literal(manifest.published_at)} AS published_at, "
            f"? AS load_execution_id, {_ts_literal(now)} AS warehouse_loaded_at",
            [pub_id, dataset, source, rows, execution_id],
        )

    def _upsert_load_state(
        self, con: duckdb.DuckDBPyConnection, dataset: str, pub_id: str,
        manifest: PublicationManifest, execution_id: str, *, previous: str | None,
        now: datetime, inserted: int, updated: int, unchanged: int,
    ) -> None:
        con.execute("DELETE FROM _load_state WHERE dataset = ?::VARCHAR", [dataset])
        con.execute(
            "INSERT INTO _load_state VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [dataset, pub_id, manifest.schema_version, pub_id, execution_id, previous,
             now.replace(tzinfo=None), inserted, updated, unchanged, 0],
        )

    def _refresh_dimensions(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("DELETE FROM dim_instrument")
        con.execute(
            "INSERT INTO dim_instrument SELECT DISTINCT symbol, (hash(symbol) >> 1)::BIGINT, "
            "'equity', NULL FROM fact_market_bars"
        )
        con.execute("DELETE FROM dim_company")
        con.execute(
            "INSERT INTO dim_company SELECT DISTINCT cik, (hash(cik) >> 1)::BIGINT, NULL "
            "FROM fact_company_financials"
        )
        con.execute("DELETE FROM dim_economic_series")
        con.execute(
            "INSERT INTO dim_economic_series SELECT DISTINCT series_id, "
            "(hash(series_id) >> 1)::BIGINT, source_code, any_value(frequency) "
            "FROM fact_economic_observations GROUP BY series_id, source_code"
        )
        con.execute("DELETE FROM dim_evidence")
        _evi = "SELECT bronze_artifact_id, source_code, retrieved_at FROM"
        con.execute(
            "INSERT INTO dim_evidence SELECT bronze_artifact_id, any_value(source_code), NULL, "
            "min(retrieved_at) FROM ("
            f"  {_evi} fact_market_bars "
            f"  UNION ALL {_evi} fact_company_financials"
            f"  UNION ALL {_evi} fact_economic_observations"
            f"  UNION ALL {_evi} fact_treasury_yields"
            ") GROUP BY bronze_artifact_id"
        )
        con.execute("DELETE FROM dim_pipeline_run")
        con.execute(
            "INSERT INTO dim_pipeline_run SELECT silver_publication_id, 'silver_publication', "
            "dataset, published_at FROM fact_pipeline_runs"
        )
        con.execute("DELETE FROM dim_date")
        con.execute(_DIM_DATE_SQL)

    # -- reconciliation ----------------------------------------------------

    def reconcile(self, dataset: str) -> WarehouseReconciliation:
        fact = SILVER_TO_FACT[dataset]
        manifest, _ = self._load_publication(dataset)
        silver_rows = manifest.row_count
        con = self.connect(read_only=True)
        try:
            source = _dataset_source(dataset)
            agg = con.execute(
                f"SELECT count(*), count(DISTINCT silver_natural_key), "
                f"count(*) FILTER (WHERE {_value_col(fact)} IS NULL), "
                f"min({_date_col(fact)}), max({_date_col(fact)}) "
                f"FROM {fact} WHERE source_code = ?::VARCHAR",
                [source],
            ).fetchone()
            assert agg is not None
            wh_rows, uniq, nulls, dmin, dmax = agg
            lineage_missing = _scalar(
                con,
                f"SELECT count(*) FROM {fact} WHERE source_code = ?::VARCHAR AND "
                "(bronze_artifact_id IS NULL OR source_locator IS NULL)",
                [source],
            )
        finally:
            con.close()

        discrepancies: list[str] = []
        if wh_rows != uniq:
            discrepancies.append(f"duplicate natural keys: rows={wh_rows} distinct={uniq}")
        if wh_rows != silver_rows:
            discrepancies.append(
                f"row mismatch: silver={silver_rows} warehouse={wh_rows} (source={source})"
            )
        if lineage_missing:
            discrepancies.append(f"{lineage_missing} rows missing lineage")
        return WarehouseReconciliation(
            dataset=dataset, fact_table=fact, silver_rows=silver_rows, warehouse_rows=wh_rows,
            unique_natural_keys=uniq, duplicate_keys=wh_rows - uniq, null_value_rows=nulls,
            min_observation_date=str(dmin) if dmin else None,
            max_observation_date=str(dmax) if dmax else None,
            lineage_complete=(lineage_missing == 0), discrepancies=tuple(discrepancies),
        )

    # -- read-only query ---------------------------------------------------

    def query(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[tuple[Any, ...]]]:
        con = self.connect(read_only=True)
        try:
            cur = con.execute(sql, params or [])
            columns = [d[0] for d in cur.description]
            return columns, cur.fetchall()
        finally:
            con.close()

    # -- lineage -----------------------------------------------------------

    def lineage(self, fact: str, natural_key: str) -> LineageRecord | None:
        from strix.lakehouse.bronze import BronzeIngestor
        from strix.lakehouse.ingest.catalog import load_manifests
        from strix.lakehouse.storage import LocalObjectStore

        con = self.connect(read_only=True)
        try:
            row = con.execute(
                f"SELECT bronze_artifact_id, source_locator, silver_schema_version, "
                f"silver_publication_id, retrieved_at FROM {fact} "
                "WHERE silver_natural_key = ?::VARCHAR LIMIT 1",
                [natural_key],
            ).fetchone()
        finally:
            con.close()
        if row is None:
            return None
        artifact_id, locator, schema_version, pub_id, retrieved = row

        store = LocalObjectStore(self._silver_root)
        bronze = BronzeIngestor(store)
        present = hash_ok = False
        for manifest in load_manifests(store):
            if manifest.artifact.artifact_id == artifact_id:
                present = True
                try:
                    bronze.read_artifact(manifest.artifact)  # re-verifies hash
                    hash_ok = True
                except LakehouseError:
                    hash_ok = False
                break
        return LineageRecord(
            natural_key=natural_key, fact_table=fact, silver_schema_version=str(schema_version),
            silver_publication_id=str(pub_id), bronze_artifact_id=str(artifact_id),
            source_locator=str(locator), retrieved_at=str(retrieved),
            bronze_artifact_present=present, bronze_hash_ok=hash_ok,
        )


# --------------------------------------------------------------------------
# Projection SQL (Silver parquet -> fact columns, by name)
# --------------------------------------------------------------------------


def _md5(*cols: str) -> str:
    parts = ",".join(f"COALESCE(CAST({c} AS VARCHAR),'')" for c in cols)
    return f"md5(concat_ws('|', {parts}))"


def _alpaca_proj(glob: str, pub: str, exe: str, now: str) -> str:
    return f"""SELECT natural_key AS silver_natural_key,
      CAST(strftime(session_date,'%Y%m%d') AS INTEGER) AS date_key,
      symbol, session_date, observation_ts, open, high, low, close, volume, trade_count, vwap,
      source_feed AS source_code, schema_version AS silver_schema_version,
      bronze_artifact_id, source_locator, retrieved_at,
      '{pub}' AS silver_publication_id, '{exe}' AS load_execution_id,
      {now} AS warehouse_loaded_at,
      {_md5('open','high','low','close','volume','trade_count','vwap')} AS row_signature
      FROM {glob}"""


def _sec_proj(glob: str, pub: str, exe: str, now: str) -> str:
    return f"""SELECT natural_key AS silver_natural_key, cik, taxonomy, concept, unit,
      period_start, period_end, filed_date, fiscal_year, fiscal_period, form, accession, frame,
      value, source_feed AS source_code, schema_version AS silver_schema_version,
      bronze_artifact_id, source_locator, retrieved_at,
      '{pub}' AS silver_publication_id, '{exe}' AS load_execution_id,
      {now} AS warehouse_loaded_at,
      {_md5('value','filed_date','accession','form')} AS row_signature
      FROM {glob}"""


def _bls_proj(glob: str, pub: str, exe: str, now: str) -> str:
    return f"""SELECT natural_key AS silver_natural_key, series_id, observation_date, frequency,
      period, CAST(value AS DECIMAL(28,10)) AS value, NULL::DATE AS realtime_start,
      NULL::DATE AS realtime_end, source_feed AS source_code,
      schema_version AS silver_schema_version, bronze_artifact_id, source_locator, retrieved_at,
      '{pub}' AS silver_publication_id, '{exe}' AS load_execution_id,
      {now} AS warehouse_loaded_at, {_md5('value','period','frequency')} AS row_signature
      FROM {glob}"""


def _fred_proj(glob: str, pub: str, exe: str, now: str) -> str:
    return f"""SELECT natural_key AS silver_natural_key, series_id, observation_date,
      NULL::VARCHAR AS frequency, NULL::VARCHAR AS period, value, realtime_start, realtime_end,
      source_feed AS source_code, schema_version AS silver_schema_version,
      bronze_artifact_id, source_locator, retrieved_at,
      '{pub}' AS silver_publication_id, '{exe}' AS load_execution_id,
      {now} AS warehouse_loaded_at,
      {_md5('value','realtime_start','realtime_end')} AS row_signature
      FROM {glob}"""


def _treasury_proj(glob: str, pub: str, exe: str, now: str) -> str:
    return f"""SELECT natural_key AS silver_natural_key,
      CAST(strftime(date,'%Y%m%d') AS INTEGER) AS date_key, date AS observation_date, tenor,
      yield_pct, source_feed AS source_code, schema_version AS silver_schema_version,
      bronze_artifact_id, source_locator, retrieved_at,
      '{pub}' AS silver_publication_id, '{exe}' AS load_execution_id,
      {now} AS warehouse_loaded_at, {_md5('yield_pct')} AS row_signature
      FROM {glob}"""


_PROJECTIONS = {
    "alpaca_equity_bars_daily": _alpaca_proj,
    "sec_company_facts": _sec_proj,
    "bls_observations": _bls_proj,
    "fred_observations": _fred_proj,
    "treasury_yield_curve": _treasury_proj,
}

_VALUE_COL = {
    "fact_market_bars": "close", "fact_company_financials": "value",
    "fact_economic_observations": "value", "fact_treasury_yields": "yield_pct",
}
_DATE_COL = {
    "fact_market_bars": "session_date", "fact_company_financials": "period_end",
    "fact_economic_observations": "observation_date", "fact_treasury_yields": "observation_date",
}
_SOURCE_OF_DATASET = {
    "alpaca_equity_bars_daily": "alpaca", "sec_company_facts": "sec_edgar",
    "bls_observations": "bls", "fred_observations": "fred",
    "treasury_yield_curve": "us_treasury",
}


def _value_col(fact: str) -> str:
    return _VALUE_COL[fact]


def _date_col(fact: str) -> str:
    return _DATE_COL[fact]


def _dataset_source(dataset: str) -> str:
    return _SOURCE_OF_DATASET[dataset]


_DIM_DATE_SQL = """INSERT INTO dim_date
  WITH d AS (
    SELECT session_date AS dt FROM fact_market_bars
    UNION SELECT period_end FROM fact_company_financials
    UNION SELECT filed_date FROM fact_company_financials
    UNION SELECT observation_date FROM fact_economic_observations
    UNION SELECT observation_date FROM fact_treasury_yields
  )
  SELECT DISTINCT CAST(strftime(dt,'%Y%m%d') AS INTEGER), dt,
    year(dt), quarter(dt), month(dt), day(dt), dayofweek(dt),
    (dayofweek(dt) BETWEEN 1 AND 5)
  FROM d WHERE dt IS NOT NULL"""
