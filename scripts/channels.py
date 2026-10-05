"""
Source registry for Applied AI Hub.

data/portal_sources.csv is the single source of truth for every channel and
written feed. This module only groups it into sections - one section per
`track` value in the CSV - and reads the display metadata for each section from data/sections.json.

To add or remove a source, edit the CSV; to add or change a section, edit
data/sections.json. Commit on GitHub: the refresh workflow rebuilds every page
(scripts/build_pages.py) and fetches the new channels by itself.
"""

import csv
import json
import re
from pathlib import Path

SOURCES_FILE = Path(__file__).parent.parent / "data" / "portal_sources.csv"

SECTIONS_FILE = Path(__file__).parent.parent / "data" / "sections.json"

# Slugs that are already pages of their own.
RESERVED_SLUGS = {"index", "all", "player"}


def _load_sections():
    """The sections of the site, from data/sections.json (order = dropdown/tile order).

    `slug` is the page name (<slug>.html) and the key used in data/videos.json and
    data/posts.json; `track` must match the CSV's `track` column.
    """
    with SECTIONS_FILE.open(encoding="utf-8") as f:
        sections = json.load(f)["sections"]
    seen_slugs, seen_tracks = set(), set()
    for s in sections:
        missing = [k for k in ("slug", "track", "title", "icon", "color", "blurb") if not s.get(k)]
        if missing:
            raise ValueError(f"{SECTIONS_FILE.name}: section {s.get('slug') or s} is missing {missing}")
        if not re.fullmatch(r"[a-z0-9_]+", s["slug"]) or s["slug"] in RESERVED_SLUGS:
            raise ValueError(f"{SECTIONS_FILE.name}: bad slug {s['slug']!r} "
                             f"(use lowercase letters, digits and _; not {sorted(RESERVED_SLUGS)})")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", s["color"]):
            raise ValueError(f"{SECTIONS_FILE.name}: {s['slug']}: color must look like #1a2b3c")
        if s["slug"] in seen_slugs or s["track"] in seen_tracks:
            raise ValueError(f"{SECTIONS_FILE.name}: duplicate slug or track in {s['slug']!r}")
        seen_slugs.add(s["slug"]); seen_tracks.add(s["track"])
        if s.get("title_filter") and s["title_filter"] not in TITLE_FILTERS:
            raise ValueError(f"{SECTIONS_FILE.name}: {s['slug']}: unknown title_filter {s['title_filter']!r} "
                             f"(known: {sorted(TITLE_FILTERS)})")
    return sections



# The aggregated page (all.html) is not a section: it merges every section above.
HOME = {"slug": "all", "title": "All Videos", "icon": "🌐", "color": "#7c5cff",
        "blurb": "Every section in one feed, with a Section filter"}
# The landing page (index.html): a tile grid linking to the pages.
LANDING = {"slug": "index", "title": "Home", "icon": "🏠", "color": "#7c5cff"}

# Title filters a section can opt into with "title_filter". A video is kept only if
# its title still matches `match` after `strip` removes phrases that contain "AI"
# without being about AI: the database's product name ("Oracle AI Database",
# "26ai") and a channel's own name. `match` is broad on purpose: it must catch
# "Select AI", "Agent Studio", "RAG", "LangChain", "MCP", "vector search" etc. but
# not plain OIC / database / ERP videos.
TITLE_FILTERS = {
    "oracle_ai": {
        "strip": re.compile(r"oracle\s+ai\s+database|ai\s+database|\b\d{2}\s?ai\b|ai\s+dba\s+hub", re.I),
        "match": re.compile(
            r"\bai\b|\bagent|agentic|generative|\bgen\s?ai\b|\bgenai\b|\bllms?\b|"
            r"\brag\b|retrieval|vector|embedding|langchain|langgraph|llamaindex|\bmcp\b|"
            r"cohere|llama|openai|gpt|machine learning|\bnl2sql\b|natural language|chatbot|"
            r"copilot|\bocr\b|\bsemantic\b|prompt", re.I),
    },
}


def title_passes(slug, title):
    """Whether a title is allowed in a section (always True for sections with no filter)."""
    name = SECTION_TITLE_FILTER.get(slug)
    if name is None:
        return True
    f = TITLE_FILTERS[name]
    return bool(f["match"].search(f["strip"].sub(" ", title or "")))


SECTIONS = _load_sections()
SECTION_SLUGS = [s["slug"] for s in SECTIONS]
# Per-section window overrides (days); none today - every section uses fetch.py's FETCH_DAYS.
SECTION_WINDOW_DAYS = {s["slug"]: s["window_days"] for s in SECTIONS if "window_days" in s}
SECTION_TITLE_FILTER = {s["slug"]: s["title_filter"] for s in SECTIONS if "title_filter" in s}
_SLUG_BY_TRACK = {s["track"]: s["slug"] for s in SECTIONS}


def _load():
    youtube = {slug: [] for slug in SECTION_SLUGS}
    written = {slug: [] for slug in SECTION_SLUGS}
    with SOURCES_FILE.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            slug = _SLUG_BY_TRACK.get(row["track"])
            if slug is None:
                raise ValueError(
                    f"{SOURCES_FILE.name}: {row['name']!r} has unknown track "
                    f"{row['track']!r} - add it to SECTIONS in channels.py")
            if row["type"] == "youtube":
                youtube[slug].append({
                    "id":         row["channel_id"],
                    "name":       row["name"],
                    "handle":     row["handle"],
                    "niche":      row["niche"],
                    "layer":      row["layer"],
                    "language":   row["language"] or "en",
                    "status":     row["status"],
                })
            elif row["type"] == "written":
                written[slug].append({
                    "name":   row["name"],
                    "site":   row["site"],
                    "feed":   row["feed_url"] or None,   # None = page watch, no RSS/Atom feed
                    "layer":  row["layer"],
                    "status": row["status"],
                })
            else:
                raise ValueError(f"{SOURCES_FILE.name}: unknown type {row['type']!r}")
    return youtube, written


YOUTUBE_BY_SECTION, WRITTEN_BY_SECTION = _load()
