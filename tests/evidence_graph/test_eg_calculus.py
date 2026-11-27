"""Tests for the compositional evidence calculus (R-N3): A_C = (⋀A(cᵢ)) ∧ R ∧ K ∧ F.

Covers the admission-algebra composition (incl. INV-ALG-1/3 and the RC-3 empty-set
guard), the R/K/F component predicates, and the end-to-end ``admit_conclusion`` — most
importantly that a conclusion whose premises are all admitted is still REJECTED when the
premises do not entail it (the defining value of conclusion-level verification).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from strix.evidence_graph.calculus import (
    Conclusion,
    FormalEncoding,
    SupportBalance,
    admit_conclusion,
    assess_contextual,
    assess_faithfulness,
    assess_inferential,
    compose_statuses,
)
from strix.evidence_graph.graph import EvidenceGraph
from strix.evidence_graph.inference import And, Atom, Implies, Not
from strix.evidence_graph.nodes import (
    AdmissionOutcome,
    PredicateStatus,
    RelationshipKind,
    make_edge,
    make_source_observation,
)
from strix.models import SourceArtifact, SourceType

A, B = Atom("A"), Atom("B")
KNOWN = datetime(2024, 1, 1, tzinfo=UTC)
HEX64 = "a" * 64

ENTAILED_FORMAL = FormalEncoding(context=And(()), premises=And((A, Implies(A, B))), conclusion=B)
UNENTAILED_FORMAL = FormalEncoding(context=And(()), premises=Implies(A, B), conclusion=B)


def _conclusion(**kw) -> Conclusion:
    base: dict = {
        "conclusion_id": "CONC-1",
        "proposition": "B holds.",
        "premise_claim_ids": ("C1", "C2"),
    }
    base.update(kw)
    return Conclusion(**base)


def _admitted(*ids: str) -> dict[str, AdmissionOutcome]:
    return dict.fromkeys(ids, AdmissionOutcome.ADMITTED)


# --------------------------------------------------------------------------
# Admission-algebra composition (INV-ALG-1/3, RC-3)
# --------------------------------------------------------------------------


def test_compose_fail_dominates() -> None:
    assert compose_statuses((PredicateStatus.PASS, PredicateStatus.FAIL)) is PredicateStatus.FAIL
    assert (
        compose_statuses((PredicateStatus.UNKNOWN, PredicateStatus.FAIL)) is PredicateStatus.FAIL
    )


def test_compose_unknown_over_pass() -> None:
    assert (
        compose_statuses((PredicateStatus.PASS, PredicateStatus.UNKNOWN))
        is PredicateStatus.UNKNOWN
    )


def test_compose_all_pass() -> None:
    assert compose_statuses((PredicateStatus.PASS, PredicateStatus.PASS)) is PredicateStatus.PASS


def test_compose_na_is_satisfied() -> None:
    assert (
        compose_statuses((PredicateStatus.PASS, PredicateStatus.NOT_APPLICABLE))
        is PredicateStatus.PASS
    )


def test_compose_empty_applicable_raises_rc3() -> None:
    with pytest.raises(ValueError, match="vacuous"):
        compose_statuses((PredicateStatus.NOT_APPLICABLE, PredicateStatus.NOT_APPLICABLE))


def test_prop3_fail_closed_extension() -> None:
    # INV-ALG-3: appending a FAIL to a PASS conjunction cannot yield PASS.
    base = (PredicateStatus.PASS, PredicateStatus.PASS)
    assert compose_statuses(base) is PredicateStatus.PASS
    assert compose_statuses((*base, PredicateStatus.FAIL)) is PredicateStatus.FAIL
    assert compose_statuses((*base, PredicateStatus.UNKNOWN)) is PredicateStatus.UNKNOWN


# --------------------------------------------------------------------------
# R — inferential validity
# --------------------------------------------------------------------------


def test_inferential_not_applicable_without_formal() -> None:
    res = assess_inferential(_conclusion())
    assert res.status is PredicateStatus.NOT_APPLICABLE


def test_inferential_pass_on_entailment() -> None:
    res = assess_inferential(_conclusion(formal=ENTAILED_FORMAL))
    assert res.status is PredicateStatus.PASS


def test_inferential_fail_on_non_entailment() -> None:
    res = assess_inferential(_conclusion(formal=UNENTAILED_FORMAL))
    assert res.status is PredicateStatus.FAIL
    assert res.reason_codes == ("counterexample_exists",)


def test_inferential_fail_on_inconsistent_premises() -> None:
    bad = FormalEncoding(context=And(()), premises=And((A, Not(A))), conclusion=B)
    res = assess_inferential(_conclusion(formal=bad))
    assert res.status is PredicateStatus.FAIL
    assert res.reason_codes == ("inconsistent_premises",)


# --------------------------------------------------------------------------
# K — contextual applicability
# --------------------------------------------------------------------------


def test_contextual_not_applicable_without_assumptions() -> None:
    assert assess_contextual(_conclusion(), frozenset()).status is PredicateStatus.NOT_APPLICABLE


def test_contextual_pass_when_satisfied() -> None:
    res = assess_contextual(_conclusion(assumptions=("us_gaap",)), frozenset({"us_gaap"}))
    assert res.status is PredicateStatus.PASS


def test_contextual_fail_when_unmet() -> None:
    res = assess_contextual(_conclusion(assumptions=("us_gaap", "fy2023")), frozenset({"us_gaap"}))
    assert res.status is PredicateStatus.FAIL
    assert res.reason_codes == ("unmet_contextual_assumptions",)


# --------------------------------------------------------------------------
# F — completeness & faithfulness
# --------------------------------------------------------------------------


def test_faithfulness_fail_on_no_premises() -> None:
    res = assess_faithfulness(_conclusion(premise_claim_ids=()), {})
    assert res.status is PredicateStatus.FAIL
    assert res.reason_codes == ("no_supporting_premises",)


def test_faithfulness_fail_on_rejected_premise() -> None:
    adm = {"C1": AdmissionOutcome.ADMITTED, "C2": AdmissionOutcome.REJECTED}
    res = assess_faithfulness(_conclusion(), adm)
    assert res.status is PredicateStatus.FAIL
    assert res.reason_codes == ("rejected_premise",)


def test_faithfulness_unknown_on_abstained_premise() -> None:
    adm = {"C1": AdmissionOutcome.ADMITTED, "C2": AdmissionOutcome.ABSTAINED}
    res = assess_faithfulness(_conclusion(), adm)
    assert res.status is PredicateStatus.UNKNOWN


def test_faithfulness_pass_without_graph() -> None:
    res = assess_faithfulness(_conclusion(), _admitted("C1", "C2"))
    assert res.status is PredicateStatus.PASS


def test_faithfulness_rejects_substantive_contradiction() -> None:
    conc = _conclusion(balance=SupportBalance(opposing=("X",), substantive_conflict=True))
    res = assess_faithfulness(conc, _admitted("C1", "C2"))
    assert res.status is PredicateStatus.FAIL
    assert res.reason_codes == ("unresolved_substantive_contradiction",)


# --------------------------------------------------------------------------
# F with graph — derivation closure (grounding + cycles)
# --------------------------------------------------------------------------


def _obs(oid_artifact: str):
    return make_source_observation(
        subject_id="S", concept="c", value=__import__("decimal").Decimal("1"), unit="u",
        observation_period="FY", observed_at=KNOWN, source_artifact_id=oid_artifact,
        source_locator="/0",
    )


def test_faithfulness_grounded_closure_passes() -> None:
    art = SourceArtifact(
        artifact_id="ART-1", source_type=SourceType.SYNTHETIC_FIXTURE, source_name="a.json",
        source_version="v1", content_hash=HEX64, known_at=KNOWN, local_path="raw/a.json",
        byte_size=1,
    )
    obs = _obs("ART-1")
    g = EvidenceGraph()
    g.add_node(art)
    g.add_node(obs)
    g.add_edge(make_edge(RelationshipKind.DERIVED_FROM, obs.observation_id, "ART-1"))
    conc = _conclusion(premise_claim_ids=(obs.observation_id,))
    res = assess_faithfulness(conc, _admitted(obs.observation_id), graph=g)
    assert res.status is PredicateStatus.PASS


def test_faithfulness_cyclic_closure_fails() -> None:
    o1, o2 = _obs("ART-1"), _obs("ART-2")
    g = EvidenceGraph()
    g.add_node(o1)
    g.add_node(o2)
    g.add_edge(make_edge(RelationshipKind.DERIVED_FROM, o1.observation_id, o2.observation_id))
    g.add_edge(make_edge(RelationshipKind.DERIVED_FROM, o2.observation_id, o1.observation_id))
    conc = _conclusion(premise_claim_ids=(o1.observation_id, o2.observation_id))
    res = assess_faithfulness(conc, _admitted(o1.observation_id, o2.observation_id), graph=g)
    assert res.status is PredicateStatus.FAIL
    assert res.reason_codes == ("cyclic_derivation_closure",)


# --------------------------------------------------------------------------
# admit_conclusion — end-to-end composition
# --------------------------------------------------------------------------


def test_admit_conclusion_admitted() -> None:
    dec = admit_conclusion(_conclusion(), _admitted("C1", "C2"))
    assert dec.outcome is AdmissionOutcome.ADMITTED


def test_admit_conclusion_rejected_on_rejected_premise() -> None:
    adm = {"C1": AdmissionOutcome.ADMITTED, "C2": AdmissionOutcome.REJECTED}
    assert admit_conclusion(_conclusion(), adm).outcome is AdmissionOutcome.REJECTED


def test_admit_conclusion_abstains_on_unresolved_premise() -> None:
    adm = {"C1": AdmissionOutcome.ADMITTED}  # C2 missing/unknown
    assert admit_conclusion(_conclusion(), adm).outcome is AdmissionOutcome.ABSTAINED


def test_admitted_premises_but_unentailed_conclusion_is_rejected() -> None:
    # THE headline property of R-N3: every premise is independently admitted, yet the
    # conclusion is REJECTED because the premises do not entail it. Per-premise
    # verification alone would wrongly accept this.
    conc = _conclusion(formal=UNENTAILED_FORMAL)
    dec = admit_conclusion(conc, _admitted("C1", "C2"))
    assert dec.outcome is AdmissionOutcome.REJECTED
    assert dec.entailment_status == "counterexample_exists"


def test_admitted_premises_and_entailed_conclusion_is_admitted() -> None:
    conc = _conclusion(formal=ENTAILED_FORMAL)
    dec = admit_conclusion(conc, _admitted("C1", "C2"))
    assert dec.outcome is AdmissionOutcome.ADMITTED


def test_admit_conclusion_rejected_on_unmet_context() -> None:
    conc = _conclusion(assumptions=("needs_this",))
    dec = admit_conclusion(conc, _admitted("C1", "C2"), satisfied_context=frozenset())
    assert dec.outcome is AdmissionOutcome.REJECTED
