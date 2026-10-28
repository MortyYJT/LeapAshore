"""Fetch one official page politely and keep a snapshot of it.

    python -m app.collect.snapshot <url> --school <school-key> [--render]

Rules this enforces, so a collecting agent cannot forget them:

- `robots.txt` is honoured; a disallowed URL is not fetched.
- At most one request every `MIN_INTERVAL` seconds per domain, shared across processes.
- A 403 or 429 is recorded as a block and never retried with a different identity: a site that
  refuses us is left alone.
- The User-Agent names the project.

The raw HTML and its visible text are written under `api/var/snapshots/<school>/<sha256>.*`, with a
`.json` record of where and when it came from. The sha256 of the HTML names the snapshot, so a data
file can cite exactly the version its quotes were checked against.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
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


def snapshot_dir(school: str, root: Path = SNAPSHOT_ROOT) -> Path:
    return root / school


def _rate_file(domain: str, root: Path) -> Path:
    return root / "_rate" / domain


def wait_for_turn(domain: str, root: Path = SNAPSHOT_ROOT, now=time.time, sleep=time.sleep) -> None:
    """Sleep until `MIN_INTERVAL` has passed since the last request to `domain`, then claim it."""
    marker = _rate_file(domain, root)
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        last = float(marker.read_text() or 0)
    except (FileNotFoundError, ValueError):
        last = 0.0
    gap = last + MIN_INTERVAL - now()
    if gap > 0:
        sleep(gap)
    marker.write_text(str(now()))


_robots: dict[str, urllib.robotparser.RobotFileParser] = {}


def allowed_by_robots(url: str) -> bool:
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    parser = _robots.get(base)
    if parser is None:
        parser = urllib.robotparser.RobotFileParser()
        try:
            request = urllib.request.Request(f"{base}/robots.txt", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                parser.parse(response.read().decode("utf-8", "replace").splitlines())
        except urllib.error.HTTPError as error:
            # 401/403 on robots.txt means "keep out" by convention; a missing file means no rules.
            parser.parse(["User-agent: *", "Disallow: /"] if error.code in (401, 403) else [])
        except Exception:
            parser.parse([])
        _robots[base] = parser
    return parser.can_fetch(USER_AGENT, url)


def fetch_html(url: str) -> tuple[int, str, str, str]:
    """(status, final_url, content_type, html) over plain HTTP."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read()
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
    path.parent.mkdir(parents=True, exist_ok=True)
    blocked = json.loads(path.read_text()) if path.exists() else []
    blocked.append({"url": url, "reason": reason, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    path.write_text(json.dumps(blocked, ensure_ascii=False, indent=1))


def save_snapshot(school: str, requested_url: str, final_url: str, status: int, content_type: str,
                  html: str, root: Path = SNAPSHOT_ROOT, rendered: bool = False) -> dict:
    sha = hashlib.sha256(html.encode("utf-8")).hexdigest()
    folder = snapshot_dir(school, root)
    folder.mkdir(parents=True, exist_ok=True)
    text = html_to_text(html)
    (folder / f"{sha}.html").write_text(html, encoding="utf-8")
    (folder / f"{sha}.txt").write_text(text, encoding="utf-8")
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
    (folder / f"{sha}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    return meta


def snapshot(url: str, school: str, render: bool = False, root: Path = SNAPSHOT_ROOT) -> dict:
    if not allowed_by_robots(url):
        record_block(school, url, "robots.txt disallows", root)
        raise Blocked(f"robots.txt disallows {url}")
    wait_for_turn(urlsplit(url).netloc, root)
    status, final_url, content_type, html = render_html(url) if render else fetch_html(url)
    if status in (401, 403, 429):
        record_block(school, url, f"HTTP {status}", root)
        raise Blocked(f"HTTP {status} for {url}")
    if status >= 400 or not html:
        raise RuntimeError(f"HTTP {status} for {url}")
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
