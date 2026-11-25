"""Parity certification: native-CPU backend vs the Python reference (R1 §5.3, §35).

The parity harness is the independent certification step: it runs the same
operations on the native backend and the reference backend over a fixture suite
and certifies agreement within the native backend's declared tolerance. A backend
NEVER self-certifies; certification is produced here.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from strix.native.backends.native_build import build_native_library
from strix.native.backends.native_cpu import NativeCPUBackend
from strix.native.backends.parity import (
    DEFAULT_PARITY_CASES,
    ParityCase,
    check_parity,
)
from strix.native.backends.python_reference import PythonReferenceBackend


@pytest.fixture(scope="module")
def native() -> NativeCPUBackend:
    path = build_native_library()
    if path is None:
        pytest.skip("native C toolchain unavailable; cannot build strix_native")
    return NativeCPUBackend(library_path=path)


@pytest.fixture(scope="module")
def reference() -> PythonReferenceBackend:
    return PythonReferenceBackend()


def test_default_cases_cover_every_supported_operation(native: NativeCPUBackend) -> None:
    covered = {case.operation for case in DEFAULT_PARITY_CASES}
    assert set(native.info().supported_operations) <= covered


def test_native_passes_parity_over_default_cases(
    native: NativeCPUBackend, reference: PythonReferenceBackend
) -> None:
    report = check_parity(native, reference, DEFAULT_PARITY_CASES)
    assert report.backend_id == native.backend_id
    assert report.all_passed, [
        (o.operation, str(o.reference_value), str(o.native_value), str(o.absolute_difference))
        for o in report.outcomes
        if not o.passed
    ]
    assert len(report.outcomes) == len(DEFAULT_PARITY_CASES)


def test_parity_report_records_measured_differences(
    native: NativeCPUBackend, reference: PythonReferenceBackend
) -> None:
    report = check_parity(native, reference, DEFAULT_PARITY_CASES)
    for outcome in report.outcomes:
        assert outcome.absolute_difference >= Decimal(0)
        assert outcome.reference_value is not None
        assert outcome.native_value is not None


def test_parity_detects_disagreement() -> None:
    # A deliberately-wrong fake backend must FAIL parity — proving the harness
    # actually discriminates rather than rubber-stamping.
    class WrongBackend:
        backend_id = "wrong@0.0.0"

        def run(self, operation: str, inputs: object, **_: object) -> object:
            ref = PythonReferenceBackend().run(operation, inputs)  # type: ignore[arg-type]
            bad = (ref.scalar or Decimal(0)) + Decimal("1000")
            return ref.model_copy(update={"scalar": bad})

    report = check_parity(
        WrongBackend(),  # type: ignore[arg-type]
        PythonReferenceBackend(),
        (ParityCase(operation="mean", inputs={"series": ["1", "2", "3"]}),),
    )
    assert report.all_passed is False
    assert report.outcomes[0].passed is False
