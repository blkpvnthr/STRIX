"""Secure, bounded PDF acquisition over HTTPS.

Threat model: an :class:`~strix.corpus.acquisition.models.AcquisitionRecord`
describes a resource an external, untrusted party controls. Before any
byte of a response body is read, every destination in the chain — the
initial URL and every redirect target — is checked against, in order:

1. URL shape — exactly ``https``, no user info, no fragment, a resolvable
   host, a policy-approved port.
2. The originating :class:`~strix.corpus.acquisition.models.SearchPlan`'s
   ``allowed_domains``/``excluded_domains``.
3. SSRF: the hostname is resolved (through an injectable
   :class:`~strix.corpus.acquisition.network_safety.HostnameResolver`,
   never a real socket in tests) and *every* returned address is checked
   against loopback/private/link-local/multicast/reserved/unspecified/
   metadata-service ranges for both IPv4 and IPv6. One unsafe address
   among several safe ones still rejects the whole hostname.

Only after a destination passes all of that is a request made, and only
over a bounded, streamed read that enforces the document-size limit as
bytes actually arrive — never after buffering an unbounded body. See
:mod:`strix.corpus.acquisition.network_safety` for the DNS-rebinding
limitation this does **not** close.

Downloading never happens merely because a ``SearchResult`` exists: every
call requires an explicit :class:`~strix.corpus.acquisition.policy.
AcquisitionPolicy`, and an access/license gate (or explicit per-call
``user_authorized=True``) in addition to the network/content checks above.

This phase is limited to PDF acquisition and makes no live request: tests
exercise a real ``httpx.Client`` wired to ``httpx.MockTransport``, never a
socket — the suite-wide ``no_network`` guard
(``tests/conftest.py``) backstops that independently of this module's
own design.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from strix.corpus.acquisition.models import AccessStatus, SearchPlan, SearchResult
from strix.corpus.acquisition.network_safety import (
    HostnameResolver,
    ensure_safe_resolution,
    normalize_hostname,
)
from strix.corpus.acquisition.policy import AcquisitionPolicy
from strix.corpus.acquisition.redaction import redact_url
from strix.errors import (
    AcquisitionPolicyError,
    AcquisitionTimeoutError,
    PdfValidationError,
    UnsafeDestinationError,
)

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_ACCEPTED_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf"})
_REJECTED_CONTENT_TYPES = frozenset({"text/html", "application/json"})
_PDF_SIGNATURE = b"%PDF-"


@dataclass(frozen=True)
class FetchedPdf:
    """Validated, in-memory PDF bytes plus provenance — not yet stored.

    URLs here are redacted (see
    :func:`strix.corpus.acquisition.redaction.redact_url`); the raw,
    unredacted URL is used only for the actual network request and never
    retained afterward.
    """

    data: bytes
    original_url: str
    redirect_chain: tuple[str, ...]
    final_url: str
    media_type: str


@dataclass(frozen=True)
class _Destination:
    hostname: str
    port: int


def _domain_matches(hostname: str, domain: str) -> bool:
    domain = domain.lower()
    return hostname == domain or hostname.endswith(f".{domain}")


def _check_plan_domain_policy(hostname: str, plan: SearchPlan, url: str) -> None:
    if plan.excluded_domains and any(_domain_matches(hostname, d) for d in plan.excluded_domains):
        raise AcquisitionPolicyError(
            f"host {hostname!r} ({redact_url(url)!r}) is excluded by the search plan"
        )
    if plan.allowed_domains and not any(_domain_matches(hostname, d) for d in plan.allowed_domains):
        raise AcquisitionPolicyError(
            f"host {hostname!r} ({redact_url(url)!r}) is not in the search plan's allowed domains"
        )


def _validate_destination(
    url: str, *, policy: AcquisitionPolicy, plan: SearchPlan, resolver: HostnameResolver
) -> _Destination:
    """Validate one URL (initial or redirect target) against every rule.

    Raises :class:`UnsafeDestinationError` for a URL-shape or SSRF
    failure, :class:`AcquisitionPolicyError` for a plan-domain violation.
    Nothing is read from the network here — this only ever inspects the
    URL string and the resolver's answer.
    """
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise UnsafeDestinationError(
            f"URL {redact_url(url)!r} uses scheme {parsed.scheme!r}; only https is permitted"
        )
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeDestinationError(
            f"URL {redact_url(url)!r} carries user information, which is not permitted"
        )
    if parsed.fragment:
        raise UnsafeDestinationError(
            f"URL {redact_url(url)!r} carries a fragment, which is not permitted"
        )
    if not parsed.hostname:
        raise UnsafeDestinationError(f"URL {redact_url(url)!r} has no hostname")

    hostname = normalize_hostname(parsed.hostname)
    port = parsed.port if parsed.port is not None else 443
    if port not in policy.allowed_ports:
        raise UnsafeDestinationError(
            f"URL {redact_url(url)!r} uses port {port}, which is not permitted"
        )

    if policy.enforce_plan_domain_restrictions:
        _check_plan_domain_policy(hostname, plan, url)

    ensure_safe_resolution(hostname, resolver)
    return _Destination(hostname=hostname, port=port)


def _read_streaming_with_limit(response: httpx.Response, max_bytes: int) -> bytes:
    """Accumulate the body, aborting the instant it exceeds *max_bytes*.

    Never buffers past the limit regardless of what (or whether)
    Content-Length claimed — this is the independent backstop for a
    missing, absent, or understated declared size.
    """
    total = 0
    chunks: list[bytes] = []
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise AcquisitionPolicyError(
                f"streamed body exceeded the {max_bytes}-byte limit while reading"
            )
        chunks.append(chunk)
    return b"".join(chunks)


class PdfDownloader:
    """One bounded acquisition session: policy + resolver + transport.

    Tracks documents and bytes acquired across repeated :meth:`fetch`
    calls on the same instance, enforcing the policy's session-wide
    ``max_documents``/``max_total_size_bytes`` limits in addition to the
    per-call checks (declared/streamed size, redirects, timeouts,
    authorization) each call makes independently.
    """

    DOWNLOADER_VERSION = "1.0.0"

    def __init__(
        self,
        policy: AcquisitionPolicy,
        *,
        resolver: HostnameResolver,
        transport: httpx.BaseTransport,
    ) -> None:
        self.policy = policy
        self.resolver = resolver
        self.transport = transport
        self._documents_acquired = 0
        self._total_bytes_acquired = 0

    def fetch(
        self, result: SearchResult, plan: SearchPlan, *, user_authorized: bool = False
    ) -> FetchedPdf:
        """Fetch and validate one PDF; does not write anything to disk."""
        self._check_authorization(result, user_authorized=user_authorized)
        if self._documents_acquired >= self.policy.max_documents:
            raise AcquisitionPolicyError(
                f"acquisition session already reached its "
                f"{self.policy.max_documents}-document limit"
            )
        if not result.document_url:
            raise AcquisitionPolicyError(f"search result {result.result_id!r} has no document_url")

        original_url = result.document_url
        current_url = original_url
        redirect_chain: list[str] = []
        _validate_destination(current_url, policy=self.policy, plan=plan, resolver=self.resolver)

        timeout = httpx.Timeout(
            connect=self.policy.connect_timeout_seconds,
            read=self.policy.read_timeout_seconds,
            write=self.policy.write_timeout_seconds,
            pool=self.policy.pool_timeout_seconds,
        )
        data: bytes | None = None
        media_type = ""
        final_url = current_url

        with httpx.Client(
            transport=self.transport, timeout=timeout, follow_redirects=False, verify=True
        ) as client:
            for _attempt in range(self.policy.max_redirects + 1):
                try:
                    with client.stream("GET", current_url) as response:
                        if response.status_code in _REDIRECT_STATUSES:
                            location = response.headers.get("location")
                            if not location:
                                raise AcquisitionPolicyError(
                                    f"redirect from {redact_url(current_url)!r} has no "
                                    "Location header"
                                )
                            redirect_chain.append(current_url)
                            current_url = urljoin(current_url, location)
                            _validate_destination(
                                current_url, policy=self.policy, plan=plan, resolver=self.resolver
                            )
                            continue

                        if response.status_code != 200:
                            raise PdfValidationError(
                                f"unapproved HTTP status {response.status_code} from "
                                f"{redact_url(current_url)!r}"
                            )

                        content_type = response.headers.get("content-type", "")
                        base_type = content_type.split(";", 1)[0].strip().lower()
                        if base_type in _REJECTED_CONTENT_TYPES:
                            raise PdfValidationError(
                                f"response from {redact_url(current_url)!r} looks like an "
                                f"HTML/JSON error page (content-type {content_type!r})"
                            )
                        if base_type not in _ACCEPTED_CONTENT_TYPES:
                            raise PdfValidationError(
                                f"response from {redact_url(current_url)!r} has incompatible "
                                f"content type {content_type!r}"
                            )

                        self._check_declared_size(response.headers.get("content-length"))

                        data = _read_streaming_with_limit(
                            response, self.policy.max_document_size_bytes
                        )
                        media_type = base_type
                        final_url = current_url
                except httpx.TimeoutException as exc:
                    raise AcquisitionTimeoutError(
                        f"timed out retrieving {redact_url(current_url)!r}: {exc}"
                    ) from exc
                else:
                    break
            else:
                raise AcquisitionPolicyError(
                    f"redirect limit of {self.policy.max_redirects} exceeded"
                )

        assert data is not None  # the loop exits normally only after assigning it
        if not data.startswith(_PDF_SIGNATURE):
            raise PdfValidationError(
                f"response from {redact_url(final_url)!r} does not have the %PDF- file signature"
            )
        if self._total_bytes_acquired + len(data) > self.policy.max_total_size_bytes:
            raise AcquisitionPolicyError(
                "acquiring this document would exceed the session's "
                f"{self.policy.max_total_size_bytes}-byte total limit"
            )

        self._documents_acquired += 1
        self._total_bytes_acquired += len(data)
        return FetchedPdf(
            data=data,
            original_url=original_url,
            redirect_chain=tuple(redirect_chain),
            final_url=final_url,
            media_type=media_type,
        )

    def _check_declared_size(self, declared_header: str | None) -> None:
        if declared_header is None:
            return
        try:
            declared_size = int(declared_header)
        except ValueError:
            return
        if declared_size > self.policy.max_document_size_bytes:
            raise AcquisitionPolicyError(
                f"declared content-length {declared_size} exceeds the "
                f"{self.policy.max_document_size_bytes}-byte per-document limit"
            )
        if self._total_bytes_acquired + declared_size > self.policy.max_total_size_bytes:
            raise AcquisitionPolicyError(
                "declared content-length would exceed the session's "
                f"{self.policy.max_total_size_bytes}-byte total limit"
            )

    def _check_authorization(self, result: SearchResult, *, user_authorized: bool) -> None:
        if user_authorized and self.policy.allow_explicit_authorization_override:
            return
        if self.policy.require_open_access and result.access_status is not AccessStatus.OPEN_ACCESS:
            raise AcquisitionPolicyError(
                f"search result {result.result_id!r} is not open access and no explicit "
                "user authorization was provided"
            )
        if self.policy.require_license and not result.license:
            raise AcquisitionPolicyError(
                f"search result {result.result_id!r} has no recorded license and no explicit "
                "user authorization was provided"
            )
