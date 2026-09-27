#!/usr/bin/env python3
"""hash58: the checksum an iPod Classic requires in its iTunesDB header.

Without a valid hash58 the Classic firmware treats the database as corrupt and
shows an empty library. This is the ONLY thing standing between "we can write
the binary format" and "the device accepts it" -- and it turns out to need
nothing secret: an HMAC-SHA1 over the whole file, keyed from the first 8 bytes
of the device's FireWire GUID through three constant tables.

Ported from libgpod `src/itdb_hash58.c` (Nikias Bassen / Christophe Fergeau,
LGPL), tables embedded so this file stands alone. Verified 2026-09-27 against the
database iTunes wrote to a real 160 GB Classic: recomputing from that device's
GUID reproduces the stored hash byte for byte, and a GUID one bit off does not.

Header layout that matters (all offsets into `mhbd`):
    0x18  db_id        8 bytes   zeroed while hashing
    0x30  hashing_scheme (u16)   must be 1 for hash58
    0x32  20 bytes               zeroed while hashing
    0x58  hash58       20 bytes  zeroed while hashing, result written here

    python3 src/hash58.py verify <iTunesDB> <GUID-hex>
    python3 src/hash58.py sign   <iTunesDB> <GUID-hex>   # writes IN PLACE
"""
import hashlib
import math
import sys

TABLE1 = bytes.fromhex(''.join((
    '637c777bf26b6fc53001672bfed7ab76'
    'ca82c97dfa5947f0add4a2af9ca472c0'
    'b7fd9326363ff7cc34a5e5f171d83115'
    '04c723c31896059a071280e2eb27b275'
    '09832c1a1b6e5aa0523bd6b329e32f84'
    '53d100ed20fcb15b6acbbe394a4c58cf'
    'd0efaafb434d338545f9027f503c9fa8'
    '51a3408f929d38f5bcb6da2110fff3d2'
    'cd0c13ec5f974417c4a77e3d645d1973'
    '60814fdc222a908846eeb814de5e0bdb'
    'e0323a0a4906245cc2d3ac629195e479'
    'e7c8376d8dd54ea96c56f4ea657aae08'
    'ba78252e1ca6b4c6e8dd741f4bbd8b8a'
    '703eb5664803f60e613557b986c11d9e'
    'e1f8981169d98e949b1e87e9ce5528df'
    '8ca1890dbfe6426841992d0fb054bb16'
)))
TABLE2 = bytes.fromhex(''.join((
    '52096ad53036a538bf40a39e81f3d7fb'
    '7ce339829b2fff87348e4344c4dee9cb'
    '547b9432a6c2233dee4c950b42fac34e'
    '082ea16628d924b2765ba2496d8bd125'
    '72f8f66486689816d4a45ccc5d65b692'
    '6c704850fdedb9da5e154657a78d9d84'
    '90d8ab008cbcd30af7e45805b8b34506'
    'd02c1e8fca3f0f02c1afbd0301138a6b'
    '3a9111414f67dcea97f2cfcef0b4e673'
    '96ac7422e7ad3585e2f937e81c75df6e'
    '47f11a711d29c5896fb7620eaa18be1b'
    'fc563e4bc6d279209adbc0fe78cd5af4'
    '1fdda8338807c731b11210592780ec5f'
    '60517fa919b54a0d2de57a9f93c99cef'
    'a0e03b4dae2af5b0c8ebbb3c83539961'
    '172b047eba77d626e169146355210c7d'
)))
FIXED = bytes.fromhex(''.join((
    '6723fe304533f890992107c1d012b2a1'
    '0781'
)))

OFF_DBID, OFF_SCHEME, OFF_UNK32, OFF_HASH = 0x18, 0x30, 0x32, 0x58


def _lcm(a, b):
    return 1 if a == 0 or b == 0 else a * b // math.gcd(a, b)


def _key(guid):
    """64-byte HMAC key from the first 8 GUID bytes: LCM of byte pairs -> S-boxes -> SHA1."""
    y = bytearray()
    for i in range(4):
        l = _lcm(guid[2 * i], guid[2 * i + 1])
        hi, lo = (l >> 8) & 0xff, l & 0xff
        y += bytes([TABLE1[hi], TABLE2[hi], TABLE1[lo], TABLE2[lo]])
    key = bytearray(64)
    key[:20] = hashlib.sha1(FIXED + bytes(y)).digest()
    return bytes(key)


def compute(guid, data):
    """hash58 of a complete iTunesDB image, with the volatile fields zeroed."""
    if isinstance(guid, str):
        guid = bytes.fromhex(guid)
    d = bytearray(data)
    if d[:4] != b'mhbd':
        raise ValueError('not an iTunesDB')
    d[OFF_SCHEME:OFF_SCHEME + 2] = b'\x01\x00'
    d[OFF_DBID:OFF_DBID + 8] = bytes(8)
    d[OFF_UNK32:OFF_UNK32 + 20] = bytes(20)
    d[OFF_HASH:OFF_HASH + 20] = bytes(20)
    k = _key(guid[:8])
    inner = hashlib.sha1(bytes(b ^ 0x36 for b in k) + bytes(d)).digest()
    return hashlib.sha1(bytes(b ^ 0x5c for b in k) + inner).digest()


def verify(data, guid):
    return bytes(data[OFF_HASH:OFF_HASH + 20]) == compute(guid, data)


def sign(data, guid):
    """Return a copy of the image with hashing_scheme=1 and a fresh hash58."""
    d = bytearray(data)
    d[OFF_SCHEME:OFF_SCHEME + 2] = b'\x01\x00'
    d[OFF_HASH:OFF_HASH + 20] = compute(guid, d)
    return bytes(d)


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] not in ('verify', 'sign'):
        sys.exit(__doc__)
    cmd, path, guid = sys.argv[1:]
    data = open(path, 'rb').read()
    if cmd == 'verify':
        ok = verify(data, guid)
        print('stored %s' % data[OFF_HASH:OFF_HASH + 20].hex())
        print('calc   %s' % compute(guid, data).hex())
        print('MATCH' if ok else 'MISMATCH')
        sys.exit(0 if ok else 1)
    out = sign(data, guid)
    open(path, 'wb').write(out)
    print('signed %s (%d bytes)' % (path, len(out)))
