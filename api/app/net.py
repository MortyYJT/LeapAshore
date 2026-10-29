"""The address a request is counted against (openspec/changes/advisor-limits, D8).

`X-Forwarded-For` is whatever the sender wrote, so it is read only when the connection itself comes
from a listed proxy (`TRUSTED_PROXIES`). Production lists the `caddy` service, whose Caddyfile sets the
header to the address it accepted the connection from; any other peer, including a client that reaches
the API directly, is counted as its own address whatever header it sends.
"""

import ipaddress
import socket
import time

from starlette.requests import Request

from app.config import settings

# Hostname entries are resolved at most this often; a restarted proxy container gets a new address.
RESOLVE_TTL_SECONDS = 30.0
_resolved: dict[str, tuple[float, set[str]]] = {}


def _resolve(host: str) -> set[str]:
    try:
        return {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return set()


def _addresses_of(host: str) -> set[str]:
    now = time.monotonic()
    cached = _resolved.get(host)
    if cached and now - cached[0] < RESOLVE_TTL_SECONDS:
        return cached[1]
    addresses = _resolve(host)
    _resolved[host] = (now, addresses)
    return addresses


def is_trusted_proxy(peer: str) -> bool:
    """True when `peer` is one of the `TRUSTED_PROXIES` entries (IP, CIDR or hostname)."""
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        peer_ip = None
    for entry in (part.strip() for part in settings.trusted_proxies.split(",")):
        if not entry:
            continue
        if entry == peer:
            return True
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            if peer in _addresses_of(entry):
                return True
            continue
        if peer_ip is not None and peer_ip in network:
            return True
    return False


def client_ip(request: Request) -> str | None:
    """The caller's address: the proxy's right-most `X-Forwarded-For` entry, else the peer."""
    peer = request.client.host if request.client else None
    if peer and is_trusted_proxy(peer):
        forwarded = request.headers.get("x-forwarded-for", "")
        entries = [part.strip() for part in forwarded.split(",") if part.strip()]
        if entries:
            return entries[-1][:64]
    return peer[:64] if peer else None
