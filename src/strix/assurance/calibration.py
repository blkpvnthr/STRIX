"""Calibration harness + uncertainty propagation (R-N4, part 1).

Reference implementation of the calibration/uncertainty measurement tools for research
engine R-N4 (confidential companion §7). These are **measurement** tools used when
independently-labelled correctness data exists — the Brier score, expected calibration
error (ECE), reliability bins, and first-order uncertainty propagation.

**Honesty discipline (binding).** STRIX does **not** fabricate calibrated probabilities
when labelled data is unavailable — the operational path remains ordinal
(`assurance/uncertainty.py`), and a calibrated probability may only be produced from
parameters fitted on independent labels (not provided here; blocked on labelled data,
ALG-N4-2). This module computes calibration *diagnostics over supplied (prediction,
label) samples*; it never invents predictions. All arithmetic is exact
:class:`~decimal.Decimal` (predictions/labels are Decimals; no float).
"""

from __future__ import annotations

from decimal import Decimal

from strix.models import DecimalValue, StrixModel
from strix.native.arithmetic import checked_div, checked_mul, checked_sum

__all__ = [
    "CalibrationSample",
    "EvidenceFeatures",
    "ReliabilityBin",
    "brier_score",
    "expected_calibration_error",
    "propagate_variance",
    "reliability_bins",
]


class EvidenceFeatures(StrixModel):
    """The evidence-characterization vector ``x_c`` (each quality score in ``[0, 1]``).

    These are the independently-computed quality signals that a calibrated reliability
    model *would* consume. They are **not** a probability; mapping them to a calibrated
    ``p̂`` requires parameters fitted on independent labels (blocked).
    """

    support: DecimalValue
    independence: DecimalValue
    temporal: DecimalValue
    provenance: DecimalValue
    derivation: DecimalValue
    coverage: DecimalValue
    agreement: DecimalValue
    applicability: DecimalValue


class CalibrationSample(StrixModel):
    """One ``(prediction p̂, label y)`` pair for calibration diagnostics.

    ``prediction`` is a supplied probability in ``[0, 1]``; ``label`` is the independently
    assessed correctness in ``{0, 1}``. Supplied, never fabricated by this module.
    """

    prediction: DecimalValue
    label: int


class ReliabilityBin(StrixModel):
    """Per-bin reliability statistics for a reliability diagram."""

    lower: DecimalValue
    upper: DecimalValue
    count: int
    accuracy: DecimalValue
    confidence: DecimalValue


def _validate_samples(samples: tuple[CalibrationSample, ...]) -> None:
    if not samples:
        raise ValueError("calibration requires at least one sample")
    for s in samples:
        p = Decimal(s.prediction)
        if p < 0 or p > 1:
            raise ValueError(f"prediction {p} outside [0, 1]")
        if s.label not in (0, 1):
            raise ValueError(f"label {s.label} is not 0 or 1")


def brier_score(samples: tuple[CalibrationSample, ...]) -> Decimal:
    """Exact Brier score ``BS = N⁻¹ Σ (p̂_i - y_i)²`` over supplied samples."""
    _validate_samples(samples)
    squared = [(Decimal(s.prediction) - Decimal(s.label)) ** 2 for s in samples]
    return checked_div(checked_sum(squared), Decimal(len(samples)))


def reliability_bins(
    samples: tuple[CalibrationSample, ...], n_bins: int = 10
) -> tuple[ReliabilityBin, ...]:
    """Partition predictions into ``n_bins`` equal-width bins over ``[0, 1]`` and return
    per-bin ``(count, accuracy, confidence)``. Empty bins are reported with zero count."""
    _validate_samples(samples)
    if n_bins <= 0:
        raise ValueError("n_bins must be positive")
    width = checked_div(Decimal(1), Decimal(n_bins))
    bins: list[ReliabilityBin] = []
    for b in range(n_bins):
        lower = width * b
        upper = width * (b + 1) if b < n_bins - 1 else Decimal(1)
        # Half-open [lower, upper), last bin closed at 1 so p==1 lands in the final bin.
        members = [
            s
            for s in samples
            if Decimal(s.prediction) >= lower
            and (Decimal(s.prediction) < upper or (b == n_bins - 1 and Decimal(s.prediction) == 1))
        ]
        if members:
            accuracy = checked_div(
                checked_sum([Decimal(s.label) for s in members]), Decimal(len(members))
            )
            confidence = checked_div(
                checked_sum([Decimal(s.prediction) for s in members]), Decimal(len(members))
            )
        else:
            accuracy = Decimal(0)
            confidence = Decimal(0)
        bins.append(
            ReliabilityBin(
                lower=lower, upper=upper, count=len(members),
                accuracy=accuracy, confidence=confidence,
            )
        )
    return tuple(bins)


def expected_calibration_error(
    samples: tuple[CalibrationSample, ...], n_bins: int = 10
) -> Decimal:
    """Exact ECE ``= Σ_m (|B_m|/N)·|acc(B_m) - conf(B_m)|`` (bins fixed before testing)."""
    _validate_samples(samples)
    n = Decimal(len(samples))
    bins = reliability_bins(samples, n_bins)
    terms = [
        checked_div(Decimal(b.count), n) * abs(Decimal(b.accuracy) - Decimal(b.confidence))
        for b in bins
        if b.count > 0
    ]
    return checked_sum(terms) if terms else Decimal(0)


def propagate_variance(
    gradient: tuple[Decimal, ...], covariance: list[list[Decimal]]
) -> Decimal:
    """First-order uncertainty propagation ``Var(y) ≈ ∇fᵀ Σ ∇f`` (exact Decimal).

    ``covariance`` must be an ``nxn`` symmetric matrix (``Σ``, dependency-aware off
    diagonals) and ``gradient`` an ``n``-vector (``∇f``). Valid for near-linear ``f`` with
    small ``Σ``; interval / Monte-Carlo alternatives apply when those assumptions fail
    (not fabricated here).
    """
    n = len(gradient)
    if len(covariance) != n or any(len(row) != n for row in covariance):
        raise ValueError("covariance must be an n x n matrix matching the gradient length")
    for i in range(n):
        for j in range(n):
            if covariance[i][j] != covariance[j][i]:
                raise ValueError("covariance matrix must be symmetric")
    terms: list[Decimal] = []
    for i in range(n):
        for j in range(n):
            # Each product in an operand-sized local context (exact; the global 28-digit
            # context would round large-magnitude variance terms).
            terms.append(checked_mul(checked_mul(gradient[i], covariance[i][j]), gradient[j]))
    return checked_sum(terms) if terms else Decimal(0)
