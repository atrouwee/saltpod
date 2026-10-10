"""The ground under the page: one luminance measurement per cover, kept.

The page's ground is the selected track's cover, blurred, under a scrim of
the ground colour. How thick that scrim must be depends on how bright the
cover is, and THE PAGE NEVER WORKS THAT OUT: the layer rule says it looks
things up. So the server measures every cover once -- its mean colour, the
luminance of that, and the scrim that keeps the composite at or under the
band's ceiling -- and hands the page `{'y', 'scrim'}` on the row. A row not
yet measured carries `None`, and the page uses the system's unknown default.

The arithmetic is not here. It is saltglass's band.py, vendored as
glassband.py by scripts/vendor_glass.py, so the server and any check run the
one implementation the design system publishes.

WHICH IMAGE. The one the row's `art` shows, and nothing else, or the scrim
answers for a picture nobody sees:

  - `/api/art?key=K` (your own file's cover): the art cache file for K, made
    by the same code /api/art uses -- curate passes it in as `local`, so the
    extraction rule is spelled once.
  - an iTunes URL: downloaded once into the same cache under the same name,
    so /api/art can serve it afterwards too. A file already there is
    measured as it is and never overwritten: it may be a cover you supplied.

THE CACHE is data/local/ground.json, `{key: {'y', 'scrim', 'mean', 'src',
'at'}}`. `src` is the row's art string at the time; a different `src` is a
different picture and is measured again. A cover replaced under the same
`src` (put_art) calls forget(). Re-read from disk whenever its mtime moves,
so a `saltpod ground scan` in the terminal reaches a running server.
"""
import json
import os
import re
import threading
import time
import urllib.request
from urllib.parse import urlparse, parse_qs

from . import glassband as B

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(ROOT, 'data', 'local', 'ground.json')
ART_DIR = os.path.join(ROOT, 'data', 'local', 'art')
USER_AGENT = 'saltpod (cover measurement)'

MeasureError = B.MeasureError

_LOCK = threading.Lock()
_MEM = {'d': None, 'mtime': None}


def art_path(ident):
    """The art cache file for a key or path -- the name /api/art and put_art use."""
    return os.path.join(ART_DIR, re.sub(r'[^A-Za-z0-9]+', '_', ident)[:120] + '.jpg')


def remote(art):
    return bool(art) and art.startswith(('http://', 'https://'))


def _read():
    try:
        with open(CACHE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def cache():
    """The measurements, re-read when the file has changed on disk."""
    with _LOCK:
        try:
            m = os.path.getmtime(CACHE)
        except OSError:
            m = None
        if _MEM['d'] is None or m != _MEM['mtime']:
            _MEM['d'], _MEM['mtime'] = _read(), m
        return _MEM['d']


def _write(mutate):
    """Read-modify-write against the file, not the memory copy, so a server
    and a terminal measuring at the same time do not drop each other's rows."""
    with _LOCK:
        d = _read()
        mutate(d)
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        tmp = CACHE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(d, f, indent=0, sort_keys=True)
            f.write('\n')
        os.replace(tmp, CACHE)
        _MEM['d'], _MEM['mtime'] = d, os.path.getmtime(CACHE)


def lookup(key, art):
    """`{'y', 'scrim'}` for this row's picture, or None if it is not measured."""
    if not art:
        return None
    e = cache().get(key)
    if not e or e.get('src') != art:
        return None
    return {'y': e['y'], 'scrim': e['scrim']}


def forget(key):
    """The picture behind `key` changed without its `src` changing."""
    if key in cache():
        _write(lambda d: d.pop(key, None))


def _fetch(url, out):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            blob = r.read(12 * 1024 * 1024 + 1)
    except Exception as e:
        raise MeasureError('could not download %s: %s' % (url, e))
    if not (blob[:3] == b'\xff\xd8\xff' or blob[:8] == b'\x89PNG\r\n\x1a\n'):
        raise MeasureError('not a jpeg or png: %s' % url)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + '.part'                   # never leave a half-written cover
    with open(tmp, 'wb') as f:
        f.write(blob)
    os.replace(tmp, out)


def picture(key, art, local=None):
    """The file behind a row's `art`: (path, downloaded).

    An iTunes URL is downloaded once into the art cache under the row's key
    (never over a file already there); `/api/art?key=K` is `local(K)`, the
    file /api/art serves. One rule for the ground and for the playlist
    mosaics (mosaic.py), so both read the picture the page shows. Raises
    MeasureError when there is no file to be had.
    """
    downloaded = False
    if remote(art):
        path = art_path(key)
        if not os.path.exists(path):
            _fetch(art, path)
            downloaded = True
    else:
        q = parse_qs(urlparse(art or '').query)
        ident = (q.get('key') or [''])[0] or (q.get('path') or [''])[0]
        if not ident:
            raise MeasureError('no picture behind %r' % art)
        path = local(ident) if local else art_path(ident)
        if not path or not os.path.exists(path):
            raise MeasureError('no cover file for %s' % ident)
    return path, downloaded


def measure_key(key, art, local=None):
    """Measure the picture a row shows and keep the result.

    `local(ident)` returns the art cache file for a local cover, making it
    if need be (curate.art_file); without it only an existing cache file is
    measured. Returns (entry, downloaded). Raises MeasureError when there is
    no picture to measure or ffmpeg cannot read it.
    """
    path, downloaded = picture(key, art, local)
    m = B.measure(path)
    entry = {'y': m['y'], 'scrim': m['scrim'], 'mean': m['mean'], 'src': art,
             'at': time.strftime('%Y-%m-%dT%H:%M:%S')}
    _write(lambda d: d.__setitem__(key, entry))
    return entry, downloaded


def check():
    """Every kept scrim inside the band's range, and what the arithmetic
    gives today from the kept mean (to .01). Returns (n, problems)."""
    d = cache()
    bad = []
    for k, e in sorted(d.items()):
        s = e.get('scrim')
        if not isinstance(s, (int, float)) or not (B.SCRIM_MIN <= s <= B.SCRIM_MAX):
            bad.append('%s: scrim %r outside [%.2f, %.2f]' % (k, s, B.SCRIM_MIN, B.SCRIM_MAX))
            continue
        mean = e.get('mean')
        if not (isinstance(mean, list) and len(mean) == 3):
            bad.append('%s: no mean kept' % k)
            continue
        again = B.scrim_for(tuple(mean))
        if abs(again - s) > .01:
            bad.append('%s: kept %.2f, recomputed %.2f from mean %s' % (k, s, again, mean))
    return len(d), bad


def histogram(scrims, bins=10):
    """Counts of scrims in `bins` equal bins across [SCRIM_MIN, SCRIM_MAX]:
    [(lo, hi, n), ...]."""
    lo, hi = B.SCRIM_MIN, B.SCRIM_MAX
    w = (hi - lo) / bins
    n = [0] * bins
    for s in scrims:
        n[min(bins - 1, max(0, int((s - lo) / w + 1e-9)))] += 1
    return [(lo + i * w, lo + (i + 1) * w, n[i]) for i in range(bins)]
