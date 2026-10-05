"""
Source registry for Applied AI Hub.

data/portal_sources.csv is the single source of truth for every channel and
written feed. This module only groups it into sections - one section per
`track` value in the CSV - and holds the display metadata for each section.

To add or remove a source, edit the CSV and run `python scripts/build_pages.py`
(the build regenerates every page).
"""

import csv
import re
from pathlib import Path

SOURCES_FILE = Path(__file__).parent.parent / "data" / "portal_sources.csv"

# One entry per `track` in the CSV. Order here is the order of the dropdown
# switcher (Home first, then these). `slug` is the page name (<slug>.html) and the
# key used in data/videos.json and data/posts.json.
SECTIONS = [
    {"slug": "oracle",      "track": "Oracle AI",               "title": "Oracle AI Hub",
     "icon": "🔴", "color": "#c74634",
     "blurb": "OCI Generative AI, Oracle AI Agent Studio, Oracle Integration (OIC) and Fusion AI",
     # Oracle channels mostly post non-AI topics, so only videos whose title is about AI
     # are kept (see TITLE_FILTERS below).
     "title_filter": "oracle_ai"},
    {"slug": "news",        "track": "News & Research",         "title": "News & Research",
     "icon": "📰", "color": "#e63946",
     "blurb": "Lab announcements, model releases, research explainers and talks"},
    {"slug": "agents",      "track": "Agents & Automation",     "title": "Agents & Automation",
     "icon": "🤖", "color": "#3a86ff",
     "blurb": "n8n, Make, Zapier, voice agents and no-code agent builds"},
    {"slug": "coding",      "track": "Agentic Coding",          "title": "Agentic Coding",
     "icon": "💻", "color": "#2dc653",
     "blurb": "Claude Code, Cursor, Codex and AI-assisted software engineering"},
    {"slug": "engineering", "track": "AI Engineering",          "title": "AI Engineering",
     "icon": "🛠️", "color": "#9b59b6",
     "blurb": "LLM apps, RAG, evals, frameworks and ML fundamentals"},
    {"slug": "enterprise",  "track": "Enterprise AI",           "title": "Enterprise AI",
     "icon": "🏢", "color": "#e67e22",
     "blurb": "Copilot, Agentforce, Power Automate and agentic RPA"},
    {"slug": "productivity", "track": "Productivity",           "title": "AI for Professionals",
     "icon": "⚡", "color": "#f5c518",
     "blurb": "Everyday AI workflows for office work, finance and note-taking"},
    {"slug": "business",    "track": "Business & Startups",     "title": "Business & Startups",
     "icon": "🚀", "color": "#16a085",
     "blurb": "AI agencies, SaaS ideas and building a business on AI"},
    {"slug": "video",       "track": "Video & Content",         "title": "Video & Content",
     "icon": "🎬", "color": "#ff6b9d",
     "blurb": "AI video, filmmaking and content generation tools"},
    {"slug": "selfhost",    "track": "Self-hosting & Local AI", "title": "Self-hosting & Local AI",
     "icon": "🖥️", "color": "#00b4d8",
     "blurb": "Local LLMs, homelabs and privacy-first setups"},
    {"slug": "marketing",   "track": "Marketing & Growth",      "title": "Marketing & Growth",
     "icon": "📣", "color": "#8e7dff",
     "blurb": "AI in CRM, ads and marketing platforms"},
]

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
