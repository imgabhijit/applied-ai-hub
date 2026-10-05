"""
Fetches the written sources (RSS 2.0 / Atom feeds) listed in
data/portal_sources.csv and saves recent posts to data/posts.json.

No API key and no third-party packages. Sources without a feed URL ("Page
watch" in the CSV) are skipped here; the section pages link to them directly.

A feed that fails to download or parse is reported and skipped - its previous
posts are carried forward from the existing posts.json, so one flaky feed never
blanks a section.
"""

import gzip
import json
import datetime
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from pathlib import Path

from channels import SECTION_SLUGS, WRITTEN_BY_SECTION

POSTS_FILE      = Path(__file__).parent.parent / "data" / "posts.json"
WINDOW_DAYS     = 14
MAX_PER_FEED    = 30
FETCH_TIMEOUT   = 20
USER_AGENT      = "applied-ai-hub/1.0 (+https://github.com/imgabhijit/applied-ai-hub)"

ATOM = "{http://www.w3.org/2005/Atom}"


def now_ts():
    return int(datetime.datetime.now(datetime.timezone.utc).timestamp())


def parse_date(text):
    """RFC 822 (RSS) or ISO 8601 (Atom) -> unix seconds, or 0 if unparseable."""
    if not text:
        return 0
    text = text.strip()
    try:
        return int(parsedate_to_datetime(text).timestamp())
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return 0


def safe_link(url):
    """Only http(s) links ever reach the pages; anything else is dropped."""
    url = (url or "").strip()
    return url if url.lower().startswith(("https://", "http://")) else ""


def parse_feed(xml_bytes):
    """Return [{title, link, timestamp}] from an RSS 2.0 or Atom document."""
    root = ET.fromstring(xml_bytes)
    items = []

    for item in root.iter("item"):                       # RSS 2.0
        items.append({
            "title":     (item.findtext("title") or "").strip(),
            "link":      safe_link(item.findtext("link")),
            "timestamp": parse_date(item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date")),
        })

    for entry in root.iter(ATOM + "entry"):              # Atom
        link = ""
        for el in entry.findall(ATOM + "link"):
            if el.get("rel", "alternate") == "alternate":
                link = safe_link(el.get("href"))
                break
        items.append({
            "title":     (entry.findtext(ATOM + "title") or "").strip(),
            "link":      link,
            "timestamp": parse_date(entry.findtext(ATOM + "published") or entry.findtext(ATOM + "updated")),
        })

    return [i for i in items if i["title"] and i["link"] and i["timestamp"]]


def fetch_source(entry):
    slug, src = entry
    req = urllib.request.Request(src["feed"], headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as res:
            body = res.read()
            if body[:2] == b"\x1f\x8b":       # some servers gzip even without Accept-Encoding
                body = gzip.decompress(body)
            posts = parse_feed(body)
    except Exception as e:                               # network, HTTP or XML error
        print(f"  [fail] {src['name']}: {e}")
        return slug, src, None
    print(f"  {src['name']}: {len(posts)} posts")
    return slug, src, posts


def main():
    existing = {}
    if POSTS_FILE.exists():
        try:
            existing = json.loads(POSTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    cutoff  = now_ts() - WINDOW_DAYS * 86400
    sources = [(slug, src) for slug in SECTION_SLUGS
               for src in WRITTEN_BY_SECTION[slug] if src["feed"]]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch_source, sources))

    output = {"last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    for slug in SECTION_SLUGS:
        output[slug] = []

    failed = set()
    for slug, src, posts in results:
        if posts is None:
            failed.add((slug, src["name"]))
            continue
        for p in sorted(posts, key=lambda p: -p["timestamp"])[:MAX_PER_FEED]:
            if p["timestamp"] >= cutoff:
                output[slug].append({**p, "source": src["name"], "layer": src["layer"]})

    # Carry forward the previous posts of any feed that failed this run.
    for slug in SECTION_SLUGS:
        for p in existing.get(slug, []):
            if (slug, p.get("source")) in failed and p.get("timestamp", 0) >= cutoff:
                output[slug].append(p)
        output[slug].sort(key=lambda p: -p["timestamp"])

    POSTS_FILE.parent.mkdir(exist_ok=True)
    POSTS_FILE.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    total = sum(len(output[s]) for s in SECTION_SLUGS)
    print(f"[done] {total} posts saved to {POSTS_FILE}"
          + (f" ({len(failed)} feed(s) failed)" if failed else ""))


if __name__ == "__main__":
    main()
