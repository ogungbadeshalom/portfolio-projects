"""URL validation helpers, including SSRF-safety checks."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from pydantic import HttpUrl

#: Hostnames that resolve to the machine itself and must never be targeted.
_LOOPBACK_HOSTS = frozenset({"localhost", "localhost.localdomain"})
# Local / reserved ranges that would let a client probe internal services.
_MAX_URL_LENGTH = 2048


def normalize_url(raw: str) -> str:
    """Validate and normalize a target URL string.

    Rules enforced:
    * length <= 2048 characters
    * scheme is ``http`` or ``https``
    * host is not a loopback address
    * host does not resolve to a private/loopback/link-local IP

    Args:
        raw: The URL as supplied by the caller.

    Returns:
        The normalized (fully-qualified-ified) URL string.

    Raises:
        ValueError: If the URL fails any validation rule.
    """
    if len(raw) > _MAX_URL_LENGTH:
        raise ValueError("URL must be at most 2048 characters")

    # HttpUrl validates scheme/host and that it is absolute http(s).
    parsed = HttpUrl(raw)
    url = str(parsed)
    split = urlsplit(url)

    host = split.hostname or ""
    host = host.lower().rstrip(".")

    if host in _LOOPBACK_HOSTS:
        raise ValueError("loopback hosts are not allowed")

    # IPv4/IPv6 literal addresses.
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
        try:
            addr = ipaddress.ip_address(split.hostname or "")
        except ValueError:
            addr = None

    if addr is not None and _is_forbidden_ip(addr):
        raise ValueError("reserved/private IP addresses are not allowed")

    # Resolve hostnames (may be blocked in restricted envs) and check their IPs.
    if addr is None:
        try:
            infos = socket.getaddrinfo(host, split.port or 443, proto=socket.IPPROTO_TCP)
        except OSError:
            # DNS failure — let the caller surface a clear 422.
            raise ValueError(f"could not resolve host: {host}")
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if _is_forbidden_ip(ip):
                raise ValueError("resolved to a restricted IP address")

    return url


def _is_forbidden_ip(addr: object) -> bool:
    """True if ``addr`` is loopback, link-local, private, multicast, or reserved."""
    if isinstance(addr, ipaddress.IPv4Address):
        if (
            addr.is_loopback
            or addr.is_link_local
            or addr.is_private
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
        ):
            return True
        return False
    if isinstance(addr, ipaddress.IPv6Address):
        if (
            addr.is_loopback
            or addr.is_link_local
            or addr.is_private
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
            or addr.ipv4_mapped is not None and _is_forbidden_ip(addr.ipv4_mapped)
        ):
            return True
        return False
    return False