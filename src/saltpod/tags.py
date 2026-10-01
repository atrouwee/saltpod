"""Write tags into the file on disk, without moving one byte of audio.

WHY NOT FFMPEG. `ffmpeg -c copy -map 0` is the usual answer and it is the
wrong one. Measured on real files off the drive (research/TAG-WRITING.md):
on MP3 it prepends a Xing/LAME frame that was not there and the decoded
audio MD5 changes; on M4A it drops the 485 KB `free` atom and 36 KB of the
`moov` it did not understand. It is a remuxer -- it rebuilds the container
from what it recognises and silently discards the rest.

This module patches instead, which is the same rule `itunesdb.py` follows
and the same one CONTRIBUTING states: never regenerate what you can patch.

THE GUARANTEE, and it is checked rather than claimed: after a write, the
bytes of the audio payload are identical and start at the same offset. See
`verify()` and `python3 -m saltpod.tags selftest`.

Containers are added in the order the drive actually needs them. Of 581
untagged files: WAV 366, MP3 186, M4A 21, AIF 8, FLAC 0.
"""

import os
import re
import struct
import sys

# The seven fields worth editing. Everything downstream -- the index, the
# ALAC conversion, the iPod database -- speaks these names.
FIELDS = ('title', 'artist', 'album', 'album_artist', 'genre', 'year', 'track')

# RIFF LIST/INFO four-character codes. ffprobe maps these to the names above,
# which is the path that matters: an untagged WAV is converted to ALAC with
# `-map_metadata 0`, so whatever ffprobe reads here rides onto the device.
_INFO = {
    'title': b'INAM',
    'artist': b'IART',
    'album': b'IPRD',
    'album_artist': b'IAAR',   # non-standard but round-trips; ffprobe keeps it
    'genre': b'IGNR',
    'year': b'ICRD',
    'track': b'ITRK',
}
_INFO_BACK = {v: k for k, v in _INFO.items()}

# The one tag chunk this module owns and may replace. Anything else in the
# file is left exactly where it is.
_WAV_TAG_CHUNKS = (b'LIST',)
# An `id3 ` chunk inside a WAV can carry things a LIST/INFO cannot -- embedded
# artwork among them -- so replacing it needs the ID3v2 writer, which does
# not exist yet. Until it does, a file carrying one is refused rather than
# quietly stripped: losing 2 KB of somebody's cover art to a rename is not a
# trade this tool gets to make silently.
_ID3_CHUNKS = (b'id3 ', b'ID3 ')


class TagError(Exception):
    pass


# --------------------------------------------------------------- RIFF / WAV

def _riff_chunks(b):
    """[(fourcc, header_offset, data_offset, size)] in file order."""
    if b[:4] != b'RIFF' or b[8:12] != b'WAVE':
        raise TagError('not a RIFF/WAVE file')
    out, o, n = [], 12, len(b)
    while o + 8 <= n:
        cid = b[o:o + 4]
        size = struct.unpack('<I', b[o + 4:o + 8])[0]
        out.append((cid, o, o + 8, size))
        o += 8 + size + (size & 1)          # chunks are word-aligned
    return out


def _info_chunk(tags):
    """A LIST/INFO chunk carrying the non-empty tags, word-aligned."""
    body = b'INFO'
    for name in FIELDS:
        v = (tags.get(name) or '').strip()
        if not v:
            continue
        raw = v.encode('utf-8') + b'\0'      # INFO strings are NUL-terminated
        if len(raw) & 1:
            raw += b'\0'
        body += _INFO[name] + struct.pack('<I', len(raw)) + raw
    if body == b'INFO':
        return b''                           # nothing to say: write no chunk
    if len(body) & 1:
        body += b'\0'
    return b'LIST' + struct.pack('<I', len(body)) + body


def read_wav(path):
    """Read only the tag chunk, never the audio.

    This used to slurp the whole file. Harmless while nothing called it in a
    loop -- and then the ancestor snapshot started calling it once per device
    track at the end of every sync. A 95 MB WAV read 466 times over is the
    kind of thing that is fine in every test and ruinous in use.
    """
    out = {}
    with open(path, 'rb') as fh:
        if fh.read(4) != b'RIFF':
            raise TagError('not a RIFF/WAVE file')
        fh.seek(12)
        while True:
            h = fh.read(8)
            if len(h) < 8:
                break
            cid = h[:4]
            size = struct.unpack('<I', h[4:8])[0]
            if cid != b'LIST':
                fh.seek(size + (size & 1), 1)      # skip the audio, do not read it
                continue
            b = fh.read(size + (size & 1))
            if b[:4] != b'INFO':
                continue
            o = 4
            while o + 8 <= 4 + size:
                k = b[o:o + 4]
                n = struct.unpack('<I', b[o + 4:o + 8])[0]
                v = b[o + 8:o + 8 + n].split(b'\0')[0].decode('utf-8', 'replace')
                if k in _INFO_BACK:
                    out[_INFO_BACK[k]] = _genre_norm(v) if _INFO_BACK[k] == 'genre' else v
                o += 8 + n + (n & 1)
    return out


def write_wav(path, tags):
    """Replace the tag chunks. Every other chunk keeps its bytes and offset.

    Tag chunks live after `data` in every file measured, so the rebuild is
    just: keep everything that is not ours, then append ours. If a tag chunk
    were to sit BEFORE the audio, dropping it would slide the audio down the
    file -- so that case refuses rather than risking it.
    """
    with open(path, 'rb') as fh:
        b = fh.read()
    chunks = _riff_chunks(b)
    if not any(c[0] == b'data' for c in chunks):
        raise TagError('no data chunk')
    data_at = next(c for c in chunks if c[0] == b'data')[1]
    for cid, h, _d, _s in chunks:
        if cid in _WAV_TAG_CHUNKS and h < data_at:
            raise TagError('tag chunk precedes the audio; refusing to move it')
        if cid in _ID3_CHUNKS:
            raise TagError('this WAV carries an id3 chunk and the ID3v2 writer '
                           'is not built yet; refusing rather than dropping it')

    keep = bytearray(b[:12])
    for cid, h, _d, size in chunks:
        if cid in _WAV_TAG_CHUNKS:
            continue
        keep += b[h:h + 8 + size + (size & 1)]
    keep += _info_chunk(tags)
    struct.pack_into('<I', keep, 4, len(keep) - 8)      # RIFF size field

    _replace(path, bytes(keep))
    return len(keep)


# ============================================================ ID3v2

# Frame ids we manage. Everything else in the tag is carried through
# untouched -- APIC artwork above all, which is exactly what made stripping
# the WAV `id3 ` chunk unacceptable.
_ID3_FRAME = {
    'title': 'TIT2', 'artist': 'TPE1', 'album': 'TALB',
    'album_artist': 'TPE2', 'genre': 'TCON', 'year': 'TYER', 'track': 'TRCK',
}
_ID3_BACK = {v: k for k, v in _ID3_FRAME.items()}
# THREE FRAMES MEAN `date` TO FFMPEG, and that is measured rather than read
# off a spec: writing TDOR=2008 ahead of TDRL=1990 into a real file and
# asking ffprobe returned `date=1990`, with TDOR kept as its own key. So
# TYER (v2.3), TDRC (v2.4 recording date) and TDRL (release date) are all
# read as the year and all replaced on write, leaving exactly one behind --
# two frames meaning `date` is two truths, settled by file order.
#
# TDOR IS NOT ONE OF THEM. ffmpeg does not fold it into `date`, it is the
# ORIGINAL release date rather than the release date, and it differs from
# TDRL on 9 of the 432 Beatport AIFFs here. It is carried through untouched.
#
# 428 of 482 .aif files read as having no year at all until TDRL was added
# here. The differential against ffprobe found that; a round-trip never
# could have, because it only ever proves we read back what we wrote.
_ID3_BACK['TDRC'] = 'year'
_ID3_BACK['TDRL'] = 'year'
_ID3_YEAR = ('TYER', 'TDRC', 'TDRL')

# v2.2 used three-character ids and three-byte sizes. 47 of 600 files
# sampled are still v2.2, so they are read and up-converted rather than
# refused.
_V22 = {'TT2': 'TIT2', 'TP1': 'TPE1', 'TAL': 'TALB', 'TP2': 'TPE2',
        'TCO': 'TCON', 'TYE': 'TYER', 'TRK': 'TRCK', 'PIC': 'APIC',
        'COM': 'COMM', 'TEN': 'TENC', 'TCM': 'TCOM', 'TPA': 'TPOS'}


def _synchsafe(n):
    return bytes(((n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F))


def _unsynchsafe(b):
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


# ID3v1's numbered genres. Older encoders write the number in front of the
# name -- "(5)Funk" -- or the number alone. The device resolves it to "Funk",
# so a reader that does not will report 208 tracks as having drifted when
# nothing has changed. That is exactly what the first run of the drift
# detector did.
_ID3V1_GENRES = [
    'Blues', 'Classic Rock', 'Country', 'Dance', 'Disco', 'Funk', 'Grunge',
    'Hip-Hop', 'Jazz', 'Metal', 'New Age', 'Oldies', 'Other', 'Pop', 'R&B',
    'Rap', 'Reggae', 'Rock', 'Techno', 'Industrial', 'Alternative', 'Ska',
    'Death Metal', 'Pranks', 'Soundtrack', 'Euro-Techno', 'Ambient',
    'Trip-Hop', 'Vocal', 'Jazz+Funk', 'Fusion', 'Trance', 'Classical',
    'Instrumental', 'Acid', 'House', 'Game', 'Sound Clip', 'Gospel', 'Noise',
    'AlternRock', 'Bass', 'Soul', 'Punk', 'Space', 'Meditative',
    'Instrumental Pop', 'Instrumental Rock', 'Ethnic', 'Gothic', 'Darkwave',
    'Techno-Industrial', 'Electronic', 'Pop-Folk', 'Eurodance', 'Dream',
    'Southern Rock', 'Comedy', 'Cult', 'Gangsta', 'Top 40', 'Christian Rap',
    'Pop/Funk', 'Jungle', 'Native American', 'Cabaret', 'New Wave',
    'Psychadelic', 'Rave', 'Showtunes', 'Trailer', 'Lo-Fi', 'Tribal',
    'Acid Punk', 'Acid Jazz', 'Polka', 'Retro', 'Musical', 'Rock & Roll',
    'Hard Rock',
]


def _genre_norm(v):
    """`(5)Funk` and `(5)` and `Funk` are the same genre."""
    v = (v or '').strip()
    m = re.match(r'^\((\d{1,3})\)\s*(.*)$', v)
    if not m:
        return v
    rest = m.group(2).strip()
    if rest:
        return rest
    n = int(m.group(1))
    return _ID3V1_GENRES[n] if 0 <= n < len(_ID3V1_GENRES) else v


def _year_norm(v):
    """A year, out of whatever the tagger wrote.

    iTunes puts a full timestamp in `©day` -- "2011-01-01T08:00:00Z" -- and
    ID3v2.4's TDRC is also a date rather than a year. The index, the device
    and the panel all want four digits, and a field that reads 2011 in one
    container and 2011-01-01T08:00:00Z in another is a drift row that never
    settles.
    """
    m = re.match(r'\s*(\d{4})', v or '')
    return m.group(1) if m else (v or '').strip()


def _id3_text(raw):
    """Decode a text frame payload: one encoding byte, then the string."""
    if not raw:
        return ''
    enc, body = raw[0], raw[1:]
    try:
        if enc == 0:
            s = body.decode('latin-1')
        elif enc == 1:
            s = body.decode('utf-16')          # BOM-led
        elif enc == 2:
            s = body.decode('utf-16-be')
        else:
            s = body.decode('utf-8')
    except Exception:
        s = body.decode('latin-1', 'replace')
    return s.split('\x00')[0].strip()


def _id3_encode(value):
    """UTF-16 with a BOM: encoding 1, which every reader since 1999 handles.

    Latin-1 would be smaller and 238 of the sampled files use it, but it
    cannot hold the accented titles already in this library, and a tag
    writer that mangles `It's` on some files and not others is worse than
    one that is uniformly a few bytes larger.
    """
    return b'\x01' + '﻿'.encode('utf-16-le') + value.encode('utf-16-le') + b'\x00\x00'


def _id3_read_tag(b):
    """(frames, tag_size) from a buffer starting at the ID3 header.

    frames is [(id, payload_bytes)] in file order, ids normalised to their
    v2.3 spelling. Returns (None, 0) when there is no tag.
    """
    if b[:3] != b'ID3':
        return None, 0
    major, flags = b[3], b[5]
    size = _unsynchsafe(b[6:10])
    body = b[10:10 + size]
    if flags & 0x80:                      # unsynchronisation: undo it
        body = body.replace(b'\xff\x00', b'\xff')
    o = 0
    if flags & 0x40:                      # extended header, skip
        if major == 3:
            o = 4 + struct.unpack('>I', body[0:4])[0]
        else:
            o = _unsynchsafe(body[0:4])
    out = []
    idlen, szlen = (3, 3) if major == 2 else (4, 4)
    while o + idlen + szlen <= len(body):
        fid = body[o:o + idlen]
        if not fid.strip(b'\x00'):
            break                          # padding begins
        if major == 2:
            fsz = int.from_bytes(body[o + 3:o + 6], 'big')
            head = 6
        else:
            raw = body[o + 4:o + 8]
            fsz = _unsynchsafe(raw) if major == 4 else struct.unpack('>I', raw)[0]
            head = 10
        if fsz < 0 or o + head + fsz > len(body):
            break
        name = fid.decode('latin-1', 'replace')
        if major == 2:
            name = _V22.get(name, name)
        out.append((name, body[o + head:o + head + fsz]))
        o += head + fsz
    return out, 10 + size


def _pic_to_apic(payload):
    """v2.2 PIC -> v2.3 APIC. Three-letter format becomes a MIME string."""
    if len(payload) < 5:
        return None
    enc, fmt = payload[0], payload[1:4].decode('latin-1', 'replace').upper()
    mime = {'JPG': 'image/jpeg', 'PNG': 'image/png'}.get(fmt, 'image/' + fmt.lower())
    return bytes([enc]) + mime.encode('latin-1') + b'\x00' + payload[4:]


def _id3_fields(frames):
    """Frames -> the seven field names. Shared by every container that
    carries an ID3 tag, which is now MP3 *and* AIFF *and* some .flac."""
    # LAST FRAME WINS, because that is what ffmpeg does, and ffmpeg is what
    # converts these files to the ALAC the device plays. Not a detail: 151 of
    # the 327 .aiff files here carry TDRC "2012" *and* TDRL "2012-11-21", and
    # reading the first gave a bare year where ffmpeg gave the full date. Both
    # normalise to 2012, so the read differential passed and the disagreement
    # only surfaced on the write side, as a date losing its month and day.
    out = {}
    for fid, payload in (frames or []):
        f = _ID3_BACK.get(fid)
        if not f:
            continue
        v = _id3_text(payload)
        if v:
            out[f] = v
    if out.get('genre'):
        out['genre'] = _genre_norm(out['genre'])
    if out.get('year'):
        out['year'] = _year_norm(out['year'])
    return {k: v for k, v in out.items() if v}


def read_id3(path):
    with open(path, 'rb') as fh:
        b = fh.read(_id3_span(path))
    frames, _n = _id3_read_tag(b)
    return _id3_fields(frames)


def _id3_span(path):
    """Just the header, then the tag -- never the whole file."""
    with open(path, 'rb') as fh:
        h = fh.read(10)
    if h[:3] != b'ID3':
        return 0                 # no tag: the audio starts at byte zero
    return 10 + _unsynchsafe(h[6:10])


def _id3_build(frames, pad, major=3):
    """An ID3v2 tag, in the version the file already used.

    WHY THE VERSION IS PRESERVED. All 807 tagged AIFFs here are v2.4, whose
    frame sizes are synchsafe where v2.3's are plain. Rebuilding a v2.4 tag
    as v2.3 re-encodes every size correctly, so it reads -- but a carried
    frame using v2.4's UTF-8 encoding byte (3) becomes a frame a strict v2.3
    reader cannot decode. Writing back the version we found keeps every
    frame we did not touch exactly as valid as we found it.
    """
    if major not in (3, 4):
        major = 3
    body = b''
    for fid, payload in frames:
        size = _synchsafe(len(payload)) if major == 4 else struct.pack('>I', len(payload))
        body += fid.encode('latin-1') + size + b'\x00\x00' + payload
    body += b'\x00' * pad
    return b'ID3' + bytes((major, 0, 0)) + _synchsafe(len(body)) + body


def _norm_for(field, v):
    """The value as every consumer downstream will see it."""
    if field == 'genre':
        return _genre_norm(v)
    if field == 'year':
        return _year_norm(v)
    return (v or '').strip()


def _id3_frames_for(tags, old_frames, major):
    """The new frame list: ours first, every frame we do not manage after.

    AN UNCHANGED FIELD KEEPS THE BYTES THE FILE ALREADY HAD. That is not an
    optimisation, it is the fix for a real loss. `read` normalises, so a
    Beatport TDRL of "2008-05-05" comes back as "2008" -- and the editor then
    sends "2008" back as the current value of a field nobody touched. Writing
    it would quietly throw away the month and the day on 432 files. So a
    field whose NORMALISED value has not moved is carried through verbatim,
    which also makes repeated saves genuinely idempotent.
    """
    # The frame kept is the LAST one that maps to the field, which is the one
    # the reader reported and the one ffmpeg believes. Keeping the first meant
    # preserving TDRC's bare "2012" and dropping TDRL's "2012-11-21" -- the
    # date survived the save and lost its month and day anyway.
    managed = set(_ID3_BACK)
    kept, old_by_field = [], {}
    for fid, payload in old_frames:
        if fid in managed:
            if _id3_text(payload):
                old_by_field[_ID3_BACK[fid]] = (fid, payload)
        else:
            kept.append((fid, payload))
    had = [f for f, _p in old_frames if f in _ID3_YEAR]
    year_id = had[-1] if had else ('TDRC' if major == 4 else 'TYER')
    mine = []
    for field in FIELDS:
        v = (tags.get(field) or '').strip()
        if not v:
            continue
        old = old_by_field.get(field)
        if old is not None and _norm_for(field, _id3_text(old[1])) == v:
            mine.append(old)                      # untouched: keep its bytes
            continue
        mine.append((year_id if field == 'year' else _ID3_FRAME[field],
                     _id3_encode(v)))
    return mine + kept


def _id3_major(path):
    with open(path, 'rb') as fh:
        h = fh.read(10)
    return h[3] if h[:3] == b'ID3' else None


def write_id3(path, tags, _audio_from=None):
    """Replace the managed frames, keep every other frame byte for byte.

    IN PLACE WHEN IT FITS. An ID3v2 tag is padded by design -- the median
    file here carries 1,142 spare bytes and 455 of 532 carry at least 256 --
    so the new tag is written into the space the old one occupied and not a
    byte of audio moves. When it does not fit, the file is rebuilt with a
    larger pad and the audio copied across verbatim, which is the same
    fallback the iTunesDB writer has.
    """
    # v2.2 REFUSED, not converted. Its frame ids are three characters to
    # v2.3's four, so carrying an unmapped frame across means writing a
    # malformed header and losing everything after it -- which is exactly
    # what the first attempt did: an 11-frame tag came back as 5 and the
    # cover art was gone. 47 of 600 sampled files are v2.2; they wait for a
    # real converter rather than being quietly emptied.
    if _id3_major(path) == 2:
        raise TagError('ID3v2.2 needs a converter that does not exist yet; '
                       'refusing rather than dropping its frames')
    with open(path, 'rb') as fh:
        head = fh.read(10)
        old_span = 10 + _unsynchsafe(head[6:10]) if head[:3] == b'ID3' else 0
        fh.seek(0)
        prefix = fh.read(old_span) if old_span else b''
    frames, _n = _id3_read_tag(prefix) if old_span else ([], 0)
    frames = frames or []

    new_frames = _id3_frames_for(tags, frames, _id3_major(path) or 3)

    bare = len(_id3_build(new_frames, 0))
    if old_span and bare <= old_span:
        blob = _id3_build(new_frames, old_span - bare)      # exact fit, no move
        with open(path, 'r+b') as fh:
            fh.write(blob)
        return old_span
    # grow: rebuild with room to spare so the next edit lands in place
    blob = _id3_build(new_frames, 2048)
    with open(path, 'rb') as fh:
        fh.seek(old_span)
        audio = fh.read()
    _replace(path, blob + audio)
    return len(blob)


def _id3_payload(path):
    """Everything after the tag -- the bytes write_id3 promises not to move."""
    span = _id3_span(path)
    with open(path, 'rb') as fh:
        fh.seek(span)
        return span, fh.read()


# ============================================================ FORM / AIFF
#
# AN AIFF IS NOT AN MP3 WITH A DIFFERENT EXTENSION, and assuming it was is
# the bug that sat here for two days. A FORM file keeps its ID3 tag in an
# `ID3 ` CHUNK, not at byte 0 where `read_id3` looks -- so reading one
# returned {} and writing one would have PREPENDED an ID3 header to a FORM
# file, corrupting it. Nothing had asked to write an AIFF yet, so it never
# fired; the differential test on the index found it by noticing that 103 of
# 300 files had lost their artist.
#
# Surveyed all 809 AIFFs on the drive before writing a line of this:
#
#     FORM/AIFF                     809 of 809
#     `ID3 ` chunk, ID3v2.4         807      (2 carry no tag at all)
#     that chunk AFTER the audio    807 of 807
#
# Which is the same shape `write_wav` already handles, so it gets the same
# treatment: keep every chunk that is not ours byte for byte, and because
# the tag is last, a tag that fits is written at its own offset and not one
# byte of the file moves. Chunk sizes are big-endian here; RIFF's are little.

_AIFF_TAG_CHUNKS = (b'ID3 ', b'id3 ')


def _form_chunks(path):
    """[(fourcc, header_at, data_at, size)] by SEEKING, never reading audio.

    These files run to 113 MB and SSND is nearly all of it. `_riff_chunks`
    slurps because a WAV here tops out at 95 MB and it already existed;
    this one was written after that lesson.
    """
    out = []
    with open(path, 'rb') as fh:
        hdr = fh.read(12)
        if hdr[:4] != b'FORM' or hdr[8:12] not in (b'AIFF', b'AIFC'):
            raise TagError('not a FORM/AIFF file')
        n = os.path.getsize(path)
        o = 12
        while o + 8 <= n:
            fh.seek(o)
            h = fh.read(8)
            if len(h) < 8:
                break
            size = struct.unpack('>I', h[4:8])[0]
            out.append((h[:4], o, o + 8, size))
            o += 8 + size + (size & 1)          # FORM chunks are word-aligned
    return out


def _aiff_tag(path, chunks=None):
    """(frames, major, chunk) for the ID3 chunk, or ([], 3, None)."""
    chunks = chunks if chunks is not None else _form_chunks(path)
    tagc = [c for c in chunks if c[0] in _AIFF_TAG_CHUNKS]
    if not tagc:
        return [], 3, None
    c = tagc[-1]
    with open(path, 'rb') as fh:
        fh.seek(c[2])
        b = fh.read(c[3])
    major = b[3] if b[:3] == b'ID3' and b[3] in (2, 3, 4) else 3
    frames, _n = _id3_read_tag(b)
    return (frames or []), major, c


def read_aiff(path):
    frames, _major, _c = _aiff_tag(path)
    return _id3_fields(frames)


def write_aiff(path, tags):
    """Replace the `ID3 ` chunk. Every other chunk keeps its bytes and offset.

    Three cases, and only the last one copies anything:

      tag chunk is last and the new tag fits  -> written at its own offset,
                                                 padded to the same size.
                                                 Nothing moves, the FORM
                                                 size does not even change.
      tag chunk is last and does not fit      -> truncate at its header and
                                                 append. Audio untouched.
      no tag chunk                            -> append one.
    """
    chunks = _form_chunks(path)
    ssnd = next((c for c in chunks if c[0] == b'SSND'), None)
    if ssnd is None:
        raise TagError('no SSND chunk; this is not audio we can tag')
    frames, major, old = _aiff_tag(path, chunks)
    if old and old[1] < ssnd[1]:
        raise TagError('tag chunk precedes the audio; refusing to move it')
    if major == 2:
        raise TagError('ID3v2.2 inside a FORM chunk needs the converter; '
                       'refusing rather than dropping its frames')

    new_frames = _id3_frames_for(tags, frames, major)
    bare = len(_id3_build(new_frames, 0, major))

    last = chunks[-1]
    if old and old is last and bare <= old[3]:
        # EXACT FIT: pad the tag out to the size the chunk already has, so
        # the chunk header, the FORM size and every byte after it stand.
        blob = _id3_build(new_frames, old[3] - bare, major)
        assert len(blob) == old[3]
        with open(path, 'r+b') as fh:
            fh.seek(old[2])
            fh.write(blob)
        return old[3]

    # Grow with room to spare, so the next edit lands in the branch above.
    blob = _id3_build(new_frames, 2048, major)
    if len(blob) & 1:
        blob += b'\x00'
    chunk = b'ID3 ' + struct.pack('>I', len(blob)) + blob
    if old and old is last:
        cut = old[1]
    elif not old:
        cut = os.path.getsize(path)
    else:
        # Measured zero times in 809 files. Rather than carry an untested
        # rebuild path, refuse: an unmeasured code path that moves audio is
        # worse than a file this tool declines to edit.
        raise TagError('the ID3 chunk is not the last chunk; this layout was '
                       'never seen on the drive and has no tested path')
    with open(path, 'r+b') as fh:
        fh.truncate(cut)
        fh.seek(cut)
        fh.write(chunk)
        fh.seek(4)
        fh.write(struct.pack('>I', cut + len(chunk) - 8))   # FORM size
    return len(chunk)


# ============================================================ FLAC
#
# Metadata is a chain of blocks at the head of the file, each [flag|type][24
# bit size], and the audio frames follow the one flagged last. Surveyed all
# 244 .flac files here:
#
#     STREAMINFO SEEKTABLE VORBIS_COMMENT PADDING    226
#     an ID3v2 tag BEFORE the fLaC magic              18
#     PADDING present                                226 of 226, ~8 KB each
#
# So the same bargain as everywhere else: rewrite the comment block and take
# the difference out of the padding that is already there, and the audio
# frames never move. The 18 with a leading ID3 tag are tagged by some other
# program's convention; the fLaC magic is found after it and the real blocks
# are read from there, because a file is not its first four bytes.

_VORBIS = {
    'title': 'TITLE', 'artist': 'ARTIST', 'album': 'ALBUM',
    'album_artist': 'ALBUMARTIST', 'genre': 'GENRE', 'year': 'DATE',
    'track': 'TRACKNUMBER',
}
_VORBIS_BACK = {v: k for k, v in _VORBIS.items()}
_VORBIS_BACK['ALBUM ARTIST'] = 'album_artist'    # the other common spelling
_VORBIS_BACK['YEAR'] = 'year'
_VORBIS_BACK['TRACK'] = 'track'


def _flac_start(path):
    """Where the fLaC magic is -- 0, or past a leading ID3 tag."""
    with open(path, 'rb') as fh:
        h = fh.read(10)
        if h[:4] == b'fLaC':
            return 0
        if h[:3] == b'ID3':
            at = 10 + _unsynchsafe(h[6:10])
            fh.seek(at)
            if fh.read(4) == b'fLaC':
                return at
    raise TagError('no fLaC magic')


def _flac_blocks(path):
    """[(type, header_at, data_at, size, is_last)] and where the audio starts."""
    at = _flac_start(path)
    out = []
    with open(path, 'rb') as fh:
        fh.seek(at + 4)
        while True:
            o = fh.tell()
            h = fh.read(4)
            if len(h) < 4:
                raise TagError('truncated metadata')
            last, typ = bool(h[0] & 0x80), h[0] & 0x7F
            size = int.from_bytes(h[1:4], 'big')
            out.append((typ, o, o + 4, size, last))
            fh.seek(size, 1)
            if last:
                return out, fh.tell()


def _vorbis_parse(b):
    """(vendor, [(KEY, value)]) from a VORBIS_COMMENT body."""
    n = struct.unpack('<I', b[0:4])[0]
    vendor = b[4:4 + n]
    o = 4 + n
    count = struct.unpack('<I', b[o:o + 4])[0]
    o += 4
    items = []
    for _ in range(count):
        if o + 4 > len(b):
            break
        ln = struct.unpack('<I', b[o:o + 4])[0]
        raw = b[o + 4:o + 4 + ln].decode('utf-8', 'replace')
        o += 4 + ln
        k, _, v = raw.partition('=')
        items.append((k.upper(), v))
    return vendor, items


def _vorbis_build(vendor, items):
    out = struct.pack('<I', len(vendor)) + vendor + struct.pack('<I', len(items))
    for k, v in items:
        raw = ('%s=%s' % (k, v)).encode('utf-8')
        out += struct.pack('<I', len(raw)) + raw
    return out


def read_flac(path):
    for typ, _h, d, size, _last in _flac_blocks(path)[0]:
        if typ != 4:
            continue
        with open(path, 'rb') as fh:
            fh.seek(d)
            b = fh.read(size)
        _vendor, items = _vorbis_parse(b)
        out = {}
        for k, v in items:
            f = _VORBIS_BACK.get(k)
            if f and v.strip() and f not in out:
                out[f] = v.strip()
        if out.get('genre'):
            out['genre'] = _genre_norm(out['genre'])
        if out.get('year'):
            out['year'] = _year_norm(out['year'])
        return out
    return {}


def write_flac(path, tags):
    """Rewrite VORBIS_COMMENT, take the difference out of PADDING.

    The two blocks are rewritten as one span of identical total length, so
    the audio frames stay exactly where they were and nothing else in the
    chain is touched -- SEEKTABLE above all, whose offsets are relative to
    the first frame and would be wrong if it moved.
    """
    blocks, _audio_at = _flac_blocks(path)
    vc = next((b for b in blocks if b[0] == 4), None)
    pad = next((b for b in blocks if b[0] == 1), None)
    if vc is None:
        raise TagError('no VORBIS_COMMENT block; nothing on the drive looks '
                       'like this and creating one has no tested path')
    if pad is None:
        raise TagError('no PADDING block to borrow from; refusing to move '
                       'the audio frames')
    if not (vc[1] < pad[1] and pad[4]):
        raise TagError('PADDING is not the last block after the comment; '
                       'this layout was never seen on the drive')

    with open(path, 'rb') as fh:
        fh.seek(vc[2])
        vendor, items = _vorbis_parse(fh.read(vc[3]))
    keep = [(k, v) for k, v in items if k not in _VORBIS_BACK]
    old_by_field = {}
    for k, v in items:
        f = _VORBIS_BACK.get(k)
        if f:
            old_by_field.setdefault(f, (k, v))
    mine = []
    for f in FIELDS:
        v = (tags.get(f) or '').strip()
        if not v:
            continue
        old = old_by_field.get(f)
        if old is not None and _norm_for(f, old[1]) == v:
            mine.append(old)                      # unchanged: keep its bytes
            continue
        mine.append((_VORBIS[f], v))
    body = _vorbis_build(vendor, mine + keep)

    # the span the two blocks share, which must not change length
    span = (pad[1] + 4 + pad[3]) - vc[1]
    newpad = span - (4 + len(body)) - 4
    if newpad < 0:
        raise TagError('tags need %d more bytes than the %d of padding this '
                       'file carries' % (-newpad, pad[3]))
    blob = (bytes([4]) + len(body).to_bytes(3, 'big') + body
            + bytes([0x81]) + newpad.to_bytes(3, 'big') + b'\x00' * newpad)
    assert len(blob) == span, (len(blob), span)
    with open(path, 'r+b') as fh:
        fh.seek(vc[1])
        fh.write(blob)
    return len(body)


# ============================================================ MP4 / M4A
#
# THE WHOLE TRICK IS THE `free` ATOM, and understanding that is also the
# explanation of why ffmpeg was so destructive here. The layout is
#
#     ftyp | moov (... udta/meta/ilst: the tags ...) | free | mdat (audio)
#
# and `stco` inside moov holds ABSOLUTE FILE OFFSETS into mdat. Move mdat by
# one byte and every one of those offsets is wrong, which is why a naive
# tag edit on an m4a either rewrites the sample tables or breaks the file.
#
# But `free` is padding -- 521 KB in the median file here -- and it sits
# between moov and mdat. Grow moov by N and shrink `free` by N: mdat does
# not move, stco stays true, and nothing else is touched. `ffmpeg -c copy`
# DROPPED that 485 KB free atom, which is precisely the room that makes
# editing in place possible, and 36 KB of moov it did not recognise with it.
#
# Surveyed all 117 m4a files on the drive:
#
#     ftyp moov free mdat    97   edit moov, absorb the delta into free
#     ftyp wide mdat moov    20   moov is LAST; growing it moves nothing
#     moov/udta/meta        117 of 117
#
# The second shape is QuickTime's recording layout, and it is the easier of
# the two: there is nothing after moov to disturb.

# ilst atom names. The leading byte is the © copyright sign, 0xA9.
_MP4_ATOM = {
    'title': b'\xa9nam', 'artist': b'\xa9ART', 'album': b'\xa9alb',
    'album_artist': b'aART', 'genre': b'\xa9gen', 'year': b'\xa9day',
    'track': b'trkn',
}
_MP4_BACK = {v: k for k, v in _MP4_ATOM.items()}
# `gnre` is the ID3v1 NUMBERED genre, and iTunes writes it instead of ©gen
# when the genre is one of the standard 80. It is read, and then DROPPED on
# write in favour of ©gen -- two atoms meaning genre is two truths, and the
# device reads whichever it finds first.
_MP4_GNRE = b'gnre'
_MP4_MANAGED = set(_MP4_BACK) | {_MP4_GNRE}
# Containers whose children are atoms. `meta` is the odd one: four bytes of
# version and flags sit before its children.
_MP4_PARENT = {b'moov': 0, b'udta': 0, b'trak': 0, b'meta': 4, b'ilst': 0}


def _mp4_children(b, start, end, skip=0):
    """[(type, offset, size)] of the atoms between two offsets of a buffer."""
    out, o = [], start + skip
    while o + 8 <= end:
        size = struct.unpack('>I', b[o:o + 4])[0]
        if size == 1:                       # 64-bit size, used by big mdat
            if o + 16 > end:
                break
            size = struct.unpack('>Q', b[o + 8:o + 16])[0]
        elif size == 0:                     # "to end of file"
            size = end - o
        if size < 8 or o + size > end:
            break
        out.append((b[o + 4:o + 8], o, size))
        o += size
    return out


def _mp4_top(path):
    """Top-level atoms by seeking -- an m4a here is 12 MB and mdat is most."""
    out = []
    n = os.path.getsize(path)
    with open(path, 'rb') as fh:
        o = 0
        while o + 8 <= n:
            fh.seek(o)
            h = fh.read(16)
            if len(h) < 8:
                break
            size = struct.unpack('>I', h[0:4])[0]
            if size == 1:
                size = struct.unpack('>Q', h[8:16])[0]
            elif size == 0:
                size = n - o
            if size < 8:
                break
            out.append((h[4:8], o, size))
            o += size
    if not out or out[0][0] != b'ftyp':
        raise TagError('not an MP4 container')
    return out


def _mp4_chain(moov, names):
    """[(offset, size)] outermost..innermost for a path inside moov, or None."""
    chain, start, end = [], 0, len(moov)
    for name in names:
        # The skip belongs to the container we are listing the children OF,
        # which is the last link in the chain -- `meta` hides four bytes of
        # version and flags before its first child, and reading those as an
        # atom size yields nonsense.
        parent = moov[chain[-1][0] + 4:chain[-1][0] + 8] if chain else b''
        kids = _mp4_children(moov, start, end, _MP4_PARENT.get(parent, 0))
        hit = next((k for k in kids if k[0] == name), None)
        if hit is None:
            return None
        _t, off, size = hit
        chain.append((off, size))
        start, end = off + 8, off + size
    return chain


def _mp4_data(b, off, size):
    """The payload and type-flag of an ilst item's `data` atom."""
    for typ, o, sz in _mp4_children(b, off + 8, off + size):
        if typ == b'data' and sz >= 16:
            flags = struct.unpack('>I', b[o + 8:o + 12])[0] & 0xFFFFFF
            return flags, b[o + 16:o + sz]
    return None, b''


def _mp4_item(name, flags, payload):
    data = (struct.pack('>I', 16 + len(payload)) + b'data'
            + struct.pack('>II', flags, 0) + payload)
    return struct.pack('>I', 8 + len(data)) + name + data


def _mp4_text(name, value):
    return _mp4_item(name, 1, value.encode('utf-8'))      # 1 = UTF-8


def _mp4_trkn(value):
    """`trkn` is binary: two reserved bytes, number, total, two reserved."""
    a, _, t = (value or '').partition('/')
    try:
        n = int(a.strip())
    except ValueError:
        return b''
    try:
        total = int(t.strip())
    except ValueError:
        total = 0
    return _mp4_item(b'trkn', 0, struct.pack('>HHHH', 0, n, total, 0))


def _mp4_ilst(path):
    """(moov_bytes, chain_to_ilst) or (moov_bytes, None)."""
    top = _mp4_top(path)
    mo = next((a for a in top if a[0] == b'moov'), None)
    if mo is None:
        raise TagError('no moov atom')
    with open(path, 'rb') as fh:
        fh.seek(mo[1])
        moov = fh.read(mo[2])
    return mo, moov, _mp4_chain(moov, [b'moov', b'udta', b'meta', b'ilst'])


def read_m4a(path):
    _mo, moov, chain = _mp4_ilst(path)
    if not chain:
        return {}
    off, size = chain[-1]
    out = {}
    for typ, o, sz in _mp4_children(moov, off + 8, off + size):
        flags, payload = _mp4_data(moov, o, sz)
        if payload is None:
            continue
        if typ == _MP4_GNRE and len(payload) >= 2 and 'genre' not in out:
            n = struct.unpack('>H', payload[:2])[0] - 1
            if 0 <= n < len(_ID3V1_GENRES):
                out['genre'] = _ID3V1_GENRES[n]
            continue
        f = _MP4_BACK.get(typ)
        if not f or f in out:
            continue
        if typ == b'trkn' and len(payload) >= 4:
            n = struct.unpack('>H', payload[2:4])[0]
            total = struct.unpack('>H', payload[4:6])[0] if len(payload) >= 6 else 0
            out['track'] = ('%d/%d' % (n, total)) if total else str(n)
        else:
            v = payload.decode('utf-8', 'replace').strip()
            if v:
                out[f] = v
    if out.get('genre'):
        out['genre'] = _genre_norm(out['genre'])
    if out.get('year'):
        out['year'] = _year_norm(out['year'])
    return {k: v for k, v in out.items() if v}


def write_m4a(path, tags):
    """Replace the managed ilst atoms; every other atom keeps its bytes.

    `covr` above all -- 142 KB of cover art in one file here -- which is
    carried through untouched for exactly the reason the WAV writer refuses
    an id3 chunk it cannot rewrite: losing somebody's artwork to a rename is
    not a trade this tool gets to make silently.
    """
    mo, moov, chain = _mp4_ilst(path)
    if not chain:
        raise TagError('no moov/udta/meta/ilst; all 117 files on the drive '
                       'have one and creating the tree has no tested path')
    off, size = chain[-1]

    kept, old_by_field = b'', {}
    for typ, o, sz in _mp4_children(moov, off + 8, off + size):
        if typ not in _MP4_MANAGED:
            kept += moov[o:o + sz]
            continue
        f = _MP4_BACK.get(typ)
        if f:
            old_by_field.setdefault(f, moov[o:o + sz])
    mine = b''
    for f in FIELDS:
        v = (tags.get(f) or '').strip()
        if not v:
            continue
        # iTunes writes `©day` as "2011-01-01T08:00:00Z"; read gives "2011",
        # and writing that back throws the rest away on every save.
        old = old_by_field.get(f)
        if old is not None and f != 'track':
            _flags, payload = _mp4_data(old, 0, len(old))
            if _norm_for(f, (payload or b'').decode('utf-8', 'replace')) == v:
                mine += old                       # unchanged: keep its bytes
                continue
        mine += _mp4_trkn(v) if f == 'track' else _mp4_text(_MP4_ATOM[f], v)
    body = mine + kept
    new_ilst = struct.pack('>I', 8 + len(body)) + b'ilst' + body

    # splice it in and correct every ancestor's size field
    new_moov = bytearray(moov[:off] + new_ilst + moov[off + size:])
    delta = len(new_ilst) - size
    for a_off, a_size in chain[:-1]:
        if struct.unpack('>I', moov[a_off:a_off + 4])[0] == 1:
            raise TagError('64-bit container atom; no tested path')
        struct.pack_into('>I', new_moov, a_off, a_size + delta)
    new_moov = bytes(new_moov)

    top = _mp4_top(path)
    after = [a for a in top if a[1] > mo[1]]
    if not after:
        # moov is last: nothing downstream to disturb. 20 files here.
        with open(path, 'r+b') as fh:
            fh.truncate(mo[1])
            fh.seek(mo[1])
            fh.write(new_moov)
        return len(new_moov)

    free = after[0]
    if free[0] not in (b'free', b'skip'):
        raise TagError('no free atom after moov to absorb %+d bytes; rewriting '
                       'the sample tables has no tested path' % delta)
    newfree = free[2] - delta
    if newfree < 8:
        raise TagError('tags need %d bytes more than the %d of free space this '
                       'file carries' % (8 - newfree, free[2] - 8))
    blob = new_moov + struct.pack('>I', newfree) + b'free' + b'\x00' * (newfree - 8)
    assert len(blob) == mo[2] + free[2], (len(blob), mo[2] + free[2])
    with open(path, 'r+b') as fh:
        fh.seek(mo[1])
        fh.write(blob)                      # mdat does not move: stco holds
    return len(new_moov)


# --------------------------------------------------------------- dispatch

_WRITERS = {'.wav': write_wav, '.mp3': write_id3, '.aif': write_aiff,
            '.aiff': write_aiff, '.aifc': write_aiff, '.flac': write_flac,
            '.m4a': write_m4a, '.m4b': write_m4a, '.mp4': write_m4a}
_READERS = {'.wav': read_wav, '.mp3': read_id3, '.aif': read_aiff,
            '.aiff': read_aiff, '.aifc': read_aiff, '.flac': read_flac,
            '.m4a': read_m4a, '.m4b': read_m4a, '.mp4': read_m4a}


def write(path, tags):
    """Returns True when the audio did not move -- the tag fitted in place."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in _WRITERS:
        raise TagError('no writer for %s yet' % (ext or '(no extension)'))
    at0 = None
    try:
        at0, _n = audio_span(path)
    except TagError:
        pass
    _WRITERS[ext](path, tags)
    try:
        at1, _n = audio_span(path)
        return at0 is None or at1 == at0
    except TagError:
        return True


def read(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in _READERS:
        raise TagError('no reader for %s yet' % (ext or '(no extension)'))
    return _READERS[ext](path)


def _riff_walk(path):
    """Chunk ids by seeking the headers -- a 23 MB wav is not read to answer
    "does this have an id3 chunk", and the one that mattered had it at byte
    4,584,224, past any sane read-ahead."""
    out = []
    with open(path, 'rb') as fh:
        if fh.read(4) != b'RIFF':
            raise TagError('not RIFF')
        fh.seek(12)
        while True:
            h = fh.read(8)
            if len(h) < 8:
                break
            size = struct.unpack('<I', h[4:8])[0]
            out.append(h[:4])
            fh.seek(size + (size & 1), 1)
    return out


def supported(path):
    """Writable *and* safe to write -- the second half is the point.

    Every branch answers by LOOKING AT THE FILE, not at its extension. The
    AIFF branch used to be `_id3_major(path) != 2`, which read byte 0 of a
    FORM file, found "FORM" instead of "ID3", returned None, and compared
    not-equal to 2 -- the right answer by accident, for the wrong reason,
    which is how the AIFF bug stayed invisible.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in _WRITERS:
        return False
    try:
        if ext == '.wav':
            return not any(c in _ID3_CHUNKS for c in _riff_walk(path))
        if ext == '.mp3':
            return _id3_major(path) != 2
        if ext in ('.aif', '.aiff', '.aifc'):
            chunks = _form_chunks(path)
            if not any(c[0] == b'SSND' for c in chunks):
                return False
            _frames, major, old = _aiff_tag(path, chunks)
            if major == 2:
                return False
            return old is None or old is chunks[-1]
        if ext == '.flac':
            blocks, _at = _flac_blocks(path)
            vc = next((b for b in blocks if b[0] == 4), None)
            pad = next((b for b in blocks if b[0] == 1), None)
            return bool(vc and pad and vc[1] < pad[1] and pad[4])
        if ext in ('.m4a', '.m4b', '.mp4'):
            mo, _moov, chain = _mp4_ilst(path)
            if not chain:
                return False
            after = [a for a in _mp4_top(path) if a[1] > mo[1]]
            return not after or after[0][0] in (b'free', b'skip')
    except Exception:
        return False
    return True


# --------------------------------------------------------------- safety

def _replace(path, blob):
    """Write beside the original and rename over it, keeping the mtime moving.

    A rename is atomic on the same filesystem, so an interrupted write leaves
    the original intact rather than a half-tagged file.
    """
    tmp = path + '.saltpod.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(blob)
    os.replace(tmp, path)


def audio_span(path):
    """(offset, length) of the audio, by seeking. Reads none of it.

    THIS EXISTS BECAUSE THE OLD ONE DID NOT SCALE. `audio_payload` returned
    the bytes, and `write()` called it twice to learn one integer -- fine at
    95 MB of WAV, 226 MB of reads per edit once AIFF arrived at 113 MB a
    file. The offset is the thing almost every caller actually wanted.
    """
    ext = os.path.splitext(path)[1].lower()
    n = os.path.getsize(path)
    if ext == '.wav':
        with open(path, 'rb') as fh:
            if fh.read(4) != b'RIFF':
                raise TagError('not a RIFF/WAVE file')
            fh.seek(12)
            while True:
                h = fh.read(8)
                if len(h) < 8:
                    break
                size = struct.unpack('<I', h[4:8])[0]
                if h[:4] == b'data':
                    return fh.tell(), size
                fh.seek(size + (size & 1), 1)
        raise TagError('no data chunk')
    if ext == '.mp3':
        at = _id3_span(path)
        return at, n - at
    if ext in ('.aif', '.aiff', '.aifc'):
        for cid, _h, d, size in _form_chunks(path):
            if cid == b'SSND':
                return d, size
        raise TagError('no SSND chunk')
    if ext == '.flac':
        _blocks, at = _flac_blocks(path)
        return at, n - at
    if ext in ('.m4a', '.m4b', '.mp4'):
        for typ, at, size in _mp4_top(path):
            if typ == b'mdat':
                return at + 8, size - 8
        raise TagError('no mdat atom')
    raise TagError('no payload rule for %s' % ext)


def audio_probe(path, _chunk=1 << 20):
    """(offset, length, sha1) -- the proof, without holding the audio.

    A digest is a better promise than a byte comparison anyway: it is the
    same standard `hash58` already sets for the device, and it does not
    need 113 MB of memory to make it.
    """
    import hashlib
    at, size = audio_span(path)
    h = hashlib.sha1()
    left = size
    with open(path, 'rb') as fh:
        fh.seek(at)
        while left > 0:
            b = fh.read(min(_chunk, left))
            if not b:
                break
            h.update(b)
            left -= len(b)
    return at, size, h.hexdigest()


def audio_payload(path):
    """The bytes themselves. Prefer `audio_probe` unless you need them."""
    at, size = audio_span(path)
    with open(path, 'rb') as fh:
        fh.seek(at)
        return at, fh.read(size)


def verify(path, before, in_place=True):
    """The standard `rehearse` sets for the device, applied to a file.

    TWO PROMISES, and only one of them is unconditional. **The audio bytes
    are never altered** -- that holds for every write. Their *offset* holds
    only when the new tag fits in the space the old one had, which is the
    common case here: the median file carries 1,142 spare bytes. Adding a
    tag to a file that never had one necessarily pushes the audio down, and
    a check that called that corruption would be crying wolf.
    """
    before_at, before_size, before_sha = before
    at, size, sha = audio_probe(path)
    if sha != before_sha:
        raise TagError('audio changed: %d bytes %s -> %d bytes %s'
                       % (before_size, before_sha[:12], size, sha[:12]))
    if in_place and at != before_at:
        raise TagError('audio moved: %d -> %d' % (before_at, at))
    return True


# --------------------------------------------------------------- self-test

def selftest(path):
    """Round-trip a real file: write, read back, prove the audio is untouched."""
    import hashlib
    import shutil
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix='saltpod-tags-')
    work = os.path.join(tmpdir, os.path.basename(path))
    shutil.copy2(path, work)

    probe0 = audio_probe(work)
    at0, len0, sha0 = probe0
    size0 = os.path.getsize(work)
    before = read(work)

    tags = {'title': 'Round Trip', 'artist': 'Saltpod',
            'album': 'Self Test', 'genre': 'Test', 'year': '2026', 'track': '1'}
    write(work, tags)
    got = read(work)
    verify(work, probe0, in_place=bool(at0))

    # and again, to prove a second write does not accumulate chunks
    write(work, tags)
    verify(work, probe0, in_place=bool(at0))
    size2 = os.path.getsize(work)
    write(work, tags)
    verify(work, probe0, in_place=bool(at0))
    if os.path.getsize(work) != size2:
        raise TagError('file grows on repeated writes')

    at1, len1, sha1 = audio_probe(work)
    print('  %s' % os.path.basename(path)[:54])
    print('    audio offset %d -> %d          %s' % (at0, at1, 'same' if at0 == at1 else 'MOVED'))
    print('    audio sha1   %s  %s  (%d bytes)'
          % (sha0[:16], 'same' if sha1 == sha0 else 'CHANGED', len1))
    print('    file size    %d -> %d  (%+d bytes of tag)' % (size0, os.path.getsize(work), os.path.getsize(work) - size0))
    print('    tags before  %s' % (before or '(none)'))
    print('    tags after   %s' % got)
    missing = [k for k, v in tags.items() if got.get(k) != v]
    if missing:
        raise TagError('did not round-trip: %s' % missing)
    print('    stable over three writes, audio untouched')
    shutil.rmtree(tmpdir, ignore_errors=True)
    return True


def main(argv=None):
    a = (argv if argv is not None else sys.argv[1:])
    if not a or a[0] != 'selftest':
        print('usage: python3 -m saltpod.tags selftest <file> [file ...]')
        return 2
    for p in a[1:]:
        selftest(p)
    print('\nall round-trips clean')
    return 0


if __name__ == '__main__':
    sys.exit(main())
