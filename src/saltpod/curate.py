#!/usr/bin/env python3
"""The whole tool, as one local page.

    python3 src/curate.py            # or double-click ipod-playlists.command

Everything happens in the browser after that: exporting playlists out of
Music.app, matching them against iTunes, checking Bandcamp, curating, building
collections, and reading the buy and vinyl lists. There is no second CLI to
learn. One command exists only because something has to open the door.

WHY A LOCAL SERVER AND NOT A PUBLISHED ARTIFACT. The artifact sandbox blocks
media from non-allowlisted hosts, so Apple's 30s previews will not play there,
and ~200 embedded previews would exceed the 16MB page cap. It also cannot run
`osascript` against Music.app or touch the iPod. Served from here, previews
stream, and every decision lands in data/state.json -- in git, diffable --
rather than in a browser.

Slow work (matching a month is minutes) runs as a background job; the page polls
/api/job and streams the log, so the browser never blocks.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
from . import state as S  # noqa: E402

LOCK = threading.Lock()
JOBS = {}
JOBS_LOCK = threading.Lock()


# ---------------------------------------------------------------- jobs

class Job:
    def __init__(self, name):
        self.id = '%s-%d' % (name, int(time.time() * 1000) % 10_000_000)
        self.name = name
        self.state = 'running'
        self.log = []
        self.started = time.time()

    def line(self, s):
        with JOBS_LOCK:
            self.log.append(s.rstrip())
            del self.log[:-400]          # a long match run must not eat memory

    def as_dict(self):
        return {'id': self.id, 'name': self.name, 'state': self.state,
                'log': self.log[-60:], 'seconds': round(time.time() - self.started)}


def run_job(name, steps):
    """steps: list of (label, argv) or (label, callable)."""
    job = Job(name)
    with JOBS_LOCK:
        JOBS[job.id] = job

    def work():
        try:
            for label, step in steps:
                job.line('--- %s' % label)
                if callable(step):
                    step(job)
                    continue
                p = subprocess.Popen(step, cwd=ROOT, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, bufsize=1,
                                     env={**os.environ,
                                          'DEVELOPER_DIR': '/Library/Developer/CommandLineTools'})
                for ln in p.stdout:
                    job.line(ln)
                if p.wait() != 0:
                    job.line('!! exited %d' % p.returncode)
                    job.state = 'error'
                    return
            S.rebuild(verbose=False)
            job.line('--- state rebuilt')
            job.state = 'done'
        except Exception as e:
            job.line('!! %s' % e)
            job.state = 'error'

    threading.Thread(target=work, daemon=True).start()
    return job


def playlist_slugs():
    return sorted(os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(ROOT, 'data/exports/*.json')))


def music_playlists():
    """Names and track counts straight out of Music.app."""
    try:
        out = subprocess.run(['osascript', '-l', 'JavaScript',
                              os.path.join(ROOT, 'bin/export_playlists.js'), '--list'],
                             capture_output=True, text=True, timeout=180, cwd=ROOT).stdout
        return json.loads(out)
    except Exception:
        return []


# ---------------------------------------------------------------- data

def tracks_payload(scope=''):
    st = S.load()
    out = []
    for k, r in st['tracks'].items():
        if scope and not any(p.startswith(scope) for p in r['playlists']):
            continue
        it = r.get('itunes') or {}
        art = (it.get('art') or '').replace('100x100bb', '300x300bb')
        dev = r.get('device') or {}
        out.append({
            'device': bool(dev), 'dev_album': dev.get('album'),
            'dev_seconds': dev.get('seconds'), 'origin_ext': dev.get('origin_ext'),
            'lossless': dev.get('lossless'),
            'audio': bool(dev.get('origin') or dev.get('location')),
            'key': k, 'artist': r['artist'], 'title': r['title'],
            'playlists': r['playlists'], 'tier': r['tier'], 'vinyl': r['vinyl'],
            'bought': r['bought'], 'on_ipod': r['on_ipod'],
            'collections': r['collections'], 'note': r.get('note', ''),
            'orphan': bool(r.get('orphan')),
            'album': it.get('album'), 'genre': it.get('genre'),
            'released': it.get('released'), 'price': it.get('price'),
            'seconds': it.get('seconds'), 'url': it.get('url'),
            'preview': it.get('preview'), 'art': art,
            'bandcamp': (r.get('bandcamp') or {}).get('url'),
            'bc_verdict': (r.get('bandcamp') or {}).get('verdict'),
        })
    order = {p: i for i, p in enumerate(sorted({p for t in out for p in t['playlists']}))}
    out.sort(key=lambda t: (order.get(t['playlists'][0], 99) if t['playlists'] else 99,
                            t['artist'].lower(), t['title'].lower()))
    st_cols = sorted(st.get('collections', []))
    order = {c: S.order_for(st, c) for c in st_cols}
    return {'tracks': out, 'collections': st_cols, 'order': order,
            'slugs': playlist_slugs(), 'updated': st.get('updated')}


def apply_decision(body):
    with LOCK:
        st = S.load()
        keys = body.get('keys') or ([body['key']] if body.get('key') else [])
        touched = []
        for k in keys:
            rec = st['tracks'].get(k)
            if not rec:
                continue
            if 'tier' in body and body['tier'] in S.TIERS:
                rec['tier'] = body['tier']
                rec['decided_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
            for f in ('vinyl', 'bought', 'on_ipod'):
                if f in body:
                    rec[f] = bool(body[f])
            if 'note' in body:
                rec['note'] = str(body['note'])[:500]
            if 'collection' in body:
                c = str(body['collection']).strip()[:60]
                if c:
                    mode = body.get('mode')          # add | remove | toggle
                    has = c in rec['collections']
                    order = st.setdefault('collection_order', {}).setdefault(c, [])
                    if mode == 'add' or (mode != 'remove' and not has):
                        if not has:
                            rec['collections'].append(c)
                            rec['collections'].sort()
                            order.append(k)          # new members go to the END
                    elif has:
                        rec['collections'].remove(c)
                        if k in order:
                            order.remove(k)
                    st['collections'] = sorted(set(st.get('collections', [])) | {c})
            touched.append(k)
        if 'reorder' in body:
            r = body['reorder']
            S.set_order(st, str(r.get('collection', '')), [str(x) for x in r.get('keys', [])])
        if 'rename_collection' in body:
            old, new = body['rename_collection'], str(body.get('to', '')).strip()[:60]
            for rec in st['tracks'].values():
                if old in rec['collections']:
                    rec['collections'].remove(old)
                    if new:
                        rec['collections'].append(new)
                    rec['collections'].sort()
            cols = set(st.get('collections', [])) - {old}
            co = st.setdefault('collection_order', {})
            seq = co.pop(old, [])
            if new:
                cols.add(new)
                co[new] = seq
            st['collections'] = sorted(cols)
        S.save(st)
        return {'ok': True, 'touched': touched}


# ---------------------------------------------------------------- audio

# Chrome will not play AIFF and is patchy on FLAC; Safari is the other way round.
# Rather than guess at the browser, anything outside this set is transcoded.
DIRECT = {'.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.aac': 'audio/aac',
          '.wav': 'audio/wav'}


def audio_source(key, mount=None):
    """Prefer the T7 original; fall back to the copy on the device."""
    if mount is None:
        from . import config
        try:
            mount = config.load()['mount']
        except SystemExit:
            mount = '/Volumes/IPOD'
    rec = S.load()['tracks'].get(key) or {}
    dev = rec.get('device') or {}
    o = dev.get('origin')
    if o and os.path.exists(o):
        return o
    loc = dev.get('location')
    if loc:
        from . import itunesdb as I
        p = I.ipod_path(loc, mount)
        if os.path.exists(p):
            return p
    return None


# ---------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json'):
        b = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == '/':
            return self._send(200, open(os.path.join(HERE, 'curate.html')).read(),
                              'text/html; charset=utf-8')
        if u.path == '/api/tracks':
            return self._send(200, json.dumps(tracks_payload((q.get('scope') or [''])[0])))
        if u.path == '/api/job':
            with JOBS_LOCK:
                j = JOBS.get((q.get('id') or [''])[0])
            return self._send(200, json.dumps(j.as_dict() if j else {'state': 'gone'}))
        if u.path == '/api/audio':
            return self._audio((q.get('key') or [''])[0])
        if u.path == '/api/music':
            return self._send(200, json.dumps({'playlists': music_playlists(),
                                               'have': playlist_slugs()}))
        return self._send(404, '{}')

    def _audio(self, key):
        path = audio_source(key)
        if not path:
            return self._send(404, json.dumps({'error': 'no local file'}))
        ext = os.path.splitext(path)[1].lower()
        if ext in DIRECT:
            return self._file(path, DIRECT[ext])
        return self._transcode(path)

    def _file(self, path, ctype):
        """Serve with Range support, or the browser cannot seek."""
        size = os.path.getsize(path)
        rng = self.headers.get('Range')
        start, end = 0, size - 1
        code = 200
        if rng and rng.startswith('bytes='):
            try:
                a, _, b = rng[6:].partition('-')
                start = int(a) if a else 0
                end = int(b) if b else size - 1
                end = min(end, size - 1)
                code = 206
            except ValueError:
                start, end, code = 0, size - 1, 200
        length = max(0, end - start + 1)
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(length))
        if code == 206:
            self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, size))
        self.end_headers()
        with open(path, 'rb') as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(262144, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return               # the user hit play on something else
                left -= len(chunk)

    def _transcode(self, path):
        """AIFF/FLAC/etc -> mp3 on the fly. No Range: it is a live stream."""
        self.send_response(200)
        self.send_header('Content-Type', 'audio/mpeg')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        # -vn and an explicit audio map are NOT optional: these AIFFs carry
        # embedded cover art as an mjpeg stream, and ffmpeg will happily mux it
        # into the mp3 as a PNG -- which inflated a 3:28 track to a 9:01 file.
        p = subprocess.Popen(
            ['ffmpeg', '-v', 'quiet', '-i', path, '-vn', '-map', '0:a:0',
             '-f', 'mp3', '-b:a', '192k', '-'],
            stdout=subprocess.PIPE)
        try:
            while True:
                chunk = p.stdout.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            p.kill()                     # skipping tracks must not leave ffmpeg running

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get('Content-Length') or 0)
        try:
            body = json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            return self._send(400, json.dumps({'ok': False, 'error': 'bad json'}))
        try:
            if u.path == '/api/decide':
                return self._send(200, json.dumps(apply_decision(body)))
            if u.path == '/api/action':
                return self._send(200, json.dumps(self._action(body)))
        except Exception as e:
            return self._send(500, json.dumps({'ok': False, 'error': str(e)}))
        return self._send(404, '{}')

    def _action(self, body):
        a = body.get('action')
        py = sys.executable
        if a == 'rebuild':
            S.rebuild(verbose=False)
            return {'ok': True}
        if a == 'device':
            S.import_device(verbose=False)
            return {'ok': True}
        if a == 'reports':
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                S.buylist()
                S.vinyl_list()
            return {'ok': True, 'output': buf.getvalue()}
        if a == 'export':
            names = body.get('names') or []
            steps = [('export %s' % nm,
                      ['osascript', '-l', 'JavaScript', 'bin/export_playlists.js', nm])
                     for nm in names]
            if not steps:
                return {'ok': False, 'error': 'no playlists named'}
            return {'ok': True, 'job': run_job('export', steps).id}
        if a == 'match':
            slugs = body.get('slugs') or []
            steps = [('match %s' % s, [py, 'src/itunes_match.py', s]) for s in slugs]
            if not steps:
                return {'ok': False, 'error': 'no playlists named'}
            return {'ok': True, 'job': run_job('match', steps).id}
        if a == 'verify':
            slugs = body.get('slugs') or []
            steps = [('verify %s' % s, [py, 'src/verify_bandcamp.py', s]) for s in slugs]
            if not steps:
                return {'ok': False, 'error': 'no playlists named'}
            return {'ok': True, 'job': run_job('verify', steps).id}
        return {'ok': False, 'error': 'unknown action %r' % a}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=7654)
    ap.add_argument('--no-open', action='store_true')
    a = ap.parse_args(argv)

    if not S.load()['tracks']:
        print('first run - building state'); S.rebuild()

    srv = ThreadingHTTPServer(('127.0.0.1', a.port), Handler)
    url = 'http://127.0.0.1:%d/' % a.port
    print('ipod-playlists  ->  %s' % url)
    print('everything happens in the page. ctrl-c here when done.')
    if not a.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\nstopped. state: %s' % os.path.relpath(S.STATE, ROOT))


if __name__ == '__main__':
    main()
