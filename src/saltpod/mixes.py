"""Genius-style mixes, computed here instead of on Apple's servers.

WHAT GENIUS WAS. Apple uploaded a library fingerprint and sent back a
similarity graph; iTunes baked up to twelve "Genius Mixes" from it at sync
time and pushed them to the device as finished lists. The server is gone,
so the feature is dead everywhere -- and research/DEVICE-CENSUS.md found the
graph was catalogue-wide (937 ids referenced from a 481-track library) and
only ever matched 13% of this library anyway. It cannot be recomputed.

WHAT THIS DOES INSTEAD. Builds mixes from what this library actually knows
about itself, measured on the device's 643 music tracks:

    genre    631    year     642    loudness 642    plays 69
    BPM        0  -- the files carry it on ~1,000 tracks, but the device
                     was never given it; it arrives with the next index

so v1 groups by STYLE FAMILY, splits a large family by ERA, and sequences
each mix by loudness so the level does not lurch from track to track. Key
and tempo -- the signals that would make this better than Apple's, for a
library this electronic -- slot in once the index carries them.

A PROPOSAL, NOT A DECISION. The family table below is a judgement about
genre names, written out so it can be read and changed, and `build()`
reports every raw genre with where it went -- including the ones that went
nowhere. Nothing here writes to the device.
"""
import collections

# Raw genre -> family, by the words in it. Longest match wins, so
# "Deep House" is House and "Electronica / Downtempo" is Electronic.
FAMILIES = {
    'Hip-Hop': ('hip-hop', 'hip hop', 'rap', 'trap', 'grime'),
    'House & Dance': ('house', 'deep house', 'tech house', 'dance', 'garage', 'disco house', 'nu disco'),
    'Electronic': ('electronic', 'electronica', 'electro', 'downtempo', 'techno', 'ambient',
                   'idm', 'breakbeat', 'drum & bass', 'dubstep', 'trip-hop', 'trip hop',
                   'minimal', 'deep tech'),
    'Soul & Funk': ('soul', 'funk', 'r&b', 'rnb', 'rhythmic soul', 'disco', 'motown', 'gospel'),
    'Rock': ('rock', 'rock & roll', 'classic rock', 'alternative', 'indie', 'punk',
             'grunge', 'metal', 'new wave'),
    'Reggae': ('reggae', 'dub', 'ska', 'dancehall', 'rocksteady'),
    'Country & Folk': ('country', 'folk', 'americana', 'bluegrass', 'singer/songwriter'),
    'Pop': ('pop', 'synthpop', 'synth-pop'),
    'Jazz & Blues': ('jazz', 'blues', 'swing', 'bossa nova'),
    'Latin': ('latin', 'salsa', 'reggaeton', 'cumbia'),
}
# Shorter than this is a jingle, a skit or an interlude, not a song for a
# mix. The first preview opened half its mixes with radio-station idents --
# they are quiet, so a loudness walk put them first. Duration is the honest
# test; guessing from titles is not.
MIN_SECONDS = 90

ERAS = ((0, 1979, 'before 1980'), (1980, 1999, '80s & 90s'),
        (2000, 2009, '2000s'), (2010, 9999, '2010s on'))


def family_of(genre):
    """The family a raw genre string belongs to, or None."""
    g = (genre or '').casefold()
    best, blen = None, 0
    for fam, words in FAMILIES.items():
        for w in words:
            if w in g and len(w) > blen:
                best, blen = fam, len(w)
    return best


def era_of(year):
    for lo, hi, name in ERAS:
        if lo <= (year or 0) <= hi:
            return name
    return None


def build(tracks, loudness=None, min_size=15, max_mixes=12):
    """Mixes from `tracks` (dicts with id, artist, title, genre, year,
    play_count -- smartlists.load_tracks' shape). `loudness` maps track id
    to integrated LUFS where known.

    Returns {'mixes': [{name, family, era, ids, size, plays}],
             'placement': {raw genre: family or None},
             'unplaced': n}.
    """
    loudness = loudness or {}
    placement, by_family = {}, collections.defaultdict(list)
    short = [t for t in tracks if (t.get('ms') or 0) < MIN_SECONDS * 1000]
    tracks = [t for t in tracks if (t.get('ms') or 0) >= MIN_SECONDS * 1000]
    for t in tracks:
        g = t.get('genre') or ''
        fam = family_of(g)
        placement[g] = fam
        if fam:
            by_family[fam].append(t)

    groups = []
    for fam, ts in by_family.items():
        eras = collections.Counter(era_of(t.get('year')) for t in ts)
        big = len(ts) >= 2 * min_size and len([e for e, n in eras.items() if n >= min_size]) >= 2
        if big:
            for era, n in eras.items():
                part = [t for t in ts if era_of(t.get('year')) == era]
                if len(part) >= min_size:
                    groups.append((fam, era, part))
                else:
                    # too few to stand alone: fold back into the family's
                    # largest era rather than drop them
                    pass
            placed = {id(t) for _f, _e, p in groups if _f == fam for t in p}
            rest = [t for t in ts if id(t) not in placed]
            if rest:
                largest = max((g for g in groups if g[0] == fam), key=lambda g: len(g[2]))
                largest[2].extend(rest)
        elif len(ts) >= min_size:
            groups.append((fam, None, ts))

    def sequence(ts):
        # A slow walk up the loudness scale, so the level never lurches;
        # tracks with no measurement keep their place at the quiet end.
        return sorted(ts, key=lambda t: (loudness.get(t['id'], -99.0), t.get('year') or 0))

    mixes = []
    for fam, era, ts in groups:
        ordered = sequence(ts)
        mixes.append({'name': '%s Mix%s' % (fam, (' · ' + era) if era else ''),
                      'family': fam, 'era': era,
                      'ids': [t['id'] for t in ordered], 'size': len(ordered),
                      'plays': sum(t.get('play_count') or 0 for t in ordered)})
    mixes.sort(key=lambda m: (-m['size'], -m['plays']))
    unplaced = sum(1 for t in tracks if not family_of(t.get('genre')))
    return {'mixes': mixes[:max_mixes], 'placement': placement,
            'unplaced': unplaced, 'short': len(short),
            'dropped': max(0, len(mixes) - max_mixes)}
