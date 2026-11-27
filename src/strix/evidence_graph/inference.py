"""Formal entailment for the compositional evidence calculus (R-N3).

The compositional calculus (confidential companion §6) admits a *conclusion* only when
its premises genuinely entail it — not merely when each premise is independently
verified. For the subset of conclusions that are *formally representable*, this module
decides entailment over propositional logic by the two-query contract

    ENTAILED  ⟺  SAT(Γ ∧ Φ)  and  UNSAT(Γ ∧ Φ ∧ ¬φ_C)

(manuscript eq 10). The first query rejects inconsistent premises; the second searches
for a counterexample to the conclusion.

**Proposition 2 (conditional soundness, INV-N3-1):** if the encoded premises are
satisfiable and ``Γ ∧ Φ ∧ ¬φ_C`` is unsatisfiable then ``Γ ∧ Φ ⊨ φ_C`` — *relative to
the encoding only*. This establishes neither translation fidelity (natural-language →
logic) nor the empirical truth of the premises.

Two deciders are provided:
- :class:`ReferenceChecker` — a deterministic, exact truth-table enumerator (no external
  dependency), the trusted baseline. It returns UNKNOWN above a bounded atom count
  rather than guessing.
- :func:`z3_checker` — an optional SMT backend (``z3-solver``, feature-flagged). A
  missing solver, a timeout, or a solver ``unknown`` result **never** yields ENTAILED —
  it degrades to UNKNOWN and the caller falls back to the reference checker.

**Hard rule:** solver timeouts, unsupported translations, and UNKNOWN results are never
treated as a successful proof (CE-N3-4).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from itertools import product

__all__ = [
    "And",
    "Atom",
    "Const",
    "EntailmentResult",
    "EntailmentStatus",
    "Formula",
    "Iff",
    "Implies",
    "Not",
    "Or",
    "ReferenceChecker",
    "atoms_of",
    "decide_entailment",
    "evaluate",
    "z3_available",
    "z3_checker",
]

#: Reference enumeration is exact but exponential; above this many distinct atoms it
#: returns UNKNOWN rather than enumerate (the caller may try the SMT backend).
MAX_REFERENCE_ATOMS = 16


# --------------------------------------------------------------------------
# Propositional formula algebra (immutable, hashable)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Atom:
    """A propositional variable."""

    name: str


@dataclass(frozen=True)
class Const:
    """A boolean constant."""

    value: bool


@dataclass(frozen=True)
class Not:
    """Negation."""

    operand: Formula


@dataclass(frozen=True)
class And:
    """Conjunction of zero or more formulas (empty = true)."""

    operands: tuple[Formula, ...]


@dataclass(frozen=True)
class Or:
    """Disjunction of zero or more formulas (empty = false)."""

    operands: tuple[Formula, ...]


@dataclass(frozen=True)
class Implies:
    """Material implication ``antecedent → consequent``."""

    antecedent: Formula
    consequent: Formula


@dataclass(frozen=True)
class Iff:
    """Biconditional ``left ↔ right``."""

    left: Formula
    right: Formula


Formula = Atom | Const | Not | And | Or | Implies | Iff


def atoms_of(formula: Formula) -> frozenset[str]:
    """Return the set of atom names occurring in *formula*."""
    match formula:
        case Atom(name):
            return frozenset({name})
        case Const():
            return frozenset()
        case Not(operand):
            return atoms_of(operand)
        case And(operands) | Or(operands):
            out: set[str] = set()
            for sub in operands:
                out |= atoms_of(sub)
            return frozenset(out)
        case Implies(a, b):
            return atoms_of(a) | atoms_of(b)
        case Iff(left, right):
            return atoms_of(left) | atoms_of(right)
    raise TypeError(f"unknown formula node {formula!r}")  # pragma: no cover


def evaluate(formula: Formula, assignment: Mapping[str, bool]) -> bool:
    """Evaluate *formula* under a total truth *assignment* (missing atom ⇒ False)."""
    match formula:
        case Atom(name):
            return assignment.get(name, False)
        case Const(value):
            return value
        case Not(operand):
            return not evaluate(operand, assignment)
        case And(operands):
            return all(evaluate(sub, assignment) for sub in operands)
        case Or(operands):
            return any(evaluate(sub, assignment) for sub in operands)
        case Implies(a, b):
            return (not evaluate(a, assignment)) or evaluate(b, assignment)
        case Iff(left, right):
            return evaluate(left, assignment) == evaluate(right, assignment)
    raise TypeError(f"unknown formula node {formula!r}")  # pragma: no cover


# --------------------------------------------------------------------------
# Entailment result
# --------------------------------------------------------------------------


class EntailmentStatus(StrEnum):
    """Outcome of the two-query entailment contract."""

    ENTAILED = "entailed"
    NOT_ENTAILED = "not_entailed"
    INCONSISTENT_PREMISES = "inconsistent_premises"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EntailmentResult:
    """An entailment decision plus, when NOT_ENTAILED, a refuting assignment."""

    status: EntailmentStatus
    counterexample: tuple[tuple[str, bool], ...] | None = None
    backend: str = "reference"
    detail: str = ""


# --------------------------------------------------------------------------
# Reference checker — exact truth-table enumeration
# --------------------------------------------------------------------------


class ReferenceChecker:
    """Deterministic, exact propositional SAT by truth-table enumeration.

    Trusted baseline for the SMT backend. Returns ``None`` from :meth:`satisfiable`
    above :data:`MAX_REFERENCE_ATOMS` atoms (UNKNOWN), never a guess.
    """

    def satisfiable(
        self, formula: Formula
    ) -> tuple[bool | None, tuple[tuple[str, bool], ...] | None]:
        """Return ``(sat, model)``: ``(True, model)``, ``(False, None)``, or
        ``(None, None)`` when the atom count exceeds the enumeration bound."""
        names = sorted(atoms_of(formula))
        if len(names) > MAX_REFERENCE_ATOMS:
            return None, None
        for combo in product((False, True), repeat=len(names)):
            assignment = dict(zip(names, combo, strict=True))
            if evaluate(formula, assignment):
                return True, tuple(sorted(assignment.items()))
        return False, None


def _entailment_from(
    checker: ReferenceChecker, premises: Formula, conclusion: Formula, backend: str
) -> EntailmentResult:
    sat_premises, _ = checker.satisfiable(premises)
    if sat_premises is None:
        return EntailmentResult(EntailmentStatus.UNKNOWN, backend=backend,
                                detail="premise satisfiability undecided within bound")
    if not sat_premises:
        return EntailmentResult(EntailmentStatus.INCONSISTENT_PREMISES, backend=backend,
                                detail="premises Γ∧Φ are unsatisfiable")
    sat_refute, model = checker.satisfiable(And((premises, Not(conclusion))))
    if sat_refute is None:
        return EntailmentResult(EntailmentStatus.UNKNOWN, backend=backend,
                                detail="refutation satisfiability undecided within bound")
    if sat_refute:
        return EntailmentResult(EntailmentStatus.NOT_ENTAILED, counterexample=model,
                                backend=backend, detail="a counterexample to the conclusion exists")
    return EntailmentResult(EntailmentStatus.ENTAILED, backend=backend,
                            detail="SAT(Γ∧Φ) and UNSAT(Γ∧Φ∧¬φ)")


def decide_entailment(
    premises: Formula, conclusion: Formula, *, checker: ReferenceChecker | None = None
) -> EntailmentResult:
    """Decide ``premises ⊨ conclusion`` with the reference checker (ALG-N3-3)."""
    return _entailment_from(checker or ReferenceChecker(), premises, conclusion, "reference")


# --------------------------------------------------------------------------
# Optional SMT backend (z3), feature-flagged and fail-safe
# --------------------------------------------------------------------------


def z3_available() -> bool:
    """Whether the optional ``z3-solver`` backend can be imported."""
    try:
        import z3  # noqa: F401
    except ImportError:
        return False
    return True


def _to_z3(formula: Formula, cache: dict[str, object]) -> object:
    import z3

    match formula:
        case Atom(name):
            if name not in cache:
                cache[name] = z3.Bool(name)
            return cache[name]
        case Const(value):
            return z3.BoolVal(value)
        case Not(operand):
            return z3.Not(_to_z3(operand, cache))
        case And(operands):
            return z3.And(*[_to_z3(s, cache) for s in operands]) if operands else z3.BoolVal(True)
        case Or(operands):
            return z3.Or(*[_to_z3(s, cache) for s in operands]) if operands else z3.BoolVal(False)
        case Implies(a, b):
            return z3.Implies(_to_z3(a, cache), _to_z3(b, cache))
        case Iff(left, right):
            return _to_z3(left, cache) == _to_z3(right, cache)
    raise TypeError(f"unknown formula node {formula!r}")  # pragma: no cover


def _z3_satisfiable(formula: Formula, timeout_ms: int) -> bool | None:
    """Return True/False, or None on solver 'unknown'/timeout (never a guess)."""
    import z3

    solver = z3.Solver()
    solver.set("timeout", timeout_ms)
    solver.add(_to_z3(formula, {}))
    result = solver.check()
    if result == z3.sat:
        return True
    if result == z3.unsat:
        return False
    return None


def z3_checker(
    premises: Formula, conclusion: Formula, *, timeout_ms: int = 5000
) -> EntailmentResult:
    """Decide entailment with the SMT backend (ALG-N3-4), fail-safe to UNKNOWN.

    If ``z3-solver`` is absent, or either query returns 'unknown'/times out, the result
    is UNKNOWN — it is **never** ENTAILED on an undecided query.
    """
    if not z3_available():
        return EntailmentResult(EntailmentStatus.UNKNOWN, backend="z3",
                                detail="z3-solver not installed")
    sat_premises = _z3_satisfiable(premises, timeout_ms)
    if sat_premises is None:
        return EntailmentResult(EntailmentStatus.UNKNOWN, backend="z3",
                                detail="premise query timed out / unknown")
    if not sat_premises:
        return EntailmentResult(EntailmentStatus.INCONSISTENT_PREMISES, backend="z3",
                                detail="premises unsatisfiable")
    sat_refute = _z3_satisfiable(And((premises, Not(conclusion))), timeout_ms)
    if sat_refute is None:
        return EntailmentResult(EntailmentStatus.UNKNOWN, backend="z3",
                                detail="refutation query timed out / unknown")
    if sat_refute:
        return EntailmentResult(EntailmentStatus.NOT_ENTAILED, backend="z3",
                                detail="z3 found a counterexample")
    return EntailmentResult(EntailmentStatus.ENTAILED, backend="z3",
                            detail="z3: SAT(Γ∧Φ) and UNSAT(Γ∧Φ∧¬φ)")
