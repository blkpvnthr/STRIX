"""Observation-level deduplication, conflict handling, and revision counting.

Rows sharing a natural key are collapsed: byte-identical observations (same data,
different response envelope) become one canonical row counted as a duplicate;
rows with the *same* natural key but *different* data are a conflict — the latest
retrieval wins and the superseded value is quarantined (never silently dropped).

Legitimate revisions (SEC restatements across accessions, FRED vintages) have
*distinct* natural keys, so they are retained as separate canonical rows; the
revision count reports how many such revisions exist beyond the base observation.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from strix.lakehouse.silver.schemas import DatasetSchema

# Columns that are lineage/provenance, not observation data.
_NON_DATA = frozenset(
    {"natural_key", "bronze_artifact_id", "source_locator", "retrieved_at",
     "schema_version", "source_feed"}
)

# Logical-observation key (ignoring the vintage/filing dimension) per dataset, used
# only to *report* how many retained rows are revisions of a base observation.
_REVISION_FAMILY: dict[str, tuple[str, ...]] = {
    "sec_company_facts": ("cik", "taxonomy", "concept", "unit", "period_start", "period_end"),
    "fred_observations": ("series_id", "observation_date"),
}


@dataclass(frozen=True)
class DedupResult:
    canonical: list[dict[str, Any]]
    duplicates: int
    conflicts: list[tuple[dict[str, Any], str]]
    revisions_retained: int


def deduplicate(schema: DatasetSchema, rows: list[dict[str, Any]]) -> DedupResult:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["natural_key"]].append(row)

    data_fields = [
        f.name for f in schema.arrow_schema if f.name not in _NON_DATA
    ]
    canonical: list[dict[str, Any]] = []
    duplicates = 0
    conflicts: list[tuple[dict[str, Any], str]] = []

    for group in groups.values():
        if len(group) == 1:
            canonical.append(group[0])
            continue
        ordered = sorted(group, key=lambda r: r["retrieved_at"], reverse=True)
        winner = ordered[0]
        canonical.append(winner)
        for other in ordered[1:]:
            if _data_equal(data_fields, winner, other):
                duplicates += 1
            else:
                conflicts.append(
                    (other, "value differs from the latest-retrieved canonical for this key")
                )
    return DedupResult(
        canonical=canonical,
        duplicates=duplicates,
        conflicts=conflicts,
        revisions_retained=_count_revisions(schema, canonical),
    )


def _data_equal(data_fields: list[str], a: dict[str, Any], b: dict[str, Any]) -> bool:
    return all(a.get(f) == b.get(f) for f in data_fields)


def _count_revisions(schema: DatasetSchema, canonical: list[dict[str, Any]]) -> int:
    family = _REVISION_FAMILY.get(schema.name)
    if not family:
        return 0
    seen: dict[tuple[Any, ...], int] = defaultdict(int)
    for row in canonical:
        seen[tuple(row.get(k) for k in family)] += 1
    return sum(count - 1 for count in seen.values() if count > 1)
