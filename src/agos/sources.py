"""Source connector contracts, including an opt-in pinned HTTPS research connector.

Fixture connectors remain the default. ``HTTPSResearchConnector`` is opt-in: it
accepts only pre-registered source IDs, explicit HTTPS host allowlists, and an
injectable one-hop transport. It has no credential or cookie behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import http.client
import ipaddress
import socket
import ssl
from typing import Callable, Mapping, Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    title: str
    url: str
    retrieved_at: str
    content: str
    adapter: str = "fixture"

    def provenance(self) -> dict[str, str]:
        return {"source_id": self.source_id, "title": self.title, "url": self.url, "retrieved_at": self.retrieved_at, "content": self.content, "adapter": self.adapter}


class SourceConnector(Protocol):
    """A collection contract that must return provenance-complete source records."""

    def collect(self, source_ids: list[str]) -> list[dict[str, str]]: ...


class AllowlistedFixtureConnector:
    """Strict source-ID allowlist backed only by caller-supplied fixtures."""

    def __init__(self, fixtures: dict[str, SourceRecord], adapter_name: str = "fixture") -> None:
        self._fixtures = dict(fixtures)
        self._adapter_name = adapter_name

    def collect(self, source_ids: list[str]) -> list[dict[str, str]]:
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source ids must not contain duplicates")
        missing = [source_id for source_id in source_ids if source_id not in self._fixtures]
        if missing:
            raise ValueError(f"source ids are not allow-listed: {missing}")
        records = []
        for source_id in source_ids:
            record = self._fixtures[source_id].provenance()
            record["adapter"] = self._adapter_name
            records.append(record)
        return records


class DeterministicFakeSourceConnector(AllowlistedFixtureConnector):
    """Test-only fake connector; it is fixture-backed and has no network behavior."""

    def __init__(self, fixtures: dict[str, SourceRecord]) -> None:
        super().__init__(fixtures, adapter_name="fake")


@dataclass(frozen=True)
class HTTPSResearchSource:
    """A caller-approved research source; IDs are not arbitrary URLs."""

    source_id: str
    title: str
    url: str


@dataclass(frozen=True)
class HTTPResponse:
    """A bounded response returned by a single-hop, credential-free transport."""

    status: int
    headers: Mapping[str, str]
    body: bytes


class HTTPSResearchTransport(Protocol):
    """One-hop transport seam. Redirects are handled and revalidated by connector."""

    def fetch(self, url: str, *, timeout: float, max_bytes: int, resolved_ip: str) -> HTTPResponse: ...


Resolver = Callable[[str, int], list[str]]
Clock = Callable[[], datetime]


class ResearchSourceError(ValueError):
    """A safe research-boundary rejection; message intentionally omits response body."""


def _default_resolver(host: str, port: int) -> list[str]:
    return sorted({entry[4][0] for entry in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _is_public_destination(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified or ip.is_multicast)


def normalize_https_url(url: str) -> str:
    """Canonicalize safe URL presentation without changing path/query semantics."""
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise ResearchSourceError("invalid HTTPS URL") from exc
    if parts.scheme.lower() != "https" or not hostname or parts.username is not None or parts.password is not None:
        raise ResearchSourceError("research URLs must be credential-free HTTPS URLs")
    if port not in (None, 443):
        raise ResearchSourceError("research URLs must use HTTPS port 443")
    try:
        host = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ResearchSourceError("invalid HTTPS hostname") from exc
    netloc = host if ":" not in host else f"[{host}]"
    return urlunsplit(("https", netloc, parts.path or "/", parts.query, ""))


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """TLS connection that dials the connector-validated address, not a fresh DNS result."""

    def __init__(self, host: str, port: int, resolved_ip: str, timeout: float) -> None:
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self._resolved_ip = resolved_ip

    def connect(self) -> None:
        sock = socket.create_connection((self._resolved_ip, self.port), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class StdlibHTTPSResearchTransport:
    """Credential-free stdlib transport with DNS-pinned TLS and bounded reads."""

    def fetch(self, url: str, *, timeout: float, max_bytes: int, resolved_ip: str) -> HTTPResponse:
        parts = urlsplit(url)
        assert parts.hostname is not None
        connection = _PinnedHTTPSConnection(parts.hostname, parts.port or 443, resolved_ip, timeout)
        try:
            target = urlunsplit(("", "", parts.path or "/", parts.query, ""))
            connection.request("GET", target, headers={"Accept": "text/plain, text/html, application/json", "User-Agent": "agos-research/1"})
            response = connection.getresponse()
            body = response.read(max_bytes + 1)
            return HTTPResponse(response.status, {key.lower(): value for key, value in response.getheaders()}, body)
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise ResearchSourceError("HTTPS research request failed") from exc
        finally:
            connection.close()


class HTTPSResearchConnector:
    """Opt-in, allowlisted, redirect-safe HTTPS collector with no credential support."""

    def __init__(
        self,
        sources: Mapping[str, HTTPSResearchSource],
        allowed_hosts: frozenset[str],
        *,
        transport: HTTPSResearchTransport | None = None,
        resolver: Resolver = _default_resolver,
        timeout: float = 5.0,
        max_bytes: int = 1_000_000,
        max_redirects: int = 3,
        content_types: frozenset[str] = frozenset({"text/plain", "text/html", "application/json"}),
        clock: Clock = _utc_now,
    ) -> None:
        if not allowed_hosts:
            raise ValueError("HTTPS research requires an explicit non-empty host allowlist")
        if timeout <= 0 or max_bytes <= 0 or max_redirects < 0:
            raise ValueError("timeout, response cap, and redirect limit must be positive/safe")
        self._sources = dict(sources)
        self._allowed_hosts = frozenset(self._normalize_host(host) for host in allowed_hosts)
        if any(source_id != source.source_id for source_id, source in self._sources.items()):
            raise ValueError("HTTPS research source mapping keys must match source IDs")
        self._transport = transport or StdlibHTTPSResearchTransport()
        self._resolver, self._timeout, self._max_bytes = resolver, timeout, max_bytes
        self._max_redirects, self._content_types, self._clock = max_redirects, frozenset(item.lower() for item in content_types), clock

    @staticmethod
    def _normalize_host(host: str) -> str:
        normalized = normalize_https_url(f"https://{host}/")
        return urlsplit(normalized).hostname or ""

    def _validate_destination(self, url: str) -> tuple[str, str]:
        normalized = normalize_https_url(url)
        parts = urlsplit(normalized)
        assert parts.hostname is not None
        if parts.hostname not in self._allowed_hosts:
            raise ResearchSourceError("research URL host is not allow-listed")
        try:
            addresses = self._resolver(parts.hostname, parts.port or 443)
        except OSError as exc:
            raise ResearchSourceError("research hostname resolution failed") from exc
        try:
            safe_addresses = bool(addresses) and all(_is_public_destination(address) for address in addresses)
        except ValueError:
            safe_addresses = False
        if not safe_addresses:
            raise ResearchSourceError("research destination is not a public IP address")
        return normalized, addresses[0]

    def collect(self, source_ids: list[str]) -> list[dict[str, str]]:
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source ids must not contain duplicates")
        missing = [source_id for source_id in source_ids if source_id not in self._sources]
        if missing:
            raise ValueError(f"source ids are not allow-listed: {missing}")
        return [self._collect_one(self._sources[source_id]) for source_id in source_ids]

    def _collect_one(self, source: HTTPSResearchSource) -> dict[str, str]:
        url = source.url
        for hop in range(self._max_redirects + 1):
            normalized, resolved_ip = self._validate_destination(url)
            response = self._transport.fetch(normalized, timeout=self._timeout, max_bytes=self._max_bytes, resolved_ip=resolved_ip)
            if len(response.body) > self._max_bytes:
                raise ResearchSourceError("research response exceeds byte cap")
            headers = {key.lower(): value for key, value in response.headers.items()}
            if response.status in {301, 302, 303, 307, 308}:
                location = headers.get("location")
                if not location or hop == self._max_redirects:
                    raise ResearchSourceError("research redirect was missing or exceeded limit")
                url = urljoin(normalized, location)
                continue
            if not 200 <= response.status < 300:
                raise ResearchSourceError("research response status was not successful")
            content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type not in self._content_types:
                raise ResearchSourceError("research response content type is not allow-listed")
            try:
                content = response.body.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ResearchSourceError("research response must be UTF-8") from exc
            retrieved_at = self._clock().astimezone(UTC).isoformat().replace("+00:00", "Z")
            return {"source_id": source.source_id, "title": source.title, "url": normalized, "retrieved_at": retrieved_at, "digest": f"sha256:{hashlib.sha256(response.body).hexdigest()}", "content": content, "adapter": "https-research"}
        raise AssertionError("redirect loop should have returned or raised")
