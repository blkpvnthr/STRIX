"""Tests for R-N6: institutional admissibility, policy precedence, federation,
noninterference, and computation-backed entity binding (DTEC-R-N6-BIND)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from strix.evidence_graph.graph import EvidenceGraph
from strix.evidence_graph.nodes import (
    Assertion,
    PredicateName,
    PredicateStatus,
    make_candidate_claim,
    make_source_observation,
)
from strix.institutional.admissibility import (
    InstitutionalContext,
    InstitutionalLabel,
    assess_institutional,
    institution_admissible_ids,
)
from strix.institutional.applicability import (
    assess_entity_binding,
    noninterference_holds,
    project_observable,
    states_equivalent_for,
)
from strix.institutional.federation import FederationPolicy, project_federation
from strix.institutional.policy_reasoner import PolicyPrecedence
from strix.native.backends.python_reference import PythonReferenceBackend

KNOWN = datetime(2024, 1, 1, tzinfo=UTC)


def _ctx(**kw) -> InstitutionalContext:
    base: dict = {
        "organization": "ORG-A", "user": "u1", "role": "analyst", "project": "P1",
        "jurisdiction": "US", "authorized_organizations": ("ORG-A",),
        "authorized_access_levels": ("public", "internal"),
        "authorized_jurisdictions": ("US",), "authorized_projects": ("P1",),
    }
    base.update(kw)
    return InstitutionalContext(**base)  # type: ignore[arg-type]


def _label(eid="E1", org="ORG-A", access="internal", jur="US", project="P1") -> InstitutionalLabel:
    return InstitutionalLabel(
        evidence_id=eid, organization=org, access_level=access, jurisdiction=jur, project=project
    )


# --------------------------------------------------------------------------
# A_inst
# --------------------------------------------------------------------------


def test_ainst_pass_when_all_dims_authorized() -> None:
    res = assess_institutional(_label(), _ctx())
    assert res.status is PredicateStatus.PASS
    assert res.predicate is PredicateName.INSTITUTIONAL


def test_ainst_fail_on_unauthorized_org() -> None:
    res = assess_institutional(_label(org="ORG-X"), _ctx())
    assert res.status is PredicateStatus.FAIL
    assert "org_not_applicable" in res.reason_codes


def test_ainst_fail_on_unauthorized_access() -> None:
    res = assess_institutional(_label(access="secret"), _ctx())
    assert res.status is PredicateStatus.FAIL


def test_ainst_unknown_on_missing_label() -> None:
    assert assess_institutional(None, _ctx()).status is PredicateStatus.UNKNOWN


def test_ainst_unknown_on_empty_field() -> None:
    assert assess_institutional(_label(jur=""), _ctx()).status is PredicateStatus.UNKNOWN


def test_scoped_ids_filters() -> None:
    labels = (_label("A"), _label("B", org="ORG-X"), _label("C", project="P9"))
    assert institution_admissible_ids(labels, _ctx()) == frozenset({"A"})


# --------------------------------------------------------------------------
# Policy precedence
# --------------------------------------------------------------------------


def test_precedence_unique_maximum() -> None:
    # low <= high: high takes precedence.
    p = PolicyPrecedence(policies=("low", "high"), relations=(("low", "high"),))
    r = p.resolve(frozenset({"low", "high"}))
    assert r.status == "resolved" and r.resolved == "high"


def test_precedence_transitive() -> None:
    p = PolicyPrecedence(policies=("a", "b", "c"), relations=(("a", "b"), ("b", "c")))
    r = p.resolve(frozenset({"a", "b", "c"}))
    assert r.resolved == "c"


def test_precedence_conflict_fails_closed() -> None:
    # Two incomparable policies -> conflict -> deny.
    p = PolicyPrecedence(policies=("x", "y"))
    r = p.resolve(frozenset({"x", "y"}))
    assert r.resolved is None and r.status == "conflict"


def test_precedence_empty_fails_closed() -> None:
    p = PolicyPrecedence(policies=("x",))
    assert p.resolve(frozenset()).status == "empty"


def test_precedence_cycle_fails_closed() -> None:
    p = PolicyPrecedence(policies=("a", "b"), relations=(("a", "b"), ("b", "a")))
    r = p.resolve(frozenset({"a", "b"}))
    assert r.resolved is None and r.status == "cyclic"


# --------------------------------------------------------------------------
# Federation
# --------------------------------------------------------------------------


def test_federation_transfers_only_authorized() -> None:
    res = project_federation(
        frozenset({"n1", "n2", "n3"}), frozenset(), FederationPolicy(transferable_ids=("n1", "n2"))
    )
    assert res.authorized and set(res.node_ids) == {"n1", "n2"}


def test_federation_edge_requires_both_endpoints() -> None:
    res = project_federation(
        frozenset({"n1", "n2"}),
        frozenset({("n1", "n2"), ("n1", "n3")}),
        FederationPolicy(transferable_ids=("n1", "n2")),
    )
    assert ("n1", "n2") in res.edges
    assert ("n1", "n3") not in res.edges  # n3 not authorized -> edge dropped


def test_federation_composition_leakage_fails_closed() -> None:
    res = project_federation(
        frozenset({"a", "b"}),
        frozenset(),
        FederationPolicy(transferable_ids=("a", "b"), forbidden_joint=(("a", "b"),)),
    )
    assert not res.authorized and res.node_ids == ()


# --------------------------------------------------------------------------
# Noninterference
# --------------------------------------------------------------------------


def test_project_observable() -> None:
    assert project_observable({"a": 1, "b": 2}, frozenset({"a"})) == {"a": 1}


def test_noninterference_holds_when_output_independent_of_secret() -> None:
    acc = frozenset({"pub"})
    s1 = {"pub": 1, "secret": 10}
    s2 = {"pub": 1, "secret": 99}  # j-equivalent (same pub), differ only in secret
    # Response depends only on pub -> j-observable identical.
    assert noninterference_holds(s1, s2, acc, lambda s: {"pub": s["pub"]})


def test_noninterference_violated_when_output_leaks_secret() -> None:
    acc = frozenset({"pub"})
    s1 = {"pub": 1, "secret": 10}
    s2 = {"pub": 1, "secret": 99}
    # Response leaks the secret into the observable channel -> violation.
    assert not noninterference_holds(s1, s2, acc, lambda s: {"pub": s["secret"]})


def test_states_equivalent_for() -> None:
    assert states_equivalent_for({"a": 1, "b": 2}, {"a": 1, "b": 9}, frozenset({"a"}))
    assert not states_equivalent_for({"a": 1}, {"a": 2}, frozenset({"a"}))


# --------------------------------------------------------------------------
# DTEC-R-N6-BIND — computation-backed entity binding
# --------------------------------------------------------------------------


def _obs(subject: str):
    return make_source_observation(
        subject_id=subject, concept="revenue", value=Decimal("100"), unit="usd",
        observation_period="FY2023", observed_at=KNOWN, source_artifact_id="ART-1",
        source_locator="/0",
    )


def _comp_from(obs_ids: tuple[str, ...]):
    backend = PythonReferenceBackend()
    return backend.run(
        "mean", {"series": [Decimal("100"), Decimal("200")]}, input_observation_ids=obs_ids
    )


def test_binding_never_passes_on_untrusted_provenance() -> None:
    # Even when the claimed subject matches a (trusted-looking) input observation, binding
    # abstains — untrusted, non-value-bound provenance can never CONFIRM the entity (an
    # any-match PASS would be spoofable). PASS is reserved for value-bound provenance.
    obs = _obs("ACME")
    comp = _comp_from((obs.observation_id,))
    graph = EvidenceGraph()
    graph.add_node(obs)
    graph.add_node(comp)
    claim = make_candidate_claim(
        subject_id="ACME", claim_type="revenue", statement="ACME revenue.",
        evidence_ids=(comp.computation_id,),
        assertions=(Assertion(metric="revenue", asserted_value=Decimal("150"), unit="usd",
                              evidence_id=comp.computation_id),),
    )
    res = assess_entity_binding(claim, graph)
    assert res.status is PredicateStatus.UNKNOWN
    assert res.status is not PredicateStatus.PASS


def test_binding_decoy_added_observation_does_not_pass() -> None:
    # Attacker lists a decoy EVILCORP observation (plus the real ACME one) and claims
    # EVILCORP. Any-match would PASS; the sound predicate must NOT PASS (abstains).
    real = _obs("ACME")
    decoy = _obs("EVILCORP")
    comp = _comp_from((real.observation_id, decoy.observation_id))
    graph = EvidenceGraph()
    graph.add_node(real)
    graph.add_node(decoy)
    graph.add_node(comp)
    claim = make_candidate_claim(
        subject_id="EVILCORP", claim_type="revenue", statement="EVILCORP revenue.",
        evidence_ids=(comp.computation_id,),
        assertions=(Assertion(metric="revenue", asserted_value=Decimal("150"), unit="usd",
                              evidence_id=comp.computation_id),),
    )
    assert assess_entity_binding(claim, graph).status is not PredicateStatus.PASS


def test_binding_decoy_replaced_observation_does_not_pass() -> None:
    # Only a decoy EVILCORP observation listed; claim EVILCORP. Still never PASS.
    decoy = _obs("EVILCORP")
    comp = _comp_from((decoy.observation_id,))
    graph = EvidenceGraph()
    graph.add_node(decoy)
    graph.add_node(comp)
    claim = make_candidate_claim(
        subject_id="EVILCORP", claim_type="revenue", statement="EVILCORP revenue.",
        evidence_ids=(comp.computation_id,),
        assertions=(Assertion(metric="revenue", asserted_value=Decimal("150"), unit="usd",
                              evidence_id=comp.computation_id),),
    )
    assert assess_entity_binding(claim, graph).status is not PredicateStatus.PASS


def test_binding_fail_on_entity_mismatch_closes_relabel() -> None:
    # The EVILCORP-style relabel: cite a computation about ACME but claim EVILCORP.
    obs = _obs("ACME")
    comp = _comp_from((obs.observation_id,))
    graph = EvidenceGraph()
    graph.add_node(obs)
    graph.add_node(comp)
    claim = make_candidate_claim(
        subject_id="EVILCORP", claim_type="revenue", statement="EVILCORP revenue.",
        evidence_ids=(comp.computation_id,),
        assertions=(Assertion(metric="revenue", asserted_value=Decimal("150"), unit="usd",
                              evidence_id=comp.computation_id),),
    )
    res = assess_entity_binding(claim, graph)
    assert res.status is PredicateStatus.FAIL
    assert "computation_entity_mismatch" in res.reason_codes


def test_binding_unknown_when_no_input_observations() -> None:
    comp = _comp_from(())  # no input observations -> entity cannot be established
    graph = EvidenceGraph()
    graph.add_node(comp)
    claim = make_candidate_claim(
        subject_id="ACME", claim_type="revenue", statement="x",
        evidence_ids=(comp.computation_id,),
        assertions=(Assertion(metric="revenue", asserted_value=Decimal("150"), unit="usd",
                              evidence_id=comp.computation_id),),
    )
    assert assess_entity_binding(claim, graph).status is PredicateStatus.UNKNOWN


def test_binding_not_applicable_without_computation_citation() -> None:
    obs = _obs("ACME")
    graph = EvidenceGraph()
    graph.add_node(obs)
    claim = make_candidate_claim(
        subject_id="ACME", claim_type="revenue", statement="x",
        evidence_ids=(obs.observation_id,),
        assertions=(Assertion(metric="revenue", asserted_value=Decimal("100"), unit="usd",
                              evidence_id=obs.observation_id),),
    )
    assert assess_entity_binding(claim, graph).status is PredicateStatus.NOT_APPLICABLE
