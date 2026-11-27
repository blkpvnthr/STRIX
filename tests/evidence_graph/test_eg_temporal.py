"""Tests for bitemporal evidence reasoning (R-N2): two-axis admissibility + leak-freedom.

Unit tests for the interval algebra, the extended type/temporal predicate, revision
handling, and contradiction; Hypothesis property tests for the leak-freedom invariant
(INV-N2-1) and half-open interval membership. A passing property test corroborates the
proof; it is not the proof.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from strix.evidence_graph.nodes import PredicateName, PredicateStatus, TemporalMode
from strix.evidence_graph.temporal import (
    TemporalEnvelope,
    TemporalInterval,
    TemporalScope,
    admissible_evidence_ids,
    assess_bitemporal,
    is_admissible,
    temporal_contradiction,
    temporal_leakage,
)

BASE = datetime(2024, 1, 1, tzinfo=UTC)


def _t(hours: int) -> datetime:
    return BASE + timedelta(hours=hours)


def _env(
    eid: str = "E1",
    *,
    v: tuple[int | None, int | None] = (0, 100),
    k: tuple[int | None, int | None] = (0, 100),
    available: int | None = 0,
    retracted: int | None = None,
    superseded_by: str | None = None,
) -> TemporalEnvelope:
    return TemporalEnvelope(
        evidence_id=eid,
        validity=TemporalInterval(
            start=None if v[0] is None else _t(v[0]),
            end=None if v[1] is None else _t(v[1]),
        ),
        knowledge=TemporalInterval(
            start=None if k[0] is None else _t(k[0]),
            end=None if k[1] is None else _t(k[1]),
        ),
        available_at=None if available is None else _t(available),
        retracted_at=None if retracted is None else _t(retracted),
        superseded_by=superseded_by,
    )


def _scope(tv: int = 50, tk: int = 50, mode: TemporalMode = TemporalMode.POINT_IN_TIME):
    return TemporalScope(valid_time=_t(tv), knowledge_time=_t(tk), mode=mode)


# --------------------------------------------------------------------------
# Interval algebra (unit)
# --------------------------------------------------------------------------


def test_half_open_membership() -> None:
    iv = TemporalInterval(start=_t(10), end=_t(20))
    assert iv.contains(_t(10))  # start is inclusive
    assert iv.contains(_t(19))
    assert not iv.contains(_t(20))  # end is exclusive
    assert not iv.contains(_t(9))


def test_unbounded_interval() -> None:
    assert TemporalInterval().contains(_t(0))
    assert TemporalInterval(start=_t(5)).contains(_t(1_000))
    assert not TemporalInterval(start=_t(5)).contains(_t(4))


def test_adjacent_intervals_do_not_overlap() -> None:
    a = TemporalInterval(start=_t(0), end=_t(10))
    b = TemporalInterval(start=_t(10), end=_t(20))
    assert not a.overlaps(b) and not b.overlaps(a)


def test_overlapping_intervals() -> None:
    a = TemporalInterval(start=_t(0), end=_t(15))
    b = TemporalInterval(start=_t(10), end=_t(20))
    assert a.overlaps(b) and b.overlaps(a)


# --------------------------------------------------------------------------
# is_admissible (unit)
# --------------------------------------------------------------------------


def test_admissible_when_valid_and_known() -> None:
    assert is_admissible(_env(available=10), _scope(tv=50, tk=50)) == (True, "admissible")


def test_future_information_leakage_blocked() -> None:
    # available_at (60) after knowledge_time (50): leak, even with an early knowledge interval.
    verdict, reason = is_admissible(_env(available=60, k=(0, 100)), _scope(tk=50))
    assert verdict is False and reason == "future_information_leakage"


def test_backdated_wrapper_cannot_hide_late_availability() -> None:
    # Forged early knowledge interval [0,100) but true availability is 70 > t_k=50.
    verdict, reason = is_admissible(_env(available=70, k=(0, 100)), _scope(tk=50))
    assert verdict is False and reason == "future_information_leakage"


def test_unresolved_availability_is_unknown() -> None:
    assert is_admissible(_env(available=None), _scope())[0] is None


def test_known_retraction_blocks() -> None:
    verdict, reason = is_admissible(_env(available=0, retracted=40), _scope(tk=50))
    assert verdict is False and reason == "retracted_as_of_knowledge_time"


def test_retraction_after_knowledge_time_does_not_block() -> None:
    # Retracted at 60 but we reconstruct at t_k=50: the retraction is not yet known.
    assert is_admissible(_env(available=0, retracted=60), _scope(tk=50))[0] is True


def test_outside_validity_blocked() -> None:
    verdict, reason = is_admissible(_env(v=(0, 30), available=0), _scope(tv=50))
    assert verdict is False and reason == "outside_validity_interval"


def test_point_in_time_enforces_knowledge_interval() -> None:
    verdict, reason = is_admissible(_env(k=(0, 30), available=0), _scope(tk=50))
    assert verdict is False and reason == "outside_knowledge_interval"


def test_retrospective_relaxes_knowledge_interval() -> None:
    # Knowledge interval [0,30) excludes t_k=50, but retrospective mode uses current
    # knowledge; availability (0) <= t_k still enforced, validity still required.
    verdict, _ = is_admissible(
        _env(k=(0, 30), available=0), _scope(tk=50, mode=TemporalMode.RETROSPECTIVE)
    )
    assert verdict is True


# --------------------------------------------------------------------------
# assess_bitemporal predicate (unit)
# --------------------------------------------------------------------------


def test_assess_pass() -> None:
    res = assess_bitemporal((_env("A", available=10), _env("B", available=20)), _scope())
    assert res.status is PredicateStatus.PASS
    assert res.predicate is PredicateName.TYPE_TEMPORAL


def test_assess_fail_on_leak_surfaces_leak_reason() -> None:
    res = assess_bitemporal((_env("A", available=10), _env("B", available=90)), _scope(tk=50))
    assert res.status is PredicateStatus.FAIL
    assert res.reason_codes == ("future_information_leakage",)


def test_assess_unknown_on_unresolved() -> None:
    res = assess_bitemporal((_env("A", available=10), _env("B", available=None)), _scope())
    assert res.status is PredicateStatus.UNKNOWN


def test_assess_not_applicable_when_no_envelopes() -> None:
    res = assess_bitemporal((), _scope())
    assert res.status is PredicateStatus.NOT_APPLICABLE


def test_fail_dominates_unknown() -> None:
    res = assess_bitemporal(
        (_env("A", available=90), _env("B", available=None)), _scope(tk=50)
    )
    assert res.status is PredicateStatus.FAIL


# --------------------------------------------------------------------------
# leakage metric + contradiction (unit)
# --------------------------------------------------------------------------


def test_leakage_zero_on_clean_set() -> None:
    envs = (_env("A", available=10), _env("B", available=20))
    assert temporal_leakage(envs, _scope(tk=50)) == Decimal(0)


def test_leakage_fraction() -> None:
    envs = (_env("A", available=10), _env("B", available=90), _env("C", available=95))
    assert temporal_leakage(envs, _scope(tk=50)) == Decimal("0.666666666667")


def test_contradiction_requires_substance() -> None:
    a = _env("A", v=(0, 20))
    b = _env("B", v=(10, 30))
    assert temporal_contradiction(a, b, substantive=True)
    assert not temporal_contradiction(a, b, substantive=False)  # overlap alone is not conflict


def test_contradiction_requires_overlap() -> None:
    a = _env("A", v=(0, 10))
    b = _env("B", v=(10, 20))  # adjacent, no overlap
    assert not temporal_contradiction(a, b, substantive=True)


# --------------------------------------------------------------------------
# Property tests (INV-N2-1 leak-freedom; interval membership)
# --------------------------------------------------------------------------


@st.composite
def _envelopes_and_scope(draw):
    n = draw(st.integers(min_value=0, max_value=6))
    envs = []
    for i in range(n):
        avail = draw(st.one_of(st.none(), st.integers(min_value=-50, max_value=150)))
        vlo = draw(st.integers(min_value=-50, max_value=60))
        vhi = draw(st.integers(min_value=61, max_value=200))
        klo = draw(st.integers(min_value=-50, max_value=60))
        khi = draw(st.integers(min_value=61, max_value=200))
        envs.append(_env(f"E{i}", v=(vlo, vhi), k=(klo, khi), available=avail))
    tk = draw(st.integers(min_value=0, max_value=100))
    tv = draw(st.integers(min_value=0, max_value=100))
    mode = draw(st.sampled_from(list(TemporalMode)))
    return tuple(envs), _scope(tv=tv, tk=tk, mode=mode)


@settings(max_examples=300)
@given(_envelopes_and_scope())
def test_invn2_1_leak_freedom(data) -> None:
    """INV-N2-1: every admitted envelope has a_i <= t_k; admitted-set leakage is 0."""
    envs, scope = data
    admitted_ids = admissible_evidence_ids(envs, scope)
    admitted = tuple(e for e in envs if e.evidence_id in admitted_ids)
    for e in admitted:
        assert e.available_at is not None
        assert e.available_at <= scope.knowledge_time
    assert temporal_leakage(admitted, scope) == Decimal(0)


@settings(max_examples=200)
@given(
    st.integers(min_value=-20, max_value=20),
    st.integers(min_value=21, max_value=60),
    st.integers(min_value=-40, max_value=80),
)
def test_half_open_membership_property(lo: int, hi: int, t: int) -> None:
    iv = TemporalInterval(start=_t(lo), end=_t(hi))
    assert iv.contains(_t(t)) == (lo <= t < hi)


# --------------------------------------------------------------------------
# Supersession (independent-review finding: known supersession must exclude stale)
# --------------------------------------------------------------------------


def test_known_supersession_excludes_stale_version() -> None:
    # E1 superseded_by E2; E2 is available (30<=t_k=50) so the supersession is known.
    e1 = _env("E1", available=0, superseded_by="E2")
    e2 = _env("E2", available=30, k=(30, 100))
    cohort = {"E1": e1, "E2": e2}
    verdict, reason = is_admissible(e1, _scope(tk=50), cohort=cohort)
    assert verdict is False and reason == "superseded_by_known_revision"
    assert admissible_evidence_ids((e1, e2), _scope(tk=50)) == frozenset({"E2"})


def test_superseded_at_excludes_like_retraction() -> None:
    e1 = TemporalEnvelope(
        evidence_id="E1", validity=TemporalInterval(start=_t(0), end=_t(100)),
        knowledge=TemporalInterval(start=_t(0), end=_t(100)), available_at=_t(0),
        superseded_at=_t(40),
    )
    verdict, reason = is_admissible(e1, _scope(tk=50))
    assert verdict is False and reason == "superseded_as_of_knowledge_time"


def test_supersession_after_knowledge_time_still_admits() -> None:
    e1 = TemporalEnvelope(
        evidence_id="E1", validity=TemporalInterval(start=_t(0), end=_t(100)),
        knowledge=TemporalInterval(start=_t(0), end=_t(100)), available_at=_t(0),
        superseded_at=_t(60),  # not yet known at t_k=50
    )
    assert is_admissible(e1, _scope(tk=50))[0] is True


def test_supersession_unresolved_abstains() -> None:
    # Marked superseded by a revision not in the cohort and no superseded_at -> cannot
    # confirm currency -> abstain (never silently admit a possibly-stale version).
    e1 = _env("E1", available=0, superseded_by="E-UNKNOWN")
    verdict, reason = is_admissible(e1, _scope(tk=50), cohort={"E1": e1})
    assert verdict is None and reason == "supersession_unresolved"


def test_supersession_chain_excludes_all_stale_versions() -> None:
    # E1 -> E2 -> E3 (E3 current). Both E1 and E2 are known-superseded; only E3 admits.
    # Transitive resolution must exclude E1 even though its direct successor E2 is itself
    # superseded (the rev2 immediate-only fix admitted E1 here).
    e1 = _env("E1", available=0, superseded_by="E2")
    e2 = _env("E2", available=0, superseded_by="E3")
    e3 = _env("E3", available=0)
    cohort = {"E1": e1, "E2": e2, "E3": e3}
    assert is_admissible(e1, _scope(tk=50), cohort=cohort)[0] is False
    assert is_admissible(e2, _scope(tk=50), cohort=cohort)[0] is False
    assert is_admissible(e3, _scope(tk=50), cohort=cohort)[0] is True
    assert admissible_evidence_ids((e1, e2, e3), _scope(tk=50)) == frozenset({"E3"})


def test_supersession_chain_unresolved_when_successor_missing() -> None:
    # E1 -> E2 but E2 not in cohort and undated: cannot confirm currency -> abstain.
    e1 = _env("E1", available=0, superseded_by="E2")
    verdict, reason = is_admissible(e1, _scope(tk=50), cohort={"E1": e1})
    assert verdict is None and reason == "supersession_unresolved"


def test_supersession_cycle_never_admits_stale() -> None:
    # E1 -> E2 -> E1 (contradictory cycle): the invariant is that neither stale version is
    # ADMITTED (fail-safe) and there is no infinite loop. Here each is superseded by a
    # base-admissible sibling, so both are excluded.
    e1 = _env("E1", available=0, superseded_by="E2")
    e2 = _env("E2", available=0, superseded_by="E1")
    cohort = {"E1": e1, "E2": e2}
    assert is_admissible(e1, _scope(tk=50), cohort=cohort)[0] is not True
    assert is_admissible(e2, _scope(tk=50), cohort=cohort)[0] is not True


def test_supersession_cycle_with_unavailable_links_abstains() -> None:
    # A cycle where neither sibling is base-admissible (not yet available): the chain
    # cannot confirm a known newer revision -> abstain (UNKNOWN), no infinite loop.
    e1 = _env("E1", available=None, superseded_by="E2")
    e2 = _env("E2", available=None, superseded_by="E1")
    cohort = {"E1": e1, "E2": e2}
    # available None short-circuits to UNKNOWN in the base gate before supersession.
    assert is_admissible(e1, _scope(tk=50), cohort=cohort)[0] is None


def test_supersession_known_regardless_of_correction_query_applicability() -> None:
    # E1 (valid [0,100)) superseded_by E2 whose correction only covers validity [0,40),
    # queried at t_v=50. The supersession IS known (E2 available at 0<=t_k), so E1 must be
    # excluded regardless of E2's validity-at-t_v. (Base-admissibility of E2 would be False
    # here — that was the fail-open.)
    e1 = _env("E1", v=(0, 100), available=0, superseded_by="E2")
    e2 = _env("E2", v=(0, 40), available=0)
    cohort = {"E1": e1, "E2": e2}
    assert is_admissible(e1, _scope(tv=50, tk=50), cohort=cohort)[0] is False


def test_supersession_pointer_and_date_encodings_agree() -> None:
    # Two encodings of ONE real-world supersession must yield the same verdict.
    e1_ptr = _env("E1", v=(0, 100), available=0, superseded_by="E2")
    e2 = _env("E2", v=(0, 40), available=0)  # correction not applicable at t_v=50
    ptr = is_admissible(e1_ptr, _scope(tv=50, tk=50), cohort={"E1": e1_ptr, "E2": e2})[0]
    e1_dated = TemporalEnvelope(
        evidence_id="E1d",
        validity=TemporalInterval(start=_t(0), end=_t(100)),
        knowledge=TemporalInterval(start=_t(0), end=_t(100)),
        available_at=_t(0),
        superseded_at=_t(30),  # same supersession, dated encoding
    )
    dated = is_admissible(e1_dated, _scope(tv=50, tk=50))[0]
    assert ptr is False and dated is False and ptr == dated


def test_supersession_known_regardless_of_correction_pit_knowledge_window() -> None:
    # Successor knowledge interval [0,30) ends before t_k=50, but it was available by t_k,
    # so the supersession is known -> stale E1 excluded (PIT-knowledge variant of the fix).
    e1 = _env("E1", available=0, superseded_by="E2")
    e2 = _env("E2", k=(0, 30), available=0)
    cohort = {"E1": e1, "E2": e2}
    assert is_admissible(e1, _scope(tk=50), cohort=cohort)[0] is False


def test_retracted_correction_does_not_supersede() -> None:
    # If the correction E2 is itself retracted as of t_k, it is not a valid newer revision,
    # so the original E1 stands (admitted) rather than being wrongly excluded.
    e1 = _env("E1", available=0, superseded_by="E2")
    e2 = _env("E2", available=0, retracted=40)  # correction withdrawn before t_k=50
    cohort = {"E1": e1, "E2": e2}
    assert is_admissible(e1, _scope(tk=50), cohort=cohort)[0] is True


def test_not_yet_known_immediate_correction_does_not_supersede_via_deeper() -> None:
    # E1 -> E2(not available until 60) -> E3(available 0); t_k=50. E2's supersession of E1
    # is NOT knowable yet, so E1 must stand even though a deeper revision E3 is available
    # (knowing E3 supersedes E1 would require knowing the not-yet-available E2 link).
    e1 = _env("E1", available=0, superseded_by="E2")
    e2 = _env("E2", available=60, superseded_by="E3")
    e3 = _env("E3", available=0)
    cohort = {"E1": e1, "E2": e2, "E3": e3}
    assert is_admissible(e1, _scope(tk=50), cohort=cohort)[0] is True
    assert admissible_evidence_ids((e1, e2, e3), _scope(tk=50)) == frozenset({"E1", "E3"})


def test_retracted_intermediate_with_onward_chain_leaves_original() -> None:
    # E2 (the direct corrector of E1) is retracted as of t_k, so E1 stands even though a
    # further revision E3 exists — a withdrawn correction does not supersede.
    e1 = _env("E1", available=0, superseded_by="E2")
    e2 = _env("E2", available=0, retracted=40, superseded_by="E3")
    e3 = _env("E3", available=0)
    cohort = {"E1": e1, "E2": e2, "E3": e3}
    assert is_admissible(e1, _scope(tk=50), cohort=cohort)[0] is True
