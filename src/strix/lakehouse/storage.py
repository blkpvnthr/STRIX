"""Storage abstractions for the lakehouse.

:class:`ObjectStore` is the seam that lets Bronze/Silver/Gold persist bytes to any
backend. :class:`LocalObjectStore` is the filesystem implementation: writes are
atomic (temp file + fsync + ``os.replace``) and **immutable** — writing a path
that already holds identical bytes is an idempotent no-op, while writing
different bytes to an existing path raises :class:`LakehouseIntegrityError`.
Paths are validated to stay within the store root (no traversal).

A future cloud backend (e.g. S3) implements the same protocol; nothing above the
store depends on the filesystem.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Protocol

from strix.canonical import sha256_hex
from strix.errors import LakehouseIntegrityError


class ObjectStore(Protocol):
    """Content store for immutable artifacts (local now; cloud later)."""

    def exists(self, relative_path: str) -> bool: ...

    def get(self, relative_path: str) -> bytes: ...

    def put_immutable(self, relative_path: str, data: bytes) -> bool:
        """Write bytes if absent. Return True if newly written, False if an
        identical object already exists. Raise on a differing existing object."""
        ...


class LocalObjectStore:
    """Filesystem-backed immutable object store rooted at one directory."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _resolve(self, relative_path: str) -> Path:
        if relative_path.startswith("/") or ".." in Path(relative_path).parts:
            raise LakehouseIntegrityError(f"unsafe lakehouse path {relative_path!r}")
        root = self.root.resolve()
        candidate = (self.root / relative_path).resolve()
        if root != candidate and root not in candidate.parents:
            raise LakehouseIntegrityError(f"path {relative_path!r} escapes the lakehouse root")
        return candidate

    def exists(self, relative_path: str) -> bool:
        return self._resolve(relative_path).is_file()

    def get(self, relative_path: str) -> bytes:
        path = self._resolve(relative_path)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise LakehouseIntegrityError(f"cannot read {relative_path}: {exc}") from exc

    def put_immutable(self, relative_path: str, data: bytes) -> bool:
        path = self._resolve(relative_path)
        if path.is_file():
            if sha256_hex(path.read_bytes()) == sha256_hex(data):
                return False  # identical content already present — idempotent
            raise LakehouseIntegrityError(
                f"refusing to overwrite immutable object {relative_path} with different bytes"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(path, data)
        return True


def _write_atomic(path: Path, data: bytes) -> None:
    """Write via temp file + fsync + atomic replace in the target directory."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise LakehouseIntegrityError(f"could not write {path.name}: {exc}") from exc
