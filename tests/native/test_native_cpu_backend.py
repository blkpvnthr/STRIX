"""Tests for the native-CPU (ctypes/C) computational backend (R1 §5.3, §8, L).

The native backend computes in IEEE-754 ``double`` and is therefore a
``TOLERANCE``-class backend — it is NEVER exact against the Decimal reference.
These tests pin (a) that honest classification, (b) agreement with the
``PythonReferenceBackend`` within the declared tolerance, and (c) graceful
degradation when the shared library is unavailable.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from strix.errors import CalculationError
from strix.native.backends.native_build import build_native_library
from strix.native.backends.native_cpu import (
    NATIVE_CPU_CONTRACT,
    NativeCPUBackend,
)
from strix.native.backends.python_reference import PythonReferenceBackend
from strix.native.contracts import (
    BackendKind,
    BackendValidation,
    ContractClass,
    within_tolerance,
)

_SERIES = [Decimal("1.5"), Decimal("2.25"), Decimal("3.75"), Decimal("4.0"), Decimal("5.5")]
_X = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5")]
_Y = [Decimal("2"), Decimal("4"), Decimal("5"), Decimal("4"), Decimal("5")]

_UNARY_OPS = ("mean", "variance", "stdev", "minimum", "maximum")
_BIVARIATE_OPS = ("covariance", "correlation")


@pytest.fixture(scope="module")
def native() -> NativeCPUBackend:
    """A loaded native backend, or skip if the toolchain cannot build the lib."""
    path = build_native_library()
    if path is None:
        pytest.skip("native C toolchain unavailable; cannot build strix_native")
    return NativeCPUBackend(library_path=path)


@pytest.fixture(scope="module")
def reference() -> PythonReferenceBackend:
    return PythonReferenceBackend()


def _inputs(op: str) -> dict[str, object]:
    if op in _BIVARIATE_OPS:
        return {"x": _X, "y": _Y}
    return {"series": _SERIES}


# --- honest numerical classification -------------------------------------


def test_contract_is_tolerance_not_exact() -> None:
    assert NATIVE_CPU_CONTRACT.contract_class is ContractClass.TOLERANCE
    assert NATIVE_CPU_CONTRACT.contract_class is not ContractClass.EXACT
    assert NATIVE_CPU_CONTRACT.representation == "float64"
    # A float64 backend must declare a non-None tolerance (never exact equality).
    assert (
        NATIVE_CPU_CONTRACT.absolute_tolerance is not None
        or NATIVE_CPU_CONTRACT.relative_tolerance is not None
    )


def test_info_reports_native_cpu_kind(native: NativeCPUBackend) -> None:
    info = native.info()
    assert info.kind is BackendKind.NATIVE_CPU
    # The backend does NOT self-certify as the reference; parity certifies it.
    assert info.validation_status is not BackendValidation.REFERENCE
    assert set(_UNARY_OPS + _BIVARIATE_OPS) <= set(info.supported_operations)


# --- agreement with the reference within tolerance -----------------------


@pytest.mark.parametrize("op", _UNARY_OPS + _BIVARIATE_OPS)
def test_native_agrees_with_reference_within_tolerance(
    native: NativeCPUBackend, reference: PythonReferenceBackend, op: str
) -> None:
    inputs = _inputs(op)
    native_result = native.run(op, inputs)
    reference_result = reference.run(op, inputs)
    assert native_result.scalar is not None
    assert reference_result.scalar is not None
    assert within_tolerance(
        native_result.scalar, reference_result.scalar, NATIVE_CPU_CONTRACT
    ), f"{op}: native {native_result.scalar} vs reference {reference_result.scalar}"


def test_result_carries_native_contract_and_backend_id(native: NativeCPUBackend) -> None:
    result = native.run("mean", {"series": _SERIES})
    assert result.contract.contract_class is ContractClass.TOLERANCE
    assert result.backend_id == native.backend_id
    assert "native_cpu" in result.backend_id
    assert result.algorithm_id == "native.mean"
    # Provenance is recorded but does not alter the value.
    assert result.numerical_validation_status is not BackendValidation.REFERENCE


def test_provenance_is_propagated(native: NativeCPUBackend) -> None:
    result = native.run(
        "mean",
        {"series": _SERIES},
        input_observation_ids=("OBS-1", "OBS-2"),
        input_artifact_refs=("ART-1",),
    )
    assert result.input_observation_ids == ("OBS-1", "OBS-2")
    assert result.input_artifact_refs == ("ART-1",)


# --- input-contract parity with the reference ----------------------------


def test_native_rejects_float_inputs_like_reference(native: NativeCPUBackend) -> None:
    # The float ban applies at the input boundary even though the kernel is
    # float64 internally; callers must supply Decimal/str/int.
    with pytest.raises((CalculationError, Exception)):
        native.run("mean", {"series": [1.5, 2.5]})


def test_unknown_operation_raises(native: NativeCPUBackend) -> None:
    with pytest.raises(CalculationError):
        native.run("no_such_operation", {"series": _SERIES})


def test_empty_series_raises(native: NativeCPUBackend) -> None:
    with pytest.raises(CalculationError):
        native.run("mean", {"series": []})


def test_variance_requires_two_points(native: NativeCPUBackend) -> None:
    with pytest.raises(CalculationError):
        native.run("variance", {"series": [Decimal("1")]})


# --- graceful degradation ------------------------------------------------


def test_missing_library_degrades_gracefully() -> None:
    backend = NativeCPUBackend(library_path="/nonexistent/path/libstrix_native.dylib")
    assert backend.available is False
    assert backend.supports("mean") is False
    info = backend.info()
    assert info.validation_status is BackendValidation.UNVALIDATED
    assert info.supported_operations == ()
    with pytest.raises(CalculationError):
        backend.run("mean", {"series": _SERIES})
