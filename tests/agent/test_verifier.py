"""Tests for the independent claim verification engine."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from strix.agent import calculations as calc
from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import (
    AgentCalculation,
    AgentClaim,
    AgentClaimType,
    AgentVerificationStatus,
    CalculationMethod,
    FreshnessStatus,
    Observation,
    SourceKind,
)
from strix.agent.verifier import verify_claim

_NOW = datetime(2026, 11, 22, tzinfo=UTC)
_PRICES = ["100", "110", "99", "105"]


def _setup(*, published_at: datetime | None = None, freshness=FreshnessStatus.CURRENT):
    collector = EvidenceCollector()
    ev = collector.register(
        source_type=SourceKind.MARKET_DATA,
        provider="Alpaca",
        source_title="SPY bars",
        raw=b'{"bars":[...]}',
        retrieved_at=_NOW,
        source_url="https://data.alpaca.markets/v2/stocks/SPY/bars",
        published_at=published_at,
        freshness_status=freshness,
    )
    obs = tuple(
        Observation(at=f"2026-11-{20 + i}", value=Decimal(p)) for i, p in enumerate(_PRICES)
    )
    series = collector.add_series(
        subject="SPY", concept="close", unit="USD",
        observations=obs, source_evidence_id=ev.evidence_id,
    )
    return collector, ev, series


def _quant_claim(series_id: str, evidence_ids: tuple[str, ...], claimed: Decimal) -> AgentClaim:
    calculation = AgentCalculation(
        method=CalculationMethod.PERIOD_RETURN,
        calculation_version=calc.CALC_VERSION,
        input_series_ids=(series_id,),
        claimed_value=claimed,
        units="ratio",
    )
    return AgentClaim(
        claim_id="CL-1",
        claim_type=AgentClaimType.QUANTITATIVE,
        statement="SPY period return",
        evidence_ids=evidence_ids,
        calculation=calculation,
    )


def test_correct_number_is_verified() -> None:
    collector, ev, series = _setup()
    expected = calc.period_return([Decimal(p) for p in _PRICES])
    claim = _quant_claim(series.series_id, (ev.evidence_id,), expected)
    result = verify_claim(claim, collector, now=_NOW)
    assert result.verification.status is AgentVerificationStatus.VERIFIED
    assert result.verification.computed_value == expected
    assert result.verification.verifier_version == "agent-verify-1.0.0"


def test_wrong_number_is_contradicted() -> None:
    collector, ev, series = _setup()
    claim = _quant_claim(series.series_id, (ev.evidence_id,), Decimal("0.99"))
    result = verify_claim(claim, collector, now=_NOW)
    assert result.verification.status is AgentVerificationStatus.CONTRADICTED
    assert "differs from claimed" in (result.verification.reason or "")


def test_missing_series_is_insufficient() -> None:
    collector, ev, _series = _setup()
    claim = _quant_claim("SER-nonexistent", (ev.evidence_id,), Decimal("0.05"))
    result = verify_claim(claim, collector, now=_NOW)
    assert result.verification.status is AgentVerificationStatus.INSUFFICIENT_EVIDENCE


def test_series_on_uncited_evidence_is_insufficient() -> None:
    collector, _ev, series = _setup()
    # Claim cites a *different* (also-registered) evidence, not the series' source.
    other = collector.register(
        source_type=SourceKind.WEB_PAGE, provider="x", source_title="t",
        raw=b"other", retrieved_at=_NOW, source_url="https://other",
    )
    claim = _quant_claim(series.series_id, (other.evidence_id,), Decimal("0.05"))
    result = verify_claim(claim, collector, now=_NOW)
    assert result.verification.status is AgentVerificationStatus.INSUFFICIENT_EVIDENCE
    assert "uncited evidence" in (result.verification.reason or "")


def test_no_citations_is_insufficient() -> None:
    collector, _ev, series = _setup()
    claim = _quant_claim(series.series_id, (), Decimal("0.05"))
    result = verify_claim(claim, collector, now=_NOW)
    assert result.verification.status is AgentVerificationStatus.INSUFFICIENT_EVIDENCE
    assert "no citations" in (result.verification.reason or "")


def test_unknown_evidence_is_insufficient() -> None:
    collector, _ev, series = _setup()
    claim = _quant_claim(series.series_id, ("EV-ghost",), Decimal("0.05"))
    result = verify_claim(claim, collector, now=_NOW)
    assert result.verification.status is AgentVerificationStatus.INSUFFICIENT_EVIDENCE
    assert "unknown evidence" in (result.verification.reason or "")


def test_quantitative_without_calculation_is_insufficient() -> None:
    collector, ev, _series = _setup()
    claim = AgentClaim(
        claim_id="CL-x",
        claim_type=AgentClaimType.QUANTITATIVE,
        statement="SPY fell 9%",
        evidence_ids=(ev.evidence_id,),
    )
    result = verify_claim(claim, collector, now=_NOW)
    assert result.verification.status is AgentVerificationStatus.INSUFFICIENT_EVIDENCE
    assert "no calculation" in (result.verification.reason or "")


def test_interpretation_is_unverifiable() -> None:
    collector, ev, _series = _setup()
    claim = AgentClaim(
        claim_id="CL-i",
        claim_type=AgentClaimType.INTERPRETATION,
        statement="The decline reflects risk-off sentiment.",
        evidence_ids=(ev.evidence_id,),
    )
    result = verify_claim(claim, collector, now=_NOW)
    assert result.verification.status is AgentVerificationStatus.UNVERIFIABLE


def test_verified_but_stale_is_downgraded() -> None:
    collector, ev, series = _setup(freshness=FreshnessStatus.STALE)
    expected = calc.period_return([Decimal(p) for p in _PRICES])
    claim = _quant_claim(series.series_id, (ev.evidence_id,), expected)
    result = verify_claim(claim, collector, now=_NOW)
    assert result.verification.status is AgentVerificationStatus.STALE


def test_attributed_statement_found_in_excerpt_is_verified() -> None:
    collector = EvidenceCollector()
    ev = collector.register(
        source_type=SourceKind.NEWS_ARTICLE,
        provider="Reuters",
        source_title="Market wrap",
        raw=b"full article bytes",
        retrieved_at=_NOW,
        source_url="https://reuters.example/x",
        excerpt="The Federal Reserve held rates steady on Wednesday.",
        freshness_status=FreshnessStatus.CURRENT,
    )
    claim = AgentClaim(
        claim_id="CL-a",
        claim_type=AgentClaimType.ATTRIBUTED_STATEMENT,
        statement="Reuters reported the Fed held rates steady.",
        attributed_to="The Federal Reserve held rates steady",
        evidence_ids=(ev.evidence_id,),
    )
    result = verify_claim(claim, collector, now=_NOW)
    assert result.verification.status is AgentVerificationStatus.VERIFIED
    assert result.verification.method == "source_attribution"


def test_attributed_statement_not_in_excerpt_is_insufficient() -> None:
    collector = EvidenceCollector()
    ev = collector.register(
        source_type=SourceKind.NEWS_ARTICLE, provider="Reuters", source_title="x",
        raw=b"bytes", retrieved_at=_NOW, source_url="https://x",
        excerpt="Unrelated text about something else entirely.",
    )
    claim = AgentClaim(
        claim_id="CL-a2",
        claim_type=AgentClaimType.ATTRIBUTED_STATEMENT,
        statement="The Fed cut rates by 50 basis points.",
        attributed_to="The Fed cut rates by 50 basis points",
        evidence_ids=(ev.evidence_id,),
    )
    result = verify_claim(claim, collector, now=_NOW)
    assert result.verification.status is AgentVerificationStatus.INSUFFICIENT_EVIDENCE
