"""CLI coverage for `strix compute` (R1 §25 operational surface)."""

from __future__ import annotations

import io

from strix.cli import main


def _run(argv: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    err = io.StringIO()
    code = main(argv, stdout=out, stderr=err)
    return code, out.getvalue()


def test_compute_backends_reports_reference_backend() -> None:
    code, text = _run(["compute", "backends"])
    assert code == 0
    assert "python_reference" in text
    assert "reference" in text  # validation status
    assert "operations:" in text


def test_compute_operations_lists_native_ops() -> None:
    code, text = _run(["compute", "operations"])
    assert code == 0
    assert "mean" in text
    assert "linear_regression" in text
    assert "welch_t_test" in text


def test_compute_backends_also_reports_native_cpu() -> None:
    code, text = _run(["compute", "backends"])
    assert code == 0
    # Both the reference and the native-CPU backend are enumerated.
    assert "python_reference" in text
    assert "native_cpu" in text


def test_compute_parity_reports_certification() -> None:
    code, text = _run(["compute", "parity"])
    assert code == 0
    lowered = text.lower()
    assert "parity" in lowered
    if "unavailable" not in lowered:
        # When the native library is present it must certify (within tolerance).
        assert "native_cpu" in text
        assert "pass" in lowered
        assert "mean" in text
