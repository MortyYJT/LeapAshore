"""Which address a request is counted against (openspec/changes/advisor-limits, D8)."""

import pytest
from starlette.requests import Request

from app import net
from app.config import settings


def request_from(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "client": (peer, 1234)})


@pytest.fixture(autouse=True)
def fresh_resolver_cache():
    net._resolved.clear()
    yield
    net._resolved.clear()


def test_without_a_trusted_proxy_the_header_is_ignored(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "")
    assert net.client_ip(request_from("172.18.0.5", "203.0.113.9")) == "172.18.0.5"


def test_a_peer_that_is_not_the_proxy_cannot_forge_the_header(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "172.18.0.2")
    assert net.client_ip(request_from("172.18.0.9", "203.0.113.9")) == "172.18.0.9"


def test_the_proxy_s_right_most_entry_is_the_client(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "172.18.0.2")
    assert net.client_ip(request_from("172.18.0.2", "198.51.100.1, 203.0.113.7")) == "203.0.113.7"


def test_a_cidr_entry_matches(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.1, 172.16.0.0/12")
    assert net.client_ip(request_from("172.18.0.2", "203.0.113.7")) == "203.0.113.7"


def test_the_proxy_without_a_header_is_counted_as_itself(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "172.18.0.2")
    assert net.client_ip(request_from("172.18.0.2")) == "172.18.0.2"


def test_a_hostname_entry_is_resolved_and_cached(monkeypatch):
    calls = []

    def fake_resolve(host):
        calls.append(host)
        return {"172.18.0.2"}

    monkeypatch.setattr(settings, "trusted_proxies", "caddy")
    monkeypatch.setattr(net, "_resolve", fake_resolve)
    assert net.client_ip(request_from("172.18.0.2", "203.0.113.7")) == "203.0.113.7"
    assert net.client_ip(request_from("172.18.0.3", "203.0.113.7")) == "172.18.0.3"
    assert calls == ["caddy"]


def test_an_unresolvable_hostname_trusts_nobody(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "no-such-host.invalid")
    monkeypatch.setattr(net, "_resolve", lambda host: set())
    assert net.client_ip(request_from("172.18.0.2", "203.0.113.7")) == "172.18.0.2"


def test_a_peer_that_stops_matching_triggers_a_fresh_lookup(monkeypatch):
    """A recreated proxy comes back on a new address; it is trusted within a second, not after 30."""
    answers = iter([{"172.18.0.2"}, {"172.18.0.7"}])
    clock = [100.0]
    monkeypatch.setattr(settings, "trusted_proxies", "caddy")
    monkeypatch.setattr(net, "_resolve", lambda host: next(answers))
    monkeypatch.setattr(net.time, "monotonic", lambda: clock[0])
    assert net.client_ip(request_from("172.18.0.2", "203.0.113.7")) == "203.0.113.7"
    clock[0] += 2
    assert net.client_ip(request_from("172.18.0.7", "203.0.113.7")) == "203.0.113.7"
