"""Writing the ArtworkDB, so covers already on disk reach the screen.

653 tracks on this device, 399 of them matched to a file that carries
cover art, and the device holds artwork for 259. The missing 140 are not
missing from anywhere except the iPod: the pictures are in the files, and
nothing has ever written the index that makes the firmware look.

THE SHAPE, measured rather than taken from a spec:

    mhfd
      mhsd type 1 -> mhli  -> mhii  x259      the images
      mhsd type 2 -> mhla  (0 entries)        albums
      mhsd type 3 -> mhlf  -> mhif  x3        the formats

    mhii   764 bytes, 4 children, uniform across all 259
      +0x10  image id          100..363 here, with gaps
      +0x14  song dbid (u64)   matches mhit+0x70; 253 of 259 match a
                               live track, the rest outlived their track
      mhod type 2 -> mhni      one per format
      mhod type 6 -> mhaf      sixty bytes, all zero in every entry

    mhni   140 bytes
      +0x10  correlation id    1055 / 1060 / 1061
      +0x14  OFFSET into the .ithmb
      +0x18  byte size         32768 / 204800 / 6160
      mhod type 3              ":F1055_1.ithmb" in UTF-16LE

CLONED, NEVER AUTHORED. Every new entry is a byte copy of one the
firmware already accepted on this device, with four numbers patched: the
image id, the song dbid, and the three offsets. That is the same rule the
iTunesDB writer follows, and the reason it has never produced an empty
library.

APPEND ONLY. The `.ithmb` files are only ever grown, so the undo is a
truncate back to the previous length plus the old ArtworkDB -- which
`rehearse()` records before touching anything.
"""

import contextlib
import os
import struct

from . import itunesdb_write as W


class ArtworkDBError(Exception):
    pass


@contextlib.contextmanager
def _artwork_grammar():
    """The parser is shared with the iTunesDB and the two use different
    container names, so the mapping is swapped in and put back."""
    lists, items = dict(W.LISTS), set(W.ITEMS_WITH_MHODS)
    W.LISTS.update({b'mhli': b'mhii', b'mhlf': b'mhif', b'mhla': b'mhaf'})
    W.ITEMS_WITH_MHODS.update({b'mhii', b'mhni'})
    try:
        yield
    finally:
        W.LISTS.clear(); W.LISTS.update(lists)
        W.ITEMS_WITH_MHODS.clear(); W.ITEMS_WITH_MHODS.update(items)


def parse(path):
    """The tree. Round-trips byte-identically -- a selftest check holds that."""
    raw = open(path, 'rb').read()
    if raw[:4] != b'mhfd':
        raise ArtworkDBError('not an ArtworkDB (magic %r)' % raw[:4])
    with _artwork_grammar():
        hl, tl = W.u32(raw, 4), W.u32(raw, 8)
        root = W.Node(b'mhfd', raw[:hl])
        o = hl
        while o < tl:
            shl, stl = W.u32(raw, o + 4), W.u32(raw, o + 8)
            sd = W.Node(b'mhsd', raw[o:o + shl])
            sd.children.append(W._parse_list(raw, o + shl, o + stl))
            root.children.append(sd)
            o += stl
    return root


def serialise(root):
    with _artwork_grammar():
        return W._ser(root)


def images(root):
    """The mhli holding the mhii entries."""
    for sd in root.children:
        for lst in sd.children:
            if lst.magic == b'mhli':
                return lst
    raise ArtworkDBError('no mhli in this database')


def formats(root):
    """{correlation id: image byte size} as the DEVICE declares them.

    Read, never assumed: a different iPod wants different sizes, and the
    byte count is the only thing that must be exactly right -- the firmware
    memory-maps these, so a wrong length corrupts every image after it.
    """
    out = {}
    for sd in root.children:
        for lst in sd.children:
            if lst.magic != b'mhlf':
                continue
            for f in lst.children:
                out[f.get32(0x10)] = f.get32(0x14)
    return out


def dbids(root):
    return {m.get32(0x14) | (m.get32(0x18) << 32) for m in images(root).children}


def _mhnis(mhii):
    """[(mhod, correlation id)] for each image reference in this entry.

    THE MHNI IS NOT A PARSED CHILD. The shared parser only descends into
    containers it knows, and an `mhod` inside an `mhii` is not one of them,
    so its `mhni` stays in the mhod's BODY as opaque bytes. Which is
    convenient rather than awkward: an entry is cloned byte for byte and
    only four numbers change, so reaching into the body to patch an offset
    is less surgery than parsing a level deeper would be.

    Body layout, measured: `mhni` at body+0, correlation id at body+0x10,
    offset into the .ithmb at body+0x14, byte size at body+0x18.
    """
    out = []
    for mhod in mhii.children:
        b = mhod.body
        if len(b) >= 0x1C and b[:4] == b'mhni':
            out.append((mhod, struct.unpack_from('<I', b, 0x10)[0]))
    return out


def clone(template, dbid, image_id, offsets):
    """A new mhii from one the firmware already took.

    `offsets` is {correlation id: byte offset into that .ithmb}.
    """
    import copy
    m = copy.deepcopy(template)
    m.set32(0x10, image_id)
    m.set32(0x14, dbid & 0xFFFFFFFF)
    m.set32(0x18, (dbid >> 32) & 0xFFFFFFFF)
    seen = set()
    for mhod, corr in _mhnis(m):
        if corr not in offsets:
            raise ArtworkDBError('no offset given for format %d' % corr)
        body = bytearray(mhod.body)
        struct.pack_into('<I', body, 0x14, offsets[corr])
        mhod.body = bytes(body)
        seen.add(corr)
    missing = set(offsets) - seen
    if missing:
        raise ArtworkDBError('the template has no mhni for format(s) %s'
                             % sorted(missing))
    return m


def next_image_id(root):
    ids = [m.get32(0x10) for m in images(root).children]
    return (max(ids) + 1) if ids else 100


def snapshot(artwork_dir, into):
    """Everything needed to undo an `add`, which is less than it sounds.

    The operation only ever APPENDS to the .ithmb files, so the undo is the
    previous ArtworkDB plus the previous lengths -- 199 KB and three
    integers, not the 63 MB of thumbnails. `apply.backup()` copies
    iPod_Control/iTunes and would not have covered any of this.
    """
    import json
    import shutil
    os.makedirs(into, exist_ok=True)
    shutil.copy2(os.path.join(artwork_dir, 'ArtworkDB'), into)
    lens = {}
    for name in sorted(os.listdir(artwork_dir)):
        if name.endswith('.ithmb') and not name.startswith('._'):
            lens[name] = os.path.getsize(os.path.join(artwork_dir, name))
    with open(os.path.join(into, 'ithmb-lengths.json'), 'w') as fh:
        json.dump({'artwork_dir': artwork_dir, 'lengths': lens}, fh, indent=1)
    return {'into': into, 'lengths': lens}


def restore(snapshot_dir, artwork_dir=None):
    """Put it back: truncate each .ithmb to the recorded length, restore the
    database. Exact, because nothing was ever overwritten."""
    import json
    import shutil
    meta = json.load(open(os.path.join(snapshot_dir, 'ithmb-lengths.json')))
    target = artwork_dir or meta['artwork_dir']
    for name, n in meta['lengths'].items():
        p = os.path.join(target, name)
        if os.path.exists(p) and os.path.getsize(p) > n:
            with open(p, 'r+b') as fh:
                fh.truncate(n)
    shutil.copy2(os.path.join(snapshot_dir, 'ArtworkDB'),
                 os.path.join(target, 'ArtworkDB'))
    return meta['lengths']


def add(artwork_dir, entries, db_name='ArtworkDB'):
    """Add covers. `entries` is [(dbid, {corr: rgb565})]. Returns a receipt.

    Writes the .ithmb files first and the database last, so an interruption
    leaves orphaned bytes at the end of an .ithmb -- which nothing reads,
    because nothing points at them -- rather than a database pointing at
    bytes that are not there.
    """
    db_path = os.path.join(artwork_dir, db_name)
    root = parse(db_path)
    want = formats(root)
    lst = images(root)
    if not lst.children:
        raise ArtworkDBError('no existing entry to clone; this writer does not '
                             'author one from the spec')
    template = lst.children[0]
    have = dbids(root)

    before = {c: os.path.getsize(os.path.join(artwork_dir, 'F%d_1.ithmb' % c))
              for c in want}
    added, skipped = [], []
    handles = {}
    try:
        for dbid, blobs in entries:
            if dbid in have:
                skipped.append((dbid, 'already has artwork'))
                continue
            if set(blobs) != set(want):
                skipped.append((dbid, 'has %s, the device wants %s'
                                % (sorted(blobs), sorted(want))))
                continue
            bad = [c for c in want if len(blobs[c]) != want[c]]
            if bad:
                skipped.append((dbid, 'wrong size for format(s) %s' % bad))
                continue
            offsets = {}
            for corr in sorted(want):
                fh = handles.get(corr)
                if fh is None:
                    fh = handles[corr] = open(
                        os.path.join(artwork_dir, 'F%d_1.ithmb' % corr), 'r+b')
                fh.seek(0, os.SEEK_END)
                offsets[corr] = fh.tell()
                fh.write(blobs[corr])
            lst.children.append(clone(template, dbid, next_image_id(root), offsets))
            have.add(dbid)
            added.append(dbid)
    finally:
        for fh in handles.values():
            fh.flush(); os.fsync(fh.fileno()); fh.close()

    if added:
        blob = serialise(root)
        tmp = db_path + '.tmp'
        with open(tmp, 'wb') as fh:
            fh.write(blob)
        os.replace(tmp, db_path)
    return {'added': added, 'skipped': skipped, 'before': before,
            'after': {c: os.path.getsize(os.path.join(artwork_dir, 'F%d_1.ithmb' % c))
                      for c in want}}
