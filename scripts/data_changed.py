"""
Decides whether a refresh produced a change worth committing.

Every run rewrites a few volatile fields (the `last_updated` / `last_run` timestamps and the rotating
`section_offset`), so a plain `git diff` is never empty and every run would commit - and every commit
triggers a GitHub Pages deployment. This script ignores that noise.

    python scripts/data_changed.py      # exit 0: commit;  exit 10 (SKIP): only noise, skip the commit
                                        # any other exit code (a crash) must be treated as "commit"

It compares the working tree with HEAD (the commit the run started from) and counts as noise only:
  - data/videos.json, data/posts.json : the `last_updated` timestamp
  - data/periodic_state.json          : `last_run`, `section_offset`, `quota_exhausted`
  - data/video_id_cache.json          : a change that only REMOVES old IDs (the daily purge)
Anything else counts - a changed view count, a new video, new channel metadata, a changed scan time
(`last_scan`, which must be saved or the next run re-scans), a rebuilt page. If anything looks odd the answer is
"commit": a needless commit is harmless, a skipped real change is not.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKIP = 10      # deliberately not 1: a crashed Python script exits 1, and a crash must never mean "skip"

NOISE_KEYS = {
    "data/videos.json":         {"last_updated"},
    "data/posts.json":          {"last_updated"},
    "data/periodic_state.json": {"last_run", "section_offset", "quota_exhausted"},
}
CACHE_FILE = "data/video_id_cache.json"


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def changed_paths():
    """Every modified, added, deleted or untracked path in the working tree."""
    out = git("status", "--porcelain", "--untracked-files=all")
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    paths = []
    for line in out.stdout.splitlines():
        path = line[3:]
        if " -> " in path:                       # rename: take the new name
            path = path.split(" -> ")[1]
        paths.append(path.strip().strip('"'))
    return paths


def head_json(rel):
    out = git("show", f"HEAD:{rel}")
    return json.loads(out.stdout) if out.returncode == 0 else None


def current_json(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def without(doc, keys):
    return {k: v for k, v in doc.items() if k not in keys} if isinstance(doc, dict) else doc


def only_shrank(old, new):
    """True if `new` is `old` with some entries removed and nothing added or altered."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return False
    for cid, ids in new.items():
        old_ids = old.get(cid)
        if old_ids is None or not isinstance(ids, dict):
            return False
        if any(old_ids.get(vid) != ts for vid, ts in ids.items()):
            return False
    return True


def is_noise(rel):
    """True if this changed path is only volatile fields / purge; False if it is a real change."""
    if rel in NOISE_KEYS:
        old = head_json(rel)
        if old is None:
            return False                          # new file
        return without(old, NOISE_KEYS[rel]) == without(current_json(rel), NOISE_KEYS[rel])
    if rel == CACHE_FILE:
        old = head_json(rel)
        return old is not None and only_shrank(old, current_json(rel))
    return False


def main():
    try:
        real = [p for p in changed_paths() if not is_noise(p)]
    except Exception as e:                        # fail safe: when unsure, commit
        print(f"[data_changed] could not decide ({e}); committing to be safe")
        return 0
    if real:
        print("[data_changed] real changes: " + ", ".join(real[:8]) + (" ..." if len(real) > 8 else ""))
        return 0
    print("[data_changed] only timestamps / cache clean-up changed - nothing worth committing")
    return SKIP


if __name__ == "__main__":
    sys.exit(main())
