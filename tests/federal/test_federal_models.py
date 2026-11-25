"""Tests for strix.federal.models — federal procurement schemas.

These assert the domain-independence contract: federal money kinds are
semantically distinct, money fields are exact Decimal (never float), and
award obligation/outlay/award_amount are independent fields.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.errors import StrixError
from strix.federal.models import (
    Agency,
    AwardModification,
    Contractor,
    FederalAward,
    FederalError,
    MoneyKind,
    make_award,
)

# --------------------------------------------------------------------------
# Error hierarchy
# --------------------------------------------------------------------------


def test_federal_error_is_strix_error() -> None:
    assert issubclass(FederalError, StrixError)


# --------------------------------------------------------------------------
# MoneyKind — six distinct, non-interchangeable members
# --------------------------------------------------------------------------


def test_money_kind_has_six_distinct_members() -> None:
    values = {kind.value for kind in MoneyKind}
    assert values == {
        "award_amount",
        "obligation",
        "deobligation",
        "outlay",
        "disbursement",
        "modification_amount",
    }
    assert len(list(MoneyKind)) == 6


def test_money_kind_members_are_distinct() -> None:
    members = [
        MoneyKind.AWARD_AMOUNT,
        MoneyKind.OBLIGATION,
        MoneyKind.DEOBLIGATION,
        MoneyKind.OUTLAY,
        MoneyKind.DISBURSEMENT,
        MoneyKind.MODIFICATION_AMOUNT,
    ]
    # No two lifecycle quantities collapse to the same member or value.
    assert len(set(members)) == len(members)
    assert len({m.value for m in members}) == len(members)


# --------------------------------------------------------------------------
# Agency
# --------------------------------------------------------------------------


def test_build_agency() -> None:
    agency = Agency(agency_id="A-1", name="Department of Example", toptier_code="097")
    assert agency.agency_id == "A-1"
    assert agency.name == "Department of Example"
    assert agency.toptier_code == "097"


def test_agency_toptier_code_defaults_empty() -> None:
    agency = Agency(agency_id="A-2", name="Agency Two")
    assert agency.toptier_code == ""


# --------------------------------------------------------------------------
# Contractor
# --------------------------------------------------------------------------


def test_build_contractor() -> None:
    contractor = Contractor(
        contractor_id="C-1",
        name="Acme Corp",
        uei="ABC123DEF456",
        duns="001234567",
        parent_uei="PARENT000001",
    )
    assert contractor.uei == "ABC123DEF456"
    assert contractor.duns == "001234567"
    assert contractor.parent_uei == "PARENT000001"


def test_contractor_optional_fields_default() -> None:
    contractor = Contractor(contractor_id="C-2", name="Beta LLC")
    assert contractor.uei == ""
    assert contractor.duns == ""
    assert contractor.parent_uei is None


# --------------------------------------------------------------------------
# FederalAward — obligation / outlay / award_amount are distinct fields
# --------------------------------------------------------------------------


def test_build_federal_award() -> None:
    award = FederalAward(
        award_id="PIID-0001",
        recipient_uei="ABC123DEF456",
        agency_id="A-1",
        award_amount=Decimal("1000000"),
        obligated_amount=Decimal("250000"),
        outlayed_amount=Decimal("100000"),
        action_date=date(2025, 1, 15),
        period_of_performance_start=date(2025, 2, 1),
        naics="541512",
        description="Software engineering services",
    )
    assert award.award_amount == Decimal("1000000")
    assert award.obligated_amount == Decimal("250000")
    assert award.outlayed_amount == Decimal("100000")
    assert award.naics == "541512"


def test_award_outlayed_amount_defaults_zero() -> None:
    award = FederalAward(
        award_id="PIID-0002",
        recipient_uei="ABC",
        agency_id="A-1",
        award_amount=Decimal("500000"),
        obligated_amount=Decimal("500000"),
        action_date=date(2025, 3, 1),
    )
    assert award.outlayed_amount == Decimal(0)
    assert award.period_of_performance_start is None
    assert award.naics == ""
    assert award.description == ""


def test_award_obligated_outlayed_award_amount_are_separate() -> None:
    """An award can be fully obligated but not yet outlayed."""
    award = FederalAward(
        award_id="PIID-0003",
        recipient_uei="ABC",
        agency_id="A-1",
        award_amount=Decimal("800000"),
        obligated_amount=Decimal("800000"),
        outlayed_amount=Decimal("0"),
        action_date=date(2025, 4, 1),
    )
    assert award.obligated_amount == award.award_amount
    assert award.outlayed_amount == Decimal(0)
    assert award.obligated_amount != award.outlayed_amount


@pytest.mark.parametrize(
    "field",
    ["award_amount", "obligated_amount", "outlayed_amount"],
)
def test_award_money_fields_reject_float(field: str) -> None:
    kwargs = {
        "award_id": "PIID-0004",
        "recipient_uei": "ABC",
        "agency_id": "A-1",
        "award_amount": Decimal("1"),
        "obligated_amount": Decimal("1"),
        "action_date": date(2025, 5, 1),
    }
    kwargs[field] = 1.5
    with pytest.raises(ValidationError):
        FederalAward(**kwargs)


# --------------------------------------------------------------------------
# make_award — deterministic content id
# --------------------------------------------------------------------------


def test_make_award_sets_deterministic_id() -> None:
    kwargs = {
        "award_id": "PIID-9",
        "recipient_uei": "ABC123DEF456",
        "agency_id": "A-1",
        "award_amount": Decimal("1000000"),
        "obligated_amount": Decimal("250000"),
        "outlayed_amount": Decimal("100000"),
        "action_date": date(2025, 1, 15),
        "naics": "541512",
    }
    first = make_award(**kwargs)  # type: ignore[arg-type]
    second = make_award(**kwargs)  # type: ignore[arg-type]
    assert first.award_id == second.award_id
    assert first.award_id.startswith("AWD-")
    assert first == second


def test_make_award_id_changes_with_content() -> None:
    base = {
        "recipient_uei": "ABC",
        "agency_id": "A-1",
        "award_amount": Decimal("1000000"),
        "obligated_amount": Decimal("250000"),
        "action_date": date(2025, 1, 15),
    }
    a = make_award(**base)  # type: ignore[arg-type]
    b = make_award(**{**base, "obligated_amount": Decimal("300000")})  # type: ignore[arg-type]
    assert a.award_id != b.award_id


# --------------------------------------------------------------------------
# AwardModification — signed amount
# --------------------------------------------------------------------------


def test_build_award_modification_positive() -> None:
    mod = AwardModification(
        modification_id="MOD-1",
        award_id="AWD-abc123",
        modification_amount=Decimal("50000"),
        action_date=date(2025, 6, 1),
        reason="obligation increase",
    )
    assert mod.modification_amount == Decimal("50000")
    assert mod.modification_amount > 0


def test_award_modification_negative_is_deobligation() -> None:
    mod = AwardModification(
        modification_id="MOD-2",
        award_id="AWD-abc123",
        modification_amount=Decimal("-25000"),
        action_date=date(2025, 7, 1),
    )
    assert mod.modification_amount == Decimal("-25000")
    assert mod.modification_amount < 0
    assert mod.reason == ""


def test_modification_amount_rejects_float() -> None:
    with pytest.raises(ValidationError):
        AwardModification(
            modification_id="MOD-3",
            award_id="AWD-abc123",
            modification_amount=25000.0,
            action_date=date(2025, 8, 1),
        )


# --------------------------------------------------------------------------
# Frozen / closed schema
# --------------------------------------------------------------------------


def test_federal_award_is_frozen() -> None:
    award = FederalAward(
        award_id="PIID-F",
        recipient_uei="ABC",
        agency_id="A-1",
        award_amount=Decimal("1"),
        obligated_amount=Decimal("1"),
        action_date=date(2025, 1, 1),
    )
    with pytest.raises(ValidationError):
        award.award_amount = Decimal("2")  # type: ignore[misc]


def test_agency_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Agency(agency_id="A-9", name="X", bogus="nope")  # type: ignore[call-arg]
