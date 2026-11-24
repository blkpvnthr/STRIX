"""Contract tests for strix.native.contracts — numerical-contract taxonomy and
computational-backend abstraction (R1 §5.3, §7.1)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.errors import CalculationError
from strix.native import contracts as C


class TestContractClass:
    def test_has_five_classes(self) -> None:
        names = {c.value for c in C.ContractClass}
        assert names == {"exact", "deterministic_fp", "tolerance", "approximate", "stochastic"}


class TestBackendKind:
    def test_three_backends(self) -> None:
        names = {b.value for b in C.BackendKind}
        assert names == {"python_reference", "native_cpu", "metal"}


class TestNumericalContract:
    def test_construct_exact(self) -> None:
        contract = C.NumericalContract(
            representation="decimal",
            contract_class=C.ContractClass.EXACT,
            precision="arbitrary",
            rounding="round_half_even",
            reference_method="exact Decimal arithmetic",
        )
        assert contract.absolute_tolerance is None
        assert contract.relative_tolerance is None

    def test_is_frozen(self) -> None:
        contract = C.NumericalContract(
            representation="decimal",
            contract_class=C.ContractClass.EXACT,
            precision="arbitrary",
            rounding="round_half_even",
            reference_method="x",
        )
        with pytest.raises(ValidationError):
            contract.representation = "float64"  # type: ignore[misc]

    def test_rejects_float_tolerance(self) -> None:
        with pytest.raises(ValidationError):
            C.NumericalContract(
                representation="float64",
                contract_class=C.ContractClass.TOLERANCE,
                precision="ieee754_double",
                rounding="n/a",
                absolute_tolerance=1e-9,  # type: ignore[arg-type]
                reference_method="x",
            )


class TestBackendInfo:
    def test_construct(self) -> None:
        info = C.BackendInfo(
            kind=C.BackendKind.PYTHON_REFERENCE,
            version="0.1.0",
            supported_operations=("mean", "variance"),
            numerical_precision="decimal/50",
            validation_status=C.BackendValidation.REFERENCE,
            platform="python",
        )
        assert info.kind is C.BackendKind.PYTHON_REFERENCE
        assert "mean" in info.supported_operations


class TestWithinTolerance:
    def _exact(self) -> C.NumericalContract:
        return C.NumericalContract(
            representation="decimal",
            contract_class=C.ContractClass.EXACT,
            precision="arbitrary",
            rounding="round_half_even",
            reference_method="x",
        )

    def _tol(self, *, atol: str | None, rtol: str | None) -> C.NumericalContract:
        return C.NumericalContract(
            representation="float64",
            contract_class=C.ContractClass.TOLERANCE,
            precision="ieee754_double",
            rounding="n/a",
            absolute_tolerance=None if atol is None else Decimal(atol),
            relative_tolerance=None if rtol is None else Decimal(rtol),
            reference_method="x",
        )

    def test_exact_requires_equality(self) -> None:
        contract = self._exact()
        assert C.within_tolerance(Decimal("0.3"), Decimal("0.3"), contract)
        assert not C.within_tolerance(Decimal("0.30000001"), Decimal("0.3"), contract)

    def test_absolute_tolerance(self) -> None:
        contract = self._tol(atol="0.000000001", rtol="0")
        assert C.within_tolerance(Decimal("1.0000000005"), Decimal("1"), contract)
        assert not C.within_tolerance(Decimal("1.001"), Decimal("1"), contract)

    def test_relative_tolerance(self) -> None:
        contract = self._tol(atol="0", rtol="0.001")
        assert C.within_tolerance(Decimal("1000.5"), Decimal("1000"), contract)
        assert not C.within_tolerance(Decimal("1002"), Decimal("1000"), contract)

    def test_rejects_float_observation(self) -> None:
        contract = self._tol(atol="0.1", rtol="0")
        with pytest.raises(CalculationError):
            C.within_tolerance(1.0, Decimal("1"), contract)  # type: ignore[arg-type]
