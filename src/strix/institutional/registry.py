"""Durable institution registry (§13).

Registers institutions under a base directory (one subdirectory per institution,
named by its content-addressed id, holding an ``institution.json`` manifest) and
hands out cached, isolated :class:`InstanceContext` objects.

Trust posture — fail-closed throughout:

* On reload, every manifest is re-validated: its ``institution_id`` must
  content-address its own ``slug`` (enforced by :class:`Institution`) AND equal its
  enclosing directory name, and no slug or id may appear twice. A manifest that
  violates any of these — through tampering, corruption, or a bad restore — raises
  :class:`IsolationError` naming the offending directory, rather than silently
  aliasing one tenant onto another's scope.
* Manifests are written atomically and exclusively, so a crash cannot leave a torn
  file and a concurrent duplicate registration loses deterministically.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

from strix.institutional.isolation import InstanceContext, IsolationError
from strix.institutional.models import Institution, make_institution

_MANIFEST_NAME = "institution.json"


class InstitutionRegistry:
    """A persistent, uniqueness-enforcing registry of institutions."""

    def __init__(self, base_dir: Path | str) -> None:
        self._base_dir = Path(base_dir)
        self._by_slug: dict[str, Institution] = {}
        self._by_id: dict[str, Institution] = {}
        self._contexts: dict[str, InstanceContext] = {}
        self._load_existing()

    def _load_existing(self) -> None:
        if not self._base_dir.is_dir():
            return
        for child in sorted(self._base_dir.iterdir()):
            manifest = child / _MANIFEST_NAME
            if not manifest.is_file():
                continue
            # Parse fail-closed: a corrupt/unreadable manifest is a targeted error
            # (naming the directory), never an opaque crash of the whole registry.
            try:
                institution = Institution.model_validate_json(manifest.read_text())
            except (OSError, ValueError) as exc:
                raise IsolationError(
                    f"corrupt or unreadable institution manifest in {child.name!r}"
                ) from exc
            # Bind the (already content-address-checked) id to its directory name,
            # so a valid manifest cannot sit in — and redirect a tenant to — a
            # directory it does not own.
            if child.name != institution.institution_id:
                raise IsolationError(
                    f"manifest in directory {child.name!r} declares id "
                    f"{institution.institution_id!r}; id must equal its directory"
                )
            if institution.slug in self._by_slug:
                raise IsolationError(
                    f"duplicate institution slug on load: {institution.slug!r}"
                )
            if institution.institution_id in self._by_id:
                raise IsolationError(
                    f"duplicate institution id on load: {institution.institution_id!r}"
                )
            self._by_slug[institution.slug] = institution
            self._by_id[institution.institution_id] = institution

    def _write_manifest_atomically(
        self, instance_dir: Path, institution: Institution
    ) -> None:
        """Write the manifest atomically and exclusively.

        Serializes to a temp file in the same directory, fsyncs it, then
        ``os.link``s it into place — an atomic operation that also fails closed
        (``FileExistsError``) if the manifest already exists, defeating a
        concurrent duplicate registration working from a stale in-memory view.
        """
        data = institution.model_dump_json()
        manifest = instance_dir / _MANIFEST_NAME
        fd, tmp_name = tempfile.mkstemp(dir=instance_dir, prefix=".manifest-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(tmp_name, manifest)
            except FileExistsError as exc:
                raise IsolationError(
                    f"institution already registered: {institution.slug!r}"
                ) from exc
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)

    def register(self, slug: str, name: str) -> Institution:
        """Register a new institution. Raises on a duplicate slug."""
        institution = make_institution(slug, name)
        if institution.slug in self._by_slug:
            raise IsolationError(f"institution already registered: {slug!r}")
        instance_dir = self._base_dir / institution.institution_id
        instance_dir.mkdir(parents=True, exist_ok=True)
        self._write_manifest_atomically(instance_dir, institution)
        self._by_slug[institution.slug] = institution
        self._by_id[institution.institution_id] = institution
        return institution

    def get(self, slug: str) -> Institution:
        """Return the institution for ``slug``. Raises if unknown."""
        institution = self._by_slug.get(slug)
        if institution is None:
            raise IsolationError(f"unknown institution: {slug!r}")
        return institution

    def list(self) -> tuple[Institution, ...]:
        """All registered institutions, ordered by slug."""
        return tuple(self._by_slug[slug] for slug in sorted(self._by_slug))

    def context_for(self, slug: str) -> InstanceContext:
        """Return the cached :class:`InstanceContext` for ``slug``."""
        institution = self.get(slug)
        context = self._contexts.get(institution.institution_id)
        if context is None:
            context = InstanceContext(institution, self._base_dir)
            self._contexts[institution.institution_id] = context
        return context
