"""Tests for institution identity (§13 institutional instance isolation)."""

from __future__ import annotations

import re

import pytest

from strix.institutional.models import make_institution


def test_institution_id_is_content_addressed_and_patterned() -> None:
    inst = make_institution("acme-health", "Acme Health System")
    assert re.fullmatch(r"INST-[0-9a-f]{12}", inst.institution_id)
    assert inst.slug == "acme-health"
    assert inst.name == "Acme Health System"


def test_institution_id_is_deterministic_from_slug() -> None:
    a = make_institution("acme-health", "Acme Health System")
    b = make_institution("acme-health", "Acme Health (renamed)")
    # Identity follows the slug; the display name may change without a new id.
    assert a.institution_id == b.institution_id


def test_distinct_slugs_get_distinct_ids() -> None:
    a = make_institution("acme-health", "Acme")
    b = make_institution("beta-clinic", "Beta")
    assert a.institution_id != b.institution_id


def test_all_institution_ids_share_one_length() -> None:
    # Fixed-length ids + the "::" delimiter prevent one id being a prefix of
    # another (no resource-ownership confusion across institutions).
    ids = [make_institution(s, s).institution_id for s in ("a", "ab", "abc-x")]
    assert len({len(i) for i in ids}) == 1


@pytest.mark.parametrize("bad", ["", "Has Space", "UPPER", "under_score", "../escape", "a" * 64])
def test_invalid_slug_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        make_institution(bad, "name")
