"""Policy precedence resolution (R-N6, part 2).

Represents policy precedence as a partial order ``(P, ⪯)`` where ``a ⪯ b`` means policy ``b``
takes precedence over ``a``. Resolving a set of applicable policies yields the unique
⪯-greatest one; **unresolved conflicts fail closed** (confidential companion §9): incomparable
maxima, an empty applicable set, or a precedence cycle (not a partial order) all deny rather
than guess.
"""

from __future__ import annotations

from strix.models import StrixModel

__all__ = ["PolicyPrecedence", "PolicyResolution"]


class PolicyResolution(StrixModel):
    """Outcome of resolving applicable policies against a precedence order."""

    resolved: str | None
    status: str  # resolved | conflict | cyclic | empty
    detail: str = ""


class PolicyPrecedence(StrixModel):
    """A precedence partial order over policy ids.

    ``relations`` is a tuple of ``(lower, higher)`` pairs meaning ``lower ⪯ higher``
    (``higher`` takes precedence). The transitive closure is computed on demand; a cycle
    makes it not a partial order and resolution fails closed.
    """

    policies: tuple[str, ...]
    relations: tuple[tuple[str, str], ...] = ()

    def _dominators(self) -> dict[str, set[str]]:
        """Map each policy to the set of policies that transitively take precedence over it."""
        direct: dict[str, set[str]] = {p: set() for p in self.policies}
        for lower, higher in self.relations:
            direct.setdefault(lower, set()).add(higher)
            direct.setdefault(higher, set())
        # Transitive closure (Floyd-style over the reachability sets).
        changed = True
        while changed:
            changed = False
            for node in list(direct):
                for d in list(direct[node]):
                    new = direct.get(d, set()) - direct[node]
                    if new:
                        direct[node] |= new
                        changed = True
        return direct

    def _has_cycle(self, dominators: dict[str, set[str]]) -> bool:
        return any(node in doms for node, doms in dominators.items())

    def resolve(self, applicable: frozenset[str]) -> PolicyResolution:
        """Resolve *applicable* to the unique ⪯-greatest policy, or fail closed."""
        if not applicable:
            return PolicyResolution(resolved=None, status="empty", detail="no applicable policy")
        dominators = self._dominators()
        if self._has_cycle(dominators):
            return PolicyResolution(
                resolved=None, status="cyclic", detail="precedence relation is not a partial order"
            )
        # Maximal applicable policies: those not dominated by any other applicable policy.
        maximal = sorted(
            p for p in applicable if not (dominators.get(p, set()) & applicable)
        )
        if len(maximal) == 1:
            return PolicyResolution(resolved=maximal[0], status="resolved", detail="")
        return PolicyResolution(
            resolved=None,
            status="conflict",
            detail=f"incomparable maxima: {maximal}; failing closed",
        )
