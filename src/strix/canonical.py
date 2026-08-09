"""Canonical JSON serialization and deterministic hashing.

Every hash and every content-derived identifier in STRIX flows through this
module. The rules are deliberately strict so that identical logical content
always produces identical bytes:

- Object keys are sorted; separators are compact; encoding is UTF-8.
- ``float`` is forbidden everywhere. Monetary and ratio values are
  ``Decimal`` and are encoded as exact plain-decimal JSON strings.
- ``Decimal`` encoding is representation-normalized: trailing zeros are
  stripped, scientific notation is expanded, and all zero values collapse
  to ``"0"``. ``Decimal("84000000.00")`` and ``Decimal("8.4E+7")`` therefore
  hash identically to ``Decimal("84000000")``.
- ``datetime`` values must be timezone-aware and are normalized to UTC
  ISO 8601. ``date`` values use ISO 8601 dates.
- Enums are encoded by value.

Hashes assert content identity and integrity — they do not assert that the
content is factually true.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel

__all__ = [
    "ID_HASH_LENGTH",
    "canonical_bytes",
    "canonical_hash",
    "encode_decimal",
    "make_id",
    "pretty_json_bytes",
    "sha256_hex",
    "to_jsonable",
]

# Length of the hex hash prefix used in content-derived identifiers
# (FACT-, CALC-, EV-, CL-, ART-). 12 hex chars = 48 bits.
ID_HASH_LENGTH = 12


def encode_decimal(value: Decimal) -> str:
    """Encode a Decimal as an exact, representation-normalized plain string.

    Never passes through binary floating point. Raises for non-Decimal and
    non-finite inputs.
    """
    if not isinstance(value, Decimal):
        raise TypeError(f"encode_decimal expects Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError("non-finite Decimal values cannot be canonically encoded")
    if value == 0:
        return "0"
    # format(..., "f") is exact, expands exponents, and ignores decimal context.
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def to_jsonable(obj: Any) -> Any:
    """Recursively convert *obj* into JSON-safe primitives under STRIX rules.

    Emits only ``dict[str, ...] | list | str | int | bool | None``.
    Raises ``TypeError`` for floats, bytes, naive datetimes, non-string
    mapping keys, and any unsupported type.
    """
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, float):
        raise TypeError("float values are forbidden in canonical serialization; use Decimal")
    if isinstance(obj, int):
        return obj
    if isinstance(obj, Decimal):
        return encode_decimal(obj)
    if isinstance(obj, datetime):  # must precede date (datetime subclasses date)
        if obj.tzinfo is None or obj.tzinfo.utcoffset(obj) is None:
            raise ValueError("naive datetimes are forbidden; use timezone-aware UTC datetimes")
        return obj.astimezone(UTC).isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return to_jsonable(obj.value)
    if isinstance(obj, BaseModel):
        # Python-mode dump keeps Decimal as Decimal; json mode would float it.
        return to_jsonable(obj.model_dump())
    if isinstance(obj, Mapping):
        result: dict[str, Any] = {}
        for key, val in obj.items():
            if not isinstance(key, str):
                raise TypeError(f"mapping keys must be str, got {type(key).__name__}")
            result[key] = to_jsonable(val)
        return result
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(item) for item in obj]
    raise TypeError(f"type {type(obj).__name__} is not canonically serializable")


def canonical_bytes(obj: Any) -> bytes:
    """Serialize *obj* to canonical compact JSON bytes (the hashing form)."""
    return json.dumps(
        to_jsonable(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def canonical_hash(obj: Any) -> str:
    """SHA-256 hex digest of the canonical serialization of *obj*."""
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def sha256_hex(data: bytes) -> str:
    """SHA-256 hex digest of raw bytes (used for preserved source artifacts)."""
    return hashlib.sha256(data).hexdigest()


def make_id(prefix: str, payload: Mapping[str, Any]) -> str:
    """Build a stable content-derived identifier: ``PREFIX-<sha256[:12]>``.

    *payload* must contain only reproducible fields — never the object's own
    id, wall-clock timestamps, or absolute filesystem paths.
    """
    return f"{prefix}-{canonical_hash(payload)[:ID_HASH_LENGTH]}"


def pretty_json_bytes(obj: Any) -> bytes:
    """Human-readable JSON bytes for on-disk run artifacts.

    Uses the same value encoding as the canonical form (Decimals as strings,
    UTC ISO datetimes) but with indentation. Hashes are always computed from
    :func:`canonical_bytes`, never from this pretty form.
    """
    return (
        json.dumps(to_jsonable(obj), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
