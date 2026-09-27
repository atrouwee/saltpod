#!/usr/bin/env python3
"""Index owned audio files on disk so the matcher can skip buying them again.

The Apple Music library is not the source of truth for what is owned -- 95% of
it is subscription rental. The files actually owned (Beatport, vinyl download
codes) sit in folders outside the library entirely. This walks those folders
and reads tags with ffprobe.

    python3 src/local_index.py ~/Documents/vinyl [more roots...]
    python3 src/local_index.py --stats
"""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INDEX = os.path.join(ROOT, "data", "local", "index.json")

# .movpkg is deliberately absent: it is a DRM'd HLS subscription download, not
# an owned file, and it will never play on an iPod Classic.
AUDIO_EXT = {".mp3", ".m4a", ".aiff", ".aif", ".flac", ".wav", ".alac", ".aac", ".ogg"}

# Formats the iPod Classic plays natively on stock firmware. FLAC and WAV need
# converting (afconvert to ALAC); WAV additionally carries no reliable tags,
# and tags are how the stock firmware navigates.
IPOD_NATIVE = {".mp3", ".m4a", ".aac", ".alac", ".aiff", ".aif", ".wav"}
NEEDS_CONVERT = {".flac", ".ogg"}


def probe(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", path],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return None
        fmt = json.loads(out.stdout).get("format", {})
    except Exception:  # noqa: BLE001 - a bad file should not stop the walk
        return None
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    try:
        dur = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    ext = os.path.splitext(path)[1].lower()
    return {
        "path": path,
        "ext": ext,
        "title": tags.get("title"),
        "artist": tags.get("artist"),
        "album": tags.get("album"),
        "album_artist": tags.get("album_artist") or tags.get("albumartist"),
        "duration_sec": round(dur, 2),
        "ipod_ready": ext in IPOD_NATIVE,
        "needs_convert": ext in NEEDS_CONVERT,
        "untagged": not (tags.get("title") and tags.get("artist")),
    }


def build(roots, workers=6):
    """ffprobe is IO-bound, so threads help a lot; 7k files serial takes an hour.

    Kept modest on purpose -- this machine has 18 GB and has fallen over before
    on wide parallel batches. ffprobe itself is light, the risk is the spawn
    storm, not the memory.
    """
    paths = []
    for root in roots:
        root = os.path.expanduser(root)
        for dirpath, _dirs, files in os.walk(root):
            for fn in sorted(files):
                # macOS writes a ._<name> AppleDouble stub beside every file on
                # FAT/exFAT volumes. They carry the same extension, and ffprobe
                # parses some of them successfully -- which quietly inflated this
                # index by ~760 phantom "tracks" before they were excluded.
                if fn.startswith('._'):
                    continue
                if os.path.splitext(fn)[1].lower() in AUDIO_EXT:
                    paths.append(os.path.join(dirpath, fn))
    print("probing %d files with %d workers..." % (len(paths), workers))
    entries, skipped, done = [], 0, 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for e in ex.map(probe, paths):
            done += 1
            if done % 250 == 0:
                print("  %d/%d" % (done, len(paths)), flush=True)
            if e is None:
                skipped += 1
                continue
            entries.append(e)
    os.makedirs(os.path.dirname(INDEX), exist_ok=True)
    with open(INDEX, "w") as f:
        json.dump({"roots": roots, "count": len(entries), "tracks": entries}, f, indent=1)
    return entries, skipped


def stats():
    with open(INDEX) as f:
        d = json.load(f)
    by_ext, untagged, convert = {}, 0, 0
    for t in d["tracks"]:
        by_ext[t["ext"]] = by_ext.get(t["ext"], 0) + 1
        untagged += bool(t["untagged"])
        convert += bool(t["needs_convert"])
    print("indexed %d files from %s" % (d["count"], ", ".join(d["roots"])))
    for e, n in sorted(by_ext.items(), key=lambda kv: -kv[1]):
        print("  %-6s %4d" % (e, n))
    print("untagged (invisible to stock iPod menus): %d" % untagged)
    print("needs conversion before the iPod plays it: %d" % convert)


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "--stats":
        stats()
        return 0
    entries, skipped = build(argv)
    print("")
    print("indexed %d files (%d unreadable)" % (len(entries), skipped))
    print("index: %s" % INDEX)
    stats()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
