"""Tests for evidence dependency intelligence (R-N1): N_eff, bounds, and A_ind.

Covers the reference estimator, the effective-independent-count arithmetic, the
conservative-bound admission predicate, and — via Hypothesis property tests — the
mathematical invariants that are *proved* in the confidential companion
(``mathematical-invariants.md`` INV-N1-1/2/3). A passing property test is corroborating
evidence for the proof, not the proof itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from strix.evidence_graph.dependency import (
    DependencyPolicy,
    assess_independence,
    conservative_effective_bounds,
    effective_independent_count,
    estimate_dependence,
)
from strix.evidence_graph.graph import EvidenceGraph
from strix.evidence_graph.nodes import (
    PredicateName,
    PredicateStatus,
    RelationshipKind,
    make_candidate_claim,
    make_edge,
    make_source_observation,
)
from strix.models import SourceArtifact, SourceType
from strix.native.arithmetic import NumericalContractError

KNOWN = datetime(2024, 1, 1, tzinfo=UTC)
HEX64 = "a" * 64


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------


def _hash_for(seed: str) -> str:
    """A distinct 64-hex content hash per seed (distinct documents hash differently)."""
    import hashlib

    return hashlib.sha256(seed.encode()).hexdigest()


def _artifact(artifact_id: str, *, content_hash: str | None = None) -> SourceArtifact:
    return SourceArtifact(
        artifact_id=artifact_id,
        source_type=SourceType.SYNTHETIC_FIXTURE,
        source_name=f"{artifact_id}.json",
        source_version="v1",
        content_hash=content_hash or _hash_for(artifact_id),
        known_at=KNOWN,
        local_path=f"raw/{artifact_id}.json",
        byte_size=100,
    )


def _obs(*, artifact_id: str, value: Decimal = Decimal("0.25"), concept: str = "operating_margin"):
    return make_source_observation(
        subject_id="SUBJ-1",
        concept=concept,
        value=value,
        unit="ratio",
        observation_period="FY2023",
        observed_at=KNOWN,
        available_at=KNOWN,
        source_artifact_id=artifact_id,
        source_locator="/facts/0",
    )


def _graph(*observations) -> EvidenceGraph:
    graph = EvidenceGraph()
    seen_artifacts: set[str] = set()
    for obs in observations:
        if obs.source_artifact_id not in seen_artifacts:
            graph.add_node(_artifact(obs.source_artifact_id))
            seen_artifacts.add(obs.source_artifact_id)
        graph.add_node(obs)
    return graph


def _claim(evidence_ids: tuple[str, ...]):
    return make_candidate_claim(
        subject_id="SUBJ-1",
        claim_type="profitability",
        statement="Operating margin was 25%.",
        evidence_ids=evidence_ids,
        assertions=(),
    )


def _policy(theta: str, **kw) -> DependencyPolicy:
    return DependencyPolicy(min_effective_independent=Decimal(theta), **kw)


# --------------------------------------------------------------------------
# N_eff arithmetic (unit)
# --------------------------------------------------------------------------


def test_two_independent_items_give_neff_two() -> None:
    w = (Fraction(1), Fraction(1))
    identity = [[Fraction(1), Fraction(0)], [Fraction(0), Fraction(1)]]
    assert effective_independent_count(w, identity) == Fraction(2)


def test_fully_dependent_items_give_neff_one() -> None:
    w = (Fraction(1), Fraction(1))
    ones = [[Fraction(1), Fraction(1)], [Fraction(1), Fraction(1)]]
    assert effective_independent_count(w, ones) == Fraction(1)


def test_uniform_rho_closed_form() -> None:
    # N_eff = n / (1 + (n-1)rho); n=10, rho=0.6 → 10/6.4 = 1.5625.
    n, rho = 10, Fraction(6, 10)
    w = tuple(Fraction(1) for _ in range(n))
    matrix = [[Fraction(1) if i == j else rho for j in range(n)] for i in range(n)]
    expected = Fraction(n) / (1 + (n - 1) * rho)
    assert effective_independent_count(w, matrix) == expected
    assert expected == Fraction(10, 1) / Fraction(64, 10)  # 1.5625


def test_zero_weight_vector_raises() -> None:
    identity = [[Fraction(1), Fraction(0)], [Fraction(0), Fraction(1)]]
    with pytest.raises(ValueError, match="nonzero weight"):
        effective_independent_count((Fraction(0), Fraction(0)), identity)


# --------------------------------------------------------------------------
# Structural estimator (unit)
# --------------------------------------------------------------------------


def test_same_artifact_is_fully_dependent() -> None:
    a = _obs(artifact_id="ART-1")
    b = _obs(artifact_id="ART-1", value=Decimal("0.30"))  # same origin, different value
    graph = _graph(a, b)
    est = estimate_dependence(graph, a.observation_id, b.observation_id)
    assert est.resolved and est.lower == est.upper == Fraction(1)
    assert "shared_origin" in est.signals


def test_distinct_artifacts_are_independent() -> None:
    a = _obs(artifact_id="ART-1")
    b = _obs(artifact_id="ART-2", value=Decimal("0.30"))
    graph = _graph(a, b)
    est = estimate_dependence(graph, a.observation_id, b.observation_id)
    assert est.resolved and est.lower == est.upper == Fraction(0)


def test_semantic_duplicate_across_artifacts_is_dependent() -> None:
    # Same (subject, concept, unit, value) restated from a different artifact.
    a = _obs(artifact_id="ART-1", value=Decimal("0.25"))
    b = _obs(artifact_id="ART-2", value=Decimal("0.25"))
    graph = _graph(a, b)
    est = estimate_dependence(graph, a.observation_id, b.observation_id)
    assert est.lower == est.upper == Fraction(1)
    assert "semantic_duplicate" in est.signals


def test_unresolved_item_widens_interval() -> None:
    a = _obs(artifact_id="ART-1")
    graph = _graph(a)
    est = estimate_dependence(graph, a.observation_id, "MISSING-OBS")
    assert not est.resolved
    assert est.lower == Fraction(0) and est.upper == Fraction(1)
    assert "unresolved_provenance" in est.signals


# --------------------------------------------------------------------------
# A_ind predicate (unit)
# --------------------------------------------------------------------------


def test_aind_pass_on_independent_evidence() -> None:
    a, b = _obs(artifact_id="ART-1"), _obs(artifact_id="ART-2", value=Decimal("0.30"))
    graph = _graph(a, b)
    claim = _claim((a.observation_id, b.observation_id))
    out = assess_independence(claim, graph, _policy("2"))
    assert out.result.status is PredicateStatus.PASS
    assert out.result.predicate is PredicateName.INDEPENDENCE
    assert out.effective_independent_lower == Decimal("2.000000000000")


def test_aind_fail_on_artificial_corroboration() -> None:
    # Ten restatements of the same fact from distinct artifacts: N_eff = 1 < θ=2.
    obs = [_obs(artifact_id=f"ART-{i}", value=Decimal("0.25")) for i in range(10)]
    graph = _graph(*obs)
    claim = _claim(tuple(o.observation_id for o in obs))
    out = assess_independence(claim, graph, _policy("2"))
    assert out.result.status is PredicateStatus.FAIL
    assert out.result.reason_codes == ("insufficient_independent_evidence",)
    assert out.effective_independent_upper == Decimal("1.000000000000")


def test_aind_unknown_on_unresolved_intermediate() -> None:
    # One resolved item + one missing item, θ between the conservative and optimistic bounds.
    a = _obs(artifact_id="ART-1")
    graph = _graph(a)
    claim = _claim((a.observation_id, "MISSING-OBS"))
    out = assess_independence(claim, graph, _policy("1.5"))
    # upper bound (independent) → N̄_eff = 2 ≥ 1.5; lower bound (dependent) → N̲_eff = 1 < 1.5
    assert out.result.status is PredicateStatus.UNKNOWN
    assert out.result.reason_codes == ("unresolved_independence",)


def test_aind_not_applicable_when_not_required() -> None:
    a = _obs(artifact_id="ART-1")
    graph = _graph(a)
    claim = _claim((a.observation_id,))
    out = assess_independence(claim, graph, _policy("2", require_independent_evidence=False))
    assert out.result.status is PredicateStatus.NOT_APPLICABLE


def test_aind_fail_on_empty_evidence() -> None:
    out = assess_independence(_claim(()), EvidenceGraph(), _policy("1"))
    assert out.result.status is PredicateStatus.FAIL
    assert out.result.reason_codes == ("empty_evidence",)


def test_aind_primary_record_exception_requires_validation() -> None:
    # The exception fires only for VALIDATED evidence tracing to a real, authorized
    # primary artifact node.
    a = _obs(artifact_id="ART-PRIMARY")
    graph = _graph(a)  # adds a real SourceArtifact node ART-PRIMARY
    claim = _claim((a.observation_id,))
    policy = _policy("5", primary_record_artifact_ids=("ART-PRIMARY",))
    out = assess_independence(
        claim, graph, policy, validated_evidence_ids=frozenset({a.observation_id})
    )
    assert out.result.status is PredicateStatus.PASS
    assert out.result.reason_codes == ("primary_record_exception",)


def test_aind_primary_exception_fails_closed_without_validation() -> None:
    # Same setup but WITHOUT validated_evidence_ids: the waiver must not fire (point 1).
    a = _obs(artifact_id="ART-PRIMARY")
    graph = _graph(a)
    claim = _claim((a.observation_id,))
    policy = _policy("5", primary_record_artifact_ids=("ART-PRIMARY",))
    out = assess_independence(claim, graph, policy)  # no validation supplied
    assert out.result.status is not PredicateStatus.PASS
    assert out.result.reason_codes != ("primary_record_exception",)


def test_aind_single_item_passes_threshold_one() -> None:
    a = _obs(artifact_id="ART-1")
    graph = _graph(a)
    out = assess_independence(_claim((a.observation_id,)), graph, _policy("1"))
    assert out.result.status is PredicateStatus.PASS


# --------------------------------------------------------------------------
# Property tests — the proved invariants (INV-N1-1/2/3)
# --------------------------------------------------------------------------


def _symmetric_matrix(n: int, off: list[int]) -> list[list[Fraction]]:
    """Build a symmetric unit-diagonal matrix from flat off-diagonal numerators/10."""
    m = [[Fraction(1) if i == j else Fraction(0) for j in range(n)] for i in range(n)]
    k = 0
    for i in range(n):
        for j in range(i + 1, n):
            m[i][j] = m[j][i] = Fraction(off[k], 10)
            k += 1
    return m


@st.composite
def _weights_and_matrix(draw):
    n = draw(st.integers(min_value=1, max_value=6))
    weights = tuple(Fraction(draw(st.integers(min_value=0, max_value=9))) for _ in range(n))
    n_off = n * (n - 1) // 2
    off = draw(st.lists(st.integers(min_value=0, max_value=10), min_size=n_off, max_size=n_off))
    return weights, _symmetric_matrix(n, off)


@settings(max_examples=250)
@given(_weights_and_matrix())
def test_prop1_neff_bounds(data) -> None:
    """INV-N1-1 (Proposition 1): 1 ≤ N_eff ≤ (Σw)²/Σw² ≤ n."""
    weights, matrix = data
    n = len(weights)
    sum_w = sum(weights, Fraction(0))
    if sum_w == 0:
        return  # undefined; handled as insufficiency elsewhere
    neff = effective_independent_count(weights, matrix)
    sum_w2 = sum((w * w for w in weights), Fraction(0))
    middle = sum_w * sum_w / sum_w2
    assert Fraction(1) <= neff <= middle <= Fraction(n)


@settings(max_examples=200)
@given(_weights_and_matrix())
def test_invn1_2_monotone_decreasing_in_dependence(data) -> None:
    """INV-N1-2: raising any off-diagonal dependence cannot increase N_eff."""
    weights, matrix = data
    if sum(weights, Fraction(0)) == 0:
        return
    n = len(weights)
    if n < 2:
        return
    base = effective_independent_count(weights, matrix)
    # Raise every off-diagonal toward 1 (more dependence).
    raised = [[Fraction(1) if i == j else min(Fraction(1), matrix[i][j] + Fraction(1, 10))
               for j in range(n)] for i in range(n)]
    assert effective_independent_count(weights, raised) <= base


@settings(max_examples=200)
@given(_weights_and_matrix())
def test_invn1_3_conservative_ordering(data) -> None:
    """INV-N1-3: N̲_eff ≤ N̄_eff for any lower ⪯ upper dependence box."""
    weights, upper = data
    if sum(weights, Fraction(0)) == 0:
        return
    n = len(weights)
    # lower matrix: half the dependence of upper (still ≤ upper entrywise).
    lower = [[Fraction(1) if i == j else upper[i][j] / 2 for j in range(n)] for i in range(n)]
    lo, hi = conservative_effective_bounds(weights, lower, upper)
    assert lo <= hi


# --------------------------------------------------------------------------
# Adversarial / trust-boundary regressions (independent-review remediation)
# Each guards a confirmed defect: C1 (spoofable exception), M1 (scale evasion),
# M2 (fabricated-origin false independence), plus points 1/3/5/7 hardening.
# --------------------------------------------------------------------------


def test_C1_spoofed_primary_id_without_node_does_not_pass() -> None:
    # Observation merely CLAIMS a primary artifact id; no SourceArtifact node exists.
    a = _obs(artifact_id="SEC-PRIMARY-10K")
    graph = EvidenceGraph()
    graph.add_node(a)  # NOTE: no artifact node added
    claim = _claim((a.observation_id,))
    policy = _policy("5", primary_record_artifact_ids=("SEC-PRIMARY-10K",))
    out = assess_independence(
        claim, graph, policy, validated_evidence_ids=frozenset({a.observation_id})
    )
    assert out.result.status is PredicateStatus.FAIL
    assert out.result.reason_codes != ("primary_record_exception",)


def test_C1_primary_exception_requires_evidence_in_validated_set() -> None:
    a = _obs(artifact_id="ART-PRIMARY")
    graph = _graph(a)
    claim = _claim((a.observation_id,))
    policy = _policy("5", primary_record_artifact_ids=("ART-PRIMARY",))
    # Validated set is some OTHER id — the cited evidence is not validated.
    out = assess_independence(
        claim, graph, policy, validated_evidence_ids=frozenset({"SOME-OTHER-ID"})
    )
    assert out.result.reason_codes != ("primary_record_exception",)


def test_M1_scale_variant_duplicate_is_dependent() -> None:
    # 0.25 vs 0.250 are the same fact; must be scored fully dependent (canonical Decimal).
    a = _obs(artifact_id="ART-1", value=Decimal("0.25"))
    b = _obs(artifact_id="ART-2", value=Decimal("0.250"))
    graph = _graph(a, b)
    est = estimate_dependence(graph, a.observation_id, b.observation_id)
    assert est.lower == est.upper == Fraction(1)
    claim = _claim((a.observation_id, b.observation_id))
    out = assess_independence(claim, graph, _policy("2"))
    assert out.result.status is PredicateStatus.FAIL  # N_eff = 1 < 2


def test_M2_fabricated_distinct_origins_are_uncertain_not_independent() -> None:
    # Two observations declaring DISTINCT but non-existent artifact ids (fabricated).
    a = _obs(artifact_id="FAKE-A", value=Decimal("0.25"))
    b = _obs(artifact_id="FAKE-B", value=Decimal("0.30"))
    graph = EvidenceGraph()
    graph.add_node(a)
    graph.add_node(b)  # no artifact nodes exist
    est = estimate_dependence(graph, a.observation_id, b.observation_id)
    assert not est.resolved and est.lower == Fraction(0) and est.upper == Fraction(1)
    claim = _claim((a.observation_id, b.observation_id))
    out = assess_independence(claim, graph, _policy("2"))
    # Cannot infer independence from distinct fabricated identifiers → not PASS.
    assert out.result.status is not PredicateStatus.PASS


def test_identity_spoofing_declared_id_points_to_non_artifact() -> None:
    # Observation 'a' declares a source_artifact_id that resolves to ANOTHER observation,
    # not a SourceArtifact. It must not count as a trusted origin.
    decoy = _obs(artifact_id="ART-REAL", value=Decimal("0.99"))
    graph = _graph(decoy)  # ART-REAL artifact + decoy obs exist
    spoof = _obs(artifact_id=decoy.observation_id, value=Decimal("0.25"))  # points at an OBS id
    graph.add_node(spoof)
    arts = estimate_dependence(graph, spoof.observation_id, decoy.observation_id)
    # spoof's declared "artifact" is an observation, not a SourceArtifact → unresolved origin.
    assert not arts.resolved


def test_circular_provenance_abstains() -> None:
    a = _obs(artifact_id="ART-1", value=Decimal("0.25"))
    b = _obs(artifact_id="ART-2", value=Decimal("0.30"))
    graph = _graph(a, b)
    graph.add_edge(make_edge(RelationshipKind.DERIVED_FROM, a.observation_id, b.observation_id))
    graph.add_edge(make_edge(RelationshipKind.DERIVED_FROM, b.observation_id, a.observation_id))
    claim = _claim((a.observation_id, b.observation_id))
    out = assess_independence(claim, graph, _policy("2"))
    assert out.result.status is PredicateStatus.UNKNOWN
    assert out.result.reason_codes == ("circular_provenance",)


def test_shared_upstream_ancestor_is_dependent() -> None:
    # Two observations with distinct direct artifacts but a SHARED upstream artifact.
    common = SourceArtifact(
        artifact_id="ART-COMMON", source_type=SourceType.SYNTHETIC_FIXTURE,
        source_name="common.json", source_version="v1", content_hash=HEX64,
        known_at=KNOWN, local_path="raw/common.json", byte_size=100,
    )
    a = _obs(artifact_id="ART-1", value=Decimal("0.25"))
    b = _obs(artifact_id="ART-2", value=Decimal("0.30"))
    graph = _graph(a, b)
    graph.add_node(common)
    # Both direct artifacts derive from the common upstream artifact.
    graph.add_edge(make_edge(RelationshipKind.DERIVED_FROM, a.observation_id, "ART-COMMON"))
    graph.add_edge(make_edge(RelationshipKind.DERIVED_FROM, b.observation_id, "ART-COMMON"))
    est = estimate_dependence(graph, a.observation_id, b.observation_id)
    assert est.lower > Fraction(0)  # shared upstream ⇒ not independent


def test_float_weight_rejected() -> None:
    a, b = _obs(artifact_id="ART-1"), _obs(artifact_id="ART-2", value=Decimal("0.30"))
    graph = _graph(a, b)
    claim = _claim((a.observation_id, b.observation_id))
    with pytest.raises(NumericalContractError):
        assess_independence(claim, graph, _policy("2"), weights={a.observation_id: 0.1})  # type: ignore[dict-item]


def test_negative_weight_rejected_in_count() -> None:
    identity = [[Fraction(1), Fraction(0)], [Fraction(0), Fraction(1)]]
    with pytest.raises(ValueError, match="nonnegative"):
        effective_independent_count((Fraction(1), Fraction(-3)), identity)


def test_malformed_matrix_rejected() -> None:
    # Non-symmetric matrix.
    bad = [[Fraction(1), Fraction(1)], [Fraction(0), Fraction(1)]]
    with pytest.raises(ValueError, match="symmetric"):
        effective_independent_count((Fraction(1), Fraction(1)), bad)
    # Diagonal not 1.
    bad_diag = [[Fraction(1, 2), Fraction(0)], [Fraction(0), Fraction(1)]]
    with pytest.raises(ValueError, match="diagonal"):
        effective_independent_count((Fraction(1), Fraction(1)), bad_diag)
    # Out of range.
    bad_range = [[Fraction(1), Fraction(2)], [Fraction(2), Fraction(1)]]
    with pytest.raises(ValueError, match="outside"):
        effective_independent_count((Fraction(1), Fraction(1)), bad_range)


def test_distinct_real_artifacts_remain_independent() -> None:
    # The legitimate case must still pass: two genuinely distinct trusted artifacts.
    a = _obs(artifact_id="ART-1", value=Decimal("0.25"))
    b = _obs(artifact_id="ART-2", value=Decimal("0.30"))
    graph = _graph(a, b)
    out = assess_independence(_claim((a.observation_id, b.observation_id)), graph, _policy("2"))
    assert out.result.status is PredicateStatus.PASS


@settings(max_examples=150)
@given(
    st.integers(min_value=2, max_value=6),
    st.integers(min_value=0, max_value=9),
    st.integers(min_value=0, max_value=9),
)
def test_invn1_2_coordinatewise_monotone(n: int, i_sel: int, j_sel: int) -> None:
    """INV-N1-2 coordinate-wise: raising a SINGLE off-diagonal cannot increase N_eff."""
    weights = tuple(Fraction(1) for _ in range(n))
    base = [[Fraction(1) if i == j else Fraction(2, 10) for j in range(n)] for i in range(n)]
    i, j = i_sel % n, j_sel % n
    if i == j:
        return
    before = effective_independent_count(weights, base)
    base[i][j] = base[j][i] = Fraction(9, 10)  # raise one pair only
    after = effective_independent_count(weights, base)
    assert after <= before


def test_finding1_ancestor_descendant_pair_is_dependent() -> None:
    # 'a' is DERIVED_FROM 'b' (b is a's provenance ancestor): not independent corroborators.
    a = _obs(artifact_id="ART-1", value=Decimal("0.30"))
    b = _obs(artifact_id="ART-2", value=Decimal("0.25"))
    graph = _graph(a, b)
    graph.add_edge(make_edge(RelationshipKind.DERIVED_FROM, a.observation_id, b.observation_id))
    est = estimate_dependence(graph, a.observation_id, b.observation_id)
    assert est.lower == est.upper == Fraction(1)
    assert est.signals == ("lineage_dependence",)
    out = assess_independence(_claim((a.observation_id, b.observation_id)), graph, _policy("2"))
    assert out.result.status is not PredicateStatus.PASS


def test_finding2_duplicate_document_distinct_ids_is_dependent() -> None:
    # Same source document ingested twice under different artifact_ids (identical hash).
    dup_hash = _hash_for("THE-DOC")
    art_a = _artifact("ART-A", content_hash=dup_hash)
    art_b = _artifact("ART-B", content_hash=dup_hash)
    a = _obs(artifact_id="ART-A", value=Decimal("0.25"), concept="operating_margin")
    b = _obs(artifact_id="ART-B", value=Decimal("1000"), concept="revenue")
    graph = EvidenceGraph()
    graph.add_node(art_a)
    graph.add_node(art_b)
    graph.add_node(a)
    graph.add_node(b)
    est = estimate_dependence(graph, a.observation_id, b.observation_id)
    assert est.lower > Fraction(0)  # one duplicated source -> not independent
    out = assess_independence(_claim((a.observation_id, b.observation_id)), graph, _policy("2"))
    assert out.result.status is not PredicateStatus.PASS
