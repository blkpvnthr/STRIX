"""Regression tests for adversarial-review findings on institutional isolation.

Pins the confirmed defects so they cannot regress:

1. CRITICAL — the registry must not trust a manifest's institution_id on reload:
   it must hold the id↔slug content-address invariant, bind id to directory name,
   and reject duplicates — all fail-closed — so a tampered/misplaced manifest can
   never alias one tenant onto another's audit/key/resource scope.
2. MAJOR — a corrupt manifest must surface as a targeted error, not an opaque crash.
3. MAJOR/MINOR — manifest writes must be atomic and exclusive (no torn file; a
   duplicate registration across processes loses deterministically).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strix.canonical import make_id
from strix.institutional.isolation import IsolationError
from strix.institutional.models import Institution, make_institution
from strix.institutional.registry import InstitutionRegistry

_MANIFEST = "institution.json"


def _seed(base: Path, slug: str, name: str) -> Institution:
    return InstitutionRegistry(base).register(slug, name)


# --- Finding 1 (CRITICAL): id↔slug + id↔dir binding on reload -------------


def test_model_rejects_id_not_matching_slug() -> None:
    real = make_institution("beta", "Beta")
    # An institution_id that does not content-address its own slug is invalid.
    with pytest.raises(ValueError):
        Institution(institution_id=real.institution_id, slug="rogue", name="x")


def test_reload_rejects_manifest_whose_id_mismatches_slug(tmp_path: Path) -> None:
    beta = _seed(tmp_path, "beta", "Beta")
    rogue = tmp_path / "INST-000000000000"
    rogue.mkdir()
    (rogue / _MANIFEST).write_text(
        json.dumps({"institution_id": beta.institution_id, "slug": "rogue", "name": "x"})
    )
    with pytest.raises(IsolationError):
        InstitutionRegistry(tmp_path)


def test_reload_rejects_manifest_in_wrong_directory(tmp_path: Path) -> None:
    # Internally consistent manifest (id == hash(slug)) but placed in a directory
    # whose name is not that id.
    good = make_institution("gamma", "Gamma")
    wrong_dir = tmp_path / "INST-deadbeef0000"
    wrong_dir.mkdir()
    (wrong_dir / _MANIFEST).write_text(good.model_dump_json())
    with pytest.raises(IsolationError):
        InstitutionRegistry(tmp_path)


def test_reload_rejects_duplicate_slug_across_directories(tmp_path: Path) -> None:
    alpha = _seed(tmp_path, "alpha", "Alpha")
    # A second directory hijacking the same slug with a different id.
    hijack_id = "INST-ffffffffffff"
    hijack = tmp_path / hijack_id
    hijack.mkdir()
    # Must bypass the model validator's id↔slug check to simulate a crafted file,
    # so write raw JSON that the loader has to reject structurally.
    (hijack / _MANIFEST).write_text(
        json.dumps({"institution_id": hijack_id, "slug": "alpha", "name": "evil"})
    )
    with pytest.raises(IsolationError):
        InstitutionRegistry(tmp_path)
    # Sanity: the legitimate alpha id is the content-address of its slug.
    assert alpha.institution_id == make_id("INST", {"slug": "alpha"})


# --- Finding 2 (MAJOR): corrupt manifest -> targeted fail-closed error ----


def test_corrupt_manifest_raises_targeted_isolation_error(tmp_path: Path) -> None:
    _seed(tmp_path, "alpha", "Alpha")
    corrupt = tmp_path / "INST-000000000001"
    corrupt.mkdir()
    (corrupt / _MANIFEST).write_text("")  # torn / empty write
    with pytest.raises(IsolationError):
        InstitutionRegistry(tmp_path)


# --- Finding 3 (MAJOR/MINOR): atomic + exclusive write --------------------


def test_duplicate_registration_across_registries_loses_deterministically(
    tmp_path: Path,
) -> None:
    # Two registries constructed over the same empty base dir (stale in-memory
    # views); the second register of the same slug must still fail-closed via the
    # filesystem, not silently overwrite the first.
    reg1 = InstitutionRegistry(tmp_path)
    reg2 = InstitutionRegistry(tmp_path)
    reg1.register("acme", "Acme One")
    with pytest.raises(IsolationError):
        reg2.register("acme", "Acme Two")
    # The first writer's durable record survives.
    assert InstitutionRegistry(tmp_path).get("acme").name == "Acme One"


def test_registered_manifest_is_complete_valid_json(tmp_path: Path) -> None:
    inst = _seed(tmp_path, "alpha", "Alpha")
    manifest = tmp_path / inst.institution_id / _MANIFEST
    # A readable, complete manifest (atomic write leaves no torn file).
    assert Institution.model_validate_json(manifest.read_text()) == inst
