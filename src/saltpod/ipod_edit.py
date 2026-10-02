#!/usr/bin/env python3
"""Edit operations on an iTunesDB tree: playlists and tracks.

Principle: never invent a structure the firmware has not already accepted
from this device. Every new mhyp, mhip, position mhod and mhit is CLONED from
one already in the database and then patched field by field. Only the string
mhods are built from scratch, and their shape (UTF-16LE, body words 1,len,1,0)
is the one the device already carries 3,689 times.

Operations (all pure: take a tree, return nothing, mutate in place):
    playlist_create(root, name)                 -> playlist persistent id
    playlist_delete(root, name)
    playlist_rename(root, old, new)
    playlist_set_tracks(root, name, [track ids])
    track_add(root, meta, location)             -> track id
    track_remove(root, track_id)                -> location string

Two things the caller must do around a track-set change, because they live
outside this file: delete `Play Counts` on the device (it is positional), and
copy/delete the audio file itself. `apply.py` does both.

iTunes stores each regular playlist TWICE (mhsd type 3 and type 2); every
playlist operation is applied to both, identically. The master playlist's
mhod 52/53 letter indexes are positional over the track list, so they are
dropped whenever a track is added or removed -- the spec calls them optional
("browsing slower without them"), and stale ones are worse than none.
"""
import os
import struct
import time

from . import itunesdb_write as W

MAC_EPOCH = 2082844800            # seconds between 1904-01-01 and 1970-01-01
FILETYPE_STR = {'.mp3': 'MPEG audio file', '.m4a': 'AAC audio file',
                '.aac': 'AAC audio file'}
SUPPORTED = ('.mp3', '.m4a', '.aac')      # containers stock firmware plays as-is


def mac_now():
    return int(time.time()) + MAC_EPOCH


def rand64():
    v = 0
    while v == 0:
        v = int.from_bytes(os.urandom(8), 'little')
    return v


# --------------------------------------------------------------- lookup

def playlist_sections(root):
    return [s for t in (3, 2) for s in [W.section(root, t)] if s is not None]


def playlists(root, sect):
    return sect.children[0].children                      # mhlp's mhyps


def pl_name(mhyp):
    for c in mhyp.children:
        if c.magic == b'mhod' and W.mhod_type(c) == 1:
            return W.mhod_string(c)
    return None


def is_master(mhyp):
    return mhyp.hdr[0x14] == 1


def is_smart(mhyp):
    return any(c.magic == b'mhod' and W.mhod_type(c) in (50, 51) for c in mhyp.children)


def find_playlist(root, sect, name):
    hits = [p for p in playlists(root, sect) if pl_name(p) == name]
    if not hits:
        raise KeyError('no playlist named %r' % name)
    return hits[0]


def tracks(root):
    return W.section(root, 1).children[0].children        # mhlt's mhits


def track_id(mhit):
    return mhit.get32(0x10)


def track_dbid(mhit):
    return struct.unpack_from('<Q', mhit.hdr, 0x70)[0]


def track_location(mhit):
    for c in mhit.children:
        if W.mhod_type(c) == 2:
            return W.mhod_string(c)
    return None


def _plain_template(root, sect):
    for p in playlists(root, sect):
        if not is_master(p) and not is_smart(p) and any(c.magic == b'mhip' for c in p.children):
            return p
    for p in playlists(root, sect):
        if not is_master(p) and not is_smart(p):
            return p
    raise RuntimeError('no plain playlist to clone from')


def _mhip_template(root):
    for sect in playlist_sections(root):
        for p in playlists(root, sect):
            for c in p.children:
                if c.magic == b'mhip' and c.children:
                    return c
    raise RuntimeError('no mhip to clone from')


def _next_ids(root):
    tids = [track_id(t) for t in tracks(root)]
    gids = [c.get32(0x14) for s in playlist_sections(root) for p in playlists(root, s)
            for c in p.children if c.magic == b'mhip']
    return max(tids) + 1, max(gids + tids) + 1


# ------------------------------------------------------------- playlists

def _make_mhip(root, tid, dbid, position, group_id):
    t = _mhip_template(root)
    m = W.Node(b'mhip', bytes(t.hdr))
    m.set32(0x14, group_id)
    m.set32(0x18, tid)
    m.set32(0x1C, mac_now())
    m.set32(0x20, 0)
    m.set64(0x2C, dbid)
    m.set64(0x3C, rand64())
    pos = t.children[0]
    p = W.Node(b'mhod', bytes(pos.hdr), bytes(pos.body))
    # "position at +0x18" is from the mhod's start; its header is exactly
    # 0x18 bytes, so the position is the first word of the body.
    p.body = struct.pack('<I', position) + p.body[4:]
    m.children = [p]
    return m


def playlist_create(root, name):
    pid = rand64()
    now = mac_now()
    for sect in playlist_sections(root):
        t = _plain_template(root, sect)
        y = W.Node(b'mhyp', bytes(t.hdr))
        y.hdr[0x14] = 0
        y.set32(0x18, now)
        y.set64(0x1C, pid)
        y.set32(0x2C, 1)                          # manual order
        y.set64(0x44, pid)
        if len(y.hdr) > 0x5C:
            y.set32(0x58, now)
        y.children = [W.make_string_mhod(1, name)]
        for c in t.children:                      # column def (100) and 102, cloned
            if c.magic == b'mhod' and W.mhod_type(c) in (100, 102):
                y.children.append(W.Node(b'mhod', bytes(c.hdr), bytes(c.body)))
        playlists(root, sect).append(y)
    return pid


def playlist_delete(root, name):
    for sect in playlist_sections(root):
        p = find_playlist(root, sect, name)
        if is_master(p):
            raise ValueError('refusing to delete the master playlist')
        playlists(root, sect).remove(p)


def playlist_rename(root, old, new):
    for sect in playlist_sections(root):
        p = find_playlist(root, sect, old)
        for i, c in enumerate(p.children):
            if c.magic == b'mhod' and W.mhod_type(c) == 1:
                p.children[i] = W.make_string_mhod(1, new)
                break


def track_retag(root, tid, fields):
    """Change what the device says a track is called.

    The same move `playlist_rename` makes, on a track: find the mhod of the
    right type and swap the string. Nothing else in the record is touched --
    not the location, not the dbid, not the play count sitting in the header.

    This exists for the iPod that outlived its library. A Classic cannot
    retag itself (there is no keyboard), so saltpod is the only writer on
    either side, which is what makes "whichever edit was last" a fact we
    record rather than a guess we make.

    Passing a field as None leaves it alone; passing '' clears it.
    """
    mhods = {'title': 1, 'album': 3, 'artist': 4, 'genre': 5, 'composer': 12,
             'album_artist': 22}
    t = next((x for x in tracks(root) if track_id(x) == tid), None)
    if t is None:
        raise KeyError('no track %r on the device' % tid)
    changed = []
    for name, typ in mhods.items():
        if fields.get(name) is None:
            continue
        val = str(fields[name])
        for i, c in enumerate(t.children):
            if c.magic == b'mhod' and W.mhod_type(c) == typ:
                t.children[i] = W.make_string_mhod(typ, val)
                changed.append(name)
                break
        else:
            # the field was never set on this track; add it before the
            # non-mhod children so the record keeps its shape
            at = len([c for c in t.children if c.magic == b'mhod'])
            t.children.insert(at, W.make_string_mhod(typ, val))
            changed.append(name)
    return changed


def playlist_set_tracks(root, name, track_ids):
    by_id = {track_id(t): t for t in tracks(root)}
    missing = [i for i in track_ids if i not in by_id]
    if missing:
        raise KeyError('unknown track ids: %s' % missing)
    # ONE ROW, ONE IDENTITY, IN BOTH SECTIONS. Apple writes every playlist's
    # type-2 and type-3 rows byte-identical -- same group id, timestamp,
    # dbid and the 64-bit value at 0x3C (481 of 481 master rows on the
    # pristine database). This used to keep incrementing the group id across
    # sections and draw a fresh random 0x3C per row per section, so the two
    # copies of every list it wrote disagreed. Each row is now made once and
    # the same bytes go to both.
    _, gid = _next_ids(root)
    made = []
    for pos, tid in enumerate(track_ids, 1):
        made.append(_make_mhip(root, tid, track_dbid(by_id[tid]), pos, gid))
        gid += 1
    for sect in playlist_sections(root):
        p = find_playlist(root, sect, name)
        if is_master(p) or is_smart(p):
            raise ValueError('refusing to rewrite a master or smart playlist')
        p.children = [c for c in p.children if c.magic != b'mhip']
        for m in made:
            p.children.append(W.Node(b'mhip', bytes(m.hdr), m.body,
                                     [W.Node(c.magic, bytes(c.hdr), c.body) for c in m.children]))


# ---------------------------------------------------------------- tracks

def _drop_master_indexes(root):
    for sect in playlist_sections(root):
        for p in playlists(root, sect):
            if is_master(p):
                p.children = [c for c in p.children
                              if not (c.magic == b'mhod' and W.mhod_type(c) in (52, 53))]


def _fold(s):
    """Case- and accent-folded, the way the device keys artists: on this
    device "Beyonce" and "Beyoncé" share one artist id (295 keys, 295 ids)."""
    import unicodedata
    s = unicodedata.normalize('NFKD', s or '')
    return ''.join(c for c in s if not unicodedata.combining(c)).casefold().strip()


def _mhod_str(node, typ):
    for c in node.children:
        if c.magic == b'mhod' and W.mhod_type(c) == typ:
            return W.mhod_string(c)
    return ''


def _artist_ids(root):
    """folded (album artist, else artist) -> the artist id at mhit+0x1E0,
    the most common one where tracks disagree."""
    seen = {}
    for t in tracks(root):
        v = t.get32(0x1E0) if len(t.hdr) > 0x1E4 else 0
        if not v:
            continue
        k = _fold(_mhod_str(t, 22) or _mhod_str(t, 4))
        seen.setdefault(k, {})
        seen[k][v] = seen[k].get(v, 0) + 1
    return {k: max(c, key=c.get) for k, c in seen.items()}


def _album_ids(root):
    """(folded album, folded album artist or artist) -> mhia id. The same
    key the album list itself groups by (libgpod :5793-5815; 338 of 338
    entries match it on this device)."""
    out = {}
    s4 = W.section(root, 4)
    if s4 is None or not s4.children:
        return out
    for a in s4.children[0].children:
        if a.magic != b'mhia':
            continue
        alb = _mhod_str(a, 200)
        who = _mhod_str(a, 201) or _mhod_str(a, 202)
        out.setdefault((_fold(alb), _fold(who)), a.get32(0x10))
    return out


def _mhit_template(root, ext):
    """Clone from a track of the same container, chosen by its location's
    extension. That way fourcc (0x18), type1/type2 (0x1C) and the
    format-specific unknowns (0x90, 0x94, 0xCC) come from a record the
    firmware already plays, whatever their encoding turns out to be."""
    for t in tracks(root):
        loc = track_location(t) or ''
        if loc.lower().endswith(ext):
            return t
    raise RuntimeError('no existing %s track to clone from' % ext)


def track_add(root, meta, location):
    """meta: dict(ext, title, artist, album, genre, size, ms, bitrate, samplerate,
    track_no, year). location: ':iPod_Control:Music:F07:ABCD.mp3'"""
    ext = meta['ext']
    if ext not in SUPPORTED:
        raise ValueError('unsupported on stock firmware without conversion: %s' % ext)
    t = _mhit_template(root, ext)
    tid, gid = _next_ids(root)
    dbid = rand64()
    now = mac_now()
    m = W.Node(b'mhit', bytes(t.hdr))
    m.set32(0x10, tid)
    m.set32(0x14, 1)                          # visible
    m.hdr[0x1E] = 0                           # compilation
    m.hdr[0x1F] = 0                           # rating
    m.set32(0x20, now)                        # modified
    m.set32(0x24, meta['size'])
    m.set32(0x28, meta['ms'])
    m.set32(0x2C, meta.get('track_no') or 0)
    m.set32(0x30, 0)
    m.set32(0x34, meta.get('year') or 0)
    m.set32(0x38, meta['bitrate'])
    m.set32(0x3C, meta['samplerate'] << 16)
    for off in (0x40, 0x44, 0x48, 0x4C, 0x50, 0x54, 0x58):
        m.set32(off, 0)                       # volume, start/stop, soundcheck, plays, last played
    m.set32(0x5C, 0)
    m.set32(0x60, 0)
    m.set32(0x68, now)                        # date added
    m.set32(0x6C, 0)
    m.set64(0x70, dbid)
    m.set16(0x7C, 0)                          # artwork count
    m.set32(0x80, 0)                          # artwork size
    struct.pack_into('<f', m.hdr, 0x88, float(meta['samplerate']))
    m.set32(0x8C, 0)
    m.set32(0x9C, 0)
    m.set32(0xA0, 0)
    m.hdr[0xA4] = 2                           # has_artwork: 2 = none
    m.hdr[0xA7] = 0                           # not a podcast
    m.set64(0xA8, dbid)                       # dbid2
    m.set32(0xB8, 0)                          # gapless: pregap
    m.set64(0xBC, 0)                          #          sample count
    m.set32(0xC8, 0)                          #          postgap
    m.set32(0xD0, 1)                          # mediatype: audio
    if len(m.hdr) > 0xF8:
        m.set32(0xF8, 0)                      # gapless data (0 = off)
    if len(m.hdr) > 0x104:
        m.hdr[0x104:0x104 + 20] = bytes(20)   # unk39 hash, "not checked"
    if len(m.hdr) > 0x120:
        m.set32(0x120, 0)                     # album-list link: none
    if len(m.hdr) > 0x160:
        m.set32(0x160, 0)                     # ArtworkDB mhii link: none
    # IDENTITY, NOT INHERITANCE. The template is a real track, and every
    # field below used to arrive with that track's value on it -- one artist
    # id ended up covering about a hundred artists, two tracks shared a
    # 0x1F4, and new tracks were left out of the album list entirely, which
    # is the 89 extra albums the taxonomy sweep counted.
    if len(m.hdr) > 0x1F8:
        m.set32(0x1F4, tid + 1)               # track id + 1 on 653 of 653
    who = _fold(meta.get('album_artist') or meta.get('artist') or '')
    if len(m.hdr) > 0x1E4:
        ids = _artist_ids(root)
        # A FRESH id is one above EVERY id in use, not above the per-artist
        # map: a track can carry a minority id that the map does not keep,
        # and allocating under it would hand a new artist someone else's id
        # -- the pollution this exists to stop. Caught by its own test.
        used = [t.get32(0x1E0) for t in tracks(root) if len(t.hdr) > 0x1E4]
        m.set32(0x1E0, ids.get(who) or (max(used or [0]) + 1))
    if len(m.hdr) > 0x124:
        m.set32(0x120, _album_ids(root).get((_fold(meta.get('album') or ''), who), 0))
    m.hdr[0xB2] = 2                           # unplayed: iTunes' value on 443 of 481
    if meta.get('compilation'):
        m.hdr[0x1E] = 1
    if len(m.hdr) > GENIUS_ID:
        # A NEW TRACK HAS NO GENIUS IDENTITY. 0x1E4 holds the genius_id
        # that joins a track to its row in Extras.itdb -- measured, by
        # searching every mhit for the 63 ids in that database: 64 hits,
        # all at this offset, where 63 random integers of the same
        # magnitude produce none. The template is cloned from a track the
        # firmware already plays, and one such clone carried its donor's
        # genius_id onto a new track, pointing it at another song's
        # similarity row. The same inheritance that put one .mp3's size on
        # 177 records.
        m.set32(GENIUS_ID, 0)
    m.children = [
        W.make_string_mhod(1, meta.get('title') or os.path.basename(location)),
        W.make_string_mhod(2, location),
        W.make_string_mhod(3, meta.get('album') or ''),
        W.make_string_mhod(4, meta.get('artist') or ''),
        W.make_string_mhod(5, meta.get('genre') or ''),
        W.make_string_mhod(6, FILETYPE_STR[ext]),
    ]
    if meta.get('album_artist'):
        m.children.append(W.make_string_mhod(22, meta['album_artist']))
    tracks(root).append(m)
    # every track belongs to the master playlist, in both sections
    for sect in playlist_sections(root):
        for p in playlists(root, sect):
            if is_master(p):
                n = sum(1 for c in p.children if c.magic == b'mhip')
                p.children.append(_make_mhip(root, tid, dbid, n + 1, gid))
                gid += 1
    _drop_master_indexes(root)
    return tid


# The file size is written twice: at the documented 0x24 and again at
# 0x12C, which the format research does not name. Measured as an exact
# mirror on 653 of 653 tracks.
SIZE_MIRROR = 0x12C

# The Genius id, joining a track to its row in Extras.itdb. Undocumented in
# the format research; found by searching the header for ids read out of
# that database. See track_add.
GENIUS_ID = 0x1E4


def write_db(path, blob):
    """Write a database to the device and DO NOT RETURN until it is on the
    disk.

    THIS COST A LIBRARY. Two writes went out on 2 October, each verified
    by re-reading the file immediately afterwards -- and the re-read
    passed, because it was served from the page cache. The device was
    then unplugged without an eject, macOS had flushed only part of the
    second write, and the iPod showed an empty library: hash58 covers the
    whole file, so a file that is 94% written fails its own signature as
    surely as a corrupt one. Sound Check had landed on 619 of 653 tracks
    instead of 652; the tail never reached the platter.

    A plain `open(...).write(...)` hands bytes to the kernel and returns.
    That is a promise about memory, not about storage. `fsync` on the file
    forces the data out; `fsync` on the DIRECTORY forces the metadata that
    says how long the file now is -- both are needed, and the second is
    the one people forget.

    An eject is still worth doing, but it is now a courtesy rather than
    the thing standing between a write and a wiped library.
    """
    with open(path, 'wb') as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    d = os.open(os.path.dirname(path) or '.', os.O_RDONLY)
    try:
        os.fsync(d)
    finally:
        os.close(d)
    # Read it back from a fresh descriptor and compare. Cheap against a
    # 1.1 MB file, and it is the only check that would have caught this.
    with open(path, 'rb') as fh:
        back = fh.read()
    if back != blob:
        raise IOError('the database on disk is not what was written '
                      '(%d bytes out of %d)' % (len(back), len(blob)))
    return len(blob)


class WriteRefused(Exception):
    """A guarded write found a broken invariant and put the device back."""


def invariants(root, blob, guid, expect_tracks=None):
    """The checks every device database must pass after a write. Returns a
    list of failures; empty means sound.

    Each one is a way this device has actually broken, or a way the format
    research says it breaks, not a guess at what might matter:

      hash58            the empty-library trigger, seen on 2 October
      parses            a structurally broken file
      track count       a write that silently drops or duplicates tracks
      dangling refs     a playlist row naming a track that is not there
      stray group flag  a podcast group flag on an ordinary row -- the
                        format research says it "breaks iPods"
      one podcast list  two DIFFERENT flagged playlists show neither
    """
    from . import hash58 as _H
    bad = []
    if not _H.verify(blob, guid):
        bad.append('hash58 does not verify')
    try:
        r = W.parse(blob)
    except Exception as e:
        return bad + ['does not parse: %s' % e]
    ts = tracks(r)
    if expect_tracks is not None and len(ts) != expect_tracks:
        bad.append('track count %d, expected %d' % (len(ts), expect_tracks))
    ids = {track_id(t) for t in ts}
    flagged = set()
    for sect in playlist_sections(r):
        for p in playlists(r, sect):
            name = pl_name(p)
            if len(p.hdr) > 0x2C and struct.unpack_from('<H', p.hdr, 0x2A)[0]:
                flagged.add(name)
            for c in p.children:
                if c.magic != b'mhip':
                    continue
                tid = c.get32(0x18)
                is_header = c.get32(0x10) == 0x100
                if is_header:
                    if not (len(p.hdr) > 0x2C and struct.unpack_from('<H', p.hdr, 0x2A)[0]):
                        bad.append('group header in non-podcast playlist %r' % name)
                    continue
                if c.get32(0x10):
                    bad.append('stray group flag in %r' % name)
                if tid not in ids:
                    bad.append('%r names missing track %d' % (name, tid))
    if len(flagged) > 1:
        bad.append('%d different playlists carry the podcast flag: %s'
                   % (len(flagged), sorted(flagged)))
    # one line per kind of failure is enough to act on
    seen, out = set(), []
    for b in bad:
        k = b.split(' ')[0] + b.split(' ')[-1][:1]
        if b not in seen:
            seen.add(b); out.append(b)
    return out[:20]


def guarded_write(mount, mutate, guid, expect_track_delta=0, label='write'):
    """Change the device database safely enough to do it unsupervised.

        back up -> parse -> mutate -> serialise -> check invariants on the
        BLOB -> durable write -> re-read FROM DISK -> check again ->
        and if anything fails at any point after the write, put the
        original bytes back and check THOSE.

    Written for the night the owner was away from the machine: a write
    that breaks the library with nobody there to notice is the expensive
    case, so a broken write must undo itself rather than wait to be found.
    `mutate(root)` changes the tree in place and returns a summary.
    """
    from . import apply as _A
    dbp = os.path.join(mount, 'iPod_Control', 'iTunes', 'iTunesDB')
    original = open(dbp, 'rb').read()
    _A.backup(mount)
    before = len(tracks(W.parse(original)))
    root = W.parse(original)
    summary = mutate(root)
    blob = W.serialise(root, guid)
    want = before + expect_track_delta
    pre = invariants(root, blob, guid, want)
    if pre:
        raise WriteRefused('%s refused before writing: %s' % (label, '; '.join(pre)))
    try:
        write_db(dbp, blob)
        on_disk = open(dbp, 'rb').read()
        post = invariants(None, on_disk, guid, want)
        if post:
            raise WriteRefused('%s failed after writing: %s' % (label, '; '.join(post)))
    except Exception:
        write_db(dbp, original)
        restored = open(dbp, 'rb').read()
        if restored != original or invariants(None, restored, guid, before):
            raise WriteRefused('%s FAILED AND THE RESTORE DID NOT VERIFY -- '
                               'restore by hand from backups/' % label)
        raise
    return summary


def size_audit(root, mount):
    """Every track whose `mhit`+0x24 disagrees with the file on the device.

    0x24 is the file size in bytes and the format research marks it
    REQUIRED. Found wrong on 344 of 653 tracks on the owner's device, in
    two distinct shapes:

      178 tracks     all carrying 3629903 -- the size of the .mp3 the
                     template is cloned from, so the clone's value
                     survived instead of being replaced. Real sizes among
                     them run 750 KB to 127 MB. NINE OF THE TEN PODCASTS
                     are in this set, which is the leading explanation
                     for the Podcasts menu being slow every time it is
                     opened: the firmware is told a 113 MB episode is
                     3.6 MB.
      166 tracks     exactly 56 bytes too large, every one an .m4a added
                     by iTunes in March and retagged by saltpod since. A
                     tag write changed the file and nothing updated the
                     record.

    The cause of the first group is NOT yet found. `track_add` is the only
    code that writes 0x24 and it writes the probed size; the tracks had
    correct values in the 12:17 backup and the template's value in the
    12:31 one. Recorded as open rather than guessed at -- but the repair
    stands on its own, because it writes the measured truth either way.

    THE SIZE IS STORED TWICE. 0x12C mirrors 0x24 exactly -- on this device
    it equalled the pre-repair 0x24 on 653 of 653 tracks, so it is the same
    quantity written at the same moment, at an offset the format research
    does not name. The first repair fixed 0x24 alone and left 0x12C, which
    took the device from "two fields consistently wrong" to "two fields
    disagreeing on 344 tracks" -- arguably worse, since nobody knows which
    one the firmware reads. Both are checked and both are written.

    Returns [{'mhit', 'location', 'was', 'was_mirror', 'now', 'delta'}, ...].
    """
    out = []
    for t in tracks(root):
        loc = track_location(t) or ''
        rel = loc.lstrip(':').replace(':', os.sep)
        path = os.path.join(mount, rel)
        try:
            real = os.path.getsize(path)
        except OSError:
            continue
        was, mirror = t.get32(0x24), t.get32(SIZE_MIRROR)
        if was != real or mirror != real:
            out.append({'mhit': t, 'location': loc, 'was': was,
                        'was_mirror': mirror, 'now': real,
                        'delta': real - was})
    return out


def size_repair(root, mount):
    """Write the real file size into every track whose record disagrees.

    Writing a measured truth over a wrong value, so there is no judgement
    call here and nothing to rehearse beyond confirming the count.
    """
    rows = size_audit(root, mount)
    for r in rows:
        r['mhit'].set32(0x24, r['now'])
        r['mhit'].set32(SIZE_MIRROR, r['now'])
    return rows


def track_remove(root, tid):
    ts = tracks(root)
    hit = [t for t in ts if track_id(t) == tid]
    if not hit:
        raise KeyError('no track id %d' % tid)
    loc = track_location(hit[0])
    ts.remove(hit[0])
    for sect in playlist_sections(root):
        for p in playlists(root, sect):
            p.children = [c for c in p.children
                          if not (c.magic == b'mhip' and c.get32(0x18) == tid)]
    _drop_master_indexes(root)
    return loc
