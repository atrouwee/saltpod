#!/usr/bin/env python3
"""Loudness measurement and Apple Sound Check encoding.

WHAT SOUND CHECK IS. Apple's per-track volume normalisation -- the same job
ReplayGain does. The iPod stores one value per track in the iTunesDB at
`mhit`+0x4C (confirmed against this device: `research/ITUNES-PARITY.md` has
85/653 tracks -- everything iTunes itself added -- carrying a nonzero value,
0 on the 568 tracks saltpod has added since; `itunesdb.py` does not parse
the field at all yet). The encoding, confirmed by walking those same 85
raw values on THIS device:

    raw = 1000 * 10^(-gain_dB / 10)        raw 1000 = 0 dB, higher = more attenuation
    observed range here: raw 1252..10907, i.e. -0.98 dB .. -10.38 dB

(`1000 * 10**(-(-0.98)/10) = 1252.1`, `1000 * 10**(-(-10.38)/10) = 10908` --
both round to the observed integers, so the formula is right, not just
plausible.)

WHAT APPLE WAS AIMING AT. Measuring 20 of those 85 tracks with ffmpeg's
ebur128 and adding Apple's own gain (target = measured_LUFS + gain_dB) gave
an implied target of -17.69 to -12.28 LUFS, median -15.18, a 5.41 dB SPREAD.
That spread is the finding: Sound Check used an older RMS-style measure, not
LUFS, so "the same Sound Check gain" never meant "the same loudness" --
unlike a true LUFS-based scheme, which is the whole point of doing this over.

THE OWNER'S LIBRARY, 90 random tracks measured the same way: integrated
loudness median -11.0 LUFS (min -17.4, max -5.2), true peak median
+0.4 dBFS, max +4.0 dBFS -- loudness-war masters that already clip before
any gain is applied. Targets tried against those 90:

    -14 LUFS   24/90 would need AMPLIFYING (gain_dB > 0)
    -16 LUFS   10/90
    -18 LUFS    0/90      <- chosen
    -20 LUFS    0/90

THE DECISION: -18 LUFS. First target where nothing needs amplifying, so the
gain this module computes can never ADD clipping of its own on top of a
master that already clips -- and it happens to be the ReplayGain 2.0
reference level, so a track tagged for RG2 and one Sound-Check-encoded here
would play at matching loudness on any device that honours both.

THROUGHPUT, measured on this machine, which turned out to matter: ffmpeg's
own progress line claims ~1480x realtime for `ebur128` on a typical file
here -- but that is WITHOUT `peak=true`. True-peak needs 4x oversampling
internally, and measured head-to-head on the same file it drops throughput
to ~260x (8 real tracks, mixed mp3/flac, averaged 254x; a separate 18-file
sample gave 259x on one file in isolation). `analyse()` needs true_peak for
`clips_after`, so this module always asks ebur128 for peak -- there is no
cheaper mode that still answers the clipping question. Budget scan() time
off ~260x single-threaded, not the quoted ~1480x.

With a 6-worker thread pool the measured EFFECTIVE throughput (18 real
files, mixed formats) was ~483x, not ~6x260=1560x -- sub-linear, because a
single `ffmpeg -filter:a ebur128` process already pins ~2 CPU cores on its
own (observed via `time`: ~113-197% CPU for one process), so 6 of them
compete for cores rather than scaling cleanly. Extrapolated to the real
library (data/local/index.json: 4,048 tracks, 380.6 hours of audio) at
483x: roughly 47 minutes for a cold, uncached, 6-worker scan of everything.

CACHING. A measurement is a full decode-and-analyse pass over the audio --
it must happen exactly once per file, ever, not once per sync. The cache is
keyed by the file's path, and a hit additionally requires the file's
CURRENT size and mtime (from a fresh os.stat, never trusted from an index
that might itself be stale) to match what was recorded at measurement time
-- the same stat-before-trust gate `apply.py._tags_cached` and
`local_index.py.probe_fast` already use for exactly this reason. Only the
expensive, target-independent numbers (lufs, true_peak, backend) are
cached; gain_dB/raw/clips_after are one-line arithmetic from `lufs` and are
always recomputed for whatever `target` is asked for, so changing the
target later never needs a re-measure.

The cache lives at data/local/loudness_cache.json, one JSON object keyed by
absolute path. Writing is funnelled through a lock per cache path (so two
scan() worker threads finishing at once cannot each read-modify-write and
silently drop the other's result) and persisted via write-temp-then-
os.replace, which is atomic on the same filesystem -- a concurrent reader
(this process's own threads, or another saltpod invocation reading the same
file) only ever sees a complete JSON document, never a half-written one.
What this does NOT do is coordinate ACROSS processes while they are both
running: each process keeps its own in-memory mirror once loaded, so a
second process's writes are not seen until this one reloads. Nothing in
this codebase runs two writers against the same cache concurrently today,
so that gap is noted rather than solved.

STANDARD LIBRARY PLUS FFMPEG ONLY. ffmpeg may be absent -- every public
function checks with shutil.which and returns None (never raises) when it
is. Nothing imports this module yet; it changes no existing behaviour.
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CACHE_PATH = os.path.join(ROOT, 'data', 'local', 'loudness_cache.json')
INDEX_PATH = os.path.join(ROOT, 'data', 'local', 'index.json')
RECONCILE_PATH = os.path.join(ROOT, 'data', 'local', 'reconcile.json')

DEFAULT_TARGET = -18.0

# a fallback, never an override -- mirrors apply.py's FF_ENV and platform.py's
# _FF_ENV. An unaccepted Xcode licence makes the Command Line Tools refuse to
# run; setting DEVELOPER_DIR to them directly sidesteps it without sudo.
_FF_ENV = {**os.environ,
           'DEVELOPER_DIR': os.environ.get('DEVELOPER_DIR')
                            or '/Library/Developer/CommandLineTools'}

# ebur128's Summary block prints
#     Integrated loudness:
#       I:         -10.2 LUFS
#     True peak:
#       Peak:        0.3 dBFS
# but the SAME "I:  ... LUFS" shape also appears in every periodic progress
# line ffmpeg prints while it runs ("M: -63.8 S: -42.5  I: -10.2 LUFS ...").
# "Peak:" does not -- those lines say "TPK:"/"FTPK:" instead -- but matching
# both the same way and taking the LAST hit is what the task this was built
# from specified, and it is robust either way: the Summary is always the
# last thing ebur128 prints.
_RE_LUFS = re.compile(r'\bI:\s*(-?\d+(?:\.\d+)?)\s*LUFS')
_RE_PEAK = re.compile(r'\bPeak:\s*(-?\d+(?:\.\d+)?)\s*dBFS')


def have_ffmpeg():
    return shutil.which('ffmpeg') is not None


# ========================================================== measurement

def measure(path, timeout=120):
    """{'lufs': float, 'true_peak': float, 'backend': 'ffmpeg'}, or None.

    None means: ffmpeg is missing, the file could not be opened/decoded, it
    timed out, or ebur128's Summary could not be found in the output --
    never an exception. Measured speed: see the module docstring -- ~260x
    realtime with peak=true, not the ~1480x ebur128 claims without it.

    MUST be `-v info`, not `-v error`: ebur128 logs its own Summary (the
    only place the numbers this function wants live) at ffmpeg's INFO
    level. `-v error` runs fine and silently returns None forever -- this
    cost an hour to find once already.
    """
    if not have_ffmpeg():
        return None
    if not os.path.exists(path):
        return None
    try:
        r = subprocess.run(
            ['ffmpeg', '-v', 'info', '-i', path, '-map', '0:a:0', '-vn',
             '-filter:a', 'ebur128=peak=true', '-f', 'null', '-'],
            capture_output=True, text=True, timeout=timeout, env=_FF_ENV)
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = (r.stderr or '') + (r.stdout or '')
    lufs = _RE_LUFS.findall(out)
    peak = _RE_PEAK.findall(out)
    if not lufs or not peak:
        return None
    return {'lufs': float(lufs[-1]), 'true_peak': float(peak[-1]), 'backend': 'ffmpeg'}


# ============================================================== encoding

def soundcheck_for(lufs, target=DEFAULT_TARGET):
    """The raw u32 value for mhit+0x4C, from a measured integrated loudness.

        raw = 1000 * 10^(-gain_dB / 10)      gain_dB = target - lufs

    raw 1000 is exactly 0 dB (no change). raw > 1000 is attenuation -- every
    one of the 85 Apple-authored values on this device is in that direction
    (1252..10907, see module docstring). `lufs=None` (a failed measurement)
    returns 1000: do nothing rather than guess.

    A TRACK QUIETER THAN THE TARGET gives gain_dB > 0, i.e. raw < 1000 --
    the device would be told to turn that track UP. This function does NOT
    special-case it or floor it back to 1000: raw < 1000 is just as valid a
    u32 under the same formula, and silently flooring it would make a
    quiet track play at the SAME loudness as everything else got turned
    down to, which is not what "normalise to -18 LUFS" means. At the chosen
    -18 target this never actually happens -- 0 of the owner's 90 sampled
    tracks are quiet enough (see module docstring: -14 needed it for 24/90,
    -16 for 10/90, -18 for 0/90) -- but a different target, or a genuine
    outlier (a spoken-word intro, a deliberately quiet mix), could still
    produce one. The thing that actually guards against amplification
    clipping a quiet track is `analyse()`'s `clips_after`, not a floor here
    -- callers that write Sound Check should check that flag, not assume
    raw >= 1000 always.

    THE LOWER CLAMP IS NOT THEORETICAL. A near-silent file (long room tone,
    a spoken intermission) can measure below -70 LUFS; at a -18 target
    that is gain_dB = -18 - (-70) = +52 dB of (nominal) amplification, raw =
    1000 * 10**(-5.2) ~= 0.0063, which rounds to 0 -- and 0 is already taken:
    it is what this device's own 85-track sample uses for "no Sound Check
    value" (research/ITUNES-PARITY.md), not for "0 dB" (that is raw 1000).
    Floored to 1 so a real measurement, however quiet, is never written as
    the same raw value as no measurement at all.

    THE UPPER CLAMP IS DEFENSIVE, NOT REALISTIC. Reaching raw's u32 ceiling
    needs gain_dB beyond -66 dB -- lufs some 66+ dB louder than the target,
    i.e. above roughly +48 LUFS. Real integrated loudness does not get
    there (the owner's loudest of 90 measured tracks was -5.2 LUFS; even a
    sustained full-scale tone tops out near 0 LUFS). The only realistic way
    to hit this clamp is a corrupt or out-of-range `lufs` argument -- a
    measurement bug, or a caller passing the wrong unit -- and clamping
    instead of raising keeps that bug from corrupting the field with a
    value that wraps or does not fit, while still being visibly wrong
    (2**32 - 1 is not a plausible Sound Check value either).
    """
    if lufs is None:
        return 1000
    gain_db = target - lufs
    raw = 1000.0 * (10.0 ** (-gain_db / 10.0))
    return max(1, min(int(round(raw)), 2**32 - 1))


def _decode_gain_db(raw):
    """Inverse of soundcheck_for's formula: the dB a raw value encodes."""
    return -10.0 * math.log10(raw / 1000.0)


# =============================================================== analysis

def analyse(path, target=DEFAULT_TARGET):
    """{'lufs','true_peak','gain_db','raw','clips_after'}, or None if
    `measure` could not (see its own docstring for why).

    clips_after is True when true_peak + gain_db would land above -1.0
    dBFS -- the standard streaming-mastering headroom line, and the one 5
    of the owner's 90 sampled tracks cross at a -18 target even though none
    of them needed amplifying to get there (loud AND already peaking is
    the loudness-war signature: gain_dB is negative but true_peak was
    already close to 0 dBFS, so attenuating by less than the peak's excess
    still leaves it over). This module only reports the risk; nothing here
    limits or re-encodes audio.
    """
    m = measure(path)
    if m is None:
        return None
    gain_db = target - m['lufs']
    raw = soundcheck_for(m['lufs'], target)
    clips_after = (m['true_peak'] + gain_db) > -1.0
    return {'lufs': m['lufs'], 'true_peak': m['true_peak'], 'gain_db': gain_db,
            'raw': raw, 'clips_after': clips_after}


# ==================================================================== cache
#
# One in-memory dict per cache_path, loaded from disk once and kept for the
# life of the process; a lock per cache_path serialises every write (both
# the in-memory mutation and the file it is persisted to). Reads of the
# in-memory dict happen under the same lock -- it is a plain dict lookup,
# cheap enough that holding the lock for it costs nothing, and it is what
# makes "measure once, never twice" true even when several scan() workers
# ask for the same cache_path's lock at once.

class _Cache:
    __slots__ = ('data', 'lock')

    def __init__(self, data):
        self.data = data
        self.lock = threading.Lock()


_registry = {}
_registry_lock = threading.Lock()


def _load_cache_file(cache_path):
    try:
        with open(cache_path) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}          # absent, empty, or corrupt -- start clean rather than raise


def _cache_obj(cache_path):
    with _registry_lock:
        obj = _registry.get(cache_path)
        if obj is None:
            obj = _Cache(_load_cache_file(cache_path))
            _registry[cache_path] = obj
        return obj


def _persist(cache_path, data):
    """Atomic write: a reader of cache_path never sees a partial file."""
    d = os.path.dirname(cache_path) or '.'
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.loudness-cache-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as fh:
            json.dump(data, fh)
        os.replace(tmp, cache_path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def analyse_cached(path, target=DEFAULT_TARGET, cache_path=None):
    """Like `analyse`, but a file already measured (same path, size AND
    mtime as last time) is never re-measured -- it is the entry point
    everything else in this module that touches many files should use.

    Adds one key beyond `analyse`'s contract: 'cached' (bool), true when
    this call was served from the cache rather than running ffmpeg --
    useful for proving the cache works (see selftest()) and harmless for
    anything that ignores it.
    """
    cp = cache_path or DEFAULT_CACHE_PATH
    try:
        st = os.stat(path)
    except OSError:
        return None
    size, mtime = st.st_size, st.st_mtime

    obj = _cache_obj(cp)
    with obj.lock:
        hit = obj.data.get(path)
        fresh = bool(hit) and hit.get('size') == size and hit.get('mtime') == mtime
        if fresh:
            m = {'lufs': hit['lufs'], 'true_peak': hit['true_peak'], 'backend': hit['backend']}

    if not fresh:
        m = measure(path)          # the expensive part -- deliberately outside the lock
        if m is None:
            return None
        with obj.lock:
            obj.data[path] = {'size': size, 'mtime': mtime,
                               'lufs': m['lufs'], 'true_peak': m['true_peak'],
                               'backend': m['backend']}
            _persist(cp, obj.data)

    gain_db = target - m['lufs']
    raw = soundcheck_for(m['lufs'], target)
    clips_after = (m['true_peak'] + gain_db) > -1.0
    return {'lufs': m['lufs'], 'true_peak': m['true_peak'], 'gain_db': gain_db,
            'raw': raw, 'clips_after': clips_after, 'cached': fresh}


# =================================================================== import


def import_scan(scan_path, cache_path=None):
    """Fold a completed scan file into the cache `analyse_cached` reads.

    THE TWO STORES WERE NOT THE SAME STORE. The 4,047-file scan of 2 October
    was written by a one-off script to `data/local/loudness_scan.json`, in
    its own shape -- `{'at': when, 'tracks': {path: {...}}}` with `lra` and
    `duration_sec` that this module does not keep. Nothing here ever looked
    at that file, so `analyse_cached` would have re-measured every one of
    those files: nineteen minutes of ffmpeg, already paid for, invisible.

    The scan carries `size` and `mtime`, which are exactly the two keys the
    cache tests for freshness, so the fold is lossless in the direction that
    matters -- an imported entry is indistinguishable from one this module
    measured itself, and goes stale on the same evidence.

    A scan row with no `lufs` is a file ffmpeg could not read. Those are
    skipped rather than cached: caching a failure would mean never trying it
    again, and the reason is usually fixable (three WAVs on this drive).

    Returns {'read', 'imported', 'already', 'skipped'}.
    """
    cp = cache_path or DEFAULT_CACHE_PATH
    with open(scan_path) as fh:
        doc = json.load(fh)
    rows = doc.get('tracks', doc) if isinstance(doc, dict) else {}

    obj = _cache_obj(cp)
    read = imported = already = skipped = 0
    with obj.lock:
        for path, r in rows.items():
            read += 1
            if not isinstance(r, dict) or r.get('lufs') is None:
                skipped += 1
                continue
            if r.get('size') is None or r.get('mtime') is None:
                skipped += 1
                continue
            hit = obj.data.get(path)
            if hit and hit.get('size') == r['size'] and hit.get('mtime') == r['mtime']:
                already += 1
                continue
            obj.data[path] = {'size': r['size'], 'mtime': r['mtime'],
                              'lufs': r['lufs'], 'true_peak': r.get('true_peak'),
                              'backend': r.get('backend') or 'import'}
            imported += 1
        _persist(cp, obj.data)
    return {'read': read, 'imported': imported, 'already': already,
            'skipped': skipped}


def cached_rows(cache_path=None):
    """Every measurement the cache holds, {path: {...}} -- without stat()ing
    a single file.

    Deliberately NOT `analyse_cached` in a loop: that one checks the file on
    disk is still the file it measured, which is right before writing a value
    and wrong for a report. The drive this library lives on is usually
    unplugged, and a report that needs the drive to say what was already
    measured is a report that cannot be read.
    """
    return dict(_cache_obj(cache_path or DEFAULT_CACHE_PATH).data)


# ===================================================================== scan

def scan(paths, target=DEFAULT_TARGET, workers=6, progress=None, cache_path=None):
    """{path: analyse_cached(path, target) result} for many files at once.

    A thread pool, not a process pool: `measure` spends essentially all of
    its time inside `subprocess.run`, which releases the GIL while
    waiting, so threads parallelise the actual ffmpeg work without the
    pickling overhead of shipping paths to worker processes. Measured
    sub-linear with 6 workers (module docstring: ~483x effective against
    ~260x single-threaded) because one ffmpeg process already uses ~2
    cores on its own.

    `progress(done, total, path)`, if given, is called after each file
    completes (success or not) -- from whichever worker thread finished
    it, so keep it cheap and thread-safe if it does anything beyond print.
    """
    paths = list(paths)
    total = len(paths)
    results = {}
    if total == 0:
        return results

    if workers <= 1:
        for i, p in enumerate(paths, 1):
            results[p] = analyse_cached(p, target, cache_path=cache_path)
            if progress:
                progress(i, total, p)
        return results

    done = 0
    done_lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(analyse_cached, p, target, cache_path): p for p in paths}
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                results[p] = fut.result()
            except Exception:
                results[p] = None
            if progress:
                with done_lock:
                    done += 1
                    n = done
                progress(n, total, p)
    return results


# ================================================================= selftest
#
# Everything below is verification against real files, never against
# data/local/loudness_cache.json -- every cached call in here passes an
# explicit cache_path under tempfile.mkdtemp().

def _library_sample(n=5):
    """n real (path, size) pairs from data/local/index.json, or []."""
    try:
        d = json.load(open(INDEX_PATH))
    except (OSError, ValueError):
        return []
    out = []
    for e in d.get('tracks', []):
        p = e.get('path')
        if p and os.path.exists(p):
            out.append((p, e.get('size'), e.get('ext')))
        if len(out) >= n:
            break
    return out


def _apple_soundcheck_samples(mount, limit=5):
    """[(title, artist, location, raw)] for device tracks that carry a
    nonzero Sound Check value, newest-offset-first. itunesdb.py does not
    parse offset 0x4C (research/ITUNES-PARITY.md calls it a gap), so this
    walks the same mhit chunks itunesdb._tracks does, a second time, for
    that one field -- selftest-only, nothing in the public API depends on
    reading someone else's module internals.
    """
    dbp = os.path.join(mount, 'iPod_Control', 'iTunes', 'iTunesDB')
    if not os.path.exists(dbp):
        return []
    from . import itunesdb as I
    b = open(dbp, 'rb').read()
    if b[:4] != b'mhbd':
        return []
    db = I.read(dbp)

    _, hl, _ = I._chunk(b, 0)
    o = hl
    offs = []
    while o < len(b) - 12:
        magic, shl, stl = I._chunk(b, o)
        if magic != b'mhsd':
            break
        inner = o + shl
        im, ihl, _ = I._chunk(b, inner)
        if im == b'mhlt':
            n = I._u32(b, inner + 8)
            p = inner + ihl
            for _ in range(n):
                m2, hl2, tl2 = I._chunk(b, p)
                if m2 != b'mhit':
                    break
                offs.append(p)
                p += tl2
        o += stl
    if len(offs) != len(db['tracks']):
        return []          # format assumption broken -- say nothing rather than guess

    out = []
    for tr, off in zip(db['tracks'], offs):
        raw = I._u32(b, off + 0x4C)
        if raw and tr.get('location'):
            out.append((tr.get('title'), tr.get('artist'), tr['location'], raw))
        if len(out) >= limit:
            break
    return out


def _origin_for_location(location):
    """The T7 source file for a device-relative location, via reconcile.json
    (data/local/reconcile.json's 'matched' list) if one exists. None if the
    file is absent, not yet reconciled, or reconcile.json itself is absent.
    """
    try:
        d = json.load(open(RECONCILE_PATH))
    except (OSError, ValueError):
        return None
    for e in d.get('matched', []):
        if e.get('ipod') == location:
            origin = e.get('origin')
            return origin if origin and os.path.exists(origin) else None
    return None


def _selftest_measure_real_files():
    print('--- measure() on real library files ---')
    sample = _library_sample(5)
    if not sample:
        print('  NOT VERIFIED: no readable data/local/index.json tracks found')
        return True
    ok = True
    for path, size, ext in sample:
        import time
        t0 = time.time()
        m = measure(path)
        dt = time.time() - t0
        if m is None:
            print('  FAILED to measure %s' % path)
            ok = False
            continue
        print('  %5.2fs  %7.2f LUFS  %6.2f dBFS peak  (%s, %s)'
              % (dt, m['lufs'], m['true_peak'], ext, m['backend']))
    return ok


def _selftest_cache_hit():
    import time
    print()
    print('--- cache: same file twice ---')
    sample = _library_sample(1)
    if not sample:
        print('  NOT VERIFIED: no library file to test against')
        return True
    path = sample[0][0]
    tmpdir = tempfile.mkdtemp(prefix='saltpod-loudness-cache-')
    cache_path = os.path.join(tmpdir, 'cache.json')
    try:
        t0 = time.time()
        r1 = analyse_cached(path, cache_path=cache_path)
        dt1 = time.time() - t0
        t0 = time.time()
        r2 = analyse_cached(path, cache_path=cache_path)
        dt2 = time.time() - t0
        print('  first call:  %.3fs  cached=%s' % (dt1, r1 and r1['cached']))
        print('  second call: %.3fs  cached=%s' % (dt2, r2 and r2['cached']))
        if not r1 or not r2:
            print('  FAILED: measurement returned None')
            return False
        same = (r1['lufs'], r1['true_peak'], r1['raw']) == (r2['lufs'], r2['true_peak'], r2['raw'])
        fast = r2['cached'] and (dt2 < dt1 / 3 or dt2 < 0.02)
        if same and fast:
            print('  ok: identical result, second call near-instant and cache-hit')
            return True
        print('  FAILED: same=%s fast=%s' % (same, fast))
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _selftest_cache_invalidates():
    print()
    print('--- cache: invalidates when the file changes ---')
    if not have_ffmpeg():
        print('  NOT VERIFIED: no ffmpeg to re-encode a probe file')
        return True
    sample = _library_sample(1)
    if not sample:
        print('  NOT VERIFIED: no library file to copy')
        return True
    src = sample[0][0]
    tmpdir = tempfile.mkdtemp(prefix='saltpod-loudness-invalidate-')
    cache_path = os.path.join(tmpdir, 'cache.json')
    probe = os.path.join(tmpdir, 'probe' + os.path.splitext(src)[1])
    try:
        shutil.copy2(src, probe)
        r1 = analyse_cached(probe, cache_path=cache_path)
        r1_again = analyse_cached(probe, cache_path=cache_path)
        if not r1 or not r1_again or not r1_again['cached']:
            print('  FAILED: did not even get a clean cache hit before altering the file')
            return False

        # Alter it: re-encode the first 5 seconds over the same path. Changes
        # size, mtime, AND the actual audio -- a 5s clip of a full track
        # almost never shares its integrated loudness, so a different lufs
        # on the next call is itself evidence of a real re-measure, not just
        # a cache-bypass that happens to replay the same numbers.
        #
        # Output as .wav explicitly (-f wav, and the temp file is NAMED
        # .wav): ffmpeg picks its muxer from the output extension, and
        # "probe.mp3.trim" has none it recognises. ffmpeg's INPUT side
        # sniffs content rather than trusting the extension, so the later
        # os.replace() onto `probe` (whatever its original extension) is
        # still read back correctly by measure().
        trimmed = os.path.join(tmpdir, 'trimmed.wav')
        r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', probe, '-t', '5',
                            '-map', '0:a:0', '-vn', '-c:a', 'pcm_s16le', '-f', 'wav', trimmed],
                           capture_output=True, text=True, timeout=30, env=_FF_ENV)
        if r.returncode != 0 or not os.path.exists(trimmed):
            print('  NOT VERIFIED: could not re-encode the probe file (%s)'
                  % (r.stderr or '').strip()[:200])
            return True
        os.replace(trimmed, probe)

        r2 = analyse_cached(probe, cache_path=cache_path)
        if not r2:
            print('  FAILED: re-measurement after the change returned None')
            return False
        print('  before: %.2f LUFS (cached=%s)   after: %.2f LUFS (cached=%s)'
              % (r1_again['lufs'], r1_again['cached'], r2['lufs'], r2['cached']))
        if r2['cached']:
            print('  FAILED: still served from cache after the file changed')
            return False
        print('  ok: changed file was re-measured, not served stale')
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _selftest_roundtrip():
    print()
    print('--- soundcheck_for() / decode round-trip ---')
    # Real integrated-loudness values from the module docstring's own
    # measurements (the owner's library median/min/max, and Apple's
    # implied-target median/range) plus 0 dB -- all within the range the u32
    # field represents without clamping, so decode(encode(x)) should recover
    # x to within integer-rounding noise. Clamped values are tested
    # separately below, because by construction they do NOT round-trip.
    samples = [-11.0, -17.4, -5.2, -15.18, -17.69, -12.28, -18.0]
    target = DEFAULT_TARGET
    worst = 0.0
    for lufs in samples:
        raw = soundcheck_for(lufs, target)
        decoded_gain = _decode_gain_db(raw)
        true_gain = target - lufs
        err = abs(decoded_gain - true_gain)
        worst = max(worst, err)
        print('  lufs=%7.2f  gain=%7.2f dB  raw=%10d  decoded=%7.2f dB  err=%.4f dB'
              % (lufs, true_gain, raw, decoded_gain, err))
    ok = worst < 0.01
    print('  worst round-trip error: %.4f dB (%s)' % (worst, 'ok' if ok else 'FAILED'))
    return ok


def _selftest_clamp():
    print()
    print('--- soundcheck_for() clamp: never 0, never past a u32 ---')
    target = DEFAULT_TARGET
    # Floor: realistic near-silent audio (-90 LUFS against a -18 target asks
    # for +72 dB of nominal amplification; raw would round to 0, which is
    # reserved for "no Sound Check value").
    quiet_raw = soundcheck_for(-90.0, target)
    # Ceiling: not reachable by real audio (see soundcheck_for's docstring)
    # -- this stands in for a corrupt/out-of-range measurement.
    loud_raw = soundcheck_for(50.0, target)
    print('  near-silent (-90 LUFS):  raw=%d  (floored, not 0)' % quiet_raw)
    print('  corrupt (+50 LUFS):      raw=%d  (ceilinged, fits a u32)' % loud_raw)
    ok = (quiet_raw == 1) and (0 < loud_raw <= 2**32 - 1) and loud_raw == 2**32 - 1
    print('  %s' % ('ok' if ok else 'FAILED'))
    return ok


def _selftest_apple_cross_check():
    print()
    print('--- cross-check against Apple: implied target vs our -18 LUFS ---')
    try:
        from . import config
        mount = config.load()['mount']
    except SystemExit:
        print('  NOT VERIFIED: no data/device.json configured')
        return True
    samples = _apple_soundcheck_samples(mount, limit=5)
    if not samples:
        print('  NOT VERIFIED: iPod not mounted, or no Sound Check values found on it')
        return True

    found = 0
    for title, artist, location, raw in samples:
        origin = _origin_for_location(location)
        if not origin:
            continue
        m = measure(origin)
        if not m:
            continue
        found += 1
        apple_gain = _decode_gain_db(raw)
        apple_target = m['lufs'] + apple_gain
        our_raw = soundcheck_for(m['lufs'], DEFAULT_TARGET)
        diff = apple_target - DEFAULT_TARGET
        print('  %s - %s' % (artist, title))
        print('    measured source:    %.2f LUFS' % m['lufs'])
        print('    Apple wrote:        raw %5d -> %.2f dB -> implied target %.2f LUFS'
              % (raw, apple_gain, apple_target))
        print('    we would write:     raw %5d -> target %.1f LUFS  (differs by %+.2f dB)'
              % (our_raw, DEFAULT_TARGET, diff))
    if found == 0:
        print('  NOT VERIFIED: none of the sampled device tracks matched a T7 original '
              '(check data/local/reconcile.json)')
        return True
    print('  (expected roughly a 3 dB gap, per the module docstring -- shown above, not asserted)')
    return True


def selftest():
    """Everything this module claims, checked against real files, never
    touching data/local/loudness_cache.json. Returns bool, matching
    platform.selftest()'s convention."""
    print('ffmpeg: %s' % ('yes, ' + shutil.which('ffmpeg') if have_ffmpeg() else 'ABSENT'))
    print()

    ok = _selftest_roundtrip()
    ok = _selftest_clamp() and ok
    if have_ffmpeg():
        ok = _selftest_measure_real_files() and ok
        ok = _selftest_cache_hit() and ok
        ok = _selftest_cache_invalidates() and ok
        ok = _selftest_apple_cross_check() and ok
    else:
        print()
        print('--- skipping every ffmpeg-dependent check: ffmpeg is ABSENT ---')

    print()
    print('selftest %s' % ('PASSED' if ok else 'FAILED'))
    return ok


def main(argv=None):
    a = argv if argv is not None else sys.argv[1:]
    if not a or a[0] != 'selftest':
        print('usage: python3 -m saltpod.loudness selftest')
        return 2
    return 0 if selftest() else 1


if __name__ == '__main__':
    sys.exit(main())
