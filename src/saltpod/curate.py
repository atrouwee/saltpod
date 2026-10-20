#!/usr/bin/env python3
"""The whole tool, as one local page.

    saltpod                          # or double-click saltpod.command

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
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

HERE = os.path.dirname(os.path.abspath(__file__))
from .paths import CODE_ROOT, DATA_ROOT  # noqa: E402  the two roots: see paths.py
ROOT = DATA_ROOT                 # data/, backups/, reports/ -- SALTPOD_HOME when set
from . import state as S  # noqa: E402
from . import observe as O  # noqa: E402
from . import platform as P  # noqa: E402
from . import ground as G  # noqa: E402
from . import mosaic as M  # noqa: E402

LOCK = threading.Lock()
JOBS = {}
JOBS_LOCK = threading.Lock()

# Two facts the page cannot see from the filesystem alone. A sync ends by
# ejecting the iPod, so its absence right afterwards is success, not a fault;
# and Music.app can accept a request and never answer it, which only a real
# read can discover. Both are remembered here and reported by /api/health.
EJECTED_AT = None
MUSIC_WEDGED_AT = None
_INDEX_CACHE = {}


def _mark_ejected(job=None):
    global EJECTED_AT
    EJECTED_AT = datetime.now().strftime('%H:%M')
    if job:
        job.line('--- ejected at %s' % EJECTED_AT)


def _osa(argv, timeout):
    """Run an AppleScript with a hard timeout, and remember if it hung."""
    global MUSIC_WEDGED_AT
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=CODE_ROOT)
    except subprocess.TimeoutExpired:
        MUSIC_WEDGED_AT = datetime.now().strftime('%H:%M')
        raise RuntimeError('Music.app accepted the request and did not answer within %ds' % timeout)
    MUSIC_WEDGED_AT = None
    return r


def volume_of(path):
    """The mount point a source sits on.

    A SOURCE IS NOT A DEVICE. Several sources can live on one drive --
    `/Volumes/X/Music` and `/Volumes/X/Podcasts` are two sources and one
    thing that gets unplugged -- so status belongs to the volume, and the
    volume is what has to be found first.

    `/Volumes/<name>` is checked before stat because it is the only form
    that survives the volume being ABSENT, which is exactly when the
    answer matters. Otherwise walk up while the device id holds; the point
    where it changes is the mount point.
    """
    p = os.path.abspath(os.path.expanduser(path))
    parts = p.split(os.sep)
    if len(parts) > 2 and parts[1] == 'Volumes':
        return os.sep.join(parts[:3])
    try:
        dev = os.stat(p).st_dev
        cur = p
        while cur != os.sep:
            par = os.path.dirname(cur)
            if os.stat(par).st_dev != dev:
                break
            cur = par
        else:
            return os.sep
        # macOS firmlinks the data volume over the system one; both are the
        # boot disk and neither can be unplugged.
        return os.sep if cur.startswith('/System/Volumes/Data') else cur
    except OSError:
        return os.sep


def volumes_for(roots):
    """One entry per VOLUME, with how many sources sit on it.

    `removable` is what earns a slot in the health strip: the boot volume
    cannot go away, so reporting it as online forever is reporting nothing.
    """
    vols = {}
    for root in roots:
        mp = volume_of(root)
        v = vols.get(mp)
        if v is None:
            v = vols[mp] = {'name': os.path.basename(mp) or 'this Mac',
                            'path': mp, 'online': os.path.isdir(mp),
                            'removable': mp != os.sep, 'sources': 0}
        v['sources'] += 1
    return list(vols.values())


def library_reach():
    """{'tracks', 'reachable'} -- how much of the library can be read now.

    NOT A HEALTH FIGURE. It sat in the strip for one commit, next to the
    iPod and Music.app, and that was the wrong neighbourhood: the strip is
    for things outside the application that can go away, and the library
    IS the application. It belongs with the library's own count, which is
    where /api/local serves it.

    Cached against the index's mtime, because this walks every entry.
    `resolve` is the same function every verb uses, so the number on
    screen is the number sync would get.
    """
    idx = os.path.join(ROOT, 'data', 'local', 'index.json')
    if not os.path.exists(idx):
        return None
    mt = os.path.getmtime(idx)
    if _INDEX_CACHE.get('reach_mtime') != mt:
        try:
            from . import local_index as LI
            rows = LI.load(resolved=False).get('tracks', [])
            n = sum(1 for e in rows if os.path.exists(LI.resolve(e)))
            _INDEX_CACHE.update(reach_mtime=mt, reach=n, reach_total=len(rows))
        except Exception:
            return None
    return {'tracks': _INDEX_CACHE.get('reach_total'),
            'reachable': _INDEX_CACHE.get('reach')}


def _source_row(root):
    """One library root as health reports it."""
    # Name it by the drive when it is on one -- the volume, not the folder.
    # That is the thing that gets unplugged, and the word you would use.
    parts = root.rstrip('/').split('/')
    name = parts[2] if len(parts) > 2 and parts[1] == 'Volumes' else (parts[-1] or root)
    return {'name': name, 'path': root, 'online': os.path.isdir(root),
            'volume': volume_of(root)}


def health():
    """What the tool can reach right now. Every check here is a filesystem
    stat or a pgrep -- never an Apple event, which is the one thing that can
    hang. The iPod's readiness is the database file, the same test plan uses,
    so the strip and the sync never disagree."""
    global EJECTED_AT
    out = {'ipod': 'absent', 'music': 'closed', 'sources': [], 'tools': {}, 'index': None,
           'ejected_at': None, 'wedged_at': MUSIC_WEDGED_AT, 'config': None}
    try:
        from . import config, apply as A
        cfg = config.load()
        mount = cfg.get('mount', '/Volumes/IPOD')
    except SystemExit as e:
        out['config'] = str(e)
        # the folders are named even before the iPod is: a fresh install
        # adds one from the Data sheet, and the sheet should say it took
        out['sources'] = [_source_row(r) for r in config.roots()]
        out['job'] = job_summary()
        out['headline'] = headline(out)
        return out
    vol = os.path.isdir(mount)
    db = os.path.exists(os.path.join(mount, A.DB_REL))
    if db:
        out['ipod'] = 'ready'
        EJECTED_AT = None
        # Free space is a statvfs -- cheap enough to poll, unlike plan(),
        # which reads the whole database. That is why the gauge can be
        # always-on while the "what a sync would add" figure cannot.
        try:
            sv = os.statvfs(mount)
            out['free'] = sv.f_bavail * sv.f_frsize
            out['size'] = sv.f_blocks * sv.f_frsize
        except Exception:
            pass
    elif vol:
        out['ipod'] = 'waking'
    elif EJECTED_AT:
        out['ipod'] = 'ejected'
        out['ejected_at'] = EJECTED_AT
    running = subprocess.run(['pgrep', '-x', 'Music'], capture_output=True).returncode == 0
    out['music'] = 'wedged' if (running and MUSIC_WEDGED_AT) else ('ok' if running else 'closed')
    for root in cfg.get('library_roots', []):
        out['sources'].append(_source_row(root))
    # STATUS BELONGS TO THE VOLUME, not the source. Two folders on one
    # drive are two sources and one thing that can be unplugged, and the
    # strip showed that drive twice. The sources list stays for settings,
    # where the folders themselves are the subject.
    out['volumes'] = volumes_for(cfg.get('library_roots', []))
    out['tools'] = {'ffmpeg': bool(shutil.which('ffmpeg')), 'ffprobe': bool(shutil.which('ffprobe'))}
    idx = os.path.join(ROOT, 'data', 'local', 'index.json')
    if os.path.exists(idx):
        mt = os.path.getmtime(idx)
        if _INDEX_CACHE.get('mtime') != mt:
            try:
                n = len(json.load(open(idx)).get('tracks', []))
            except Exception:
                n = None
            _INDEX_CACHE.update(mtime=mt, tracks=n)
        out['index'] = {'built': datetime.fromtimestamp(mt).strftime('%Y-%m-%d %H:%M'),
                        'tracks': _INDEX_CACHE.get('tracks')}
    out['job'] = job_summary()
    out['headline'] = headline(out)
    return out


SYNC_JOB = 'sync to the iPod'


def running_job(name=None):
    """The job still running, newest first; one named `name` if given."""
    with JOBS_LOCK:
        live = [j for j in JOBS.values() if j.state == 'running'
                and (name is None or j.name == name)]
    return max(live, key=lambda j: j.started) if live else None


def job_summary():
    """health.job (debt D12): the running job, a sync before anything else,
    with its step counts so "14 of 38" is a lookup; None when idle."""
    j = running_job(SYNC_JOB) or running_job()
    if not j:
        return None
    with JOBS_LOCK:
        steps = list(j.steps.values())
    return {'id': j.id, 'name': j.name, 'state': j.state,
            'seconds': round(time.time() - j.started),
            'done': sum(1 for x in steps if x['state'] in ('done', 'error')),
            'total': len(steps)}


def headline(h):
    """The idle headline (debt D12): one line about the link to the device,
    the most severe first -- no configuration, then the iPod's state, then
    ready with its free space. DESIGN-GLASS ("the shelf") wanted it on the
    server so the phone shelf, the iPad accessory and the Mac footer say one
    sentence. `level` is a status family name: ok, warn, missed, fault.
    Reach ("Can't reach the Mac") is the one fact only a client can know,
    so a client overlays it; it is not here."""
    if h.get('config'):
        return {'level': 'fault', 'text': 'No device configured'}
    pod = h.get('ipod')
    if pod == 'waking':
        return {'level': 'warn', 'text': 'iPod waking'}
    if pod == 'ejected':
        when = h.get('ejected_at')
        return {'level': 'ok', 'text': 'Ejected%s \u00b7 safe to unplug'
                % ((' ' + str(when)) if when else '')}
    if pod == 'ready':
        free = h.get('free')
        return {'level': 'ok', 'text': 'iPod ready' + (
            ' \u00b7 %d GB free' % round(free / 1e9) if free is not None else '')}
    return {'level': 'missed', 'text': 'iPod not connected'}


class Busy(Exception):
    """A second sync while one runs: answered 409 with the running job."""
    def __init__(self, job):
        super().__init__('a sync is already running')
        self.job = job


# ---------------------------------------------------------------- jobs

LOGS = os.path.join(ROOT, 'data/logs')

# ---------------------------------------------------------------- live updates
#
# One-way server -> browser over Server-Sent Events. Stdlib only: SSE is a plain
# text/event-stream response held open, which ThreadingHTTPServer already
# supports because every request gets its own thread.
#
# Two kinds of push, because they deserve different answers:
#
#   data   -- the underlying facts moved (a sync finished, the device was read).
#             The page re-fetches and redraws IN PLACE. Scroll position, the
#             open sheet and the selected collection all survive, which a
#             refresh would throw away mid-task.
#   reload -- curate.html itself changed on disk. Nothing short of a real reload
#             can pick up new markup or new script, so this one is the blunt
#             instrument, used only when the file's mtime actually moves.
#
CLIENTS = []
CLIENTS_LOCK = threading.Lock()


# THE CHANGE SIGNAL (debt D11). Every event and every JSON reply carries
# `rev`; it moves on each `data` or `job` event, so a client compares the
# rev of an event with the rev of the payload it holds and refetches only
# when they differ -- instead of refetching 1.5 MB on every event, its own
# included. It starts from the clock, so a restarted server never hands out
# a rev an old client has already seen.
REV = {'n': int(time.time() * 1000)}
REV_LOCK = threading.Lock()


def rev():
    return REV['n']


def push(event):
    """Fan out to every open page. A dead client is dropped, never raised."""
    with REV_LOCK:
        if event.get('type') in ('data', 'job'):
            REV['n'] += 1
        event = dict(event, rev=REV['n'])
    line = 'data: %s\n\n' % json.dumps(event, ensure_ascii=False)
    with CLIENTS_LOCK:
        for q in list(CLIENTS):
            try:
                q.put_nowait(line)
            except Exception:
                pass


def watch_page(path, interval=1.0):
    """Push `reload` when the page file is edited. This is the dev loop: save
    curate.html, and every open tab has the new page a second later."""
    def run():
        last = None
        while True:
            try:
                m = os.path.getmtime(path)
                if last is not None and m != last:
                    push({'type': 'reload', 'why': 'curate.html changed'})
                last = m
            except Exception:
                pass
            time.sleep(interval)
    threading.Thread(target=run, daemon=True).start()


# THE SERVER KEEPS UP WITH ITS OWN CODE. curate.html is read fresh on every
# request, so a server left running for days serves today's page from last
# week's Python -- and the page then asks for fields the server never sends
# (10-20 Oct 2026: every preview silent, Read Apple Music never landing,
# because the 4 Oct server predated `play`). So the server watches its own
# .py files and, once they have been quiet for a moment and no job is running,
# replaces itself in place (same pid, same port, same arguments). Pages hear a
# new `boot` in the hello on reconnect and reload.
BOOT = str(int(time.time() * 1000))


def _code_mtimes():
    out = {}
    for f in glob.glob(os.path.join(HERE, '*.py')):
        try:
            out[f] = os.path.getmtime(f)
        except OSError:
            pass
    return out


def restart_self():
    sys.stdout.flush(); sys.stderr.flush()
    spec = globals().get('__spec__')
    if __name__ == '__main__' and spec is not None and spec.name:
        cmd = [sys.executable, '-m', spec.name] + sys.argv[1:]
    else:
        cmd = [sys.executable] + sys.argv
    if '--no-open' not in cmd:
        cmd.append('--no-open')              # the tab is already open; never a second one
    os.execv(sys.executable, cmd)


def watch_code(interval=1.0, quiet=2.0):
    def run():
        seen = _code_mtimes()
        changed_at = None
        while True:
            time.sleep(interval)
            now = _code_mtimes()
            if now != seen:
                seen, changed_at = now, time.time()
                continue
            if changed_at is None or time.time() - changed_at < quiet:
                continue
            j = running_job()
            if j is not None:                # never under a sync, a read or an index
                continue
            try:
                O.event('info', 'restart', 'saltpod code changed; restarting in place')
            except Exception:
                pass
            print('saltpod code changed - restarting in place')
            restart_self()
    threading.Thread(target=run, daemon=True).start()



def device_fingerprint():
    """What the iPod holds right now, cheap enough to take twice per sync.

    This is the audit record. `backups/` proves what the database WAS; this
    says what a run changed, which is the question actually asked afterwards
    -- and answering it used to mean parsing a backup by hand.
    """
    try:
        # `A` is imported locally in health(), not at module level -- this
        # used A.DB_REL without importing it, so every fingerprint failed with
        # a NameError and the sync history recorded the error instead of the
        # diff. It failed silently because the fingerprint is deliberately
        # wrapped: a broken audit line must never break a write.
        from . import apply as A, config, itunesdb
        db = itunesdb.read(os.path.join(config.load()['mount'], A.DB_REL))
        return {'tracks': len(db['tracks']),
                'playlists': {p['name']: len(p['items']) for p in db['playlists']}}
    except Exception as e:
        return {'error': '%s: %s' % (type(e).__name__, e)}


class Job:
    say = None                          # `@@ say <sentence>`: the run's last word

    def __init__(self, name):
        self.id = '%s-%d' % (name, int(time.time() * 1000) % 10_000_000)
        self.name = name
        self.state = 'running'
        self.log = []
        self.steps = {}                 # id -> {id, state, error}, in run order
        self.say = None
        self.started = time.time()
        # A job log used to live only in this dict, capped at 400 lines, gone
        # the moment the server restarted -- for a tool whose whole job is
        # writing to hardware. Now every line also lands on disk as it streams.
        self.slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
        self.path = os.path.join(LOGS, '%s-%s.log' % (
            time.strftime('%Y-%m-%d-%H%M%S'), self.slug))
        self.fp = None
        try:
            os.makedirs(LOGS, exist_ok=True)
            self.fp = open(self.path, 'a', buffering=1)     # line-buffered
            self.fp.write('# %s -- started %s\n' % (name, time.strftime('%Y-%m-%d %H:%M:%S')))
        except Exception:
            self.fp = None                                  # never fail a sync over a log

    # `@@ <id> <state>[ <error>]`. A playlist id (`p:`) may hold spaces and
    # never carries an error, so it is matched greedily up to its state.
    # A smart list's id (`s:`) may hold spaces the same way.
    STEP = re.compile(r'^@@ ([ps]:.+|\S+) (doing|done|error)(?: (.*))?$')

    def step_line(self, s):
        """Fold one `@@` line into `steps` (debt D10). The page used to read
        these out of the last 60 log lines and assume the ones it missed;
        the job sees every line, so its list is complete."""
        if s.startswith('@@ say '):
            # THE ONE SENTENCE A CLIENT SHOWS WHEN THE RUN ENDS, in the
            # server's words -- "the iPod is as it was" after a sync put its
            # backup back. A client toasts it; it never composes its own.
            self.say = s[len('@@ say '):].strip()
            return
        if s.startswith('@@ steps '):
            try:
                ids = json.loads(s[len('@@ steps '):])
            except ValueError:
                return
            for i in ids:
                self.steps.setdefault(i, {'id': i, 'state': 'waiting', 'error': None})
            return
        m = self.STEP.match(s)
        if m:
            st = self.steps.setdefault(m.group(1), {'id': m.group(1), 'state': 'waiting',
                                                    'error': None})
            st['state'] = m.group(2)
            if m.group(3):
                st['error'] = m.group(3)

    def end_steps(self):
        """When the run ends, a step still waiting is settled: it ran
        unreported if the job finished, and never ran if it stopped."""
        with JOBS_LOCK:
            for st in self.steps.values():
                if st['state'] in ('waiting', 'doing'):
                    st['state'] = 'done' if self.state == 'done' else (
                        'error' if st['state'] == 'doing' else 'todo')

    def line(self, s):
        with JOBS_LOCK:
            self.log.append(s.rstrip())
            del self.log[:-400]          # a long match run must not eat memory
            if s.startswith('@@ '):
                self.step_line(s.rstrip())
        if self.fp:
            try:
                self.fp.write(s.rstrip() + '\n')
            except Exception:
                pass

    def close(self, before=None, after=None):
        """Seal the log and append one line to the history."""
        rec = {'id': self.id, 'name': self.name, 'state': self.state,
               'started': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(self.started)),
               'seconds': round(time.time() - self.started),
               'log': os.path.relpath(self.path, ROOT)}
        if before is not None or after is not None:
            rec['device'] = {'before': before, 'after': after}
            if isinstance(before, dict) and isinstance(after, dict) \
                    and 'tracks' in before and 'tracks' in after:
                pb, pa = before.get('playlists', {}), after.get('playlists', {})
                rec['changed'] = {
                    'tracks': [before['tracks'], after['tracks']],
                    'playlists_removed': sorted(set(pb) - set(pa)),
                    'playlists_added': sorted(set(pa) - set(pb)),
                    'counts_changed': {k: [pb[k], pa[k]] for k in set(pb) & set(pa)
                                       if pb[k] != pa[k]}}
        if self.fp:
            try:
                self.fp.write('# %s after %ds\n' % (self.state, rec['seconds']))
                if 'changed' in rec:
                    self.fp.write('# changed: %s\n' % json.dumps(rec['changed'], ensure_ascii=False))
                self.fp.close()
            except Exception:
                pass
            self.fp = None
        try:
            os.makedirs(LOGS, exist_ok=True)
            with open(os.path.join(LOGS, 'history.jsonl'), 'a') as h:
                h.write(json.dumps(rec, ensure_ascii=False) + '\n')
        except Exception:
            pass

    def as_dict(self):
        return {'id': self.id, 'name': self.name, 'state': self.state,
                'log': self.log[-60:], 'seconds': round(time.time() - self.started),
                'steps': [dict(x) for x in self.steps.values()],
                'say': self.say}


def run_job(name, steps, fingerprint=False):
    """steps: list of (label, argv) or (label, callable).

    `fingerprint` reads the device before and after, so the history line says
    what the run actually changed rather than only that it ran.
    """
    job = Job(name)
    with JOBS_LOCK:
        JOBS[job.id] = job

    def work():
        before = device_fingerprint() if fingerprint else None
        after = None
        try:
            for label, step in steps:
                job.line('--- %s' % label)
                if callable(step):
                    step(job)
                    continue
                p = subprocess.Popen(step, cwd=CODE_ROOT, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, bufsize=1,
                                     env={**os.environ,
                                          'DEVELOPER_DIR': DEV_DIR})
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
        finally:
            # The fingerprint is taken BEFORE the eject step in a sync job would
            # make it unreadable; on the error path it is the more useful of the
            # two, because it says how far the write got.
            if fingerprint:
                after = device_fingerprint()
            job.end_steps()
            job.close(before, after)
            push({'type': 'job', 'id': job.id, 'state': job.state, 'name': job.name})
            push({'type': 'data', 'why': job.name})

    threading.Thread(target=work, daemon=True).start()
    return job


def playlist_slugs():
    return sorted(os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(ROOT, 'data/exports/*.json'))
                  if not os.path.basename(p).startswith('_'))


# Not under data/exports: rebuild() reads every file there as a playlist
# export, and this one is not. It sat there for an evening and made every job
# report "failed" after doing its work correctly.
AM_INDEX = os.path.join(ROOT, 'data/local/apple_music.json')


def am_index():
    """The cached read of Apple Music: its playlists, and every track in it.

    Music.app has no creation date for a playlist -- its whole property list is
    id, index, name, persistentID, duration, size, time, visible, specialKind,
    loved, hated, smart, shared, genius -- so `created` is the earliest a track
    in it was added, which for a monthly is the month it was made.

    Cached because it reads the entire library; refresh it from the gear.
    """
    if not os.path.exists(AM_INDEX):
        return {'playlists': [], 'keys': [], 'read_at': None}
    try:
        return json.load(open(AM_INDEX))
    except Exception:
        return {'playlists': [], 'keys': [], 'read_at': None}


# Which Apple Music cloud statuses mean you own the file (debt D5). It lived
# in the page as AM_OWNED, so the same sentence was in JavaScript twice --
# export_playlists.js decides `owned` for a playlist export, the page decided
# it again for a library row -- and Swift would have made three.
AM_OWNED = ('purchased', 'matched', 'uploaded')


def am_row_answers(cloud):
    """The answers a row seen only in Apple Music carries, so a client can
    render it like any other row without deciding anything: whether the
    cloud status means owned, the status worth showing (None for owned and
    for an ordinary subscription track), and law 3's state -- no file on any
    drive of yours, so `unowned`, with nothing to play until it is adopted."""
    owned = cloud in AM_OWNED
    return {'am_owned': owned,
            'am_status': None if (owned or cloud == 'subscription' or not cloud) else cloud,
            'state': 'unowned', 'play': None,
            'decision': decision_of([{'held': False, 'tier': '', 'collections': []}])}


def library_payload():
    """/api/library: every Apple Music library row, with its answers."""
    rows = []
    for r in am_index().get('library') or []:
        rows.append(dict(r, **am_row_answers(r.get('cloud'))))
    return {'tracks': rows}


def refresh_am_index():
    out = _osa(['osascript', '-l', 'JavaScript',
                os.path.join(CODE_ROOT, 'bin/export_playlists.js'), '--index'], 600)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or 'osascript failed').strip()[:400])
    d = json.loads(out.stdout)
    lib = []
    for row in d.get('library', []):
        if not (row.get('artist') or row.get('title')):
            continue
        row['key'] = S.key_for(row.get('artist'), row.get('title'))
        lib.append(row)
    keys = sorted({r['key'] for r in lib})
    doc = {'playlists': d.get('playlists', []), 'keys': keys, 'library': lib,
           'read_at': datetime.now().strftime('%Y-%m-%d %H:%M')}
    os.makedirs(os.path.dirname(AM_INDEX), exist_ok=True)
    tmp = AM_INDEX + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(doc, f)
    os.replace(tmp, AM_INDEX)
    print('%d playlists, %d tracks in the Apple Music library'
          % (len(doc['playlists']), len(lib)))
    return doc


def music_playlists():
    """Names and track counts straight out of Music.app."""
    try:
        out = subprocess.run(['osascript', '-l', 'JavaScript',
                              os.path.join(CODE_ROOT, 'bin/export_playlists.js'), '--list'],
                             capture_output=True, text=True, timeout=180, cwd=CODE_ROOT).stdout
        return json.loads(out)
    except Exception:
        return []


# ---------------------------------------------------------------- data

def device_playlists():
    """Every playlist the iPod carries, ours or not.

    The pane used to list only the collections this tool made, and the owner
    noticed the rest were missing -- the iPod has fourteen it never made. They
    are read from the device when it is mounted and from the latest backup
    otherwise, and a smart playlist is shown but never authored.
    """
    from . import itunesdb as I
    try:
        from . import config
        mount = config.load().get('mount', '/Volumes/IPOD')
    except SystemExit:
        mount = '/Volumes/IPOD'
    dbp = os.path.join(mount, 'iPod_Control/iTunes/iTunesDB')
    mounted = os.path.exists(dbp)
    if not mounted:
        cand = sorted(glob.glob(os.path.join(ROOT, 'backups/ipod-*/iTunesDB')))
        if not cand:
            return {'mounted': False, 'source': None, 'playlists': []}
        dbp = cand[-1]
    try:
        db = I.read(dbp)
    except Exception as e:
        return {'mounted': mounted, 'source': None, 'error': str(e)[:200], 'playlists': []}
    by_id = {t['id']: S.key_for(t.get('artist'), t.get('title')) for t in db['tracks']}
    st = S.load()
    ours = set(st.get('collections', [])) | set(st.get('synced_playlists', []))
    out = []
    for p in db['playlists']:
        if p.get('master'):
            continue
        keys = []
        for it in p.get('items') or []:
            tid = it if isinstance(it, int) else (it.get('track_id') or it.get('id') or it.get('tid')) if isinstance(it, dict) else None
            k = by_id.get(tid)
            if k:
                keys.append(k)
        out.append({'name': p['name'], 'n': len(keys), 'keys': keys,
                    'smart': bool(p.get('smart')), 'ours': p['name'] in ours})
    src = 'device' if mounted else os.path.basename(os.path.dirname(dbp)).replace('ipod-', 'backup ')
    return {'mounted': mounted, 'source': src, 'playlists': out}


# ------------------------------------------------- the Podcasts collection
#
# A collection like any other in state -- filled by a drop, `saltpod decide`
# or `saltpod podcasts add`, ordered and emptied the same way -- whose effect
# on sync is the podcast media type rather than a playlist (apply._plan pops
# it, podcasts.sync_collection carries it out). What lives here is what the
# page and the terminal ask of it: its count, what is pending, and the
# seeding from files that declare themselves podcasts.

_PODDEV = {'key': None, 'filed': set(), 'listed': []}


def _device_db():
    """(path, mounted): the device's iTunesDB, else the newest backup, else (None, False)."""
    try:
        from . import config
        mount = config.load().get('mount', '/Volumes/IPOD')
    except SystemExit:
        mount = '/Volumes/IPOD'
    dbp = os.path.join(mount, 'iPod_Control/iTunes/iTunesDB')
    if os.path.exists(dbp):
        return dbp, True
    cand = sorted(glob.glob(os.path.join(ROOT, 'backups/ipod-*/iTunesDB')))
    return (cand[-1], False) if cand else (None, False)


def _podcasts_on_device():
    """{'filed': keys the device files as podcasts, 'listed': the flagged
    list's keys in order}, read once per database file and mtime."""
    from . import podcasts as P, itunesdb_write as W, ipod_edit as E
    dbp, _m = _device_db()
    if not dbp:
        return None
    stamp = (dbp, os.path.getmtime(dbp))
    if _PODDEV['key'] != stamp:
        try:
            root = W.parse(open(dbp, 'rb').read())
        except Exception:
            return None
        key_of = {}
        for t in E.tracks(root):
            key_of[E.track_dbid(t)] = S.key_for(P._mhod(t, 4), P._mhod(t, 1))
        _PODDEV.update({'key': stamp,
                        'filed': {key_of[d] for d in P.filed(root) if d in key_of},
                        'listed': [key_of[d] for d in P.list_dbids(root) if d in key_of]})
    return _PODDEV


def podcasts_summary(st=None):
    """The Podcasts row's answers: members, and how many a sync still owes.

    `pending` counts what the next sync would change: a member not yet on
    the iPod, a member on it but not filed as a podcast, and -- only once the
    collection exists in state -- a device podcast it no longer names. With
    no device and no backup to read, only the first can be known.
    """
    from . import podcasts as P
    st = st or S.load()
    name = P.COLLECTION
    members = [k for k in S.order_for(st, name) if k in st['tracks']]
    live = [k for k in members if (st['tracks'][k].get('tier') != 'remove')]
    dev = _podcasts_on_device()
    coming = [k for k in live if not (st['tracks'][k].get('device') or {}).get('location')]
    unfiled = filed_out = []
    if dev is not None:
        unfiled = [k for k in live if k not in coming and k not in dev['filed']]
        if name in (st.get('collections') or []) or members:
            filed_out = sorted(dev['filed'] - set(live))
    return {'name': name, 'n': len(members),
            'pending': len(coming) + len(unfiled) + len(filed_out),
            'coming': len(coming), 'unfiled': len(unfiled), 'filed_out': len(filed_out),
            'device_read': dev is not None}


def _declaring_keys(st):
    """State tracks whose file on the drive declares itself a podcast."""
    from . import podcasts as P
    out = []
    for k, r in st['tracks'].items():
        f = (_original(r.get('device') or {}, k) or {}).get('path')
        if f and os.path.exists(f) and P.declares_podcast(f):
            out.append(k)
    return out


def podcasts_op(body=None):
    """The Podcasts collection, for the page and `saltpod podcasts`.

    action status   its members, what is pending, and which files declare
                    themselves podcasts but are not in it yet
           seed     put those declaring files in (one undo entry)
           add      put `keys` in -- a long mix, an audiobook
           remove   take `keys` out; the next sync files them as music again
    """
    from . import podcasts as P
    body = body or {}
    act = body.get('action') or 'status'
    name = P.COLLECTION
    if act in ('add', 'remove'):
        keys = [k for k in (body.get('keys') or []) if k]
        if not keys:
            return {'ok': False, 'error': 'no tracks named'}
        out = apply_decision({'keys': keys, 'collection': name, 'mode': act})
        return dict(out if isinstance(out, dict) else {}, ok=True, action=act,
                    podcasts=podcasts_summary())
    with LOCK:
        st = S.load()
    have = set(S.order_for(st, name))
    declaring = [k for k in _declaring_keys(st) if k not in have]
    if act == 'seed':
        if declaring:
            apply_decision({'keys': declaring, 'collection': name, 'mode': 'add'})
        return {'ok': True, 'action': 'seed', 'added': declaring,
                'podcasts': podcasts_summary()}
    if act != 'status':
        return {'ok': False, 'error': 'no action called %r' % act}
    return {'ok': True, 'action': 'status', 'members': S.order_for(st, name),
            'declaring': declaring, 'podcasts': podcasts_summary(st)}


def cover_put(body=None):
    """`saltpod cover`: put_art for the terminal, which hands over bytes.

    The page POSTs the image itself to /api/art; JSON cannot carry one, so
    this refuses anything but bytes rather than reading a path it was sent.
    """
    body = body or {}
    blob = body.get('image')
    if not isinstance(blob, (bytes, bytearray)):
        return {'ok': False, 'error': 'POST the image bytes to /api/art'}
    return put_art(body.get('key') or '', body.get('path') or '', bytes(blob))


def sync_fits(exclude=None, mount=None):
    """Would a sync with these rows unticked fit on the device (debt D7)?
    The same plan and the same apply.fit() the sync itself runs; asked
    before the job starts so a refusal is an answer, not a failed job.
    None when there is no device to ask."""
    try:
        from . import apply as A
        A._cfg()
        m = mount or A.MOUNT
        if not os.path.exists(os.path.join(m, A.DB_REL)):
            return None
        return A.fit(A.drop_excluded(A.plan(m), exclude), m)
    except Exception:
        return None


def plan_summary(mount=None):
    """What a sync would do, as JSON, touching nothing.

    The device has to be there to answer honestly -- the plan is a diff
    against what the iPod actually holds, not a guess from state -- so when it
    is not mounted this says so rather than inventing an answer.
    """
    try:
        from . import apply as A
        A._cfg()
        m = mount or A.MOUNT
        if not os.path.exists(os.path.join(m, A.DB_REL)):
            return {'ok': False, 'reason': 'no iPod at %s' % m}
        p = A.plan(m)
        # Estimated on the converted size (apply.estimated_bytes). Per row
        # as well as in total: the panel lets you untick rows, and a
        # capacity figure that did not follow would be worse than none.
        add_bytes = 0
        add_size = {}
        for k, r, src in p['adds']:
            est = A.estimated_bytes(src)
            add_size[k] = est
            add_bytes += est
        try:
            sv = os.statvfs(m)
            free_bytes = sv.f_bavail * sv.f_frsize
        except OSError:
            free_bytes = None
        return {
            'add_bytes': add_bytes, 'free_bytes': free_bytes,
            'ok': True, 'mount': m,
            'new': p['new_playlists'], 'update': p['update_playlists'],
            'unchanged': p.get('unchanged', []),
            'delete': p['delete_playlists'],
            'adds': [{'key': k, 'artist': r['artist'], 'title': r['title'],
                      'bytes': add_size.get(k, 0),
                      'convert': os.path.splitext(src)[1].lower() in A.CONVERT}
                     for k, r, src in p['adds']],
            # (key, record, why) since plan() learned offline from unowned;
            # unpacking two of the three made every plan with one unsourced
            # track answer {ok: false} -- found by the first fixture library
            'no_source': [{'artist': r['artist'], 'title': r['title']}
                          for k, r, _why in p['no_source']],
            'removes': [{'key': k, 'artist': r['artist'], 'title': r['title']}
                        for k, r, t in p['removes']],
            # metadata the two sides disagree about. `winner` says which one
            # is right; 'file' is the ordinary direction.
            'retags': [{'key': k, 'artist': r.get('artist') or '',
                        'title': r.get('title') or '', 'winner': w,
                        'fields': {kk: vv for kk, vv in f.items() if vv}}
                       for k, r, tid, w, f in (p.get('retags') or [])],
            # THE SMART-PLAYLIST PHASE (decided 12 October, "Yes, a phase
            # with rows"): one row per list the sync refreshes from its
            # rules, `now` -> `would`, and the summary and Sound Check lines
            # `saltpod plan` prints -- the same functions write both, so the
            # terminal and the page say the same words. None when there is
            # nothing to say.
            'smart': A.smart_rows(p),
            'smart_line': A.smart_line(p) if [r for r in (p.get('smart') or [])
                                              if not r.get('firmware')] else None,
            'soundcheck_line': A.soundcheck_line(p),
            # How many tracks each playlist ends up with, so an unticked
            # playlist row can say what it is leaving alone.
            'sizes': {c: len(m) for c, m in p['collections'].items()},
            # The Podcasts collection is not a playlist row: its effect is a
            # media type (apply._plan). `named` is False while state does not
            # name it, and then the device's podcasts are left alone.
            'podcasts': ({'named': True,
                          'file': len(p['podcasts']['file']) + len(p['podcasts']['coming']),
                          'unfile': len(p['podcasts']['unfile']),
                          'reorder': p['podcasts']['reorder'],
                          'changed': p['podcasts']['changed']}
                         if p.get('podcasts') else
                         {'named': False, 'file': 0, 'unfile': 0, 'reorder': False,
                          'changed': False}),
            # AND WHICH ONES. A count tells you a playlist is being written;
            # it does not tell you what will be in it, which is the thing
            # you are actually approving. `on` is whether the track is
            # already on the device -- a playlist of tracks that are all
            # there copies nothing and only builds a menu.
            # `off` means: in this playlist, and also marked to come off the
            # device. A contradiction worth showing rather than resolving
            # quietly -- the sync skips it, and you can see why.
            'members': {c: [{'key': k,
                             'artist': r.get('artist') or '',
                             'title': r.get('title') or '',
                             'on': k in p['dev_by_key'],
                             'off': r.get('tier') == 'remove'}
                            for k, r in m]
                        for c, m in p['collections'].items()
                        if c in p['new_playlists'] or c in p['update_playlists']},
        }
    except Exception as e:
        return {'ok': False, 'reason': str(e)[:300]}


# A fallback, never an override: an unaccepted Xcode licence makes the shelled
# tools refuse to run, and the Command Line Tools sidestep it without sudo. A
# machine whose licence is accepted, or one with a deliberate DEVELOPER_DIR,
# keeps its own.
DEV_DIR = os.environ.get('DEVELOPER_DIR') or '/Library/Developer/CommandLineTools'

LOSSLESS_EXT = {'.flac', '.wav', '.aif', '.aiff', '.alac'}


def quality_of(dev, key):
    """The one figure that actually discriminates, for this file's format.

    Bitrate is the quality knob for a LOSSY file -- 128 against 320 is
    audible. For a LOSSLESS one it is a side-effect of how dense the music
    is: this library's own lossless tracks run 807 to 1122 kbps and are all
    the same fidelity. There, depth and sample rate are the answer.

    So: `320k` for lossy, `16/44.1` for lossless. Depth and rate come from
    the drive index, so a lossless file reads as plain kbps until the drive
    has been re-indexed -- honest, and it corrects itself.
    """
    # THE ORIGINAL ON DISK, not the copy on the iPod. The device holds a
    # CONVERTED file -- a WAV original arrives as ALAC at roughly half the
    # size -- so reading the device would report the transfer rather than the
    # music you own. The drive index is preferred wherever it has the track;
    # the device is only the fallback for something whose source has gone.
    e = _original(dev, key)
    ext = e.get('ext') or (dev or {}).get('origin_ext')
    lossless = (ext or '').lower() in LOSSLESS_EXT
    depth, rate = e.get('bit_depth'), e.get('sample_rate')
    if lossless and rate:
        khz = ('%g' % round(rate / 1000.0, 1))
        return '%s/%s' % (depth or '?', khz)
    k = kbps_of(dev, key)
    return ('%dk' % k) if k else None


def kbps_of(dev, key):
    """Bitrate of the ORIGINAL, worked out from size and duration.

    Two things this deliberately does not do. It does not read the iTunesDB
    bitrate field, which is not trustworthy -- 60928 for every MP3 on this
    device, 160 for AIFFs that are really nearer 850, six distinct values
    across 467 tracks. And it does not prefer the device copy, which is the
    converted file rather than the music you own.
    """
    e = _original(dev, key)
    if e.get('duration_sec') and e.get('size'):
        return round(e['size'] * 8 / e['duration_sec'] / 1000)
    secs, size = (dev or {}).get('seconds'), (dev or {}).get('size')
    if secs and size:
        return round(size * 8 / secs / 1000)
    return None


_LOCBYKEY = {'built': None, 'key': {}, 'path': {}}


def _local_maps():
    """The drive index, by track key AND by absolute path.

    Path is the better join for anything already on the iPod: the device
    record carries `origin`, the exact file it was made from, so it finds the
    original even when the tags are too poor for a key to match -- and 581 of
    this drive's files carry no tags at all.
    """
    idx = os.path.join(ROOT, 'data', 'local', 'index.json')
    stamp = os.path.getmtime(idx) if os.path.exists(idx) else 0
    if _LOCBYKEY['built'] == stamp:
        return _LOCBYKEY
    bykey, bypath = {}, {}
    for e in (local_index_raw() or {}).get('tracks') or []:
        bykey.setdefault(S.key_for(e.get('artist'), e.get('title')), e)
        if e.get('path'):
            bypath[e['path']] = e
    _LOCBYKEY.update({'built': stamp, 'key': bykey, 'path': bypath})
    return _LOCBYKEY


def file_identity(e):
    """The key, artist and title a drive file is decided under.

    ONE RULE FOR BOTH WAYS IN. The page names a drive row by this (an
    untagged file's filename stands in for its title, because a key is
    artist|title and it has neither) and `saltpod decide PATH` resolves a
    path to the same key here, so a file decided on in the terminal and the
    same file decided on in the page land on one record.
    """
    stem = os.path.splitext(os.path.basename(e.get('path') or ''))[0]
    artist, title = e.get('artist') or '', e.get('title') or ''
    if not (artist or title):
        title = stem
    # key_for('', '') is '|', which is truthy, so the old `key_for(artist,
    # title) or key_for('', stem)` never reached the stem: every untagged
    # file shared the one key '|'. The stem stands in before the key is made.
    return {'key': S.key_for(artist, title), 'artist': artist, 'title': title}


def path_identity(path):
    """file_identity for an absolute path in the drive index, or None."""
    ent = _local_maps()['path'].get(path) or _local_maps()['path'].get(os.path.abspath(path))
    return file_identity(ent) if ent else None


def _original(dev, key):
    """The index entry for the file this track was made from, if we have it."""
    m = _local_maps()
    o = (dev or {}).get('origin')
    return (o and m['path'].get(o)) or m['key'].get(key) or {}

def _detail_of(key, rec, dev):
    """Where this track's file is, and whether we can write to it.

    The source file is the master (see HANDOFF, "One store"), so this resolves
    the file FIRST and reports the device entry only as what will be brought
    into line.
    """
    from . import tags as T
    ent = _original(dev, key) or {}
    path = ent.get('path') or ''
    on_disk = bool(path and os.path.exists(path))
    ext = os.path.splitext(path)[1].lower() if path else ''
    why = ''
    if not on_disk:
        why = 'no file on the drive — nothing to edit yet'
    elif not T.supported(path):
        why = T.why_not(path)
    return {
        'path': path, 'name': os.path.basename(path), 'ext': ext,
        'folder': os.path.basename(os.path.dirname(path)) if path else '',
        'on_disk': on_disk,
        'writable': bool(on_disk and T.supported(path)),
        'why': why,
        'seconds': ent.get('duration_sec') or rec.get('seconds'),
        'size': ent.get('size'),
        'codec': ent.get('codec'), 'has_art': bool(ent.get('has_art')),
    }


def track_detail(key, path=''):
    """Everything the details panel shows for one track.

    ADDRESSED BY PATH AS WELL AS KEY, and that is not a convenience. A state
    key is `artist|title`, so **an untagged file cannot have one** -- it has
    neither. Zero of the 1,211 state records resolve to a WAV, while 366 of
    the untagged files on the drive are WAVs. The population this panel
    exists to fix is reachable only by path.

    `fields` is read back from the FILE, not from the index, so what you edit
    is what is actually there.
    """
    from . import tags as T
    if not key and not path:
        return {'ok': False, 'error': 'no key or path'}
    rec, dev = {}, {}
    if key:
        with LOCK:
            st = S.load()
            rec = dict(st['tracks'].get(key) or {})
        dev = rec.get('device') or {}
    if path:
        ent = _local_maps()['path'].get(path)
        if not ent:
            return {'ok': False, 'error': 'not in the drive index'}
        det = _detail_from_entry(ent)
    else:
        if not rec:
            return {'ok': False, 'error': 'no such track'}
        det = _detail_of(key, rec, dev)

    cur = {}
    if det['on_disk']:
        try:
            cur = T.read(det['path'])
        except Exception:
            cur = {}
        if not cur:
            # no writer-readable tags: fall back to what ffprobe saw
            ent = _original(dev, key) or {}
            cur = {k: ent.get(k) or '' for k in
                   ('title', 'artist', 'album', 'album_artist', 'genre')}
            if ent.get('year'):
                cur['year'] = str(ent['year'])

    return {
        'ok': True, 'key': key, 'path': det['path'],
        'artist': rec.get('artist') or cur.get('artist') or '',
        'title': rec.get('title') or cur.get('title') or '',
        'fields': {f: (cur.get(f) or '') for f in T.FIELDS},
        'guess': _guess_from_name(det['name']),
        'file': det,
        # What the device currently holds, shown as drift to be ended -- never
        # as a second thing to edit.
        'device': {'on': bool(dev.get('location')),
                   'title': dev.get('title') or '', 'artist': dev.get('artist') or ''},
        'art': ('/api/art?key=' + quote(key or det['path']))
               if _art_cached_or_makeable(key or det['path'], dev) else None,
    }


def _detail_from_entry(ent):
    """The same shape as _detail_of, for a file with no state record yet."""
    from . import tags as T
    path = ent.get('path') or ''
    on_disk = bool(path and os.path.exists(path))
    ext = os.path.splitext(path)[1].lower() if path else ''
    why = ''
    if not on_disk:
        why = 'the file is gone'
    elif not T.supported(path):
        why = T.why_not(path)
    return {'path': path, 'name': os.path.basename(path), 'ext': ext,
            'folder': os.path.basename(os.path.dirname(path)) if path else '',
            'on_disk': on_disk, 'writable': bool(on_disk and T.supported(path)),
            'why': why, 'seconds': ent.get('duration_sec'), 'size': ent.get('size'),
            'codec': ent.get('codec'), 'has_art': bool(ent.get('has_art'))}


def _guess_from_name(name):
    """What the filename is willing to say. 175 of the 581 read `artist - title`.

    Deliberately conservative: one separator, both halves non-empty, and a
    leading track number stripped. A wrong guess you have to notice and undo
    is worse than no guess, because the whole point is that nobody is reading
    these carefully the 400th time.
    """
    import re as _re
    stem = os.path.splitext(name or '')[0]
    stem = _re.sub(r'^\s*\d{1,3}\s*[-._)]\s*', '', stem)   # 09- , 03. , 12)
    for sep in (' - ', ' – ', ' — ', '_-_'):
        if stem.count(sep) == 1:
            a, t = [x.strip(' _-') for x in stem.split(sep)]
            if a and t:
                return {'artist': a, 'title': t, 'from': name}
    return None


def _art_cached_or_makeable(key, dev):
    # the same name /api/art writes; one rule, spelled once in ground.art_path
    if os.path.exists(G.art_path(key)):
        return True
    e = _local_maps()['key'].get(key) or _original(dev, key) or {}
    return bool(e.get('has_art'))


def art_file(key):
    """The cover /api/art serves for a key (or path), as a file in the art
    cache -- made now if it can be. Returns (path, already_cached), or
    (None, False) when there is no cover to be had.

    Lifted out of the /api/art handler so the ground measurement reads
    exactly the picture the page is served, by exactly this rule.

    The T7 original first -- full quality, and the copy that reliably kept
    its art. Resolved from the cached index maps, NOT by loading state: a
    row of 200 covers would otherwise queue 200 reads of a 1.9 MB state
    file behind one lock.

    THE CACHE IS CHECKED FIRST, and that is not just a shortcut: a cover you
    supplied yourself lives only there, so hunting for a file with embedded
    art before looking would mean an uploaded cover could never be served.
    It 404'd exactly that way once.
    """
    hit = G.art_path(key)
    if os.path.exists(hit):
        return hit, True
    src = None
    e = _local_maps()['key'].get(key) or {}
    if e.get('path') and os.path.exists(e['path']) and e.get('has_art'):
        src = e['path']
    dev = {}
    if not src:
        with LOCK:
            dev = ((S.load()['tracks'] or {}).get(key) or {}).get('device') or {}
        e2 = _original(dev, key)
        if e2.get('path') and os.path.exists(e2['path']) and e2.get('has_art'):
            src = e2['path']
    if not src and dev.get('location'):
        from . import itunesdb as I, config as CFG
        try:
            cand = I.ipod_path(dev['location'], CFG.load()['mount'])
            if os.path.exists(cand):
                src = cand
        except Exception:
            src = None
    if not src:
        return None, False
    out = G.art_path(key)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if not os.path.exists(out):
        try:
            subprocess.run(['ffmpeg', '-v', 'quiet', '-y', '-i', src,
                            '-an', '-vframes', '1', '-vf', 'scale=300:-1', out],
                           timeout=20, check=False)
        except Exception:
            pass
    if not os.path.exists(out) or not os.path.getsize(out):
        return None, False
    return out, False


def write_tags(body):
    """Write the fields into the file on disk. The file is the master.

    One save is one undo entry -- never one per keystroke -- so the existing
    stack stays useful across an editing session. The previous tag values are
    what the snapshot holds, which is a complete record: only the tag block
    changes, never the audio.
    """
    from . import tags as T
    key = body.get('key') or ''
    path = body.get('path') or ''
    fields = body.get('fields') or {}
    if not key and not path:
        return {'ok': False, 'error': 'no key or path'}
    rec = None
    if path:
        ent = _local_maps()['path'].get(path)
        if not ent:
            return {'ok': False, 'error': 'not in the drive index'}
        det = _detail_from_entry(ent)
    else:
        with LOCK:
            st = S.load()
            rec = st['tracks'].get(key)
            if not rec:
                return {'ok': False, 'error': 'no such track'}
            dev = rec.get('device') or {}
        det = _detail_of(key, rec, dev)
    if not det['on_disk']:
        return {'ok': False, 'error': 'no file on the drive'}
    if not det['writable']:
        return {'ok': False, 'error': det['why'] or 'not writable'}

    # PATCH THE FIELDS YOU CHANGED, do not rewrite the set. Sending all
    # seven every time means any field the reader could not see comes back
    # as empty and its frame is dropped -- which silently deleted a genre
    # the device still had. Only keys actually present in the request are
    # touched; everything else keeps whatever the file says.
    current = {}
    try:
        current = T.read(det['path'])
    except Exception:
        pass
    clean = {f: str(current.get(f) or '') for f in T.FIELDS}
    for f in T.FIELDS:
        if f in fields:
            clean[f] = str(fields[f] or '').strip()
    try:
        before = T.read(det['path'])
        # A DIGEST, NOT THE PAYLOAD. This used to read the whole audio stream
        # into memory to compare it afterwards -- fine at 95 MB of WAV, and
        # 226 MB of reads per saved edit once AIFF arrived at 113 MB a file.
        probe = T.audio_probe(det['path'])
        in_place = T.write(det['path'], clean)
        # the audio BYTES never change; the offset only holds when the new
        # tag fitted where the old one was
        T.verify(det['path'], probe, in_place=in_place)
    except Exception as e:
        return {'ok': False, 'error': '%s' % e}

    # ONE SAVE IS ONE UNDO ENTRY -- never one per keystroke, which is what
    # keeps a 60-deep stack useful across an editing session. The entry holds
    # the file's previous tags, so undo rewrites the file rather than putting
    # a value back in state that the file would then contradict.
    with LOCK:
        st = S.load()
        snap = _snapshot(st, [key] if key else [])
        snap['files'] = {det['path']: before}
        UNDO.append({'label': 'edit tags', 'snap': snap})
        del UNDO[:-UNDO_MAX]
        REDO.clear()
        # State carries the name only so the rest of the page can find the
        # track. The file is still the master; this is the index catching up.
        if key:
            r = st['tracks'].get(key) or {}
            if clean.get('artist'):
                r['artist'] = clean['artist']
            if clean.get('title'):
                r['title'] = clean['title']
            st['tracks'][key] = r
        S.save(st)
    _index_patch(det['path'], clean)
    push({'type': 'data', 'why': 'tags'})
    return {'ok': True, 'before': before, 'after': T.read(det['path']),
            'mtime': os.path.getmtime(det['path'])}


IDX_LOCK = threading.Lock()     # the drive index is not state; it locks separately


def undo_step(body=None):
    """Undo, or redo. One operation, not a branch of an HTTP handler.

    Undo and redo are the same move in opposite directions: take the top of
    one stack, snapshot the present onto the other, then restore. That makes
    redo free and keeps the two symmetric.

    THIS USED TO LIVE INSIDE `do_POST`, and that was the one real violation
    of the layer rule on the server side. A rule welded to a transport cannot
    be called by the terminal, cannot be called by the native app, and cannot
    be tested without a socket. Everything else here was already a plain
    function taking a dict and returning one; this is now too.
    """
    body = body or {}
    back = body.get('redo') is not True
    src, dst = (UNDO, REDO) if back else (REDO, UNDO)
    if not src:
        return {'ok': False, 'empty': True}
    entry = src.pop()
    with LOCK:
        st = S.load()
        other = _snapshot(st, entry['snap']['tracks'].keys())
        if entry['snap'].get('files'):
            from . import tags as _T
            other['files'] = {}
            for _p in entry['snap']['files']:
                try:
                    other['files'][_p] = _T.read(_p)
                except Exception:
                    pass
        dst.append({'label': entry['label'], 'snap': other})
        _restore(st, entry['snap'])
        S.save(st)
    push({'type': 'data', 'why': ('undo ' if back else 'redo ') + entry['label']})
    return {'ok': True, 'label': entry['label'], 'undone': back,
            'can_undo': len(UNDO), 'can_redo': len(REDO)}


def track_info(body=None):
    """The track panel's payload, by key or by path.

    BY PATH MATTERS. A key is `artist|title`, so a file with no tags has no
    key -- and the files most in need of an editor are exactly the ones with
    nothing to address them by.
    """
    body = body or {}
    return track_detail(body.get('key') or '', body.get('path') or '')



def discard_plan(body=None):          # body unused: there is nothing to say
    """Put the staged changes back so the next plan is empty.

    NOT "cancel the sync" -- there is no queued operation to cancel. The
    plan is derived: it is the difference between what you have decided and
    what the device holds. So the only way to empty it is to take the
    decisions back, and that is what this does:

      tracks marked remove   -> undecided
      tracks marked sync
        and not yet copied   -> undecided
      a playlist never
        written to the device -> the collection goes
      a playlist whose members
        have moved            -> back to exactly what the device holds
      a collection deleted
        but still on the device -> re-adopted as it is there

    Metadata edits are NOT touched. They are already in the file on disk,
    which is the master; undoing one is a separate act with its own entry on
    the stack.

    IT IS ONE UNDO ENTRY, and that is a deliberate departure from the brief,
    which said no undo. Everything else here reverses -- law 8 -- and an
    action this broad is the last one that should be the exception. The
    prompt says so, which makes it a smaller decision to take rather than a
    scarier one.
    """
    from . import apply as A
    A._cfg()
    try:
        p = A.plan(A.MOUNT)
    except Exception as e:
        return {'ok': False, 'error': 'could not read the iPod (%s)' % e}

    dev_by_key = p['dev_by_key']
    tid_to_key = {t: k for k, t in dev_by_key.items()}
    touched = {'tracks': 0, 'playlists': 0}

    with LOCK:
        st = S.load()
        keys = ([a[0] for a in p['adds']] + [r[0] for r in p['removes']]
                + [n[0] for n in p['no_source']])
        # the snapshot has to cover the playlists too, since collections and
        # their order are what a revert rewrites
        snap = _snapshot(st, set(keys) | set(st['tracks']))
        UNDO.append({'label': 'discard the staged changes', 'snap': snap})
        del UNDO[:-UNDO_MAX]
        REDO.clear()

        for k in keys:
            r = st['tracks'].get(k)
            if r and r.get('tier') in ('sync', 'remove'):
                r['tier'] = 'undecided'
                touched['tracks'] += 1

        cols = set(st.get('collections') or [])
        order = st.setdefault('collection_order', {})

        # never written to the device: it exists only as an intention
        for c in p['new_playlists']:
            cols.discard(c)
            order.pop(c, None)
            for r in st['tracks'].values():
                if c in (r.get('collections') or []):
                    r['collections'] = [x for x in r['collections'] if x != c]
            touched['playlists'] += 1

        # moved: put it back to exactly what the device holds, in that order
        dev_seq = p.get('dev_seq') or {}
        for c in p['update_playlists']:
            want = [tid_to_key[t] for t in dev_seq.get(c, []) if t in tid_to_key]
            order[c] = want
            keep = set(want)
            for k, r in st['tracks'].items():
                has = c in (r.get('collections') or [])
                if has and k not in keep:
                    r['collections'] = [x for x in r['collections'] if x != c]
                elif not has and k in keep:
                    r.setdefault('collections', []).append(c)
            touched['playlists'] += 1

        # deleted here but still on the device: take it back as it is there
        for c in p['delete_playlists']:
            want = [tid_to_key[t] for t in dev_seq.get(c, []) if t in tid_to_key]
            cols.add(c)
            order[c] = want
            for k in want:
                r = st['tracks'].get(k)
                if r is not None and c not in (r.get('collections') or []):
                    r.setdefault('collections', []).append(c)
            touched['playlists'] += 1

        st['collections'] = sorted(cols)
        S.save(st)

    push({'type': 'data', 'why': 'discarded'})
    return {'ok': True, 'tracks': touched['tracks'], 'playlists': touched['playlists'],
            'undo': 'discard the staged changes'}


def put_art(key, path, blob):
    """A cover you dropped: into the art cache, into the file, then the iPod.

    THREE PLACES, ONE PICTURE. The cache (keyed the way /api/art reads it)
    is what the page shows at once. The file on the drive is the master, so
    the cover is written into it -- m4a through tags.write_art, MP3, AIFF
    and WAV through an APIC frame in their ID3 tag (tags.embed_art) -- and
    the drive index's has_art follows. From there the device half needs
    nothing new: `saltpod art status` counts a track on the iPod whose file
    has art and whose entry on the device has none, and `saltpod art write`
    renders it into the ArtworkDB at the next sync.

    This function's first note said the cache was only a start: "Saving it
    here now means the work is not lost when they are: the cache is where
    both will read from." Both now do -- the file is written from the
    picture you dropped, and the device is given what the file carries.

    A file that cannot take one keeps the cover in the cache only, and the
    reply says why in the same words the track panel uses.
    """
    if not blob:
        return {'ok': False, 'error': 'no image'}
    if len(blob) > 12 * 1024 * 1024:
        return {'ok': False, 'error': 'that image is over 12 MB'}
    sniff = blob[:12]
    if not (sniff[:3] == b'\xff\xd8\xff' or sniff[:8] == b'\x89PNG\r\n\x1a\n'
            or sniff[:4] == b'RIFF' or sniff[4:12] == b'ftypheic'):
        return {'ok': False, 'error': 'not a jpeg, png, webp or heic'}
    ident = key or path
    if not ident:
        return {'ok': False, 'error': 'no track'}
    out = G.art_path(ident)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    # normalised to jpeg at the size the Classic's largest thumbnail wants,
    # so the ArtworkDB step has nothing left to decide
    tmp = out + '.in'
    with open(tmp, 'wb') as fh:
        fh.write(blob)
    # SCALE TO COVER AND CROP, not resize to fit: a squashed cover is worse
    # than a cropped one. `platform.resize_cover` prefers sips (in /usr/bin,
    # nothing to bundle) and falls back to ffmpeg off macOS. Measured against
    # each other on a real cover and a deliberately 900x300 one: mean absolute
    # difference 2.0-2.7 of 255, which is resampler and JPEG noise. The naive
    # exact-size resize differs by 61.8 of 255 on the non-square source, which
    # is why this is its own operation rather than a size argument.
    r = P.resize_cover(tmp, out, 320, 320)
    os.path.exists(tmp) and os.remove(tmp)
    if not r['ok']:
        return {'ok': False, 'error': 'could not read that image (%s)' % r['error']}
    O.event('info', 'art', 'cover normalised', backend=r['backend'],
            bytes=os.path.getsize(out))
    G.forget(ident)                       # a new picture under the same src
    sniffed = blob[:3] == b'\xff\xd8\xff' or blob[:8] == b'\x89PNG\r\n\x1a\n'
    # THE ORIGINAL, NOT THE 320px CACHE COPY, when the file can carry it: a
    # jpeg or png goes in at the resolution you dropped. webp and heic are
    # not pictures an ID3 or MP4 reader can be relied on to show, so those
    # go in as the normalised jpeg.
    filed = embed_cover(key, path, blob if sniffed else open(out, 'rb').read())
    push({'type': 'data', 'why': 'art'})
    if filed.get('in_file'):
        note = 'in the file; `saltpod art write` puts it on the iPod'
    else:
        note = 'saltpod only: ' + (filed.get('why') or 'not written into the file')
    return {'ok': True, 'art': '/api/art?key=' + quote(ident),
            'bytes': os.path.getsize(out), 'in_file': bool(filed.get('in_file')),
            'note': note}


def embed_cover(key, path, image):
    """Write `image` into the track's file on the drive. {'in_file', 'why'}.

    ON A COPY, THEN RENAMED OVER. The audio digest is taken before and
    checked on the copy, so a write that touched one byte of audio is thrown
    away rather than discovered afterwards -- tags.verify's promise, kept
    before the original is replaced rather than after.
    """
    import shutil as _sh
    from . import tags as T
    if path:
        ent = _local_maps()['path'].get(path)
        if not ent:
            return {'in_file': False, 'why': 'not in the drive index'}
        det = _detail_from_entry(ent)
    else:
        with LOCK:
            rec = dict(S.load()['tracks'].get(key) or {})
        if not rec:
            return {'in_file': False, 'why': 'no such track'}
        det = _detail_of(key, rec, rec.get('device') or {})
    f = det.get('path') or ''
    if not det.get('on_disk'):
        return {'in_file': False, 'why': det.get('why') or 'no file on the drive'}
    why = T.art_why_not(f)
    if why:
        return {'in_file': False, 'why': why}
    stem, ext = os.path.splitext(f)
    tmp = stem + '.saltpod-art' + ext
    try:
        probe = T.audio_probe(f)
        _sh.copy2(f, tmp)
        in_place = T.embed_art(tmp, image)
        T.verify(tmp, probe, in_place=in_place)
        os.replace(tmp, f)
    except Exception as e:
        O.event('warn', 'art', 'cover not written into the file', path=f, error=str(e))
        return {'in_file': False, 'why': str(e)}
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    O.event('info', 'art', 'cover written into the file', path=f, bytes=len(image))
    _index_patch(f, {'has_art': True})
    if key:
        # The row shows this cover from now on, ahead of an iTunes one: you
        # chose it (row_art reads the flag).
        with LOCK:
            st = S.load()
            if key in st['tracks']:
                st['tracks'][key]['art_own'] = True
                S.save(st)
    return {'in_file': True, 'why': '', 'path': f}


def _index_add(path):
    """Put one new file into the drive index, without re-probing the other 4,047.

    A recovered track that needs a full reindex before it can be edited is a
    recovery you have to remember to finish. One ffprobe, one append.
    """
    from . import local_index as LI
    idx_path = os.path.join(ROOT, 'data', 'local', 'index.json')
    try:
        ent = LI.probe(path)
    except Exception:
        ent = None
    if not ent:
        ent = {'path': path, 'ext': os.path.splitext(path)[1].lower(),
               'size': os.path.getsize(path), 'untagged': True}
    ent['mtime'] = os.path.getmtime(path)
    try:
        with IDX_LOCK:
            idx = json.load(open(idx_path))
            rows = idx.get('tracks')
            if isinstance(rows, list) and not any(e.get('path') == path for e in rows):
                rows.append(ent)
                idx['count'] = len(rows)
                tmp = idx_path + '.tmp'
                json.dump(idx, open(tmp, 'w'))
                os.replace(tmp, idx_path)
        _LOCBYKEY['built'] = None
        return True
    except Exception:
        return False


def recover_from_ipod(body):
    """Copy a track off the iPod and back onto the drive.

    THE ANSWER TO "what if there is no source file", and it is not an
    exception to the rule -- it restores it. The file is the master; if the
    only copy left is the one on the device, the fix is to bring it home,
    not to invent a second place to edit.

    The iPod is a disk. `iPod_Control/Music/F07/ABCD.mp3` is an ordinary
    file with a scrambled name; everything that makes it findable lives in
    the database. So the copy is a plain copy, and the naming comes from the
    database entry that has been carrying the truth all along.

    Worth saying plainly: this also recovers a library. An iPod outliving
    the machine that filled it is the ordinary way these collections end up
    stranded, and the audio was never the part that went missing.
    """
    from . import apply as A, config as CFG, tags as T
    A._cfg()
    key = body.get('key') or ''
    if not key:
        return {'ok': False, 'error': 'no key'}
    with LOCK:
        st = S.load()
        rec = st['tracks'].get(key)
    if not rec:
        return {'ok': False, 'error': 'no such track'}
    dev = rec.get('device') or {}
    loc = dev.get('location') or ''
    if not loc:
        return {'ok': False, 'error': 'not on the iPod'}

    src = os.path.join(A.MOUNT, loc.lstrip(':').replace(':', os.sep))
    if not os.path.exists(src):
        return {'ok': False, 'error': 'the device file is missing'}
    if _original(dev, key).get('path'):
        return {'ok': False, 'error': 'there is already a copy on the drive'}

    # config normalises to a list; the first root is where recovered files land
    roots = (CFG.load() or {}).get('library_roots') or []
    root = next((r for r in roots if os.path.isdir(r)), None)
    if not root:
        return {'ok': False, 'error': 'no library_root configured'}
    dest_dir = os.path.join(root, 'Recovered from iPod')
    os.makedirs(dest_dir, exist_ok=True)

    # Named from the database, which is the only place the name survives.
    artist = (rec.get('artist') or dev.get('artist') or 'Unknown artist').strip()
    title = (rec.get('title') or dev.get('title') or 'Unknown title').strip()
    safe = re.sub(r'[/\\:\x00-\x1f]', '_', '%s - %s' % (artist, title))[:150]
    dst = os.path.join(dest_dir, safe + os.path.splitext(src)[1].lower())
    n = 1
    while os.path.exists(dst):
        n += 1
        dst = os.path.join(dest_dir, '%s (%d)%s' % (safe, n, os.path.splitext(src)[1].lower()))

    shutil.copy2(src, dst)

    # The device entry knew the name; the file did not. Write it in, so the
    # recovered copy is a proper master rather than another nameless file.
    wrote = False
    if T.supported(dst):
        try:
            cur = T.read(dst)
            if not (cur.get('artist') or '').strip():
                T.write(dst, {'artist': artist, 'title': title,
                              'album': dev.get('album') or rec.get('album') or ''})
                wrote = True
        except Exception:
            pass

    with LOCK:
        st = S.load()
        r = st['tracks'].get(key) or {}
        r.setdefault('device', {})['origin'] = dst   # the join that finds it again
        r.pop('orphan', None)
        st['tracks'][key] = r
        S.save(st)
    _index_add(dst)
    _LOCBYKEY['built'] = None
    push({'type': 'data', 'why': 'recovered'})
    return {'ok': True, 'path': dst, 'bytes': os.path.getsize(dst), 'tagged': wrote}


def _index_patch(path, fields):
    """Keep the drive index in step without re-probing 4,048 files.

    mtime is the cheap gate everywhere else; here we know exactly what
    changed, so write it through and move on.
    """
    idx_path = os.path.join(ROOT, 'data', 'local', 'index.json')
    try:
        with IDX_LOCK:
            idx = json.load(open(idx_path))
            rows = idx['tracks'] if isinstance(idx.get('tracks'), list) else []
            for e in rows:
                if e.get('path') == path:
                    for k, v in fields.items():
                        if v:
                            e[k] = v
                    e['untagged'] = not ((e.get('artist') or '').strip()
                                         and (e.get('title') or '').strip())
                    e['mtime'] = os.path.getmtime(path)
                    break
            tmp = idx_path + '.tmp'
            json.dump(idx, open(tmp, 'w'))
            os.replace(tmp, idx_path)
        _LOCBYKEY['built'] = None          # force the next _local_maps() to rebuild
    except Exception:
        pass


# ------------------------------------------------- lookup, when it is needed
#
# Identity, price and a lossless source are only interesting for a track you
# have decided to BUY. Looking them up for a whole playlist up front spends
# hundreds of requests on tracks that will never be marked sync -- and the
# answers go stale before they are read. So the lookup now happens the moment
# a track joins the buy list, for that track alone, in the background.
#
# Bandcamp is deliberately NOT here. Its search returns an empty page to a
# cookieless request, so availability needs a real bandcamp.com tab; that stays
# a batch job you run against the buy list, which is now short by construction.
LOOKUP_Q = queue.Queue()
LOOKING = set()                 # keys in flight, so the page can say so
LOOKUP_LOCK = threading.Lock()


def wanted_seconds(key, rec):
    """How long the recording we want actually runs.

    WITHOUT THIS THE LOOKUP IS WORTH LESS THAN IT LOOKS. Duration is what
    separates the 3:30 radio edit from the 7:15 extended mix; with no duration
    every match scores `variant` and a human has to check each one by hand --
    which is exactly the work this was meant to remove. Three places know it,
    in order of trust: the file on the device, the file on the drive, and
    Apple Music's own library.
    """
    d = (rec.get('device') or {}).get('seconds')
    if d:
        return d
    return _secs_map().get(key)


_SECS = {'built': None, 'map': {}}


def _secs_map():
    """key -> seconds, from the drive index and the Apple Music library.

    Built once and reused: a linear scan of 9,000 entries per marked
    track would make a queue of fifty feel broken.
    """
    idx = os.path.join(ROOT, 'data', 'local', 'index.json')
    stamp = (os.path.getmtime(idx) if os.path.exists(idx) else 0,
             os.path.getmtime(AM_INDEX) if os.path.exists(AM_INDEX) else 0)
    if _SECS['built'] == stamp:
        return _SECS['map']
    m = {}
    for e in am_index().get('library') or []:
        if e.get('key') and e.get('secs'):
            m[e['key']] = e['secs']
    for e in (local_index_raw() or {}).get('tracks') or []:      # the file wins
        if e.get('duration_sec'):
            m[S.key_for(e.get('artist'), e.get('title'))] = e['duration_sec']
    _SECS['built'], _SECS['map'] = stamp, m
    return m


def local_index_raw():
    idx = os.path.join(ROOT, 'data', 'local', 'index.json')
    if not os.path.exists(idx):
        return None
    try:
        return json.load(open(idx))
    except Exception:
        return None


def _lookup_one(key):
    """Ask the iTunes Search API who this recording is. Keyless, cacheable."""
    from . import itunes_match as IM
    with LOCK:
        rec = (S.load()['tracks'] or {}).get(key)
    if not rec or rec.get('itunes'):
        return
    t = {'title': rec.get('title') or '', 'artist': rec.get('artist') or '',
         'album_artist': None, 'duration_sec': wanted_seconds(key, rec)}
    term = ('%s %s' % (t['artist'], IM.full_title(t['title']))).strip()
    try:
        payload = IM.search(term, 'NL')
    except Exception as e:                                   # network shape varies
        payload = {'results': [], '_error': str(e)}
    m, cand = IM.best_match(t, payload.get('results') or [])
    with LOCK:
        st = S.load()
        rec = st['tracks'].get(key)
        if not rec:
            return
        if cand:
            rec['itunes'] = {
                'track_id': cand.get('trackId'), 'album_id': cand.get('collectionId'),
                'album': cand.get('collectionName'), 'genre': cand.get('primaryGenreName'),
                'released': (cand.get('releaseDate') or '')[:10],
                'price': cand.get('trackPrice'), 'url': cand.get('trackViewUrl'),
                'preview': cand.get('previewUrl'), 'art': cand.get('artworkUrl100'),
                'seconds': round((cand.get('trackTimeMillis') or 0) / 1000.0, 1) or None,
                'verdict': (m or {}).get('verdict'), 'looked_up': time.strftime('%Y-%m-%d %H:%M'),
            }
        else:
            # a real answer, and worth keeping: do not ask again every redraw
            rec['itunes'] = {'verdict': 'not_found', 'looked_up': time.strftime('%Y-%m-%d %H:%M')}
        S.save(st)


def _lookup_worker():
    while True:
        key = LOOKUP_Q.get()
        try:
            _lookup_one(key)
        except Exception:
            pass
        finally:
            with LOOKUP_LOCK:
                LOOKING.discard(key)
            LOOKUP_Q.task_done()
            if LOOKUP_Q.empty():
                push({'type': 'data', 'why': 'looked up'})
            time.sleep(0.4)                    # the API is free; do not hammer it


def want_lookup(keys):
    """Queue a lookup for tracks that have no iTunes identity yet."""
    with LOOKUP_LOCK:
        for k in keys:
            if k not in LOOKING:
                LOOKING.add(k)
                LOOKUP_Q.put(k)


# THE GROUND, MEASURED IN THE BACKGROUND. Same shape as the lookup above:
# tracks_payload queues every row that has a picture and no measurement,
# this measures them one at a time, and when the queue drains the page is
# told to reload -- it then finds `ground` on those rows. The arithmetic and
# the cache are ground.py's; this is only the scheduling.
#
# A FAILURE IS REMEMBERED FOR THE LIFE OF THE PROCESS, not retried on the
# next payload: a cover on an unplugged drive would otherwise be queued,
# fail, push `data`, be queued again by the reload, and loop. A drain that
# measured nothing pushes nothing, for the same reason. Restarting the
# server, or `saltpod ground scan`, tries them again.
GROUND_Q = queue.Queue()
GROUNDING = set()
GROUND_FAILED = {}              # key -> the art it failed on
GROUND_LOCK = threading.Lock()


def _ground_worker():
    got = 0
    while True:
        key, art = GROUND_Q.get()
        downloaded = False
        try:
            _entry, downloaded = G.measure_key(key, art, local=lambda i: art_file(i)[0])
            got += 1
        except Exception as e:
            with GROUND_LOCK:
                GROUND_FAILED[key] = art
            O.event('debug', 'ground', 'not measured', key=key, error=str(e)[:200])
        finally:
            with GROUND_LOCK:
                GROUNDING.discard(key)
            GROUND_Q.task_done()
            if GROUND_Q.empty() and got:
                push({'type': 'data', 'why': 'ground'})
                got = 0
            if downloaded:
                time.sleep(0.4)                # one cover per .4 s from Apple's CDN


def want_ground(rows):
    """Queue a measurement for (key, art) pairs that have none."""
    with GROUND_LOCK:
        for k, art in rows:
            if k not in GROUNDING and GROUND_FAILED.get(k) != art:
                GROUNDING.add(k)
                GROUND_Q.put((k, art))


# THE PLAYLIST MOSAICS, MADE IN THE BACKGROUND. Same shape as the ground:
# playlists_payload queues every imported playlist, this asks mosaic.build for each
# (which does nothing when the kept mosaic is still made from the playlist's
# first four covers), and when a batch that MADE something drains, the page
# is told to reload and finds `art` on those rows. A drain that made nothing
# pushes nothing, so the reload's own /api/playlists cannot loop. A failure
# is remembered for the life of the process, as the ground's is.
MOSAIC_Q = queue.Queue()
MOSAICING = set()
MOSAIC_FAILED = set()
MOSAIC_LOCK = threading.Lock()


def _mosaic_worker():
    made = 0
    art_of = None
    while True:
        s = MOSAIC_Q.get()
        downloaded = 0
        try:
            if art_of is None:                 # one state read per batch
                art_of = track_art_of()
            state, downloaded = M.build(s, art_of, S.key_for, local=lambda i: art_file(i)[0])
            made += state == 'made'
        except Exception as e:
            with MOSAIC_LOCK:
                MOSAIC_FAILED.add(s)
            O.event('debug', 'mosaic', 'not made', playlist=s, error=str(e)[:200])
        finally:
            with MOSAIC_LOCK:
                MOSAICING.discard(s)
            MOSAIC_Q.task_done()
            if MOSAIC_Q.empty():
                art_of = None
                if made:
                    push({'type': 'data', 'why': 'mosaics'})
                    made = 0
            if downloaded:
                time.sleep(0.4 * downloaded)   # one cover per .4 s from Apple's CDN


def want_mosaics(slugs):
    """Queue a mosaic check for each playlist slug not already queued."""
    with MOSAIC_LOCK:
        for s in slugs:
            if s not in MOSAICING and s not in MOSAIC_FAILED:
                MOSAICING.add(s)
                MOSAIC_Q.put(s)


def playlists_payload():
    """Apple Music's playlists as the page's Music tab lists them.

    From the cached index read (am_index): `name`, `tracks` (the count),
    `created` and `last` (ISO times), plus `slug`, `imported`, and `art` --
    the playlist's mosaic URL when one has been made, else None. Asking for
    this queues the mosaics that are missing or stale (want_mosaics)."""
    d = am_index()
    have = set(playlist_slugs())
    rows = d.get('playlists', [])
    for p in rows:
        p['slug'] = M.slug(p['name'])
        p['imported'] = p['slug'] in have
        p['art'] = M.url(p['slug'])
    want_mosaics([p['slug'] for p in rows if p['imported']])
    return {'playlists': rows, 'read_at': d.get('read_at'),
            'library': len(d.get('keys', []))}


LOCAL_KEYS = set()          # refreshed on every decision; see apply_decision


def local_index():
    """The music you already own, as the drive itself organises it.

    No taxonomy is invented here. The folders on the drive ARE the grouping --
    they are how the music was filed when it was bought, and any scheme this
    tool imposed instead would be a second, worse one to keep in your head.
    Files loose in the root become one group named after the root.
    """
    idx = os.path.join(ROOT, 'data', 'local', 'index.json')
    if not os.path.exists(idx):
        return {'roots': [], 'folders': [], 'built': None}
    try:
        d = json.load(open(idx))
    except Exception:
        return {'roots': [], 'folders': [], 'built': None}
    roots = d.get('roots') or []
    # whether each root's volume is mounted, asked once per call: a lean
    # drive row's `state` (row_state's offline/ready) depends on nothing else
    online = {r: os.path.isdir(r) for r in roots}
    # ...and its decision row: a file you hold, undecided, in no collection
    lean_decision = decision_of([{'held': True, 'tier': '', 'collections': []}])
    groups = {}
    for e in d.get('tracks') or []:
        path = e.get('path') or ''
        root = next((r for r in roots if path.startswith(r)), None)
        if root is None:
            continue
        rel = os.path.relpath(path, root)
        parts = rel.split(os.sep)
        name = parts[0] if len(parts) > 1 else os.path.basename(root)
        g = groups.setdefault(name, {'name': name, 'root': os.path.basename(os.path.dirname(root)) or root,
                                     'tracks': [], 'lossless': 0})
        ext = (e.get('ext') or '').lower()
        if ext in LOSSLESS_EXT:
            g['lossless'] += 1
        # 581 files carry no tags at all. Their filename is the only name they
        # have, and a blank row is useless to browse, so it stands in.
        ident = file_identity(e)
        g['tracks'].append({
            'key': ident['key'],
            'artist': ident['artist'], 'title': ident['title'], 'file': parts[-1],
            # the absolute path, because a key is artist|title and an
            # untagged file has neither -- the panel addresses it by this
            'path': e.get('path'),
            'album': e.get('album'), 'secs': e.get('duration_sec'),
            'ext': ext, 'lossless': ext in LOSSLESS_EXT,
            # a sub-path is worth showing: "Bought Tracks" is 1,180 files deep
            'sub': os.sep.join(parts[1:-1]) or None,
            'untagged': bool(e.get('untagged')),
            # the answers a row needs before it has a record in the state
            # (debt D3/D4): a file you own, ready when its drive is mounted;
            # nothing to play until it is adopted, because /api/audio serves
            # state rows (audio_source)
            'state': row_state({'local': True, 'reachable': online.get(root)}),
            'play': None,
            'decision': lean_decision,
        })
    for g in groups.values():
        g['tracks'].sort(key=lambda t: ((t['sub'] or '').lower(), t['artist'].lower(), t['title'].lower()))
    out = sorted(groups.values(), key=lambda g: g['name'].lower())
    return {'roots': roots, 'built': time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(idx))),
            'folders': out}


def local_keys(reachable_only=False):
    """Keys we hold a playable file for, from the index of your own drive.

    A collection may name a track you have not bought; sync reports it under
    `no_source` and writes the rest. This is what lets the page say which is
    which before you plug anything in.

    `reachable_only` is the difference between OWNING a track and being able
    to WRITE it today. The two were one flag, so a track on an unplugged
    drive rendered exactly like one sitting ready -- full ink, no warning,
    and the first sign of trouble was sync declining to add it. Owning it is
    permanent; reaching it depends on what is mounted this minute, and the
    page needs both to say "you have this, plug the drive in" instead of
    "buy this".
    """
    try:
        from . import local_index as LI
        rows = LI.load()['tracks']
    except Exception:
        return set()
    out = set()
    for e in rows:
        if reachable_only and not os.path.exists(e.get('path') or ''):
            continue
        out.add(S.key_for(e.get('artist'), e.get('title')))
    return out


# Reachability changes when a drive is plugged in, not when the index is
# rebuilt, so it is cached for a few seconds rather than against the index's
# mtime -- long enough that one page render does not stat the library twice,
# short enough that plugging a drive in shows up without a reload.
_REACH_CACHE = {'at': 0, 'keys': None}


def reachable_keys(ttl=5.0):
    now = time.time()
    if _REACH_CACHE['keys'] is None or now - _REACH_CACHE['at'] > ttl:
        _REACH_CACHE.update(at=now, keys=local_keys(reachable_only=True))
    return _REACH_CACHE['keys']


# ---------------------------------------------------------------- answers
#
# THE SERVER ANSWERS THE QUESTIONS; A CLIENT RENDERS THE ANSWERS.
#
# The payload used to be 37 facts and no answers, so "is this on the buy
# list" was worked out in the page from three of them -- and would have been
# worked out again, separately, in the native app, and a third time in
# anything else that ever talked to this. Three implementations of one rule
# is three places for it to drift.
#
# So the rule is: **a client may look things up; it may not work them out.**
# Membership of a named list is a lookup. Deciding what belongs in that list
# is a rule, and rules live here.

LISTS = ('to buy', 'to sync', 'to remove', 'needs a drive', 'on iPod', 'on T7',
         'on vinyl', 'rented only', 'owned digitally',
         # the buy pane's stages (debt D8) and the vinyl pane's to-do (D9)
         'synced', 'FLAC to buy', 'not looked up', 'vinyl to add')


_LP = {'built': None, 'own': set(), 'want': set()}


def _vinyl_sets():
    """The Discogs collection and wantlist, as release keys.

    Cached on the file timestamps, because this is asked once per track and
    there are 1,211 of them.
    """
    from . import discogs as D
    stamp = tuple(os.path.getmtime(os.path.join(D.DIR, fn))
                  if os.path.exists(os.path.join(D.DIR, fn)) else 0
                  for fn in D.FILES.values())
    if _LP['built'] != stamp:
        pay = D.payload()
        _LP['own'] = {x['key'] for x in (pay.get('collection') or []) if x.get('key')}
        _LP['want'] = {x['key'] for x in (pay.get('wantlist') or []) if x.get('key')}
        _LP['built'] = stamp
    return _LP


def _release_key(artist, album):
    """The same key discogs.py builds, so the two sides can be compared.

    It lived in the page as `vkey()` -- which meant the matching rule for
    "do I own this record" existed twice, in two languages, and would have
    existed a third time in Swift.
    """
    from . import discogs as D
    a, b = D.norm(artist or ''), D.norm(album or '')
    return (a + '|' + b) if (a and b) else None


def _answers(t):
    """The questions the interface asks, answered once.

    `lists` is the whole filter model: every chip in the centre pane, the
    buy pane and the vinyl pane is membership of one of these. A client
    filters by `name in t['lists']`, which is a lookup, and gains nothing by
    knowing why.
    """
    held = bool(t.get('local') or t.get('device'))
    rk = _release_key(t.get('artist'), t.get('album') or t.get('dev_album'))
    lp = _vinyl_sets()
    owned_lp = bool(rk and rk in lp['own'])
    wanted_lp = bool(rk and rk in lp['want'])
    lists = []
    if t.get('tier') == 'sync' and not held:
        lists.append('to buy')
    # `reachable`, not `local`. "To sync" is a promise about the next sync,
    # and a file on an unplugged drive cannot be part of one -- plan() will
    # not add it either. The tracks that fall out of this list do not
    # vanish; they land in the one below, which is a different sentence:
    # not "buy this" and not "ready", but "fetch the drive".
    if t.get('tier') == 'sync' and t.get('reachable') and not t.get('device'):
        lists.append('to sync')
    if (t.get('tier') == 'sync' and t.get('local')
            and not t.get('reachable') and not t.get('device')):
        lists.append('needs a drive')
    # ONLY WHAT WILL ACTUALLY HAPPEN. `remove` stays on a track after the
    # sync that carried it out -- nothing resets it, and nothing should,
    # because the decision is still true. But a list called "to remove"
    # that counts five tracks already off the device is answering a
    # different question from the one the name asks. plan() says a removal
    # is pending only when the track is still there; this agrees with it.
    if t.get('tier') == 'remove' and t.get('device'):
        lists.append('to remove')
    if t.get('device'):
        lists.append('on iPod')
    if t.get('t7'):
        lists.append('on T7')
    if owned_lp:
        lists.append('on vinyl')
    if t.get('am') and not t.get('t7') and not owned_lp:
        lists.append('rented only')
    if held:
        lists.append('owned digitally')
    # THE BUY PANE'S STAGES (debt D8), which the page filtered for itself:
    # marked sync and now on the device is the last stage, "synced"; a track
    # still to buy whose Bandcamp release was confirmed lossless is one to
    # buy as FLAC; and one still to buy that nobody has looked up yet -- no
    # iTunes answer, no verdict, not in flight -- is what "Look up the N
    # without a source" is about.
    if t.get('tier') == 'sync' and t.get('device'):
        lists.append('synced')
    if 'to buy' in lists and t.get('bc_verdict') == 'confirmed':
        lists.append('FLAC to buy')
    if 'to buy' in lists and not (t.get('url') or t.get('it_verdict') or t.get('looking')):
        lists.append('not looked up')
    # THE VINYL PANE'S TO-DO (debt D9): flagged for vinyl, and the release
    # is neither in the Discogs collection nor on the wantlist yet.
    if t.get('vinyl') and not owned_lp and not wanted_lp:
        lists.append('vinyl to add')
    return {
        'lists': lists,
        'vinyl_owned': owned_lp, 'vinyl_wanted': wanted_lp, 'release_key': rk,
        # the one grouping rule, settled once: album NAME alone. Keying on
        # artist+album shattered every compilation -- 389 "albums" out of
        # 466 tracks -- because only 904 of this drive's 4,048 files carry
        # an album_artist tag.
        'album_key': (t.get('album') or '').strip().lower() or None,
        # the vinyl pane's group heading: one card per release, named the
        # way the Discogs search wants it (D9)
        'release_label': '%s \u2014 %s' % (t.get('artist') or '',
                                             t.get('album') or '(unknown release)'),
        'held': held,
        'state': row_state(t),
        'play': row_play(t),
        'decision': decision_of([dict(t, held=held)]),
    }


def decision_of(rows):
    """The one decision row a track menu offers, for one track or a
    selection (debt D2, law 8).

    It lived in the page's paintMenu as a nested ternary -- on the device,
    else held, else not -- plus the tier the click sets, and Swift would have
    been the second copy of both. Each row needs `device`, `held`, `tier`
    and `collections`.

    `verb`  'remove' when any of them is on the iPod; else 'sync' when every
            one is held (a file you own); else 'buy'
    `on`    the decision is already made: every one marked remove (for
            'remove') or sync (for the other two). The label flips; there is
            no third "undecided" row, because pressing it again IS the undo
    `sets`  the tier the click sets. Undoing sync lands on 'undecided',
            except that a track in a collection cannot be undecided (being
            in one is the decision), so it stays 'sync'. For 'remove' when
            not on, it is 'remove' and applies only to the rows on the device
    `digital_only`  not on the iPod and every one held: "Owned digitally"

    The words are the client's: a lookup table keyed by verb and on.
    """
    rows = list(rows)
    if not rows:
        return None
    on_dev = any(r.get('device') for r in rows)
    held = all(r.get('held') for r in rows)
    if on_dev:
        on = all(r.get('tier') == 'remove' for r in rows)
        return {'verb': 'remove', 'on': on,
                'sets': {'tier': 'undecided' if on else 'remove'},
                'digital_only': False}
    on = all(r.get('tier') == 'sync' for r in rows)
    any_col = any(r.get('collections') for r in rows)
    return {'verb': 'sync' if held else 'buy', 'on': on,
            'sets': {'tier': 'undecided' if (on and not any_col) else 'sync'},
            'digital_only': held}


def decision_for(body):
    """/api/decision and `saltpod decision`: decision_of over a selection.

    The menu for one row reads the row's own `decision`; a selection of many
    asks here, so no client combines rows. A key with no record in the state
    (a library or drive row not yet adopted) counts as undecided, in no
    collection, held when the drive index has a file for it.
    """
    keys = [k for k in (body.get('keys') or []) if k]
    if not keys:
        return {'ok': False, 'error': 'no keys'}
    with LOCK:
        tracks = S.load()['tracks']
    loc = local_keys()
    rows = []
    for k in keys:
        r = tracks.get(k)
        if r is None:
            rows.append({'device': False, 'held': k in loc, 'tier': '', 'collections': []})
            continue
        dev = r.get('device') or {}
        on_pod = bool(dev) and r.get('on_ipod', True) is not False
        rows.append({'device': on_pod,
                     'held': bool(on_pod or dev.get('origin') or k in loc),
                     'tier': r.get('tier'), 'collections': r.get('collections') or []})
    return dict(decision_of(rows), ok=True, n=len(rows))


def row_state(t):
    """Which of law 3's three positions a row is in (debt D3).

    `ready`    you hold the music and a sync could write it today
    `offline`  you hold it, but on a drive that is not mounted
    `unowned`  no file anywhere: buy it, or it stays a wish

    The page worked this out in rowHTML from four fields; a Swift row would
    have been the second copy. `device` counts as holding it.
    """
    if not (t.get('device') or t.get('local')):
        return 'unowned'
    return 'ready' if (t.get('device') or t.get('reachable')) else 'offline'


def row_play(t):
    """What a click on the row plays (debt D4): the file wherever it is
    (`play_from` says which library), else the 30-second preview, else
    nothing. Agrees with audio_source(), which serves `audio` rows."""
    if t.get('audio'):
        return 'file'
    return 'preview' if t.get('preview') else None


def collate(s):
    """A sort key that reads names the way a person files them: accents
    folded, case ignored, so "Ásgeir" sits with the A's and "dj" with "DJ".
    One collation, here, because every client's own (JavaScript's
    localeCompare, Swift's localizedCompare) differs from the next."""
    import unicodedata
    s = unicodedata.normalize('NFKD', s or '')
    return ''.join(c for c in s if not unicodedata.combining(c)).casefold()


def on_ipod_order(rows):
    """"All on iPod" (debt D6): every track on the device, by artist then
    title, as the Classic's Songs menu lists them. The page sorted this
    itself with localeCompare; Swift's collation would not have agreed, so
    the order is sent as keys."""
    on = [t for t in rows if t.get('device')]
    on.sort(key=lambda t: (collate(t.get('artist')), collate(t.get('title'))))
    return [t['key'] for t in on]


def sync_counts(rows):
    """What the Sync button promises, answered once (debt D1).

    The page used to count this itself, three lines in `counts()` and the
    off count again in the data panel -- and the Swift client would have been
    the third copy. It is a different question from `to_sync`: that list is
    defined by TIER (marked sync, reachable, not on the device), while the
    button is defined by COLLECTION MEMBERSHIP, because a sync writes the
    collections and a track in none of them is never put on the device
    whatever its tier. Both are kept and both are named, so neither client
    has to pick one or derive the other.

    `sync_off`     on the iPod and marked remove: what the next sync takes off
    `sync_on`      not on the iPod, in a collection, its file reachable now
    `sync_pending` the two together: the number on the button
    `sync_waiting` in a collection and owned, but on a drive not mounted
    """
    off = sum(1 for t in rows if t.get('device') and t.get('tier') == 'remove')
    on = sum(1 for t in rows if not t.get('device') and t.get('reachable')
             and t.get('collections'))
    waiting = sum(1 for t in rows if not t.get('device') and t.get('local')
                  and not t.get('reachable') and t.get('collections'))
    return {'sync_off': off, 'sync_on': on, 'sync_pending': off + on,
            'sync_waiting': waiting}


def row_art(k, r):
    """The picture a track's row shows: a cover you dropped on it, else the
    iTunes cover at 300px, else your own file's cover through /api/art,
    else ''. One rule, read by the payload and by `saltpod ground`."""
    if r.get('art_own'):
        # a cover you dropped on this track, written into its file: the
        # same picture the panel shows and the iPod is given
        return '/api/art?key=' + quote(k)
    art = ((r.get('itunes') or {}).get('art') or '').replace('100x100bb', '300x300bb')
    if not art and (_original(r.get('device') or {}, k) or {}).get('has_art'):
        art = '/api/art?key=' + quote(k)
    return art


def track_art_of(tracks=None):
    """`art_of(key)`: the picture a track's row shows (row_art), or a cover
    you supplied that sits in the art cache, or ''. What a playlist mosaic
    is made of (mosaic.py); `tracks` is the state's, loaded once if absent."""
    if tracks is None:
        with LOCK:
            tracks = S.load()['tracks'] or {}

    def art_of(k):
        r = tracks.get(k)
        art = row_art(k, r) if r else ''
        if not art and os.path.exists(G.art_path(k)):
            art = '/api/art?key=' + quote(k)
        return art
    return art_of


def tracks_payload(scope=''):
    st = S.load()
    am_keys = set(am_index().get('keys') or [])
    loc_keys = local_keys()
    reach_keys = reachable_keys()
    out = []
    for k, r in st['tracks'].items():
        if scope and not any(p.startswith(scope) for p in r['playlists']):
            continue
        it = r.get('itunes') or {}
        art = row_art(k, r)
        dev = r.get('device') or {}
        # Which libraries hold this, and which one a click would play from.
        # `t7` is a file we own; `device` is a copy on the iPod; `am` is that it
        # came out of an Apple Music playlist at all. audio_source() prefers the
        # T7 original, so play_from says the same thing rather than guessing.
        t7 = bool(dev.get('origin'))
        # `device` must mean ON THE IPOD RIGHT NOW, not "has been". The metadata
        # blob survives a removal -- sync clears `on_ipod` but keeps the blob so
        # the origin path and duration stay available -- so testing the blob
        # alone left a removed track wearing POD, filtered as "on iPod", offered
        # "Delete from iPod", and counted forever in the Sync badge.
        on_pod = bool(dev) and r.get('on_ipod', True) is not False
        out.append({
            'device': on_pod, 'had_device': bool(dev), 'dev_album': dev.get('album'),
            'dev_seconds': dev.get('seconds'), 'origin_ext': dev.get('origin_ext'),
            'lossless': dev.get('lossless'),
            't7': t7, 'am': bool(r['playlists']) or k in am_keys,
            'am_owned': bool(r.get('am_owned')),
            'am_status': r.get('am_status'),
            'local': t7 or k in loc_keys,      # a file exists somewhere: you own it
            # ...and whether it can be written TODAY. A track you own on an
            # unplugged drive is not the same as one you have never bought,
            # and until now the page could not tell you apart.
            'reachable': bool(t7 or k in reach_keys or dev.get('location')),
            'play_from': 't7' if t7 else ('ipod' if dev.get('location') else None),
            # PLAYABLE MEANS THERE IS A FILE, wherever it is. This read
            # only the device record, so every track that existed solely on
            # the drive answered "nothing to play for this one" -- which is
            # most of the library, and the server had always been willing to
            # serve them. `play_from` on the line above already worked it
            # out; this now agrees with it instead of contradicting it.
            'audio': bool(t7 or dev.get('origin') or dev.get('location')),
            'key': k, 'artist': r['artist'], 'title': r['title'],
            'playlists': r['playlists'], 'tier': r['tier'], 'vinyl': r['vinyl'],
            # `bought` means you hold the music: a file on disk or on the
            # iPod IS that proof, so it is derived and nothing else. The
            # stored flag is ignored (control room, "Two buy lists that
            # disagree": the file is the proof); held, below, is the same.
            'bought': bool(t7 or k in loc_keys or on_pod),
            'on_ipod': r['on_ipod'],
            'collections': r['collections'],
            'orphan': bool(r.get('orphan')),
            'quality': quality_of(dev, k), 'looking': k in LOOKING, 'it_verdict': it.get('verdict'),
            'album': it.get('album') or dev.get('album') or (_original(dev, k) or {}).get('album'),
            'album_artist': (_original(dev, k) or {}).get('album_artist'),
            'genre': it.get('genre'),
            'released': it.get('released'), 'price': it.get('price'),
            'seconds': it.get('seconds'), 'url': it.get('url'),
            'preview': it.get('preview'), 'art': art,
            # the scrim that keeps this cover's ground inside the band, as
            # measured by the server (ground.py); None until it has been
            'ground': G.lookup(k, art),
            'bandcamp': (r.get('bandcamp') or {}).get('url'),
            'bc_verdict': (r.get('bandcamp') or {}).get('verdict'),
        })
        out[-1].update(_answers(out[-1]))
    want_ground([(t['key'], t['art']) for t in out if t['art'] and t['ground'] is None])
    order = {p: i for i, p in enumerate(sorted({p for t in out for p in t['playlists']}))}
    out.sort(key=lambda t: (order.get(t['playlists'][0], 99) if t['playlists'] else 99,
                            t['artist'].lower(), t['title'].lower()))
    # THE TOTALS, ANSWERED HERE. Two places in the page added these up and
    # a third would have in Swift. A sum over rows the server already has
    # is not something a client should be doing.
    buy = [t for t in out if 'to buy' in t['lists']]
    totals = {'to_buy': len(buy),
              'to_buy_eur': round(sum(t.get('price') or 0 for t in buy), 2),
              'to_sync': sum(1 for t in out if 'to sync' in t['lists']),
              'needs_drive': sum(1 for t in out if 'needs a drive' in t['lists']),
              'to_remove': sum(1 for t in out if 'to remove' in t['lists']),
              'on_ipod': sum(1 for t in out if 'on iPod' in t['lists']),
              'synced': sum(1 for t in out if 'synced' in t['lists']),
              'flac_to_buy': sum(1 for t in out if 'FLAC to buy' in t['lists']),
              'not_looked_up': sum(1 for t in out if 'not looked up' in t['lists']),
              'vinyl_to_add': len({t['release_label'] for t in out
                                   if 'vinyl to add' in t['lists']})}
    totals.update(sync_counts(out))
    # The Podcasts collection is always there to drop onto, members or not.
    from . import podcasts as _P
    st_cols = sorted(set(st.get('collections', [])) | {_P.COLLECTION})
    order = {c: S.order_for(st, c) for c in st_cols}
    pods = podcasts_summary(st)
    # what only the podcast phase would change; members still to be copied
    # are already in sync_on
    totals['sync_podcasts'] = pods['unfiled'] + pods['filed_out']
    totals['sync_pending'] = totals.get('sync_pending', 0) + totals['sync_podcasts']
    return {'tracks': out, 'collections': st_cols, 'order': order, 'totals': totals,
            'podcasts': pods,
            'on_ipod_order': on_ipod_order(out),
            # the vinyl pane's cards, one per release, in heading order (D9)
            'vinyl_order': sorted({t['release_label'] for t in out if t.get('vinyl')}, key=collate),
            'synced': st.get('synced_playlists') or [],
            'slugs': playlist_slugs(), 'updated': st.get('updated')}


def adopt(st, body):
    """Give a track its first record.

    Everything in Apple Music is browsable, but only what you decide on earns a
    row in state -- otherwise the curation queue would be the whole library and
    mean nothing. The first b / v / c on a library track creates it here.
    """
    for a in body.get('adopt') or []:
        k = a.get('key')
        if k and k not in st['tracks']:
            st['tracks'][k] = S.blank(a.get('artist') or '', a.get('title') or '')


UNDO, REDO = [], []
UNDO_MAX = 60


def _snapshot(st, keys):
    """A before-image of everything a decision can touch.

    Copies rather than references: the caller is about to mutate these in
    place. Collections and their order come along because a decision can
    change membership, and membership carries a sequence -- which is the
    product.
    """
    import copy
    return {'tracks': {k: copy.deepcopy(st['tracks'][k])
                       for k in keys if k in st['tracks']},
            'collections': list(st.get('collections', [])),
            'collection_order': copy.deepcopy(st.get('collection_order', {}))}


def _restore(st, snap):
    for k, rec in snap['tracks'].items():
        st['tracks'][k] = rec
    st['collections'] = list(snap['collections'])
    st['collection_order'] = snap['collection_order']
    # A TAG EDIT IS UNDONE BY REWRITING THE FILE, not by putting a value back
    # in state -- the file is the master. The previous tag values are a
    # complete record because only the tag block ever changed, so this is a
    # real restore rather than an approximation.
    #
    # It is also FORWARD, not backward, with respect to the device: rewriting
    # the file bumps its mtime, the next plan() sees the device disagrees, and
    # the sync after that corrects it.
    from . import tags as T
    for path, before in (snap.get('files') or {}).items():
        try:
            if os.path.exists(path):
                T.write(path, before)
                _index_patch(path, {f: (before.get(f) or '') for f in T.FIELDS})
        except Exception:
            pass


def _label(body, keys):
    n = len(keys)
    many = '%d tracks' % n if n != 1 else 'a track'
    if body.get('rename_collection') is not None:
        to = body.get('to')
        return ('delete "%s"' % body['rename_collection']) if not to \
            else ('rename "%s"' % body['rename_collection'])
    if 'reorder' in body:
        return 're-sequence %s' % (body['reorder'].get('collection') or 'a collection')
    if 'collection' in body:
        verb = 'remove from' if body.get('mode') == 'remove' else 'add to'
        return '%s %s \u2014 %s' % (verb, body['collection'], many)
    if 'tier' in body:
        return '%s \u2014 %s' % ({'remove': 'remove from the iPod', 'sync': 'sync to the iPod',
                                   'undecided': 'undecide'}.get(body['tier'], body['tier']), many)
    if 'vinyl' in body:
        return '%s vinyl \u2014 %s' % ('set' if body['vinyl'] else 'clear', many)
    return 'edit %s' % many


def _resolve_paths(body):
    """`paths` in a decision become keys, adopted under file_identity (D13).

    A path names a file on the drive that may have no record yet -- an
    untagged WAV has no key to type -- so the terminal can address it the
    way the page does. Returns the body with `keys` and `adopt` filled in,
    or an error naming the first path the index does not hold.
    """
    if not body.get('paths'):
        return body, None
    body = dict(body)
    keys = list(body.get('keys') or ([body['key']] if body.get('key') else []))
    adopt = list(body.get('adopt') or [])
    for p in body.pop('paths'):
        ident = path_identity(p)
        if not ident:
            return body, 'not in the drive index: %s' % p
        keys.append(ident['key'])
        adopt.append(ident)
    body['keys'], body['adopt'] = keys, adopt
    body.pop('key', None)
    return body, None


def apply_decision(body, _record=True):
    from . import podcasts as _P
    if body.get('rename_collection') == _P.COLLECTION:
        # A place with an effect, not a name: renaming it would leave the
        # device's podcasts filed under a list nothing names, and deleting it
        # is what taking every track out already does, with an undo.
        return {'ok': False, 'error': 'the Podcasts collection cannot be renamed or '
                'deleted; take tracks out of it instead'}
    body, err = _resolve_paths(body)
    if err:
        return {'ok': False, 'error': err}
    if body.get('rename_collection') is not None and not str(body['rename_collection']).strip():
        return {'ok': False, 'error': 'which collection?'}
    if 'reorder' in body and not str((body['reorder'] or {}).get('collection') or '').strip():
        return {'ok': False, 'error': 'which collection?'}
    out = {}
    with LOCK:
        global LOCAL_KEYS
        LOCAL_KEYS = local_keys()
        st = S.load()
        named = body.get('rename_collection')
        if named is None and 'reorder' in body:
            named = body['reorder'].get('collection')
        if named is not None and named not in st.get('collections', []) \
                and not any(named in r['collections'] for r in st['tracks'].values()):
            return {'ok': False, 'error': 'no collection called %r' % named}
        if _record:
            touched = set(body.get('keys') or ([body['key']] if body.get('key') else []))
            for a in body.get('adopt') or []:
                touched.add(a.get('key'))
            if 'reorder' in body:
                touched |= set(body['reorder'].get('keys') or [])
            if body.get('rename_collection') is not None:
                touched |= set(st['tracks'])          # a rename can touch any record
            UNDO.append({'label': _label(body, touched), 'snap': _snapshot(st, touched)})
            del UNDO[:-UNDO_MAX]
            REDO.clear()
        adopt(st, body)
        keys = body.get('keys') or ([body['key']] if body.get('key') else [])
        touched = []
        marked = []
        for k in keys:
            rec = st['tracks'].get(k)
            if not rec:
                continue
            if 'tier' in body and body['tier'] in S.TIERS:
                rec['tier'] = body['tier']
                rec['decided_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
                if body['tier'] == 'sync':
                    marked.append(k)
            # `vinyl` only. `bought` went with the card's button (a file is
            # the proof) and `on_ipod` is the sync's to set, never a decision.
            if 'vinyl' in body:
                rec['vinyl'] = bool(body['vinyl'])
            if 'collection' in body:
                c = str(body['collection']).strip()[:60]
                if c:
                    mode = body.get('mode')          # add | remove | toggle
                    has = c in rec['collections']
                    order = st.setdefault('collection_order', {}).setdefault(c, [])
                    # Putting a track in a collection says it belongs on the
                    # iPod. If there is no file for it and it is not on the
                    # iPod, that is the same sentence as "I have to go and buy
                    # this" -- so it joins the buy list rather than sitting
                    # undecided in a playlist that sync will report as
                    # no_source. (The file is the proof: the old `bought`
                    # flag is not read.)
                    if (mode != 'remove' and not has
                            and not rec.get('on_ipod')
                            and not (rec.get('device') or {}).get('origin')
                            and k not in LOCAL_KEYS
                            and rec.get('tier') in (None, '', 'undecided', 'remove')):
                        rec['tier'] = 'sync'
                        rec['decided_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
                        marked.append(k)
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
            # the sequence as it now stands, members you did not name kept
            # at the end: the receipt says what the iPod will play, in order
            out['order'] = S.set_order(st, str(r.get('collection', '')),
                                       [str(x) for x in r.get('keys', [])])
        if 'rename_collection' in body:
            old, new = body['rename_collection'], str(body.get('to', '')).strip()[:60]
            out['renamed'] = {'from': old, 'to': new or None,
                              'members': sum(1 for rec in st['tracks'].values()
                                             if old in rec['collections'])}
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
    # outside the lock: the worker takes it for itself
    want_lookup([k for k in marked if not (st['tracks'].get(k) or {}).get('itunes')])
    # A DECISION SAYS SO (D11). It used to push nothing, so a second client
    # never heard the first one decide; the reply carries the new rev, so
    # the client that decided can tell this event is its own.
    push({'type': 'data', 'why': 'decided'})
    return dict({'ok': True, 'touched': touched, 'looking': len(marked), 'rev': rev()}, **out)


# ---------------------------------------------------------------- audio

# Chrome will not play AIFF and is patchy on FLAC; Safari is the other way round.
# Rather than guess at the browser, anything outside this set is transcoded.
# WHAT THE BROWSER PLAYS UNTOUCHED, which is nearly everything here. AIFF
# was missing and its 809 files were being transcoded on EVERY PLAY --
# Safari and Chrome both play audio/aiff natively, so that was a subprocess
# and a re-encode to deliver bytes already on disk. 3,806 of 4,050 files
# now stream straight off the drive, seekable, with nothing in between.
DIRECT = {'.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.aac': 'audio/aac',
          '.wav': 'audio/wav', '.aif': 'audio/aiff', '.aiff': 'audio/aiff',
          '.aifc': 'audio/aiff', '.mp4': 'audio/mp4', '.m4b': 'audio/mp4'}

# FLAC is the only container here no browser will take: 244 files.
PREVIEW_DIR = os.path.join(ROOT, 'data', 'local', 'preview')


def preview_for(path):
    """A browser-playable file for a container no browser takes. {'ok','path'}.

    CONVERTED ONCE, THEN CACHED, and the cache is keyed by the source's
    mtime and size so editing the file's tags produces a new preview rather
    than serving the old one. Measured on real FLACs off the drive: 138 ms
    for a 25-second track, 740 ms for 2:36, 2.2 s for 8:22 -- so the first
    play of a long track has a real pause, and the page shows it in the row
    rather than appearing to do nothing.

    AAC, not ALAC: a preview is for listening. Lossless would be slower and
    several times the size for something nobody keeps.
    """
    try:
        st = os.stat(path)
    except OSError:
        return {'ok': False, 'error': 'the file is gone'}
    stamp = '%s-%d-%d' % (re.sub(r'[^A-Za-z0-9]+', '_', os.path.basename(path))[:80],
                          int(st.st_mtime), st.st_size)
    out = os.path.join(PREVIEW_DIR, stamp + '.m4a')
    if os.path.exists(out) and os.path.getsize(out):
        return {'ok': True, 'path': out, 'cached': True}
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    tmp = out + '.part'                   # never serve a half-written file
    with O.span('preview', name=os.path.basename(path)):
        r = P.to_preview(path, tmp)
    if not r.get('ok'):
        if os.path.exists(tmp):
            os.remove(tmp)
        return {'ok': False, 'error': r.get('error') or 'conversion failed'}
    os.replace(tmp, out)
    return {'ok': True, 'path': out, 'cached': False, 'backend': r['backend']}


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

    def _json(self, obj, code=200):
        """A JSON reply, stamped with the current `rev` (D11)."""
        if isinstance(obj, dict) and 'rev' not in obj:
            obj = dict(obj, rev=rev())
        return self._send(code, json.dumps(obj))

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
            return self._json(tracks_payload((q.get('scope') or [''])[0]))
        if u.path == '/api/playlists':
            return self._json(playlists_payload())
        if u.path == '/api/events':
            q = queue.Queue(maxsize=64)
            with CLIENTS_LOCK:
                CLIENTS.append(q)
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'keep-alive')
                self.end_headers()
                self.wfile.write(b'retry: 2000\n\n')
                self.wfile.write(('data: %s\n\n' % json.dumps({'type': 'hello', 'boot': BOOT})).encode())
                self.wfile.flush()
                while True:
                    try:
                        self.wfile.write(q.get(timeout=20).encode())
                    except queue.Empty:
                        self.wfile.write(b': keepalive\n\n')   # through proxies and idle timeouts
                    self.wfile.flush()
            except Exception:
                pass                                            # the tab closed
            finally:
                with CLIENTS_LOCK:
                    if q in CLIENTS:
                        CLIENTS.remove(q)
            return
        if u.path == '/api/undo':
            return self._json({'can_undo': len(UNDO), 'can_redo': len(REDO),
                                               'next': UNDO[-1]['label'] if UNDO else None})
        if u.path == '/api/looking':
            with LOOKUP_LOCK:
                return self._json({'keys': sorted(LOOKING)})
        if u.path == '/api/history':
            hp = os.path.join(LOGS, 'history.jsonl')
            rows = []
            if os.path.exists(hp):
                for ln in open(hp):
                    try:
                        rows.append(json.loads(ln))
                    except Exception:
                        pass
            return self._json({'runs': rows[-50:][::-1]})
        if u.path == '/api/device':
            return self._json(device_playlists())
        if u.path == '/api/health':
            return self._json(health())
        if u.path == '/api/plan':
            return self._json(plan_summary())
        if u.path == '/api/art':
            # Your own cover art, out of your own file. Extracted once with
            # ffmpeg and cached; no network, no API, no account -- and it
            # covers the music iTunes has never heard of, which on this drive
            # is most of it.
            # key OR path: an untagged file has no key, because a key is
            # artist|title and it has neither. Same identity rule as put_art.
            _q = parse_qs(u.query)
            if 'playlist' in _q:
                # a playlist's mosaic, made by the worker (mosaic.py); never
                # made here, so a request costs a file read at most
                pl = (_q.get('playlist') or [''])[0]
                path = M.out_path(pl) if M.valid(pl) else None
                if not path or not os.path.exists(path):
                    return self._send(404, b'', 'image/jpeg')
                return self._send(200, open(path, 'rb').read(), 'image/jpeg')
            key = (_q.get('key') or [''])[0] or (_q.get('path') or [''])[0]
            # Which file, and in what order it is looked for: art_file().
            out, hit = art_file(key)
            if hit:
                return self._send(200, open(out, 'rb').read(), 'image/jpeg')
            if not out:
                return self._send(404, b'', 'image/jpeg')
            body = open(out, 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'max-age=86400')
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path == '/api/decision':
            # a question, so a GET as well as the registry's POST
            return self._json(OPS['/api/decision']({'keys': q.get('key') or []}))
        if u.path == '/api/track':
            q = parse_qs(u.query)
            return self._json(track_detail(
                (q.get('key') or [''])[0], (q.get('path') or [''])[0]))
        if u.path == '/api/local':
            d = local_index()
            want = (parse_qs(u.query).get('folder') or [None])[0]
            # the folder list is small; the tracks are 4,000+, so they come one
            # folder at a time, the way a peek reads one playlist
            folders = [{'name': g['name'], 'n': len(g['tracks']), 'lossless': g['lossless']}
                       for g in d['folders']]
            body = {'root': os.path.basename(d['roots'][0]) if d['roots'] else None,
                    'built': d['built'], 'folders': folders,
                    'total': sum(f['n'] for f in folders),
                    'reach': library_reach()}
            if want is not None:
                body['folder'] = want
                if want == '__all__':
                    every = [t for g in d['folders'] for t in g['tracks']]
                    every.sort(key=lambda t: ((t['artist'] or '').lower(), (t['title'] or '').lower()))
                    body['tracks'] = every
                else:
                    g = next((x for x in d['folders'] if x['name'] == want), None)
                    body['tracks'] = (g or {}).get('tracks') or []
            return self._json(body)
        if u.path == '/api/library':
            return self._json(library_payload())
        if u.path == '/api/peek':
            name = (parse_qs(u.query).get('name') or [''])[0]
            try:
                r = _osa(['osascript', '-l', 'JavaScript',
                          os.path.join(CODE_ROOT, 'bin/export_playlists.js'), '--peek', name], 180)
                d = json.loads(r.stdout or '{}')
            except Exception as e:
                d = {'error': str(e)[:200]}
            for row in d.get('tracks', []):
                row['key'] = S.key_for(row.get('artist'), row.get('title'))
                row.update(am_row_answers(row.get('cloud')))
            return self._json(d)
        if u.path == '/api/discogs':
            from . import discogs
            return self._json(discogs.payload())
        if u.path == '/api/job':
            with JOBS_LOCK:
                j = JOBS.get((q.get('id') or [''])[0])
            return self._json(j.as_dict() if j else {'state': 'gone'})
        if u.path == '/api/audio':
            return self._audio((q.get('key') or [''])[0])
        if u.path == '/api/music':
            return self._json({'playlists': music_playlists(),
                                               'have': playlist_slugs()})
        return self._send(404, '{}')

    def _audio(self, key):
        path = audio_source(key)
        if not path:
            return self._send(404, json.dumps({'error': 'no local file'}))
        ext = os.path.splitext(path)[1].lower()
        if ext in DIRECT:
            return self._file(path, DIRECT[ext])
        made = preview_for(path)
        if not made.get('ok'):
            return self._send(404, json.dumps({'error': made.get('error') or
                                               'cannot make this playable'}))
        return self._file(made['path'], 'audio/mp4')

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
        """DEAD. Kept only so the reason does not have to be rediscovered.

        Everything used to come through here: a subprocess per play, a
        re-encode of bytes already on disk, no Range header, so no seeking
        in any track in the library. It exists now only as the explanation
        for why `_file` and `preview_for` replaced it.
        """
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
        # A cover is bytes, not JSON, so it is routed before the parse rather
        # than through it.
        if u.path == '/api/art':
            q = parse_qs(u.query)
            return self._json(put_art(
                (q.get('key') or [''])[0], (q.get('path') or [''])[0],
                self.rfile.read(n)))
        try:
            body = json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            return self._send(400, json.dumps({'ok': False, 'error': 'bad json'}))
        try:
            if u.path == '/api/decide':
                return self._json(apply_decision(body))
            if u.path in OPS:
                return self._json(OPS[u.path](body))
            if u.path == '/api/action':
                return self._json(self._action(body))
        except Busy as b:
            return self._json({'ok': False, 'error': str(b), 'job': b.job}, 409)
        except SystemExit as e:
            # a module that still says no by exiting (config.load, for one)
            # must not take the request thread down with no reply
            return self._json({'ok': False, 'error': str(e)})
        except Exception as e:
            return self._send(500, json.dumps({'ok': False, 'error': str(e)}))
        return self._send(404, '{}')

    def _action(self, body):
        a = body.get('action')
        py = sys.executable
        if a == 'lookup':
            keys = body.get('keys') or []
            if body.get('all_device'):
                # Tracks on the iPod are yours by definition, so identifying
                # them is not the speculative lookup the buy list avoids --
                # it is what gives them artwork, genre and a release date.
                with LOCK:
                    st = S.load()
                keys = [k for k, r in st['tracks'].items()
                        if r.get('device') and not r.get('itunes')]
            if body.get('all_sync'):
                with LOCK:
                    st = S.load()
                keys = [k for k, r in st['tracks'].items()
                        if r.get('tier') == 'sync' and not r.get('itunes')]
            want_lookup(keys)
            return {'ok': True, 'queued': len(keys)}
        if a == 'rebuild':
            S.rebuild(verbose=False)
            return {'ok': True}
        if a == 'device':
            return reread_device()
        if a == 'sync':
            # Exclusions travel to the subprocess as a file, not as an
            # argument: a selection can name hundreds of keys and an argv is
            # not the place for that. Written under the run directory so a
            # sync is reconstructible from what is on disk afterwards.
            # ONE SYNC AT A TIME (D12): two writers to one iTunesDB is the
            # thing the whole backup discipline exists to prevent. A second
            # client's Sync gets 409 and the running job's id to follow.
            live = running_job(SYNC_JOB)
            if live:
                raise Busy(live.id)
            args = ['sync']
            ex = body.get('exclude') or None
            # THE SERVER RE-CHECKS THE ROOM. The panel's Confirm is disabled
            # when its own arithmetic says the ticked rows will not fit, but
            # a button is not a guarantee: a second client, a stale panel,
            # or a drive that filled since the plan was read would all get
            # through. Refused here with the numbers; apply._sync refuses
            # the same way for the terminal.
            f = sync_fits(ex)
            if f and f['fits'] is False:
                return {'ok': False, 'error': 'will not fit', 'bytes': f['bytes'],
                        'free_bytes': f['free_bytes']}
            if ex and (ex.get('tracks') or ex.get('playlists') or ex.get('smart')):
                rd = os.path.join(ROOT, 'data', 'runs')
                os.makedirs(rd, exist_ok=True)
                xp = os.path.join(rd, 'exclude-%d.json' % int(time.time()))
                with open(xp, 'w') as fh:
                    json.dump({'tracks': list(ex.get('tracks') or []),
                               'playlists': list(ex.get('playlists') or []),
                               'smart': list(ex.get('smart') or [])}, fh, indent=1)
                args += ['--exclude', xp]
            return {'ok': True, 'job': run_job(SYNC_JOB, [
                ('sync', [py, '-u', '-c',
                 'import sys; sys.path.insert(0, "src"); from saltpod.cli import main; '
                 'sys.exit(main(%r))' % (args,)]),
                ('ejected', _mark_ejected)], fingerprint=True).id}
        if a == 'index':
            return {'ok': True, 'job': run_job('index the music drive', [
                ('index', [py, '-u', '-c',
                 'import sys; sys.path.insert(0, "src"); from saltpod.cli import main; '
                 'sys.exit(main(["index"]))'])]).id}
        if a == 'am_index':
            return {'ok': True, 'job': run_job('read Apple Music', [
                ('read playlists and library', [py, '-c',
                 'import sys; sys.path.insert(0, "src"); '
                 'from saltpod.curate import refresh_am_index; refresh_am_index()'])]).id}
        if a == 'am_plays':
            # Apple Music's play counts, read from its library FILE with the
            # iPod ejected and Music closed -- `saltpod plays applemusic`,
            # which refuses with one sentence (shown in the job box) when
            # either is not so. Decided 12 October, "Make it a command".
            return {'ok': True, 'job': run_job("read Apple Music's plays", [
                ('read plays, last played and skips', [py, '-u', '-c',
                 'import sys; sys.path.insert(0, "src"); from saltpod.cli import main; '
                 'sys.exit(main(["plays", "applemusic"]))'])]).id}
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
                      ['osascript', '-l', 'JavaScript', 'bin/export_playlists.js',
                       '--out', os.path.join(ROOT, 'data', 'exports'), nm])
                     for nm in names]
            if not steps:
                return {'ok': False, 'error': 'no playlists named'}
            return {'ok': True, 'job': run_job('export', steps).id}
        if a == 'match':
            slugs = body.get('slugs') or []
            steps = [('match %s' % s, job_module_argv('itunes_match', [s])) for s in slugs]
            if not steps:
                return {'ok': False, 'error': 'no playlists named'}
            return {'ok': True, 'job': run_job('match', steps).id}
        if a == 'verify':
            slugs = body.get('slugs') or []
            steps = [('verify %s' % s, job_module_argv('verify_bandcamp', [s])) for s in slugs]
            if not steps:
                return {'ok': False, 'error': 'no playlists named'}
            return {'ok': True, 'job': run_job('verify', steps).id}
        if a == 'source':
            # NAMING A MUSIC FOLDER FROM THE PAGE (control room, "Naming the
            # music folder"). The check is the one `saltpod sources add`
            # makes, answered before a job starts so a typo is a toast, not
            # a failed job; the job then runs that same verb, which walks
            # the folder into the index and records it in device.json.
            from . import config
            folder, err = config.check_root(body.get('folder') or '')
            if err:
                return {'ok': False, 'error': err}
            return {'ok': True, 'folder': folder, 'job': run_job('add a music folder', [
                ('sources add', [py, '-u', '-c',
                 'import sys; sys.path.insert(0, "src"); from saltpod.cli import main; '
                 'sys.exit(main(%r))' % (['sources', 'add', folder],)])]).id}
        return {'ok': False, 'error': 'unknown action %r' % a}


def reread_device(body=None):
    """Read the iPod's database into the curation state, or say why not.

    With no iPod and no backup there is nothing to read, and this used to
    let import_device's SystemExit escape the request thread: the handler
    catches Exception only, so the page got no reply and no toast. Now it is
    a refusal with a sentence. With a backup it says so -- `read` is
    'device' or 'backup', and `from` names the backup -- so the page's toast
    can tell you it read last week's copy rather than claiming the device.
    """
    dbp, source = S.device_db()
    if not dbp:
        return {'ok': False, 'error': 'no iPod and no backup to read: plug it in '
                                      'and put it in Disk Mode'}
    try:
        S.import_device(verbose=False, db_path=dbp)
    except SystemExit as e:
        return {'ok': False, 'error': str(e)}
    out = {'ok': True, 'read': source}
    if source == 'backup':
        out['from'] = os.path.basename(os.path.dirname(dbp))
    return out


# The research modules a Data-sheet job runs. They moved into the package and
# the jobs kept pointing at src/<name>.py, so both ended "job failed" every
# time. A job names the module, never a path, and runpy finds it the way an
# import would; bin/layer_census.py reads this tuple to count them reachable.
JOB_MODULES = ('itunes_match', 'verify_bandcamp')


def job_module_argv(mod, args):
    """The argv a job step runs to start one of JOB_MODULES as __main__."""
    if mod not in JOB_MODULES:
        raise ValueError('not a job module: %s' % mod)
    return [sys.executable, '-u', '-c',
            'import sys, runpy; sys.path.insert(0, "src"); sys.argv = %r; '
            'runpy.run_module("saltpod.%s", run_name="__main__")'
            % (['saltpod/%s.py' % mod] + list(args), mod)]


# ------------------------------------------------------- the service surface
#
# ONE TABLE, TWO ADAPTERS. The HTTP server dispatches through this and so
# does the terminal; neither contains an operation of its own. That is the
# other half of the layer rule -- the page may not work things out, and the
# server may not hide what it works out inside a transport.
#
# The rule this buys: A SECOND CALLER IS THE PROOF AN ENDPOINT IS A BOUNDARY.
# An endpoint only the page calls is a function that happens to be reachable
# over HTTP; one the terminal calls too has a shape that survives contact
# with a client that is not a browser. `bin/layer_census.py --strict` fails
# when an entry here has no verb, so the gap cannot quietly reopen.
#
# Every operation has the same signature: it takes a dict and returns a
# dict. No request object, no argv, no printing, no exit codes.
_OPS = {
    '/api/decide': apply_decision,
    '/api/undo': undo_step,
    '/api/discard': discard_plan,
    '/api/recover': recover_from_ipod,
    '/api/tags': write_tags,
    '/api/track': track_info,
    '/api/decision': decision_for,
    '/api/podcasts': podcasts_op,
    '/api/cover': cover_put,
}


def _observed(name, fn):
    """Wrap one operation so it logs a start, a duration and any error.

    INSTRUMENTING THE TABLE INSTRUMENTS BOTH CLIENTS. This is the dividend
    of having one registry rather than two dispatch blocks: the page, the
    terminal and whatever calls the API next all run through here, so there
    is exactly one place where an operation is timed and exactly one place
    where a failure is recorded. Had undo still lived inside do_POST, it
    would have needed its own instrumentation and would have been the one
    operation nobody could see.

    What is logged is the operation, the keys it touched and how long it
    took -- never the field VALUES, which are the user's metadata and belong
    in the file rather than in a log.
    """
    def run(body=None):
        body = body or {}
        keys = body.get('keys') or ([body['key']] if body.get('key') else [])
        op = name.rsplit('/', 1)[-1]
        # Only what is actually there. A log line reading n=null fields=null
        # is three quarters punctuation, and the whole value of a structured
        # log is that you can read a hundred lines of it at a glance.
        data = {}
        if keys:
            data['n'] = len(keys)
        if body.get('fields'):
            data['fields'] = sorted(body['fields'])
        if body.get('path'):
            data['path'] = body['path']
        with O.span(op, **data) as rid:
            out = fn(body)
            if isinstance(out, dict) and out.get('ok') is False:
                # A refusal is not a crash, but it is the thing you want to
                # find afterwards: "not in the drive index" twice over is a
                # client asking the wrong question, and nothing else records
                # that it happened.
                O.event('warn', op, out.get('error') or 'refused', run=rid)
            return out
    run.__name__ = getattr(fn, '__name__', name)
    run.__doc__ = fn.__doc__
    return run


OPS = {k: _observed(k, f) for k, f in _OPS.items()}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=7654)
    ap.add_argument('--no-open', action='store_true')
    a = ap.parse_args(argv)

    if not S.load()['tracks']:
        print('first run - building state'); S.rebuild()

    srv = ThreadingHTTPServer(('127.0.0.1', a.port), Handler)
    threading.Thread(target=_lookup_worker, daemon=True).start()
    threading.Thread(target=_ground_worker, daemon=True).start()
    threading.Thread(target=_mosaic_worker, daemon=True).start()
    watch_page(os.path.join(HERE, 'curate.html'))
    watch_code()
    url = 'http://127.0.0.1:%d/' % a.port
    print('saltpod  ->  %s' % url)
    print('everything happens in the page. ctrl-c here when done.')
    print('live: edits to curate.html reload open tabs; edits to the .py files restart the server; jobs redraw in place.')
    if not a.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\nstopped. state: %s' % os.path.relpath(S.STATE, ROOT))


if __name__ == '__main__':
    main()
