#!/usr/bin/env python3
"""Gate 0: the shape of every reply the server gives, written down.

    python3 bin/contract.py --write          # record contract/ from a fixture server
    python3 bin/contract.py --check          # the same run, compared; exit 1 on any drift
    python3 bin/contract.py --url http://127.0.0.1:7654   # a running server, against the record

WHY. Two clients now read this server -- the page and the native app -- and
the native one decodes with Codable, which fails on a renamed field or a
number that became a string. Nothing noticed that kind of change before:
the page reads `t.foo` and gets undefined, silently. So the replies'
SHAPES are recorded -- field names, JSON types, which fields are optional,
which objects are maps keyed by data -- never their values, which move with
the library. A route change and its snapshot change land in one commit.

WHAT A RUN DOES. It builds the fixture library (fixtures/build.py) in a
temporary directory, refuses to go on unless that home's device.json names
the fake mount, starts `saltpod curate` on it with SALTPOD_HOME pointing
there, listens on /api/events, and asks every route it can ask safely --
GETs, then a decision, an undo and a job, all on the temporary copy. The
replies become `contract/snapshot.json` (the shapes) and
`contract/fixtures/*.json` (one real reply per request, paths rewritten to
/fixture, for the Swift tests to decode). The temporary directory is
removed afterwards; nothing under the source tree's data/ is read or written.

WHAT IT DOES NOT ASK: /api/music and /api/peek (osascript into the owner's
Music.app, up to 180 s), the POSTs that touch a device or the network
(sync, export, match, verify, am_index, recover), and tag or cover writes.
They are listed in the snapshot under `not_recorded`, with the reason, so
the gap is written down rather than invisible.

--url compares a running server's GET replies with the record. The live
library is bigger than the fixture, so the test is conformance, not
equality: every field the server sends must be in the record with a type
the record allows, and every field it leaves out must be optional there.
"""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT = os.path.join(ROOT, 'contract')
SNAPSHOT = os.path.join(CONTRACT, 'snapshot.json')
FIXTURES = os.path.join(CONTRACT, 'fixtures')
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'fixtures'))

PLACEHOLDER = '/fixture'

# Objects whose KEYS are data (a playlist name, a track key), not field
# names. Recorded as a map of one value shape, or every new playlist would
# be "a field added". Paths use [] for array items and {} for map values.
MAPS = {
    'GET /api/tracks': ['order'],
    'GET /api/plan': ['sizes', 'members'],
    'GET /api/history': ['runs[].device.before.playlists', 'runs[].device.after.playlists',
                         'runs[].changed.counts_changed'],
}

# Types the fixture cannot show, declared. A field the fixture only ever
# sends as null, or an array it only ever sends empty, says nothing about
# what it holds the day it holds something; a Codable model needs to know.
# Each hint names the source line that decides it. A hint whose path no
# longer exists fails --check, so this list cannot outlive the fields.
def _obj(**fields):
    """A hinted object shape, for a field the fixture run only sees as null
    or empty: each keyword is a field name and its type names."""
    return {'type': ['object'],
            'fields': {k: {'type': sorted(v.split('|'))} for k, v in fields.items()}}


HINTS = {
    # curate.health: strftime('%H:%M') when the iPod was ejected / Music.app
    # stopped answering; config.load's SystemExit text when device.json is bad.
    # `job` is curate.job_summary: null unless a job runs, which the fixture
    # run's one job (it errors at once) never overlaps
    'GET /api/health': {'ejected_at': 'string', 'wedged_at': 'string', 'config': 'string',
                        'job': _obj(id='string', name='string', state='string',
                                    seconds='int', done='int', total='int')},
    # curate.Handler /api/looking: sorted(LOOKING), the keys being looked up
    'GET /api/looking': {'keys[]': 'string'},
    # curate.Job.step_line: only a sync prints @@ lines, and a sync is not
    # recorded (it writes a device)
    # and `say` is the run's last sentence (curate.Job.step_line's `@@ say`),
    # which only a sync prints: "the iPod is as it was" after a restore
    'GET /api/job': {'steps[]': _obj(id='string', state='string', error='null|string'),
                     'say': 'string'},
    # curate.row_play: 'file' or 'preview'; the fixture's drive and library
    # rows have neither a playable file in the state nor a preview
    'GET /api/local': {'tracks[].play': 'string'},
    # curate.am_row_answers: the Apple Music cloud status, when Music.app
    # gave one; the fixture's library rows carry none
    'GET /api/library': {'tracks[].play': 'string', 'tracks[].am_status': 'string'},
}

# The enumerations a client switches on. Where the code holds the list it is
# imported; the rest are read off the code by hand, with the line, and every
# value a run observes must be in its list or --check fails.
DECLARED_ENUMS = {
    'health.ipod': (['absent', 'ejected', 'ready', 'waking'], 'curate.health'),
    'health.music': (['closed', 'ok', 'wedged'], 'curate.health'),
    'job.state': (['done', 'error', 'gone', 'running'], 'curate.Job, Handler /api/job'),
    'track.play_from': (['ipod', 't7', None], 'curate.tracks_payload'),
    'event.type': (['data', 'job', 'reload', 'hello'], 'curate.push callers; hello is the SSE greeting with the server boot'),
    'track.state': (['offline', 'ready', 'unowned'], 'curate.row_state'),
    'track.play': (['file', 'preview', None], 'curate.row_play'),
    'decision.verb': (['buy', 'remove', 'sync'], 'curate.decision_of'),
    'health.headline.level': (['fault', 'missed', 'ok', 'warn'], 'curate.headline'),
    'job.step.state': (['doing', 'done', 'error', 'todo', 'waiting'],
                       'curate.Job.step_line, Job.end_steps'),
}

NOT_RECORDED = {
    'GET /api/music': 'osascript into Music.app (the owner\'s), up to 180 s',
    'GET /api/peek': 'osascript into Music.app (the owner\'s), up to 180 s',
    'POST /api/action sync': 'writes a device and ejects it',
    'POST /api/action export|match|verify|am_index': 'Music.app or the network',
    'POST /api/action am_plays': "Apple Music's library file in the owner's home",
    'POST /api/action lookup': 'the iTunes Search API',
    'POST /api/action source': 'a real folder is walked into the index as a job; '
                               'the refusal is recorded (source-refused)',
    'POST /api/recover': 'copies a file off a device',
    'POST /api/tags': 'writes an audio file',
    'POST /api/art': 'writes the cover cache from uploaded bytes',
    'POST /api/discard': 'not yet: needs a pending plan to discard',
    'POST /api/track': 'not yet: a second spelling of GET /api/track',
}


# ----------------------------------------------------------------- shapes

def _scalar(v):
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'bool'
    if isinstance(v, int):
        return 'int'
    if isinstance(v, float):
        return 'float'
    if isinstance(v, str):
        return 'string'
    if isinstance(v, list):
        return 'array'
    return 'object'


def shape_of(v, path='', maps=()):
    t = _scalar(v)
    s = {'type': [t]}
    if t == 'array':
        items = None
        for x in v:
            items = merge(items, shape_of(x, path + '[]', maps))
        s['items'] = items
    elif t == 'object':
        if path.lstrip('.') in maps:
            vals = None
            for x in v.values():
                vals = merge(vals, shape_of(x, path + '{}', maps))
            s['type'] = ['map']
            s['values'] = vals
        else:
            s['fields'] = {k: shape_of(x, (path + '.' + k) if path else k, maps)
                           for k, x in v.items()}
    return s


def merge(a, b):
    """The shape that admits both: union of types, fields optional when one
    side lacks them, int widened to float when both appear."""
    if a is None:
        return b
    if b is None:
        return a
    types = sorted(set(a['type']) | set(b['type']))
    if 'int' in types and 'float' in types:
        types.remove('int')
    out = {'type': types}
    if 'items' in a or 'items' in b:
        out['items'] = merge(a.get('items'), b.get('items'))
    if 'values' in a or 'values' in b:
        out['values'] = merge(a.get('values'), b.get('values'))
    if 'fields' in a or 'fields' in b:
        fa, fb = a.get('fields'), b.get('fields')
        if fa is None or fb is None:
            # one side was null or another type: the fields stand as they are
            out['fields'] = dict(fa or fb)
        else:
            f = {}
            for k in sorted(set(fa) | set(fb)):
                m = merge(fa.get(k), fb.get(k))
                if k not in fa or k not in fb or fa[k].get('optional') or fb[k].get('optional'):
                    m = dict(m, optional=True)
                f[k] = m
            out['fields'] = f
    for k in ('optional', 'hinted'):
        if a.get(k) or b.get(k):
            out[k] = True
    return out


def _at(shape, path):
    """The sub-shape at a path like `tracks[].ground` or `members{}[].key`."""
    cur = shape
    for tok in re.findall(r'[^.\[\]{}]+|\[\]|\{\}', path):
        if cur is None:
            return None
        if tok == '[]':
            cur = cur.get('items')
        elif tok == '{}':
            cur = cur.get('values')
        else:
            cur = (cur.get('fields') or {}).get(tok)
    return cur


def _set_at(shape, path, hint):
    toks = re.findall(r'[^.\[\]{}]+|\[\]|\{\}', path)
    parent = _at(shape, ''.join(('.' + t if t not in ('[]', '{}') else t) for t in toks[:-1]).lstrip('.'))
    last = toks[-1]
    if parent is None:
        return False
    if isinstance(hint, dict):
        # a whole shape (an object the run never saw filled)
        if last == '[]':
            parent['items'] = merge(parent.get('items'), dict(hint, hinted=True))
            return True
        f = (parent.get('fields') or {}).get(last)
        if f is None:
            return False
        f.update(merge(f, dict(hint, hinted=True)))
        return True
    if last == '[]':
        if parent.get('items') is None:
            parent['items'] = {'type': [hint], 'hinted': True}
        elif hint not in parent['items']['type']:
            parent['items'] = merge(parent['items'], {'type': [hint], 'hinted': True})
        return True
    f = (parent.get('fields') or {}).get(last)
    if f is None:
        return False
    if hint not in f['type'] and not (hint == 'int' and 'float' in f['type']):
        f.update(merge(f, {'type': [hint], 'hinted': True}))
    return True


def apply_hints(routes):
    stale = []
    for route, hints in HINTS.items():
        r = routes.get(route)
        for path, t in hints.items():
            if not r or not _set_at(r['shape'], path, t):
                stale.append('%s %s' % (route, path))
    return stale


def gaps(shape, path=''):
    """Fields with no type a decoder can use: only ever null, or an array
    only ever empty. Each is a hole in the fixture, or a missing hint."""
    out = []
    if shape is None:
        return [path or '.']
    if shape['type'] == ['null']:
        out.append(path)
    if 'array' in shape['type'] and shape.get('items') is None:
        out.append(path + '[]')
    if shape.get('items'):
        out += gaps(shape['items'], path + '[]')
    if shape.get('values'):
        out += gaps(shape['values'], path + '{}')
    for k, f in (shape.get('fields') or {}).items():
        out += gaps(f, (path + '.' + k) if path else k)
    return out


def diff(a, b, path=''):
    """Human lines for every difference between two shapes."""
    out = []
    if a is None or b is None:
        if a is not b:
            out.append('%s: %s -> %s' % (path or '.', 'absent' if a is None else a['type'],
                                         'absent' if b is None else b['type']))
        return out
    if a['type'] != b['type']:
        out.append('%s: type %s -> %s' % (path or '.', a['type'], b['type']))
    if bool(a.get('optional')) != bool(b.get('optional')):
        out.append('%s: %s -> %s' % (path or '.', 'optional' if a.get('optional') else 'required',
                                     'optional' if b.get('optional') else 'required'))
    if 'items' in a or 'items' in b:
        out += diff(a.get('items'), b.get('items'), path + '[]')
    if 'values' in a or 'values' in b:
        out += diff(a.get('values'), b.get('values'), path + '{}')
    fa, fb = a.get('fields') or {}, b.get('fields') or {}
    for k in sorted(set(fa) | set(fb)):
        p = (path + '.' + k) if path else k
        if k not in fa:
            out.append('%s: added (%s)' % (p, '|'.join(fb[k]['type'])))
        elif k not in fb:
            out.append('%s: removed' % p)
        else:
            out += diff(fa[k], fb[k], p)
    return out


def conforms(rec, live, path=''):
    """Lines where a live shape steps outside the recorded one."""
    if rec is None:
        return ['%s: not in the record' % (path or '.')]
    if live is None:
        return []
    out = []
    allowed = set(rec['type'])
    if 'float' in allowed:
        allowed.add('int')
    if 'map' in allowed:
        allowed.add('object')
    bad = set(live['type']) - allowed
    if bad:
        out.append('%s: sends %s, the record allows %s' % (path or '.', sorted(bad), rec['type']))
    if live.get('items') is not None:
        if rec.get('items') is None:
            out.append('%s[]: items the record never saw' % path)
        else:
            out += conforms(rec['items'], live['items'], path + '[]')
    fl = live.get('fields')
    if fl is None:
        if live.get('values') is not None:
            out += conforms(rec.get('values'), live['values'], path + '{}')
        return out
    if 'map' in rec['type']:                 # the live side did not know it was a map
        for v in fl.values():
            out += conforms(rec.get('values'), v, path + '{}')
        return out
    fr = rec.get('fields') or {}
    for k, v in fl.items():
        p = (path + '.' + k) if path else k
        out += conforms(fr[k], v, p) if k in fr else ['%s: sent, not in the record' % p]
    for k, v in fr.items():
        if k not in fl and not v.get('optional'):
            out.append('%s: required in the record, not sent' % ((path + '.' + k) if path else k))
    return out


# ------------------------------------------------------------------ server

def _free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _req(base, method, path, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method,
                               headers={'Content-Type': 'application/json'} if data else {})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.headers.get('Content-Type', ''), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get('Content-Type', ''), e.read()


class Events(threading.Thread):
    """Reads /api/events until the server goes away."""

    def __init__(self, base):
        super().__init__(daemon=True)
        self.base, self.events, self.retry, self.ready = base, [], None, threading.Event()

    def run(self):
        try:
            resp = urllib.request.urlopen(self.base + '/api/events', timeout=120)
            self.ready.set()
            for raw in resp:
                ln = raw.decode('utf-8', 'replace').rstrip('\n')
                if ln.startswith('retry:'):
                    self.retry = int(ln.split(':', 1)[1])
                elif ln.startswith('data: '):
                    self.events.append(json.loads(ln[6:]))
        except Exception:
            self.ready.set()


def _scrub(text, roots):
    """Machine paths out of a reply: the fixture directory becomes /fixture,
    the source tree /code (a job's traceback names it), the home ~."""
    swaps = {r: PLACEHOLDER for r in roots}
    swaps[ROOT] = '/code'
    swaps[os.path.realpath(ROOT)] = '/code'
    swaps[os.path.expanduser('~')] = '~'
    for r in sorted(swaps, key=len, reverse=True):
        text = text.replace(r, swaps[r])
        text = text.replace(urllib.parse.quote(r), urllib.parse.quote(swaps[r]))
    return text


def record():
    """Build the fixtures, run the server on them, return (snapshot, replies)."""
    import build as FX
    tmp = tempfile.mkdtemp(prefix='saltpod-contract-')
    proc = None
    try:
        m = FX.build(os.path.join(tmp, 'f'))
        dev = json.load(open(os.path.join(m['home'], 'data', 'device.json')))
        # THE ONE THING THAT MUST NOT HAPPEN is a fixture run reading or
        # writing the owner's iPod, so the run refuses before the server starts.
        if dev.get('mount') != m['mount'] or dev['mount'].startswith('/Volumes'):
            raise SystemExit('fixture device.json does not name the fake mount: %r' % dev.get('mount'))
        port = _free_port()
        base = 'http://127.0.0.1:%d' % port
        env = dict(os.environ, SALTPOD_HOME=m['home'])
        proc = subprocess.Popen(
            [sys.executable, '-c', 'import sys; sys.path.insert(0, "src"); '
             'from saltpod.curate import main; main(["--no-open", "--port", "%d"])' % port],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(200):
            try:
                _req(base, 'GET', '/api/undo', timeout=2)
                break
            except Exception:
                if proc.poll() is not None:
                    raise SystemExit('the fixture server did not start: %s'
                                     % proc.stderr.read().decode()[-800:])
                time.sleep(0.1)
        ev = Events(base)
        ev.start()
        ev.ready.wait(10)

        q = urllib.parse.quote
        # the fixture's longest collection, for the reorder and rename asks
        co = json.load(open(os.path.join(m['home'], 'data', 'state.json')))['collection_order']
        col = sorted(co, key=lambda c: (-len(co[c]), c))[0]
        plan = [
            ('GET /api/tracks', '', 'GET', '/api/tracks', None),
            ('GET /api/playlists', '', 'GET', '/api/playlists', None),
            ('GET /api/device', '', 'GET', '/api/device', None),
            ('GET /api/local', 'folders', 'GET', '/api/local', None),
            ('GET /api/local', 'folder', 'GET', '/api/local?folder=' + q(m['folder']), None),
            ('GET /api/local', 'all', 'GET', '/api/local?folder=__all__', None),
            ('GET /api/library', '', 'GET', '/api/library', None),
            ('GET /api/discogs', '', 'GET', '/api/discogs', None),
            ('GET /api/health', '', 'GET', '/api/health', None),
            ('GET /api/plan', '', 'GET', '/api/plan', None),
            ('GET /api/track', 'key', 'GET', '/api/track?key=' + q(m['detail_key']), None),
            ('GET /api/track', 'path', 'GET', '/api/track?path=' + q(m['untagged_path']), None),
            ('GET /api/track', 'refused', 'GET', '/api/track?key=' + q('no-such|track'), None),
            ('GET /api/undo', 'empty', 'GET', '/api/undo', None),
            ('GET /api/looking', '', 'GET', '/api/looking', None),
            ('GET /api/decision', 'selection', 'GET', '/api/decision?key=%s&key=%s'
             % (q(m['detail_key']), q(m['decide_key'])), None),
            ('GET /api/decision', 'refused', 'GET', '/api/decision', None),
            ('POST /api/decision', 'selection', 'POST', '/api/decision',
             {'keys': [m['detail_key'], m['decide_key']]}),
            ('GET /api/job', 'gone', 'GET', '/api/job?id=no-such-job', None),
            ('BIN /api/art', 'key', 'GET', '/api/art?key=' + q(m['detail_key']), None),
            ('BIN /api/art', 'playlist', 'GET', '/api/art?playlist=2026-january', None),
            ('BIN /api/audio', 'key', 'GET', '/api/audio?key=' + q(m['detail_key']), None),
            # the iPod unplugged: the same three routes, from the fixture's backup
            ('UNPLUG', '', '', '', None),
            ('GET /api/health', 'unplugged', 'GET', '/api/health', None),
            ('GET /api/device', 'unplugged', 'GET', '/api/device', None),
            ('GET /api/plan', 'unplugged', 'GET', '/api/plan', None),
            ('POST /api/action', 'device-backup', 'POST', '/api/action', {'action': 'device'}),
            ('PLUG', '', '', '', None),
            ('POST /api/action', 'device', 'POST', '/api/action', {'action': 'device'}),
            ('POST /api/action', 'source-refused', 'POST', '/api/action',
             {'action': 'source', 'folder': '/no/such/folder'}),
            ('POST /api/decide', 'tier', 'POST', '/api/decide',
             {'keys': [m['decide_key']], 'tier': 'sync'}),
            ('GET /api/undo', 'after-decide', 'GET', '/api/undo', None),
            ('POST /api/undo', 'undo', 'POST', '/api/undo', {}),
            ('GET /api/undo', 'after-undo', 'GET', '/api/undo', None),
            ('POST /api/decide', 'reorder', 'POST', '/api/decide',
             {'reorder': {'collection': col, 'keys': list(reversed(co[col]))}}),
            ('POST /api/decide', 'rename', 'POST', '/api/decide',
             {'rename_collection': col, 'to': col + ' renamed'}),
            ('POST /api/decide', 'refused', 'POST', '/api/decide',
             {'rename_collection': 'no such collection', 'to': 'x'}),
            ('POST /api/action', 'index', 'POST', '/api/action', {'action': 'index'}),
        ]
        replies = []
        roots = {tmp, os.path.realpath(tmp)}
        for route, variant, method, path, body in plan:
            if route in ('UNPLUG', 'PLUG'):
                a, b = m['mount'], m['mount'] + '.unplugged'
                os.rename(*((a, b) if route == 'UNPLUG' else (b, a)))
                continue
            status, ctype, raw = _req(base, method, path, body)
            rec = {'route': route, 'variant': variant, 'status': status,
                   'content_type': ctype.split(';')[0]}
            if not route.startswith('BIN '):
                rec['body'] = json.loads(_scrub(raw.decode('utf-8'), roots))
            replies.append(rec)
            if route == 'POST /api/action' and rec['body'].get('job'):
                job = rec['body'].get('job')
                done = None
                for _ in range(600):
                    s, c, r = _req(base, 'GET', '/api/job?id=' + q(job))
                    done = json.loads(_scrub(r.decode('utf-8'), roots))
                    if done.get('state') != 'running':
                        break
                    time.sleep(0.1)
                replies.append({'route': 'GET /api/job', 'variant': 'finished', 'status': s,
                                'content_type': c.split(';')[0], 'body': done})
                s, c, r = _req(base, 'GET', '/api/history')
                replies.append({'route': 'GET /api/history', 'variant': '', 'status': s,
                                'content_type': c.split(';')[0],
                                'body': json.loads(_scrub(r.decode('utf-8'), roots))})
        deadline = time.time() + 5
        while time.time() < deadline and not any(e.get('type') == 'job' for e in ev.events):
            time.sleep(0.1)
        events = [json.loads(_scrub(json.dumps(e), roots)) for e in ev.events]
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(10)
            except Exception:
                proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    return _snapshot(replies, events, ev.retry), replies, events


def _snapshot(replies, events, retry):
    from saltpod import state as S, curate as C
    routes = {}
    for r in replies:
        e = routes.setdefault(r['route'], {'status': [], 'content_type': [], 'variants': []})
        if r['status'] not in e['status']:
            e['status'].append(r['status'])
        if r['content_type'] not in e['content_type']:
            e['content_type'].append(r['content_type'])
        e['variants'].append(r['variant'])
        if 'body' in r:
            e['shape'] = merge(e.get('shape'), shape_of(r['body'], '', MAPS.get(r['route'], ())))
    stale = apply_hints(routes)
    ev_shapes = {}
    for e in events:
        ev_shapes[e.get('type')] = merge(ev_shapes.get(e.get('type')), shape_of(e))
    enums = {'tier': list(S.TIERS), 'lists': list(C.LISTS)}
    for name, (vals, src) in DECLARED_ENUMS.items():
        enums[name] = vals
    observed = _observed_enums(replies, events)
    return {
        '_about': 'written by bin/contract.py --write from fixtures/seed.json; shapes, never values',
        'routes': routes,
        'events': {'retry_ms': retry, 'shapes': ev_shapes},
        'enums': enums,
        'enum_sources': {k: v[1] for k, v in DECLARED_ENUMS.items()},
        'not_recorded': NOT_RECORDED,
        'fixtures': {_fixture_name(r): r['route'] for r in replies if 'body' in r},
        '_check': {'stale_hints': stale, 'observed_enums': observed},
    }


def _observed_enums(replies, events):
    seen = {}

    def add(k, v):
        if v not in seen.setdefault(k, []):
            seen[k].append(v)
    for r in replies:
        b = r.get('body')
        if not isinstance(b, dict):
            continue
        if r['route'] == 'GET /api/tracks':
            for t in b['tracks']:
                add('tier', t['tier'])
                add('track.play_from', t['play_from'])
                add('track.state', t['state'])
                add('track.play', t['play'])
                add('decision.verb', t['decision']['verb'])
                for x in t['lists']:
                    add('lists', x)
        if r['route'] == 'GET /api/health':
            add('health.ipod', b['ipod'])
            add('health.music', b['music'])
            add('health.headline.level', b['headline']['level'])
        if r['route'] == 'GET /api/job':
            add('job.state', b['state'])
            for st in b.get('steps') or []:
                add('job.step.state', st['state'])
    for e in events:
        add('event.type', e.get('type'))
    return {k: sorted(v, key=lambda x: (x is None, str(x))) for k, v in seen.items()}


# ------------------------------------------------------------------- files

def _fixture_name(r):
    base = r['route'].replace(' /api/', '_').replace('/', '_').lower()
    return base + ('--' + r['variant'] if r['variant'] else '') + '.json'


def _dump(path, obj):
    with open(path, 'w') as f:
        json.dump(obj, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write('\n')


def write(snap, replies, events):
    os.makedirs(FIXTURES, exist_ok=True)
    for f in os.listdir(FIXTURES):
        if f.endswith('.json'):
            os.remove(os.path.join(FIXTURES, f))
    for r in replies:
        if 'body' in r:
            _dump(os.path.join(FIXTURES, _fixture_name(r)), r['body'])
    _dump(os.path.join(FIXTURES, 'events.json'), events)
    _dump(SNAPSHOT, snap)


LEAK_EXEMPT = {r'"tracks": \{'}   # a state file's shape; the fixture state is invented


def leaks():
    """The publish gate's patterns, over everything this writes."""
    pats = [r'/Users/', r'/private/var/', r'/var/folders/']
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    try:
        # The lab's publish gate names what must never ship. The public repo
        # does not carry that list (it names the owner), so there the check
        # is the machine paths alone.
        import publish_public as P
        pats += [p for p in P.LEAKS if p not in LEAK_EXEMPT]
    except ImportError:
        pass
    hits = []
    for top in (CONTRACT, os.path.join(ROOT, 'fixtures')):
        for d, _dirs, files in os.walk(top):
            for f in files:
                p = os.path.join(d, f)
                if '__pycache__' in p:
                    continue
                try:
                    text = open(p).read()
                except UnicodeDecodeError:
                    continue
                for pat in pats:
                    if re.search(pat, text, re.I):
                        hits.append('%s: %s' % (os.path.relpath(p, ROOT), pat))
    return hits


def problems(snap):
    """What makes a fresh snapshot unacceptable whatever the committed one says."""
    out = ['stale hint: %s' % s for s in snap['_check']['stale_hints']]
    for k, vals in snap['_check']['observed_enums'].items():
        allowed = snap['enums'].get(k)
        for v in vals:
            if allowed is not None and v not in allowed:
                out.append('enum %s: %r observed, not declared' % (k, v))
    for route, e in snap['routes'].items():
        if 'shape' in e:
            for g in gaps(e['shape']):
                out.append('%s: %s has no usable type (fixture hole or missing hint)' % (route, g))
    return out


def check():
    if not os.path.exists(SNAPSHOT):
        print('no contract/snapshot.json -- run --write first')
        return 1
    old = json.load(open(SNAPSHOT))
    snap, replies, events = record()
    bad = problems(snap)
    for route in sorted(set(old['routes']) | set(snap['routes'])):
        a, b = old['routes'].get(route), snap['routes'].get(route)
        if a is None or b is None:
            bad.append('%s: %s' % (route, 'new route' if a is None else 'route gone'))
            continue
        for k in ('status', 'content_type'):
            if sorted(a[k]) != sorted(b[k]):
                bad.append('%s: %s %s -> %s' % (route, k, a[k], b[k]))
        bad += ['%s %s' % (route, x) for x in diff(a.get('shape'), b.get('shape'))]
    for t in sorted(set(old['events']['shapes']) | set(snap['events']['shapes'])):
        bad += ['event %s %s' % (t, x) for x in diff(old['events']['shapes'].get(t),
                                                      snap['events']['shapes'].get(t))]
    if old['enums'] != snap['enums']:
        bad.append('enums changed: %s -> %s' % (old['enums'], snap['enums']))
    # the committed replies the Swift tests decode must still fit the record
    for f, route in sorted(old.get('fixtures', {}).items()):
        p = os.path.join(FIXTURES, f)
        if not os.path.exists(p):
            bad.append('contract/fixtures/%s: missing' % f)
            continue
        for x in conforms(old['routes'][route]['shape'],
                          shape_of(json.load(open(p)), '', MAPS.get(route, ()))):
            bad.append('contract/fixtures/%s: %s' % (f, x))
    if old.get('fixtures', {}) != snap['fixtures']:
        bad.append('the set of fixture replies changed: %s -> %s'
                   % (sorted(old.get('fixtures', {})), sorted(snap['fixtures'])))
    bad += ['leak: %s' % x for x in leaks()]
    n = sum(1 for e in snap['routes'].values() if 'shape' in e)
    if bad:
        print('contract DRIFT (%d):' % len(bad))
        for b in bad:
            print('  ' + b)
        print('\nif the change is meant: python3 bin/contract.py --write, and commit it with the route')
        return 1
    print('contract holds: %d routes, %d replies, %d event types, no leaks'
          % (n, len(replies), len(snap['events']['shapes'])))
    return 0


def against_url(url):
    old = json.load(open(SNAPSHOT))
    base = url.rstrip('/')
    asks = [('GET /api/tracks', '/api/tracks'), ('GET /api/playlists', '/api/playlists'),
            ('GET /api/device', '/api/device'), ('GET /api/local', '/api/local'),
            ('GET /api/library', '/api/library'), ('GET /api/discogs', '/api/discogs'),
            ('GET /api/health', '/api/health'), ('GET /api/plan', '/api/plan'),
            ('GET /api/undo', '/api/undo'), ('GET /api/looking', '/api/looking'),
            ('GET /api/history', '/api/history'), ('GET /api/job', '/api/job?id=no-such-job')]
    bad = []
    first_key = None
    for route, path in asks:
        s, c, raw = _req(base, 'GET', path, timeout=120)
        body = json.loads(raw)
        if route == 'GET /api/tracks' and body.get('tracks'):
            first_key = body['tracks'][0]['key']
        bad += ['%s %s' % (route, x) for x in
                conforms(old['routes'][route]['shape'], shape_of(body, '', MAPS.get(route, ())))]
    if first_key:
        s, c, raw = _req(base, 'GET', '/api/track?key=' + urllib.parse.quote(first_key))
        bad += ['GET /api/track %s' % x for x in
                conforms(old['routes']['GET /api/track']['shape'], shape_of(json.loads(raw)))]
    if bad:
        print('%s steps outside the contract (%d):' % (base, len(bad)))
        for b in bad:
            print('  ' + b)
        return 1
    print('%s conforms to the contract: %d routes' % (base, len(asks) + bool(first_key)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--write', action='store_true', help='record contract/ from a fixture server')
    g.add_argument('--check', action='store_true', help='record again and fail on any difference')
    g.add_argument('--url', help='compare a running server with the record')
    a = ap.parse_args(argv)
    if a.write:
        snap, replies, events = record()
        bad = problems(snap)
        write(snap, replies, events)
        lk = leaks()
        print('wrote contract/snapshot.json: %d routes, %d replies, %d event types'
              % (len(snap['routes']), len(replies), len(snap['events']['shapes'])))
        for b in bad + ['leak: %s' % x for x in lk]:
            print('  !! ' + b)
        return 1 if (bad or lk) else 0
    if a.check:
        return check()
    return against_url(a.url)


if __name__ == '__main__':
    sys.exit(main())
