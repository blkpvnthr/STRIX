"""Offline DTEC ablation harness  -  engine marginal-contribution measurement (Phase 5).

Builds a small, fully-synthetic, ground-truth-labelled benchmark of adversarial and valid
items and runs each through the unified :func:`~strix.evidence_graph.unified.admit_dtec`
with individual engines ablated, producing the ablation deltas

    Δ_i  = M(F) - M(F₋ᵢ)                 (engine i's marginal contribution)
    Δ_ij = M(F) - M(F₋ᵢ) - M(F₋ⱼ) + M(F₋ᵢⱼ)   (pairwise interaction)

where ``M`` is detection accuracy (fraction of items whose admit/reject outcome matches the
ground truth). **These are deterministic offline measurements on synthetic data**  -  real
measurements, reported with their denominators, NOT the live H1-H12 validation (the live
comparative arms are `EXTERNALLY_BLOCKED` on GPT-6 Luna credentials + budget). No figure here
is a pre-registration target; negative or null Δ values are reported as-is.

An ablated engine is simply *not configured* in :class:`DTECOptions` for that run  -  a sound
ablation that never introduces a bypass into the production evaluator (the entity-binding
predicate is always-on by design; its contribution is reported as full-vs-core).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction

from strix.evidence_graph.dependency import DependencyPolicy
from strix.evidence_graph.graph import EvidenceGraph
from strix.evidence_graph.nodes import (
    AdmissionOutcome,
    Assertion,
    CandidateClaim,
    PredicateName,
    RelationshipKind,
    SourceObservation,
    TemporalMode,
    VerificationPolicy,
    make_candidate_claim,
    make_edge,
    make_source_observation,
    make_verification_policy,
)
from strix.evidence_graph.predicates import admit
from strix.evidence_graph.temporal import TemporalEnvelope, TemporalInterval, TemporalScope
from strix.evidence_graph.unified import DTECOptions, admit_dtec
from strix.institutional.admissibility import InstitutionalContext, InstitutionalLabel
from strix.models import SourceArtifact, SourceType, StrixModel
from strix.native.arithmetic import checked_div
from strix.native.backends.python_reference import PythonReferenceBackend

__all__ = [
    "ABLATABLE_ENGINES",
    "AblationItem",
    "AblationReport",
    "build_benchmark",
    "detection_accuracy",
    "interaction_delta",
    "run_ablation",
]

_T0 = datetime(2024, 1, 1, tzinfo=UTC)
_HEX = "a" * 64
_ALL_FIVE = (
    PredicateName.INTEGRITY,
    PredicateName.TYPE_TEMPORAL,
    PredicateName.PROVENANCE,
    PredicateName.DERIVATION,
    PredicateName.SUPPORT,
)

#: Option-gated engines that the harness can ablate by removing their configuration.
ABLATABLE_ENGINES: tuple[str, ...] = ("dependency", "temporal", "institutional", "budget")


@dataclass(frozen=True)
class AblationItem:
    """One labelled benchmark item: inputs, the full DTEC options, and ground truth."""

    name: str
    attack_class: str
    claim: CandidateClaim
    graph: EvidenceGraph
    policy: VerificationPolicy
    options: DTECOptions
    should_admit: bool


class AblationReport(StrixModel):
    """Measured ablation results over a benchmark (all offline, synthetic, deterministic)."""

    item_count: int
    full_accuracy: Decimal
    core_only_accuracy: Decimal
    engine_deltas: tuple[tuple[str, Decimal], ...]
    note: str = (
        "Offline synthetic ablation  -  real measurements, NOT the live H1-H12 validation "
        "(live arms EXTERNALLY_BLOCKED). No value here is a target."
    )


# --------------------------------------------------------------------------
# Benchmark construction
# --------------------------------------------------------------------------


def _artifact(aid: str) -> SourceArtifact:
    return SourceArtifact(
        artifact_id=aid, source_type=SourceType.SYNTHETIC_FIXTURE, source_name=f"{aid}.json",
        source_version="v1", content_hash=_HEX, known_at=_T0, local_path=f"raw/{aid}.json",
        byte_size=100,
    )


def _obs(subject: str, concept: str, value: str, aid: str) -> SourceObservation:
    return make_source_observation(
        subject_id=subject, concept=concept, value=Decimal(value), unit="ratio",
        observation_period="FY2023", observed_at=_T0, available_at=_T0,
        source_artifact_id=aid, source_locator="/0",
    )


def _policy() -> VerificationPolicy:
    return make_verification_policy(
        version="dtec-eval-1", mandatory_predicates=_ALL_FIVE,
        temporal_mode=TemporalMode.RETROSPECTIVE,
        absolute_tolerance=Decimal("0.0001"), relative_tolerance=Decimal("0.0001"),
    )


def _graph_with(*nodes_and_edges: StrixModel | tuple[str, str]) -> EvidenceGraph:
    g = EvidenceGraph()
    for item in nodes_and_edges:
        if isinstance(item, tuple):
            g.add_edge(make_edge(RelationshipKind.EXTRACTED_FROM, item[0], item[1]))
        else:
            g.add_node(item)
    return g


def _valid_item(name: str, subject: str = "ACME", value: str = "0.25") -> AblationItem:
    art = _artifact("ART-1")
    obs = _obs(subject, "operating_margin", value, "ART-1")
    graph = _graph_with(art, obs, (obs.observation_id, "ART-1"))
    claim = make_candidate_claim(
        subject_id=subject, claim_type="profitability", statement="margin",
        evidence_ids=(obs.observation_id,),
        assertions=(Assertion(metric="operating_margin", asserted_value=Decimal(value),
                              unit="ratio", evidence_id=obs.observation_id),),
    )
    opts = DTECOptions(dependency_policy=DependencyPolicy(min_effective_independent=Decimal("1")))
    return AblationItem(name, "valid", claim, graph, _policy(), opts, should_admit=True)


def _fabricated_item(name: str) -> AblationItem:
    item = _valid_item(name, value="0.25")
    # Assert a value the cited evidence does not attest -> core support FAILs.
    bad_assertion = Assertion(
        metric="operating_margin", asserted_value=Decimal("0.99"), unit="ratio",
        evidence_id=item.claim.evidence_ids[0],
    )
    claim = make_candidate_claim(
        subject_id="ACME", claim_type="profitability", statement="margin",
        evidence_ids=item.claim.evidence_ids, assertions=(bad_assertion,),
    )
    return replace(
        item, name=name, attack_class="fabricated_value", claim=claim, should_admit=False
    )


def _dependency_inflated_item(name: str) -> AblationItem:
    # Two observations from ONE artifact (dependent) cited as corroboration; θ=2 can't be met.
    art = _artifact("ART-1")
    o1 = _obs("ACME", "operating_margin", "0.25", "ART-1")
    o2 = _obs("ACME", "operating_margin", "0.25", "ART-1")
    graph = _graph_with(art, o1, o2, (o1.observation_id, "ART-1"), (o2.observation_id, "ART-1"))
    claim = make_candidate_claim(
        subject_id="ACME", claim_type="profitability", statement="margin",
        evidence_ids=(o1.observation_id, o2.observation_id),
        assertions=(Assertion(metric="operating_margin", asserted_value=Decimal("0.25"),
                              unit="ratio", evidence_id=o1.observation_id),),
    )
    opts = DTECOptions(dependency_policy=DependencyPolicy(min_effective_independent=Decimal("2")))
    return AblationItem(
        name, "dependency_inflated", claim, graph, _policy(), opts, should_admit=False
    )


def _temporal_leak_item(name: str) -> AblationItem:
    base = _valid_item(name)
    leaking = TemporalEnvelope(
        evidence_id="E", validity=TemporalInterval(start=_T0, end=_T0 + timedelta(days=100)),
        knowledge=TemporalInterval(start=_T0, end=_T0 + timedelta(days=100)),
        available_at=_T0 + timedelta(days=90),
    )
    opts = replace(
        base.options,
        temporal_envelopes=(leaking,),
        temporal_scope=TemporalScope(
            valid_time=_T0 + timedelta(days=50), knowledge_time=_T0 + timedelta(days=50)
        ),
    )
    return replace(base, name=name, attack_class="temporal_leak", options=opts, should_admit=False)


def _institutional_violation_item(name: str) -> AblationItem:
    base = _valid_item(name)
    ctx = InstitutionalContext(
        organization="ORG-A", user="u", role="analyst", project="P1", jurisdiction="US",
        authorized_organizations=("ORG-A",), authorized_access_levels=("public",),
        authorized_jurisdictions=("US",), authorized_projects=("P1",),
    )
    # Label with an unauthorized organization -> A_inst FAIL.
    label = InstitutionalLabel(
        evidence_id=base.claim.evidence_ids[0], organization="ORG-FORBIDDEN",
        access_level="public", jurisdiction="US", project="P1",
    )
    opts = replace(base.options, institutional_context=ctx, institutional_labels=(label,))
    return replace(base, name=name, attack_class="institutional_violation", options=opts,
                   should_admit=False)


def _entity_relabel_item(name: str) -> AblationItem:
    acme_obs = _obs("ACME", "revenue", "100", "ART-1")
    comp = PythonReferenceBackend().run(
        "mean", {"series": [Decimal("100"), Decimal("200")]},
        input_observation_ids=(acme_obs.observation_id,), input_artifact_refs=("ART-1",),
    )
    # Artifact provenance so the CORE admits (support/derivation miss the entity); only the
    # always-on binding predicate catches the relabel.
    graph = _graph_with(_artifact("ART-1"), acme_obs, comp)
    # Match the computation's own unit/value so the CORE admits (support/derivation pass;
    # entity/metric are not attested by a bare ComputationResult)  -  only binding catches
    # the EVILCORP relabel.
    claim = make_candidate_claim(
        subject_id="EVILCORP", claim_type="revenue", statement="revenue",
        evidence_ids=(comp.computation_id,),
        assertions=(Assertion(metric="revenue", asserted_value=comp.scalar, unit=comp.output_unit,
                              evidence_id=comp.computation_id),),
    )
    # Binding is always-on; no option needed.
    return AblationItem(name, "entity_relabel", claim, graph, _policy(), DTECOptions(),
                        should_admit=False)


def build_benchmark() -> tuple[AblationItem, ...]:
    """A small deterministic synthetic benchmark spanning valid + five attack classes."""
    items: list[AblationItem] = []
    for i in range(2):
        items.append(_valid_item(f"valid-{i}", value="0.2" + str(5 + i)))
        items.append(_fabricated_item(f"fabricated-{i}"))
        items.append(_dependency_inflated_item(f"depinflate-{i}"))
        items.append(_temporal_leak_item(f"templeak-{i}"))
        items.append(_institutional_violation_item(f"instviol-{i}"))
        items.append(_entity_relabel_item(f"relabel-{i}"))
    return tuple(items)


# --------------------------------------------------------------------------
# Ablation measurement
# --------------------------------------------------------------------------


def _disable(options: DTECOptions, engines: frozenset[str]) -> DTECOptions:
    """Return *options* with the named engines' configuration removed (ablated)."""
    opts = options
    if "dependency" in engines:
        opts = replace(opts, dependency_policy=None)
    if "temporal" in engines:
        opts = replace(opts, temporal_envelopes=None, temporal_scope=None)
    if "institutional" in engines:
        opts = replace(opts, institutional_context=None, institutional_labels=())
    if "budget" in engines:
        opts = replace(opts, verification_ops=None, budget=None)
    return opts


def _admitted_full(item: AblationItem, disabled: frozenset[str]) -> bool:
    decision = admit_dtec(item.claim, item.graph, item.policy, _disable(item.options, disabled))
    return decision.outcome is AdmissionOutcome.ADMITTED


def _admitted_core(item: AblationItem) -> bool:
    return admit(item.graph, item.claim, item.policy).outcome is AdmissionOutcome.ADMITTED


def _acc_frac(items: tuple[AblationItem, ...], disabled: frozenset[str]) -> Fraction:
    """Exact detection accuracy as a rational (so Δ combinations are exact, not rounded)."""
    if not items:
        return Fraction(0)
    correct = sum(1 for it in items if _admitted_full(it, disabled) == it.should_admit)
    return Fraction(correct, len(items))


def _frac_to_decimal(value: Fraction) -> Decimal:
    return checked_div(Decimal(value.numerator), Decimal(value.denominator))


def detection_accuracy(
    items: tuple[AblationItem, ...], disabled: frozenset[str] = frozenset()
) -> Decimal:
    """Fraction of items whose DTEC admit/reject outcome matches ground truth (reported Decimal)."""
    return _frac_to_decimal(_acc_frac(items, disabled))


def interaction_delta(items: tuple[AblationItem, ...], engine_a: str, engine_b: str) -> Decimal:
    """Pairwise interaction ``Δ_ij = M(F) - M(F₋ᵢ) - M(F₋ⱼ) + M(F₋ᵢⱼ)`` (exact rational)."""
    full = _acc_frac(items, frozenset())
    without_a = _acc_frac(items, frozenset({engine_a}))
    without_b = _acc_frac(items, frozenset({engine_b}))
    without_both = _acc_frac(items, frozenset({engine_a, engine_b}))
    return _frac_to_decimal(full - without_a - without_b + without_both)


def run_ablation(items: tuple[AblationItem, ...] | None = None) -> AblationReport:
    """Run the full ablation and return measured deltas for each option-gated engine."""
    bench = items if items is not None else build_benchmark()
    full = _acc_frac(bench, frozenset())
    deltas = tuple(
        (engine, _frac_to_decimal(full - _acc_frac(bench, frozenset({engine}))))
        for engine in ABLATABLE_ENGINES
    )
    core_correct = sum(1 for it in bench if _admitted_core(it) == it.should_admit)
    return AblationReport(
        item_count=len(bench),
        full_accuracy=_frac_to_decimal(full),
        core_only_accuracy=(
            _frac_to_decimal(Fraction(core_correct, len(bench))) if bench else Decimal(0)
        ),
        engine_deltas=deltas,
    )
