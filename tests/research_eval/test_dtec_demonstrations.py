"""Reproducible offline demonstrations of DTEC capabilities (§4).

Deterministic, synthetic, with fair comparators. These demonstrate that the engines behave as
specified where naive methods fail; they are NOT empirical validation (live arms blocked).
"""

from __future__ import annotations

from strix.research_eval.dtec_demonstrations import (
    Demonstration,
    demo_historical_reconstruction,
    demo_inconsistent_premises,
    run_demonstrations,
)


def test_inconsistent_premises_is_rejected_where_naive_accepts() -> None:
    demo = demo_inconsistent_premises()
    assert isinstance(demo, Demonstration)
    assert demo.capability == "detection_of_inconsistent_premises"
    assert "rejected" in demo.dtec_result.lower()
    assert demo.demonstrates is True  # DTEC rejects; naive comparator accepts


def test_historical_reconstruction_excludes_future_information() -> None:
    demo = demo_historical_reconstruction()
    assert demo.capability == "historical_evidence_reconstruction"
    # As-of the past knowledge time, later-available evidence is excluded (no leakage); the
    # naive "use all current evidence" comparator includes it.
    assert demo.demonstrates is True
    assert "excluded" in demo.dtec_result.lower() or "leak" in demo.comparator_result.lower()


def test_run_demonstrations_covers_all_twelve_capabilities() -> None:
    report = run_demonstrations()
    capabilities = {d.capability for d in report.demonstrations}
    # The §4 capability set must all be accounted for (demonstrated inline or indexed to a
    # reproducible artifact).
    assert len(capabilities) >= 12
    # Every demonstration carries a reproducible artifact pointer and an honest note.
    assert all(d.artifact for d in report.demonstrations)
    assert "not empirical validation" in report.note.lower()
    # No demonstration may silently fail its own criterion.
    assert all(d.demonstrates for d in report.demonstrations)
