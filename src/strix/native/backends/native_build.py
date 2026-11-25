"""Locate or build the native-CPU shared library (R1 §5.3, §8, L).

The native kernels live in ``src/strix/native/_c`` and are compiled to a shared
library via CMake. This module finds a prebuilt library or builds one on demand,
returning ``None`` (never raising) when the toolchain is unavailable so callers
degrade gracefully to the :class:`PythonReferenceBackend`.

Resolution order:

1. ``STRIX_NATIVE_LIB`` — an explicit path to a prebuilt shared library.
2. A cached build under ``_c/build`` newer than every build input (the C source,
   the header, and ``CMakeLists.txt``).
3. A fresh CMake build (skipped silently if ``cmake``/a C compiler is absent).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

#: Library base name (CMake target ``strix_native`` → ``libstrix_native.*``).
LIB_STEM = "strix_native"

_C_DIR = Path(__file__).resolve().parent.parent / "_c"
_BUILD_DIR = _C_DIR / "build"
_SOURCE = _C_DIR / "strix_native.c"
_HEADER = _C_DIR / "strix_native.h"
_CMAKE = _C_DIR / "CMakeLists.txt"
#: Every input that affects the compiled library; a change to any of them must
#: invalidate a cached build (not just the C source).
_BUILD_INPUTS = (_SOURCE, _HEADER, _CMAKE)


def _lib_suffixes() -> tuple[str, ...]:
    # Bind to a plain ``str`` so mypy does not prune the other platforms'
    # branches as unreachable via ``sys.platform`` narrowing.
    platform: str = sys.platform
    if platform == "darwin":
        return (".dylib", ".so")
    if platform.startswith("win"):
        return (".dll",)
    return (".so",)


def _find_in(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None
    for suffix in _lib_suffixes():
        for name in (f"lib{LIB_STEM}{suffix}", f"{LIB_STEM}{suffix}"):
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def _env_override() -> Path | None:
    raw = os.environ.get("STRIX_NATIVE_LIB")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None


def _is_fresh(lib: Path) -> bool:
    """True if ``lib`` is at least as new as every build input.

    Compares against the C source, the header, and ``CMakeLists.txt`` — editing
    any of them (e.g. changing a compile flag) must invalidate a cached build.
    """
    try:
        inputs = [p for p in _BUILD_INPUTS if p.is_file()]
        if not inputs:
            return False
        newest_input = max(p.stat().st_mtime for p in inputs)
        return lib.stat().st_mtime >= newest_input
    except OSError:
        return False


def native_lib_path() -> Path | None:
    """Return a usable prebuilt library path, or ``None`` (never builds)."""
    override = _env_override()
    if override is not None:
        return override
    cached = _find_in(_BUILD_DIR)
    if cached is not None and _is_fresh(cached):
        return cached
    return None


def build_native_library(*, force: bool = False) -> Path | None:
    """Return a path to the native shared library, building it if needed.

    Returns ``None`` — never raises — when the C toolchain or CMake is
    unavailable, so callers can fall back to the Python reference backend.
    """
    if not force:
        existing = native_lib_path()
        if existing is not None:
            return existing

    if not _SOURCE.is_file():
        return None

    _BUILD_DIR.mkdir(parents=True, exist_ok=True)
    # Fixed argument vectors, no shell, trusted local paths only.
    try:
        subprocess.run(
            ["cmake", "-S", str(_C_DIR), "-B", str(_BUILD_DIR)],
            check=True,
            capture_output=True,
            timeout=180,
        )
        subprocess.run(
            ["cmake", "--build", str(_BUILD_DIR), "--config", "Release"],
            check=True,
            capture_output=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    return _find_in(_BUILD_DIR)
