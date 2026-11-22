"""Collects and preserves evidence and observation series for one research run.

Every source-backed claim resolves to an :class:`AgentEvidence` record here.
Raw artifact bytes are preserved and content-hashed (SHA-256); evidence ids are
derived from that hash, so identical sources deduplicate. Preserved observation
series are the ground the numerical verifier recomputes from.

Artifact paths are internal references (``artifacts/<hash>.bin``); the collector
never exposes the real filesystem, and callers decide what to surface.
"""

from __future__ import annotations

from datetime import datetime

from strix.agent.models import (
    AgentEvidence,
    FreshnessStatus,
    Observation,
    ObservationSeries,
    SourceKind,
)
from strix.canonical import sha256_hex

#: Default staleness window (days) for freshness classification.
DEFAULT_MAX_AGE_DAYS = 45


class EvidenceCollector:
    """In-memory registry of preserved evidence and series for one run."""

    def __init__(self) -> None:
        self._evidence: dict[str, AgentEvidence] = {}
        self._series: dict[str, ObservationSeries] = {}
        self._artifacts: dict[str, bytes] = {}

    def register(
        self,
        *,
        source_type: SourceKind,
        provider: str,
        source_title: str,
        raw: bytes,
        retrieved_at: datetime,
        source_url: str | None = None,
        published_at: datetime | None = None,
        observation_period: str | None = None,
        source_anchor: str | None = None,
        excerpt: str | None = None,
        freshness_status: FreshnessStatus | None = None,
    ) -> AgentEvidence:
        """Preserve raw bytes and return a deduplicated evidence record."""
        content_hash = sha256_hex(raw)
        evidence_id = AgentEvidence.make_id(content_hash, source_url, source_anchor)
        if evidence_id in self._evidence:
            return self._evidence[evidence_id]
        freshness = freshness_status or classify_freshness(published_at, retrieved_at)
        evidence = AgentEvidence(
            evidence_id=evidence_id,
            source_type=source_type,
            provider=provider,
            source_title=source_title,
            source_url=source_url,
            retrieved_at=retrieved_at,
            published_at=published_at,
            observation_period=observation_period,
            content_hash=content_hash,
            artifact_path=f"artifacts/{content_hash}.bin",
            source_anchor=source_anchor,
            excerpt=excerpt,
            freshness_status=freshness,
        )
        self._evidence[evidence_id] = evidence
        self._artifacts[content_hash] = raw
        return evidence

    def add_series(
        self,
        *,
        subject: str,
        concept: str,
        unit: str,
        observations: tuple[Observation, ...],
        source_evidence_id: str,
    ) -> ObservationSeries:
        """Record a preserved numeric series extracted from an evidence record."""
        if source_evidence_id not in self._evidence:
            raise KeyError(f"series references unknown evidence {source_evidence_id!r}")
        series = ObservationSeries(
            series_id=ObservationSeries.make_id(subject, concept, observations),
            subject=subject,
            concept=concept,
            unit=unit,
            observations=observations,
            source_evidence_id=source_evidence_id,
        )
        self._series[series.series_id] = series
        return series

    # -- read-only access --------------------------------------------------

    def evidence(self, evidence_id: str) -> AgentEvidence | None:
        return self._evidence.get(evidence_id)

    def series(self, series_id: str) -> ObservationSeries | None:
        return self._series.get(series_id)

    def artifact_bytes(self, content_hash: str) -> bytes | None:
        return self._artifacts.get(content_hash)

    def all_evidence(self) -> tuple[AgentEvidence, ...]:
        return tuple(self._evidence.values())

    def all_series(self) -> tuple[ObservationSeries, ...]:
        return tuple(self._series.values())

    def all_artifacts(self) -> dict[str, bytes]:
        """Content-hash -> preserved raw bytes (copy)."""
        return dict(self._artifacts)

    def put_evidence(self, evidence: AgentEvidence) -> None:
        """Insert a prebuilt evidence record (used when reloading a run)."""
        self._evidence[evidence.evidence_id] = evidence

    def put_series(self, series: ObservationSeries) -> None:
        """Insert a prebuilt series (used when reloading a run for replay)."""
        self._series[series.series_id] = series


def classify_freshness(
    published_at: datetime | None,
    reference: datetime,
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> FreshnessStatus:
    """Classify freshness from publication age relative to a reference time."""
    if published_at is None:
        return FreshnessStatus.UNKNOWN
    age_days = (reference - published_at).total_seconds() / 86400
    if age_days < 0:
        return FreshnessStatus.UNKNOWN
    return FreshnessStatus.CURRENT if age_days <= max_age_days else FreshnessStatus.STALE
