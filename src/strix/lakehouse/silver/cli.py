"""`strix normalize` command implementations (Bronze -> Silver)."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, TextIO

from strix.canonical import sha256_hex, to_jsonable
from strix.lakehouse.ingest.cli import resolve_lakehouse_dir
from strix.lakehouse.silver.engine import SilverTransformer
from strix.lakehouse.silver.models import PublicationManifest, TransformResult
from strix.lakehouse.silver.schemas import SILVER_SCHEMAS


def run_normalize(
    args: argparse.Namespace, *, out: TextIO, err: TextIO, environ: Any = None
) -> int:
    root = resolve_lakehouse_dir(getattr(args, "lakehouse_dir", None), environ)
    command = args.normalize_command
    as_json = getattr(args, "json", False)

    if command == "run":
        return _run(root, args, out, err, as_json=as_json)
    if command == "status":
        return _status(root, out, as_json=as_json)
    if command == "verify":
        return _verify(root, out, as_json=as_json)
    if command in ("profile", "reconcile"):
        return _reports(root, out, as_json=as_json, reconcile=(command == "reconcile"))
    if command == "quarantine":
        return _quarantine(root, out, args, as_json=as_json)
    err.write(f"unknown normalize command {command!r}\n")
    return 1


def _datasets(args: argparse.Namespace) -> list[str]:
    ds = getattr(args, "dataset", None)
    if ds and ds != "all":
        return [ds]
    return list(SILVER_SCHEMAS)


def _run(root: Path, args: argparse.Namespace, out: TextIO, err: TextIO, *, as_json: bool) -> int:
    start = _date(getattr(args, "start", None))
    end = _date(getattr(args, "end", None))
    transformer = SilverTransformer(root)
    results: list[TransformResult] = []
    for dataset in _datasets(args):
        if dataset not in SILVER_SCHEMAS:
            err.write(f"unknown dataset {dataset!r}\n")
            return 1
        results.append(transformer.transform(dataset, start=start, end=end))

    if as_json:
        out.write(json.dumps([to_jsonable(r.model_dump()) for r in results], indent=2) + "\n")
    else:
        for r in results:
            _print_result(r, out)
    return 0 if all(r.published for r in results) else 1


def _print_result(r: TransformResult, out: TextIO) -> None:
    rec = r.reconciliation
    status = "published" if r.published else f"BLOCKED ({r.blocked_reason})"
    out.write(f"- {r.dataset}: {status}\n")
    out.write(
        f"    artifacts={rec.source_artifacts} extracted={rec.extracted_observations} "
        f"accepted={rec.accepted} duplicates={rec.duplicates} "
        f"revisions={rec.revisions_retained} quarantined={rec.quarantined} "
        f"excluded={rec.excluded} balanced={rec.balanced}\n"
    )
    if r.manifest:
        out.write(
            f"    published {r.manifest.row_count} rows "
            f"({r.manifest.natural_key_count} unique keys) in "
            f"{len(r.manifest.files)} partition file(s)\n"
        )
    for d in rec.discrepancies:
        out.write(f"    ! {d}\n")


def _load_manifest(root: Path, dataset: str) -> PublicationManifest | None:
    path = root / "silver" / dataset / "_publication.json"
    if not path.is_file():
        return None
    try:
        return PublicationManifest.model_validate(json.loads(path.read_text()))
    except (ValueError, OSError):
        return None


def _status(root: Path, out: TextIO, *, as_json: bool) -> int:
    summaries: list[dict[str, Any]] = []
    for dataset in SILVER_SCHEMAS:
        m = _load_manifest(root, dataset)
        if m is None:
            continue
        summaries.append(
            {
                "dataset": dataset,
                "rows": m.row_count,
                "unique_keys": m.natural_key_count,
                "partitions": len(m.files),
                "published_at": m.published_at.isoformat(),
                "schema_version": m.schema_version,
            }
        )
    if as_json:
        out.write(json.dumps(summaries, indent=2) + "\n")
    elif not summaries:
        out.write("No Silver datasets published yet.\n")
    else:
        out.write("Published Silver datasets:\n")
        for s in summaries:
            out.write(
                f"  {s['dataset']:<28} rows={s['rows']:<8} keys={s['unique_keys']:<8} "
                f"partitions={s['partitions']:<4} {s['published_at']}\n"
            )
    return 0


def _verify(root: Path, out: TextIO, *, as_json: bool) -> int:
    checked = ok = 0
    failures: list[str] = []
    for dataset in SILVER_SCHEMAS:
        m = _load_manifest(root, dataset)
        if m is None:
            continue
        for f in m.files:
            checked += 1
            path = root / f.relative_path
            if not path.is_file():
                failures.append(f"{dataset}: missing {f.relative_path}")
            elif sha256_hex(path.read_bytes()) != f.content_hash:
                failures.append(f"{dataset}: hash mismatch {f.relative_path}")
            else:
                ok += 1
    if as_json:
        out.write(json.dumps({"checked": checked, "ok": ok, "failures": failures}, indent=2) + "\n")
    else:
        out.write(f"Silver integrity: checked {checked}, ok {ok}, failures {len(failures)}\n")
        for fail in failures:
            out.write(f"  FAIL: {fail}\n")
    return 0 if not failures else 1


def _reports(root: Path, out: TextIO, *, as_json: bool, reconcile: bool) -> int:
    reports: list[dict[str, Any]] = []
    for dataset in SILVER_SCHEMAS:
        m = _load_manifest(root, dataset)
        if m is None:
            continue
        reports.append(to_jsonable(m.reconciliation.model_dump()))
    if as_json:
        out.write(json.dumps(reports, indent=2) + "\n")
    elif not reports:
        out.write("No published datasets to report.\n")
    else:
        out.write("Reconciliation reports:\n" if reconcile else "Dataset profiles:\n")
        for r in reports:
            out.write(
                f"  {r['dataset']:<28} extracted={r['extracted_observations']} "
                f"accepted={r['accepted']} dup={r['duplicates']} rev={r['revisions_retained']} "
                f"quar={r['quarantined']} excl={r['excluded']} balanced={_balanced(r)}\n"
            )
    return 0


def _balanced(r: dict[str, Any]) -> bool:
    accounted = r["accepted"] + r["duplicates"] + r["quarantined"] + r["excluded"]
    return accounted == r["extracted_observations"] and not r["discrepancies"]


def _quarantine(root: Path, out: TextIO, args: argparse.Namespace, *, as_json: bool) -> int:
    qdir = root / "silver" / "_quarantine"
    rows: list[dict[str, Any]] = []
    if qdir.is_dir():
        for path in sorted(qdir.glob("*.json")):
            try:
                rows.extend(json.loads(path.read_text()))
            except (ValueError, OSError):
                continue
    if as_json:
        out.write(json.dumps(rows, indent=2) + "\n")
        return 0
    if not rows:
        out.write("No quarantined observations.\n")
        return 0
    by_reason: dict[str, int] = {}
    for r in rows:
        by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    out.write(f"Quarantined observations: {len(rows)}\n")
    for reason, count in sorted(by_reason.items()):
        out.write(f"  {reason}: {count}\n")
    return 0


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None
