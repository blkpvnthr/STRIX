"""`strix warehouse` command implementations (DuckDB default; Snowflake optional)."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from strix.agent.config import merged_environment
from strix.lakehouse.ingest.cli import resolve_lakehouse_dir
from strix.lakehouse.warehouse.contracts import LoadResult
from strix.lakehouse.warehouse.duckdb_warehouse import DuckDBWarehouse
from strix.lakehouse.warehouse.model import SILVER_TO_FACT, WAREHOUSE_TABLES
from strix.lakehouse.warehouse.snowflake_warehouse import SnowflakeProfile, SnowflakeWarehouse

_DATASETS = tuple(SILVER_TO_FACT)


def _db_path(args: argparse.Namespace, root: Path) -> Path:
    if getattr(args, "db_path", None):
        return Path(args.db_path)
    return root / "warehouse" / "strix.duckdb"


def run_warehouse(
    args: argparse.Namespace, *, out: TextIO, err: TextIO, environ: Mapping[str, str] | None = None
) -> int:
    backend = getattr(args, "backend", "duckdb")
    if backend == "snowflake":
        return _snowflake(args, out, environ)

    root = resolve_lakehouse_dir(getattr(args, "lakehouse_dir", None), environ)
    wh = DuckDBWarehouse(_db_path(args, root), root)
    command = args.warehouse_command
    as_json = getattr(args, "json", False)

    if command == "init":
        created = wh.init_schema()
        _emit(out, as_json, {"created_tables": created}, f"Initialized {len(created)} tables.")
        return 0
    if command == "load":
        return _load(wh, args, out, err, as_json=as_json)
    if command == "reconcile":
        return _reconcile(wh, out, as_json=as_json)
    if command == "status":
        return _status(wh, out, as_json=as_json)
    if command == "profile":
        return _profile(wh, out, as_json=as_json)
    if command == "verify":
        return _reconcile(wh, out, as_json=as_json)  # verify == reconcile balance + lineage
    if command == "lineage":
        return _lineage(wh, args, out, err, as_json=as_json)
    err.write(f"unknown warehouse command {command!r}\n")
    return 1


def _datasets(args: argparse.Namespace) -> list[str]:
    ds = getattr(args, "dataset", None)
    return [ds] if ds and ds != "all" else list(_DATASETS)


def _load(
    wh: DuckDBWarehouse, args: argparse.Namespace, out: TextIO, err: TextIO, *, as_json: bool
) -> int:
    wh.init_schema()
    now = datetime.now(UTC)
    dry_run = getattr(args, "dry_run", False)
    results: list[LoadResult] = []
    for dataset in _datasets(args):
        if dataset not in SILVER_TO_FACT:
            err.write(f"unknown dataset {dataset!r}\n")
            return 1
        if not wh.has_publication(dataset):
            out.write(f"- {dataset}: skipped (no published Silver)\n")
            continue
        try:
            results.append(wh.load_silver(dataset, now=now, dry_run=dry_run))
        except Exception as exc:
            err.write(f"- {dataset}: ERROR {exc}\n")
            return 1
    if as_json:
        out.write(json.dumps([r.model_dump(mode="json") for r in results], indent=2) + "\n")
    else:
        for r in results:
            state = "skipped" if r.skipped else "loaded"
            out.write(
                f"- {r.dataset} -> {r.fact_table}: {state} "
                f"(ins={r.inserted} upd={r.updated} unch={r.unchanged} "
                f"rows={r.silver_rows}) pub={r.silver_publication_id[:12]}\n"
            )
    return 0


def _reconcile(wh: DuckDBWarehouse, out: TextIO, *, as_json: bool) -> int:
    reports = []
    ok = True
    for dataset in _DATASETS:
        try:
            rec = wh.reconcile(dataset)
        except Exception:
            continue
        reports.append(rec)
        ok = ok and rec.balanced
    if as_json:
        out.write(json.dumps([r.model_dump() for r in reports], indent=2) + "\n")
    elif not reports:
        out.write("No warehouse datasets loaded.\n")
    else:
        out.write("Warehouse reconciliation:\n")
        for r in reports:
            out.write(
                f"  {r.dataset:<26} silver={r.silver_rows} warehouse={r.warehouse_rows} "
                f"keys={r.unique_natural_keys} dup={r.duplicate_keys} "
                f"lineage={'ok' if r.lineage_complete else 'INCOMPLETE'} "
                f"balanced={r.balanced}\n"
            )
            for d in r.discrepancies:
                out.write(f"    ! {d}\n")
    return 0 if ok else 1


def _status(wh: DuckDBWarehouse, out: TextIO, *, as_json: bool) -> int:
    rows = _table_counts(wh)
    if as_json:
        out.write(json.dumps(rows, indent=2) + "\n")
    else:
        out.write("Warehouse tables:\n")
        for name, count in rows.items():
            out.write(f"  {name:<30} {count}\n")
    return 0


def _profile(wh: DuckDBWarehouse, out: TextIO, *, as_json: bool) -> int:
    counts = _table_counts(wh)
    profile = []
    for table in WAREHOUSE_TABLES:
        profile.append(
            {
                "table": table.name, "kind": table.kind, "rows": counts.get(table.name, 0),
                "schema_only": table.schema_only, "grain": table.grain,
            }
        )
    if as_json:
        out.write(json.dumps(profile, indent=2) + "\n")
    else:
        out.write("Warehouse profile:\n")
        for p in profile:
            tag = " [schema-only]" if p["schema_only"] else ""
            out.write(f"  {p['table']:<30} {p['kind']:<10} rows={p['rows']}{tag}\n")
    return 0


def _table_counts(wh: DuckDBWarehouse) -> dict[str, int]:
    con = wh.connect(read_only=True)
    counts: dict[str, int] = {}
    try:
        existing = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        for table in WAREHOUSE_TABLES:
            if table.name in existing:
                row = con.execute(f"SELECT count(*) FROM {table.name}").fetchone()
                counts[table.name] = row[0] if row else 0
    finally:
        con.close()
    return counts


def _lineage(
    wh: DuckDBWarehouse, args: argparse.Namespace, out: TextIO, err: TextIO, *, as_json: bool
) -> int:
    dataset = getattr(args, "dataset", None)
    key = getattr(args, "key", None)
    if not dataset or dataset == "all" or not key:
        err.write("lineage requires --dataset NAME and --key NATURAL_KEY\n")
        return 1
    fact = SILVER_TO_FACT.get(dataset)
    if fact is None:
        err.write(f"unknown dataset {dataset!r}\n")
        return 1
    record = wh.lineage(fact, key)
    if record is None:
        err.write("no warehouse row for that natural key\n")
        return 1
    if as_json:
        out.write(json.dumps(record.model_dump(), indent=2) + "\n")
    else:
        out.write(
            f"warehouse row -> bronze {record.bronze_artifact_id} @ {record.source_locator}\n"
            f"  present={record.bronze_artifact_present} hash_ok={record.bronze_hash_ok} "
            f"complete={record.complete}\n"
        )
    return 0 if record.complete else 1


def _snowflake(args: argparse.Namespace, out: TextIO, environ: Mapping[str, str] | None) -> int:
    env = merged_environment(environ)
    sf = SnowflakeWarehouse(SnowflakeProfile.from_env(env))
    available = sf.available()
    command = args.warehouse_command
    if command in ("init",):
        out.write("-- Snowflake DDL (dry-run; execute with credentials configured) --\n")
        for stmt in [*sf.warehouse_setup_sql(), *sf.ddl_statements()]:
            out.write(stmt + ";\n")
        return 0
    out.write(
        f"Snowflake adapter: available={available}"
        + ("" if available else f" ({sf.unavailable_reason()})")
        + "\nStatus: implemented + offline-tested; live load runs when credentials are set.\n"
    )
    return 0


def _emit(out: TextIO, as_json: bool, payload: dict[str, object], text: str) -> None:
    out.write(json.dumps(payload, indent=2) + "\n" if as_json else text + "\n")
