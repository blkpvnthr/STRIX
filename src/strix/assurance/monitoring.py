"""Independent runtime behavior monitoring (R2-B, R1 §2).

The autonomous agent must **never** be permitted to override its own assurance
controls (R1 §2). :class:`BehaviorMonitor` is that control for *runtime*
behavior: an external observer that accumulates :class:`MonitoredEvent` records
and, on demand, applies a trusted frozen :class:`MonitorPolicy` to produce a
deterministic :class:`MonitorFinding` whose terminal :class:`Intervention` is
one of ``continue`` / ``restrict`` / ``abstain`` / ``terminate`` /
``escalate_human``.

Independence (R1 §2)
--------------------
The monitored code can only *append* events via :meth:`BehaviorMonitor.record`.
There is **no** method to clear recorded events, relax or replace the policy,
disable the monitor, or suppress a finding. The policy is supplied at
construction and is itself a frozen model. Two "terminate on …" policy flags may
*downgrade* a hard stop to a ``restrict``, but they can never silence a
violation into a normal ``continue`` — relaxing a flag is not the same as
overriding the control.

Honesty
-------
A finding reports **ordinal** interventions and explicit named ``reason_codes``
derived deterministically from recorded events — never an invented probability.
The monitor asserts behavioral-policy violations; it makes no claim about the
factual correctness of the underlying work.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import AwareDatetime, Field

from strix.errors import StrixError
from strix.models import DecimalValue, StrixModel

__all__ = [
    "BehaviorMonitor",
    "Intervention",
    "MonitorFinding",
    "MonitorPolicy",
    "MonitoredEvent",
    "MonitoredEventType",
    "MonitoringError",
]


class MonitoringError(StrixError):
    """The runtime monitor received an input it refuses to record or assess."""


class MonitoredEventType(StrEnum):
    """The bounded vocabulary of observable runtime behaviors."""

    TOOL_INVOCATION = "tool_invocation"
    UNAUTHORIZED_OPERATION = "unauthorized_operation"
    POLICY_VIOLATION = "policy_violation"
    EVIDENCE_INTEGRITY_FAILURE = "evidence_integrity_failure"
    VERIFICATION_FAILURE = "verification_failure"
    COST_INCURRED = "cost_incurred"
    LOOP_DETECTED = "loop_detected"


class Intervention(StrEnum):
    """The terminal ordinal verdict the monitor issues (least→most severe)."""

    CONTINUE = "continue"
    RESTRICT = "restrict"
    ABSTAIN = "abstain"
    ESCALATE_HUMAN = "escalate_human"
    TERMINATE = "terminate"


#: Ordinal severity used to select the single terminal intervention when several
#: conditions fire at once. Higher wins; ordering is a pure function of policy.
_SEVERITY: dict[Intervention, int] = {
    Intervention.CONTINUE: 0,
    Intervention.RESTRICT: 1,
    Intervention.ABSTAIN: 2,
    Intervention.ESCALATE_HUMAN: 3,
    Intervention.TERMINATE: 4,
}


class MonitorPolicy(StrixModel):
    """Trusted, versioned thresholds governing runtime interventions.

    ``terminate_on_unauthorized`` / ``terminate_on_integrity_failure`` may
    *downgrade* a hard stop to a ``restrict`` when ``False``; they can never
    suppress the violation into a ``continue`` (R1 §2).
    """

    max_tool_calls: int
    #: Loop guard: a run of this many identical consecutive tool calls is a loop.
    max_identical_calls: int
    max_cost: DecimalValue
    max_verification_failures: int
    terminate_on_unauthorized: bool = True
    terminate_on_integrity_failure: bool = True


class MonitoredEvent(StrixModel):
    """One observed runtime behavior, recorded by the monitor."""

    event_type: MonitoredEventType
    label: str
    #: Non-negative: a negative cost could otherwise be appended to pull the
    #: running total back below the budget and evade the cost circuit-breaker.
    cost: DecimalValue = Field(default=Decimal(0), ge=Decimal(0))
    timestamp: AwareDatetime


class MonitorFinding(StrixModel):
    """The deterministic outcome of applying a policy to accumulated events."""

    intervention: Intervention
    reason_codes: tuple[str, ...]
    tool_calls: int
    #: Length of the longest run of identical consecutive tool invocations.
    identical_call_runs: int
    total_cost: DecimalValue
    verification_failures: int


def _longest_identical_run(labels: list[str]) -> int:
    """Length of the longest run of identical consecutive entries in *labels*."""
    longest = 0
    current = 0
    previous: str | None = None
    for label in labels:
        if label == previous:
            current += 1
        else:
            current = 1
            previous = label
        longest = max(longest, current)
    return longest


class BehaviorMonitor:
    """An independent, append-only runtime behavior monitor (R1 §2).

    Construct with a trusted :class:`MonitorPolicy`; feed observed behaviors via
    :meth:`record`; call :meth:`assess` for the current :class:`MonitorFinding`.
    The monitored agent cannot disable this control: there is no method to clear
    events, replace or relax the policy, or suppress a finding.
    """

    def __init__(self, policy: MonitorPolicy) -> None:
        if not isinstance(policy, MonitorPolicy):
            raise MonitoringError("BehaviorMonitor requires a MonitorPolicy")
        # Private, append-only; no accessor ever returns the live list.
        self._policy = policy
        self._events: list[MonitoredEvent] = []

    @property
    def policy(self) -> MonitorPolicy:
        """The frozen policy governing this monitor (read-only)."""
        return self._policy

    @property
    def events(self) -> tuple[MonitoredEvent, ...]:
        """An immutable snapshot of recorded events (mutating it is inert)."""
        return tuple(self._events)

    def record(self, event: MonitoredEvent) -> None:
        """Append one observed behavior. Events can only be added, never removed."""
        if not isinstance(event, MonitoredEvent):
            raise MonitoringError("record expects a MonitoredEvent")
        self._events.append(event)

    def assess(self) -> MonitorFinding:
        """Apply the policy to all recorded events, deterministically.

        Collects every triggered reason code (for audit) and selects the single
        most severe :class:`Intervention`. An empty or compliant history yields
        ``continue``.
        """
        policy = self._policy
        tool_labels = [
            e.label for e in self._events
            if e.event_type is MonitoredEventType.TOOL_INVOCATION
        ]
        tool_calls = len(tool_labels)
        identical_run = _longest_identical_run(tool_labels)
        total_cost = sum((e.cost for e in self._events), Decimal(0))
        verification_failures = sum(
            1 for e in self._events
            if e.event_type is MonitoredEventType.VERIFICATION_FAILURE
        )
        has_unauthorized = any(
            e.event_type is MonitoredEventType.UNAUTHORIZED_OPERATION
            for e in self._events
        )
        has_integrity_failure = any(
            e.event_type is MonitoredEventType.EVIDENCE_INTEGRITY_FAILURE
            for e in self._events
        )
        has_policy_violation = any(
            e.event_type is MonitoredEventType.POLICY_VIOLATION for e in self._events
        )
        loop_event = any(
            e.event_type is MonitoredEventType.LOOP_DETECTED for e in self._events
        )

        triggers: list[tuple[str, Intervention]] = []

        # An unauthorized op or integrity failure is a hard stop when configured;
        # relaxing the flag downgrades to RESTRICT but never to CONTINUE (R1 §2).
        if has_unauthorized:
            triggers.append((
                "unauthorized_operation",
                Intervention.TERMINATE
                if policy.terminate_on_unauthorized
                else Intervention.RESTRICT,
            ))
        if has_integrity_failure:
            triggers.append((
                "evidence_integrity_failure",
                Intervention.TERMINATE
                if policy.terminate_on_integrity_failure
                else Intervention.RESTRICT,
            ))
        if loop_event or identical_run >= policy.max_identical_calls:
            triggers.append(("loop_detected", Intervention.TERMINATE))
        if total_cost > policy.max_cost:
            triggers.append(("cost_overrun", Intervention.TERMINATE))
        if tool_calls > policy.max_tool_calls:
            triggers.append(("tool_call_budget_exceeded", Intervention.RESTRICT))
        if verification_failures > policy.max_verification_failures:
            triggers.append((
                "verification_failures_exceeded",
                Intervention.ESCALATE_HUMAN,
            ))
        if has_policy_violation:
            triggers.append(("policy_violation", Intervention.RESTRICT))

        if triggers:
            intervention = max(
                (t[1] for t in triggers), key=lambda i: _SEVERITY[i]
            )
            reason_codes = tuple(sorted({t[0] for t in triggers}))
        else:
            intervention = Intervention.CONTINUE
            reason_codes = ()

        return MonitorFinding(
            intervention=intervention,
            reason_codes=reason_codes,
            tool_calls=tool_calls,
            identical_call_runs=identical_run,
            total_cost=total_cost,
            verification_failures=verification_failures,
        )
