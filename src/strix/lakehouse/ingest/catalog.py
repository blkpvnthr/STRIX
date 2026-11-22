"""Read-only catalog over the Bronze layer: coverage and integrity checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

from strix.lakehouse.contracts import DataSource, ProvenanceManifest
from strix.lakehouse.storage import ObjectStore

_MANIFEST_PREFIX = "bronze/_manifests"


def load_manifests(
    store: ObjectStore, *, source: DataSource | None = None
) -> list[ProvenanceManifest]:
    prefix = f"{_MANIFEST_PREFIX}/{source.value}" if source else _MANIFEST_PREFIX
    manifests: list[ProvenanceManifest] = []
    for rel in store.iter_paths(prefix):
        if not rel.endswith(".manifest.json"):
            continue
        try:
            manifests.append(ProvenanceManifest.model_validate(json.loads(store.get(rel))))
        except (ValueError, OSError):
            continue
    return manifests


@dataclass(frozen=True)
class DatasetCoverage:
    source: str
    dataset: str
    manifest_count: int
    unique_artifacts: int
    records: int
    bytes_total: int
    windows: tuple[tuple[str, str], ...]


def coverage(store: ObjectStore) -> list[DatasetCoverage]:
    by_key: dict[tuple[str, str], list[ProvenanceManifest]] = {}
    for m in load_manifests(store):
        by_key.setdefault((m.source.value, m.dataset), []).append(m)
    out: list[DatasetCoverage] = []
    for (src, ds), ms in sorted(by_key.items()):
        hashes = {m.artifact.content_hash for m in ms}
        records = sum(m.record_count or 0 for m in ms)
        size = sum(m.artifact.byte_size for m in ms)
        wins = _merge([w for w in (_window_of(m) for m in ms) if w is not None])
        out.append(
            DatasetCoverage(src, ds, len(ms), len(hashes), records, size, wins)
        )
    return out


@dataclass(frozen=True)
class IntegrityReport:
    checked: int
    ok: int
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failures


def verify_integrity(store: ObjectStore) -> IntegrityReport:
    """Re-read every manifest's artifact and verify its recorded content hash."""
    from strix.canonical import sha256_hex

    checked = ok = 0
    failures: list[str] = []
    for m in load_manifests(store):
        checked += 1
        art = m.artifact
        if not store.exists(art.relative_path):
            failures.append(f"missing artifact for {m.ingestion_id}: {art.relative_path}")
            continue
        if sha256_hex(store.get(art.relative_path)) != art.content_hash:
            failures.append(f"hash mismatch for {art.relative_path}")
            continue
        ok += 1
    return IntegrityReport(checked=checked, ok=ok, failures=tuple(failures))


def _window_of(m: ProvenanceManifest) -> tuple[str, str] | None:
    # Manifests don't store the observation window directly; derive a 1-day
    # window from the partition when it is an ISO date (best-effort coverage).
    part = m.partition
    try:
        if "_" in part:
            s, e = part.split("_", 1)
            date.fromisoformat(s)
            date.fromisoformat(e)
            return (s, e)
        date.fromisoformat(part)
        return (part, part)
    except ValueError:
        return None


def _merge(ranges: list[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    items = sorted((date.fromisoformat(s), date.fromisoformat(e)) for s, e in ranges)
    if not items:
        return ()
    merged: list[tuple[date, date]] = [items[0]]
    for s, e in items[1:]:
        ls, le = merged[-1]
        if s <= le + timedelta(days=1):
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return tuple((s.isoformat(), e.isoformat()) for s, e in merged)
