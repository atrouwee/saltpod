#!/usr/bin/env python3
"""Smart-playlist rules: parse the mhod 50/51 chunks and evaluate them against
real tracks, so a smart playlist's on-device membership can be refreshed
instead of trusting whatever iTunes last wrote there.

WHY THIS EXISTS. `research/SMART-PLAYLISTS.md` found that every smart
playlist's *materialised* membership (the `mhip` children iTunes writes under
its `mhyp`) is a snapshot frozen at the last iTunes sync -- nothing on the
device, and nothing elsewhere in this repo, ever re-evaluates it. "Recently
Added" has shown 0 members in 11 backups spanning 2026-09-27 through
2026-10-01 while 178 of 653 tracks genuinely qualify. This module is the
piece that actually answers "what SHOULD be in this smart playlist right
now": decode the rule tree, then run it.

WIRE FORMAT (measured against this device's real iTunesDB, v0x75, 653
tracks, and cross-checked against 11 backups -- see
`research/SMART-PLAYLISTS.md` for the full derivation; this is the summary
needed to read the code below):

    mhyp (a playlist)
      mhod 50  SPLPref   96 bytes total (24-byte mhod header + 72-byte body)
               liveupdate/checkrules/checklimits/limittype/limitsort as
               single bytes, limitvalue as a LE u32 at body+0x08, all
               LITTLE-ENDIAN like the rest of the file.
      mhod 51  SPLRules  body starts `SLst`, then rule_count and a match
               operator (0=AND/"all", 1=OR/"any"), then rules starting at
               body offset 0x88. EVERYTHING FROM THE `SLst` MAGIC ONWARDS IS
               BIG-ENDIAN -- the one place in the whole iTunesDB that is not
               little-endian, including string rule values (UTF-16BE). Get
               this backwards and every multi-byte field silently reads as
               nonsense that still happens to look like a plausible number.

    Each rule (56-byte prefix + a value block, all BE):
        0x00 u32 field id        0x04 u32 action id (a bitmask, see ACTIONS)
        0x08 44 bytes padding    0x34 u32 value length (0x44=68 for non-string)
        0x38 value: UTF-16BE text for string fields, length bytes, no
             terminator; for everything else, 68 bytes of
             fromvalue/fromdate/fromunits/tovalue/todate/tounits (u64/i64
             pairs) plus 20 trailing unknown bytes.

    "In the last N units" dates do not store a value at all: fromvalue is
    the literal sentinel 0x2dae2dae2dae2dae ("today, compute at eval time"),
    and the real window is `fromdate * fromunits` seconds -- fromdate
    negative ("N units ago"), fromunits a plain second count (604800 = a
    week), not an enum.

THE SAFETY RULE. `parse_rules()` marks a playlist `understood: False` the
moment ANY of its rules uses a field id, an action id, or a field/action
PAIRING this module does not have in its tables -- or uses a field id this
module cannot fetch a value for, even if the id itself is recognised (a
rule nobody can evaluate is exactly as dangerous as one nobody recognises:
either way, silently skipping it produces a playlist that is wrong but
looks complete). `evaluate()` refuses outright -- raises `NotUnderstood`,
never returns a partial list -- rather than apply the rules it does
recognise and quietly drop the rest. Two real cases on this device:

  - "Favourite Songs" uses field 0x9a, which is in neither libgpod's field
    table nor its `strawberrymusicplayer` fork's (checked both). Refused.
  - "Recently Added", "Recently Played" and "Top 25 Most Played" all use
    field 0x39 (Podcast), which libgpod's OWN reference evaluator declares
    int-typed but never actually implements (no `case` for it at all in
    `itdb_splr_eval` -- grepped the function body). Ported literally, that
    bug makes every AND-matched playlist using it permanently empty. This
    module does not copy that bug: see the comment by `FIELD_ACCESSORS`
    below for what it does instead and why.

Standard library only. Read-only: nothing here opens the device for
writing. Additive: nothing in this repo imports this module yet.
"""
import os
import random
import struct
import sys
import time

from . import ipod_edit as E
from . import itunesdb as I
from . import itunesdb_write as W

MAC_EPOCH = I.MAC_EPOCH


class NotUnderstood(Exception):
    """Raised by evaluate() for a playlist parse_rules() could not fully
    decode. Never silently swallowed -- a caller that wants "skip playlists
    we can't evaluate" has to catch this explicitly and say so."""


# ======================================================== field/action tables
#
# Transcribed from research/SMART-PLAYLISTS.md section 1.4/1.5, which took
# them from libgpod's itdb.h (ItdbSPLField, ItdbSPLAction) and cross-checked
# the ones this device actually uses against real bytes. Anything NOT in
# these two dicts is, by construction, not understood -- that is the point
# of keeping them as the single source of truth rather than inlining ids.

# field id -> (name, type). type is one of:
#   string | int | date | bool | playlist | binary_and
FIELDS = {
    0x02: ('Song Name', 'string'),
    0x03: ('Album', 'string'),
    0x04: ('Artist', 'string'),
    0x05: ('Bitrate', 'int'),
    0x06: ('Sample Rate', 'int'),
    0x07: ('Year', 'int'),
    0x08: ('Genre', 'string'),
    0x09: ('Kind', 'string'),
    0x0a: ('Date Modified', 'date'),
    0x0b: ('Track Number', 'int'),
    0x0c: ('Size', 'int'),
    0x0d: ('Time', 'int'),
    0x0e: ('Comment', 'string'),
    0x10: ('Date Added', 'date'),
    0x12: ('Composer', 'string'),
    0x16: ('Play Count', 'int'),
    0x17: ('Last Played', 'date'),
    0x18: ('Disc Number', 'int'),
    0x19: ('Rating', 'int'),
    0x1f: ('Compilation', 'bool'),
    0x23: ('BPM', 'int'),
    0x27: ('Grouping', 'string'),
    0x28: ('Playlist', 'playlist'),
    0x29: ('Purchase', 'bool'),
    0x36: ('Description', 'string'),
    0x37: ('Category', 'string'),
    0x39: ('Podcast', 'int'),          # see FIELD_ACCESSORS: L declares this,
                                        # then never implements it -- we do.
    0x3c: ('Video Kind', 'binary_and'),
    0x3e: ('TV Show', 'string'),
    0x3f: ('Season Number', 'int'),
    0x44: ('Skip Count', 'int'),
    0x45: ('Last Skipped', 'date'),
    0x47: ('Album Artist', 'string'),
    0x4e: ('Sort Song Name', 'string'),
    0x4f: ('Sort Album', 'string'),
    0x50: ('Sort Artist', 'string'),
    0x51: ('Sort Album Artist', 'string'),
    0x52: ('Sort Composer', 'string'),
    0x53: ('Sort TV Show', 'string'),
    0x5a: ('Album Rating', 'int'),
    # 0x9a is deliberately NOT here. It appears on this device's "Favourite
    # Songs" playlist and in no libgpod field table (checked fadingred/libgpod
    # and the strawberrymusicplayer fork). Guessing its meaning -- iTunes
    # 12.2's Loved/Disliked flag is the leading hypothesis in the research
    # doc -- would be exactly the "looks right, is wrong" failure this
    # module exists to avoid. Any playlist using it is refused, not guessed.
}

# action id (a bitmask, not sequential) -> name.
ACTIONS = {
    0x00000001: 'IS_INT',
    0x00000010: 'IS_GREATER_THAN',
    0x00000040: 'IS_LESS_THAN',
    0x00000100: 'IS_IN_THE_RANGE',
    0x00000200: 'IS_IN_THE_LAST',
    0x00000400: 'BINARY_AND',
    0x00000800: 'BINARY_UNKNOWN1',
    0x01000001: 'IS_STRING',
    0x01000002: 'CONTAINS',
    0x01000004: 'STARTS_WITH',
    0x01000008: 'ENDS_WITH',
    0x02000001: 'IS_NOT_INT',
    0x02000010: 'IS_NOT_GREATER_THAN',
    0x02000040: 'IS_NOT_LESS_THAN',
    0x02000100: 'IS_NOT_IN_THE_RANGE',
    0x02000200: 'IS_NOT_IN_THE_LAST',
    0x02000400: 'NOT_BINARY_AND',
    0x02000800: 'BINARY_UNKNOWN2',
    0x03000001: 'IS_NOT',
    0x03000002: 'DOES_NOT_CONTAIN',
    0x03000004: 'DOES_NOT_START_WITH',
    0x03000008: 'DOES_NOT_END_WITH',
}

# field type -> set of action NAMES legal for it (itdb_splr_get_action_type).
# An evaluator is told to validate against this, not accept any pairing --
# a recognised field with an action that doesn't belong to its type is just
# as much "not understood" as an unrecognised id would be.
LEGAL_ACTIONS = {
    'string': {'IS_STRING', 'IS_NOT', 'CONTAINS', 'DOES_NOT_CONTAIN',
               'STARTS_WITH', 'DOES_NOT_START_WITH', 'ENDS_WITH', 'DOES_NOT_END_WITH'},
    'int': {'IS_INT', 'IS_NOT_INT', 'IS_GREATER_THAN', 'IS_NOT_GREATER_THAN',
            'IS_LESS_THAN', 'IS_NOT_LESS_THAN', 'IS_IN_THE_RANGE', 'IS_NOT_IN_THE_RANGE'},
    'bool': {'IS_INT', 'IS_NOT_INT'},
    'date': {'IS_INT', 'IS_NOT_INT', 'IS_GREATER_THAN', 'IS_NOT_GREATER_THAN',
             'IS_LESS_THAN', 'IS_NOT_LESS_THAN', 'IS_IN_THE_RANGE', 'IS_NOT_IN_THE_RANGE',
             'IS_IN_THE_LAST', 'IS_NOT_IN_THE_LAST'},
    'playlist': {'IS_INT', 'IS_NOT_INT'},
    'binary_and': {'BINARY_AND', 'NOT_BINARY_AND', 'BINARY_UNKNOWN1', 'BINARY_UNKNOWN2'},
}

LIMIT_TYPES = {1: 'minutes', 2: 'MB', 3: 'songs', 4: 'hours', 5: 'GB'}

# limitsort low byte -> name. The "least/lowest" variants of the last four
# are not separate wire values: same byte, with the limit's `opposite` flag
# set (see _parse_pref).
LIMIT_SORTS = {
    0x02: 'random',
    0x03: 'song name',
    0x04: 'album',
    0x05: 'artist',
    0x07: 'genre',
    0x10: 'most recently added',
    0x14: 'most often played',
    0x15: 'most recently played',
    0x17: 'highest rating',
}
_ALPHA_SORTS = {0x03: 'title', 0x04: 'album', 0x05: 'artist', 0x07: 'genre'}
_RANKED_SORTS = {0x10: 'date_added', 0x14: 'play_count', 0x15: 'last_played', 0x17: 'rating'}

SPL_DATE_SENTINEL = 0x2dae2dae2dae2dae      # ITDB_SPL_DATE_IDENTIFIER (L)

# field id -> key in the track dict this module builds (see load_tracks()).
# A field present in FIELDS but absent here (None, or simply missing) is
# "known" for decoding purposes but has nowhere to get a value from -- such
# a rule is marked not-understood rather than silently treated as False.
FIELD_ACCESSORS = {
    0x02: 'title', 0x03: 'album', 0x04: 'artist', 0x05: 'bitrate',
    0x06: 'sample_rate', 0x07: 'year', 0x08: 'genre', 0x09: 'filetype',
    0x0a: 'date_modified', 0x0b: 'track_no', 0x0c: 'size', 0x0d: 'ms',
    0x0e: 'comment', 0x10: 'date_added', 0x12: 'composer',
    0x16: 'play_count', 0x17: 'last_played', 0x18: 'disc_no', 0x19: 'rating',
    0x1f: 'compilation', 0x23: 'bpm', 0x27: 'grouping',
    0x28: None,                      # Playlist: a cross-playlist membership
                                      # test, not a track field -- needs the
                                      # whole tree, which evaluate(parsed,
                                      # tracks) does not receive. Not seen on
                                      # this device (research 3.3). Refused
                                      # rather than half-wired.
    0x29: None,                      # Purchase: no documented mhit offset.
    0x36: 'desc', 0x37: 'category',
    # Podcast (0x39): libgpod's own itdb_splr_eval has NO case for this field
    # at all despite itdb_splr_get_field_type declaring it int -- confirmed
    # by reading the function body in itdb_playlist.c. Ported literally that
    # makes every AND-matched rule using it permanently false, which would
    # silently empty "Recently Added", "Recently Played" and "Top 25 Most
    # Played" on this device -- all three use it. CHOICE MADE HERE: derive
    # it from mediatype instead, the same way Video Kind already has to
    # (mediatype bit 0x4 covers both podcast=4 and video podcast=6). This
    # is implementing the field's documented type, not guessing a new one.
    0x39: 'podcast',
    0x3c: 'mediatype',                # Video Kind: raw bitmask, see load_tracks()
    0x3e: None,                       # TV Show: mhod types 19-21 cover this
                                      # region but research/itunesdb-format.md
                                      # does not pin which of the three is
                                      # which -- guessing wrong would silently
                                      # read the wrong string. Refused.
    0x3f: None,                      # Season Number: no documented offset.
    0x44: 'skip_count', 0x45: 'last_skipped',
    0x47: 'album_artist',
    0x4e: 'sort_title', 0x4f: 'sort_album', 0x50: 'sort_artist',
    0x51: 'sort_album_artist', 0x52: 'sort_composer', 0x53: 'sort_tvshow',
    0x5a: None,                      # Album Rating: no documented offset;
                                      # research notes it may be computed
                                      # from the album's tracks rather than
                                      # stored at all.
}

# mhod type -> track-dict key, for the string fields read off each mhit's
# own mhod children. 1-14 from itunesdb.py's own MHOD map (kept in sync by
# hand since that map is file-scope private there); 22-31 are the sort/
# album-artist region research/itunesdb-format.md section 4 documents but
# itunesdb.py's reader does not decode.
_MHOD_STRING_FIELDS = {
    1: 'title', 3: 'album', 4: 'artist', 5: 'genre', 6: 'filetype',
    8: 'comment', 9: 'category', 12: 'composer', 13: 'grouping', 14: 'desc',
    22: 'album_artist', 23: 'sort_artist', 27: 'sort_title', 28: 'sort_album',
    29: 'sort_album_artist', 30: 'sort_composer', 31: 'sort_tvshow',
}


# =============================================================== mhod 50/51

def _mhod(mhyp, typ):
    for c in mhyp.children:
        if c.magic == b'mhod' and W.mhod_type(c) == typ:
            return c
    return None


def _parse_pref(node):
    """mhod 50, SPLPref: 72-byte body, little-endian (unlike mhod 51)."""
    b = node.body
    if len(b) < 72:
        raise ValueError('mhod 50 (SPLPref) body is %d bytes, expected >= 72' % len(b))
    limitvalue = struct.unpack_from('<I', b, 0x08)[0]
    # MEASURED, not in research/SMART-PLAYLISTS.md: the doc calls body+0x10
    # (56 bytes) "padding, zero on every D sample". On THIS read it is not --
    # every one of the 7 user-visible smart playlists carries a nonzero byte
    # at +0x10 (0x05 on six of them, 0x01 on "Favourite Songs"). Nothing
    # here interprets it; it rides along in `raw` untouched. Recorded because
    # the doc's claim is now known to be incomplete, not because this module
    # acts on it.
    return {
        'liveupdate': bool(b[0x00]),
        'checkrules': bool(b[0x01]),
        'checklimits': bool(b[0x02]),
        'limittype': b[0x03],
        'limitsort': b[0x04],
        'limitvalue': limitvalue,
        'matchcheckedonly': bool(b[0x0C]),
        'opposite': bool(b[0x0D]),
        'raw': bytes(b),
    }


def _mac_to_unix(v):
    """A rule's absolute-date value (Mac time) to a Unix timestamp. Unlike
    itunesdb._mactime(), 0 is not special-cased to None here: a rule's
    fromvalue is a value someone typed, not a track field where 0 means
    "never set"."""
    return v - MAC_EPOCH


def _decode_rule(field, action, body, off, vlen):
    raw = bytes(body[off: off + 56 + vlen])
    fname, ftype = FIELDS.get(field, (None, None))
    aname = ACTIONS.get(action)
    negate = bool(action & 0x02000000)          # high byte bit 1 = NOT (1.5)
    legal = ftype is not None and aname is not None and aname in LEGAL_ACTIONS.get(ftype, ())
    has_accessor = FIELD_ACCESSORS.get(field) is not None
    understood = bool(ftype) and bool(aname) and legal and has_accessor

    if ftype == 'string':
        value = {'string': body[off + 0x38: off + 0x38 + vlen].decode('utf-16-be', 'replace')}
    else:
        fromvalue, fromdate, fromunits, tovalue, todate, tounits = \
            struct.unpack_from('>QqQQqQ', body, off + 0x38)
        if ftype == 'date' and aname in ('IS_IN_THE_LAST', 'IS_NOT_IN_THE_LAST'):
            # fromvalue here is the sentinel, not a real value (1.6) -- the
            # window is computed at evaluate() time from fromdate*fromunits.
            value = {'from_date_count': fromdate, 'from_unit_seconds': fromunits,
                     'sentinel': fromvalue}
        elif ftype == 'date':
            value = {'from': _mac_to_unix(fromvalue), 'to': _mac_to_unix(tovalue)}
        else:
            value = {'from': fromvalue, 'to': tovalue}

    reason = None
    if not understood:
        if ftype is None:
            reason = 'field %#04x is not in the SPLField table' % field
        elif aname is None:
            reason = 'action %#010x is not in the SPLAction table' % action
        elif not legal:
            reason = 'action %s is not legal for field %s (type %s)' % (aname, fname, ftype)
        else:
            reason = ('field %s (%#04x) is recognised but this evaluator has no '
                       'data source for it' % (fname, field))

    return {
        'field': field, 'field_name': fname or ('field_%#04x' % field), 'field_type': ftype,
        'action': action, 'action_name': aname, 'negate': negate,
        'value': value, 'raw': raw, 'understood': understood, 'reason': reason,
    }


def _parse_rules(node):
    """mhod 51, SPLRules. Big-endian from the SLst magic onwards -- the one
    exception to the file's own little-endian convention (1.3)."""
    b = node.body
    if b[:4] != b'SLst':
        raise ValueError('mhod 51 (SPLRules) body does not start with SLst')
    unk004, rule_count, matchop = struct.unpack_from('>III', b, 4)
    off = 0x88
    rules = []
    for _ in range(rule_count):
        field, action = struct.unpack_from('>II', b, off)
        vlen = struct.unpack_from('>I', b, off + 0x34)[0]
        rules.append(_decode_rule(field, action, b, off, vlen))
        off += 56 + vlen
    return bool(matchop), rules, unk004


def parse_rules(mhyp):
    """A playlist's mhod 50+51, decoded into a plain structure:

        {match_any, rules: [{field, field_name, field_type, action,
         action_name, negate, value, raw, understood, reason}, ...],
         limit: {enabled, type, type_name, value, sort, sort_name, opposite,
         matchcheckedonly, raw}, live, understood, reasons, unk004}

    `understood` is False the moment any rule's field or action is not in
    FIELDS/ACTIONS, pairs a field with an action illegal for its type, or
    names a field this module has no data source for (FIELD_ACCESSORS) --
    or, when the limit is enabled, if `limitsort` is not one this module
    knows how to apply. `reasons` collects every reason found, even when
    only the first is what trips `understood`, so a caller can show the
    whole picture (see 2.4 in the research doc: "Favourite Songs" has both
    an unrecognised field AND an unrecognised limitsort, not just one).
    """
    m50, m51 = _mhod(mhyp, 50), _mhod(mhyp, 51)
    if m50 is None or m51 is None:
        raise ValueError('not a smart playlist: missing mhod 50 and/or 51')
    pref = _parse_pref(m50)
    match_any, rules, unk004 = _parse_rules(m51)

    reasons = [r['reason'] for r in rules if r['reason']]
    limit_understood = True
    if pref['checklimits'] and pref['limitsort'] not in LIMIT_SORTS:
        limit_understood = False
        reasons.append('limitsort %#x is not a recognised ItdbLimitSort value' % pref['limitsort'])

    understood = all(r['understood'] for r in rules) and limit_understood
    return {
        'match_any': match_any,
        'rules': rules,
        'limit': {
            'enabled': pref['checklimits'],
            'type': pref['limittype'],
            'type_name': LIMIT_TYPES.get(pref['limittype']),
            'value': pref['limitvalue'],
            'sort': pref['limitsort'],
            'sort_name': LIMIT_SORTS.get(pref['limitsort']),
            'opposite': pref['opposite'],
            'matchcheckedonly': pref['matchcheckedonly'],
            'raw': pref['raw'],
        },
        'live': pref['liveupdate'],
        'understood': understood,
        'reasons': reasons,
        'unk004': unk004,
    }


# ===================================================================== tracks

def load_tracks(root):
    """Every track on the device as a plain dict, keyed the way
    FIELD_ACCESSORS expects. Built directly off the itunesdb_write tree
    (not itunesdb.read()) because the narrow 14-field record itunesdb.py
    exposes does not carry `mediatype` at all (needed for Video Kind and
    the derived Podcast field) -- see research/SMART-PLAYLISTS.md section
    3.2. Offsets below are mhit-header-relative, from
    research/itunesdb-format.md section 3; mactime conversion reuses
    itunesdb._mactime, the same helper playcounts.py already shares.

    Every value here comes from the mhit as it stands in the iTunesDB --
    play_count/rating/last_played are therefore only as fresh as the last
    iTunes sync (playcounts.py's own caveat). Merging the `Play Counts`
    sidecar for a truly live count is the caller's job, not this loader's:
    `playcounts.read()` already knows how to pair a sidecar to a database
    positionally and refuses when the counts disagree, and duplicating that
    refusal logic here would be the kind of guess this module avoids.
    """
    out = []
    for t in E.tracks(root):
        h = t.hdr

        def u32(o, default=0):
            return struct.unpack_from('<I', h, o)[0] if len(h) >= o + 4 else default

        def u8(o, default=0):
            return h[o] if len(h) > o else default

        mediatype = u32(0xD0)
        rec = {
            'id': E.track_id(t),
            'visible': u32(0x14),
            'compilation': u8(0x1E),
            'rating': u8(0x1F),
            'date_modified': I._mactime(u32(0x20)),
            'size': u32(0x24),
            'ms': u32(0x28),
            'track_no': u32(0x2C),
            'year': u32(0x34),
            'bitrate': u32(0x38),
            'sample_rate': u32(0x3C) >> 16,
            'play_count': u32(0x50),
            'play_count2': u32(0x54),
            'last_played': I._mactime(u32(0x58)),
            'disc_no': u32(0x5C),
            'date_added': I._mactime(u32(0x68)),
            'bookmark_ms': u32(0x6C),
            'checked': u8(0x78, 0) == 0,            # mhit+0x78: "0 = checked" (W)
            'bpm': struct.unpack_from('<H', h, 0x7A)[0] if len(h) >= 0x7C else 0,
            'skip_count': u32(0x9C),
            'last_skipped': I._mactime(u32(0xA0)),
            'mediatype': mediatype,
            # mediatype bit 0x4 covers both podcast(4) and video podcast(6) --
            # see FIELD_ACCESSORS for why this field is derived rather than
            # left unimplemented the way libgpod leaves it.
            'podcast': 1 if (mediatype & 0x04) else 0,
            'title': '', 'album': '', 'artist': '', 'genre': '', 'filetype': '',
            'comment': '', 'category': '', 'composer': '', 'grouping': '', 'desc': '',
            'album_artist': '', 'sort_artist': '', 'sort_title': '', 'sort_album': '',
            'sort_album_artist': '', 'sort_composer': '', 'sort_tvshow': '',
        }
        for c in t.children:
            if c.magic == b'mhod':
                name = _MHOD_STRING_FIELDS.get(W.mhod_type(c))
                if name:
                    try:
                        rec[name] = W.mhod_string(c)
                    except Exception:
                        pass
        out.append(rec)
    return out


def materialized_ids(mhyp):
    """Track ids already materialised as `mhip` children of this playlist --
    what iTunes last wrote, for comparing against evaluate()'s fresh answer."""
    return [c.get32(0x18) for c in mhyp.children if c.magic == b'mhip']


# ================================================================== evaluate

def _eval_string(action, v, rule_s):
    # "If either string is empty/absent, every comparison returns FALSE" --
    # research 1.7, transcribed from itdb_splr_eval. This is a hard floor
    # applied BEFORE positive/negative logic: DOES_NOT_CONTAIN on a track
    # with no value is false too, not true-by-double-negative.
    if not v or not rule_s:
        return False
    if action == 'IS_STRING':
        return v == rule_s
    if action == 'IS_NOT':
        return v != rule_s
    if action == 'CONTAINS':
        return rule_s in v
    if action == 'DOES_NOT_CONTAIN':
        return rule_s not in v
    if action == 'STARTS_WITH':
        return v.startswith(rule_s)
    if action == 'DOES_NOT_START_WITH':
        return not v.startswith(rule_s)
    if action == 'ENDS_WITH':
        return v.endswith(rule_s)
    if action == 'DOES_NOT_END_WITH':
        return not v.endswith(rule_s)
    return False          # unreachable once parse_rules has validated the pair


def _eval_bool(action, v):
    v = v or 0
    if action == 'IS_INT':
        return v != 0
    if action == 'IS_NOT_INT':
        return v == 0
    return False


def _eval_int(action, v, value):
    v = v if v is not None else 0
    fromv, tov = value['from'], value['to']
    if action == 'IS_INT':
        return v == fromv
    if action == 'IS_NOT_INT':
        return v != fromv
    if action == 'IS_GREATER_THAN':
        return v > fromv
    if action == 'IS_NOT_GREATER_THAN':
        return not v > fromv
    if action == 'IS_LESS_THAN':
        return v < fromv
    if action == 'IS_NOT_LESS_THAN':
        return not v < fromv
    if action in ('IS_IN_THE_RANGE', 'IS_NOT_IN_THE_RANGE'):
        lo, hi = (fromv, tov) if fromv <= tov else (tov, fromv)
        inrange = lo <= v <= hi
        return inrange if action == 'IS_IN_THE_RANGE' else not inrange
    return False


def _eval_date(action, v, value, now):
    if action in ('IS_IN_THE_LAST', 'IS_NOT_IN_THE_LAST'):
        # research 1.6/1.7: t = now + fromdate*fromunits (fromdate negative);
        # "in the last" means stored_value > t. A track with no timestamp at
        # all was definitely not played/added inside the window, so this
        # folds cleanly to False/True without a separate absent-value rule.
        window_start = now + value['from_date_count'] * value['from_unit_seconds']
        inlast = v is not None and v > window_start
        return inlast if action == 'IS_IN_THE_LAST' else not inlast
    if v is None:
        # DECISION: unlike IN_THE_LAST above, an absolute date comparison
        # against a track with no recorded date (never modified/played/
        # added) is treated as a hard non-match for BOTH the positive and
        # the NOT form -- consistent with the string rule's documented
        # "absent is always false", not derived from L's source (which the
        # research doc does not detail to this level for dates). A track
        # that was "never played" is not thereby "last played before 2010".
        return False
    fromv, tov = value['from'], value['to']
    if action == 'IS_INT':
        return v == fromv
    if action == 'IS_NOT_INT':
        return v != fromv
    if action == 'IS_GREATER_THAN':
        return v > fromv
    if action == 'IS_NOT_GREATER_THAN':
        return not v > fromv
    if action == 'IS_LESS_THAN':
        return v < fromv
    if action == 'IS_NOT_LESS_THAN':
        return not v < fromv
    if action in ('IS_IN_THE_RANGE', 'IS_NOT_IN_THE_RANGE'):
        lo, hi = (fromv, tov) if fromv <= tov else (tov, fromv)
        inrange = lo <= v <= hi
        return inrange if action == 'IS_IN_THE_RANGE' else not inrange
    return False


def _eval_binary(action, v, value):
    v = v or 0
    fromv, tov = value['from'], value['to']
    if action == 'BINARY_AND':
        return (v & fromv) != 0
    if action == 'NOT_BINARY_AND':
        return (v & fromv) == 0
    if action in ('BINARY_UNKNOWN1', 'BINARY_UNKNOWN2'):
        # L's own doc comment hypothesises ((val & from) == val) and (val &
        # to), explicitly unsure ("probably"). The only real example on this
        # device (Rentals, mask 0x42/to 0x8000, and a second rule with
        # from==to==0x8000) has from==to in the one that matters, which does
        # not discriminate this formula from a plain BINARY_AND either way.
        # Implemented per L's hypothesis rather than guessed differently,
        # and untested beyond "does not raise and does not misfire on this
        # device's all-audio (mediatype=1) library".
        positive = (v & fromv) == v and bool(v & tov)
        return positive if action == 'BINARY_UNKNOWN1' else not positive
    return False


def _eval_rule(rule, track, now):
    ftype = rule['field_type']
    key = FIELD_ACCESSORS.get(rule['field'])
    v = track.get(key) if key else None
    if ftype == 'string':
        return _eval_string(rule['action_name'], v, rule['value'].get('string'))
    if ftype == 'bool':
        return _eval_bool(rule['action_name'], v)
    if ftype == 'int':
        return _eval_int(rule['action_name'], v, rule['value'])
    if ftype == 'date':
        return _eval_date(rule['action_name'], v, rule['value'], now)
    if ftype == 'binary_and':
        return _eval_binary(rule['action_name'], v, rule['value'])
    raise NotUnderstood('rule on field %r reached evaluation without a field type -- '
                         'parse_rules() should have refused this playlist' % rule['field_name'])


def _matches(parsed, track, now):
    rules = parsed['rules']
    if not rules:
        return True             # "an empty rule list always matches" (1.7)
    if parsed['match_any']:
        return any(_eval_rule(r, track, now) for r in rules)
    return all(_eval_rule(r, track, now) for r in rules)


def _alpha_key(s):
    s = s or ''
    # MEASURED (not in research/SMART-PLAYLISTS.md): the one real tie this
    # device's "Top 25 Most Played" has to break at the limit boundary --
    # 29 tracks tied at play_count==2, only 3 slots left under the limit --
    # is resolved by iTunes as "A Guy Called Gerald", "Bachar Mar-Khalifé",
    # "Beyoncé", in that order, NOT "28th Street Crew" first as a plain
    # byte/codepoint or even a plain casefolded compare would put it (digit
    # < letter in both ASCII and Unicode). Reproduced here by sorting
    # letter-led names before anything else, case-insensitively, and
    # pushing digit-led names after them. One sample point -- the device
    # offers only this one real tie wide enough to expose it -- but it
    # reproduces that tie's order and all of this playlist's smaller ties
    # (a 9-way and a 4-way, both at non-boundary play counts, both already
    # unambiguous in plain alphabetical order either way) exactly.
    return (0 if s[:1].isalpha() else 1, s.casefold())


def _sort_for_limit(tracks, lim):
    ls = lim['sort']
    if ls == 0x02:
        out = list(tracks)
        random.shuffle(out)
        return out
    if ls in _ALPHA_SORTS:
        field = _ALPHA_SORTS[ls]
        # The `opposite` flag's effect on an alphabetical sort is not
        # documented or exercised on this device (only "most often played"
        # and, unusably, "random" are ever configured with checklimits=1
        # here) -- left ascending regardless of `opposite` rather than
        # guessed at reversed.
        return sorted(tracks, key=lambda t: _alpha_key(t.get(field)))
    if ls in _RANKED_SORTS:
        field = _RANKED_SORTS[ls]
        sign = 1 if lim['opposite'] else -1
        return sorted(tracks, key=lambda t: (sign * (t.get(field) or 0), _alpha_key(t.get('artist'))))
    raise NotUnderstood('limitsort %#x has no sort implementation' % ls)


def _apply_limit(matched, lim):
    ordered = _sort_for_limit(matched, lim)
    kind = lim['type']
    out, total = [], 0.0
    for t in ordered:
        if kind == 3:
            add = 1.0
        elif kind == 1:
            add = (t.get('ms') or 0) / 60000.0
        elif kind == 4:
            add = (t.get('ms') or 0) / 3600000.0
        elif kind == 2:
            add = (t.get('size') or 0) / 1048576.0
        elif kind == 5:
            add = (t.get('size') or 0) / 1073741824.0
        else:
            raise NotUnderstood('limittype %r has no implementation' % kind)
        if total + add > lim['value']:
            break            # "the last track that would overflow it is dropped" (1.7)
        out.append(t)
        total += add
    return out


def evaluate(parsed, tracks, now=None):
    """Apply `parsed` (from parse_rules()) to `tracks` (from load_tracks(),
    or any list of dicts using the same keys) and return the ordered list
    of matching track dicts.

    Refuses -- raises NotUnderstood -- rather than evaluate the rules it
    does recognise on a playlist parse_rules() marked not understood. A
    half-applied rule set produces a list that is wrong and gives no sign
    of it; refusing is the only safe default.
    """
    if not parsed['understood']:
        raise NotUnderstood('playlist is not fully understood: ' + '; '.join(parsed['reasons']))
    now = time.time() if now is None else now
    lim = parsed['limit']
    cand = [t for t in tracks if t.get('checked', True)] if lim['matchcheckedonly'] else list(tracks)
    matched = [t for t in cand if _matches(parsed, t, now)]
    if lim['enabled']:
        matched = _apply_limit(matched, lim)
    return matched


# ===================================================================== describe

def why_not(parsed, track, now=None):
    """Which rules reject this track -- the explanation behind a `check`
    miss.

    A MISS IS NO LONGER AUTOMATICALLY OUR BUG. The device's `mhip` list is
    a snapshot iTunes materialised at some past moment, and saltpod now
    WRITES to the device as well as reading it. The first real run of
    `smartlists check` reported "Recently Added: FAIL, 9 misses" -- and
    all nine were the podcast episodes saltpod itself had filed the day
    before, correctly excluded by that playlist's own `Podcast IS_NOT 1`
    rule. The evaluator was right and the diff was describing it as
    broken.

    So the useful output is not a count but a reason. Returns the list of
    rules that rejected the track, as described strings.
    """
    now = time.time() if now is None else now
    return [describe_rule(r) for r in parsed['rules']
            if not _eval_rule(r, track, now)]


def describe_rule(r):
    aname = r['action_name'] or ('action %#010x (unrecognised)' % r['action'])
    if r['field_type'] == 'string':
        val = repr(r['value'].get('string'))
    elif 'from_date_count' in r['value']:
        val = 'in the last %d x %ds' % (-r['value']['from_date_count'], r['value']['from_unit_seconds'])
    elif r['value']:
        f, t = r['value'].get('from'), r['value'].get('to')
        val = str(f) if f == t else '%s..%s' % (f, t)
    else:
        val = '?'
    tag = '' if r['understood'] else '  [NOT UNDERSTOOD: %s]' % r['reason']
    return '%s %s %s%s' % (r['field_name'], aname, val, tag)


def describe(parsed):
    lines = []
    if not parsed['rules']:
        lines.append('match everything (no rules)')
    else:
        lines.append('match %s of:' % ('ANY' if parsed['match_any'] else 'ALL'))
        for r in parsed['rules']:
            lines.append('  - ' + describe_rule(r))
    lim = parsed['limit']
    if lim['enabled']:
        sort_desc = lim['sort_name'] or ('sort %#x (unrecognised)' % lim['sort'])
        lines.append('limit: %s %s, selected by %s%s' % (
            lim['value'], lim['type_name'] or ('type %r' % lim['type']),
            sort_desc, ' (reversed)' if lim['opposite'] else ''))
    else:
        lines.append('no limit')
    if lim['matchcheckedonly']:
        lines.append('only checked tracks are eligible')
    lines.append('live updating' if parsed['live'] else 'not live-updating')
    if not parsed['understood']:
        lines.append('NOT UNDERSTOOD:')
        for reason in parsed['reasons']:
            lines.append('  - ' + reason)
    return '\n'.join(lines)


# ===================================================================== selftest

def _find_playlist(root, typ, predicate):
    sect = W.section(root, typ)
    if sect is None:
        return None
    for p in E.playlists(root, sect):
        if E.is_smart(p) and predicate(E.pl_name(p)):
            return p
    return None


def _diff(expected_ids, got_tracks, label, check_order=True):
    """Print and return ok for one playlist's evaluate() result against what
    iTunes actually materialised.

    "ok" means every expected id is present (and, when `check_order` is
    True, in the same relative order) -- misses or reordering are an
    evaluator bug. EXTRA ids (things evaluate() finds that the device's
    stale list does not have) are reported but do NOT fail the check: the
    device is known-stale (research/SMART-PLAYLISTS.md), and finding more
    than iTunes last wrote is the whole reason this module exists. Per the
    task's own rule: if the required members are missing (or, when order is
    meaningful, out of order), that is this evaluator's bug, not the
    device's, and is reported as a failure rather than explained away.

    `check_order` is False for an unlimited playlist (checklimits=0): the
    wire format's only sort field (limitsort) is documented as applying
    while "applying the limit" (1.7), and this device's own unlimited
    playlists have a limitsort value that plainly isn't being honoured for
    display order either (90's Music stores limitsort=2/"random" yet
    iTunes wrote a fixed, non-random order) -- so whatever order iTunes
    wrote for an unlimited list reflects UI state (which library column was
    sorted at save time) that is not recoverable from the rule chunk at
    all. Holding this evaluator to an order the format itself does not
    specify would be scoring it against a guess, not a measurement.
    """
    got_ids = [t['id'] for t in got_tracks]
    got_set = set(got_ids)
    misses = [i for i in expected_ids if i not in got_set]
    extras = [i for i in got_ids if i not in expected_ids]
    common_order = [i for i in got_ids if i in set(expected_ids)]
    order_ok = (not check_order) or common_order == list(expected_ids)
    ok = not misses and order_ok
    print('  %s: device has %d materialised, evaluator returned %d'
          % (label, len(expected_ids), len(got_ids)))
    print('    exact matches: %d/%d%s' % (len(expected_ids) - len(misses), len(expected_ids),
                                           ' (in order)' if check_order and order_ok and not misses else
                                           '' if check_order else ' (order not meaningful -- see below)'))
    if misses:
        print('    MISSES (device has these, evaluator does not): %r' % misses)
    if check_order and not order_ok and not misses:
        print('    ORDER MISMATCH: same ids, different order -- got %r expected %r'
              % (got_ids[:len(expected_ids)], list(expected_ids)))
    if not check_order:
        print('    (order not checked: this playlist has no limit, so the wire format has no'
              ' sort that applies -- see _diff\'s docstring)')
    if extras:
        print('    extras (evaluator finds these, device does not -- expected if the device'
              ' is stale, see research/SMART-PLAYLISTS.md): %r' % extras)
    print('    %s' % ('PASS' if ok else 'FAIL -- the evaluator disagrees with iTunes, not the device'))
    return ok


def selftest(mount_or_path='/Volumes/IPOD'):
    """Parse every smart playlist on the real device (read-only), print each
    one decoded into plain English, then check the two playlists this
    device's own written-by-iTunes membership can verify against: "Top 25
    Most Played" (24 materialised members, strictly descending by play
    count) and "90's Music" (3 materialised members, a year range). Prints
    which playlists came back not-understood and why. Returns True only if
    nothing crashed and both verified playlists match iTunes exactly
    (extras from staleness aside -- see _diff).
    """
    path = mount_or_path if os.path.isfile(mount_or_path) else \
        os.path.join(mount_or_path, 'iPod_Control', 'iTunes', 'iTunesDB')
    try:
        data = open(path, 'rb').read()
    except OSError as e:
        print('cannot read %s: %s' % (path, e))
        print('selftest FAILED: device not available')
        return False

    root = W.parse(data)
    tracks = load_tracks(root)
    print('iTunesDB: %d tracks, read from %s' % (len(tracks), path))

    ok = True
    not_understood = []
    sect2 = W.section(root, 2)
    sect5 = W.section(root, 5)
    playlists = [('regular', p) for p in (E.playlists(root, sect2) if sect2 else []) if E.is_smart(p)]
    playlists += [('media-type', p) for p in (E.playlists(root, sect5) if sect5 else []) if E.is_smart(p)]
    print('\n%d smart playlists found (regular + media-type; type-3 duplicates of the '
          'regular set are skipped, per research/SMART-PLAYLISTS.md 2.0)\n' % len(playlists))

    for kind, p in playlists:
        name = E.pl_name(p) or '?'
        print('=== %s (%s) ===' % (name, kind))
        try:
            parsed = parse_rules(p)
        except ValueError as e:
            print('  FAILED TO PARSE: %s' % e)
            ok = False
            continue
        for line in describe(parsed).splitlines():
            print('  ' + line)
        if not parsed['understood']:
            not_understood.append(name)
        print()

    print('not understood: %s' % (', '.join(not_understood) if not_understood else '(none)'))
    # "Favourite Songs" using field 0x9a is the one case research/SMART-
    # PLAYLISTS.md confirmed by hand; if it stops showing up here, either
    # the device changed or this module's field table drifted from it.
    if not any('Favourite Songs' in n for n in not_understood):
        print('  WARNING: expected "Favourite Songs" (field 0x9a) in that list and did not find it')
        ok = False

    top25 = _find_playlist(root, 2, lambda n: n == 'Top 25 Most Played')
    nineties = _find_playlist(root, 2, lambda n: n and n.startswith('90') and 'Music' in n)

    print()
    if top25 is None:
        print('Top 25 Most Played: NOT FOUND')
        ok = False
    else:
        parsed = parse_rules(top25)
        if not parsed['understood']:
            print('Top 25 Most Played: NOT UNDERSTOOD (%s) -- cannot verify' % '; '.join(parsed['reasons']))
            ok = False
        else:
            got = evaluate(parsed, tracks)
            ok = _diff(materialized_ids(top25), got, 'Top 25 Most Played') and ok

    if nineties is None:
        print("90's Music: NOT FOUND")
        ok = False
    else:
        parsed = parse_rules(nineties)
        if not parsed['understood']:
            print("90's Music: NOT UNDERSTOOD (%s) -- cannot verify" % '; '.join(parsed['reasons']))
            ok = False
        else:
            got = evaluate(parsed, tracks)
            ok = _diff(materialized_ids(nineties), got, "90's Music", check_order=False) and ok

    recent = _find_playlist(root, 2, lambda n: n == 'Recently Added')
    if recent is not None:
        parsed = parse_rules(recent)
        if parsed['understood']:
            got = evaluate(parsed, tracks)
            print("\nRecently Added evaluates to %d tracks right now (device shows %d materialised)"
                  % (len(got), len(materialized_ids(recent))))
        else:
            print('\nRecently Added: NOT UNDERSTOOD (%s)' % '; '.join(parsed['reasons']))

    print()
    print('selftest %s' % ('PASSED' if ok else 'FAILED'))
    return ok


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] != 'selftest':
        print('usage: python3 -m saltpod.smartlists selftest [iTunesDB path or mount]')
        return 2
    path = argv[1] if len(argv) > 1 else '/Volumes/IPOD'
    return 0 if selftest(path) else 1


if __name__ == '__main__':
    sys.exit(main())
