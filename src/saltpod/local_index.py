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
import plistlib
import unicodedata
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

# ONE `mdls -plist -` CALL, AND IT RETURNS A PLIST, so there is nothing to
# scrape. The previous version of this parsed mdls's human-readable output by
# counting lines, which forced it to request SCALAR ATTRIBUTES ONLY -- an
# array like `kMDItemAuthors` spans three lines and shifted every following
# file's data onto the one before it.
#
# THAT LIMITATION WAS SELF-INFLICTED AND IT WAS WRITTEN UP AS SPOTLIGHT'S.
# Having dropped the artist to work around its own parser, this file then
# recorded "Spotlight has no artist" as a finding, and the Spotlight path was
# shelved behind a flag on the strength of it. Re-run with -plist and the
# full attribute list, over 600 randomly chosen files across all six
# containers, Unicode normalised:
#
#     title   523/523      artist  518/518      album  495/495
#     genre   493/495      track   371/371      year   184/493
#
# So the real gaps are narrow and specific:
#
#     year          absent on FLAC and AIFF; our own readers have it
#     album_artist  absent everywhere; our own readers have it
#     has_art       absent; tags.has_art() answers it, 150/150 vs ffprobe
#     bit_depth     present only on WAV; ffprobe for the rest
#
# Which is the split this file's own research doc proposed and the first
# implementation never actually tested.
_MD = {
    'kMDItemTitle': 'title',
    'kMDItemAlbum': 'album',
    'kMDItemAuthors': 'artist',
    'kMDItemDurationSeconds': 'duration_sec',
    'kMDItemAudioSampleRate': 'sample_rate',
    'kMDItemAudioChannelCount': 'channels',
    'kMDItemBitsPerSample': 'bit_depth',
    'kMDItemFSSize': 'size',
    # NOT A FIELD WE WANT -- A FIELD THAT SAYS WHETHER TO BELIEVE THE REST.
    # See `probe_fast`: the drive this library lives on is usually detached,
    # so Spotlight can be behind on files changed while it was away.
    'kMDItemFSContentChangeDate': 'seen_at',
}
_MD_INT = ('sample_rate', 'channels', 'bit_depth', 'size')


def _mdls_batch(paths):
    """{path: {field: value}} from one mdls call, parsed as a plist."""
    if not paths:
        return {}
    args = ['mdls', '-plist', '-']
    for k in _MD:
        args += ['-name', k]
    try:
        out = subprocess.run(args + paths, capture_output=True,
                             timeout=300).stdout
        rows = plistlib.loads(out) if out.strip() else []
    except Exception:
        return {}
    if isinstance(rows, dict):
        rows = [rows]
    if len(rows) != len(paths):
        return {}            # not the shape we assumed: take none of it
    got = {}
    for path, row in zip(paths, rows):
        rec = {}
        for k, field in _MD.items():
            v = (row or {}).get(k)
            if isinstance(v, list):
                v = v[0] if v else None
            if v is None or v == '':
                continue
            if field in _MD_INT:
                try:
                    rec[field] = int(float(v))
                except (TypeError, ValueError):
                    pass
            elif field == 'duration_sec':
                try:
                    rec[field] = round(float(v), 2)
                except (TypeError, ValueError):
                    pass
            else:
                # Spotlight hands back NFD on this filesystem and the tag
                # readers hand back NFC. Identical to a reader, different to
                # ==, and it showed up as six "disagreements" that were not.
                rec[field] = unicodedata.normalize('NFC', str(v)).strip()
        got[path] = rec
    return got


def _codec_for(ext, path, depth):
    """The codec name ffprobe would give. The container settles it, except
    for the two places it does not.

    A WAV is not always 16-bit PCM: three in this library are 24 and 32 bit,
    and one of those is FLOAT, which the full-library differential caught as
    `pcm_s16le` where the shipped index said `pcm_f32le`.
    """
    if ext == '.wav':
        return {24: 'pcm_s24le', 32: 'pcm_f32le'}.get(depth, 'pcm_s16le')
    if ext in ('.m4a', '.mp4') and _is_alac(path):
        return 'alac'
    return _CODEC_BY_EXT.get(ext)


def _is_alac(path):
    """An .m4a is AAC unless its sample description says alac. Cheap: the
    four-character code appears in the moov, which is already in memory for
    anything the tag reader touched."""
    from . import tags as T
    try:
        for typ, at, size in T._mp4_top(path):
            if typ != b'moov':
                continue
            with open(path, 'rb') as fh:
                fh.seek(at)
                return b'alac' in fh.read(min(size, 1 << 20))
    except Exception:
        pass
    return False


def probe_fast(path, md):
    """An index entry from Spotlight, our own tag readers, and nothing else.

    EACH FIELD COMES FROM WHICHEVER SOURCE IS BEST AT IT, which is the point
    of measuring them separately:

        title artist album        Spotlight -- 100% against ffprobe, fastest
        album_artist year         our readers -- Spotlight does not have them
        has_art                   tags.has_art() -- 150/150 against ffprobe
        duration sample_rate
        channels size             Spotlight
        bit_depth                 Spotlight on WAV, otherwise left None
        codec                     the extension settles it for this library

    Returns None when Spotlight does not know the file at all; the caller
    then falls back to ffprobe rather than writing a half-built record.
    """
    from . import tags as T
    if not md or not md.get('duration_sec'):
        return None
    # STALE IS WORSE THAN ABSENT, and the external drive makes stale likely.
    # A volume that is usually unplugged can have files changed on another
    # machine, or by anything that ran while Spotlight was not watching; it
    # then answers confidently with what it last saw. An absent record is
    # safe -- it returns None here and the caller runs ffprobe -- so the job
    # is to turn "stale" into "absent".
    #
    # The gate is the same one `plan()` uses and it costs a stat: if the file
    # on disk is not the size Spotlight recorded, or has been written since
    # Spotlight last looked, none of its answers are trusted. 0.001 ms to
    # avoid believing a wrong duration.
    try:
        st = os.stat(path)
    except OSError:
        return None
    if md.get('size') is not None and md['size'] != st.st_size:
        return None
    seen = md.get('seen_at')
    if seen is not None:
        try:
            # allow a couple of seconds: the two clocks are not the same clock
            if st.st_mtime > seen.timestamp() + 2:
                return None
        except Exception:
            pass
    ext = os.path.splitext(path)[1].lower()
    tg = {}
    try:
        tg = T.read(path) or {}
    except Exception:
        tg = {}        # no reader for this container: Spotlight alone, then

    def pick(field):
        a = (tg.get(field) or '').strip()
        b = md.get(field) or ''
        return unicodedata.normalize('NFC', a or b).strip() or None

    title, artist = pick('title'), pick('artist')
    # FLAC states its own rate, channels and depth in STREAMINFO. Spotlight
    # has no bit depth for it at all, which cost 244 files the field.
    rate = depth = chans = None
    if ext == '.flac':
        try:
            got = T.flac_streaminfo(path)
            if got:
                rate, chans, depth = got
        except Exception:
            pass
    return {
        'path': path, 'ext': ext,
        'title': title, 'artist': artist, 'album': pick('album'),
        # Spotlight has neither of these for any container.
        'album_artist': (tg.get('album_artist') or '').strip() or None,
        'duration_sec': md.get('duration_sec'),
        # from the stat we already took: free, and never stale
        'size': st.st_size,
        'codec': _codec_for(ext, path, depth or md.get('bit_depth')),
        'sample_rate': rate or md.get('sample_rate'),
        'bit_depth': depth or md.get('bit_depth'),
        'channels': chans or md.get('channels'),
        'has_art': T.has_art(path),
        'ipod_ready': ext in IPOD_NATIVE,
        'needs_convert': ext in NEEDS_CONVERT,
        'untagged': not (title and artist),
        'mtime': st.st_mtime,
    }


# WAV AND AIFF WERE MISSING AND 1,532 FILES LOST THEIR CODEC, which the
# full-library differential caught -- the shipped ffprobe index had them and
# the new path did not. The container settles it for everything here: these
# are all PCM, and an .m4a in this library is AAC unless its moov says alac,
# which `probe_fast` checks rather than assumes.
_CODEC_BY_EXT = {'.mp3': 'mp3', '.m4a': 'aac', '.aac': 'aac', '.alac': 'alac',
                 '.flac': 'flac', '.ogg': 'vorbis',
                 '.wav': 'pcm_s16le', '.aif': 'pcm_s16be', '.aiff': 'pcm_s16be',
                 '.aifc': 'pcm_s16be'}


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

    # SPOTLIGHT IS THE DEFAULT NOW. `SALTPOD_FFPROBE=1` forces the old path.
    #
    # It was off for weeks on the strength of a differential that said 103
    # of 300 files lost their artist. THAT WAS THIS FILE'S OWN PARSER, not
    # Spotlight: mdls's human-readable output was being scraped by counting
    # lines, which only works if every attribute is one line, which forced
    # a scalar-only attribute list, which meant never asking for the artist
    # at all. The workaround got written up as the other tool's limitation
    # and the whole path was shelved on it.
    #
    # Re-run with `mdls -plist -` and the full attribute list, over all
    # 4,049 files, diffed field by field against the shipped ffprobe index:
    #
    #     title artist album album_artist   4047/4047
    #     bit_depth codec                   4047/4047
    #     duration sample_rate channels     4041-4045, the rest ffprobe got WRONG
    #
    #     130 s  ->  22.7 s
    #
    # Nine files differ and the new path is right on seven of them: ffprobe
    # returns duration 0 for one mp3 it cannot parse, and misses an 870 KB
    # cover on another because ffmpeg's own ID3 walk desynchronises where
    # ours now resynchronises. Two are the shipped index being stale.
    #
    # Each field comes from whichever source is actually best at it, and
    # `probe_fast` refuses Spotlight's answer outright when the file on disk
    # does not match what Spotlight last saw -- which matters because this
    # library lives on a drive that is usually unplugged.
    if os.environ.get('SALTPOD_FFPROBE') == '1':
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
