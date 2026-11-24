"""The Python reference computational backend (R1 §5.3).

Exposes every native operation under a stable name, produces a typed
:class:`~strix.native.results.ComputationResult`, and serves as the independent
numerical reference (``BackendValidation.REFERENCE``) against which native-CPU and
Metal backends are certified for parity. The backend never assigns a factual claim
verdict — it only emits evidence the independent verifier may admit (R1 §4, §21).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from strix.errors import CalculationError
from strix.native import inference as infer
from strix.native import multivariate as mv
from strix.native import statistics as st
from strix.native import timeseries as ts
from strix.native.contracts import (
    BackendInfo,
    BackendKind,
    BackendValidation,
    ContractClass,
    NumericalContract,
)
from strix.native.results import ComputationResult, make_computation_result

BACKEND_VERSION = "0.1.0"

try:
    SOFTWARE_VERSION = f"strix@{version('strix')}"
except PackageNotFoundError:  # pragma: no cover - installed in dev
    SOFTWARE_VERSION = "strix@unknown"

_DETERMINISTIC = NumericalContract(
    representation="decimal",
    contract_class=ContractClass.TOLERANCE,
    precision="50",
    rounding="round_half_even",
    absolute_tolerance=Decimal("0"),
    relative_tolerance=Decimal("0.000000001"),
    reference_method="exact Decimal arithmetic cross-checked against Python stdlib statistics",
)

_APPROXIMATE = NumericalContract(
    representation="float64",
    contract_class=ContractClass.APPROXIMATE,
    precision="ieee754_double",
    rounding="n/a",
    absolute_tolerance=Decimal("0.0001"),
    relative_tolerance=Decimal("0.0001"),
    reference_method="Student-t via regularized incomplete beta (Numerical Recipes)",
)

_STOCHASTIC = NumericalContract(
    representation="float64",
    contract_class=ContractClass.STOCHASTIC,
    precision="ieee754_double",
    rounding="n/a",
    absolute_tolerance=Decimal("0.0001"),
    relative_tolerance=Decimal("0.0001"),
    reference_method="seeded percentile bootstrap",
)


def _req(inputs: Mapping[str, Any], key: str) -> Any:
    if key not in inputs:
        raise CalculationError(f"operation requires input {key!r}")
    return inputs[key]


def _fields(model: object, names: tuple[str, ...]) -> tuple[tuple[str, Decimal], ...]:
    return tuple((name, getattr(model, name)) for name in names)


# --- operation adapters: inputs mapping -> make_computation_result kwargs subset ---


def _scalar(value: Decimal, unit: str, *, n: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"scalar": value, "output_unit": unit}
    if n is not None:
        out["sample_size"] = n
    return out


def _adapt_mean(i: Mapping[str, Any]) -> dict[str, Any]:
    s = _req(i, "series")
    return _scalar(st.mean(s), "value", n=len(s))


def _adapt_unary(
    fn: Callable[[Any], Decimal], unit: str
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    def adapter(i: Mapping[str, Any]) -> dict[str, Any]:
        s = _req(i, "series")
        return _scalar(fn(s), unit, n=len(s))

    return adapter


def _adapt_quantile(i: Mapping[str, Any]) -> dict[str, Any]:
    s = _req(i, "series")
    return _scalar(st.quantile(s, _req(i, "q")), "value", n=len(s))


def _adapt_growth_rate(i: Mapping[str, Any]) -> dict[str, Any]:
    return _scalar(ts.growth_rate(_req(i, "first"), _req(i, "last")), "ratio")


def _adapt_cagr(i: Mapping[str, Any]) -> dict[str, Any]:
    return _scalar(ts.cagr(_req(i, "begin"), _req(i, "end"), _req(i, "periods")), "ratio")


def _adapt_moving_average(i: Mapping[str, Any]) -> dict[str, Any]:
    vector = ts.moving_average(_req(i, "series"), _req(i, "window"))
    return {"vector": vector, "output_unit": "value"}


def _adapt_ewma(i: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "vector": ts.ewma(_req(i, "series"), span=i.get("span"), alpha=i.get("alpha")),
        "output_unit": "value",
    }


def _adapt_volatility(i: Mapping[str, Any]) -> dict[str, Any]:
    s = _req(i, "series")
    return _scalar(ts.volatility(s), "ratio", n=len(s))


def _adapt_autocorrelation(i: Mapping[str, Any]) -> dict[str, Any]:
    return _scalar(ts.autocorrelation(_req(i, "series"), _req(i, "lag")), "ratio")


def _adapt_linear_trend(i: Mapping[str, Any]) -> dict[str, Any]:
    fit = ts.linear_trend(_req(i, "series"))
    return {"fields": _fields(fit, ("slope", "intercept", "r_squared")), "output_unit": "value"}


def _adapt_covariance(i: Mapping[str, Any]) -> dict[str, Any]:
    return _scalar(mv.covariance(_req(i, "x"), _req(i, "y")), "value")


def _adapt_correlation(i: Mapping[str, Any]) -> dict[str, Any]:
    return _scalar(mv.correlation(_req(i, "x"), _req(i, "y")), "ratio")


def _adapt_covariance_matrix(i: Mapping[str, Any]) -> dict[str, Any]:
    return {"matrix": mv.covariance_matrix(_req(i, "columns")), "output_unit": "value"}


def _adapt_correlation_matrix(i: Mapping[str, Any]) -> dict[str, Any]:
    return {"matrix": mv.correlation_matrix(_req(i, "columns")), "output_unit": "ratio"}


def _adapt_linear_regression(i: Mapping[str, Any]) -> dict[str, Any]:
    fit = mv.linear_regression(_req(i, "x"), _req(i, "y"))
    return {
        "fields": _fields(fit, ("slope", "intercept", "r_squared", "std_error_slope")),
        "output_unit": "value",
        "sample_size": fit.n,
    }


def _adapt_welch(i: Mapping[str, Any]) -> dict[str, Any]:
    result = infer.welch_t_test(_req(i, "a"), _req(i, "b"))
    return {
        "fields": _fields(
            result,
            ("t_statistic", "degrees_of_freedom", "p_value_two_sided", "mean_a", "mean_b"),
        ),
        "output_unit": "value",
        "statistical_assumptions": ("two-sided", "unequal variance (Welch)"),
    }


def _adapt_cohens_d(i: Mapping[str, Any]) -> dict[str, Any]:
    return _scalar(infer.cohens_d(_req(i, "a"), _req(i, "b")), "effect_size")


def _adapt_mean_ci(i: Mapping[str, Any]) -> dict[str, Any]:
    ci = infer.mean_confidence_interval(_req(i, "series"), confidence=i.get("confidence", "0.95"))
    return {
        "fields": _fields(ci, ("point", "lower", "upper", "confidence", "degrees_of_freedom")),
        "output_unit": "value",
        "sample_size": ci.n,
    }


def _adapt_bootstrap(i: Mapping[str, Any]) -> dict[str, Any]:
    result = infer.bootstrap_mean_ci(
        _req(i, "series"),
        confidence=i.get("confidence", "0.95"),
        n_resamples=int(i.get("n_resamples", 2000)),
        seed=int(_req(i, "seed")),
    )
    return {
        "fields": _fields(result, ("point", "lower", "upper", "confidence")),
        "output_unit": "value",
        "random_seed": result.seed,
        "statistical_assumptions": ("percentile bootstrap",),
    }


@dataclass(frozen=True)
class _Operation:
    name: str
    contract: NumericalContract
    invoke: Callable[[Mapping[str, Any]], dict[str, Any]]
    version: str = "1.0.0"


def _op(
    name: str,
    contract: NumericalContract,
    invoke: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> _Operation:
    return _Operation(name=name, contract=contract, invoke=invoke)


_OPERATIONS: dict[str, _Operation] = {
    op.name: op
    for op in (
        _op("mean", _DETERMINISTIC, _adapt_mean),
        _op("median", _DETERMINISTIC, _adapt_unary(st.median, "value")),
        _op("variance", _DETERMINISTIC, _adapt_unary(st.variance, "value")),
        _op("stdev", _DETERMINISTIC, _adapt_unary(st.stdev, "value")),
        _op("mad", _DETERMINISTIC, _adapt_unary(st.mad, "value")),
        _op("iqr", _DETERMINISTIC, _adapt_unary(st.iqr, "value")),
        _op("skewness", _DETERMINISTIC, _adapt_unary(st.skewness, "value")),
        _op("kurtosis", _DETERMINISTIC, _adapt_unary(st.kurtosis, "value")),
        _op("minimum", _DETERMINISTIC, _adapt_unary(st.minimum, "value")),
        _op("maximum", _DETERMINISTIC, _adapt_unary(st.maximum, "value")),
        _op("quantile", _DETERMINISTIC, _adapt_quantile),
        _op("growth_rate", _DETERMINISTIC, _adapt_growth_rate),
        _op("cagr", _DETERMINISTIC, _adapt_cagr),
        _op("moving_average", _DETERMINISTIC, _adapt_moving_average),
        _op("ewma", _DETERMINISTIC, _adapt_ewma),
        _op("volatility", _DETERMINISTIC, _adapt_volatility),
        _op("autocorrelation", _DETERMINISTIC, _adapt_autocorrelation),
        _op("linear_trend", _DETERMINISTIC, _adapt_linear_trend),
        _op("covariance", _DETERMINISTIC, _adapt_covariance),
        _op("correlation", _DETERMINISTIC, _adapt_correlation),
        _op("covariance_matrix", _DETERMINISTIC, _adapt_covariance_matrix),
        _op("correlation_matrix", _DETERMINISTIC, _adapt_correlation_matrix),
        _op("linear_regression", _DETERMINISTIC, _adapt_linear_regression),
        _op("welch_t_test", _APPROXIMATE, _adapt_welch),
        _op("cohens_d", _APPROXIMATE, _adapt_cohens_d),
        _op("mean_confidence_interval", _APPROXIMATE, _adapt_mean_ci),
        _op("bootstrap_mean_ci", _STOCHASTIC, _adapt_bootstrap),
    )
}


class PythonReferenceBackend:
    """The reference computational backend. Portable; no native dependencies."""

    backend_id = f"python_reference@{BACKEND_VERSION}"

    def info(self) -> BackendInfo:
        return BackendInfo(
            kind=BackendKind.PYTHON_REFERENCE,
            version=BACKEND_VERSION,
            supported_operations=tuple(sorted(_OPERATIONS)),
            numerical_precision="decimal/50 (statistics); ieee754_double (inference)",
            validation_status=BackendValidation.REFERENCE,
            platform="python",
        )

    def supports(self, operation: str) -> bool:
        return operation in _OPERATIONS

    def run(
        self,
        operation: str,
        inputs: Mapping[str, Any],
        *,
        input_observation_ids: Sequence[str] = (),
        input_artifact_refs: Sequence[str] = (),
    ) -> ComputationResult:
        """Execute ``operation`` over ``inputs`` and return a typed result.

        ``input_observation_ids``/``input_artifact_refs`` record the provenance of
        the inputs so the result can carry a resolvable lineage into the evidence
        graph (R1 §7.2, §9.3). They do not affect the computed value.
        """
        op = _OPERATIONS.get(operation)
        if op is None:
            raise CalculationError(f"unknown native operation {operation!r}")
        outcome = op.invoke(inputs)
        return make_computation_result(
            algorithm_id=f"native.{op.name}",
            algorithm_version=op.version,
            backend_id=self.backend_id,
            inputs=dict(inputs),
            contract=op.contract,
            software_version=SOFTWARE_VERSION,
            numerical_validation_status=BackendValidation.REFERENCE,
            input_observation_ids=tuple(input_observation_ids),
            input_artifact_refs=tuple(input_artifact_refs),
            **outcome,
        )
