"""Tests for the institution registry (§13)."""

from __future__ import annotations

from pathlib import Path

import pytest

from strix.institutional.isolation import InstanceContext, IsolationError
from strix.institutional.registry import InstitutionRegistry


def test_register_and_get(tmp_path: Path) -> None:
    reg = InstitutionRegistry(tmp_path)
    inst = reg.register("acme-health", "Acme Health")
    assert reg.get("acme-health") == inst


def test_duplicate_slug_rejected(tmp_path: Path) -> None:
    reg = InstitutionRegistry(tmp_path)
    reg.register("acme-health", "Acme Health")
    with pytest.raises(IsolationError):
        reg.register("acme-health", "Acme Health Again")


def test_unknown_get_raises(tmp_path: Path) -> None:
    reg = InstitutionRegistry(tmp_path)
    with pytest.raises(IsolationError):
        reg.get("nonexistent")


def test_list_returns_all_sorted(tmp_path: Path) -> None:
    reg = InstitutionRegistry(tmp_path)
    reg.register("beta-clinic", "Beta")
    reg.register("acme-health", "Acme")
    slugs = [i.slug for i in reg.list()]
    assert slugs == sorted(slugs)
    assert set(slugs) == {"acme-health", "beta-clinic"}


def test_registry_persists_across_instances(tmp_path: Path) -> None:
    InstitutionRegistry(tmp_path).register("acme-health", "Acme Health")
    # A fresh registry over the same base dir sees the persisted institution...
    reloaded = InstitutionRegistry(tmp_path)
    assert reloaded.get("acme-health").name == "Acme Health"
    # ...and still rejects a duplicate registration.
    with pytest.raises(IsolationError):
        reloaded.register("acme-health", "dupe")


def test_context_for_is_cached(tmp_path: Path) -> None:
    reg = InstitutionRegistry(tmp_path)
    reg.register("acme-health", "Acme Health")
    ctx1 = reg.context_for("acme-health")
    ctx2 = reg.context_for("acme-health")
    assert isinstance(ctx1, InstanceContext)
    assert ctx1 is ctx2  # same context → same keyring/ledger root


def test_context_for_unknown_raises(tmp_path: Path) -> None:
    reg = InstitutionRegistry(tmp_path)
    with pytest.raises(IsolationError):
        reg.context_for("nope")
