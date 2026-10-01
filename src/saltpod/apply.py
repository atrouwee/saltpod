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
# a fallback, never an override -- see DEV_DIR in curate.py
FF_ENV = {**os.environ,
          'DEVELOPER_DIR': os.environ.get('DEVELOPER_DIR')
                           or '/Library/Developer/CommandLineTools'}


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
    # A collection is what state DECLARES, not only what has members: one
    # emptied in the page stays on the device as an empty playlist, the way a
    # phone keeps one. It is deleted only when it is deleted -- removed from
    # state.collections by the collection's own delete.
    cols = {}
    names = set(st.get('collections', [])) | {c for r in st['tracks'].values() for c in r['collections']}
    for c in sorted(names):
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

    # ONE ANSWER DECIDES IT: tier == 'sync'. A collection additionally says
    # where in a playlist the track goes, and in what order -- but wanting it
    # on the device is the same fact whether it arrived through a playlist or
    # through an album. (An album is not a playlist: the Classic builds its
    # Albums menu from the tracks' own tags, so writing one would put the
    # record in two menus.)
    loose = [(k, r) for k, r in st['tracks'].items()
             if r.get('tier') == 'sync' and not r['collections']]
    adds, no_source, removes = [], [], []
    for members in list(cols.values()) + [loose]:
        for k, r in members:
            if k in dev_by_key or any(k == a[0] for a in adds):
                continue
            # A skipped track is not a candidate, whatever collection names
            # it. Without this, removing a track that belongs to a playlist
            # meant stripping it from that playlist first -- destroying the
            # membership to make the removal stick -- and the next plan would
            # otherwise add it back on the following sync.
            if r.get('tier') == 'remove':
                continue
            src = source_for(k, r)
            if not src:
                no_source.append((k, r))
                continue
            adds.append((k, r, src))
    for k, r in st['tracks'].items():
        if r.get('device') and r['tier'] == 'remove' and k in dev_by_key:
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
        # MIRROR THE WRITER EXACTLY. It writes the members that are on the
        # device and silently drops the rest, so the comparison has to do
        # the same -- and "something still has to be copied across" must
        # only count members that CAN still land. A track marked to come
        # off stays in its collection on purpose, is never an add
        # candidate, and so would otherwise hold the playlist in
        # "out of date" forever: every sync rewriting it to the same two
        # tracks, every next plan asking again.
        would_write = [dev_by_key[k] for k, r in members if k in dev_by_key]
        pending = [k for k, r in members
                   if k not in dev_by_key and r.get('tier') != 'remove']
        if not pending and would_write == dev_seq.get(c):
            unchanged.append(c)
    # A collection is deletable if this tool wrote it OR adopted it from the
    # device -- both put it in synced_playlists. Smart playlists are never there.
    ours = set(st.get('synced_playlists', []))
    # Resolve it ONCE and hand the answer around. Three places needed
    # "where is this track's file" -- the adds, the drift detector and the
    # ancestor snapshot -- and two of them had grown their own version that
    # only knew about `device.origin`. That field is recorded when saltpod
    # copies a file across and absent for everything iTunes put there, so
    # both quietly skipped a third of the library. Same bug, found twice.
    origin_of = {}
    for k in dev_by_key:
        r = st['tracks'].get(k)
        if r:
            src = source_for(k, r)
            if src:
                origin_of[k] = src
    retags = _metadata_drift(st, dbp, dev_by_key, origin_of)
    return {'root': root, 'state': st, 'dev_by_key': dev_by_key, 'collections': cols,
            'adds': adds, 'no_source': no_source, 'removes': removes,
            'retags': retags,
            'unchanged': unchanged,
            # what each playlist on the device holds right now, so a revert
            # has something authoritative to revert TO
            'dev_seq': dev_seq, 'origin_of': origin_of,
            'new_playlists': [c for c in cols if c not in existing],
            'update_playlists': [c for c in cols if c in existing and c not in unchanged],
            'delete_playlists': sorted(n for n in ours if n in existing and n not in cols)}


# WHAT COUNTS AS DRIFT. Genre is deliberately not in here. It is the field
# every encoder and importer spells differently -- "(5)Funk" against "Funk",
# "Alt. Rock" against "AlternRock" -- and including it reported 12 tracks as
# disagreeing when nobody had touched them. It is still editable and still
# written; it is just not evidence that the two sides have diverged.
TAGGED = ('title', 'artist', 'album')

# MTIME IS THE GATE, AND HERE IS WHERE IT FINALLY EARNS ITS KEEP. The drift
# detector reads the tag span of every file on the device, once per plan --
# 638 files over USB, and a profile says 2,513 ms of plan()'s 2,677 ms is
# that read, waiting on the drive. The work itself is 164 ms.
#
# A stat is 0.001 ms against a read's 3.7 ms: the gate is three thousand
# times cheaper than the read it avoids. Cache the tags against the file's
# mtime and a file nobody has touched is never opened again.
_TAGCACHE = {}


def _tags_cached(path):
    """The file's tags, re-read only when the file has actually changed."""
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    hit = _TAGCACHE.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    from . import tags as T
    try:
        val = T.read(path)
    except Exception:
        val = {}
    _TAGCACHE[path] = (mt, val)
    return val


def _metadata_drift(st, dbp, dev_by_key, origin_of):
    """Where the file and the device disagree about what a track is called.

    THE FILE IS MASTER, so the normal answer is "make the device match".
    But a Classic cannot retag itself -- there is no keyboard -- which means
    saltpod is the only writer on either side, and "whichever edit was last"
    is a fact we recorded rather than a guess we make. So a device entry
    that was edited here, against a file nobody has touched, wins.

    Attribution comes from two things that cost nothing:

      * the file's **mtime**, straight off the filesystem. An mtime equal to
        the one recorded at the last sync is a RELIABLE NEGATIVE: the file
        did not move, full stop.
      * the tag values **as written at the last sync**, kept in the record.
        They are the common ancestor, and they are free because they are
        what we just wrote.

    mtime alone would be wrong in one direction: a restore or a `touch`
    bumps it without changing a tag, and last-write-wins would then let an
    untouched file overwrite a real edit on the device. Comparing against
    the ancestor closes that.

    Returns [(key, rec, tid, winner, fields)] where winner is 'file' or
    'device' and fields are the values to write to the loser.
    """
    from . import itunesdb as I, tags as T
    out = []
    # the proven parser, not a second reading of the same bytes
    db = I.read(dbp)
    rows = db['tracks'] if isinstance(db, dict) else db
    dev_meta = {t['id']: t for t in rows}

    for k, tid in dev_by_key.items():
        r = st['tracks'].get(k) or {}
        dev = r.get('device') or {}
        # THE SAME RESOLVER THE REST OF plan() USES. This asked only for
        # `origin`, which is recorded when saltpod copies a file across and
        # absent for everything iTunes put there -- 178 of 644 tracks. So a
        # retag on any of those was written to the file and then invisible
        # to the plan, because the panel found the file by one rule and the
        # drift detector by another. One question, one answer.
        src = origin_of.get(k)
        if not src or not os.path.exists(src):
            continue                       # nothing to compare against
        d = dev_meta.get(tid)
        if not d:
            continue
        fil = _tags_cached(src)
        # ffprobe's view is the fallback for a container we cannot read yet
        if not fil:
            continue

        now = {f: (fil.get(f) or '').strip() for f in TAGGED}
        was = {f: (str(d.get(f) or '')).strip() for f in TAGGED}
        if now == was:
            continue

        winner, fields = resolve_drift(now, was, dev.get('synced') or {},
                                       os.path.getmtime(src))
        out.append((k, r, tid, winner, fields))
    return out


def resolve_drift(now, was, anc, file_mtime):
    """Which side moved, and therefore which side wins. Pure, so it is tested.

    `now` is the file's tags, `was` is the device's, `anc` is what was
    written at the last sync -- the common ancestor -- carrying the tag
    values and the file's mtime at that moment.

    MTIME IS THE GATE, THE VALUES ARE THE TRUTH -- and getting that the
    wrong way round is a real bug I shipped into the first draft of this
    function. mtime decides whether the file is worth re-reading; it does
    NOT decide whether the file changed. A restore or a `touch` bumps it
    without altering a tag, and treating that as an edit let an untouched
    file overwrite a genuine one on the device. Both sides are judged
    against the ancestor by VALUE.

      file moved    its tags differ from the ones recorded at last sync
      device moved  its tags differ from the ones we wrote there.
                    saltpod is the only thing that can have changed them,
                    because a Classic has no keyboard.

    With no ancestor recorded -- everything synced before this existed --
    the file wins, which is the standing rule and the safe default.
    """
    anc_tags = {f: ((anc.get('tags') or {}).get(f) or '').strip() for f in TAGGED}
    have_anc = bool(anc.get('tags'))
    file_moved = (not have_anc) or now != anc_tags
    dev_moved = have_anc and was != anc_tags

    if dev_moved and not file_moved:
        return 'device', was
    if dev_moved and file_moved:
        # both moved: the later one, by the clock each side actually keeps
        later_dev = (anc.get('edited_at') or 0) > file_mtime
        return ('device', was) if later_dev else ('file', now)
    return 'file', now


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


def drop_excluded(p, exclude):
    """Take the rows the page unticked out of a fresh plan.

    Sync always re-plans against the live device -- it never trusts a plan the
    page computed seconds ago -- so exclusions arrive as IDENTITIES, not as
    indices into a list that may have moved: track keys and playlist names.
    Anything named here that is no longer in the plan is silently ignored,
    which is the right outcome: it means the device already agrees.
    """
    if not exclude:
        return p
    xt = set(exclude.get('tracks') or ())
    xp = set(exclude.get('playlists') or ())
    if xt:
        p['adds'] = [a for a in p['adds'] if a[0] not in xt]
        p['removes'] = [r for r in p['removes'] if r[0] not in xt]
        p['retags'] = [r for r in p.get('retags', ()) if r[0] not in xt]
    if xp:
        # An unticked playlist is left exactly as the device has it. Its
        # tracks may still be copied across -- that is honest: you said not to
        # touch the playlist, not that the music should stay off the device.
        p['collections'] = {c: m for c, m in p['collections'].items() if c not in xp}
        p['new_playlists'] = [c for c in p['new_playlists'] if c not in xp]
        p['update_playlists'] = [c for c in p['update_playlists'] if c not in xp]
        p['delete_playlists'] = [c for c in p['delete_playlists'] if c not in xp]
    return p


def sync(mount=None, eject=True, exclude=None):
    _cfg()
    mount = mount or MOUNT
    p = drop_excluded(plan(mount), exclude)
    print_plan(p)
    if not (p['adds'] or p['removes'] or p.get('retags') or p['new_playlists']
            or p['update_playlists'] or p['delete_playlists']):
        print('\nnothing to do'); return
    root, st = p['root'], p['state']
    # '## <phase> [i/n]' lines are for the page's progress panel; the prose
    # after each is for a person reading the log.
    print('@@ backup doing')
    print('## backup'); bdir = backup(mount)
    print('@@ backup done')
    print('\nbackup: %s' % os.path.relpath(bdir, ROOT))
    changed_tracks = False

    # 1. files + database entries for additions
    n_add = len(p['adds'])
    for i_add, (k, r, src) in enumerate(p['adds'], 1):
        print('## copy %d/%d' % (i_add, n_add))
        print('@@ a:%s doing' % k)
        ext = os.path.splitext(src)[1].lower()
        if ext in CONVERT:
            rel, loc = new_location(mount, '.m4a')
            tmp = os.path.join('/tmp', 'ipod-conv-' + os.path.basename(rel))
            print('  converting %s' % os.path.basename(src)); convert_to_alac(src, tmp)
            staged = tmp
        elif ext in AS_IS:
            rel, loc = new_location(mount, ext); staged = src
        else:
            print('  skip (unsupported): %s' % src)
            print('@@ a:%s error unsupported file type' % k); continue
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
        print('@@ a:%s done' % k)

    # 2. removals
    if p['removes']:
        print('## remove %d' % len(p['removes']))
    for k, r, tid in p['removes']:
        print('@@ r:%s doing' % k)
        loc = E.track_remove(root, tid)
        f = os.path.join(mount, loc.lstrip(':').replace(':', os.sep))
        if os.path.exists(f):
            os.remove(f)
        st['tracks'][k]['on_ipod'] = False
        # THE MAP IS NOW STALE FOR THIS TRACK and the playlist writer reads
        # it. A track can be in a collection AND marked to come off -- the
        # membership deliberately survives a removal -- so without this the
        # next step asks for a track id that was deleted a moment ago and
        # the whole sync dies with `unknown track ids`. It died exactly
        # there on the first hardware run, above the commit boundary, which
        # is the only reason that was a bug report rather than an incident.
        p['dev_by_key'].pop(k, None)
        changed_tracks = True
        print('  removed %s - %s (id %d)' % (r['artist'], r['title'], tid))
        print('@@ r:%s done' % k)

    # 2b. metadata the two sides disagree about
    if p.get('retags'):
        print('## retag %d' % len(p['retags']))
    for k, r, tid, winner, fields in p.get('retags', ()):
        print('@@ m:%s doing' % k)
        try:
            if winner == 'device':
                # the device was edited here and the file was not: bring the
                # file into line, which is the one direction that needs a
                # writer and may not have one yet
                from . import tags as T
                src = (r.get('device') or {}).get('origin')
                if src and T.supported(src):
                    T.write(src, fields)
                    print('  file    <- device  %s' % os.path.basename(src))
                else:
                    print('  skip    no writer for %s' % os.path.basename(src or '?'))
                    print('@@ m:%s error no writer' % k); continue
            else:
                E.track_retag(root, tid, fields)
                print('  device  <- file    %s - %s' % (fields.get('artist'), fields.get('title')))
                changed_tracks = True
        except Exception as e:
            print('  !! %s' % e)
            print('@@ m:%s error %s' % (k, e)); continue
        print('@@ m:%s done' % k)

    # 3. playlists from collections
    for c in p['delete_playlists']:
        print('@@ p:%s doing' % c)
        E.playlist_delete(root, c)
        print('  playlist %-30s deleted' % c[:30])
        print('@@ p:%s done' % c)
    print('## playlists')
    for c, members in p['collections'].items():
        if c in p.get('unchanged', ()):
            continue                      # already exactly this on the device
        print('@@ p:%s doing' % c)
        ids = [p['dev_by_key'][k] for k, r in members if k in p['dev_by_key']]
        if c in p['new_playlists']:
            E.playlist_create(root, c)
        E.playlist_set_tracks(root, c, ids)
        print('  playlist %-30s %d tracks' % (c[:30], len(ids)))
        print('@@ p:%s done' % c)

    # 4. write, verify, bookkeeping
    # THE POINT OF NO RETURN. Everything above this line is recoverable by
    # doing nothing: copied files the database does not mention are orphans
    # that the next sync tidies, and the database on the device is untouched.
    # From here the device is committed.
    print('@@ write doing')
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
    # RECORD THE ANCESTOR. What we just wrote, and the mtime of the file we
    # wrote it from -- the two things that make the next plan able to say
    # which side moved rather than only that they differ. Both are free.
    from . import tags as _T
    for k in list(p.get('origin_of') or {}):
        rr = st['tracks'].get(k)
        if not rr:
            continue
        src = p['origin_of'][k]
        if not os.path.exists(src):
            continue
        try:
            snap = _T.read(src)
        except Exception:
            snap = {}
        rr.setdefault('device', {})['synced'] = {
            'at': int(time.time()),
            'mtime': os.path.getmtime(src),
            'tags': {f: (snap.get(f) or '') for f in TAGGED},
        }
    st['synced_playlists'] = sorted((set(st.get('synced_playlists', [])) | set(p['collections']))
                                    - set(p['delete_playlists']))
    S.save(st)
    print('@@ write done')
    print('@@ verify doing')
    print('## verify')
    print('\ndatabase written and verified on device: %d bytes, hash58 OK' % len(out))
    print('@@ verify done')
    if eject:
        print('@@ eject doing')
        print('## eject')
        subprocess.run(['sync']); subprocess.run(['diskutil', 'eject', mount])
        print('ejected')
        print('@@ eject done')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['plan', 'sync'])
    ap.add_argument('--exclude', default=None,
                    help='JSON file naming tracks/playlists to leave out of this sync')
    ap.add_argument('--mount', default=None)
    ap.add_argument('--no-eject', action='store_true')
    a = ap.parse_args()
    _cfg()
    a.mount = a.mount or MOUNT
    if not os.path.exists(os.path.join(a.mount, DB_REL)):
        sys.exit('iPod not mounted at %s' % a.mount)
    ex = json.load(open(a.exclude)) if a.exclude else None
    if a.cmd == 'plan':
        print_plan(drop_excluded(plan(a.mount), ex))
    else:
        sync(a.mount, eject=not a.no_eject, exclude=ex)


if __name__ == '__main__':
    main()
