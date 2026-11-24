"""Numerical contracts and computational-backend abstraction (R1 §5.3, §7.1).

A :class:`NumericalContract` classifies an operation's numerical guarantees so an
independent backend (Python reference, native C++ CPU, Metal) can be certified
for parity against the reference. Backends never assign claim verdicts; they only
produce results that the independent verifier may admit.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from strix.models import DecimalValue, StrixModel
from strix.native import arithmetic as A


class ContractClass(StrEnum):
    """The five numerical-contract classes (R1 §7.1)."""

    #: Exact arithmetic (e.g. integer / exact Decimal). Bitwise reproducible.
    EXACT = "exact"
    #: Deterministic floating point under a pinned environment.
    DETERMINISTIC_FP = "deterministic_fp"
    #: Reproducible only within a stated numerical tolerance.
    TOLERANCE = "tolerance"
    #: Approximate statistical computation (documented error).
    APPROXIMATE = "approximate"
    #: Stochastic computation under recorded parameters (e.g. a seed).
    STOCHASTIC = "stochastic"


class BackendKind(StrEnum):
    """The three computational backends (R1 §5.3)."""

    PYTHON_REFERENCE = "python_reference"
    NATIVE_CPU = "native_cpu"
    METAL = "metal"


class BackendValidation(StrEnum):
    """Independent-validation status of a backend/operation."""

    UNVALIDATED = "unvalidated"
    #: This backend *is* the independent reference.
    REFERENCE = "reference"
    PARITY_PASSED = "parity_passed"
    PARITY_FAILED = "parity_failed"


class NumericalContract(StrixModel):
    """The numerical guarantees of one operation (R1 §7.1)."""

    #: Value representation, e.g. ``"decimal"`` or ``"float64"``.
    representation: str
    contract_class: ContractClass
    #: Required precision, e.g. ``"arbitrary"`` or ``"ieee754_double"``.
    precision: str
    #: Rounding behaviour, e.g. ``"round_half_even"`` or ``"n/a"``.
    rounding: str
    #: Absolute error tolerance (``None`` means exact agreement required).
    absolute_tolerance: DecimalValue | None = None
    #: Relative error tolerance (``None`` means exact agreement required).
    relative_tolerance: DecimalValue | None = None
    input_constraints: tuple[str, ...] = ()
    output_constraints: tuple[str, ...] = ()
    #: Name of the applicable independent reference method.
    reference_method: str


class BackendInfo(StrixModel):
    """Self-description of a computational backend (R1 §5.3)."""

    kind: BackendKind
    version: str
    supported_operations: tuple[str, ...]
    numerical_precision: str
    validation_status: BackendValidation
    platform: str
    hardware_requirements: tuple[str, ...] = ()


def within_tolerance(observed: object, expected: object, contract: NumericalContract) -> bool:
    """True if ``observed`` agrees with ``expected`` under ``contract``.

    With no tolerances declared the contract demands exact equality; otherwise
    the admissible deviation is ``abs_tol + rel_tol * |expected|``.
    """
    obs = A.as_decimal(observed)
    exp = A.as_decimal(expected)
    atol = contract.absolute_tolerance
    rtol = contract.relative_tolerance
    if atol is None and rtol is None:
        return obs == exp
    bound = (atol or Decimal(0)) + (rtol or Decimal(0)) * abs(exp)
    return abs(obs - exp) <= bound
