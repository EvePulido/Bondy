"""The single, SSRF-safe way Bondy downloads a remote URL (no FastAPI, no ADK).

Every remote image fetch (``bondy.core.images``, the ADK vision tools and the
``fetch_image.py`` skill script) goes through :func:`fetch_public_bytes`.

Guarantees, per request *and per redirect hop* (at most ``MAX_REDIRECTS``):

- only ``http``/``https``, no ``user:pass@`` credentials;
- the host is resolved **once**; every returned address must be globally
  routable (no loopback, private, link-local/metadata, reserved, multicast...);
- the TCP connection goes to one of those *already validated* addresses, never
  to the hostname again, so a DNS answer that changes between the check and the
  connection (DNS rebinding, TTL 0) cannot reach an internal host. The original
  hostname is kept for the ``Host`` header and for TLS SNI/certificate checks;
- the body is read with a hard byte cap.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import urllib.parse
from dataclasses import dataclass

MAX_REDIRECTS = 3
DEFAULT_TIMEOUT_S = 10
USER_AGENT = "Bondy/1.0"
_REDIRECT_CODES = {301, 302, 303, 307, 308}


class NetGuardError(ValueError):
    """The URL (or a redirect target) is not allowed by the SSRF policy."""


class FetchError(OSError):
    """The request was allowed but failed (HTTP error, connection, size...)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ResponseTooLarge(FetchError):
    """The body exceeded ``max_bytes``."""


@dataclass(frozen=True)
class FetchResult:
    data: bytes
    content_type: str  # media type only, lowercase ('' when absent)
    final_url: str


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        # ::ffff:127.0.0.1 and NAT64/6to4 forms must be judged by the IPv4 inside
        if ip.ipv4_mapped is not None:
            return _is_public(ip.ipv4_mapped)
        if ip.sixtofour is not None and not _is_public(ip.sixtofour):
            return False
    return ip.is_global and not ip.is_multicast


def parse_public_url(url: str) -> tuple[str, str, int]:
    """Validates the *syntax* of ``url``; returns ``(scheme, host, port)``."""
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as e:
        raise NetGuardError(f"URL not allowed: '{url}': {e}") from e
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https") or not parsed.hostname:
        raise NetGuardError(
            f"URL not allowed: '{url}'. Only http(s) URLs are supported."
        )
    if parsed.username is not None or parsed.password is not None:
        raise NetGuardError("URL not allowed: credentials in the URL are rejected.")
    return scheme, parsed.hostname, port or (443 if scheme == "https" else 80)


def resolve_public(host: str, port: int) -> list[str]:
    """Resolves ``host`` once and returns its addresses, all of them public.

    Raises ``NetGuardError`` if it does not resolve or *any* address is not
    public (a mixed answer is refused outright).
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise NetGuardError(f"Could not resolve host '{host}': {e}") from e
    ips: list[str] = []
    for info in infos:
        raw = str(info[4][0]).split("%", 1)[0]  # drop IPv6 scope id
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError as e:
            raise NetGuardError(f"'{host}' resolved to an invalid address.") from e
        if not _is_public(ip):
            raise NetGuardError(
                f"URL not allowed: '{host}' resolves to a non-public address."
            )
        if raw not in ips:
            ips.append(raw)
    if not ips:
        raise NetGuardError(f"Could not resolve host '{host}'.")
    return ips


def validate_public_url(url: str) -> None:
    """Pre-check only (syntax + one resolution). Does NOT protect against
    rebinding by itself: to actually download use :func:`fetch_public_bytes`."""
    _, host, port = parse_public_url(url)
    resolve_public(host, port)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Connects to a pre-validated IP; ``self.host`` stays the original name."""

    def __init__(self, host: str, port: int, ip: str, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self._pinned_ip = ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, ip: str, timeout: float) -> None:
        self._tls_context = ssl.create_default_context()
        super().__init__(host, port, timeout=timeout, context=self._tls_context)
        self._pinned_ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        try:
            # SNI + certificate verification use the ORIGINAL hostname
            self.sock = self._tls_context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def _request(
    scheme: str, host: str, port: int, ips: list[str], target: str, timeout: float
):
    """Opens a pinned connection (first reachable validated IP) and sends GET."""
    last: Exception | None = None
    for ip in ips:
        cls = _PinnedHTTPSConnection if scheme == "https" else _PinnedHTTPConnection
        conn = cls(host, port, ip, timeout)
        try:
            conn.request(
                "GET",
                target,
                headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            )
            return conn, conn.getresponse()
        except (OSError, http.client.HTTPException) as e:
            conn.close()
            last = e
    raise FetchError(f"could not connect to '{host}': {last}")


def fetch_public_bytes(
    url: str,
    max_bytes: int,
    timeout: float = DEFAULT_TIMEOUT_S,
    max_redirects: int = MAX_REDIRECTS,
) -> FetchResult:
    """Downloads ``url`` (GET) under the SSRF policy described in the module doc.

    Raises ``NetGuardError`` when the URL or a redirect target is not allowed,
    ``FetchError`` (with ``.status`` for HTTP errors) for any other failure.
    """
    current = url
    for hop in range(max_redirects + 1):
        scheme, host, port = parse_public_url(current)
        ips = resolve_public(host, port)  # one resolution per hop
        parts = urllib.parse.urlsplit(current)
        target = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
        conn, res = _request(scheme, host, port, ips, target, timeout)
        try:
            if res.status in _REDIRECT_CODES:
                location = res.getheader("Location")
                if not location:
                    raise FetchError("redirect without Location header")
                if hop == max_redirects:
                    raise FetchError(f"more than {max_redirects} redirects")
                current = urllib.parse.urljoin(current, location)
                continue  # next hop is fully re-validated at the top of the loop
            if res.status != 200:
                raise FetchError(f"HTTP {res.status}", res.status)
            try:
                data = res.read(max_bytes + 1)
            except (OSError, http.client.HTTPException) as e:
                raise FetchError(f"could not download the body: {e}") from e
            if len(data) > max_bytes:
                raise ResponseTooLarge(f"response larger than {max_bytes} bytes")
            ctype = (res.getheader("Content-Type") or "").split(";", 1)[0]
            return FetchResult(data, ctype.strip().lower(), current)
        finally:
            conn.close()
    raise FetchError(f"more than {max_redirects} redirects")  # pragma: no cover
