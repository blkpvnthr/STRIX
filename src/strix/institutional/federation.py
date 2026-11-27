"""Authorized federation between institutions (R-N6, part 3).

Projects one institution's evidence subgraph into another under a transfer policy
(confidential companion §9):

    G_{i→j} = Project_{P_ij}(G_i)

A node transfers only if it is transfer-authorized; an **edge/derivation transfers only if
both endpoints are authorized** (so an authorized-node-but-unauthorized-edge path cannot leak
a restricted relationship — the edge-closure lesson from the R-N1/infra review). Composition
leakage — individually-permissible disclosures that jointly reveal a restricted fact — fails
closed: a forbidden joint pair rejects the whole projection.
"""

from __future__ import annotations

from strix.models import StrixModel

__all__ = ["FederationPolicy", "ProjectionResult", "project_federation"]


class FederationPolicy(StrixModel):
    """Transfer authorization for an ``i → j`` federation.

    ``transferable_ids`` is the per-node ``A_transfer`` allow-list; ``forbidden_joint`` lists
    id pairs that must not both be transferred (composition-leakage constraints).
    """

    transferable_ids: tuple[str, ...]
    forbidden_joint: tuple[tuple[str, str], ...] = ()


class ProjectionResult(StrixModel):
    """The projected subgraph (nodes + edges) and whether the transfer is authorized."""

    node_ids: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    authorized: bool
    detail: str = ""


def project_federation(
    node_ids: frozenset[str],
    edges: frozenset[tuple[str, str]],
    policy: FederationPolicy,
) -> ProjectionResult:
    """Project the transfer-authorized subgraph. Edges require both endpoints authorized;
    a forbidden joint disclosure fails the whole projection closed."""
    allow = set(policy.transferable_ids)
    transferred = {n for n in node_ids if n in allow}

    # Composition leakage: if a forbidden pair would both transfer, deny the projection.
    for a, b in policy.forbidden_joint:
        if a in transferred and b in transferred:
            return ProjectionResult(
                node_ids=(),
                edges=(),
                authorized=False,
                detail=f"composition leakage: {{{a}, {b}}} cannot be jointly transferred",
            )

    transferred_edges = tuple(
        sorted((s, t) for (s, t) in edges if s in transferred and t in transferred)
    )
    return ProjectionResult(
        node_ids=tuple(sorted(transferred)),
        edges=transferred_edges,
        authorized=True,
        detail=f"projected {len(transferred)} node(s), {len(transferred_edges)} edge(s)",
    )
