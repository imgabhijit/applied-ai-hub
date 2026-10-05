# 🧠 Applied AI Hub

A serverless Progressive Web App that ranks the most-watched new videos and lists the latest posts from **222 hand-picked applied-AI sources** (205 YouTube channels + 17 written sources) across a Home page and 11 sections: Oracle AI, AI engineering, automation, agentic coding, tools and news.

It runs on **GitHub Pages + GitHub Actions + the YouTube Data API v3** with no backend. Refreshes run on GitHub's own scheduler four times a day - see [docs/refresh-schedule.md](docs/refresh-schedule.md).

> Status: scaffold. The site and fetchers are in place and tested against stubbed data; the first live fetch needs a `YOUTUBE_API_KEY` (see below) and the GitHub Pages / cron setup has not been done yet.

---

## Sections

[index.html](index.html) is the **landing page**: a tile grid linking to every page, each tile showing how many new videos arrived this week. [all.html](all.html) is **All Videos**: it merges the videos and posts of every section, with a Section filter. The nav dropdown on every page switches between Home, All Videos and the sections. Each section is one `track` in [data/portal_sources.csv](data/portal_sources.csv):

| Page | Section | YouTube | Written |
|---|---|---:|---:|
| [oracle.html](oracle.html) | 🔴 Oracle AI Hub | 49 | 2 (links) |
| [news.html](news.html) | 📰 News & Research | 31 | 7 |
| [agents.html](agents.html) | 🤖 Agents & Automation | 27 | 1 |
| [coding.html](coding.html) | 💻 Agentic Coding | 22 | 1 |
| [engineering.html](engineering.html) | 🛠️ AI Engineering | 24 | 5 |
| [enterprise.html](enterprise.html) | 🏢 Enterprise AI | 11 | - |
| [productivity.html](productivity.html) | ⚡ AI for Professionals | 11 | - |
| [business.html](business.html) | 🚀 Business & Startups | 8 | - |
| [video.html](video.html) | 🎬 Video & Content | 12 | 1 |
| [selfhost.html](selfhost.html) | 🖥️ Self-hosting & Local AI | 8 | - |
| [marketing.html](marketing.html) | 📣 Marketing & Growth | 2 | - |

Every page has these tabs: **🎬 Long videos** (3 minutes and over), **⚡ Shorts** (under 3 minutes, including true YouTube Shorts under 60 s), **📺 By Channel**, **🔥 Topics**, and **📝 Articles** where the section has written sources. Videos are sorted by **velocity** (views per hour since publishing) by default; other sorts are views, trending and newest. The Time filter offers 1 day to 90 days (7 days by default), and there are filters for layer, language, min views and search. Every source has a **layer**: *Primary* (official/first-party), *Analysis*, or *Practitioner*. Sections with written sources get an **Articles** tab; sources with no usable RSS feed (Anthropic News, The Batch, Oracle's blogs) appear as direct links.

## Shorts viewer (swipe up / down)

On the **⚡ Shorts** tab of every page, tapping a short opens a full-screen vertical viewer ([assets/shorts.js](assets/shorts.js)): **swipe up for the next short, swipe down for the previous one**. On desktop the same works by mouse drag, wheel, ArrowUp/ArrowDown (or K/J), with ▲ ▼ buttons; tap, click or Space plays and pauses; Esc, the ✕ button or the browser/phone Back button closes it. It walks through the tab's current list, so the Time, Sort, Layer, Language, Min views and Duration filters decide what you swipe through. The Long videos tab keeps the normal player.

Two details worth knowing: YouTube's player swallows touches, so a transparent layer over the video catches the swipes and play/pause is sent to the player with `postMessage`; and videos are swapped by replacing the iframe element, because changing its `src` adds browser-history entries and would make Back step through old videos.

## Topics tab (what's buzzing)

Every page has a **🔥 Topics** tab that reads the titles of the videos in the selected time window (1 day to 90 days) and ranks the phrases they are about, for example "Dots", "Meta Muse", "Sonnet 5.5". It runs in the browser from `data/videos.json`; there is nothing extra to fetch. How [assets/topics.js](assets/topics.js) does it:

1. **Clean** each title: drop emojis, URLs and the channel's own name; split `GPT-6` into `GPT 6`.
2. **Tokenize** into lowercase words, skipping stopwords and clickbait filler ("insane", "tutorial", "just dropped").
3. **Build 1-3 word phrases** that do not start or end with a filler word. Word order is ignored, so "Muse from Meta" and "Meta's Muse" are one phrase.
4. **Count per video and per channel.** A phrase needs 2+ different channels (3+ for single words, and for 30/90-day windows), so one channel's series cannot fake a trend.
5. **Drop ordinary words.** The code learns which words are plain English (never capitalised mid-sentence, e.g. "price", "understand") from the titles themselves, plus a built-in list.
6. **Rank.** *Rising* compares the phrase's rate in the window with its rate in the rest of the 90 days, so new buzz beats always-popular words; *Most mentioned* ranks by breadth then volume. For a 90-day window there is no "before" to compare with, so it falls back to mentions.
7. **Merge variants** ("OpenAI Dots", "ChatGPT Dots" -> "Dots") and show the most-viewed video for each topic. Clicking a topic opens the Videos tab narrowed to it.

It runs entirely in the browser from `data/videos.json`, so it refreshes automatically whenever the GitHub Action refreshes the data. There is no model, API key or package to install.

**Tuning without code.** Edit [data/topic_rules.json](data/topic_rules.json) on GitHub (pencil icon -> commit; the site picks it up on the next load):
- `ignore_words`: words that may never be a topic ("gave", "understand")
- `ignore_topics`: phrases to hide ("open source")
- `aliases`: merge phrases into one topic (`"grok bot": "GrokBot"`)

**Safety check.** After every refresh the workflow runs `node scripts/check_topics.js`, which computes topics for every section at 7 and 30 days and fails the run (red X in the Actions tab) if the Topics tab would break, throw, or come back empty from plenty of videos. It runs after the data commit, so it never blocks a data refresh.

Try it from the terminal: `node scripts/test_topics.js agents 7 rising` (section, days, rising|mentions).

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

- **Quota-cheap discovery**: `playlistItems.list` on each channel's uploads playlist (1 unit) instead of `search.list` (100 units); `videos.list` batched 50 at a time; channel metadata cached for 7 days. Roughly 205 + ~50 units per run.
- **90 days of videos are kept; every page defaults to 7 days.** The Time filter offers 1 day / 3 days / 7 days / 30 days / 90 days (news-hub keeps only 24h; these channels upload a few times a week). True YouTube Shorts (under 60 s) are fetched too; only zero-length items (upcoming premieres) are dropped.
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
│   ├── sections.json               # the sections (page name, title, icon, colour); edit to add a section
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
│   ├── test_topics.js              # prints top topics from the real data (Node)
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

### Changing sources or sections (no computer needed)

Everything is edited as data on GitHub; the **Refresh Data** workflow does the rest. It runs automatically when you commit one of these files, and also four times a day.

| To do this | Edit this file (pencil icon on GitHub, then commit) |
|---|---|
| Add / remove / move a channel or written source | [data/portal_sources.csv](data/portal_sources.csv) (`track` decides the section) |
| Add a new section (page) | [data/sections.json](data/sections.json): a new entry with `slug`, `track`, `title`, `icon`, `color`, `blurb`; then rows in the CSV using that `track` |
| Remove a section | delete its entry in `sections.json` and its CSV rows; its page is deleted automatically |
| Tune the Topics tab | [data/topic_rules.json](data/topic_rules.json) |

What the workflow does after your commit: rebuilds `index.html`, `all.html` and every section page from those files (`scripts/build_pages.py`, standard library only), fetches the new channels' videos, commits the result, and Pages publishes it. A typo in `sections.json` fails the run with a readable message and leaves the published site as it was. The generated HTML pages are never edited by hand.

To do the same locally: `python scripts/build_pages.py`.

## Deployment

1. Push to GitHub as `imgabhijit/applied-ai-hub` and enable **Pages** (deploy from `main`, root).
2. Add the `YOUTUBE_API_KEY` repository secret.
3. Run the **Refresh Data** workflow once manually from the Actions tab; after that it runs by itself on the schedule in [docs/refresh-schedule.md](docs/refresh-schedule.md).

`manifest.json` and `sw.js` hardcode the `/applied-ai-hub/` base path; update both if the repo name differs.

## Notes on the source list

- **Oracle AI Hub is filtered to AI.** Only videos whose title is about AI are kept: Agent Studio, OCI Generative AI, Select AI, Fusion AI, RAG/vector/LangChain/MCP and similar. Plain OIC, database, APEX-without-AI and ERP videos are dropped. The product name "Oracle AI Database" / "26ai" alone does not count. The rule is `TITLE_FILTERS` in [scripts/channels.py](scripts/channels.py).
- *Andrej Karpathy* uploads rarely (last Feb 2025), and the two "Watch" channels (*AI at Meta*, *Yannic Kilcher*) have stale uploads, so they will often be empty in the 7-day window.
