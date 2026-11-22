"""Row-level data-quality checks producing machine-readable quarantine reasons.

Rules are financial-aware: OHLC relationships and non-negative volume are enforced
for equity bars, but negative economic rates / accounting values are valid and are
NOT rejected, and missing weekend observations are not treated as defects (that is
a coverage concern handled in reconciliation, not a row rejection).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from strix.lakehouse.silver.models import QuarantineReason
from strix.lakehouse.silver.schemas import DatasetSchema


def check_row(schema: DatasetSchema, row: dict[str, Any]) -> tuple[QuarantineReason, str] | None:
    """Return a (reason, detail) if the row must be quarantined, else None."""
    missing = _missing_required(schema, row)
    if missing:
        return QuarantineReason.MISSING_REQUIRED_FIELD, f"null required field(s): {missing}"

    if schema.name == "alpaca_equity_bars_daily":
        return _check_ohlcv(row)
    if schema.name == "sec_company_facts":
        return _check_period(row)
    return None


def _missing_required(schema: DatasetSchema, row: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in schema.arrow_schema:
        if not field.nullable and row.get(field.name) is None:
            missing.append(field.name)
    return missing


def _check_ohlcv(row: dict[str, Any]) -> tuple[QuarantineReason, str] | None:
    o, h, lo, c = row.get("open"), row.get("high"), row.get("low"), row.get("close")
    if not (
        isinstance(o, Decimal)
        and isinstance(h, Decimal)
        and isinstance(lo, Decimal)
        and isinstance(c, Decimal)
    ):
        return QuarantineReason.SCHEMA_NONCONFORMITY, "non-decimal OHLC value"
    if h < lo:
        return QuarantineReason.INVALID_OHLC, f"high {h} < low {lo}"
    if h < max(o, c) or lo > min(o, c):
        return (
            QuarantineReason.INVALID_OHLC,
            f"high/low do not bracket open/close (o={o},h={h},l={lo},c={c})",
        )
    volume = row.get("volume")
    if not isinstance(volume, int) or volume < 0:
        return QuarantineReason.NEGATIVE_VOLUME, f"volume={volume!r}"
    return None


def _check_period(row: dict[str, Any]) -> tuple[QuarantineReason, str] | None:
    start, end, filed = row.get("period_start"), row.get("period_end"), row.get("filed_date")
    if isinstance(start, date) and isinstance(end, date) and start > end:
        return (
            QuarantineReason.TEMPORAL_INCONSISTENCY,
            f"period_start {start} after period_end {end}",
        )
    if isinstance(end, date) and isinstance(filed, date) and filed < end:
        # Filing before the period even ended is implausible.
        return (
            QuarantineReason.TEMPORAL_INCONSISTENCY,
            f"filed {filed} before period_end {end}",
        )
    return None
