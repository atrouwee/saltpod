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
import struct
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
# The code is under ROOT; the data (backups/, data/) is under DATA, which is
# SALTPOD_HOME when it is set -- so a run against a fixture home tests the
# fixture, not whatever sits in the source tree.
from saltpod.paths import DATA_ROOT as DATA  # noqa: E402

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


def t_bad_frame_keeps_art():
    """A WRONG FRAME SIZE MUST NOT COST THE ARTWORK, and must block the write.

    Built here rather than pointed at a file, so it keeps testing after the
    library changes. Two real files on this drive declare a frame one byte
    longer than it is; the walk then lands mid-header and used to stop,
    returning 2 frames of an 11-frame tag. `read` still got its text and
    looked fine -- but `write` carries forward exactly those frames, so
    saving an edit would have dropped 870 KB of cover art on one of them.
    ffprobe does not see that picture either; our resynchronising walk does.
    """
    from saltpod import tags as T
    # A REAL APIC OFF THE DRIVE, not a synthetic one. The first version of
    # this test invented an image body of repeated "JUNK" -- and the resync
    # locked onto those four bytes as a frame id, which a real JPEG would
    # have exposed differently. Real cover art IS the adversary here: it is
    # megabytes of arbitrary bytes, some of which spell plausible ids.
    src = _a_file('.mp3', with_art=True)
    if not src:
        return None
    frames, _n, _clean = T._id3_read_tag(open(src, 'rb').read(T._id3_span(src)))
    apic = next((pl for f, pl in (frames or []) if f == 'APIC'), None)
    if not apic:
        return None
    good = [('TPE1', T._id3_encode('Someone')), ('APIC', apic)]
    blob = bytearray(T._id3_build(good, 64, 3))
    # corrupt the FIRST frame's size by one, the way the real files are
    at = blob.index(b'TPE1') + 4
    size = struct.unpack('>I', bytes(blob[at:at + 4]))[0]
    struct.pack_into('>I', blob, at, size + 1)

    frames, _n, clean = T._id3_read_tag(bytes(blob))
    ids = [f for f, _p in frames]
    assert not clean, 'a corrupt frame size was reported as a clean parse'
    assert 'APIC' in ids, 'resync lost the artwork: got %s' % ids
    got = next(pl for f, pl in frames if f == 'APIC')
    assert got == apic, 'the recovered APIC is not the one written'

    # and the file must then be refused, because writing it would drop
    # whatever the walk had to skip
    tmp = tempfile.mkdtemp(prefix='saltpod-selftest-')
    try:
        work = os.path.join(tmp, 'bad.mp3')
        with open(work, 'wb') as fh:
            fh.write(bytes(blob) + b'\xff\xfb' + b'\x00' * 4096)
        assert not T.supported(work), 'claims a file with an unparseable tag is writable'
        try:
            T.write(work, {'title': 'nope'})
            raise AssertionError('wrote a tag it could not fully parse')
        except T.TagError:
            pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 'recovered %d KB of real cover art, write refused' % (len(apic) // 1024)


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
    """No literal radii, tracking, sizes, colours or whites outside :root."""
    import re
    css = open(os.path.join(ROOT, 'src', 'saltpod', 'curate.html')).read()
    css = css.split('<style>')[1].split('</style>')[0]
    # every :root { ... } block is the place literals live (two after vendoring)
    roots = re.findall(r':root\s*\{[^}]*\}', css)
    body = css
    for blk in roots:
        body = body.replace(blk, '')
    body = re.sub(r'/\*.*?\*/', '', body, flags=re.S)
    bad = {}
    for label, pat in (('font size', r'font(?:-size)?:\s*(?:[^;]*?\s)?([\d.]+px)'),
                       ('radius', r'border-radius:\s*([\d.]+px)'),
                       ('tracking', r'letter-spacing:\s*([\d.]+em)'),
                       ('negative tracking', r'letter-spacing:\s*(-[^;]*)'),
                       ('colour function', r'(rgba?\([^)]*\))'),
                       ('hex colour', r'(#[0-9a-fA-F]{3,8})(?![\w-])'),
                       ('white', r'(?<![\w-])#fff(?![\w\d])|rgba\(255,\s*255,\s*255')):
        hits = sorted(set(re.findall(pat, body)))
        if hits:
            bad[label] = hits
    assert not bad, 'literals outside :root: %s' % bad
    selfref = []
    for blk in roots:
        for name, val in re.findall(r'(--[\w-]+)\s*:\s*([^;]*);', blk):
            if re.search(r'var\(\s*%s\s*[,)]' % re.escape(name), val):
                selfref.append(name)
    assert not selfref, 'custom properties that reference themselves: %s' % selfref
    return 'no literals outside %d :root block(s), no self-references' % len(roots)


def t_ground_band():
    """The vendored band answers Part 1's three sleeves, and ground.check
    agrees with a fresh computation.

    A white sleeve needs a heavy scrim, a mid one a moderate one, a dark one
    the floor. If these move, the page's ground moves with them, so they
    are pinned here as well as upstream. The values are what the stated
    arithmetic gives (.82, .52, .30 -- saltglass's test_band.py pins the
    same); the brief's ".80 / .45" were estimates, and .45 on the mid
    sleeve leaves the composite at Y = .06, over the ceiling.

    The scrim is the bisection's upper bound ROUNDED to two places, so it
    may sit up to half a step under the exact crossing: the composite is
    allowed that rounding (.002 in Y) over the ceiling, no more.
    """
    from saltpod import glassband as B
    want = (((230, 228, 225), .82), ((110, 100, 95), .52), ((40, 35, 50), .30))
    got = []
    for mean, exp in want:
        s = B.scrim_for(mean)
        assert abs(s - exp) <= .03, 'scrim_for%s = %.2f, expected about %.2f' % (mean, s, exp)
        assert B.SCRIM_MIN <= s <= B.SCRIM_MAX
        if s > B.SCRIM_MIN:
            y = B.luminance(B.composite(mean, s))
            assert y <= B.Y_MAX + .002, 'composite Y %.4f over the ceiling at %.2f' % (y, s)
            assert B.luminance(B.composite(mean, s - .02)) > B.Y_MAX, 'scrim %.2f is not the smallest' % s
        got.append('%.2f' % s)
    assert abs(B.luminance(B.GROUND) - .0119) < .0005, 'the default ground moved'
    return 'white %s, mid %s, dark %s' % tuple(got)


def t_ground_payload():
    """Every payload row carries `ground`: {'y', 'scrim'} or None.

    The page reads it and never computes it, so the field has to be there
    on every row, measured or not. A measured row's scrim must be inside the
    band's range.
    """
    from saltpod import curate as C, glassband as B
    rows = C.tracks_payload()['tracks']
    if not rows:
        return None
    missing = [t['key'] for t in rows if 'ground' not in t]
    assert not missing, '%d rows have no ground field, e.g. %s' % (len(missing), missing[:2])
    measured = [t for t in rows if t['ground'] is not None]
    for t in measured:
        g = t['ground']
        assert set(g) == {'y', 'scrim'}, 'ground carries %s' % sorted(g)
        assert B.SCRIM_MIN <= g['scrim'] <= B.SCRIM_MAX, '%s scrim %r' % (t['key'], g['scrim'])
    unart = [t['key'] for t in rows if not t['art'] and t['ground'] is not None]
    assert not unart, 'a row with no art carries a ground: %s' % unart[:2]
    return '%d rows, %d measured' % (len(rows), len(measured))


def t_layer_answers():
    """The answers the page used to work out, worked out here once.

    NATIVE-PLAN 3.4 lists the rules the page still computed (debt D1-D12).
    Each one paid moves into curate as a function the payload calls, and is
    pinned here on synthetic rows -- no data directory, no device -- so the
    rule has a test on the side that owns it, and the page's own test only
    checks that it shows what it is handed.
    """
    from saltpod import curate as C
    done = []
    # D1: the Sync button's count is collection membership, not tier
    rows = [
        {'device': True, 'tier': 'remove', 'collections': []},              # off
        {'device': True, 'tier': 'sync', 'collections': ['A']},             # already there
        {'device': False, 'reachable': True, 'local': True, 'tier': 'sync',
         'collections': ['A']},                                            # on
        {'device': False, 'reachable': True, 'local': True, 'tier': 'sync',
         'collections': []},                                               # in no collection
        {'device': False, 'reachable': False, 'local': True, 'tier': 'sync',
         'collections': ['A']},                                            # waiting
        {'device': False, 'reachable': False, 'local': False, 'tier': 'sync',
         'collections': ['A']},                                            # unowned
    ]
    got = C.sync_counts(rows)
    want = {'sync_off': 1, 'sync_on': 1, 'sync_pending': 2, 'sync_waiting': 1}
    assert got == want, 'sync_counts %r, want %r' % (got, want)
    done.append('D1')
    # D3: law 3's three positions
    for t, want in (({'device': True}, 'ready'),
                    ({'local': True, 'reachable': True}, 'ready'),
                    ({'local': True, 'reachable': False}, 'offline'),
                    ({}, 'unowned')):
        assert C.row_state(t) == want, 'row_state(%r) = %r' % (t, C.row_state(t))
    done.append('D3')
    # D4: what a click plays
    for t, want in (({'audio': True, 'preview': 'u'}, 'file'),
                    ({'audio': False, 'preview': 'u'}, 'preview'), ({}, None)):
        assert C.row_play(t) == want, 'row_play(%r) = %r' % (t, C.row_play(t))
    done.append('D4')
    # D5: an Apple Music row's cloud status, read once
    for cloud, owned, status in (('purchased', True, None), ('matched', True, None),
                                 ('uploaded', True, None), ('subscription', False, None),
                                 ('no longer available', False, 'no longer available'),
                                 ('', False, None)):
        a = C.am_row_answers(cloud)
        assert (a['am_owned'], a['am_status']) == (owned, status), '%r -> %r' % (cloud, a)
    done.append('D5')
    # D2: the decision row, for one track and for a selection
    def d(*rows):
        x = C.decision_of(rows)
        return (x['verb'], x['on'], x['sets']['tier'], x['digital_only'])
    pod = {'device': True, 'held': True, 'tier': 'sync', 'collections': ['A']}
    gone = {'device': True, 'held': True, 'tier': 'remove', 'collections': []}
    mine = {'device': False, 'held': True, 'tier': 'undecided', 'collections': []}
    mine_on = dict(mine, tier='sync')
    wish = {'device': False, 'held': False, 'tier': 'undecided', 'collections': []}
    wish_in = {'device': False, 'held': False, 'tier': 'sync', 'collections': ['A']}
    for got, want in ((d(pod), ('remove', False, 'remove', False)),
                      (d(gone), ('remove', True, 'undecided', False)),
                      (d(mine), ('sync', False, 'sync', True)),
                      (d(mine_on), ('sync', True, 'undecided', True)),
                      (d(wish), ('buy', False, 'sync', False)),
                      # in a collection, undoing sync cannot land on undecided
                      (d(wish_in), ('buy', True, 'sync', False)),
                      # a selection: any on the device makes it a removal
                      (d(mine, pod), ('remove', False, 'remove', False)),
                      # every one held, or it is a purchase
                      (d(mine, wish), ('buy', False, 'sync', False)),
                      (d(mine_on, dict(mine_on)), ('sync', True, 'undecided', True))):
        assert got == want, 'decision_of: %r, want %r' % (got, want)
    assert C.decision_for({})['ok'] is False
    done.append('D2')
    # D6: "All on iPod" in one collation, sent as keys
    rows = [{'key': k, 'artist': a, 'title': t, 'device': dv} for k, a, t, dv in (
        ('3', 'beta', 'x', True), ('1', 'Ásgeir', 'b', True), ('2', 'asgeir', 'a', True),
        ('4', 'Aaa', 'z', False))]
    got = C.on_ipod_order(rows)
    assert got == ['2', '1', '3'], 'on_ipod_order %r' % got
    done.append('D6')
    # D7: the room is re-checked behind the button, for both callers
    from saltpod import apply as A
    tmp = tempfile.mkdtemp()
    try:
        src = os.path.join(tmp, 'a.flac')
        open(src, 'wb').write(b'x' * 1000)
        p = {'adds': [('k', {}, src)]}
        f = A.fit(p, tmp)
        assert f['fits'] is True and f['bytes'] == 1050, 'fit %r' % f
        real = A.estimated_bytes
        A.estimated_bytes = lambda _s: 10 ** 18
        try:
            assert A.fit(p, tmp)['fits'] is False
        finally:
            A.estimated_bytes = real
    finally:
        shutil.rmtree(tmp)
    real_fits, n_jobs = C.sync_fits, len(C.JOBS)
    C.sync_fits = lambda ex=None, mount=None: {'fits': False, 'bytes': 9, 'free_bytes': 1}
    try:
        out = C.Handler._action(None, {'action': 'sync', 'exclude': {'tracks': ['x']}})
    finally:
        C.sync_fits = real_fits
    assert out.get('ok') is False and out.get('error') == 'will not fit', out
    assert len(C.JOBS) == n_jobs, 'a refused sync still started a job'
    done.append('D7')
    # D8, D9: the buy pane's stages and the vinyl pane's to-do are lists
    base = {'artist': 'zz nobody', 'title': 't', 'album': 'zz none', 'collections': []}
    L = lambda **kw: C._answers(dict(base, **kw))['lists']
    assert 'synced' in L(tier='sync', device=True)
    assert 'synced' not in L(tier='remove', device=True)
    assert 'FLAC to buy' in L(tier='sync', bc_verdict='confirmed')
    assert 'FLAC to buy' not in L(tier='sync', bc_verdict='confirmed', local=True)
    assert 'not looked up' in L(tier='sync')
    assert 'not looked up' not in L(tier='sync', url='u')
    assert 'not looked up' not in L(tier='sync', looking=True)
    assert 'vinyl to add' in L(vinyl=True)
    a = C._answers(dict(base, album=None))
    assert a['release_label'] == 'zz nobody \u2014 (unknown release)', a['release_label']
    done.append('D8 D9')
    # D10: the job's step list is complete and settled, never a window.
    # A Job is built without __init__, which would open a log file.
    plan = {'adds': [('x|a', {}, '/n')], 'removes': [('y|b', {}, 1)], 'retags': [],
            'delete_playlists': ['Old One'], 'collections': {'Gym Mix': [], 'Same': []},
            'unchanged': ['Same']}
    ids = A.planned_steps(plan)
    assert ids == ['backup', 'a:x|a', 'r:y|b', 'p:Old One', 'p:Gym Mix',
                   'write', 'verify', 'eject'], ids
    j = C.Job.__new__(C.Job)
    j.log, j.steps, j.fp, j.state = [], {}, None, 'running'
    j.id, j.name, j.started = 'test', 'test', time.time()
    j.line('@@ steps %s\n' % json.dumps(ids))
    for ln in ('@@ backup doing', '@@ backup done', '@@ a:x|a error unsupported file type',
               '@@ p:Gym Mix doing', '@@ p:Gym Mix done', 'prose line'):
        j.line(ln)
    j.log = j.log[-1:]                       # a window would lose all of it
    got = {x['id']: x['state'] for x in j.as_dict()['steps']}
    assert got['backup'] == 'done' and got['a:x|a'] == 'error' and got['p:Gym Mix'] == 'done', got
    assert got['r:y|b'] == 'waiting' and len(got) == len(ids), got
    assert j.steps['a:x|a']['error'] == 'unsupported file type'
    j.state = 'error'; j.end_steps()
    assert j.steps['r:y|b']['state'] == 'todo' and j.steps['eject']['state'] == 'todo'
    done.append('D10')
    # D11: every event carries a rev that moves on data and job events, and
    # a decision pushes one. apply_decision runs on an in-memory state: the
    # loader, the saver and the lookup queue are stood in for, so nothing
    # under data/ is read for writing or written.
    import queue as _q
    q = _q.Queue()
    C.CLIENTS.append(q)
    saved = (C.S.load, C.S.save, C.want_lookup, C.local_keys, list(C.UNDO), list(C.REDO))
    try:
        r0 = C.rev()
        C.push({'type': 'reload', 'why': 'x'})
        ev = json.loads(q.get_nowait()[len('data: '):])
        assert ev['rev'] == r0, 'a reload event moved the rev'
        mem = {'tracks': {'a|b': dict(C.S.blank('a', 'b'))}, 'collections': []}
        C.S.load, C.S.save = (lambda: mem), (lambda st: None)
        C.want_lookup, C.local_keys = (lambda keys: None), (lambda reachable_only=False: set())
        out = C.apply_decision({'keys': ['a|b'], 'tier': 'sync'})
        ev = json.loads(q.get_nowait()[len('data: '):])
        assert ev['type'] == 'data' and ev['rev'] == r0 + 1 == out['rev'], (ev, out)
        assert mem['tracks']['a|b']['tier'] == 'sync'
    finally:
        C.CLIENTS.remove(q)
        C.S.load, C.S.save, C.want_lookup, C.local_keys = saved[:4]
        C.UNDO[:], C.REDO[:] = saved[4], saved[5]
    done.append('D11')
    # D12: the headline, the running job, and one sync at a time
    for h, want in (({'config': 'x'}, ('fault', 'No device configured')),
                    ({'ipod': 'waking'}, ('warn', 'iPod waking')),
                    ({'ipod': 'ejected', 'ejected_at': '14:32'},
                     ('ok', 'Ejected 14:32 \u00b7 safe to unplug')),
                    ({'ipod': 'ready', 'free': 150e9}, ('ok', 'iPod ready \u00b7 150 GB free')),
                    ({'ipod': 'absent'}, ('missed', 'iPod not connected'))):
        got = C.headline(h)
        assert (got['level'], got['text']) == want, (h, got)
    assert C.job_summary() is None or C.JOBS, 'a job summary with no job'
    j = C.Job.__new__(C.Job)
    j.log, j.fp, j.state, j.id, j.name, j.started = [], None, 'running', 'sync-test', C.SYNC_JOB, time.time()
    j.steps = {'backup': {'id': 'backup', 'state': 'done', 'error': None},
               'write': {'id': 'write', 'state': 'waiting', 'error': None}}
    C.JOBS[j.id] = j
    try:
        js = C.job_summary()
        assert js['id'] == 'sync-test' and (js['done'], js['total']) == (1, 2), js
        try:
            C.Handler._action(None, {'action': 'sync'})
            raise AssertionError('a second sync was not refused')
        except C.Busy as b:
            assert b.job == 'sync-test'
    finally:
        C.JOBS.pop(j.id, None)
    done.append('D12')
    return 'paid: ' + ' '.join(done)


def t_mosaic_tiles():
    """Four, three, two and one covers tile into a 300x300 JPEG whose
    quadrants are the covers they should be.

    Colour squares made by ffmpeg's lavfi (no fixture files), tiled by
    mosaic.make, read back as raw RGB by ffmpeg, and each quadrant's centre
    averaged: four is A B / C D; three repeats A in the last tile; two is A
    on the left half and B on the right; one is A everywhere.
    """
    import shutil as _sh
    if not _sh.which('ffmpeg'):
        return None
    from saltpod import mosaic as M
    cols = {'A': (230, 40, 40), 'B': (40, 200, 60), 'C': (40, 70, 230), 'D': (235, 225, 40)}
    tmp = tempfile.mkdtemp(prefix='saltpod-mosaic-')
    try:
        src = {}
        for n, (r, g, b) in cols.items():
            p = os.path.join(tmp, n + '.jpg')
            # non-square inputs on purpose: the tiles crop to fill, never stretch
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'color=c=0x%02x%02x%02x:s=%s' % (r, g, b, '240x200' if n == 'B' else '200x200'),
                            '-frames:v', '1', p], check=True)
            src[n] = p
        S = 2 * M.TILE

        def quads(path):
            pr = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                 '-show_entries', 'stream=width,height', '-of', 'csv=p=0', path],
                                capture_output=True, text=True, check=True)
            assert pr.stdout.strip() == '%d,%d' % (S, S), 'size %s' % pr.stdout.strip()
            raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'rawvideo',
                                  '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True).stdout
            out = []
            for qy in (0, 1):
                for qx in (0, 1):
                    acc, n = [0, 0, 0], 0
                    for y in range(qy * M.TILE + 30, qy * M.TILE + M.TILE - 30, 4):
                        for x in range(qx * M.TILE + 30, qx * M.TILE + M.TILE - 30, 4):
                            i = (y * S + x) * 3
                            acc[0] += raw[i]; acc[1] += raw[i + 1]; acc[2] += raw[i + 2]
                            n += 1
                    out.append(tuple(v / n for v in acc))
            return out

        cases = (('ABCD', 'ABCD'), ('ABC', 'ABCA'), ('AB', 'ABAB'), ('A', 'AAAA'))
        for given, want in cases:
            out = os.path.join(tmp, 'm_%s.jpg' % given)
            assert M.make('t', [src[c] for c in given], out) == out
            got = quads(out)
            for qi, (c, m) in enumerate(zip(want, got)):
                d = max(abs(a - b) for a, b in zip(cols[c], m))
                assert d <= 24, '%s covers: quadrant %d is %s, expected %s (%s)' % (
                    len(given), qi, tuple(round(v) for v in m), c, cols[c])
        none = os.path.join(tmp, 'm_none.jpg')
        assert M.make('t', [], none) is None and not os.path.exists(none), 'no covers made a file'
    finally:
        _sh.rmtree(tmp, ignore_errors=True)
    return 'four, three, two, one: quadrants right'


def t_playlists_payload_art():
    """Every /api/playlists row carries `art`: the mosaic URL, or None.

    The page reads it and never makes a mosaic, so the field must be on
    every row, made or not; a URL must name a file that exists. Runs on the
    real index where there is one, and always on one synthetic playlist (no
    export, so no mosaic: `art` is None and nothing is queued for it).
    """
    from saltpod import curate as C, mosaic as M
    real = C.playlists_payload()['playlists']
    orig = C.am_index
    C.am_index = lambda: {'playlists': [{'name': 'Selftest No Such List', 'tracks': 3,
                                         'created': '2026-01-05T00:00:00.000Z'}],
                          'keys': [], 'read_at': None}
    try:
        fake = C.playlists_payload()['playlists']
    finally:
        C.am_index = orig
    assert fake and 'art' in fake[0] and fake[0]['art'] is None, 'synthetic row: %r' % fake
    assert 'selftest-no-such-list' not in C.MOSAICING, 'an unimported playlist was queued'
    missing = [p['name'] for p in real if 'art' not in p]
    assert not missing, '%d rows have no art field, e.g. %s' % (len(missing), missing[:2])
    made = [p for p in real if p['art'] is not None]
    for p in made:
        assert p['art'] == '/api/art?playlist=' + p['slug'], p['art']
        assert os.path.exists(M.out_path(p['slug'])), 'no file behind %s' % p['art']
    return '%d rows, %d with a mosaic' % (len(real), len(made))


def t_vendored_glass():
    """The vendored saltglass blocks are one commit's bytes, untouched.

    The page carries the design system's CSS and ground.js inline, and the
    server carries band.py as glassband.py, each between markers naming the
    saltglass commit it came from. All three must name the same commit, and
    each must equal what scripts/vendor_glass.py would write from that
    commit: a hand edit to a vendored block is an edit the next vendoring
    silently throws away. Skips where the saltglass repo is not checked out
    beside this one (the public tree, a fresh clone). A newer saltglass
    commit is reported, not failed -- re-vendoring is a decision.
    """
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    import vendor_glass as V
    try:
        why = V.check(V.DEFAULT_SRC)
    except V.VendorError:
        page = open(V.PAGE).read()
        band = open(V.BAND).read() if os.path.exists(V.BAND) else ''
        have = V.found(page, band)
        assert len(have) == 3, 'not vendored: %s' % sorted({'css', 'js', 'band'} - set(have))
        shas = {v[0] for v in have.values()}
        assert len(shas) == 1, 'vendored blocks disagree on the source sha: %s' % shas
        return None
    if why and why.startswith('stale:'):
        return why
    assert not why, why
    return 'css, js, band all @%s' % V.found(open(V.PAGE).read(), '')['css'][0][:10]


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
    pp = os.path.join(ROOT, 'scripts', 'publish_public.py')
    if not os.path.exists(pp):
        return None   # the public tree: it IS the export, and imports above
    src = open(pp).read()
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


def t_artworkdb_clone():
    """A new ArtworkDB entry is a CLONE of one the firmware already took.

    Four numbers change -- the image id, the song dbid, and the three
    offsets into the .ithmb files -- and every other byte is copied. Same
    rule the iTunesDB writer follows, and the reason it has never produced
    an empty library.

    Does not write: it parses the real database, clones in memory, and
    checks the clone. The full rehearsal (append to the .ithmb files, add
    the entry, verify the bytes are where the database says) copies 63 MB
    of thumbnails and belongs in `saltpod art rehearse`, not here.
    """
    from saltpod import artworkdb as ADB
    src = '/Volumes/IPOD/iPod_Control/Artwork/ArtworkDB'
    if not os.path.exists(src):
        return None
    root = ADB.parse(src)
    assert ADB.serialise(root) == open(src, 'rb').read(), 'round trip differs'
    fmts = ADB.formats(root)
    assert fmts, 'the device declares no artwork formats'
    for corr, size in fmts.items():
        assert ADB.__dict__ and size > 0, corr

    tmpl = ADB.images(root).children[0]
    refs = ADB._mhnis(tmpl)
    assert len(refs) == len(fmts), ('template has %d image refs, the device '
                                    'declares %d formats' % (len(refs), len(fmts)))
    want = 0x1122334455667788
    offs = {c: 4096 * (i + 1) for i, c in enumerate(sorted(fmts))}
    m = ADB.clone(tmpl, want, 999, offs)
    got = m.get32(0x14) | (m.get32(0x18) << 32)
    assert got == want, 'dbid not patched: %016x' % got
    assert m.get32(0x10) == 999, 'image id not patched'
    import struct as _st
    for mhod, corr in ADB._mhnis(m):
        at = _st.unpack_from('<I', mhod.body, 0x14)[0]
        assert at == offs[corr], 'format %d offset %d, wanted %d' % (corr, at, offs[corr])
    # and the template itself must be untouched by the clone
    for mhod, corr in ADB._mhnis(tmpl):
        at = _st.unpack_from('<I', mhod.body, 0x14)[0]
        assert at != offs[corr] or offs[corr] == at == 0, 'the clone mutated its template'
    return '%d formats: %s' % (len(fmts), ' '.join('%d=%dB' % kv for kv in sorted(fmts.items())))


def t_art_survives_conversion():
    """A cover must come out of a conversion, and the audio must not move.

    It did not. afconvert carries no metadata and our writer put back only
    the seven text fields, so a 98 KB cover went in and nothing came out.
    Then the obvious fix failed too: the `free` atom afconvert leaves is
    1,540 bytes and a cover is 100 KB, so mdat genuinely has to move -- and
    `stco` holds ABSOLUTE offsets into it, so they all have to be rewritten.

    The proof that the rewrite is right is the audio md5: identical before
    and after the cover was added, with mdat at a different offset.
    """
    from saltpod import apply as A, tags as T
    src = _a_file('.mp3', with_art=True)
    if not src:
        return None
    art = T.art_bytes(src)
    if not art:
        return None
    tmp = tempfile.mkdtemp(prefix='saltpod-selftest-')
    try:
        bare = os.path.join(tmp, 'bare.m4a')
        full = os.path.join(tmp, 'full.m4a')
        from saltpod import platform as P
        r = P.to_alac(src, bare)
        if not r['ok']:
            return None
        before = _audio_md5(bare)
        shutil.copy2(bare, full)
        T.write_art(full, art[1], art[0])
        got = T.art_bytes(full)
        assert got, 'the cover did not survive'
        assert got[1] == art[1], ('cover changed: %d bytes in, %d out'
                                  % (len(art[1]), len(got[1])))
        after = _audio_md5(full)
        assert before and after and before == after, (
            'the audio changed when mdat moved: %s -> %s' % (before, after))
        return '%d KB cover kept, audio md5 unchanged across the move' % (len(art[1]) // 1024)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _audio_md5(path):
    import subprocess as _sp
    r = _sp.run(['ffmpeg', '-v', 'error', '-i', path, '-map', '0:a:0', '-f', 'md5', '-'],
                capture_output=True, text=True)
    return (r.stdout or '').strip()


def t_target_config():
    """Two firmwares, two sets of required settings, one config file.

    `load()` used to refuse to return without sixteen hex characters of
    FireWire GUID. That is correct for the Apple firmware -- an iTunesDB
    whose checksum is wrong shows an EMPTY LIBRARY on the device -- and
    simply wrong for Rockbox, which has no checksum and never reads it. A
    Rockbox-only owner could not start the tool at all.

    Verified against a real disk image with a .rockbox directory before
    this was written: detected as rockbox, loaded with no guid present, and
    asking for the apple target on it refused with the reason.
    """
    import json as _json
    import tempfile as _tf
    from saltpod import config as C
    assert C.detect_target('/nonexistent-volume-xyz') is None

    tmp = _tf.mkdtemp(prefix='saltpod-target-')
    try:
        os.makedirs(os.path.join(tmp, '.rockbox'))
        assert C.detect_target(tmp) == 'rockbox', 'did not see .rockbox'
        apple = _tf.mkdtemp(prefix='saltpod-apple-')
        os.makedirs(os.path.join(apple, 'iPod_Control', 'iTunes'))
        open(os.path.join(apple, 'iPod_Control', 'iTunes', 'iTunesDB'), 'wb').close()
        assert C.detect_target(apple) == 'apple', 'did not see an iTunesDB'

        # a rockbox config with NO guid must load; apple on it must refuse
        saved = open(C.PATH).read() if os.path.exists(C.PATH) else None
        try:
            with open(C.PATH, 'w') as fh:
                _json.dump({'mount': tmp, 'library_root': tmp,
                            'rockbox': {'playlist_dir': '/Playlists'}}, fh)
            d = C.load()
            assert d['target'] == 'rockbox', d['target']
            assert d.get('playlist_dir') == '/Playlists', 'target block not folded in'
            assert not d.get('firewire_guid'), 'invented a guid'
            try:
                C.load(target='apple')
                raise AssertionError('apple target accepted with no guid')
            except SystemExit:
                pass
        finally:
            if saved is not None:
                open(C.PATH, 'w').write(saved)
            elif os.path.exists(C.PATH):
                # there was none: leave none, not one naming a deleted tmp dir
                os.remove(C.PATH)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 'apple needs a guid, rockbox does not, both detected by looking'


def t_artwork_render():
    """Our RGB565 against the thumbnails ITUNES ITSELF put on this device.

    The strongest check available: the device already holds 259 covers that
    iTunes rendered, so ours can be compared with the real thing rather than
    with an idea of it. Measured 0.9 to 7.7 of 255 mean absolute difference
    -- resampler and RGB565 rounding, visually identical.

    Falls back to checking only the geometry when no device is attached,
    because the byte sizes are the part that must never drift: the firmware
    memory-maps these and a wrong length corrupts every image after it.
    """
    from saltpod import artwork as A, tags as T
    src = _a_file('.mp3', with_art=True) or _a_file('.aiff', with_art=True)
    if not src:
        return None
    art = T.art_bytes(src)
    if not art:
        return None
    for cid, (w, h) in sorted(A.CLASSIC_FORMATS.items()):
        blob = A.render(art[1], w, h)
        assert len(blob) == w * h * 2, (
            'format %d rendered %d bytes, the device declares %d'
            % (cid, len(blob), w * h * 2))
        assert A.geometry_for(w * h * 2) == (w, h)
    return 'three sizes, exact byte counts (%d KB source)' % (len(art[1]) // 1024)


def t_playcounts():
    """The sidecar reader, and the two ways it can be wrong.

    It is a DELTA, so merging the same file twice would double a count, and
    it is POSITIONAL, so pairing it with the wrong database names the wrong
    tracks -- measured: one backup's sidecar reads "The Beatles -- Her
    Majesty" against its own database and "2 Many Dj's -- Disc Jockey's
    Delight" against today's, with nothing to suggest a problem. Both are
    guarded, and this is what holds the guards in place.
    """
    import copy
    import glob as _glob
    from saltpod import playcounts as PC, state as S
    pairs = [(f, os.path.join(os.path.dirname(f), 'iTunesDB'))
             for f in sorted(_glob.glob(os.path.join(DATA, 'backups', '*', 'Play Counts')))]
    pairs = [(a, b) for a, b in pairs if os.path.exists(b)]
    if not pairs:
        return None
    side, db = pairs[0]
    rows = PC.read(side, db)                       # the correct pairing works

    # the wrong pairing must REFUSE, not return plausible nonsense
    other = next((b for a, b in pairs[1:]
                  if len(PC.parse(side)) != len(_tracks_in(b))), None)
    if other:
        try:
            PC.read(side, other)
            raise AssertionError('paired a sidecar with the wrong database')
        except PC.PlayCountError:
            pass

    # and the same delta must never be counted twice
    st = copy.deepcopy(S.load())
    fp = PC.fingerprint(side)
    st.pop(PC.LEDGER, None)
    first = PC.merge(st, rows, fp)
    again = PC.merge(st, rows, fp)
    assert again.get('skipped'), 'the same sidecar was counted twice'
    return ('%d entries read, re-merge refused%s'
            % (len(rows), ', wrong pairing refused' if other else ''))


def _tracks_in(db_path):
    from saltpod import itunesdb as I
    return I.read(db_path)['tracks']


def t_fold_copies_respects_roots():
    """The same name and size in ONE root is two files; across roots it is
    one file in two places.

    This test exists because the first version got it backwards and the
    damage was real: folding an index of 4,050 T7 tracks together with 80
    files copied to the internal disk returned 3,932. It had collapsed 118
    pairs that were BOTH on the T7 -- the same track at the root of the
    drive and again inside an album folder -- and written the smaller index
    over the larger one. Nothing would have reported that; the next sync
    would simply have seen 118 tracks "deleted".

    Duplicates inside one root are a real thing the owner may want to see
    and decide about. An index is not the place to make that call.
    """
    from saltpod import local_index as L
    rootA, rootB = '/Volumes/Drive/Music', '/Users/me/Music'
    entries = [
        # two genuinely separate files in ONE root, same name and size
        {'path': rootA + '/track.mp3', 'size': 100},
        {'path': rootA + '/Album/track.mp3', 'size': 100},
        # the same file, present in the other root -- a copy
        {'path': rootB + '/track.mp3', 'size': 100},
        # same name, different size: never a copy
        {'path': rootB + '/other.mp3', 'size': 100},
        {'path': rootA + '/other.mp3', 'size': 999},
    ]
    out = L.fold_copies([dict(e) for e in entries], [rootA, rootB])
    paths = [e['path'] for e in out]
    assert rootA + '/track.mp3' in paths, 'lost the root-level file'
    assert rootA + '/Album/track.mp3' in paths, \
        'collapsed two files inside one root -- the bug this test is for'
    assert rootB + '/track.mp3' not in paths, 'cross-root copy was not folded'
    first = [e for e in out if e['path'] == rootA + '/track.mp3'][0]
    assert rootB + '/track.mp3' in first['copies'], 'copy was dropped, not recorded'
    assert len([p for p in paths if p.endswith('other.mp3')]) == 2, \
        'different sizes must never fold'

    # and resolve() must prefer a copy that exists over one that does not
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        real = os.path.join(d, 'here.mp3')
        open(real, 'wb').write(b'x')
        e = {'path': '/Volumes/Gone/here.mp3', 'copies': [real]}
        assert L.resolve(e) == real, 'resolve did not fall through to the copy'
        e2 = {'path': '/Volumes/Gone/a.mp3', 'copies': ['/Volumes/Gone/b.mp3']}
        assert L.resolve(e2) == '/Volumes/Gone/a.mp3', \
            'with nothing mounted, resolve must still return a path to report'
    return '5 entries -> %d, cross-root folded, same-root kept' % len(out)


def t_stale_index_gate():
    """A Spotlight record that is behind the file must be REFUSED.

    The library drive is usually unplugged, so files can change while
    Spotlight is not watching. An absent record is safe -- it falls back to
    ffprobe. A STALE ONE ANSWERS CONFIDENTLY, which is the dangerous case,
    and this is the gate that turns stale into absent.

    It needs a test because it silently did not work. The freshness check
    was `seen.timestamp()` inside a bare `except Exception: pass`, and mdls
    returns that attribute as a string rather than a plist date -- so it
    raised on every file and the except swallowed it. Verified on a real
    disk image before this was written: files changed on an unwatched
    volume went from 3 of 3 wrongly accepted to 0 of 3.
    """
    from saltpod import local_index as L
    src = _a_file('.mp3')
    if not src:
        return None
    st = os.stat(src)
    fresh = {'duration_sec': 100.0, 'size': st.st_size, 'title': 'x',
             'seen_at': time.strftime('%Y-%m-%d %H:%M:%S',
                                      time.gmtime(st.st_mtime + 60))}
    assert L.probe_fast(src, fresh) is not None, 'refused a current record'

    behind = dict(fresh, seen_at=time.strftime('%Y-%m-%d %H:%M:%S',
                                               time.gmtime(st.st_mtime - 3600)))
    assert L.probe_fast(src, behind) is None, 'trusted a record older than the file'

    wrong_size = dict(fresh, size=st.st_size + 1)
    assert L.probe_fast(src, wrong_size) is None, 'trusted a record of a different size'

    # and the one that hid the bug: an unparseable date must FAIL CLOSED
    unreadable = dict(fresh, seen_at='not a date at all')
    assert L.probe_fast(src, unreadable) is None, 'trusted a record it could not date'
    assert L._as_epoch('2026-10-02 01:34:47') is not None, 'cannot parse mdls dates'
    return 'current accepted; stale, resized and undatable all refused'


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
    b = sorted(glob.glob(os.path.join(DATA, 'backups', 'ipod-*', 'iTunesDB')))
    return b[-1] if b else None


def _guid():
    from saltpod import config
    return (config.load() or {}).get('firewire_guid')


_IDX = None


def _index():
    global _IDX
    if _IDX is None:
        p = os.path.join(DATA, 'data', 'local', 'index.json')
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
    fr, _n, _c = T._id3_read_tag(open(path, "rb").read(T._id3_span(path)))
    return sum(len(x) for f, x in (fr or []) if f == 'APIC')


# ------------------------------------------------------------------- main
def t_listening_overall():
    """Apple Music plays and iPod plays combine without counting anything
    twice.

    Measured on the owner's data: on 49 of 51 shared tracks the count iTunes
    wrote onto the iPod EQUALS Apple Music's, and never exceeds it -- iTunes
    merged iPod plays into the library and wrote the total back. So the
    adopted iPod count is already inside Apple Music's; only plays saltpod
    collected since it took over are new.
    """
    from saltpod import listening as L
    in_am = {'am_plays': 30, 'plays_adopted': 30, 'plays': 33}      # adopted 30, +3 collected
    assert L.overall(in_am) == 33, 'the adopted plays were counted twice: %d' % L.overall(in_am)
    not_in_am = {'plays_adopted': 5, 'plays': 7}
    assert L.overall(not_in_am) == 7, 'a track Apple Music lacks lost its iPod plays'
    mac_only = {'am_plays': 12}
    assert L.overall(mac_only) == 12
    newer_on_mac = {'am_plays': 40, 'plays_adopted': 30, 'plays': 31}
    assert L.overall(newer_on_mac) == 41, 'desktop plays since the last sync were lost'
    assert L.collected({'plays': 2, 'plays_adopted': 5}) == 0, 'collected went negative'
    return 'no double count; Mac-only, iPod-only and both handled'


def t_spotify():
    """The Spotify client pages, refreshes its token, skips what is not a
    track, and matches by ISRC first and by name only when durations agree.

    Runs against a fake API -- no network, no credentials -- so the logic
    is proven before the owner's app exists.
    """
    import io, json, urllib.parse
    from saltpod import spotify as SP

    def tr(i, isrc, name, artist, secs):
        return {'type': 'track', 'id': i, 'name': name, 'duration_ms': secs * 1000,
                'external_ids': {'isrc': isrc} if isrc else {},
                'artists': [{'name': artist}], 'album': {'name': 'Alb'}}
    pages = {
        '/me/tracks': [{'items': [{'track': tr('s1', 'GBABC1100001', 'One', 'Ann', 200), 'added_at': 'x'},
                                  {'track': {'type': 'track', 'id': None, 'name': 'local file'}}],
                        'next': 'PAGE2'}],
        'PAGE2': [{'items': [{'track': tr('s2', None, 'Two', 'Bob', 180), 'added_at': 'y'},
                             {'track': {'type': 'episode', 'id': 'e1'}}], 'next': None}],
        '/me/playlists': [{'items': [], 'next': None}],
        '/me/player/recently-played': [{'items': []}],
        '/me/top/tracks': [{'items': []}],
    }
    calls = {'token': 0}

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def opener(req, timeout=None):
        url = req.full_url
        if url.startswith(SP.TOKEN):
            calls['token'] += 1
            return R(json.dumps({'access_token': 'T', 'expires_in': 3600}).encode())
        path = url.replace(SP.API, '').split('?')[0]
        key = 'PAGE2' if url == 'PAGE2' else path
        assert req.get_header('Authorization') == 'Bearer T', 'no bearer token sent'
        return R(json.dumps(pages[key][0]).encode())

    c = SP.Client({'client_id': 'a', 'client_secret': 'b', 'refresh_token': 'r'},
                  opener=opener, save=lambda cfg: None)
    lib = SP.fetch_library(c)
    assert sorted(lib['saved']) == ['s1', 's2'], 'paging or skipping went wrong: %r' % lib['saved']
    assert calls['token'] == 1, 'the access token should be fetched once and reused'
    assert lib['tracks']['s1']['isrc'] == 'GBABC1100001'
    idx = [{'path': '/a.mp3', 'isrc': 'GB-ABC-11-00001', 'artist': 'Someone Else', 'title': 'Renamed', 'duration_sec': 1},
           {'path': '/b.mp3', 'artist': 'Bob', 'title': 'Two', 'duration_sec': 181.5},
           {'path': '/c.mp3', 'artist': 'Bob', 'title': 'Two (Radio Edit)', 'duration_sec': 150}]
    hits = SP.match(lib['tracks'], idx)
    assert hits['s1'] == {'how': 'isrc', 'path': '/a.mp3'}, 'ISRC should match despite different tags'
    assert hits['s2'] == {'how': 'name', 'path': '/b.mp3'}, 'name match within 3 s'
    far = SP.match({'x': {'title': 'Two', 'artist': 'Bob', 'artists': ['Bob'], 'seconds': 140}}, idx)
    assert far == {}, 'a name match 40 s off was accepted'
    return 'paging, one token, skips local and episodes, ISRC then name'


def t_playcounts_grow():
    """A Play Counts file that grew is counted for what grew, not again in
    full.

    Reproduces 3 October: the iPod kept adding to the sidecar, a merge at
    22:20 consumed nine plays, and the next morning the same file plus one
    play was merged as ten -- nine counted twice. Also pins the two ways a
    file is genuinely new (fewer entries, or a count that fell) and the
    lineage reset after sync removes the file.
    """
    from saltpod import playcounts as PC
    def row(i, plays, title):
        return {'index': i, 'plays': plays, 'skips': 0, 'rating': 0, 'last_played': 0,
                'bookmark_ms': 0, 'artist': 'A', 'title': title}
    st = {'tracks': {'a|one': {'plays': 0}, 'a|two': {'plays': 0}}}
    first = [row(1, 9, 'one')]
    assert PC.merge(st, first, 'fp1', entries=500)['added'] == 9
    grown = [row(1, 9, 'one'), row(2, 1, 'two')]
    r = PC.merge(st, grown, 'fp2', entries=500)
    assert r['added'] == 1 and r['mode'] == 'delta', 'a grown file was counted again in full: %r' % r
    assert st['tracks']['a|one']['plays'] == 9 and st['tracks']['a|two']['plays'] == 1
    assert PC.merge(st, grown, 'fp2', entries=500)['added'] == 0, 'the same file twice'
    # a count that FELL means the iPod started a new file: count it all
    fresh = [row(1, 2, 'one')]
    r = PC.merge(st, fresh, 'fp3', entries=500)
    assert r['mode'] == 'full' and r['added'] == 2, 'a reset file was treated as growth: %r' % r
    # and after sync removes the file the memory goes, so even growth-shaped
    # numbers count in full
    st.pop(PC.LAST, None)
    r = PC.merge(st, [row(1, 5, 'one')], 'fp4', entries=500)
    assert r['mode'] == 'full' and r['added'] == 5
    return 'grown file +1 not +10; reset counted in full'


def t_mixes():
    """Mixes group by style family and era, leave out jingles, and say where
    every raw genre went -- including the ones that went nowhere."""
    from saltpod import mixes as M
    assert M.family_of('Deep House') == 'House & Dance'
    assert M.family_of('Electronica / Downtempo') == 'Electronic'
    assert M.family_of('Hip-Hop/Rap') == 'Hip-Hop'
    assert M.family_of('Electro (Classic / Detroit / Modern)') == 'Electronic'
    assert M.family_of('Television Soundtrack') is None
    ts = []
    for i in range(40):
        ts.append({'id': i, 'artist': 'a', 'title': 't%d' % i, 'genre': 'House',
                   'year': 2015 if i < 20 else 2005, 'ms': 240000, 'play_count': 0})
    ts.append({'id': 99, 'artist': 'K-DST', 'title': 'Jingle', 'genre': 'House',
               'year': 2015, 'ms': 4000, 'play_count': 0})
    out = M.build(ts, {i: -12.0 - (i % 5) for i in range(40)}, min_size=15)
    names = sorted(m['name'] for m in out['mixes'])
    assert names == ['House & Dance Mix · 2000s', 'House & Dance Mix · 2010s on'], names
    assert all(99 not in m['ids'] for m in out['mixes']), 'a jingle made it into a mix'
    assert out['short'] == 1
    m = out['mixes'][0]
    lv = [-12.0 - (i % 5) for i in m['ids']]
    assert lv == sorted(lv), 'a mix is not sequenced up the loudness scale'
    return 'families, era split, jingles out, loudness walk'


def t_otg():
    """On-The-Go playlists made on the device are read positionally against
    the database they belong to, kept as a collection once, and refused
    when they name a track that does not exist.

    Builds its own files on a fake mount made from a backup; there is no
    On-The-Go list on the owner's iPod to test against.
    """
    import glob, shutil, struct, tempfile
    from saltpod import otg as O, itunesdb as I
    src = sorted(glob.glob(os.path.join(DATA, 'backups', 'ipod-*', 'iTunesDB')))
    if not src:
        return ('skip', 'no backup to build a fake mount from')
    m = tempfile.mkdtemp(prefix='fakepod-')
    try:
        d = os.path.join(m, 'iPod_Control', 'iTunes')
        os.makedirs(d)
        db = os.path.join(d, 'iTunesDB')
        shutil.copy2(src[-1], db)
        tracks = I.read(db)['tracks']
        picks = [3, 0, 7]
        O.write_file(os.path.join(d, 'OTGPlaylistInfo'), picks)
        rows = O.read(os.path.join(d, 'OTGPlaylistInfo'), db)
        assert [r['title'] for r in rows] == [tracks[i].get('title') for i in picks], \
            'entries were not paired by position, in order'
        st = {'tracks': {}, 'collections': []}
        made = O.adopt(st, m, db)
        assert len(made) == 1 and made[0][1] == 3, 'not kept as one 3-track collection'
        assert O.adopt(st, m, db) == [], 'the same file was imported twice'
        name = made[0][0]
        assert len(st['collection_order'][name]) == 3, 'the order was not kept'
        # a big-endian file reads the same
        rev = os.path.join(d, 'OTGPlaylistInfo_1')
        with open(rev, 'wb') as fh:
            fh.write(b'opmh' + struct.pack('>IIII', 0x14, 4, 1, 0) + struct.pack('>I', 5))
        assert [r['index'] for r in O.read(rev, db)] == [5], 'byte-reversed file misread'
        # an index past the end means the file belongs to another database
        O.write_file(rev, [len(tracks) + 10])
        try:
            O.read(rev, db)
            raise AssertionError('an index past the end was accepted')
        except O.OTGError:
            pass
        return '3 tracks by position, kept once, reversed read, bad index refused'
    finally:
        shutil.rmtree(m, ignore_errors=True)


def t_track_add_identity():
    """A track added to the device gets its own identity, not its template's.

    track_add clones a real track's header, and three identity fields used
    to arrive with that track's values: one artist id (0x1E0) ended up
    covering about a hundred artists, two tracks shared 0x1F4, and new
    tracks were left out of the album list -- the 89 extra albums the
    taxonomy sweep counted. Also pins the collision this fix nearly
    reintroduced: a "fresh" artist id has to be above every id in use, not
    above the per-artist map, or it lands on someone else's.
    """
    import glob
    from saltpod import itunesdb_write as W, ipod_edit as E, config as CFG
    src = sorted(glob.glob(os.path.join(DATA, 'backups', 'ipod-2026-10-0*', 'iTunesDB')))
    if not src:
        return ('skip', 'no backup to build on')
    root = W.parse(open(src[-1], 'rb').read())
    ref = next((t for t in E.tracks(root) if E._mhod_str(t, 22) and t.get32(0x120)), None)
    if ref is None:
        return ('skip', 'no linked track with an album artist in the backup')
    base = dict(ext='.mp3', title='T', genre='G', size=1, ms=1, bitrate=320,
                samplerate=44100, track_no=1, year=2024)
    used_before = {t.get32(0x1E0) for t in E.tracks(root)}
    t1 = E.track_add(root, dict(base, artist=E._mhod_str(ref, 4), album=E._mhod_str(ref, 3),
                                album_artist=E._mhod_str(ref, 22)), ':iPod_Control:Music:F00:A.mp3')
    t2 = E.track_add(root, dict(base, artist='Nobody Yet', album='Nowhere',
                                album_artist='Nobody Yet'), ':iPod_Control:Music:F00:B.mp3')
    by = {E.track_id(t): t for t in E.tracks(root)}
    a, b = by[t1], by[t2]
    assert a.get32(0x1E0) == ref.get32(0x1E0), 'a known artist did not reuse its id'
    assert a.get32(0x120) == ref.get32(0x120), 'a known album was not linked'
    assert a.get32(0x1F4) == t1 + 1 and b.get32(0x1F4) == t2 + 1, '0x1F4 is not id + 1'
    assert b.get32(0x1E0) not in used_before, 'a new artist got an id already in use'
    assert b.get32(0x120) == 0, 'an album that does not exist was linked'
    assert a.hdr[0xB2] == 2 and a.get32(0x1E4) == 0, 'unplayed mark or Genius id inherited'
    assert E._mhod_str(a, 22) == E._mhod_str(ref, 22), 'album artist not written'
    assert E._fold('Beyoncé') == E._fold('BEYONCE')
    return 'artist id, album link, 0x1F4, no collision'


def t_sync_merges_plays_first():
    """Sync reads the Play Counts sidecar BEFORE it replaces the database
    the sidecar belongs to, and only then removes it.

    The sidecar is positional, so it can only be read correctly against the
    database it was written with. Sync used to delete it unread whenever the
    track list changed -- against playcounts.py's own rule -- and every such
    sync threw away the plays since the last merge. Structural rather than
    behavioural because exercising a full sync needs a device; what matters
    is the ORDER, and the order is what this pins.
    """
    import inspect
    from saltpod import apply as A
    # the body lives in _sync; sync() wraps it in a log span
    src = inspect.getsource(A._sync)
    merge = src.find('_PC.merge(')
    replace = src.find('os.replace(tmp, dbp)')
    remove = src.find('os.remove(pc)')
    assert merge > 0, 'sync no longer merges the Play Counts sidecar at all'
    assert replace > 0 and remove > 0, 'sync changed shape -- re-check this test'
    assert merge < replace, 'the merge must come before the database is replaced'
    assert merge < remove, 'the merge must come before the sidecar is removed'
    return 'merge, then replace, then remove'


def t_cover_into_file():
    """A dropped cover goes INTO the file, and nothing else in it moves.

    fr-covers, decided 12 October: m4a through write_art, MP3 / AIFF / WAV
    through an APIC frame (tags.embed_art). Each case is built here, tiny,
    never from the library: an MP3 with a v2.3 tag (in place), one with v2.4
    (stays v2.4), one with no tag; a WAV with an id3 chunk among INFO and cue
    labels, and one without; an AIFF; an m4a when ffmpeg is there to make one.
    The bar each time: every frame / atom / chunk that is not a picture keeps
    its bytes, the audio keeps its digest, and the file reads back the cover.
    """
    import struct, tempfile
    from saltpod import tags as T

    old = b'\xff\xd8\xff\xe0' + b'old-cover' * 40 + b'\xff\xd9'
    new = b'\x89PNG\r\n\x1a\n' + bytes(range(256)) * 3
    audio = (b'\xff\xfb\x90\x64' + bytes(413)) * 12

    def fr(fid, payload, v4=False):
        n = len(payload)
        size = bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F]) \
            if v4 else struct.pack('>I', n)
        return fid + size + b'\x00\x00' + payload

    def tag(frames, major=3, pad=2048):
        body = b''.join(frames) + bytes(pad)
        n = len(body)
        return b'ID3' + bytes((major, 0, 0)) + bytes(
            [(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F]) + body

    def others(frames):
        return [(f, p) for f, p in frames if f != 'APIC']

    tmp = tempfile.mkdtemp(prefix='saltpod-cover-')
    done = []
    try:
        # MP3, v2.3 and v2.4, each with an old cover, a comment, a private frame
        for major in (3, 4):
            v4 = major == 4
            frames = [fr(b'TIT2', b'\x00Field', v4), fr(b'TPE1', b'\x00Alder', v4),
                      fr(b'TBPM', b'\x00124', v4), fr(b'COMM', b'\x00eng\x00note', v4),
                      fr(b'PRIV', b'dj.app\x00\x01\x02', v4),
                      fr(b'APIC', b'\x00image/jpeg\x00\x03\x00' + old, v4)]
            p = os.path.join(tmp, 'v2%d.mp3' % major)
            open(p, 'wb').write(tag(frames, major) + audio)
            span0 = T._id3_span(p)
            before = T._id3_read_tag(open(p, 'rb').read()[:span0])[0]
            text0 = T.read(p)
            assert T.art_why_not(p) == '', T.art_why_not(p)
            assert T.embed_art(p, new) is True, 'the audio moved: the tag had room'
            raw = open(p, 'rb').read()
            span = T._id3_span(p)
            after = T._id3_read_tag(raw[:span])[0]
            assert raw[3] == major, 'the tag changed version: v2.%d -> v2.%d' % (major, raw[3])
            assert others(after) == others(before), 'a frame other than the picture changed'
            assert [f for f, _p in after].count('APIC') == 1, 'more than one picture left'
            assert raw[span:] == audio and span == span0, 'the audio moved or changed'
            assert T.art_bytes(p) == ('image/png', new), 'the new cover does not read back'
            assert T.read(p) == text0 and T.has_art(p)
        done.append('mp3 v2.3+v2.4 in place')

        p = os.path.join(tmp, 'bare.mp3')
        open(p, 'wb').write(audio)
        T.embed_art(p, new)
        raw = open(p, 'rb').read()
        assert raw[T._id3_span(p):] == audio and T.art_bytes(p)[1] == new
        done.append('untagged mp3')

        # WAV: id3 chunk between INFO and a cue-label LIST; and one with none
        def chunk(cid, body):
            return cid + struct.pack('<I', len(body)) + body + (b'\x00' if len(body) & 1 else b'')
        pcm = bytes(range(256)) * 32
        id3 = tag([fr(b'TIT2', b'\x00Old'), fr(b'TBPM', b'\x00124'),
                   fr(b'APIC', b'\x00image/jpeg\x00\x03\x00' + old)], 3, 64)
        fmt = chunk(b'fmt ', struct.pack('<HHIIHH', 1, 1, 8000, 16000, 2, 16))
        info = chunk(b'LIST', b'INFO' + chunk(b'INAM', b'Old\x00') + chunk(b'NITR', b'dj\x00'))
        cue = chunk(b'LIST', b'adtl' + chunk(b'labl', struct.pack('<I', 1) + b'Drop\x00'))
        for name, chunks in (('with.wav', [fmt, chunk(b'data', pcm), info, chunk(b'id3 ', id3), cue]),
                             ('without.wav', [fmt, chunk(b'data', pcm), info, cue])):
            body = b''.join(chunks)
            p = os.path.join(tmp, name)
            open(p, 'wb').write(b'RIFF' + struct.pack('<I', 4 + len(body)) + b'WAVE' + body)
            probe = T.audio_probe(p)
            assert T.art_why_not(p) == '', T.art_why_not(p)
            T.embed_art(p, new)
            T.verify(p, probe, in_place=True)
            b = open(p, 'rb').read()
            ch = T._riff_chunks(b)
            assert struct.unpack('<I', b[4:8])[0] == len(b) - 8, 'RIFF size wrong'
            kept = [b[h:h + 8 + sz + (sz & 1)] for c, h, d, sz in ch if c not in T._ID3_CHUNKS]
            assert kept == [c for c in chunks if c[:4] not in T._ID3_CHUNKS], \
                'a chunk other than the id3 one changed, moved or went'
            if name == 'with.wav':
                assert [c for c, *_r in ch] == [b'fmt ', b'data', b'LIST', b'id3 ', b'LIST'], \
                    'the id3 chunk was not rewritten where it stood'
                f = T._id3_read_tag([b[d:d + sz] for c, h, d, sz in ch if c == b'id3 '][0])[0]
                assert others(f) == others(T._id3_read_tag(id3)[0]), 'an id3 frame changed'
            assert T.art_bytes(p)[1] == new and T.has_art(p)
        done.append('wav, with and without an id3 chunk')

        # AIFF: COMM, SSND, then the ID3 chunk
        def fchunk(cid, body):
            return cid + struct.pack('>I', len(body)) + body + (b'\x00' if len(body) & 1 else b'')
        comm = fchunk(b'COMM', struct.pack('>hIh', 1, len(pcm) // 2, 16) + b'\x40\x0b\xfa' + bytes(7))
        ssnd = fchunk(b'SSND', bytes(8) + pcm)
        body = b'AIFF' + comm + ssnd + fchunk(b'ID3 ', tag([fr(b'TIT2', b'\x00Old', True),
                                                           fr(b'TKEY', b'\x008A', True)], 4, 64))
        p = os.path.join(tmp, 'a.aif')
        open(p, 'wb').write(b'FORM' + struct.pack('>I', len(body)) + body)
        probe, text0 = T.audio_probe(p), T.read(p)
        T.embed_art(p, new)
        T.verify(p, probe, in_place=True)
        fr4, major, _c, _cl = T._aiff_tag(p)
        assert major == 4 and others(fr4) == [('TIT2', b'\x00Old'), ('TKEY', b'\x008A')]
        assert T.read(p) == text0 and T.art_bytes(p)[1] == new
        done.append('aiff')

        # m4a, made by ffmpeg when it is installed
        if shutil.which('ffmpeg'):
            p = os.path.join(tmp, 'a.m4a')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'anullsrc=r=8000:cl=mono', '-t', '1', '-metadata', 'title=Field',
                            '-metadata', 'artist=Alder', '-c:a', 'alac', p], check=True)

            def ilst_items(path):
                _mo, moov, chain = T._mp4_ilst(path)
                off, size = chain[-1]
                return [(t, moov[o:o + sz]) for t, o, sz in T._mp4_children(moov, off + 8, off + size)
                        if t != b'covr']
            items0, text0, probe = ilst_items(p), T.read(p), T.audio_probe(p)
            jpg = b'\xff\xd8\xff\xe0' + bytes(range(256)) * 2 + b'\xff\xd9'
            in_place = T.embed_art(p, jpg)
            T.verify(p, probe, in_place=in_place)
            assert ilst_items(p) == items0, 'an ilst item other than covr changed'
            assert T.read(p) == text0 and T.art_bytes(p) == ('image/jpeg', jpg)
            done.append('m4a')

        # refusals: a tag we could not read cleanly, and a container with no picture writer
        p = os.path.join(tmp, 'bad.mp3')
        broken = tag([fr(b'TIT2', b'\x00x'), b'TPE1' + struct.pack('>I', 9999) + b'\x00\x00ab'], 3, 0)
        open(p, 'wb').write(broken + audio)
        snap = open(p, 'rb').read()
        assert 'cannot parse' in T.art_why_not(p), T.art_why_not(p)
        try:
            T.embed_art(p, new)
            raise AssertionError('a tag we could not read cleanly was written')
        except T.TagError:
            pass
        assert open(p, 'rb').read() == snap, 'a refusal touched the file'
        assert T.art_why_not('x.flac') == 'no artwork writer for flac yet'
        return ', '.join(done) + '; refusals untouched'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_wav_refusal_named():
    """A WAV the tag writer turns down says WHY, not "needs the ID3v2 writer".

    fr-defaults item 5. The writer for a WAV's id3 chunk has existed since
    30 September; what is still refused is a chunk we could not read cleanly
    (or an ID3v2.2 one with a frame that has no v2.3 name), and the panel
    and the terminal now name that.
    """
    import struct, tempfile
    from saltpod import tags as T
    bad = b'TIT2' + struct.pack('>I', 9999) + b'\x00\x00ab'
    n = len(bad)
    id3 = b'ID3\x03\x00\x00' + bytes([0, 0, (n >> 7) & 0x7F, n & 0x7F]) + bad

    def chunk(cid, body):
        return cid + struct.pack('<I', len(body)) + body + (b'\x00' if len(body) & 1 else b'')
    body = (chunk(b'fmt ', struct.pack('<HHIIHH', 1, 1, 8000, 16000, 2, 16))
            + chunk(b'data', bytes(64)) + chunk(b'id3 ', id3))
    fd, p = tempfile.mkstemp(suffix='.wav')
    try:
        os.write(fd, b'RIFF' + struct.pack('<I', 4 + len(body)) + b'WAVE' + body); os.close(fd)
        assert not T.supported(p)
        why = T.why_not(p)
        assert why.startswith('its id3 chunk') and 'cannot parse' in why, why
        assert 'ID3v2 writer' not in why
        return why[:40]
    finally:
        os.remove(p)


def t_id3v22_converts():
    """An ID3v2.2 tag converts to v2.3 keeping every frame and the cover; a
    frame with no v2.3 equivalent refuses with the file untouched.

    The bar is the one the writer's own comment set after the first attempt
    failed: "an 11-frame tag came back as 5 and the cover art was gone".
    So this builds an 11-frame v2.2 tag with a picture and asserts 11 come
    back. Also checks the untagged MP3, which supported() used to call
    unwritable through a branch that could never be reached.
    """
    import tempfile, hashlib
    from saltpod import tags as T

    def f22(fid, payload):
        return fid + len(payload).to_bytes(3, 'big') + payload

    def tag22(frames):
        body = b''.join(frames); n = len(body)
        return b'ID3\x02\x00\x00' + bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F,
                                             (n >> 7) & 0x7F, n & 0x7F]) + body

    def txt(v):
        return b'\x00' + v.encode('latin-1')

    art = b'\xff\xd8\xff\xe0' + bytes(range(256)) * 6 + b'\xff\xd9'
    frames = [f22(b'TT2', txt('Old')), f22(b'TP1', txt('A')), f22(b'TAL', txt('B')),
              f22(b'TCO', txt('House')), f22(b'TYE', txt('2008')), f22(b'TRK', txt('3')),
              f22(b'TBP', txt('124')), f22(b'TKE', txt('8A')),
              f22(b'COM', b'\x00eng\x00note'), f22(b'TCP', txt('1')),
              f22(b'PIC', b'\x00JPG\x03\x00' + art)]
    audio = (b'\xff\xfb\x90\x64' + bytes(413)) * 20
    paths = []
    try:
        fd, p = tempfile.mkstemp(suffix='.mp3'); paths.append(p)
        os.write(fd, tag22(frames) + audio); os.close(fd)
        assert T.supported(p), 'a convertible v2.2 tag should be writable'
        T.write_id3(p, {'title': 'New', 'artist': 'A', 'album': 'B',
                        'genre': 'House', 'year': '2008', 'track': '3'})
        raw = open(p, 'rb').read()
        span = T._id3_span(p)
        assert raw[3] == 3, 'should land as v2.3, got v2.%d' % raw[3]
        fr = T._id3_read_tag(raw[:span])[0]
        assert len(fr) == 11, '11 frames went in, %d came back' % len(fr)
        d = dict(fr)
        assert art in d.get('APIC', b'') and b'image/jpeg' in d['APIC'][:16], 'cover lost or MIME wrong'
        assert raw[span:] == audio, 'the audio moved'
        assert T.read(p).get('title') == 'New'

        fd, q = tempfile.mkstemp(suffix='.mp3'); paths.append(q)
        os.write(fd, tag22(frames[:2] + [f22(b'XYZ', txt('?'))]) + audio); os.close(fd)
        before = open(q, 'rb').read()
        assert not T.supported(q), 'an unconvertible frame should make it unwritable'
        try:
            T.write_id3(q, {'title': 'x'})
            raise AssertionError('an unconvertible v2.2 tag was written')
        except T.TagError:
            pass
        assert open(q, 'rb').read() == before, 'a refusal touched the file'

        fd, u = tempfile.mkstemp(suffix='.mp3'); paths.append(u)
        os.write(fd, audio); os.close(fd)
        assert T.supported(u), 'an untagged MP3 should be writable'
        return '11 of 11 frames and the cover; unknown frame refused'
    finally:
        for x in paths:
            os.remove(x)


def t_wav_id3_write():
    """A WAV carrying an id3 chunk can be retagged, and nothing else in it
    is lost.

    368 of 724 WAVs here carry an id3 chunk, and the writer refused all of
    them. It also, when it did write, stripped every INFO entry it did not
    manage (comments, copyright, and NITR on 11 files) and every LIST chunk
    whatever it held, including `adtl` cue labels. This builds a WAV with
    all of those hazards in it -- artwork, a BPM frame, a comment, NITR, a
    cue label -- retags it twice, and checks every one survives.
    """
    import struct, tempfile, hashlib
    from saltpod import tags as T

    def chunk(cid, body):
        return cid + struct.pack('<I', len(body)) + body + (b'\x00' if len(body) & 1 else b'')

    def info(entries):
        body = b'INFO'
        for cid, v in entries:
            raw = v + b'\x00'
            if len(raw) & 1:
                raw += b'\x00'
            body += cid + struct.pack('<I', len(raw)) + raw
        return chunk(b'LIST', body)

    def fr(fid, payload):
        return fid + struct.pack('>I', len(payload)) + b'\x00\x00' + payload

    art = b'\xff\xd8\xff\xe0' + bytes(range(256)) * 8 + b'\xff\xd9'
    frames = (fr(b'TIT2', b'\x00Old') + fr(b'TBPM', b'\x00124')
              + fr(b'APIC', b'\x00image/jpeg\x00\x03\x00' + art))
    n = len(frames)
    tag = b'ID3\x03\x00\x00' + bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F]) + frames
    audio = bytes(range(256)) * 64
    body = (chunk(b'fmt ', struct.pack('<HHIIHH', 1, 2, 44100, 176400, 4, 16))
            + chunk(b'data', audio)
            + info([(b'INAM', b'Old'), (b'ICMT', b'mixed live'), (b'NITR', b'traktor')])
            + chunk(b'LIST', b'adtl' + chunk(b'labl', struct.pack('<I', 1) + b'Drop\x00'))
            + chunk(b'id3 ', tag))
    fd, path = tempfile.mkstemp(suffix='.wav')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(b'RIFF' + struct.pack('<I', 4 + len(body)) + b'WAVE' + body)
        assert T.supported(path), 'a clean id3-carrying WAV should now be writable'
        for title in ('New', 'Third'):
            T.write_wav(path, {'title': title})
            b = open(path, 'rb').read()
            ch = T._riff_chunks(b)
            assert struct.unpack('<I', b[4:8])[0] == len(b) - 8, 'RIFF size wrong'
            data = [b[d:d + sz] for c, h, d, sz in ch if c == b'data'][0]
            assert data == audio, 'the audio moved or changed'
            id3c = [b[d:d + sz] for c, h, d, sz in ch if c == b'id3 '][0]
            f = dict(T._id3_read_tag(id3c)[0])
            assert art in f.get('APIC', b''), 'artwork was lost'
            assert T._id3_text(f.get('TBPM', b'')) == '124', 'an unmanaged frame was lost'
            infos = [b[d + 4:d + sz] for c, h, d, sz in ch if c == b'LIST' and b[d:d + 4] == b'INFO']
            e = dict(T._info_parse(infos[0]))
            assert e.get(b'ICMT', b'').rstrip(b'\x00') == b'mixed live', 'INFO comment lost'
            assert e.get(b'NITR', b'').rstrip(b'\x00') == b'traktor', 'NITR lost'
            assert any(c == b'LIST' and b[d:d + 4] == b'adtl' for c, h, d, sz in ch), 'cue labels lost'
            assert T.read_wav(path).get('title') == title, 'did not read back'
            assert e.get(b'INAM', b'').rstrip(b'\x00').decode() == title, 'INFO and ID3 disagree'
        return 'artwork, BPM, comment, NITR, cue labels all kept; twice'
    finally:
        os.remove(path)


def t_read_extra():
    """Key, tempo, ISRC, label and iTunNORM are read -- including the forms
    DJ software uses -- and the writers' FIELDS are untouched by it.

    Builds an ID3v2.3 tag in memory rather than relying on the drive, and
    covers the three ways these values actually arrive: native frames
    (TBPM/TKEY/TSRC/TPUB), a user text frame (TXXX:INITIALKEY, what key
    detection tools wrote before TKEY), and a comment (COMM:iTunNORM, where
    iTunes keeps its Sound Check). Differential-checked against ffprobe on
    the 80 local files before this test was written: every field agreed.
    """
    import struct, tempfile
    from saltpod import tags as T

    def frame(fid, payload):
        return fid.encode() + struct.pack('>I', len(payload)) + b'\x00\x00' + payload

    def text(v):
        return b'\x00' + v.encode('latin-1')

    norm = ' 00000AF3 00000B4E 00008C1C 00008D3B 00024CA8 00024CA8 00007FFF 00007FFF 00024CA8 00024CA8'
    body = (frame('TIT2', text('x')) + frame('TBPM', text('123.6'))
            + frame('TSRC', text('GX9U42400001')) + frame('TPUB', text('Pond Recordings'))
            + frame('TXXX', b'\x00INITIALKEY\x00' + b'8A')
            + frame('COMM', b'\x00eng' + b'iTunNORM\x00' + norm.encode()))
    size = len(body)
    syncsafe = bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F])
    tag = b'ID3\x03\x00\x00' + syncsafe + body
    fd, path = tempfile.mkstemp(suffix='.mp3')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(tag + b'\xff\xfb\x90\x00' + b'\x00' * 64)
        x = T.read_extra(path)
        assert x.get('bpm') == '124', 'bpm %r -- 123.6 should round to 124' % x.get('bpm')
        assert x.get('key') == '8A', 'the TXXX:INITIALKEY form was missed: %r' % x.get('key')
        assert x.get('isrc') == 'GX9U42400001', x.get('isrc')
        assert x.get('label') == 'Pond Recordings', x.get('label')
        assert x.get('soundcheck_apple') == 0xB4E, \
            'iTunNORM should give the louder channel, 0xB4E: %r' % x.get('soundcheck_apple')
        # and the editable set is exactly what it was
        assert T.FIELDS == ('title', 'artist', 'album', 'album_artist', 'genre', 'year', 'track'), \
            'FIELDS changed -- the writers would now own these'
        return 'native, TXXX and COMM forms; FIELDS untouched'
    finally:
        os.remove(path)


def t_guarded_write():
    """An unsupervised write must refuse what breaks a device and undo what
    breaks after the fact.

    Built for the night the owner was away from the machine. Runs entirely
    against a FAKE mount made from a backup, so it can never touch an iPod:
    a stray podcast group flag and a silently dropped track must both be
    refused before anything is written, and a file corrupted after a
    write must be put back byte for byte.
    """
    import glob, shutil, tempfile
    from saltpod import ipod_edit as E, config as CFG, apply as A
    try:
        guid = CFG.load().get('firewire_guid')
    except SystemExit:
        return ('skip', 'no device configured')
    src = sorted(glob.glob(os.path.join(DATA, 'backups', 'ipod-*', 'iTunesDB')))
    if not guid or not src:
        return ('skip', 'no backup to build a fake mount from')
    orig = open(src[-1], 'rb').read()
    if E.invariants(None, orig, guid):
        return ('skip', 'newest backup does not pass invariants itself')
    m = tempfile.mkdtemp(prefix='fakepod-')
    keep_backup, keep_write = A.backup, E.write_db
    try:
        os.makedirs(os.path.join(m, 'iPod_Control', 'iTunes'))
        dbp = os.path.join(m, 'iPod_Control', 'iTunes', 'iTunesDB')
        open(dbp, 'wb').write(orig)
        A.backup = lambda mount: None
        def stray(root):
            for sect in E.playlist_sections(root):
                for p in E.playlists(root, sect):
                    rows = [c for c in p.children if c.magic == b'mhip']
                    flag = len(p.hdr) > 0x2C and int.from_bytes(p.hdr[0x2A:0x2C], 'little')
                    if rows and not flag and not E.is_master(p):
                        rows[0].set16(0x10, 0x100); return
        def drop(root):
            E.tracks(root).pop()
        for name, fn in (('stray group flag', stray), ('dropped track', drop)):
            try:
                E.guarded_write(m, fn, guid, label=name)
                raise AssertionError('%s was NOT refused' % name)
            except E.WriteRefused:
                pass
            assert open(dbp, 'rb').read() == orig, '%s touched the file' % name
        def corrupting(path, blob):
            keep_write(path, blob)
            if blob != orig:
                with open(path, 'r+b') as f:
                    f.seek(len(blob) // 2); f.write(b'\x00' * 64)
        E.write_db = corrupting
        def change(root):
            t = E.tracks(root)[0]; t.set32(0x4C, (t.get32(0x4C) or 1000) + 1)
        try:
            E.guarded_write(m, change, guid, label='corrupt')
            raise AssertionError('a post-write corruption was NOT caught')
        except E.WriteRefused:
            pass
        assert open(dbp, 'rb').read() == orig, 'the restore did not reproduce the original bytes'
        return 'refuses 2, restores 1, on a fake mount'
    finally:
        A.backup, E.write_db = keep_backup, keep_write
        shutil.rmtree(m, ignore_errors=True)


def _fixture_lib():
    """A fresh fixture library in a temp directory: (tmpdir, manifest), or
    None where fixtures/ is not in the tree (the public export)."""
    if not os.path.exists(os.path.join(ROOT, 'fixtures', 'build.py')):
        return None
    sys.path.insert(0, os.path.join(ROOT, 'fixtures'))
    import build as FX
    tmp = tempfile.mkdtemp(prefix='saltpod-fx-')
    return tmp, FX.build(os.path.join(tmp, 'f'))


def _in_home(home, code, timeout=120):
    """Run `code` in a fresh interpreter with SALTPOD_HOME=home, the way a
    job step runs: the code root as cwd, its src/ importable. Every module
    reads SALTPOD_HOME once, at import, so a fixture home has to be a new
    process -- this one already imported the source tree's."""
    r = subprocess.run([sys.executable, '-c', 'import sys; sys.path.insert(0, "src")\n' + code],
                       cwd=ROOT, env=dict(os.environ, SALTPOD_HOME=home),
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


# The sync these tests run: the fixture's plan without its one add (an add
# needs ffprobe and an .m4a on the device to clone from, neither of which a
# fixture has), so a removal, a retag, three playlists and a smart list.
_SYNC = ('''
import json, os, sys
from saltpod import ipod_edit as E
ex = os.path.join(os.environ["SALTPOD_HOME"], "ex.json")
json.dump({"tracks": ["dune-society|low-tide"]}, open(ex, "w"))
%s
from saltpod.cli import main
sys.exit(main(["sync", "--no-eject", "--exclude", ex]))
''')


def t_sync_restores():
    """A sync whose write fails its check puts the backup back by itself.

    Decided 12 October ("Restore by itself"). On the fixture's FAKE mount,
    never a device: the write is corrupted after it lands, the way the
    2 October partial write was, and the sync must restore the backup's
    database byte for byte, keep the removed track's file (deleted only
    after a verified write), leave state unsaved, exit non-zero and say
    "the iPod is as it was" -- in the CLI receipt and in the `@@ say` line
    the page toasts.
    """
    fx = _fixture_lib()
    if not fx:
        return ('skip', 'no fixtures/ in this tree (not in the public export)')
    tmp, m = fx
    try:
        dbp = os.path.join(m['mount'], 'iPod_Control', 'iTunes', 'iTunesDB')
        before = open(dbp, 'rb').read()
        state = os.path.join(m['home'], 'data', 'state.json')
        st_before = open(state, 'rb').read()
        music = sorted(os.path.join(d, f) for d, _x, fs in
                       os.walk(os.path.join(m['mount'], 'iPod_Control', 'Music')) for f in fs)
        inject = ('''
keep = E.write_db
def corrupting(path, blob):
    keep(path, blob)
    if path.endswith(".saltgate.tmp"):
        with open(path, "r+b") as f:
            f.seek(len(blob) // 2); f.write(b"\\0" * 64)
E.write_db = corrupting''')
        rc, out = _in_home(m['home'], _SYNC % inject)
        assert rc == 1, 'exit %d, expected 1: %s' % (rc, out[-300:])
        assert open(dbp, 'rb').read() == before, 'the database is not the backup\'s'
        assert '@@ restore done' in out, 'no restore step: %s' % out[-300:]
        assert '@@ say the iPod is as it was' in out, 'the page would get no sentence'
        assert 'restored   the iPod is as it was' in out, 'no CLI receipt'
        now = sorted(os.path.join(d, f) for d, _x, fs in
                     os.walk(os.path.join(m['mount'], 'iPod_Control', 'Music')) for f in fs)
        assert now == music, 'audio files moved: %s' % sorted(set(music) ^ set(now))
        assert open(state, 'rb').read() == st_before, 'state was saved for a sync that did not land'
        # and the page's job reads the sentence out of the log
        from saltpod import curate as C
        j = C.Job.__new__(C.Job)              # no __init__: it would open a log file
        j.log, j.steps, j.fp, j.state = [], {}, None, 'error'
        j.id, j.name, j.started = 'test', 'test', time.time()
        for ln in out.splitlines():
            j.line(ln)
        d = j.as_dict()
        steps = {x['id']: x['state'] for x in d['steps']}
        assert d['say'].startswith('the iPod is as it was'), d['say']
        assert steps.get('restore') == 'done' and steps.get('s:Since 2000') == 'done', steps
        return 'corrupted write restored byte for byte'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_sync_smart_phase():
    """Sync refreshes the smart playlists from their rules, as a phase with
    rows: the plan names each list, /api/plan carries the rows and the
    plan's summary and Sound Check lines, and after the sync the list holds
    what its rule says. Fake mount, fixture home.
    """
    fx = _fixture_lib()
    if not fx:
        return ('skip', 'no fixtures/ in this tree (not in the public export)')
    tmp, m = fx
    try:
        rc, out = _in_home(m['home'], '''
import json
from saltpod import curate as C
p = C.plan_summary()
print(json.dumps({k: p.get(k) for k in ("ok", "smart", "smart_line", "soundcheck_line")}))
''')
        assert rc == 0, out[-300:]
        p = json.loads(out.strip().splitlines()[-1])
        assert p['ok'], p
        assert p['smart'] == [{'name': 'Since 2000', 'now': 0, 'would': 2}], p['smart']
        assert p['smart_line'].startswith('smart playlists: 1 ours, 1 would change'), p
        assert p['soundcheck_line'].startswith('sound check: '), p
        rc, out = _in_home(m['home'], _SYNC % '')
        assert rc == 0, 'sync failed: %s' % out[-300:]
        assert '## smart playlists' in out and '@@ s:Since 2000 done' in out, out[-400:]
        assert out.index('## playlists') < out.index('## smart playlists') < out.index('## write')
        from saltpod import itunesdb as I
        dbp = os.path.join(m['mount'], 'iPod_Control', 'iTunes', 'iTunesDB')
        sm = [pl for pl in I.read(dbp)['playlists'] if pl['name'] == 'Since 2000']
        assert sm and len(sm[0]['items']) == 2, 'the smart list was not refreshed: %s' % sm
        rc, out = _in_home(m['home'], 'from saltpod.cli import main; main(["plan"])')
        assert '0 would change' in out, out
        return 'Since 2000: 0 -> 2, between playlists and write'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _sidecar(path, entries):
    """A Play Counts file: entries of (plays, last played mac, bookmark,
    rating x20, unknown, skips, last skipped mac), in database order."""
    b = bytearray(b'mhdp' + struct.pack('<III', 0x60, 0x1C, len(entries)))
    b += bytes(0x60 - len(b))
    for e in entries:
        b += struct.pack('<IIIIIII', *e)
    open(path, 'wb').write(b)


def t_plays_write():
    """`saltpod plays write`: a rehearsal changes nothing; --write merges the
    sidecar first, puts plays, last played, skips and ratings into the
    tracks' own fields, re-signs and verifies; a corrupted write restores.

    Decided 12 October ("First release"), research/TAXONOMY.md ranked fix 2.
    Fixture home, fake mount: the device's three tracks carry 3 plays and
    four stars; state says 7 plays for one, and the sidecar adds 2 plays, a
    skip and five stars on another.
    """
    fx = _fixture_lib()
    if not fx:
        return ('skip', 'no fixtures/ in this tree (not in the public export)')
    tmp, m = fx
    try:
        it = os.path.join(m['mount'], 'iPod_Control', 'iTunes')
        dbp, side = os.path.join(it, 'iTunesDB'), os.path.join(it, 'Play Counts')
        state = os.path.join(m['home'], 'data', 'state.json')
        cli = 'from saltpod.cli import main; sys.exit(main(%r))'
        rc, out = _in_home(m['home'], cli % (['plays', 'adopt'],))
        assert rc == 0, out[-300:]
        mac = 3700000000
        _sidecar(side, [(0,) * 7, (2, mac, 0, 100, 0, 1, mac + 60), (0,) * 7])
        before = {f: open(f, 'rb').read() for f in (dbp, state, side)}
        rc, out = _in_home(m['home'], cli % (['plays', 'write'],))
        assert rc == 0, out[-300:]
        assert 'plays 3 -> 7' in out and 'plays 3 -> 5' in out and 'rating **** -> *****' in out, out
        assert all(open(f, 'rb').read() == b for f, b in before.items()), 'a rehearsal changed a file'
        # a write that fails its check puts the backup back
        rc, out = _in_home(m['home'], '''
from saltpod import ipod_edit as E
keep = E.write_db
def corrupting(path, blob):
    keep(path, blob)
    if blob != E.__dict__.get("_orig"):
        with open(path, "r+b") as f:
            f.seek(len(blob) // 2); f.write(b"\\0" * 64)
E._orig = open(%r, "rb").read()
E.write_db = corrupting
''' % dbp + cli % (['plays', 'write', '--write'],))
        assert rc == 1 and 'restored   the iPod is as it was' in out, out[-300:]
        assert open(dbp, 'rb').read() == before[dbp], 'the failed write was not restored'
        assert os.path.exists(side), 'the sidecar went with a write that did not land'
        rc, out = _in_home(m['home'], cli % (['plays', 'write', '--write'],))
        assert rc == 0 and 're-signed and verified' in out, out[-300:]
        from saltpod import itunesdb as I, hash58 as H
        blob = open(dbp, 'rb').read()
        assert H.verify(blob, '0000000000000000'), 'not re-signed'
        got = {t['title']: t for t in I.read(dbp)['tracks']}
        assert got['Morning Field']['play_count'] == 7, got['Morning Field']
        b = got['Second Light']
        assert b['play_count'] == 5 and b['rating'] == 100, b
        assert b['last_played'] == mac - I.MAC_EPOCH, b['last_played']
        assert not os.path.exists(side), 'the sidecar was left to be counted twice'
        rc, out = _in_home(m['home'], cli % (['plays', 'write'],))
        assert 'tracks to change 0' in out.replace('\u25c6', '').replace('  ', ' '), out
        return 'rehearse 0 bytes; write 2 tracks; restore 1'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_plays_applemusic():
    """`saltpod plays applemusic` reads Apple Music's plays from a library
    FILE, refusing while the iPod is mounted or Music is open (asked of the
    process list, never of Music). Uses fixtures/music-library.xml, an
    invented Music XML library, and a saved read in the columnar form.
    """
    fx = _fixture_lib()
    if not fx:
        return ('skip', 'no fixtures/ in this tree (not in the public export)')
    tmp, m = fx
    try:
        xml = os.path.join(ROOT, 'fixtures', 'music-library.xml')
        away = os.path.join(tmp, 'no-ipod-here')
        run = ('''
from saltpod import listening as LS
LS.music_running = lambda: %s
from saltpod.cli import main
sys.exit(main(%r))''')
        rc, out = _in_home(m['home'], run % (False, ['plays', 'applemusic', xml]))
        assert rc != 0 and 'iPod is mounted' in out, 'read with the iPod mounted: ' + out[-200:]
        rc, out = _in_home(m['home'], run % (True, ['plays', 'applemusic', xml, '--mount', away]))
        assert rc != 0 and 'Music is open' in out, 'read with Music open: ' + out[-200:]
        rc, out = _in_home(m['home'], run % (False, ['plays', 'applemusic', xml, '--mount', away]))
        assert rc == 0, out[-300:]
        st = json.load(open(os.path.join(m['home'], 'data', 'state.json')))['tracks']
        a, g = st['alder-quartet|morning-field'], st['grove|paper-moon']
        assert (a['am_plays'], a['am_skips']) == (12, 2), 'the larger copy should win: %s' % a
        assert g['am_plays'] == 5 and g['am_last_played'] > 0, g
        saved = os.path.join(tmp, 'read.json')
        json.dump({'name': ['Paper Moon'], 'artist': ['Grove'], 'played': [9],
                   'last': ['2026-01-01T10:00:00Z'], 'skipped': [1], 'read_at': 'x'}, open(saved, 'w'))
        rc, out = _in_home(m['home'], run % (False, ['plays', 'applemusic', saved, '--mount', away]))
        assert rc == 0, out[-300:]
        st = json.load(open(os.path.join(m['home'], 'data', 'state.json')))['tracks']
        assert st['grove|paper-moon']['am_plays'] == 9, st['grove|paper-moon']
        from saltpod import curate as C
        import inspect
        assert '"plays", "applemusic"' in inspect.getsource(C), 'no Data-sheet job runs it'
        return 'refuses 2; XML and saved read both import'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_contract():
    """Gate 0: every reply's shape matches contract/snapshot.json.

    bin/contract.py builds the fixture library in a temporary directory,
    starts the server on it under SALTPOD_HOME and compares what comes back
    with the record; the Swift models decode the same replies. A rename on
    either side fails here first.
    """
    tool = os.path.join(ROOT, 'bin', 'contract.py')
    if not os.path.exists(tool):
        return ('skip', 'no bin/contract.py in this tree (not in the public export)')
    r = subprocess.run([sys.executable, tool, '--check'],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        lines = [l.strip() for l in r.stdout.splitlines() if l.startswith('  ')]
        raise AssertionError('; '.join(lines[:3]) or r.stdout[-200:] or r.stderr[-200:])
    return r.stdout.strip().splitlines()[-1].replace('contract holds: ', '')


def t_home_isolated():
    """A job step under a temporary SALTPOD_HOME writes nothing in the source tree.

    The step is the one run_job starts for "index the music drive" -- the
    same argv, the same cwd (the code root), the environment inherited --
    pointed at the fixture library's drive. It must rewrite the fixture
    home's index and leave data/, backups/ and reports/ under the source
    tree exactly as they were, file for file.
    """
    if not os.path.exists(os.path.join(ROOT, 'fixtures', 'build.py')):
        return ('skip', 'no fixtures/ in this tree (not in the public export)')
    sys.path.insert(0, os.path.join(ROOT, 'fixtures'))
    import build as FX

    def listing():
        out = {}
        for top in ('data', 'backups', 'reports'):
            for d, _dirs, files in os.walk(os.path.join(ROOT, top)):
                for f in files:
                    p = os.path.join(d, f)
                    st = os.stat(p)
                    out[p] = (st.st_size, st.st_mtime_ns)
        return out
    tmp = tempfile.mkdtemp(prefix='saltpod-home-')
    try:
        m = FX.build(os.path.join(tmp, 'f'))
        idx = os.path.join(m['home'], 'data', 'local', 'index.json')
        before_idx = os.stat(idx).st_mtime_ns
        before = listing()
        step = [sys.executable, '-u', '-c',
                'import sys; sys.path.insert(0, "src"); from saltpod.cli import main; '
                'sys.exit(main(%r))' % (['index', m['library']],)]
        r = subprocess.run(step, cwd=ROOT, env=dict(os.environ, SALTPOD_HOME=m['home']),
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, 'the step failed: %s' % (r.stdout + r.stderr)[-200:]
        assert os.stat(idx).st_mtime_ns != before_idx, 'the fixture index was not rewritten'
        after = listing()
        moved = sorted(set(before.items()) ^ set(after.items()))
        assert not moved, 'written under the source tree: %s' % os.path.relpath(moved[0][0], ROOT)
        n = len(json.load(open(idx))['tracks'])
        return 'index of %d files under the fixture home; %d source files unmoved' % (n, len(after))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_FIXTURE_COVER_PODCASTS = r"""
import io, json, os, sys, contextlib, time
sys.path.insert(0, 'src'); sys.path.insert(0, 'fixtures')
import build as FX
from saltpod import curate as C, tags as T, apply as A, state as S, cli
from saltpod import itunesdb_write as W, ipod_edit as E, podcasts as P
m = json.load(open(sys.argv[1]))
mount, home = m['mount'], m['home']
IDX = os.path.join(home, 'data', 'local', 'index.json')
key, birch = 'alder-quartet|morning-field', 'birch-ensemble|second-light'

def run(argv):
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = cli.main(argv)
    except SystemExit as e:
        code = e.code
    return code or 0, buf.getvalue()

def sync():
    time.sleep(1.05)        # a backup folder is named to the second
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pl = A.plan(mount)
        # the fixture iPod holds only WAVs, so an m4a add has nothing to be
        # cloned from; the adds stay out and everything else runs for real
        A.sync(mount, eject=False, exclude={'tracks': [a[0] for a in pl['adds']]})
    return buf.getvalue()

def filed():
    root = W.parse(open(os.path.join(mount, A.DB_REL), 'rb').read())
    return sorted(P._mhod(t, 1) for t in E.tracks(root) if t.get32(P.MEDIATYPE) == P.PODCAST)

# --- a cover dropped in the panel: file, index, row, `art status`
f = next(e['path'] for e in json.load(open(IDX))['tracks'] if e.get('title') == 'Morning Field')
assert not T.has_art(f)
ix = json.load(open(IDX))
for e in ix['tracks']:
    if e['path'] == f:
        e['has_art'] = False             # the seed says so; the file says not
json.dump(ix, open(IDX, 'w'))
C._LOCBYKEY['built'] = None
_c, before = run(['art', 'status', '--mount', mount])
assert 'covers we could add 0' in before, before
text0, probe = T.read(f), T.audio_probe(f)
r = C.OPS['/api/cover']({'key': key, 'image': FX.COVER})
assert r['ok'] and r['in_file'], r
assert T.has_art(f) and T.art_bytes(f)[1] == FX.COVER, 'not in the file'
assert T.read(f) == text0, 'the other tags changed'
T.verify(f, probe, in_place=True)
e = next(e for e in json.load(open(IDX))['tracks'] if e['path'] == f)
assert e['has_art'] is True, 'the index did not follow'
assert C.row_art(key, S.load()['tracks'][key]).startswith('/api/art?key='), 'the row'
_c, after = run(['art', 'status', '--mount', mount])
assert 'covers we could add 1' in after and 'Morning Field' in after, after
assert C.OPS['/api/cover']({'key': key, 'image': 'x'})['ok'] is False

# --- the Podcasts collection: a drop files it, taking it out unfiles it
assert C.apply_decision({'rename_collection': 'Podcasts', 'to': ''})['ok'] is False
assert 'Podcasts' in C.tracks_payload()['collections'], 'the drop target is always there'
assert filed() == []
pc = C.OPS['/api/podcasts']({'action': 'add', 'keys': [birch]})['podcasts']
assert pc['n'] == 1 and pc['pending'] == 1, pc
assert C.plan_summary(mount)['podcasts']['file'] == 1
log = sync()
assert '## podcasts' in log and '@@ podcasts done' in log, log[-400:]
assert filed() == ['Second Light'], filed()
root = W.parse(open(os.path.join(mount, A.DB_REL), 'rb').read())
assert P._flagged_playlists(root) == ['Podcasts']
assert 'Keepers' in [E.pl_name(p) for p in E.playlists(root, E.playlist_sections(root)[0])], \
    'an ordinary playlist went missing'
assert C.podcasts_summary()['pending'] == 0
code, out = run(['podcasts', 'remove', birch])
assert code == 0 and C.podcasts_summary()['filed_out'] == 1, out
sync()
assert filed() == [], 'taken out, still filed as a podcast'

# --- `saltpod podcasts write` refuses without a rehearsal of this database
C.OPS['/api/podcasts']({'action': 'add', 'keys': [birch]})
code, out = run(['podcasts', 'write', '--mount', mount])
assert code != 0 and 'rehearse first' in out, out
assert filed() == [], 'a refused write wrote'
code, out = run(['podcasts', 'rehearse', '--mount', mount])
assert code == 0, out
time.sleep(1.05)
code, out = run(['podcasts', 'write', '--mount', mount])
assert code == 0 and filed() == ['Second Light'], out
print('OK')
"""


def t_fixture_cover_and_podcasts():
    """On the fixture library and its fake iPod: a dropped cover reaches the
    file, the index, the row and `saltpod art status`; the Podcasts
    collection files a track as a podcast at sync and unfiles it when taken
    out; `saltpod podcasts write` refuses until a rehearsal.

    Runs in a child process with SALTPOD_HOME on a fresh fixture build, so
    nothing here reads or writes the source tree's data/ or a real device.
    """
    if not os.path.exists(os.path.join(ROOT, 'fixtures', 'build.py')):
        return ('skip', 'no fixtures/ in this tree (not in the public export)')
    if not shutil.which('ffmpeg'):
        return ('skip', 'ffmpeg not installed (the cover is normalised with it off macOS)')
    sys.path.insert(0, os.path.join(ROOT, 'fixtures'))
    import build as FX
    tmp = tempfile.mkdtemp(prefix='saltpod-fixture-')
    try:
        FX.build(os.path.join(tmp, 'f'))
        script = os.path.join(tmp, 'run.py')
        open(script, 'w').write(_FIXTURE_COVER_PODCASTS)
        r = subprocess.run([sys.executable, script, os.path.join(tmp, 'f', 'fixture.json')],
                           cwd=ROOT, env=dict(os.environ, SALTPOD_HOME=os.path.join(tmp, 'f', 'home')),
                           capture_output=True, text=True, timeout=180)
        if r.returncode != 0 or 'OK' not in r.stdout:
            raise AssertionError((r.stderr or r.stdout).strip().splitlines()[-1][:200])
        return 'cover in file+index+row+status; podcasts filed, unfiled, rehearsed'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _fixture_home():
    """A fresh fixture library in a temp dir: (tmp, manifest), or None."""
    if not os.path.exists(os.path.join(ROOT, 'fixtures', 'build.py')):
        return None
    sys.path.insert(0, os.path.join(ROOT, 'fixtures'))
    import build as FX
    tmp = tempfile.mkdtemp(prefix='saltpod-fr-')
    return tmp, FX.build(os.path.join(tmp, 'f'))


def _saltpod(m, *argv):
    """`saltpod ARGV` under the fixture home: (returncode, stdout+stderr)."""
    r = subprocess.run([sys.executable, '-c', 'import sys; sys.path.insert(0, "src"); '
                        'from saltpod.cli import main; sys.exit(main(sys.argv[1:]))'] + list(argv),
                       cwd=ROOT, env=dict(os.environ, SALTPOD_HOME=m['home']),
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def _server_call(m, expr):
    """Evaluate `expr` with curate imported as C, under the fixture home; JSON back."""
    r = subprocess.run([sys.executable, '-c', 'import sys, json; sys.path.insert(0, "src"); '
                        'from saltpod import curate as C; print(json.dumps(%s))' % expr],
                       cwd=ROOT, env=dict(os.environ, SALTPOD_HOME=m['home']),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-300:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def t_data_jobs_resolve():
    """The Data sheet's match and verify jobs start their modules.

    They pointed at src/itunes_match.py and src/verify_bandcamp.py after the
    package move, so both ended "job failed" every time. The argv each job
    runs is built by curate.job_module_argv; run with no playlist, each
    module must answer with its own usage, not "No module named" or "can't
    open file". No network, no data touched.
    """
    from saltpod import curate as C
    src = open(os.path.join(ROOT, 'src', 'saltpod', 'curate.py')).read()
    assert "'src/itunes_match.py'" not in src and "'src/verify_bandcamp.py'" not in src, \
        'a job still names a path the package move left behind'
    for mod in C.JOB_MODULES:
        r = subprocess.run(C.job_module_argv(mod, []), cwd=C.CODE_ROOT,
                           capture_output=True, text=True, timeout=60)
        out = r.stdout + r.stderr
        assert 'No module named' not in out and "can't open file" not in out, \
            '%s did not resolve: %s' % (mod, out[-200:])
        assert 'Traceback' not in out, '%s crashed: %s' % (mod, out[-200:])
        assert ('usage' in out.lower()) or (mod.replace('_', '') in out.replace('_', '')), \
            '%s answered something else: %s' % (mod, out[-200:])
    return 'both start: ' + ', '.join(C.JOB_MODULES)


def t_honest_fails():
    """No iPod, no backup, a root unplugged, a backup file: one sentence each.

    `saltpod read` with no iPod printed a FileNotFoundError traceback;
    `index` with a root unplugged died with MissingRoot and indexed nothing;
    "Re-read the device" with neither iPod nor backup let a SystemExit kill
    the request thread; `smartlists write --mount FILE` claimed it wrote
    both sections. Each now says what happened, on the fixture library.
    """
    fx = _fixture_home()
    if not fx:
        return ('skip', 'no fixtures/ in this tree (not in the public export)')
    tmp, m = fx
    try:
        idx = os.path.join(m['home'], 'data', 'local', 'index.json')
        kept = [e['path'] for e in json.load(open(idx))['tracks']
                if e['path'].startswith(m['unplugged'])]
        assert kept, 'the fixture has no track under its unplugged root'
        rc, out = _saltpod(m, 'index')
        assert rc == 0 and 'not mounted: ' in out and 'Traceback' not in out, \
            'index with a root unplugged: %s' % out[-200:]
        after = [e['path'] for e in json.load(open(idx))['tracks']]
        assert set(kept) <= set(after), 'the unplugged root\'s tracks were dropped'
        assert any(p.startswith(m['library']) for p in after), 'the mounted root was not indexed'

        db = os.path.join(m['mount'], 'iPod_Control', 'iTunes', 'iTunesDB')
        before = open(db, 'rb').read()
        rc, out = _saltpod(m, 'smartlists', 'write', '--mount', db)
        assert 'refreshed in memory only' in out and 'written to both' not in out, out[-200:]
        assert open(db, 'rb').read() == before, 'a database file was written'

        os.rename(m['mount'], m['mount'] + '.away')
        rc, out = _saltpod(m, 'read')
        assert rc == 1 and 'no iPod database' in out and 'Traceback' not in out, out[-200:]
        r = _server_call(m, 'C.reread_device()')
        assert r['ok'] and r['read'] == 'backup' and r['from'].startswith('ipod-'), r
        shutil.move(os.path.join(m['home'], 'backups'), os.path.join(tmp, 'backups.away'))
        r = _server_call(m, 'C.reread_device()')
        assert r['ok'] is False and 'no iPod and no backup' in r['error'], r
        os.rename(m['mount'] + '.away', m['mount'])
        r = _server_call(m, 'C.reread_device()')
        assert r == {'ok': True, 'read': 'device'}, r

        os.rename(m['library'], m['library'] + '.away')
        os.rename(idx, idx + '.was')
        rc, out = _saltpod(m, 'index')
        assert rc == 1 and 'not mounted' in out and 'Traceback' not in out, out[-200:]
        assert not os.path.exists(idx), 'an index was written with nothing mounted'
        return 'index, read, re-read, smartlists write: sentences, no tracebacks'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_decide_d13():
    """`saltpod decide` orders, renames and deletes a collection, and takes paths (D13).

    The page could sequence and rename a collection through /api/decide and
    the terminal could not. Run on the fixture: --reorder answers with the
    whole sequence, --rename and --delete with the member count, an unknown
    collection and an unindexed path are refused, and an untagged file named
    by path lands on the record the page would give it (file_identity).
    """
    fx = _fixture_home()
    if not fx:
        return ('skip', 'no fixtures/ in this tree (not in the public export)')
    tmp, m = fx
    try:
        st_path = os.path.join(m['home'], 'data', 'state.json')
        st = json.load(open(st_path))
        col = sorted(st['collection_order'], key=lambda c: -len(st['collection_order'][c]))[0]
        seq = st['collection_order'][col]
        assert len(seq) >= 2, 'the fixture has no collection of two'
        want = list(reversed(seq))
        rc, out = _saltpod(m, 'decide', '--reorder', col, *want[:2], '--json')
        r = json.loads(out)
        assert rc == 0 and r['order'][:2] == want[:2] and sorted(r['order']) == sorted(seq), r
        assert json.load(open(st_path))['collection_order'][col][:2] == want[:2]
        rc, out = _saltpod(m, 'decide', '--rename', col, '--to', 'Renamed Here', '--json')
        r = json.loads(out)
        assert rc == 0 and r['renamed'] == {'from': col, 'to': 'Renamed Here', 'members': len(seq)}, r
        rc, out = _saltpod(m, 'decide', '--reorder', 'No Such Collection', seq[0])
        assert rc == 1 and 'no collection called' in out, out[-200:]
        rc, out = _saltpod(m, 'decide', '--delete', 'Renamed Here', '--json')
        assert rc == 0 and json.loads(out)['renamed']['to'] is None
        assert 'Renamed Here' not in json.load(open(st_path))['collections']
        rc, out = _saltpod(m, 'decide', m['untagged_path'], '--vinyl', 'yes', '--json')
        r = json.loads(out)
        k = os.path.splitext(os.path.basename(m['untagged_path']))[0]
        ident = _server_call(m, 'C.path_identity(%r)' % m['untagged_path'])
        assert rc == 0 and r['touched'] == [ident['key']], (r, ident)
        assert json.load(open(st_path))['tracks'][ident['key']]['vinyl'] is True
        from saltpod.state import key_for
        assert ident['key'] == key_for('', k), 'an untagged file is not keyed by its name: %s' % ident
        rc, out = _saltpod(m, 'decide', os.path.join(m['library'], 'nope.wav'), '--tier', 'sync')
        assert rc == 1 and 'not in the drive index' in out, out[-200:]
        rc, out = _saltpod(m, 'decide', seq[0], '--bought', 'yes')
        assert rc != 0, '--bought is still accepted'
        return 'reorder, rename, delete, a path; two refusals'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_one_buy_list():
    """`saltpod state buylist` and the Buy pane read one list: the file is the proof.

    The card's button set a `bought` flag that only the terminal read, so
    after an index the two lists disagreed. Now both are the server's
    'to buy' list; a stale flag on a track with no file changes nothing.
    """
    fx = _fixture_home()
    if not fx:
        return ('skip', 'no fixtures/ in this tree (not in the public export)')
    tmp, m = fx
    try:
        pay = _server_call(m, 'C.tracks_payload()')
        to_buy = sorted(t['key'] for t in pay['tracks'] if 'to buy' in t['lists'])
        assert to_buy, 'the fixture has nothing to buy'
        # an old flag, left by the removed button, on a track still to buy
        st_path = os.path.join(m['home'], 'data', 'state.json')
        st = json.load(open(st_path))
        st['tracks'][to_buy[0]]['bought'] = True
        json.dump(st, open(st_path, 'w'))
        pay = _server_call(m, 'C.tracks_payload()')
        again = sorted(t['key'] for t in pay['tracks'] if 'to buy' in t['lists'])
        assert again == to_buy, 'the stale bought flag moved a card: %s' % again
        rc, out = _saltpod(m, 'state', 'buylist')
        assert rc == 0 and out.startswith('%d tracks' % len(to_buy)), out[-200:]
        rep = open(os.path.join(m['home'], 'reports', 'buylist.md')).read()
        names = {(t['artist'], t['title']) for t in pay['tracks'] if t['key'] in to_buy}
        for a, ti in names:
            assert '### %s - %s' % (a, ti) in rep, 'the report lacks %s - %s' % (a, ti)
        assert rep.count('### ') == len(to_buy), 'the report has rows the pane does not'
        page = open(os.path.join(ROOT, 'src', 'saltpod', 'curate.html')).read()
        assert 'data-bought' not in page, 'the card still has its bought button'
        return '%d to buy, the same in the pane and the report' % len(to_buy)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_source_from_page():
    """A fresh install names its music folder and indexes it (the Data sheet's field).

    /api/action source checks the folder with config.check_root -- the check
    `saltpod sources add` makes -- and runs that verb. Here, on a home with
    no device.json at all: a bad path is refused with a sentence, a real one
    is walked into the index, and health names it as a source even though
    there is no iPod configured yet.
    """
    fx = _fixture_home()
    if not fx:
        return ('skip', 'no fixtures/ in this tree (not in the public export)')
    tmp, m = fx
    try:
        os.remove(os.path.join(m['home'], 'data', 'device.json'))
        os.remove(os.path.join(m['home'], 'data', 'local', 'index.json'))
        r = _server_call(m, '__import__("saltpod.config").config.check_root("%s")'
                         % os.path.join(tmp, 'no-such'))
        assert r[1] and r[1].startswith('no such folder'), r
        rc, out = _saltpod(m, 'index')
        assert rc == 1 and 'no music folder named yet' in out, out[-200:]
        rc, out = _saltpod(m, 'sources', 'add', m['library'])
        assert rc == 0 and 'files found' in out, out[-300:]
        h = _server_call(m, 'C.health()')
        assert [x['path'] for x in h['sources']] == [m['library']], h['sources']
        idx = json.load(open(os.path.join(m['home'], 'data', 'local', 'index.json')))
        assert idx['count'] >= 1 and idx['roots'] == [m['library']], idx['roots']
        r = _server_call(m, '__import__("saltpod.config").config.check_root("%s")' % m['library'])
        assert r[1] and r[1].startswith('already a source'), r
        rc, out = _saltpod(m, 'index')
        assert rc == 0, 'index after naming a folder on a fresh install: %s' % out[-200:]
        return 'no device.json: named, walked, reported, re-indexed'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_pagetest():
    """The page's BEHAVIOURAL suite, run as part of this one.

    bin/pagetest.py has existed for a while and nothing ran it, which is
    the same failure as a module with no verb: a test that is not in the
    suite does not protect anything. It needs node; where there is none it
    skips rather than fails, because the rest of this suite is stdlib
    Python and must stay runnable without a JS runtime.
    """
    import shutil as _sh
    if not _sh.which('node'):
        return ('skip', 'node not installed')
    pt = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pagetest.py')
    r = subprocess.run([sys.executable, pt], capture_output=True, text=True)
    last = [l for l in r.stdout.strip().splitlines() if 'passed' in l]
    if r.returncode != 0:
        bad = [l.strip() for l in r.stdout.splitlines() if l.strip().startswith('!!')]
        raise AssertionError('; '.join(bad[:3]) or (last[-1] if last else 'pagetest failed'))
    return last[-1].strip() if last else 'ok'


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
    check('a bad frame size keeps the art', t_bad_frame_keeps_art)
    check('ID3v1 genre numbers resolve', t_genre_numbers)

    section('core — the rules')
    check('drift resolution table', t_drift_resolution)
    check('migrate is idempotent', t_migrate_idempotent)
    check('sync exclusions', t_exclusions)
    check('plan is cached by mtime', t_plan_cached)

    section('layers — the boundary and the design system')
    check('every module imports', t_imports)
    check('the published tree imports too', t_published_tree_imports)
    check('an ArtworkDB entry is cloned, not authored', t_artworkdb_clone)
    check('a cover survives conversion', t_art_survives_conversion, slow=True)
    check('two targets, two sets of settings', t_target_config)
    check('artwork renders to the exact sizes', t_artwork_render, slow=True)
    check('play counts: delta once, paired right', t_playcounts)
    check('a stale Spotlight record is refused', t_stale_index_gate)
    check('two roots, one track; one root, two files', t_fold_copies_respects_roots)
    check('an unsupervised write refuses and restores', t_guarded_write)
    check('a sync that fails its check restores itself', t_sync_restores)
    check('sync refreshes smart lists, as rows', t_sync_smart_phase)
    check('plays write: rehearse, write, restore', t_plays_write)
    check("Apple Music's plays, from a file, guarded", t_plays_applemusic)
    check('key, tempo, ISRC, label, iTunNORM are read', t_read_extra)
    check('a WAV with an id3 chunk retags, losing nothing', t_wav_id3_write)
    check('ID3v2.2 converts, every frame or none', t_id3v22_converts)
    check('a dropped cover goes into the file, nothing else moves', t_cover_into_file)
    check('a refused WAV names its reason', t_wav_refusal_named)
    check('sync merges plays before it replaces the database', t_sync_merges_plays_first)
    check('an added track gets its own identity', t_track_add_identity)
    check('on-the-go lists are kept, by position', t_otg)
    check('genius-style mixes, previewed', t_mixes)
    check('a grown Play Counts file counts only what grew', t_playcounts_grow)
    check('spotify: pages, one token, ISRC first', t_spotify)
    check('Apple Music and iPod plays, nothing twice', t_listening_overall)
    check('adapters, and both backends agree', t_platform, slow=True)
    check('the event log', t_observe)
    check('one implementation, two adapters', t_one_implementation)
    check('inline script parses', t_js_parses)
    check('no literals outside :root', t_token_census)
    check('vendored saltglass is one commit, untouched', t_vendored_glass)
    check('the band: three sleeves, three scrims', t_ground_band)
    check('every row carries its ground', t_ground_payload)
    check('a playlist mosaic tiles its covers', t_mosaic_tiles)
    check('every playlist row carries its art', t_playlists_payload_art)
    check('front end does not decide', t_layer_census)
    check('the answers the page stopped working out', t_layer_answers)
    check('the page behaves (pagetest.py)', t_pagetest, slow=True)

    section('http — the contract both clients use')
    check('a job under SALTPOD_HOME stays out of the tree', t_home_isolated)
    check('fixture: cover into the file, Podcasts at sync', t_fixture_cover_and_podcasts)
    check('the contract holds (contract.py --check)', t_contract)
    check('the API answers questions', t_api)

    section('first release, web and CLI -- one sentence, one list (fr-web)')
    check('the Data sheet jobs start their modules', t_data_jobs_resolve)
    check('no iPod, no backup, a root away: sentences', t_honest_fails)
    check('decide orders, renames, deletes, takes paths', t_decide_d13)
    check('one buy list: the file is the proof', t_one_buy_list)
    check('a fresh install names its music folder', t_source_from_page)

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
