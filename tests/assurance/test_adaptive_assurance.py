"""Tests for R4 adaptive assurance (deterministic, auditable policy adaptation).

Adaptive assurance adjusts the REQUIRED assurance strictness for a context from its
recorded outcome history. It is deterministic (no ML, no randomness, no future
data), fail-closed (never loosens below a floor, never tolerates HIGH/INSUFFICIENT
uncertainty at any tier), and asymmetric (tighten fast on any failure, relax slowly
after a sustained clean streak). It never bypasses the gateway — it only moves the
required bar within [floor, max].
"""

from __future__ import annotations

import pytest

from strix.assurance.adaptive import (
    DEFAULT_ADAPTATION_POLICY,
    MAX_TIER,
    MIN_TIER,
    AdaptationDirection,
    AdaptationPolicy,
    OutcomeKind,
    initial_state,
    max_tolerated_uncertainty,
    observe,
    requires_secondary_review,
)
from strix.assurance.uncertainty import UncertaintyLevel

_POLICY = DEFAULT_ADAPTATION_POLICY
_STRICTNESS = {  # higher = stricter (less uncertainty tolerated)
    UncertaintyLevel.MODERATE: 0,
    UncertaintyLevel.LOW: 1,
}


def _fold(kinds: list[OutcomeKind], policy: AdaptationPolicy = _POLICY):
    state = initial_state("ctx", policy)
    for kind in kinds:
        state = observe(state, kind, policy).new_state
    return state


# --- bounds (the safety floor and cap) ------------------------------------


def test_tier_never_drops_below_floor() -> None:
    state = _fold([OutcomeKind.CLEAN] * 50)
    assert state.tier >= MIN_TIER
    assert state.tier == MIN_TIER  # a long clean history relaxes all the way to floor


def test_tier_never_exceeds_max() -> None:
    state = _fold([OutcomeKind.FAILURE] * 50)
    assert state.tier <= MAX_TIER
    assert state.tier == MAX_TIER


# --- asymmetric adaptation ------------------------------------------------


def test_any_failure_tightens_one_tier() -> None:
    state = initial_state("ctx", _POLICY)
    result = observe(state, OutcomeKind.FAILURE, _POLICY)
    assert result.direction is AdaptationDirection.TIGHTEN
    assert result.new_tier == min(state.tier + 1, MAX_TIER)
    assert result.new_state.consecutive_clean == 0


def test_relax_requires_a_full_clean_streak() -> None:
    # Start tightened, then feed cleans; HOLD until the streak threshold, then RELAX.
    state = observe(initial_state("ctx", _POLICY), OutcomeKind.FAILURE, _POLICY).new_state
    tightened = state.tier
    for _ in range(_POLICY.relax_after_clean_streak - 1):
        result = observe(state, OutcomeKind.CLEAN, _POLICY)
        assert result.direction is AdaptationDirection.HOLD
        assert result.new_tier == tightened
        state = result.new_state
    final = observe(state, OutcomeKind.CLEAN, _POLICY)
    assert final.direction is AdaptationDirection.RELAX
    assert final.new_tier == tightened - 1


def test_failure_resets_a_building_clean_streak() -> None:
    state = observe(initial_state("ctx", _POLICY), OutcomeKind.FAILURE, _POLICY).new_state
    # Build a partial clean streak, then one failure wipes it.
    for _ in range(_POLICY.relax_after_clean_streak - 1):
        state = observe(state, OutcomeKind.CLEAN, _POLICY).new_state
    assert state.consecutive_clean > 0
    after_failure = observe(state, OutcomeKind.FAILURE, _POLICY).new_state
    assert after_failure.consecutive_clean == 0


# --- determinism / auditability -------------------------------------------


def test_folding_is_deterministic() -> None:
    seq = [OutcomeKind.CLEAN, OutcomeKind.FAILURE, OutcomeKind.CLEAN, OutcomeKind.FAILURE]
    assert _fold(seq).digest() == _fold(seq).digest()


def test_result_records_rationale_and_counts() -> None:
    result = observe(initial_state("ctx", _POLICY), OutcomeKind.FAILURE, _POLICY)
    assert result.rationale
    assert result.new_state.total_failure == 1
    assert result.previous_tier != result.new_tier or result.direction is AdaptationDirection.HOLD


# --- the hard safety floor: never tolerate HIGH/INSUFFICIENT ---------------


@pytest.mark.parametrize("tier", list(range(MIN_TIER, MAX_TIER + 1)))
def test_mapping_never_tolerates_high_or_insufficient(tier: int) -> None:
    tolerated = max_tolerated_uncertainty(tier)
    assert tolerated not in (UncertaintyLevel.HIGH, UncertaintyLevel.INSUFFICIENT)


def test_mapping_is_monotonic_in_strictness() -> None:
    # A higher tier tolerates no MORE uncertainty than a lower tier.
    for tier in range(MIN_TIER, MAX_TIER):
        looser = _STRICTNESS[max_tolerated_uncertainty(tier)]
        stricter = _STRICTNESS[max_tolerated_uncertainty(tier + 1)]
        assert stricter >= looser


def test_secondary_review_only_at_max_tier() -> None:
    assert requires_secondary_review(MAX_TIER) is True
    assert requires_secondary_review(MIN_TIER) is False


# --- policy validation ----------------------------------------------------


def test_policy_floor_cannot_exceed_max() -> None:
    with pytest.raises(ValueError):
        AdaptationPolicy(min_tier=2, max_tier=1, start_tier=1, relax_after_clean_streak=3)


def test_start_tier_must_be_within_bounds() -> None:
    with pytest.raises(ValueError):
        AdaptationPolicy(min_tier=0, max_tier=2, start_tier=5, relax_after_clean_streak=3)
