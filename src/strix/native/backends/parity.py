"""Backend parity certification (R1 §5.3, §35).

A non-reference backend (native CPU, Metal) is *certified* by running the same
operations over a fixture suite and checking agreement with the
:class:`PythonReferenceBackend` within the backend's own declared contract
tolerance. This is the independent-validation step: a backend never self-certifies.
``check_parity`` discriminates — a backend whose results drift outside tolerance
fails, it is not rubber-stamped.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

from strix.models import DecimalValue, StrixModel
from strix.native.contracts import ContractClass, NumericalContract, within_tolerance
from strix.native.results import ComputationResult

#: The TRUSTED tolerance the harness judges against. It is defined here — by the
#: independent verifier — NOT read from the backend under test, so a backend
#: cannot self-certify by declaring a loose contract. A float64 two-pass backend
#: is expected to agree with the exact Decimal reference to well within this bound.
TRUSTED_PARITY_TOLERANCE = NumericalContract(
    representation="float64",
    contract_class=ContractClass.TOLERANCE,
    precision="ieee754_double",
    rounding="n/a",
    absolute_tolerance=Decimal("1e-9"),
    relative_tolerance=Decimal("1e-9"),
    reference_method="independent parity ceiling (not supplied by the backend under test)",
)


class _Backend(Protocol):
    backend_id: str

    def run(
        self, operation: str, inputs: object, /, **kwargs: object
    ) -> ComputationResult: ...


class ParityCase(StrixModel):
    """One parity fixture: an operation and its inputs."""

    operation: str
    inputs: dict[str, tuple[DecimalValue, ...]]
    description: str = ""


class ParityOutcome(StrixModel):
    """The measured agreement of one operation against the reference."""

    operation: str
    passed: bool
    reference_value: DecimalValue | None
    native_value: DecimalValue | None
    absolute_difference: DecimalValue
    tolerance_bound: DecimalValue


class ParityReport(StrixModel):
    """The full certification result for a backend over a case suite."""

    backend_id: str
    reference_backend_id: str
    outcomes: tuple[ParityOutcome, ...]

    @property
    def all_passed(self) -> bool:
        return len(self.outcomes) > 0 and all(o.passed for o in self.outcomes)


def _evaluate(
    backend: _Backend,
    reference: _Backend,
    case: ParityCase,
    tolerance: NumericalContract,
) -> ParityOutcome:
    inputs = dict(case.inputs)
    native_result = backend.run(case.operation, inputs)
    reference_result = reference.run(case.operation, inputs)

    native_value = native_result.scalar
    reference_value = reference_result.scalar
    if native_value is None or reference_value is None:
        # Scalar-only parity suite; a non-scalar result cannot be certified here.
        return ParityOutcome(
            operation=case.operation,
            passed=False,
            reference_value=reference_value,
            native_value=native_value,
            absolute_difference=Decimal(0),
            tolerance_bound=Decimal(0),
        )

    # Judge against the TRUSTED tolerance, never the backend's self-declared
    # contract — otherwise a drifting backend could pass by declaring a loose one.
    atol = tolerance.absolute_tolerance or Decimal(0)
    rtol = tolerance.relative_tolerance or Decimal(0)
    bound = atol + rtol * abs(reference_value)
    diff = abs(native_value - reference_value)
    passed = within_tolerance(native_value, reference_value, tolerance)
    return ParityOutcome(
        operation=case.operation,
        passed=passed,
        reference_value=reference_value,
        native_value=native_value,
        absolute_difference=diff,
        tolerance_bound=bound,
    )


def check_parity(
    backend: _Backend,
    reference: _Backend,
    cases: Sequence[ParityCase],
    *,
    tolerance: NumericalContract = TRUSTED_PARITY_TOLERANCE,
) -> ParityReport:
    """Certify ``backend`` against ``reference`` over ``cases``.

    ``tolerance`` is the independent pass bar, defaulting to
    :data:`TRUSTED_PARITY_TOLERANCE`. It is deliberately NOT derived from the
    backend under test, so the backend cannot self-certify by emitting results
    tagged with a loose contract.
    """
    outcomes = tuple(_evaluate(backend, reference, case, tolerance) for case in cases)
    return ParityReport(
        backend_id=backend.backend_id,
        reference_backend_id=reference.backend_id,
        outcomes=outcomes,
    )


def _series(*values: str) -> tuple[Decimal, ...]:
    return tuple(Decimal(v) for v in values)


#: Fixtures covering every native-CPU operation with varied magnitudes/signs.
DEFAULT_PARITY_CASES: tuple[ParityCase, ...] = (
    ParityCase(operation="mean", inputs={"series": _series("1", "2", "3", "4", "5")}),
    ParityCase(
        operation="mean",
        inputs={"series": _series("1.5", "2.25", "3.75", "4.0", "5.5")},
    ),
    ParityCase(
        operation="mean",
        inputs={"series": _series("-10", "0", "10", "1000000", "-1000000")},
    ),
    ParityCase(
        operation="variance",
        inputs={"series": _series("1.5", "2.25", "3.75", "4.0", "5.5")},
    ),
    ParityCase(
        operation="variance",
        inputs={"series": _series("100", "101", "99", "102", "98")},
    ),
    ParityCase(
        operation="stdev",
        inputs={"series": _series("1.5", "2.25", "3.75", "4.0", "5.5")},
    ),
    ParityCase(
        operation="minimum",
        inputs={"series": _series("3", "-1", "7", "0.5", "2")},
    ),
    ParityCase(
        operation="maximum",
        inputs={"series": _series("3", "-1", "7", "0.5", "2")},
    ),
    ParityCase(
        operation="covariance",
        inputs={
            "x": _series("1", "2", "3", "4", "5"),
            "y": _series("2", "4", "5", "4", "5"),
        },
    ),
    ParityCase(
        operation="correlation",
        inputs={
            "x": _series("1", "2", "3", "4", "5"),
            "y": _series("2", "4", "5", "4", "5"),
        },
    ),
)
