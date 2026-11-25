"""Tests for per-institution instance isolation (§13).

Isolation is the trust boundary STRIX is built on: one institution's audit chain,
signing keys, and resources must never be visible to or usable by another.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from strix.assurance.signing import generate_keypair, sign_certificate, verify_signature
from strix.audit.events import EventDraft, EventType
from strix.institutional.isolation import InstanceContext, IsolationError
from strix.institutional.models import make_institution

_DOMAIN = "strix.test"


def _ctx(base: Path, slug: str) -> InstanceContext:
    return InstanceContext(make_institution(slug, slug.title()), base)


def _draft(run_id: str) -> EventDraft:
    return EventDraft(
        research_run_id=run_id,
        correlation_id="corr-1",
        event_type=EventType.RESEARCH_REQUESTED,
        event_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        actor="tester",
        idempotency_key="idem-1",
    )


def test_instance_directories_are_separate(tmp_path: Path) -> None:
    a = _ctx(tmp_path, "alpha")
    b = _ctx(tmp_path, "beta")
    assert a.instance_dir != b.instance_dir
    assert a.audit_dir != b.audit_dir
    assert a.institution_id in str(a.instance_dir)


def test_ledger_is_isolated_between_institutions(tmp_path: Path) -> None:
    a = _ctx(tmp_path, "alpha")
    b = _ctx(tmp_path, "beta")
    a.ledger().append(_draft("run-1"))
    # The event exists in A's chain...
    assert len(a.ledger().read("run-1")) == 1
    # ...and is invisible to B, which uses a separate root.
    assert b.ledger().read("run-1") == ()
    assert a.ledger().root_dir != b.ledger().root_dir


def test_signing_keys_are_isolated_between_institutions(tmp_path: Path) -> None:
    a = _ctx(tmp_path, "alpha")
    b = _ctx(tmp_path, "beta")
    private_bytes, record = generate_keypair(created_at=datetime(2026, 1, 1, tzinfo=UTC))
    a.keyring().register(record)
    # Sign an arbitrary StrixModel (the institution record itself serves as one).
    signature = sign_certificate(
        a.institution, private_bytes, record, domain=_DOMAIN,
        signed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    # Verifies under A's keyring (key present)...
    assert verify_signature(a.institution, signature, a.keyring(), expected_domain=_DOMAIN) is True
    # ...but NOT under B's keyring (B never registered the key → fail-closed).
    assert verify_signature(a.institution, signature, b.keyring(), expected_domain=_DOMAIN) is False


def test_resource_ids_are_namespaced_and_owned(tmp_path: Path) -> None:
    a = _ctx(tmp_path, "alpha")
    b = _ctx(tmp_path, "beta")
    rid = a.issue_resource_id("CLAIM", {"q": "revenue"})
    assert rid.startswith(f"{a.institution_id}::")
    assert a.owns(rid) is True
    assert b.owns(rid) is False
    a.assert_owns(rid)  # no raise
    with pytest.raises(IsolationError):
        b.assert_owns(rid)


def test_same_logical_payload_yields_distinct_ids_across_institutions(tmp_path: Path) -> None:
    a = _ctx(tmp_path, "alpha")
    b = _ctx(tmp_path, "beta")
    payload = {"q": "same question"}
    assert a.issue_resource_id("CLAIM", payload) != b.issue_resource_id("CLAIM", payload)


def test_keyring_is_stable_within_a_context(tmp_path: Path) -> None:
    a = _ctx(tmp_path, "alpha")
    assert a.keyring() is a.keyring()
