#!/usr/bin/env python3
"""Read an iPod's iTunesDB: the file that decides what the device can see.

The stock firmware navigates by this database, not by the filesystem. A file
copied into iPod_Control/Music that has no entry here is invisible on the
device -- which is exactly why dragging files onto an iPod "doesn't work".

Format is a tree of chunks, each `4-byte magic | header_len | total_len`:

    mhbd  the database
      mhsd  a section (type 1 = tracks, 2/3 = playlists, 4 = albums...)
        mhlt  track list   -> mhit  track   -> mhod  a string field
        mhlp  playlist list-> mhyp  playlist-> mhip  an entry -> mhod

Read-only. Writing is a separate problem and a destructive one; nothing here
opens a file for writing.
"""
import os
import struct
import sys

# mhod string types that matter
MHOD = {1: 'title', 2: 'location', 3: 'album', 4: 'artist', 5: 'genre', 6: 'filetype',
        7: 'eq', 8: 'comment', 9: 'category', 12: 'composer', 13: 'grouping',
        14: 'desc', 50: 'smart_data', 51: 'smart_rules', 52: 'library_index',
        100: 'playlist_column'}


def _u32(b, o):
    return struct.unpack('<I', b[o:o + 4])[0]


def _chunk(b, o):
    """(magic, header_len, total_len) at offset o."""
    return b[o:o + 4], _u32(b, o + 4), _u32(b, o + 8)


def _read_mhod(b, o):
    """Return (type_name, value, total_len)."""
    magic, hl, tl = _chunk(b, o)
    if magic != b'mhod':
        return None, None, 0
    t = _u32(b, o + 12)
    name = MHOD.get(t, 'type%d' % t)
    if t in (1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 14, 200, 201, 202, 203):
        # string body at header+16: [unknown, byte_length, flag, unknown, data...]
        ln = _u32(b, o + hl + 4)
        raw = b[o + hl + 16: o + hl + 16 + ln]
        return name, _decode(raw), tl
    return name, None, tl


def _decode(raw):
    """Sniff UTF-16LE vs UTF-8 from the bytes.

    The word at header+8 looks like an encoding flag and is NOT one: this
    device writes 1 there while storing UTF-16LE. Trusting it yields strings
    with a NUL between every character, which is how 'AJ's iPod' turns into
    'A J  s   i P o d'. Sniffing is the only thing that has held.
    """
    if not raw:
        return ''
    if len(raw) % 2 == 0 and raw[1::2].count(0) > len(raw) // 4:
        try:
            return raw.decode('utf-16-le', 'replace').rstrip('\x00')
        except Exception:
            pass
    return raw.decode('utf-8', 'replace').rstrip('\x00')


def _tracks(b, o, count):
    out = []
    for _ in range(count):
        magic, hl, tl = _chunk(b, o)
        if magic != b'mhit':
            break
        n_mhod = _u32(b, o + 12)
        rec = {
            'id': _u32(b, o + 16),
            'visible': _u32(b, o + 20),
            'size': _u32(b, o + 36),
            'ms': _u32(b, o + 40),
            'track_no': _u32(b, o + 44),
            'year': _u32(b, o + 52),
            'bitrate': _u32(b, o + 56),
        }
        p = o + hl
        for _ in range(n_mhod):
            name, val, mtl = _read_mhod(b, p)
            if not mtl:
                break
            if val is not None:
                rec[name] = val
            p += mtl
        out.append(rec)
        o += tl
    return out, o


def _playlists(b, o, count):
    out = []
    for _ in range(count):
        magic, hl, tl = _chunk(b, o)
        if magic != b'mhyp':
            break
        n_mhod = _u32(b, o + 12)
        n_items = _u32(b, o + 16)
        is_master = _u32(b, o + 20)
        pl = {'name': None, 'master': bool(is_master), 'items': [], 'smart': False}
        p = o + hl
        for _ in range(n_mhod):
            name, val, mtl = _read_mhod(b, p)
            if not mtl:
                break
            if name == 'title' and val is not None:
                pl['name'] = val
            if name in ('smart_data', 'smart_rules'):
                pl['smart'] = True
            p += mtl
        for _ in range(n_items):
            m2, hl2, tl2 = _chunk(b, p)
            if m2 != b'mhip':
                break
            n_m = _u32(b, p + 12)
            pl['items'].append(_u32(b, p + 24))       # track id
            q = p + hl2
            for _ in range(n_m):
                _, _, mtl = _read_mhod(b, q)
                if not mtl:
                    break
                q += mtl
            p += tl2
        out.append(pl)
        o = p
    return out, o


def read(path):
    b = open(path, 'rb').read()
    if b[:4] != b'mhbd':
        raise ValueError('not an iTunesDB (magic %r)' % b[:4])
    _, hl, tl = _chunk(b, 0)
    db = {'version': _u32(b, 16), 'size': len(b), 'tracks': [], 'playlists': []}
    o = hl
    while o < len(b) - 12:
        magic, shl, stl = _chunk(b, o)
        if magic != b'mhsd':
            break
        typ = _u32(b, o + 12)
        inner = o + shl
        im, ihl, itl = _chunk(b, inner)
        n = _u32(b, inner + 8) if im in (b'mhlt', b'mhlp', b'mhla') else 0
        if im == b'mhlt':
            db['tracks'], _ = _tracks(b, inner + ihl, n)
        elif im == b'mhlp' and not db['playlists']:
            db['playlists'], _ = _playlists(b, inner + ihl, n)
        o += stl
    return db


def ipod_path(location, mount):
    """':iPod_Control:Music:F00:ABCD.mp3' -> an absolute path on the mount."""
    return os.path.join(mount, location.lstrip(':').replace(':', os.sep))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    arg = argv[0] if argv else '/Volumes/IPOD'
    # a mount point, or any file that is a database (patched copies have other names)
    path = arg if os.path.isfile(arg) else os.path.join(arg, 'iPod_Control/iTunes/iTunesDB')
    db = read(path)
    print('iTunesDB v%d  %.1f KB' % (db['version'], db['size'] / 1024))
    print('%d tracks, %d playlists\n' % (len(db['tracks']), len(db['playlists'])))

    for pl in db['playlists']:
        tag = ' (master)' if pl['master'] else (' (smart)' if pl['smart'] else '')
        print('  %-40s %4d%s' % ((pl['name'] or '?')[:40], len(pl['items']), tag))

    print('\nfirst 5 tracks:')
    for t in db['tracks'][:5]:
        print('  %-28s %-24s %5.1f MB  %s'
              % ((t.get('artist') or '?')[:28], (t.get('title') or '?')[:24],
                 t['size'] / 1e6, (t.get('location') or '')[-18:]))


if __name__ == '__main__':
    main()
