#!/usr/bin/env python3
"""A lossless tree model of an iTunesDB, for editing it without regenerating it.

Every chunk becomes a Node holding its ORIGINAL header bytes and, for leaves,
its original body. Serialising an unmodified tree reproduces the file byte for
byte -- that is the first test and the whole point: fields nobody has
documented (mhit 0x184-0x270, mhod 37/43/44/102, mhsd 9) travel through
untouched, and only the lengths and counts we recompute change.

Container rules (which chunk owns which children) follow the file itself:
    mhbd -> mhsd*            mhsd -> one list (mhlt|mhlp|mhla|...)
    mhlt -> mhit*            mhit -> mhod*
    mhlp -> mhyp*            mhyp -> mhod* then mhip*      mhip -> mhod*
    mhla -> mhia*            mhia -> mhod*
Anything else (mhsd type 9 and unknown lists) is kept as an opaque blob.

Counts recomputed on serialise: mhbd+0x14 (n mhsd; +0x10 is the version), mhlt/mhlp/mhla +0x08,
mhit+0x0C (mhods), mhyp+0x0C (mhods BEFORE the first mhip) and +0x10 (mhips),
mhip+0x0C (mhods). Lengths: header_len untouched; total_len = header + children.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
from . import hash58  # noqa: E402

LISTS = {b'mhlt': b'mhit', b'mhlp': b'mhyp', b'mhla': b'mhia'}
ITEMS_WITH_MHODS = {b'mhit', b'mhia', b'mhip'}


def u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


class Node:
    __slots__ = ('magic', 'hdr', 'body', 'children')

    def __init__(self, magic, hdr, body=b'', children=None):
        self.magic, self.hdr, self.body = magic, bytearray(hdr), bytes(body)
        self.children = children if children is not None else []

    def get32(self, off):
        return struct.unpack_from('<I', self.hdr, off)[0]

    def set32(self, off, v):
        struct.pack_into('<I', self.hdr, off, v)

    def set16(self, off, v):
        struct.pack_into('<H', self.hdr, off, v)

    def set64(self, off, v):
        struct.pack_into('<Q', self.hdr, off, v)

    def find(self, magic):
        return [c for c in self.children if c.magic == magic]

    def __repr__(self):
        return '<%s hdr=%d body=%d kids=%d>' % (self.magic.decode(), len(self.hdr),
                                                  len(self.body), len(self.children))


# ------------------------------------------------------------------ parse

def _parse_item(b, o, magic_expected):
    magic, hl, tl = b[o:o + 4], u32(b, o + 4), u32(b, o + 8)
    if magic != magic_expected:
        raise ValueError('expected %r at %d, got %r' % (magic_expected, o, magic))
    node = Node(magic, b[o:o + hl])
    p = o + hl
    end = o + tl
    if magic == b'mhyp':
        # mhods then mhips; the header counts them separately
        n_mhod, n_mhip = u32(b, o + 0x0C), u32(b, o + 0x10)
        for _ in range(n_mhod):
            c, p = _parse_mhod(b, p)
            node.children.append(c)
        for _ in range(n_mhip):
            c, p = _parse_item(b, p, b'mhip')
            node.children.append(c)
    elif magic in ITEMS_WITH_MHODS:
        for _ in range(u32(b, o + 0x0C)):
            c, p = _parse_mhod(b, p)
            node.children.append(c)
    if p != end:
        # keep anything unexpected rather than lose it
        node.body = b[p:end]
    return node, end


def _parse_mhod(b, o):
    magic, hl, tl = b[o:o + 4], u32(b, o + 4), u32(b, o + 8)
    if magic != b'mhod':
        raise ValueError('expected mhod at %d, got %r' % (o, magic))
    return Node(magic, b[o:o + hl], b[o + hl:o + tl]), o + tl


def _parse_list(b, o, end):
    magic, hl, tl = b[o:o + 4], u32(b, o + 4), u32(b, o + 8)
    item = LISTS.get(magic)
    if item is None:
        # Opaque payload (mhsd 9 holds a Genius CUID, not a chunk). Its first
        # words are NOT a header -- reading a header_len out of them and then
        # stamping a total_len back in corrupted 3 bytes near EOF. Raw, untouched.
        return Node(magic, b'', b[o:end])
    node = Node(magic, b[o:o + hl])
    p = o + hl
    for _ in range(u32(b, o + 8)):
        c, p = _parse_item(b, p, item)
        node.children.append(c)
    if p != end:
        node.body = b[p:end]
    return node


def parse(data):
    b = bytes(data)
    if b[:4] != b'mhbd':
        raise ValueError('not an iTunesDB')
    hl, tl = u32(b, 4), u32(b, 8)
    root = Node(b'mhbd', b[:hl])
    o = hl
    while o < tl:
        m, shl, stl = b[o:o + 4], u32(b, o + 4), u32(b, o + 8)
        if m != b'mhsd':
            raise ValueError('expected mhsd at %d, got %r' % (o, m))
        sd = Node(b'mhsd', b[o:o + shl])
        sd.children.append(_parse_list(b, o + shl, o + stl))
        root.children.append(sd)
        o += stl
    return root


# -------------------------------------------------------------- serialise

def _ser(node):
    kids = b''.join(_ser(c) for c in node.children) + node.body
    if not node.hdr:                       # opaque payload: emit verbatim
        return kids
    hdr = bytearray(node.hdr)
    m = node.magic
    if m == b'mhbd':
        struct.pack_into('<I', hdr, 0x14, len(node.children))    # 0x10 is the version
    elif m in LISTS:
        struct.pack_into('<I', hdr, 0x08, len(node.children))
    elif m == b'mhyp':
        n_mhod = sum(1 for c in node.children if c.magic == b'mhod')
        n_mhip = sum(1 for c in node.children if c.magic == b'mhip')
        struct.pack_into('<I', hdr, 0x0C, n_mhod)
        struct.pack_into('<I', hdr, 0x10, n_mhip)
    elif m in ITEMS_WITH_MHODS:
        struct.pack_into('<I', hdr, 0x0C, len(node.children))
    # List headers (mhlt/mhlp/mhla) carry a COUNT at +0x08, not a total_len:
    # they are `magic, header_len, count` and nothing spans their children.
    if m not in LISTS:
        struct.pack_into('<I', hdr, 0x08, len(hdr) + len(kids))
    return bytes(hdr) + kids


def serialise(root, guid=None):
    out = _ser(root)
    return hash58.sign(out, guid) if guid else out


# ------------------------------------------------------------- helpers

def section(root, typ):
    for sd in root.children:
        if sd.get32(0x0C) == typ:
            return sd
    return None


def mhod_string(n):
    """Decode a string mhod's text (body words: unk, byte_len, unk, unk, data)."""
    ln = u32(n.body, 4)
    return n.body[16:16 + ln].decode('utf-16-le', 'replace')


def mhod_type(n):
    return n.get32(0x0C)


def make_string_mhod(typ, text):
    raw = text.encode('utf-16-le')
    hdr = b'mhod' + struct.pack('<III', 24, 0, typ) + bytes(8)
    body = struct.pack('<IIII', 1, len(raw), 1, 0) + raw
    return Node(b'mhod', hdr, body)


if __name__ == '__main__':
    path = sys.argv[1]
    data = open(path, 'rb').read()
    root = parse(data)
    out = serialise(root)
    print('parsed: %d sections; tracks %d; playlists %d'
          % (len(root.children),
             len(section(root, 1).children[0].children),
             len(section(root, 2).children[0].children)))
    print('round-trip byte-identical: %s' % (out == data))
    if out != data:
        i = next(i for i in range(min(len(out), len(data))) if out[i] != data[i])
        print('first difference at 0x%x  (%d vs %d bytes)' % (i, len(out), len(data)))
