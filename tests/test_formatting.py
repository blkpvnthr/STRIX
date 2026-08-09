"""Display formatting: internal consistency, negative-zero, range guards."""

from __future__ import annotations

from decimal import Decimal

import pytest

from strix.formatting import (
    display_percent,
    display_percentage_points,
    render_statement,
)
from strix.models import Direction


class TestNegativeZero:
    def test_tiny_negative_ratio_never_displays_minus_zero(self) -> None:
        assert display_percent(Decimal("-0.0004")) == "0.0%"
        assert display_percentage_points(Decimal("-0.04")) == "0.0 percentage points"

    def test_genuine_negatives_keep_their_sign(self) -> None:
        assert display_percent(Decimal("-0.084")) == "-8.4%"
        assert display_percentage_points(Decimal("-1.7")) == "-1.7 percentage points"


class TestStatementConsistency:
    def test_displayed_numbers_always_add_up(self) -> None:
        # Authoritative change is 1.70 pp, but the displayed endpoints round
        # to 8.4% and 10.2%. The sentence must show their exact difference
        # (1.8), never a magnitude that contradicts the visible endpoints.
        statement = render_statement(Direction.INCREASED, Decimal("0.084500"), Decimal("0.101500"))
        assert statement == (
            "Operating margin increased from 8.4% to 10.2%, an improvement "
            "of 1.8 percentage points."
        )

    def test_demo_statement_unchanged(self) -> None:
        statement = render_statement(Direction.INCREASED, Decimal("0.084000"), Decimal("0.101000"))
        assert statement == (
            "Operating margin increased from 8.4% to 10.1%, an improvement "
            "of 1.7 percentage points."
        )

    def test_sub_display_change_reads_effectively_unchanged(self) -> None:
        # A real but tiny increase collapses to 0.0 at display precision;
        # the sentence must not assert an increase "of 0.0 percentage points".
        statement = render_statement(Direction.INCREASED, Decimal("0.083980"), Decimal("0.084280"))
        assert statement == (
            "Operating margin was effectively unchanged at 8.4% "
            "(a change of less than 0.1 percentage points)."
        )

    def test_exactly_unchanged(self) -> None:
        statement = render_statement(Direction.UNCHANGED, Decimal("0.084000"), Decimal("0.084000"))
        assert statement == "Operating margin was unchanged at 8.4%."

    def test_decrease(self) -> None:
        statement = render_statement(Direction.DECREASED, Decimal("0.101000"), Decimal("0.084000"))
        assert statement == (
            "Operating margin decreased from 10.1% to 8.4%, a decline of 1.7 percentage points."
        )


class TestFloatRejection:
    def test_display_functions_require_decimal(self) -> None:
        with pytest.raises((TypeError, AttributeError)):
            display_percent(0.084)  # type: ignore[arg-type]
