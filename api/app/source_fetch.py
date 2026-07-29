from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import codecs
import http.client
import ipaddress
import re
import socket
import ssl
from urllib.parse import urljoin, urlsplit, urlunsplit

from .models import ProgramSourceSnapshot


MAX_SOURCE_BYTES = 512 * 1024
MAX_SOURCE_REDIRECTS = 3
SOURCE_FETCH_TIMEOUT_SECONDS = 5.0
ALLOWED_SOURCE_CONTENT_TYPES = frozenset({
    "application/xhtml+xml",
    "text/html",
    "text/plain",
})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_USER_AGENT = "OfferPilot-Source-Review/1.0"


class SourceFetchError(RuntimeError):
    def __init__(self, message: str, *, upstream: bool = False) -> None:
        super().__init__(message)
        self.upstream = upstream


@dataclass(frozen=True)
class _RawResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


Resolver = Callable[[str, int], Sequence[str]]
Requester = Callable[[str, Sequence[str], float, int], _RawResponse]


def _official_hostname(hostname: str, allowed_domains: Sequence[str]) -> bool:
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in allowed_domains
    )


def _validate_url(url: str, allowed_domains: Sequence[str]) -> tuple[str, str]:
    if (
        not url
        or len(url) > 2048
        or any(ord(character) < 32 or ord(character) == 127 for character in url)
    ):
        raise SourceFetchError("来源 URL 为空、过长或包含控制字符")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise SourceFetchError("来源 URL 端口无效") from error
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() != "https":
        raise SourceFetchError("来源抓取只允许 HTTPS")
    if parsed.username or parsed.password:
        raise SourceFetchError("来源 URL 不允许携带用户凭据")
    if not hostname or not _official_hostname(hostname, allowed_domains):
        raise SourceFetchError("来源抓取只能访问该项目登记的学校官方域名")
    if port not in {None, 443}:
        raise SourceFetchError("来源抓取只允许 HTTPS 默认端口")
    normalized = urlunsplit(("https", hostname, parsed.path or "/", parsed.query, ""))
    return normalized, hostname


def _validate_public_addresses(addresses: Sequence[str]) -> list[str]:
    if not addresses:
        raise SourceFetchError("学校官网域名没有可用的 DNS 记录", upstream=True)
    parsed_addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as error:
            raise SourceFetchError("学校官网 DNS 返回了无效地址") from error
        if not parsed.is_global:
            raise SourceFetchError("学校官网 DNS 解析包含非公网地址，抓取已拒绝")
        parsed_addresses.append(parsed)
    return [
        str(address)
        for address in sorted(set(parsed_addresses), key=lambda item: (item.version, int(item)))
    ]


def _resolve_public_addresses(hostname: str, port: int) -> list[str]:
    try:
        records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise SourceFetchError("学校官网域名解析失败", upstream=True) from error
    return _validate_public_addresses([record[4][0] for record in records])


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Dial a validated IP while preserving the official hostname for TLS SNI."""

    def __init__(self, hostname: str, resolved_address: str, *, timeout: float) -> None:
        super().__init__(hostname, port=443, timeout=timeout, context=ssl.create_default_context())
        self._resolved_address = resolved_address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._resolved_address, self.port),
            self.timeout,
            self.source_address,
        )
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def _request_pinned(
    url: str,
    addresses: Sequence[str],
    timeout_seconds: float,
    max_bytes: int,
) -> _RawResponse:
    parsed = urlsplit(url)
    target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    last_error: Exception | None = None
    for address in addresses:
        connection = _PinnedHTTPSConnection(parsed.hostname or "", address, timeout=timeout_seconds)
        try:
            connection.request(
                "GET",
                target,
                headers={
                    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                    "User-Agent": _USER_AGENT,
                },
            )
            response = connection.getresponse()
            headers = {name.lower(): value.strip() for name, value in response.getheaders()}
            body = b"" if response.status in REDIRECT_STATUSES else response.read(max_bytes + 1)
            return _RawResponse(status=response.status, headers=headers, body=body)
        except (OSError, ssl.SSLError, http.client.HTTPException) as error:
            last_error = error
        finally:
            connection.close()
    raise SourceFetchError("学校官网连接失败或 TLS 校验未通过", upstream=True) from last_error


def _response_charset(content_type: str) -> str:
    match = re.search(r"(?:^|;)\s*charset\s*=\s*[\"']?([^;\"'\s]+)", content_type, re.IGNORECASE)
    charset = match.group(1) if match else "utf-8"
    try:
        return codecs.lookup(charset).name
    except LookupError as error:
        raise SourceFetchError("学校官网返回了未知字符编码", upstream=True) from error


def fetch_official_source(
    url: str,
    allowed_domains: Sequence[str],
    *,
    resolver: Resolver = _resolve_public_addresses,
    requester: Requester = _request_pinned,
    now: datetime | None = None,
) -> ProgramSourceSnapshot:
    """Fetch one bounded official page and return a review-only text snapshot."""

    requested_url, hostname = _validate_url(url, allowed_domains)
    current_url = requested_url
    redirect_chain: list[str] = []

    while True:
        addresses = _validate_public_addresses(resolver(hostname, 443))
        response = requester(
            current_url,
            addresses,
            SOURCE_FETCH_TIMEOUT_SECONDS,
            MAX_SOURCE_BYTES,
        )
        if response.status in REDIRECT_STATUSES:
            if len(redirect_chain) >= MAX_SOURCE_REDIRECTS:
                raise SourceFetchError("学校官网重定向次数超过安全上限", upstream=True)
            location = response.headers.get("location", "").strip()
            if not location:
                raise SourceFetchError("学校官网重定向缺少 Location", upstream=True)
            current_url, hostname = _validate_url(urljoin(current_url, location), allowed_domains)
            redirect_chain.append(current_url)
            continue
        if response.status != 200:
            raise SourceFetchError(f"学校官网返回 HTTP {response.status}", upstream=True)

        content_type_header = response.headers.get("content-type", "")
        media_type = content_type_header.split(";", 1)[0].strip().lower()
        if media_type not in ALLOWED_SOURCE_CONTENT_TYPES:
            raise SourceFetchError("学校官网响应不是允许的 HTML 或纯文本")
        content_encoding = response.headers.get("content-encoding", "").strip().lower()
        if content_encoding not in {"", "identity"}:
            raise SourceFetchError("学校官网响应使用了不受支持的压缩编码")
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError as error:
                raise SourceFetchError("学校官网 Content-Length 无效", upstream=True) from error
            if declared_length < 0 or declared_length > MAX_SOURCE_BYTES:
                raise SourceFetchError("学校官网响应超过 512 KiB 安全上限")
        if not response.body:
            raise SourceFetchError("学校官网响应正文为空", upstream=True)
        if len(response.body) > MAX_SOURCE_BYTES:
            raise SourceFetchError("学校官网响应超过 512 KiB 安全上限")

        body_text = response.body.decode(_response_charset(content_type_header), errors="replace")
        canonical_body = body_text.encode("utf-8")
        return ProgramSourceSnapshot(
            requested_url=requested_url,
            final_url=current_url,
            fetched_at=now or datetime.now(UTC),
            content_type=media_type,
            content_sha256=sha256(canonical_body).hexdigest(),
            content_bytes=len(response.body),
            body_text=body_text,
            redirect_chain=redirect_chain,
        )
