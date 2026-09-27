#!/usr/bin/env python3
"""Match what is ON the iPod back to the originals on the T7.

The iPod holds transcoded copies under scrambled four-letter names
(`Music/F19/MLTO.m4a`), so the filesystem tells you nothing about provenance.
The database does: it carries artist, title, album and duration for every track.
Matching those against an ffprobe index of the T7 answers three questions that
decide what to do next:

  1. Which iPod tracks have a **lossless original** worth re-encoding properly?
  2. Which exist **only on the iPod** -- a one-copy situation, and the only
     thing here that is actually at risk?
  3. Which T7 originals are **not on the iPod** at all?

    python3 src/reconcile.py                       # uses the default mount
    python3 src/reconcile.py --mount /Volumes/IPOD

Read-only on both sides.
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
from . import itunesdb as I  # noqa: E402

INDEX = os.path.join(ROOT, 'data', 'local', 'index.json')
OUT = os.path.join(ROOT, 'data', 'local', 'reconcile.json')
LOSSLESS = {'.flac', '.wav', '.aiff', '.aif', '.alac'}


def norm(s):
    s = unicodedata.normalize('NFD', (s or '').lower())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.replace('&', 'and')
    s = re.sub(r'\b(feat|ft|featuring)\b.*', '', s)      # credits drift between sources
    s = re.sub(r'\(.*?\)|\[.*?\]', ' ', s)
    s = re.sub(r"[^a-z0-9]+", ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--mount', default=None)
    ap.add_argument('--tolerance', type=float, default=3.0, help='seconds')
    a = ap.parse_args(argv)
    if a.mount is None:
        from . import config
        a.mount = config.load()['mount']

    if not os.path.exists(INDEX):
        sys.exit('no local index yet - run: python3 src/local_index.py <your music folder>')
    lib = json.load(open(INDEX))['tracks']

    dbp = os.path.join(a.mount, 'iPod_Control/iTunes/iTunesDB')
    if not os.path.exists(dbp):
        dbp = os.path.join(ROOT, 'backups/ipod-2026-09-27/iTunesDB')
        if not os.path.exists(dbp):
            sys.exit('iPod not mounted and no backup to read')
        print('(iPod not mounted - reading the backup)')
    db = I.read(dbp)

    # index the library by artist|title, then by title alone as a fallback
    by_at, by_t = defaultdict(list), defaultdict(list)
    for e in lib:
        at, t = norm(e.get('artist')), norm(e.get('title'))
        if t:
            if at:
                by_at['%s|%s' % (at, t)].append(e)
            by_t[t].append(e)

    matched, ipod_only, ambiguous = [], [], []
    for tr in db['tracks']:
        at = '%s|%s' % (norm(tr.get('artist')), norm(tr.get('title')))
        cands = by_at.get(at) or []
        how = 'artist+title'
        if not cands:
            cands = by_t.get(norm(tr.get('title'))) or []
            how = 'title only'
        secs = (tr.get('ms') or 0) / 1000.0
        near = [c for c in cands if abs((c.get('duration_sec') or 0) - secs) <= a.tolerance] \
            if secs else cands
        if not near:
            (ipod_only if not cands else ambiguous).append(
                {'artist': tr.get('artist'), 'title': tr.get('title'),
                 'seconds': round(secs, 1), 'reason': 'no source' if not cands else 'length differs'})
            continue
        # prefer a lossless original, then the largest file
        near.sort(key=lambda c: (c['ext'] not in LOSSLESS, -(os.path.getsize(c['path'])
                                 if os.path.exists(c['path']) else 0)))
        best = near[0]
        matched.append({'artist': tr.get('artist'), 'title': tr.get('title'),
                        'ipod': tr.get('location'), 'origin': best['path'],
                        'ext': best['ext'], 'lossless': best['ext'] in LOSSLESS,
                        'how': how, 'candidates': len(near)})

    origins = {m['origin'] for m in matched}
    not_on_ipod = [e for e in lib if e['path'] not in origins]

    n = len(db['tracks'])
    print('iPod database        : %d tracks' % n)
    print('T7 library indexed   : %d files' % len(lib))
    print()
    print('matched to an original     : %-4d (%.0f%%)' % (len(matched), 100 * len(matched) / max(n, 1)))
    print('   of those, lossless      : %d' % sum(1 for m in matched if m['lossless']))
    print('   matched on title only   : %d  <- weaker, check these' % sum(1 for m in matched if m['how'] == 'title only'))
    print('length differs             : %-4d <- same name, different cut' % len(ambiguous))
    print('ONLY ON THE IPOD           : %-4d <- no original anywhere. One copy.' % len(ipod_only))
    print()
    print('on the T7 but not the iPod : %d' % len(not_on_ipod))

    if ipod_only:
        print('\nat risk (first 10):')
        for r in ipod_only[:10]:
            print('   %-30s %-34s %s' % ((r['artist'] or '?')[:30], (r['title'] or '?')[:34], r['reason']))

    json.dump({'matched': matched, 'ipod_only': ipod_only, 'ambiguous': ambiguous,
               'not_on_ipod': [e['path'] for e in not_on_ipod]},
              open(OUT, 'w'), indent=1, ensure_ascii=False)
    print('\nwritten: %s' % os.path.relpath(OUT, ROOT))


if __name__ == '__main__':
    main()
