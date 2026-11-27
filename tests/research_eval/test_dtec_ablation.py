"""Tests for the offline DTEC ablation harness (Phase 5 scientific evaluation).

These assert the ablation *methodology* produces coherent measurements on the synthetic
benchmark: full DTEC detects every item, the core alone misses the extension-engine attack
classes, and each option-gated engine has a positive marginal contribution. Figures here are
deterministic offline measurements, not the live H1-H12 validation.
"""

from __future__ import annotations

from decimal import Decimal

from strix.research_eval.dtec_ablation import (
    build_benchmark,
    detection_accuracy,
    interaction_delta,
    run_ablation,
)


def test_benchmark_spans_all_classes() -> None:
    classes = {it.attack_class for it in build_benchmark()}
    assert classes == {
        "valid", "fabricated_value", "dependency_inflated",
        "temporal_leak", "institutional_violation", "entity_relabel",
    }


def test_full_dtec_detects_everything() -> None:
    assert detection_accuracy(build_benchmark()) == Decimal(1)


def test_core_alone_misses_extension_attacks() -> None:
    report = run_ablation()
    # Core catches only valid + fabricated (support); it misses the four extension classes
    # (dependency/temporal/institutional/entity-relabel) -> 4 of 12 correct = 1/3.
    assert report.full_accuracy == Decimal(1)
    assert report.core_only_accuracy < report.full_accuracy
    assert Decimal("0.33") <= report.core_only_accuracy <= Decimal("0.34")


def test_each_configured_engine_has_positive_contribution() -> None:
    deltas = dict(run_ablation().engine_deltas)
    assert deltas["dependency"] > 0
    assert deltas["temporal"] > 0
    assert deltas["institutional"] > 0
    # No budget-attack items in this benchmark -> honest null contribution.
    assert deltas["budget"] == 0


def test_independent_engines_have_zero_interaction() -> None:
    # Dependency and temporal each catch their own disjoint attack class -> Δ_ij == 0.
    assert interaction_delta(build_benchmark(), "dependency", "temporal") == Decimal(0)


def test_ablation_report_is_deterministic() -> None:
    a = run_ablation()
    b = run_ablation()
    assert a.full_accuracy == b.full_accuracy
    assert a.engine_deltas == b.engine_deltas
