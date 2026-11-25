"""Operating modes and the capability policy they imply (§10).

Four modes bound what STRIX may do; the policy is derived deterministically per
mode. ``require_*`` guards raise :class:`SecurityError` when a capability is denied,
so callers fail closed instead of silently proceeding.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from strix.errors import StrixError
from strix.models import StrixModel

#: Environment variable that selects the operating mode.
OPERATING_MODE_ENV = "STRIX_OPERATING_MODE"


class SecurityError(StrixError):
    """Raised when an operating-mode policy denies a requested capability."""


class OperatingMode(StrEnum):
    """The four supported operating modes (§10)."""

    #: Open research: all capabilities permitted (the default).
    OPEN_RESEARCH = "open_research"
    #: Closed institutional: no external research or cloud inference; assurance
    #: cannot be disabled.
    CLOSED_INSTITUTIONAL = "closed_institutional"
    #: Controlled hybrid: external research permitted, assurance mandatory.
    CONTROLLED_HYBRID = "controlled_hybrid"
    #: Fully disconnected: no network-facing capability; the most restrictive mode.
    DISCONNECTED = "disconnected"


class SecurityPolicy(StrixModel):
    """The capabilities an operating mode permits."""

    mode: OperatingMode
    external_research_allowed: bool
    cloud_inference_allowed: bool
    #: Whether the ``--no-assurance`` / assurance-bypass escape may be used.
    assurance_bypass_allowed: bool


_POLICIES: dict[OperatingMode, SecurityPolicy] = {
    OperatingMode.OPEN_RESEARCH: SecurityPolicy(
        mode=OperatingMode.OPEN_RESEARCH,
        external_research_allowed=True,
        cloud_inference_allowed=True,
        assurance_bypass_allowed=True,
    ),
    OperatingMode.CONTROLLED_HYBRID: SecurityPolicy(
        mode=OperatingMode.CONTROLLED_HYBRID,
        external_research_allowed=True,
        cloud_inference_allowed=True,
        assurance_bypass_allowed=False,
    ),
    OperatingMode.CLOSED_INSTITUTIONAL: SecurityPolicy(
        mode=OperatingMode.CLOSED_INSTITUTIONAL,
        external_research_allowed=False,
        cloud_inference_allowed=False,
        assurance_bypass_allowed=False,
    ),
    OperatingMode.DISCONNECTED: SecurityPolicy(
        mode=OperatingMode.DISCONNECTED,
        external_research_allowed=False,
        cloud_inference_allowed=False,
        assurance_bypass_allowed=False,
    ),
}


def policy_for(mode: OperatingMode) -> SecurityPolicy:
    """The capability policy for ``mode``."""
    return _POLICIES[mode]


def resolve_operating_mode(environ: Mapping[str, str]) -> OperatingMode:
    """Resolve the operating mode from the environment.

    Defaults to :attr:`OperatingMode.OPEN_RESEARCH` when unset; an unrecognized
    value fails closed to :attr:`OperatingMode.DISCONNECTED` (most restrictive).
    """
    raw = environ.get(OPERATING_MODE_ENV)
    if raw is None or raw == "":
        return OperatingMode.OPEN_RESEARCH
    try:
        return OperatingMode(raw.strip().lower())
    except ValueError:
        return OperatingMode.DISCONNECTED


def require_external_research(policy: SecurityPolicy) -> None:
    """Raise unless external research is permitted."""
    if not policy.external_research_allowed:
        raise SecurityError(
            f"external research is disabled in {policy.mode.value} mode"
        )


def require_cloud_inference(policy: SecurityPolicy) -> None:
    """Raise unless cloud model inference is permitted."""
    if not policy.cloud_inference_allowed:
        raise SecurityError(
            f"cloud inference is disabled in {policy.mode.value} mode"
        )


def require_assurance_enabled(policy: SecurityPolicy, *, assurance_disabled: bool) -> None:
    """Raise if the caller tries to disable assurance where it is not permitted."""
    if assurance_disabled and not policy.assurance_bypass_allowed:
        raise SecurityError(
            f"disabling assurance is not permitted in {policy.mode.value} mode"
        )
