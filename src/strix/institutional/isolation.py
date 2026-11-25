"""Per-institution instance isolation context (§13).

An :class:`InstanceContext` binds one :class:`Institution` to a dedicated on-disk
layout and an in-process keyring, and namespaces every resource id under the
institution. It is the single seam through which scoped audit and signing flow, and
it refuses — fail-closed — to operate on a resource belonging to another
institution.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from strix.assurance.signing import Keyring
from strix.audit.ledger import EventLedger
from strix.canonical import make_id
from strix.errors import StrixError
from strix.institutional.models import Institution

#: Separates an institution id from a resource id; the institution id is
#: fixed-length so this delimiter makes ownership prefixes unambiguous.
RESOURCE_DELIMITER = "::"


class IsolationError(StrixError):
    """Raised on a cross-institution access attempt or an unknown institution."""


class InstanceContext:
    """The isolated runtime scope for one institution."""

    def __init__(self, institution: Institution, base_dir: Path | str) -> None:
        self.institution = institution
        self._instance_dir = Path(base_dir) / institution.institution_id
        self._keyring = Keyring()

    @property
    def institution_id(self) -> str:
        return self.institution.institution_id

    @property
    def instance_dir(self) -> Path:
        return self._instance_dir

    @property
    def audit_dir(self) -> Path:
        return self._instance_dir / "audit"

    def ledger(self) -> EventLedger:
        """A hash-chained audit ledger rooted inside this institution's scope."""
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        return EventLedger(self.audit_dir)

    def keyring(self) -> Keyring:
        """This institution's signing keyring (never shared with another)."""
        return self._keyring

    def issue_resource_id(self, kind: str, payload: Mapping[str, Any]) -> str:
        """Mint a content-addressed resource id namespaced to this institution."""
        return f"{self.institution_id}{RESOURCE_DELIMITER}{make_id(kind, payload)}"

    def owns(self, resource_id: str) -> bool:
        """True iff ``resource_id`` was issued under this institution."""
        return resource_id.startswith(f"{self.institution_id}{RESOURCE_DELIMITER}")

    def assert_owns(self, resource_id: str) -> None:
        """Raise :class:`IsolationError` unless this institution owns the id."""
        if not self.owns(resource_id):
            raise IsolationError(
                f"resource {resource_id!r} does not belong to institution "
                f"{self.institution_id}"
            )
