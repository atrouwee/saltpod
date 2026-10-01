#!/usr/bin/env python3
"""Index owned audio files on disk so the matcher can skip buying them again.

The Apple Music library is not the source of truth for what is owned -- 95% of
it is subscription rental. The files actually owned (Beatport, vinyl download
codes) sit in folders outside the library entirely. This walks those folders
and reads tags with ffprobe.

    saltpod index /Volumes/YourDrive/Music [more roots...]
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
            # -show_streams as well as -show_format: bitrate is the quality
            # number for a lossy file and says nothing about a lossless one,
            # where depth and sample rate are what discriminate. Both cost
            # the same single ffprobe call.
            # All streams, not just audio: a file's own cover art is a video
            # stream, and knowing it is there is what lets the page show the
            # artwork you already have instead of a grey square.
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return None
        parsed = json.loads(out.stdout)
        fmt = parsed.get("format", {})
        streams = parsed.get("streams") or []
        st = next((x for x in streams if x.get("codec_type") == "audio"), {})
        has_art = any(x.get("codec_type") == "video" for x in streams)
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
        # size is here so a bitrate can be worked out without a second pass:
        # the stored bitrate in an iTunesDB is not trustworthy, and arithmetic
        # on size and duration is
        "size": (os.path.getsize(path) if os.path.exists(path) else None),
        "codec": st.get("codec_name"),
        "sample_rate": (int(st["sample_rate"]) if str(st.get("sample_rate") or "").isdigit() else None),
        "bit_depth": (int(st.get("bits_per_raw_sample") or st.get("bits_per_sample") or 0) or None),
        "channels": st.get("channels"),
        "has_art": has_art,
        "ipod_ready": ext in IPOD_NATIVE,
        "needs_convert": ext in NEEDS_CONVERT,
        "untagged": not (tags.get("title") and tags.get("artist")),
    }


# ---------------------------------------------------------------- spotlight
#
# macOS HAS ALREADY READ THESE FILES. The index spawned ffprobe once per
# file -- 4,048 of them, about 130 seconds -- to learn things Spotlight
# indexed when the file landed on the drive. One `mdls` call over 600 real
# files came back in 0.32 s, which is 0.53 ms each against ffprobe's 32.
#
# It is a FAST PATH, NOT A REPLACEMENT, and the gaps are specific:
# Spotlight has no album_artist, no codec and no has_art for anything, and
# reads no tags at all out of a WAV because it does not look at LIST/INFO.
# So the tags come from our own readers -- the same ones that WRITE them,
# which is why the index and the editor now agree by construction instead
# of being two readings of one file -- and ffprobe is kept for the rest.

# SCALAR ATTRIBUTES ONLY, and that is load-bearing. `mdls` given many files
# prints their attribute blocks back to back with NO separator between
# them, so the only way to map a block to its file is to count lines -- and
# that only works while every attribute is exactly one line. A scalar is,
# including when it is `(null)`. An array is not: `kMDItemAuthors` spans
# three. Asking for it silently shifted every file's data onto the one
# before it, which is how the first version of this read one track's album
# off another's.
#
# No loss: the artist comes from our own tag reader, which is also the one
# that writes it.
_MD = {
    'kMDItemDurationSeconds': 'duration_sec',
    'kMDItemAudioSampleRate': 'sample_rate',
    'kMDItemAudioChannelCount': 'channels',
    'kMDItemBitsPerSample': 'bit_depth',
    'kMDItemFSSize': 'size',
    'kMDItemTitle': 'title',
    'kMDItemAlbum': 'album',
}


def _mdls_batch(paths):
    """{path: {field: value}} for as many as Spotlight knows about.

    mdls prints one block per file in the order given, separated by a line
    of dashes, so the blocks map back positionally.
    """
    if not paths:
        return {}
    args = ['mdls']
    for k in _MD:
        args += ['-name', k]
    try:
        out = subprocess.run(args + paths, capture_output=True, text=True,
                             timeout=120).stdout
    except Exception:
        return {}
    lines = [l for l in out.split('\n') if l.strip()]
    n = len(_MD)
    if len(lines) != n * len(paths):
        return {}            # the shape is not what we assumed: take none of it
    got = {}
    for i, path in enumerate(paths):
        rec = {}
        for line in lines[i * n:(i + 1) * n]:
            k, _, v = line.partition('=')
            k, v = k.strip(), v.strip()
            if k not in _MD or v == '(null)':
                continue
            field = _MD[k]
            v = v.strip('"')
            if field in ('sample_rate', 'channels', 'bit_depth', 'size'):
                try:
                    rec[field] = int(float(v))
                except ValueError:
                    pass
            elif field == 'duration_sec':
                try:
                    rec[field] = round(float(v), 2)
                except ValueError:
                    pass
            elif v:
                rec[field] = v
        got[path] = rec
    return got


def probe_fast(path, md):
    """An index entry from Spotlight plus our own tag reader, no subprocess.

    Returns None when Spotlight knows too little to be trusted -- then the
    caller falls back to ffprobe rather than writing a half-built record.
    """
    from . import tags as T
    if not md or not md.get('duration_sec'):
        return None
    ext = os.path.splitext(path)[1].lower()
    tg = {}
    if T.supported(path) or ext in ('.mp3', '.aiff', '.aif', '.wav'):
        try:
            tg = T.read(path) or {}
        except Exception:
            tg = {}
    title = tg.get('title') or md.get('title')
    artist = tg.get('artist') or md.get('artist')
    return {
        'path': path, 'ext': ext,
        'title': title, 'artist': artist,
        'album': tg.get('album') or md.get('album'),
        'album_artist': tg.get('album_artist'),
        'duration_sec': md.get('duration_sec'),
        'size': md.get('size') or (os.path.getsize(path) if os.path.exists(path) else None),
        # Spotlight does not report a codec and the container settles it for
        # everything this tool handles.
        'codec': _CODEC_BY_EXT.get(ext),
        'sample_rate': md.get('sample_rate'),
        'bit_depth': md.get('bit_depth'),
        'channels': md.get('channels'),
        # the one thing nothing cheap can answer; filled in by the art pass
        'has_art': None,
        'ipod_ready': ext in IPOD_NATIVE,
        'needs_convert': ext in NEEDS_CONVERT,
        'untagged': not (title and artist),
        'mtime': (os.path.getmtime(path) if os.path.exists(path) else None),
    }


_CODEC_BY_EXT = {'.mp3': 'mp3', '.m4a': 'aac', '.aac': 'aac', '.alac': 'alac',
                 '.flac': 'flac', '.ogg': 'vorbis'}


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
    entries, skipped, done = [], 0, 0

    # SPOTLIGHT IS OFF BY DEFAULT, and the reason is worth keeping.
    #
    # It looked right and it was 8x faster. Running both paths over the
    # same 300 files and diffing every field said otherwise: 103 of 300
    # lost their artist, 114 their codec, 21 their bit depth. Spotlight
    # has no album_artist, no codec and no has_art for anything, and reads
    # no tags at all from a WAV because it never looks at LIST/INFO -- and
    # our own readers only cover wav and mp3, so an AIFF or FLAC falls
    # through both.
    #
    # Keep it here, behind a flag, because the 60x is real for the fields
    # it does know and the remaining gap is a reader away. Do not make it
    # the default until the differential comes back clean.
    if os.environ.get('SALTPOD_SPOTLIGHT') != '1':
        print("probing %d files with ffprobe (%d workers)..." % (len(paths), workers), flush=True)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for e in ex.map(probe, paths):
                done += 1
                if done % 250 == 0:
                    print("  %d/%d" % (done, len(paths)), flush=True)
                if e is None:
                    skipped += 1
                    continue
                e['mtime'] = (os.path.getmtime(e['path'])
                              if os.path.exists(e['path']) else None)
                entries.append(e)
        os.makedirs(os.path.dirname(INDEX), exist_ok=True)
        with open(INDEX, "w") as f:
            json.dump({"roots": roots, "count": len(entries), "tracks": entries}, f, indent=1)
        return entries, skipped

    print("asking spotlight about %d files..." % len(paths), flush=True)
    md_all = {}
    for i in range(0, len(paths), 500):
        md_all.update(_mdls_batch(paths[i:i + 500]))
    fell_back = []
    for path in paths:
        e = probe_fast(path, md_all.get(path))
        if e is None:
            fell_back.append(path)
        else:
            entries.append(e)
    print("  spotlight answered %d, ffprobe needed for %d"
          % (len(entries), len(fell_back)), flush=True)

    if fell_back:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for e in ex.map(probe, fell_back):
                done += 1
                if done % 250 == 0:
                    print("  %d/%d" % (done, len(fell_back)), flush=True)
                if e is None:
                    skipped += 1
                    continue
                e['mtime'] = (os.path.getmtime(e['path'])
                              if os.path.exists(e['path']) else None)
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
