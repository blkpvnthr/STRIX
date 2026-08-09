"""Terminal rendering: pure text formatting of already-computed results.

This module may display prompts, progress, findings, citations, and
verification status. It may not calculate financial metrics, create or
mutate evidence and claims, verify anything, read fixtures, touch the
network, or modify saved run artifacts.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

from strix.models import ResearchReport, VerificationResult, VerificationStatus

if TYPE_CHECKING:
    from strix.replay import ReplayOutcome

BANNER = (
    "STRIX — Structured Traceability, Retrieval, and Intelligence eXtraction\n"
    "Evidence-grounded research prototype\n"
)

_PROGRESS_WIDTH = 34
_REPLAY_WIDTH = 28
_WRAP_WIDTH = 58


def progress_line(step: int, total: int, label: str, status: str) -> str:
    """One progress row, e.g. ``[1/6] Preserving source artifact........ complete``."""
    dots = "." * max(_PROGRESS_WIDTH - len(label), 3)
    return f"[{step}/{total}] {label}{dots} {status}"


def finding_text(report: ResearchReport) -> str:
    """The interactive result block shown after a run completes."""
    lines: list[str] = ["Finding", ""]
    if report.verification_status is VerificationStatus.PASSED:
        for claim in report.claims:
            lines.append(textwrap.fill(claim.statement, width=_WRAP_WIDTH))
            lines.append(f"[{', '.join(claim.evidence_ids)}]")
        verification = "Passed"
    else:
        lines.append(textwrap.fill(report.summary, width=_WRAP_WIDTH))
        verification = "Failed"
    lines += [
        "",
        f"Verification: {verification}",
        f"Research run: {report.run_id}",
        "",
        report.disclaimer,
    ]
    return "\n".join(lines) + "\n"


def failures_text(verification: VerificationResult) -> str:
    """Human-readable list of verification failures."""
    lines = ["Verification failures:"]
    lines.extend(
        f"  - [{failure.code.value}] {failure.message}" for failure in verification.failures
    )
    return "\n".join(lines) + "\n"


def report_text(report: ResearchReport) -> str:
    """Standalone content of ``report.txt`` inside a run directory."""
    title_line = report.title
    lines = [
        title_line,
        "=" * len(title_line),
        "",
        f"Run: {report.run_id}",
        f"Verification: {report.verification_status.value}",
        "",
    ]
    if report.claims:
        lines.append("Finding:")
        for claim in report.claims:
            statement = textwrap.fill(
                claim.statement, width=70, initial_indent="  ", subsequent_indent="  "
            )
            lines.append(statement)
            lines.append(f"  Evidence: {', '.join(claim.evidence_ids)}")
    else:
        lines.append(textwrap.fill(report.summary, width=70))
    lines += ["", report.disclaimer, ""]
    return "\n".join(lines)


def replay_text(outcome: ReplayOutcome) -> str:
    """The replay verification table."""
    lines = ["Replay verification", ""]
    for stage in outcome.stages:
        dots = "." * max(_REPLAY_WIDTH - len(stage.name), 3)
        status = "matched" if stage.matched else f"MISMATCH ({stage.detail})"
        lines.append(f"  {stage.name}{dots} {status}")
    lines.append("")
    verdict = "passed" if outcome.passed else "FAILED"
    lines.append(f"Result: Deterministic replay {verdict}")
    return "\n".join(lines) + "\n"
