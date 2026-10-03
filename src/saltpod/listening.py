"""How much the owner has listened to each track, across every source.

The owner, 3 October: Apple Music play counts should count, "as its played
by me overall". The trap is overlap, and it is not hypothetical: the same
morning a merge counted nine iPod plays twice.

EACH SOURCE IS KEPT SEPARATELY, WITH ITS NAME, and `overall()` is the one
place they are combined. Measured before writing a line of this, on the 70
tracks iTunes left a play count on in the pristine iPod database:

    Apple Music equals the iPod count     49
    Apple Music higher (played on the Mac since)  2
    Apple Music lower                      0
    not in Apple Music                    19

Never lower, mostly identical: iTunes merged the iPod's plays into the
library and wrote the library's total back onto the iPod. So the counts
saltpod ADOPTED from the iPod database are Apple Music's counts, and adding
the two would count every iTunes-era iPod play twice. What Apple Music has
never seen are the plays saltpod collected from the iPod's Play Counts file
since it took over.

    overall = apple music count            (if Apple Music has the track)
              or the adopted iPod count    (if it does not)
            + plays collected from the iPod since saltpod took over

Record fields, all per track in state:
    am_plays, am_last_played, am_skips   Apple Music, as last read
    plays_adopted                        what iTunes had written on the iPod
    plays                                saltpod's iPod-side total (adopted
                                         floor plus Play Counts merges) --
                                         unchanged, so nothing that reads it
                                         moves
"""
import datetime
import json

from . import itunesdb as I
from . import state as S


def _epoch(v):
    if not v:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(datetime.datetime.fromisoformat(str(v).replace('Z', '+00:00')).timestamp())
    except ValueError:
        return 0


def import_apple_music(st, am_path):
    """Put Apple Music's play counts on the tracks state knows about.

    Matched by artist + title. Where Apple Music holds the same track more
    than once (a re-download, a second copy) the largest count is taken,
    because they are the same recording and the largest is the one that
    was played. Returns {'matched', 'unmatched_in_state', 'library'}.
    """
    am = json.load(open(am_path))
    best = {}
    for i in range(len(am['name'] or [])):
        k = S.key_for(am['artist'][i], am['name'][i])
        cur = best.get(k)
        plays = am['played'][i] or 0
        if cur is None or plays > cur['plays']:
            best[k] = {'plays': plays, 'last': _epoch(am['last'][i]),
                       'skips': am['skipped'][i] or 0}
    matched = 0
    for k, rec in st['tracks'].items():
        hit = best.get(k)
        if hit is None:
            rec.pop('am_plays', None)
            continue
        rec['am_plays'] = hit['plays']
        rec['am_last_played'] = hit['last']
        rec['am_skips'] = hit['skips']
        matched += 1
    st['apple_music_read_at'] = am.get('read_at')
    return {'matched': matched, 'unmatched_in_state': len(st['tracks']) - matched,
            'library': len(am['name'] or [])}


def record_adopted(st, db_path):
    """Remember, per track, the count iTunes had written on the iPod -- the
    floor `adopt_db_counts` took -- so the plays saltpod added on top can be
    told apart from it. Never lowers an existing record."""
    n = 0
    for t in I.read(db_path)['tracks']:
        if not t.get('play_count'):
            continue
        rec = st['tracks'].get(S.key_for(t.get('artist'), t.get('title')))
        if rec is None:
            continue
        if t['play_count'] > (rec.get('plays_adopted') or 0):
            rec['plays_adopted'] = t['play_count']
            n += 1
    return n


def collected(rec):
    """Plays saltpod gathered from the iPod's Play Counts file -- the ones no
    other source has seen."""
    return max(0, (rec.get('plays') or 0) - (rec.get('plays_adopted') or 0))


def overall(rec):
    """The owner's total plays of this track, every source, nothing twice."""
    base = rec['am_plays'] if rec.get('am_plays') is not None else (rec.get('plays_adopted') or 0)
    return base + collected(rec)


def breakdown(rec):
    return {'overall': overall(rec), 'apple_music': rec.get('am_plays'),
            'adopted_from_ipod': rec.get('plays_adopted') or 0,
            'collected_from_ipod': collected(rec)}
