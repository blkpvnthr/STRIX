"""Canonical serialization: stability, Decimal encoding, float rejection."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from strix.canonical import (
    canonical_bytes,
    canonical_hash,
    encode_decimal,
    make_id,
    sha256_hex,
    to_jsonable,
)


class TestEncodeDecimal:
    def test_integer_forms_are_equivalent(self) -> None:
        assert encode_decimal(Decimal("84000000")) == "84000000"
        assert encode_decimal(Decimal("84000000.00")) == "84000000"
        assert encode_decimal(Decimal("8.4E+7")) == "84000000"

    def test_fraction_forms_are_equivalent(self) -> None:
        assert encode_decimal(Decimal("0.084")) == "0.084"
        assert encode_decimal(Decimal("0.0840")) == "0.084"
        assert encode_decimal(Decimal("0.084000")) == "0.084"

    def test_zero_collapses(self) -> None:
        for text in ("0", "0.00", "-0", "-0.000", "0E+2"):
            assert encode_decimal(Decimal(text)) == "0"

    def test_negative_values(self) -> None:
        assert encode_decimal(Decimal("-1.70")) == "-1.7"

    def test_no_scientific_notation(self) -> None:
        assert encode_decimal(Decimal("1E-6")) == "0.000001"

    def test_rejects_float(self) -> None:
        with pytest.raises(TypeError):
            encode_decimal(0.084)  # type: ignore[arg-type]

    def test_rejects_non_finite(self) -> None:
        with pytest.raises(ValueError):
            encode_decimal(Decimal("NaN"))
        with pytest.raises(ValueError):
            encode_decimal(Decimal("Infinity"))


class TestCanonicalJson:
    def test_key_order_does_not_change_bytes(self) -> None:
        first = {"b": 1, "a": {"d": 2, "c": 3}}
        second = {"a": {"c": 3, "d": 2}, "b": 1}
        assert canonical_bytes(first) == canonical_bytes(second)
        assert canonical_hash(first) == canonical_hash(second)

    def test_decimal_never_passes_through_float(self) -> None:
        # A float that "looks like" the Decimal must produce a TypeError,
        # never silently the same bytes.
        assert canonical_bytes({"v": Decimal("0.1")}) == b'{"v":"0.1"}'
        with pytest.raises(TypeError):
            canonical_bytes({"v": 0.1})

    def test_datetime_normalized_to_utc(self) -> None:
        from datetime import timedelta
        from datetime import timezone as tz

        eastern = tz(timedelta(hours=-5))
        aware = datetime(2026, 7, 15, 5, 0, tzinfo=eastern)
        utc = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
        assert canonical_bytes(aware) == canonical_bytes(utc)

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValueError):
            canonical_bytes(datetime(2026, 7, 15))

    def test_date_iso(self) -> None:
        assert canonical_bytes(date(2026, 8, 8)) == b'"2026-08-08"'

    def test_non_string_keys_rejected(self) -> None:
        with pytest.raises(TypeError):
            canonical_bytes({1: "a"})

    def test_unsupported_type_rejected(self) -> None:
        with pytest.raises(TypeError):
            canonical_bytes({"x": object()})

    def test_bytes_rejected(self) -> None:
        with pytest.raises(TypeError):
            to_jsonable(b"raw")


class TestHashesAndIds:
    def test_sha256_hex_known_vector(self) -> None:
        assert sha256_hex(b"") == hashlib.sha256(b"").hexdigest()
        assert (
            sha256_hex(b"strix")
            == "18c293d7235eede439844cbe72679e537c0bdf59fea84aaaa9e19cfe18281a2f"
        )

    def test_make_id_shape_and_stability(self) -> None:
        payload = {"a": Decimal("1.0"), "b": "x"}
        first = make_id("EV", payload)
        second = make_id("EV", {"b": "x", "a": Decimal("1")})
        assert first == second
        prefix, digest = first.split("-", 1)
        assert prefix == "EV"
        assert len(digest) == 12
        assert set(digest) <= set("0123456789abcdef")
