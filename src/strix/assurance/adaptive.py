"""R4 adaptive assurance: deterministic, auditable policy adaptation.

The assurance bar for a context is raised or lowered from its RECORDED outcome
history — not learned by a model, not drawn from a distribution, and never using
future information. Adaptation is:

* **deterministic** — folding the same outcome sequence always yields the same
  state (replayable; every state is content-addressed via :meth:`digest`);
* **asymmetric and conservative** — any failure tightens the bar by one tier
  immediately; relaxing requires a sustained clean streak (fast to distrust, slow
  to trust);
* **bounded** — the tier never leaves ``[min_tier, max_tier]``; the floor is a
  non-negotiable minimum strictness;
* **non-bypassing** — adaptation only moves the REQUIRED tier, which maps to the
  maximum tolerated :class:`UncertaintyLevel`; that mapping never tolerates
  ``HIGH`` or ``INSUFFICIENT`` at any tier, so the gateway's fail-closed floor
  holds regardless of how far the policy relaxes.

This module produces the required tier and its mapping; wiring it into the live
gateway is a separate integration step. It never assigns a factual verdict.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import model_validator

from strix.assurance.uncertainty import UncertaintyLevel
from strix.canonical import canonical_hash
from strix.models import StrixModel

#: Ordinal assurance tiers (higher = stricter = less uncertainty tolerated).
MIN_TIER = 0
MAX_TIER = 2


class OutcomeKind(StrEnum):
    """A recorded post-decision outcome used to adapt the bar."""

    #: The decision held up (no breach/mismatch/correction later observed).
    CLEAN = "clean"
    #: A later-detected problem (monitored breach, reconciliation mismatch, correction).
    FAILURE = "failure"


class AdaptationDirection(StrEnum):
    """What one observation did to the required tier."""

    TIGHTEN = "tighten"
    RELAX = "relax"
    HOLD = "hold"


class AdaptationPolicy(StrixModel):
    """Bounds and cadence for adaptation (all deterministic)."""

    min_tier: int = MIN_TIER
    max_tier: int = MAX_TIER
    start_tier: int = MIN_TIER
    #: Consecutive clean outcomes required before the bar relaxes one tier.
    relax_after_clean_streak: int = 3

    @model_validator(mode="after")
    def _check_bounds(self) -> AdaptationPolicy:
        if self.min_tier > self.max_tier:
            raise ValueError("min_tier must not exceed max_tier")
        if not self.min_tier <= self.start_tier <= self.max_tier:
            raise ValueError("start_tier must lie within [min_tier, max_tier]")
        if self.relax_after_clean_streak < 1:
            raise ValueError("relax_after_clean_streak must be >= 1")
        return self


DEFAULT_ADAPTATION_POLICY = AdaptationPolicy()


class AdaptiveAssuranceState(StrixModel):
    """The adapted assurance state for one context."""

    context_key: str
    tier: int
    consecutive_clean: int = 0
    consecutive_failure: int = 0
    total_clean: int = 0
    total_failure: int = 0

    def digest(self) -> str:
        """Content address of the state (for the audit ledger / replay checks)."""
        return canonical_hash(
            {
                "context_key": self.context_key,
                "tier": self.tier,
                "consecutive_clean": self.consecutive_clean,
                "consecutive_failure": self.consecutive_failure,
                "total_clean": self.total_clean,
                "total_failure": self.total_failure,
            }
        )


class AdaptationResult(StrixModel):
    """The outcome of folding one observation into the state."""

    new_state: AdaptiveAssuranceState
    direction: AdaptationDirection
    previous_tier: int
    new_tier: int
    rationale: str


def initial_state(context_key: str, policy: AdaptationPolicy) -> AdaptiveAssuranceState:
    """The starting state for a context at the policy's ``start_tier``."""
    return AdaptiveAssuranceState(context_key=context_key, tier=policy.start_tier)


def observe(
    state: AdaptiveAssuranceState,
    outcome: OutcomeKind,
    policy: AdaptationPolicy,
) -> AdaptationResult:
    """Fold one recorded outcome into ``state`` and return the adaptation."""
    previous_tier = state.tier

    if outcome is OutcomeKind.FAILURE:
        new_tier = min(state.tier + 1, policy.max_tier)
        direction = (
            AdaptationDirection.TIGHTEN if new_tier > previous_tier else AdaptationDirection.HOLD
        )
        new_state = state.model_copy(
            update={
                "tier": new_tier,
                "consecutive_failure": state.consecutive_failure + 1,
                "consecutive_clean": 0,
                "total_failure": state.total_failure + 1,
            }
        )
        rationale = (
            f"failure observed (consecutive={new_state.consecutive_failure}); "
            f"tier {previous_tier}->{new_tier}"
        )
        return AdaptationResult(
            new_state=new_state,
            direction=direction,
            previous_tier=previous_tier,
            new_tier=new_tier,
            rationale=rationale,
        )

    # CLEAN: build the streak; relax one tier only once it reaches the threshold.
    streak = state.consecutive_clean + 1
    if streak >= policy.relax_after_clean_streak and state.tier > policy.min_tier:
        new_tier = state.tier - 1
        direction = AdaptationDirection.RELAX
        new_streak = 0
    else:
        new_tier = state.tier
        direction = AdaptationDirection.HOLD
        new_streak = streak
    new_state = state.model_copy(
        update={
            "tier": new_tier,
            "consecutive_clean": new_streak,
            "consecutive_failure": 0,
            "total_clean": state.total_clean + 1,
        }
    )
    rationale = (
        f"clean observed (streak={streak}/{policy.relax_after_clean_streak}); "
        f"tier {previous_tier}->{new_tier}"
    )
    return AdaptationResult(
        new_state=new_state,
        direction=direction,
        previous_tier=previous_tier,
        new_tier=new_tier,
        rationale=rationale,
    )


def max_tolerated_uncertainty(tier: int) -> UncertaintyLevel:
    """Maximum uncertainty acceptable for AUTHORIZED at ``tier``.

    The mapping NEVER returns ``HIGH`` or ``INSUFFICIENT`` — those are rejected at
    every tier, so adaptation can never loosen past the gateway's fail-closed
    safety floor. A higher tier tolerates no more uncertainty than a lower one.

    ``tier`` is interpreted on the canonical ``[MIN_TIER, MAX_TIER]`` scale;
    custom :class:`AdaptationPolicy` bounds that widen this range still map safely
    (any tier above ``MIN_TIER`` requires ``LOW``), never below the floor.
    """
    if tier <= MIN_TIER:
        return UncertaintyLevel.MODERATE
    return UncertaintyLevel.LOW


def requires_secondary_review(tier: int) -> bool:
    """Whether the strictest tier additionally mandates a secondary review."""
    return tier >= MAX_TIER
