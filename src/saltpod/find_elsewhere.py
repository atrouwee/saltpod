#!/usr/bin/env python3
"""Resolve tracks the iTunes Store does not carry.

Runs after itunes_match.py. For every track it could not find, this asks two
keyless catalogues what the recording actually is, then builds targeted links
to the stores that sell files outright.

    python3 src/find_elsewhere.py set-2025-dani [vinyl ...]

Why these two:

  MusicBrainz  identifies the recording and -- the useful part -- names the
               label. Electronic singles are findable on Bandcamp through the
               label's page far more reliably than through the artist's, and
               a label name turns a hopeless search into a two-click one.
  Deezer       says whether the track exists digitally anywhere. A Deezer hit
               on something iTunes lacks means it is licensed and sold
               somewhere; no hit anywhere points at vinyl-only or bandcamp-
               only, which changes where you look.

Neither needs an API key. MusicBrainz requires a real User-Agent and one
request per second, and enforces both.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

from itunes_match import (ROOT, EXPORTS, REPORTS, full_title, norm_artist,  # noqa: E402
                          ratio, split_title, best_match, load_local_index,
                          match_local, DURATION_TOLERANCE_SEC)

MB_UA = "ipod-playlists/0.1 (https://github.com/; personal playlist matcher)"
MB_DELAY = 1.1   # MusicBrainz enforces 1 req/sec and will 503 otherwise.
DZ_DELAY = 0.4


def get(url, headers=None, timeout=30, attempts=4):
    """GET with backoff.

    MusicBrainz answers 503 when it decides you are going too fast, and a 503
    swallowed silently turns into a confident "not found" -- a network failure
    dressed up as a finding. Retry, and let a real failure surface as an error
    the caller has to handle.
    """
    req = urllib.request.Request(url, headers=headers or {"User-Agent": MB_UA})
    last = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (503, 429):
                raise
            time.sleep(MB_DELAY * (2 ** i))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(MB_DELAY * (2 ** i))
    raise last


_LABEL_CACHE = {}


def release_labels(mbid):
    """Label names for a release, via the one endpoint that carries them."""
    if not mbid:
        return []
    if mbid in _LABEL_CACHE:
        return _LABEL_CACHE[mbid]
    url = "https://musicbrainz.org/ws/2/release/%s?inc=labels&fmt=json" % mbid
    try:
        d = get(url)
        time.sleep(MB_DELAY)
    except Exception:  # noqa: BLE001
        _LABEL_CACHE[mbid] = []
        return []
    names = []
    for li in d.get("label-info", []) or []:
        nm = (li.get("label") or {}).get("name")
        if nm and nm not in names:
            names.append(nm)
    _LABEL_CACHE[mbid] = names
    return names


def musicbrainz(artist, title):
    q = 'recording:"%s" AND artist:"%s"' % (title.replace('"', ""), artist.replace('"', ""))
    url = "https://musicbrainz.org/ws/2/recording?" + urllib.parse.urlencode(
        {"query": q, "fmt": "json", "limit": 5})
    try:
        d = get(url)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    time.sleep(MB_DELAY)
    out = []
    for rec in d.get("recordings", [])[:5]:
        deep = len(out) < 2  # label lookups only for the top candidates
        labels, year, rel_title = [], None, None
        for rel in (rec.get("releases", [])[:2] if deep else rec.get("releases", [])[:1]):
            rel_title = rel_title or rel.get("title")
            year = year or (rel.get("date") or "")[:4] or None
            # The recording search omits label-info; only a release lookup with
            # inc=labels carries it, and the label is the whole point -- it is
            # what makes a track findable on Bandcamp.
            for nm in (release_labels(rel.get("id")) if deep else []):
                if nm not in labels:
                    labels.append(nm)
        out.append({
            "title": rec.get("title"),
            "artist": " ".join(c.get("name", "") for c in rec.get("artist-credit", [])
                               if isinstance(c, dict)).strip(),
            "length_sec": round((rec.get("length") or 0) / 1000.0, 1) or None,
            "release": rel_title, "year": year, "labels": labels,
            "isrcs": rec.get("isrcs") or [],
            "score": rec.get("score"),
        })
    return {"results": out}


def deezer(artist, title):
    url = "https://api.deezer.com/search?" + urllib.parse.urlencode(
        {"q": 'artist:"%s" track:"%s"' % (artist, title), "limit": 5})
    try:
        d = get(url, headers={"User-Agent": MB_UA})
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    time.sleep(DZ_DELAY)
    return {"results": [{
        "title": r.get("title"), "artist": (r.get("artist") or {}).get("name"),
        "album": (r.get("album") or {}).get("title"),
        "duration_sec": r.get("duration"), "link": r.get("link"),
    } for r in d.get("data", [])[:5]]}


def links(artist, title, labels):
    q = urllib.parse.quote_plus("%s %s" % (artist, title))
    out = [
        ("Beatport", "https://www.beatport.com/search?q=" + q),
        ("Bandcamp", "https://bandcamp.com/search?q=" + q),
        ("Discogs", "https://www.discogs.com/search/?type=release&q=" + q),
        ("Qobuz", "https://www.qobuz.com/nl-nl/search?q=" + q),
        ("Juno", "https://www.junodownload.com/search/?q%5Ball%5D%5B%5D=" + q),
    ]
    for lb in labels[:2]:
        out.append(("Bandcamp - %s" % lb,
                    "https://bandcamp.com/search?q=" + urllib.parse.quote_plus(lb)))
    return out


def verdict(track, mb, dz):
    """What the two catalogues jointly imply about where to look."""
    want = full_title(track["title"])
    wa = norm_artist(track.get("artist"))
    dur = track.get("duration_sec") or 0

    def close(cand_title, cand_artist, cand_dur):
        if ratio(want, full_title(cand_title or "")) < 0.85:
            return False
        if ratio(wa, norm_artist(cand_artist or "")) < 0.80:
            return False
        return not (dur and cand_dur and abs(cand_dur - dur) > DURATION_TOLERANCE_SEC)

    dz_hit = any(close(r["title"], r["artist"], r.get("duration_sec"))
                 for r in dz.get("results", []))
    mb_hit = any(close(r["title"], r["artist"], r.get("length_sec"))
                 for r in mb.get("results", []))
    if dz_hit:
        return ("sold digitally", "On Deezer at this length, so it is licensed "
                "and distributed. Beatport or Juno will almost certainly have it.")
    if mb_hit:
        return ("released, not streaming", "MusicBrainz knows the release but "
                "Deezer does not carry it. Bandcamp or the label direct; "
                "possibly vinyl-only with a download code.")
    if mb.get("error") or dz.get("error"):
        # Say so rather than reporting a lookup failure as an absence.
        which = ", ".join(n for n, r in (("MusicBrainz", mb), ("Deezer", dz))
                          if r.get("error"))
        return ("lookup failed", "%s did not answer, so this is unresolved "
                "rather than missing. Re-run to retry." % which)
    if mb.get("results"):
        return ("released, different length", "The release exists but no "
                "version matches your length, so yours is an edit. The search "
                "links below are still good; check the running time before buying.")
    return ("unidentified", "Neither catalogue matches at this length. Check "
            "the exact mix name in Apple Music -- it may be an edit that only "
            "exists on the original release.")


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    local = load_local_index()
    sections = []
    for slug in argv:
        with open(os.path.join(EXPORTS, slug + ".json")) as f:
            data = json.load(f)
        raw_dir = os.path.join(ROOT, "data", "itunes", slug)
        misses = []
        for t in data["tracks"]:
            if t.get("owned") or match_local(t, local):
                continue
            cache = os.path.join(raw_dir, "%03d.json" % t["index"])
            if not os.path.exists(cache):
                continue
            with open(cache) as f:
                payload = json.load(f)
            m, _c = best_match(t, payload.get("results", []))
            if m is None:
                misses.append(t)

        print("%s: %d not on iTunes" % (slug, len(misses)))
        rows = []
        for t in misses:
            core, _ = split_title(t["title"])
            print("  looking up %s - %s ..." % (t["artist"], t["title"]))
            mb = musicbrainz(t["artist"] or "", core)
            dz = deezer(t["artist"] or "", core)
            v, why = verdict(t, mb, dz)
            labels = []
            for r in mb.get("results", []):
                for lb in r["labels"]:
                    if lb not in labels:
                        labels.append(lb)
            rows.append({"track": t, "mb": mb, "dz": dz, "verdict": v,
                         "why": why, "labels": labels})
            print("     -> %s%s" % (v, ("  [%s]" % ", ".join(labels[:2])) if labels else ""))
        sections.append((data["playlist"], slug, rows))

        out = os.path.join(ROOT, "data", "itunes", slug, "_elsewhere.json")
        with open(out, "w") as f:
            json.dump([{k: r[k] for k in ("verdict", "why", "labels", "mb", "dz")}
                       | {"track": r["track"]} for r in rows], f, indent=1)

    L = ["# Not on iTunes - where to buy instead", "",
         "Generated %s. Verdicts come from MusicBrainz (identity, label) and "
         "Deezer (does it exist digitally)." % time.strftime("%Y-%m-%d %H:%M"), ""]
    for playlist, slug, rows in sections:
        L.append("## %s" % playlist)
        L.append("")
        if not rows:
            L.append("Everything matched on iTunes.")
            L.append("")
            continue
        for r in rows:
            t = r["track"]
            L.append("### %s - %s" % (t["artist"], t["title"]))
            L.append("")
            L.append("*%s.* %s" % (r["verdict"], r["why"]))
            L.append("")
            L.append("- wanted length: %d:%02d" % divmod(int(t["duration_sec"] or 0), 60))
            if t.get("album"):
                L.append("- album in your playlist: %s" % t["album"])
            if r["labels"]:
                L.append("- label(s): **%s**" % ", ".join(r["labels"][:4]))
            best_mb = (r["mb"].get("results") or [None])[0]
            if best_mb:
                L.append("- MusicBrainz: %s - %s%s%s" % (
                    best_mb["artist"], best_mb["title"],
                    " (%s)" % best_mb["release"] if best_mb["release"] else "",
                    " %s" % best_mb["year"] if best_mb["year"] else ""))
                if best_mb["isrcs"]:
                    L.append("- ISRC: `%s`" % best_mb["isrcs"][0])
            for r2 in (r["dz"].get("results") or [])[:1]:
                L.append("- Deezer has: %s - %s (%s) %s" % (
                    r2["artist"], r2["title"], r2["album"], r2["link"]))
            L.append("")
            L.append("  " + " - ".join("[%s](%s)" % (n, u)
                                       for n, u in links(t["artist"], t["title"], r["labels"])))
            L.append("")
    path = os.path.join(REPORTS, "elsewhere.md")
    with open(path, "w") as f:
        f.write("\n".join(L))
    print("")
    print("report: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
