"""Tests for the audit event contracts and the ``make_event_record`` factory."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from strix.audit import AUDIT_SCHEMA_VERSION
from strix.audit.events import (
    AuditError,
    EventDraft,
    EventRecord,
    EventType,
    make_event_record,
    recompute_event_id,
)
from strix.canonical import canonical_hash
from strix.errors import StrixError

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def _record(**overrides: object) -> EventRecord:
    base: dict[str, object] = {
        "research_run_id": "RUN-20261124-001",
        "correlation_id": "CORR-1",
        "causation_id": None,
        "sequence": 0,
        "event_type": EventType.RESEARCH_REQUESTED,
        "schema_version": AUDIT_SCHEMA_VERSION,
        "event_timestamp": NOW,
        "actor": "orchestrator",
        "policy_version": None,
        "payload": {"question": "did margin improve?"},
        "previous_event_digest": None,
        "idempotency_key": "k-0",
    }
    base.update(overrides)
    return make_event_record(**base)  # type: ignore[arg-type]


def test_audit_error_is_strix_error() -> None:
    assert issubclass(AuditError, StrixError)


def test_event_type_covers_the_lifecycle() -> None:
    names = {e.value for e in EventType}
    # A reasonable subset of R1 §19.1 across every phase.
    required = {
        "research_requested",
        "calculation_completed",
        "claim_proposed",
        "claim_verified",
        "certificate_issued",
        "answer_synthesized",
        "authorization_granted",
        "action_dispatched",
        "action_completed",
        "outcome_observed",
        "outcome_reconciled",
        "outcome_certified",
        "research_completed",
        "research_terminated",
    }
    assert required <= names
    assert len(names) >= 20


def test_make_event_record_computes_payload_digest() -> None:
    rec = _record(payload={"a": "1", "b": "2"})
    assert rec.payload_digest == canonical_hash({"a": "1", "b": "2"})
    assert rec.event_id.startswith("EVT-")


def test_make_event_record_is_deterministic() -> None:
    assert _record().event_id == _record().event_id
    assert _record().payload_digest == _record().payload_digest


def test_payload_change_changes_both_digests() -> None:
    a = _record(payload={"x": "1"})
    b = _record(payload={"x": "2"})
    assert a.payload_digest != b.payload_digest
    assert a.event_id != b.event_id


def test_event_id_commits_to_chain_position() -> None:
    # Same intrinsic content at a different sequence / chain link => different id.
    a = _record(sequence=0, previous_event_digest=None, idempotency_key="k")
    b = _record(sequence=1, previous_event_digest="EVT-deadbeef0000", idempotency_key="k")
    assert a.event_id != b.event_id


def test_recompute_event_id_matches() -> None:
    rec = _record(payload={"m": "n"}, sequence=3, previous_event_digest="EVT-aaaaaaaaaaaa")
    assert recompute_event_id(rec) == rec.event_id


def test_event_record_is_frozen() -> None:
    rec = _record()
    with pytest.raises(ValidationError):
        rec.sequence = 9  # type: ignore[misc]


def test_event_draft_is_closed_schema() -> None:
    with pytest.raises(ValidationError):
        EventDraft(  # type: ignore[call-arg]
            research_run_id="RUN-20261124-001",
            correlation_id="CORR-1",
            event_type=EventType.RESEARCH_REQUESTED,
            event_timestamp=NOW,
            actor="orchestrator",
            payload={"q": "x"},
            idempotency_key="k",
            extra_field="nope",
        )


def test_naive_timestamp_rejected() -> None:
    # The canonical layer refuses naive datetimes (ValueError) before the model
    # would (ValidationError); either way the record is never built.
    with pytest.raises((ValidationError, ValueError)):
        _record(event_timestamp=datetime(2026, 11, 24, 12, 0))  # naive
