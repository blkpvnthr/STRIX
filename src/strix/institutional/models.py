"""Institution identity (§13).

An :class:`Institution` has a content-addressed ``institution_id`` derived from its
``slug`` (its stable identity) — the display ``name`` may change without minting a
new id. All ids share one fixed length and are used with a ``"::"`` delimiter in
resource namespacing, so no institution's id can be a prefix of another's.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from strix.canonical import make_id
from strix.models import StrixModel

#: Lowercase, hyphenated, 1-63 chars; no whitespace, path, or case ambiguity.
SLUG_PATTERN = r"^[a-z0-9][a-z0-9\-]{0,62}$"


def _institution_id_for(slug: str) -> str:
    """The content-addressed id of ``slug`` (the single source of identity)."""
    return make_id("INST", {"slug": slug})


class Institution(StrixModel):
    """A content-addressed institutional tenant identity.

    The ``institution_id`` MUST be the content address of ``slug``; this invariant
    is enforced on every construction and deserialization, so a tampered manifest
    whose id disagrees with its slug is rejected the moment it is parsed.
    """

    institution_id: str = Field(pattern=r"^INST-[0-9a-f]{12}$")
    slug: str = Field(pattern=SLUG_PATTERN)
    name: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_content_address(self) -> Institution:
        expected = _institution_id_for(self.slug)
        if self.institution_id != expected:
            raise ValueError(
                f"institution_id {self.institution_id!r} does not content-address "
                f"slug {self.slug!r} (expected {expected!r})"
            )
        return self


def make_institution(slug: str, name: str) -> Institution:
    """Create an :class:`Institution`; its id is content-addressed from ``slug``.

    Raises :class:`pydantic.ValidationError` (a ``ValueError``) if ``slug`` does
    not match :data:`SLUG_PATTERN` or ``name`` is empty.
    """
    return Institution(institution_id=_institution_id_for(slug), slug=slug, name=name)
