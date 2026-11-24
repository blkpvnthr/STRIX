"""Data-integrity screening over heterogeneous observations (R1 §12, GAP-003).

Generalizes the C-engine integrity patterns into deterministic, exact-Decimal
checks over a sequence of observations. Each check accepts either a typed
:class:`strix.evidence_graph.nodes.SourceObservation` or a simple mapping with
the keys ``subject``/``concept``/``unit``/``period``/``value``/``timestamp``,
and returns a frozen finding model carrying a ``classification`` and the
offending items (by index) — never a bare boolean.

A finding is **evidence** for the verifier (R1 §12.4); it never admits or
rejects a claim. ``float`` is forbidden on every value, and every timestamp
must be timezone-aware.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from typing import NamedTuple

from strix.canonical import encode_decimal
from strix.errors import StrixError
from strix.evidence_graph.nodes import SourceObservation
from strix.models import DecimalValue, StrixModel
from strix.native.arithmetic import as_decimal, checked_div

__all__ = [
    "CoverageFinding",
    "DuplicateFinding",
    "MissingObservationsFinding",
    "ObservationLike",
    "ReconciliationError",
    "TemporalConsistencyFinding",
    "TimestampSkewFinding",
    "UnitValidationFinding",
    "check_temporal_consistency",
    "check_timestamp_skew",
    "detect_duplicate_records",
    "detect_missing_observations",
    "observation_coverage",
    "validate_measurement_units",
]


class ReconciliationError(StrixError):
    """An observation, dataset, or reconciliation input could not be trusted,
    normalized, or interpreted (malformed dict, naive timestamp, empty
    expected-period set, or an out-of-range parameter)."""


#: What every integrity check accepts: a typed node or a simple mapping.
ObservationLike = SourceObservation | Mapping[str, object]

_REQUIRED_KEYS = ("subject", "concept", "unit", "period", "value", "timestamp")


# --------------------------------------------------------------------------
# Finding models (frozen; classification + offending items)
# --------------------------------------------------------------------------


class DuplicateFinding(StrixModel):
    """Groups of indices whose observations are byte-identical records."""

    classification: str
    duplicate_groups: tuple[tuple[int, ...], ...]


class MissingObservationsFinding(StrixModel):
    """Expected periods with no corresponding observation present."""

    classification: str
    expected_periods: tuple[str, ...]
    present_periods: tuple[str, ...]
    missing_periods: tuple[str, ...]


class TemporalConsistencyFinding(StrixModel):
    """Index pairs ``(earlier_period_idx, later_period_idx)`` whose observation
    timestamps regress: a later period was observed before an earlier one."""

    classification: str
    violations: tuple[tuple[int, int], ...]


class TimestampSkewFinding(StrixModel):
    """Observations whose timestamp lies more than ``max_skew_seconds`` after
    the earliest timestamp in the set."""

    classification: str
    max_skew_seconds: int
    observed_skew_seconds: DecimalValue
    flagged_indices: tuple[int, ...]


class CoverageFinding(StrixModel):
    """Fraction of expected periods that are present (exact Decimal ratio)."""

    classification: str
    coverage_ratio: DecimalValue
    expected_periods: tuple[str, ...]
    present_periods: tuple[str, ...]
    missing_periods: tuple[str, ...]


class UnitValidationFinding(StrixModel):
    """Observations whose measurement unit differs from the expected unit."""

    classification: str
    expected_unit: str
    flagged_indices: tuple[int, ...]
    offending_units: tuple[str, ...]


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------


class _Obs(NamedTuple):
    """Internal, normalized view of one observation."""

    subject: str
    concept: str
    unit: str
    period: str
    value: Decimal
    timestamp: datetime


def _coerce_decimal(value: object) -> Decimal:
    """Coerce to a finite Decimal, re-raising float/parse failures as typed."""
    try:
        return as_decimal(value)
    except StrixError as exc:  # NumericalContractError is a StrixError
        raise ReconciliationError(str(exc)) from exc


def _require_str(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ReconciliationError(
            f"observation field {field!r} must be a str, got {type(value).__name__}"
        )
    return value


def _require_aware(value: object, *, field: str = "timestamp") -> datetime:
    if not isinstance(value, datetime):
        raise ReconciliationError(
            f"observation field {field!r} must be a datetime, got {type(value).__name__}"
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ReconciliationError("timestamps must be timezone-aware (naive forbidden)")
    return value


def _normalize_one(item: ObservationLike) -> _Obs:
    if isinstance(item, SourceObservation):
        return _Obs(
            subject=item.subject_id,
            concept=item.concept,
            unit=item.unit,
            period=item.observation_period,
            value=item.value,
            timestamp=item.observed_at,
        )
    if isinstance(item, Mapping):
        for key in _REQUIRED_KEYS:
            if key not in item:
                raise ReconciliationError(f"observation mapping is missing key {key!r}")
        return _Obs(
            subject=_require_str(item["subject"], field="subject"),
            concept=_require_str(item["concept"], field="concept"),
            unit=_require_str(item["unit"], field="unit"),
            period=_require_str(item["period"], field="period"),
            value=_coerce_decimal(item["value"]),
            timestamp=_require_aware(item["timestamp"]),
        )
    raise ReconciliationError(
        f"unsupported observation type {type(item).__name__}; expected "
        "SourceObservation or a mapping"
    )


def _normalize(observations: Sequence[ObservationLike]) -> list[_Obs]:
    return [_normalize_one(item) for item in observations]


def _delta_seconds(later: datetime, earlier: datetime) -> Decimal:
    """Exact Decimal seconds between two aware datetimes (no float)."""
    delta = later.astimezone(UTC) - earlier.astimezone(UTC)
    return (
        Decimal(delta.days) * Decimal(86400)
        + Decimal(delta.seconds)
        + checked_div(Decimal(delta.microseconds), Decimal(1_000_000))
    )


def _unique(periods: Sequence[str]) -> tuple[str, ...]:
    """Order-preserving de-duplication."""
    return tuple(dict.fromkeys(periods))


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def detect_duplicate_records(observations: Sequence[ObservationLike]) -> DuplicateFinding:
    """Flag groups of byte-identical observation records.

    Two records are duplicates when they agree on subject, concept, unit,
    period, canonical value, and UTC-normalized timestamp.
    """
    rows = _normalize(observations)
    groups: dict[tuple[str, ...], list[int]] = {}
    for index, row in enumerate(rows):
        key = (
            row.subject,
            row.concept,
            row.unit,
            row.period,
            encode_decimal(row.value),
            row.timestamp.astimezone(UTC).isoformat(),
        )
        groups.setdefault(key, []).append(index)
    duplicate_groups = tuple(
        tuple(indices) for indices in groups.values() if len(indices) > 1
    )
    classification = "duplicates_present" if duplicate_groups else "no_duplicates"
    return DuplicateFinding(classification=classification, duplicate_groups=duplicate_groups)


def detect_missing_observations(
    observations: Sequence[ObservationLike], expected_periods: Sequence[str]
) -> MissingObservationsFinding:
    """Flag expected periods that have no corresponding observation."""
    expected = _unique(expected_periods)
    if not expected:
        raise ReconciliationError("expected_periods must contain at least one period")
    rows = _normalize(observations)
    present_set = {row.period for row in rows}
    present = tuple(p for p in expected if p in present_set)
    missing = tuple(p for p in expected if p not in present_set)
    classification = "missing_observations" if missing else "complete"
    return MissingObservationsFinding(
        classification=classification,
        expected_periods=expected,
        present_periods=present,
        missing_periods=missing,
    )


def check_temporal_consistency(
    observations: Sequence[ObservationLike],
) -> TemporalConsistencyFinding:
    """Flag timestamp regressions within each ``(subject, concept)`` series.

    Within a series, observations ordered by ``period`` (lexicographically, as
    supplied) must have non-decreasing timestamps; a later period observed
    before an earlier one is a violation. Periods are compared as given, so the
    caller must supply sortable period labels.
    """
    rows = _normalize(observations)
    groups: dict[tuple[str, str], list[int]] = {}
    for index, row in enumerate(rows):
        groups.setdefault((row.subject, row.concept), []).append(index)
    violations: list[tuple[int, int]] = []
    for indices in groups.values():
        ordered = sorted(indices, key=lambda i: rows[i].period)
        for prev, curr in pairwise(ordered):
            if rows[curr].timestamp < rows[prev].timestamp:
                violations.append((prev, curr))
    violations.sort()
    classification = "temporal_violation" if violations else "consistent"
    return TemporalConsistencyFinding(
        classification=classification, violations=tuple(violations)
    )


def check_timestamp_skew(
    observations: Sequence[ObservationLike], max_skew_seconds: int
) -> TimestampSkewFinding:
    """Flag observations lagging the earliest timestamp by more than the window.

    ``observed_skew_seconds`` is the full span (max minus min) in exact Decimal
    seconds; ``flagged_indices`` are those more than ``max_skew_seconds`` after
    the earliest timestamp.
    """
    if max_skew_seconds < 0:
        raise ReconciliationError("max_skew_seconds must be non-negative")
    rows = _normalize(observations)
    if not rows:
        raise ReconciliationError("timestamp skew requires at least one observation")
    baseline = min(row.timestamp for row in rows)
    latest = max(row.timestamp for row in rows)
    limit = Decimal(max_skew_seconds)
    flagged = tuple(
        index
        for index, row in enumerate(rows)
        if _delta_seconds(row.timestamp, baseline) > limit
    )
    classification = "skew_exceeded" if flagged else "within_skew"
    return TimestampSkewFinding(
        classification=classification,
        max_skew_seconds=max_skew_seconds,
        observed_skew_seconds=_delta_seconds(latest, baseline),
        flagged_indices=flagged,
    )


def observation_coverage(
    observations: Sequence[ObservationLike], expected_periods: Sequence[str]
) -> CoverageFinding:
    """Report the fraction of expected periods that are present."""
    expected = _unique(expected_periods)
    if not expected:
        raise ReconciliationError("expected_periods must contain at least one period")
    rows = _normalize(observations)
    present_set = {row.period for row in rows}
    present = tuple(p for p in expected if p in present_set)
    missing = tuple(p for p in expected if p not in present_set)
    ratio = checked_div(Decimal(len(present)), Decimal(len(expected)))
    classification = "incomplete" if missing else "complete"
    return CoverageFinding(
        classification=classification,
        coverage_ratio=ratio,
        expected_periods=expected,
        present_periods=present,
        missing_periods=missing,
    )


def validate_measurement_units(
    observations: Sequence[ObservationLike], expected_unit: str
) -> UnitValidationFinding:
    """Flag observations whose measurement unit differs from ``expected_unit``."""
    rows = _normalize(observations)
    flagged: list[int] = []
    offending: list[str] = []
    for index, row in enumerate(rows):
        if row.unit != expected_unit:
            flagged.append(index)
            offending.append(row.unit)
    classification = "unit_mismatch" if flagged else "consistent"
    return UnitValidationFinding(
        classification=classification,
        expected_unit=expected_unit,
        flagged_indices=tuple(flagged),
        offending_units=tuple(offending),
    )
