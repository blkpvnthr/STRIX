"""Offline DTEC comparative-baseline evaluation harness (§5/§7/§8).

Where :mod:`strix.research_eval.dtec_ablation` measures each engine's *marginal
contribution* to end-to-end admission, this module measures each engine against the
**strongest applicable named baseline** on a synthetic, ground-truth-labelled benchmark,
and reports whether the §8 research target is met *on that benchmark*:

===========================  =====================================  ==================
Engine                       Baseline(s)                            §8 target
===========================  =====================================  ==================
R-N1 dependency detection    naive citation count, artifact-id      F1 ≥ 0.90
                             match, value-based dedup
R-N2 temporal selection      validity-only single-axis filter       accuracy ≥ 0.95,
                                                                    zero leakage
R-N4 calibration diagnostic  overconfident probability source       ECE ≤ 0.05
R-N3 compositional support   individual-claim (RAG-like) composer   unsupported-claim
                                                                    reduction ≥ 50%
R-N5 resource-bounded plan    FIFO / cheapest-first / utility-first  improved verified
                             / pure yield-maximizer                 yield at equal budget
===========================  =====================================  ==================

**Honesty contract.** Every number here is a deterministic offline measurement on
*constructed synthetic data*, reported with its denominator. The dependence/temporal
structure is expressed *structurally* in the benchmark (shared artifact nodes, explicit
availability stamps); near-ceiling DTEC scores therefore confirm the engine recovers
structurally-expressed ground truth that the baselines miss — they are **not** evidence
that the §8 targets hold on real corpora. Hidden non-structural dependence (CE-N1-1),
natural-language faithfulness, and a *production* calibration model remain open and
their live comparative arms are ``EXTERNALLY_BLOCKED`` (model credentials + budget).
No value here is pre-registered as a demonstrated outcome.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from itertools import combinations

from strix.assurance.calibration import CalibrationSample, expected_calibration_error
from strix.assurance.verification_planner import (
    ResourceBudget,
    VerificationOp,
    plan_verification,
)
from strix.evidence_graph.calculus import (
    Conclusion,
    FormalEncoding,
    SupportBalance,
    admit_conclusion,
)
from strix.evidence_graph.dependency import estimate_dependence
from strix.evidence_graph.graph import EvidenceGraph
from strix.evidence_graph.inference import And, Atom, Const, Implies
from strix.evidence_graph.nodes import (
    AdmissionOutcome,
    RelationshipKind,
    SourceObservation,
    make_edge,
    make_source_observation,
)
from strix.evidence_graph.temporal import TemporalEnvelope, TemporalInterval, TemporalScope
from strix.evidence_graph.temporal import is_admissible as temporal_is_admissible
from strix.models import SourceArtifact, SourceType, StrixModel
from strix.native.arithmetic import checked_div

__all__ = [
    "BaselineComparison",
    "BinaryClassMetrics",
    "CalibrationEvalResult",
    "CompositionalEvalResult",
    "ConclusionCase",
    "DTECBaselineReport",
    "DependencyEvalResult",
    "DependencyPair",
    "PlannerEvalResult",
    "PlanningInstance",
    "TemporalCase",
    "TemporalEvalResult",
    "artifact_id_match_predicts_dependent",
    "availability_only_admits_temporal",
    "brute_force_optimum",
    "composite_match_predicts_dependent",
    "conclusion_benchmark",
    "confusion_metrics",
    "contradiction_aware_admits_conclusion",
    "cost_ascending_select",
    "dependency_benchmark",
    "dtec_predicts_dependent",
    "dtec_ratio_select",
    "evaluate_calibration",
    "evaluate_compositional_support",
    "evaluate_dependency_detection",
    "evaluate_resource_planning",
    "evaluate_temporal_selection",
    "fifo_select",
    "individual_claim_admits_conclusion",
    "null_floor_predicts_dependent",
    "planning_benchmark",
    "run_dtec_baselines",
    "selected_utility",
    "semantic_tuple_match_predicts_dependent",
    "temporal_benchmark",
    "utility_descending_select",
    "validity_only_admits_temporal",
    "value_dedup_predicts_dependent",
    "yield_maximizer_select",
]

_T0 = datetime(2024, 1, 1, tzinfo=UTC)

_OFFLINE_NOTE = (
    "Offline synthetic comparative measurement — real deterministic measurements with "
    "denominators, NOT live H1-H12 validation. Live comparative arms EXTERNALLY_BLOCKED "
    "(model credentials + budget); no value here is a demonstrated-on-real-corpora outcome."
)


# --------------------------------------------------------------------------
# Metric arithmetic (exact rationals -> reported Decimals)
# --------------------------------------------------------------------------


def _frac_to_decimal(value: Fraction) -> Decimal:
    return checked_div(Decimal(value.numerator), Decimal(value.denominator))


class BinaryClassMetrics(StrixModel):
    """Exact binary-classification metrics for the positive (``dependent``/``admit``) class."""

    positive_label: str
    tp: int
    fp: int
    fn: int
    tn: int
    precision: Decimal
    recall: Decimal
    f1: Decimal
    accuracy: Decimal


def confusion_metrics(
    predictions: list[tuple[bool, bool]], *, positive_label: str = "positive"
) -> BinaryClassMetrics:
    """Compute exact P/R/F1/accuracy from ``(predicted_positive, actual_positive)`` pairs.

    Degenerate denominators are defined as ``0`` (never a division error): precision is
    ``0`` when nothing is predicted positive, recall ``0`` when there is no positive, F1
    ``0`` when both are empty. Accuracy requires at least one observation.
    """
    if not predictions:
        raise ValueError("confusion_metrics requires at least one observation")
    tp = sum(1 for pred, act in predictions if pred and act)
    fp = sum(1 for pred, act in predictions if pred and not act)
    fn = sum(1 for pred, act in predictions if not pred and act)
    tn = sum(1 for pred, act in predictions if not pred and not act)
    precision = _frac_to_decimal(Fraction(tp, tp + fp)) if (tp + fp) else Decimal(0)
    recall = _frac_to_decimal(Fraction(tp, tp + fn)) if (tp + fn) else Decimal(0)
    f1 = (
        _frac_to_decimal(Fraction(2 * tp, 2 * tp + fp + fn))
        if (2 * tp + fp + fn)
        else Decimal(0)
    )
    accuracy = _frac_to_decimal(Fraction(tp + tn, len(predictions)))
    return BinaryClassMetrics(
        positive_label=positive_label,
        tp=tp, fp=fp, fn=fn, tn=tn,
        precision=precision, recall=recall, f1=f1, accuracy=accuracy,
    )


class BaselineComparison(StrixModel):
    """A named baseline's metrics, for side-by-side comparison against DTEC."""

    name: str
    metrics: BinaryClassMetrics


# --------------------------------------------------------------------------
# R-N1 — evidence dependency detection
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DependencyPair:
    """One labelled evidence pair: the graph plus construction-defined ground truth."""

    name: str
    attack_class: str
    graph: EvidenceGraph
    id_i: str
    id_j: str
    value_i: Decimal
    value_j: Decimal
    artifact_i: str
    artifact_j: str
    dependent: bool


def _artifact(aid: str, content_hash: str) -> SourceArtifact:
    return SourceArtifact(
        artifact_id=aid, source_type=SourceType.SYNTHETIC_FIXTURE, source_name=f"{aid}.json",
        source_version="v1", content_hash=content_hash, known_at=_T0,
        local_path=f"raw/{aid}.json", byte_size=100,
    )


def _obs(oid_subject: str, concept: str, value: str, aid: str, locator: str) -> SourceObservation:
    return make_source_observation(
        subject_id=oid_subject, concept=concept, value=Decimal(value), unit="ratio",
        observation_period="FY2023", observed_at=_T0, available_at=_T0,
        source_artifact_id=aid, source_locator=locator,
    )


def _hash(tag: str) -> str:
    """A distinct 64-hex content hash per tag (distinct origins must differ).

    A deterministic polynomial fold of the tag into a 64-hex string (matches the
    ``^[0-9a-f]{64}$`` content-hash contract); distinct tags yield distinct hashes.
    """
    acc = 0
    for ch in tag:
        acc = (acc * 131 + ord(ch)) % (16**16)
    return f"{acc:064x}"


def _pair(
    name: str, attack_class: str, nodes: list[SourceObservation | SourceArtifact],
    edges: list[tuple[str, str, RelationshipKind]], id_i: str, id_j: str,
    value_i: str, value_j: str, artifact_i: str, artifact_j: str, dependent: bool,
) -> DependencyPair:
    g = EvidenceGraph()
    for node in nodes:
        g.add_node(node)
    for src, dst, kind in edges:
        g.add_edge(make_edge(kind, src, dst))
    return DependencyPair(
        name=name, attack_class=attack_class, graph=g, id_i=id_i, id_j=id_j,
        value_i=Decimal(value_i), value_j=Decimal(value_j),
        artifact_i=artifact_i, artifact_j=artifact_j, dependent=dependent,
    )


def dependency_benchmark() -> tuple[DependencyPair, ...]:
    """Synthetic pairs spanning dependent/independent classes with naive-baseline confounders."""
    pairs: list[DependencyPair] = []

    # shared_origin_same_value: one artifact, two observations, identical fact (DEPENDENT).
    art = _artifact("ART-1", _hash("art1"))
    o1 = _obs("ACME", "operating_margin", "0.25", "ART-1", "/0")
    o2 = _obs("ACME", "operating_margin", "0.25", "ART-1", "/1")
    pairs.append(_pair(
        "shared-same", "shared_origin_same_value", [art, o1, o2],
        [(o1.observation_id, "ART-1", RelationshipKind.EXTRACTED_FROM),
         (o2.observation_id, "ART-1", RelationshipKind.EXTRACTED_FROM)],
        o1.observation_id, o2.observation_id, "0.25", "0.25", "ART-1", "ART-1", True,
    ))

    # shared_origin_diff_value: one artifact, two observations, DIFFERENT values (DEPENDENT).
    # value-dedup MISSES this; DTEC catches it via shared provenance.
    art2 = _artifact("ART-2", _hash("art2"))
    a1 = _obs("ACME", "operating_margin", "0.25", "ART-2", "/0")
    a2 = _obs("ACME", "gross_margin", "0.40", "ART-2", "/1")
    pairs.append(_pair(
        "shared-diff", "shared_origin_diff_value", [art2, a1, a2],
        [(a1.observation_id, "ART-2", RelationshipKind.EXTRACTED_FROM),
         (a2.observation_id, "ART-2", RelationshipKind.EXTRACTED_FROM)],
        a1.observation_id, a2.observation_id, "0.25", "0.40", "ART-2", "ART-2", True,
    ))

    # semantic_duplicate: SAME fact from DIFFERENT artifacts (restated) (DEPENDENT).
    art3 = _artifact("ART-3", _hash("art3"))
    art4 = _artifact("ART-4", _hash("art4"))
    s1 = _obs("ACME", "operating_margin", "0.25", "ART-3", "/0")
    s2 = _obs("ACME", "operating_margin", "0.25", "ART-4", "/0")
    pairs.append(_pair(
        "semantic-dup", "semantic_duplicate", [art3, art4, s1, s2],
        [(s1.observation_id, "ART-3", RelationshipKind.EXTRACTED_FROM),
         (s2.observation_id, "ART-4", RelationshipKind.EXTRACTED_FROM)],
        s1.observation_id, s2.observation_id, "0.25", "0.25", "ART-3", "ART-4", True,
    ))

    # lineage: one observation DERIVED_FROM the other (DEPENDENT). Both naive baselines miss.
    art5 = _artifact("ART-5", _hash("art5"))
    base_obs = _obs("ACME", "revenue", "100", "ART-5", "/0")
    derived = _obs("ACME", "revenue_restated", "100", "ART-5", "/1")
    pairs.append(_pair(
        "lineage", "lineage", [art5, base_obs, derived],
        [(base_obs.observation_id, "ART-5", RelationshipKind.EXTRACTED_FROM),
         (derived.observation_id, base_obs.observation_id, RelationshipKind.DERIVED_FROM)],
        base_obs.observation_id, derived.observation_id, "100", "100", "ART-5", "ART-5", True,
    ))

    # disjoint_diff_value: different artifacts, different values (INDEPENDENT). All correct.
    art6 = _artifact("ART-6", _hash("art6"))
    art7 = _artifact("ART-7", _hash("art7"))
    d1 = _obs("ACME", "operating_margin", "0.25", "ART-6", "/0")
    d2 = _obs("BETA", "operating_margin", "0.31", "ART-7", "/0")
    pairs.append(_pair(
        "disjoint-diff", "disjoint_diff_value", [art6, art7, d1, d2],
        [(d1.observation_id, "ART-6", RelationshipKind.EXTRACTED_FROM),
         (d2.observation_id, "ART-7", RelationshipKind.EXTRACTED_FROM)],
        d1.observation_id, d2.observation_id, "0.25", "0.31", "ART-6", "ART-7", False,
    ))

    # disjoint_same_value: different artifacts/subjects, COINCIDENTALLY equal value
    # (INDEPENDENT). value-dedup FALSE POSITIVE; DTEC correct via disjoint provenance.
    art8 = _artifact("ART-8", _hash("art8"))
    art9 = _artifact("ART-9", _hash("art9"))
    c1 = _obs("ACME", "operating_margin", "0.25", "ART-8", "/0")
    c2 = _obs("BETA", "operating_margin", "0.25", "ART-9", "/0")
    pairs.append(_pair(
        "disjoint-same", "disjoint_same_value", [art8, art9, c1, c2],
        [(c1.observation_id, "ART-8", RelationshipKind.EXTRACTED_FROM),
         (c2.observation_id, "ART-9", RelationshipKind.EXTRACTED_FROM)],
        c1.observation_id, c2.observation_id, "0.25", "0.25", "ART-8", "ART-9", False,
    ))

    # same_hash_diff_artifact_id: two artifacts with IDENTICAL content bytes (same
    # content_hash) registered under different ids, different subjects/values (DEPENDENT —
    # the same source document re-registered twice). DTEC canonicalizes origins by
    # content_hash (dependency.py:_upstream_set) and catches it; the fair composite
    # (artifact-id OR semantic-tuple) MISSES it — ids differ AND semantic tuples differ.
    # This is the one case where DTEC genuinely SEPARATES from the strongest fair baseline:
    # the ground truth (same bytes ⇒ dependent) is fixed by the generating process, not by
    # the engine's rule, and only hash canonicalization recovers it.
    shared_hash = _hash("sharedbytes")
    art10 = _artifact("ART-10", shared_hash)
    art11 = _artifact("ART-11", shared_hash)
    h1 = _obs("ACME", "revenue", "100", "ART-10", "/0")
    h2 = _obs("BETA", "headcount", "200", "ART-11", "/0")
    pairs.append(_pair(
        "same-hash", "same_hash_diff_artifact_id", [art10, art11, h1, h2],
        [(h1.observation_id, "ART-10", RelationshipKind.EXTRACTED_FROM),
         (h2.observation_id, "ART-11", RelationshipKind.EXTRACTED_FROM)],
        h1.observation_id, h2.observation_id, "100", "200", "ART-10", "ART-11", True,
    ))
    return tuple(pairs)


def dtec_predicts_dependent(pair: DependencyPair) -> bool:
    """DTEC prediction: the structural estimator finds positive (or unresolvable) dependence.

    Dependent iff the interval estimate is unresolved (dependence cannot be excluded) or
    has a positive lower bound; independent only on a resolved, disjoint ``[0, 0]``.
    """
    est = estimate_dependence(pair.graph, pair.id_i, pair.id_j)
    return (not est.resolved) or est.lower > 0


def null_floor_predicts_dependent(pair: DependencyPair) -> bool:
    """Floor reference (NOT a steelman): constant-False on distinct-id pairs.

    Models "each distinct citation is an independent source". Included only as a lower-bound
    reference so the informative baselines are read against a floor, never as a baseline DTEC
    "beats".
    """
    return pair.id_i == pair.id_j


def artifact_id_match_predicts_dependent(pair: DependencyPair) -> bool:
    """Baseline (provenance-lite): dependent iff the declared source artifact ids match."""
    return pair.artifact_i == pair.artifact_j


def value_dedup_predicts_dependent(pair: DependencyPair) -> bool:
    """Naive baseline (value-only dedup): dependent iff the asserted values are equal."""
    return pair.value_i.normalize() == pair.value_j.normalize()


def _semantic_tuple(pair: DependencyPair, oid: str) -> tuple[str, str, str, str] | None:
    node = pair.graph.node(oid)
    if isinstance(node, SourceObservation):
        return (node.subject_id, node.concept, node.unit, str(node.value.normalize()))
    return None


def semantic_tuple_match_predicts_dependent(pair: DependencyPair) -> bool:
    """Fair baseline (record-linkage dedup): dependent iff ``(subject,concept,unit,value)`` match.

    Stronger than value-only dedup — it does not false-positive on coincidentally equal
    values across different subjects (the standard key a competent deduplicator uses).
    """
    t_i = _semantic_tuple(pair, pair.id_i)
    t_j = _semantic_tuple(pair, pair.id_j)
    return t_i is not None and t_i == t_j


def composite_match_predicts_dependent(pair: DependencyPair) -> bool:
    """Strongest FAIR baseline: artifact-id match OR semantic-tuple match.

    The composite a competent entity-resolution engineer would actually deploy. It catches
    every dependent class on this benchmark EXCEPT hash-canonicalized shared origin (same
    content bytes under different artifact ids with different semantics) — the one case that
    requires DTEC's content-hash canonicalization.
    """
    return artifact_id_match_predicts_dependent(pair) or semantic_tuple_match_predicts_dependent(
        pair
    )


class DependencyEvalResult(StrixModel):
    """Dependency-detection measurement.

    ``dtec`` is a **consistency check** (DTEC recovers the structural labels it was handed);
    the informative content is the baseline failure rates and whether DTEC **separates from
    the strongest FAIR baseline** (``composite_match``) on the hash-canonicalization case.
    ``dtec_meets_target`` therefore records label-recovery consistency, not a §8 capability
    measurement (which requires the live corpora).
    """

    item_count: int
    dtec: BinaryClassMetrics
    baselines: tuple[BaselineComparison, ...]
    strongest_baseline_name: str
    strongest_baseline_f1: Decimal
    dtec_separates_from_strongest: bool
    target_f1: Decimal
    dtec_meets_target: bool
    note: str = (
        "DTEC-vs-label is a consistency/regression check (not a §8 capability measurement). "
        + _OFFLINE_NOTE
    )


def evaluate_dependency_detection() -> DependencyEvalResult:
    bench = dependency_benchmark()

    def metrics_for(predict: Callable[[DependencyPair], bool]) -> BinaryClassMetrics:
        preds = [(predict(p), p.dependent) for p in bench]
        return confusion_metrics(preds, positive_label="dependent")

    dtec = metrics_for(dtec_predicts_dependent)
    baselines = tuple(
        BaselineComparison(name=name, metrics=metrics_for(predict))
        for name, predict in (
            ("null_floor", null_floor_predicts_dependent),
            ("value_dedup", value_dedup_predicts_dependent),
            ("artifact_id_match", artifact_id_match_predicts_dependent),
            ("semantic_tuple_match", semantic_tuple_match_predicts_dependent),
            ("composite_match", composite_match_predicts_dependent),
        )
    )
    strongest = max(baselines, key=lambda b: b.metrics.f1)
    target = Decimal("0.90")
    return DependencyEvalResult(
        item_count=len(bench), dtec=dtec, baselines=baselines,
        strongest_baseline_name=strongest.name,
        strongest_baseline_f1=strongest.metrics.f1,
        dtec_separates_from_strongest=dtec.f1 > strongest.metrics.f1,
        target_f1=target, dtec_meets_target=dtec.f1 >= target,
    )


# --------------------------------------------------------------------------
# R-N2 — bitemporal evidence selection
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TemporalCase:
    """One labelled temporal scenario with construction-defined admissibility + leak flag."""

    name: str
    envelope: TemporalEnvelope
    scope: TemporalScope
    admissible: bool
    is_future_leak: bool


def _interval(start_days: int, end_days: int) -> TemporalInterval:
    return TemporalInterval(
        start=_T0 + timedelta(days=start_days), end=_T0 + timedelta(days=end_days)
    )


def temporal_benchmark() -> tuple[TemporalCase, ...]:
    """Valid, future-availability-leak, and validity-expired scenarios."""
    cases: list[TemporalCase] = []
    # Query as-of knowledge_time = day 50, valid_time = day 50.
    scope = TemporalScope(
        valid_time=_T0 + timedelta(days=50), knowledge_time=_T0 + timedelta(days=50)
    )
    for i in range(2):
        # valid: available before t_k; validity & knowledge contain the query -> ADMISSIBLE.
        cases.append(TemporalCase(
            f"valid-{i}",
            TemporalEnvelope(
                evidence_id=f"V{i}", validity=_interval(0, 100), knowledge=_interval(0, 100),
                available_at=_T0 + timedelta(days=10),
            ),
            scope, admissible=True, is_future_leak=False,
        ))
        # future_avail_leak: available AFTER t_k but validity still contains t_v. A validity-
        # only filter admits this (leak); DTEC's availability gate rejects it.
        cases.append(TemporalCase(
            f"leak-{i}",
            TemporalEnvelope(
                evidence_id=f"L{i}", validity=_interval(0, 100), knowledge=_interval(0, 100),
                available_at=_T0 + timedelta(days=90),
            ),
            scope, admissible=False, is_future_leak=True,
        ))
        # validity_expired: t_v outside the validity interval -> INADMISSIBLE (both agree).
        cases.append(TemporalCase(
            f"expired-{i}",
            TemporalEnvelope(
                evidence_id=f"E{i}", validity=_interval(60, 100), knowledge=_interval(0, 100),
                available_at=_T0 + timedelta(days=10),
            ),
            scope, admissible=False, is_future_leak=False,
        ))
    return tuple(cases)


def dtec_admits_temporal(case: TemporalCase) -> bool:
    """DTEC prediction via the two-axis gate (availability checked first)."""
    return temporal_is_admissible(case.envelope, case.scope)[0] is True


def validity_only_admits_temporal(case: TemporalCase) -> bool:
    """Single-axis baseline A (validity-only): ignores availability and knowledge time.

    Admits future-availability leaks whose validity still covers the query time.
    """
    return case.envelope.validity.contains(case.scope.valid_time)


def availability_only_admits_temporal(case: TemporalCase) -> bool:
    """Single-axis baseline B (availability/as-of only): admits iff ``a_i ≤ t_k``.

    The canonical anti-lookahead filter (STRIX's own pre-existing knowledge-axis predicate).
    Achieves zero leakage but admits validity-expired evidence (no validity axis), so it
    cannot meet the joint accuracy∧zero-leak objective either.
    """
    a = case.envelope.available_at
    return a is not None and a <= case.scope.knowledge_time


class TemporalEvalResult(StrixModel):
    """Temporal-selection measurement.

    The informative result is NOT that DTEC scores perfectly (its labels are its own gate —
    a consistency check), but that **neither single axis meets the joint objective**
    (accuracy ≥ target AND zero leakage): validity-only leaks; availability-only loses
    accuracy on expired validity. Only the two-axis gate meets both.
    """

    item_count: int
    dtec_accuracy: Decimal
    validity_only_accuracy: Decimal
    availability_only_accuracy: Decimal
    dtec_leaks: int
    validity_only_leaks: int
    availability_only_leaks: int
    target_accuracy: Decimal
    dtec_meets_target: bool
    dtec_zero_leak: bool
    no_single_axis_meets_joint: bool
    two_axis_required: bool
    note: str = (
        "DTEC-vs-label is a consistency check; the informative result is that no single axis "
        "meets the joint accuracy∧zero-leak objective. " + _OFFLINE_NOTE
    )


def evaluate_temporal_selection() -> TemporalEvalResult:
    bench = temporal_benchmark()
    n = len(bench)

    def acc(predict: Callable[[TemporalCase], bool]) -> Decimal:
        return _frac_to_decimal(Fraction(sum(1 for c in bench if predict(c) == c.admissible), n))

    def leaks(predict: Callable[[TemporalCase], bool]) -> int:
        return sum(1 for c in bench if c.is_future_leak and predict(c))

    target = Decimal("0.95")
    dtec_acc = acc(dtec_admits_temporal)
    val_acc, avail_acc = acc(validity_only_admits_temporal), acc(availability_only_admits_temporal)
    dtec_leaks, val_leaks = leaks(dtec_admits_temporal), leaks(validity_only_admits_temporal)
    avail_leaks = leaks(availability_only_admits_temporal)
    dtec_meets = dtec_acc >= target and dtec_leaks == 0
    val_joint = val_acc >= target and val_leaks == 0
    avail_joint = avail_acc >= target and avail_leaks == 0
    no_single = not (val_joint or avail_joint)
    return TemporalEvalResult(
        item_count=n,
        dtec_accuracy=dtec_acc,
        validity_only_accuracy=val_acc,
        availability_only_accuracy=avail_acc,
        dtec_leaks=dtec_leaks, validity_only_leaks=val_leaks, availability_only_leaks=avail_leaks,
        target_accuracy=target,
        dtec_meets_target=dtec_acc >= target,
        dtec_zero_leak=dtec_leaks == 0,
        no_single_axis_meets_joint=no_single,
        two_axis_required=dtec_meets and no_single,
    )


# --------------------------------------------------------------------------
# R-N4 — calibration diagnostic
# --------------------------------------------------------------------------


def _calibrated_samples() -> tuple[CalibrationSample, ...]:
    """A well-calibrated supplied source: per-confidence-level empirical accuracy ≈ p̂."""
    samples: list[CalibrationSample] = []
    # For p in {0.1,...,0.9}: 10 samples each, #positives = round(10*p) -> ECE ~ 0.
    for tenth in range(1, 10):
        p = Decimal(tenth) / Decimal(10)
        positives = tenth  # exactly 10*p of 10
        for k in range(10):
            samples.append(CalibrationSample(prediction=p, label=1 if k < positives else 0))
    return tuple(samples)


def _overconfident_samples() -> tuple[CalibrationSample, ...]:
    """An overconfident supplied source: predicts 0.95 but is right only ~60% of the time."""
    samples: list[CalibrationSample] = []
    p = Decimal("0.95")
    for k in range(100):
        samples.append(CalibrationSample(prediction=p, label=1 if k < 60 else 0))
    return tuple(samples)


class CalibrationEvalResult(StrixModel):
    """Calibration-diagnostic measurement: the ECE metric discriminates the two sources."""

    calibrated_ece: Decimal
    overconfident_ece: Decimal
    target_ece: Decimal
    calibrated_meets_target: bool
    diagnostic_discriminates: bool
    note: str = (
        "Metric-validation only (NOT a comparative method arm): the exact ECE metric correctly "
        "scores a calibrated source ≤ target and flags an overconfident one. This does NOT claim "
        "STRIX's production reliability model is calibrated — fitting p̂ on independent real labels "
        "is EXTERNALLY_BLOCKED (model credentials + budget). " + _OFFLINE_NOTE
    )


def evaluate_calibration() -> CalibrationEvalResult:
    calibrated_ece = expected_calibration_error(_calibrated_samples())
    overconfident_ece = expected_calibration_error(_overconfident_samples())
    target = Decimal("0.05")
    return CalibrationEvalResult(
        calibrated_ece=calibrated_ece,
        overconfident_ece=overconfident_ece,
        target_ece=target,
        calibrated_meets_target=calibrated_ece <= target,
        diagnostic_discriminates=calibrated_ece <= target < overconfident_ece,
    )


# --------------------------------------------------------------------------
# R-N3 — compositional unsupported-claim reduction
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ConclusionCase:
    """A conclusion with ALL premises individually admitted; ``supported`` is the truth."""

    name: str
    conclusion: Conclusion
    premise_admissions: dict[str, AdmissionOutcome]
    satisfied_context: frozenset[str] = field(default_factory=frozenset)
    supported: bool = True


def conclusion_benchmark() -> tuple[ConclusionCase, ...]:
    """Supported and (premises-valid-but-)unsupported conclusions."""
    admitted = {"c1": AdmissionOutcome.ADMITTED}
    cases: list[ConclusionCase] = []

    # supported (formally entailed): p, p->q |= q.
    cases.append(ConclusionCase(
        "entailed",
        Conclusion(
            conclusion_id="K1", proposition="q holds", premise_claim_ids=("c1",),
            formal=FormalEncoding(
                context=Const(True), premises=And((Atom("p"), Implies(Atom("p"), Atom("q")))),
                conclusion=Atom("q"),
            ),
        ),
        dict(admitted), supported=True,
    ))

    # supported (empirical): no formal encoding, premise admitted, no opposition.
    cases.append(ConclusionCase(
        "empirical_supported",
        Conclusion(conclusion_id="K2", proposition="trend", premise_claim_ids=("c1",)),
        dict(admitted), supported=True,
    ))

    # unsupported (not entailed): premise admitted but p ⊭ q (counterexample exists) -> R FAIL.
    cases.append(ConclusionCase(
        "not_entailed",
        Conclusion(
            conclusion_id="K3", proposition="q holds", premise_claim_ids=("c1",),
            formal=FormalEncoding(context=Const(True), premises=Atom("p"), conclusion=Atom("q")),
        ),
        dict(admitted), supported=False,
    ))

    # unsupported (missing context): required assumption not satisfied -> K FAIL.
    cases.append(ConclusionCase(
        "missing_context",
        Conclusion(
            conclusion_id="K4", proposition="applies here", premise_claim_ids=("c1",),
            assumptions=("jurisdiction_us",),
        ),
        dict(admitted), satisfied_context=frozenset(), supported=False,
    ))

    # unsupported (unfaithful): a substantive opposing contradiction -> F FAIL.
    cases.append(ConclusionCase(
        "unfaithful",
        Conclusion(
            conclusion_id="K5", proposition="net positive", premise_claim_ids=("c1",),
            balance=SupportBalance(supporting=("c1",), opposing=("x",), substantive_conflict=True),
        ),
        dict(admitted), supported=False,
    ))
    return tuple(cases)


def dtec_admits_conclusion(case: ConclusionCase) -> bool:
    """DTEC prediction via ``A_C = (⋀A(c_i)) ∧ R ∧ K ∧ F``."""
    decision = admit_conclusion(
        case.conclusion, case.premise_admissions, satisfied_context=case.satisfied_context
    )
    return decision.outcome is AdmissionOutcome.ADMITTED


def individual_claim_admits_conclusion(case: ConclusionCase) -> bool:
    """Naive baseline (RAG-like): admit iff every premise is individually admitted."""
    return all(
        case.premise_admissions.get(pid) is AdmissionOutcome.ADMITTED
        for pid in case.conclusion.premise_claim_ids
    ) and bool(case.conclusion.premise_claim_ids)


def contradiction_aware_admits_conclusion(case: ConclusionCase) -> bool:
    """Stronger baseline: all premises admitted AND no flagged substantive opposition.

    Common in production retrieval stacks. It catches the ``unfaithful`` (substantive
    contradiction) case, but still has no inference (R) or context (K) check, so it admits
    the not-entailed and missing-context unsupported conclusions that A_C rejects.
    """
    if not individual_claim_admits_conclusion(case):
        return False
    bal = case.conclusion.balance
    return not (bal.opposing and bal.substantive_conflict)


class CompositionalEvalResult(StrixModel):
    """Unsupported-claim-reduction measurement vs TWO baselines (naive + contradiction-aware).

    DTEC rejecting every unsupported conclusion is a consistency check (each is built to trip
    exactly one A_C predicate). The informative result is that even the STRONGER
    contradiction-aware baseline admits the R (entailment) and K (context) failures it cannot
    see. ``reduction_vs_strongest`` is the honest headline; the not-entailed case additionally
    has a genuine external oracle (propositional entailment), the K/F cases do not.
    """

    item_count: int
    unsupported_count: int
    individual_claim_admit_rate: Decimal
    contradiction_aware_admit_rate: Decimal
    dtec_admit_rate: Decimal
    reduction_vs_individual: Decimal
    reduction_vs_strongest: Decimal
    target_reduction: Decimal
    meets_target: bool
    note: str = (
        "DTEC-vs-label is a consistency check; the informative result is that even a "
        "contradiction-aware baseline admits R/K failures A_C rejects. " + _OFFLINE_NOTE
    )


def evaluate_compositional_support() -> CompositionalEvalResult:
    bench = conclusion_benchmark()
    unsupported = [c for c in bench if not c.supported]
    n = len(unsupported)
    naive_admits = sum(1 for c in unsupported if individual_claim_admits_conclusion(c))
    strong_admits = sum(1 for c in unsupported if contradiction_aware_admits_conclusion(c))
    dtec_admits = sum(1 for c in unsupported if dtec_admits_conclusion(c))

    def rate(count: int) -> Decimal:
        return _frac_to_decimal(Fraction(count, n)) if n else Decimal(0)

    def reduction(baseline: Callable[[ConclusionCase], bool]) -> Decimal:
        # Direct set difference (matches the docstring, robust even if DTEC-admits were not a
        # subset of baseline-admits): of the unsupported conclusions the baseline admits, the
        # fraction DTEC rejects.
        admitted = [c for c in unsupported if baseline(c)]
        if not admitted:
            return Decimal(0)
        rejected_by_dtec = sum(1 for c in admitted if not dtec_admits_conclusion(c))
        return _frac_to_decimal(Fraction(rejected_by_dtec, len(admitted)))

    target = Decimal("0.50")
    red_strong = reduction(contradiction_aware_admits_conclusion)
    return CompositionalEvalResult(
        item_count=len(bench), unsupported_count=n,
        individual_claim_admit_rate=rate(naive_admits),
        contradiction_aware_admit_rate=rate(strong_admits),
        dtec_admit_rate=rate(dtec_admits),
        reduction_vs_individual=reduction(individual_claim_admits_conclusion),
        reduction_vs_strongest=red_strong,
        target_reduction=target, meets_target=red_strong >= target,
    )


# --------------------------------------------------------------------------
# R-N5 — resource-bounded verification: equal-budget yield vs naive strategies
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanningInstance:
    """One verification-planning instance: candidate ops and a scalar budget."""

    name: str
    ops: tuple[VerificationOp, ...]
    budget: ResourceBudget


def _op(op_id: str, utility: str, cost: str, *, mandatory: bool = False) -> VerificationOp:
    return VerificationOp(
        op_id=op_id, utility=Decimal(utility), cost=Decimal(cost), mandatory=mandatory
    )


def planning_benchmark() -> tuple[PlanningInstance, ...]:
    """Prereq-free synthetic instances where the strategies genuinely diverge."""
    return (
        # beats_fifo: a bad item listed first starves FIFO; ratio/cost/util recover.
        PlanningInstance(
            "beats_fifo",
            (_op("a_bad", "1", "5"), _op("b_hi", "4", "2"), _op("c_hi", "4", "2")),
            ResourceBudget(total=Decimal("5")),
        ),
        # beats_utility_first: a big high-utility low-ratio item starves utility-first.
        PlanningInstance(
            "beats_utility_first",
            (_op("a_hi", "4", "2"), _op("b_hi", "4", "2"), _op("c_big", "5", "5")),
            ResourceBudget(total=Decimal("5")),
        ),
        # knapsack_suboptimal: equal ratios; greedy-ratio picks the big item and wastes
        # budget, where cheapest-first reaches the optimum. Honest negative for the heuristic.
        PlanningInstance(
            "knapsack_suboptimal",
            (_op("a_big", "3", "3"), _op("b_sm", "2", "2"), _op("c_sm", "2", "2")),
            ResourceBudget(total=Decimal("4")),
        ),
        # cost_ascending_fails: many cheap low-value items crowd out one high-value item;
        # cheapest-first and FIFO take the junk, ratio/utility take the prize.
        PlanningInstance(
            "cost_ascending_fails",
            (*(_op(f"s{i}", "1", "1") for i in range(6)), _op("z_prize", "10", "6")),
            ResourceBudget(total=Decimal("6")),
        ),
    )


def _mandatory_instance() -> PlanningInstance:
    """A mandatory low-ratio op that a pure yield-maximizer would drop to fit optional ops."""
    return PlanningInstance(
        "mandatory_safety",
        (_op("m_mand", "1", "3", mandatory=True), _op("h1", "3", "2"), _op("h2", "3", "2")),
        ResourceBudget(total=Decimal("5")),
    )


def _pack(ordered_ops: tuple[VerificationOp, ...], budget: ResourceBudget) -> frozenset[str]:
    """Greedily take ops in the given order while they fit the budget (prereq-free)."""
    selected: set[str] = set()
    spent = Decimal(0)
    total = Decimal(budget.total)
    for op in ordered_ops:
        cost = Decimal(op.cost)
        if spent + cost <= total:
            selected.add(op.op_id)
            spent += cost
    return frozenset(selected)


def _ratio_key(op: VerificationOp) -> tuple[int, Fraction, str]:
    if Decimal(op.cost) == 0:
        return (0, Fraction(0), op.op_id)
    return (1, -Fraction(Decimal(op.utility)) / Fraction(Decimal(op.cost)), op.op_id)


def dtec_ratio_select(instance: PlanningInstance) -> frozenset[str]:
    """DTEC prediction: the mandatory-first greedy value/cost-ratio planner (``M_B``)."""
    return frozenset(plan_verification(instance.ops, instance.budget).selected)


def fifo_select(instance: PlanningInstance) -> frozenset[str]:
    """Baseline: take ops in declaration order until the budget is exhausted."""
    return _pack(instance.ops, instance.budget)


def cost_ascending_select(instance: PlanningInstance) -> frozenset[str]:
    """Baseline: cheapest-first."""
    return _pack(
        tuple(sorted(instance.ops, key=lambda o: (Decimal(o.cost), o.op_id))), instance.budget
    )


def utility_descending_select(instance: PlanningInstance) -> frozenset[str]:
    """Baseline: highest-utility-first (ignores cost)."""
    return _pack(
        tuple(sorted(instance.ops, key=lambda o: (-Decimal(o.utility), o.op_id))), instance.budget
    )


def yield_maximizer_select(instance: PlanningInstance) -> frozenset[str]:
    """Unsafe baseline: pure value/cost-ratio greedy that IGNORES the mandatory flag.

    Identical selection rule to the DTEC planner's *optional* ordering, but without the
    mandatory-first guarantee — so it will drop an expensive low-ratio mandatory op to fit
    higher-ratio optional ops. Included to demonstrate the safety property DTEC adds.
    """
    return _pack(tuple(sorted(instance.ops, key=_ratio_key)), instance.budget)


def selected_utility(ops: tuple[VerificationOp, ...], selected: frozenset[str]) -> Decimal:
    chosen = [Decimal(op.utility) for op in ops if op.op_id in selected]
    return sum(chosen, Decimal(0))


def brute_force_optimum(instance: PlanningInstance) -> Decimal:
    """The exact budget-feasible maximum utility (respecting mandatory inclusion)."""
    total = Decimal(instance.budget.total)
    mandatory = {op.op_id for op in instance.ops if op.mandatory}
    best = Decimal(0)
    for r in range(len(instance.ops) + 1):
        for combo in combinations(instance.ops, r):
            ids = {op.op_id for op in combo}
            if not mandatory <= ids:
                continue
            if sum((Decimal(op.cost) for op in combo), Decimal(0)) <= total:
                util = sum((Decimal(op.utility) for op in combo), Decimal(0))
                best = max(best, util)
    return best


class PlannerEvalResult(StrixModel):
    """Equal-budget verified-yield measurement vs naive strategies, with an honest negative.

    ``strategy_mean_yield_fraction`` is each strategy's mean (achieved utility / brute-force
    optimum) across the prereq-free yield instances. The greedy value/cost-ratio planner has
    the highest mean but is **not** universally optimal (``suboptimality_case``). Its genuine
    safety advantage is ``dtec_mandatory_safe`` ∧ ``yield_maximizer_drops_mandatory``.
    """

    instance_count: int
    strategy_mean_yield_fraction: tuple[tuple[str, Decimal], ...]
    greedy_not_universally_optimal: bool
    suboptimality_case: str
    dtec_mandatory_safe: bool
    yield_maximizer_drops_mandatory: bool
    note: str = (
        "Equal-budget comparison of genuinely different selection strategies (NOT circular — "
        "yield is an objective output measurement). Greedy-ratio leads on mean yield but is a "
        "heuristic, not optimal (documented counterexample); its decisive advantage is mandatory "
        "safety, which a pure yield-maximizer violates. " + _OFFLINE_NOTE
    )


def evaluate_resource_planning() -> PlannerEvalResult:
    bench = planning_benchmark()
    strategies: tuple[tuple[str, Callable[[PlanningInstance], frozenset[str]]], ...] = (
        ("dtec_ratio", dtec_ratio_select),
        ("fifo", fifo_select),
        ("cost_ascending", cost_ascending_select),
        ("utility_descending", utility_descending_select),
    )

    def mean_fraction(select: Callable[[PlanningInstance], frozenset[str]]) -> Decimal:
        fractions: list[Fraction] = []
        for inst in bench:
            opt = brute_force_optimum(inst)
            got = selected_utility(inst.ops, select(inst))
            fractions.append(Fraction(got) / Fraction(opt) if opt > 0 else Fraction(1))
        return _frac_to_decimal(sum(fractions, Fraction(0)) / Fraction(len(fractions)))

    means = tuple((name, mean_fraction(select)) for name, select in strategies)

    # Honest negative: the instance (if any) where greedy-ratio underperforms the optimum.
    subopt = ""
    for inst in bench:
        if selected_utility(inst.ops, dtec_ratio_select(inst)) < brute_force_optimum(inst):
            subopt = inst.name
            break

    mand = _mandatory_instance()
    mandatory_ids = {op.op_id for op in mand.ops if op.mandatory}
    dtec_sel = dtec_ratio_select(mand)
    # Safe = DTEC either keeps every mandatory op or abstains entirely (never a partial plan
    # that silently drops a mandatory op).
    dtec_safe = mandatory_ids <= dtec_sel or dtec_sel == frozenset()
    ym_sel = yield_maximizer_select(mand)
    return PlannerEvalResult(
        instance_count=len(bench),
        strategy_mean_yield_fraction=means,
        greedy_not_universally_optimal=subopt != "",
        suboptimality_case=subopt,
        dtec_mandatory_safe=dtec_safe,
        yield_maximizer_drops_mandatory=not (mandatory_ids <= ym_sel),
    )


# --------------------------------------------------------------------------
# Aggregate
# --------------------------------------------------------------------------


class DTECBaselineReport(StrixModel):
    """The full offline comparative-baseline report across the measurable engines."""

    dependency: DependencyEvalResult
    temporal: TemporalEvalResult
    calibration: CalibrationEvalResult
    compositional: CompositionalEvalResult
    planning: PlannerEvalResult
    note: str = (
        "Offline synthetic comparative baselines (§5/§7/§8). DTEC-vs-label scores are a "
        "CONSISTENCY/REGRESSION check (labels are structurally defined, so a perfect DTEC "
        "score is tautological, not a measurement). The INFORMATIVE results are: naive "
        "baselines genuinely fail; the strongest FAIR baselines (composite record-linkage, "
        "availability-only temporal, contradiction-aware RAG) nearly tie DTEC; and DTEC "
        "separates only on specific capability cases (hash-canonicalized shared origin; the "
        "joint accuracy∧zero-leak temporal objective; R/K conclusion checks). This does NOT "
        "establish the §8 targets on real corpora. Hidden dependence, NL faithfulness, and "
        "production calibration remain open; live comparative arms are EXTERNALLY_BLOCKED "
        "(model credentials + budget)."
    )


def run_dtec_baselines() -> DTECBaselineReport:
    """Run every offline comparative-baseline measurement and aggregate the report."""
    return DTECBaselineReport(
        dependency=evaluate_dependency_detection(),
        temporal=evaluate_temporal_selection(),
        calibration=evaluate_calibration(),
        compositional=evaluate_compositional_support(),
        planning=evaluate_resource_planning(),
    )
