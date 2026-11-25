"""Regression tests for adversarial-review findings on the native-CPU backend.

Each test pins a confirmed defect found by the Wave-6 adversarial review so it can
never silently regress:

1. ``strix_correlation`` fabricated ``0.0`` when ``sxx*syy`` overflowed float64,
   bypassing the fail-closed guard (MAJOR, numerical-honesty / fail-closed).
2. ``check_parity`` used the *subject's* self-declared contract as the pass bar, so
   a drifting backend declaring a loose tolerance self-certified (MAJOR,
   build-and-parity-trust).
3. native bivariate ops iterated a bare ``str``/``bytes`` series instead of
   rejecting it like the reference — while unary ops must stay permissive to match
   the reference (MINOR, numerical-honesty).
4. the build freshness check compared only against ``strix_native.c``, so a
   ``CMakeLists.txt``/header edit left a stale library trusted (MINOR, fail-closed).
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest

from strix.errors import CalculationError
from strix.native.backends import native_build
from strix.native.backends.native_build import build_native_library
from strix.native.backends.native_cpu import NATIVE_CPU_CONTRACT, NativeCPUBackend
from strix.native.backends.parity import ParityCase, check_parity
from strix.native.backends.python_reference import PythonReferenceBackend
from strix.native.contracts import ContractClass, NumericalContract, within_tolerance


@pytest.fixture(scope="module")
def native() -> NativeCPUBackend:
    path = build_native_library()
    if path is None:
        pytest.skip("native C toolchain unavailable; cannot build strix_native")
    return NativeCPUBackend(library_path=path)


@pytest.fixture(scope="module")
def reference() -> PythonReferenceBackend:
    return PythonReferenceBackend()


# --- Finding 1/3: correlation overflow must not fabricate 0.0 -------------


def test_correlation_large_but_representable_matches_reference(
    native: NativeCPUBackend, reference: PythonReferenceBackend
) -> None:
    # sxx*syy overflows float64 here; the scaled kernel must still compute the
    # true correlation (≈1.0) rather than a fabricated 0.0.
    big = (Decimal("-1e100"), Decimal("1e100"))
    inputs = {"x": big, "y": big}
    native_value = native.run("correlation", inputs).scalar
    reference_value = reference.run("correlation", inputs).scalar
    assert native_value is not None and reference_value is not None
    # Must NOT be the fabricated 0.0 of the old bug.
    assert native_value != Decimal(0)
    assert within_tolerance(native_value, reference_value, NATIVE_CPU_CONTRACT)


def test_correlation_beyond_float64_fails_closed(native: NativeCPUBackend) -> None:
    # Deviations square to +Inf; the backend must fail closed, never fabricate.
    huge = (Decimal("-1e200"), Decimal("1e200"))
    with pytest.raises(CalculationError):
        native.run("correlation", {"x": huge, "y": huge})


# --- Finding 2: parity must judge against a TRUSTED tolerance -------------


def _loose_drifting_backend(drift: Decimal) -> object:
    class _Drifting:
        backend_id = "drift@0.0.0"

        def run(self, operation: str, inputs: object, **_: object) -> object:
            ref = PythonReferenceBackend().run(operation, inputs)  # type: ignore[arg-type]
            loose = NumericalContract(
                representation="float64",
                contract_class=ContractClass.TOLERANCE,
                precision="ieee754_double",
                rounding="n/a",
                absolute_tolerance=Decimal("1e9"),
                relative_tolerance=Decimal("0"),
                reference_method="attacker-declared loose tolerance",
            )
            return ref.model_copy(
                update={"scalar": (ref.scalar or Decimal(0)) + drift, "contract": loose}
            )

    return _Drifting()


def test_parity_rejects_drift_hidden_behind_loose_self_declared_contract() -> None:
    # A backend that drifts by 500 but declares a 1e9 tolerance must still FAIL —
    # the harness may not trust the subject's own tolerance as the pass bar.
    report = check_parity(
        _loose_drifting_backend(Decimal("500")),  # type: ignore[arg-type]
        PythonReferenceBackend(),
        (ParityCase(operation="mean", inputs={"series": ["1", "2", "3"]}),),
    )
    assert report.all_passed is False
    assert report.outcomes[0].passed is False


def test_parity_still_certifies_the_real_native_backend(
    native: NativeCPUBackend, reference: PythonReferenceBackend
) -> None:
    report = check_parity(
        native,
        reference,
        (ParityCase(operation="mean", inputs={"series": ["1.5", "2.25", "3.75"]}),),
    )
    assert report.all_passed is True


# --- Finding 3: bivariate rejects str/bytes; unary stays permissive -------


@pytest.mark.parametrize("op", ["covariance", "correlation"])
def test_bivariate_rejects_str_series(native: NativeCPUBackend, op: str) -> None:
    with pytest.raises(CalculationError):
        native.run(op, {"x": "12", "y": "34"})


def test_unary_accepts_str_series_to_match_reference(
    native: NativeCPUBackend, reference: PythonReferenceBackend
) -> None:
    # The reference unary path iterates a str's characters; native must match it
    # (do NOT over-tighten unary, or we introduce a new parity divergence).
    native_value = native.run("mean", {"series": "123"}).scalar
    reference_value = reference.run("mean", {"series": "123"}).scalar
    assert native_value is not None and reference_value is not None
    assert within_tolerance(native_value, reference_value, NATIVE_CPU_CONTRACT)


# --- Finding 4: freshness must consider every build input -----------------


def test_freshness_invalidated_by_newer_cmakelists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "strix_native.c"
    header = tmp_path / "strix_native.h"
    cmake = tmp_path / "CMakeLists.txt"
    lib = tmp_path / "libstrix_native.so"
    for p in (source, header, cmake, lib):
        p.write_text("x")

    monkeypatch.setattr(native_build, "_SOURCE", source)
    monkeypatch.setattr(native_build, "_BUILD_INPUTS", (source, header, cmake))

    # All inputs older than the lib → fresh.
    old = 1_000_000
    for p in (source, header, cmake):
        os.utime(p, (old, old))
    os.utime(lib, (old + 100, old + 100))
    assert native_build._is_fresh(lib) is True

    # A CMakeLists edit newer than the lib → stale (the old bug returned True).
    os.utime(cmake, (old + 500, old + 500))
    assert native_build._is_fresh(lib) is False

    # A header edit newer than the lib → stale too.
    os.utime(cmake, (old, old))
    os.utime(header, (old + 500, old + 500))
    assert native_build._is_fresh(lib) is False
