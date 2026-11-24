"""Tests for the durable, append-only, hash-chained audit ledger."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from strix.audit import ledger as ledger_mod
from strix.audit.events import AuditError, EventDraft, EventType
from strix.audit.ledger import ChainIssueType, EventLedger

RUN = "RUN-20261124-001"
NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def _draft(key: str, event_type: EventType, **payload: str) -> EventDraft:
    return EventDraft(
        research_run_id=RUN,
        correlation_id="CORR-1",
        event_type=event_type,
        event_timestamp=NOW,
        actor="orchestrator",
        payload=dict(payload),
        idempotency_key=key,
    )


def _seed(ledger: EventLedger) -> None:
    ledger.append(_draft("k0", EventType.RESEARCH_REQUESTED, q="margin?"))
    ledger.append(_draft("k1", EventType.CALCULATION_COMPLETED, metric="operating_margin"))
    ledger.append(_draft("k2", EventType.CLAIM_VERIFIED, claim="CL-1"))


def test_append_assigns_increasing_sequence_and_chains(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    r0 = ledger.append(_draft("k0", EventType.RESEARCH_REQUESTED, q="x"))
    r1 = ledger.append(_draft("k1", EventType.CALCULATION_COMPLETED, m="y"))
    r2 = ledger.append(_draft("k2", EventType.CLAIM_VERIFIED, c="z"))
    assert (r0.sequence, r1.sequence, r2.sequence) == (0, 1, 2)
    assert r0.previous_event_digest is None
    assert r1.previous_event_digest == r0.event_id
    assert r2.previous_event_digest == r1.event_id


def test_idempotent_reappend_returns_existing(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    first = ledger.append(_draft("same", EventType.RESEARCH_REQUESTED, q="x"))
    again = ledger.append(_draft("same", EventType.RESEARCH_REQUESTED, q="x"))
    assert again == first
    assert len(ledger.read(RUN)) == 1


def test_read_returns_ordered(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    _seed(ledger)
    records = ledger.read(RUN)
    assert [r.sequence for r in records] == [0, 1, 2]
    assert [r.event_type for r in records] == [
        EventType.RESEARCH_REQUESTED,
        EventType.CALCULATION_COMPLETED,
        EventType.CLAIM_VERIFIED,
    ]


def test_read_missing_run_is_empty(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    assert ledger.read(RUN) == ()


def test_verify_chain_ok_on_clean_log(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    _seed(ledger)
    report = ledger.verify_chain(RUN)
    assert report.ok is True
    assert report.event_count == 3
    assert report.issues == ()


def test_verify_chain_detects_tampered_payload(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    _seed(ledger)
    path = ledger.ledger_path(RUN)
    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[1])
    rec["payload"]["metric"] = "tampered_value"  # digest no longer matches
    lines[1] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = ledger.verify_chain(RUN)
    assert report.ok is False
    assert ChainIssueType.PAYLOAD_DIGEST_MISMATCH in {i.issue_type for i in report.issues}


def test_verify_chain_detects_sequence_gap(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    _seed(ledger)
    path = ledger.ledger_path(RUN)
    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[1]  # drop the middle event -> gap
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = ledger.verify_chain(RUN)
    assert report.ok is False
    assert ChainIssueType.SEQUENCE_GAP in {i.issue_type for i in report.issues}


def test_verify_chain_detects_broken_chain_link(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    _seed(ledger)
    path = ledger.ledger_path(RUN)
    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[2])
    rec["previous_event_digest"] = "EVT-000000000000"  # points nowhere
    lines[2] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = ledger.verify_chain(RUN)
    assert report.ok is False
    assert ChainIssueType.BROKEN_CHAIN_LINK in {i.issue_type for i in report.issues}


def test_verify_chain_detects_tail_truncation_via_manifest(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    _seed(ledger)
    path = ledger.ledger_path(RUN)
    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[-1]  # drop the last event; remaining chain stays internally valid
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = ledger.verify_chain(RUN)
    assert report.ok is False
    assert ChainIssueType.TAIL_TRUNCATION in {i.issue_type for i in report.issues}


def test_replay_reconstructs_committed_trace(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    _seed(ledger)
    replay = ledger.replay(RUN)
    assert replay.ok is True
    assert replay.events == ledger.read(RUN)
    assert replay.event_type_sequence == (
        EventType.RESEARCH_REQUESTED,
        EventType.CALCULATION_COMPLETED,
        EventType.CLAIM_VERIFIED,
    )


def test_replay_refuses_a_broken_trace(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    _seed(ledger)
    path = ledger.ledger_path(RUN)
    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(AuditError):
        ledger.replay(RUN)


def test_durable_recovery_fresh_ledger_reads_prior_events(tmp_path: Path) -> None:
    EventLedger(tmp_path).append(_draft("k0", EventType.RESEARCH_REQUESTED, q="x"))
    _seed_second = EventLedger(tmp_path)
    _seed_second.append(_draft("k1", EventType.CALCULATION_COMPLETED, m="y"))
    reopened = EventLedger(tmp_path)
    records = reopened.read(RUN)
    assert [r.sequence for r in records] == [0, 1]
    assert reopened.verify_chain(RUN).ok is True


def test_write_failure_raises_not_silent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = EventLedger(tmp_path)

    def boom(path: Path, data: bytes) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(ledger_mod, "_write_atomic", boom)
    with pytest.raises(AuditError):
        ledger.append(_draft("k0", EventType.RESEARCH_REQUESTED, q="x"))


def test_append_rejects_unsafe_run_id(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path)
    with pytest.raises(AuditError):
        ledger.append(
            EventDraft(
                research_run_id="../escape",
                correlation_id="CORR-1",
                event_type=EventType.RESEARCH_REQUESTED,
                event_timestamp=NOW,
                actor="a",
                payload={},
                idempotency_key="k",
            )
        )
