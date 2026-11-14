"""Tests for SSRF protection: hostname normalization, resolution, and
address classification. No socket is ever used — StaticResolver is the
only resolver exercised here (SystemResolver is production-only and
would be blocked by tests/conftest.py's no_network guard if it were)."""

from __future__ import annotations

import ipaddress

import pytest
from tests.corpus.acquisition_fixtures import SAFE_IPV4, SAFE_IPV6

from strix.corpus.acquisition.network_safety import (
    StaticResolver,
    ensure_safe_resolution,
    is_unsafe_address,
    normalize_hostname,
)
from strix.errors import UnsafeDestinationError


def _addr(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    return ipaddress.ip_address(text)


# --------------------------------------------------------------------------
# Address classification — every required category, both address families
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # private (RFC 1918)
        "172.16.0.5",  # private (RFC 1918)
        "192.168.1.5",  # private (RFC 1918)
        "169.254.1.1",  # link-local
        "169.254.169.254",  # cloud metadata service
        "224.0.0.1",  # multicast
        "240.0.0.5",  # reserved (class E)
        "0.0.0.0",  # unspecified
        "::1",  # IPv6 loopback
        "fe80::1",  # IPv6 link-local
        "fc00::1",  # IPv6 unique local (private)
        "fd00:ec2::254",  # AWS IMDSv2, IPv6 metadata
        "ff02::1",  # IPv6 multicast
    ],
)
def test_is_unsafe_address_rejects_every_required_category(address: str) -> None:
    assert is_unsafe_address(_addr(address)) is True


@pytest.mark.parametrize("address", [SAFE_IPV4, SAFE_IPV6, "8.8.8.8"])
def test_is_unsafe_address_allows_public_addresses(address: str) -> None:
    assert is_unsafe_address(_addr(address)) is False


# --------------------------------------------------------------------------
# Hostname normalization
# --------------------------------------------------------------------------


def test_normalize_hostname_lowercases_ascii_hosts() -> None:
    assert normalize_hostname("Example.COM") == "example.com"


def test_normalize_hostname_idna_encodes_unicode_labels() -> None:
    assert normalize_hostname("bücher.example") == "xn--bcher-kva.example"


def test_normalize_hostname_passes_through_ip_literals() -> None:
    assert normalize_hostname(SAFE_IPV4) == SAFE_IPV4
    assert normalize_hostname("::1") == "::1"


def test_normalize_hostname_rejects_a_malformed_host() -> None:
    with pytest.raises(UnsafeDestinationError):
        normalize_hostname("a" * 64 + ".example.com")  # label exceeds 63 octets


# --------------------------------------------------------------------------
# Resolution: every address inspected; mixed answers fail closed
# --------------------------------------------------------------------------


def test_ensure_safe_resolution_accepts_all_safe_addresses() -> None:
    resolver = StaticResolver({"safe.example": (SAFE_IPV4, SAFE_IPV6)})
    addresses = ensure_safe_resolution("safe.example", resolver)
    assert len(addresses) == 2


def test_ensure_safe_resolution_rejects_an_unresolvable_hostname() -> None:
    resolver = StaticResolver({})
    with pytest.raises(UnsafeDestinationError):
        ensure_safe_resolution("nowhere.example", resolver)


def test_ensure_safe_resolution_rejects_a_purely_unsafe_hostname() -> None:
    resolver = StaticResolver({"internal.example": ("127.0.0.1",)})
    with pytest.raises(UnsafeDestinationError):
        ensure_safe_resolution("internal.example", resolver)


def test_ensure_safe_resolution_rejects_mixed_safe_and_unsafe_answers() -> None:
    """One unsafe address among several safe ones still rejects the host —
    a partially-safe DNS answer is never partially trusted."""
    resolver = StaticResolver({"mixed.example": (SAFE_IPV4, "127.0.0.1", SAFE_IPV6)})
    with pytest.raises(UnsafeDestinationError):
        ensure_safe_resolution("mixed.example", resolver)


def test_static_resolver_is_case_insensitive() -> None:
    resolver = StaticResolver({"Example.Org": (SAFE_IPV4,)})
    assert resolver.resolve("example.org") == (SAFE_IPV4,)
