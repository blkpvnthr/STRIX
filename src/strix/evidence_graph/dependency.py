"""Evidence dependency intelligence — the independent-evidence sufficiency predicate.

This is the reference implementation of research engine R-N1 (master spec §1.1). It
estimates pairwise *dependence* between supporting evidence items, derives an
**effective independent evidence count** ``N_eff``, and produces a four-valued
admission predicate ``A_ind`` that decides whether a claim's evidence is
*independently* sufficient — not merely numerous. Artificial corroboration (the same
fact restated, or many items tracing to one origin) must not count as independent
support.

Mathematical object (confidential companion §4; bounds proved in
``mathematical-invariants.md`` INV-N1-1/2/3):

    d_ij ∈ [0, 1]      symmetric pairwise dependence, d_ii = 1
    N_eff(w, D) = (1ᵀw)² / (wᵀDw)                         effective independent count
    1 ≤ N_eff ≤ (Σwᵢ)²/Σwᵢ² ≤ n                            (Proposition 1)
    N̲_eff = inf_{D∈S} N_eff(w, D)                          conservative lower bound

**Not a probability.** ``d_ij`` here is a transparent *structural dependence score*
built from observable provenance signals (shared origin artifacts, semantic
duplication), **not** a calibrated probability. The calibrated logistic form
``d_ij = sigma(β₀ + βᵀx)`` requires independently labelled data (ALG-N1-2) and is
deliberately not fabricated here.

**Exactness.** Jaccard overlaps are rationals that do not terminate in decimal, so all
dependency/``N_eff`` arithmetic is carried in exact :class:`fractions.Fraction`
(itself float-free, consistent with the project's exact-numeric contract). Results are
quantised to :class:`~decimal.Decimal` only for human-readable reporting; the
PASS/FAIL/UNKNOWN comparison against the policy threshold is exact over ``Fraction``.

**Conservatism.** By monotonicity (INV-N1-2), ``N_eff`` is non-increasing in
dependence, so the infimum of ``N_eff`` over an interval box ``[d̲_ij, d̄_ij]`` is
attained at the *upper* dependence bounds. The predicate admits only when even this
conservative lower bound clears the threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction

from strix.evidence_graph.graph import EvidenceGraph
from strix.evidence_graph.nodes import (
    CandidateClaim,
    PredicateName,
    PredicateResult,
    PredicateStatus,
    SourceObservation,
)
from strix.models import DecimalValue, SourceArtifact, StrixModel
from strix.native.arithmetic import STAT_QUANTUM, as_decimal

__all__ = [
    "DependencyEstimate",
    "DependencyPolicy",
    "IndependenceAssessment",
    "assess_independence",
    "conservative_effective_bounds",
    "dependency_bounds",
    "effective_independent_count",
    "estimate_dependence",
]


# --------------------------------------------------------------------------
# Policy + result models
# --------------------------------------------------------------------------


class DependencyPolicy(StrixModel):
    """Trusted configuration for the ``A_ind`` predicate (kept separate from the
    content-addressed :class:`~strix.evidence_graph.nodes.VerificationPolicy` so the
    existing policy identity is never perturbed).

    ``min_effective_independent`` is the threshold ``θ`` on the effective independent
    evidence count. ``require_independent_evidence`` False is an authorized
    applicability decision that makes the predicate NOT_APPLICABLE. Evidence tracing
    to a ``primary_record_artifact_ids`` entry is an authoritative primary record for
    which independent corroboration is unnecessary (an explicit, policy-gated
    exception — only honored when the evidence resolves to a *real* ``SourceArtifact``
    node whose id is listed, never a self-declared id).

    **Caveat (m4):** since ``N_eff >= 1`` always (Proposition 1), a threshold ``θ ≤ 1``
    provides no independence protection — every nonempty, nonzero-weight claim passes.
    Choose ``θ >= 2`` to require genuine corroboration.
    """

    min_effective_independent: DecimalValue
    require_independent_evidence: bool = True
    primary_record_artifact_ids: tuple[str, ...] = ()


class IndependenceAssessment(StrixModel):
    """The outcome of evaluating ``A_ind`` for one claim, with the numeric bounds.

    ``effective_independent_lower`` is the conservative ``N̲_eff`` (computed at maximum
    feasible dependence); ``effective_independent_upper`` is the optimistic ``N̄_eff``
    (minimum feasible dependence). Both are reported as quantised Decimals; the
    admission decision in ``result`` was taken on the exact rational values.
    """

    result: PredicateResult
    item_count: int
    effective_independent_lower: DecimalValue
    effective_independent_upper: DecimalValue
    threshold: DecimalValue
    all_pairs_resolved: bool


@dataclass(frozen=True)
class DependencyEstimate:
    """An interval estimate ``[lower, upper] ⊆ [0, 1]`` of pairwise dependence.

    ``lower == upper`` when both items' provenance is fully resolved (a point
    estimate). When provenance is unresolved for either item the interval widens to
    ``[known_lower, 1]`` — the feasible set is underspecified, which conservatively
    admits maximal dependence.
    """

    lower: Fraction
    upper: Fraction
    resolved: bool
    signals: tuple[str, ...]


# --------------------------------------------------------------------------
# Structural signal extraction
# --------------------------------------------------------------------------


def _origin_artifacts(graph: EvidenceGraph, item_id: str) -> tuple[frozenset[str], bool]:
    """Return ``(trusted origin-artifact ids, resolved)`` for an evidence item.

    **Trust boundary (security fix C1/M2).** Only a :class:`SourceArtifact` that
    actually exists in the graph — created by trusted ingestion — counts as an origin.
    An item's self-declared ``source_artifact_id`` is honored *only when it resolves to
    a real ``SourceArtifact`` node*; a declared id with no backing node (or any
    attacker-fabricated id) does **not** establish a trusted origin. Provenance
    ancestors that are real ``SourceArtifact`` nodes are also included. ``resolved`` is
    True only when at least one trusted origin artifact is found.

    This asymmetry is deliberate and conservative: unverifiable origin metadata can
    never be used to *claim independence* or to *waive corroboration* (it only ever
    leaves an item unresolved, which widens the dependence interval toward full
    dependence). Self-declared metadata is thus fail-safe, never fail-open.

    **Honest limitation.** A hidden shared origin that is *not* expressed as a shared
    artifact node (e.g. two genuinely-ingested artifacts that secretly copy one
    upstream source not represented in the graph) will be scored independent. The
    structural estimator cannot see origins the graph does not contain; such cases are
    a modeling limit, documented in ``counterexample-registry.md`` (CE-N1-1), not a
    silent pass — detecting them is open research (hidden-source reconstruction).
    """
    if not graph.has_node(item_id):
        return frozenset(), False
    node = graph.node(item_id)
    arts: set[str] = set()
    if isinstance(node, SourceObservation):
        declared = node.source_artifact_id
        if graph.has_node(declared) and isinstance(graph.node(declared), SourceArtifact):
            arts.add(declared)
    for ancestor_id in graph.ancestors(item_id):
        if isinstance(graph.node(ancestor_id), SourceArtifact):
            arts.add(ancestor_id)
    return frozenset(arts), bool(arts)


def _semantic_key(graph: EvidenceGraph, item_id: str) -> tuple[str, str, str, str] | None:
    """Return a content key identifying a restated fact, or ``None``.

    Two observations sharing ``(subject, concept, unit, value)`` are the same fact
    restated — complete dependence regardless of origin. The numeric value is compared
    on its **normalized** Decimal form so that scale-variant restatements
    (``0.25`` vs ``0.250``) are recognized as equal (fix M1).
    """
    if not graph.has_node(item_id):
        return None
    node = graph.node(item_id)
    if isinstance(node, SourceObservation):
        return (node.subject_id, node.concept, node.unit, str(node.value.normalize()))
    return None


def _upstream_set(graph: EvidenceGraph, item_id: str) -> frozenset[str]:
    """Canonical upstream-origin tokens for *item_id* (excluding the item itself).

    Artifacts are canonicalized by **content_hash** so that the same source document
    ingested under different ``artifact_id``s collapses to a single origin token (fix:
    duplicate-document false independence — a non-content-addressed ``artifact_id`` must
    not be read as a distinct origin). Non-artifact provenance ancestors are keyed by
    node id. Used to decide shared vs disjoint origin for the dependence estimate.
    """
    tokens: set[str] = set()
    arts, _ = _origin_artifacts(graph, item_id)
    for artifact_id in arts:
        node = graph.node(artifact_id)  # guaranteed a real SourceArtifact by _origin_artifacts
        if isinstance(node, SourceArtifact):
            tokens.add(f"hash:{node.content_hash}")
    if graph.has_node(item_id):
        for ancestor_id in graph.evidence_closure(item_id) - {item_id}:
            node = graph.node(ancestor_id)
            if isinstance(node, SourceArtifact):
                tokens.add(f"hash:{node.content_hash}")
            else:
                tokens.add(f"node:{ancestor_id}")
    return frozenset(tokens)


def estimate_dependence(graph: EvidenceGraph, id_i: str, id_j: str) -> DependencyEstimate:
    """Estimate the symmetric structural dependence of two evidence items.

    Dependence is the Jaccard overlap of the two items' *trusted upstream sets* (real
    artifact origins plus provenance ancestors), with a semantic-duplicate override.

    **Independence is earned, not assumed (point 3).** A ``0`` (independent) point
    estimate is returned **only** when both items have validated, *non-empty, disjoint*
    trusted upstream provenance. Distinct identifiers alone never imply independence: if
    either item's origin is unresolved, fabricated, or unverifiable, the estimate is the
    *interval* ``[0, 1]`` (``resolved=False``) — dependence cannot be excluded, so the
    conservative lower bound ``N̲_eff`` (built from the upper matrix) stays small and the
    predicate abstains rather than crediting independence.

    Semantic duplicates (same subject/concept/unit/canonical-value) are fully dependent
    (``d = 1``) regardless of origin (fix M1 via canonical Decimal equivalence).
    """
    if id_i == id_j:
        return DependencyEstimate(Fraction(1), Fraction(1), True, ("self",))

    sem_i = _semantic_key(graph, id_i)
    sem_j = _semantic_key(graph, id_j)
    if sem_i is not None and sem_i == sem_j:
        return DependencyEstimate(Fraction(1), Fraction(1), True, ("semantic_duplicate",))

    _, res_i = _origin_artifacts(graph, id_i)
    _, res_j = _origin_artifacts(graph, id_j)
    if not (res_i and res_j):
        # Unresolved / fabricated / unverifiable origin: independence cannot be inferred.
        return DependencyEstimate(Fraction(0), Fraction(1), False, ("unresolved_provenance",))

    # Direct lineage: if one cited item is itself a provenance ancestor/descendant of the
    # other, they are not two independent corroborators (fix: ancestor-descendant false
    # independence — the upstream-set overlap alone misses this because each set excludes
    # its own id). ``evidence_closure(x)`` includes x and all its ancestors.
    if id_i in graph.evidence_closure(id_j) or id_j in graph.evidence_closure(id_i):
        return DependencyEstimate(Fraction(1), Fraction(1), True, ("lineage_dependence",))

    u_i = _upstream_set(graph, id_i)
    u_j = _upstream_set(graph, id_j)
    union = u_i | u_j
    inter = u_i & u_j
    jaccard = Fraction(len(inter), len(union)) if union else Fraction(0)
    if inter:
        return DependencyEstimate(jaccard, jaccard, True, ("shared_origin",))
    return DependencyEstimate(
        Fraction(0), Fraction(0), True, ("validated_disjoint_provenance",)
    )


def dependency_bounds(
    graph: EvidenceGraph, item_ids: tuple[str, ...]
) -> tuple[list[list[Fraction]], list[list[Fraction]], bool]:
    """Return ``(lower_matrix, upper_matrix, all_resolved)`` over ``item_ids``.

    Both matrices are symmetric with unit diagonal; ``lower_matrix`` holds the
    minimum feasible dependence per pair and ``upper_matrix`` the maximum.
    """
    n = len(item_ids)
    lower = [[Fraction(1) if i == j else Fraction(0) for j in range(n)] for i in range(n)]
    upper = [[Fraction(1) if i == j else Fraction(0) for j in range(n)] for i in range(n)]
    all_resolved = True
    for i in range(n):
        for j in range(i + 1, n):
            est = estimate_dependence(graph, item_ids[i], item_ids[j])
            lower[i][j] = lower[j][i] = est.lower
            upper[i][j] = upper[j][i] = est.upper
            all_resolved = all_resolved and est.resolved
    return lower, upper, all_resolved


# --------------------------------------------------------------------------
# Effective independent count
# --------------------------------------------------------------------------


def _validate_dependency_matrix(matrix: list[list[Fraction]], n: int) -> None:
    """Reject a malformed dependency matrix (point 5).

    Requires an ``nxn`` matrix of exact :class:`Fraction` entries in ``[0, 1]`` with a
    unit diagonal and symmetry — the structural preconditions under which Proposition 1
    and the monotonicity/conservative-bound results hold (see ``mathematical-invariants.md``
    INV-N1-1/2/3). ``Fraction`` already excludes float/NaN/inf; this guards shape and range.
    """
    if len(matrix) != n:
        raise ValueError(f"dependency matrix has {len(matrix)} rows, expected {n}")
    for i, row in enumerate(matrix):
        if len(row) != n:
            raise ValueError(f"dependency matrix row {i} has {len(row)} entries, expected {n}")
        for j, value in enumerate(row):
            if not isinstance(value, Fraction):
                raise ValueError(f"dependency matrix entry [{i}][{j}] is not an exact Fraction")
            if value < 0 or value > 1:
                raise ValueError(f"dependency matrix entry [{i}][{j}]={value} is outside [0, 1]")
            if i == j and value != 1:
                raise ValueError(f"dependency matrix diagonal [{i}][{i}]={value} must be 1")
            if matrix[i][j] != matrix[j][i]:
                raise ValueError(f"dependency matrix is not symmetric at [{i}][{j}]")


def effective_independent_count(
    weights: tuple[Fraction, ...], matrix: list[list[Fraction]]
) -> Fraction:
    """Exact ``N_eff(w, D) = (Σwᵢ)² / (wᵀDw)`` over rationals.

    Preconditions (validated; point 5): ``n >= 1`` items; weights nonnegative with a
    positive sum; ``matrix`` an ``nxn`` symmetric unit-diagonal matrix of Fractions in
    ``[0, 1]``. Raises :class:`ValueError` on any violation or a zero denominator
    (which cannot occur under the preconditions, but is guarded defensively).
    """
    n = len(weights)
    if n == 0:
        raise ValueError("effective_independent_count requires at least one item")
    if any(w < 0 for w in weights):
        # INV-N1-3's conservative-bound argument requires w >= 0 (denominator
        # coefficients 2·wᵢwⱼ must be nonnegative). Fail closed on misuse.
        raise ValueError("effective_independent_count requires nonnegative weights")
    _validate_dependency_matrix(matrix, n)
    sum_w = sum(weights, Fraction(0))
    if sum_w == 0:
        raise ValueError("effective_independent_count requires a nonzero weight vector")
    numerator = sum_w * sum_w
    denominator = Fraction(0)
    for i in range(n):
        for j in range(n):
            denominator += weights[i] * weights[j] * matrix[i][j]
    if denominator == 0:
        raise ValueError("degenerate dependency matrix (zero quadratic form)")
    return numerator / denominator


def conservative_effective_bounds(
    weights: tuple[Fraction, ...],
    lower_matrix: list[list[Fraction]],
    upper_matrix: list[list[Fraction]],
) -> tuple[Fraction, Fraction]:
    """Return ``(N̲_eff, N̄_eff)`` — the conservative and optimistic effective counts.

    By monotonicity (INV-N1-2) ``N_eff`` is non-increasing in dependence, so the
    conservative lower bound ``N̲_eff`` is ``N_eff`` at the *upper* dependence matrix
    and the optimistic upper bound ``N̄_eff`` is ``N_eff`` at the *lower* matrix.
    """
    n_eff_lower = effective_independent_count(weights, upper_matrix)
    n_eff_upper = effective_independent_count(weights, lower_matrix)
    return n_eff_lower, n_eff_upper


# --------------------------------------------------------------------------
# The A_ind admission predicate
# --------------------------------------------------------------------------


def _frac_to_decimal(value: Fraction) -> Decimal:
    """Quantise an exact rational to a reporting Decimal (never float)."""
    with localcontext() as ctx:
        ctx.prec = 50
        dec = Decimal(value.numerator) / Decimal(value.denominator)
    return dec.quantize(STAT_QUANTUM)


def assess_independence(
    claim: CandidateClaim,
    graph: EvidenceGraph,
    policy: DependencyPolicy,
    *,
    weights: dict[str, Decimal] | None = None,
    validated_evidence_ids: frozenset[str] | None = None,
) -> IndependenceAssessment:
    """Evaluate ``A_ind`` for *claim* under *policy*.

    ``A_ind`` is **one** predicate in the unified calculus; a PASS here satisfies the
    independence/corroboration requirement **only** and never bypasses any other
    mandatory predicate (the fail-closed composition guarantees this — Prop 3).

    ``validated_evidence_ids`` is the set of cited evidence ids that have independently
    passed the prerequisite assurance (integrity + provenance + temporal applicability).
    The authoritative-primary-record exception is honored **only** for evidence in this
    set whose trusted origin is a policy-authorized primary artifact — satisfying the
    layered trust requirement (validated provenance, integrity, ingestion authority via a
    real ``SourceArtifact`` node, temporal applicability, and claim-specific authority via
    the policy allow-list). Absent this set the exception cannot fire (fail-closed).

    Result (four-valued):

    - **NOT_APPLICABLE** — the policy does not require independent evidence.
    - **PASS** — a *validated*, policy-authorized primary record is cited, or the
      conservative ``N̲_eff >= θ``.
    - **FAIL** — empty / zero-weight evidence, or even the optimistic ``N̄_eff < θ``.
    - **UNKNOWN** — intermediate (``N̲_eff < θ ≤ N̄_eff``), unresolved/fabricated
      provenance, or circular provenance. Abstention, never a silent pass.
    """
    threshold = Fraction(policy.min_effective_independent)
    threshold_dec = Decimal(policy.min_effective_independent)
    validated = validated_evidence_ids or frozenset()

    def _assess(status: PredicateStatus, code: str, detail: str, *, lo: Fraction, hi: Fraction,
                resolved: bool, n: int) -> IndependenceAssessment:
        return IndependenceAssessment(
            result=PredicateResult(
                predicate=PredicateName.INDEPENDENCE,
                status=status,
                reason_codes=(code,),
                detail=detail,
            ),
            item_count=n,
            effective_independent_lower=_frac_to_decimal(lo),
            effective_independent_upper=_frac_to_decimal(hi),
            threshold=threshold_dec,
            all_pairs_resolved=resolved,
        )

    if not policy.require_independent_evidence:
        return _assess(
            PredicateStatus.NOT_APPLICABLE,
            "independence_not_required",
            "policy does not require independent-evidence sufficiency",
            lo=Fraction(0), hi=Fraction(0), resolved=True, n=0,
        )

    item_ids = tuple(claim.evidence_ids)
    n = len(item_ids)
    if n == 0:
        return _assess(
            PredicateStatus.FAIL, "empty_evidence",
            "claim cites no evidence; independent support cannot be established",
            lo=Fraction(0), hi=Fraction(0), resolved=True, n=0,
        )

    # Circular provenance is a malformed-graph attack: abstain, never guess (point 7).
    try:
        graph.assert_acyclic_derivation()
    except Exception as exc:  # EvidenceGraphError names the cycle
        return _assess(
            PredicateStatus.UNKNOWN, "circular_provenance",
            f"provenance contains a derivation cycle; cannot assess independence: {exc}",
            lo=Fraction(0), hi=Fraction(1), resolved=False, n=n,
        )

    # Authoritative-primary-record exception — STRICT and scoped (points 1, 2).
    # Fires only for evidence that (a) has passed prerequisite assurance
    # (``validated_evidence_ids``), (b) resolves to a REAL ``SourceArtifact`` node
    # (not a self-declared id), and (c) is on the policy's authorized primary allow-list.
    # It waives ONLY the corroboration requirement; all other predicates still apply.
    if policy.primary_record_artifact_ids and validated:
        primary = set(policy.primary_record_artifact_ids)
        for item_id in item_ids:
            if item_id not in validated:
                continue
            arts, resolved = _origin_artifacts(graph, item_id)
            if resolved and (arts & primary):
                return _assess(
                    PredicateStatus.PASS, "primary_record_exception",
                    f"validated evidence {item_id} traces to authorized primary record "
                    f"{sorted(arts & primary)}; corroboration requirement waived (this "
                    "predicate only; other mandatory predicates unaffected)",
                    lo=Fraction(n), hi=Fraction(n), resolved=True, n=n,
                )

    # Weights (default uniform). ``as_decimal`` rejects float at the boundary (fix m1),
    # preserving the exact-numeric contract; negatives are rejected (fail closed).
    frac_weights: list[Fraction] = []
    for item_id in item_ids:
        if weights is None:
            w = Fraction(1)
        else:
            w = Fraction(as_decimal(weights.get(item_id, Decimal(0))))
        if w < 0:
            raise ValueError(f"evidence weight for {item_id!r} is negative")
        frac_weights.append(w)
    weight_tuple = tuple(frac_weights)
    if sum(weight_tuple, Fraction(0)) == 0:
        return _assess(
            PredicateStatus.FAIL, "zero_weight",
            "all evidence weights are zero; no independent support",
            lo=Fraction(0), hi=Fraction(0), resolved=True, n=n,
        )

    lower_matrix, upper_matrix, all_resolved = dependency_bounds(graph, item_ids)
    n_eff_lo, n_eff_hi = conservative_effective_bounds(weight_tuple, lower_matrix, upper_matrix)

    detail = (
        f"N_eff ∈ [{_frac_to_decimal(n_eff_lo)}, {_frac_to_decimal(n_eff_hi)}] "
        f"vs θ={threshold_dec} over {n} item(s); "
        f"provenance {'fully' if all_resolved else 'partially'} resolved"
    )
    if n_eff_lo >= threshold:
        return _assess(PredicateStatus.PASS, "sufficient_independent_evidence", detail,
                       lo=n_eff_lo, hi=n_eff_hi, resolved=all_resolved, n=n)
    if n_eff_hi < threshold:
        return _assess(PredicateStatus.FAIL, "insufficient_independent_evidence", detail,
                       lo=n_eff_lo, hi=n_eff_hi, resolved=all_resolved, n=n)
    return _assess(PredicateStatus.UNKNOWN, "unresolved_independence", detail,
                   lo=n_eff_lo, hi=n_eff_hi, resolved=all_resolved, n=n)
