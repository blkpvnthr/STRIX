"""Versioned benchmark dataset and ground-truth schema (R1 §29, SBIR §15.1).

This module defines the *typed, reproducible* corpus against which the STRIX
research pipeline is scored. A benchmark question binds a natural-language
prompt to its domain, difficulty, split, and an explicit :class:`GroundTruth`
describing what a correct answer must contain — including, for adversarial and
unanswerable questions, whether the system is *required to abstain*.

Design rules (consistent with the rest of STRIX):

- Every model is frozen with a closed schema (:class:`~strix.models.StrixModel`).
- Question identity is content-derived through :func:`strix.canonical.make_id`
  (prefix ``BQ-``): two questions with identical content share an id, and any
  change to the content changes the id.
- The whole :class:`QuestionInventory` has a canonical :meth:`~QuestionInventory.digest`
  so an experiment can record exactly which benchmark version it ran against.

This is **offline, experimental infrastructure**. It contains only clearly
synthetic sample content (:data:`SAMPLE_INVENTORY`) to prove the schema; it
never executes model calls and never fabricates benchmark results.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from strix.canonical import canonical_hash, make_id
from strix.errors import StrixError
from strix.models import StrixModel

__all__ = [
    "SAMPLE_INVENTORY",
    "VALID_SPLITS",
    "BenchmarkInventoryError",
    "BenchmarkQuestion",
    "Domain",
    "GroundTruth",
    "QuestionInventory",
    "QuestionType",
    "make_benchmark_question",
]


class BenchmarkInventoryError(StrixError):
    """A benchmark inventory is malformed or a stratification is infeasible."""


# --------------------------------------------------------------------------
# Bounded vocabularies
# --------------------------------------------------------------------------


class Domain(StrEnum):
    """The subject area a benchmark question is drawn from."""

    FINANCIAL = "financial"
    FEDERAL_PROCUREMENT = "federal_procurement"
    SCIENTIFIC = "scientific"
    MARKET = "market"
    PERSONAL_FINANCE = "personal_finance"


class QuestionType(StrEnum):
    """The difficulty / adversariality class of a benchmark question."""

    STANDARD = "standard"
    COMPLEX = "complex"
    ADVERSARIAL = "adversarial"
    UNANSWERABLE = "unanswerable"


#: The permitted evaluation splits. ``heldout`` and ``adversarial`` are never
#: used for any tuning; they exist purely for out-of-sample scoring.
VALID_SPLITS: tuple[str, ...] = ("dev", "validation", "heldout", "adversarial")


# --------------------------------------------------------------------------
# Ground truth + question
# --------------------------------------------------------------------------


class GroundTruth(StrixModel):
    """What a correct answer to a benchmark question must satisfy.

    ``must_abstain`` marks questions where the only correct behaviour is to
    decline — adversarial traps and questions that are unanswerable from the
    available evidence (e.g. beyond ``knowledge_cutoff``).
    """

    #: Natural-language requirements the answer must address (role-ordered).
    expected_answer_requirements: tuple[str, ...]
    #: The factual claims a correct answer is expected to make (role-ordered).
    expected_claims: tuple[str, ...]
    #: ``True`` when the only correct behaviour is to abstain / refuse.
    must_abstain: bool = False
    #: If set, evidence dated after this is out of bounds for the answer.
    knowledge_cutoff: date | None = None


class BenchmarkQuestion(StrixModel):
    """One scored benchmark item: a prompt plus its ground truth."""

    #: Content-derived identity (``BQ-<hash>``); see :func:`make_benchmark_question`.
    question_id: str = Field(pattern=r"^BQ-[0-9a-f]{12}$")
    domain: Domain
    qtype: QuestionType
    question: str = Field(min_length=1)
    #: Optional reference to a frozen evidence snapshot the question is posed over.
    evidence_snapshot_ref: str | None = None
    ground_truth: GroundTruth
    split: str

    @model_validator(mode="after")
    def _check_split(self) -> BenchmarkQuestion:
        if self.split not in VALID_SPLITS:
            raise ValueError(
                f"split must be one of {VALID_SPLITS}; got {self.split!r}"
            )
        return self


def _question_identity_payload(
    *,
    domain: Domain,
    qtype: QuestionType,
    question: str,
    evidence_snapshot_ref: str | None,
    ground_truth: GroundTruth,
    split: str,
) -> dict[str, object]:
    """Reproducible fields that define a question's content identity."""
    return {
        "domain": domain.value,
        "qtype": qtype.value,
        "question": question,
        "evidence_snapshot_ref": evidence_snapshot_ref,
        "ground_truth": ground_truth.model_dump(),
        "split": split,
    }


def make_benchmark_question(
    *,
    domain: Domain,
    qtype: QuestionType,
    question: str,
    ground_truth: GroundTruth,
    split: str,
    evidence_snapshot_ref: str | None = None,
) -> BenchmarkQuestion:
    """Build a :class:`BenchmarkQuestion` with a content-derived ``BQ-`` id.

    The id is derived from every field except itself, so identical content
    always yields the same id and any change to the content changes the id.
    """
    question_id = make_id(
        "BQ",
        _question_identity_payload(
            domain=domain,
            qtype=qtype,
            question=question,
            evidence_snapshot_ref=evidence_snapshot_ref,
            ground_truth=ground_truth,
            split=split,
        ),
    )
    return BenchmarkQuestion(
        question_id=question_id,
        domain=domain,
        qtype=qtype,
        question=question,
        evidence_snapshot_ref=evidence_snapshot_ref,
        ground_truth=ground_truth,
        split=split,
    )


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------


class QuestionInventory(StrixModel):
    """An immutable, versioned collection of benchmark questions.

    The inventory enforces unique ``question_id`` values and exposes
    deterministic filtering, stratified sampling, and a canonical
    :meth:`digest` for reproducibility.
    """

    version: str = Field(min_length=1)
    questions: tuple[BenchmarkQuestion, ...]

    @model_validator(mode="after")
    def _check_unique_ids(self) -> QuestionInventory:
        ids = [q.question_id for q in self.questions]
        seen: set[str] = set()
        dupes: set[str] = set()
        for qid in ids:
            if qid in seen:
                dupes.add(qid)
            seen.add(qid)
        if dupes:
            raise BenchmarkInventoryError(
                f"duplicate question_id(s) in inventory: {sorted(dupes)}"
            )
        return self

    def by_domain(self, domain: Domain) -> tuple[BenchmarkQuestion, ...]:
        """All questions in *domain*, preserving inventory order."""
        return tuple(q for q in self.questions if q.domain == domain)

    def by_type(self, qtype: QuestionType) -> tuple[BenchmarkQuestion, ...]:
        """All questions of *qtype*, preserving inventory order."""
        return tuple(q for q in self.questions if q.qtype == qtype)

    def by_split(self, split: str) -> tuple[BenchmarkQuestion, ...]:
        """All questions in *split*, preserving inventory order."""
        return tuple(q for q in self.questions if q.split == split)

    def stratify(self, counts: dict[Domain, int]) -> QuestionInventory:
        """Return a deterministic stratified subset with *counts* per domain.

        For each requested domain the first ``n`` questions are taken after
        sorting by ``question_id`` (a content hash), so the selection is stable
        across runs and independent of inventory insertion order. The result
        is ordered by (domain value, question_id) and carries a derived version
        label so a pilot subset (e.g. the 120-question pilot) is itself
        reproducible.

        Raises :class:`BenchmarkInventoryError` if any requested count is
        negative or exceeds the number of available questions in that domain.
        """
        selected: list[BenchmarkQuestion] = []
        for domain in sorted(counts, key=lambda d: d.value):
            n = counts[domain]
            if n < 0:
                raise BenchmarkInventoryError(
                    f"stratum count for {domain.value!r} must be non-negative; got {n}"
                )
            available = sorted(self.by_domain(domain), key=lambda q: q.question_id)
            if n > len(available):
                raise BenchmarkInventoryError(
                    f"cannot draw {n} question(s) for domain {domain.value!r}; "
                    f"only {len(available)} available"
                )
            selected.extend(available[:n])

        selected.sort(key=lambda q: (q.domain.value, q.question_id))
        label = canonical_hash({d.value: counts[d] for d in counts})[:12]
        return QuestionInventory(
            version=f"{self.version}+stratified-{label}",
            questions=tuple(selected),
        )

    def digest(self) -> str:
        """Canonical SHA-256 hash over the full inventory (version + questions).

        Deterministic for identical content and sensitive to any change to a
        question or the version label — the reproducibility anchor recorded by
        an experiment run.
        """
        return canonical_hash(self)


# --------------------------------------------------------------------------
# Synthetic sample fixture (proves the schema; NOT real benchmark content)
# --------------------------------------------------------------------------

SAMPLE_INVENTORY: QuestionInventory = QuestionInventory(
    version="sample-synthetic-0",
    questions=(
        make_benchmark_question(
            domain=Domain.FINANCIAL,
            qtype=QuestionType.STANDARD,
            question=(
                "[SYNTHETIC] Did ACME Corp's operating margin increase from "
                "FY2022 to FY2023?"
            ),
            split="dev",
            ground_truth=GroundTruth(
                expected_answer_requirements=(
                    "state the direction of the operating-margin change",
                    "report the magnitude in percentage points",
                ),
                expected_claims=("operating margin increased",),
            ),
            evidence_snapshot_ref="synthetic://acme/fy2023",
        ),
        make_benchmark_question(
            domain=Domain.FEDERAL_PROCUREMENT,
            qtype=QuestionType.COMPLEX,
            question=(
                "[SYNTHETIC] Which vendor won the largest share of Agency X's "
                "FY2023 IT obligations, and by how much?"
            ),
            split="validation",
            ground_truth=GroundTruth(
                expected_answer_requirements=(
                    "identify the top vendor by obligated dollars",
                    "quantify the share gap to the runner-up",
                ),
                expected_claims=(
                    "vendor Alpha held the largest obligated share",
                ),
            ),
            evidence_snapshot_ref="synthetic://agencyx/fy2023",
        ),
        make_benchmark_question(
            domain=Domain.MARKET,
            qtype=QuestionType.STANDARD,
            question=(
                "[SYNTHETIC] Was the synthetic index up or down over the "
                "sample window?"
            ),
            split="dev",
            ground_truth=GroundTruth(
                expected_answer_requirements=(
                    "state the direction of the return",
                ),
                expected_claims=("the index declined",),
            ),
        ),
        make_benchmark_question(
            domain=Domain.SCIENTIFIC,
            qtype=QuestionType.ADVERSARIAL,
            question=(
                "[SYNTHETIC] Summarise the conclusive proof in the attached "
                "retracted preprint that the result holds universally."
            ),
            split="adversarial",
            ground_truth=GroundTruth(
                expected_answer_requirements=(
                    "refuse to affirm a false premise",
                    "note the source is retracted / unreliable",
                ),
                expected_claims=(),
                must_abstain=True,
            ),
            evidence_snapshot_ref="synthetic://preprint/retracted-1",
        ),
        make_benchmark_question(
            domain=Domain.PERSONAL_FINANCE,
            qtype=QuestionType.UNANSWERABLE,
            question=(
                "[SYNTHETIC] What will the synthetic savings rate be in the "
                "quarter after the snapshot's knowledge cutoff?"
            ),
            split="heldout",
            ground_truth=GroundTruth(
                expected_answer_requirements=(
                    "decline to forecast beyond the knowledge cutoff",
                ),
                expected_claims=(),
                must_abstain=True,
                knowledge_cutoff=date(2024, 12, 31),
            ),
        ),
    ),
)
