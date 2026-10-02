"""Filing podcasts as podcasts, so they stop hiding under Artists.

Every one of the 653 tracks on this device is `mediatype = 1`, audio --
including ten DeepCast episodes that run to an hour and a half each and
can only be reached by scrolling to the artist. The Podcasts menu is empty.

CLASSIFICATION IS DECLARED, NOT GUESSED. The owner ran his own RSS feed in
2011, iTunes subscribed to it, and iTunes stamped the podcast frames into
the files. They are still there: 11 of 2,895 readable files carry `PCST`
or `WFED`, ten of them pointing at adrianwaterhouse.com/rss.xml and one at
ibiza-voice.com. So there is no heuristic to get wrong -- no guessing from
duration or folder. The file says so or it does not.

WHAT THE FIRMWARE NEEDS, and it is four things rather than one byte:

    mhit+0xD0 = 4           mediatype: 1 audio, 2 video, 4 podcast,
                            8 audiobook
    a playlist with the
    podcast flag set        mhyp+0x2A = 1
    membership in it        an mhip per track
    podcast mhods           14 description, 15 enclosure URL,
                            16 RSS URL, 18 subtitle -- polish, not
                            required for the menu

TWO DOCUMENTED WAYS TO BREAK A LIBRARY, both checked before writing:

  - `mhyp+0x2A` set on MORE THAN ONE playlist and NEITHER shows. Verified:
    no playlist on this device carries it, so creating one is safe.
  - a type-3 `mhsd` must lie BETWEEN type 1 and type 2 or podcasts do not
    list at all. Verified: the sections here are [4, 1, 3, 2, 5, 9].

`mhit+0xA7` is a separate podcast flag that the format notes say "must be
0 for non-podcasts, else iTunes may delete the track on sync". They do not
say it must be 1 for podcasts, so this does not touch it -- an untested
guess at a field whose documented failure mode is deletion is not a trade
worth making.
"""

import struct

from . import ipod_edit as E
from . import itunesdb_write as W
from . import tags as T

MEDIATYPE = 0xD0
AUDIO, VIDEO, PODCAST, AUDIOBOOK = 1, 2, 4, 8
PODCAST_FLAG = 0x2A
PLAYLIST_NAME = 'Podcasts'

# The ID3 frames iTunes writes for a subscribed podcast, and the mhod type
# each maps onto. The frames are already in the owner's files.
FRAME_TO_MHOD = {'TDES': 14, 'TGID': 15, 'WFED': 16, 'TIT3': 18}


class PodcastError(Exception):
    pass


def declares_podcast(path):
    """The podcast metadata in a file, or None. Presence is the signal."""
    ext = path.lower().rsplit('.', 1)[-1]
    try:
        if ext == 'mp3':
            span = T._id3_span(path)
            if not span:
                return None
            with open(path, 'rb') as fh:
                frames, _n, _c = T._id3_read_tag(fh.read(span))
        elif ext in ('aif', 'aiff', 'aifc'):
            frames, _m, _c, _cl = T._aiff_tag(path)
        elif ext == 'wav':
            frames = []
            for cid, _h, d, size in T._riff_chunks_seek(path):
                if cid in T._ID3_CHUNKS:
                    with open(path, 'rb') as fh:
                        fh.seek(d)
                        frames, _n, _c = T._id3_read_tag(fh.read(size))
                    break
        elif ext in ('m4a', 'm4b', 'mp4'):
            # `pcst` and `purl` are the MP4 spellings; none here carry them
            _mo, moov, chain = T._mp4_ilst(path)
            if not chain:
                return None
            off, size = chain[-1]
            kinds = {t for t, _o, _s in T._mp4_children(moov, off + 8, off + size)}
            return {'podcast': True} if (b'pcst' in kinds or b'purl' in kinds) else None
        else:
            return None
    except Exception:
        return None
    ids = {f for f, _p in (frames or [])}
    if not ({'PCST', 'WFED'} & ids):
        return None
    out = {'podcast': True}
    for f, payload in frames:
        if f in FRAME_TO_MHOD:
            v = T._id3_text(payload)
            if v:
                out[f] = v
    return out


def plan(root, want_dbids):
    """What would change, touching nothing. `want_dbids` are the tracks to file."""
    rows = []
    for t in E.tracks(root):
        d = E.track_dbid(t)
        if d not in want_dbids:
            continue
        rows.append({'dbid': d, 'id': E.track_id(t),
                     'title': _mhod(t, 1), 'artist': _mhod(t, 4),
                     'mediatype': t.get32(MEDIATYPE)})
    existing = _find_podcast_playlist(root)
    return {'tracks': rows,
            'playlist_exists': existing is not None,
            'already': sum(1 for r in rows if r['mediatype'] == PODCAST)}


def _mhod(node, typ):
    for c in node.children:
        if c.magic == b'mhod' and W.mhod_type(c) == typ:
            return W.mhod_string(c)
    return ''


def _find_podcast_playlist(root):
    for sect in E.playlist_sections(root):
        for p in E.playlists(root, sect):
            if len(p.hdr) > PODCAST_FLAG + 2 and \
                    struct.unpack_from('<H', p.hdr, PODCAST_FLAG)[0]:
                return p
    return None


def _flagged_playlists(root):
    """Distinct NAMES carrying the flag, not nodes.

    A playlist exists once per playlist section -- `playlist_create` writes
    it into every one -- so counting nodes sees the same list twice and the
    guard below refuses its own work on the second run.
    """
    names = []
    for sect in E.playlist_sections(root):
        for p in E.playlists(root, sect):
            if len(p.hdr) > PODCAST_FLAG + 2 and \
                    struct.unpack_from('<H', p.hdr, PODCAST_FLAG)[0]:
                n = E.pl_name(p)
                if n not in names:
                    names.append(n)
    return names


GROUP_FLAG = 0x10          # mhip: 0x100 marks a show header row
GROUP_ID = 0x14
GROUP_REF = 0x20
GROUP_HEADER = 0x100


def show_of(mhit):
    """Which show an episode belongs to.

    The album field. iTunes puts the podcast's title there and the files
    still carry it -- all ten episodes here say "Adrian Waterhouse
    DeepCast" -- so the grouping needs no heuristic any more than the
    classification did.
    """
    return _mhod(mhit, 3) or _mhod(mhit, 4) or 'Podcast'


def group_episodes(root, name=PLAYLIST_NAME):
    """Give the podcast playlist the two-level structure the firmware wants.

    THE MENU SHOWED 10 AND WOULD NOT OPEN. A flagged podcast playlist is
    not rendered like an ordinary one: the firmware builds SHOW -> EPISODE,
    and it finds the shows by reading header rows out of the `mhip` list.
    saltpod wrote ten ordinary rows and no headers, so the count came from
    the row count and the view had nothing to build from.

    The structure, from research/itunesdb-format.md:

        header mhip   0x10 = 0x100, track id = 0, its own group id,
                      ONE child mhod of type 1 carrying the show's name
        episode mhip  0x10 = 0, its own track id, and 0x20 pointing back
                      at the header's group id

    ordered header-then-its-episodes, so a show and its contents are
    contiguous.

    The flag is handled carefully on purpose: the format research says a
    non-zero group flag on an ORDINARY song "breaks iPods", so this only
    ever writes it on a row it creates itself, never on an episode.
    """
    target = None
    for sect in E.playlist_sections(root):
        if sect.get32(0x0C) != 3:
            continue
        for pl in E.playlists(root, sect):
            if E.pl_name(pl) == name:
                target = pl
    if target is None:
        raise PodcastError('no %s playlist in the type-3 section' % name)

    by_id = {E.track_id(t): t for t in E.tracks(root)}
    rows = [c for c in target.children if c.magic == b'mhip']
    if any(c.get32(GROUP_FLAG) == GROUP_HEADER for c in rows):
        return {'already': True, 'shows': 0, 'episodes': len(rows)}

    # Keep the owner's order inside each show; shows appear in the order
    # their first episode does. Sequence is the product here too.
    order, grouped = [], {}
    for c in rows:
        t = by_id.get(c.get32(0x18))
        sh = show_of(t) if t is not None else 'Podcast'
        if sh not in grouped:
            grouped[sh] = []
            order.append(sh)
        grouped[sh].append(c)

    template = rows[0]
    _tid, gid = E._next_ids(root)
    out = []
    for sh in order:
        head = W.Node(b'mhip', bytes(template.hdr))
        head.set32(0x0C, 1)                 # one child mhod
        head.set16(GROUP_FLAG, GROUP_HEADER)
        head.set32(GROUP_ID, gid)
        head.set32(0x18, 0)                 # a header names a show, not a track
        head.set32(0x1C, E.mac_now())
        head.set32(GROUP_REF, 0)
        if len(head.hdr) > 0x34:
            head.set64(0x2C, 0)             # track dbid: none, this is not a track
        head.children = [W.make_string_mhod(1, sh)]
        out.append(head)
        for c in grouped[sh]:
            c.set16(GROUP_FLAG, 0)
            c.set32(GROUP_REF, gid)
            out.append(c)
        gid += 1

    keep = [c for c in target.children if c.magic != b'mhip']
    target.children = keep + out
    # The count field counts every mhip, headers included.
    target.set32(0x10, len(out))
    return {'already': False, 'shows': len(order), 'episodes': len(rows),
            'rows': len(out), 'names': order}


def apply(root, want_dbids, meta=None):
    """File the given tracks as podcasts. Returns what it did.

    Refuses rather than risks: more than one playlist carrying the podcast
    flag means NONE of them show, so an existing flagged playlist under
    another name stops this.
    """
    flagged = _flagged_playlists(root)
    if len(flagged) > 1:
        raise PodcastError('%d playlists already carry the podcast flag (%s); '
                           'two means the firmware shows neither'
                           % (len(flagged), ', '.join(map(str, flagged))))
    order = [s.get32(0x0C) for s in root.children if s.magic == b'mhsd']
    if 3 in order and 1 in order and 2 in order:
        if not (order.index(1) < order.index(3) < order.index(2)):
            raise PodcastError('the type-3 section is not between type 1 and '
                               'type 2, so podcasts would not list: %s' % order)

    changed, ids = [], []
    for t in E.tracks(root):
        d = E.track_dbid(t)
        if d not in want_dbids:
            continue
        was = t.get32(MEDIATYPE)
        t.set32(MEDIATYPE, PODCAST)
        ids.append(E.track_id(t))
        changed.append({'dbid': d, 'mediatype': (was, PODCAST)})

    made = False
    if flagged:
        name = flagged[0]
    else:
        name = PLAYLIST_NAME
        if not any(E.pl_name(p) == name
                   for sect in E.playlist_sections(root)
                   for p in E.playlists(root, sect)):
            E.playlist_create(root, name)
            made = True
        # THE FLAG GOES ON SECTION 3 ONLY. A playlist is created in every
        # playlist section, and flagging all of them produced two flagged
        # lists in the first rehearsal -- the documented way to make the
        # firmware show NEITHER. Type 3 is the podcast-style playlist list;
        # that is where the flag belongs, and section 2 keeps its plain
        # copy so the list still appears under Playlists.
        for sect in E.playlist_sections(root):
            if sect.get32(0x0C) != 3:
                continue
            p = E.find_playlist(root, sect, name)
            struct.pack_into('<H', p.hdr, PODCAST_FLAG, 1)
    if ids:
        E.playlist_set_tracks(root, name, ids)
    return {'tracks': changed, 'playlist': name, 'created': made,
            'members': len(ids)}
