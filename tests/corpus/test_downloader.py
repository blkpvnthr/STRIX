"""Tests for the Phase 5 PdfDownloader: policy, SSRF integration, redirects,
streaming/size limits, timeouts, and PDF content validation.

Every test uses httpx.MockTransport — no socket is ever opened, which
tests/conftest.py's no_network autouse fixture enforces at the harness
level (it would raise RuntimeError if anything here tried).
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from tests.corpus.acquisition_fixtures import (
    PDF_BYTES,
    SAFE_HOST,
    SAFE_IPV4,
    make_plan,
    make_result,
)

from strix.corpus.acquisition.downloader import PdfDownloader
from strix.corpus.acquisition.network_safety import StaticResolver
from strix.corpus.acquisition.policy import AcquisitionPolicy
from strix.errors import (
    AcquisitionPolicyError,
    AcquisitionTimeoutError,
    PdfValidationError,
    UnsafeDestinationError,
)

Handler = Callable[[httpx.Request], httpx.Response]


def _unreachable_handler(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"transport should never have been called for {request.url!r}")


def _pdf_response(
    *, content_type: str = "application/pdf", body: bytes = PDF_BYTES, declare_length: bool = True
) -> httpx.Response:
    headers = {"content-type": content_type}
    if declare_length:
        headers["content-length"] = str(len(body))
        return httpx.Response(200, headers=headers, content=body)
    # Omitting content=<bytes> in favor of content=<iterator> prevents
    # httpx from computing its own Content-Length header.
    return httpx.Response(200, headers=headers, content=iter([body]))


def _downloader(
    handler: Handler,
    *,
    policy: AcquisitionPolicy | None = None,
    resolver_map: dict[str, tuple[str, ...]] | None = None,
) -> PdfDownloader:
    resolver = StaticResolver(resolver_map or {SAFE_HOST: (SAFE_IPV4,)})
    return PdfDownloader(
        policy or AcquisitionPolicy(),
        resolver=resolver,
        transport=httpx.MockTransport(handler),
    )


# --------------------------------------------------------------------------
# Valid download
# --------------------------------------------------------------------------


def test_valid_pdf_download_succeeds() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    downloader = _downloader(lambda request: _pdf_response())

    fetched = downloader.fetch(result, plan)

    assert fetched.data == PDF_BYTES
    assert fetched.media_type == "application/pdf"
    assert fetched.final_url == result.document_url
    assert fetched.redirect_chain == ()


# --------------------------------------------------------------------------
# URL shape rejections (before any request is made)
# --------------------------------------------------------------------------


def test_http_scheme_is_rejected_without_a_request() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"http://{SAFE_HOST}/doc.pdf")
    downloader = _downloader(_unreachable_handler)
    with pytest.raises(UnsafeDestinationError):
        downloader.fetch(result, plan)


def test_user_info_is_rejected_without_a_request() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://user:pass@{SAFE_HOST}/doc.pdf")
    downloader = _downloader(_unreachable_handler)
    with pytest.raises(UnsafeDestinationError):
        downloader.fetch(result, plan)


def test_fragment_is_rejected_without_a_request() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf#section")
    downloader = _downloader(_unreachable_handler)
    with pytest.raises(UnsafeDestinationError):
        downloader.fetch(result, plan)


def test_unsafe_port_is_rejected_without_a_request() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}:8443/doc.pdf")
    downloader = _downloader(_unreachable_handler)
    with pytest.raises(UnsafeDestinationError):
        downloader.fetch(result, plan)


# --------------------------------------------------------------------------
# SSRF integration (full category coverage lives in test_network_safety.py;
# these confirm PdfDownloader actually wires the resolver check in)
# --------------------------------------------------------------------------


def test_resolution_to_a_private_address_is_rejected_without_a_request() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    downloader = _downloader(_unreachable_handler, resolver_map={SAFE_HOST: ("10.0.0.5",)})
    with pytest.raises(UnsafeDestinationError):
        downloader.fetch(result, plan)


def test_resolution_to_a_metadata_service_address_is_rejected() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    downloader = _downloader(_unreachable_handler, resolver_map={SAFE_HOST: ("169.254.169.254",)})
    with pytest.raises(UnsafeDestinationError):
        downloader.fetch(result, plan)


def test_mixed_safe_and_unsafe_resolution_is_rejected() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    downloader = _downloader(
        _unreachable_handler, resolver_map={SAFE_HOST: (SAFE_IPV4, "127.0.0.1")}
    )
    with pytest.raises(UnsafeDestinationError):
        downloader.fetch(result, plan)


# --------------------------------------------------------------------------
# Redirects: revalidated, bounded
# --------------------------------------------------------------------------


def test_redirect_to_a_safe_destination_is_followed() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/old.pdf")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old.pdf":
            return httpx.Response(302, headers={"location": f"https://{SAFE_HOST}/new.pdf"})
        return _pdf_response()

    downloader = _downloader(handler)
    fetched = downloader.fetch(result, plan)

    assert fetched.data == PDF_BYTES
    assert fetched.redirect_chain == (f"https://{SAFE_HOST}/old.pdf",)
    assert fetched.final_url == f"https://{SAFE_HOST}/new.pdf"


def test_unsafe_redirect_target_is_rejected_before_being_followed() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/old.pdf")
    requested_new = {"called": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/new.pdf":
            requested_new["called"] = True
            return _pdf_response()
        return httpx.Response(302, headers={"location": "http://internal.example/new.pdf"})

    downloader = _downloader(handler, resolver_map={SAFE_HOST: (SAFE_IPV4,)})
    with pytest.raises(UnsafeDestinationError):
        downloader.fetch(result, plan)
    assert requested_new["called"] is False


def test_redirect_limit_is_enforced() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/r0.pdf")
    policy = AcquisitionPolicy(max_redirects=2)

    def handler(request: httpx.Request) -> httpx.Response:
        current = int(request.url.path.lstrip("/r").removesuffix(".pdf"))
        return httpx.Response(302, headers={"location": f"https://{SAFE_HOST}/r{current + 1}.pdf"})

    downloader = _downloader(handler, policy=policy)
    with pytest.raises(AcquisitionPolicyError, match="redirect limit"):
        downloader.fetch(result, plan)


# --------------------------------------------------------------------------
# Plan domain enforcement
# --------------------------------------------------------------------------


def test_host_outside_allowed_domains_is_rejected() -> None:
    plan = make_plan(allowed_domains=("other.example",))
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    downloader = _downloader(_unreachable_handler)
    with pytest.raises(AcquisitionPolicyError):
        downloader.fetch(result, plan)


def test_host_in_excluded_domains_is_rejected() -> None:
    plan = make_plan(excluded_domains=(SAFE_HOST,))
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    downloader = _downloader(_unreachable_handler)
    with pytest.raises(AcquisitionPolicyError):
        downloader.fetch(result, plan)


def test_host_in_allowed_domains_succeeds() -> None:
    plan = make_plan(allowed_domains=(SAFE_HOST,))
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    downloader = _downloader(lambda request: _pdf_response())
    assert downloader.fetch(result, plan).data == PDF_BYTES


# --------------------------------------------------------------------------
# Authorization: access status and license
# --------------------------------------------------------------------------


def test_missing_license_without_authorization_is_rejected() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf", license=None)
    downloader = _downloader(_unreachable_handler)
    with pytest.raises(AcquisitionPolicyError):
        downloader.fetch(result, plan)


def test_closed_access_without_authorization_is_rejected() -> None:
    from strix.corpus.acquisition.models import AccessStatus

    plan = make_plan()
    result = make_result(
        plan, document_url=f"https://{SAFE_HOST}/doc.pdf", access_status=AccessStatus.CLOSED_ACCESS
    )
    downloader = _downloader(_unreachable_handler)
    with pytest.raises(AcquisitionPolicyError):
        downloader.fetch(result, plan)


def test_closed_access_succeeds_with_explicit_user_authorization() -> None:
    from strix.corpus.acquisition.models import AccessStatus

    plan = make_plan()
    result = make_result(
        plan,
        document_url=f"https://{SAFE_HOST}/doc.pdf",
        access_status=AccessStatus.CLOSED_ACCESS,
        license=None,
    )
    downloader = _downloader(lambda request: _pdf_response())
    fetched = downloader.fetch(result, plan, user_authorized=True)
    assert fetched.data == PDF_BYTES


def test_authorization_override_does_not_bypass_network_safety() -> None:
    from strix.corpus.acquisition.models import AccessStatus

    plan = make_plan()
    result = make_result(
        plan, document_url=f"https://{SAFE_HOST}/doc.pdf", access_status=AccessStatus.CLOSED_ACCESS
    )
    downloader = _downloader(_unreachable_handler, resolver_map={SAFE_HOST: ("127.0.0.1",)})
    with pytest.raises(UnsafeDestinationError):
        downloader.fetch(result, plan, user_authorized=True)


# --------------------------------------------------------------------------
# Size limits: declared (pre-stream) and streamed (actual bytes)
# --------------------------------------------------------------------------


def test_excessive_declared_content_length_is_rejected_before_streaming() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    policy = AcquisitionPolicy(max_document_size_bytes=10)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf", "content-length": "99999"},
            content=iter([PDF_BYTES]),
        )

    downloader = _downloader(handler, policy=policy)
    with pytest.raises(AcquisitionPolicyError, match="declared content-length"):
        downloader.fetch(result, plan)


def test_excessive_streamed_body_is_rejected_without_declared_length() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    policy = AcquisitionPolicy(max_document_size_bytes=10)
    big_body = PDF_BYTES + b"x" * 1000

    downloader = _downloader(
        lambda request: _pdf_response(body=big_body, declare_length=False), policy=policy
    )
    with pytest.raises(AcquisitionPolicyError, match="streamed body"):
        downloader.fetch(result, plan)


def test_session_total_size_budget_is_enforced_across_calls() -> None:
    plan = make_plan()
    policy = AcquisitionPolicy(max_total_size_bytes=len(PDF_BYTES))
    downloader = _downloader(lambda request: _pdf_response(), policy=policy)

    result1 = make_result(plan, document_url=f"https://{SAFE_HOST}/one.pdf")
    result2 = make_result(plan, document_url=f"https://{SAFE_HOST}/two.pdf", title="Second")
    downloader.fetch(result1, plan)
    with pytest.raises(AcquisitionPolicyError, match="total limit"):
        downloader.fetch(result2, plan)


def test_session_document_count_budget_is_enforced_across_calls() -> None:
    plan = make_plan()
    policy = AcquisitionPolicy(max_documents=1)
    downloader = _downloader(lambda request: _pdf_response(), policy=policy)

    result1 = make_result(plan, document_url=f"https://{SAFE_HOST}/one.pdf")
    result2 = make_result(plan, document_url=f"https://{SAFE_HOST}/two.pdf", title="Second")
    downloader.fetch(result1, plan)
    with pytest.raises(AcquisitionPolicyError, match="document limit"):
        downloader.fetch(result2, plan)


# --------------------------------------------------------------------------
# Timeout
# --------------------------------------------------------------------------


def test_timeout_is_surfaced_as_acquisition_timeout_error() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout")

    downloader = _downloader(handler)
    with pytest.raises(AcquisitionTimeoutError):
        downloader.fetch(result, plan)


# --------------------------------------------------------------------------
# PDF content validation
# --------------------------------------------------------------------------


def test_html_error_page_disguised_as_pdf_is_rejected() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    downloader = _downloader(
        lambda request: _pdf_response(content_type="text/html", body=b"<html>Not found</html>")
    )
    with pytest.raises(PdfValidationError):
        downloader.fetch(result, plan)


def test_json_error_response_disguised_as_pdf_is_rejected() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    downloader = _downloader(
        lambda request: _pdf_response(
            content_type="application/json", body=b'{"error": "not found"}'
        )
    )
    with pytest.raises(PdfValidationError):
        downloader.fetch(result, plan)


def test_incorrect_mime_type_is_rejected() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    downloader = _downloader(
        lambda request: _pdf_response(content_type="image/png", body=PDF_BYTES)
    )
    with pytest.raises(PdfValidationError):
        downloader.fetch(result, plan)


def test_incorrect_file_signature_is_rejected() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    downloader = _downloader(
        lambda request: _pdf_response(body=b"this is not a pdf at all, just text")
    )
    with pytest.raises(PdfValidationError):
        downloader.fetch(result, plan)


def test_unapproved_http_status_is_rejected() -> None:
    plan = make_plan()
    result = make_result(plan, document_url=f"https://{SAFE_HOST}/doc.pdf")
    downloader = _downloader(lambda request: httpx.Response(404))
    with pytest.raises(PdfValidationError):
        downloader.fetch(result, plan)
