"""Adversarial tests for the independent runtime behavior monitor (R2-B, R1 §2).

The monitor is an *independent* assurance control: the monitored autonomous
agent must never be able to override it (R1 §2). These tests confirm the
deterministic policy assessment (continue / restrict / terminate /
escalate_human) and — critically — that there is no API by which monitored code
can disable the monitor, relax its policy, or erase a recorded violation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.assurance.monitoring import (
    BehaviorMonitor,
    Intervention,
    MonitoredEvent,
    MonitoredEventType,
    MonitorFinding,
    MonitoringError,
    MonitorPolicy,
)
from strix.errors import StrixError

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _policy(**overrides: object) -> MonitorPolicy:
    base: dict[str, object] = {
        "max_tool_calls": 10,
        "max_identical_calls": 3,
        "max_cost": Decimal("100"),
        "max_verification_failures": 2,
    }
    base.update(overrides)
    return MonitorPolicy(**base)


def _event(
    event_type: MonitoredEventType,
    label: str = "x",
    cost: Decimal = Decimal(0),
    *,
    offset: int = 0,
) -> MonitoredEvent:
    return MonitoredEvent(
        event_type=event_type,
        label=label,
        cost=cost,
        timestamp=NOW + timedelta(seconds=offset),
    )


# --------------------------------------------------------------------------
# Taxonomy / model discipline
# --------------------------------------------------------------------------


def test_monitoring_error_is_strix_error() -> None:
    assert issubclass(MonitoringError, StrixError)


def test_event_rejects_float_cost() -> None:
    with pytest.raises(ValueError):
        MonitoredEvent(
            event_type=MonitoredEventType.COST_INCURRED,
            label="c",
            cost=1.5,
            timestamp=NOW,
        )


def test_policy_and_event_are_frozen() -> None:
    policy = _policy()
    with pytest.raises(ValidationError):
        policy.max_tool_calls = 999  # type: ignore[misc]
    event = _event(MonitoredEventType.TOOL_INVOCATION)
    with pytest.raises(ValidationError):
        event.label = "mutated"  # type: ignore[misc]


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------


def test_normal_sequence_continues() -> None:
    monitor = BehaviorMonitor(_policy())
    for i in range(3):
        monitor.record(_event(MonitoredEventType.TOOL_INVOCATION, f"tool_{i}", offset=i))
    monitor.record(_event(MonitoredEventType.COST_INCURRED, "c", Decimal("5"), offset=9))
    finding = monitor.assess()
    assert isinstance(finding, MonitorFinding)
    assert finding.intervention is Intervention.CONTINUE
    assert finding.reason_codes == ()
    assert finding.tool_calls == 3
    assert finding.total_cost == Decimal("5")


def test_empty_monitor_continues() -> None:
    assert BehaviorMonitor(_policy()).assess().intervention is Intervention.CONTINUE


# --------------------------------------------------------------------------
# Termination triggers
# --------------------------------------------------------------------------


def test_unauthorized_operation_terminates() -> None:
    monitor = BehaviorMonitor(_policy())
    monitor.record(_event(MonitoredEventType.TOOL_INVOCATION, "a"))
    monitor.record(_event(MonitoredEventType.UNAUTHORIZED_OPERATION, "danger", offset=1))
    finding = monitor.assess()
    assert finding.intervention is Intervention.TERMINATE
    assert "unauthorized_operation" in finding.reason_codes


def test_evidence_integrity_failure_terminates() -> None:
    monitor = BehaviorMonitor(_policy())
    monitor.record(_event(MonitoredEventType.EVIDENCE_INTEGRITY_FAILURE, "tamper"))
    finding = monitor.assess()
    assert finding.intervention is Intervention.TERMINATE
    assert "evidence_integrity_failure" in finding.reason_codes


def test_cost_overrun_terminates() -> None:
    monitor = BehaviorMonitor(_policy(max_cost=Decimal("10")))
    monitor.record(_event(MonitoredEventType.COST_INCURRED, "c", Decimal("7")))
    monitor.record(_event(MonitoredEventType.COST_INCURRED, "c", Decimal("7"), offset=1))
    finding = monitor.assess()
    assert finding.total_cost == Decimal("14")
    assert finding.intervention is Intervention.TERMINATE
    assert "cost_overrun" in finding.reason_codes


def test_tight_loop_detected_and_terminates() -> None:
    monitor = BehaviorMonitor(_policy(max_identical_calls=3))
    for i in range(3):
        monitor.record(_event(MonitoredEventType.TOOL_INVOCATION, "same", offset=i))
    finding = monitor.assess()
    assert finding.identical_call_runs == 3
    assert "loop_detected" in finding.reason_codes
    assert finding.intervention is Intervention.TERMINATE


def test_loop_detected_event_terminates() -> None:
    monitor = BehaviorMonitor(_policy())
    monitor.record(_event(MonitoredEventType.LOOP_DETECTED, "reported"))
    finding = monitor.assess()
    assert "loop_detected" in finding.reason_codes
    assert finding.intervention is Intervention.TERMINATE


def test_interleaved_different_labels_do_not_trip_loop() -> None:
    monitor = BehaviorMonitor(_policy(max_identical_calls=3))
    labels = ["a", "b", "a", "b", "a"]
    for i, lbl in enumerate(labels):
        monitor.record(_event(MonitoredEventType.TOOL_INVOCATION, lbl, offset=i))
    finding = monitor.assess()
    assert finding.identical_call_runs == 1
    assert "loop_detected" not in finding.reason_codes
    assert finding.intervention is Intervention.CONTINUE


# --------------------------------------------------------------------------
# Restrict / escalate triggers
# --------------------------------------------------------------------------


def test_tool_budget_exceeded_restricts() -> None:
    monitor = BehaviorMonitor(_policy(max_tool_calls=3, max_identical_calls=99))
    for i in range(4):
        monitor.record(_event(MonitoredEventType.TOOL_INVOCATION, f"t{i}", offset=i))
    finding = monitor.assess()
    assert finding.tool_calls == 4
    assert finding.intervention is Intervention.RESTRICT
    assert "tool_call_budget_exceeded" in finding.reason_codes


def test_repeated_verification_failures_escalate_human() -> None:
    monitor = BehaviorMonitor(_policy(max_verification_failures=2))
    for i in range(3):
        monitor.record(_event(MonitoredEventType.VERIFICATION_FAILURE, "v", offset=i))
    finding = monitor.assess()
    assert finding.verification_failures == 3
    assert finding.intervention is Intervention.ESCALATE_HUMAN
    assert "verification_failures_exceeded" in finding.reason_codes


def test_policy_violation_event_restricts() -> None:
    monitor = BehaviorMonitor(_policy())
    monitor.record(_event(MonitoredEventType.POLICY_VIOLATION, "pv"))
    finding = monitor.assess()
    assert finding.intervention is Intervention.RESTRICT
    assert "policy_violation" in finding.reason_codes


# --------------------------------------------------------------------------
# Severity selection / deterministic ordering
# --------------------------------------------------------------------------


def test_most_severe_intervention_wins_and_all_reasons_recorded() -> None:
    # Budget exceeded (restrict), verification failures (escalate), AND an
    # unauthorized op (terminate) all present at once: terminate must win and
    # every reason code must be carried for audit.
    monitor = BehaviorMonitor(_policy(max_tool_calls=1, max_verification_failures=0))
    monitor.record(_event(MonitoredEventType.TOOL_INVOCATION, "t0", offset=0))
    monitor.record(_event(MonitoredEventType.TOOL_INVOCATION, "t1", offset=1))
    monitor.record(_event(MonitoredEventType.VERIFICATION_FAILURE, "v", offset=2))
    monitor.record(_event(MonitoredEventType.UNAUTHORIZED_OPERATION, "u", offset=3))
    finding = monitor.assess()
    assert finding.intervention is Intervention.TERMINATE
    assert "unauthorized_operation" in finding.reason_codes
    assert "tool_call_budget_exceeded" in finding.reason_codes
    assert "verification_failures_exceeded" in finding.reason_codes
    # reason codes are deterministically ordered (sorted)
    assert list(finding.reason_codes) == sorted(finding.reason_codes)


def test_assess_is_deterministic_and_repeatable() -> None:
    monitor = BehaviorMonitor(_policy())
    monitor.record(_event(MonitoredEventType.UNAUTHORIZED_OPERATION, "u"))
    assert monitor.assess() == monitor.assess()


# --------------------------------------------------------------------------
# Control cannot be overridden (R1 §2)
# --------------------------------------------------------------------------


def test_no_api_to_disable_or_erase_violations() -> None:
    monitor = BehaviorMonitor(_policy())
    monitor.record(_event(MonitoredEventType.UNAUTHORIZED_OPERATION, "u"))
    # No method to clear/reset/disable the monitor or wipe recorded events.
    for forbidden in (
        "clear",
        "reset",
        "disable",
        "relax",
        "suppress",
        "override",
        "remove",
        "pop",
        "erase",
        "set_policy",
    ):
        assert not hasattr(monitor, forbidden), f"monitor must not expose {forbidden!r}"
    # The violation persists across re-assessment; it cannot be forgotten.
    assert monitor.assess().intervention is Intervention.TERMINATE


def test_recorded_events_view_is_immutable_snapshot() -> None:
    monitor = BehaviorMonitor(_policy())
    monitor.record(_event(MonitoredEventType.UNAUTHORIZED_OPERATION, "u"))
    events = monitor.events
    assert isinstance(events, tuple)
    # The snapshot is a copy: rebinding or extending it cannot reach back into
    # the monitor's own recorded state.
    extended = (*events, _event(MonitoredEventType.TOOL_INVOCATION, "sneaky"))
    assert len(extended) == 2
    assert len(monitor.events) == 1
    assert monitor.assess().intervention is Intervention.TERMINATE


def test_relaxing_terminate_flag_still_does_not_silently_continue() -> None:
    # Even if policy disables hard-termination on unauthorized ops, the monitor
    # must NOT let the violation pass as a normal 'continue': the control cannot
    # be fully overridden via policy. It downgrades to RESTRICT, still flagged.
    monitor = BehaviorMonitor(_policy(terminate_on_unauthorized=False))
    monitor.record(_event(MonitoredEventType.UNAUTHORIZED_OPERATION, "u"))
    finding = monitor.assess()
    assert finding.intervention is not Intervention.CONTINUE
    assert finding.intervention is Intervention.RESTRICT
    assert "unauthorized_operation" in finding.reason_codes


def test_relaxing_integrity_flag_still_flags_restrict() -> None:
    monitor = BehaviorMonitor(_policy(terminate_on_integrity_failure=False))
    monitor.record(_event(MonitoredEventType.EVIDENCE_INTEGRITY_FAILURE, "tamper"))
    finding = monitor.assess()
    assert finding.intervention is Intervention.RESTRICT
    assert "evidence_integrity_failure" in finding.reason_codes


def test_record_rejects_non_event() -> None:
    monitor = BehaviorMonitor(_policy())
    with pytest.raises(MonitoringError):
        monitor.record("not-an-event")  # type: ignore[arg-type]
