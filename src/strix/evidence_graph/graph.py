"""The :class:`EvidenceGraph` container and its operations (R1 §9.3).

The evidence graph G=(V,E) holds typed, identity-bearing nodes keyed by their
content-derived ``*_id`` and a set of typed :class:`~strix.evidence_graph.nodes.Edge`
relationships. A node may be any R1 node type
(:class:`~strix.evidence_graph.nodes.SourceObservation`,
:class:`~strix.evidence_graph.nodes.CandidateClaim`,
:class:`~strix.evidence_graph.nodes.VerificationPolicy`) or an existing lineage
model (:class:`strix.models.SourceArtifact`, ``SourceFact``,
``CalculationResult``, ``Evidence``) or a
:class:`strix.native.results.ComputationResult`.

Mutability contract: :class:`EvidenceGraph` is a *mutable builder*. ``add_node``
and ``add_edge`` mutate internal state; all read accessors return immutable
copies (tuples / fresh sets) so callers cannot reach the internal containers.
:meth:`EvidenceGraph.snapshot` produces an immutable, hashable
:class:`GraphSnapshot` suitable for certificate references.

Derivation semantics: an edge ``(source_id --DERIVED_FROM--> target_id)`` reads
"``source_id`` is derived from ``target_id``"; the target is the *ancestor*
(provenance) and the source is the *descendant*. The derivation subgraph used by
ancestry, closure, topological order, and the acyclicity check is induced by the
edge kinds ``DERIVED_FROM``, ``EXTRACTED_FROM``, ``CALCULATED_FROM`` and
``DEPENDS_ON``. Other kinds (notably ``CONTRADICTED_BY``) may form cycles and
are excluded from that subgraph.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import TypeVar

from strix.canonical import canonical_bytes, canonical_hash
from strix.evidence_graph.nodes import (
    CandidateClaim,
    Edge,
    EvidenceGraphError,
    RelationshipKind,
    SourceObservation,
    VerificationPolicy,
)
from strix.models import (
    CalculationResult,
    Evidence,
    SourceArtifact,
    SourceFact,
    StrixModel,
)
from strix.native.results import ComputationResult

__all__ = ["EvidenceGraph", "GraphSnapshot"]

Node = StrixModel
_NodeT = TypeVar("_NodeT", bound=StrixModel)

# Edge kinds that induce the derivation / provenance subgraph (R1 §9.3).
DERIVATION_KINDS: frozenset[RelationshipKind] = frozenset(
    {
        RelationshipKind.DERIVED_FROM,
        RelationshipKind.EXTRACTED_FROM,
        RelationshipKind.CALCULATED_FROM,
        RelationshipKind.DEPENDS_ON,
    }
)

# Explicit identity field per known node type. Falls back to the first field
# whose name ends with ``_id`` for any other StrixModel.
_NODE_ID_FIELDS: dict[type[StrixModel], str] = {
    SourceObservation: "observation_id",
    CandidateClaim: "candidate_claim_id",
    VerificationPolicy: "policy_id",
    SourceArtifact: "artifact_id",
    SourceFact: "fact_id",
    CalculationResult: "calculation_id",
    Evidence: "evidence_id",
    ComputationResult: "computation_id",
}


def node_identity(node: Node) -> str:
    """Return the content-derived identity (``*_id``) of *node*.

    Uses the explicit :data:`_NODE_ID_FIELDS` registry, else the first model
    field whose name ends with ``_id``. Raises :class:`EvidenceGraphError` if no
    identity field exists or its value is empty.
    """
    field = _NODE_ID_FIELDS.get(type(node))
    if field is None:
        field = next((name for name in type(node).model_fields if name.endswith("_id")), None)
    if field is None:
        raise EvidenceGraphError(f"{type(node).__name__} has no '*_id' identity field")
    value = getattr(node, field)
    if not isinstance(value, str) or not value:
        raise EvidenceGraphError(f"{type(node).__name__}.{field} is not a non-empty id")
    return value


class GraphSnapshot(StrixModel):
    """An immutable, hashable summary of an :class:`EvidenceGraph`.

    Captures the deterministic ``graph_hash`` plus the sorted node and edge ids,
    which are content-addressed and therefore sufficient as certificate
    references. Being a frozen :class:`~strix.models.StrixModel`, it is hashable.
    """

    graph_hash: str
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]


class EvidenceGraph:
    """A mutable builder for the typed evidence graph (R1 §9.3).

    Nodes are stored in an ``id -> node`` mapping; edges in an
    ``edge_id -> Edge`` mapping (deduplicated by content-derived id). All read
    accessors return copies, so internal state is never exposed by reference.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}

    # -- construction ------------------------------------------------------

    def add_node(self, node: Node) -> EvidenceGraph:
        """Add *node*, keyed by its content identity. Returns ``self``.

        Re-adding an identical node is a no-op; a different node sharing the
        same id signals a hash collision or corruption and raises.
        """
        node_id = node_identity(node)
        existing = self._nodes.get(node_id)
        if existing is not None and existing != node:
            raise EvidenceGraphError(f"conflicting node already present for id {node_id!r}")
        self._nodes[node_id] = node
        return self

    def add_edge(self, edge: Edge) -> EvidenceGraph:
        """Add *edge* after validating referential integrity. Returns ``self``.

        Raises :class:`EvidenceGraphError` if either endpoint is not a known
        node. Edges are deduplicated by their content-derived ``edge_id``.
        """
        if edge.source_id not in self._nodes:
            raise EvidenceGraphError(f"edge source {edge.source_id!r} is not a known node")
        if edge.target_id not in self._nodes:
            raise EvidenceGraphError(f"edge target {edge.target_id!r} is not a known node")
        self._edges[edge.edge_id] = edge
        return self

    # -- node lookups ------------------------------------------------------

    def has_node(self, node_id: str) -> bool:
        """Whether a node with *node_id* is present."""
        return node_id in self._nodes

    def node(self, node_id: str) -> Node:
        """Return the node with *node_id* or raise :class:`EvidenceGraphError`."""
        try:
            return self._nodes[node_id]
        except KeyError:
            raise EvidenceGraphError(f"no node with id {node_id!r}") from None

    def node_ids(self) -> tuple[str, ...]:
        """Return all node ids, sorted."""
        return tuple(sorted(self._nodes))

    def nodes_by_type(self, node_type: type[_NodeT]) -> tuple[_NodeT, ...]:
        """Return all nodes that are instances of *node_type*, sorted by id."""
        matched = [
            (nid, node) for nid, node in self._nodes.items() if isinstance(node, node_type)
        ]
        return tuple(node for _, node in sorted(matched, key=lambda pair: pair[0]))

    # -- edge lookups ------------------------------------------------------

    def edges(self) -> tuple[Edge, ...]:
        """Return all edges, in a deterministic order."""
        return tuple(sorted(self._edges.values(), key=lambda e: e.edge_id))

    def edges_from(self, node_id: str) -> tuple[Edge, ...]:
        """Return edges whose ``source_id`` equals *node_id*."""
        return tuple(e for e in self.edges() if e.source_id == node_id)

    def edges_to(self, node_id: str) -> tuple[Edge, ...]:
        """Return edges whose ``target_id`` equals *node_id*."""
        return tuple(e for e in self.edges() if e.target_id == node_id)

    def edges_of_kind(self, kind: RelationshipKind) -> tuple[Edge, ...]:
        """Return edges of the given relationship *kind*."""
        return tuple(e for e in self.edges() if e.kind == kind)

    # -- derivation traversal ---------------------------------------------

    def _require_node(self, node_id: str) -> None:
        if node_id not in self._nodes:
            raise EvidenceGraphError(f"no node with id {node_id!r}")

    def _derivation_edges(self) -> tuple[Edge, ...]:
        return tuple(e for e in self.edges() if e.kind in DERIVATION_KINDS)

    def ancestors(self, node_id: str) -> set[str]:
        """Return all nodes *node_id* is transitively derived from.

        Follows outgoing derivation edges (``source == current``) to their
        targets. Excludes *node_id* itself.
        """
        self._require_node(node_id)
        parents: dict[str, list[str]] = {}
        for edge in self._derivation_edges():
            parents.setdefault(edge.source_id, []).append(edge.target_id)
        return self._reachable(node_id, parents)

    def descendants(self, node_id: str) -> set[str]:
        """Return all nodes transitively derived from *node_id*.

        Follows incoming derivation edges (``target == current``) back to their
        sources. Excludes *node_id* itself.
        """
        self._require_node(node_id)
        children: dict[str, list[str]] = {}
        for edge in self._derivation_edges():
            children.setdefault(edge.target_id, []).append(edge.source_id)
        return self._reachable(node_id, children)

    def evidence_closure(self, node_id: str) -> set[str]:
        """Return *node_id* plus every node reachable via provenance edges.

        The evidence supporting *node_id*: itself together with all of its
        derivation ancestors (R1 §9.3).
        """
        return {node_id} | self.ancestors(node_id)

    @staticmethod
    def _reachable(start: str, adjacency: dict[str, list[str]]) -> set[str]:
        """Transitive closure from *start* over *adjacency*, excluding *start*."""
        seen: set[str] = set()
        stack: list[str] = list(adjacency.get(start, ()))
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(adjacency.get(current, ()))
        seen.discard(start)
        return seen

    # -- ordering & acyclicity --------------------------------------------

    def topological_order(self) -> tuple[str, ...]:
        """Return a dependencies-first topological order of the full node set.

        For every derivation edge ``child --> parent`` the parent precedes the
        child. Nodes not in the derivation subgraph are included in id order.
        Raises :class:`EvidenceGraphError` if the derivation subgraph has a
        cycle.
        """
        self.assert_acyclic_derivation()
        # prerequisite -> dependents: parent (target) must come before child.
        dependents: dict[str, set[str]] = {nid: set() for nid in self._nodes}
        indegree: dict[str, int] = dict.fromkeys(self._nodes, 0)
        for edge in self._derivation_edges():
            if edge.source_id not in dependents[edge.target_id]:
                dependents[edge.target_id].add(edge.source_id)
                indegree[edge.source_id] += 1
        ready = sorted(nid for nid, deg in indegree.items() if deg == 0)
        order: list[str] = []
        while ready:
            current = ready.pop(0)
            order.append(current)
            newly: list[str] = []
            for child in dependents[current]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    newly.append(child)
            ready = sorted([*ready, *newly])
        if len(order) != len(self._nodes):  # pragma: no cover - guarded by assert
            raise EvidenceGraphError("derivation subgraph is not acyclic")
        return tuple(order)

    def assert_acyclic_derivation(self) -> None:
        """Raise :class:`EvidenceGraphError` if the derivation subgraph cycles.

        The subgraph induced by ``DERIVED_FROM``/``EXTRACTED_FROM``/
        ``CALCULATED_FROM``/``DEPENDS_ON`` must be acyclic; the raised error
        names the detected cycle. Non-derivation edges are ignored.
        """
        adjacency: dict[str, list[str]] = {}
        for edge in self._derivation_edges():
            adjacency.setdefault(edge.source_id, []).append(edge.target_id)
        for targets in adjacency.values():
            targets.sort()

        # Iterative three-colour DFS (white=0, grey=1, black=2) — avoids a
        # RecursionError on deep derivation chains while still naming the cycle.
        color: dict[str, int] = {}
        for start in sorted(self._nodes):
            if color.get(start, 0) != 0:
                continue
            color[start] = 1
            path: list[str] = [start]
            stack: list[tuple[str, int]] = [(start, 0)]
            while stack:
                node_id, index = stack[-1]
                neighbours = adjacency.get(node_id, ())
                if index < len(neighbours):
                    stack[-1] = (node_id, index + 1)
                    nxt = neighbours[index]
                    state = color.get(nxt, 0)
                    if state == 1:
                        cycle = [*path[path.index(nxt):], nxt]
                        raise EvidenceGraphError(
                            f"derivation cycle detected: {' -> '.join(cycle)}"
                        )
                    if state == 0:
                        color[nxt] = 1
                        path.append(nxt)
                        stack.append((nxt, 0))
                else:
                    color[node_id] = 2
                    stack.pop()
                    path.pop()

    def find_contradictions(self) -> tuple[tuple[str, str], ...]:
        """Return ``(source_id, target_id)`` pairs linked by ``CONTRADICTED_BY``."""
        return tuple(
            (e.source_id, e.target_id) for e in self.edges_of_kind(RelationshipKind.CONTRADICTED_BY)
        )

    # -- hashing & snapshot -----------------------------------------------

    def _canonical_payload(self) -> dict[str, object]:
        nodes_payload = sorted(
            (
                {"id": nid, "type": type(node).__name__, "data": node.model_dump()}
                for nid, node in self._nodes.items()
            ),
            key=lambda entry: str(entry["id"]),
        )
        edges_payload = sorted(
            (edge.model_dump() for edge in self._edges.values()),
            key=canonical_bytes,
        )
        return {"nodes": nodes_payload, "edges": edges_payload}

    def graph_hash(self) -> str:
        """Return a deterministic, order-independent hash of the whole graph.

        Identical logical graphs hash identically regardless of insertion
        order; any change to a node's content or the edge set changes the hash.
        """
        return canonical_hash(self._canonical_payload())

    def snapshot(self) -> GraphSnapshot:
        """Return an immutable, hashable :class:`GraphSnapshot` of this graph."""
        return GraphSnapshot(
            graph_hash=self.graph_hash(),
            node_ids=self.node_ids(),
            edge_ids=tuple(sorted(self._edges)),
        )

    # -- dunders -----------------------------------------------------------

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, node_id: object) -> bool:
        return isinstance(node_id, str) and node_id in self._nodes

    def __iter__(self) -> Iterator[Node]:
        return iter(self._nodes.values())

    def extend(self, nodes: Iterable[Node]) -> EvidenceGraph:
        """Add many nodes. Returns ``self``."""
        for node in nodes:
            self.add_node(node)
        return self
