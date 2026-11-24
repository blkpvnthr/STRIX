"""Audit event vocabulary, the durable event record, and its factory.

An :class:`EventRecord` is the atomic, frozen unit of the audit ledger. Its
``event_id`` is content-derived (:func:`strix.canonical.make_id`) and commits
to everything that identifies the event *including its chain position* — its
``sequence`` and ``previous_event_digest`` — so each id transitively anchors
the entire prior history. The id never hashes itself and never hashes any
persistence wall-clock, exactly as the rest of STRIX requires.

Callers never fill in ``sequence`` or ``previous_event_digest`` by hand: they
submit an :class:`EventDraft` to the ledger, which assigns the chain position
and builds the final record through :func:`make_event_record`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum

from pydantic import AwareDatetime, Field

from strix.audit import AUDIT_SCHEMA_VERSION
from strix.canonical import canonical_hash, make_id
from strix.errors import StrixError
from strix.models import StrixModel

__all__ = [
    "AuditError",
    "EventDraft",
    "EventRecord",
    "EventType",
    "make_event_record",
    "recompute_event_id",
]

#: Content-id prefix for audit events: ``EVT-<sha256[:12]>``.
EVENT_ID_PREFIX = "EVT"

#: Filesystem-safe token accepted as a run identifier on a persisted record.
_RUN_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$"


class AuditError(StrixError):
    """A durable-audit operation could not be trusted or completed.

    Raised for unsafe identifiers, corrupt or unreadable ledger state, and —
    critically — any failed durable write. An audit-critical write never fails
    silently: the record is either committed and acknowledged or this is raised.
    """


class EventType(StrEnum):
    """The R1 §19.1 decision-to-outcome lifecycle vocabulary.

    Ordered by phase: research, verification, answer, execution, outcome, and
    termination. The ledger stores the raw event; this enum only constrains the
    permissible *kinds* of event so the lifecycle stays a closed vocabulary.
    """

    # -- research --------------------------------------------------------
    RESEARCH_REQUESTED = "research_requested"
    ACQUISITION_ACTION_SELECTED = "acquisition_action_selected"
    BUDGET_RESERVED = "budget_reserved"
    SOURCE_ARTIFACT_PRESERVED = "source_artifact_preserved"
    OBSERVATION_NORMALIZED = "observation_normalized"
    CALCULATION_COMPLETED = "calculation_completed"
    NUMERICAL_PARITY_CHECKED = "numerical_parity_checked"
    # -- verification ----------------------------------------------------
    CLAIM_PROPOSED = "claim_proposed"
    CLAIM_VERIFIED = "claim_verified"
    CLAIM_REJECTED = "claim_rejected"
    CLAIM_INVALIDATED = "claim_invalidated"
    CERTIFICATE_ISSUED = "certificate_issued"
    # -- answer ----------------------------------------------------------
    ANSWER_PLAN_CREATED = "answer_plan_created"
    ANSWER_SYNTHESIZED = "answer_synthesized"
    ANSWER_VALIDATED = "answer_validated"
    # -- execution -------------------------------------------------------
    AUTHORIZATION_REQUESTED = "authorization_requested"
    AUTHORIZATION_GRANTED = "authorization_granted"
    AUTHORIZATION_REJECTED = "authorization_rejected"
    ACTION_DISPATCHED = "action_dispatched"
    EXECUTOR_ACKNOWLEDGED = "executor_acknowledged"
    ACTION_COMPLETED = "action_completed"
    ACTION_FAILED = "action_failed"
    # -- outcome ---------------------------------------------------------
    OUTCOME_OBSERVED = "outcome_observed"
    OUTCOME_RECONCILED = "outcome_reconciled"
    OUTCOME_CERTIFIED = "outcome_certified"
    # -- termination -----------------------------------------------------
    BUDGET_RECONCILED = "budget_reconciled"
    RESEARCH_COMPLETED = "research_completed"
    RESEARCH_TERMINATED = "research_terminated"


class EventDraft(StrixModel):
    """A caller-supplied audit event, before the ledger assigns its position.

    The ledger derives ``sequence``, ``previous_event_digest``, ``payload_digest``
    and ``event_id`` on append; the caller supplies only what describes the event
    itself plus the ``idempotency_key`` that makes the append safe to retry.
    """

    research_run_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    causation_id: str | None = None
    event_type: EventType
    schema_version: str = AUDIT_SCHEMA_VERSION
    event_timestamp: AwareDatetime
    actor: str = Field(min_length=1)
    policy_version: str | None = None
    payload: dict[str, str] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1)


class EventRecord(StrixModel):
    """One committed, hash-chained audit event.

    ``payload_digest`` is the canonical hash of ``payload``; ``event_id`` is the
    content id over every identifying field (including ``sequence`` and
    ``previous_event_digest``) but never over ``event_id`` itself or any
    persistence timestamp. ``previous_event_digest`` is the prior event's
    ``event_id`` (``None`` for the first event in a run), forming the chain.
    """

    event_id: str = Field(pattern=r"^EVT-[0-9a-f]{12}$")
    research_run_id: str = Field(pattern=_RUN_ID_PATTERN)
    correlation_id: str = Field(min_length=1)
    causation_id: str | None
    sequence: int = Field(ge=0)
    event_type: EventType
    schema_version: str = Field(min_length=1)
    event_timestamp: AwareDatetime
    actor: str = Field(min_length=1)
    policy_version: str | None
    payload: dict[str, str]
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_event_digest: str | None
    idempotency_key: str = Field(min_length=1)


def _event_id_payload(
    *,
    research_run_id: str,
    correlation_id: str,
    causation_id: str | None,
    sequence: int,
    event_type: EventType,
    schema_version: str,
    event_timestamp: datetime,
    actor: str,
    policy_version: str | None,
    payload_digest: str,
    previous_event_digest: str | None,
    idempotency_key: str,
) -> dict[str, object]:
    """Reproducible id inputs — the payload is represented only by its digest."""
    return {
        "research_run_id": research_run_id,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "sequence": sequence,
        "event_type": event_type,
        "schema_version": schema_version,
        "event_timestamp": event_timestamp,
        "actor": actor,
        "policy_version": policy_version,
        "payload_digest": payload_digest,
        "previous_event_digest": previous_event_digest,
        "idempotency_key": idempotency_key,
    }


def make_event_record(
    *,
    research_run_id: str,
    correlation_id: str,
    causation_id: str | None,
    sequence: int,
    event_type: EventType,
    schema_version: str,
    event_timestamp: datetime,
    actor: str,
    policy_version: str | None,
    payload: Mapping[str, str],
    previous_event_digest: str | None,
    idempotency_key: str,
) -> EventRecord:
    """Build a committed :class:`EventRecord`, computing its digest and id.

    ``payload_digest`` is ``canonical_hash(payload)`` and ``event_id`` is the
    :func:`strix.canonical.make_id` over every identifying field — never over
    the id itself and never over any wall-clock persistence time.
    """
    payload_dict = dict(payload)
    payload_digest = canonical_hash(payload_dict)
    event_id = make_id(
        EVENT_ID_PREFIX,
        _event_id_payload(
            research_run_id=research_run_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            sequence=sequence,
            event_type=event_type,
            schema_version=schema_version,
            event_timestamp=event_timestamp,
            actor=actor,
            policy_version=policy_version,
            payload_digest=payload_digest,
            previous_event_digest=previous_event_digest,
            idempotency_key=idempotency_key,
        ),
    )
    return EventRecord(
        event_id=event_id,
        research_run_id=research_run_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        sequence=sequence,
        event_type=event_type,
        schema_version=schema_version,
        event_timestamp=event_timestamp,
        actor=actor,
        policy_version=policy_version,
        payload=payload_dict,
        payload_digest=payload_digest,
        previous_event_digest=previous_event_digest,
        idempotency_key=idempotency_key,
    )


def recompute_event_id(record: EventRecord) -> str:
    """Recompute the content id of a record from its own fields.

    Used by chain verification to detect any in-place tamper: if the recomputed
    id differs from ``record.event_id`` the record's identifying content changed
    after it was committed.
    """
    return make_id(
        EVENT_ID_PREFIX,
        _event_id_payload(
            research_run_id=record.research_run_id,
            correlation_id=record.correlation_id,
            causation_id=record.causation_id,
            sequence=record.sequence,
            event_type=record.event_type,
            schema_version=record.schema_version,
            event_timestamp=record.event_timestamp,
            actor=record.actor,
            policy_version=record.policy_version,
            payload_digest=record.payload_digest,
            previous_event_digest=record.previous_event_digest,
            idempotency_key=record.idempotency_key,
        ),
    )
