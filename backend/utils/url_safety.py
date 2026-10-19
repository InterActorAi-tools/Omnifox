"""
SSRF defenses for outbound HTTP fetches.

The ExportComments service hands us a `download_link` from the API response
and we fetch it server-side. Without validation, a compromised upstream (or
a MITM on a misconfigured TLS chain) could point us at:

    http://169.254.169.254/latest/meta-data/      # cloud metadata
    http://127.0.0.1:5432/                        # local Postgres
    http://10.0.0.5/                              # internal LAN
    file:///etc/passwd                            # local file
    gopher://...                                  # smuggled protocol

`validate_external_url` enforces:

  1. Scheme allowlist (https only).
  2. Hostname allowlist (suffix match against a trusted domain set).
  3. DNS resolution to public IPs only - rejects private, loopback,
     link-local, reserved, multicast, and IPv4-mapped IPv6 variants.

`PinnedResolver` defeats DNS rebinding by returning ONLY the IPs that
`validate_external_url` already vetted. Without pinning, an attacker-
controlled DNS server can answer a public IP at validation time and an
internal IP a few milliseconds later when aiohttp connects.

Usage:

    validated = validate_external_url(url, allowed_suffixes=(".exportcomments.com",))
    connector = aiohttp.TCPConnector(resolver=PinnedResolver(validated.resolved_ips))
    async with aiohttp.ClientSession(connector=connector, ...) as session:
        async with session.get(validated.url, allow_redirects=False, ...) as resp:
            ...

Always pass `allow_redirects=False`. A 30x response would otherwise let the
attacker hand off to an arbitrary URL after passing validation.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Iterable, Tuple
from urllib.parse import urlparse

from aiohttp.abc import AbstractResolver


class UnsafeURLError(ValueError):
    """Raised when a URL fails SSRF validation."""


@dataclass(frozen=True)
class ValidatedURL:
    """Result of `validate_external_url`.

    `url` is the original URL string (unchanged - callers pass it back to
    aiohttp so the Host header / SNI come out right).
    `hostname` is the lowercased hostname.
    `port` is the resolved port (defaults to 443 for https).
    `resolved_ips` is the tuple of IPs that DNS returned at validation
    time. Feed this into `PinnedResolver` to defeat DNS rebinding.
    """

    url: str
    hostname: str
    port: int
    resolved_ips: Tuple[str, ...]


_ALLOWED_SCHEMES = frozenset({"https"})


def _check_ip_is_public(ip_str: str) -> None:
    """Raise `UnsafeURLError` if `ip_str` is in a non-public range.

    Blocks:
      - private (10/8, 172.16/12, 192.168/16, fc00::/7)
      - loopback (127/8, ::1)
      - link-local (169.254/16, fe80::/10) - blocks cloud metadata at
        169.254.169.254 (AWS, GCP, Azure) and IPv6 link-local.
      - reserved / unspecified (0.0.0.0, ::, broadcast)
      - multicast (224/4, ff00::/8)
      - IPv4-mapped IPv6 (::ffff:127.0.0.1) - aiohttp may resolve to
        these on dual-stack systems; we re-check after unmapping.
    """
    ip = ipaddress.ip_address(ip_str)

    # Unmap IPv4-in-IPv6 so we apply the same v4 rules to ::ffff:10.0.0.1.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        raise UnsafeURLError(f"IP {ip} is in a disallowed range")


def _hostname_is_allowed(hostname: str, allowed_suffixes: Iterable[str]) -> bool:
    """Return True if `hostname` matches any allowed suffix.

    Suffixes starting with "." enforce a true subdomain boundary so that
    "evilexportcomments.com" does NOT match ".exportcomments.com". A
    suffix without a leading dot matches the bare hostname exactly.
    """
    host = hostname.lower()
    for suffix in allowed_suffixes:
        suffix_lower = suffix.lower()
        if suffix_lower.startswith("."):
            # Match exact apex (host == suffix without leading dot) or
            # any subdomain (host endswith suffix-with-dot).
            apex = suffix_lower[1:]
            if host == apex or host.endswith(suffix_lower):
                return True
        else:
            if host == suffix_lower:
                return True
    return False


def validate_external_url(
    url: str,
    allowed_suffixes: Iterable[str],
) -> ValidatedURL:
    """Validate a URL before fetching it server-side.

    Returns a `ValidatedURL` containing the resolved IPs (to feed into
    `PinnedResolver`).

    Raises `UnsafeURLError` if any check fails.
    """
    if not isinstance(url, str) or not url:
        raise UnsafeURLError("URL must be a non-empty string")

    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(
            f"Scheme {parsed.scheme!r} not allowed (https only)"
        )

    if not parsed.hostname:
        raise UnsafeURLError("URL has no hostname")

    hostname = parsed.hostname.lower()

    # Reject literal IPs in the URL - the allowlist is hostname-based,
    # and an IP-literal URL bypasses the suffix check entirely.
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass  # Not an IP literal, which is what we want.
    else:
        raise UnsafeURLError("URL must use a hostname, not an IP literal")

    if not _hostname_is_allowed(hostname, allowed_suffixes):
        raise UnsafeURLError(f"Hostname {hostname!r} is not in the allowlist")

    port = parsed.port or 443

    try:
        addr_infos = socket.getaddrinfo(
            hostname, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror as exc:
        raise UnsafeURLError(f"DNS resolution failed for {hostname}") from exc

    resolved_ips: list[str] = []
    for family, _, _, _, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        _check_ip_is_public(ip_str)  # raises on any disallowed IP
        if ip_str not in resolved_ips:
            resolved_ips.append(ip_str)

    if not resolved_ips:
        raise UnsafeURLError(f"No usable IPs resolved for {hostname}")

    return ValidatedURL(
        url=url,
        hostname=hostname,
        port=port,
        resolved_ips=tuple(resolved_ips),
    )


class PinnedResolver(AbstractResolver):
    """Custom aiohttp resolver that returns ONLY pre-validated IPs.

    Pass the `resolved_ips` from `ValidatedURL` so the actual TCP
    connection cannot land on a different IP than the one we vetted.
    This is the defense against DNS rebinding: even if the upstream
    authoritative server flips its answer between validation and
    connection, the resolver inside aiohttp ignores DNS entirely.

    We carry the `hostname` separately so SNI / Host header still go
    out as the original domain (the server picks the right cert).
    """

    def __init__(self, hostname: str, port: int, ips: Iterable[str]) -> None:
        self._hostname = hostname
        self._port = port
        self._ips = tuple(ips)
        if not self._ips:
            raise ValueError("PinnedResolver requires at least one IP")

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: int = socket.AF_INET,
    ) -> list[dict]:
        # aiohttp passes the URL's hostname back in here. If it tries to
        # resolve anything else (e.g., via a redirect that changed Host),
        # refuse - we have not vetted that name.
        if host.lower() != self._hostname:
            raise UnsafeURLError(
                f"PinnedResolver only serves {self._hostname!r}, got {host!r}"
            )

        results: list[dict] = []
        for ip in self._ips:
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                continue
            sock_family = socket.AF_INET6 if isinstance(addr, ipaddress.IPv6Address) else socket.AF_INET
            if family not in (socket.AF_UNSPEC, sock_family):
                continue
            results.append(
                {
                    "hostname": self._hostname,
                    "host": ip,
                    "port": port or self._port,
                    "family": sock_family,
                    "proto": 0,
                    "flags": 0,
                }
            )
        if not results:
            raise UnsafeURLError(
                f"No pinned IPs available for family {family}"
            )
        return results

    async def close(self) -> None:
        return None
