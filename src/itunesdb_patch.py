#!/usr/bin/env python3
"""Surgical, in-place edits to an existing iTunesDB -- the safest way to write.

Rather than regenerating the whole database (which is where every third-party
tool's fidelity problems come from), this keeps the iTunes-written file exactly
as it is and changes only the bytes that must change, then fixes the chain of
enclosing `total_len` fields and re-signs with hash58.

Everything stays: track IDs, dbids, smart playlists, iTunes-Store mhods, the
hash72 block, sort orders. If the firmware accepts the result, the ONLY
variables in the experiment are our edit and our checksum.

    python3 src/itunesdb_patch.py rename-playlist <db> <GUID> "<old>" "<new>" [--out FILE]

Never writes to the input unless --out is the same path. Verify the output
with `python3 src/itunesdb.py <file>` and `python3 src/hash58.py verify`.
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hash58  # noqa: E402

OFF_UNK70, OFF_HASH72 = 0x70, 0x72       # hash72 scheme word + 46-byte block


def neutralise_hash72(b):
    """Zero the hash72 block, as libgpod does for every Classic.

    iTunes writes 0x70=3 and a 46-byte hash72 signature at 0x72. After an edit
    that signature is STALE -- it covered the old content -- and a stale
    signature is a configuration nobody has ever tested against the firmware.
    Zeros are: libgpod has shipped them to Classics for 15 years via gtkpod.
    So the patched file matches the one combination with field evidence.
    """
    b[OFF_UNK70:OFF_UNK70 + 2] = b'\x00\x00'
    b[OFF_HASH72:OFF_HASH72 + 46] = bytes(46)


def _u32(b, o):
    return struct.unpack('<I', b[o:o + 4])[0]


def _put32(b, o, v):
    b[o:o + 4] = struct.pack('<I', v)


def _chunk(b, o):
    return bytes(b[o:o + 4]), _u32(b, o + 4), _u32(b, o + 8)


def walk_playlists(b):
    """Yield (mhyp_off, [enclosing chunk offsets], title_mhod_off) per playlist.

    The enclosing list is every chunk whose total_len covers the mhyp:
    mhbd -> mhsd -> mhlp(header only, its total_len is just the header)
    """
    _, hl, _ = _chunk(b, 0)
    o = hl
    while o < len(b) - 12:
        m, shl, stl = _chunk(b, o)
        if m != b'mhsd':
            break
        typ = _u32(b, o + 12)
        inner = o + shl
        im, ihl, itl = _chunk(b, inner)
        if im == b'mhlp' and typ in (2, 3):
            n = _u32(b, inner + 8)
            p = inner + ihl
            for _ in range(n):
                ym, yhl, ytl = _chunk(b, p)
                if ym != b'mhyp':
                    break
                n_mhod = _u32(b, p + 12)
                q = p + yhl
                title_off = None
                for _ in range(n_mhod):
                    dm, dhl, dtl = _chunk(b, q)
                    if dm != b'mhod':
                        break
                    if _u32(b, q + 12) == 1 and title_off is None:
                        title_off = q
                    q += dtl
                yield p, [0, o], title_off, typ
                p += ytl
        o += stl


def mhod_string(b, o):
    _, hl, tl = _chunk(b, o)
    ln = _u32(b, o + hl + 4)
    raw = bytes(b[o + hl + 16:o + hl + 16 + ln])
    return raw.decode('utf-16-le', 'replace')


def rename_playlist(data, guid, old, new, keep_hash72=False):
    b = bytearray(data)
    hits = [(y, enc, t, typ) for y, enc, t, typ in walk_playlists(b)
            if t is not None and mhod_string(b, t) == old]
    if not hits:
        raise SystemExit('no playlist named %r' % old)
    # iTunes stores each regular playlist twice (mhsd type 2 and type 3);
    # rename every occurrence or the firmware sees two different names.
    hits.sort(key=lambda h: h[2], reverse=True)   # patch from the end: earlier offsets stay valid
    new_raw = new.encode('utf-16-le')
    for mhyp, enclosing, t, typ in hits:
        _, hl, tl = _chunk(b, t)
        old_ln = _u32(b, t + hl + 4)
        delta = len(new_raw) - old_ln
        b[t + hl + 16:t + hl + 16 + old_ln] = new_raw
        _put32(b, t + hl + 4, len(new_raw))
        _put32(b, t + 8, tl + delta)                        # mhod total_len
        _put32(b, mhyp + 8, _u32(b, mhyp + 8) + delta)      # mhyp total_len
        for e in enclosing:                                 # mhbd, mhsd total_len
            _put32(b, e + 8, _u32(b, e + 8) + delta)
    if not keep_hash72:
        neutralise_hash72(b)
    return hash58.sign(bytes(b), guid), len(hits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['rename-playlist'])
    ap.add_argument('db')
    ap.add_argument('guid')
    ap.add_argument('old')
    ap.add_argument('new')
    ap.add_argument('--out', help='output path (default: <db>.patched)')
    ap.add_argument('--keep-hash72', action='store_true',
                    help='leave the stale iTunes hash72 block in place (untested config)')
    a = ap.parse_args()
    data = open(a.db, 'rb').read()
    out, n = rename_playlist(data, a.guid, a.old, a.new, keep_hash72=a.keep_hash72)
    dest = a.out or (a.db + '.patched')
    open(dest, 'wb').write(out)
    print('renamed %d occurrence(s) of %r -> %r' % (n, a.old, a.new))
    print('%d -> %d bytes, hash58 %s' % (len(data), len(out),
          'OK' if hash58.verify(out, a.guid) else 'BAD'))
    print('written: %s' % dest)


if __name__ == '__main__':
    main()
