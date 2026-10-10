"""A playlist's picture: the first four covers of its tracks, tiled 2x2.

The page shows an Apple Music playlist the way it shows an album -- with a
picture -- and THE PAGE NEVER MAKES THAT PICTURE (no canvas, no pixels; the
layer rule). The server tiles it once with ffmpeg, keeps the file in the art
cache beside the covers, and hands the page a URL on the playlist row.

WHICH COVERS. The first four tracks of the playlist, in its own order, that
have a picture -- and the picture is exactly the one each track's row shows
(curate.row_art: the iTunes cover, else your own file's cover through
/api/art), resolved to a file by ground.picture, the rule the ground uses.
Four covers tile 2x2; three repeat the first in the last tile; two stand
side by side, each a half of the square; one is the cover itself; none makes
no file.

WHICH TRACKS. A playlist's members are known on disk only once it has been
imported (data/exports/<slug>.json). Music.app's index read keeps names,
counts and dates, not members, and asking Music.app per playlist is the
automation that wedges -- so a playlist not yet imported has no mosaic, and
its row carries `art: None` (the page draws the empty thumbnail).

THE CACHE is the picture, data/local/art/playlist_<slug>.jpg, and its
receipt in data/local/mosaics.json, `{slug: {'sources': [art, ...], 'at'}}`.
The sources are the four (or fewer) art strings it was made from; when the
playlist's first four with art are no longer those, it is made again.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time

from . import ground as G

ROOT = G.ROOT
ART_DIR = G.ART_DIR
CACHE = os.path.join(ROOT, 'data', 'local', 'mosaics.json')
EXPORTS = os.path.join(ROOT, 'data', 'exports')
TILE = 150                      # each tile; the mosaic is 2 x TILE square

_LOCK = threading.Lock()


class MosaicError(Exception):
    pass


def slug(name):
    """A playlist's slug -- the name its export file and /api/playlists use."""
    return re.sub(r'^-|-$', '', re.sub(r'[^a-z0-9]+', '-', (name or '').lower()))


def valid(s):
    return bool(s) and re.fullmatch(r'[a-z0-9][a-z0-9-]*', s) is not None


def out_path(s):
    return os.path.join(ART_DIR, 'playlist_%s.jpg' % s)


def url(s):
    """The row's `art`: the served mosaic, or None when there is no file."""
    return '/api/art?playlist=' + s if valid(s) and os.path.exists(out_path(s)) else None


def _read():
    try:
        with open(CACHE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def cache():
    with _LOCK:
        return _read()


def _write(mutate):
    with _LOCK:
        d = _read()
        mutate(d)
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        tmp = CACHE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(d, f, indent=0, sort_keys=True)
            f.write('\n')
        os.replace(tmp, CACHE)


def members(s):
    """[(artist, title), ...] in the playlist's order, or [] when the
    playlist has not been imported."""
    try:
        with open(os.path.join(EXPORTS, s + '.json')) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    rows = sorted(d.get('tracks') or [], key=lambda t: t.get('index') or 0)
    return [(t.get('artist'), t.get('title')) for t in rows]


def sources(s, art_of, key_for):
    """The first four (key, art) of the playlist that have a picture.
    `art_of(key)` is the picture a track's row shows, or ''."""
    out, seen = [], set()
    for artist, title in members(s):
        k = key_for(artist, title)
        if k in seen:
            continue
        seen.add(k)
        art = art_of(k)
        if art:
            out.append((k, art))
            if len(out) == 4:
                break
    return out


def _ffmpeg():
    exe = shutil.which('ffmpeg')
    if not exe:
        raise MosaicError('ffmpeg is not installed')
    return exe


def make(key_slug, cover_paths, out):
    """Tile up to four covers into `out` (a 2*TILE square JPEG).

    Four: 2x2. Three: the fourth tile is the first again. Two: side by side,
    each the half of the square it fills. One: the cover itself, squared.
    None: no file (an existing one is removed). Returns `out`, or None.
    """
    paths = list(cover_paths)[:4]
    if not paths:
        if os.path.exists(out):
            os.remove(out)
        return None
    S = 2 * TILE
    fill = 'scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1'
    if len(paths) == 1:
        graph = '[0]' + fill % (S, S, S, S) + '[v]'
    elif len(paths) == 2:
        graph = ('[0]' + fill % (TILE, S, TILE, S) + '[a];'
                 '[1]' + fill % (TILE, S, TILE, S) + '[b];'
                 '[a][b]hstack=inputs=2[v]')
    else:
        if len(paths) == 3:
            paths = paths + [paths[0]]
        graph = ''.join('[%d]%s[t%d];' % (i, fill % (TILE, TILE, TILE, TILE), i)
                        for i in range(4))
        graph += '[t0][t1][t2][t3]xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0[v]'
    cmd = [_ffmpeg(), '-v', 'error', '-y']
    for p in paths:
        cmd += ['-i', p]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + '.part.jpg'
    cmd += ['-filter_complex', graph, '-map', '[v]', '-frames:v', '1',
            '-pix_fmt', 'yuvj420p', '-q:v', '3', tmp]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise MosaicError('ffmpeg could not tile %s: %s'
                          % (key_slug, (r.stderr or '').strip()[:200]))
    os.replace(tmp, out)
    return out


def current(s, srcs):
    """Is the kept mosaic for `s` the one these sources make?"""
    e = cache().get(s)
    arts = [a for _k, a in srcs]
    if not arts:
        return not os.path.exists(out_path(s)) and (not e or not e.get('sources'))
    return bool(e) and e.get('sources') == arts and os.path.exists(out_path(s))


def build(s, art_of, key_for, local=None, force=False):
    """Make (or re-make) the mosaic for playlist `s` when its sources moved.

    Returns (state, downloaded) with state one of 'made', 'current', 'none'
    (no member has a picture; no file is kept). A cover that cannot be had
    is skipped and the next track with a picture takes its place.
    """
    if not valid(s):
        raise MosaicError('not a playlist slug: %r' % s)
    srcs = sources(s, art_of, key_for)
    if not force and current(s, srcs):
        return ('current' if srcs else 'none'), 0
    paths, used, downloaded = [], [], 0
    for k, art in srcs:
        try:
            p, dl = G.picture(k, art, local)
        except G.MeasureError:
            continue
        downloaded += dl
        paths.append(p)
        used.append(art)
    out = make(s, paths, out_path(s))
    entry = {'sources': [a for _k, a in srcs], 'used': used,
             'at': time.strftime('%Y-%m-%dT%H:%M:%S')}
    if out:
        _write(lambda d: d.__setitem__(s, entry))
        return 'made', downloaded
    _write(lambda d: d.pop(s, None))
    return 'none', downloaded


def _is_jpeg(path):
    try:
        with open(path, 'rb') as f:
            return f.read(3) == b'\xff\xd8\xff'
    except OSError:
        return False


def check(art_of, key_for):
    """Every kept mosaic exists, is a non-empty JPEG, and was made from the
    playlist's first four covers as they are today. Returns (n, problems)."""
    d = cache()
    bad = []
    for s, e in sorted(d.items()):
        p = out_path(s)
        if not os.path.exists(p):
            bad.append('%s: no file at %s' % (s, os.path.relpath(p, ROOT)))
            continue
        if os.path.getsize(p) == 0 or not _is_jpeg(p):
            bad.append('%s: not a JPEG (%d bytes)' % (s, os.path.getsize(p)))
            continue
        now = [a for _k, a in sources(s, art_of, key_for)]
        if now != e.get('sources'):
            bad.append('%s: made from %d covers that are no longer its first four with art'
                       % (s, len(e.get('sources') or [])))
    return len(d), bad
