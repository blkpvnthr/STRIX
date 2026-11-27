"""Tests for the compositional-calculus inference layer (R-N3): entailment + Prop 2.

Unit tests for formula evaluation and the two-query entailment contract; a Hypothesis
property test for Proposition 2 (INV-N3-1, conditional soundness relative to the
encoding); and a parity test between the deterministic reference checker and the optional
z3 backend. Solver/UNKNOWN results must never be reported as ENTAILED.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from strix.evidence_graph.counterexamples import find_counterexample, refutes_conclusion
from strix.evidence_graph.inference import (
    And,
    Atom,
    Const,
    EntailmentStatus,
    Iff,
    Implies,
    Not,
    Or,
    ReferenceChecker,
    atoms_of,
    decide_entailment,
    evaluate,
    z3_available,
    z3_checker,
)

A, B, C = Atom("A"), Atom("B"), Atom("C")


# --------------------------------------------------------------------------
# Formula evaluation
# --------------------------------------------------------------------------


def test_evaluate_connectives() -> None:
    assign = {"A": True, "B": False}
    assert evaluate(A, assign) is True
    assert evaluate(Not(B), assign) is True
    assert evaluate(And((A, B)), assign) is False
    assert evaluate(Or((A, B)), assign) is True
    assert evaluate(Implies(A, B), assign) is False
    assert evaluate(Implies(B, A), assign) is True
    assert evaluate(Iff(A, B), assign) is False
    assert evaluate(Const(True), assign) is True
    assert evaluate(And(()), assign) is True  # empty conjunction = true
    assert evaluate(Or(()), assign) is False  # empty disjunction = false


def test_atoms_of() -> None:
    assert atoms_of(Implies(A, And((B, Not(C))))) == frozenset({"A", "B", "C"})
    assert atoms_of(Const(True)) == frozenset()


# --------------------------------------------------------------------------
# Reference checker SAT
# --------------------------------------------------------------------------


def test_sat_and_unsat() -> None:
    checker = ReferenceChecker()
    sat, model = checker.satisfiable(And((A, Implies(A, B))))
    assert sat is True and model is not None
    unsat, none_model = checker.satisfiable(And((A, Not(A))))
    assert unsat is False and none_model is None


def test_sat_too_many_atoms_is_unknown() -> None:
    big = And(tuple(Atom(f"x{i}") for i in range(20)))
    sat, model = ReferenceChecker().satisfiable(big)
    assert sat is None and model is None


# --------------------------------------------------------------------------
# Entailment (the two-query contract)
# --------------------------------------------------------------------------


def test_modus_ponens_entailed() -> None:
    premises = And((A, Implies(A, B)))
    assert decide_entailment(premises, B).status is EntailmentStatus.ENTAILED


def test_affirming_consequent_not_entailed() -> None:
    premises = Implies(A, B)  # A→B alone does not give B
    result = decide_entailment(premises, B)
    assert result.status is EntailmentStatus.NOT_ENTAILED
    assert result.counterexample is not None


def test_inconsistent_premises() -> None:
    premises = And((A, Not(A)))
    assert decide_entailment(premises, B).status is EntailmentStatus.INCONSISTENT_PREMISES


def test_compliance_counterexample() -> None:
    # CE-N3-2: "limit 85C" + "tested at 85C" does not entail "compliant" without a
    # duration premise; a countermodel sets sufficient_duration = False.
    tested = Atom("tested_at_limit")
    duration = Atom("sufficient_duration")
    compliant = Atom("compliant")
    rule = Iff(compliant, And((tested, duration)))
    premises = And((rule, tested))  # note: no sufficient_duration premise
    result = decide_entailment(premises, compliant)
    assert result.status is EntailmentStatus.NOT_ENTAILED
    ce = dict(result.counterexample or ())
    assert ce["sufficient_duration"] is False


def test_find_counterexample_helpers() -> None:
    assert find_counterexample(Implies(A, B), B) is not None
    assert refutes_conclusion(Implies(A, B), B) is True
    # Entailed ⇒ no counterexample.
    assert find_counterexample(And((A, Implies(A, B))), B) is None
    assert refutes_conclusion(And((A, Implies(A, B))), B) is False


# --------------------------------------------------------------------------
# Proposition 2 — conditional soundness (INV-N3-1), property test
# --------------------------------------------------------------------------


@st.composite
def _small_formula(draw, atoms=("A", "B", "C"), depth=3):
    if depth <= 0 or draw(st.booleans()):
        return Atom(draw(st.sampled_from(atoms)))
    kind = draw(st.sampled_from(["not", "and", "or", "implies"]))
    if kind == "not":
        return Not(draw(_small_formula(atoms=atoms, depth=depth - 1)))
    left = draw(_small_formula(atoms=atoms, depth=depth - 1))
    right = draw(_small_formula(atoms=atoms, depth=depth - 1))
    if kind == "and":
        return And((left, right))
    if kind == "or":
        return Or((left, right))
    return Implies(left, right)


@settings(max_examples=300)
@given(_small_formula(), _small_formula())
def test_prop2_conditional_soundness(premises, conclusion) -> None:
    """INV-N3-1: ENTAILED ⇒ every model of the premises satisfies the conclusion."""
    result = decide_entailment(premises, conclusion)
    if result.status is EntailmentStatus.ENTAILED:
        names = sorted(atoms_of(premises) | atoms_of(conclusion))
        from itertools import product

        for combo in product((False, True), repeat=len(names)):
            assignment = dict(zip(names, combo, strict=True))
            if evaluate(premises, assignment):
                assert evaluate(conclusion, assignment), "ENTAILED but a model refutes it"


# --------------------------------------------------------------------------
# z3 backend parity + fail-safety
# --------------------------------------------------------------------------


@pytest.mark.skipif(not z3_available(), reason="z3-solver not installed")
@settings(max_examples=120, deadline=None)
@given(_small_formula(), _small_formula())
def test_z3_parity_with_reference(premises, conclusion) -> None:
    """The SMT backend must agree with the trusted reference on decided queries."""
    ref = decide_entailment(premises, conclusion)
    z3r = z3_checker(premises, conclusion)
    if ref.status is not EntailmentStatus.UNKNOWN and z3r.status is not EntailmentStatus.UNKNOWN:
        assert ref.status == z3r.status


@pytest.mark.skipif(not z3_available(), reason="z3-solver not installed")
def test_z3_matches_entailment_examples() -> None:
    assert z3_checker(And((A, Implies(A, B))), B).status is EntailmentStatus.ENTAILED
    assert z3_checker(Implies(A, B), B).status is EntailmentStatus.NOT_ENTAILED
    assert z3_checker(And((A, Not(A))), B).status is EntailmentStatus.INCONSISTENT_PREMISES
