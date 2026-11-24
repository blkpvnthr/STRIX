"""Fail-closed unit tests for :func:`strix.agent.response_validator.validate_answer`.

Each test crafts a *minimal* answer that violates exactly one invariant and
asserts that validation refuses it with :class:`ResponseValidationError`. The
positive tests prove a fully-valid answer (and a legitimately citation-free one
when citations are not required) passes untouched.

The invariants enumerated from the real code (response_validator.py) are:

1. No claim appears in both ``verified_claims`` and ``unresolved_claims``.
2. Every claim in ``verified_claims`` actually has status VERIFIED.
3. With ``require_citations``, every verified claim cites >= 1 evidence id.
4. Every evidence id a verified claim cites must resolve in the collector.
5. Every verified claim of a recomputed type (QUANTITATIVE,
   HISTORICAL_COMPARISON) must carry both a computed_value and a method.
6. No claim in ``unresolved_claims`` is marked VERIFIED.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.agent.agent_fixtures import build_config

from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import (
    AgentClaim,
    AgentClaimType,
    AgentVerificationStatus,
    ClaimVerification,
    ResearchAnswer,
    SourceKind,
)
from strix.agent.response_validator import validate_answer
from strix.errors import ResponseValidationError

_NOW = datetime(2026, 11, 23, tzinfo=UTC)


# --------------------------------------------------------------------------
# Construction helpers
# --------------------------------------------------------------------------


def _collector_with_evidence() -> tuple[EvidenceCollector, str]:
    """A collector holding one resolvable evidence record; returns its id."""
    collector = EvidenceCollector()
    ev = collector.register(
        source_type=SourceKind.MARKET_DATA,
        provider="Alpaca Market Data",
        source_title="SPY daily closes",
        raw=b"spy-closes-payload",
        retrieved_at=_NOW,
        source_url="https://data.alpaca.markets/SPY",
    )
    return collector, ev.evidence_id


def _claim(
    *,
    claim_id: str,
    claim_type: AgentClaimType,
    evidence_ids: tuple[str, ...],
    status: AgentVerificationStatus,
    computed_value: Decimal | None = None,
    method: str | None = None,
) -> AgentClaim:
    return AgentClaim(
        claim_id=claim_id,
        claim_type=claim_type,
        statement=f"{claim_id} statement.",
        evidence_ids=evidence_ids,
        verification=ClaimVerification(
            status=status,
            computed_value=computed_value,
            method=method,
        ),
    )


def _verified_observation(claim_id: str, eid: str) -> AgentClaim:
    """A valid verified OBSERVATION claim (not a recomputed type)."""
    return _claim(
        claim_id=claim_id,
        claim_type=AgentClaimType.OBSERVATION,
        evidence_ids=(eid,),
        status=AgentVerificationStatus.VERIFIED,
    )


def _verified_quantitative(claim_id: str, eid: str) -> AgentClaim:
    """A valid verified QUANTITATIVE claim (recomputed: value + method)."""
    return _claim(
        claim_id=claim_id,
        claim_type=AgentClaimType.QUANTITATIVE,
        evidence_ids=(eid,),
        status=AgentVerificationStatus.VERIFIED,
        computed_value=Decimal("0.12"),
        method="period_return",
    )


def _answer(
    *,
    verified: tuple[AgentClaim, ...] = (),
    unresolved: tuple[AgentClaim, ...] = (),
    collector: EvidenceCollector,
) -> ResearchAnswer:
    return ResearchAnswer(
        run_id="RUN-20261123-001",
        question="How did SPY perform?",
        data_as_of=_NOW,
        summary="summary",
        verified_claims=verified,
        unresolved_claims=unresolved,
        evidence=collector.all_evidence(),
        limitations=(),
        disclaimer="disclaimer",
    )


# --------------------------------------------------------------------------
# Positive paths
# --------------------------------------------------------------------------


def test_fully_valid_answer_passes() -> None:
    config = build_config()
    collector, eid = _collector_with_evidence()
    answer = _answer(
        verified=(
            _verified_observation("CL-obs", eid),
            _verified_quantitative("CL-quant", eid),
        ),
        unresolved=(
            _claim(
                claim_id="CL-unresolved",
                claim_type=AgentClaimType.OBSERVATION,
                evidence_ids=(eid,),
                status=AgentVerificationStatus.INSUFFICIENT_EVIDENCE,
            ),
        ),
        collector=collector,
    )
    # Must not raise.
    validate_answer(answer, collector, config)


def test_empty_answer_passes() -> None:
    config = build_config()
    collector, _ = _collector_with_evidence()
    validate_answer(_answer(collector=collector), collector, config)


def test_citationless_verified_claim_passes_when_citations_not_required() -> None:
    # Config separation: the require_citations invariant (branch 3) is policy,
    # not a hard model contract. With it disabled, a verified claim that cites
    # no evidence is allowed.
    config = build_config(STRIX_AGENT_REQUIRE_CITATIONS="false")
    assert config.require_citations is False
    collector, _ = _collector_with_evidence()
    answer = _answer(
        verified=(
            _claim(
                claim_id="CL-nocite",
                claim_type=AgentClaimType.OBSERVATION,
                evidence_ids=(),
                status=AgentVerificationStatus.VERIFIED,
            ),
        ),
        collector=collector,
    )
    validate_answer(answer, collector, config)


# --------------------------------------------------------------------------
# Branch 1: a claim in both verified and unresolved groups
# --------------------------------------------------------------------------


def test_claim_in_both_groups_is_rejected() -> None:
    config = build_config()
    collector, eid = _collector_with_evidence()
    verified = _verified_observation("CL-dup", eid)
    # Same claim_id present as a (non-verified) unresolved claim: pure overlap.
    unresolved = _claim(
        claim_id="CL-dup",
        claim_type=AgentClaimType.OBSERVATION,
        evidence_ids=(eid,),
        status=AgentVerificationStatus.INSUFFICIENT_EVIDENCE,
    )
    answer = _answer(verified=(verified,), unresolved=(unresolved,), collector=collector)
    with pytest.raises(ResponseValidationError, match="both verified and unresolved"):
        validate_answer(answer, collector, config)


# --------------------------------------------------------------------------
# Branch 2: a verified claim whose status is not VERIFIED
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [
        AgentVerificationStatus.PENDING,
        AgentVerificationStatus.CONTRADICTED,
        AgentVerificationStatus.INSUFFICIENT_EVIDENCE,
        AgentVerificationStatus.UNVERIFIABLE,
        AgentVerificationStatus.STALE,
    ],
)
def test_verified_group_requires_verified_status(status: AgentVerificationStatus) -> None:
    config = build_config()
    collector, eid = _collector_with_evidence()
    # OBSERVATION type keeps branch 5 (recomputation) out of the picture.
    claim = _claim(
        claim_id="CL-notverified",
        claim_type=AgentClaimType.OBSERVATION,
        evidence_ids=(eid,),
        status=status,
    )
    answer = _answer(verified=(claim,), collector=collector)
    with pytest.raises(ResponseValidationError, match="has status"):
        validate_answer(answer, collector, config)


# --------------------------------------------------------------------------
# Branch 3: a verified claim that cites no evidence (require_citations)
# --------------------------------------------------------------------------


def test_verified_claim_without_citations_rejected_by_default() -> None:
    config = build_config()
    assert config.require_citations is True
    collector, _ = _collector_with_evidence()
    claim = _claim(
        claim_id="CL-nocite",
        claim_type=AgentClaimType.OBSERVATION,
        evidence_ids=(),
        status=AgentVerificationStatus.VERIFIED,
    )
    answer = _answer(verified=(claim,), collector=collector)
    with pytest.raises(ResponseValidationError, match="cites no evidence"):
        validate_answer(answer, collector, config)


# --------------------------------------------------------------------------
# Branch 4: a verified claim citing evidence that does not resolve
# --------------------------------------------------------------------------


def test_verified_claim_citing_unresolvable_evidence_rejected() -> None:
    config = build_config()
    collector, _ = _collector_with_evidence()
    # Non-empty (so branch 3 does not fire) but unknown to the collector.
    claim = _claim(
        claim_id="CL-dangling",
        claim_type=AgentClaimType.OBSERVATION,
        evidence_ids=("EV-does-not-exist",),
        status=AgentVerificationStatus.VERIFIED,
    )
    answer = _answer(verified=(claim,), collector=collector)
    with pytest.raises(ResponseValidationError, match="unresolved evidence"):
        validate_answer(answer, collector, config)


# --------------------------------------------------------------------------
# Branch 5: a verified quantitative claim that was not recomputed
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claim_type",
    [AgentClaimType.QUANTITATIVE, AgentClaimType.HISTORICAL_COMPARISON],
)
def test_verified_quantitative_without_computed_value_rejected(
    claim_type: AgentClaimType,
) -> None:
    config = build_config()
    collector, eid = _collector_with_evidence()
    claim = _claim(
        claim_id="CL-notrecomputed",
        claim_type=claim_type,
        evidence_ids=(eid,),
        status=AgentVerificationStatus.VERIFIED,
        computed_value=None,  # missing recomputation
        method="period_return",
    )
    answer = _answer(verified=(claim,), collector=collector)
    with pytest.raises(ResponseValidationError, match="not independently"):
        validate_answer(answer, collector, config)


@pytest.mark.parametrize(
    "claim_type",
    [AgentClaimType.QUANTITATIVE, AgentClaimType.HISTORICAL_COMPARISON],
)
def test_verified_quantitative_without_method_rejected(
    claim_type: AgentClaimType,
) -> None:
    config = build_config()
    collector, eid = _collector_with_evidence()
    claim = _claim(
        claim_id="CL-nomethod",
        claim_type=claim_type,
        evidence_ids=(eid,),
        status=AgentVerificationStatus.VERIFIED,
        computed_value=Decimal("0.05"),
        method=None,  # no recomputation method recorded
    )
    answer = _answer(verified=(claim,), collector=collector)
    with pytest.raises(ResponseValidationError, match="not independently"):
        validate_answer(answer, collector, config)


# --------------------------------------------------------------------------
# Branch 6: an unresolved claim marked VERIFIED
# --------------------------------------------------------------------------


def test_unresolved_claim_marked_verified_rejected() -> None:
    config = build_config()
    collector, eid = _collector_with_evidence()
    claim = _claim(
        claim_id="CL-sneaky",
        claim_type=AgentClaimType.OBSERVATION,
        evidence_ids=(eid,),
        status=AgentVerificationStatus.VERIFIED,
    )
    answer = _answer(unresolved=(claim,), collector=collector)
    with pytest.raises(ResponseValidationError, match="is marked VERIFIED"):
        validate_answer(answer, collector, config)


# --------------------------------------------------------------------------
# Multiple simultaneous violations are all reported
# --------------------------------------------------------------------------


def test_multiple_violations_are_aggregated() -> None:
    config = build_config()
    collector, eid = _collector_with_evidence()
    bad_status = _claim(
        claim_id="CL-a",
        claim_type=AgentClaimType.OBSERVATION,
        evidence_ids=(eid,),
        status=AgentVerificationStatus.PENDING,
    )
    bad_quant = _claim(
        claim_id="CL-b",
        claim_type=AgentClaimType.QUANTITATIVE,
        evidence_ids=(eid,),
        status=AgentVerificationStatus.VERIFIED,
        computed_value=None,
        method=None,
    )
    answer = _answer(verified=(bad_status, bad_quant), collector=collector)
    with pytest.raises(ResponseValidationError) as excinfo:
        validate_answer(answer, collector, config)
    message = str(excinfo.value)
    assert "has status" in message
    assert "not independently" in message
