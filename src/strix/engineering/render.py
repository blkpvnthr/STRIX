"""Terminal/report rendering for engineering compilations.

Pure text formatting of already-computed results: no analysis, no
verification, no persistence. ``model-report.txt`` is derived from the
verified export content and is non-authoritative (not hashed, not
replay-compared).
"""

from __future__ import annotations

from strix.engineering.models import (
    CompileMetrics,
    CompileResult,
    ModelStatus,
    RejectedCandidate,
)

_STATUS_LABEL = {
    ModelStatus.PASSED: "Passed",
    ModelStatus.COMPLETED_WITH_REJECTIONS: "Completed with rejections",
    ModelStatus.FAILED_MODEL: "Failed (no verified elements)",
}

_DISCLAIMER = (
    "Synthetic demonstration data - not a real system. Handling markings are "
    "propagated source metadata only (no CUI, classification, export-control, "
    "or CMMC enforcement)."
)


def quarantine_lines(rejected: tuple[RejectedCandidate, ...]) -> list[str]:
    lines: list[str] = []
    for candidate in rejected:
        lines.append(f"  - {candidate.candidate_id} [{candidate.rule.value}]")
        lines.append(f"      {candidate.summary}")
        for anchor in candidate.anchors:
            lines.append(f"      anchor: {anchor}")
    return lines


def metrics_lines(metrics: CompileMetrics) -> list[str]:
    lines = [
        f"  Elements verified:      {metrics.elements_accepted} "
        f"(rejected {metrics.elements_rejected})",
        f"  Relationships verified: {metrics.relationships_accepted} "
        f"(rejected {metrics.relationships_rejected})",
        f"  Conflicts:              {metrics.conflict_count}",
        f"  Traceability coverage:  {metrics.traceability_coverage}",
        f"  Allocation coverage:    {metrics.allocation_coverage}",
    ]
    if metrics.ground_truth is not None:
        lines.append(
            f"  Ground truth P/R:       elements "
            f"{metrics.ground_truth.element_precision}/"
            f"{metrics.ground_truth.element_recall}, relationships "
            f"{metrics.ground_truth.relationship_precision}/"
            f"{metrics.ground_truth.relationship_recall}"
        )
    return lines


def compile_summary(result: CompileResult) -> str:
    """The interactive block printed after a compilation."""
    verification = result.verification
    lines = ["", "Engineering model compiled", ""]
    lines += metrics_lines(result.metrics)
    if result.model.rejected:
        lines += ["", "Quarantined candidates (never silently dropped):"]
        lines += quarantine_lines(result.model.rejected)
    lines += [
        "",
        f"Verification: {_STATUS_LABEL[verification.status]}",
        f"Research run: {result.run_manifest.run_id}",
        f"Model export: {result.run_directory / 'model.json'}",
        "",
        _DISCLAIMER,
    ]
    return "\n".join(lines) + "\n"


def report_text(result: CompileResult) -> str:
    """Contents of model-report.txt (derived, non-authoritative)."""
    title = f"Engineering model of {result.project.project_name} ({result.spec.project_id})"
    lines = [
        title,
        "=" * len(title),
        "",
        f"Run: {result.run_manifest.run_id}",
        f"As-of date: {result.spec.as_of_date.isoformat()}",
        f"Status: {_STATUS_LABEL[result.verification.status]}",
        "",
        "Verified elements:",
    ]
    for element in result.model.elements:
        revision = f" rev {element.revision}" if element.revision else ""
        lines.append(
            f"  {element.identity_key}{revision} [{element.element_type.value}] {element.name[:60]}"
        )
    lines += ["", "Verified relationships:"]
    for relationship in result.model.relationships:
        lines.append(
            f"  {relationship.from_ref} -{relationship.relationship_type.value}-> "
            f"{relationship.to_ref}"
        )
    if result.model.rejected:
        lines += ["", "Quarantined candidates:"]
        lines += quarantine_lines(result.model.rejected)
    lines += ["", "Metrics:"]
    lines += metrics_lines(result.metrics)
    lines += ["", _DISCLAIMER, ""]
    return "\n".join(lines)
