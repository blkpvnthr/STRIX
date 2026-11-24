"""Contract tests for the PythonReferenceBackend + operation registry (R1 §5.3).

The reference backend exposes every native operation under a stable name,
produces a typed ComputationResult, and is the independent-validation baseline
(BackendValidation.REFERENCE) against which native-CPU/Metal backends are
certified for parity.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from strix.errors import CalculationError
from strix.native.backends import python_reference as B
from strix.native.contracts import BackendKind, BackendValidation, ContractClass
from strix.native.results import ResultKind


@pytest.fixture
def backend() -> B.PythonReferenceBackend:
    return B.PythonReferenceBackend()


class TestBackendInfo:
    def test_identity(self, backend: B.PythonReferenceBackend) -> None:
        info = backend.info()
        assert info.kind is BackendKind.PYTHON_REFERENCE
        assert info.validation_status is BackendValidation.REFERENCE
        assert len(info.supported_operations) >= 10

    def test_supports(self, backend: B.PythonReferenceBackend) -> None:
        assert backend.supports("mean")
        assert not backend.supports("definitely_not_an_operation")


class TestScalarOperations:
    def test_mean(self, backend: B.PythonReferenceBackend) -> None:
        r = backend.run("mean", {"series": [Decimal("1"), Decimal("2"), Decimal("3")]})
        assert r.result_kind is ResultKind.SCALAR
        assert r.scalar == Decimal("2")
        assert r.algorithm_id == "native.mean"
        assert r.backend_id.startswith("python_reference@")
        assert r.contract.contract_class is ContractClass.TOLERANCE

    def test_cagr(self, backend: B.PythonReferenceBackend) -> None:
        r = backend.run("cagr", {"begin": Decimal("100"), "end": Decimal("200"), "periods": 10})
        assert r.result_kind is ResultKind.SCALAR
        assert abs(float(r.scalar) - 0.0717734625) < 1e-6  # type: ignore[arg-type]

    def test_correlation(self, backend: B.PythonReferenceBackend) -> None:
        r = backend.run(
            "correlation",
            {"x": [Decimal(v) for v in (1, 2, 3, 4)], "y": [Decimal(v) for v in (2, 4, 6, 8)]},
        )
        assert r.scalar == Decimal("1")


class TestStructuredOperations:
    def test_linear_regression(self, backend: B.PythonReferenceBackend) -> None:
        r = backend.run(
            "linear_regression",
            {"x": [Decimal(v) for v in (0, 1, 2, 3)], "y": [Decimal(v) for v in (2, 4, 6, 8)]},
        )
        assert r.result_kind is ResultKind.STRUCTURED
        names = {k for k, _ in (r.fields or ())}
        assert {"slope", "intercept", "r_squared"} <= names

    def test_welch_t_test(self, backend: B.PythonReferenceBackend) -> None:
        a = [Decimal(v) for v in (1, 2, 3, 4, 5)]
        b = [Decimal(v) for v in (2, 4, 6, 8, 10)]
        r = backend.run("welch_t_test", {"a": a, "b": b})
        assert r.result_kind is ResultKind.STRUCTURED
        assert r.contract.contract_class is ContractClass.APPROXIMATE
        names = {k for k, _ in (r.fields or ())}
        assert "t_statistic" in names and "p_value_two_sided" in names


class TestVectorOperations:
    def test_moving_average(self, backend: B.PythonReferenceBackend) -> None:
        r = backend.run(
            "moving_average",
            {"series": [Decimal(v) for v in (1, 2, 3, 4, 5)], "window": 3},
        )
        assert r.result_kind is ResultKind.VECTOR
        assert r.vector == (Decimal("2"), Decimal("3"), Decimal("4"))


class TestErrors:
    def test_unknown_operation(self, backend: B.PythonReferenceBackend) -> None:
        with pytest.raises(CalculationError):
            backend.run("no_such_op", {"series": [Decimal("1")]})

    def test_missing_input_key(self, backend: B.PythonReferenceBackend) -> None:
        with pytest.raises(CalculationError):
            backend.run("mean", {"wrong_key": [Decimal("1")]})

    def test_propagates_float_rejection(self, backend: B.PythonReferenceBackend) -> None:
        with pytest.raises(CalculationError):
            backend.run("mean", {"series": [1.0, 2.0]})


class TestDeterminism:
    def test_same_inputs_same_id(self, backend: B.PythonReferenceBackend) -> None:
        a = backend.run("mean", {"series": [Decimal("1"), Decimal("2")]})
        b = backend.run("mean", {"series": [Decimal("1"), Decimal("2")]})
        assert a.computation_id == b.computation_id
