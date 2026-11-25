"""The native-CPU computational backend (ctypes → C kernels) (R1 §5.3, §8, L).

Loads ``libstrix_native`` via :mod:`ctypes` and exposes a subset of the reference
operations computed in IEEE-754 ``double``. Because ``double`` cannot reproduce
exact Decimal arithmetic, this backend declares a ``TOLERANCE``-class contract and
self-reports as ``UNVALIDATED`` — correctness is certified separately by the
parity harness (:mod:`strix.native.backends.parity`) against the
:class:`PythonReferenceBackend`. The backend never assigns a factual claim
verdict; it only emits evidence the independent verifier may admit (R1 §4, §21).

If the shared library cannot be loaded the backend degrades gracefully:
``available`` is ``False``, ``supports`` returns ``False``, and ``run`` raises a
typed :class:`CalculationError` rather than silently fabricating a value.
"""

from __future__ import annotations

import ctypes
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from strix.errors import CalculationError
from strix.native.arithmetic import as_decimal
from strix.native.backends.native_build import native_lib_path
from strix.native.backends.python_reference import SOFTWARE_VERSION
from strix.native.contracts import (
    BackendInfo,
    BackendKind,
    BackendValidation,
    ContractClass,
    NumericalContract,
)
from strix.native.results import ComputationResult, make_computation_result

BACKEND_VERSION = "0.1.0"

#: The ABI version the C header pins; a mismatch marks the library unusable.
_EXPECTED_ABI = 1

#: float64 kernels agree with the Decimal reference only within a tolerance.
NATIVE_CPU_CONTRACT = NumericalContract(
    representation="float64",
    contract_class=ContractClass.TOLERANCE,
    precision="ieee754_double",
    rounding="n/a",
    absolute_tolerance=Decimal("1e-9"),
    relative_tolerance=Decimal("1e-9"),
    reference_method=(
        "IEEE-754 double kernels (two-pass variance/covariance), "
        "certified for parity against PythonReferenceBackend"
    ),
)

_DoublePtr = ctypes.POINTER(ctypes.c_double)


def _to_floats(values: Sequence[object], *, what: str) -> list[float]:
    """Coerce inputs to ``float`` via the Decimal contract (rejects ``float``)."""
    if not values:
        raise CalculationError(f"operation requires a non-empty {what}")
    return [float(as_decimal(v)) for v in values]


def _array(values: Sequence[float]) -> ctypes.Array[ctypes.c_double]:
    return (ctypes.c_double * len(values))(*values)


def _req(inputs: Mapping[str, Any], key: str) -> Any:
    if key not in inputs:
        raise CalculationError(f"operation requires input {key!r}")
    return inputs[key]


@dataclass(frozen=True)
class _Op:
    name: str
    output_unit: str
    sample_sized: bool
    invoke: Callable[[NativeCPUBackend, Mapping[str, Any]], float]


def _unary(fn_name: str, *, pass_sample: bool = False) -> Callable[..., float]:
    def invoke(backend: NativeCPUBackend, inputs: Mapping[str, Any]) -> float:
        floats = _to_floats(_req(inputs, "series"), what="series")
        fn = backend._fn(fn_name)
        arr = _array(floats)
        if pass_sample:
            return float(fn(arr, len(floats), 1))
        return float(fn(arr, len(floats)))

    return invoke


def _reject_str_series(value: object, *, what: str) -> None:
    # Match the reference's multivariate coercion, which rejects a bare str/bytes
    # (iterating its characters would silently fabricate a numeric series).
    if isinstance(value, str | bytes | bytearray):
        raise CalculationError(f"{what} must be a sequence of numbers, not a string")


def _bivariate(fn_name: str, *, pass_sample: bool = False) -> Callable[..., float]:
    def invoke(backend: NativeCPUBackend, inputs: Mapping[str, Any]) -> float:
        xraw = _req(inputs, "x")
        yraw = _req(inputs, "y")
        _reject_str_series(xraw, what="x")
        _reject_str_series(yraw, what="y")
        xs = _to_floats(xraw, what="x series")
        ys = _to_floats(yraw, what="y series")
        if len(xs) != len(ys):
            raise CalculationError("x and y must have equal length")
        fn = backend._fn(fn_name)
        ax, ay = _array(xs), _array(ys)
        if pass_sample:
            return float(fn(ax, ay, len(xs), 1))
        return float(fn(ax, ay, len(xs)))

    return invoke


_OPERATIONS: dict[str, _Op] = {
    op.name: op
    for op in (
        _Op("mean", "value", True, _unary("strix_mean")),
        _Op("variance", "value", True, _unary("strix_variance", pass_sample=True)),
        _Op("stdev", "value", True, _unary("strix_stdev", pass_sample=True)),
        _Op("minimum", "value", True, _unary("strix_minimum")),
        _Op("maximum", "value", True, _unary("strix_maximum")),
        _Op("covariance", "value", False, _bivariate("strix_covariance", pass_sample=True)),
        _Op("correlation", "ratio", False, _bivariate("strix_correlation")),
    )
}

# ctypes signatures: (name) -> (argtypes, restype). restype is always c_double
# except the ABI probe.
_SIGNATURES: dict[str, list[Any]] = {
    "strix_mean": [_DoublePtr, ctypes.c_size_t],
    "strix_minimum": [_DoublePtr, ctypes.c_size_t],
    "strix_maximum": [_DoublePtr, ctypes.c_size_t],
    "strix_variance": [_DoublePtr, ctypes.c_size_t, ctypes.c_int],
    "strix_stdev": [_DoublePtr, ctypes.c_size_t, ctypes.c_int],
    "strix_covariance": [_DoublePtr, _DoublePtr, ctypes.c_size_t, ctypes.c_int],
    "strix_correlation": [_DoublePtr, _DoublePtr, ctypes.c_size_t],
}


def _load_library(path: Path | str) -> ctypes.CDLL | None:
    try:
        lib = ctypes.CDLL(str(path))
    except OSError:
        return None
    try:
        lib.strix_native_abi_version.argtypes = []
        lib.strix_native_abi_version.restype = ctypes.c_int
        if int(lib.strix_native_abi_version()) != _EXPECTED_ABI:
            return None
        for fn_name, argtypes in _SIGNATURES.items():
            fn = getattr(lib, fn_name)
            fn.argtypes = argtypes
            fn.restype = ctypes.c_double
    except (AttributeError, OSError):
        return None
    return lib


class NativeCPUBackend:
    """Native-CPU backend over ``libstrix_native`` (TOLERANCE class)."""

    backend_id = f"native_cpu@{BACKEND_VERSION}"

    def __init__(self, *, library_path: Path | str | None = None) -> None:
        resolved = Path(library_path) if library_path is not None else native_lib_path()
        self._lib: ctypes.CDLL | None = (
            _load_library(resolved) if resolved is not None else None
        )

    @property
    def available(self) -> bool:
        return self._lib is not None

    def _fn(self, name: str) -> Any:
        if self._lib is None:  # pragma: no cover - guarded by run()
            raise CalculationError("native library is not loaded")
        return getattr(self._lib, name)

    def info(self) -> BackendInfo:
        if not self.available:
            return BackendInfo(
                kind=BackendKind.NATIVE_CPU,
                version=BACKEND_VERSION,
                supported_operations=(),
                numerical_precision="ieee754_double",
                validation_status=BackendValidation.UNVALIDATED,
                platform="native_cpu",
                hardware_requirements=("C shared library libstrix_native",),
            )
        return BackendInfo(
            kind=BackendKind.NATIVE_CPU,
            version=BACKEND_VERSION,
            supported_operations=tuple(sorted(_OPERATIONS)),
            numerical_precision="ieee754_double",
            validation_status=BackendValidation.UNVALIDATED,
            platform="native_cpu",
            hardware_requirements=("C shared library libstrix_native",),
        )

    def supports(self, operation: str) -> bool:
        return self.available and operation in _OPERATIONS

    def run(
        self,
        operation: str,
        inputs: Mapping[str, Any],
        *,
        input_observation_ids: Sequence[str] = (),
        input_artifact_refs: Sequence[str] = (),
    ) -> ComputationResult:
        """Execute ``operation`` in native ``double`` and return typed evidence.

        Raises :class:`CalculationError` when the library is unavailable, the
        operation is unknown, or the kernel reports an invalid request (NaN).
        """
        if not self.available:
            raise CalculationError("native_cpu backend unavailable: libstrix_native not loaded")
        op = _OPERATIONS.get(operation)
        if op is None:
            raise CalculationError(f"unknown native operation {operation!r}")

        raw = op.invoke(self, inputs)
        if math.isnan(raw) or math.isinf(raw):
            raise CalculationError(
                f"native operation {operation!r} produced a non-finite result "
                "(invalid input, e.g. empty series or undefined correlation)"
            )
        scalar = Decimal(str(raw))

        sample_size = len(_req(inputs, "series")) if op.sample_sized else None
        return make_computation_result(
            algorithm_id=f"native.{op.name}",
            algorithm_version="1.0.0",
            backend_id=self.backend_id,
            inputs=dict(inputs),
            contract=NATIVE_CPU_CONTRACT,
            output_unit=op.output_unit,
            software_version=SOFTWARE_VERSION,
            numerical_validation_status=BackendValidation.UNVALIDATED,
            scalar=scalar,
            sample_size=sample_size,
            input_observation_ids=tuple(input_observation_ids),
            input_artifact_refs=tuple(input_artifact_refs),
        )
