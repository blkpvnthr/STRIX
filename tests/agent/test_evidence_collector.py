"""Tests for evidence preservation and observation-series collection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from strix.agent.evidence_collector import EvidenceCollector, classify_freshness
from strix.agent.models import FreshnessStatus, Observation, SourceKind
from strix.canonical import sha256_hex

_NOW = datetime(2026, 11, 22, tzinfo=UTC)


def _collector_with_evidence() -> tuple[EvidenceCollector, str]:
    collector = EvidenceCollector()
    ev = collector.register(
        source_type=SourceKind.MARKET_DATA,
        provider="Alpaca",
        source_title="SPY bars",
        raw=b'{"bars":[]}',
        retrieved_at=_NOW,
        source_url="https://data.alpaca.markets/v2/stocks/SPY/bars",
    )
    return collector, ev.evidence_id


def test_register_sets_content_hash_and_artifact() -> None:
    collector, evidence_id = _collector_with_evidence()
    ev = collector.evidence(evidence_id)
    assert ev is not None
    assert ev.content_hash == sha256_hex(b'{"bars":[]}')
    assert ev.artifact_path == f"artifacts/{ev.content_hash}.bin"
    assert collector.artifact_bytes(ev.content_hash) == b'{"bars":[]}'


def test_register_deduplicates_identical_bytes_and_url() -> None:
    collector = EvidenceCollector()
    a = collector.register(
        source_type=SourceKind.WEB_PAGE,
        provider="x",
        source_title="t",
        raw=b"same",
        retrieved_at=_NOW,
        source_url="https://x",
    )
    b = collector.register(
        source_type=SourceKind.WEB_PAGE,
        provider="x",
        source_title="t",
        raw=b"same",
        retrieved_at=_NOW,
        source_url="https://x",
    )
    assert a.evidence_id == b.evidence_id
    assert len(collector.all_evidence()) == 1


def test_different_url_gives_different_evidence_id() -> None:
    collector = EvidenceCollector()
    a = collector.register(
        source_type=SourceKind.WEB_PAGE, provider="x", source_title="t", raw=b"same",
        retrieved_at=_NOW, source_url="https://a",
    )
    b = collector.register(
        source_type=SourceKind.WEB_PAGE, provider="x", source_title="t", raw=b"same",
        retrieved_at=_NOW, source_url="https://b",
    )
    assert a.evidence_id != b.evidence_id


def test_add_series_requires_known_evidence() -> None:
    collector = EvidenceCollector()
    try:
        collector.add_series(
            subject="SPY", concept="close", unit="USD",
            observations=(Observation(at="2026-11-20", value=__import__("decimal").Decimal("1")),),
            source_evidence_id="EV-missing",
        )
    except KeyError as exc:
        assert "EV-missing" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected KeyError")


def test_add_series_builds_series() -> None:
    from decimal import Decimal

    collector, evidence_id = _collector_with_evidence()
    obs = (
        Observation(at="2026-11-20", value=Decimal("100")),
        Observation(at="2026-11-21", value=Decimal("110")),
    )
    series = collector.add_series(
        subject="SPY", concept="close", unit="USD",
        observations=obs, source_evidence_id=evidence_id,
    )
    assert series.values == (Decimal("100"), Decimal("110"))
    assert collector.series(series.series_id) is series
    assert series.source_evidence_id == evidence_id


def test_classify_freshness() -> None:
    assert classify_freshness(None, _NOW) is FreshnessStatus.UNKNOWN
    assert classify_freshness(_NOW - timedelta(days=5), _NOW) is FreshnessStatus.CURRENT
    assert classify_freshness(_NOW - timedelta(days=200), _NOW) is FreshnessStatus.STALE
    # Publication in the future is treated as unknown, not current.
    assert classify_freshness(_NOW + timedelta(days=1), _NOW) is FreshnessStatus.UNKNOWN
