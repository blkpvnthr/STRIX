"""SSRF protection: hostname normalization, resolution, and address safety.

**Residual limitation — read before relying on this for anything but
tests.** The safety check performed here (resolve a hostname, inspect
every address it returns) and the actual network connection a real
transport makes are not atomically linked. ``httpx``'s default transport
performs its own OS-level DNS resolution at connect time; a sufficiently
time-precise DNS-rebinding attacker could change the answer between this
check and that connection, bypassing it entirely. Full mitigation needs
IP pinning — resolving once here, then connecting directly to the
validated address via a custom ``httpx.BaseTransport`` that overrides
connection establishment — which is **not implemented** in this phase.
:class:`HostnameResolver` and the downloader's ``transport`` constructor
argument are kept as separate, swappable components specifically so that
can be added later without reworking the policy layer above them. No
phase of this project makes a live network call yet, so this gap has no
live consequence today; it would before any real connector is approved.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Mapping, Sequence
from typing import Protocol

from strix.errors import UnsafeDestinationError

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

#: Known cloud-metadata endpoints, rejected explicitly in addition to (and
#: overlapping with) the general link-local/private checks below, for
#: clarity about exactly what this is defending against.
_METADATA_SERVICE_ADDRESSES: frozenset[IPAddress] = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),  # AWS / GCP / Azure / OpenStack / Alibaba
        ipaddress.ip_address("fd00:ec2::254"),  # AWS IMDSv2, IPv6
    }
)


class HostnameResolver(Protocol):
    """Resolves a hostname to every address it currently answers with.

    Returns an empty tuple for an unresolvable hostname — never raises
    for that case; callers treat "nothing resolved" as unsafe themselves.
    """

    def resolve(self, hostname: str) -> tuple[str, ...]: ...


class StaticResolver:
    """Deterministic, socket-free resolver — the only one tests may use."""

    def __init__(self, mapping: Mapping[str, Sequence[str]]) -> None:
        self._mapping = {host.lower(): tuple(addresses) for host, addresses in mapping.items()}

    def resolve(self, hostname: str) -> tuple[str, ...]:
        return self._mapping.get(hostname.lower(), ())


class SystemResolver:
    """Real DNS resolution via ``socket.getaddrinfo``.

    Production-only: the test suite's ``no_network`` guard (tests/conftest.py)
    blocks the sockets this needs, so no test path can reach here — that
    block is itself a backstop confirming "zero socket use" in tests, not
    merely a convention.
    """

    def resolve(self, hostname: str) -> tuple[str, ...]:
        try:
            infos = socket.getaddrinfo(hostname, None)
        except OSError:
            return ()
        addresses = {str(info[4][0]) for info in infos}
        return tuple(sorted(addresses))


def normalize_hostname(hostname: str) -> str:
    """IDNA-encode and lowercase a hostname; pass IP literals through.

    Raises :class:`UnsafeDestinationError` for a hostname that is neither
    a valid IP literal nor IDNA-encodable (malformed labels, embedded
    control characters, etc.).
    """
    try:
        ipaddress.ip_address(hostname)
        return hostname.lower()
    except ValueError:
        pass
    try:
        return hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise UnsafeDestinationError(f"hostname {hostname!r} is not a valid hostname") from exc


def is_unsafe_address(address: IPAddress) -> bool:
    """True if *address* must never be connected to."""
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or address in _METADATA_SERVICE_ADDRESSES
    )


def ensure_safe_resolution(hostname: str, resolver: HostnameResolver) -> tuple[IPAddress, ...]:
    """Resolve *hostname* and require every returned address to be safe.

    Fails closed on both ends: a hostname that resolves to nothing is
    rejected (nothing to verify), and a hostname with even one unsafe
    address among several safe ones is rejected outright — a mixed
    safe/unsafe answer set is never partially trusted.
    """
    raw_addresses = resolver.resolve(hostname)
    if not raw_addresses:
        raise UnsafeDestinationError(f"hostname {hostname!r} did not resolve to any address")
    parsed: list[IPAddress] = []
    for raw in raw_addresses:
        try:
            address = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise UnsafeDestinationError(f"resolver returned an invalid address {raw!r}") from exc
        if is_unsafe_address(address):
            raise UnsafeDestinationError(
                f"hostname {hostname!r} resolves to unsafe address {address}"
            )
        parsed.append(address)
    return tuple(parsed)
