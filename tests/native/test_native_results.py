"""Contract tests for strix.native.results — typed evidence-compatible
computation results (R1 §7.2)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.native import results as R
from strix.native.contracts import (
    BackendValidation,
    ContractClass,
    NumericalContract,
)

CONTRACT = NumericalContract(
    representation="decimal",
    contract_class=ContractClass.TOLERANCE,
    precision="50",
    rounding="round_half_even",
    absolute_tolerance=Decimal("0"),
    relative_tolerance=Decimal("0.000000001"),
    reference_method="python stdlib statistics",
)


def _scalar(**overrides: object) -> R.ComputationResult:
    kwargs: dict[str, object] = {
        "algorithm_id": "native.statistics.mean",
        "algorithm_version": "1.0.0",
        "backend_id": "python_reference@0.1.0",
        "inputs": {"values": [Decimal("1"), Decimal("2"), Decimal("3")]},
        "contract": CONTRACT,
        "scalar": Decimal("2"),
        "output_unit": "ratio",
        "software_version": "strix@0.3.0.dev0",
        "numerical_validation_status": BackendValidation.REFERENCE,
        "sample_size": 3,
    }
    kwargs.update(overrides)
    return R.make_computation_result(**kwargs)  # type: ignore[arg-type]


class TestScalarResult:
    def test_kind_and_value(self) -> None:
        r = _scalar()
        assert r.result_kind is R.ResultKind.SCALAR
        assert r.scalar == Decimal("2")
        assert r.vector is None and r.matrix is None and r.fields is None

    def test_id_is_content_derived(self) -> None:
        r = _scalar()
        assert r.computation_id.startswith("COMP-")
        assert len(r.input_digest) == 64  # full sha256 hex

    def test_is_frozen(self) -> None:
        r = _scalar()
        with pytest.raises(ValidationError):
            r.scalar = Decimal("9")  # type: ignore[misc]


class TestDeterminism:
    def test_same_inputs_same_id(self) -> None:
        assert _scalar().computation_id == _scalar().computation_id
        assert _scalar().input_digest == _scalar().input_digest

    def test_duration_excluded_from_id(self) -> None:
        a = _scalar(execution_duration_ms=10)
        b = _scalar(execution_duration_ms=9999)
        assert a.computation_id == b.computation_id
        assert a.execution_duration_ms == 10 and b.execution_duration_ms == 9999

    def test_version_changes_id(self) -> None:
        assert _scalar().computation_id != _scalar(algorithm_version="2.0.0").computation_id

    def test_inputs_change_digest(self) -> None:
        other = _scalar(inputs={"values": [Decimal("1"), Decimal("2"), Decimal("4")]})
        assert other.input_digest != _scalar().input_digest
        assert other.computation_id != _scalar().computation_id


class TestResultKinds:
    def test_vector(self) -> None:
        r = _scalar(scalar=None, vector=(Decimal("1"), Decimal("2")))
        assert r.result_kind is R.ResultKind.VECTOR
        assert r.vector == (Decimal("1"), Decimal("2"))

    def test_matrix(self) -> None:
        identity = ((Decimal("1"), Decimal("0")), (Decimal("0"), Decimal("1")))
        r = _scalar(scalar=None, matrix=identity)
        assert r.result_kind is R.ResultKind.MATRIX

    def test_structured_fields(self) -> None:
        r = _scalar(scalar=None, fields=(("slope", Decimal("2")), ("intercept", Decimal("0"))))
        assert r.result_kind is R.ResultKind.STRUCTURED
        assert r.fields == (("slope", Decimal("2")), ("intercept", Decimal("0")))


class TestValidation:
    def test_requires_exactly_one_payload(self) -> None:
        with pytest.raises((ValidationError, ValueError)):
            _scalar(scalar=None)  # none provided
        with pytest.raises((ValidationError, ValueError)):
            _scalar(vector=(Decimal("1"),))  # scalar AND vector

    def test_rejects_float_scalar(self) -> None:
        with pytest.raises((ValidationError, ValueError)):
            _scalar(scalar=1.0)

    def test_optional_metadata(self) -> None:
        r = _scalar(
            observation_interval="2020..2024",
            knowledge_cutoff=date(2024, 12, 31),
            random_seed=42,
            statistical_assumptions=("iid",),
            missing_value_policy="drop",
        )
        assert r.observation_interval == "2020..2024"
        assert r.knowledge_cutoff == date(2024, 12, 31)
        assert r.random_seed == 42
