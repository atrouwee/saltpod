"""On-The-Go playlists: the ones the owner made on the iPod itself.

A Classic lets you build a playlist with the click wheel -- hold Select on a
song -- and keeps it in `iPod_Control/iTunes/OTGPlaylistInfo` (and
`OTGPlaylistInfo_1`, `_2`, ... for saved ones). iTunes read those files on
the next sync, turned them into real playlists, and deleted them. saltpod
did not read them at all, so a sync that rewrote the database left them
naming whatever tracks now sat at those positions -- or the iPod discarded
them -- and the owner's own playlist was silently gone. TODO.md listed this
as "made on the device, silently dropped by a sync".

THE FORMAT, from libgpod (itdb_itunesdb.c:2762-2900, `process_OTG_file`):

    0x00  "mhpo"   (byte-reversed "opmh" on big-endian devices)
    0x04  header length   at least 0x14
    0x08  entry length    at least 4
    0x0C  entry count
    then  count entries, each starting with a u32 TRACK INDEX

POSITIONAL, LIKE PLAY COUNTS. An entry is the n-th track of the database as
it was when the list was made, not a track id. Paired with a later database
the same number names a different song, so `read()` takes the database
path as well and refuses an index that does not exist, and sync reads these
files before it replaces the database they belong to.

Imported lists become saltpod collections named "On-The-Go <date>", and a
fingerprint of exactly what was imported is recorded so the same file is
never imported twice -- the same ledger idea as the play-count merge.
"""
import hashlib
import os
import struct
import time

from . import itunesdb as I
from . import state as S

LEDGER = 'otg_adopted'


class OTGError(Exception):
    """An On-The-Go file that cannot be read safely."""


def find(mount):
    """The On-The-Go files on the device, in the order the iPod numbers them."""
    d = os.path.join(mount, 'iPod_Control', 'iTunes')
    out = []
    first = os.path.join(d, 'OTGPlaylistInfo')
    if os.path.exists(first):
        out.append(first)
    i = 1
    while True:
        p = os.path.join(d, 'OTGPlaylistInfo_%d' % i)
        if not os.path.exists(p):
            break
        out.append(p)
        i += 1
    return out


def fingerprint(path):
    with open(path, 'rb') as fh:
        return hashlib.sha1(fh.read()).hexdigest()


def parse(path):
    """The track indices in one On-The-Go file, in playlist order."""
    with open(path, 'rb') as fh:
        b = fh.read()
    if b[:4] == b'mhpo':
        end = '<'
    elif b[:4] == b'opmh':
        end = '>'
    else:
        raise OTGError('%s is not an On-The-Go file (no mhpo header)' % path)
    if len(b) < 16:
        raise OTGError('%s is too short to hold a header' % path)
    hlen, elen, count = struct.unpack_from(end + 'III', b, 4)
    if hlen < 0x14 or elen < 4:
        raise OTGError('%s has a header or entry length smaller than any '
                       'known file (%d, %d)' % (path, hlen, elen))
    out = []
    for i in range(count):
        o = hlen + elen * i
        if o + 4 > len(b):
            raise OTGError('%s says %d entries but ends after %d' % (path, count, i))
        out.append(struct.unpack_from(end + 'I', b, o)[0])
    return out


def read(path, db_path):
    """Entries paired with the tracks they name, against `db_path`.

    Refuses an index past the end of the track list rather than guessing:
    that means this file does not belong to this database, and every row it
    produced would be plausible and wrong.
    """
    idx = parse(path)
    tracks = I.read(db_path)['tracks']
    out = []
    for n in idx:
        if n >= len(tracks):
            raise OTGError('%s names track %d and the database has %d -- they '
                           'are not from the same moment' % (path, n, len(tracks)))
        t = tracks[n]
        out.append({'index': n, 'track_id': t.get('id'),
                    'artist': t.get('artist'), 'title': t.get('title')})
    return out


def adopt(st, mount, db_path=None, when=None):
    """Import every not-yet-imported On-The-Go file as a collection.

    Returns [(name, tracks)]. Changes nothing for a file already imported.
    """
    db_path = db_path or os.path.join(mount, 'iPod_Control', 'iTunes', 'iTunesDB')
    seen = st.setdefault(LEDGER, [])
    day = time.strftime('%Y-%m-%d', time.localtime(when or time.time()))
    made = []
    for path in find(mount):
        fp = fingerprint(path)
        if fp in seen:
            continue
        rows = read(path, db_path)
        seen.append(fp)
        if not rows:
            continue
        name, n = 'On-The-Go %s' % day, 2
        while name in (st.get('collections') or []):
            name = 'On-The-Go %s (%d)' % (day, n)
            n += 1
        keys = []
        for r in rows:
            k = S.key_for(r['artist'], r['title'])
            rec = st['tracks'].setdefault(k, S.blank(r['artist'], r['title']))
            if name not in rec['collections']:
                rec['collections'].append(name)
            keys.append(k)
        st.setdefault('collections', []).append(name)
        S.set_order(st, name, keys)
        made.append((name, len(keys)))
    return made


def write_file(path, indices):
    """An On-The-Go file holding `indices` -- for tests and fixtures; the
    device writes the real ones."""
    body = b''.join(struct.pack('<I', i) for i in indices)
    head = b'mhpo' + struct.pack('<IIII', 0x14, 4, len(indices), 0)
    with open(path, 'wb') as fh:
        fh.write(head + body)
