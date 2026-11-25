"""Federal procurement analytics: entity resolution, relationship graph,
obligation reconciliation, concentration, and duplicate / anomaly screening.

This module is an *application adapter* over the STRIX assurance primitives; it
does not modify the assurance core. It reuses
:mod:`strix.reconciliation` for cross-source reconciliation and anomaly
screening, :mod:`strix.native` for exact :class:`~decimal.Decimal` arithmetic,
and :mod:`strix.federal.models` for the typed procurement schemas.

Money-kind discipline (see :class:`strix.federal.models.MoneyKind`)
-------------------------------------------------------------------
Obligations, deobligations, outlays, disbursements, award amounts, and
modification amounts are **semantically distinct and never interchangeable**.
Every total computed here is an *obligation* total: outlays are never summed
with obligations, and obligation reconstruction never consults an award's
outlayed amount.

Honesty / safety
----------------
Nothing here classifies a record as confirmed fraud. Duplicate-report and
spending-anomaly findings describe a *possible inconsistency* flagged for
investigation; the reason codes and notes say "possible"/"anomaly", never
"fraud", and the decision to act rests with a downstream reviewer.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, localcontext

from strix.federal.models import (
    Agency,
    AwardModification,
    Contractor,
    FederalAward,
    FederalError,
)
from strix.models import DecimalValue, StrixModel
from strix.native.arithmetic import (
    ARITH_PRECISION,
    STAT_QUANTUM,
    checked_div,
    checked_sum,
    quantize,
)
from strix.reconciliation.reconcile import (
    AnomalyFinding,
    ReconciliationResult,
    reconcile_aggregate,
    screen_anomalies,
)

__all__ = [
    "AgencyTotal",
    "ConcentrationSummary",
    "ContractorTotal",
    "DuplicateReportFinding",
    "DuplicateReportGroup",
    "ProcurementEdge",
    "ProcurementGraph",
    "award_concentration",
    "detect_duplicate_reporting",
    "normalize_entity_name",
    "procurement_graph",
    "reconcile_obligations",
    "resolve_contractors",
    "screen_spending_anomalies",
]

#: Corporate suffix tokens dropped when normalizing an entity name. These carry
#: no identity (a filer may spell them inconsistently across records).
_SUFFIX_TOKENS = frozenset(
    {
        "inc",
        "incorporated",
        "llc",
        "llp",
        "lp",
        "corp",
        "corporation",
        "co",
        "company",
        "ltd",
        "limited",
        "plc",
        "pllc",
        "pc",
    }
)

#: Note attached to a possible-duplicate-report finding. Deliberately framed as
#: an inconsistency flagged for review — never an assertion of fraud.
_DUPLICATE_NOTE = (
    "possible duplicate report: distinct award records share recipient, award "
    "amount, and action date within the window; flagged for investigation, not "
    "a confirmed finding"
)

#: Reason code for a possible duplicate report (never implies fraud).
_DUPLICATE_REASON = "possible_duplicate_report"


# --------------------------------------------------------------------------
# Result models
# --------------------------------------------------------------------------


class ProcurementEdge(StrixModel):
    """One contractor<->agency relationship summarized over its awards.

    ``obligated_total`` is the exact sum of the obligated amounts of the awards
    on this edge — obligations only, never outlays.
    """

    recipient_uei: str
    agency_id: str
    obligated_total: DecimalValue
    award_count: int


class ContractorTotal(StrixModel):
    """Per-recipient obligation total across all agencies (obligations only)."""

    recipient_uei: str
    name: str
    obligated_total: DecimalValue
    award_count: int


class AgencyTotal(StrixModel):
    """Per-agency obligation total across all recipients (obligations only)."""

    agency_id: str
    name: str
    obligated_total: DecimalValue
    award_count: int


class ProcurementGraph(StrixModel):
    """A deterministic relationship summary of a set of federal awards.

    The graph carries the contractor<->agency edge list and per-contractor and
    per-agency obligation totals. All monetary totals are exact Decimal
    obligations; outlays and award ceilings are never folded in.
    """

    edges: tuple[ProcurementEdge, ...]
    contractor_totals: tuple[ContractorTotal, ...]
    agency_totals: tuple[AgencyTotal, ...]


class ConcentrationSummary(StrixModel):
    """Concentration of obligations across recipients.

    ``top_recipient_share`` is the largest recipient's share of total
    obligations and ``herfindahl_index`` is the sum of squared recipient
    shares (1 for a single recipient, approaching 0 as breadth grows). Both are
    computed from obligations only.
    """

    total_obligated: DecimalValue
    recipient_count: int
    top_recipient_uei: str
    top_recipient_obligated: DecimalValue
    top_recipient_share: DecimalValue
    herfindahl_index: DecimalValue


class DuplicateReportGroup(StrixModel):
    """A set of award records that look like the same obligation reported more
    than once (same recipient, award amount, and action date within a window).

    This is a *possible* inconsistency flagged for investigation: the
    ``reason_code`` and ``note`` never assert fraud.
    """

    reason_code: str
    note: str
    recipient_uei: str
    award_amount: DecimalValue
    award_ids: tuple[str, ...]
    earliest_action_date: date
    latest_action_date: date


class DuplicateReportFinding(StrixModel):
    """Evidence of possible duplicate reporting across a set of awards.

    ``classification`` is ``duplicates_present`` or ``clean``; the groups are
    flagged for investigation and never classified as fraud.
    """

    classification: str
    groups: tuple[DuplicateReportGroup, ...]


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------


class _UnionFind:
    """A minimal deterministic union-find over integer indices."""

    def __init__(self, size: int) -> None:
        self._parent = list(range(size))

    def find(self, node: int) -> int:
        root = node
        while self._parent[root] != root:
            root = self._parent[root]
        # Path compression keeps repeated lookups cheap and deterministic.
        while self._parent[node] != root:
            self._parent[node], node = root, self._parent[node]
        return root

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a == root_b:
            return
        # Point the larger root at the smaller so cluster roots are stable.
        low, high = sorted((root_a, root_b))
        self._parent[high] = low

    def components(self) -> dict[int, list[int]]:
        clusters: dict[int, list[int]] = {}
        for node in range(len(self._parent)):
            clusters.setdefault(self.find(node), []).append(node)
        return clusters


def normalize_entity_name(name: str) -> str:
    """Normalize a contractor name for identity comparison.

    Lower-cases, strips punctuation, collapses whitespace, and drops trailing
    corporate-suffix tokens (``inc``, ``llc``, ``corp`` …) so that
    ``"Beta Systems, Inc."`` and ``"beta systems inc"`` compare equal. If
    nothing survives suffix stripping, the punctuation-stripped form is kept so
    distinct names never collapse to an empty key.
    """
    lowered = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    tokens = lowered.split()
    stripped = list(tokens)
    while stripped and stripped[-1] in _SUFFIX_TOKENS:
        stripped.pop()
    chosen = stripped or tokens
    return " ".join(chosen)


# --------------------------------------------------------------------------
# resolve_contractors
# --------------------------------------------------------------------------


def resolve_contractors(contractors: Sequence[Contractor]) -> dict[str, tuple[str, ...]]:
    """Group contractor records into deterministic entity clusters.

    Two records join the same cluster when they share any of:

    * the same normalized name (:func:`normalize_entity_name`);
    * the same non-empty UEI;
    * a parent/child link (one record's ``parent_uei`` equals another's UEI);
    * the same non-empty ``parent_uei`` (siblings under one parent).

    Returns a mapping ``cluster_key -> (contractor_id, ...)`` where the key is
    the lexicographically smallest ``contractor_id`` in the cluster and the
    value is the sorted tuple of member ids. The mapping is ordered by key, so
    the result is independent of input order.
    """
    items = list(contractors)
    uf = _UnionFind(len(items))

    for i in range(len(items)):
        a = items[i]
        a_name = normalize_entity_name(a.name)
        for j in range(i + 1, len(items)):
            b = items[j]
            same_name = bool(a_name) and a_name == normalize_entity_name(b.name)
            same_uei = bool(a.uei) and a.uei == b.uei
            parent_child = (bool(a.parent_uei) and a.parent_uei == b.uei) or (
                bool(b.parent_uei) and b.parent_uei == a.uei
            )
            same_parent = bool(a.parent_uei) and a.parent_uei == b.parent_uei
            if same_name or same_uei or parent_child or same_parent:
                uf.union(i, j)

    clusters: dict[str, tuple[str, ...]] = {}
    for members in uf.components().values():
        ids = sorted(items[index].contractor_id for index in members)
        clusters[ids[0]] = tuple(ids)
    return {key: clusters[key] for key in sorted(clusters)}


# --------------------------------------------------------------------------
# procurement_graph
# --------------------------------------------------------------------------


def procurement_graph(
    awards: Sequence[FederalAward],
    contractors: Sequence[Contractor],
    agencies: Sequence[Agency],
) -> ProcurementGraph:
    """Summarize contractor<->agency relationships over a set of awards.

    Builds the edge list keyed by ``(recipient_uei, agency_id)`` with the exact
    obligation total and award count for each edge, plus per-contractor and
    per-agency obligation totals. ``contractors`` and ``agencies`` supply human
    names for the totals. Every total is obligations only — outlays and award
    ceilings are never summed in.
    """
    contractor_name = _name_by_uei(contractors)
    agency_name = {agency.agency_id: agency.name for agency in agencies}

    edge_obs: dict[tuple[str, str], list[Decimal]] = {}
    contractor_obs: dict[str, list[Decimal]] = {}
    agency_obs: dict[str, list[Decimal]] = {}

    for award in awards:
        obligated = Decimal(award.obligated_amount)
        edge_obs.setdefault((award.recipient_uei, award.agency_id), []).append(obligated)
        contractor_obs.setdefault(award.recipient_uei, []).append(obligated)
        agency_obs.setdefault(award.agency_id, []).append(obligated)

    edges = tuple(
        ProcurementEdge(
            recipient_uei=uei,
            agency_id=agency_id,
            obligated_total=checked_sum(values),
            award_count=len(values),
        )
        for (uei, agency_id), values in sorted(edge_obs.items())
    )
    contractor_totals = tuple(
        ContractorTotal(
            recipient_uei=uei,
            name=contractor_name.get(uei, ""),
            obligated_total=checked_sum(values),
            award_count=len(values),
        )
        for uei, values in sorted(contractor_obs.items())
    )
    agency_totals = tuple(
        AgencyTotal(
            agency_id=agency_id,
            name=agency_name.get(agency_id, ""),
            obligated_total=checked_sum(values),
            award_count=len(values),
        )
        for agency_id, values in sorted(agency_obs.items())
    )
    return ProcurementGraph(
        edges=edges,
        contractor_totals=contractor_totals,
        agency_totals=agency_totals,
    )


def _name_by_uei(contractors: Sequence[Contractor]) -> dict[str, str]:
    """Map each non-empty UEI to a deterministic representative name.

    When several records share a UEI the name of the record with the smallest
    ``contractor_id`` is used, so the mapping is order-independent.
    """
    names: dict[str, str] = {}
    for contractor in sorted(contractors, key=lambda c: c.contractor_id):
        if contractor.uei and contractor.uei not in names:
            names[contractor.uei] = contractor.name
    return names


# --------------------------------------------------------------------------
# reconcile_obligations
# --------------------------------------------------------------------------


def reconcile_obligations(
    award: FederalAward,
    modifications: Sequence[AwardModification],
    *,
    abs_tol: Decimal,
    rel_tol: Decimal,
) -> ReconciliationResult:
    """Reconcile an award's obligated amount against its reconstruction.

    The observed quantity is ``award.obligated_amount``; the reconstruction is
    the base ``award.award_amount`` plus the sum of the signed
    ``modification_amount`` values (positive = obligation increase, negative =
    deobligation). The residual is classified ``within_tolerance`` or
    ``mismatch`` by :func:`strix.reconciliation.reconcile.reconcile_aggregate`.

    This reconstructs obligations only: the award's ``outlayed_amount`` is never
    consulted, and disbursements/outlays are never mixed into the components.
    """
    components: list[Decimal] = [Decimal(award.award_amount)]
    components.extend(Decimal(mod.modification_amount) for mod in modifications)
    source_references = (award.award_id, *(mod.modification_id for mod in modifications))
    return reconcile_aggregate(
        "obligated_amount",
        Decimal(award.obligated_amount),
        components,
        aggregation="sum",
        abs_tol=abs_tol,
        rel_tol=rel_tol,
        source_references=source_references,
    )


# --------------------------------------------------------------------------
# award_concentration
# --------------------------------------------------------------------------


def award_concentration(awards: Sequence[FederalAward]) -> ConcentrationSummary:
    """Measure how concentrated obligations are across recipients.

    Returns the total obligated, the top recipient and its share of the total,
    and the Herfindahl index (sum of squared recipient shares). All quantities
    are obligations only — outlays are never summed in. Shares and the index
    are exact Decimal, quantized to the canonical statistical quantum for
    reproducibility. Raises :class:`FederalError` on an empty award set.
    """
    if not awards:
        raise FederalError("award_concentration requires at least one award")

    by_recipient: dict[str, list[Decimal]] = {}
    for award in awards:
        by_recipient.setdefault(award.recipient_uei, []).append(
            Decimal(award.obligated_amount)
        )
    recipient_totals = {uei: checked_sum(values) for uei, values in by_recipient.items()}
    total = checked_sum(list(recipient_totals.values()))

    # Deterministic top recipient: largest obligation, ties broken by UEI.
    top_uei = min(
        recipient_totals, key=lambda uei: (-recipient_totals[uei], uei)
    )
    top_obligated = recipient_totals[top_uei]

    if total == 0:
        return ConcentrationSummary(
            total_obligated=total,
            recipient_count=len(recipient_totals),
            top_recipient_uei=top_uei,
            top_recipient_obligated=top_obligated,
            top_recipient_share=Decimal(0),
            herfindahl_index=Decimal(0),
        )

    squared_shares: list[Decimal] = []
    for value in recipient_totals.values():
        share = checked_div(value, total)
        with localcontext() as ctx:
            ctx.prec = ARITH_PRECISION
            squared_shares.append(+(share * share))
    herfindahl = checked_sum(squared_shares)
    top_share = checked_div(top_obligated, total)

    return ConcentrationSummary(
        total_obligated=total,
        recipient_count=len(recipient_totals),
        top_recipient_uei=top_uei,
        top_recipient_obligated=top_obligated,
        top_recipient_share=quantize(top_share, STAT_QUANTUM),
        herfindahl_index=quantize(herfindahl, STAT_QUANTUM),
    )


# --------------------------------------------------------------------------
# detect_duplicate_reporting
# --------------------------------------------------------------------------


def detect_duplicate_reporting(
    awards: Sequence[FederalAward],
    *,
    window_days: int = 0,
) -> DuplicateReportFinding:
    """Flag awards that may be the same obligation reported more than once.

    Awards are grouped by ``(recipient_uei, award_amount)``; within each group,
    two records are linked when their ``action_date`` values differ by at most
    ``window_days`` (default ``0`` = same date). Each linked set of two or more
    records becomes a :class:`DuplicateReportGroup` with reason code
    ``possible_duplicate_report``.

    This reports a *possible* inconsistency for investigation; it never asserts
    fraud. Raises :class:`FederalError` on a negative window.
    """
    if window_days < 0:
        raise FederalError("window_days must be non-negative")

    buckets: dict[tuple[str, Decimal], list[FederalAward]] = {}
    for award in awards:
        buckets.setdefault(
            (award.recipient_uei, Decimal(award.award_amount)), []
        ).append(award)

    groups: list[DuplicateReportGroup] = []
    for (recipient_uei, award_amount), bucket in sorted(
        buckets.items(), key=lambda item: (item[0][0], item[0][1])
    ):
        if len(bucket) < 2:
            continue
        ordered = sorted(bucket, key=lambda a: (a.action_date, a.award_id))
        uf = _UnionFind(len(ordered))
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                delta = abs((ordered[i].action_date - ordered[j].action_date).days)
                if delta <= window_days:
                    uf.union(i, j)
        for members in uf.components().values():
            if len(members) < 2:
                continue
            member_awards = [ordered[index] for index in members]
            dates = [a.action_date for a in member_awards]
            groups.append(
                DuplicateReportGroup(
                    reason_code=_DUPLICATE_REASON,
                    note=_DUPLICATE_NOTE,
                    recipient_uei=recipient_uei,
                    award_amount=award_amount,
                    award_ids=tuple(sorted(a.award_id for a in member_awards)),
                    earliest_action_date=min(dates),
                    latest_action_date=max(dates),
                )
            )

    groups.sort(key=lambda g: (g.recipient_uei, g.award_amount, g.award_ids))
    classification = "duplicates_present" if groups else "clean"
    return DuplicateReportFinding(classification=classification, groups=tuple(groups))


# --------------------------------------------------------------------------
# screen_spending_anomalies
# --------------------------------------------------------------------------


def screen_spending_anomalies(
    obligations: Sequence[Decimal],
    *,
    method: str = "iqr",
    k: Decimal | str = "1.5",
) -> AnomalyFinding:
    """Flag statistical outliers in a series of obligation amounts.

    Delegates to :func:`strix.reconciliation.reconcile.screen_anomalies`. A
    flagged obligation triggers *investigation*, never automatic rejection and
    never a fraud determination. Only obligations are passed in — outlays and
    disbursements are never mixed into the same series.
    """
    return screen_anomalies(obligations, method=method, k=k)
