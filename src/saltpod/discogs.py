"""Discogs exports, read as they come.

Discogs lets you download two CSVs: the collection (what is owned) and the
wantlist (what is wanted). Drop them at data/discogs/collection.csv and
data/discogs/wantlist.csv and they are read on every load; nothing is fetched.

Two things about the files that cost a look: the wantlist export carries one
more column than its header names -- a trailing "Date Added" -- so headers are
padded rather than trusted; and Discogs disambiguates artists as "Ada (2)",
which the match key strips along with any other bracketed suffix.
"""
import csv
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DIR = os.path.join(ROOT, 'data', 'discogs')
FILES = {'collection': 'collection.csv', 'wantlist': 'wantlist.csv'}


def norm(s):
    """A key that lets a track's artist + album meet a release's artist + title."""
    s = (s or '').lower()
    s = re.sub(r'\s*[\(\[].*?[\)\]]', '', s)       # (Remastered), [Deluxe], (2)
    s = re.sub(r'^(the|a)\s+', '', s)
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def _read(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    head = rows[0]
    width = max(len(r) for r in rows)
    if len(head) < width:
        head = head + ['Date Added'] + ['extra%d' % i for i in range(width - len(head) - 1)]
    out = []
    for r in rows[1:]:
        if not any(r):
            continue
        d = dict(zip(head, r + [''] * (len(head) - len(r))))
        out.append({
            'artist': d.get('Artist', ''), 'title': d.get('Title', ''),
            'label': d.get('Label', ''), 'format': d.get('Format', ''),
            'year': d.get('Released', ''), 'catno': d.get('Catalog#', ''),
            'release_id': d.get('release_id', ''), 'added': d.get('Date Added', ''),
            'folder': d.get('CollectionFolder', ''), 'rating': d.get('Rating', ''),
            'media': d.get('Collection Media Condition', ''),
            'sleeve': d.get('Collection Sleeve Condition', ''),
            'notes': d.get('Collection Notes', '') or d.get('Notes', ''),
            'key': norm(d.get('Artist', '')) + '|' + norm(d.get('Title', '')),
        })
    return out


def payload():
    out = {'dir': os.path.relpath(DIR, ROOT), 'files': {}}
    for name, fn in FILES.items():
        path = os.path.join(DIR, fn)
        rel = os.path.relpath(path, ROOT)
        if os.path.exists(path):
            out[name] = _read(path)
            out['files'][name] = {'path': rel, 'rows': len(out[name]),
                                  'modified': time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(path)))}
        else:
            out[name] = []
            out['files'][name] = {'path': rel, 'rows': 0, 'modified': None}
    return out
