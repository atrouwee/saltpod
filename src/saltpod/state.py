#!/usr/bin/env python3
"""The curation state: one record per track, decisions preserved across rebuilds.

Four tiers, per AJ's own model:

    seen         it turned up in a monthly playlist. The default, not a choice.
    shortlisted  I want this in lossless.       -> feeds the buy guides
    maybe        defer; resurfaces next quarter.
    skipped      not this one.

plus two independent flags that are NOT tiers, because they answer different
questions: `vinyl` (feeds a Discogs want-list) and `bought` (a file exists).
`on_ipod` is owned by the sync step, never by curation.

Monthly playlists are METADATA here, not structure -- a track carries the list
of months it appeared in, and the playlists that reach the iPod are the
user-named `collections` built during curation.

    python3 src/state.py rebuild      # merge new playlist data in, keep decisions
    python3 src/state.py device       # pull in what is already on the iPod
    python3 src/state.py stats
    python3 src/state.py buylist      # what I actually chose to buy -> reports/
    python3 src/state.py vinyl        # the Discogs want-list
    python3 src/state.py collections  # what would go on the iPod, by collection

REBUILD IS NON-DESTRUCTIVE BY CONSTRUCTION. It only ever writes identity fields
(what iTunes and Bandcamp say). Everything a human decided -- tier, vinyl,
collections, bought -- is copied forward untouched. A track that vanishes from
the exports keeps its record and is flagged `orphan` rather than deleted.
"""
import glob
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE = os.path.join(ROOT, 'data', 'state.json')

DECISION_FIELDS = ('tier', 'vinyl', 'collections', 'bought', 'on_ipod', 'note', 'decided_at')
TIERS = ('seen', 'shortlisted', 'maybe', 'skipped')


def key_for(artist, title):
    """Stable identity for a track across playlists and reruns."""
    s = '%s|%s' % (artist or '', title or '')
    s = unicodedata.normalize('NFD', s.lower())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.replace('&', 'and').replace("’", "'")
    s = re.sub(r"[^a-z0-9|']+", '-', s)
    return re.sub(r'-+', '-', s).strip('-')


def load():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {'version': 1, 'tracks': {}, 'collections': []}


def save(st):
    st['updated'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(st, f, indent=1, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, STATE)          # atomic: a crash mid-write cannot truncate state


def import_device(mount=None, verbose=True):
    """Bring the tracks already ON the iPod into curation.

    These merge with playlist tracks by the same key, so something that is both
    in a 2026 monthly and already on the device becomes ONE record carrying
    both facts. For a device track the tiers read differently but mean the same
    thing: `shortlisted` = keep it, `skipped` = take it off.

    Sets bought=True: it is on the device, so it is owned, whatever route it
    took to get there.
    """
    from . import itunesdb as I
    if mount is None:
        from . import config
        mount = config.load()['mount']
    dbp = os.path.join(mount, 'iPod_Control/iTunes/iTunesDB')
    if not os.path.exists(dbp):
        cand = sorted(glob.glob(os.path.join(ROOT, 'backups/ipod-*/iTunesDB')))
        if not cand:
            raise SystemExit('iPod not mounted and no backup found')
        dbp = cand[-1]
        if verbose:
            print('(iPod not mounted - reading %s)' % os.path.relpath(dbp, ROOT))
    db = I.read(dbp)

    origin = {}
    rec_path = os.path.join(ROOT, 'data/local/reconcile.json')
    if os.path.exists(rec_path):
        for m in json.load(open(rec_path))['matched']:
            origin[key_for(m['artist'], m['title'])] = m

    st = load()
    added = merged = 0
    for t in db['tracks']:
        artist, title = t.get('artist') or '', t.get('title') or ''
        if not (artist or title):
            continue
        k = key_for(artist, title)
        if k in st['tracks']:
            merged += 1
        else:
            st['tracks'][k] = blank(artist, title)
            added += 1
        r = st['tracks'][k]
        r['on_ipod'] = True
        r['bought'] = True
        r['device'] = {'location': t.get('location'), 'album': t.get('album'),
                       'seconds': round((t.get('ms') or 0) / 1000.0, 1),
                       'size': t.get('size'), 'bitrate': t.get('bitrate')}
        o = origin.get(k)
        if o:
            r['device']['origin'] = o['origin']
            r['device']['origin_ext'] = o['ext']
            r['device']['lossless'] = o['lossless']
    adopted = adopt_device_playlists(st, db)
    save(st)
    if verbose:
        print('%d device tracks: %d new, %d merged with playlist records'
              % (len(db['tracks']), added, merged))
        if adopted:
            print('%d playlists on the device became collections: %s'
                  % (len(adopted), ', '.join(adopted)))
    return st


def adopt_device_playlists(st, db):
    """Every non-smart playlist the iPod carries is a collection.

    The owner's rule: no difference between what this tool made and what was
    already there -- the only exception is a smart playlist, which the
    firmware owns. So each one is adopted into state under its own name, in
    the device's order, and into synced_playlists, so that deleting it in the
    page deletes it on the next sync exactly as for any other collection.

    A name already in synced_playlists is skipped even if it is not a
    collection: that is a deletion waiting to be synced, not a playlist to
    resurrect.
    """
    by_id = {t['id']: key_for(t.get('artist'), t.get('title')) for t in db['tracks']}
    cols = set(st.get('collections', []))
    synced = set(st.get('synced_playlists', []))
    order = st.setdefault('collection_order', {})
    adopted = []
    for p in db.get('playlists') or []:
        name = p.get('name') or ''
        if not name or p.get('master') or p.get('smart'):
            continue
        if name in cols or name in synced:
            continue
        keys = []
        for it in p.get('items') or []:
            k = by_id.get(it if isinstance(it, int) else None)
            if k and k in st['tracks'] and k not in keys:
                keys.append(k)
        for k in keys:
            rec = st['tracks'][k]
            if name not in rec['collections']:
                rec['collections'].append(name)
                rec['collections'].sort()
        order[name] = keys
        cols.add(name)
        synced.add(name)
        adopted.append(name)
    st['collections'] = sorted(cols)
    st['synced_playlists'] = sorted(synced)
    return adopted


def order_for(st, name):
    """The sequence of a collection -- the source of truth for what the iPod
    plays in what order. Self-healing: members with no position are appended
    (in artist/title order, so first-time migration is deterministic), and
    positions for tracks no longer in the collection are dropped.
    """
    members = {k for k, r in st['tracks'].items() if name in r['collections']}
    order = [k for k in st.setdefault('collection_order', {}).get(name, []) if k in members]
    missing = sorted(members - set(order),
                     key=lambda k: (st['tracks'][k]['artist'].lower(), st['tracks'][k]['title'].lower()))
    order += missing
    st['collection_order'][name] = order
    return order


def set_order(st, name, keys):
    """Replace a collection's sequence. Keys not in the collection are ignored;
    members missing from `keys` keep their relative order at the end."""
    members = {k for k, r in st['tracks'].items() if name in r['collections']}
    new = [k for k in keys if k in members]
    seen = set(new)
    new += [k for k in order_for(st, name) if k not in seen]
    st.setdefault('collection_order', {})[name] = new
    return new


def blank(artist, title):
    return {'artist': artist, 'title': title, 'playlists': [],
            'tier': 'seen', 'vinyl': False, 'collections': [], 'bought': False,
            'on_ipod': False, 'note': '', 'decided_at': None}


def rebuild(verbose=True):
    st = load()
    tracks = st['tracks']
    seen_now = set()

    for path in sorted(glob.glob(os.path.join(ROOT, 'data/exports/*.json'))):
        slug = os.path.splitext(os.path.basename(path))[0]
        if slug.startswith('_'):
            continue                      # a cache or a note, not a playlist
        d = json.load(open(path))
        items = d.get('tracks') if isinstance(d, dict) else d
        if not isinstance(items, list):
            if verbose:
                print('skipping %s: not a playlist export' % os.path.basename(path))
            continue

        itunes = {}
        for f in sorted(glob.glob(os.path.join(ROOT, 'data/itunes', slug, '0*.json'))):
            i = int(os.path.basename(f)[:3])
            res = (json.load(open(f)).get('results') or [None])[0]
            if res:
                itunes[i] = res

        bandcamp = {}
        bc_path = os.path.join(ROOT, 'data/bandcamp', '%s_verified.json' % slug)
        if os.path.exists(bc_path):
            for r in json.load(open(bc_path)):
                bandcamp[r['i']] = r

        for n, t in enumerate(items, 1):
            artist = t.get('artist') or ''
            title = t.get('name') or t.get('title') or ''
            if not (artist or title):
                continue
            k = key_for(artist, title)
            seen_now.add(k)
            rec = tracks.setdefault(k, blank(artist, title))
            rec.pop('orphan', None)
            # Where it lives in Apple Music. `owned` comes from cloudStatus in
            # the export: purchased, uploaded or matched, as against a
            # subscription rental, which is a .movpkg and will never play on a
            # Classic. Only ~110 of 4,876 library tracks are genuinely owned,
            # which is the whole reason the buy list exists. A record is owned
            # if ANY export says so -- one playlist knowing is enough.
            if t.get('owned'):
                rec['am_owned'] = True
            rec.setdefault('am_owned', False)
            cs = t.get('cloud_status')
            if cs and cs != 'subscription':
                rec['am_status'] = cs        # 'no longer available' -- the rental is gone
            if slug not in rec['playlists']:
                rec['playlists'].append(slug)
                rec['playlists'].sort()

            r = itunes.get(n)
            if r:
                rec['itunes'] = {
                    'track_id': r.get('trackId'), 'album_id': r.get('collectionId'),
                    'album': r.get('collectionName'), 'genre': r.get('primaryGenreName'),
                    'released': (r.get('releaseDate') or '')[:10],
                    'price': r.get('trackPrice'), 'url': r.get('trackViewUrl'),
                    'preview': r.get('previewUrl'), 'art': r.get('artworkUrl100'),
                    'seconds': round((r.get('trackTimeMillis') or 0) / 1000.0, 1) or None,
                }
            b = bandcamp.get(n)
            if b and b.get('url'):
                rec['bandcamp'] = {'url': b['url'], 'verdict': b.get('verdict'),
                                   'seconds': b.get('bandcamp_sec')}

    orphans = 0
    for k, rec in tracks.items():
        if k not in seen_now:
            rec['orphan'] = True           # kept, never deleted - a decision lives here
            orphans += 1

    save(st)
    if verbose:
        print('%d tracks in state (%d newly seen this run, %d orphaned)'
              % (len(tracks), len(seen_now - set()) and len(seen_now), orphans))
    return st


def stats():
    st = load()
    tr = st['tracks']
    if not tr:
        print('no state yet - run: python3 src/state.py rebuild'); return
    by = {}
    for r in tr.values():
        by[r['tier']] = by.get(r['tier'], 0) + 1
    print('%d tracks' % len(tr))
    for t in TIERS:
        if by.get(t):
            print('  %-12s %4d' % (t, by[t]))
    print('  %-12s %4d' % ('bought', sum(1 for r in tr.values() if r['bought'])))
    print('  %-12s %4d' % ('vinyl', sum(1 for r in tr.values() if r['vinyl'])))
    print('  %-12s %4d' % ('on iPod', sum(1 for r in tr.values() if r['on_ipod'])))
    miss = sum(1 for r in tr.values() if not r.get('itunes'))
    if miss:
        print('  %-12s %4d  (no iTunes identity - run itunes_match)' % ('unmatched', miss))
    cols = {}
    for r in tr.values():
        for c in r['collections']:
            cols[c] = cols.get(c, 0) + 1
    if cols:
        print('\ncollections')
        for c, n in sorted(cols.items(), key=lambda kv: -kv[1]):
            print('  %-24s %4d' % (c, n))


def _fmt(sec):
    return '%d:%02d' % (int(sec) // 60, int(sec) % 60) if sec else '?'


def buylist():
    """The buy guide for what was CHOSEN, not for whole playlists."""
    st = load()
    sel = [r for r in st['tracks'].values() if r['tier'] == 'shortlisted' and not r['bought']]
    if not sel:
        print('nothing shortlisted yet - curate first: python3 src/curate.py'); return
    sel.sort(key=lambda r: (r['artist'].lower(), r['title'].lower()))
    itunes_total = sum((r.get('itunes') or {}).get('price') or 0 for r in sel)
    have_flac = [r for r in sel if (r.get('bandcamp') or {}).get('verdict') == 'confirmed']

    L = ['# Buy list - chosen, not defaulted\n',
         '%d tracks shortlisted and not yet bought.\n' % len(sel),
         '| | |', '|---|---|',
         '| iTunes equivalent (AAC 256) | **EUR %.2f** |' % itunes_total,
         '| of these, confirmed lossless on Bandcamp | **%d** |' % len(have_flac), '']
    for r in sel:
        it = r.get('itunes') or {}
        bc = r.get('bandcamp') or {}
        months = ', '.join(p.replace('2026-', '').title() for p in r['playlists'])
        L.append('### %s - %s' % (r['artist'], r['title']))
        bits = [_fmt(it.get('seconds'))]
        if it.get('album'):
            bits.append(it['album'])
        bits.append('from %s' % months)
        if r['vinyl']:
            bits.append('**also wanted on vinyl**')
        if r['collections']:
            bits.append('for: %s' % ', '.join(r['collections']))
        L.append('- ' + '  ·  '.join(bits))
        links = []
        if bc.get('url'):
            tag = 'Bandcamp FLAC' + (' (duration confirmed)' if bc.get('verdict') == 'confirmed'
                                     else ' (CHECK LENGTH)')
            links.append('[%s](%s)' % (tag, bc['url']))
        if it.get('url'):
            links.append('[iTunes AAC 256 - EUR %.2f](%s)' % (it.get('price') or 0, it['url']))
        if links:
            L.append('')
            L.append('  ' + '  ·  '.join(links))
        L.append('')
    out = os.path.join(ROOT, 'reports', 'buylist.md')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, 'w').write('\n'.join(L) + '\n')
    print('%d tracks, EUR %.2f at iTunes prices, %d confirmed lossless'
          % (len(sel), itunes_total, len(have_flac)))
    print('written: %s' % os.path.relpath(out, ROOT))


def vinyl_list():
    st = load()
    sel = [r for r in st['tracks'].values() if r['vinyl']]
    if not sel:
        print('nothing flagged for vinyl'); return
    sel.sort(key=lambda r: (r['artist'].lower(), r['title'].lower()))
    L = ['# Vinyl want-list\n',
         'Flagged during curation. Search Discogs by RELEASE, not by track - '
         'the album is what is for sale.\n']
    by_album = {}
    for r in sel:
        alb = (r.get('itunes') or {}).get('album') or '(unknown release)'
        by_album.setdefault((r['artist'], alb), []).append(r)
    for (artist, alb), rs in sorted(by_album.items()):
        q = ('%s %s' % (artist, alb)).replace(' ', '+')
        L.append('- **%s - %s** (%d track%s: %s)  '
                 % (artist, alb, len(rs), '' if len(rs) == 1 else 's',
                    ', '.join(x['title'] for x in rs)))
        L.append('  [Discogs](https://www.discogs.com/search/?q=%s&type=release)' % q)
    out = os.path.join(ROOT, 'reports', 'vinyl-wantlist.md')
    open(out, 'w').write('\n'.join(L) + '\n')
    print('%d tracks across %d releases -> %s'
          % (len(sel), len(by_album), os.path.relpath(out, ROOT)))


def collections():
    """What would actually go on the iPod, as the user named it."""
    st = load()
    cols = {}
    for r in st['tracks'].values():
        for c in r['collections']:
            cols.setdefault(c, []).append(r)
    if not cols:
        print('no collections yet - press c while curating'); return
    for c, rs in sorted(cols.items()):
        ready = [r for r in rs if r['bought']]
        print('%-26s %3d tracks  %3d owned  %3d still to buy'
              % (c, len(rs), len(ready), len(rs) - len(ready)))


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'stats'
    if cmd == 'rebuild':
        rebuild()
    elif cmd == 'stats':
        stats()
    elif cmd == 'device':
        import_device()
    elif cmd == 'buylist':
        buylist()
    elif cmd == 'vinyl':
        vinyl_list()
    elif cmd == 'collections':
        collections()
    else:
        sys.exit(__doc__)
