"""Tests for the versioned benchmark dataset + ground-truth schema (R1 §29)."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from strix.research_eval.dataset import (
    SAMPLE_INVENTORY,
    BenchmarkInventoryError,
    BenchmarkQuestion,
    Domain,
    GroundTruth,
    QuestionInventory,
    QuestionType,
    make_benchmark_question,
)


def _gt(**overrides: object) -> GroundTruth:
    base: dict[str, object] = {
        "expected_answer_requirements": ("state the direction",),
        "expected_claims": ("revenue increased",),
    }
    base.update(overrides)
    return GroundTruth(**base)


def _q(
    *,
    domain: Domain = Domain.FINANCIAL,
    qtype: QuestionType = QuestionType.STANDARD,
    question: str = "Did revenue grow year over year?",
    split: str = "dev",
    ground_truth: GroundTruth | None = None,
    evidence_snapshot_ref: str | None = None,
) -> BenchmarkQuestion:
    return make_benchmark_question(
        domain=domain,
        qtype=qtype,
        question=question,
        split=split,
        ground_truth=ground_truth if ground_truth is not None else _gt(),
        evidence_snapshot_ref=evidence_snapshot_ref,
    )


# --------------------------------------------------------------------------
# Construction + content identity
# --------------------------------------------------------------------------


def test_make_benchmark_question_has_bq_content_id() -> None:
    q = _q()
    assert q.question_id.startswith("BQ-")
    # Content-derived: identical inputs -> identical id.
    assert _q().question_id == q.question_id


def test_question_id_changes_when_content_changes() -> None:
    assert _q(question="A").question_id != _q(question="B").question_id
    assert _q(split="dev").question_id != _q(split="heldout").question_id


def test_ground_truth_defaults() -> None:
    gt = _gt()
    assert gt.must_abstain is False
    assert gt.knowledge_cutoff is None


def test_models_are_frozen() -> None:
    q = _q()
    with pytest.raises(ValidationError):
        q.question = "mutated"  # type: ignore[misc]


# --------------------------------------------------------------------------
# Inventory digest determinism
# --------------------------------------------------------------------------


def test_inventory_digest_is_deterministic() -> None:
    questions = (
        _q(question="Q1"),
        _q(question="Q2", domain=Domain.MARKET),
    )
    inv_a = QuestionInventory(version="v1", questions=questions)
    inv_b = QuestionInventory(version="v1", questions=questions)
    assert inv_a.digest() == inv_b.digest()
    assert len(inv_a.digest()) == 64


def test_inventory_digest_changes_when_a_question_changes() -> None:
    base = QuestionInventory(version="v1", questions=(_q(question="Q1"),))
    changed = QuestionInventory(version="v1", questions=(_q(question="Q1-edited"),))
    assert base.digest() != changed.digest()


def test_inventory_digest_changes_when_version_changes() -> None:
    qs = (_q(question="Q1"),)
    assert (
        QuestionInventory(version="v1", questions=qs).digest()
        != QuestionInventory(version="v2", questions=qs).digest()
    )


# --------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------


def test_by_domain_type_split_filters() -> None:
    q_fin = _q(domain=Domain.FINANCIAL, question="fin")
    q_mkt = _q(domain=Domain.MARKET, question="mkt")
    q_adv = _q(
        qtype=QuestionType.ADVERSARIAL,
        question="adv",
        split="adversarial",
        ground_truth=_gt(must_abstain=True),
    )
    inv = QuestionInventory(version="v1", questions=(q_fin, q_mkt, q_adv))

    assert inv.by_domain(Domain.MARKET) == (q_mkt,)
    assert set(inv.by_type(QuestionType.STANDARD)) == {q_fin, q_mkt}
    assert inv.by_split("adversarial") == (q_adv,)
    assert inv.by_domain(Domain.SCIENTIFIC) == ()


# --------------------------------------------------------------------------
# Stratification
# --------------------------------------------------------------------------


def test_stratify_returns_requested_per_stratum_counts() -> None:
    fin = tuple(_q(domain=Domain.FINANCIAL, question=f"f{i}") for i in range(5))
    mkt = tuple(_q(domain=Domain.MARKET, question=f"m{i}") for i in range(4))
    inv = QuestionInventory(version="v1", questions=fin + mkt)

    subset = inv.stratify({Domain.FINANCIAL: 3, Domain.MARKET: 2})
    assert len(subset.by_domain(Domain.FINANCIAL)) == 3
    assert len(subset.by_domain(Domain.MARKET)) == 2
    assert len(subset.questions) == 5


def test_stratify_is_deterministic() -> None:
    fin = tuple(_q(domain=Domain.FINANCIAL, question=f"f{i}") for i in range(5))
    inv = QuestionInventory(version="v1", questions=fin)
    a = inv.stratify({Domain.FINANCIAL: 3})
    b = inv.stratify({Domain.FINANCIAL: 3})
    assert a.digest() == b.digest()
    assert tuple(q.question_id for q in a.questions) == tuple(
        q.question_id for q in b.questions
    )


def test_stratify_rejects_insufficient_stratum() -> None:
    fin = tuple(_q(domain=Domain.FINANCIAL, question=f"f{i}") for i in range(2))
    inv = QuestionInventory(version="v1", questions=fin)
    with pytest.raises(BenchmarkInventoryError):
        inv.stratify({Domain.FINANCIAL: 3})


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def test_duplicate_question_id_rejected() -> None:
    q = _q()
    with pytest.raises(BenchmarkInventoryError):
        QuestionInventory(version="v1", questions=(q, q))


def test_adversarial_and_unanswerable_carry_must_abstain() -> None:
    adv = _q(
        qtype=QuestionType.ADVERSARIAL,
        split="adversarial",
        question="trap",
        ground_truth=_gt(must_abstain=True),
    )
    una = _q(
        qtype=QuestionType.UNANSWERABLE,
        split="heldout",
        question="beyond cutoff",
        ground_truth=_gt(
            must_abstain=True,
            knowledge_cutoff=date(2024, 1, 1),
        ),
    )
    assert adv.ground_truth.must_abstain is True
    assert una.ground_truth.must_abstain is True
    assert una.ground_truth.knowledge_cutoff == date(2024, 1, 1)


# --------------------------------------------------------------------------
# Sample fixture
# --------------------------------------------------------------------------


def test_sample_inventory_validates() -> None:
    assert isinstance(SAMPLE_INVENTORY, QuestionInventory)
    assert len(SAMPLE_INVENTORY.questions) >= 4
    ids = [q.question_id for q in SAMPLE_INVENTORY.questions]
    assert len(ids) == len(set(ids))
    # Spans multiple domains and splits.
    assert len({q.domain for q in SAMPLE_INVENTORY.questions}) >= 2
    assert len({q.split for q in SAMPLE_INVENTORY.questions}) >= 2
    # Abstention-required questions carry must_abstain.
    for q in SAMPLE_INVENTORY.questions:
        if q.qtype in (QuestionType.ADVERSARIAL, QuestionType.UNANSWERABLE):
            assert q.ground_truth.must_abstain is True
    assert len(SAMPLE_INVENTORY.digest()) == 64
