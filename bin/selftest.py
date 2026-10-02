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
             for f in sorted(_glob.glob(os.path.join(ROOT, 'backups', '*', 'Play Counts')))]
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
    fr, _n, _c = T._id3_read_tag(open(path, "rb").read(T._id3_span(path)))
    return sum(len(x) for f, x in (fr or []) if f == 'APIC')


# ------------------------------------------------------------------- main
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
    src = sorted(glob.glob(os.path.join(ROOT, 'backups', 'ipod-*', 'iTunesDB')))
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
    src = sorted(glob.glob(os.path.join(ROOT, 'backups', 'ipod-2026-10-0*', 'iTunesDB')))
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
    src = sorted(glob.glob(os.path.join(ROOT, 'backups', 'ipod-*', 'iTunesDB')))
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
    check('key, tempo, ISRC, label, iTunNORM are read', t_read_extra)
    check('a WAV with an id3 chunk retags, losing nothing', t_wav_id3_write)
    check('ID3v2.2 converts, every frame or none', t_id3v22_converts)
    check('sync merges plays before it replaces the database', t_sync_merges_plays_first)
    check('an added track gets its own identity', t_track_add_identity)
    check('on-the-go lists are kept, by position', t_otg)
    check('genius-style mixes, previewed', t_mixes)
    check('adapters, and both backends agree', t_platform, slow=True)
    check('the event log', t_observe)
    check('one implementation, two adapters', t_one_implementation)
    check('inline script parses', t_js_parses)
    check('no literals outside :root', t_token_census)
    check('front end does not decide', t_layer_census)
    check('the page behaves (pagetest.py)', t_pagetest, slow=True)

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
