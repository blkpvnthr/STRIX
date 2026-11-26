"""Fail-closed enforcement of the conclusion-level verdict in validate_answer."""

from __future__ import annotations

import pytest
from tests.agent.agent_fixtures import build_config

from strix.agent.config import AgentConfig
from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import ConclusionVerification, ResearchAnswer
from strix.agent.response_validator import validate_answer
from strix.errors import ResponseValidationError


def _answer(
    *, verdict: ConclusionVerification | None, limitations: tuple[str, ...]
) -> ResearchAnswer:
    return ResearchAnswer(
        run_id="RUN-TEST",
        question="q",
        data_as_of=None,
        summary="s",
        verified_claims=(),
        unresolved_claims=(),
        evidence=(),
        limitations=limitations,
        disclaimer="d",
        conclusion_verification=verdict,
    )


def _config() -> AgentConfig:
    return build_config()


def test_rejected_conclusion_without_communication_is_withheld() -> None:
    verdict = ConclusionVerification(
        outcome="rejected", reason_codes=("recompute_contradicted_evidence",)
    )
    answer = _answer(verdict=verdict, limitations=("some unrelated note",))
    with pytest.raises(ResponseValidationError, match="conclusion-level"):
        validate_answer(answer, EvidenceCollector(), _config())


def test_rejected_conclusion_with_communication_passes() -> None:
    verdict = ConclusionVerification(outcome="rejected")
    answer = _answer(
        verdict=verdict,
        limitations=("Conclusion-level verification REJECTED the synthesized answer: ...",),
    )
    validate_answer(answer, EvidenceCollector(), _config())  # must not raise


def test_admitted_conclusion_needs_no_special_limitation() -> None:
    verdict = ConclusionVerification(outcome="admitted")
    validate_answer(_answer(verdict=verdict, limitations=()), EvidenceCollector(), _config())
