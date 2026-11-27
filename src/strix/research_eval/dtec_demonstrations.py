"""Reproducible offline demonstrations of the DTEC capabilities (§4).

Each :class:`Demonstration` names a §4 capability, a synthetic scenario, what DTEC does, what a
fair naive comparator does, whether the capability is demonstrated (DTEC correct AND distinct
from naive), and the reproducible artifact that backs it. **Every ``demonstrates`` flag is
computed, never hardcoded:** the engine capabilities by *calling* the offline harnesses
(``dtec_ablation`` / ``dtec_baselines``) so the numbers are recomputed, not quoted; the remaining
capabilities (inconsistent-premises detection, historical evidence reconstruction, final-answer
synthesis, citation integrity) inline on the core primitives (``admit_conclusion`` /
``admissible_evidence_ids``).

**Honesty:** these are deterministic synthetic demonstrations, NOT empirical validation — the
live comparative arms and real corpora are EXTERNALLY_BLOCKED (model credentials + budget).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from strix.evidence_graph.calculus import (
    Conclusion,
    FormalEncoding,
    SupportBalance,
    admit_conclusion,
)
from strix.evidence_graph.inference import And, Atom, Const, Not
from strix.evidence_graph.nodes import AdmissionOutcome
from strix.evidence_graph.temporal import (
    TemporalEnvelope,
    TemporalInterval,
    TemporalScope,
    admissible_evidence_ids,
    temporal_leakage,
)
from strix.models import StrixModel
from strix.research_eval.dtec_ablation import run_ablation
from strix.research_eval.dtec_baselines import (
    dependency_benchmark,
    dtec_predicts_dependent,
    evaluate_calibration,
    evaluate_compositional_support,
    evaluate_dependency_detection,
    evaluate_resource_planning,
    evaluate_temporal_selection,
    semantic_tuple_match_predicts_dependent,
    value_dedup_predicts_dependent,
)

__all__ = [
    "Demonstration",
    "DemonstrationReport",
    "demo_historical_reconstruction",
    "demo_inconsistent_premises",
    "run_demonstrations",
]

_T0 = datetime(2024, 1, 1, tzinfo=UTC)
_NOTE = (
    "Deterministic synthetic demonstrations with fair comparators and negative findings — "
    "NOT empirical validation. Live comparative arms and real corpora are EXTERNALLY_BLOCKED "
    "(model credentials + budget); no figure here is a demonstrated-on-real-corpora outcome."
)


class Demonstration(StrixModel):
    """One §4 capability demonstration with a fair comparator and a reproducible artifact."""

    capability: str
    scenario: str
    dtec_result: str
    comparator_result: str
    demonstrates: bool
    artifact: str


class DemonstrationReport(StrixModel):
    """The full §4 demonstration set across the DTEC capabilities."""

    demonstrations: tuple[Demonstration, ...]
    note: str = _NOTE


# --------------------------------------------------------------------------
# Inline demonstrations for capabilities not covered by the baseline harnesses
# --------------------------------------------------------------------------


def demo_inconsistent_premises() -> Demonstration:
    """A conclusion whose formal premises are mutually inconsistent is rejected.

    Naive composition accepts the conclusion because each premise was individually 'admitted';
    the compositional calculus detects ``p ∧ ¬p`` as inconsistent and rejects.
    """
    conclusion = Conclusion(
        conclusion_id="demo-inconsistent",
        proposition="q follows",
        premise_claim_ids=("c1",),
        formal=FormalEncoding(
            context=Const(True),
            premises=And((Atom("p"), Not(Atom("p")))),
            conclusion=Atom("q"),
        ),
    )
    decision = admit_conclusion(
        conclusion, {"c1": AdmissionOutcome.ADMITTED}
    )
    rejected = decision.outcome is AdmissionOutcome.REJECTED
    return Demonstration(
        capability="detection_of_inconsistent_premises",
        scenario="conclusion with mutually inconsistent formal premises (p ∧ ¬p)",
        dtec_result=f"A_C outcome={decision.outcome.value} ({decision.entailment_status})",
        comparator_result="naive individual-claim composer: accepted (premise 'admitted')",
        demonstrates=rejected,
        artifact="strix.research_eval.dtec_demonstrations.demo_inconsistent_premises",
    )


def demo_historical_reconstruction() -> Demonstration:
    """Reconstruct the admissible evidence set as-of a past knowledge time.

    Evidence that only became available AFTER the requested knowledge time is excluded (no
    future-information leakage); a naive 'use all current evidence' comparator includes it.
    """
    scope = TemporalScope(
        valid_time=_T0 + timedelta(days=50), knowledge_time=_T0 + timedelta(days=50)
    )
    envelopes = (
        TemporalEnvelope(
            evidence_id="past-1",
            validity=TemporalInterval(start=_T0, end=_T0 + timedelta(days=100)),
            knowledge=TemporalInterval(start=_T0, end=_T0 + timedelta(days=100)),
            available_at=_T0 + timedelta(days=10),
        ),
        TemporalEnvelope(
            evidence_id="future-leak",
            validity=TemporalInterval(start=_T0, end=_T0 + timedelta(days=100)),
            knowledge=TemporalInterval(start=_T0, end=_T0 + timedelta(days=100)),
            available_at=_T0 + timedelta(days=90),  # not available as-of day 50
        ),
    )
    admissible = admissible_evidence_ids(envelopes, scope)
    naive_leakage = temporal_leakage(envelopes, scope)  # fraction with a_i > t_k
    excluded_future = "future-leak" not in admissible and "past-1" in admissible
    return Demonstration(
        capability="historical_evidence_reconstruction",
        scenario="reconstruct admissible evidence as-of a past knowledge time (t_k = day 50)",
        dtec_result=(
            f"admissible as-of t_k = {sorted(admissible)}; later-available evidence excluded"
        ),
        comparator_result=(
            f"naive 'use all current evidence' leakage fraction = {naive_leakage} "
            "(includes future-available evidence)"
        ),
        demonstrates=excluded_future and naive_leakage > 0,
        artifact="strix.research_eval.dtec_demonstrations.demo_historical_reconstruction",
    )


# --------------------------------------------------------------------------
# Harness-backed demonstrations (recompute the existing offline results)
# --------------------------------------------------------------------------


def _dependency_pair_demo(
    capability: str, attack_class: str, scenario: str
) -> Demonstration:
    pair = next(p for p in dependency_benchmark() if p.attack_class == attack_class)
    dtec = dtec_predicts_dependent(pair)
    naive_value = value_dedup_predicts_dependent(pair)
    naive_tuple = semantic_tuple_match_predicts_dependent(pair)
    # Demonstrated when DTEC classifies the pair correctly AND at least one *non-strawman*
    # baseline (value dedup / semantic-tuple record linkage) gets it wrong. The constant-False
    # null_floor is deliberately NOT used as the distinctness criterion (the baselines module
    # disclaims it as a floor, never a baseline DTEC "beats").
    correct = dtec == pair.dependent
    naive_wrong = (naive_value != pair.dependent) or (naive_tuple != pair.dependent)
    return Demonstration(
        capability=capability,
        scenario=scenario,
        dtec_result=f"DTEC dependent={dtec} (ground truth dependent={pair.dependent})",
        comparator_result=(
            f"value-dedup dependent={naive_value}; semantic-tuple dedup dependent={naive_tuple}"
        ),
        demonstrates=correct and naive_wrong,
        artifact="strix.research_eval.dtec_baselines.dependency_benchmark",
    )


def run_demonstrations() -> DemonstrationReport:
    """Run every §4 capability demonstration and aggregate the report."""
    demos: list[Demonstration] = []

    # R-N1 dependency family (recomputed from the baseline benchmark).
    demos.append(
        _dependency_pair_demo(
            "detection_of_circular_corroboration",
            "lineage",
            "one observation derived from another, cited as two corroborating sources",
        )
    )
    demos.append(
        _dependency_pair_demo(
            "detection_of_shared_origin_evidence",
            "shared_origin_diff_value",
            "two observations from one artifact with differing values",
        )
    )
    demos.append(
        _dependency_pair_demo(
            "prevention_of_artificial_independence",
            "disjoint_same_value",
            "independent sources with a coincidentally equal value (naive dedup false positive)",
        )
    )

    # R-N2 temporal (recomputed).
    temporal = evaluate_temporal_selection()
    demos.append(
        Demonstration(
            capability="prevention_of_future_information_leakage",
            scenario="admit evidence as-of a knowledge time; a future-available item must not leak",
            dtec_result=f"DTEC two-axis leaks={temporal.dtec_leaks}",
            comparator_result=f"validity-only single axis leaks={temporal.validity_only_leaks}",
            demonstrates=temporal.dtec_leaks == 0 and temporal.validity_only_leaks > 0,
            artifact="strix.research_eval.dtec_baselines.evaluate_temporal_selection",
        )
    )
    demos.append(demo_historical_reconstruction())

    # R-N3 compositional (recomputed) + inline inconsistency.
    comp = evaluate_compositional_support()
    demos.append(
        Demonstration(
            capability="rejection_of_unsupported_compositional_conclusions",
            scenario="conclusions whose premises are admitted but do not support the conclusion",
            dtec_result=f"A_C unsupported-admit rate={comp.dtec_admit_rate}",
            comparator_result=(
                f"individual-claim composer admit rate={comp.individual_claim_admit_rate}"
            ),
            demonstrates=(
                comp.meets_target and comp.dtec_admit_rate < comp.individual_claim_admit_rate
            ),
            artifact="strix.research_eval.dtec_baselines.evaluate_compositional_support",
        )
    )
    demos.append(demo_inconsistent_premises())

    # R-N4 uncertainty / abstention (recomputed).
    calib = evaluate_calibration()
    demos.append(
        Demonstration(
            capability="appropriate_uncertainty_and_abstention",
            scenario="score a calibrated vs an overconfident probability source",
            dtec_result=(
                f"ECE calibrated={calib.calibrated_ece}, overconfident={calib.overconfident_ece}"
            ),
            comparator_result="an uncalibrated system treats both sources as equally reliable",
            demonstrates=calib.diagnostic_discriminates,
            artifact="strix.research_eval.dtec_baselines.evaluate_calibration",
        )
    )

    # R-N5 resource-bounded verification (recomputed).
    planning = evaluate_resource_planning()
    dtec_frac = dict(planning.strategy_mean_yield_fraction)["dtec_ratio"]
    demos.append(
        Demonstration(
            capability="resource_bounded_verification",
            scenario="maximize verified yield under an equal budget; never drop a mandatory op",
            dtec_result=(
                f"greedy ratio mean yield-fraction={dtec_frac}; mandatory-safe="
                f"{planning.dtec_mandatory_safe}"
            ),
            comparator_result=(
                "pure yield-maximizer drops a mandatory op="
                f"{planning.yield_maximizer_drops_mandatory}"
            ),
            demonstrates=planning.dtec_mandatory_safe and planning.yield_maximizer_drops_mandatory,
            artifact="strix.research_eval.dtec_baselines.evaluate_resource_planning",
        )
    )

    # R-N6 institutional (recomputed from the ablation).
    ablation = run_ablation()
    inst_delta = dict(ablation.engine_deltas).get("institutional")
    demos.append(
        Demonstration(
            capability="institutional_evidence_admissibility",
            scenario="an evidence item labelled with an unauthorized organization",
            dtec_result=(
                f"removing A_inst drops detection by Δ={inst_delta} (the engine catches it)"
            ),
            comparator_result="no institutional check: the unauthorized item is admitted",
            demonstrates=inst_delta is not None and inst_delta > 0,
            artifact="strix.research_eval.dtec_ablation.run_ablation",
        )
    )

    # Phase 9 live-path integration capabilities — COMPUTED via the core conclusion calculus
    # that backs the live checks (not hardcoded). Clean vs adversarial scenarios.
    _clean = admit_conclusion(
        Conclusion(
            conclusion_id="demo-clean",
            proposition="supported conclusion",
            premise_claim_ids=("p1",),
            balance=SupportBalance(supporting=("p1",)),
        ),
        {"p1": AdmissionOutcome.ADMITTED},
    )
    _contra = admit_conclusion(
        Conclusion(
            conclusion_id="demo-contra",
            proposition="contradicted conclusion",
            premise_claim_ids=("p1",),
            balance=SupportBalance(supporting=("p1",), opposing=("x",), substantive_conflict=True),
        ),
        {"p1": AdmissionOutcome.ADMITTED},
    )
    demos.append(
        Demonstration(
            capability="independently_verified_final_answer_synthesis",
            scenario="the complete synthesized answer evaluated at conclusion level (A_C)",
            dtec_result=(
                f"clean conclusion={_clean.outcome.value}; contradicted conclusion="
                f"{_contra.outcome.value}"
            ),
            comparator_result="naive synthesis: emit the prose regardless of conclusion support",
            demonstrates=(
                _clean.outcome is AdmissionOutcome.ADMITTED
                and _contra.outcome is AdmissionOutcome.REJECTED
            ),
            artifact="strix.evidence_graph.calculus.admit_conclusion (live: conclusion_check)",
        )
    )
    # Citation integrity: an assertion whose cited premise is NOT admitted is rejected at the
    # conclusion level; a backed one is admitted.
    _backed = admit_conclusion(
        Conclusion(
            conclusion_id="demo-backed",
            proposition="cited premise admitted",
            premise_claim_ids=("p1",),
            balance=SupportBalance(supporting=("p1",)),
        ),
        {"p1": AdmissionOutcome.ADMITTED},
    )
    _unbacked = admit_conclusion(
        Conclusion(
            conclusion_id="demo-unbacked",
            proposition="cited premise not admitted",
            premise_claim_ids=("p1",),
            balance=SupportBalance(supporting=("p1",)),
        ),
        {"p1": AdmissionOutcome.REJECTED},
    )
    demos.append(
        Demonstration(
            capability="citation_integrity",
            scenario="an assertion whose cited premise is not admitted must be rejected",
            dtec_result=(
                f"admitted-premise conclusion={_backed.outcome.value}; "
                f"unadmitted-premise conclusion={_unbacked.outcome.value}"
            ),
            comparator_result="ungrounded prose with no verifiable citation mapping",
            demonstrates=(
                _backed.outcome is AdmissionOutcome.ADMITTED
                and _unbacked.outcome is AdmissionOutcome.REJECTED
            ),
            artifact="strix.evidence_graph.calculus.admit_conclusion (live: answering.validate)",
        )
    )

    dep = evaluate_dependency_detection()
    demos.append(
        Demonstration(
            capability="dependency_detection_overall",
            scenario="recover constructed dependence structure vs the strongest fair baseline",
            dtec_result=f"DTEC F1={dep.dtec.f1}",
            comparator_result=(
                f"strongest fair baseline ({dep.strongest_baseline_name}) F1="
                f"{dep.strongest_baseline_f1}"
            ),
            demonstrates=dep.dtec_separates_from_strongest,
            artifact="strix.research_eval.dtec_baselines.evaluate_dependency_detection",
        )
    )

    return DemonstrationReport(demonstrations=tuple(demos))
