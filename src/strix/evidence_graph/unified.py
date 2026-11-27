"""Unified DTEC admission — composing all predicates into one decision (Phase 4 integration).

Wires the preserved claim-level core ``A(c)=I∧T∧P_rov∧D_num∧S`` together with the DTEC
extension predicates into the unified calculus (confidential companion §10):

    A_DTEC = I ∧ T ∧ P_rov ∧ D_num ∧ S ∧ R ∧ K ∧ F ∧ A_inst ∧ A_ind ∧ M_B

Every applicable component is evaluated under the same four-valued admission algebra and
composed with :func:`strix.evidence_graph.calculus.compose_statuses`. By the fail-closed
extension property (Proposition 3 / INV-ALG-3) adding any mandatory extension predicate can
only hold a claim to a *stricter* standard — so enabling DTEC never admits something the
preserved core would have rejected or abstained on. A predicate whose engine is not
configured for this request contributes ``NOT_APPLICABLE`` (the policy did not require it);
the RC-3 guard in ``compose_statuses`` refuses a vacuous admission if nothing applies.

The decision carries a deterministic content digest (certificate identity) and maps to the
existing five gateway dispositions; signing reuses ``assurance.signing`` (Ed25519).

**Integration status (honest, 2026-11-26).** ``admit_dtec`` is the complete unified evaluator
but is NOT yet wired into the live research lifecycle — its callers today are the offline
ablation/baseline harness (``research_eval``) and the integration tests. The live chokepoint
(``agent.orchestrator.run_research_question``) currently enforces the recompute verifier plus
the conclusion-level ``A_C`` (``agent.conclusion_check``) and the dependency projection
(``agent.dependency_check``); the per-claim temporal / institutional / budget / entity-binding /
full-compositional engines run here and in the harness but are not yet invoked per live claim.
Completing that wiring (the AgentClaim→EvidenceGraph bridge) is scoped-remaining engineering —
see ``research/execution-state.md`` (S18). Do not read this module as proof that eleven
predicates gate every live answer today.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from strix.assurance.gateway import GatewayOutcome
from strix.assurance.verification_planner import ResourceBudget, VerificationOp, assess_budget
from strix.canonical import canonical_hash
from strix.evidence_graph.calculus import Conclusion, admit_conclusion, compose_statuses
from strix.evidence_graph.dependency import DependencyPolicy, assess_independence
from strix.evidence_graph.graph import EvidenceGraph
from strix.evidence_graph.nodes import (
    AdmissionOutcome,
    CandidateClaim,
    PredicateName,
    PredicateResult,
    PredicateStatus,
    VerificationPolicy,
)
from strix.evidence_graph.predicates import admit
from strix.evidence_graph.temporal import TemporalEnvelope, TemporalScope, assess_bitemporal
from strix.institutional.admissibility import (
    InstitutionalContext,
    InstitutionalLabel,
    assess_institutional,
)
from strix.institutional.applicability import assess_entity_binding
from strix.models import StrixModel

__all__ = ["DTECDecision", "DTECOptions", "admit_dtec"]


@dataclass(frozen=True)
class DTECOptions:
    """Per-request configuration of the DTEC extension predicates.

    Each engine runs only when its configuration is supplied; otherwise its predicate is
    NOT_APPLICABLE (the versioned policy did not require it for this request).
    """

    dependency_policy: DependencyPolicy | None = None
    validated_evidence_ids: frozenset[str] = frozenset()
    temporal_envelopes: tuple[TemporalEnvelope, ...] | None = None
    temporal_scope: TemporalScope | None = None
    institutional_context: InstitutionalContext | None = None
    institutional_labels: tuple[InstitutionalLabel, ...] = ()
    verification_ops: tuple[VerificationOp, ...] | None = None
    budget: ResourceBudget | None = None
    conclusion: Conclusion | None = None
    premise_admissions: Mapping[str, AdmissionOutcome] = field(default_factory=dict)
    satisfied_context: frozenset[str] = frozenset()
    use_z3: bool = False


class DTECDecision(StrixModel):
    """The unified admission decision: outcome, gateway disposition, every predicate result,
    and a deterministic content digest (certificate identity)."""

    claim_id: str
    outcome: AdmissionOutcome
    disposition: GatewayOutcome
    predicate_results: tuple[PredicateResult, ...]
    decision_digest: str
    detail: str = ""


def _outcome_of(status: PredicateStatus) -> AdmissionOutcome:
    if status is PredicateStatus.FAIL:
        return AdmissionOutcome.REJECTED
    if status is PredicateStatus.UNKNOWN:
        return AdmissionOutcome.ABSTAINED
    return AdmissionOutcome.ADMITTED


def _disposition(status: PredicateStatus) -> GatewayOutcome:
    # Core mapping; QUALIFIED / REVIEW_REQUIRED are refined by the six-pillar gateway
    # (assurance.gateway.evaluate_gateway) when uncertainty/monitor signals are present.
    if status is PredicateStatus.FAIL:
        return GatewayOutcome.REJECTED
    if status is PredicateStatus.UNKNOWN:
        return GatewayOutcome.ABSTAIN
    return GatewayOutcome.AUTHORIZED


def _compose_institutional(
    labels: tuple[InstitutionalLabel, ...], context: InstitutionalContext
) -> PredicateResult:
    """Compose A_inst over all supplied labels into one INSTITUTIONAL result. With no labels
    the context cannot establish applicability → UNKNOWN (abstain), never favorable."""
    if not labels:
        return assess_institutional(None, context)
    results = [assess_institutional(label, context) for label in labels]
    status = compose_statuses(tuple(r.status for r in results))
    codes = tuple(
        c for r in results if r.status is not PredicateStatus.PASS for c in r.reason_codes
    )
    return PredicateResult(
        predicate=PredicateName.INSTITUTIONAL,
        status=status,
        reason_codes=codes or ("institutionally_admissible",),
        detail=f"A_inst over {len(labels)} label(s)",
    )


def admit_dtec(
    claim: CandidateClaim,
    graph: EvidenceGraph,
    policy: VerificationPolicy,
    options: DTECOptions | None = None,
) -> DTECDecision:
    """Evaluate the unified ``A_DTEC`` for *claim* and return the composed decision.

    Always evaluates the preserved claim-level core (I/T/P_rov/D_num/S via :func:`admit`) and
    the entity-binding check; evaluates each DTEC extension predicate whose engine is
    configured in *options*. Composes all results fail-closed (any FAIL ⇒ REJECTED; else any
    UNKNOWN ⇒ ABSTAINED; else ADMITTED) and maps to a gateway disposition. The result's
    ``decision_digest`` is a deterministic content hash over the inputs and outcome.
    """
    opts = options or DTECOptions()
    results: list[PredicateResult] = list(admit(graph, claim, policy).predicate_results)

    if opts.dependency_policy is not None:
        results.append(
            assess_independence(
                claim, graph, opts.dependency_policy,
                validated_evidence_ids=opts.validated_evidence_ids or None,
            ).result
        )
    # Entity binding always runs (NOT_APPLICABLE when no computation-backed assertions).
    results.append(assess_entity_binding(claim, graph))

    if opts.temporal_envelopes is not None and opts.temporal_scope is not None:
        results.append(assess_bitemporal(opts.temporal_envelopes, opts.temporal_scope))

    if opts.institutional_context is not None:
        results.append(
            _compose_institutional(opts.institutional_labels, opts.institutional_context)
        )

    if opts.verification_ops is not None and opts.budget is not None:
        results.append(assess_budget(opts.verification_ops, opts.budget))

    if opts.conclusion is not None:
        conclusion_decision = admit_conclusion(
            opts.conclusion, opts.premise_admissions, graph=graph,
            satisfied_context=opts.satisfied_context, use_z3=opts.use_z3,
        )
        results.extend(conclusion_decision.predicate_results)

    unified_status = compose_statuses(tuple(r.status for r in results))
    outcome = _outcome_of(unified_status)
    disposition = _disposition(unified_status)

    digest = canonical_hash(
        {
            "claim_id": claim.candidate_claim_id,
            "graph_hash": graph.graph_hash(),
            "policy_version": policy.version,
            "results": sorted(
                (r.predicate.value, r.status.value, tuple(sorted(r.reason_codes))) for r in results
            ),
            "outcome": outcome.value,
        }
    )
    return DTECDecision(
        claim_id=claim.candidate_claim_id,
        outcome=outcome,
        disposition=disposition,
        predicate_results=tuple(results),
        decision_digest=digest,
        detail=f"A_DTEC={unified_status.value} over {len(results)} predicate(s)",
    )
