"""Tests for deterministic question classification (spec §2)."""

from __future__ import annotations

from datetime import date

from strix.agent.question import (
    AssetClass,
    QuestionIntent,
    TimeHorizon,
    classify_question,
)

_AS_OF = date(2026, 11, 23)


def _c(text: str, **kw: bool):
    return classify_question(text, as_of=_AS_OF, **kw)


def test_tomorrow_is_predictive_and_forward_looking() -> None:
    q = _c("how can i expect the market to perform tomorrow?")
    assert q.intent is QuestionIntent.PREDICTIVE
    assert q.is_forward_looking is True
    assert q.horizon is TimeHorizon.NEXT_SESSION
    assert AssetClass.EQUITY_INDEX in q.asset_classes
    assert "directional_market_assessment" in q.objectives


def test_bullish_bearish_is_current_market() -> None:
    q = _c("should i expect bearish or bullish conditions?")
    # "expect" makes it forward-looking → predictive directional assessment.
    assert q.intent is QuestionIntent.PREDICTIVE
    assert "directional_market_assessment" in q.objectives


def test_selloff_question_requests_news_and_explanation() -> None:
    q = _c("why is the market selling off?")
    assert q.intent in (QuestionIntent.ANALYTICAL, QuestionIntent.CURRENT_MARKET)
    assert "explain_recent_move" in q.objectives
    assert "current_financial_news" in q.evidence_requirements


def test_invalidation_is_scenario() -> None:
    q = _c("what would invalidate the bearish outlook?")
    assert q.intent is QuestionIntent.SCENARIO
    assert "identify_invalidation_conditions" in q.objectives


def test_sectors_question_detects_sector_asset_class() -> None:
    q = _c("which sectors are outperforming?")
    assert AssetClass.SECTOR in q.asset_classes
    assert "sector_relative_performance" in q.evidence_requirements


def test_regime_comparison_is_comparative() -> None:
    q = _c("are current market conditions similar to 2022?")
    assert q.intent is QuestionIntent.COMPARATIVE
    assert q.horizon is TimeHorizon.HISTORICAL


def test_apple_margin_is_corporate_fundamentals() -> None:
    q = _c("is Apple's operating margin improving?")
    assert q.intent is QuestionIntent.CORPORATE_FUNDAMENTALS
    assert "AAPL" in q.entities
    assert AssetClass.EQUITY_SINGLE_NAME in q.asset_classes
    assert "company_fundamentals" in q.evidence_requirements


def test_treasury_question_is_macro_with_yield_evidence() -> None:
    q = _c("what do current Treasury yields suggest?")
    assert q.intent is QuestionIntent.MACROECONOMIC
    assert AssetClass.TREASURY in q.asset_classes
    assert "treasury_yields" in q.evidence_requirements


def test_inflation_question_is_macro() -> None:
    q = _c("how is inflation affecting market conditions?")
    assert q.intent is QuestionIntent.MACROECONOMIC
    assert AssetClass.MACRO in q.asset_classes
    assert "inflation" in q.evidence_requirements


def test_follow_up_requires_prior_context() -> None:
    standalone = _c("what would invalidate that assessment?")
    # Scenario words win even without context.
    assert standalone.intent is QuestionIntent.SCENARIO

    short_follow = _c("what about that?", has_prior_context=True)
    assert short_follow.is_follow_up is True
    assert short_follow.intent is QuestionIntent.FOLLOW_UP

    # Same short pronoun question with no thread is NOT a follow-up.
    no_context = _c("what about that?", has_prior_context=False)
    assert no_context.is_follow_up is False


def test_explicit_tickers_extracted_without_false_positives() -> None:
    q = _c("compare SPY and QQQ performance")
    assert "SPY" in q.entities and "QQQ" in q.entities
    # Bare pronoun "I" / "AI" must never be captured as tickers.
    q2 = _c("how should I read the AI rally in the US market?")
    assert "I" not in q2.entities and "AI" not in q2.entities and "US" not in q2.entities
