"""`strix transform` command implementations (dbt orchestration + cross-validation).

Every dbt call goes through :class:`DbtRunner` with controlled, validated arguments
and no shell. The language model is never given raw SQL or shell access through this
surface.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from strix.lakehouse.ingest.cli import resolve_lakehouse_dir
from strix.lakehouse.transform.contracts import DbtRunResult
from strix.lakehouse.transform.runner import DbtError, DbtRunner, resolve_project_dir
from strix.lakehouse.transform.verification import WarehouseCrossValidator
from strix.lakehouse.warehouse.duckdb_warehouse import DuckDBWarehouse


def _db_path(args: argparse.Namespace, root: Path) -> Path:
    if getattr(args, "db_path", None):
        return Path(args.db_path)
    return root / "warehouse" / "strix.duckdb"


def _runner(args: argparse.Namespace, environ: Mapping[str, str] | None) -> tuple[DbtRunner, Path]:
    root = resolve_lakehouse_dir(getattr(args, "lakehouse_dir", None), environ)
    db = _db_path(args, root)
    project = resolve_project_dir(getattr(args, "project_dir", None), environ)
    backend = getattr(args, "backend", "duckdb")
    return DbtRunner(project, db, backend=backend, environ=environ), db


def run_transform(
    args: argparse.Namespace, *, out: TextIO, err: TextIO, environ: Mapping[str, str] | None = None
) -> int:
    command = args.transform_command
    as_json = getattr(args, "json", False)
    runner, db = _runner(args, environ)

    try:
        if command == "init":
            return _init(runner, db, args, out, as_json=as_json)
        if command == "run":
            return _invoke(runner, "run", args, out, err, as_json=as_json)
        if command == "test":
            return _invoke(runner, "test", args, out, err, as_json=as_json)
        if command == "build":
            return _invoke(runner, "build", args, out, err, as_json=as_json)
        if command == "docs":
            return _invoke(runner, "docs", args, out, err, as_json=as_json)
        if command == "status":
            return _status(runner, db, out, as_json=as_json)
        if command == "profile":
            return _profile(runner, out, as_json=as_json)
        if command == "lineage":
            return _lineage(runner, args, out, err, as_json=as_json)
        if command == "validate":
            return _validate(db, args, out, err, as_json=as_json)
    except DbtError as exc:
        err.write(f"transform error: {exc}\n")
        return 1
    err.write(f"unknown transform command {command!r}\n")
    return 1


def _init(
    runner: DbtRunner, db: Path, args: argparse.Namespace, out: TextIO, *, as_json: bool
) -> int:
    profile = runner.write_profile()
    # Ensure the warehouse schema exists so dbt sources resolve (DuckDB only).
    created: list[str] = []
    if runner.backend == "duckdb":
        created = DuckDBWarehouse(db, db.parent.parent).init_schema()
    steps: list[DbtRunResult] = []
    if getattr(args, "with_deps", False):
        steps.append(runner.invoke("deps", timeout=getattr(args, "timeout", None)))
    if runner.backend == "duckdb":
        steps.append(runner.invoke("seed", timeout=getattr(args, "timeout", None)))
    # parse validates the project (for snowflake this is offline jinja validation).
    steps.append(runner.invoke("parse", timeout=getattr(args, "timeout", None)))
    ok = all(s.success for s in steps)
    if as_json:
        out.write(json.dumps(
            {"profile": str(profile), "warehouse_tables": len(created),
             "steps": [s.model_dump(mode="json") for s in steps], "ok": ok}, indent=2) + "\n")
    else:
        out.write(f"Wrote profile: {profile}\n")
        if created:
            out.write(f"Warehouse schema ready ({len(created)} tables).\n")
        for s in steps:
            out.write(f"  dbt {s.dbt_subcommand}: {'ok' if s.success else 'FAILED'} "
                      f"({s.elapsed_seconds}s)\n")
        if runner.backend == "snowflake":
            out.write("Snowflake: offline parse validated; full compile/run needs credentials.\n")
    return 0 if ok else 1


def _invoke(
    runner: DbtRunner, sub: str, args: argparse.Namespace, out: TextIO, err: TextIO,
    *, as_json: bool,
) -> int:
    result = runner.invoke(
        sub,
        select=getattr(args, "select", None),
        full_refresh=getattr(args, "full_refresh", False),
        timeout=getattr(args, "timeout", None),
    )
    if as_json:
        out.write(json.dumps(result.model_dump(mode="json"), indent=2) + "\n")
    else:
        out.write(
            f"dbt {result.dbt_subcommand} (target={result.backend}): "
            f"{'ok' if result.success else 'FAILED'} in {result.elapsed_seconds}s — "
            f"pass={result.pass_count} fail={result.fail_count} "
            f"error={result.error_count} skip={result.skip_count}\n"
        )
        if result.source_publications:
            out.write(f"  source publications: {len(result.source_publications)} dataset(s)\n")
        if not result.success:
            err.write(result.stderr_tail or result.stdout_tail)
            err.write("\n")
    return 0 if result.success else 1


def _status(runner: DbtRunner, db: Path, out: TextIO, *, as_json: bool) -> int:
    inventory = runner.model_inventory()
    by_layer: dict[str, int] = {}
    for m in inventory:
        by_layer[m.layer] = by_layer.get(m.layer, 0) + 1
    pubs = runner.source_publications()
    payload = {
        "models_by_layer": by_layer,
        "total_models": len(inventory),
        "source_publications": pubs,
        "warehouse_db": str(db),
        "warehouse_present": db.is_file(),
    }
    if as_json:
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        out.write("Transform status:\n")
        if not inventory:
            out.write("  no manifest yet — run `strix transform build` first.\n")
        for layer, n in sorted(by_layer.items()):
            out.write(f"  {layer:<14} {n} model(s)\n")
        out.write(f"  source publications: {len(pubs)}\n")
        for ds, pid in sorted(pubs.items()):
            out.write(f"    {ds:<28} {pid[:12]}\n")
    return 0


def _profile(runner: DbtRunner, out: TextIO, *, as_json: bool) -> int:
    inventory = runner.model_inventory()
    if as_json:
        out.write(json.dumps([m.model_dump() for m in inventory], indent=2) + "\n")
    elif not inventory:
        out.write("No manifest — run `strix transform build` first.\n")
    else:
        out.write("Model inventory:\n")
        for m in inventory:
            out.write(f"  {m.layer:<13} {m.name:<34} {m.materialization:<6} "
                      f"schema={m.schema_name} deps={len(m.depends_on)}\n")
    return 0


def _lineage(
    runner: DbtRunner, args: argparse.Namespace, out: TextIO, err: TextIO, *, as_json: bool
) -> int:
    target = getattr(args, "select", None)
    inventory = {m.name: m for m in runner.model_inventory()}
    if not inventory:
        err.write("no manifest — run `strix transform build` first.\n")
        return 1
    if not target or target not in inventory:
        err.write("lineage requires --select MODEL_NAME (an existing model)\n")
        return 1
    # Walk upstream dependencies transitively.
    seen: list[str] = []
    frontier = [target]
    while frontier:
        node = frontier.pop()
        model = inventory.get(node)
        if model is None:
            continue
        for dep in model.depends_on:
            if dep not in seen:
                seen.append(dep)
                frontier.append(dep)
    if as_json:
        out.write(json.dumps({"model": target, "upstream": seen}, indent=2) + "\n")
    else:
        out.write(f"Lineage for {target}:\n")
        for dep in seen:
            kind = inventory[dep].layer if dep in inventory else "source/seed"
            out.write(f"  <- {dep} ({kind})\n")
        out.write("  row-level evidence resolves via `strix warehouse lineage`.\n")
    return 0


def _validate(
    db: Path, args: argparse.Namespace, out: TextIO, err: TextIO, *, as_json: bool
) -> int:
    validator = WarehouseCrossValidator(db)
    results = []
    symbol = getattr(args, "symbol", None)
    pair = getattr(args, "pair", None)
    cik = getattr(args, "cik", None)
    if symbol:
        results += [
            validator.cumulative_return(symbol),
            validator.max_drawdown(symbol),
            validator.realized_volatility(symbol),
        ]
    if pair:
        try:
            a, b = pair.split(",", 1)
        except ValueError:
            err.write("--pair expects SYMBOL_A,SYMBOL_B\n")
            return 1
        results.append(validator.correlation(a.strip(), b.strip()))
    if cik:
        for ratio in ("gross_profit_margin", "operating_margin", "net_profit_margin"):
            results.append(validator.margin(cik, ratio))
    if not results:
        err.write("validate requires --symbol SYM, --pair A,B, and/or --cik CIK\n")
        return 1
    if as_json:
        out.write(json.dumps([r.model_dump() for r in results], indent=2) + "\n")
    else:
        out.write("Independent cross-validation (SQL mart vs Decimal recompute):\n")
        for r in results:
            out.write(
                f"  [{'OK ' if r.agrees else r.status:<16}] {r.claim}\n"
                f"       sql={r.sql_value} python={r.python_value} "
                f"diff={r.difference} tol={r.tolerance} n={r.sample_size}\n"
            )
    # Any discrepancy on an available value is a failure signal.
    discrepant = [r for r in results if r.status == "discrepancy"]
    return 1 if discrepant else 0
