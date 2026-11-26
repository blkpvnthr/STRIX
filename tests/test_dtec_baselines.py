"""Tests for the offline DTEC comparative-baseline evaluation harness.

**Honest measurement contract (post adversarial review).** A benchmark whose ground-truth
labels are defined by the same structural criteria an engine uses cannot *measure* that
engine — a perfect DTEC score is then tautological. So this harness is explicit that the
DTEC-vs-label numbers are a **consistency/regression check** (does the engine correctly
recover the structure it was handed), and the *informative* content is:

  1. the **baseline failure rates** (naive methods genuinely fail these cases), and
  2. whether DTEC **separates from the strongest FAIR composite baseline** on at least one
     case that requires machinery the composite lacks (hash-canonicalized shared origin;
     the joint accuracy∧zero-leak temporal objective; R/K/F conclusion checks a RAG-like
     composer misses).

Nothing here is a live H1-H12 validation (the comparative live arms are EXTERNALLY_BLOCKED
on model credentials + budget); these are deterministic offline measurements with denominators.
"""

from __future__ import annotations

from decimal import Decimal

from strix.research_eval.dtec_baselines import (
    BinaryClassMetrics,
    composite_match_predicts_dependent,
    confusion_metrics,
    dependency_benchmark,
    dtec_predicts_dependent,
    evaluate_calibration,
    evaluate_compositional_support,
    evaluate_dependency_detection,
    evaluate_temporal_selection,
    run_dtec_baselines,
    semantic_tuple_match_predicts_dependent,
    value_dedup_predicts_dependent,
)

# --------------------------------------------------------------------------
# Metric arithmetic
# --------------------------------------------------------------------------


def test_confusion_metrics_exact_precision_recall_f1() -> None:
    pairs = (
        [(True, True)] * 3 + [(True, False)] * 1 + [(False, True)] * 1 + [(False, False)] * 5
    )
    m = confusion_metrics(pairs)
    assert (m.tp, m.fp, m.fn, m.tn) == (3, 1, 1, 5)
    assert m.precision == Decimal("0.75")
    assert m.recall == Decimal("0.75")
    assert m.f1 == Decimal("0.75")
    assert m.accuracy == Decimal("0.8")


def test_confusion_metrics_no_positive_predictions_defines_zero_precision() -> None:
    m = confusion_metrics([(False, True), (False, False)])
    assert m.tp == 0 and m.fp == 0
    assert m.precision == Decimal(0)
    assert m.recall == Decimal(0)
    assert m.f1 == Decimal(0)


# --------------------------------------------------------------------------
# R-N1 — Evidence dependency detection vs steelmanned baselines
# --------------------------------------------------------------------------


def test_dependency_benchmark_includes_hash_canonicalization_separation_case() -> None:
    bench = dependency_benchmark()
    classes = {p.attack_class for p in bench}
    # The original confounder classes plus the DTEC-separation case must all be present.
    assert {
        "shared_origin_same_value",
        "shared_origin_diff_value",
        "semantic_duplicate",
        "lineage",
        "disjoint_diff_value",
        "disjoint_same_value",
        "same_hash_diff_artifact_id",
    } <= classes


def test_dtec_separates_from_fair_composite_on_hash_canonicalization() -> None:
    # Two artifacts with IDENTICAL content bytes (same content_hash) registered under
    # different artifact ids: genuinely dependent (same source). DTEC infers this via hash
    # canonicalization; the fair composite (artifact-id OR semantic-tuple) cannot — this is
    # a real, non-circular capability separation.
    pair = next(p for p in dependency_benchmark() if p.attack_class == "same_hash_diff_artifact_id")
    assert pair.dependent is True
    assert dtec_predicts_dependent(pair) is True
    assert composite_match_predicts_dependent(pair) is False


def test_semantic_tuple_match_removes_value_dedup_false_positive() -> None:
    # The fair (subject,concept,unit,value) dedup does NOT false-positive on coincidentally
    # equal values across different subjects, where naive value-only dedup does.
    pair = next(p for p in dependency_benchmark() if p.attack_class == "disjoint_same_value")
    assert pair.dependent is False
    assert value_dedup_predicts_dependent(pair) is True  # naive FP
    assert semantic_tuple_match_predicts_dependent(pair) is False  # fair: correct


def test_dtec_dependency_consistency_and_separation_from_strongest_baseline() -> None:
    result = evaluate_dependency_detection()
    # DTEC recovers every structural label (consistency check), reported honestly as such.
    assert result.dtec.f1 == Decimal("1")
    # The strongest FAIR baseline is the composite; DTEC must STRICTLY exceed it (the hash
    # case is the separation), and the composite must be strong (near-ties on the rest).
    assert result.strongest_baseline_name == "composite_match"
    assert result.dtec.f1 > result.strongest_baseline_f1
    assert result.dtec_separates_from_strongest is True
    assert result.strongest_baseline_f1 >= Decimal("0.85")  # not a strawman


# --------------------------------------------------------------------------
# R-N2 — Bitemporal selection: no single axis meets the joint objective
# --------------------------------------------------------------------------


def test_no_single_axis_meets_joint_accuracy_and_zero_leak() -> None:
    result = evaluate_temporal_selection()
    # DTEC (two-axis) achieves both >= 0.95 accuracy AND zero leakage (consistency check).
    assert result.dtec_accuracy >= Decimal("0.95")
    assert result.dtec_leaks == 0
    # The validity-only baseline leaks; the availability-only baseline achieves zero leaks
    # but fails accuracy on expired-validity. NEITHER single axis meets the joint objective.
    assert result.validity_only_leaks > 0
    assert result.availability_only_leaks == 0
    assert result.availability_only_accuracy < Decimal("0.95")
    assert result.no_single_axis_meets_joint is True
    assert result.two_axis_required is True


# --------------------------------------------------------------------------
# R-N4 — Calibration metric validation (reframed; not a method-vs-method arm)
# --------------------------------------------------------------------------


def test_calibration_metric_validation_discriminates_and_is_honestly_scoped() -> None:
    result = evaluate_calibration()
    assert result.calibrated_ece <= result.target_ece
    assert result.overconfident_ece > result.target_ece
    assert result.diagnostic_discriminates is True
    # Honest scope: metric validation, not a production-calibration claim, not a method arm.
    assert "metric-validation" in result.note.lower()


# --------------------------------------------------------------------------
# R-N3 — Compositional: even a stronger baseline misses R/K failures
# --------------------------------------------------------------------------


def test_compositional_reduction_vs_contradiction_aware_baseline() -> None:
    result = evaluate_compositional_support()
    assert result.unsupported_count == 3
    # The naive individual-claim composer admits all 3 unsupported conclusions.
    assert result.individual_claim_admit_rate == Decimal("1")
    # A STRONGER contradiction-aware baseline still admits the R (entailment) and K (context)
    # failures it cannot see — DTEC rejects them. The strongest baseline is the comparator.
    assert result.contradiction_aware_admit_rate < result.individual_claim_admit_rate
    assert result.contradiction_aware_admit_rate > Decimal("0")
    assert result.dtec_admit_rate == Decimal("0")
    # Reduction vs the STRONGEST baseline still meets the >= 50% target.
    assert result.reduction_vs_strongest >= result.target_reduction
    assert result.meets_target is True


# --------------------------------------------------------------------------
# Benchmark integrity + confidentiality hygiene
# --------------------------------------------------------------------------


def test_dependency_pair_convenience_fields_match_graph() -> None:
    # The baselines read convenience fields (value_*/artifact_*); DTEC reads the graph. They
    # MUST encode the same ground truth, or the comparison is unfair. Guard it.
    from strix.evidence_graph.nodes import SourceObservation
    from strix.models import SourceArtifact

    for pair in dependency_benchmark():
        for oid, value, aid in (
            (pair.id_i, pair.value_i, pair.artifact_i),
            (pair.id_j, pair.value_j, pair.artifact_j),
        ):
            node = pair.graph.node(oid)
            assert isinstance(node, SourceObservation)
            assert node.value.normalize() == value.normalize(), pair.name
            assert node.source_artifact_id == aid, pair.name
            art = pair.graph.node(aid)
            assert isinstance(art, SourceArtifact), pair.name


def test_no_internal_blocker_codes_in_public_notes() -> None:
    # Internal blocker-register codes (B-LIVE/B-VIS/B-PUSH) stay in the confidential set; the
    # public harness uses plain-language caveats. Guard every result note.
    report = run_dtec_baselines()
    notes = [
        report.note, report.dependency.note, report.temporal.note,
        report.calibration.note, report.compositional.note,
    ]
    for note in notes:
        for code in ("B-LIVE", "B-VIS", "B-PUSH"):
            assert code not in note, note


def test_run_dtec_baselines_aggregates_all_engines_with_honest_note() -> None:
    report = run_dtec_baselines()
    assert report.dependency.dtec_separates_from_strongest is True
    assert report.temporal.two_axis_required is True
    assert report.compositional.meets_target is True
    assert report.calibration.diagnostic_discriminates is True
    assert "synthetic" in report.note.lower()
    assert "consistency" in report.note.lower()  # the honest reframing


def test_binary_class_metrics_is_a_strix_model() -> None:
    m = confusion_metrics([(True, True)])
    assert isinstance(m, BinaryClassMetrics)
    assert m.model_dump()["f1"] == Decimal("1")
