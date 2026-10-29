"""Fill the school logos the first run could not fetch.

    api/.venv/bin/python scripts/fill-logos.py [--limit N] [--dry-run]

For every institution in web/prototype-fixtures/overseas-institutions.json without a `logo`:

1. Find its official website (the fixture's `website`, else Wikidata P856) and try the icon the site
   publishes itself (apple-touch-icon, then other `rel=icon` links, then /favicon.ico). PNG, ICO, JPEG
   and WebP only, with an honest User-Agent; robots.txt is honoured and a refusal is not retried.
2. Failing that, the logo Wikidata records (P154) on Wikimedia Commons, if its licence is free. Commons
   renders SVG files to PNG itself (`thumburl`), so nothing is rasterised here. Non-free files cannot
   live on Commons, and files restricted to Wikipedia are never used.

Each new logo is saved to web/public/logos/ and recorded on the row as `logo`, `logo_source` and, for
Commons files, `logo_license` and `logo_license_url`. Schools with neither keep the monogram fallback.
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "web" / "prototype-fixtures" / "overseas-institutions.json"
LOGO_DIR = ROOT / "web" / "public" / "logos"
USER_AGENT = "LeapAshoreBot/0.1 (+https://github.com/MortyYJT/leapashore; school-logo lookup)"
ACCEPTED = {"image/png": "png", "image/x-icon": "ico", "image/vnd.microsoft.icon": "ico",
            "image/jpeg": "jpg", "image/webp": "webp"}
MIN_BYTES = 400  # anything smaller is a blank or a 1x1 placeholder


def get(url: str, timeout: int = 20) -> tuple[int, str, bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.headers.get("Content-Type", "").split(";")[0].strip(), response.read(), response.geturl()
    except urllib.error.HTTPError as error:
        return error.code, "", b"", url
    except Exception:  # noqa: BLE001 - a dead site is an expected outcome here
        return 0, "", b"", url


def api_json(url: str) -> dict:
    """A Wikimedia API call, retried with backoff: a rate-limited answer is not an empty one."""
    for attempt in range(4):
        status, _, body, _ = get(url, timeout=30)
        time.sleep(1.0)
        if status == 200 and body:
            return json.loads(body)
        time.sleep(5 * (attempt + 1))
    return {}


_robots: dict[str, urllib.robotparser.RobotFileParser] = {}


def allowed(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _robots:
        parser = urllib.robotparser.RobotFileParser()
        status, _, body, _ = get(f"{base}/robots.txt")
        parser.parse(body.decode("utf-8", "replace").splitlines() if status == 200 else
                     (["User-agent: *", "Disallow: /"] if status in (401, 403) else []))
        _robots[base] = parser
    return _robots[base].can_fetch(USER_AGENT, url)


class IconLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[int, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        a = dict(attrs)
        rel = (a.get("rel") or "").lower()
        href = a.get("href")
        if not href or "icon" not in rel or (a.get("type") or "").endswith("svg+xml") or href.lower().split("?")[0].endswith(".svg"):
            return
        rank = 0 if "apple-touch-icon" in rel else 1
        self.links.append((rank, href))


def wikidata(name: str) -> dict:
    """The best Wikidata item for a university name: its official site and logo file, if recorded."""
    # "National University of Singapore (NUS)": the parenthesis is the fixture's, not the name's.
    query = re.sub(r"\s*\(.*?\)", "", name).strip()
    search = api_json("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "wbsearchentities", "search": query, "language": "en", "type": "item", "limit": 7, "format": "json"}))
    # Only items described as a higher-education institution, so a logo never comes from a namesake.
    ids = [hit["id"] for hit in search.get("search", [])
           if re.search(r"universit|college|institut|school|école|hochschule|polytechnic", hit.get("description", ""), re.I)]
    if not ids:
        return {}
    entities = api_json("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "wbgetentities", "ids": "|".join(ids), "props": "claims", "format": "json"})).get("entities", {})
    for qid in ids:
        claims = entities.get(qid, {}).get("claims", {})
        def first(prop):
            for claim in claims.get(prop, []):
                value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                if value:
                    return value
            return None
        # Square forms first, because the interface shows a logo in a small round slot: P8972 small
        # logo or icon, then P158 seal (a university's crest, its 校徽), then P154 logo, which is often
        # a wide wordmark.
        website = first("P856")
        files = [f for f in (first("P8972"), first("P158"), first("P154")) if f]
        if website or files:
            return {"qid": qid, "website": website, "logo_files": files}
    return {}


def site_icon(website: str) -> tuple[str, str, bytes] | None:
    if not website.startswith("http"):
        website = f"https://{website}"
    if not allowed(website):
        return None
    status, ctype, body, final = get(website)
    candidates = []
    if status == 200 and body:
        parser = IconLinks()
        try:
            parser.feed(body.decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            pass
        candidates = [urllib.parse.urljoin(final, href) for _, href in sorted(parser.links)]
    candidates.append(urllib.parse.urljoin(final if status == 200 else website, "/favicon.ico"))
    for url in candidates:
        if not allowed(url):
            continue
        status, ctype, data, _ = get(url)
        if status == 200 and ctype in ACCEPTED and len(data) >= MIN_BYTES:
            return url, ACCEPTED[ctype], data
    return None


def commons_logo(filename: str) -> dict | None:
    info = api_json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "titles": f"File:{filename}", "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata", "iiurlwidth": 256, "format": "json"}))
    pages = info.get("query", {}).get("pages", {})
    for page in pages.values():
        for image in page.get("imageinfo", []):
            meta = image.get("extmetadata", {})
            license_name = meta.get("LicenseShortName", {}).get("value", "")
            if not license_name or re.search(r"fair use|non-free", license_name, re.I):
                return None
            # A JPEG on Commons is almost always a photograph (Otago's "logo" is a picture of a wall
            # sign); a shape wider than 1.6:1 is a wordmark that turns into a sliver in a round slot.
            if image.get("mime") == "image/jpeg":
                return None
            width, height = image.get("thumbwidth") or image.get("width"), image.get("thumbheight") or image.get("height")
            if width and height and width / height > 1.6:
                return None
            url = image.get("thumburl") or image.get("url")
            status, ctype, data, _ = get(url)
            if status == 200 and ctype in ACCEPTED and len(data) >= MIN_BYTES:
                return {"url": url, "ext": ACCEPTED[ctype], "data": data, "page": image.get("descriptionurl"),
                        "license": re.sub("<[^>]+>", "", license_name).strip(),
                        "license_url": meta.get("LicenseUrl", {}).get("value")}
    return None


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def save(name: str, ext: str, data: bytes) -> str:
    filename = f"{slug(name)}-{hashlib.sha256(data).hexdigest()[:6]}.{ext}"
    (LOGO_DIR / filename).write_bytes(data)
    return filename


def dump(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--redo-commons", action="store_true", help="fetch every Commons-sourced logo again")
    args = parser.parse_args(argv)

    raw = FIXTURE.read_text(encoding="utf-8")
    document = json.loads(raw)
    if dump(document) != raw:
        print("the fixture does not round-trip byte for byte; refusing to rewrite it", file=sys.stderr)
        return 2

    if args.redo_commons and not args.dry_run:
        for row in document["institutions"]:
            if row.get("logo_license"):
                (LOGO_DIR / row["logo"]).unlink(missing_ok=True)
                for key in ("logo", "logo_source", "logo_license", "logo_license_url"):
                    row.pop(key, None)

    def rank(row):
        label = (row.get("qs_rank") or "").lstrip("=")
        return int(label) if label.isdigit() else 10_000

    missing = sorted((r for r in document["institutions"] if not r.get("logo") and r.get("name_en")), key=rank)
    report = []
    for row in missing[: args.limit]:
        found = wikidata(row["name_en"])
        website = row.get("website") or found.get("website")
        outcome = {"school": row["name_en"], "qs": row.get("qs_rank"), "website": website, "wikidata": found.get("qid")}
        icon = site_icon(website) if website else None
        if icon:
            url, ext, data = icon
            if not args.dry_run:
                row["logo"], row["logo_source"] = save(row["name_en"], ext, data), url
            outcome["result"] = f"site icon {url}"
        elif found.get("logo_files"):
            commons = next((c for c in map(commons_logo, found["logo_files"]) if c), None)
            if commons:
                if not args.dry_run:
                    row["logo"] = save(row["name_en"], commons["ext"], commons["data"])
                    row["logo_source"] = commons["page"]
                    row["logo_license"] = commons["license"]
                    if commons.get("license_url"):
                        row["logo_license_url"] = commons["license_url"]
                outcome["result"] = f"commons ({commons['license']})"
            else:
                outcome["result"] = "commons file not usable"
        else:
            outcome["result"] = "nothing found"
        report.append(outcome)
        print(json.dumps(outcome, ensure_ascii=False), flush=True)

    if not args.dry_run:
        FIXTURE.write_text(dump(document), encoding="utf-8")
    filled = sum(1 for o in report if o["result"].startswith(("site", "commons (")))
    print(json.dumps({"tried": len(report), "filled": filled}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
