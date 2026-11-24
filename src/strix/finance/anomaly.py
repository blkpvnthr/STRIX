"""Deterministic spending-anomaly detection over offline transactions.

These detectors screen a sequence of transactions for *outflows that warrant
a closer look* using robust descriptive statistics — not machine learning and
not any probabilistic classifier. Two complementary rules are provided:

* :func:`detect_large_transactions` flags an outflow whose magnitude exceeds
  the Tukey IQR upper fence (``Q3 + k * IQR``) of the outflow magnitudes.
* :func:`detect_duplicate_charges` flags charges that repeat the exact same
  amount and description within a small day window (a possible double charge).

Every result is a :class:`SpendingAnomaly` carrying the flagged transaction,
the statistical baseline it breached, a machine-readable ``reason_code`` and a
human-readable ``note``. A finding is **evidence for investigation only**: it
never asserts fraud and never triggers an automatic action — the ``note`` text
is deliberately non-accusatory, and the word "fraud" never appears.

Design rules this module upholds (shared with :mod:`strix.finance.ledger`):

* Models are frozen and closed (:class:`strix.models.StrixModel`).
* Monetary amounts use :class:`strix.models.DecimalValue` — binary ``float``
  is rejected at the model boundary and in every parameter.
* Arithmetic goes through :mod:`strix.native.arithmetic` and the robust
  statistics through :mod:`strix.native.statistics`, so every comparison is
  exact Decimal regardless of magnitude.
* Content-derived identifiers come from :func:`strix.canonical.make_id`.
* Invalid inputs raise :class:`AnomalyError` (a :class:`strix.errors.StrixError`).

No network access and no live account aggregation happen here.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, localcontext
from enum import StrEnum

from strix.errors import StrixError
from strix.finance.transactions import NormalizedTransaction, make_transaction
from strix.models import DecimalValue, StrixModel
from strix.native import statistics as stats
from strix.native.arithmetic import (
    NumericalContractError,
    as_decimal,
    exact_context_prec,
)

__all__ = [
    "AnomalyError",
    "AnomalyMethod",
    "NormalizedTransaction",
    "SpendingAnomaly",
    "detect_anomalies",
    "detect_duplicate_charges",
    "detect_large_transactions",
    "make_transaction",
]


class AnomalyError(StrixError):
    """An anomaly-detection input could not be trusted: a forbidden ``float``
    or unparseable ``iqr_k``, a negative fence multiplier, or a negative day
    gap."""


class AnomalyMethod(StrEnum):
    """The screening rule that produced a finding.

    :attr:`large_transaction` and :attr:`duplicate` are the two deterministic
    detectors implemented here; :attr:`iqr` and :attr:`zscore` name the generic
    statistical screens (mirroring
    :func:`strix.reconciliation.reconcile.screen_anomalies`) and complete the
    shared vocabulary.
    """

    IQR = "iqr"
    LARGE_TRANSACTION = "large_transaction"
    DUPLICATE = "duplicate"
    ZSCORE = "zscore"

    # Lowercase aliases for ergonomic attribute access in callers/tests.
    iqr = "iqr"
    large_transaction = "large_transaction"
    duplicate = "duplicate"
    zscore = "zscore"


class SpendingAnomaly(StrixModel):
    """Evidence that one transaction warrants investigation.

    This is **not** an assertion of fraud or wrongdoing and never triggers an
    automatic action. ``reason_code`` is a stable machine-readable label;
    ``note`` is a non-accusatory human-readable explanation; ``baseline`` is the
    statistical reference the flagged ``amount`` breached (both reported as
    positive outflow magnitudes).
    """

    method: AnomalyMethod
    txn_id: str
    amount: DecimalValue
    baseline: DecimalValue
    reason_code: str
    note: str


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------


def _coerce_k(iqr_k: object) -> Decimal:
    """Coerce the fence multiplier to a non-negative finite Decimal."""
    try:
        k = as_decimal(iqr_k)
    except NumericalContractError as exc:
        raise AnomalyError(f"iqr_k: {exc}") from exc
    if k < 0:
        raise AnomalyError(f"iqr_k must be non-negative, got {k}")
    return k


def _outflow_magnitudes(
    transactions: Sequence[NormalizedTransaction],
) -> list[tuple[NormalizedTransaction, Decimal]]:
    """Pair each outflow transaction with its positive magnitude ``-amount``."""
    return [(t, -t.amount) for t in transactions if t.amount < 0]


# --------------------------------------------------------------------------
# Detectors
# --------------------------------------------------------------------------


def detect_large_transactions(
    transactions: Sequence[NormalizedTransaction],
    *,
    iqr_k: Decimal | str = "1.5",
) -> tuple[SpendingAnomaly, ...]:
    """Flag outflows whose magnitude exceeds the IQR upper fence.

    The fence is ``Q3 + k * IQR`` computed over the magnitudes of every outflow
    (inflows are ignored). An outflow is flagged only when its magnitude is
    *strictly greater* than the fence, so a single outflow and a series of
    equal-magnitude outflows (where ``IQR == 0``) are never flagged.

    All arithmetic is exact Decimal. ``float`` and a negative ``iqr_k`` raise
    :class:`AnomalyError`.
    """
    k = _coerce_k(iqr_k)
    outflows = _outflow_magnitudes(transactions)
    if not outflows:
        return ()

    magnitudes = [magnitude for _, magnitude in outflows]
    q3 = stats.quantile(magnitudes, Decimal("0.75"))
    spread = stats.iqr(magnitudes)
    with localcontext() as ctx:
        ctx.prec = exact_context_prec((q3, spread, k), extra=4)
        fence = +(q3 + k * spread)

    findings = [
        SpendingAnomaly(
            method=AnomalyMethod.LARGE_TRANSACTION,
            txn_id=txn.txn_id,
            amount=magnitude,
            baseline=fence,
            reason_code="large_outflow_above_iqr_fence",
            note=(
                f"Outflow of {magnitude} exceeds the expected upper range "
                f"{fence} (Q3 + {k}*IQR) of recent outflows; review this "
                f"charge for a billing error or an unexpected amount."
            ),
        )
        for txn, magnitude in outflows
        if magnitude > fence
    ]
    return tuple(sorted(findings, key=lambda a: a.txn_id))


def detect_duplicate_charges(
    transactions: Sequence[NormalizedTransaction],
    *,
    max_day_gap: int = 2,
) -> tuple[SpendingAnomaly, ...]:
    """Flag outflows that repeat the same amount and description within a window.

    Two outflows form a duplicate pair when they share the exact absolute
    amount and the exact description and their posting dates differ by at most
    ``max_day_gap`` days. Every transaction that participates in at least one
    such pair is flagged (so a two-charge pair yields two findings). Inflows
    are ignored.

    A negative ``max_day_gap`` raises :class:`AnomalyError`.
    """
    if max_day_gap < 0:
        raise AnomalyError(f"max_day_gap must be non-negative, got {max_day_gap}")

    outflows = _outflow_magnitudes(transactions)
    # Flag by POSITIONAL index, not txn_id: txn_id is content-derived, so two
    # genuine identical charges (same amount/description/date/account) share one
    # id. A txn_id self-guard therefore skipped exactly the canonical double
    # charge this detector exists to catch. The inner `i + 1 :` slice already
    # prevents positional self-comparison, so each flagged occurrence is a real
    # second charge.
    flagged_indices: set[int] = set()
    for i, (txn_i, _mag_i) in enumerate(outflows):
        for offset, (txn_j, _mag_j) in enumerate(outflows[i + 1 :], start=i + 1):
            if txn_j.amount != txn_i.amount:
                continue
            if txn_j.description != txn_i.description:
                continue
            if abs((txn_j.posted_date - txn_i.posted_date).days) > max_day_gap:
                continue
            flagged_indices.add(i)
            flagged_indices.add(offset)

    findings = [
        SpendingAnomaly(
            method=AnomalyMethod.DUPLICATE,
            txn_id=outflows[idx][0].txn_id,
            amount=outflows[idx][1],
            baseline=outflows[idx][1],
            reason_code="repeated_identical_charge",
            note=(
                f"An identical charge of {outflows[idx][1]} for "
                f"{outflows[idx][0].description!r} appears more than once within "
                f"{max_day_gap} day(s); review whether this is an intentional "
                f"repeat or a double charge."
            ),
        )
        for idx in sorted(flagged_indices)
    ]
    return tuple(findings)


def detect_anomalies(
    transactions: Sequence[NormalizedTransaction],
    *,
    iqr_k: Decimal | str = "1.5",
) -> tuple[SpendingAnomaly, ...]:
    """Run every deterministic detector and return their union.

    The combined findings are sorted deterministically by
    ``(method, txn_id, reason_code)`` so the result is reproducible regardless
    of input order. A flagged anomaly triggers investigation, never an
    automatic action.
    """
    findings = [
        *detect_large_transactions(transactions, iqr_k=iqr_k),
        *detect_duplicate_charges(transactions),
    ]
    return tuple(
        sorted(findings, key=lambda a: (a.method.value, a.txn_id, a.reason_code))
    )
