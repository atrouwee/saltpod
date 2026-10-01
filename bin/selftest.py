#!/usr/bin/env python3
"""Run every core function against real data and say what broke.

WHY THIS EXISTS. Two things happened within an hour of each other. A
Spotlight fast path for the drive index looked 8x faster and correct, and a
differential run against ffprobe showed it losing the artist on 103 files
of 300. And chasing that turned up an AIFF writer that had been wrong for
two days -- `read_id3` looking at byte 0 of a FORM file -- which had never
fired because nothing had asked it to yet.

Neither was going to be found by reading. Both were found by running the
old path and the new one over the same input and diffing.

    python3 bin/selftest.py             # everything it can do without a device
    python3 bin/selftest.py --device    # include the iPod, read-only
    python3 bin/selftest.py --quick     # skip the slow file passes

NOTHING HERE WRITES TO YOUR LIBRARY OR YOUR IPOD. Tag tests run on copies
in a temp directory; device tests read and never write.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

PASS, FAIL, SKIP = [], [], []
_t0 = time.time()


def check(name, fn, slow=False):
    """Run one check. A check returns a detail string, raises, or returns None to skip."""
    if slow and '--quick' in sys.argv:
        SKIP.append((name, 'quick'))
        print('  ..  %-46s skipped (--quick)' % name)
        return
    t = time.perf_counter()
    try:
        detail = fn()
    except Exception as e:
        FAIL.append((name, '%s: %s' % (type(e).__name__, e)))
        print('  !!  %-46s %s: %s' % (name, type(e).__name__, str(e)[:60]))
        return
    ms = (time.perf_counter() - t) * 1000
    if detail is None:
        SKIP.append((name, 'not applicable here'))
        print('  ..  %-46s n/a' % name)
    else:
        PASS.append((name, detail))
        print('  ok  %-46s %-34s %6.0f ms' % (name, str(detail)[:34], ms))


def section(title):
    print('\n%s' % title)


# ------------------------------------------------------------------ format
def t_itunesdb_roundtrip():
    """The promise the whole tool rests on: parse then serialise, byte for byte."""
    from saltpod import itunesdb_write as W, config
    src = _a_database()
    if not src:
        return None
    raw = open(src, 'rb').read()
    out = W.serialise(W.parse(raw), _guid())
    assert out == raw, 'round trip differs: %d in, %d out' % (len(raw), len(out))
    return '%d bytes identical' % len(raw)


def t_hash58():
    from saltpod import hash58
    src = _a_database()
    if not src:
        return None
    raw = open(src, 'rb').read()
    assert hash58.verify(raw, _guid()), 'hash58 does not verify'
    return 'verifies'


def t_artworkdb_roundtrip():
    """Surveyed as cheap because the same tree model handles it. Hold that true."""
    from saltpod import itunesdb_write as W
    p = '/Volumes/IPOD/iPod_Control/Artwork/ArtworkDB'
    if not os.path.exists(p):
        return None
    raw = open(p, 'rb').read()
    saved_lists = dict(W.LISTS)
    W.LISTS.update({b'mhli': b'mhii', b'mhlf': b'mhif', b'mhla': b'mhaf'})
    W.ITEMS_WITH_MHODS.update({b'mhii', b'mhni'})
    try:
        hl, tl = W.u32(raw, 4), W.u32(raw, 8)
        root = W.Node(b'mhfd', raw[:hl])
        o = hl
        while o < tl:
            shl, stl = W.u32(raw, o + 4), W.u32(raw, o + 8)
            sd = W.Node(b'mhsd', raw[o:o + shl])
            sd.children.append(W._parse_list(raw, o + shl, o + stl))
            root.children.append(sd)
            o += stl
        out = W._ser(root)
    finally:
        W.LISTS.clear(); W.LISTS.update(saved_lists)
    assert out == raw, 'ArtworkDB round trip differs'
    return '%d bytes identical' % len(raw)


# -------------------------------------------------------------------- tags
def t_tag_roundtrip():
    """Write tags three times to a COPY and prove the audio never moved."""
    from saltpod import tags as T
    results = []
    tmp = tempfile.mkdtemp(prefix='saltpod-selftest-')
    try:
        for ext in ('.wav', '.mp3', '.aif', '.aiff', '.flac', '.m4a'):
            src = _a_file(ext, writable=True)
            if not src:
                continue
            work = os.path.join(tmp, 'x' + ext)
            shutil.copy2(src, work)
            probe = T.audio_probe(work)
            tags = {'title': 'Selftest', 'artist': 'Saltpod', 'album': 'Round Trip'}
            ip = T.write(work, tags)
            T.verify(work, probe, in_place=ip)
            size1 = os.path.getsize(work)
            for _ in range(2):
                T.write(work, tags)
                T.verify(work, probe, in_place=True)
            assert os.path.getsize(work) == size1, '%s grows on rewrite' % ext
            got = T.read(work)
            for k, v in tags.items():
                assert got.get(k) == v, '%s did not round-trip %s' % (ext, k)
            results.append(ext.lstrip('.'))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return ('stable: ' + ' '.join(results)) if results else None


def t_tag_preserves_art():
    """The reason unmanaged frames are carried through rather than rebuilt."""
    from saltpod import tags as T
    src = _a_file('.mp3', writable=True, with_art=True)
    if not src:
        return None
    tmp = tempfile.mkdtemp(prefix='saltpod-selftest-')
    try:
        work = os.path.join(tmp, 'art.mp3')
        shutil.copy2(src, work)
        before = _apic_bytes(work)
        if not before:
            return None
        T.write(work, {'title': 'Selftest'})
        after = _apic_bytes(work)
        assert after == before, 'artwork changed: %d -> %d bytes' % (before, after)
        return '%d bytes of APIC kept' % before
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_tag_refusals():
    """It must still say no to what it cannot do safely.

    This check used to assert the opposite -- that aif, aiff, m4a and flac
    were all refused -- and it was right to, because they were. What it
    guards now is the narrower list that is genuinely unsafe, so the next
    container cannot arrive by quietly shortening it.
    """
    from saltpod import tags as T
    bad = []
    for ext in ('.ogg', '.wma', '.opus', '.aac', ''):
        if ext in T._WRITERS:
            bad.append(ext or '(no extension)')
    assert not bad, 'claims a writer for %s' % bad
    # a WAV carrying an id3 chunk has its artwork in a span we cannot
    # rewrite; an ID3v2.2 mp3 has three-character frame ids and no
    # converter yet. Both must still come back unsupported.
    declined = 0
    for ext in ('.wav', '.mp3'):
        for path in _files(ext)[:300]:
            if not T.supported(path):
                declined += 1
    return 'no writer for ogg wma opus aac; %d files declined by inspection' % declined


def t_tag_matches_ffprobe():
    """THE DIFFERENTIAL. Our readers against the one already trusted.

    A round-trip only proves we read back what we wrote, so it cannot catch
    a WRONG MAPPING -- reading an m4a 's artist atom as album_artist would
    round-trip perfectly and be wrong on every file in the library. This is
    the check that found TDRL: 428 of 482 .aif files read as having no year,
    because Beatport writes the release date in a frame nothing here knew.
    """
    import json as _json
    import subprocess as _sp
    from saltpod import tags as T
    keys = {'title': ('title',), 'artist': ('artist',), 'album': ('album',),
            'album_artist': ('album_artist', 'albumartist'),
            'genre': ('genre',), 'year': ('date', 'tyer'), 'track': ('track',)}
    checked = 0
    for ext in ('.mp3', '.aif', '.aiff', '.flac', '.m4a'):
        for path in _files(ext)[:6]:
            r = _sp.run(['ffprobe', '-v', 'quiet', '-print_format', 'json',
                         '-show_format', path], capture_output=True, text=True)
            try:
                ff = (_json.loads(r.stdout or '{}').get('format', {})
                      .get('tags', {}) or {})
            except ValueError:
                continue
            ff = {k.lower(): v for k, v in ff.items()}
            ours = T.read(path)
            checked += 1
            for field, ks in keys.items():
                theirs = next((ff[k] for k in ks if k in ff), '')
                a, b = (ours.get(field) or '').strip(), (theirs or '').strip()
                if field == 'genre':
                    a, b = T._genre_norm(a), T._genre_norm(b)
                if field == 'year':
                    a, b = T._year_norm(a), T._year_norm(b)
                if field == 'track':
                    a, b = a.split('/')[0], b.split('/')[0]
                assert a == b, ('%s %s: ours %r, ffprobe %r'
                                % (os.path.basename(path)[:40], field, a, b))
    return '%d files agree with ffprobe on all seven fields' % checked


def t_genre_numbers():
    from saltpod import tags as T
    for raw, want in (('(5)Funk', 'Funk'), ('(5)', 'Funk'), ('Funk', 'Funk'), ('(255)', '(255)')):
        got = T._genre_norm(raw)
        assert got == want, '%r -> %r, wanted %r' % (raw, got, want)
    return 'ID3v1 numbers resolved'


# -------------------------------------------------------------------- core
def t_drift_resolution():
    """The last-write-wins table, including the case that got it wrong once."""
    from saltpod.apply import resolve_drift as R
    F = lambda t: {'title': t, 'artist': 'A', 'album': 'B'}
    base = F('old')
    anc = {'tags': base, 'mtime': 100.0, 'edited_at': 0}
    cases = [
        ('only the file moved', F('new'), base, anc, 200.0, 'file'),
        ('only the device moved', base, F('dev'), anc, 100.0, 'device'),
        ('file touched, tags unchanged', base, F('dev'), anc, 200.0, 'device'),
        ('both moved, file later', F('new'), F('dev'),
         {'tags': base, 'mtime': 100.0, 'edited_at': 150}, 200.0, 'file'),
        ('both moved, device later', F('new'), F('dev'),
         {'tags': base, 'mtime': 100.0, 'edited_at': 300}, 200.0, 'device'),
        ('no ancestor', F('new'), F('dev'), {}, 200.0, 'file'),
    ]
    for label, now, was, a, mt, want in cases:
        got, _ = R(now, was, a, mt)
        assert got == want, '%s -> %s, wanted %s' % (label, got, want)
    return '%d cases' % len(cases)


def t_migrate_idempotent():
    from saltpod import state as S
    st = {'tracks': {
        'a': {'tier': 'shortlisted', 'collections': [], 'vinyl': False},
        'b': {'tier': 'maybe', 'collections': ['x'], 'vinyl': False},
        'c': {'tier': 'nonsense', 'collections': [], 'vinyl': False},
    }}
    once = json.dumps(S.migrate(json.loads(json.dumps(st))), sort_keys=True)
    twice = json.dumps(S.migrate(S.migrate(json.loads(json.dumps(st)))), sort_keys=True)
    assert once == twice, 'migrate is not idempotent'
    got = json.loads(once)['tracks']
    assert got['a']['tier'] == 'sync' and got['b']['tier'] == 'sync'
    assert got['c']['tier'] == 'undecided'
    return 'idempotent, old names folded'


def t_exclusions():
    from saltpod import apply as A
    if not _device():
        return None
    A._cfg()
    p = A.plan(A.MOUNT)
    base = len(p['removes'])
    if base:
        k = p['removes'][0][0]
        q = A.drop_excluded(A.plan(A.MOUNT), {'tracks': [k]})
        assert len(q['removes']) == base - 1, 'exclusion did not drop the row'
    q = A.drop_excluded(A.plan(A.MOUNT), {'tracks': ['no-such-key']})
    assert len(q['removes']) == base, 'an unknown key changed the plan'
    return 'drops by identity, ignores unknowns'


def t_plan_cached():
    """The mtime gate: a second plan must be much cheaper than the first."""
    from saltpod import apply as A
    if not _device():
        return None
    A._cfg()
    A.plan(A.MOUNT)
    t = time.perf_counter(); A.plan(A.MOUNT); warm = (time.perf_counter() - t) * 1000
    assert warm < 600, 'warm plan took %.0f ms -- the tag cache is not working' % warm
    return 'warm plan %.0f ms' % warm


# ------------------------------------------------------------------ layers
def t_layer_census():
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'bin', 'layer_census.py'), '--strict'],
                       capture_output=True, text=True)
    assert r.returncode == 0, 'front end is over budget:\n' + r.stdout[-400:]
    return 'front end within budget'


def t_token_census():
    """No literal radii, tracking, sizes or whites outside :root."""
    import re
    css = open(os.path.join(ROOT, 'src', 'saltpod', 'curate.html')).read()
    css = css.split('<style>')[1].split('</style>')[0]
    body = css.split('}', 1)[1]
    bad = {}
    for label, pat in (('font size', r'font(?:-size)?:\s*(?:[^;]*?\s)?([\d.]+px)'),
                       ('radius', r'border-radius:\s*([\d.]+px)'),
                       ('tracking', r'letter-spacing:\s*([\d.]+em)'),
                       ('white', r'(?<![\w-])#fff(?![\w\d])|rgba\(255,\s*255,\s*255')):
        hits = sorted(set(re.findall(pat, body)))
        if hits:
            bad[label] = hits
    assert not bad, 'literals outside :root: %s' % bad
    return 'no literals outside :root'


def t_js_parses():
    import re
    s = open(os.path.join(ROOT, 'src', 'saltpod', 'curate.html')).read()
    js = re.findall(r'<script>(.*?)</script>', s, re.S)[-1]
    tmp = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False)
    tmp.write(js); tmp.close()
    try:
        r = subprocess.run(['node', '--check', tmp.name], capture_output=True, text=True)
        if r.returncode != 0 and 'node' in (r.stderr or '') and 'not found' in (r.stderr or ''):
            return None
        assert r.returncode == 0, r.stderr[-300:]
    except FileNotFoundError:
        return None
    finally:
        os.unlink(tmp.name)
    return '%d lines parse' % js.count('\n')


def t_one_implementation():
    """Every operation reachable from BOTH the page and the terminal.

    A SECOND CALLER IS THE PROOF AN ENDPOINT IS A BOUNDARY. Five operations
    had no verb and they were the five newest, which is how the gap always
    opens: the page needs something, the endpoint gets written, and the
    terminal is what nobody remembers. The native app would have been the
    first client to find out.
    """
    import re as _re
    from saltpod import curate as C
    cli = open(os.path.join(ROOT, 'src', 'saltpod', 'cli.py')).read()
    verbs = set(_re.findall(r'sub\.add_parser\("([a-z_]+)"', cli))
    ops = {k.rsplit('/', 1)[-1] for k in C.OPS}
    missing = sorted(ops - verbs)
    assert not missing, 'operations the terminal cannot reach: %s' % missing
    return '%d operations, each with a verb' % len(ops)


def t_published_tree_imports():
    """Every module the public manifest ships must import FROM that manifest.

    THE PUBLIC REPO DID NOT IMPORT FOR WEEKS. `tags.py` was never added to
    the deny-by-default manifest, so `apply.py` and `curate.py` shipped
    importing a module that was not there -- and nothing noticed, because
    the lab copy imports perfectly. A deny-by-default manifest is the right
    default; this is its one failure mode, and it needs a test rather than a
    habit.

    Reads the manifest and checks that every `from . import X` in a shipped
    module names a module that also ships. Does not need the export to have
    been run.
    """
    import re as _re
    src = open(os.path.join(ROOT, 'scripts', 'publish_public.py')).read()
    block = src[src.index('MANIFEST = ['):src.index(']', src.index('MANIFEST = ['))]
    shipped = set(_re.findall(r"'(src/saltpod/[a-z_]+)\.py'", block))
    names = {p.rsplit('/', 1)[-1] for p in shipped}
    missing = {}
    for rel in sorted(shipped):
        body = open(os.path.join(ROOT, rel + '.py')).read()
        for mod in set(_re.findall(r'from \.\s+import\s+([a-z_, ]+)', body)):
            for one in mod.split(','):
                one = one.split(' as ')[0].strip()
                if one and one not in names and os.path.exists(
                        os.path.join(ROOT, 'src', 'saltpod', one + '.py')):
                    missing.setdefault(one, []).append(rel.rsplit('/', 1)[-1])
    assert not missing, ('modules imported by shipped code but not in the manifest: '
                         + ', '.join('%s (needed by %s)' % (k, ' '.join(v))
                                     for k, v in missing.items()))
    return '%d modules ship, every import resolves' % len(names)


def t_platform():
    """The adapters, and the differential that keeps them honest.

    `platform.selftest()` converts a real file with BOTH backends and asserts
    the audio matches before afconvert is allowed to stay the default. It
    found that afconvert defaults to 32-BIT ALAC -- 46.3 MB where ffmpeg made
    19.2 MB of identical-sounding audio. A differential that compared only
    the audio would have passed that, which is the lesson worth keeping.
    """
    from saltpod import platform as P
    import io as _io
    import contextlib as _ctx
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        ok = P.selftest()
    assert ok, 'platform selftest failed:\n' + buf.getvalue()[-900:]
    b = P.caps()['backends']
    return ' '.join('%s=%s' % (k, v) for k, v in b.items())


def t_observe():
    """The event log, including the things that are easy to get wrong:
    two threads never interleave a line, an exception inside a span is logged
    AND re-raised, and the device GUID is redacted because a log is a file
    people paste."""
    from saltpod import observe as O
    import io as _io
    import contextlib as _ctx
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        ok = O.selftest()
    assert ok, 'observe selftest failed:\n' + buf.getvalue()[-900:]
    return 'events, spans, rotation, threads, redaction'


def t_imports():
    mods = ['apply', 'state', 'tags', 'itunesdb', 'itunesdb_write', 'ipod_edit',
            'hash58', 'local_index', 'curate', 'cli', 'reconcile', 'config',
            'observe']
    for m in mods:
        __import__('saltpod.' + m)
    return '%d modules' % len(mods)


# -------------------------------------------------------------------- http
def t_api():
    import urllib.request
    base = 'http://127.0.0.1:7654'
    try:
        urllib.request.urlopen(base + '/api/health', timeout=3)
    except Exception:
        return None
    out = []
    for ep, want in (('tracks', 'tracks'), ('health', 'ipod'), ('playlists', 'playlists')):
        d = json.load(urllib.request.urlopen('%s/api/%s' % (base, ep), timeout=60))
        assert want in d, '/api/%s has no %r' % (ep, want)
        out.append(ep)
    d = json.load(urllib.request.urlopen(base + '/api/tracks', timeout=60))
    t = d['tracks'][0]
    for f in ('lists', 'album_key', 'held'):
        assert f in t, 'the payload stopped answering %r -- clients would start deciding' % f
    return 'answers: ' + ' '.join(out)


# ----------------------------------------------------------------- helpers
def _device():
    return os.path.exists('/Volumes/IPOD/iPod_Control/iTunes/iTunesDB') and '--device' in sys.argv


def _a_database():
    live = '/Volumes/IPOD/iPod_Control/iTunes/iTunesDB'
    if _device() and os.path.exists(live):
        return live
    import glob
    b = sorted(glob.glob(os.path.join(ROOT, 'backups', 'ipod-*', 'iTunesDB')))
    return b[-1] if b else None


def _guid():
    from saltpod import config
    return (config.load() or {}).get('firewire_guid')


_IDX = None


def _index():
    global _IDX
    if _IDX is None:
        p = os.path.join(ROOT, 'data', 'local', 'index.json')
        _IDX = json.load(open(p))['tracks'] if os.path.exists(p) else []
    return _IDX


def _files(ext, limit=400, cap=140e6):
    """Real files of one container, SMALLEST FIRST.

    The cap used to be 25 MB and the order was whatever the index held, which
    silently skipped .aif entirely -- every AIFF here is 70 to 113 MB, so the
    container that had been broken for two days was the one container the
    round-trip never reached. Smallest-first keeps the suite fast and keeps
    every container in it.
    """
    out = []
    for e in _index():
        if (e.get('ext') or '').lower() != ext:
            continue
        p = e.get('path') or ''
        if not os.path.exists(p) or (e.get('size') or 0) > cap:
            continue
        out.append((e.get('size') or 0, p))
    out.sort()
    return [p for _n, p in out[:limit]]


def _a_file(ext, writable=False, with_art=False):
    from saltpod import tags as T
    art = {e.get('path'): e.get('has_art') for e in _index()}
    for p in _files(ext):
        if with_art and not art.get(p):
            continue
        if writable and not T.supported(p):
            continue
        return p
    return None


def _apic_bytes(path):
    from saltpod import tags as T
    fr, _ = T._id3_read_tag(open(path, 'rb').read(T._id3_span(path)))
    return sum(len(x) for f, x in (fr or []) if f == 'APIC')


# ------------------------------------------------------------------- main
def main():
    print('saltpod selftest   %s%s'
          % (time.strftime('%Y-%m-%d %H:%M'),
             '   (device included)' if _device() else '   (no device)'))

    section('format — the byte-exact promises')
    check('iTunesDB parse -> serialise', t_itunesdb_roundtrip)
    check('hash58 verifies', t_hash58)
    check('ArtworkDB parse -> serialise', t_artworkdb_roundtrip)

    section('tags — written on copies, never your library')
    check('write three times, audio unmoved', t_tag_roundtrip, slow=True)
    check('cover art survives a write', t_tag_preserves_art, slow=True)
    check('readers agree with ffprobe', t_tag_matches_ffprobe, slow=True)
    check('refuses what it cannot do safely', t_tag_refusals)
    check('ID3v1 genre numbers resolve', t_genre_numbers)

    section('core — the rules')
    check('drift resolution table', t_drift_resolution)
    check('migrate is idempotent', t_migrate_idempotent)
    check('sync exclusions', t_exclusions)
    check('plan is cached by mtime', t_plan_cached)

    section('layers — the boundary and the design system')
    check('every module imports', t_imports)
    check('the published tree imports too', t_published_tree_imports)
    check('adapters, and both backends agree', t_platform, slow=True)
    check('the event log', t_observe)
    check('one implementation, two adapters', t_one_implementation)
    check('inline script parses', t_js_parses)
    check('no literals outside :root', t_token_census)
    check('front end does not decide', t_layer_census)

    section('http — the contract both clients use')
    check('the API answers questions', t_api)

    print('\n%d passed, %d failed, %d skipped   (%.1fs)'
          % (len(PASS), len(FAIL), len(SKIP), time.time() - _t0))
    if FAIL:
        print('\nfailures:')
        for name, why in FAIL:
            print('  %-46s %s' % (name, why))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
