"""SEC EDGAR company-facts connector (real filing data, no credentials).

Acquisition uses two public SEC endpoints (no API key; the SEC fair-access
policy requires a descriptive User-Agent):

- ``https://www.sec.gov/files/company_tickers.json`` — ticker -> CIK.
- ``https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`` — all
  XBRL facts a company has filed.

The network is touched only inside :class:`EdgarConnector.fetch`. Parsing
(:func:`parse_companyfacts`) is a pure function of the preserved bytes plus
the research parameters, so replay reproduces it offline and byte-identically.

Point-in-time semantics: each fact's ``known_at`` is its SEC ``filed`` date,
and only facts filed on or before the research as-of date are considered.
Quarterly values are duration facts spanning roughly one quarter (80-100
days). Quarters are identified by their exact period END date; the
comparison pair is the latest available quarter and the quarter ending
350-378 days earlier (closest to 364), which pairs off-calendar and
52/53-week fiscal years correctly. The ``YYYY-QN`` label shown to users is
derived from the end date's calendar quarter and is display naming only.
When several filings restate the same quarter, the earliest-filed value
wins — the value the market learned first.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from strix.errors import SourceError
from strix.models import Concept, SourceType, Unit
from strix.sources.base import FetchedSource, NormalizedFact, SourceDocument

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

#: SEC fair-access policy requires a User-Agent identifying the requester.
USER_AGENT = "STRIX/0.1 research prototype (contact@quantumquant.trade)"

_TIMEOUT_SECONDS = 30

#: us-gaap revenue tags, in priority order.
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
)
OPERATING_INCOME_TAG = "OperatingIncomeLoss"

#: Duration bounds (days) for a value to count as one fiscal quarter.
_QUARTER_MIN_DAYS = 80
_QUARTER_MAX_DAYS = 100

EDGAR_DESCRIPTION = "SEC EDGAR company facts (live fetch, preserved per run)"
EDGAR_DISCLAIMER = (
    "Source: SEC EDGAR company facts, as filed. Research prototype output — not investment advice."
)


def fetch_url(url: str, *, user_agent: str = USER_AGENT) -> bytes:
    """GET one SEC endpoint with the fair-access User-Agent header."""
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return bytes(response.read())
    except urllib.error.HTTPError as exc:
        raise SourceError(f"SEC EDGAR returned HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceError(f"could not reach SEC EDGAR ({url}): {exc}") from exc


def resolve_cik(ticker: str, ticker_map_raw: bytes) -> int:
    """Resolve a ticker symbol to a CIK using the SEC ticker map."""
    try:
        payload = json.loads(ticker_map_raw.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError(f"SEC ticker map is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise SourceError("SEC ticker map has an unexpected shape (not a JSON object)")
    wanted = ticker.upper()
    # EDGAR lists class shares with dashes (BRK-B); accept dot input too.
    aliases = {wanted, wanted.replace(".", "-")}
    for entry in payload.values():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("ticker", "")).upper() in aliases:
            try:
                return int(entry["cik_str"])
            except (KeyError, TypeError, ValueError) as exc:
                raise SourceError(
                    f"SEC ticker map entry for {ticker!r} has an invalid CIK"
                ) from exc
    raise SourceError(f"ticker {ticker!r} was not found in the SEC EDGAR ticker map")


class EdgarConnector:
    """Fetches SEC EDGAR company facts for real tickers."""

    def __init__(self, *, user_agent: str = USER_AGENT) -> None:
        self._user_agent = user_agent

    def fetch(self, ticker: str) -> FetchedSource:
        ticker_map = fetch_url(TICKER_MAP_URL, user_agent=self._user_agent)
        cik = resolve_cik(ticker, ticker_map)
        raw = fetch_url(COMPANYFACTS_URL.format(cik=cik), user_agent=self._user_agent)
        return FetchedSource(
            raw=raw,
            source_type=SourceType.SEC_EDGAR_COMPANYFACTS,
            source_name=f"companyfacts-CIK{cik:010d}.json",
            description=EDGAR_DESCRIPTION,
            disclaimer=EDGAR_DISCLAIMER,
        )


# --------------------------------------------------------------------------
# Deterministic parsing of preserved companyfacts bytes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _QuarterFact:
    value: Decimal
    filed: date
    start: date
    end: date
    #: Position in the source units array (numeric tie-break, locator basis).
    index: int
    locator: str


#: Year-over-year pairing window: the comparable quarter's end date must lie
#: this many days before the current quarter's end (364 = exactly 52 weeks;
#: the window absorbs 52/53-week fiscal calendars and month-end drift).
_YOY_MIN_DAYS = 350
_YOY_MAX_DAYS = 378
_YOY_TARGET_DAYS = 364


def parse_companyfacts(raw: bytes, *, ticker: str, as_of_date: date) -> SourceDocument:
    """Build a normalized document from preserved companyfacts bytes.

    Pure function of ``(raw, ticker, as_of_date)``; floats never enter —
    JSON decimals parse straight to ``Decimal``. Quarters are identified by
    their exact period END date and paired year-over-year by date distance
    (350-378 days), so off-calendar fiscal years pair correctly; the
    ``YYYY-QN`` label derived from the end date is display naming only.
    """
    try:
        payload: Any = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError(f"SEC companyfacts response is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise SourceError("SEC companyfacts response is not a JSON object")

    entity_name = str(payload.get("entityName") or "").strip()
    cik = payload.get("cik")
    if not entity_name or not isinstance(cik, int):
        raise SourceError("SEC companyfacts response lacks entityName or cik")
    us_gaap = (payload.get("facts") or {}).get("us-gaap")
    if not isinstance(us_gaap, dict):
        raise SourceError(f"{entity_name} has no us-gaap facts in EDGAR")

    operating = _quarterly_facts(us_gaap, OPERATING_INCOME_TAG, as_of_date)
    if not operating:
        raise SourceError(
            f"{entity_name} reports no quarterly {OPERATING_INCOME_TAG} facts "
            f"on or before {as_of_date.isoformat()}"
        )

    for tag in REVENUE_TAGS:
        revenue = _quarterly_facts(us_gaap, tag, as_of_date)
        pair = _select_yoy_pair(set(revenue) & set(operating))
        if pair is not None:
            return _build_document(
                entity_name=entity_name,
                cik=cik,
                ticker=ticker.upper(),
                revenue_tag=tag,
                revenue=revenue,
                operating=operating,
                period_ends=pair,
            )
    raise SourceError(
        f"could not find two year-over-year comparable quarters with both "
        f"revenue and operating income for {entity_name} as of "
        f"{as_of_date.isoformat()}"
    )


def _quarterly_facts(
    us_gaap: dict[str, Any], tag: str, as_of_date: date
) -> dict[date, _QuarterFact]:
    """Collect one-quarter USD duration facts filed by the as-of date.

    Returns period end date -> the earliest-filed fact for that quarter
    (the first-known value; restatements filed later never replace it).
    Keying by exact end date keeps distinct fiscal quarters distinct even
    when they would share a calendar-quarter label.
    """
    units = ((us_gaap.get(tag) or {}).get("units") or {}).get("USD")
    if not isinstance(units, list):
        return {}
    best: dict[date, _QuarterFact] = {}
    for index, item in enumerate(units):
        if not isinstance(item, dict):
            continue
        try:
            start = date.fromisoformat(str(item["start"]))
            end = date.fromisoformat(str(item["end"]))
            filed = date.fromisoformat(str(item["filed"]))
            value = item["val"]
        except (KeyError, ValueError, TypeError):
            continue
        if not isinstance(value, int | Decimal) or isinstance(value, bool):
            continue
        if filed > as_of_date:
            continue
        if not (_QUARTER_MIN_DAYS <= (end - start).days <= _QUARTER_MAX_DAYS):
            continue
        candidate = _QuarterFact(
            value=Decimal(value),
            filed=filed,
            start=start,
            end=end,
            index=index,
            locator=f"/facts/us-gaap/{tag}/units/USD/{index}",
        )
        existing = best.get(end)
        # Earliest filed wins (first-known value); the numeric array index
        # breaks exact same-day ties in favor of the earlier entry.
        if existing is None or (candidate.filed, candidate.index) < (
            existing.filed,
            existing.index,
        ):
            best[end] = candidate
    return best


def _select_yoy_pair(common_ends: set[date]) -> tuple[date, date] | None:
    """Pick (previous_end, current_end): the latest quarter with a partner
    ending 350-378 days earlier, preferring the partner closest to 364 days.
    """
    for current_end in sorted(common_ends, reverse=True):
        candidates = [
            end for end in common_ends if _YOY_MIN_DAYS <= (current_end - end).days <= _YOY_MAX_DAYS
        ]
        if candidates:
            previous_end = min(
                candidates,
                key=lambda end: (abs((current_end - end).days - _YOY_TARGET_DAYS), end),
            )
            return previous_end, current_end
    return None


def _period_label(end: date) -> str:
    """Display label from the calendar quarter of the period end date."""
    return f"{end.year}-Q{(end.month - 1) // 3 + 1}"


def _build_document(
    *,
    entity_name: str,
    cik: int,
    ticker: str,
    revenue_tag: str,
    revenue: dict[date, _QuarterFact],
    operating: dict[date, _QuarterFact],
    period_ends: tuple[date, date],
) -> SourceDocument:
    labels = (_period_label(period_ends[0]), _period_label(period_ends[1]))
    if labels[0] == labels[1]:  # defensive: ends are >= 350 days apart
        raise SourceError(
            f"could not derive distinct period labels for quarters ending "
            f"{period_ends[0].isoformat()} and {period_ends[1].isoformat()}"
        )
    facts: list[NormalizedFact] = []
    chosen_facts: list[_QuarterFact] = []
    for end, label in zip(period_ends, labels, strict=True):
        for concept, chosen in (
            (Concept.REVENUE, revenue[end]),
            (Concept.OPERATING_INCOME, operating[end]),
        ):
            chosen_facts.append(chosen)
            facts.append(
                NormalizedFact(
                    concept=concept,
                    value=chosen.value,
                    unit=Unit.USD,
                    observation_period=label,
                    known_at=_utc(chosen.filed),
                    locator=chosen.locator,
                )
            )
    created_at = max(fact.known_at for fact in facts)
    filed_through = max(chosen.filed for chosen in chosen_facts)
    return SourceDocument(
        company_id=f"CIK{cik:010d}",
        ticker=ticker,
        company_name=entity_name,
        source_type=SourceType.SEC_EDGAR_COMPANYFACTS,
        source_version=f"{revenue_tag}@filed-through-{filed_through.isoformat()}",
        synthetic=False,
        created_at=created_at,
        periods=labels,
        facts=tuple(facts),
    )


def _utc(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)
