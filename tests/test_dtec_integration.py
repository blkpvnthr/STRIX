"""Phase-4 integration: the unified A_DTEC admission path (no-bypass end-to-end).

Proves the composed calculus is fail-closed and strictly extends the core: a valid claim is
admitted; a fabricated value, dependency-inflated corroboration, future-information leakage, or
an entity relabel are each rejected/abstained by the composition even when an individual layer
would miss them. Also checks Proposition 3 (extension never weakens) and determinism.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from strix.assurance.gateway import GatewayOutcome
from strix.evidence_graph.dependency import DependencyPolicy
from strix.evidence_graph.graph import EvidenceGraph
from strix.evidence_graph.nodes import (
    AdmissionOutcome,
    Assertion,
    PredicateName,
    RelationshipKind,
    TemporalMode,
    make_candidate_claim,
    make_edge,
    make_source_observation,
    make_verification_policy,
)
from strix.evidence_graph.temporal import TemporalEnvelope, TemporalInterval, TemporalScope
from strix.evidence_graph.unified import DTECOptions, admit_dtec
from strix.models import SourceArtifact, SourceType
from strix.native.backends.python_reference import PythonReferenceBackend

KNOWN = datetime(2024, 1, 1, tzinfo=UTC)
HEX64 = "a" * 64
ALL_FIVE = (
    PredicateName.INTEGRITY,
    PredicateName.TYPE_TEMPORAL,
    PredicateName.PROVENANCE,
    PredicateName.DERIVATION,
    PredicateName.SUPPORT,
)


def _artifact(aid: str = "ART-1") -> SourceArtifact:
    return SourceArtifact(
        artifact_id=aid, source_type=SourceType.SYNTHETIC_FIXTURE, source_name=f"{aid}.json",
        source_version="v1", content_hash=HEX64, known_at=KNOWN, local_path=f"raw/{aid}.json",
        byte_size=100,
    )


def _policy():
    return make_verification_policy(
        version="dtec-pol-1", mandatory_predicates=ALL_FIVE,
        temporal_mode=TemporalMode.RETROSPECTIVE,
        absolute_tolerance=Decimal("0.0001"), relative_tolerance=Decimal("0.0001"),
    )


def _valid_obs_claim(value: str = "0.25", asserted: str | None = None):
    """A core-admissible observation-backed claim (artifact + observation + extraction edge)."""
    art = _artifact()
    obs = make_source_observation(
        subject_id="ACME", concept="operating_margin", value=Decimal(value), unit="ratio",
        observation_period="FY2023", observed_at=KNOWN, available_at=KNOWN,
        source_artifact_id="ART-1", source_locator="/0",
    )
    graph = EvidenceGraph()
    graph.add_node(art)
    graph.add_node(obs)
    graph.add_edge(make_edge(RelationshipKind.EXTRACTED_FROM, obs.observation_id, "ART-1"))
    assertion = Assertion(
        metric="operating_margin", asserted_value=Decimal(asserted or value), unit="ratio",
        evidence_id=obs.observation_id,
    )
    claim = make_candidate_claim(
        subject_id="ACME", claim_type="profitability", statement="ACME operating margin.",
        evidence_ids=(obs.observation_id,), assertions=(assertion,),
    )
    return claim, graph, obs


# --------------------------------------------------------------------------
# Baseline + no-bypass
# --------------------------------------------------------------------------


def test_valid_claim_admitted_and_authorized() -> None:
    claim, graph, _ = _valid_obs_claim()
    dec = admit_dtec(claim, graph, _policy())
    assert dec.outcome is AdmissionOutcome.ADMITTED
    assert dec.disposition is GatewayOutcome.AUTHORIZED
    assert dec.decision_digest


def test_fabricated_value_rejected() -> None:
    # Assert a value that the cited observation does not attest -> support FAIL -> rejected.
    claim, graph, _ = _valid_obs_claim(value="0.25", asserted="0.99")
    dec = admit_dtec(claim, graph, _policy())
    assert dec.outcome is AdmissionOutcome.REJECTED
    assert dec.disposition is GatewayOutcome.REJECTED


def test_dependency_inflation_not_admitted() -> None:
    # A single-evidence claim cannot provide 2 independent items -> A_ind blocks it.
    claim, graph, _ = _valid_obs_claim()
    opts = DTECOptions(dependency_policy=DependencyPolicy(min_effective_independent=Decimal("2")))
    dec = admit_dtec(claim, graph, _policy(), opts)
    assert dec.outcome is not AdmissionOutcome.ADMITTED  # core admits, A_ind does not


def test_temporal_leak_rejected() -> None:
    claim, graph, _ = _valid_obs_claim()
    leaking = TemporalEnvelope(
        evidence_id="E", validity=TemporalInterval(start=KNOWN, end=KNOWN + timedelta(days=100)),
        knowledge=TemporalInterval(start=KNOWN, end=KNOWN + timedelta(days=100)),
        available_at=KNOWN + timedelta(days=90),  # available after the knowledge cutoff below
    )
    opts = DTECOptions(
        temporal_envelopes=(leaking,),
        temporal_scope=TemporalScope(
            valid_time=KNOWN + timedelta(days=50), knowledge_time=KNOWN + timedelta(days=50)
        ),
    )
    dec = admit_dtec(claim, graph, _policy(), opts)
    assert dec.outcome is AdmissionOutcome.REJECTED


def test_entity_relabel_rejected_by_binding() -> None:
    # Computation really about ACME; claim relabels it EVILCORP. Core support/derivation miss
    # the entity (ComputationResult carries none); the binding predicate catches the relabel.
    acme_obs = make_source_observation(
        subject_id="ACME", concept="revenue", value=Decimal("100"), unit="usd",
        observation_period="FY2023", observed_at=KNOWN, source_artifact_id="ART-1",
        source_locator="/0",
    )
    comp = PythonReferenceBackend().run(
        "mean", {"series": [Decimal("100"), Decimal("200")]},
        input_observation_ids=(acme_obs.observation_id,),
    )
    graph = EvidenceGraph()
    graph.add_node(_artifact())
    graph.add_node(acme_obs)
    graph.add_node(comp)
    claim = make_candidate_claim(
        subject_id="EVILCORP", claim_type="revenue", statement="EVILCORP revenue.",
        evidence_ids=(comp.computation_id,),
        assertions=(Assertion(metric="revenue", asserted_value=Decimal("150"), unit="usd",
                              evidence_id=comp.computation_id),),
    )
    dec = admit_dtec(claim, graph, _policy())
    assert dec.outcome is AdmissionOutcome.REJECTED  # binding FAILs the relabel


# --------------------------------------------------------------------------
# Proposition 3 (extension never weakens) + determinism
# --------------------------------------------------------------------------


def test_prop3_passing_extension_keeps_admission() -> None:
    # A single trusted item gives N_eff=1; with θ=1 A_ind passes, so admission is preserved.
    claim, graph, _ = _valid_obs_claim()
    opts = DTECOptions(dependency_policy=DependencyPolicy(min_effective_independent=Decimal("1")))
    dec = admit_dtec(claim, graph, _policy(), opts)
    assert dec.outcome is AdmissionOutcome.ADMITTED


def test_prop3_failing_extension_cannot_admit() -> None:
    # Core would admit, but a failing extension predicate holds it to a stricter standard.
    claim, graph, _ = _valid_obs_claim()
    base = admit_dtec(claim, graph, _policy())
    assert base.outcome is AdmissionOutcome.ADMITTED
    strict = admit_dtec(
        claim, graph, _policy(),
        DTECOptions(dependency_policy=DependencyPolicy(min_effective_independent=Decimal("5"))),
    )
    assert strict.outcome is not AdmissionOutcome.ADMITTED


def test_decision_is_deterministic() -> None:
    claim, graph, _ = _valid_obs_claim()
    d1 = admit_dtec(claim, graph, _policy())
    claim2, graph2, _ = _valid_obs_claim()
    d2 = admit_dtec(claim2, graph2, _policy())
    assert d1.decision_digest == d2.decision_digest
    assert d1.outcome == d2.outcome


def test_no_bypass_core_rejection_dominates_all_extensions() -> None:
    # Even with every extension configured to pass, a core FAIL (fabricated value) stays REJECTED.
    claim, graph, _ = _valid_obs_claim(value="0.25", asserted="0.99")
    opts = DTECOptions(dependency_policy=DependencyPolicy(min_effective_independent=Decimal("1")))
    dec = admit_dtec(claim, graph, _policy(), opts)
    assert dec.outcome is AdmissionOutcome.REJECTED
