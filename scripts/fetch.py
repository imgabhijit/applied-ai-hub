"""
Fetches YouTube videos for all channels and saves to data/videos.json.

Channel metadata (playlist IDs + subscribers) is cached in data/channels_meta.json
and only refreshed when older than META_STALE_DAYS. Written feeds (RSS/Atom) are
handled separately by scripts/fetch_written.py.

Quota budget (the YouTube Data API gives 10,000 units/day):
  - 1 unit per channel     -> playlistItems.list, one page in the steady state
  - 1 unit per 50 video IDs -> videos.list, batched across the whole section

  Applied-AI channels upload far less often than news channels, so the ranking
  window is FETCH_DAYS (90) days rather than 24h; the pages let readers narrow it
  to 1 day / 3 days / 7 days / 30 days. Video details (including
  view_count) are re-fetched for every cached video still inside that window on
  every run, so videos are always ranked against each other on current view
  counts. Only videos that have aged out of the window stop being refreshed.

  A run scans a channel when it is overdue (see SECTION_CADENCE_HOURS) rather
  than on a fixed clock window, so a run that dies on quota leaves it overdue
  for the next one instead of skipping it for a whole cycle.

  Playlist scans run on a thread pool: the same API calls and the same quota,
  but the run is latency-bound, so it finishes several times faster.
"""

import os
import re
import json
import datetime
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from channels import SECTION_SLUGS, YOUTUBE_BY_SECTION, SECTION_WINDOW_DAYS, title_passes

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

DATA_DIR              = Path(__file__).parent.parent / "data"
META_FILE             = DATA_DIR / "channels_meta.json"
VIDEOS_FILE           = DATA_DIR / "videos.json"
CACHE_FILE            = DATA_DIR / "video_id_cache.json"
STATE_FILE            = DATA_DIR / "periodic_state.json"
FETCH_DAYS            = 90    # ranking window for every section; SECTION_WINDOW_DAYS can override one
MIN_DURATION          = 1     # seconds; only drops zero-length items (upcoming premieres). True Shorts are kept - the pages split by length
META_STALE_DAYS       = 7
# View counts are refreshed for every video still inside its section's window
# (see window_seconds()), so videos are never ranked against each other on stale
# counts. Quota cost: ~1 unit per 50 videos in the window, cheap next to the
# 10,000/day budget.


def window_days(section):
    return SECTION_WINDOW_DAYS.get(section, FETCH_DAYS)


def window_seconds(section):
    return window_days(section) * 86400


def passes_filter(section, title):
    """Sections with a title filter keep only the videos whose title matches it."""
    return title_passes(section, title)


# Each section is visited on its own cadence (see SECTION_CADENCE_HOURS). The
# order is rotated between runs so a quota shortfall never starves the same
# sections day after day.
SECTIONS = [(slug, YOUTUBE_BY_SECTION[slug]) for slug in SECTION_SLUGS]
SECTION_OF_CHANNEL = {ch["id"]: slug for slug, chans in SECTIONS for ch in chans}

# Set once the API reports the daily quota is gone. Every later call is skipped
# so the run finishes quickly and carries existing data forward untouched.
QUOTA_EXCEEDED = False


def note_api_error(where, error):
    """Record an API failure; flag daily-quota exhaustion so the run bails out."""
    global QUOTA_EXCEEDED
    text = str(error)
    if "quotaExceeded" in text or "dailyLimitExceeded" in text:
        if not QUOTA_EXCEEDED:
            print(f"[quota] Daily API quota exhausted during {where} - "
                  f"skipping all further API calls and keeping existing data")
        QUOTA_EXCEEDED = True
    else:
        print(f"[{where}] API error: {error}")


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(state):
    DATA_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def get_youtube():
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY not set. Add it to .env or GitHub Secrets.")
    return build("youtube", "v3", developerKey=key, cache_discovery=False)


_thread_local = threading.local()


def thread_youtube():
    """A client for the calling thread.

    googleapiclient's resource objects are not thread-safe, so each worker
    thread builds and reuses its own.
    """
    client = getattr(_thread_local, "youtube", None)
    if client is None:
        client = _thread_local.youtube = get_youtube()
    return client


def load_meta():
    if META_FILE.exists():
        try:
            return json.loads(META_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def is_stale(meta):
    ts = meta.get("last_updated")
    if not ts:
        return True
    age = now_utc() - datetime.datetime.fromisoformat(ts)
    return age.days >= META_STALE_DAYS


def load_video_cache():
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# The video ID cache stores {video_id: timestamp}. A NEGATIVE timestamp marks a
# video that was fetched and then deliberately left out of videos.json (a short
# below MIN_DURATION), so it is never worth spending quota on again. A positive
# timestamp with no matching record in videos.json means the record was lost and
# has to be re-fetched.
def cache_ts(value):
    return abs(int(value))


def cache_kept(value):
    return int(value) > 0


def purge_video_cache(cache):
    now_ts = int(now_utc().timestamp())
    purged = 0
    for cid in list(cache.keys()):
        # Each channel ages out with its own section's window.
        cutoff = now_ts - window_seconds(SECTION_OF_CHANNEL.get(cid, ""))
        before = len(cache[cid])
        cache[cid] = {vid: ts for vid, ts in cache[cid].items() if cache_ts(ts) >= cutoff}
        purged += before - len(cache[cid])
        if not cache[cid]:
            del cache[cid]
    if purged:
        print(f"[cache] Purged {purged} video IDs older than their section window")
    return cache


def save_video_cache(cache):
    DATA_DIR.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    total = sum(len(v) for v in cache.values())
    print(f"[cache] Saved {total} video IDs across {len(cache)} channels")


def configured_channels():
    """Return every configured channel, keyed by its YouTube channel ID."""
    all_channels = {}
    for _, channels in SECTIONS:
        for ch in channels:
            all_channels[ch["id"]] = ch["name"]
    return all_channels


def missing_metadata_channels(meta):
    """Configured IDs which cannot yet be fetched from cached metadata."""
    cached_channels = meta.get("channels", {})
    unresolved = set(meta.get("unresolved_channel_ids", []))
    return [
        channel_id for channel_id in configured_channels()
        if (not cached_channels.get(channel_id, {}).get("playlist_id") and
            channel_id not in unresolved)
    ]


def refresh_meta(youtube, meta):
    """Resolve uploads-playlist IDs and subscriber counts for every channel.

    Results are merged into the existing metadata instead of replacing it, so a
    partial failure (quota, transient 5xx) can never wipe metadata that is still
    good and leave every channel unfetchable on the runs that follow.
    """
    print("[meta] Refreshing channel metadata (playlist IDs + subscribers)...")
    all_channels = configured_channels()

    ids = list(all_channels.keys())
    channel_data = {}
    refresh_failed = False

    for i in range(0, len(ids), 50):
        if QUOTA_EXCEEDED:
            refresh_failed = True
            break
        chunk = ids[i:i + 50]
        try:
            res = youtube.channels().list(
                part="contentDetails,statistics,snippet",
                id=",".join(chunk)
            ).execute()
            for item in res.get("items", []):
                cid = item["id"]
                channel_data[cid] = {
                    "name":        item["snippet"]["title"],
                    "playlist_id": item["contentDetails"]["relatedPlaylists"]["uploads"],
                    "subscribers": int(item["statistics"].get("subscriberCount", 0)),
                }
        except HttpError as e:
            note_api_error("meta", e)
            refresh_failed = True

    merged = dict(meta.get("channels", {}))
    merged.update(channel_data)
    meta["channels"] = merged

    # Do not spend quota refreshing on every run for a deleted or invalid channel
    # ID.  New IDs are still missing and trigger an immediate refresh; unresolved
    # IDs are retried with the normal weekly metadata refresh.
    if not refresh_failed:
        meta["unresolved_channel_ids"] = sorted(set(all_channels) - set(channel_data))
        meta["last_updated"] = now_utc().isoformat()
        print(f"[meta] Saved metadata for {len(channel_data)} channels")
    else:
        # Leave last_updated alone so the next run retries instead of treating
        # this incomplete refresh as a fresh one.
        print(f"[meta] Partial refresh: resolved {len(channel_data)}/{len(ids)} "
              f"channels, will retry next run")

    DATA_DIR.mkdir(exist_ok=True)
    META_FILE.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def duration_to_seconds(iso):
    if not iso:
        return 0
    m = re.match(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def fetch_playlist_videos(youtube, playlist_id, days, known_ids=None):
    """Fetch new video IDs from a channel's uploads playlist.

    The uploads playlist covers everything a channel published - regular
    uploads, live streams (the /streams tab) and podcast episodes - so one scan
    per channel is enough; there is no separate endpoint to call for lives.

    Playlist entries are usually newest-first, but active/scheduled live streams
    are not reliably ordered by their video publication time.  So neither a
    cached ID nor an out-of-window date is a safe boundary mid-page: a newer
    upload can sit further down the same page.  Scan the whole page, then stop,
    so a normal refresh still needs only one playlist request per channel.
    """
    cutoff = (now_utc() - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    video_ids, next_token = [], None
    while True:
        if QUOTA_EXCEEDED:
            break
        try:
            res = youtube.playlistItems().list(
                part="contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_token,
            ).execute()
        except HttpError as e:
            note_api_error("fetch", e)
            break

        stop_after_page = False
        for item in res.get("items", []):
            pub = item.get("contentDetails", {}).get("videoPublishedAt", "")
            vid = item["contentDetails"]["videoId"]

            if known_ids and vid in known_ids:
                # Already known: everything below is old cache territory, but
                # finish this page in case a live stream reordered it.
                stop_after_page = True
            elif not pub:
                # An empty publication time can be an active live stream.
                video_ids.append(vid)
            elif pub >= cutoff:
                video_ids.append(vid)
            else:
                stop_after_page = True

        if stop_after_page:
            return video_ids

        next_token = res.get("nextPageToken")
        if not next_token:
            break
    return video_ids


def fetch_video_details(youtube, video_ids):
    """videos.list over any number of IDs, batched 50 at a time (1 unit each)."""
    details = []
    for i in range(0, len(video_ids), 50):
        if QUOTA_EXCEEDED:
            break
        chunk = video_ids[i:i + 50]
        try:
            res = youtube.videos().list(
                part="snippet,statistics,contentDetails",
                id=",".join(chunk)
            ).execute()
            details.extend(res.get("items", []))
        except HttpError as e:
            note_api_error("fetch", e)
    return details


# --- scan cadence --------------------------------------------------------
# How often each section's playlists are scanned, in elapsed hours since the
# channel's last scan (not tied to a fixed run interval). The workflow ticks four
# times a day (docs/refresh-schedule.md) because GitHub's scheduler drops some
# ticks; a channel is scanned by whichever tick first finds it overdue, so the
# extra ticks only matter when an earlier one was dropped. These channels upload a
# few times a week, so a scan roughly twice a day is plenty. 11h rather than 12 so
# a tick arriving a little early still counts as due.
DEFAULT_CADENCE_HOURS = 11
SECTION_CADENCE_HOURS = {slug: DEFAULT_CADENCE_HOURS for slug in SECTION_SLUGS}

# Scheduled runs can themselves arrive a little early or late (GitHub Actions
# scheduler delay, queueing). A short grace window means a run a few
# minutes early still counts as covering its slot, instead of being judged
# "not due" and pushing the section to the next checkpoint.
SCAN_GRACE   = 15 * 60
SCAN_WORKERS = 8      # parallel playlist scans; quota is unaffected


def is_due(cid, last_scan, now_ts, cadence_hours):
    """Whether this channel's playlist is overdue for a scan.

    Asking "is it overdue?" rather than "is it this run's turn?" means a run
    that dies on quota leaves the channel overdue, so the next run picks it up.
    Nothing can be silently skipped for a whole cycle, and a channel that has
    never been scanned - a newly added one - is due immediately.
    """
    return now_ts - last_scan.get(cid, 0) >= cadence_hours * 3600 - SCAN_GRACE


def needs_stats_refresh(vid, cached_value, existing_by_id, now_ts, window):
    """Whether a cached video is worth spending quota on again this run."""
    if now_ts - cache_ts(cached_value) <= window:
        return True
    if not cache_kept(cached_value):
        return False  # a short we already looked at and deliberately dropped
    if vid not in existing_by_id:
        # Cached, but its record is not in videos.json - it was lost, most often
        # because an earlier run ran out of quota before it could be stored.
        # Without this the video stays invisible until it ages out of the cache.
        return True
    # A stream that is on air (or about to be) has to be re-checked so it can
    # flip to a finished video with a real duration and a final view count.
    return existing_by_id[vid].get("live_broadcast") in ("live", "upcoming")


def fetch_section(youtube, section, channels, meta_channels, video_cache,
                  existing_by_id, last_scan):
    """Fetch one section in two passes: parallel playlist scans of the channels
    that are due, then a single batched videos.list over every ID needed."""
    now_ts       = int(now_utc().timestamp())
    ids_to_get   = []   # ordered, de-duplicated
    id_owner     = {}   # video_id -> configured channel id
    channel_info = {}   # channel id -> (display name, subscribers)
    channel_cfg  = {}   # channel id -> its entry in channels.py (layer, language, niche)
    new_counts, cached_counts = {}, {}

    cadence      = SECTION_CADENCE_HOURS[section]
    due, skipped = [], 0
    for ch in channels:
        cid         = ch["id"]
        ch_meta     = meta_channels.get(cid, {})
        playlist_id = ch_meta.get("playlist_id")
        ch_name     = ch_meta.get("name") or ch["name"]  # prefer API name over placeholder
        channel_info[cid] = (ch_name, ch_meta.get("subscribers", 0))
        channel_cfg[cid]  = ch

        if not playlist_id:
            print(f"  {ch['name']}: no playlist ID in meta, skipping")
            continue
        if not is_due(cid, last_scan, now_ts, cadence):
            # Not overdue. Its videos still carry forward from videos.json.
            skipped += 1
            continue
        due.append((cid, playlist_id))

    # Scan the due playlists in parallel. Same number of API calls and the same
    # quota as before - the run is latency-bound, not rate-limited, so this only
    # removes waiting.
    def scan(entry):
        cid, playlist_id = entry
        known_ids = set(video_cache.get(cid, {}).keys())
        return cid, fetch_playlist_videos(
            thread_youtube(), playlist_id, window_days(section), known_ids)

    scanned = []
    if due and not QUOTA_EXCEEDED:
        with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
            scanned = list(pool.map(scan, due))

    for cid, new_ids in scanned:
        known = video_cache.get(cid, {})
        stale_ids = [vid for vid, ts in known.items()
                     if needs_stats_refresh(vid, ts, existing_by_id, now_ts,
                                           window_seconds(section))]

        new_counts[cid]    = len(new_ids)
        cached_counts[cid] = len(known)
        # Stamp the scan only once it has actually happened, so a quota failure
        # leaves the channel overdue rather than marking it done.
        if not QUOTA_EXCEEDED:
            last_scan[cid] = now_ts

        for vid in new_ids + stale_ids:
            if vid not in id_owner:
                id_owner[vid] = cid
                ids_to_get.append(vid)

    details = fetch_video_details(youtube, ids_to_get)

    videos      = []
    per_channel = {}
    for vd in details:
        cid = id_owner.get(vd["id"], vd["snippet"].get("channelId", ""))
        cfg = channel_cfg.get(cid, {})
        ch_name, subscribers = channel_info.get(
            cid, (vd["snippet"].get("channelTitle", ""), 0))

        dur  = duration_to_seconds(vd.get("contentDetails", {}).get("duration", ""))
        live = vd["snippet"].get("liveBroadcastContent", "none")

        pub = vd["snippet"].get("publishedAt", "")
        try:
            if pub:
                dt = datetime.datetime.strptime(pub, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=datetime.timezone.utc
                )
                timestamp = int(dt.timestamp())
            else:
                # Active live stream - publishedAt is empty; use current time
                timestamp = now_ts
        except Exception:
            timestamp = now_ts

        # Cache ALL video IDs (including shorts and filtered-out titles) so early-stop
        # works correctly. Dropped videos are stored with a negative timestamp so later runs know they
        # were already looked at and dropped on purpose, not lost.
        kept = (not (dur < MIN_DURATION and live != "live")
                and passes_filter(section, vd["snippet"].get("title", "")))
        video_cache.setdefault(cid, {})[vd["id"]] = timestamp if kept else -timestamp

        if not kept:
            continue

        stats = vd.get("statistics", {})
        thumb = (
            vd["snippet"].get("thumbnails", {})
            .get("high", {})
            .get("url", f"https://i.ytimg.com/vi/{vd['id']}/mqdefault.jpg")
        )

        videos.append({
            "video_id":       vd["id"],
            "title":          vd["snippet"].get("title", ""),
            "channel_id":     cid,
            "channel_name":   ch_name,
            "channel_type":   section,
            "view_count":     int(stats.get("viewCount", 0)),
            "subscribers":    subscribers,
            "layer":          cfg.get("layer", ""),
            "language":       cfg.get("language", "en"),
            "niche":          cfg.get("niche", ""),
            "timestamp":      timestamp,
            "duration":       dur,
            "thumbnail":      thumb,
            "live_broadcast": live,
        })
        per_channel[cid] = per_channel.get(cid, 0) + 1

    for ch in channels:
        cid = ch["id"]
        if cid in new_counts:
            print(f"  {channel_info[cid][0]}: {per_channel.get(cid, 0)} videos "
                  f"({new_counts[cid]} new, {cached_counts[cid]} cached)")

    print(f"[fetch] {section}: scanned {len(due)} of {len(channels)} channels "
          f"every {cadence}h ({skipped} not due yet), "
          f"refreshed {len(ids_to_get)} video IDs "
          f"(~{-(-len(ids_to_get) // 50)} videos.list units)")
    return videos


def main():
    youtube = get_youtube()
    meta    = load_meta()
    missing_metadata = missing_metadata_channels(meta)

    if is_stale(meta) or missing_metadata:
        if missing_metadata:
            print(f"[meta] Refreshing because {len(missing_metadata)} configured "
                  f"channel(s) are missing metadata")
        meta = refresh_meta(youtube, meta)
    else:
        print(f"[meta] Using cached metadata (updated {meta.get('last_updated', '?')})")

    meta_channels = meta.get("channels", {})

    # Load video ID cache and purge entries older than the ranking window
    video_cache = load_video_cache()
    video_cache = purge_video_cache(video_cache)

    existing = {}
    if VIDEOS_FILE.exists():
        try:
            existing = json.loads(VIDEOS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    now_ts = int(now_utc().timestamp())

    def keep(video, section):
        """Inside the section's rolling window and its title filter, or still on air."""
        in_window = (video.get("timestamp", 0) >= now_ts - window_seconds(section) or
                     video.get("live_broadcast") == "live")
        return in_window and passes_filter(section, video.get("title", ""))

    output         = {"last_updated": now_utc().isoformat()}
    existing_by_id = {}
    for section, _ in SECTIONS:
        # Videos of channels removed from the CSV drop out on the next run.
        output[section] = [v for v in existing.get(section, [])
                           if keep(v, section) and SECTION_OF_CHANNEL.get(v.get("channel_id")) == section]
        for v in output[section]:
            existing_by_id[v["video_id"]] = v

    def update_section(key, new_videos):
        fresh = [v for v in new_videos if keep(v, key)]
        if fresh:
            merged = {v["video_id"]: v for v in output.get(key, [])}
            for v in fresh:
                merged[v["video_id"]] = v
            output[key] = list(merged.values())
            print(f"[fetch] {key}: updated with {len(fresh)} videos "
                  f"(total {len(output[key])})")
        else:
            print(f"[fetch] {key}: no new videos fetched, keeping "
                  f"{len(output.get(key, []))} existing videos")

    # Rotate which section goes first so an exhausted quota cannot starve the
    # same sections on every run.
    state     = load_state()
    offset    = int(state.get("section_offset", 0)) % len(SECTIONS)
    order     = SECTIONS[offset:] + SECTIONS[:offset]
    last_scan = {cid: int(ts) for cid, ts in state.get("last_scan", {}).items()}

    by_cadence = {}
    for _s, _h in SECTION_CADENCE_HOURS.items():
        by_cadence.setdefault(_h, []).append(_s)
    print("[cadence] " + "  |  ".join(
        f"every {hours}h: {', '.join(sections)}"
        for hours, sections in sorted(by_cadence.items())))

    for section, channels in order:
        if QUOTA_EXCEEDED:
            print(f"\n[fetch] === {section.upper()} - skipped, quota exhausted ===")
            continue
        print(f"\n[fetch] === {section.upper()} ({len(channels)} channels) ===")
        update_section(section, fetch_section(
            youtube, section, channels, meta_channels, video_cache,
            existing_by_id, last_scan))

    # Drop channels that are no longer configured so the file cannot grow forever.
    configured = set(configured_channels())
    last_scan  = {cid: ts for cid, ts in last_scan.items() if cid in configured}

    save_state({
        "section_offset":  (offset + 1) % len(SECTIONS),
        "last_run":        now_utc().isoformat(),
        "quota_exhausted": QUOTA_EXCEEDED,
        "last_scan":       last_scan,
    })

    DATA_DIR.mkdir(exist_ok=True)
    VIDEOS_FILE.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")

    save_video_cache(video_cache)

    print("\n[done] videos per section:")
    for section, _ in SECTIONS:
        print(f"  {section:22} {len(output[section])}")
    total = sum(len(output[s]) for s, _ in SECTIONS)
    print(f"[done] {total} videos saved to {VIDEOS_FILE}"
          + (" (INCOMPLETE - daily quota exhausted)" if QUOTA_EXCEEDED else ""))


if __name__ == "__main__":
    main()
