"""Structured event and error logging for the SERVER and the CLI.

This is the MACHINE-facing counterpart to `console.py`. console.py is for a
person watching a terminal -- receipts, spinners, colour, one line that
matters. This module is for afterwards: "what did the last sync actually
do", "which op is slow", "what was the exception, three syncs ago, that
nobody was watching for." Nothing here prints. Nothing in console.py should
start logging. They solve different problems and neither should grow to
cover the other's job.

WHERE IT GOES. One append-only file, `data/logs/events.jsonl`, one JSON
object per line. Anything that ever reads this file -- a `saltpod logs`
verb, a one-off script, a person with `jq` -- depends on the shape of that
line, so it is specified here and nowhere else:

    ts     str    ISO 8601, local time, a UTC offset, millisecond precision.
                  "2026-10-01T14:23:01.123+02:00". Never UTC-only and never
                  naive: a laptop's local clock is what a person debugging
                  this at 11pm is going to compare it against.
    level  str    'debug' | 'info' | 'warn' | 'error'.
    op     str    the operation, dotted for a sub-operation: 'plan', 'sync',
                  'tags.write'. Pick one name per operation and keep using
                  it -- summary() groups by this string, verbatim.
    run    str    8 hex characters shared by every event of one run or one
                  HTTP request, so a reader can `grep` one id and see the
                  whole story. See `run_id()` and `span()`.
    ms     float  duration in milliseconds. Present on a span's completion
                  event and on an error event; absent on a start event or a
                  plain one-off event that was not timed. Rounded to 2dp.
    msg    str    short and human-readable: 'start', 'done', or a one-off
                  note. Not a format string -- put the variables in `data`.
    data   dict   everything specific to this operation: paths, counts,
                  track ids, exception details. NEVER the contents of an
                  audio file, and never the device's FireWire GUID (see
                  SECRETS below) -- log paths and numbers, not payloads.

A line missing one of these keys is a bug in this module, not a variant
schema a reader needs to cope with. Add a key if a new need arises; never
repurpose or remove one -- every consumer is reading these by name.

SECRETS. `data/device.json`'s `firewire_guid` (see config.py) is the one
secret this tool holds -- it is what hash58 signs the database with, and
leaking it is the whole security model gone. Nothing here accepts it
knowingly, but a caller will eventually pass a dict that happens to carry
it (device config, an error payload copied wholesale). Every string that
goes into a line -- `msg` and every value in `data`, recursively -- is
scanned for a bare 16-hex-character run, the GUID's exact shape, and it is
replaced before the line is ever written. See `_redact`.

ROTATION. events.jsonl is checked against a ~5 MB cap and rotated to
events.1.jsonl, pushing .1 to .2 and .2 to .3 and dropping whatever was in
.3 -- at most three generations kept, so a runaway logger costs tens of MB,
never an unbounded amount. The cap is tracked as a running byte count kept
in memory (seeded once from a real stat()) rather than stat()ing the file
on every append -- a thousand single-digit-millisecond operations must not
turn into a thousand syscalls just to find out none of them crossed 5 MB.

THREAD SAFETY. The HTTP server handles each request on its own thread.
Every append acquires one lock, builds the line under it, and writes it in
one `open().write().close()` -- so two threads logging at the same instant
produce two whole lines, never one interleaved mess. The lock also guards
the rotation check and the in-memory size counter, so a rotation can never
happen mid-write from a second thread.

NEVER THE REASON A SYNC FAILS. A write can fail -- data/ is read-only, the
disk is full, the path got weird -- and when it does this module swallows
the error and counts it in `dropped()` rather than raising. `span()` is the
sharper version of the same promise: it NEVER swallows the caller's own
exception (it always re-raises what it caught) and it NEVER raises one of
its own (a failure while building or writing the log line is itself
swallowed and counted). Logging is a bystander, not a participant.

LEVEL. Default is 'info'. Set the environment variable SALTPOD_LOG to
'debug', 'info', 'warn' or 'error' to change the threshold for the whole
process. A level below the threshold is checked and discarded before
anything else happens -- no timestamp, no redaction scan, no formatting --
so a call site can leave `event('debug', ...)` in a hot loop and pay
almost nothing for it at the default level.

USE.

    from . import observe

    with observe.span('sync', mount=mount):
        ...                                    # logs 'start', then 'done'
                                                # with ms, or 'error' + raise

    observe.event('warn', 'tags.write', 'no writer for extension', ext=ext)

    rows = observe.tail(20, level='error')
    s = observe.summary()                      # counts by op/level, slowest

`python3 -m saltpod.observe selftest` exercises every guarantee above
against a temp directory -- it never touches data/logs/.
"""
import contextlib
import json
import os
import re
import sys
import threading
import time
import traceback
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LOGS = os.path.join(ROOT, 'data', 'logs')
EVENTS = os.path.join(LOGS, 'events.jsonl')

LEVELS = {'debug': 10, 'info': 20, 'warn': 30, 'error': 40}

# A bare run of 16 hex characters is exactly the shape of config.py's
# firewire_guid (`re.fullmatch(r'[0-9A-Fa-f]{16}', ...)`). `\b` on both sides
# means this does NOT fire inside a longer hex run -- a sha1 (40 chars) or a
# hash58 signature has no word boundary in its middle, so this never mangles
# a legitimate hash, only something the exact length of the secret.
_GUID_RE = re.compile(r'\b[0-9A-Fa-f]{16}\b')
_REDACTED = '<redacted:guid-shaped>'

# Mutable run-time state. A dict (not module globals) so `configure()` can
# swap it in one place and selftest can save/restore it around itself.
_cfg = {'path': EVENTS, 'max_bytes': 5 * 1024 * 1024, 'backups': 3,
       'size_est': None, 'dir_ready': None}
_LOCK = threading.Lock()
_level_value = [None]          # lazy: read SALTPOD_LOG on first use, not at import
_dropped = 0                   # events lost to a write failure, see dropped()
_tls = threading.local()       # per-thread "current run id", for span() nesting


# ------------------------------------------------------------------ level

def _default_level():
    name = os.environ.get('SALTPOD_LOG', 'info').strip().lower()
    return LEVELS.get(name, LEVELS['info'])


def set_level(level):
    """Override the active threshold for this process. Mainly for selftest
    and for a --verbose CLI flag; most callers should just set SALTPOD_LOG."""
    _level_value[0] = LEVELS.get(str(level).lower(), LEVELS['info'])


def get_level():
    if _level_value[0] is None:
        _level_value[0] = _default_level()        # read the env var once, lazily
    return _level_value[0]


def is_enabled(level):
    """True if `level` would actually be written right now. Lets a caller
    guard an expensive debug payload without building it only to drop it:
    `if observe.is_enabled('debug'): event('debug', op, msg, **expensive())`.
    """
    return LEVELS.get(level, LEVELS['info']) >= get_level()


# -------------------------------------------------------------------- ids

def run_id():
    """8 hex characters identifying one run or one HTTP request. Not a
    secret and not required to be globally unique -- just distinct enough,
    for the handful of minutes a log file covers, to `grep` one out."""
    return os.urandom(4).hex()


def current_run():
    """The run id active on this thread. `span()` sets one for the duration
    of its block; outside any span, one is created on first use and cached
    per thread, so a stray event() call still stitches to its neighbours."""
    rid = getattr(_tls, 'run', None)
    if rid:
        return rid
    rid = getattr(_tls, 'default_run', None)
    if not rid:
        rid = run_id()
        _tls.default_run = rid
    return rid


@contextlib.contextmanager
def use_run(run):
    """Bind `run` as the current thread's run id for this block.

    `span()`'s run id lives in thread-local storage, so a worker thread
    spawned from inside a span (a thread pool doing the actual copying,
    say) does not inherit it automatically. Wrap the worker's body in
    `with observe.use_run(rid):` to carry it across.
    """
    prev = getattr(_tls, 'run', None)
    _tls.run = run
    try:
        yield run
    finally:
        if prev is None:
            try:
                del _tls.run
            except AttributeError:
                pass
        else:
            _tls.run = prev


# -------------------------------------------------------------- redaction

def _redact(value):
    """`value`, with anything shaped like the device's FireWire GUID (16 hex
    characters, see config.py) replaced. Recurses into dicts/lists/tuples;
    anything else (numbers, booleans, None) is returned as-is."""
    if isinstance(value, str):
        return _GUID_RE.sub(_REDACTED, value)
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


# ------------------------------------------------------------- the writer

def configure(path=None, max_bytes=None, backups=None):
    """Point future writes/reads somewhere else, or change the rotation
    thresholds. Nothing here calls this -- the default is data/logs/events.
    jsonl at 5 MB / 3 generations -- it exists for selftest (which must
    never touch data/logs) and for an embedder that wants a different
    location. Safe to call mid-process; takes effect on the next write.
    """
    with _LOCK:
        if path is not None:
            _cfg['path'] = path
            _cfg['size_est'] = None       # unknown for a path we haven't sized yet
            _cfg['dir_ready'] = None
        if max_bytes is not None:
            _cfg['max_bytes'] = max_bytes
        if backups is not None:
            _cfg['backups'] = backups


def current_path():
    """Where events are being written right now."""
    return _cfg['path']


def dropped():
    """How many events were lost to a write failure since process start (a
    read-only data/, a full disk, a bad path). Logging never raises, so this
    counter is the only trace a loss leaves behind -- worth surfacing
    somewhere a person will see it (a status line, a health check)."""
    return _dropped


def _gen_path(path, n):
    stem, ext = os.path.splitext(path)
    return '%s.%d%s' % (stem, n, ext)


def _rotate_locked(path, backups):
    """Shift events.jsonl -> .1 -> .2 -> .3, dropping whatever was in the
    oldest slot. Caller holds _LOCK. Processed oldest-first so a rename
    never clobbers a generation before it has been moved out of the way.
    """
    oldest = _gen_path(path, backups)
    if os.path.exists(oldest):
        os.remove(oldest)
    for n in range(backups - 1, 0, -1):
        src, dst = _gen_path(path, n), _gen_path(path, n + 1)
        if os.path.exists(src):
            os.replace(src, dst)
    if os.path.exists(path):
        os.replace(path, _gen_path(path, 1))


def _ensure_dir_locked(path):
    """mkdir -p the log directory, but only the first time this path is
    used -- `os.makedirs(..., exist_ok=True)` is still a stat on every call,
    and an append that fires constantly should not pay that each time."""
    d = os.path.dirname(path)
    if not d or _cfg.get('dir_ready') == d:
        return
    try:
        os.makedirs(d, exist_ok=True)
        _cfg['dir_ready'] = d
    except OSError:
        pass          # the open() below will fail too, and that gets counted


def _append(rec):
    """Serialise and append one record. Never raises -- any failure, from a
    bad value in `rec` to a read-only filesystem, is swallowed and counted
    in `dropped()`."""
    global _dropped
    try:
        line = json.dumps(rec, ensure_ascii=False, default=str)
    except Exception:
        _dropped += 1
        return
    blob = (line + '\n').encode('utf-8', errors='replace')
    with _LOCK:
        try:
            path = _cfg['path']
            _ensure_dir_locked(path)
            size = _cfg['size_est']
            if size is None:
                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = 0
            if size + len(blob) >= _cfg['max_bytes']:
                try:
                    _rotate_locked(path, _cfg['backups'])
                except OSError:
                    pass
                size = 0
            with open(path, 'ab') as fh:
                fh.write(blob)
            _cfg['size_est'] = size + len(blob)
        except Exception:
            _dropped += 1


def _now_iso():
    return datetime.now().astimezone().isoformat(timespec='milliseconds')


def _emit(level, op, msg, run, data, ms=None):
    rec = {'ts': _now_iso(), 'level': level, 'op': op, 'run': run}
    if ms is not None:
        rec['ms'] = round(ms, 2)
    rec['msg'] = _redact(msg) if isinstance(msg, str) else msg
    rec['data'] = _redact(data or {})
    _append(rec)


def _safe_emit(level, op, msg, run, data, ms=None):
    """`_emit`, but a failure while BUILDING the record (not writing it --
    `_append` already covers that) is caught here too. Nothing a caller
    passes in `data` should ever be able to raise out of a log call.
    """
    global _dropped
    try:
        _emit(level, op, msg, run, data, ms=ms)
    except Exception:
        _dropped += 1


# --------------------------------------------------------------- the API

def event(level, op, msg='', run=None, ms=None, **data):
    """One-off event. The level check is the very first thing that happens
    -- a call below the active threshold does no formatting, no redaction
    scan, and touches neither the lock nor the file."""
    if not is_enabled(level):
        return
    _safe_emit(level, op, msg, run or current_run(), data, ms=ms)


def _trim_traceback(exc, keep=5):
    """The exception's traceback, last `keep` frames plus the final
    'Type: message' line -- never the whole call stack. A full traceback per
    error is what makes a day's worth of this file unreadable; the last few
    frames are where the bug actually is almost every time.
    """
    lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    tail = lines[-(keep + 1):] if len(lines) > keep + 1 else lines
    return ''.join(tail).rstrip()


@contextlib.contextmanager
def span(op, level='info', **data):
    """Context manager around one operation: logs a start event, then
    either a completion event carrying `ms`, or -- on an exception -- an
    error event carrying the exception type, message and a trimmed
    traceback, before RE-RAISING. Never swallows the caller's exception,
    never raises one of its own.

    `op` and `data` describe the operation ('sync', mount=mount); `level`
    controls the start/done pair only -- an error is always logged
    regardless of the active threshold, the same way `warn` and `error`
    already are at the default 'info' level.

    Nested spans on the same thread share one run id: the outermost call
    mints it (see `run_id()`), inner calls reuse it, and only the outermost
    call clears it on the way out. Use `use_run()` to carry a run id into a
    different thread.
    """
    parent = getattr(_tls, 'run', None)
    rid = parent or run_id()
    _tls.run = rid
    t0 = time.perf_counter()
    if is_enabled(level):
        _safe_emit(level, op, 'start', rid, data)
    try:
        yield rid
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        _safe_emit('error', op, 'error: %s' % exc, rid,
                   {**data, 'exc_type': type(exc).__name__, 'exc_msg': str(exc),
                    'traceback': _trim_traceback(exc)}, ms=ms)
        raise
    else:
        ms = (time.perf_counter() - t0) * 1000
        if is_enabled(level):
            _safe_emit(level, op, 'done', rid, data, ms=ms)
    finally:
        if parent is None:
            try:
                del _tls.run
            except AttributeError:
                pass


# -------------------------------------------------------------- the reader

def _read_file(path, level=None, op=None, run=None):
    """One file's records, in file order, matching the given filters. A
    line that fails to parse -- half-written by a crash mid-append, say --
    is skipped rather than failing the whole read; a reader is for finding
    out what happened, and one bad line should not hide the rest.
    """
    rows = []
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                if level and rec.get('level') != level:
                    continue
                if op and rec.get('op') != op:
                    continue
                if run and rec.get('run') != run:
                    continue
                rows.append(rec)
    except OSError:
        pass
    return rows


def tail(n=50, level=None, op=None, run=None):
    """The last `n` events (oldest first, newest last), optionally filtered
    by level/op/run. Reads the live file, and -- only if that alone does
    not have `n` matching rows -- walks into the rotated generations one at
    a time, so a rotation that just happened does not make "what just
    happened" come back empty.
    """
    path = _cfg['path']
    combined = _read_file(path, level, op, run) if os.path.exists(path) else []
    gen = 1
    while len(combined) < n and gen <= _cfg['backups']:
        gp = _gen_path(path, gen)
        if os.path.exists(gp):
            combined = _read_file(gp, level, op, run) + combined
        gen += 1
    return combined[-n:]


def _parse_moment(value):
    """A float/int epoch, or an ISO string (ours or any other reasonable
    one) -> epoch seconds. Returns None for anything it cannot parse,
    rather than raising -- a bad `since` should make summary() see
    everything, not crash the CLI verb that called it.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return None
    return None


def summary(since=None, top=10):
    """Counts by op, counts by level, and the `top` slowest timed events --
    the thing actually wanted after a sync went wrong: what ran, how often,
    and what was slow. `since` (epoch seconds or an ISO string) restricts
    to events at or after that moment; omitted, everything currently kept
    (the live file plus whatever generations rotation has not dropped) is
    counted.
    """
    cutoff = _parse_moment(since) if since is not None else None
    path = _cfg['path']
    paths = [path] + [_gen_path(path, n) for n in range(1, _cfg['backups'] + 1)]
    by_op, by_level, slow, total = {}, {}, [], 0
    for p in paths:
        if not os.path.exists(p):
            continue
        for rec in _read_file(p):
            if cutoff is not None:
                t = _parse_moment(rec.get('ts'))
                if t is None or t < cutoff:
                    continue
            total += 1
            op_name = rec.get('op') or '?'
            lvl = rec.get('level') or '?'
            by_op[op_name] = by_op.get(op_name, 0) + 1
            by_level[lvl] = by_level.get(lvl, 0) + 1
            ms = rec.get('ms')
            if isinstance(ms, (int, float)):
                slow.append({'op': op_name, 'ms': ms, 'ts': rec.get('ts'), 'run': rec.get('run')})
    slow.sort(key=lambda r: r['ms'], reverse=True)
    return {'total': total, 'by_op': by_op, 'by_level': by_level,
           'errors': by_level.get('error', 0), 'slowest': slow[:top]}


# --------------------------------------------------------------- selftest

def selftest():
    """Exercise every guarantee this module makes, entirely inside a temp
    directory -- it never touches data/logs/. Mirrors bin/selftest.py's
    reporting: one line per check, a tally, a nonzero return if anything
    failed. Saves and restores this module's configuration and level
    around itself, so running it does not leave real callers pointed at a
    deleted temp directory.
    """
    import shutil
    import tempfile

    tmpdir = tempfile.mkdtemp(prefix='saltpod-observe-selftest-')
    saved_cfg = dict(_cfg)
    saved_level = _level_value[0]
    passed, failed = [], []

    def p(name):
        return os.path.join(tmpdir, name)

    def check(name, fn):
        try:
            detail = fn()
        except Exception as e:
            failed.append((name, '%s: %s' % (type(e).__name__, e)))
            print('  !!  %-54s %s: %s' % (name, type(e).__name__, str(e)[:70]))
            return
        passed.append((name, detail))
        print('  ok  %-54s %s' % (name, detail or ''))

    def t_span_ms():
        configure(path=p('a.jsonl'), max_bytes=5_000_000, backups=3)
        set_level('info')
        with span('selftest.sleep'):
            time.sleep(0.05)
        rows = tail(10, op='selftest.sleep')
        done = [r for r in rows if r['msg'] == 'done']
        assert done, 'no done event recorded: %r' % rows
        ms = done[0].get('ms')
        assert isinstance(ms, (int, float)) and ms >= 30, 'ms missing or too small: %r' % ms
        return 'ms=%.1f' % ms

    def t_span_error():
        configure(path=p('b.jsonl'), max_bytes=5_000_000, backups=3)
        set_level('info')
        propagated = False
        try:
            with span('selftest.boom'):
                raise ValueError('boom-xyz')
        except ValueError as e:
            propagated = (str(e) == 'boom-xyz')
        assert propagated, 'exception did not propagate out of span()'
        rows = tail(10, level='error', op='selftest.boom')
        assert rows, 'no error event recorded'
        d = rows[-1]['data']
        assert d.get('exc_type') == 'ValueError', d
        assert 'boom-xyz' in (d.get('exc_msg') or ''), d
        tb = d.get('traceback') or ''
        assert tb and tb.count('\n') <= 10, 'traceback not trimmed: %d lines' % tb.count('\n')
        return 'error event logged, exception still propagated'

    def t_rotation():
        path = p('c.jsonl')
        configure(path=path, max_bytes=2000, backups=3)
        set_level('info')
        for i in range(400):
            event('info', 'selftest.rotate', 'filler', i=i, pad='x' * 40)
        g1, g4 = _gen_path(path, 1), _gen_path(path, 4)
        assert os.path.exists(g1), 'no rotation happened at all'
        assert not os.path.exists(g4), 'kept a 4th generation; should cap at 3'
        return 'rotated, at most 3 generations on disk'

    def t_threads():
        path = p('d.jsonl')
        configure(path=path, max_bytes=50_000_000, backups=3)
        set_level('info')

        def worker(tag):
            for i in range(200):
                event('info', 'selftest.thread', 'hit', thread=tag, i=i)

        t1 = threading.Thread(target=worker, args=('t1',))
        t2 = threading.Thread(target=worker, args=('t2',))
        t1.start(); t2.start(); t1.join(); t2.join()
        with open(path, encoding='utf-8') as fh:
            lines = [ln for ln in fh if ln.strip()]
        assert len(lines) == 400, 'expected 400 lines, got %d' % len(lines)
        for ln in lines:
            json.loads(ln)          # raises ValueError if a line got interleaved
        return '400 lines from 2 threads, all parse cleanly'

    def t_level_filter():
        path = p('e.jsonl')
        configure(path=path, max_bytes=5_000_000, backups=3)
        set_level('info')
        event('debug', 'selftest.filter', 'should be skipped')
        event('info', 'selftest.filter', 'should be kept')
        with open(path, encoding='utf-8') as fh:
            rows = [json.loads(ln) for ln in fh if ln.strip()]
        assert len(rows) == 1, 'debug event was not filtered out: %r' % rows
        assert rows[0]['msg'] == 'should be kept'
        return 'debug suppressed at the info threshold'

    def t_redaction():
        path = p('f.jsonl')
        configure(path=path, max_bytes=5_000_000, backups=3)
        set_level('info')
        secret = '00112233445566EB'            # 16 hex chars: the GUID's exact shape
        event('info', 'selftest.redact', 'probed device: %s' % secret, firewire_guid=secret)
        raw = open(path, encoding='utf-8').read()
        assert secret not in raw, 'a GUID-shaped value leaked into the log file'
        row = tail(1)[0]
        assert row['data']['firewire_guid'] != secret
        assert secret not in row['msg']
        return 'guid-shaped value redacted from msg and data'

    def t_tail_summary():
        path = p('g.jsonl')
        configure(path=path, max_bytes=5_000_000, backups=3)
        set_level('debug')
        with span('selftest.readback.a'):
            time.sleep(0.01)
        with span('selftest.readback.b'):
            time.sleep(0.02)
        event('warn', 'selftest.readback.c', 'a warning')
        rows = tail(50)
        assert len(rows) == 5, 'expected 5 rows (2 starts, 2 dones, 1 event), got %d' % len(rows)
        only_a = tail(50, op='selftest.readback.a')
        assert len(only_a) == 2, only_a
        s = summary()
        assert s['by_op'].get('selftest.readback.a') == 2, s['by_op']
        assert s['by_level'].get('warn') == 1, s['by_level']
        assert s['slowest'], 'summary reported no slow ops'
        assert s['slowest'][0]['ms'] >= s['slowest'][-1]['ms']
        return 'tail() and summary() agree with what was written'

    def t_dropped_exposed():
        n = dropped()
        assert isinstance(n, int) and n >= 0
        return 'dropped()=%d' % n

    try:
        check('span() records ms on completion', t_span_ms)
        check('exception in span() logs error and re-raises', t_span_error)
        check('rotation triggers and caps at 3 generations', t_rotation)
        check('2 threads x 200 events -> 400 clean, non-interleaved lines', t_threads)
        check('level filter skips debug at the info threshold', t_level_filter)
        check('guid-shaped values are redacted', t_redaction)
        check('tail() and summary() read back what was written', t_tail_summary)
        check('dropped-event counter is exposed', t_dropped_exposed)
    finally:
        _cfg.clear(); _cfg.update(saved_cfg)
        _level_value[0] = saved_level
        shutil.rmtree(tmpdir, ignore_errors=True)

    print('\n%d passed, %d failed' % (len(passed), len(failed)))
    if failed:
        print('\nfailures:')
        for name, why in failed:
            print('  %-54s %s' % (name, why))
    # TRUE WHEN IT PASSED, matching platform.selftest() and the rest of the
    # package. This returned an EXIT CODE -- 0 for success -- and two
    # selftest() functions in one package meaning opposite things by the same
    # return value is a trap for the next caller, which is exactly how
    # bin/selftest.py first read it as a failure.
    return not failed


def main(argv=None):
    a = argv if argv is not None else sys.argv[1:]
    if not a or a[0] != 'selftest':
        print('usage: python3 -m saltpod.observe selftest')
        return 2
    print('saltpod.observe selftest   %s' % time.strftime('%Y-%m-%d %H:%M'))
    return 0 if selftest() else 1


if __name__ == '__main__':
    sys.exit(main())
