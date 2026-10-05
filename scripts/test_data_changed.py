"""
Tests for scripts/data_changed.py in a throwaway git repository:  python scripts/test_data_changed.py
The dangerous direction is skipping a real change, so most cases check that real changes are NOT treated as noise.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).parent / "data_changed.py"
failed = 0


def check(cond, name):
    global failed
    print(("PASS " if cond else "FAIL ") + name)
    failed += 0 if cond else 1


def make_repo():
    root = Path(tempfile.mkdtemp())
    (root / "scripts").mkdir()
    (root / "data").mkdir()
    shutil.copy(SCRIPT, root / "scripts" / "data_changed.py")
    w = lambda rel, obj: (root / rel).write_text(json.dumps(obj), encoding="utf-8")
    w("data/videos.json", {"last_updated": "T0", "news": [{"video_id": "a", "view_count": 10}]})
    w("data/posts.json", {"last_updated": "T0", "news": []})
    w("data/periodic_state.json", {"section_offset": 1, "last_run": "T0", "quota_exhausted": False, "last_scan": {"c1": 100}})
    w("data/video_id_cache.json", {"c1": {"a": 1, "b": 2, "old": 3}})
    w("data/channels_meta.json", {"last_updated": "T0", "channels": {"c1": {"subscribers": 5}}})
    (root / "index.html").write_text("<html>v1</html>")
    for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"]):
        subprocess.run(["git", *cmd], cwd=root, check=True)
    return root, w


def verdict(root):
    r = subprocess.run([sys.executable, "scripts/data_changed.py"], cwd=root, capture_output=True, text=True)
    return r.returncode          # 0 = commit, 10 = skip


def scenario(name, mutate, expect):
    root, w = make_repo()
    mutate(root, w)
    got = verdict(root)
    check(got == expect, f"{name}: {'commit' if got == 0 else 'skip'} (expected {'commit' if expect == 0 else 'skip'})")
    shutil.rmtree(root, ignore_errors=True)


COMMIT, SKIP = 0, 10
scenario("nothing changed at all", lambda r, w: None, SKIP)
scenario("only the timestamps changed", lambda r, w: (
    w("data/videos.json", {"last_updated": "T1", "news": [{"video_id": "a", "view_count": 10}]}),
    w("data/posts.json", {"last_updated": "T1", "news": []}),
    w("data/periodic_state.json", {"section_offset": 2, "last_run": "T1", "quota_exhausted": False, "last_scan": {"c1": 100}})), SKIP)
scenario("quota flag + offset only", lambda r, w: w("data/periodic_state.json", {"section_offset": 5, "last_run": "T9", "quota_exhausted": True, "last_scan": {"c1": 100}}), SKIP)
scenario("cache purge only (IDs removed)", lambda r, w: w("data/video_id_cache.json", {"c1": {"a": 1, "b": 2}}), SKIP)
scenario("whole channel purged from cache", lambda r, w: w("data/video_id_cache.json", {}), SKIP)
scenario("a view count changed", lambda r, w: w("data/videos.json", {"last_updated": "T1", "news": [{"video_id": "a", "view_count": 11}]}), COMMIT)
scenario("a new video appeared", lambda r, w: w("data/videos.json", {"last_updated": "T1", "news": [{"video_id": "a", "view_count": 10}, {"video_id": "b", "view_count": 1}]}), COMMIT)
scenario("a video disappeared", lambda r, w: w("data/videos.json", {"last_updated": "T1", "news": []}), COMMIT)
scenario("a new post appeared", lambda r, w: w("data/posts.json", {"last_updated": "T1", "news": [{"title": "x"}]}), COMMIT)
scenario("scan time advanced (must be saved)", lambda r, w: w("data/periodic_state.json", {"section_offset": 2, "last_run": "T1", "quota_exhausted": False, "last_scan": {"c1": 999}}), COMMIT)
scenario("new IDs added to the cache", lambda r, w: w("data/video_id_cache.json", {"c1": {"a": 1, "b": 2, "old": 3, "new": 4}}), COMMIT)
scenario("a cache timestamp altered", lambda r, w: w("data/video_id_cache.json", {"c1": {"a": 1, "b": 99}}), COMMIT)
scenario("a new channel in the cache", lambda r, w: w("data/video_id_cache.json", {"c1": {"a": 1}, "c2": {"z": 1}}), COMMIT)
scenario("channel metadata refreshed", lambda r, w: w("data/channels_meta.json", {"last_updated": "T1", "channels": {"c1": {"subscribers": 6}}}), COMMIT)
scenario("a page was rebuilt", lambda r, w: (r / "index.html").write_text("<html>v2</html>"), COMMIT)
scenario("a page was deleted", lambda r, w: (r / "index.html").unlink(), COMMIT)
scenario("a brand-new file", lambda r, w: (r / "data" / "new.json").write_text("{}"), COMMIT)
scenario("noise AND a real change together", lambda r, w: (
    w("data/posts.json", {"last_updated": "T1", "news": []}),
    w("data/videos.json", {"last_updated": "T1", "news": [{"video_id": "a", "view_count": 50}]})), COMMIT)
scenario("a data file is not valid JSON (fail safe)", lambda r, w: (r / "data" / "videos.json").write_text("{broken"), COMMIT)

print(f"\n{failed} failed" if failed else "\nAll data_changed tests passed")
sys.exit(1 if failed else 0)
