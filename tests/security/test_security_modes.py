"""Tests for security operating modes + default-deny policy (§10)."""

from __future__ import annotations

import pytest

from strix.security.modes import (
    OperatingMode,
    SecurityError,
    policy_for,
    require_assurance_enabled,
    require_cloud_inference,
    require_external_research,
    resolve_operating_mode,
)


def test_open_research_permits_everything() -> None:
    p = policy_for(OperatingMode.OPEN_RESEARCH)
    assert p.external_research_allowed
    assert p.cloud_inference_allowed
    assert p.assurance_bypass_allowed


def test_closed_institutional_denies_external_and_cloud_and_bypass() -> None:
    p = policy_for(OperatingMode.CLOSED_INSTITUTIONAL)
    assert p.external_research_allowed is False
    assert p.cloud_inference_allowed is False
    # Disabling assurance must not be a usable escape in a governed institution.
    assert p.assurance_bypass_allowed is False


def test_disconnected_denies_all_network_facing_capabilities() -> None:
    p = policy_for(OperatingMode.DISCONNECTED)
    assert p.external_research_allowed is False
    assert p.cloud_inference_allowed is False
    assert p.assurance_bypass_allowed is False


def test_controlled_hybrid_allows_external_but_not_assurance_bypass() -> None:
    p = policy_for(OperatingMode.CONTROLLED_HYBRID)
    assert p.external_research_allowed is True
    assert p.cloud_inference_allowed is True
    assert p.assurance_bypass_allowed is False


def test_require_guards_raise_when_denied() -> None:
    closed = policy_for(OperatingMode.CLOSED_INSTITUTIONAL)
    with pytest.raises(SecurityError):
        require_external_research(closed)
    with pytest.raises(SecurityError):
        require_cloud_inference(closed)
    with pytest.raises(SecurityError):
        require_assurance_enabled(closed, assurance_disabled=True)
    # Assurance enabled is always fine.
    require_assurance_enabled(closed, assurance_disabled=False)


def test_require_guards_pass_in_open_mode() -> None:
    openp = policy_for(OperatingMode.OPEN_RESEARCH)
    require_external_research(openp)
    require_cloud_inference(openp)
    require_assurance_enabled(openp, assurance_disabled=True)  # allowed in open mode


def test_resolve_mode_defaults_to_open() -> None:
    assert resolve_operating_mode({}) is OperatingMode.OPEN_RESEARCH


def test_resolve_mode_from_env() -> None:
    assert resolve_operating_mode(
        {"STRIX_OPERATING_MODE": "closed_institutional"}
    ) is OperatingMode.CLOSED_INSTITUTIONAL


def test_resolve_mode_rejects_unknown_fail_closed() -> None:
    # An unrecognized mode must fail closed to the most restrictive mode.
    assert resolve_operating_mode(
        {"STRIX_OPERATING_MODE": "bogus"}
    ) is OperatingMode.DISCONNECTED
