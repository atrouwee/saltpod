#!/usr/bin/env python3
"""Build the fixture library: a data home, a fake iPod and a music drive.

    python3 fixtures/build.py DEST
    SALTPOD_HOME=DEST/home saltpod curate --no-open

DEST/home     a data root for SALTPOD_HOME: data/state.json, the drive index,
              the Apple Music read, Discogs exports, the cover cache, a
              backups/ipod-*/iTunesDB as a sync leaves one, and a
              data/device.json that names DEST/mount and DEST/library -- never
              /Volumes/IPOD.
DEST/mount    a fake iPod: iPod_Control/iTunes/iTunesDB with three tracks,
              two plain playlists, one smart one, the master; and the three
              audio files it points at.
DEST/library  the music drive the index describes. A second library root,
              DEST/unplugged, is named in device.json and never created: the
              drive that is not plugged in.
DEST/fixture.json   where each of those is, and the keys and paths a caller
              needs to ask for one track (bin/contract.py reads it).

WHY A BUILDER AND NOT A COMMITTED DIRECTORY. The drive index, the state's
`device.origin` and device.json all hold absolute paths, so a committed copy
would either point at one checkout or carry a home path through the leak
gate. The seed (fixtures/seed.json) is committed, path-free and invented
end to end; this script turns it into files wherever they are wanted, and
the same seed gives the same library every time.

WHY THE iTunesDB IS MADE HERE, NOT CLONED. The house rule -- never invent a
structure, clone from the device -- is about writing the owner's iPod. A
fixture cannot be cloned from a backup without carrying real track names
and the device GUID into the repository. So this one is assembled from the
chunk layout `itunesdb_write` round-trips (mhbd > mhsd 1/3/2 > mhlt/mhlp >
mhit/mhyp > mhod/mhip), signed with hash58 under the all-zero GUID the
example device.json uses, and read back with the same reader the server
uses before this script says it is done.

Stdlib only. Writes nothing outside DEST, and refuses a DEST that already
has files in it unless --force, or one inside the source tree's data/.
"""
import argparse
import base64
import csv
import json
import os
import re
import shutil
import struct
import sys
import time
import wave
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(CODE, 'src'))

from saltpod import itunesdb as I            # noqa: E402
from saltpod import itunesdb_write as W      # noqa: E402
from saltpod import hash58                   # noqa: E402
from saltpod import tags as T                # noqa: E402
from saltpod.state import key_for            # noqa: E402

SEED = os.path.join(HERE, 'seed.json')
GUID = '0000000000000000'                    # the example device.json's; not a device
# Every file this writes gets this mtime, so the "built" and "modified"
# times the payloads report do not change from one build to the next.
FIXED = time.mktime((2026, 1, 2, 9, 0, 0, 0, 0, -1))
STAMP = '2026-01-02T08:00:00+00:00'
# A 16x16 slate-blue JPEG: the one cover every fixture picture is.
COVER = base64.b64decode(
    '/9j/4AAQSkZJRgABAgAAAQABAAD//gAQTGF2YzYyLjI4LjEwMgD/2wBDAAgQEBMQExYWFhYWFhoYGhsbGxoaGhob'
    'GxsdHR0iIiIdHR0bGx0dICAiIiUmJSMjIiMmJigoKDAwLi44ODpFRVP/xABMAAEBAAAAAAAAAAAAAAAAAAAABgEB'
    'AQAAAAAAAAAAAAAAAAAABAUQAQAAAAAAAAAAAAAAAAAAAAARAQAAAAAAAAAAAAAAAAAAAAD/wAARCAAQABADASIA'
    'AhEAAxEA/9oADAMBAAIRAxEAPwCTAOTX/9k=')
SECONDS = 2.0                                # every audio file is two seconds of silence
RATE = 8000


def art_name(ident):
    """The art cache's file name for a key or path -- ground.art_path's rule."""
    return re.sub(r'[^A-Za-z0-9]+', '_', ident)[:120] + '.jpg'


def row_art(itunes_art):
    """The 300px form a row shows of an iTunes cover -- curate.row_art's rule."""
    return (itunes_art or '').replace('100x100bb', '300x300bb')


def slug(name):
    """A playlist's slug -- mosaic.slug's rule."""
    return re.sub(r'^-|-$', '', re.sub(r'[^a-z0-9]+', '-', (name or '').lower()))


# ------------------------------------------------------------------ files

def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = 'wb' if isinstance(data, bytes) else 'w'
    with open(path, mode) as f:
        f.write(data)


def _json(path, obj):
    _write(path, json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + '\n')


def _wav(path, tags=None):
    """Two seconds of 8 kHz mono silence, tagged with the real writer."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b'\0\0' * int(RATE * SECONDS))
    if tags:
        T.write(path, tags)
    return os.path.getsize(path)


# --------------------------------------------------------------- iTunesDB

def _hdr(magic, length):
    b = bytearray(length)
    b[0:4] = magic
    struct.pack_into('<I', b, 4, length)
    return b


def _mhod_raw(typ, body):
    h = _hdr(b'mhod', 24)
    struct.pack_into('<I', h, 0x0C, typ)
    return W.Node(b'mhod', h, body)


def _mhit(t):
    h = _hdr(b'mhit', 0x248)
    struct.pack_into('<I', h, 0x10, t['id'])
    struct.pack_into('<I', h, 0x14, 1)                       # visible
    h[0x1F] = 80                                              # four stars
    struct.pack_into('<I', h, 0x24, t['size'])
    struct.pack_into('<I', h, 0x28, int(SECONDS * 1000))
    struct.pack_into('<I', h, 0x2C, 1)                        # track number
    struct.pack_into('<I', h, 0x34, t.get('year') or 0)
    struct.pack_into('<I', h, 0x38, 128)                      # bitrate
    struct.pack_into('<I', h, 0x3C, RATE << 16)
    struct.pack_into('<I', h, 0x50, 3)                        # play count
    struct.pack_into('<I', h, 0x68, int(FIXED) + I.MAC_EPOCH)  # date added
    struct.pack_into('<Q', h, 0x70, 0x5A17000000000000 + t['id'])   # dbid
    n = W.Node(b'mhit', h)
    for typ, val in ((1, t['title']), (2, t['location']), (3, t.get('album') or ''),
                     (4, t['artist']), (5, t.get('genre') or ''), (6, 'WAV audio file')):
        n.children.append(W.make_string_mhod(typ, val))
    return n


def _mhip(tid, pos):
    h = _hdr(b'mhip', 0x4C)
    struct.pack_into('<I', h, 0x14, 1000 + tid)               # group id
    struct.pack_into('<I', h, 0x18, tid)
    struct.pack_into('<I', h, 0x1C, int(FIXED) + I.MAC_EPOCH)
    n = W.Node(b'mhip', h)
    # the position mhod: a 0x18 header, the position as the body's first word
    n.children.append(_mhod_raw(100, struct.pack('<I', pos) + bytes(16)))
    return n


def _mhyp(name, tids, pid, master=False, smart=None):
    h = _hdr(b'mhyp', 0x6C)
    h[0x14] = 1 if master else 0
    struct.pack_into('<I', h, 0x18, int(FIXED) + I.MAC_EPOCH)
    struct.pack_into('<Q', h, 0x1C, pid)
    struct.pack_into('<I', h, 0x2C, 1)                        # manual order
    n = W.Node(b'mhyp', h)
    n.children.append(W.make_string_mhod(1, name))
    if smart:
        n.children += smart
    for i, tid in enumerate(tids, 1):
        n.children.append(_mhip(tid, i))
    return n


def _smart_year_after(year):
    """mhod 50 and 51 for "Year is greater than `year`" -- one rule the
    evaluator understands, so plan()'s smart rows carry `rules` and `would`."""
    pref = bytearray(72)
    pref[0x00] = 1                                            # live update
    pref[0x01] = 1                                            # check rules
    rules = bytearray(b'SLst' + struct.pack('>III', 0, 1, 0))
    rules += bytes(0x88 - len(rules))
    rule = bytearray(struct.pack('>II', 0x07, 0x10))          # Year, IS_GREATER_THAN
    rule += bytes(0x34 - len(rule))
    rule += struct.pack('>I', 0x44)
    rule += struct.pack('>QqQQqQ', year, 0, 1, year, 0, 1)
    rule += bytes(56 + 0x44 - len(rule))
    return [_mhod_raw(50, bytes(pref)), _mhod_raw(51, bytes(rules + rule))]


def build_itunesdb(dev_tracks, playlists):
    """dev_tracks: [{id, title, artist, album, genre, year, location, size}];
    playlists: [(name, [ids], smart_or_None)]. Returns the signed bytes."""
    mh = _hdr(b'mhbd', 0xF4)
    struct.pack_into('<I', mh, 0x0C, 1)
    struct.pack_into('<I', mh, 0x10, 0x75)                    # version
    struct.pack_into('<Q', mh, 0x18, 0x5A17F1C7F1C70001)      # database id
    root = W.Node(b'mhbd', mh)

    def section(typ, lst):
        sh = _hdr(b'mhsd', 0x60)
        struct.pack_into('<I', sh, 0x0C, typ)
        sd = W.Node(b'mhsd', sh)
        sd.children.append(lst)
        return sd

    mhlt = W.Node(b'mhlt', _hdr(b'mhlt', 0x5C), children=[_mhit(t) for t in dev_tracks])
    root.children.append(section(1, mhlt))
    for typ in (3, 2):                                        # the device's own order
        pls = [_mhyp('Fixture iPod', [t['id'] for t in dev_tracks], 0x5A17000000000100, master=True)]
        for i, (name, ids, smart) in enumerate(playlists, 1):
            pls.append(_mhyp(name, ids, 0x5A17000000000100 + i, smart=smart))
        root.children.append(section(typ, W.Node(b'mhlp', _hdr(b'mhlp', 0x5C), children=pls)))
    return W.serialise(root, GUID)


# ------------------------------------------------------------------- build

def build(dest, force=False):
    dest = os.path.abspath(os.path.expanduser(dest))
    if dest.startswith('/Volumes/'):
        raise SystemExit('refusing to build under /Volumes: %s' % dest)
    if dest == CODE or dest.startswith(os.path.join(CODE, 'data') + os.sep):
        raise SystemExit("refusing to build over the source tree's data: %s" % dest)
    if os.path.isdir(dest) and os.listdir(dest):
        if not force:
            raise SystemExit('%s is not empty (pass --force to replace it)' % dest)
        shutil.rmtree(dest)
    seed = json.load(open(SEED))
    home = os.path.join(dest, 'home')
    data = os.path.join(home, 'data')
    mount = os.path.join(dest, 'mount')
    lib_root = os.path.join(dest, 'library', 'Music')
    off_root = os.path.join(dest, 'unplugged', 'Music')      # named, never created
    roots = {'library': lib_root, 'unplugged': off_root}
    art_dir = os.path.join(data, 'local', 'art')
    os.makedirs(data, exist_ok=True)
    os.makedirs(lib_root, exist_ok=True)

    tracks, index, ground, dev_tracks = {}, [], {}, []
    by_name = {}
    for t in seed['tracks']:
        k = key_for(t['artist'], t['title'])
        by_name['%s|%s' % (t['artist'], t['title'])] = k
        rec = {'artist': t['artist'], 'title': t['title'],
               'playlists': sorted(t.get('playlists') or []), 'tier': t['tier'],
               'vinyl': bool(t.get('vinyl')), 'collections': list(t.get('collections') or []),
               'bought': bool(t.get('bought')), 'on_ipod': bool(t.get('device')),
               'decided_at': STAMP if t['tier'] != 'undecided' else None}
        if t.get('orphan'):
            rec['orphan'] = True
        if t.get('plays'):
            rec['plays'], rec['last_played'] = t['plays'], t.get('last_played')
        am = t.get('am')
        if am is not None:
            rec['am_owned'] = bool(am.get('owned'))
            if am.get('status'):
                rec['am_status'] = am['status']
            if 'plays' in am:
                rec['am_plays'], rec['am_skips'] = am['plays'], am.get('skips', 0)
                rec['am_last_played'] = am.get('last_played')
        if t.get('itunes'):
            rec['itunes'] = dict(t['itunes'], looked_up='2026-01-02 08:00')
        if t.get('bandcamp'):
            rec['bandcamp'] = dict(t['bandcamp'])

        f = t.get('file')
        path = None
        if f:
            path = os.path.join(roots[f['root']], f['path'])
            ext = os.path.splitext(path)[1].lower()
            tags = {'title': t['title'], 'artist': t['artist'], 'album': f.get('album') or '',
                    'genre': f.get('genre') or '', 'year': f.get('year') or ''}
            size = _wav(path, tags) if f['root'] == 'library' else 31_000_000
            index.append({
                'path': path, 'ext': ext, 'size': size, 'duration_sec': SECONDS if ext == '.wav' else 300.0,
                'artist': t['artist'], 'title': t['title'], 'album': f.get('album'),
                'album_artist': f.get('album_artist'), 'has_art': bool(f.get('has_art')),
                'codec': 'pcm_s16le' if ext == '.wav' else 'flac',
                'sample_rate': RATE if ext == '.wav' else 44100, 'channels': 1 if ext == '.wav' else 2,
                'bit_depth': 16, 'untagged': False, 'needs_convert': ext == '.flac',
                'ipod_ready': ext != '.flac', 'mtime': FIXED, 'copies': []})

        d = t.get('device')
        if d:
            loc = ':iPod_Control:Music:' + d['file'].replace('/', ':')
            dpath = os.path.join(mount, 'iPod_Control', 'Music', d['file'])
            dsize = _wav(dpath)
            dev_tracks.append({'id': d['id'], 'title': t['title'], 'artist': t['artist'],
                               'album': d.get('album'), 'genre': d.get('genre'),
                               'year': d.get('year'), 'location': loc, 'size': dsize})
            dev = {'location': loc, 'seconds': SECONDS, 'size': dsize, 'bitrate': 128,
                   'album': d.get('album'), 'lossless': True}
            if d.get('origin') and path:
                dev['origin'] = path
                dev['origin_ext'] = os.path.splitext(path)[1].lower()
            if d.get('synced'):
                dev['synced'] = dict(d['synced'], mtime=FIXED)
            rec['device'] = dev

        art = t.get('art')
        if art == 'local':
            ground_src = '/api/art?key=' + quote(k)
            _write(os.path.join(art_dir, art_name(k)), COVER)
        elif art == 'remote':
            ground_src = row_art(t['itunes']['art'])
            _write(os.path.join(art_dir, art_name(k)), COVER)   # already downloaded
        else:
            ground_src = None
        if ground_src:
            ground[k] = {'y': 0.041, 'scrim': 0.52, 'mean': [60, 90, 110], 'src': ground_src,
                         'at': '2026-01-02T09:00:00'}
        tracks[k] = rec

    for u in seed.get('untagged') or []:
        path = os.path.join(roots[u['root']], u['path'])
        size = _wav(path)
        index.append({'path': path, 'ext': '.wav', 'size': size, 'duration_sec': SECONDS,
                      'artist': None, 'title': None, 'album': None, 'album_artist': None,
                      'has_art': False, 'codec': 'pcm_s16le', 'sample_rate': RATE, 'channels': 1,
                      'bit_depth': 16, 'untagged': True, 'needs_convert': False,
                      'ipod_ready': True, 'mtime': FIXED, 'copies': []})

    order = {c: [by_name[n] for n in names] for c, names in seed['collection_order'].items()}
    _json(os.path.join(data, 'state.json'), {
        'version': 1, 'tracks': tracks, 'collections': list(seed['collections']),
        'collection_order': order, 'synced_playlists': list(seed['synced_playlists']),
        'apple_music_read_at': seed['apple_music_read_at'], 'updated': STAMP})
    _json(os.path.join(data, 'device.json'), {
        '_note': 'written by fixtures/build.py: a fake mount and a fixture drive, never a device',
        'mount': mount, 'library_roots': [lib_root, off_root], 'target': 'apple',
        'apple': {'firewire_guid': GUID}})
    _json(os.path.join(data, 'local', 'index.json'),
          {'roots': [lib_root, off_root], 'count': len(index), 'tracks': index})
    _json(os.path.join(data, 'local', 'ground.json'), ground)

    # Apple Music: the cached read, and one imported playlist with its mosaic
    am = seed['apple_music']
    lib = [dict(r, key=key_for(r['artist'], r['title'])) for r in am['library']]
    _json(os.path.join(data, 'local', 'apple_music.json'), {
        'playlists': [{'name': p['name'], 'tracks': len(p['members']), 'created': p['created'],
                       'last': p['last']} for p in am['playlists']],
        'keys': sorted({r['key'] for r in lib}), 'library': lib,
        'read_at': seed['apple_music_read_at']})
    mosaics = {}
    for p in am['playlists']:
        if not p.get('imported'):
            continue
        s = slug(p['name'])
        rows = []
        for i, n in enumerate(p['members'], 1):
            artist, title = n.split('|', 1)
            src = next((x for x in seed['tracks'] if x['artist'] == artist and x['title'] == title), {})
            it = src.get('itunes') or {}
            rows.append({'index': i, 'artist': artist, 'title': title, 'album': it.get('album') or '',
                         'album_artist': artist, 'cloud_status': (src.get('am') or {}).get('status') or 'subscription',
                         'database_id': 70000 + i, 'duration_sec': SECONDS, 'genre': it.get('genre') or '',
                         'kind': 'Apple Music AAC audio file', 'owned': bool((src.get('am') or {}).get('owned')),
                         'track_number': 1, 'year': 2024})
        _json(os.path.join(data, 'exports', s + '.json'), {
            'playlist': p['name'], 'exported_at': '2026-01-02T08:00:00', 'track_count': len(rows),
            'owned_count': sum(1 for r in rows if r['owned']), 'tracks': rows})
        # the mosaic, as the worker would have left it: made from the first
        # members with a picture, so the payload finds it current
        srcs = [ground[by_name[n]]['src'] for n in p['members'] if by_name.get(n) in ground][:4]
        _write(os.path.join(art_dir, 'playlist_%s.jpg' % s), COVER)
        mosaics[s] = {'sources': srcs, 'used': srcs, 'at': '2026-01-02T09:00:00'}
    _json(os.path.join(data, 'local', 'mosaics.json'), mosaics)

    # Discogs, as the two CSVs download -- the wantlist with its unnamed
    # trailing "Date Added" column, the quirk discogs.py pads for
    dc = seed['discogs']
    ccols = ['Catalog#', 'Artist', 'Title', 'Label', 'Format', 'Rating', 'Released', 'release_id',
             'CollectionFolder', 'Date Added', 'Collection Media Condition',
             'Collection Sleeve Condition', 'Collection Notes']
    wcols = ['Catalog#', 'Artist', 'Title', 'Label', 'Format', 'Rating', 'Released', 'release_id', 'Notes']
    os.makedirs(os.path.join(data, 'discogs'), exist_ok=True)
    with open(os.path.join(data, 'discogs', 'collection.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(ccols)
        for r in dc['collection']:
            w.writerow([r.get(c, '') for c in ccols])
    with open(os.path.join(data, 'discogs', 'wantlist.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(wcols)
        for r in dc['wantlist']:
            w.writerow([r.get(c, '') for c in wcols] + [r.get('Date Added', '')])

    # the fake iPod
    dev_ids = {by_name['%s|%s' % (d['artist'], d['title'])]: d['id'] for d in dev_tracks}
    evening = [dev_ids[k] for k in order['Evening'] if k in dev_ids]
    keepers = [dev_ids[k] for k in order['Keepers'] if k in dev_ids]
    old_mix = [dev_ids[k] for k, r in tracks.items() if r['tier'] == 'remove' and k in dev_ids]
    blob = build_itunesdb(dev_tracks, [('Evening', evening, None), ('Keepers', keepers, None),
                                       ('Old Mix', old_mix, None),
                                       ('Since 2000', [], _smart_year_after(2000))])
    dbp = os.path.join(mount, 'iPod_Control', 'iTunes', 'iTunesDB')
    _write(dbp, blob)
    # and the backup a sync would have left, which is what the device pane
    # and import_device read while the iPod is unplugged
    _write(os.path.join(home, 'backups', 'ipod-2026-01-02-090000', 'iTunesDB'), blob)
    back = I.read(dbp)
    assert [t['id'] for t in back['tracks']] == [t['id'] for t in dev_tracks], 'tracks did not read back'
    assert [p['name'] for p in back['playlists']] == ['Fixture iPod', 'Evening', 'Keepers', 'Old Mix',
                                                       'Since 2000']
    assert hash58.verify(blob, GUID), 'hash58 does not verify'
    assert W.serialise(W.parse(blob)) == blob, 'the tree does not round-trip'

    for top in (home, mount, os.path.join(dest, 'library')):
        for d, _dirs, files in os.walk(top):
            for f in files:
                os.utime(os.path.join(d, f), (FIXED, FIXED))

    t1 = by_name['Alder Quartet|Morning Field']
    untagged = os.path.join(roots[seed['untagged'][0]['root']], seed['untagged'][0]['path'])
    manifest = {'home': home, 'mount': mount, 'library': lib_root, 'unplugged': off_root,
                'keys': sorted(tracks), 'detail_key': t1, 'untagged_path': untagged,
                'folder': 'Bought', 'decide_key': by_name['Grove|Paper Moon']}
    _json(os.path.join(dest, 'fixture.json'), manifest)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('dest', help='an empty directory (made if missing)')
    ap.add_argument('--force', action='store_true', help='replace whatever is in DEST')
    a = ap.parse_args(argv)
    m = build(a.dest, a.force)
    print('fixture library in %s' % os.path.dirname(m['home']))
    print('  SALTPOD_HOME=%s' % m['home'])
    print('  fake iPod     %s' % m['mount'])
    print('  %d tracks in state' % len(m['keys']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
