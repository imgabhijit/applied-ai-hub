# 🧠 Applied AI Hub

A serverless Progressive Web App that ranks the most-watched new videos and lists the latest posts from **237 hand-picked applied-AI sources** (220 YouTube channels + 17 written sources) across a Home page and 11 sections: Oracle AI, AI engineering, automation, agentic coding, tools and news.

It runs on **GitHub Pages + GitHub Actions + the YouTube Data API v3** with no backend. Refreshes run on GitHub's own scheduler four times a day - see [docs/refresh-schedule.md](docs/refresh-schedule.md).

> Status: scaffold. The site and fetchers are in place and tested against stubbed data; the first live fetch needs a `YOUTUBE_API_KEY` (see below) and the GitHub Pages / cron setup has not been done yet.

---

## Sections

[index.html](index.html) is the **landing page**: a tile grid linking to every page, each tile showing how many new videos arrived this week. [all.html](all.html) is **All Videos**: it merges the videos and posts of every section, with a Section filter. The nav dropdown on every page switches between Home, All Videos and the sections. Each section is one `track` in [data/portal_sources.csv](data/portal_sources.csv):

| Page | Section | YouTube | Written |
|---|---|---:|---:|
| [oracle.html](oracle.html) | 🔴 Oracle AI Hub | 49 | 2 (links) |
| [news.html](news.html) | 📰 News & Research | 32 | 7 |
| [agents.html](agents.html) | 🤖 Agents & Automation | 27 | 1 |
| [coding.html](coding.html) | 💻 Agentic Coding | 23 | 1 |
| [engineering.html](engineering.html) | 🛠️ AI Engineering | 25 | 5 |
| [enterprise.html](enterprise.html) | 🏢 Enterprise AI | 12 | - |
| [productivity.html](productivity.html) | ⚡ AI for Professionals | 12 | - |
| [business.html](business.html) | 🚀 Business & Startups | 10 | - |
| [video.html](video.html) | 🎬 Video & Content | 12 | 1 |
| [selfhost.html](selfhost.html) | 🖥️ Self-hosting & Local AI | 13 | - |
| [marketing.html](marketing.html) | 📣 Marketing & Growth | 5 | - |

Every source also has a **layer**: *Primary* (official/first-party), *Analysis*, or *Practitioner*. Each page has a Layer filter, plus time window, sort (views / velocity / trending / newest), language, min views, duration and search. Sections with written sources get an **Articles** tab; sources with no usable RSS feed (Anthropic News, The Batch, and Oracle's blogs, which return 403 to scripts) appear as direct links.

## How it works

```
GitHub Actions `schedule` (4×/day) ──▶ refresh workflow
                      │
        ┌─────────────┴──────────────┐
        ▼                            ▼
scripts/fetch.py             scripts/fetch_written.py
(YouTube Data API v3)        (RSS / Atom, stdlib only)
        │                            │
        ▼                            ▼
data/videos.json             data/posts.json
        └─────────────┬──────────────┘
                      ▼
        git commit + push ──▶ GitHub Pages ──▶ static pages + service worker
```

- **Quota-cheap discovery**: `playlistItems.list` on each channel's uploads playlist (1 unit) instead of `search.list` (100 units); `videos.list` batched 50 at a time; channel metadata cached for 7 days. Roughly 220 + ~50 units per run.
- **90 days of videos are kept; every page defaults to 7 days.** The Time filter offers 1 day / 3 days / 7 days / 30 days / 90 days (news-hub keeps only 24h; these channels upload a few times a week). Shorts (< 60 s) are dropped.
- **Refreshed once or twice a day.** The workflow ticks four times a day because GitHub's scheduler drops some ticks; extra ticks are nearly free, since only overdue channels are scanned. Plenty for a non-news site.
- A failed run carries existing data forward instead of blanking a section.

## Project structure

```
applied-ai-hub/
├── .github/workflows/refresh.yml   # schedule (4x/day) + manual: fetch videos + feeds, commit data
├── assets/
│   ├── hub.css                     # shared styles (each page sets --accent)
│   └── hub.js                      # shared page logic: filters, tabs, player, rendering
├── data/
│   ├── portal_sources.csv          # SOURCE OF TRUTH for every channel and feed
│   ├── videos.json                 # generated: ranked videos per section
│   ├── posts.json                  # generated: recent written posts per section
│   ├── channels_meta.json          # generated: uploads-playlist IDs + subscriber counts
│   ├── video_id_cache.json         # generated: video-ID cache for the window
│   └── periodic_state.json         # generated: scan cadence state
├── docs/refresh-schedule.md
├── icons/                          # PWA icons (192, 512)
├── scripts/
│   ├── channels.py                 # reads the CSV, groups into sections
│   ├── fetch.py                    # YouTube fetcher / ranker
│   ├── fetch_written.py            # RSS/Atom fetcher
│   ├── build_pages.py              # generates index.html, all.html + the 11 section pages
│   └── create_icons.py             # PWA icon generator
├── index.html                      # generated landing page (tile grid of every page)
├── all.html                        # generated "All Videos" page (aggregates all sections)
├── <slug>.html                     # generated, one per section
├── player.html                     # standalone player (opened by the ↗ button)
├── manifest.json · sw.js           # PWA manifest and service worker
├── requirements.txt
├── CLAUDE.md                       # project rules for Claude Code
└── README.md
```

`data/*.json` are created by the first fetcher run; they are not in the repo yet.

## Local development

```bash
pip install -r requirements.txt
echo YOUTUBE_API_KEY=your_key_here > .env      # key from Google Cloud Console (YouTube Data API v3)

python scripts/fetch.py            # -> data/videos.json
python scripts/fetch_written.py    # -> data/posts.json (no key needed)
python -m http.server 8000         # open http://localhost:8000
```

### Changing sources or sections

Edit [data/portal_sources.csv](data/portal_sources.csv) (and `SECTIONS` in [scripts/channels.py](scripts/channels.py) for a new section), then:

```bash
python scripts/build_pages.py
```

The HTML pages are generated and committed; do not edit them by hand.

## Deployment

1. Push to GitHub as `imgabhijit/applied-ai-hub` and enable **Pages** (deploy from `main`, root).
2. Add the `YOUTUBE_API_KEY` repository secret.
3. Run the **Refresh Data** workflow once manually from the Actions tab; after that it runs by itself on the schedule in [docs/refresh-schedule.md](docs/refresh-schedule.md).

`manifest.json` and `sw.js` hardcode the `/applied-ai-hub/` base path; update both if the repo name differs.

## Notes on the source list

- **Oracle AI Hub is filtered to AI.** Only videos whose title is about AI are kept: Agent Studio, OCI Generative AI, Select AI, Fusion AI, RAG/vector/LangChain/MCP and similar. Plain OIC, database, APEX-without-AI and ERP videos are dropped. The product name "Oracle AI Database" / "26ai" alone does not count. The rule is `TITLE_FILTERS` in [scripts/channels.py](scripts/channels.py).
- *Andrej Karpathy* uploads rarely (last Feb 2025), and the two "Watch" channels (*AI at Meta*, *Yannic Kilcher*) have stale uploads, so they will often be empty in the 7-day window.
