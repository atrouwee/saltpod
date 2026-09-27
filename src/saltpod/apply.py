#!/usr/bin/env python3
"""Make the iPod match the curation state. The sync step.

    python3 src/apply.py plan            # what would change, touches nothing
    python3 src/apply.py sync            # do it: files, database, verify, eject
    python3 src/apply.py sync --no-eject

What "match" means, from data/state.json:
  * every collection becomes a playlist on the device with exactly its tracks,
    in the sequence arranged in the Collections view (state.collection_order);
  * a track in a collection that is not on the device gets ADDED: its T7
    original is converted if needed (FLAC/WAV/AIFF -> ALAC .m4a; MP3/AAC copied
    as-is), copied into iPod_Control/Music/Fxx/, and given a database entry;
  * a device track curated `skipped` gets REMOVED: database entry, every
    playlist reference, and the file;
  * device tracks not mentioned by any collection are left alone -- this never
    wipes the device to match a list.

The database is edited in place through the lossless tree model, re-signed
with hash58, verified on the device after writing, and `Play Counts` is
deleted whenever the track set changes (it is positional). A dated backup of
iPod_Control/iTunes is taken before every write.
"""
import argparse
import json
import os
import random
import shutil
import string
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
from . import state as S            # noqa: E402
from . import itunesdb_write as W   # noqa: E402
from . import ipod_edit as E        # noqa: E402
from . import hash58                # noqa: E402

from . import config

# Device settings are read when a command runs, not when the module is
# imported -- a fresh clone with no data/device.json must still print help.
MOUNT = '/Volumes/IPOD'
GUID = None


def _cfg():
    global MOUNT, GUID
    if GUID is None:
        c = config.load()
        MOUNT, GUID = c['mount'], c['firewire_guid']
    return MOUNT, GUID
DB_REL = 'iPod_Control/iTunes/iTunesDB'
AS_IS = {'.mp3', '.m4a', '.aac'}
CONVERT = {'.flac', '.wav', '.aiff', '.aif', '.alac', '.ogg'}
FF_ENV = {**os.environ, 'DEVELOPER_DIR': '/Library/Developer/CommandLineTools'}


# ------------------------------------------------------------- metadata

def probe(path):
    """ffprobe -> the fields track_add needs. bitrate in kbps."""
    out = subprocess.run(['ffprobe', '-v', 'quiet', '-print_format', 'json',
                          '-show_format', '-show_streams', path],
                         capture_output=True, text=True, timeout=60, env=FF_ENV).stdout
    j = json.loads(out or '{}')
    fmt = j.get('format') or {}
    tags = {k.lower(): v for k, v in (fmt.get('tags') or {}).items()}
    aud = next((s for s in j.get('streams') or [] if s.get('codec_type') == 'audio'), {})
    tno = (tags.get('track') or '0').split('/')[0]
    year = (tags.get('date') or tags.get('year') or '')[:4]
    return {
        'title': tags.get('title'), 'artist': tags.get('artist'),
        'album': tags.get('album'), 'genre': tags.get('genre'),
        'ms': int(float(fmt.get('duration') or 0) * 1000),
        'bitrate': int(int(fmt.get('bit_rate') or 0) / 1000),
        'samplerate': int(aud.get('sample_rate') or 44100),
        'track_no': int(tno) if tno.isdigit() else 0,
        'year': int(year) if year.isdigit() else 0,
        'size': os.path.getsize(path),
    }


def convert_to_alac(src, dst):
    # -vn -map 0:a:0: these AIFFs carry cover art as an mjpeg stream and ffmpeg
    # will otherwise mux it into the output (see curate.py). -movflags faststart
    # so the iPod's parser finds the moov atom without reading the whole file.
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-vn', '-map', '0:a:0',
                    '-c:a', 'alac', '-map_metadata', '0', '-movflags', '+faststart', dst],
                   check=True, env=FF_ENV, timeout=600)


def new_location(mount, ext):
    """A free Fxx/XXXX.ext slot, spread across the 50 folders like iTunes does."""
    while True:
        folder = 'F%02d' % random.randrange(50)
        name = ''.join(random.choices(string.ascii_uppercase, k=4)) + ext
        rel = os.path.join('iPod_Control', 'Music', folder, name)
        if not os.path.exists(os.path.join(mount, rel)):
            return rel, ':' + rel.replace(os.sep, ':')


# ----------------------------------------------------------------- plan

def plan(mount=None):
    _cfg()
    mount = mount or MOUNT
    st = S.load()
    dbp = os.path.join(mount, DB_REL)
    root = W.parse(open(dbp, 'rb').read())
    dev_by_key = {}
    for t in E.tracks(root):
        artist = next((W.mhod_string(c) for c in t.children if W.mhod_type(c) == 4), '')
        title = next((W.mhod_string(c) for c in t.children if W.mhod_type(c) == 1), '')
        dev_by_key[S.key_for(artist, title)] = E.track_id(t)

    # Sequence comes from state.collection_order -- what the user arranged --
    # never from a sort. A playlist's order on the device is the product.
    cols = {}
    for c in sorted({c for r in st['tracks'].values() for c in r['collections']}):
        cols[c] = [(k, st['tracks'][k]) for k in S.order_for(st, c)]

    # Files for tracks that are not on the device: a device record's origin
    # first; otherwise the T7 index by the same key, duration-checked, since a
    # bought file has no device record yet. Lossless originals win ties.
    local = {}
    idx = os.path.join(ROOT, 'data', 'local', 'index.json')
    if os.path.exists(idx):
        for e in json.load(open(idx))['tracks']:
            local.setdefault(S.key_for(e.get('artist'), e.get('title')), []).append(e)

    def source_for(k, r):
        src = (r.get('device') or {}).get('origin')
        if src and os.path.exists(src):
            return src
        want = (r.get('itunes') or {}).get('seconds')
        cands = [e for e in local.get(k, []) if os.path.exists(e['path'])
                 and (not want or abs((e.get('duration_sec') or 0) - want) <= 3)]
        cands.sort(key=lambda e: (os.path.splitext(e['path'])[1].lower() not in CONVERT,
                                  -os.path.getsize(e['path'])))
        return cands[0]['path'] if cands else None

    adds, no_source, removes = [], [], []
    for c, members in cols.items():
        for k, r in members:
            if k in dev_by_key or any(k == a[0] for a in adds):
                continue
            src = source_for(k, r)
            if not src:
                no_source.append((k, r))
                continue
            adds.append((k, r, src))
    for k, r in st['tracks'].items():
        if r.get('device') and r['tier'] == 'skipped' and k in dev_by_key:
            removes.append((k, r, dev_by_key[k]))

    existing = {E.pl_name(p) for p in E.playlists(root, E.playlist_sections(root)[0])}
    # What each playlist on the device holds right now, in order, so a
    # collection that already matches is reported as such and not rewritten.
    # Every non-smart playlist is a collection since import_device adopts them,
    # so without this the panel would say "15 to update" forever.
    from . import itunesdb as I
    dev_seq = {}
    for pl in I.read(dbp).get('playlists') or []:
        if not pl.get('master') and not pl.get('smart'):
            dev_seq[pl['name']] = [it for it in (pl.get('items') or []) if isinstance(it, int)]
    unchanged = []
    for c, members in cols.items():
        if c not in existing:
            continue
        if any(k not in dev_by_key for k, r in members):
            continue                      # something in it still has to be copied across
        if [dev_by_key[k] for k, r in members] == dev_seq.get(c):
            unchanged.append(c)
    # A collection is deletable if this tool wrote it OR adopted it from the
    # device -- both put it in synced_playlists. Smart playlists are never there.
    ours = set(st.get('synced_playlists', []))
    return {'root': root, 'state': st, 'dev_by_key': dev_by_key, 'collections': cols,
            'adds': adds, 'no_source': no_source, 'removes': removes,
            'unchanged': unchanged,
            'new_playlists': [c for c in cols if c not in existing],
            'update_playlists': [c for c in cols if c in existing and c not in unchanged],
            'delete_playlists': sorted(n for n in ours if n in existing and n not in cols)}


def print_plan(p):
    print('collections -> playlists: %d new, %d updated, %d unchanged'
          % (len(p['new_playlists']), len(p['update_playlists']), len(p.get('unchanged', []))))
    for c in p['collections']:
        if c in p.get('unchanged', ()):
            continue
        tag = 'new' if c in p['new_playlists'] else 'update'
        print('   %-8s %-30s %d tracks' % (tag, c[:30], len(p['collections'][c])))
    if p['delete_playlists']:
        print('playlists to DELETE (collection removed from state): %s' % ', '.join(p['delete_playlists']))
    print('tracks to ADD: %d' % len(p['adds']))
    for k, r, src in p['adds']:
        ext = os.path.splitext(src)[1].lower()
        print('   %-38s %s' % ((r['artist'] + ' - ' + r['title'])[:38], 'convert->ALAC' if ext in CONVERT else 'copy ' + ext))
    if p['no_source']:
        print('in a collection but NO FILE to add (buy first, or index the T7): %d' % len(p['no_source']))
        for k, r in p['no_source'][:8]:
            print('   %s - %s' % (r['artist'], r['title']))
    print('tracks to REMOVE (device tracks curated as skipped): %d' % len(p['removes']))
    for k, r, tid in p['removes'][:12]:
        print('   %-38s id %d' % ((r['artist'] + ' - ' + r['title'])[:38], tid))


# ----------------------------------------------------------------- sync

def backup(mount):
    d = os.path.join(ROOT, 'backups', 'ipod-%s' % time.strftime('%Y-%m-%d-%H%M%S'))
    shutil.copytree(os.path.join(mount, 'iPod_Control', 'iTunes'), d)
    return d


def sync(mount=None, eject=True):
    _cfg()
    mount = mount or MOUNT
    p = plan(mount)
    print_plan(p)
    if not (p['adds'] or p['removes'] or p['new_playlists'] or p['update_playlists'] or p['delete_playlists']):
        print('\nnothing to do'); return
    root, st = p['root'], p['state']
    # '## <phase> [i/n]' lines are for the page's progress panel; the prose
    # after each is for a person reading the log.
    print('## backup'); bdir = backup(mount)
    print('\nbackup: %s' % os.path.relpath(bdir, ROOT))
    changed_tracks = False

    # 1. files + database entries for additions
    n_add = len(p['adds'])
    for i_add, (k, r, src) in enumerate(p['adds'], 1):
        print('## copy %d/%d' % (i_add, n_add))
        ext = os.path.splitext(src)[1].lower()
        if ext in CONVERT:
            rel, loc = new_location(mount, '.m4a')
            tmp = os.path.join('/tmp', 'ipod-conv-' + os.path.basename(rel))
            print('  converting %s' % os.path.basename(src)); convert_to_alac(src, tmp)
            staged = tmp
        elif ext in AS_IS:
            rel, loc = new_location(mount, ext); staged = src
        else:
            print('  skip (unsupported): %s' % src); continue
        meta = probe(staged); meta['ext'] = os.path.splitext(rel)[1].lower()
        meta['title'] = meta['title'] or r['title']; meta['artist'] = meta['artist'] or r['artist']
        dst = os.path.join(mount, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(staged, dst)
        tid = E.track_add(root, meta, loc)
        p['dev_by_key'][k] = tid
        st['tracks'][k]['on_ipod'] = True
        st['tracks'][k].setdefault('device', {})['location'] = loc
        changed_tracks = True
        print('  added   %s - %s -> %s (id %d)' % (r['artist'], r['title'], rel, tid))

    # 2. removals
    if p['removes']:
        print('## remove %d' % len(p['removes']))
    for k, r, tid in p['removes']:
        loc = E.track_remove(root, tid)
        f = os.path.join(mount, loc.lstrip(':').replace(':', os.sep))
        if os.path.exists(f):
            os.remove(f)
        st['tracks'][k]['on_ipod'] = False
        changed_tracks = True
        print('  removed %s - %s (id %d)' % (r['artist'], r['title'], tid))

    # 3. playlists from collections
    for c in p['delete_playlists']:
        E.playlist_delete(root, c)
        print('  playlist %-30s deleted' % c[:30])
    print('## playlists')
    for c, members in p['collections'].items():
        if c in p.get('unchanged', ()):
            continue                      # already exactly this on the device
        ids = [p['dev_by_key'][k] for k, r in members if k in p['dev_by_key']]
        if c in p['new_playlists']:
            E.playlist_create(root, c)
        E.playlist_set_tracks(root, c, ids)
        print('  playlist %-30s %d tracks' % (c[:30], len(ids)))

    # 4. write, verify, bookkeeping
    print('## write')
    out = W.serialise(root, GUID)
    dbp = os.path.join(mount, DB_REL)
    tmp = dbp + '.saltgate.tmp'
    open(tmp, 'wb').write(out); os.replace(tmp, dbp)
    back = open(dbp, 'rb').read()
    if back != out or not hash58.verify(back, GUID):
        raise SystemExit('!! database on device does not verify after write - restore from %s' % bdir)
    if changed_tracks:
        pc = os.path.join(mount, 'iPod_Control', 'iTunes', 'Play Counts')
        if os.path.exists(pc):
            os.remove(pc)
    st['synced_playlists'] = sorted((set(st.get('synced_playlists', [])) | set(p['collections']))
                                    - set(p['delete_playlists']))
    S.save(st)
    print('## verify')
    print('\ndatabase written and verified on device: %d bytes, hash58 OK' % len(out))
    if eject:
        print('## eject')
        subprocess.run(['sync']); subprocess.run(['diskutil', 'eject', mount])
        print('ejected')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['plan', 'sync'])
    ap.add_argument('--mount', default=None)
    ap.add_argument('--no-eject', action='store_true')
    a = ap.parse_args()
    _cfg()
    a.mount = a.mount or MOUNT
    if not os.path.exists(os.path.join(a.mount, DB_REL)):
        sys.exit('iPod not mounted at %s' % a.mount)
    if a.cmd == 'plan':
        print_plan(plan(a.mount))
    else:
        sync(a.mount, eject=not a.no_eject)


if __name__ == '__main__':
    main()
