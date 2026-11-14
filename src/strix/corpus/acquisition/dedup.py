"""Deterministic deduplication for search candidates.

Priority order, as specified: a persistent identifier (DOI or otherwise)
beats a canonical URL, which beats a deterministic fallback over
publication metadata so every result always has *some* key. Content hash
is deliberately not a tier here — a :class:`SearchResult` is pre-download
metadata; once a document is actually acquired (a later phase), its
content hash becomes available and dedup can be re-applied at that layer
too.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from strix.canonical import sha256_hex
from strix.corpus.acquisition.models import SearchResult


def canonicalize_url(url: str | None) -> str | None:
    """Normalize a URL for comparison: lowercase scheme/host, no trailing
    slash, no fragment, tracking (``utm_*``) query parameters stripped,
    remaining query parameters sorted. Returns ``None`` for ``None``/empty
    input."""
    if not url:
        return None
    parsed = urlsplit(url)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    kept_params = sorted(
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    )
    query = urlencode(kept_params)
    return urlunsplit((scheme, netloc, path, query, ""))


def compute_deduplication_key(
    *,
    persistent_identifier: str | None,
    landing_page_url: str | None = None,
    document_url: str | None = None,
    title: str,
    venue: str | None = None,
    publication_date: date | None = None,
) -> str:
    """Deterministic dedup key: persistent identifier > canonical URL >
    a hashed fallback over title/venue/date, so every result gets a key."""
    if persistent_identifier:
        return f"pid:{persistent_identifier.strip().lower()}"
    canonical = canonicalize_url(landing_page_url) or canonicalize_url(document_url)
    if canonical:
        return f"url:{canonical}"
    fallback = "|".join(
        (
            title.strip().lower(),
            (venue or "").strip().lower(),
            publication_date.isoformat() if publication_date else "",
        )
    )
    return f"fallback:{sha256_hex(fallback.encode())}"


def deduplicate_results(results: Iterable[SearchResult]) -> tuple[SearchResult, ...]:
    """Keep the first occurrence of each ``deduplication_key``, in input order."""
    seen: set[str] = set()
    kept: list[SearchResult] = []
    for result in results:
        if result.deduplication_key in seen:
            continue
        seen.add(result.deduplication_key)
        kept.append(result)
    return tuple(kept)
