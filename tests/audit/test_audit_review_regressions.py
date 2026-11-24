"""Regression for the GAP-002 ledger read defect (review wf_4e2cb7c3-6ee): the
ledger split records with str.splitlines(), which also breaks on U+2028/U+2029/
U+0085 — characters that appear raw in canonical JSON (ensure_ascii=False) — so a
payload containing one corrupted the read. Records must split on newline only."""

from __future__ import annotations

from datetime import UTC, datetime

from strix.audit.events import EventDraft, EventType
from strix.audit.ledger import EventLedger

RUN = "RUN-UNICODE-001"
NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)

# Escapes, so the source has no ambiguous literals while the runtime string embeds
# U+2028 (LINE SEP), U+0085 (NEL), and U+2029 (PARA SEP).
TRICKY = "alpha" + chr(0x2028) + "beta" + chr(0x85) + "gamma" + chr(0x2029) + "delta"


def test_payload_with_unicode_line_breaks_roundtrips(tmp_path) -> None:  # type: ignore[no-untyped-def]
    ledger = EventLedger(tmp_path)
    ledger.append(
        EventDraft(
            research_run_id=RUN,
            correlation_id="CORR-1",
            event_type=EventType.RESEARCH_REQUESTED,
            event_timestamp=NOW,
            actor="orchestrator",
            payload={"question": TRICKY},
            idempotency_key="k0",
        )
    )
    events = ledger.read(RUN)
    assert len(events) == 1
    assert events[0].payload["question"] == TRICKY
    assert ledger.verify_chain(RUN).ok
