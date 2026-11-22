"""Tests for the immutable local object store."""

from __future__ import annotations

from pathlib import Path

import pytest

from strix.errors import LakehouseIntegrityError
from strix.lakehouse.storage import LocalObjectStore


def test_put_new_then_idempotent(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    assert store.put_immutable("a/b.json", b"hello") is True
    assert store.exists("a/b.json") is True
    # Writing identical bytes again is an idempotent no-op.
    assert store.put_immutable("a/b.json", b"hello") is False
    assert store.get("a/b.json") == b"hello"


def test_overwrite_with_different_bytes_rejected(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    store.put_immutable("a/b.json", b"one")
    with pytest.raises(LakehouseIntegrityError, match="refusing to overwrite"):
        store.put_immutable("a/b.json", b"two")


def test_path_traversal_rejected(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    for bad in ("../escape", "/abs/path", "a/../../b"):
        with pytest.raises(LakehouseIntegrityError):
            store.put_immutable(bad, b"x")


def test_get_missing_raises(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    with pytest.raises(LakehouseIntegrityError):
        store.get("nope.json")
