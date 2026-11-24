"""Deterministic question intent classification and entity extraction.

The research plan must address the *actual* question, not merely retrieve
loosely related financial observations. Before any model call, STRIX classifies
the question into a bounded intent, extracts the securities / asset classes it
concerns, the requested time horizon, and the analytical objectives and evidence
it will need. This is intentionally deterministic (keyword/heuristic, no model
call): it is cheap, reproducible, and keeps the LLM budget for synthesis.

The classification is advisory — it shapes the research plan and the synthesis
prompt. It never assigns a verification verdict and never fabricates data.
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum

from strix.models import StrixModel

# --------------------------------------------------------------------------
# Bounded vocabularies
# --------------------------------------------------------------------------


class QuestionIntent(StrEnum):
    """What kind of question is being asked (spec §2)."""

    FACTUAL = "factual"
    CURRENT_MARKET = "current_market"
    ANALYTICAL = "analytical"
    COMPARATIVE = "comparative"
    HISTORICAL = "historical"
    CORPORATE_FUNDAMENTALS = "corporate_fundamentals"
    MACROECONOMIC = "macroeconomic"
    PREDICTIVE = "predictive"
    SCENARIO = "scenario"
    FOLLOW_UP = "follow_up"


class AssetClass(StrEnum):
    EQUITY_INDEX = "equity_index"
    EQUITY_SINGLE_NAME = "equity_single_name"
    SECTOR = "sector"
    TREASURY = "treasury"
    RATES = "rates"
    FX = "fx"
    COMMODITY = "commodity"
    CRYPTO = "crypto"
    MACRO = "macro"
    UNKNOWN = "unknown"


class TimeHorizon(StrEnum):
    INTRADAY = "intraday"
    NEXT_SESSION = "next_session"
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"
    HISTORICAL = "historical"
    UNSPECIFIED = "unspecified"


# --------------------------------------------------------------------------
# Lexical resources (small, auditable, deterministic)
# --------------------------------------------------------------------------

#: Index proxies the agent can actually fetch (ETF proxies, not the index level).
_INDEX_PROXIES = {"SPY", "QQQ", "DIA", "IWM", "VTI", "VOO"}

#: SPDR sector ETFs — the agent's sector-rotation universe.
_SECTOR_ETFS = {
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "XLY",
    "XLP",
    "XLI",
    "XLU",
    "XLB",
    "XLRE",
    "XLC",
}

#: Common company-name -> ticker hints (extend as needed; lower-cased keys).
_COMPANY_TICKERS = {
    "apple": "AAPL",
    "microsoft": "MSFT",
    "nvidia": "NVDA",
    "amazon": "AMZN",
    "alphabet": "GOOGL",
    "google": "GOOGL",
    "meta": "META",
    "tesla": "TSLA",
    "netflix": "NFLX",
    "jpmorgan": "JPM",
    "exxon": "XOM",
}

_FORWARD_WORDS = (
    "tomorrow",
    "next week",
    "next session",
    "expect",
    "will ",
    "going to",
    "outlook",
    "forecast",
    "predict",
    "projection",
    "future",
    "ahead",
)

_SCENARIO_WORDS = (
    "what would",
    "what if",
    "invalidate",
    "scenario",
    "under what",
    "if the",
    "would change",
    "break the",
)

_COMPARATIVE_WORDS = (
    "versus",
    " vs ",
    "compare",
    "comparison",
    "similar to",
    "like 20",  # "like 2022", "like 2008"
    "relative to",
    "outperform",
    "underperform",
    "stronger than",
    "weaker than",
)

_MACRO_WORDS = (
    "inflation",
    "cpi",
    "pce",
    "unemployment",
    "jobs",
    "payroll",
    "fed",
    "fomc",
    "rate cut",
    "rate hike",
    "monetary policy",
    "gdp",
    "recession",
    "economic",
)

_TREASURY_WORDS = (
    "treasury",
    "treasuries",
    "yield",
    "yields",
    "yield curve",
    "10-year",
    "2-year",
    "bond",
    "bonds",
)

_FUNDAMENTAL_WORDS = (
    "margin",
    "operating margin",
    "revenue",
    "earnings",
    "eps",
    "net income",
    "free cash flow",
    "balance sheet",
    "guidance",
    "fundamental",
    "profitability",
)

_SELLOFF_WORDS = (
    "selling off",
    "sell-off",
    "selloff",
    "crash",
    "plunge",
    "tanking",
    "dropping",
    "falling",
    "rally",
    "rallying",
    "surge",
)

_FOLLOWUP_WORDS = (
    "that",
    "it",
    "this",
    "those",
    "the assessment",
    "that outlook",
    "the bearish",
    "the bullish",
)

_BULLBEAR_WORDS = ("bullish", "bearish")

#: A conservative ticker shape: 1-5 upper-case letters, optionally with a class
#: suffix. Matched only on upper-case tokens so ordinary words are not captured.
_TICKER_RE = re.compile(r"\b([A-Z]{1,5}(?:\.[A-Z])?)\b")

#: Words that look like tickers but are ordinary upper-case tokens to ignore.
_TICKER_STOPWORDS = {
    "I",
    "A",
    "AI",
    "US",
    "CEO",
    "CFO",
    "GDP",
    "CPI",
    "PCE",
    "FED",
    "ETF",
    "IPO",
    "SEC",
    "Q",
    "EPS",
    "YTD",
}


# --------------------------------------------------------------------------
# Result contract
# --------------------------------------------------------------------------


class ResearchQuestion(StrixModel):
    """A classified research question — the plan's target, not an answer."""

    text: str
    intent: QuestionIntent
    #: Normalized entity handles (tickers upper-cased; macro terms lower-cased).
    entities: tuple[str, ...]
    horizon: TimeHorizon
    asset_classes: tuple[AssetClass, ...]
    #: Short machine labels for what the user wants established.
    objectives: tuple[str, ...]
    #: Categories of evidence the plan should gather to answer well.
    evidence_requirements: tuple[str, ...]
    is_forward_looking: bool
    is_follow_up: bool


# --------------------------------------------------------------------------
# Classifier
# --------------------------------------------------------------------------


def classify_question(
    text: str,
    *,
    as_of: date | None = None,
    has_prior_context: bool = False,
) -> ResearchQuestion:
    """Classify a research question deterministically.

    ``has_prior_context`` is set by the conversational layer when a thread
    already holds prior turns; it lets short pronoun-led follow-ups resolve to
    FOLLOW_UP rather than being misread as standalone questions.
    """
    raw = text.strip()
    lowered = raw.lower()

    entities = _extract_entities(raw, lowered)
    asset_classes = _asset_classes(lowered, entities)
    is_forward = _contains(lowered, _FORWARD_WORDS) or "perform tomorrow" in lowered
    is_follow_up = _is_follow_up(lowered, has_prior_context)
    intent = _intent(lowered, entities, asset_classes, is_forward, is_follow_up)
    objectives = _objectives(intent, lowered)
    evidence = _evidence_requirements(intent, asset_classes, lowered)
    horizon = _horizon(lowered, intent, is_forward, as_of)

    return ResearchQuestion(
        text=raw,
        intent=intent,
        entities=entities,
        horizon=horizon,
        asset_classes=asset_classes,
        objectives=objectives,
        evidence_requirements=evidence,
        is_forward_looking=is_forward,
        is_follow_up=is_follow_up,
    )


def _extract_entities(raw: str, lowered: str) -> tuple[str, ...]:
    found: list[str] = []
    for token in _TICKER_RE.findall(raw):
        if token in _TICKER_STOPWORDS:
            continue
        if token in _INDEX_PROXIES or token in _SECTOR_ETFS or len(token) >= 2:
            found.append(token)
    for name, ticker in _COMPANY_TICKERS.items():
        if name in lowered:
            found.append(ticker)
    # De-duplicate preserving order.
    return tuple(dict.fromkeys(found))


def _asset_classes(lowered: str, entities: tuple[str, ...]) -> tuple[AssetClass, ...]:
    classes: list[AssetClass] = []
    if any(e in _INDEX_PROXIES for e in entities) or _contains(
        lowered, ("market", "s&p", "sp500", "s&p 500", "nasdaq", "dow", "index", "stocks")
    ):
        classes.append(AssetClass.EQUITY_INDEX)
    if any(e in _SECTOR_ETFS for e in entities) or "sector" in lowered:
        classes.append(AssetClass.SECTOR)
    single = [e for e in entities if e not in _INDEX_PROXIES and e not in _SECTOR_ETFS]
    if single:
        classes.append(AssetClass.EQUITY_SINGLE_NAME)
    if _contains(lowered, _TREASURY_WORDS):
        classes.append(AssetClass.TREASURY)
    if _contains(lowered, ("rate", "rates", "fed funds")):
        classes.append(AssetClass.RATES)
    if _contains(lowered, _MACRO_WORDS):
        classes.append(AssetClass.MACRO)
    if not classes:
        classes.append(AssetClass.UNKNOWN)
    return tuple(dict.fromkeys(classes))


def _intent(
    lowered: str,
    entities: tuple[str, ...],
    asset_classes: tuple[AssetClass, ...],
    is_forward: bool,
    is_follow_up: bool,
) -> QuestionIntent:
    if _contains(lowered, _SCENARIO_WORDS):
        return QuestionIntent.SCENARIO
    if is_forward:
        return QuestionIntent.PREDICTIVE
    if is_follow_up:
        return QuestionIntent.FOLLOW_UP
    if _contains(lowered, _COMPARATIVE_WORDS):
        return QuestionIntent.COMPARATIVE
    if AssetClass.EQUITY_SINGLE_NAME in asset_classes and _contains(
        lowered, _FUNDAMENTAL_WORDS
    ):
        return QuestionIntent.CORPORATE_FUNDAMENTALS
    if _contains(lowered, _TREASURY_WORDS) or _contains(lowered, _MACRO_WORDS):
        return QuestionIntent.MACROECONOMIC
    if _contains(lowered, _BULLBEAR_WORDS) or _contains(lowered, _SELLOFF_WORDS) or _contains(
        lowered, ("right now", "today", "currently", "current conditions", "market doing")
    ):
        return QuestionIntent.CURRENT_MARKET
    if _contains(lowered, ("historically", "in the past", "back in", "during 20")):
        return QuestionIntent.HISTORICAL
    if _contains(lowered, ("why", "how is", "what is driving", "explain", "what does")):
        return QuestionIntent.ANALYTICAL
    return QuestionIntent.FACTUAL


def _objectives(intent: QuestionIntent, lowered: str) -> tuple[str, ...]:
    objectives: list[str] = []
    if intent in (QuestionIntent.PREDICTIVE, QuestionIntent.CURRENT_MARKET):
        objectives.append("directional_market_assessment")
    if intent is QuestionIntent.SCENARIO:
        objectives.append("identify_invalidation_conditions")
    if intent is QuestionIntent.COMPARATIVE:
        objectives.append("compare_regimes")
    if intent is QuestionIntent.CORPORATE_FUNDAMENTALS:
        objectives.append("assess_fundamental_trend")
    if intent is QuestionIntent.MACROECONOMIC:
        objectives.append("interpret_macro_conditions")
    if _contains(lowered, _SELLOFF_WORDS):
        objectives.append("explain_recent_move")
    if not objectives:
        objectives.append("answer_factual_question")
    return tuple(dict.fromkeys(objectives))


def _evidence_requirements(
    intent: QuestionIntent, asset_classes: tuple[AssetClass, ...], lowered: str
) -> tuple[str, ...]:
    reqs: list[str] = []
    if AssetClass.EQUITY_INDEX in asset_classes or intent in (
        QuestionIntent.CURRENT_MARKET,
        QuestionIntent.PREDICTIVE,
    ):
        reqs += ["index_proxy_prices", "momentum", "realized_volatility", "drawdown"]
    if AssetClass.SECTOR in asset_classes:
        reqs.append("sector_relative_performance")
    if AssetClass.EQUITY_SINGLE_NAME in asset_classes:
        reqs.append("company_fundamentals")
    if AssetClass.TREASURY in asset_classes or AssetClass.RATES in asset_classes:
        reqs += ["treasury_yields", "yield_curve"]
    if AssetClass.MACRO in asset_classes:
        reqs += ["inflation", "employment", "monetary_policy"]
    if intent in (QuestionIntent.CURRENT_MARKET, QuestionIntent.ANALYTICAL) and _contains(
        lowered, _SELLOFF_WORDS
    ):
        reqs.append("current_financial_news")
    if intent is QuestionIntent.PREDICTIVE:
        reqs.append("economic_calendar")
    if not reqs:
        reqs.append("primary_source_facts")
    return tuple(dict.fromkeys(reqs))


def _horizon(
    lowered: str, intent: QuestionIntent, is_forward: bool, as_of: date | None
) -> TimeHorizon:
    if _references_past_year(lowered, as_of):
        return TimeHorizon.HISTORICAL
    if "tomorrow" in lowered or "next session" in lowered or "next day" in lowered:
        return TimeHorizon.NEXT_SESSION
    if _contains(lowered, ("today", "right now", "intraday", "currently")):
        return TimeHorizon.INTRADAY
    if _contains(lowered, ("next week", "coming days", "this week")):
        return TimeHorizon.SHORT_TERM
    if _contains(lowered, ("this quarter", "next quarter", "coming months", "next month")):
        return TimeHorizon.MEDIUM_TERM
    if _contains(lowered, ("this year", "long term", "long-term", "next year")):
        return TimeHorizon.LONG_TERM
    if intent is QuestionIntent.HISTORICAL or _contains(
        lowered, ("historically", "in 20", "back in", "during 20", "like 20")
    ):
        return TimeHorizon.HISTORICAL
    if is_forward:
        return TimeHorizon.SHORT_TERM
    return TimeHorizon.UNSPECIFIED


_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _references_past_year(lowered: str, as_of: date | None) -> bool:
    """True when the text names a concrete year strictly before ``as_of``."""
    current_year = as_of.year if as_of is not None else 9999
    return any(int(m) < current_year for m in _YEAR_RE.findall(lowered))


def _is_follow_up(lowered: str, has_prior_context: bool) -> bool:
    if not has_prior_context:
        return False
    # Short questions dominated by a pronoun/determiner referring back.
    words = lowered.split()
    return len(words) <= 12 and _contains(lowered, _FOLLOWUP_WORDS)


def _contains(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(n in haystack for n in needles)
