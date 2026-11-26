"""Counterexample search for the compositional evidence calculus (R-N3, ALG-N3-5).

For a correctly encoded, formally decidable conclusion, a model of ``Γ ∧ Φ ∧ ¬φ_C`` is
a *counterexample*: premises hold yet the conclusion fails, so the conclusion is not
entailed (``X(C) ≠ ∅ ⇒ A_C(C) = FAIL``; confidential companion §6). For unrestricted
natural language the search is inherently incomplete — the *absence* of a found
counterexample does not establish validity (CE-N3-1 limitation).
"""

from __future__ import annotations

from strix.evidence_graph.inference import (
    EntailmentStatus,
    Formula,
    ReferenceChecker,
    decide_entailment,
)

__all__ = ["Counterexample", "find_counterexample", "refutes_conclusion"]

Counterexample = tuple[tuple[str, bool], ...]


def find_counterexample(
    premises: Formula, conclusion: Formula, *, checker: ReferenceChecker | None = None
) -> Counterexample | None:
    """Return a truth assignment refuting ``premises ⊨ conclusion``, or ``None``.

    ``None`` means either the conclusion is entailed, the premises are inconsistent, or
    the query is undecided within the enumeration bound — the three are distinguished by
    :func:`~strix.evidence_graph.inference.decide_entailment`; this helper only surfaces
    the witness. ``None`` is **not** a proof of validity.
    """
    result = decide_entailment(premises, conclusion, checker=checker)
    if result.status is EntailmentStatus.NOT_ENTAILED:
        return result.counterexample
    return None


def refutes_conclusion(
    premises: Formula, conclusion: Formula, *, checker: ReferenceChecker | None = None
) -> bool:
    """Whether a counterexample exists (⇒ the conclusion must be FAILed)."""
    return find_counterexample(premises, conclusion, checker=checker) is not None
