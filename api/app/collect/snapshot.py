"""Fetch one official page politely and keep a snapshot of it.

    python -m app.collect.snapshot <url> --school <school-key> [--render]

Rules this enforces, so a collecting agent cannot forget them:

- `robots.txt` is honoured; a disallowed URL is not fetched.
- At most one request every `MIN_INTERVAL` seconds per domain, shared across processes.
- A 403 or 429 is recorded as a block and never retried with a different identity: a site that
  refuses us is left alone. A refusal recorded with a time holds for `REFUSAL_DAYS` days; one recorded
  before refusals carried a time holds until it is removed by hand.
- The User-Agent names the project.

The raw HTML and its visible text are written under `api/var/snapshots/<school>/<sha256>.*`, with a
`.json` record of where and when it came from. The sha256 of the HTML names the snapshot, so a data
file can cite exactly the version its quotes were checked against.
"""

import argparse
import contextlib
import contextvars
import fcntl
import gzip
import hashlib
import json
import os
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from app.collect.text import html_to_text

USER_AGENT = "LeapAshoreBot/0.1 (+https://github.com/MortyYJT/leapashore; admission-requirements research)"
MIN_INTERVAL = 2.0
TIMEOUT = 30
API_DIR = Path(__file__).resolve().parents[2]
SNAPSHOT_ROOT = API_DIR / "var" / "snapshots"
RENDER_SCRIPT = API_DIR.parent / "scripts" / "render-page.cjs"


class Blocked(Exception):
    """The site refused the request (403/429) or robots.txt disallows it."""


class HttpError(RuntimeError):
    """The page answered with an error status other than a refusal (404, 500…)."""

    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status} for {url}")
        self.status = status


# A limiter other than the file lock below, for the code running in this context: the queue installs
# its Redis token bucket here (`use_limiter`), so robots.txt and page fetches both take its turns.
_LIMITER: contextvars.ContextVar = contextvars.ContextVar("snapshot_limiter", default=None)


@contextlib.contextmanager
def use_limiter(limiter):
    """Within the block, every request waits on `limiter(host)` instead of the file lock."""
    token = _LIMITER.set(limiter)
    try:
        yield
    finally:
        _LIMITER.reset(token)


def snapshot_dir(school: str, root: Path = SNAPSHOT_ROOT) -> Path:
    return root / school


def _rate_file(domain: str, root: Path) -> Path:
    return root / "_rate" / domain


def wait_for_turn(domain: str, root: Path = SNAPSHOT_ROOT, now=time.time, sleep=time.sleep,
                  interval: float | None = None) -> None:
    """Sleep until `interval` (at least `MIN_INTERVAL`) has passed since the last request to `domain`,
    then claim it. `interval` is the site's robots.txt Crawl-delay, when it states one.

    The marker is locked while it is read and rewritten, so collectors running at the same time
    take turns instead of both reading an old timestamp.
    """
    interval = max(MIN_INTERVAL, interval or 0)
    limiter = _LIMITER.get()
    if limiter is not None:
        limiter(domain, interval)
        return
    marker = _rate_file(domain, root)
    marker.parent.mkdir(parents=True, exist_ok=True)
    with open(marker, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        try:
            last = float(handle.read() or 0)
        except ValueError:
            last = 0.0
        gap = last + interval - now()
        if gap > 0:
            sleep(gap)
        handle.seek(0)
        handle.truncate()
        handle.write(str(now()))


def _write_atomic(path: Path, text: str) -> None:
    """Write via a temporary file and a rename, so a reader in another thread or process sees the old
    file or the new one, never an empty or half-written one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


@contextlib.contextmanager
def _locked(path: Path):
    """An exclusive lock for a read-modify-write of `path`, across threads and processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(f".{path.name}.lock"), "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _blocked_hosts_file(root: Path) -> Path:
    return root / "_blocked_hosts.json"


# A refusal is honoured this long, then the host may be asked again with the same identity
# (openspec collect-queue D5). Sites change their rules; a monthly re-collection must be able to return.
REFUSAL_DAYS = 30


def _active_reason(entry, now: datetime) -> str | None:
    """The reason of a refusal that still holds. A bare string predates refusal times: it holds."""
    if entry is None:
        return None
    if isinstance(entry, str):
        return entry
    try:
        at = datetime.fromisoformat(entry["at"])
    except (KeyError, TypeError, ValueError):
        return entry.get("reason") or "refused"
    return entry.get("reason") if now - at < timedelta(days=REFUSAL_DAYS) else None


def blocked_host(host: str, root: Path = SNAPSHOT_ROOT, now: datetime | None = None) -> str | None:
    """Why `host` refused us, while that refusal holds, or None."""
    path = _blocked_hosts_file(root)
    if not path.exists():
        return None
    hosts = json.loads(path.read_text())
    now = now or datetime.now(timezone.utc)
    # www.x and x are one site: a refusal from either holds for both.
    bare = host.lower().removeprefix("www.")
    for name in (host, bare, f"www.{bare}"):
        reason = _active_reason(hosts.get(name), now)
        if reason:
            return reason
    return None


def block_host(host: str, reason: str, root: Path = SNAPSHOT_ROOT, now: datetime | None = None) -> None:
    """Record that `host` refused us, and when. An earlier refusal that still holds is kept as it is."""
    path = _blocked_hosts_file(root)
    now = now or datetime.now(timezone.utc)
    with _locked(path):
        hosts = json.loads(path.read_text()) if path.exists() else {}
        if _active_reason(hosts.get(host), now) is None:
            hosts[host] = {"reason": reason, "at": now.isoformat(timespec="seconds")}
        _write_atomic(path, json.dumps(hosts, ensure_ascii=False, indent=1))


ROBOTS_TTL = 24 * 3600


def tls_context() -> ssl.SSLContext:
    """A verifying TLS context against a current root store.

    Verification is never turned off. macOS's /etc/ssl/cert.pem lacks newer roots such as HARICA TLS
    RSA Root CA 2021, which signs the GEANT certificates of many European universities, so every
    such site failed as "self-signed certificate in chain". certifi's bundle has them; it is used
    when installed (it comes with httpx and requests) and the system store otherwise.
    """
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


KEEP_OUT_MARK = "# leapashore keep-out: "
NO_ANSWER_TTL = 3600


def _keep_out(reason: str) -> list[str]:
    # robots.txt parsers ignore comments, so the reason rides along without changing the rules.
    return [f"{KEEP_OUT_MARK}{reason}", "User-agent: *", "Disallow: /"]


def robots_rules(base: str, root: Path = SNAPSHOT_ROOT) -> list[str]:
    """The robots.txt lines for `base`, cached on disk for a day so each fetch does not ask again.

    Per RFC 9309: a missing file (404 and other 4xx) means no rules; 401/403/429, a server error, or
    no answer means "keep out", because a site that cannot say what it allows has not allowed it.
    A keep-out the site did not state (no answer, a server error) is asked again after an hour.
    """
    cache = root / "_robots" / urlsplit(base).netloc
    if cache.exists():
        lines = cache.read_text(encoding="utf-8").splitlines()
        transient = bool(lines) and lines[0].startswith(KEEP_OUT_MARK + "no answer") or (
            bool(lines) and lines[0].startswith(KEEP_OUT_MARK + "HTTP 5"))
        if time.time() - cache.stat().st_mtime < (NO_ANSWER_TTL if transient else ROBOTS_TTL):
            return lines
    wait_for_turn(urlsplit(base).netloc, root)
    try:
        request = urllib.request.Request(f"{base}/robots.txt", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=tls_context()) as response:
            lines = response.read().decode("utf-8", "replace").splitlines()
    except urllib.error.HTTPError as error:
        lines = _keep_out(f"HTTP {error.code}") if error.code in (401, 403, 429) or error.code >= 500 else []
    except Exception as error:  # noqa: BLE001 - timeouts and resets: no answer is not permission
        detail = str(getattr(error, "reason", error))[:100].replace("\n", " ")
        lines = _keep_out(f"no answer ({type(error).__name__}: {detail})")
    _write_atomic(cache, "\n".join(lines))
    return lines


def robots_keep_out_reason(url: str, root: Path = SNAPSHOT_ROOT) -> str | None:
    """Why robots.txt keeps us out of the whole host, when the site did not say so itself."""
    lines = robots_rules(f"{urlsplit(url).scheme}://{urlsplit(url).netloc}", root)
    return lines[0][len(KEEP_OUT_MARK):] if lines and lines[0].startswith(KEEP_OUT_MARK) else None


def crawl_delay(url: str, root: Path = SNAPSHOT_ROOT) -> float | None:
    """The seconds robots.txt asks between our requests to this host (`Crawl-delay`), if it says.

    Not part of RFC 9309, but a site that writes it is asking for that pace, so it is honoured: the
    host's turn comes round no sooner (`wait_for_turn`)."""
    # Read from the cache `refusal` has just filled; this never asks the site itself.
    cache = root / "_robots" / urlsplit(url).netloc
    if not cache.exists():
        return None
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(cache.read_text(encoding="utf-8").splitlines())
    try:
        delay = parser.crawl_delay(USER_AGENT)
        return float(delay) if delay is not None else None
    except (TypeError, ValueError):
        return None


def allowed_by_robots(url: str, root: Path = SNAPSHOT_ROOT) -> bool:
    parts = urlsplit(url)
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(robots_rules(f"{parts.scheme}://{parts.netloc}", root))
    return parser.can_fetch(USER_AGENT, url)


class CheckedRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only where a fresh request would be allowed (robots.txt, refused hosts)."""

    def __init__(self, refusal) -> None:
        super().__init__()
        self.refusal = refusal  # url -> reason it may not be fetched, or None

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        reason = self.refusal(newurl)
        if reason:
            raise Blocked(f"redirected to {newurl}: {reason}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def as_uri(url: str) -> str:
    """The address with non-ASCII characters percent-encoded (`/máster` → `/m%C3%A1ster`), as a
    browser sends it; http.client refuses a request line that is not ASCII. Escapes already present
    are kept, and the host is written in IDNA."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname.encode("idna").decode("ascii") if parts.hostname else ""
    netloc = host + (f":{parts.port}" if parts.port else "")
    safe = "/%:@!$&'()*+,;=-._~"
    return urllib.parse.urlunsplit((parts.scheme, netloc, urllib.parse.quote(parts.path, safe=safe),
                                    urllib.parse.quote(parts.query, safe=safe + "?"), ""))


def fetch_html(url: str, refusal=lambda url: None) -> tuple[int, str, str, str]:
    """(status, final_url, content_type, html) over plain HTTP."""
    request = urllib.request.Request(as_uri(url), headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
    opener = urllib.request.build_opener(CheckedRedirects(refusal), urllib.request.HTTPSHandler(context=tls_context()))
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            raw = response.read()
            if (response.headers.get("Content-Encoding") or "").lower() == "gzip" or raw[:2] == b"\x1f\x8b":
                # Sent compressed although we never asked for it.
                raw = gzip.decompress(raw)
            charset = response.headers.get_content_charset() or "utf-8"
            return response.status, response.geturl(), response.headers.get("Content-Type", ""), raw.decode(charset, "replace")
    except urllib.error.HTTPError as error:
        return error.code, url, error.headers.get("Content-Type", "") if error.headers else "", ""


def render_html(url: str) -> tuple[int, str, str, str]:
    """(status, final_url, content_type, html) after the page's scripts ran, in real Chrome."""
    result = subprocess.run(
        ["node", str(RENDER_SCRIPT), url, USER_AGENT],
        capture_output=True, text=True, timeout=120, env={**os.environ, "NODE_DEBUG": ""},
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-500:])
    payload = json.loads(result.stdout)
    return payload["status"], payload["url"], "text/html", payload["html"]


def record_block(school: str, url: str, reason: str, root: Path = SNAPSHOT_ROOT) -> None:
    path = snapshot_dir(school, root) / "_blocked.json"
    with _locked(path):
        blocked = json.loads(path.read_text()) if path.exists() else []
        blocked.append({"url": url, "reason": reason, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        _write_atomic(path, json.dumps(blocked, ensure_ascii=False, indent=1))


def save_snapshot(school: str, requested_url: str, final_url: str, status: int, content_type: str,
                  html: str, root: Path = SNAPSHOT_ROOT, rendered: bool = False) -> dict:
    sha = hashlib.sha256(html.encode("utf-8")).hexdigest()
    folder = snapshot_dir(school, root)
    folder.mkdir(parents=True, exist_ok=True)
    text = html_to_text(html)
    _write_atomic(folder / f"{sha}.html", html)
    _write_atomic(folder / f"{sha}.txt", text)
    meta = {
        "sha256": sha,
        "requested_url": requested_url,
        "final_url": final_url,
        "status": status,
        "content_type": content_type,
        "rendered": rendered,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "text_path": str(folder / f"{sha}.txt"),
        "text_chars": len(text),
    }
    _write_atomic(folder / f"{sha}.json", json.dumps(meta, ensure_ascii=False, indent=1))
    return meta


def refusal(url: str, root: Path = SNAPSHOT_ROOT) -> str | None:
    """Why `url` may not be fetched: its host refused us before, or robots.txt disallows it."""
    earlier = blocked_host(urlsplit(url).netloc, root)
    if earlier:
        return f"{urlsplit(url).netloc} refused an earlier request ({earlier}); not asking again"
    if not allowed_by_robots(url, root):
        why = robots_keep_out_reason(url, root)
        return f"robots.txt disallows (robots.txt itself: {why})" if why else "robots.txt disallows"
    return None


def snapshot(url: str, school: str, render: bool = False, root: Path = SNAPSHOT_ROOT) -> dict:
    host = urlsplit(url).netloc
    reason = refusal(url, root)
    if reason:
        if reason.startswith("robots"):
            record_block(school, url, reason, root)
            raise Blocked(f"{reason}: {url}")
        raise Blocked(reason)
    wait_for_turn(host, root, interval=crawl_delay(url, root))
    try:
        if render:
            status, final_url, content_type, html = render_html(url)
        else:
            status, final_url, content_type, html = fetch_html(url, refusal=lambda u: refusal(u, root))
    except Blocked as blocked:
        record_block(school, url, str(blocked), root)
        raise
    # A rendered page follows redirects inside Chrome, so its destination is checked after the fact:
    # a page we may not fetch is discarded, never saved or quoted.
    if final_url != url:
        reason = refusal(final_url, root)
        if reason:
            record_block(school, url, f"redirected to {urlsplit(final_url).netloc}: {reason}", root)
            raise Blocked(f"{url} redirected to {final_url}: {reason}")
    if status in (401, 403, 429):
        record_block(school, url, f"HTTP {status}", root)
        block_host(urlsplit(final_url).netloc or host, f"HTTP {status}", root)
        raise Blocked(f"HTTP {status} for {url}")
    if status >= 400 or not html:
        raise HttpError(status, url)
    return save_snapshot(school, url, final_url, status, content_type, html, root, rendered=render)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("url")
    parser.add_argument("--school", required=True)
    parser.add_argument("--render", action="store_true", help="run the page's scripts in real Chrome first")
    args = parser.parse_args(argv)
    try:
        meta = snapshot(args.url, args.school, render=args.render)
    except Blocked as blocked:
        print(json.dumps({"blocked": str(blocked)}, ensure_ascii=False))
        return 4
    except Exception as error:  # noqa: BLE001 - the agent needs the reason, not a traceback
        print(json.dumps({"error": str(error)[:500]}, ensure_ascii=False))
        return 2
    print(json.dumps(meta, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
