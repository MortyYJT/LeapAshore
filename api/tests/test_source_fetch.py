from datetime import UTC, datetime
from hashlib import sha256

import pytest

from app.source_fetch import (
    MAX_SOURCE_BYTES,
    SourceFetchError,
    _RawResponse,
    fetch_official_source,
)


PUBLIC_ADDRESS = "1.1.1.1"
OFFICIAL_DOMAINS = ("unsw.edu.au",)
SOURCE_URL = "https://www.unsw.edu.au/study/postgraduate/master-of-information-technology"


def public_resolver(_hostname: str, _port: int) -> list[str]:
    return [PUBLIC_ADDRESS]


def test_official_fetch_revalidates_redirect_and_builds_bounded_snapshot() -> None:
    final_url = "https://study.unsw.edu.au/postgraduate/master-of-information-technology"
    body = "<html><body>Official entry requirements</body></html>".encode()
    calls: list[tuple[str, list[str]]] = []

    def requester(url: str, addresses, _timeout: float, _max_bytes: int) -> _RawResponse:
        calls.append((url, list(addresses)))
        if url == SOURCE_URL:
            return _RawResponse(302, {"location": final_url}, b"")
        return _RawResponse(
            200,
            {"content-type": "text/html; charset=utf-8", "content-length": str(len(body))},
            body,
        )

    fetched_at = datetime(2026, 7, 29, 1, 0, tzinfo=UTC)
    snapshot = fetch_official_source(
        SOURCE_URL,
        OFFICIAL_DOMAINS,
        resolver=public_resolver,
        requester=requester,
        now=fetched_at,
    )

    assert calls == [
        (SOURCE_URL, [PUBLIC_ADDRESS]),
        (final_url, [PUBLIC_ADDRESS]),
    ]
    assert snapshot.requested_url == SOURCE_URL
    assert snapshot.final_url == final_url
    assert snapshot.redirect_chain == [final_url]
    assert snapshot.fetched_at == fetched_at
    assert snapshot.content_type == "text/html"
    assert snapshot.content_bytes == len(body)
    assert snapshot.body_text == body.decode()
    assert snapshot.content_sha256 == sha256(body).hexdigest()


def test_official_fetch_rejects_private_or_mixed_dns_answers_before_request() -> None:
    requested = False

    def requester(*_args) -> _RawResponse:
        nonlocal requested
        requested = True
        raise AssertionError("private DNS answer reached the HTTP transport")

    with pytest.raises(SourceFetchError, match="非公网地址"):
        fetch_official_source(
            SOURCE_URL,
            OFFICIAL_DOMAINS,
            resolver=lambda _hostname, _port: [PUBLIC_ADDRESS, "127.0.0.1"],
            requester=requester,
        )
    assert requested is False


def test_official_fetch_rejects_redirect_outside_registered_school_domain() -> None:
    def requester(_url: str, _addresses, _timeout: float, _max_bytes: int) -> _RawResponse:
        return _RawResponse(302, {"location": "https://example.com/internal"}, b"")

    with pytest.raises(SourceFetchError, match="学校官方域名"):
        fetch_official_source(
            SOURCE_URL,
            OFFICIAL_DOMAINS,
            resolver=public_resolver,
            requester=requester,
        )


@pytest.mark.parametrize(
    ("headers", "body", "message"),
    [
        ({"content-type": "application/pdf"}, b"%PDF", "HTML 或纯文本"),
        ({"content-type": "text/html", "content-encoding": "gzip"}, b"compressed", "压缩编码"),
        (
            {"content-type": "text/html", "content-length": str(MAX_SOURCE_BYTES + 1)},
            b"small",
            "512 KiB",
        ),
        ({"content-type": "text/html"}, b"x" * (MAX_SOURCE_BYTES + 1), "512 KiB"),
    ],
)
def test_official_fetch_rejects_unreviewable_or_oversized_responses(
    headers: dict[str, str],
    body: bytes,
    message: str,
) -> None:
    def requester(_url: str, _addresses, _timeout: float, _max_bytes: int) -> _RawResponse:
        return _RawResponse(200, headers, body)

    with pytest.raises(SourceFetchError, match=message):
        fetch_official_source(
            SOURCE_URL,
            OFFICIAL_DOMAINS,
            resolver=public_resolver,
            requester=requester,
        )


def test_official_fetch_limits_redirects() -> None:
    redirect_number = 0

    def requester(url: str, _addresses, _timeout: float, _max_bytes: int) -> _RawResponse:
        nonlocal redirect_number
        redirect_number += 1
        return _RawResponse(302, {"location": f"{url.rstrip('/')}/next-{redirect_number}"}, b"")

    with pytest.raises(SourceFetchError, match="重定向次数"):
        fetch_official_source(
            SOURCE_URL,
            OFFICIAL_DOMAINS,
            resolver=public_resolver,
            requester=requester,
        )
    assert redirect_number == 4


@pytest.mark.parametrize(
    "url",
    [
        "http://www.unsw.edu.au/program",
        "https://user@www.unsw.edu.au/program",
        "https://www.unsw.edu.au:444/program",
        "https://www.unsw.edu.au@example.com/program",
    ],
)
def test_official_fetch_rejects_unsafe_url_forms(url: str) -> None:
    with pytest.raises(SourceFetchError):
        fetch_official_source(
            url,
            OFFICIAL_DOMAINS,
            resolver=public_resolver,
            requester=lambda *_args: _RawResponse(200, {"content-type": "text/plain"}, b"ok"),
        )
