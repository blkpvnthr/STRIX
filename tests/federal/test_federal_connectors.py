"""Tests for strix.federal.connectors — read-only source adapters.

These assert the connector contract: a :class:`FederalConnector` is
**read-only** (no write/submit/post/delete method), fixture-backed
implementations serve preserved records deterministically, provenance
digests are stable, unknown queries return empty (never crash), and the
module imports no network or credential dependency (no requests/httpx/
socket/urllib/os.environ).
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from strix.federal.connectors import (
    FederalConnector,
    FixtureFederalConnector,
    SourceRecord,
    make_source_record,
)
from strix.federal.models import AwardModification, FederalAward

# --------------------------------------------------------------------------
# Fixtures (module-level deterministic test data; not pytest fixtures)
# --------------------------------------------------------------------------


def _award(award_id: str, recipient_uei: str, agency_id: str) -> FederalAward:
    return FederalAward(
        award_id=award_id,
        recipient_uei=recipient_uei,
        agency_id=agency_id,
        award_amount=Decimal("1000000"),
        obligated_amount=Decimal("250000"),
        outlayed_amount=Decimal("100000"),
        action_date=date(2025, 1, 15),
        naics="541512",
    )


def _mod(modification_id: str, award_id: str, amount: str) -> AwardModification:
    return AwardModification(
        modification_id=modification_id,
        award_id=award_id,
        modification_amount=Decimal(amount),
        action_date=date(2025, 6, 1),
    )


AWARD_A = _award("PIID-A", "UEI-AAA", "AGN-1")
AWARD_B = _award("PIID-B", "UEI-BBB", "AGN-1")
AWARD_C = _award("PIID-C", "UEI-AAA", "AGN-2")

MOD_A1 = _mod("MOD-A1", "PIID-A", "50000")
MOD_A2 = _mod("MOD-A2", "PIID-A", "-25000")
MOD_B1 = _mod("MOD-B1", "PIID-B", "10000")


def _connector() -> FixtureFederalConnector:
    return FixtureFederalConnector(
        source_name="usaspending",
        awards=(AWARD_A, AWARD_B, AWARD_C),
        modifications=(MOD_A1, MOD_A2, MOD_B1),
    )


# --------------------------------------------------------------------------
# Protocol conformance
# --------------------------------------------------------------------------


def test_fixture_connector_is_federal_connector() -> None:
    conn = _connector()
    assert isinstance(conn, FederalConnector)


def test_connector_exposes_source_name() -> None:
    assert _connector().source_name == "usaspending"


# --------------------------------------------------------------------------
# Read-only contract — no write/submit/mutation surface
# --------------------------------------------------------------------------


def test_connector_has_no_write_methods() -> None:
    forbidden = (
        "write",
        "submit",
        "post",
        "put",
        "delete",
        "create",
        "insert",
        "upsert",
        "update",
        "save",
        "push",
        "send",
    )
    for name in dir(_connector()):
        if name.startswith("_"):
            continue
        lowered = name.lower()
        assert not any(token in lowered for token in forbidden), name


def test_protocol_declares_no_write_methods() -> None:
    members = {name for name in dir(FederalConnector) if not name.startswith("_")}
    # The read-only surface is exactly these two fetchers (plus source_name).
    assert "fetch_awards" in members
    assert "fetch_modifications" in members
    forbidden = ("write", "submit", "post", "delete", "update", "create", "save")
    for name in members:
        assert not any(token in name.lower() for token in forbidden), name


# --------------------------------------------------------------------------
# Deterministic fixture serving
# --------------------------------------------------------------------------


def test_fetch_awards_returns_all_for_empty_query() -> None:
    conn = _connector()
    result = conn.fetch_awards({})
    assert result == (AWARD_A, AWARD_B, AWARD_C)
    assert isinstance(result, tuple)


def test_fetch_awards_is_deterministic() -> None:
    conn = _connector()
    assert conn.fetch_awards({}) == conn.fetch_awards({})


def test_fetch_awards_filters_by_recipient_uei() -> None:
    conn = _connector()
    result = conn.fetch_awards({"recipient_uei": "UEI-AAA"})
    assert result == (AWARD_A, AWARD_C)


def test_fetch_awards_filters_by_multiple_fields() -> None:
    conn = _connector()
    result = conn.fetch_awards({"recipient_uei": "UEI-AAA", "agency_id": "AGN-1"})
    assert result == (AWARD_A,)


def test_fetch_awards_unknown_query_returns_empty_not_crash() -> None:
    conn = _connector()
    # Unknown key is not a FederalAward field: no match, empty tuple, no error.
    assert conn.fetch_awards({"nonexistent_field": "whatever"}) == ()


def test_fetch_awards_no_match_returns_empty() -> None:
    conn = _connector()
    assert conn.fetch_awards({"recipient_uei": "UEI-ZZZ"}) == ()


def test_fetch_modifications_returns_matching() -> None:
    conn = _connector()
    assert conn.fetch_modifications("PIID-A") == (MOD_A1, MOD_A2)
    assert conn.fetch_modifications("PIID-B") == (MOD_B1,)


def test_fetch_modifications_unknown_award_returns_empty() -> None:
    conn = _connector()
    assert conn.fetch_modifications("PIID-UNKNOWN") == ()


def test_fetch_modifications_is_deterministic() -> None:
    conn = _connector()
    assert conn.fetch_modifications("PIID-A") == conn.fetch_modifications("PIID-A")


# --------------------------------------------------------------------------
# SourceRecord provenance
# --------------------------------------------------------------------------


def test_source_record_fields() -> None:
    now = datetime(2025, 11, 24, 12, 0, tzinfo=UTC)
    record = make_source_record("usaspending", (AWARD_A, AWARD_B), now)
    assert isinstance(record, SourceRecord)
    assert record.source_name == "usaspending"
    assert record.record_count == 2
    assert record.retrieved_at == now
    assert len(record.source_digest) == 64


def test_source_record_digest_is_deterministic() -> None:
    t1 = datetime(2025, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 6, 6, tzinfo=UTC)
    first = make_source_record("usaspending", (AWARD_A, AWARD_B), t1)
    # Digest depends only on the payload, not the wall-clock retrieval time.
    second = make_source_record("usaspending", (AWARD_A, AWARD_B), t2)
    assert first.source_digest == second.source_digest


def test_source_record_digest_changes_with_payload() -> None:
    now = datetime(2025, 11, 24, tzinfo=UTC)
    a = make_source_record("usaspending", (AWARD_A, AWARD_B), now)
    b = make_source_record("usaspending", (AWARD_A, AWARD_C), now)
    assert a.source_digest != b.source_digest


def test_source_record_digest_works_for_modifications() -> None:
    now = datetime(2025, 11, 24, tzinfo=UTC)
    record = make_source_record("usaspending", (MOD_A1, MOD_A2), now)
    assert record.record_count == 2
    assert len(record.source_digest) == 64


def test_connector_source_record_matches_fetch() -> None:
    conn = _connector()
    now = datetime(2025, 11, 24, tzinfo=UTC)
    fetched = conn.fetch_awards({})
    record = conn.source_record(fetched, now)
    assert record.source_name == "usaspending"
    assert record.record_count == len(fetched)
    assert record.source_digest == make_source_record("usaspending", fetched, now).source_digest


def test_source_record_is_frozen() -> None:
    now = datetime(2025, 11, 24, tzinfo=UTC)
    record = make_source_record("usaspending", (AWARD_A,), now)
    with pytest.raises(ValidationError):
        record.record_count = 99  # type: ignore[misc]


# --------------------------------------------------------------------------
# No network / credential dependency
# --------------------------------------------------------------------------


def test_module_imports_no_network_or_credential_libraries() -> None:
    # Parse the module's actual import statements (prose in the docstring that
    # names these libraries to document what is NOT used does not count).
    import strix.federal.connectors as connectors_module

    source = Path(inspect.getfile(connectors_module)).read_text()
    tree = ast.parse(source)
    banned = {"requests", "httpx", "socket", "urllib", "http", "os", "urllib3"}
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    assert banned.isdisjoint(imported_roots), imported_roots & banned
