"""Aggregate reconciliation and statistical anomaly screening (R1 §12, GAP-003).

Reconciliation reconstructs an observed aggregate from its components and
measures the residual against exact Decimal tolerances; anomaly screening flags
statistical outliers in a numeric series. Both produce **evidence** for the
verifier (R1 §12.4) and never admit or reject a claim.

Per R1 §12.3, a flagged anomaly triggers *investigation*, never automatic
rejection: :func:`screen_anomalies` reports which observations warrant a closer
look, and the downstream verifier — not this module — decides what to do.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, localcontext

from strix.errors import StrixError
from strix.models import DecimalValue, StrixModel
from strix.native import statistics as stats
from strix.native.arithmetic import (
    as_decimal,
    checked_div,
    checked_sub,
    checked_sum,
    exact_context_prec,
)

__all__ = [
    "AnomalyFinding",
    "ReconciliationError",
    "ReconciliationResult",
    "reconcile_aggregate",
    "screen_anomalies",
]


class ReconciliationError(StrixError):
    """A reconciliation or anomaly-screening input could not be trusted:
    a forbidden ``float``, a negative tolerance, an unknown method, or too few
    observations to screen."""


_AGGREGATIONS = ("sum", "mean")
_METHODS = ("iqr", "zscore")


class ReconciliationResult(StrixModel):
    """Evidence that an observed aggregate does (or does not) reconstruct from
    its components within tolerance. Carries the residuals and the tolerances
    used; it does **not** assign claim admission (R1 §12.4)."""

    aggregate_name: str
    observed_value: DecimalValue
    reconstructed_value: DecimalValue
    absolute_residual: DecimalValue
    relative_residual: DecimalValue
    absolute_tolerance: DecimalValue
    relative_tolerance: DecimalValue
    #: within_tolerance | mismatch | missing_components | incompatible
    classification: str
    missing_components: tuple[str, ...]
    source_references: tuple[str, ...]


class AnomalyFinding(StrixModel):
    """Statistical outliers in a numeric series. Flagged observations trigger
    investigation, never automatic rejection (R1 §12.3)."""

    method: str
    k: DecimalValue
    #: anomalies_present | clean
    classification: str
    flagged_indices: tuple[int, ...]
    flagged_values: tuple[DecimalValue, ...]
    lower_bound: DecimalValue | None
    upper_bound: DecimalValue | None


def _coerce(value: object, *, what: str) -> Decimal:
    """Coerce to a finite Decimal, re-raising float/parse failures as typed."""
    try:
        return as_decimal(value)
    except StrixError as exc:  # NumericalContractError is a StrixError
        raise ReconciliationError(f"{what}: {exc}") from exc


def reconcile_aggregate(
    aggregate_name: str,
    observed_value: Decimal,
    components: Sequence[Decimal],
    *,
    aggregation: str = "sum",
    abs_tol: Decimal,
    rel_tol: Decimal,
    source_references: tuple[str, ...] = (),
) -> ReconciliationResult:
    """Reconcile ``observed_value`` against ``f(components)`` within tolerance.

    ``f`` is the sum or mean of the components. The residual
    ``r = observed - f(components)`` is within tolerance when
    ``|r| <= abs_tol + rel_tol * |observed|``; otherwise it is a mismatch.

    Guards (no residual is computed for these):

    - unknown ``aggregation`` -> ``incompatible``;
    - empty ``components`` -> ``missing_components``.

    All arithmetic is exact Decimal; ``float`` and negative tolerances are
    rejected. The result is evidence only (R1 §12.4).
    """
    observed = _coerce(observed_value, what="observed_value")
    absolute_tolerance = _coerce(abs_tol, what="abs_tol")
    relative_tolerance = _coerce(rel_tol, what="rel_tol")
    if absolute_tolerance < 0 or relative_tolerance < 0:
        raise ReconciliationError("tolerances must be non-negative")

    def _result(
        *,
        reconstructed: Decimal,
        absolute_residual: Decimal,
        relative_residual: Decimal,
        classification: str,
        missing: tuple[str, ...],
    ) -> ReconciliationResult:
        return ReconciliationResult(
            aggregate_name=aggregate_name,
            observed_value=observed,
            reconstructed_value=reconstructed,
            absolute_residual=absolute_residual,
            relative_residual=relative_residual,
            absolute_tolerance=absolute_tolerance,
            relative_tolerance=relative_tolerance,
            classification=classification,
            missing_components=missing,
            source_references=source_references,
        )

    if aggregation not in _AGGREGATIONS:
        return _result(
            reconstructed=Decimal(0),
            absolute_residual=Decimal(0),
            relative_residual=Decimal(0),
            classification="incompatible",
            missing=(),
        )

    coerced = [_coerce(c, what="component") for c in components]
    if not coerced:
        return _result(
            reconstructed=Decimal(0),
            absolute_residual=Decimal(0),
            relative_residual=Decimal(0),
            classification="missing_components",
            missing=("components",),
        )

    total = checked_sum(coerced)
    reconstructed = total if aggregation == "sum" else checked_div(total, Decimal(len(coerced)))

    # Exact residual + threshold (the global prec-28 context would round large
    # reconstructions and misclassify near the tolerance boundary).
    residual = checked_sub(observed, reconstructed)
    absolute_residual = abs(residual)
    relative_residual = (
        checked_div(absolute_residual, abs(observed)) if observed != 0 else Decimal(0)
    )
    with localcontext() as ctx:
        ctx.prec = exact_context_prec(
            (observed, reconstructed, absolute_tolerance, relative_tolerance, absolute_residual),
            extra=4,
        )
        threshold = absolute_tolerance + relative_tolerance * abs(observed)
        within = absolute_residual <= threshold
    classification = "within_tolerance" if within else "mismatch"
    return _result(
        reconstructed=reconstructed,
        absolute_residual=absolute_residual,
        relative_residual=relative_residual,
        classification=classification,
        missing=(),
    )


def screen_anomalies(
    values: Sequence[Decimal],
    *,
    method: str = "iqr",
    k: Decimal | str = "1.5",
) -> AnomalyFinding:
    """Flag statistical outliers in ``values``.

    - ``iqr``: flag ``x < Q1 - k*IQR`` or ``x > Q3 + k*IQR``;
    - ``zscore``: flag ``|x - mean| / stdev > k`` (a constant series, where the
      standard deviation is zero, yields no anomalies).

    A flagged value triggers investigation, never automatic rejection
    (R1 §12.3). ``float`` is rejected; at least two observations are required.
    """
    if method not in _METHODS:
        raise ReconciliationError(
            f"unknown anomaly method {method!r}; expected one of {_METHODS}"
        )
    coerced = [_coerce(v, what="value") for v in values]
    if len(coerced) < 2:
        raise ReconciliationError("anomaly screening requires at least two observations")
    k_dec = _coerce(k, what="k")

    lower_bound: Decimal | None = None
    upper_bound: Decimal | None = None
    flagged_indices: list[int] = []
    flagged_values: list[Decimal] = []

    if method == "iqr":
        q1 = stats.quantile(coerced, Decimal("0.25"))
        q3 = stats.quantile(coerced, Decimal("0.75"))
        spread = q3 - q1
        lower_bound = q1 - k_dec * spread
        upper_bound = q3 + k_dec * spread
        for index, value in enumerate(coerced):
            if value < lower_bound or value > upper_bound:
                flagged_indices.append(index)
                flagged_values.append(value)
    else:  # zscore
        mu = stats.mean(coerced)
        sd = stats.stdev(coerced)
        if sd != 0:
            for index, value in enumerate(coerced):
                if checked_div(abs(value - mu), sd) > k_dec:
                    flagged_indices.append(index)
                    flagged_values.append(value)

    classification = "anomalies_present" if flagged_indices else "clean"
    return AnomalyFinding(
        method=method,
        k=k_dec,
        classification=classification,
        flagged_indices=tuple(flagged_indices),
        flagged_values=tuple(flagged_values),
        lower_bound=lower_bound,
        upper_bound=upper_bound,
    )
