"""Bronze->Silver transformation engine.

A full, deterministic recompute from the immutable Bronze layer: read every
relevant Bronze artifact, normalize to typed observations, attach lineage, apply
quality gates, deduplicate at the natural-key level (collapsing byte-identical
observations, quarantining conflicts, retaining true revisions), reconcile every
extracted observation, and — only if reconciliation balances — publish partitioned
Parquet atomically. Because it recomputes from immutable Bronze, reruns are
idempotent and prior research stays reproducible.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from strix.canonical import canonical_hash, pretty_json_bytes
from strix.lakehouse.bronze import BronzeIngestor
from strix.lakehouse.contracts import DataSource, ProvenanceManifest
from strix.lakehouse.ingest.catalog import load_manifests
from strix.lakehouse.silver.dedup import deduplicate
from strix.lakehouse.silver.models import (
    QuarantinedRow,
    QuarantineReason,
    ReconciliationReport,
    TransformResult,
)
from strix.lakehouse.silver.normalizers import NORMALIZERS
from strix.lakehouse.silver.publish import publish_dataset
from strix.lakehouse.silver.quality import check_row
from strix.lakehouse.silver.schemas import BRONZE_TO_SILVER, SILVER_SCHEMAS, DatasetSchema
from strix.lakehouse.storage import LocalObjectStore

_SILVER_TO_BRONZE: dict[str, tuple[DataSource, str]] = {v: k for k, v in BRONZE_TO_SILVER.items()}

#: Field used for optional --start/--end workload filtering per dataset.
_PRIMARY_DATE: dict[str, str] = {
    "alpaca_equity_bars_daily": "session_date",
    "sec_company_facts": "period_end",
    "treasury_yield_curve": "date",
    "bls_observations": "observation_date",
    "fred_observations": "observation_date",
}


class SilverTransformer:
    def __init__(self, root: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        self._root = Path(root)
        self._store = LocalObjectStore(root)
        self._bronze = BronzeIngestor(self._store)
        self._clock = clock or (lambda: datetime.now(UTC))

    def datasets(self) -> tuple[str, ...]:
        return tuple(SILVER_SCHEMAS)

    def transform(
        self, dataset: str, *, start: date | None = None, end: date | None = None
    ) -> TransformResult:
        schema = SILVER_SCHEMAS[dataset]
        source, bronze_dataset = _SILVER_TO_BRONZE[dataset]
        normalizer = NORMALIZERS[dataset]
        date_field = _PRIMARY_DATE[dataset]
        started = self._clock()

        manifests = [
            m for m in load_manifests(self._store, source=source) if m.dataset == bronze_dataset
        ]
        extracted = excluded = 0
        kept: list[dict[str, Any]] = []
        quarantined: list[QuarantinedRow] = []

        for manifest in manifests:
            raw = self._bronze.read_artifact(manifest.artifact)
            for row in normalizer(raw, manifest):
                extracted += 1
                self._enrich(row, manifest, schema)
                if _outside_window(row.get(date_field), start, end):
                    excluded += 1
                    continue
                verdict = check_row(schema, row)
                if verdict is not None:
                    reason, detail = verdict
                    quarantined.append(_quarantine(dataset, reason, detail, row))
                else:
                    kept.append(row)

        dedup = deduplicate(schema, kept)
        for conflict_row, detail in dedup.conflicts:
            quarantined.append(
                _quarantine(dataset, QuarantineReason.SUPERSEDED_REVISION, detail, conflict_row)
            )

        accepted = dedup.canonical
        discrepancies: list[str] = []
        accounted = len(accepted) + dedup.duplicates + len(quarantined) + excluded
        if accounted != extracted:
            discrepancies.append(
                f"reconciliation does not balance: extracted={extracted} != "
                f"accepted={len(accepted)} + duplicates={dedup.duplicates} + "
                f"quarantined={len(quarantined)} + excluded={excluded}"
            )

        reconciliation = ReconciliationReport(
            dataset=dataset,
            source_artifacts=len(manifests),
            extracted_observations=extracted,
            accepted=len(accepted),
            duplicates=dedup.duplicates,
            quarantined=len(quarantined),
            excluded=excluded,
            published_rows=len(accepted),
            revisions_retained=dedup.revisions_retained,
            discrepancies=tuple(discrepancies),
        )

        self._write_quarantine(dataset, quarantined)

        if not reconciliation.balanced:
            return TransformResult(
                dataset=dataset,
                published=False,
                manifest=None,
                reconciliation=reconciliation,
                quarantined=tuple(quarantined),
                blocked_reason="reconciliation failed; publication blocked",
                started_at=started,
                finished_at=self._clock(),
            )

        publication = publish_dataset(
            self._root, schema, accepted, reconciliation, now=self._clock()
        )
        return TransformResult(
            dataset=dataset,
            published=True,
            manifest=publication,
            reconciliation=reconciliation,
            quarantined=tuple(quarantined),
            started_at=started,
            finished_at=self._clock(),
        )

    # -- internals ---------------------------------------------------------

    def _enrich(
        self, row: dict[str, Any], manifest: ProvenanceManifest, schema: DatasetSchema
    ) -> None:
        row["source_feed"] = schema.source.value
        row["bronze_artifact_id"] = manifest.artifact.artifact_id
        row["retrieved_at"] = manifest.retrieved_at
        row["schema_version"] = schema.schema_version
        row["natural_key"] = canonical_hash({k: row.get(k) for k in schema.natural_keys})

    def _write_quarantine(self, dataset: str, rows: list[QuarantinedRow]) -> None:
        out_dir = self._root / "silver" / "_quarantine"
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = pretty_json_bytes([r.model_dump() for r in rows])
        path = out_dir / f"{dataset}.json"
        fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=f".{dataset}.")
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp, path)


def _outside_window(value: Any, start: date | None, end: date | None) -> bool:
    if not isinstance(value, date):
        return False
    if start is not None and value < start:
        return True
    return end is not None and value > end


def _quarantine(
    dataset: str, reason: QuarantineReason, detail: str, row: dict[str, Any]
) -> QuarantinedRow:
    return QuarantinedRow(
        dataset=dataset,
        reason=reason,
        detail=detail,
        natural_key=str(row.get("natural_key", "")),
        bronze_artifact_id=str(row.get("bronze_artifact_id", "")),
        source_locator=str(row.get("source_locator", "")),
    )
