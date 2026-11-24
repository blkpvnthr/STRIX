"""Tests for the EvidenceGraph container and its operations (R1 §9.3)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.evidence_graph.graph import EvidenceGraph, GraphSnapshot
from strix.evidence_graph.nodes import (
    EvidenceGraphError,
    RelationshipKind,
    SourceObservation,
    make_edge,
    make_source_observation,
)

_OBSERVED_AT = datetime(2024, 1, 1, tzinfo=UTC)


def _obs(concept: str) -> SourceObservation:
    """Build a distinct SourceObservation keyed by *concept*."""
    return make_source_observation(
        subject_id="SUBJ-1",
        concept=concept,
        value=Decimal("1"),
        unit="USD",
        observation_period="2024Q1",
        observed_at=_OBSERVED_AT,
        source_artifact_id="ART-1",
        source_locator="row:1",
    )


def _dag() -> tuple[EvidenceGraph, dict[str, str]]:
    """Return a small DAG and a name->id map.

    Structure (edge = ``child derived_from parent``)::

        A <- B <- D
        A <- C <- D
    """
    a, b, c, d = _obs("A"), _obs("B"), _obs("C"), _obs("D")
    ids = {
        "A": a.observation_id,
        "B": b.observation_id,
        "C": c.observation_id,
        "D": d.observation_id,
    }
    g = EvidenceGraph()
    for node in (a, b, c, d):
        g.add_node(node)
    g.add_edge(make_edge(RelationshipKind.DERIVED_FROM, ids["B"], ids["A"]))
    g.add_edge(make_edge(RelationshipKind.DERIVED_FROM, ids["C"], ids["A"]))
    g.add_edge(make_edge(RelationshipKind.DERIVED_FROM, ids["D"], ids["B"]))
    g.add_edge(make_edge(RelationshipKind.DERIVED_FROM, ids["D"], ids["C"]))
    return g, ids


# --------------------------------------------------------------------------
# Referential integrity
# --------------------------------------------------------------------------


def test_add_edge_rejects_unknown_source() -> None:
    g = EvidenceGraph()
    g.add_node(_obs("A"))
    known = g.node_ids()[0]
    with pytest.raises(EvidenceGraphError):
        g.add_edge(make_edge(RelationshipKind.DERIVED_FROM, "OBS-missing", known))


def test_add_edge_rejects_unknown_target() -> None:
    g = EvidenceGraph()
    g.add_node(_obs("A"))
    known = g.node_ids()[0]
    with pytest.raises(EvidenceGraphError):
        g.add_edge(make_edge(RelationshipKind.DERIVED_FROM, known, "OBS-missing"))


def test_node_missing_raises() -> None:
    g = EvidenceGraph()
    assert g.has_node("OBS-x") is False
    with pytest.raises(EvidenceGraphError):
        g.node("OBS-x")


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------


def test_node_and_has_node() -> None:
    g, ids = _dag()
    assert g.has_node(ids["A"]) is True
    assert g.node(ids["A"]).observation_id == ids["A"]


def test_nodes_by_type() -> None:
    g, _ = _dag()
    obs = g.nodes_by_type(SourceObservation)
    assert len(obs) == 4
    assert all(isinstance(n, SourceObservation) for n in obs)


def test_edges_from_to_and_kind() -> None:
    g, ids = _dag()
    assert {e.target_id for e in g.edges_from(ids["D"])} == {ids["B"], ids["C"]}
    assert {e.source_id for e in g.edges_to(ids["A"])} == {ids["B"], ids["C"]}
    assert len(g.edges_of_kind(RelationshipKind.DERIVED_FROM)) == 4
    assert g.edges_of_kind(RelationshipKind.CONTRADICTED_BY) == ()


# --------------------------------------------------------------------------
# Ancestors / descendants / closure
# --------------------------------------------------------------------------


def test_ancestors() -> None:
    g, ids = _dag()
    assert g.ancestors(ids["D"]) == {ids["A"], ids["B"], ids["C"]}
    assert g.ancestors(ids["A"]) == set()


def test_descendants() -> None:
    g, ids = _dag()
    assert g.descendants(ids["A"]) == {ids["B"], ids["C"], ids["D"]}
    assert g.descendants(ids["D"]) == set()


def test_evidence_closure() -> None:
    g, ids = _dag()
    assert g.evidence_closure(ids["D"]) == {ids["A"], ids["B"], ids["C"], ids["D"]}
    assert g.evidence_closure(ids["A"]) == {ids["A"]}


def test_ancestors_unknown_raises() -> None:
    g, _ = _dag()
    with pytest.raises(EvidenceGraphError):
        g.ancestors("OBS-missing")


# --------------------------------------------------------------------------
# Topological order
# --------------------------------------------------------------------------


def test_topological_order_valid() -> None:
    g, ids = _dag()
    order = g.topological_order()
    assert set(order) == set(ids.values())
    pos = {nid: i for i, nid in enumerate(order)}
    # For every derivation edge (child -> parent), parent precedes child.
    for edge in g.edges_of_kind(RelationshipKind.DERIVED_FROM):
        assert pos[edge.target_id] < pos[edge.source_id]


# --------------------------------------------------------------------------
# Acyclicity
# --------------------------------------------------------------------------


def test_assert_acyclic_passes_on_dag() -> None:
    g, _ = _dag()
    g.assert_acyclic_derivation()  # must not raise


def test_assert_acyclic_raises_on_cycle() -> None:
    g, ids = _dag()
    # A derived_from D closes a cycle A<-B<-D->...->A.
    g.add_edge(make_edge(RelationshipKind.DERIVED_FROM, ids["A"], ids["D"]))
    with pytest.raises(EvidenceGraphError):
        g.assert_acyclic_derivation()


def test_contradicted_by_cycle_does_not_trip_acyclicity() -> None:
    x, y = _obs("X"), _obs("Y")
    g = EvidenceGraph()
    g.add_node(x)
    g.add_node(y)
    g.add_edge(make_edge(RelationshipKind.CONTRADICTED_BY, x.observation_id, y.observation_id))
    g.add_edge(make_edge(RelationshipKind.CONTRADICTED_BY, y.observation_id, x.observation_id))
    g.assert_acyclic_derivation()  # must not raise
    pairs = g.find_contradictions()
    assert (x.observation_id, y.observation_id) in pairs
    assert (y.observation_id, x.observation_id) in pairs


# --------------------------------------------------------------------------
# Graph hash + snapshot
# --------------------------------------------------------------------------


def test_graph_hash_order_independent() -> None:
    g1, ids = _dag()
    # Rebuild with reversed insertion order.
    nodes = [_obs(c) for c in ("A", "B", "C", "D")]
    g2 = EvidenceGraph()
    for node in reversed(nodes):
        g2.add_node(node)
    g2.add_edge(make_edge(RelationshipKind.DERIVED_FROM, ids["D"], ids["C"]))
    g2.add_edge(make_edge(RelationshipKind.DERIVED_FROM, ids["D"], ids["B"]))
    g2.add_edge(make_edge(RelationshipKind.DERIVED_FROM, ids["C"], ids["A"]))
    g2.add_edge(make_edge(RelationshipKind.DERIVED_FROM, ids["B"], ids["A"]))
    assert g1.graph_hash() == g2.graph_hash()


def test_graph_hash_sensitive_to_changed_node() -> None:
    g1, _ = _dag()
    g2 = EvidenceGraph()
    for node in (_obs("A"), _obs("B"), _obs("C"), _obs("Z")):
        g2.add_node(node)
    assert g1.graph_hash() != g2.graph_hash()


def test_snapshot_is_immutable_and_hashable() -> None:
    g, _ = _dag()
    snap = g.snapshot()
    assert isinstance(snap, GraphSnapshot)
    assert snap.graph_hash == g.graph_hash()
    assert hash(snap) == hash(g.snapshot())
    with pytest.raises(ValidationError):
        snap.graph_hash = "mutated"  # type: ignore[misc]
