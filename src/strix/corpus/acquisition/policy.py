"""The acquisition policy contract.

Downloading never happens merely because a :class:`SearchResult` exists —
every call into :mod:`strix.corpus.acquisition.downloader` requires an
explicit :class:`AcquisitionPolicy`. HTTPS-only, no user info, no
fragments are enforced unconditionally by the downloader itself (not
policy-configurable, since there is no legitimate reason to relax them);
everything else bounded or gated here is.
"""

from __future__ import annotations

from pydantic import Field

from strix.corpus.models import CorpusModel


class AcquisitionPolicy(CorpusModel):
    """Explicit, immutable rules an acquisition session must obey."""

    policy_version: str = "1.0.0"

    #: Ports permitted on an https destination (443 unless a deployment
    #: deliberately needs an alternate HTTPS port).
    allowed_ports: frozenset[int] = frozenset({443})

    #: Maximum redirects followed before giving up (0 = none followed).
    max_redirects: int = Field(default=5, ge=0, le=20)
    #: Maximum documents one AcquisitionSession/PdfDownloader may acquire.
    max_documents: int = Field(default=50, ge=1)
    #: A single document larger than this is rejected.
    max_document_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    #: Running total across a session above which acquisition stops.
    max_total_size_bytes: int = Field(default=500 * 1024 * 1024, ge=1)

    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    read_timeout_seconds: float = Field(default=30.0, gt=0)
    write_timeout_seconds: float = Field(default=10.0, gt=0)
    pool_timeout_seconds: float = Field(default=10.0, gt=0)

    #: A SearchResult must be AccessStatus.OPEN_ACCESS unless the caller
    #: passes user_authorized=True to the downloader.
    require_open_access: bool = True
    #: A SearchResult must carry a non-empty license unless the caller
    #: passes user_authorized=True.
    require_license: bool = True
    #: Whether an explicit per-call user_authorized=True may substitute
    #: for the two checks above. Does not bypass any network-safety,
    #: domain, redirect, or size check.
    allow_explicit_authorization_override: bool = True
    #: Whether the originating SearchPlan's allowed_domains/excluded_domains
    #: are enforced against every destination in the redirect chain.
    enforce_plan_domain_restrictions: bool = True
