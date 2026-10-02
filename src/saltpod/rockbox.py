#!/usr/bin/env python3
"""Rockbox playlist mirror: the only way a Rockbox user ever sees a collection.

WHY THIS EXISTS, CONCRETELY. `research/ROCKBOX.md` section 2 and `research/ROCKBOX-DELTA.md`
section 1.1 both establish this by reading Rockbox's own source, not by guessing: Rockbox has NO
iTunesDB parser at all. A collection this tool writes today -- `ipod_edit.E.playlist_*`, into the
iTunesDB -- is therefore completely invisible to a Rockbox-booted Classic, in every format, always.
The device has two totally separate indexes (the iTunesDB for Apple firmware, a tagcache + plain
`.m3u8` files for Rockbox) and neither firmware reads the other's. So for a dual-boot owner, this
module is not an optimisation -- it is the entire mechanism by which a Rockbox session can ever show
"Night Drive" as a playlist at all. This is Shape A from `research/ROCKBOX-DELTA.md` Part 3: mirror,
don't replace. It changes nothing about the Apple-firmware sync, and nothing imports it yet.

THE DEFAULT DIRECTORY IS `.rockbox/Playlists`, NOT `/Playlists` AT THE VOLUME ROOT. This corrects
`research/ROCKBOX.md` section 4's own earlier citation of the manual ("stored by default in the
`/Playlists` directory in the root of your player's disk"). `research/ROCKBOX-DELTA.md` section 1.4
read the compiled constant directly: `firmware/export/rbpaths.h:64`,
`PLAYLIST_CATALOG_DEFAULT_DIR = ROCKBOX_DIR "/Playlists"`, and `ROCKBOX_DIR` is `.rockbox` (the same
macro behind `WPS_DIR`, unambiguously `/.rockbox/wps`). `apps/settings_list.c:2367-2368` wires that
constant up as the literal default of the user-facing "playlist catalog directory" setting. Two
sources disagree -- a years-old manual sentence against the firmware that actually ships -- and the
source wins, per that document's own stated rule. `data/device.json`'s own example in `config.py`
still shows `"playlist_dir": "/Playlists"` as a hand-written illustration of the per-target block
shape, predating this correction; it is not touched here (editing it is out of scope for this
module) but a caller should prefer `.rockbox/Playlists` unless a specific device is known to be
configured otherwise.

WHAT THIS MODULE DOES NOT DO. It does not decide which collections exist, what tracks belong to
them, or what order they play in -- `state.collection_order` is that truth, same as it is for the
Apple-firmware writer, and this module only ever renders and compares what it is handed. It does not
touch the iTunesDB, `iPod_Control/`, or anything outside the one playlist directory it is given. It
never sorts and never deduplicates: a track appearing twice in the sequence handed to it appears
twice in the file, because `publish/CONTRIBUTING.md`'s "what we will not merge" list includes
"anything that sorts a collection," and sequence is the product here exactly as it is for the
iTunesDB writer (`research/ITUNES-PARITY.md` section 2: "`state.collection_order` is the truth,
sync never sorts").

Standard library only.
"""
import glob
import hashlib
import os
import re
import shutil
import sys
import tempfile
import unicodedata

# ---------------------------------------------------------------- conventions
#
# Everything below is `.m3u8` grammar `research/ROCKBOX.md` section 4 read directly out of
# Rockbox's own `apps/playlist.c`, except where a comment says otherwise. Said once here rather
# than re-derived at every call site.

# RESEARCHED (research/ROCKBOX-DELTA.md section 1.4, `firmware/export/rbpaths.h:64` and
# `apps/settings_list.c:2367-2368`, the compiled default -- see the module docstring for the full
# citation and the manual-versus-source disagreement it corrects).
DEFAULT_PLAYLIST_DIR = '.rockbox/Playlists'

# Rockbox recognises both extensions for a playlist file (research/ROCKBOX.md section 4); this
# module only ever WRITES `.m3u8` (the BOM+UTF-8 convention below is specifically the `.m3u8`
# recommendation, not the plain `.m3u` one) but checks for both when looking at what is already on
# disk, so a `.m3u` someone wrote by hand is recognised as "ours" or "extra" rather than ignored.
RECOGNISED_EXTS = ('.m3u8', '.m3u')
_WRITE_EXT = '.m3u8'

# RESEARCHED: `research/ROCKBOX.md` section 4, read out of `apps/playlist.c` -- "a UTF-8
# byte-order mark forces UTF-8 parsing... without it, non-ASCII filenames (accents, Cyrillic) can
# fail to match." Corroborated independently by a named forum account of a from-scratch playlist
# workflow, quoted in the same section: Rockbox "prefers the format to be UTF-8-BOM with LF line
# endings (.m3u8), otherwise it won't load files with exotic characters." So: WANTED here, not
# harmful, and written on every file unconditionally -- there is no case in this tool's own output
# where the BOM could hurt and a documented one where omitting it can silently break matching.
_BOM = b'\xef\xbb\xbf'

# DECIDED, not settled by the research. `research/ROCKBOX.md` section 4 quotes the LF
# recommendation from the named forum account above; this session did not re-read
# `apps/playlist.c` itself for its own end-of-line handling (the delta document does not re-derive
# that citation past what is already quoted there), so "Rockbox requires LF" is not claimed as a
# primary-sourced fact -- only "LF is recommended, and is the lower-risk choice" is. A parser
# tolerant of bare LF (and treating a trailing \r as part of the line, which would then corrupt a
# device path) is a far more common failure mode than one that *requires* CRLF, so LF it is.
_EOL = '\n'

# DECIDED: the general Extended-M3U convention for "duration unknown," not something
# Rockbox-specific this session found documented. Every real entry this tool ever writes has a
# known duration (it comes from the device track or the source file), so this path is defensive --
# it exists so a caller's bug produces a still-valid playlist rather than a crash, not because it
# is expected to fire.
_UNKNOWN_DURATION = -1


def playlist_text(entries, style='extm3u'):
    """The bytes of one `.m3u8` file, built from `entries` in EXACTLY the order given.

    `entries` is a sequence of `(device_path, title, seconds)`:

      device_path   absolute, from the DEVICE ROOT, leading slash, e.g.
                    `/iPod_Control/Music/F04/ABCD.m4a` -- RESEARCHED, `research/ROCKBOX.md`
                    section 4: "a real, working example, not a sketch," and the convention
                    `TheRealSavi/iOpenPod` issue #192 independently converged on the same month,
                    quoted there verbatim:

                        #EXTM3U
                        #EXTINF:243,Grace Potter - Stars
                        /iPod_Control/Music/F04/ABCD.m4a

                    NEVER a Mac path (`/Volumes/IPOD/...`) -- that is "dead on arrival" per the
                    same section, and `_device_path()` below refuses one outright rather than
                    writing a file that would silently fail on the device.
      title         whatever single display string the caller wants on the `#EXTINF` line. The
                    worked example above composes "Artist - Title" itself; this function does not
                    -- `entries` carries one string, not an (artist, title) pair, so composing it
                    (or not) is the caller's decision.
      seconds       the track's duration. Written as a whole number of seconds (DECIDED, the
                    general Extended-M3U convention; see `_UNKNOWN_DURATION` above for what a
                    falsy value becomes).

    ORDER IS THE PRODUCT: nothing here sorts or deduplicates. A track appearing twice in `entries`
    appears twice in the file, at the positions given.

    `style` exists so a second format never has to break this function's signature; only
    `'extm3u'` (the one format actually researched and asked for) exists today.
    """
    if style != 'extm3u':
        raise ValueError("rockbox.playlist_text: unknown style %r (only 'extm3u' exists)" % (style,))
    lines = ['#EXTM3U']
    for device_path, title, seconds in entries:
        path = _device_path(device_path)
        text = _one_line(title or '')
        dur = _UNKNOWN_DURATION if not seconds and seconds != 0 else int(round(seconds))
        lines.append('#EXTINF:%d,%s' % (dur, text))
        lines.append(path)
    body = _EOL.join(lines) + _EOL
    return _BOM + body.encode('utf-8')


def _one_line(s):
    """Collapse any embedded line break in a title to a space.

    DECIDED, not researched: a bare `\\n` inside a title would silently insert an extra physical
    line into the file, which Rockbox's line-oriented parser (`research/ROCKBOX.md` section 4:
    "lines starting `#` are skipped") would then try to read as either another tag or a bare path
    -- corrupting the entry after it, not just this one. Collapsed to a space rather than stripped
    so two halves of a title that only had a stray newline between them don't get jammed together
    into one word.
    """
    return re.sub(r'[\r\n]+', ' ', s).strip()


def _device_path(path):
    """Enforce the one rule this whole module exists to get right: an ABSOLUTE, DEVICE-ROOT path.

    `/iPod_Control/Music/F04/ABCD.m4a`, confirmed against the real mounted device this session
    (read-only -- `/Volumes/IPOD/iPod_Control/Music/F04/CXFV.mp3` on disk is exactly
    `/iPod_Control/Music/F04/CXFV.mp3` from the device root). NEVER
    `/Volumes/IPOD/iPod_Control/...` -- a Mac path written into the file is, per
    `research/ROCKBOX.md` section 4, "dead on arrival."
    """
    p = path.replace('\\', '/')     # Rockbox itself normalises backslashes on read (same
                                     # section); done here too so the file is correct outright,
                                     # not merely tolerated by the device's own leniency.
    if not p.startswith('/'):
        raise ValueError('rockbox: device path must be absolute from the device root, got %r'
                         % (path,))
    if re.match(r'^/Volumes/', p, re.IGNORECASE):
        raise ValueError(
            "rockbox: %r looks like a Mac mount path, not a device-root path -- strip the mount "
            "prefix before calling playlist_text()" % (path,))
    return p


# ------------------------------------------------------------------ filenames

_UNSAFE = re.compile(r'[\/\\:\*\?"<>\|\x00-\x1f]')


def _sanitize_base(name):
    """A filesystem-safe stem for one collection name.

    Keeps spaces, accents and emoji -- FAT32/exFAT's long-filename form is UTF-16 and stores all
    three without complaint -- and replaces only what is actually illegal: path separators,
    FAT/exFAT's reserved `" * : < > ? \\ |`, and control characters. Leading/trailing dots and
    spaces are stripped, because both are silently dropped or rejected by FAT-family filesystems
    on a short/long-name boundary.

    NOT VERIFIED against a real FAT32-formatted iPod: whether a filename written here in NFC form
    round-trips as NFC through macOS's exFAT/msdos driver, or comes back NFD the way
    `research/alternatives.md`'s Unicode-normalisation note documents for TRACK paths specifically
    (`msdos`/`exfat` kexts list FAT32 directory entries in NFD on macOS). That note is about
    entries' device_path strings, which this tool only ever writes as plain ASCII
    (`apply.new_location()`'s random 4-letter stems), so it does not apply to entries -- but a
    collection NAME turned into a playlist FILENAME is exactly the kind of accented string that
    note warns about, and this was not re-tested against the real, mounted device for filenames.
    Flagged here rather than assumed fine.
    """
    s = unicodedata.normalize('NFC', name)
    s = _UNSAFE.sub('_', s)
    s = s.strip(' .')
    return s or 'collection'


def filenames_for(collections):
    """name -> filename, one `.m3u8` per collection, deterministic and COLLISION-FREE.

    Two different collection names must never sanitise to the same file -- that would silently
    merge two playlists into one on the device, which is worse than an ugly filename. The first
    name to reach a given sanitised base keeps the plain filename; anything that collides with it
    gets a short hash of its OWN full name appended, checked against every filename already
    handed out (not just the plain ones), so even a contrived name that happens to equal another
    collision's hash-qualified filename is caught and pushed further rather than silently
    colliding.

    `collections` is iterated in the order given -- a plain `dict` is fine, insertion order is its
    iteration order -- and that order is what the disambiguation above depends on, which is why
    `write_playlists` and `plan_playlists` both call this ONE function rather than each keeping
    their own copy that could quietly drift apart and disagree about which file belongs to which
    collection.
    """
    used = set()
    out = {}
    for name in collections:
        base = _sanitize_base(name)
        candidate = base + _WRITE_EXT
        if candidate in used:
            h = hashlib.sha1(name.encode('utf-8')).hexdigest()[:8]
            candidate = '%s~%s%s' % (base, h, _WRITE_EXT)
            n = 2
            while candidate in used:          # astronomically unlikely; still checked
                candidate = '%s~%s-%d%s' % (base, h, n, _WRITE_EXT)
                n += 1
        used.add(candidate)
        out[name] = candidate
    return out


def _resolve_dir(mount, playlist_dir):
    """`playlist_dir` is a DEVICE-ROOT path, exactly like a track's own path -- `/Playlists`,
    `.rockbox/Playlists` and `Playlists` are all accepted; a leading slash is cosmetic and
    stripped, matching `data/device.json`'s own documented `rockbox.playlist_dir` shape. Default
    is `DEFAULT_PLAYLIST_DIR` (the compiled source default, see the module docstring). Never pass
    a Mac path (`/Volumes/...`) here -- joining it onto `mount` would double the mount prefix up.
    """
    rel = (playlist_dir if playlist_dir is not None else DEFAULT_PLAYLIST_DIR).lstrip('/')
    return os.path.join(mount, rel)


# --------------------------------------------------------------- write / plan

# Indirection so `selftest()` can prove the atomic-write guarantee by making the rename itself
# fail, without touching the real `os` module. See `_selftest_atomic`.
_os_replace = os.replace


def _atomic_write(dest, data):
    """Write `data` to `dest` such that a reader never observes a partial file.

    A temp file in the SAME directory (so the final rename is same-filesystem and therefore
    atomic) gets the complete content in one write; only then is it swapped into place.
    Interrupted before the swap, `dest` is exactly what it was before this call, with nothing to
    clean up but an orphaned, oddly-named temp file that no reader would ever mistake for a
    playlist. Interrupted during or after the swap, the filesystem's own atomic rename means
    `dest` is either fully the old content or fully the new content -- there is no state where it
    is half of each. `selftest()` exercises the failure path directly, not just the happy one.
    """
    d = os.path.dirname(dest) or '.'
    fd, tmp = tempfile.mkstemp(prefix='.rockbox-write-', suffix='.tmp', dir=d)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        _os_replace(tmp, dest)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_playlists(mount, collections, playlist_dir=None):
    """Write one `.m3u8` per collection, atomically, into the Playlist Catalogue directory.

    `collections` is an ordered mapping of name -> the `(device_path, title, seconds)` sequence
    `playlist_text` takes (a plain `dict` is fine). `playlist_dir` is a device-root path or
    `None` for `DEFAULT_PLAYLIST_DIR` -- see `_resolve_dir`. The directory is created if absent.

    One collection failing to write (a permissions error, a full disk, the simulated failure
    `selftest()` injects) does not stop the others: each file is independent, and this tool's own
    model already says the device is "a slave that catches up" (`HANDOFF.md`) -- a partial sync
    this run is recoverable next run, a sync that gives up on everything because one file failed
    is not better.

    Returns a receipt:
        {'dir': <resolved playlist directory>,
         'filenames': {name: filename, ...},          # from filenames_for()
         'written':   [{'collection', 'file', 'path', 'tracks', 'bytes'}, ...],
         'errors':    [{'collection', 'file', 'error'}, ...]}
    """
    out_dir = _resolve_dir(mount, playlist_dir)
    os.makedirs(out_dir, exist_ok=True)
    names = filenames_for(collections)
    written, errors = [], []
    for name, entries in collections.items():
        entries = list(entries)
        fname = names[name]
        dest = os.path.join(out_dir, fname)
        try:
            data = playlist_text(entries)
            _atomic_write(dest, data)
            written.append({'collection': name, 'file': fname, 'path': dest,
                            'tracks': len(entries), 'bytes': len(data)})
        except Exception as e:
            errors.append({'collection': name, 'file': fname, 'error': str(e)})
    return {'dir': out_dir, 'filenames': names, 'written': written, 'errors': errors}


def collections_from_state(st, names=None):
    """saltpod's curation state, turned into the `collections` mapping the
    two functions above actually take.

    THE MODULE WAS BUILT AGAINST A SHAPE NOTHING PRODUCED. `write_playlists`
    wants `{name: [(device_path, title, seconds), ...]}`; `state.py` holds
    `collection_order` as `{name: [track_key, ...]}` and keeps the path and
    duration on the track record, in a different form again -- the device
    location is iPod colon-notation (`:iPod_Control:Music:F46:VXBJ.m4a`),
    not the slash path `_device_path` demands. So every one of this module's
    entry points was unreachable not for want of a CLI verb but for want of
    this translation, which no caller could have been expected to write.

    ORDER IS CARRIED, NEVER COMPUTED. `collection_order` is the sequence the
    owner arranged; this walks it in exactly that order and so does
    `playlist_text`. Nothing here sorts.

    A track with no `device` block has never been on the iPod, so there is no
    device path to put in a playlist that the device will read. Those are
    skipped and returned separately rather than guessed at -- a playlist
    quietly missing a track is worse than one that says what it dropped.

    Returns `(collections, skipped)` where `skipped` is
    `[{'collection', 'key', 'why'}, ...]`.
    """
    order = st.get('collection_order') or {}
    tracks = st.get('tracks') or {}
    out, skipped = {}, []
    for name, keys in order.items():
        if names and name not in names:
            continue
        entries = []
        for k in keys:
            r = tracks.get(k) or {}
            dev = r.get('device') or {}
            loc = dev.get('location')
            if not loc:
                skipped.append({'collection': name, 'key': k,
                                'why': 'not on the device -- no device.location'})
                continue
            # ':iPod_Control:Music:F46:VXBJ.m4a' -> '/iPod_Control/Music/F46/VXBJ.m4a'
            # The leading colon becomes the leading slash, which is exactly
            # the device-root form `_device_path` requires.
            path = loc.replace(':', '/')
            artist = (r.get('artist') or '').strip()
            title = (r.get('title') or '').strip()
            # One pre-composed string, because playlist_text takes one and
            # says composing it is the caller's decision.
            label = ('%s - %s' % (artist, title)).strip(' -') or (title or artist or k)
            entries.append((path, label, dev.get('seconds') or 0))
        out[name] = entries
    return out, skipped


def plan_playlists(mount, collections, playlist_dir=None):
    """What `write_playlists` WOULD do. Reads the directory; touches nothing.

    The same shape `apply.py`'s own `plan()`/`_plan()` already use for the Apple-firmware side:
    a diff against a live read, with no side effect of its own -- it does not even create
    `playlist_dir` if absent.

    Returns:
        {'dir': <resolved playlist directory>,
         'filenames': {name: filename, ...},
         'new':       [name, ...],   # no file there yet
         'changed':   [name, ...],   # a file exists, bytes differ from what would be written
         'unchanged': [name, ...],   # a file exists and already matches, byte for byte
         'extra':     [filename, ...]}  # a RECOGNISED_EXTS file in the dir that no CURRENT
                                         # collection maps to -- a renamed/deleted collection's
                                         # leftover, or something not ours
    """
    out_dir = _resolve_dir(mount, playlist_dir)
    names = filenames_for(collections)
    new, changed, unchanged = [], [], []
    for name, entries in collections.items():
        dest = os.path.join(out_dir, names[name])
        want = playlist_text(list(entries))
        if not os.path.exists(dest):
            new.append(name)
            continue
        try:
            with open(dest, 'rb') as f:
                have = f.read()
        except OSError:
            new.append(name)
            continue
        (unchanged if have == want else changed).append(name)
    ours = set(names.values())
    extra = []
    if os.path.isdir(out_dir):
        for fname in sorted(os.listdir(out_dir)):
            if fname in ours:
                continue
            if os.path.splitext(fname)[1].lower() in RECOGNISED_EXTS:
                extra.append(fname)
    return {'dir': out_dir, 'filenames': names,
            'new': new, 'changed': changed, 'unchanged': unchanged, 'extra': extra}


# =================================================================== selftest

def _selftest_text():
    print()
    print('--- playlist_text ---')
    ok = True
    entries = [
        ('/iPod_Control/Music/F04/ABCD.m4a', 'Boards of Canada - Dayvan Cowboy', 259),
        ('/iPod_Control/Music/F07/WXYZ.mp3', 'Jon Hopkins - Open Eye Signal', 353.4),
        ('/iPod_Control/Music/F04/ABCD.m4a', 'Boards of Canada - Dayvan Cowboy', 259),  # deliberate duplicate
    ]
    data = playlist_text(entries)
    if not data.startswith(_BOM):
        print('  FAILED: no UTF-8 BOM at the start of the file')
        ok = False
    text = data.decode('utf-8-sig')
    lines = text.split(_EOL)
    if lines[0] != '#EXTM3U':
        print('  FAILED: first line is %r, not #EXTM3U' % lines[0])
        ok = False
    paths = [l for l in lines if l and not l.startswith('#')]
    want_paths = [e[0] for e in entries]
    if paths != want_paths:
        print('  FAILED: order not preserved exactly -- got %r, want %r' % (paths, want_paths))
        ok = False
    else:
        print('  order preserved exactly, including the deliberate duplicate: ok')
    if '#EXTINF:259,Boards of Canada - Dayvan Cowboy' not in lines:
        print('  FAILED: #EXTINF line not in the expected shape')
        ok = False
    else:
        print('  #EXTM3U / #EXTINF:<seconds>,<title> shape: ok')

    bad_paths_ok = True
    for bad in ('iPod_Control/Music/F00/X.mp3',          # not absolute
               '/Volumes/IPOD/iPod_Control/Music/F00/X.mp3'):  # a Mac path, not a device path
        try:
            playlist_text([(bad, 't', 1)])
            print('  FAILED: accepted a bad device path %r' % (bad,))
            bad_paths_ok = False
        except ValueError:
            pass
    if bad_paths_ok:
        print('  a non-absolute path and a Mac-mounted path are both refused: ok')
    ok = ok and bad_paths_ok

    print()
    print('  full text of this generated playlist, for a human to eyeball:')
    print('  ' + '-' * 64)
    for line in text.rstrip(_EOL).split(_EOL):
        print('  ' + line)
    print('  ' + '-' * 64)
    return ok


def _selftest_filenames():
    print()
    print('--- filenames_for: distinctness ---')
    ok = True
    cols = {
        'Road Trip 2026': [],
        'Café Days / Été \U0001F3A7': [],   # space, slash, accent, emoji
        'A/B': [],
        'A:B': [],       # deliberately sanitises to the same base as 'A/B'
    }
    names = filenames_for(cols)
    if len(set(names.values())) != len(names):
        print('  FAILED: two distinct collections collided into one filename: %r' % (names,))
        ok = False
    else:
        print('  %d distinct collection names -> %d distinct files: ok' % (len(cols), len(names)))
    for k, v in names.items():
        print('    %-34r -> %s' % (k, v))
    return ok


def _selftest_atomic(mount, playlist_dir, cols, existing_path):
    print()
    print('--- atomic write: a failed rename cannot leave a partial file ---')
    ok = True
    before = open(existing_path, 'rb').read()

    global _os_replace
    saved = _os_replace

    def _boom(*a, **k):
        raise OSError('simulated rename failure (selftest)')

    _os_replace = _boom
    try:
        bad_cols = {'Night Drive': list(cols['Night Drive']) +
                                   [('/iPod_Control/Music/F04/LMNO.m4a', 'extra track', 1)]}
        receipt = write_playlists(mount, bad_cols, playlist_dir=None)
    finally:
        _os_replace = saved

    if not receipt['errors']:
        print('  FAILED: the simulated rename failure was not reported in the receipt')
        ok = False
    after = open(existing_path, 'rb').read()
    if after != before:
        print('  FAILED: the existing file changed even though the write failed')
        ok = False
    else:
        print('  a failed rename leaves the existing file completely untouched: ok')
    tmps = [f for f in os.listdir(playlist_dir) if f.endswith('.tmp')]
    if tmps:
        print('  FAILED: a temp file was left behind after the failed write: %r' % (tmps,))
        ok = False
    else:
        print('  no .tmp litter left behind after the failed write: ok')

    receipt2 = write_playlists(mount, bad_cols, playlist_dir=None)
    if receipt2['errors']:
        print('  FAILED: a normal retry right after the failure did not succeed: %r' % (receipt2,))
        ok = False
    else:
        got = open(existing_path, 'rb').read()
        want = playlist_text(bad_cols['Night Drive'])
        if got != want:
            print('  FAILED: the recovered write is not exactly the intended content')
            ok = False
        else:
            print('  a normal write right after the failure succeeds and is complete: ok')
    return ok


def _selftest_write_and_plan():
    print()
    print('--- write_playlists / plan_playlists, in a fake device tree ---')
    ok = True
    mount = tempfile.mkdtemp(prefix='saltpod-rockbox-')
    try:
        # A device tree that LOOKS real: a few scattered Fxx/XXXX.ext files (the same naming
        # apply.new_location() produces) and an installed .rockbox/, the same shape
        # config.detect_target() looks for on a real Rockbox'd Classic.
        music = os.path.join(mount, 'iPod_Control', 'Music', 'F04')
        os.makedirs(music)
        for fname in ('ABCD.m4a', 'WXYZ.mp3', 'LMNO.m4a'):
            with open(os.path.join(music, fname), 'wb') as f:
                f.write(b'\x00' * 32)
        os.makedirs(os.path.join(mount, '.rockbox'))

        p1 = '/iPod_Control/Music/F04/ABCD.m4a'
        p2 = '/iPod_Control/Music/F04/WXYZ.mp3'
        p3 = '/iPod_Control/Music/F04/LMNO.m4a'

        cols = {
            'Night Drive': [(p1, 'Boards of Canada - Dayvan Cowboy', 259),
                            (p2, 'Jon Hopkins - Open Eye Signal', 353),
                            (p1, 'Boards of Canada - Dayvan Cowboy', 259)],   # duplicate, on purpose
            'Café Days / Été \U0001F3A7': [(p3, "Air - La Femme d'Argent", 269)],
        }

        # plan BEFORE writing anything: everything should be 'new', and plan_playlists must not
        # have created the directory to find that out.
        before = plan_playlists(mount, cols)
        if sorted(before['new']) != sorted(cols) or before['changed'] or before['unchanged']:
            print('  FAILED: pre-write plan was %r' % (before,)); ok = False
        elif os.path.isdir(before['dir']):
            print('  FAILED: plan_playlists created the directory'); ok = False
        else:
            print('  pre-write plan: both collections reported new, directory untouched: ok')

        receipt = write_playlists(mount, cols)
        if receipt['errors'] or len(receipt['written']) != 2:
            print('  FAILED: write_playlists reported errors: %r' % (receipt,)); ok = False
        if not os.path.isdir(os.path.join(mount, '.rockbox', 'Playlists')):
            print('  FAILED: did not write under .rockbox/Playlists (the compiled default)')
            ok = False
        files = sorted(os.listdir(receipt['dir']))
        if len(files) != 2:
            print('  FAILED: expected 2 files, found %r' % (files,)); ok = False
        else:
            print('  wrote %d distinct .m3u8 files to %s: ok' % (len(files), receipt['dir']))

        # order, including the duplicate, survives a real round trip through disk
        night_path = os.path.join(receipt['dir'], receipt['filenames']['Night Drive'])
        with open(night_path, 'rb') as f:
            raw = f.read()
        text = raw.decode('utf-8-sig')
        got_paths = [l for l in text.split(_EOL) if l and not l.startswith('#')]
        if got_paths != [p1, p2, p1]:
            print('  FAILED: order/duplicate not preserved on disk: %r' % (got_paths,)); ok = False
        else:
            print('  order and duplicate survive a real write-then-read: ok')

        # second plan: both should now read back as unchanged
        again = plan_playlists(mount, cols)
        if again['new'] or again['changed'] or sorted(again['unchanged']) != sorted(cols):
            print('  FAILED: post-write plan was %r' % (again,)); ok = False
        else:
            print('  post-write plan: both unchanged: ok')

        # change one collection's content -> only that one shows as changed
        cols2 = dict(cols)
        cols2['Night Drive'] = list(cols['Night Drive']) + \
            [(p2, 'Jon Hopkins - Open Eye Signal', 353)]
        drift = plan_playlists(mount, cols2)
        cafe = 'Café Days / Été \U0001F3A7'
        if drift['changed'] != ['Night Drive'] or cafe not in drift['unchanged']:
            print('  FAILED: drift plan was %r' % (drift,)); ok = False
        else:
            print('  one collection changed, the other stayed unchanged: ok')

        # a brand new, not-yet-written collection is reported new, alongside the others
        cols3 = dict(cols2)
        cols3['Focus'] = [(p3, "Air - La Femme d'Argent", 269)]
        grown = plan_playlists(mount, cols3)
        if grown['new'] != ['Focus']:
            print('  FAILED: new-collection plan was %r' % (grown,)); ok = False
        else:
            print('  a brand new collection is reported new, without disturbing the others: ok')

        # a file nobody asked for -- a renamed/retired collection, or a stray -- is 'extra'
        stray = os.path.join(receipt['dir'], 'Old Mix.m3u8')
        with open(stray, 'wb') as f:
            f.write(_BOM + b'#EXTM3U\n')
        extra_plan = plan_playlists(mount, cols3)
        if extra_plan['extra'] != ['Old Mix.m3u8']:
            print('  FAILED: extra-file plan was %r' % (extra_plan,)); ok = False
        else:
            print('  a stray file already in the directory is reported extra: ok')

        ok = _selftest_atomic(mount, receipt['dir'], cols, night_path) and ok
    finally:
        shutil.rmtree(mount, ignore_errors=True)
    return ok


def _selftest_real_device():
    """Read-only cross-check against whatever iPod is actually mounted, if one is. Informational:
    a device not being plugged in is not a selftest failure, only something to report plainly.
    NEVER WRITES -- only os.listdir/glob against /Volumes/IPOD.
    """
    print()
    print('--- real device cross-check (read-only, never written to) ---')
    mount = '/Volumes/IPOD'
    if not os.path.isdir(mount):
        print('  %s not mounted -- skipped' % (mount,))
        return True
    found = []
    for folder in sorted(glob.glob(os.path.join(mount, 'iPod_Control', 'Music', 'F*'))):
        try:
            # skip macOS's own AppleDouble sidecars (._Foo.mp3) -- real track files only
            names = sorted(n for n in os.listdir(folder) if not n.startswith('.'))
        except OSError:
            continue
        for fn in names[:2]:
            found.append(os.path.join(folder, fn))
        if len(found) >= 3:
            break
    if not found:
        print('  mounted, but no files found under iPod_Control/Music/F*/ -- skipped')
        return True
    print('  real files on the mounted device:')
    for mac_path in found:
        rel = os.path.relpath(mac_path, mount)
        device_path = '/' + rel.replace(os.sep, '/')
        print('    mac:    %s' % mac_path)
        print('    device: %s' % device_path)
        try:
            _device_path(device_path)
        except ValueError as e:
            print('  FAILED: a real on-device path was rejected by this module: %s' % e)
            return False
    print('  the real on-device path shape matches what this module reads/writes: ok')
    return True


def selftest():
    """Everything in this module verified against real files, entirely under
    tempfile.mkdtemp() except the final read-only cross-check -- which never writes.
    """
    print('rockbox playlist mirror -- selftest')
    ok = True
    ok = _selftest_text() and ok
    ok = _selftest_filenames() and ok
    ok = _selftest_write_and_plan() and ok
    ok = _selftest_real_device() and ok
    print()
    print('selftest %s' % ('PASSED' if ok else 'FAILED'))
    return ok


def main(argv=None):
    a = argv if argv is not None else sys.argv[1:]
    if not a or a[0] != 'selftest':
        print('usage: python3 -m saltpod.rockbox selftest')
        return 2
    return 0 if selftest() else 1


if __name__ == '__main__':
    sys.exit(main())
