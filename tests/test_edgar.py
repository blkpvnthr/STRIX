"""SEC EDGAR connector: deterministic parsing of preserved companyfacts.

All tests run offline against a committed schema sample (synthetic figures);
the suite-wide socket guard proves no network is touched.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from strix import PIPELINE_VERSION
from strix.errors import SourceError
from strix.models import Concept, ResearchSpec, SourceType, VerificationStatus
from strix.pipeline import compute, run_research
from strix.reasoning.deterministic_demo import DeterministicDemoReasoner
from strix.replay import replay_run
from strix.sources import edgar
from strix.sources.base import FetchedSource
from strix.sources.edgar import EdgarConnector, parse_companyfacts, resolve_cik
from tests.conftest import FIXED_NOW, FixedClock

DATA_DIR = Path(__file__).parent / "data"
AS_OF = date(2026, 8, 8)


@pytest.fixture
def companyfacts_raw() -> bytes:
    return (DATA_DIR / "edgar-companyfacts-sample.json").read_bytes()


@pytest.fixture
def ticker_map_raw() -> bytes:
    return (DATA_DIR / "edgar-company-tickers-sample.json").read_bytes()


class TestParseCompanyfacts:
    def test_selects_year_over_year_quarters(self, companyfacts_raw: bytes) -> None:
        document = parse_companyfacts(companyfacts_raw, ticker="XMPL", as_of_date=AS_OF)
        assert document.periods == ("2025-Q2", "2026-Q2")
        assert document.company_id == "CIK0001234567"
        assert document.company_name == "Example Filer Inc."
        assert document.synthetic is False
        assert len(document.facts) == 4

    def test_values_are_decimal_never_float(self, companyfacts_raw: bytes) -> None:
        # The sample deliberately contains a JSON float (EPS 1.23); parsing
        # must route all decimals through Decimal, never binary float.
        document = parse_companyfacts(companyfacts_raw, ticker="XMPL", as_of_date=AS_OF)
        for fact in document.facts:
            assert isinstance(fact.value, Decimal)
            assert not isinstance(fact.value, float)

    def test_known_at_is_the_filing_date(self, companyfacts_raw: bytes) -> None:
        document = parse_companyfacts(companyfacts_raw, ticker="XMPL", as_of_date=AS_OF)
        known = {(fact.concept, fact.observation_period): fact.known_at for fact in document.facts}
        utc = UTC
        assert known[(Concept.REVENUE, "2025-Q2")] == datetime(2025, 8, 1, tzinfo=utc)
        assert known[(Concept.REVENUE, "2026-Q2")] == datetime(2026, 7, 31, tzinfo=utc)
        assert known[(Concept.OPERATING_INCOME, "2026-Q2")] == datetime(2026, 7, 31, tzinfo=utc)

    def test_earliest_filed_value_wins_over_restatement(self, companyfacts_raw: bytes) -> None:
        # 2026-Q2 revenue appears twice (original 10-Q and a later 10-Q/A);
        # the first-known value must be selected deterministically.
        document = parse_companyfacts(companyfacts_raw, ticker="XMPL", as_of_date=AS_OF)
        revenue = {
            fact.observation_period: fact
            for fact in document.facts
            if fact.concept is Concept.REVENUE
        }
        assert revenue["2026-Q2"].value == Decimal("100000000000")
        assert revenue["2026-Q2"].locator.endswith("/USD/3")

    def test_annual_and_ytd_durations_excluded(self, companyfacts_raw: bytes) -> None:
        document = parse_companyfacts(companyfacts_raw, ticker="XMPL", as_of_date=AS_OF)
        revenue_locators = {
            fact.locator for fact in document.facts if fact.concept is Concept.REVENUE
        }
        # Revenue indexes: 1 is the six-month YTD value, 2 the annual 10-K
        # value; only the true quarterly values (0 and 3) may be selected.
        assert revenue_locators == {
            "/facts/us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax/units/USD/0",
            "/facts/us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax/units/USD/3",
        }

    def test_facts_filed_after_as_of_are_not_knowable(self, companyfacts_raw: bytes) -> None:
        # As of 2026-06-30 the 2026-Q2 filings (filed 2026-07-31) do not
        # exist yet, and 2025-Q2 has no 2024-Q2 partner in the sample.
        with pytest.raises(SourceError, match="comparable quarters"):
            parse_companyfacts(companyfacts_raw, ticker="XMPL", as_of_date=date(2026, 6, 30))

    def test_missing_operating_income_rejected(self, companyfacts_raw: bytes) -> None:
        payload = json.loads(companyfacts_raw)
        del payload["facts"]["us-gaap"]["OperatingIncomeLoss"]
        with pytest.raises(SourceError, match="OperatingIncomeLoss"):
            parse_companyfacts(json.dumps(payload).encode(), ticker="XMPL", as_of_date=AS_OF)

    def test_unreadable_payload_rejected(self) -> None:
        with pytest.raises(SourceError, match="unreadable"):
            parse_companyfacts(b"not json", ticker="XMPL", as_of_date=AS_OF)


def _facts_payload(revenue_units: list, operating_units: list) -> bytes:
    return json.dumps(
        {
            "cik": 1234567,
            "entityName": "Example Filer Inc.",
            "facts": {
                "us-gaap": {
                    "Revenues": {"units": {"USD": revenue_units}},
                    "OperatingIncomeLoss": {"units": {"USD": operating_units}},
                }
            },
        }
    ).encode()


def _fact(start: str, end: str, val: int, filed: str) -> dict:
    return {"start": start, "end": end, "val": val, "filed": filed}


class TestQuarterSelectionEdgeCases:
    def test_same_day_restatement_tie_breaks_by_numeric_index(self) -> None:
        # Two facts for the same quarter filed on the SAME day at indices 2
        # and 10: the numerically-first entry (index 2) must win. A lexical
        # locator comparison would wrongly prefer '/USD/10'.
        revenue_units = [
            _fact("2015-01-01", "2015-03-31", 1, "2015-05-01"),  # index 0
            _fact("2015-04-01", "2015-06-30", 1, "2015-08-01"),  # index 1
            _fact("2026-04-01", "2026-06-30", 2222, "2026-07-31"),  # index 2
            _fact("2016-01-01", "2016-03-31", 1, "2016-05-01"),
            _fact("2016-04-01", "2016-06-30", 1, "2016-08-01"),
            _fact("2017-01-01", "2017-03-31", 1, "2017-05-01"),
            _fact("2017-04-01", "2017-06-30", 1, "2017-08-01"),
            _fact("2018-01-01", "2018-03-31", 1, "2018-05-01"),
            _fact("2018-04-01", "2018-06-30", 1, "2018-08-01"),
            _fact("2025-04-01", "2025-06-30", 2000, "2025-08-01"),  # index 9
            _fact("2026-04-01", "2026-06-30", 1010, "2026-07-31"),  # index 10
        ]
        raw = _facts_payload(
            revenue_units,
            [
                _fact("2025-04-01", "2025-06-30", 500, "2025-08-01"),
                _fact("2026-04-01", "2026-06-30", 600, "2026-07-31"),
            ],
        )
        document = parse_companyfacts(raw, ticker="XMPL", as_of_date=AS_OF)
        revenue = {
            fact.observation_period: fact
            for fact in document.facts
            if fact.concept is Concept.REVENUE
        }
        assert revenue["2026-Q2"].value == Decimal("2222")
        assert revenue["2026-Q2"].locator.endswith("/USD/2")

    def test_off_calendar_fiscal_year_pairs_by_date_distance(self) -> None:
        # A 4-4-5 filer whose quarter ends 2026-01-02 (calendar label
        # 2026-Q1) must pair with the quarter ending 2024-12-28 (calendar
        # label 2024-Q4, 370 days earlier). Label-based YoY matching would
        # look for a nonexistent "2025-Q1" and fail.
        raw = _facts_payload(
            [
                _fact("2024-09-29", "2024-12-28", 900, "2025-01-30"),
                _fact("2025-10-05", "2026-01-02", 1000, "2026-02-01"),
            ],
            [
                _fact("2024-09-29", "2024-12-28", 90, "2025-01-30"),
                _fact("2025-10-05", "2026-01-02", 130, "2026-02-01"),
            ],
        )
        document = parse_companyfacts(raw, ticker="XMPL", as_of_date=AS_OF)
        assert document.periods == ("2024-Q4", "2026-Q1")
        margins = {
            fact.observation_period: fact.value
            for fact in document.facts
            if fact.concept is Concept.OPERATING_INCOME
        }
        assert margins == {"2024-Q4": Decimal("90"), "2026-Q1": Decimal("130")}

    def test_filed_through_is_true_maximum_across_all_chosen_facts(self) -> None:
        # The latest filing date lives on the PREVIOUS period's operating
        # income (a late catch-up filing). A lexicographic tuple max would
        # report 2026-08-02 instead.
        raw = _facts_payload(
            [
                _fact("2025-04-01", "2025-06-30", 900, "2025-08-01"),
                _fact("2026-04-01", "2026-06-30", 1000, "2026-08-01"),
            ],
            [
                _fact("2025-04-01", "2025-06-30", 90, "2026-08-15"),
                _fact("2026-04-01", "2026-06-30", 130, "2026-08-02"),
            ],
        )
        document = parse_companyfacts(raw, ticker="XMPL", as_of_date=date(2026, 8, 20))
        assert document.source_version.endswith("filed-through-2026-08-15")
        assert document.created_at == datetime(2026, 8, 15, tzinfo=UTC)


class TestTickerResolution:
    def test_resolves_known_ticker(self, ticker_map_raw: bytes) -> None:
        assert resolve_cik("XMPL", ticker_map_raw) == 1234567
        assert resolve_cik("xmpl", ticker_map_raw) == 1234567

    def test_dot_class_share_alias(self, ticker_map_raw: bytes) -> None:
        assert resolve_cik("BRK.B", ticker_map_raw) == 200001

    def test_unknown_ticker_rejected(self, ticker_map_raw: bytes) -> None:
        with pytest.raises(SourceError, match="not found"):
            resolve_cik("NOPE", ticker_map_raw)

    def test_non_object_ticker_map_rejected_cleanly(self) -> None:
        with pytest.raises(SourceError, match="unexpected shape"):
            resolve_cik("XMPL", b"[]")

    def test_invalid_cik_entry_rejected_cleanly(self) -> None:
        payload = json.dumps({"0": {"cik_str": "not-a-number-!", "ticker": "XMPL"}})
        with pytest.raises(SourceError, match="invalid CIK"):
            resolve_cik("XMPL", payload.encode())


class TestConnector:
    def test_fetch_uses_canned_transport(
        self,
        monkeypatch: pytest.MonkeyPatch,
        companyfacts_raw: bytes,
        ticker_map_raw: bytes,
    ) -> None:
        def fake_fetch(url: str, *, user_agent: str = edgar.USER_AGENT) -> bytes:
            assert "STRIX" in user_agent
            if url == edgar.TICKER_MAP_URL:
                return ticker_map_raw
            assert url == edgar.COMPANYFACTS_URL.format(cik=1234567)
            return companyfacts_raw

        monkeypatch.setattr(edgar, "fetch_url", fake_fetch)
        fetched = EdgarConnector().fetch("XMPL")
        assert fetched.source_type is SourceType.SEC_EDGAR_COMPANYFACTS
        assert fetched.source_name == "companyfacts-CIK0001234567.json"
        assert fetched.raw == companyfacts_raw


class TestEdgarPipelineEndToEnd:
    def _spec(self, companyfacts_raw: bytes) -> ResearchSpec:
        document = parse_companyfacts(companyfacts_raw, ticker="XMPL", as_of_date=AS_OF)
        return ResearchSpec(
            company_id=document.company_id,
            ticker=document.ticker,
            company_name=document.company_name,
            question="Is operating profitability improving?",
            as_of_date=AS_OF,
            historical_periods=document.periods,
            pipeline_version=PIPELINE_VERSION,
        )

    def test_real_schema_data_produces_verified_claim(self, companyfacts_raw: bytes) -> None:
        spec = self._spec(companyfacts_raw)
        outcome = compute(
            spec,
            companyfacts_raw,
            source_type=SourceType.SEC_EDGAR_COMPANYFACTS,
            source_name="companyfacts-CIK0001234567.json",
            reasoner=DeterministicDemoReasoner(),
            checked_at=FIXED_NOW,
        )
        assert outcome.verification.status is VerificationStatus.PASSED
        # 27/90 = 30.0%, 31/100 = 31.0%: +1.0 percentage point.
        assert outcome.claims[0].statement == (
            "Operating margin increased from 30.0% to 31.0%, an improvement "
            "of 1.0 percentage points."
        )

    def test_edgar_run_persists_and_replays_offline(
        self, companyfacts_raw: bytes, state_dir: Path, clock: FixedClock
    ) -> None:
        spec = self._spec(companyfacts_raw)
        fetched = FetchedSource(
            raw=companyfacts_raw,
            source_type=SourceType.SEC_EDGAR_COMPANYFACTS,
            source_name="companyfacts-CIK0001234567.json",
            description=edgar.EDGAR_DESCRIPTION,
            disclaimer=edgar.EDGAR_DISCLAIMER,
        )
        result = run_research(spec, state_dir=state_dir, fetched=fetched, clock=clock)
        assert result.verification.status is VerificationStatus.PASSED
        preserved = result.run_directory / "raw" / fetched.source_name
        assert preserved.read_bytes() == companyfacts_raw
        # Replay recomputes from preserved bytes with no network available.
        outcome = replay_run(result.manifest.run_id, state_dir)
        assert outcome.passed
