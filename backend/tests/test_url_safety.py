"""Tests for backend/utils/url_safety.py: SSRF defenses.

Covers SECURITY_ASSESSMENT.md C7 - the download URL handed back by the
ExportComments upstream is fetched server-side. The validator rejects
non-https, off-allowlist, IP-literal, and private/loopback/link-local
destinations. The PinnedResolver defeats DNS rebinding by serving only
the IPs that the validator already vetted.
"""
from __future__ import annotations

import socket

import pytest

from utils.url_safety import (
    PinnedResolver,
    UnsafeURLError,
    ValidatedURL,
    validate_external_url,
)


# ---- Scheme allowlist ------------------------------------------------------

class TestScheme:
    @pytest.mark.parametrize(
        "url",
        [
            "http://api.exportcomments.com/x.json",
            "ftp://api.exportcomments.com/x.json",
            "file:///etc/passwd",
            "gopher://api.exportcomments.com/x",
            "javascript:alert(1)",
            "data:text/plain,hi",
        ],
    )
    def test_rejects_non_https(self, url):
        with pytest.raises(UnsafeURLError):
            validate_external_url(url, allowed_suffixes=(".exportcomments.com",))


# ---- Empty / malformed inputs ----------------------------------------------

class TestMalformed:
    @pytest.mark.parametrize("bad", ["", None, 123, "not a url"])
    def test_rejects_empty_or_non_string(self, bad):
        with pytest.raises(UnsafeURLError):
            validate_external_url(bad, allowed_suffixes=(".exportcomments.com",))  # type: ignore[arg-type]

    def test_rejects_missing_hostname(self):
        with pytest.raises(UnsafeURLError):
            validate_external_url("https:///foo", allowed_suffixes=(".exportcomments.com",))


# ---- Hostname allowlist ----------------------------------------------------

class TestHostnameAllowlist:
    def test_accepts_exact_apex(self, monkeypatch):
        _patch_resolver(monkeypatch, [("8.8.8.8",)])
        result = validate_external_url(
            "https://exportcomments.com/x.json",
            allowed_suffixes=(".exportcomments.com",),
        )
        assert result.hostname == "exportcomments.com"

    def test_accepts_subdomain(self, monkeypatch):
        _patch_resolver(monkeypatch, [("8.8.8.8",)])
        result = validate_external_url(
            "https://api.exportcomments.com/x.json",
            allowed_suffixes=(".exportcomments.com",),
        )
        assert result.hostname == "api.exportcomments.com"

    def test_rejects_lookalike_apex(self, monkeypatch):
        # ".exportcomments.com" must NOT match "evilexportcomments.com" -
        # the subdomain boundary check is what catches this.
        _patch_resolver(monkeypatch, [("8.8.8.8",)])
        with pytest.raises(UnsafeURLError):
            validate_external_url(
                "https://evilexportcomments.com/x.json",
                allowed_suffixes=(".exportcomments.com",),
            )

    def test_rejects_unrelated_domain(self, monkeypatch):
        _patch_resolver(monkeypatch, [("8.8.8.8",)])
        with pytest.raises(UnsafeURLError):
            validate_external_url(
                "https://attacker.example.com/x.json",
                allowed_suffixes=(".exportcomments.com",),
            )

    def test_rejects_ip_literal_in_hostname(self):
        # IP literals bypass the suffix allowlist entirely, so reject
        # before DNS resolution even runs.
        with pytest.raises(UnsafeURLError):
            validate_external_url(
                "https://169.254.169.254/x.json",
                allowed_suffixes=(".exportcomments.com",),
            )

    def test_rejects_ipv6_literal(self):
        with pytest.raises(UnsafeURLError):
            validate_external_url(
                "https://[::1]/x.json",
                allowed_suffixes=(".exportcomments.com",),
            )


# ---- IP range checks -------------------------------------------------------

class TestPrivateIPRejection:
    @pytest.mark.parametrize(
        "bad_ip",
        [
            "127.0.0.1",        # loopback
            "10.0.0.5",         # private 10/8
            "172.16.1.2",       # private 172.16/12
            "192.168.0.10",     # private 192.168/16
            "169.254.169.254",  # link-local (cloud metadata)
            "0.0.0.0",          # unspecified
            "224.0.0.1",        # multicast
        ],
    )
    def test_rejects_private_resolution(self, monkeypatch, bad_ip):
        _patch_resolver(monkeypatch, [(bad_ip,)])
        with pytest.raises(UnsafeURLError):
            validate_external_url(
                "https://api.exportcomments.com/x.json",
                allowed_suffixes=(".exportcomments.com",),
            )

    def test_rejects_ipv4_mapped_ipv6_loopback(self, monkeypatch):
        # ::ffff:127.0.0.1 must be rejected after unmapping.
        _patch_resolver(monkeypatch, [("::ffff:127.0.0.1",)], family=socket.AF_INET6)
        with pytest.raises(UnsafeURLError):
            validate_external_url(
                "https://api.exportcomments.com/x.json",
                allowed_suffixes=(".exportcomments.com",),
            )

    def test_rejects_when_any_resolved_ip_is_private(self, monkeypatch):
        # Mixed answer: one public, one private. Reject - we cannot
        # control which IP aiohttp would pick at connect time.
        _patch_resolver(monkeypatch, [("8.8.8.8",), ("10.0.0.5",)])
        with pytest.raises(UnsafeURLError):
            validate_external_url(
                "https://api.exportcomments.com/x.json",
                allowed_suffixes=(".exportcomments.com",),
            )


# ---- Happy path ------------------------------------------------------------

class TestHappyPath:
    def test_returns_validated_object(self, monkeypatch):
        _patch_resolver(monkeypatch, [("8.8.8.8",)])
        result = validate_external_url(
            "https://api.exportcomments.com:443/download/abc.json",
            allowed_suffixes=(".exportcomments.com",),
        )
        assert isinstance(result, ValidatedURL)
        assert result.url == "https://api.exportcomments.com:443/download/abc.json"
        assert result.hostname == "api.exportcomments.com"
        assert result.port == 443
        assert result.resolved_ips == ("8.8.8.8",)

    def test_default_port_is_443(self, monkeypatch):
        _patch_resolver(monkeypatch, [("8.8.8.8",)])
        result = validate_external_url(
            "https://api.exportcomments.com/x.json",
            allowed_suffixes=(".exportcomments.com",),
        )
        assert result.port == 443

    def test_dedupes_resolved_ips(self, monkeypatch):
        # getaddrinfo can return the same IP under multiple records
        # (v4 + v4-mapped-v6, or repeated for different socket types).
        _patch_resolver(monkeypatch, [("8.8.8.8",), ("8.8.8.8",)])
        result = validate_external_url(
            "https://api.exportcomments.com/x.json",
            allowed_suffixes=(".exportcomments.com",),
        )
        assert result.resolved_ips == ("8.8.8.8",)


# ---- DNS failure -----------------------------------------------------------

class TestDNSFailure:
    def test_wraps_gaierror(self, monkeypatch):
        def boom(*args, **kwargs):
            raise socket.gaierror("nodename nor servname provided")
        monkeypatch.setattr(socket, "getaddrinfo", boom)
        with pytest.raises(UnsafeURLError):
            validate_external_url(
                "https://nowhere.exportcomments.com/x.json",
                allowed_suffixes=(".exportcomments.com",),
            )


# ---- PinnedResolver --------------------------------------------------------

class TestPinnedResolver:
    @pytest.mark.asyncio
    async def test_returns_pinned_ips_for_matching_host(self):
        resolver = PinnedResolver("api.exportcomments.com", 443, ("8.8.8.8",))
        results = await resolver.resolve("api.exportcomments.com", 443, socket.AF_INET)
        assert len(results) == 1
        assert results[0]["host"] == "8.8.8.8"
        assert results[0]["port"] == 443
        assert results[0]["family"] == socket.AF_INET

    @pytest.mark.asyncio
    async def test_rejects_unexpected_host(self):
        # A redirect that swapped Host or a buggy caller cannot trick
        # the resolver into vouching for a name we never validated.
        resolver = PinnedResolver("api.exportcomments.com", 443, ("8.8.8.8",))
        with pytest.raises(UnsafeURLError):
            await resolver.resolve("attacker.example.com", 443, socket.AF_INET)

    @pytest.mark.asyncio
    async def test_hostname_match_is_case_insensitive(self):
        resolver = PinnedResolver("api.exportcomments.com", 443, ("8.8.8.8",))
        results = await resolver.resolve("API.ExportComments.COM", 443, socket.AF_INET)
        assert results[0]["host"] == "8.8.8.8"

    def test_requires_at_least_one_ip(self):
        with pytest.raises(ValueError):
            PinnedResolver("api.exportcomments.com", 443, ())

    @pytest.mark.asyncio
    async def test_close_is_noop(self):
        resolver = PinnedResolver("api.exportcomments.com", 443, ("8.8.8.8",))
        # Should not raise.
        await resolver.close()


# ---- Helpers ---------------------------------------------------------------

def _patch_resolver(monkeypatch, ip_groups, family=socket.AF_INET):
    """Patch socket.getaddrinfo to return the given IPs.

    `ip_groups` is a sequence of tuples; each tuple represents one
    getaddrinfo record where the first element is the IP string.
    """
    def fake(*args, **kwargs):
        records = []
        for group in ip_groups:
            ip = group[0]
            sockaddr = (ip, 443) if family == socket.AF_INET else (ip, 443, 0, 0)
            records.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr))
        return records
    monkeypatch.setattr(socket, "getaddrinfo", fake)
