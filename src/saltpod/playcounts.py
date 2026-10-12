"""The `Play Counts` sidecar: what the iPod played while it was away.

THE IPOD DOES NOT UPDATE `play count` IN THE ITUNESDB. It writes plays into
`iPod_Control/iTunes/Play Counts` instead, and iTunes used to read that
file, ADD the counts to the library's running total, and delete it. So the
number you saw in iTunes was always desktop plays plus iPod plays -- one
number, two sources, merged by deletion.

WE NEVER DELETE IT. The device rebuilds the file itself whenever it sees a
changed iTunesDB, so deleting is unnecessary, and a delta that has been
consumed and later found to be wrong cannot be got back. Each merge records
a fingerprint of exactly what it consumed instead, and a sidecar whose
fingerprint has been seen is skipped rather than counted twice.

POSITIONAL, AND THAT IS THE TRAP. Entry i belongs to the i-th `mhit` of the
iTunesDB AS IT WAS WHEN THE SIDECAR WAS WRITTEN. Paired with a later
database the same bytes name a different track -- measured on this drive, a
backup's sidecar reads "The Beatles -- Her Majesty, 3 plays" against its own
database and "2 Many Dj's -- Disc Jockey's Delight" against today's, with
nothing to suggest anything is wrong. So `read()` takes BOTH paths and
refuses outright when the entry count and the track count disagree.

Layout, confirmed against seven real sidecars in backups/:

    header   'mhdp'  header_len=0x60  entry_len=0x1C  entry_count
    entry    0x00 u32 play count       0x04 u32 last played (Mac time)
             0x08 u32 bookmark ms      0x0C u32 rating (stars x 20)
             0x10 u32 unknown          0x14 u32 skip count
             0x18 u32 last skipped (Mac time)

All little-endian, like the rest of the database.
"""

import hashlib
import os
import struct

from . import itunesdb as I


class PlayCountError(Exception):
    pass


def fingerprint(path):
    """What `merge` records so the same delta is never counted twice."""
    with open(path, 'rb') as fh:
        return hashlib.sha1(fh.read()).hexdigest()


def parse(path):
    """[{plays, last_played, bookmark_ms, rating, skips, last_skipped}] in order."""
    with open(path, 'rb') as fh:
        b = fh.read()
    if b[:4] != b'mhdp':
        raise PlayCountError('not a Play Counts file (magic %r)' % b[:4])
    hl, elen, n = struct.unpack('<III', b[4:16])
    if elen < 16:
        raise PlayCountError('entry length %d is too short to read' % elen)
    out = []
    for i in range(n):
        o = hl + i * elen
        e = b[o:o + elen]
        if len(e) < 16:
            break
        plays, last, bookmark, rating = struct.unpack('<IIII', e[0:16])
        skips = struct.unpack('<I', e[20:24])[0] if elen >= 24 else 0
        skipped = struct.unpack('<I', e[24:28])[0] if elen >= 28 else 0
        out.append({
            'plays': plays,
            'last_played': I._mactime(last),
            'bookmark_ms': bookmark,
            'rating': rating,
            'skips': skips,
            'last_skipped': I._mactime(skipped),
        })
    return out


def read(sidecar, db_path):
    """Entries paired with the tracks they actually describe.

    Refuses rather than guesses: the pairing is positional, so a count
    mismatch means this sidecar does not belong to this database and every
    row it produced would be plausible and wrong.
    """
    rows = parse(sidecar)
    tracks = I.read(db_path)['tracks']
    if len(rows) != len(tracks):
        raise PlayCountError(
            'this sidecar has %d entries and that database has %d tracks, so '
            'they are not from the same moment -- pairing them would name the '
            'wrong tracks' % (len(rows), len(tracks)))
    out = []
    for i, (r, t) in enumerate(zip(rows, tracks)):
        if not (r['plays'] or r['rating'] or r['skips'] or r['bookmark_ms']):
            continue
        out.append(dict(r, index=i, track_id=t.get('id'),
                        artist=t.get('artist'), title=t.get('title')))
    return out


def find(mount):
    """The sidecar on a mounted device, or None. It is often simply absent:
    the iPod only writes one once something has been played."""
    p = os.path.join(mount, 'iPod_Control', 'iTunes', 'Play Counts')
    return p if os.path.exists(p) else None


def main(argv=None):
    import sys
    a = (argv if argv is not None else sys.argv[1:])
    if not a:
        print('usage: python3 -m saltpod.playcounts <Play Counts> [iTunesDB]')
        return 2
    sidecar = a[0]
    db = a[1] if len(a) > 1 else os.path.join(os.path.dirname(sidecar), 'iTunesDB')
    rows = read(sidecar, db)
    print('%-30s %-30s %6s %5s  %s' % ('artist', 'title', 'plays', 'stars', 'last played'))
    import datetime
    for r in sorted(rows, key=lambda x: -x['plays']):
        lp = (datetime.datetime.fromtimestamp(r['last_played']).strftime('%Y-%m-%d %H:%M')
              if r['last_played'] else '-')
        print('%-30s %-30s %6d %5s  %s'
              % (str(r['artist'])[:30], str(r['title'])[:30], r['plays'],
                 r['rating'] // 20 if r['rating'] else '-', lp))
    print('\n%d entries carry something; fingerprint %s' % (len(rows), fingerprint(sidecar)[:16]))
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())


# ------------------------------------------------------------------ merging
#
# WHAT ITUNES DID, MINUS THE DELETION. The sidecar is a DELTA: three plays
# since it was last cleared, not three plays ever. iTunes added it to the
# library total and deleted the file, which is why the number you saw in
# iTunes was desktop plays plus iPod plays.
#
# We add the same way and leave the file alone. The device clears it itself
# the moment it sees a changed iTunesDB, so deleting buys nothing -- and a
# delta consumed wrongly cannot be got back. The ledger below is what stops
# the same delta being added twice: a sidecar is identified by the sha1 of
# its bytes, and one already in the ledger is skipped.

LEDGER = 'playcounts_merged'          # list of fingerprints, in state


LAST = 'playcounts_last'


def merge(st, rows, fp, when=None, entries=None):
    """Add a sidecar's delta into state. Returns what it did, and changes
    nothing when this exact file has already been counted.

    THE SIDECAR GROWS, AND THE FINGERPRINT LEDGER DID NOT KNOW IT. The iPod
    keeps adding to `Play Counts` until something clears it, and saltpod by
    design never does -- so a file merged at 22:20 was still there the next
    morning with one more play in it. A new fingerprint looked like a fresh
    delta, and the whole file was added again: 10 plays where 1 was new,
    nine counted twice. Measured against the two sidecars, corrected in
    state on 3 October.

    So the last file merged is remembered entry by entry, and a later file
    from the same lineage -- same number of entries, nothing gone DOWN --
    contributes only what rose since. A file that is shorter, or where any
    count fell, is a new file the iPod started fresh, and counts in full.
    `entries` is the sidecar's total entry count (rows only carries the
    non-zero ones).
    """
    import datetime
    seen = st.setdefault(LEDGER, [])
    if fp in seen:
        return {'ok': True, 'skipped': 'already counted', 'added': 0, 'tracks': 0}
    from . import state as S
    last = st.get(LAST) or {}
    prev_p = {int(k): v for k, v in (last.get('plays') or {}).items()}
    prev_s = {int(k): v for k, v in (last.get('skips') or {}).items()}
    cur_p = {r['index']: r['plays'] for r in rows if 'index' in r}
    cur_s = {r['index']: r['skips'] for r in rows if 'index' in r}
    same_lineage = (bool(last) and entries is not None and last.get('entries') == entries
                    and all(cur_p.get(i, 0) >= v for i, v in prev_p.items())
                    and all(cur_s.get(i, 0) >= v for i, v in prev_s.items()))
    if same_lineage:
        rows = [dict(r, plays=r['plays'] - prev_p.get(r['index'], 0),
                     skips=r['skips'] - prev_s.get(r['index'], 0)) for r in rows]
    added = touched = 0
    for r in rows:
        key = S.key_for(r.get('artist'), r.get('title'))
        rec = st['tracks'].get(key)
        if not rec:
            continue                   # not curated here; nothing to add it to
        if r['plays']:
            rec['plays'] = (rec.get('plays') or 0) + r['plays']
            added += r['plays']
            touched += 1
        # THESE ARE STATES, NOT DELTAS, so they are replaced rather than
        # summed -- adding two ratings together would be nonsense.
        if r['rating']:
            rec['rating'] = r['rating'] // 20
        if r['last_played'] and r['last_played'] > _unix(rec.get('last_played')):
            rec['last_played'] = r['last_played']
        if r['bookmark_ms']:
            rec['bookmark_ms'] = r['bookmark_ms']
        if r['skips']:
            rec['skips'] = (rec.get('skips') or 0) + r['skips']
        if r.get('last_skipped') and r['last_skipped'] > (rec.get('last_skipped') or 0):
            rec['last_skipped'] = r['last_skipped']
    seen.append(fp)
    del seen[:-200]                    # a ledger, not an archive
    st[LAST] = {'fp': fp, 'entries': entries,
                'plays': {str(i): v for i, v in cur_p.items() if v},
                'skips': {str(i): v for i, v in cur_s.items() if v}}
    st.setdefault('playcounts_log', []).append({
        'at': (when or datetime.datetime.now()).isoformat(timespec='seconds'),
        'fingerprint': fp, 'plays_added': added, 'tracks': touched,
    })
    del st['playcounts_log'][:-50]
    return {'ok': True, 'added': added, 'tracks': touched,
            'mode': 'delta' if same_lineage else 'full'}


def adopt_db_counts(st, db_path):
    """Take the counts iTunes itself left in the iTunesDB.

    A ONE-OFF, NOT A DELTA. These are totals iTunes wrote years ago -- 69 of
    653 tracks on this device, 197 plays reaching back to 2018 -- and they
    are the floor our own counting starts from. Only ever raises a number,
    so running it twice cannot inflate anything.
    """
    from . import state as S
    taken = 0
    for t in I.read(db_path)['tracks']:
        key = S.key_for(t.get('artist'), t.get('title'))
        rec = st['tracks'].get(key)
        if not rec:
            continue
        if (t.get('play_count') or 0) > (rec.get('plays') or 0):
            rec['plays'] = t['play_count']
            taken += 1
        # _unix: a record's date may be an ISO string (the fixture's form)
        if (t.get('last_played') or 0) > _unix(rec.get('last_played')):
            rec['last_played'] = t['last_played']
        if t.get('rating') and not rec.get('rating'):
            rec['rating'] = t['rating'] // 20
    return taken


# ------------------------------------------------------------- writing back
#
# THE OTHER HALF OF WHAT ITUNES DID. iTunes added the sidecar into each
# track's own fields and wrote the database back, so the device's Most
# Played, Recently Played and every smart list reading a play count saw the
# whole history. saltpod merged into state only -- 324 plays on 168 tracks
# existed nowhere on the device (research/TAXONOMY.md, ranked fix 2). This
# puts them back, into the fields libgpod writes (itdb_itunesdb.c
# :2730-2752; offsets in research/itunesdb-format.md):
#
#     0x50 play count     0x58 last played (Mac time)
#     0x9C skip count     0xA0 last skipped (Mac time)
#     0x1F rating (stars x 20)
#
# NEVER LOWER. A count or a date on the device that is already higher than
# state's stays: state's `plays` is the adopted floor plus every merged
# sidecar, so it is never below an honest device value, and if it is, the
# device knows something state does not. A rating is a state, not a count:
# state's replaces the device's when state has one (a rating made on the
# click wheel arrives through the sidecar and is in state already).
#
# What is NOT written: 0x54 ("play count 2", whose meaning the format notes
# do not settle) and 0xB2 (the unplayed mark), both left as they are; and
# Apple Music's counts, which are `plays overall`, not the iPod's own.

WRITEBACK = (('plays', 0x50, False), ('last_played', 0x58, True),
             ('skips', 0x9C, False), ('last_skipped', 0xA0, True))
RATING = 0x1F


def _unix(v):
    """A state value as unix seconds: an int, or an ISO date (the fixture's
    and some early records' form), or nothing."""
    from . import listening as _L
    return _L._epoch(v)


def writeback_rows(st, root):
    """What `saltpod plays write` would change, track by track. Pure: reads
    the tree, changes nothing. Each row: {mhit, id, artist, title, was, now},
    `was` and `now` keyed plays, last_played, skips, last_skipped (unix) and
    rating (stars)."""
    from . import ipod_edit as E, state as S
    out = []
    for t in E.tracks(root):
        if len(t.hdr) < 0xA4:
            continue                   # a header too short to hold the fields
        artist, title = E._mhod_str(t, 4), E._mhod_str(t, 1)
        rec = st['tracks'].get(S.key_for(artist, title))
        if not rec:
            continue
        was = {}
        for f, off, is_date in WRITEBACK:
            v = t.get32(off)
            was[f] = (I._mactime(v) or 0) if is_date else v
        was['rating'] = t.hdr[RATING] // 20
        now = dict(was)
        for f, _off, _d in WRITEBACK:
            v = _unix(rec.get(f)) if _d else int(rec.get(f) or 0)
            if v > now[f]:
                now[f] = v
        r = rec.get('rating')
        if r and 0 < int(r) <= 5:
            now['rating'] = int(r)
        if now != was:
            out.append({'mhit': t, 'id': E.track_id(t), 'artist': artist, 'title': title,
                        'was': was, 'now': now})
    return out


def writeback_apply(rows):
    """Put each row's `now` into its mhit. Returns the rows."""
    for r in rows:
        t, n = r['mhit'], r['now']
        for f, off, is_date in WRITEBACK:
            t.set32(off, (n[f] + I.MAC_EPOCH) if (is_date and n[f]) else n[f])
        t.hdr[RATING] = n['rating'] * 20
    return rows
