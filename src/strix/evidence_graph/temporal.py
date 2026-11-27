"""Bitemporal evidence reasoning — the extended type/temporal predicate.

Reference implementation of research engine R-N2 (master spec §1.1). It represents
each evidence version with two independent, half-open time axes — a real-world
*validity* interval ``V_i = [v_i^-, v_i^+)`` and a recorded *knowledge* interval
``K_i = [k_i^-, k_i^+)`` — and admits evidence only when it is valid at the requested
validity time ``t_v`` AND was knowable at the requested knowledge time ``t_k``, with a
hard **availability gate** ``a_i ≤ t_k`` that prevents future-information leakage
(confidential companion §5; leak-freedom proved in ``mathematical-invariants.md``
INV-N2-1):

    T_i(t_v, t_k) = 1[t_v ∈ V_i] ∧ 1[t_k ∈ K_i]
    admitted(e) ⇒ a_i ≤ t_k                 (⇒ L_temporal = 0)

This **extends** the existing single-axis point-in-time predicate
(``predicates.py::type_temporal``, the ``t_k`` axis) without replacing it; the existing
behavior is the special case where validity is unconstrained. To avoid perturbing the
content-addressed :class:`~strix.evidence_graph.nodes.SourceObservation` identity, the
two-axis metadata lives in a separate :class:`TemporalEnvelope` rather than being added
to the observation model.

Design rules carried from the manuscript:
- **Missing availability is never favorable:** an unresolved ``a_i`` yields UNKNOWN
  (abstain), never a silent pass.
- **Modes are explicit:** POINT_IN_TIME reconstructs what was knowable at ``t_k``
  (knowledge-interval containment enforced); RETROSPECTIVE analyses a historical
  validity period with current knowledge (knowledge containment relaxed, availability
  gate still enforced).
- **Interval overlap alone is not contradiction:** ``C_t`` additionally requires a
  substantive conflict (subject/units/context/semantics), supplied by the caller.
- **No substitution:** a known retraction or supersession excludes the stale version;
  missing required history abstains rather than substituting a current revision.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime, model_validator

from strix.evidence_graph.nodes import (
    PredicateName,
    PredicateResult,
    PredicateStatus,
    TemporalMode,
)
from strix.models import StrixModel

__all__ = [
    "TemporalEnvelope",
    "TemporalInterval",
    "TemporalScope",
    "admissible_evidence_ids",
    "assess_bitemporal",
    "is_admissible",
    "temporal_contradiction",
    "temporal_leakage",
]


class TemporalInterval(StrixModel):
    """A half-open time interval ``[start, end)``.

    ``start is None`` means unbounded below (-inf); ``end is None`` means unbounded
    above (+inf / still ongoing). Membership is ``start <= t < end``, so adjacent
    intervals share no point (no double-counting at a shared endpoint).
    """

    start: AwareDatetime | None = None
    end: AwareDatetime | None = None

    @model_validator(mode="after")
    def _check_order(self) -> TemporalInterval:
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("temporal interval start must not be after end")
        return self

    def contains(self, moment: datetime) -> bool:
        """Whether *moment* lies in ``[start, end)``."""
        if self.start is not None and moment < self.start:
            return False
        return not (self.end is not None and moment >= self.end)

    def overlaps(self, other: TemporalInterval) -> bool:
        """Whether two half-open intervals share any instant."""
        if self.end is not None and other.start is not None and self.end <= other.start:
            return False
        return not (other.end is not None and self.start is not None and other.end <= self.start)


class TemporalEnvelope(StrixModel):
    """Two-axis temporal metadata for one evidence version.

    ``validity`` is ``V_i`` (when the fact holds in the world); ``knowledge`` is
    ``K_i`` (when it was recorded/knowable). ``available_at`` is the independently
    verified earliest availability ``a_i`` in the relevant knowledge scope — for an
    item with upstream lineage this should be the *latest* availability across its
    provenance closure (set by the caller at graph-integration time), so a back-dated
    wrapper cannot hide a later true availability. ``superseded_by`` / ``retracted_at``
    make revision first-class.
    """

    evidence_id: str
    validity: TemporalInterval
    knowledge: TemporalInterval
    available_at: AwareDatetime | None = None
    superseded_by: str | None = None
    #: When the supersession became known (transaction time). If set and ``<= t_k`` the
    #: version is known-superseded and excluded (symmetric with ``retracted_at``).
    superseded_at: AwareDatetime | None = None
    retracted_at: AwareDatetime | None = None


class TemporalScope(StrixModel):
    """The requested ``(t_v, t_k, mode)`` for a reconstruction."""

    valid_time: AwareDatetime
    knowledge_time: AwareDatetime
    mode: TemporalMode = TemporalMode.POINT_IN_TIME


def _base_admissible(
    envelope: TemporalEnvelope, scope: TemporalScope
) -> tuple[bool | None, str]:
    """The temporal gate WITHOUT the superseded_by chain: availability leak gate,
    known-retraction, known-supersession-by-date, validity, and knowledge containment.

    Kept separate from supersession-chain resolution so that deciding whether a
    *successor* revision is "known as of t_k" cannot recurse back into supersession
    (which caused the chain fail-open). ``available_at`` is checked first as the primary
    leak defense.
    """
    if envelope.available_at is None:
        return None, "availability_unresolved"
    if envelope.available_at > scope.knowledge_time:
        return False, "future_information_leakage"
    if envelope.retracted_at is not None and envelope.retracted_at <= scope.knowledge_time:
        return False, "retracted_as_of_knowledge_time"
    if envelope.superseded_at is not None and envelope.superseded_at <= scope.knowledge_time:
        return False, "superseded_as_of_knowledge_time"
    if not envelope.validity.contains(scope.valid_time):
        return False, "outside_validity_interval"
    if scope.mode is TemporalMode.POINT_IN_TIME and not envelope.knowledge.contains(
        scope.knowledge_time
    ):
        return False, "outside_knowledge_interval"
    return True, "admissible"


def _known_as_of_tk(envelope: TemporalEnvelope, scope: TemporalScope) -> bool | None:
    """Whether a revision is *known to exist* as of the knowledge time ``t_k``.

    This is a **knowledge-time** question only — did this revision become available by
    ``t_k`` and is it not itself retracted as of ``t_k`` — and deliberately does **not**
    consider the revision's validity-at-``t_v`` or point-in-time knowledge containment,
    which concern the revision's *applicability to the query*, not whether a supersession
    is known. (Using full base-admissibility here was the chain fail-open: a correction
    whose own validity window did not cover ``t_v`` was treated as "not a known newer
    revision", re-admitting the stale predecessor — so ``superseded_by`` and the
    equivalent ``superseded_at`` encoding of the same fact disagreed.) Returns ``None``
    when availability is unresolved.
    """
    if envelope.available_at is None:
        return None
    if envelope.available_at > scope.knowledge_time:
        return False  # not yet available -> the supersession is not known as of t_k
    # Known iff not itself retracted as of t_k (a withdrawn correction is not a valid
    # newer revision, so the original would stand).
    return not (
        envelope.retracted_at is not None and envelope.retracted_at <= scope.knowledge_time
    )


def _known_newer_revision_exists(
    envelope: TemporalEnvelope,
    scope: TemporalScope,
    cohort: Mapping[str, TemporalEnvelope],
) -> bool | None:
    """Whether the **immediate** superseding revision is known as of ``t_k``.

    ``superseded_by`` is a linear pointer, so a version is superseded-as-of-``t_k`` iff its
    *immediate* successor is known as of ``t_k`` (:func:`_known_as_of_tk`). We deliberately
    do **not** walk deeper: if the immediate successor is not yet known (not-yet-available
    or retracted), nothing further down the chain is knowable either — you must know the
    immediate link to know the rest — so propagating a deeper known revision across a
    not-yet-known link would use future information and wrongly exclude a currently-valid
    version. The chain composes naturally because *each* version runs this same
    immediate-successor check (E1→E2→E3: E1 excluded iff E2 known; E2 excluded iff E3
    known; E3 current). A correction that is itself later superseded is still ``_known_as_of_tk``
    in its own right, so the genuine transitive case needs no recursion. Returns ``True``
    (a known newer revision exists), ``False`` (not superseded as of ``t_k``), or ``None``
    (the superseding revision is absent from the cohort / its availability is unresolved →
    cannot confirm → abstain). Being non-recursive, it cannot loop on a pointer cycle.
    """
    successor_id = envelope.superseded_by
    if successor_id is None:
        return False  # not superseded
    successor = cohort.get(successor_id)
    if successor is None:
        return None  # superseding revision absent -> cannot confirm currency -> abstain
    return _known_as_of_tk(successor, scope)


def is_admissible(
    envelope: TemporalEnvelope,
    scope: TemporalScope,
    *,
    cohort: Mapping[str, TemporalEnvelope] | None = None,
) -> tuple[bool | None, str]:
    """Return ``(admissible, reason)`` for one envelope under *scope*.

    ``admissible`` is ``True`` / ``False`` / ``None`` (UNKNOWN). The availability gate
    ``a_i ≤ t_k`` is the primary leak defense and is checked before the knowledge
    interval so a forged early knowledge interval cannot mask a late availability.

    **Revision.** A version is inadmissible if known-retracted or known-superseded as of
    ``t_k``: ``superseded_at <= t_k`` (handled in the base gate), or its ``superseded_by``
    chain reaches — **transitively** — a revision that is base-admissible as of the scope
    (so a newer revision is known and the stale version must not be substituted). If the
    chain's currency cannot be confirmed (successor absent from the cohort, or a cycle)
    → UNKNOWN (abstain), never a silent admit of a possibly-stale version.
    """
    base, reason = _base_admissible(envelope, scope)
    if base is not True:
        return base, reason
    if envelope.superseded_by is not None:
        newer = _known_newer_revision_exists(envelope, scope, cohort or {})
        if newer is True:
            return False, "superseded_by_known_revision"
        if newer is None:
            return None, "supersession_unresolved"
    return True, "admissible"


def _cohort(envelopes: tuple[TemporalEnvelope, ...]) -> dict[str, TemporalEnvelope]:
    return {env.evidence_id: env for env in envelopes}


def admissible_evidence_ids(
    envelopes: tuple[TemporalEnvelope, ...], scope: TemporalScope
) -> frozenset[str]:
    """The node-level reconstruction filter: ids whose envelope is admissible.

    This is the node part of ``G_{t_v,t_k,Ω} = Filter(G; T, A_inst, a_i ≤ t_k)``; edge
    and required-closure filtering happen at graph-integration time. Supersession is
    resolved within the given cohort so a known-superseded version is excluded.
    """
    cohort = _cohort(envelopes)
    return frozenset(
        env.evidence_id
        for env in envelopes
        if is_admissible(env, scope, cohort=cohort)[0] is True
    )


def temporal_leakage(
    envelopes: tuple[TemporalEnvelope, ...], scope: TemporalScope
) -> Decimal:
    """Audit metric ``L_temporal`` over *envelopes*: fraction with ``a_i > t_k``.

    By INV-N2-1 this is 0 over any set produced by :func:`admissible_evidence_ids`.
    An empty set is defined as 0 leakage (and is separately insufficiency, not success).
    """
    if not envelopes:
        return Decimal(0)
    leaked = sum(
        1
        for env in envelopes
        if env.available_at is not None and env.available_at > scope.knowledge_time
    )
    # Exact integer ratio reported to 12 dp; never float.
    return (Decimal(leaked) / Decimal(len(envelopes))).quantize(Decimal("0.000000000001"))


def temporal_contradiction(
    a: TemporalEnvelope, b: TemporalEnvelope, *, substantive: bool
) -> bool:
    """Whether ``C_t(a, b)`` holds: a substantive conflict over overlapping validity.

    ``substantive`` (subject/units/context/semantics actually conflict) is supplied by
    the caller — **validity overlap alone is never a contradiction**.
    """
    return substantive and a.validity.overlaps(b.validity)


def assess_bitemporal(
    envelopes: tuple[TemporalEnvelope, ...], scope: TemporalScope
) -> PredicateResult:
    """Evaluate the extended type/temporal predicate ``T`` over supporting envelopes.

    Four-valued admission algebra over the per-envelope results: any FALSE → FAIL (the
    most severe reason reported); else any UNKNOWN → UNKNOWN; else PASS. No supporting
    envelopes → NOT_APPLICABLE (the predicate does not apply; other predicates govern
    sufficiency).
    """
    if not envelopes:
        return PredicateResult(
            predicate=PredicateName.TYPE_TEMPORAL,
            status=PredicateStatus.NOT_APPLICABLE,
            reason_codes=("no_temporal_evidence",),
            detail="claim cites no evidence carrying two-axis temporal metadata",
        )
    cohort = _cohort(envelopes)
    fail_reasons: list[str] = []
    unknown_reasons: list[str] = []
    for env in envelopes:
        verdict, reason = is_admissible(env, scope, cohort=cohort)
        if verdict is False:
            fail_reasons.append(f"{env.evidence_id}:{reason}")
        elif verdict is None:
            unknown_reasons.append(f"{env.evidence_id}:{reason}")
    if fail_reasons:
        # Surface leakage first (the hardest failure), then other reasons.
        leak = [r for r in fail_reasons if "future_information_leakage" in r]
        code = "future_information_leakage" if leak else "temporal_inadmissible"
        return PredicateResult(
            predicate=PredicateName.TYPE_TEMPORAL,
            status=PredicateStatus.FAIL,
            reason_codes=(code,),
            detail="; ".join(fail_reasons),
        )
    if unknown_reasons:
        return PredicateResult(
            predicate=PredicateName.TYPE_TEMPORAL,
            status=PredicateStatus.UNKNOWN,
            reason_codes=("temporal_availability_unresolved",),
            detail="; ".join(unknown_reasons),
        )
    return PredicateResult(
        predicate=PredicateName.TYPE_TEMPORAL,
        status=PredicateStatus.PASS,
        reason_codes=("bitemporally_admissible",),
        detail=f"all {len(envelopes)} supporting item(s) valid at t_v and knowable at t_k",
    )
