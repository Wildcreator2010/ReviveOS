"""Strict outbound URL validation for control-plane network access."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURL(ValueError):
    """Raised when an outbound URL violates the egress policy."""


IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _resolved(host: str) -> set[IPAddress]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeURL("hostname resolution failed") from exc
    addresses: set[IPAddress] = set()
    for info in infos:
        try:
            addresses.add(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    if not addresses:
        raise UnsafeURL("hostname did not resolve")
    return addresses


def _blocked(address: IPAddress) -> bool:
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
        or address in {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("100.100.100.200")}
    )


def assert_safe_url(url: str, *, allowed_hosts: set[str] | frozenset[str] | None = None) -> str:
    """Validate URL before every server-side request and return its normalized URL.

    DNS is resolved twice; differing answers are rejected to prevent rebinding.
    Callers must use an HTTP client with redirects disabled and validate every
    Location header with this function before following it.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.scheme.lower() in {"ext", "fd"}:
        raise UnsafeURL("unsupported URL scheme")
    if parsed.username or parsed.password or not parsed.hostname:
        raise UnsafeURL("credentials and empty hosts are not allowed")
    if parsed.fragment:
        raise UnsafeURL("URL fragments are not sent to servers")
    if parsed.port is not None and parsed.port not in {80, 443}:
        raise UnsafeURL("non-standard port is not allowed")
    host = parsed.hostname.rstrip(".").lower()
    if allowed_hosts is not None and host not in {h.lower().rstrip(".") for h in allowed_hosts}:
        raise UnsafeURL("host is not allowlisted")
    first = _resolved(host)
    if any(_blocked(ip) for ip in first):
        raise UnsafeURL("private, loopback, link-local, or metadata address is not allowed")
    second = _resolved(host)
    if second != first or any(_blocked(ip) for ip in second):
        raise UnsafeURL("DNS answer changed or became unsafe")
    return parsed.geturl()


def assert_safe_redirect(location: str, *, allowed_hosts: set[str] | frozenset[str] | None = None) -> str:
    """Validate a redirect target; never blindly follow Location headers."""
    return assert_safe_url(location, allowed_hosts=allowed_hosts)


__all__ = ["UnsafeURL", "assert_safe_url", "assert_safe_redirect"]
