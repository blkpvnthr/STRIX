"""Tests for strix.reconciliation.integrity (R1 §12, GAP-003).

Each integrity check is exercised on a clean dataset (no finding) and a
violating dataset (the finding names the offending items). Covers acceptance
of both ``SourceObservation`` nodes and simple dicts, the tz-aware /
``float``-rejection discipline on dict inputs, and adversarial/edge cases.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from strix.errors import StrixError
from strix.evidence_graph.nodes import make_source_observation
from strix.reconciliation.integrity import (
    CoverageFinding,
    DuplicateFinding,
    MissingObservationsFinding,
    ReconciliationError,
    TemporalConsistencyFinding,
    TimestampSkewFinding,
    UnitValidationFinding,
    check_temporal_consistency,
    check_timestamp_skew,
    detect_duplicate_records,
    detect_missing_observations,
    observation_coverage,
    validate_measurement_units,
)


def _obs(
    *,
    subject: str = "SUB-1",
    concept: str = "revenue",
    unit: str = "USD",
    period: str,
    value: str,
    ts: datetime,
) -> dict[str, object]:
    """Build a simple-dict observation for the integrity checks."""
    return {
        "subject": subject,
        "concept": concept,
        "unit": unit,
        "period": period,
        "value": Decimal(value),
        "timestamp": ts,
    }


def _t(day: int, hour: int = 0) -> datetime:
    return datetime(2024, 1, day, hour, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# Accepts both node and dict shapes
# --------------------------------------------------------------------------


def test_accepts_source_observation_nodes() -> None:
    node = make_source_observation(
        subject_id="SUB-1",
        concept="revenue",
        value=Decimal("100"),
        unit="USD",
        observation_period="2021",
        observed_at=_t(1),
        source_artifact_id="ART-1",
        source_locator="/x",
    )
    finding = detect_duplicate_records([node])
    assert isinstance(finding, DuplicateFinding)
    assert finding.classification == "no_duplicates"


# --------------------------------------------------------------------------
# Duplicate records
# --------------------------------------------------------------------------


def test_duplicate_records_clean() -> None:
    obs = [
        _obs(period="2021", value="100", ts=_t(1)),
        _obs(period="2022", value="110", ts=_t(2)),
    ]
    finding = detect_duplicate_records(obs)
    assert finding.classification == "no_duplicates"
    assert finding.duplicate_groups == ()


def test_duplicate_records_flagged() -> None:
    obs = [
        _obs(period="2021", value="100", ts=_t(1)),
        _obs(period="2022", value="110", ts=_t(2)),
        _obs(period="2021", value="100", ts=_t(1)),
    ]
    finding = detect_duplicate_records(obs)
    assert finding.classification == "duplicates_present"
    assert finding.duplicate_groups == ((0, 2),)


# --------------------------------------------------------------------------
# Missing observations
# --------------------------------------------------------------------------


def test_missing_observations_complete() -> None:
    obs = [
        _obs(period="2021", value="100", ts=_t(1)),
        _obs(period="2022", value="110", ts=_t(2)),
    ]
    finding = detect_missing_observations(obs, expected_periods=["2021", "2022"])
    assert isinstance(finding, MissingObservationsFinding)
    assert finding.classification == "complete"
    assert finding.missing_periods == ()


def test_missing_observations_flagged() -> None:
    obs = [_obs(period="2021", value="100", ts=_t(1))]
    finding = detect_missing_observations(obs, expected_periods=["2021", "2022", "2023"])
    assert finding.classification == "missing_observations"
    assert finding.missing_periods == ("2022", "2023")


def test_missing_observations_requires_expected_periods() -> None:
    with pytest.raises(ReconciliationError):
        detect_missing_observations([], expected_periods=[])


# --------------------------------------------------------------------------
# Temporal consistency
# --------------------------------------------------------------------------


def test_temporal_consistency_clean() -> None:
    obs = [
        _obs(period="2021", value="100", ts=_t(1)),
        _obs(period="2022", value="110", ts=_t(2)),
        _obs(period="2023", value="120", ts=_t(3)),
    ]
    finding = check_temporal_consistency(obs)
    assert isinstance(finding, TemporalConsistencyFinding)
    assert finding.classification == "consistent"
    assert finding.violations == ()


def test_temporal_consistency_violation() -> None:
    # 2023 is a later period but was observed BEFORE 2022 — inconsistent.
    obs = [
        _obs(period="2021", value="100", ts=_t(1)),
        _obs(period="2022", value="110", ts=_t(5)),
        _obs(period="2023", value="120", ts=_t(3)),
    ]
    finding = check_temporal_consistency(obs)
    assert finding.classification == "temporal_violation"
    assert finding.violations == ((1, 2),)


def test_temporal_consistency_groups_by_subject_concept() -> None:
    # Two independent series interleaved; each internally monotonic -> clean.
    obs = [
        _obs(subject="A", period="2021", value="1", ts=_t(1)),
        _obs(subject="B", period="2021", value="1", ts=_t(9)),
        _obs(subject="A", period="2022", value="2", ts=_t(2)),
        _obs(subject="B", period="2022", value="2", ts=_t(10)),
    ]
    finding = check_temporal_consistency(obs)
    assert finding.classification == "consistent"


# --------------------------------------------------------------------------
# Timestamp skew
# --------------------------------------------------------------------------


def test_timestamp_skew_within() -> None:
    obs = [
        _obs(period="2021", value="100", ts=_t(1, 0)),
        _obs(period="2022", value="110", ts=_t(1, 1)),
    ]
    finding = check_timestamp_skew(obs, max_skew_seconds=7200)
    assert isinstance(finding, TimestampSkewFinding)
    assert finding.classification == "within_skew"
    assert finding.flagged_indices == ()
    assert finding.observed_skew_seconds == Decimal("3600")


def test_timestamp_skew_exceeded() -> None:
    obs = [
        _obs(period="2021", value="100", ts=_t(1, 0)),
        _obs(period="2022", value="110", ts=_t(1, 1)),
        _obs(period="2023", value="120", ts=_t(3, 0)),
    ]
    finding = check_timestamp_skew(obs, max_skew_seconds=7200)
    assert finding.classification == "skew_exceeded"
    assert finding.flagged_indices == (2,)


def test_timestamp_skew_rejects_negative_window() -> None:
    obs = [_obs(period="2021", value="100", ts=_t(1))]
    with pytest.raises(ReconciliationError):
        check_timestamp_skew(obs, max_skew_seconds=-1)


def test_timestamp_skew_requires_observations() -> None:
    with pytest.raises(ReconciliationError):
        check_timestamp_skew([], max_skew_seconds=10)


# --------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------


def test_coverage_complete() -> None:
    obs = [
        _obs(period="2021", value="100", ts=_t(1)),
        _obs(period="2022", value="110", ts=_t(2)),
    ]
    finding = observation_coverage(obs, expected_periods=["2021", "2022"])
    assert isinstance(finding, CoverageFinding)
    assert finding.classification == "complete"
    assert finding.coverage_ratio == Decimal("1")
    assert finding.missing_periods == ()


def test_coverage_incomplete() -> None:
    obs = [_obs(period="2021", value="100", ts=_t(1))]
    finding = observation_coverage(obs, expected_periods=["2021", "2022", "2023", "2024"])
    assert finding.classification == "incomplete"
    assert finding.coverage_ratio == Decimal("0.25")
    assert finding.missing_periods == ("2022", "2023", "2024")


def test_coverage_requires_expected_periods() -> None:
    with pytest.raises(ReconciliationError):
        observation_coverage([], expected_periods=[])


# --------------------------------------------------------------------------
# Measurement units
# --------------------------------------------------------------------------


def test_units_consistent() -> None:
    obs = [
        _obs(period="2021", value="100", unit="USD", ts=_t(1)),
        _obs(period="2022", value="110", unit="USD", ts=_t(2)),
    ]
    finding = validate_measurement_units(obs, expected_unit="USD")
    assert isinstance(finding, UnitValidationFinding)
    assert finding.classification == "consistent"
    assert finding.flagged_indices == ()


def test_units_mismatch() -> None:
    obs = [
        _obs(period="2021", value="100", unit="USD", ts=_t(1)),
        _obs(period="2022", value="110", unit="EUR", ts=_t(2)),
    ]
    finding = validate_measurement_units(obs, expected_unit="USD")
    assert finding.classification == "unit_mismatch"
    assert finding.flagged_indices == (1,)
    assert finding.offending_units == ("EUR",)


# --------------------------------------------------------------------------
# Input discipline (float / tz-awareness / malformed dict)
# --------------------------------------------------------------------------


def test_float_value_rejected() -> None:
    bad = {
        "subject": "SUB-1",
        "concept": "revenue",
        "unit": "USD",
        "period": "2021",
        "value": 100.0,  # float forbidden
        "timestamp": _t(1),
    }
    with pytest.raises(StrixError):
        detect_duplicate_records([bad])


def test_naive_timestamp_rejected() -> None:
    bad = {
        "subject": "SUB-1",
        "concept": "revenue",
        "unit": "USD",
        "period": "2021",
        "value": Decimal("100"),
        "timestamp": datetime(2024, 1, 1, 0, 0, 0),  # naive
    }
    with pytest.raises(ReconciliationError):
        check_timestamp_skew([bad], max_skew_seconds=10)


def test_missing_dict_key_rejected() -> None:
    bad = {"subject": "SUB-1", "concept": "revenue", "unit": "USD"}
    with pytest.raises(ReconciliationError):
        detect_duplicate_records([bad])


def test_unsupported_item_type_rejected() -> None:
    with pytest.raises(ReconciliationError):
        detect_duplicate_records(["not-an-observation"])  # type: ignore[list-item]
