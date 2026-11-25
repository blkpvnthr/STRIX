"""Tests for strix.federal.analytics — procurement analytics.

These exercise the domain-independence contract for federal procurement
analytics: obligations/outlays/award amounts stay semantically distinct,
money is exact :class:`~decimal.Decimal`, cross-source reconciliation reuses
:mod:`strix.reconciliation`, and no anomaly or duplicate finding is ever
classified as confirmed fraud.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from strix.errors import StrixError
from strix.federal.analytics import (
    ConcentrationSummary,
    DuplicateReportFinding,
    ProcurementGraph,
    award_concentration,
    detect_duplicate_reporting,
    procurement_graph,
    reconcile_obligations,
    resolve_contractors,
    screen_spending_anomalies,
)
from strix.federal.models import (
    Agency,
    AwardModification,
    Contractor,
    FederalAward,
    FederalError,
    make_award,
)
from strix.reconciliation.reconcile import AnomalyFinding, ReconciliationResult

# --------------------------------------------------------------------------
# resolve_contractors — entity clustering
# --------------------------------------------------------------------------


def _award(
    *,
    recipient_uei: str,
    agency_id: str,
    award_amount: str,
    obligated_amount: str,
    outlayed_amount: str = "0",
    action_date: date,
) -> FederalAward:
    return make_award(
        award_id=f"PIID-{recipient_uei}-{agency_id}-{action_date.isoformat()}",
        recipient_uei=recipient_uei,
        agency_id=agency_id,
        award_amount=Decimal(award_amount),
        obligated_amount=Decimal(obligated_amount),
        outlayed_amount=Decimal(outlayed_amount),
        action_date=action_date,
    )


def test_resolve_contractors_clusters_shared_uei() -> None:
    """Two records with the same UEI resolve into one entity cluster."""
    contractors = [
        Contractor(contractor_id="C-1", name="Acme Corp", uei="UEI0000001"),
        Contractor(contractor_id="C-2", name="ACME Corporation", uei="UEI0000001"),
        Contractor(contractor_id="C-3", name="Globex LLC", uei="UEI0000002"),
    ]
    clusters = resolve_contractors(contractors)
    # C-1 and C-2 share a UEI -> one cluster; C-3 alone.
    cluster_members = sorted(clusters.values())
    assert ("C-1", "C-2") in cluster_members
    assert ("C-3",) in cluster_members
    assert len(clusters) == 2


def test_resolve_contractors_clusters_parent_child() -> None:
    """A subsidiary whose parent_uei is another record's UEI clusters together."""
    contractors = [
        Contractor(contractor_id="P-1", name="Parent Holdings", uei="PARENT0001"),
        Contractor(
            contractor_id="S-1",
            name="Subsidiary One",
            uei="SUB0000001",
            parent_uei="PARENT0001",
        ),
        Contractor(
            contractor_id="S-2",
            name="Subsidiary Two",
            uei="SUB0000002",
            parent_uei="PARENT0001",
        ),
        Contractor(contractor_id="X-1", name="Unrelated Inc", uei="OTHER00001"),
    ]
    clusters = resolve_contractors(contractors)
    members = sorted(clusters.values())
    # Parent + both subsidiaries (shared parent + parent/child) cluster together.
    assert ("P-1", "S-1", "S-2") in members
    assert ("X-1",) in members


def test_resolve_contractors_clusters_normalized_name() -> None:
    """Records differing only by punctuation/suffix/case normalize to one entity."""
    contractors = [
        Contractor(contractor_id="N-1", name="Beta Systems, Inc."),
        Contractor(contractor_id="N-2", name="beta systems inc"),
        Contractor(contractor_id="N-3", name="Gamma Works"),
    ]
    clusters = resolve_contractors(contractors)
    members = sorted(clusters.values())
    assert ("N-1", "N-2") in members
    assert ("N-3",) in members


def test_resolve_contractors_is_deterministic() -> None:
    contractors = [
        Contractor(contractor_id="C-2", name="ACME Corporation", uei="UEI0000001"),
        Contractor(contractor_id="C-1", name="Acme Corp", uei="UEI0000001"),
    ]
    first = resolve_contractors(contractors)
    second = resolve_contractors(list(reversed(contractors)))
    assert first == second
    # Keys and values are sorted / stable.
    assert list(first.keys()) == sorted(first.keys())


# --------------------------------------------------------------------------
# procurement_graph — contractor<->agency edges + totals (exact Decimal)
# --------------------------------------------------------------------------


def test_procurement_graph_edge_totals_exact() -> None:
    agencies = [Agency(agency_id="A-1", name="Agency One")]
    contractors = [Contractor(contractor_id="C-1", name="Acme", uei="UEI1")]
    awards = [
        _award(
            recipient_uei="UEI1",
            agency_id="A-1",
            award_amount="1000000.01",
            obligated_amount="400000.01",
            action_date=date(2025, 1, 1),
        ),
        _award(
            recipient_uei="UEI1",
            agency_id="A-1",
            award_amount="2000000.02",
            obligated_amount="600000.02",
            action_date=date(2025, 2, 1),
        ),
    ]
    graph = procurement_graph(awards, contractors, agencies)
    assert isinstance(graph, ProcurementGraph)
    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert edge.recipient_uei == "UEI1"
    assert edge.agency_id == "A-1"
    # Exact Decimal sum — no float drift.
    assert edge.obligated_total == Decimal("1000000.03")
    assert edge.award_count == 2


def test_procurement_graph_per_contractor_and_agency_totals() -> None:
    agencies = [
        Agency(agency_id="A-1", name="Agency One"),
        Agency(agency_id="A-2", name="Agency Two"),
    ]
    contractors = [
        Contractor(contractor_id="C-1", name="Acme", uei="UEI1"),
        Contractor(contractor_id="C-2", name="Globex", uei="UEI2"),
    ]
    awards = [
        _award(
            recipient_uei="UEI1",
            agency_id="A-1",
            award_amount="100",
            obligated_amount="100",
            action_date=date(2025, 1, 1),
        ),
        _award(
            recipient_uei="UEI1",
            agency_id="A-2",
            award_amount="200",
            obligated_amount="200",
            action_date=date(2025, 1, 2),
        ),
        _award(
            recipient_uei="UEI2",
            agency_id="A-1",
            award_amount="50",
            obligated_amount="50",
            action_date=date(2025, 1, 3),
        ),
    ]
    graph = procurement_graph(awards, contractors, agencies)
    ctotals = {c.recipient_uei: c for c in graph.contractor_totals}
    atotals = {a.agency_id: a for a in graph.agency_totals}
    assert ctotals["UEI1"].obligated_total == Decimal("300")
    assert ctotals["UEI1"].name == "Acme"
    assert ctotals["UEI2"].obligated_total == Decimal("50")
    assert atotals["A-1"].obligated_total == Decimal("150")
    assert atotals["A-1"].name == "Agency One"
    assert atotals["A-2"].obligated_total == Decimal("200")
    # Three distinct contractor<->agency edges.
    assert len(graph.edges) == 3


def test_procurement_graph_totals_use_obligations_not_outlays() -> None:
    """Graph totals sum obligations only; outlays are never folded in."""
    agencies = [Agency(agency_id="A-1", name="Agency One")]
    contractors = [Contractor(contractor_id="C-1", name="Acme", uei="UEI1")]
    awards = [
        _award(
            recipient_uei="UEI1",
            agency_id="A-1",
            award_amount="1000",
            obligated_amount="400",
            outlayed_amount="999",
            action_date=date(2025, 1, 1),
        ),
    ]
    graph = procurement_graph(awards, contractors, agencies)
    assert graph.edges[0].obligated_total == Decimal("400")
    assert graph.contractor_totals[0].obligated_total == Decimal("400")
    # The large outlay (999) never leaks into the obligation total.
    assert graph.agency_totals[0].obligated_total == Decimal("400")


def test_procurement_graph_empty() -> None:
    graph = procurement_graph([], [], [])
    assert graph.edges == ()
    assert graph.contractor_totals == ()
    assert graph.agency_totals == ()


# --------------------------------------------------------------------------
# reconcile_obligations — award_amount + sum(mods) vs obligated_amount
# --------------------------------------------------------------------------


def test_reconcile_obligations_within_tolerance() -> None:
    award = make_award(
        recipient_uei="UEI1",
        agency_id="A-1",
        award_amount=Decimal("500000"),
        obligated_amount=Decimal("575000"),
        action_date=date(2025, 1, 1),
    )
    mods = [
        AwardModification(
            modification_id="MOD-1",
            award_id=award.award_id,
            modification_amount=Decimal("100000"),
            action_date=date(2025, 2, 1),
        ),
        AwardModification(
            modification_id="MOD-2",
            award_id=award.award_id,
            modification_amount=Decimal("-25000"),
            action_date=date(2025, 3, 1),
        ),
    ]
    result = reconcile_obligations(
        award, mods, abs_tol=Decimal("0.01"), rel_tol=Decimal("0")
    )
    assert isinstance(result, ReconciliationResult)
    # 500000 + 100000 - 25000 == 575000 == obligated.
    assert result.reconstructed_value == Decimal("575000")
    assert result.classification == "within_tolerance"


def test_reconcile_obligations_mismatch_when_mod_missing() -> None:
    award = make_award(
        recipient_uei="UEI1",
        agency_id="A-1",
        award_amount=Decimal("500000"),
        obligated_amount=Decimal("575000"),
        action_date=date(2025, 1, 1),
    )
    # Only the +100000 mod is reported; the -25000 deobligation is missing.
    mods = [
        AwardModification(
            modification_id="MOD-1",
            award_id=award.award_id,
            modification_amount=Decimal("100000"),
            action_date=date(2025, 2, 1),
        ),
    ]
    result = reconcile_obligations(
        award, mods, abs_tol=Decimal("0.01"), rel_tol=Decimal("0")
    )
    # 500000 + 100000 == 600000 != 575000 observed -> mismatch.
    assert result.reconstructed_value == Decimal("600000")
    assert result.classification == "mismatch"
    assert result.absolute_residual == Decimal("25000")


def test_reconcile_obligations_no_mods_uses_award_amount() -> None:
    award = make_award(
        recipient_uei="UEI1",
        agency_id="A-1",
        award_amount=Decimal("500000"),
        obligated_amount=Decimal("500000"),
        action_date=date(2025, 1, 1),
    )
    result = reconcile_obligations(
        award, [], abs_tol=Decimal("0"), rel_tol=Decimal("0")
    )
    assert result.reconstructed_value == Decimal("500000")
    assert result.classification == "within_tolerance"


def test_reconcile_obligations_ignores_outlays() -> None:
    """Reconstruction never consults outlayed_amount."""
    award = make_award(
        recipient_uei="UEI1",
        agency_id="A-1",
        award_amount=Decimal("500000"),
        obligated_amount=Decimal("500000"),
        outlayed_amount=Decimal("123456"),
        action_date=date(2025, 1, 1),
    )
    result = reconcile_obligations(
        award, [], abs_tol=Decimal("0"), rel_tol=Decimal("0")
    )
    # Outlay magnitude plays no role in the obligation reconstruction.
    assert result.reconstructed_value == Decimal("500000")
    assert result.classification == "within_tolerance"


# --------------------------------------------------------------------------
# award_concentration — top-recipient share + herfindahl
# --------------------------------------------------------------------------


def test_award_concentration_share_and_herfindahl() -> None:
    awards = [
        _award(
            recipient_uei="UEI1",
            agency_id="A-1",
            award_amount="600000",
            obligated_amount="600000",
            action_date=date(2025, 1, 1),
        ),
        _award(
            recipient_uei="UEI2",
            agency_id="A-1",
            award_amount="300000",
            obligated_amount="300000",
            action_date=date(2025, 1, 2),
        ),
        _award(
            recipient_uei="UEI3",
            agency_id="A-1",
            award_amount="100000",
            obligated_amount="100000",
            action_date=date(2025, 1, 3),
        ),
    ]
    summary = award_concentration(awards)
    assert isinstance(summary, ConcentrationSummary)
    assert summary.total_obligated == Decimal("1000000")
    assert summary.recipient_count == 3
    assert summary.top_recipient_uei == "UEI1"
    assert summary.top_recipient_obligated == Decimal("600000")
    assert summary.top_recipient_share == Decimal("0.6")
    # HHI = 0.6^2 + 0.3^2 + 0.1^2 = 0.46
    assert summary.herfindahl_index == Decimal("0.46")


def test_award_concentration_single_recipient_is_monopoly() -> None:
    awards = [
        _award(
            recipient_uei="UEI1",
            agency_id="A-1",
            award_amount="100",
            obligated_amount="100",
            action_date=date(2025, 1, 1),
        ),
        _award(
            recipient_uei="UEI1",
            agency_id="A-1",
            award_amount="100",
            obligated_amount="100",
            action_date=date(2025, 1, 2),
        ),
    ]
    summary = award_concentration(awards)
    assert summary.top_recipient_share == Decimal("1")
    assert summary.herfindahl_index == Decimal("1")
    assert summary.recipient_count == 1


def test_award_concentration_uses_obligations_not_outlays() -> None:
    awards = [
        _award(
            recipient_uei="UEI1",
            agency_id="A-1",
            award_amount="600000",
            obligated_amount="600000",
            outlayed_amount="999999",
            action_date=date(2025, 1, 1),
        ),
        _award(
            recipient_uei="UEI2",
            agency_id="A-1",
            award_amount="400000",
            obligated_amount="400000",
            outlayed_amount="1",
            action_date=date(2025, 1, 2),
        ),
    ]
    summary = award_concentration(awards)
    # Total is obligations only; the outlays (999999, 1) are never summed in.
    assert summary.total_obligated == Decimal("1000000")


def test_award_concentration_empty_raises() -> None:
    with pytest.raises(FederalError):
        award_concentration([])


# --------------------------------------------------------------------------
# detect_duplicate_reporting
# --------------------------------------------------------------------------


def test_detect_duplicate_reporting_flags_planted_duplicate() -> None:
    dup_a = _award(
        recipient_uei="UEI1",
        agency_id="A-1",
        award_amount="250000",
        obligated_amount="250000",
        action_date=date(2025, 6, 1),
    )
    dup_b = make_award(
        award_id="DIFFERENT-SOURCE-PIID",
        recipient_uei="UEI1",
        agency_id="A-2",
        award_amount=Decimal("250000"),
        obligated_amount=Decimal("250000"),
        action_date=date(2025, 6, 1),
    )
    other = _award(
        recipient_uei="UEI2",
        agency_id="A-1",
        award_amount="999",
        obligated_amount="999",
        action_date=date(2025, 6, 1),
    )
    finding = detect_duplicate_reporting([dup_a, dup_b, other])
    assert isinstance(finding, DuplicateReportFinding)
    assert finding.classification == "duplicates_present"
    assert len(finding.groups) == 1
    group = finding.groups[0]
    assert group.reason_code == "possible_duplicate_report"
    assert set(group.award_ids) == {dup_a.award_id, dup_b.award_id}
    assert group.recipient_uei == "UEI1"
    assert group.award_amount == Decimal("250000")


def test_detect_duplicate_reporting_clean_when_distinct() -> None:
    awards = [
        _award(
            recipient_uei="UEI1",
            agency_id="A-1",
            award_amount="100",
            obligated_amount="100",
            action_date=date(2025, 1, 1),
        ),
        _award(
            recipient_uei="UEI1",
            agency_id="A-1",
            award_amount="200",
            obligated_amount="200",
            action_date=date(2025, 1, 1),
        ),
    ]
    finding = detect_duplicate_reporting(awards)
    assert finding.classification == "clean"
    assert finding.groups == ()


def test_detect_duplicate_reporting_window_groups_near_dates() -> None:
    a = make_award(
        award_id="SRC-A",
        recipient_uei="UEI1",
        agency_id="A-1",
        award_amount=Decimal("500"),
        obligated_amount=Decimal("500"),
        action_date=date(2025, 1, 1),
    )
    b = make_award(
        award_id="SRC-B",
        recipient_uei="UEI1",
        agency_id="A-1",
        award_amount=Decimal("500"),
        obligated_amount=Decimal("500"),
        action_date=date(2025, 1, 3),
    )
    # Exact-date window (default 0) keeps them apart.
    assert detect_duplicate_reporting([a, b]).classification == "clean"
    # A 2-day window groups them as a possible duplicate report.
    windowed = detect_duplicate_reporting([a, b], window_days=2)
    assert windowed.classification == "duplicates_present"
    assert set(windowed.groups[0].award_ids) == {a.award_id, b.award_id}


# --------------------------------------------------------------------------
# screen_spending_anomalies
# --------------------------------------------------------------------------


def test_screen_spending_anomalies_flags_outlier() -> None:
    obligations = [
        Decimal("100"),
        Decimal("110"),
        Decimal("105"),
        Decimal("108"),
        Decimal("100000"),
    ]
    finding = screen_spending_anomalies(obligations)
    assert isinstance(finding, AnomalyFinding)
    assert finding.classification == "anomalies_present"
    assert Decimal("100000") in finding.flagged_values


def test_screen_spending_anomalies_clean() -> None:
    obligations = [Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100")]
    finding = screen_spending_anomalies(obligations)
    assert finding.classification == "clean"
    assert finding.flagged_values == ()


def test_screen_spending_anomalies_too_few_raises() -> None:
    with pytest.raises(StrixError):
        screen_spending_anomalies([Decimal("1")])


# --------------------------------------------------------------------------
# Honesty / safety: no finding is ever classified as confirmed fraud
# --------------------------------------------------------------------------


def test_no_duplicate_finding_mentions_fraud() -> None:
    dup_a = _award(
        recipient_uei="UEI1",
        agency_id="A-1",
        award_amount="250000",
        obligated_amount="250000",
        action_date=date(2025, 6, 1),
    )
    dup_b = make_award(
        award_id="OTHER-SRC",
        recipient_uei="UEI1",
        agency_id="A-2",
        award_amount=Decimal("250000"),
        obligated_amount=Decimal("250000"),
        action_date=date(2025, 6, 1),
    )
    finding = detect_duplicate_reporting([dup_a, dup_b])
    for group in finding.groups:
        assert "fraud" not in group.reason_code.lower()
        assert "fraud" not in group.note.lower()
        # Framed as a possible inconsistency, flagged for review.
        assert "possible" in group.note.lower() or "anomal" in group.note.lower()


def test_anomaly_finding_is_investigation_not_fraud() -> None:
    obligations = [
        Decimal("100"),
        Decimal("110"),
        Decimal("105"),
        Decimal("108"),
        Decimal("100000"),
    ]
    finding = screen_spending_anomalies(obligations)
    # The classification vocabulary never asserts fraud.
    assert "fraud" not in finding.classification.lower()
    assert finding.classification in {"anomalies_present", "clean"}
