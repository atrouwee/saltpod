#!/usr/bin/env python3
"""Lossless-first buy guide for a matched playlist.

The iTunes Store sells AAC 256 and has no lossless tier, so if the goal is
FLAC or ALAC then iTunes is the wrong shop -- but it is still the best
*identifier*. Its Search API is free, keyless, cacheable and precise about
which recording you mean, down to the exact running time. So this uses the
already-cached iTunes matches to pin down identity, then routes the actual
purchase to the stores that sell lossless.

Store order, best format first:

    Bandcamp   FLAC/ALAC/AIFF/WAV, artist and label direct
    Beatport   AIFF + FLAC lossless, strongest for club-oriented singles
    Qobuz      FLAC 16/24-bit
    Juno       WAV/FLAC on most releases
    iTunes     AAC 256 -- the fallback when nothing above carries it

    python3 src/buy_lossless.py 2026-august [--labels]

--labels asks MusicBrainz for each release's label, which is the field that
makes a track findable on Bandcamp (labels host their artists far more
reliably than artists host themselves). It costs one request per second and
is cached to disk, so it is slow once and free afterwards.
"""
import json
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from itunes_match import (ROOT, EXPORTS, REPORTS, best_match, load_local_index,  # noqa: E402
                          match_local, split_title)

# What a lossless copy typically costs per track, for sizing the decision.
LOSSLESS_LOW, LOSSLESS_HIGH = 1.50, 3.00


def label_cache_path(slug):
    return os.path.join(ROOT, "data", "itunes", slug, "_labels.json")


def lookup_labels(slug, rows):
    """Resolve labels via MusicBrainz, caching to disk so re-runs are free."""
    from find_elsewhere import musicbrainz

    path = label_cache_path(slug)
    cache = {}
    if os.path.exists(path):
        with open(path) as f:
            cache = json.load(f)

    fresh = 0
    for r in rows:
        t = r["track"]
        key = "%s|%s" % (t.get("artist"), t.get("title"))
        if key in cache:
            r["labels"] = cache[key]
            continue
        core, _ = split_title(t["title"])
        mb = musicbrainz(t.get("artist") or "", core)
        labels = []
        for rec in mb.get("results", []):
            for lb in rec.get("labels", []):
                # MusicBrainz uses a literal "[no label]" placeholder for
                # self-released material; it is not a label name.
                if lb and lb.strip("[]").lower() != "no label" and lb not in labels:
                    labels.append(lb)
        # Do not cache a failed lookup as an empty answer.
        if not mb.get("error"):
            cache[key] = labels
            fresh += 1
        r["labels"] = labels
        print("    %-45s %s" % (
            ("%s - %s" % (t["artist"], t["title"]))[:45],
            ", ".join(labels[:2]) or "(no label found)"))

    if fresh:
        with open(path, "w") as f:
            json.dump(cache, f, indent=1)
    return rows


# Typographic characters that survive into metadata and break a search URL.
# "Razor\u2010N\u2010Tape" encodes its hyphens as %E2%80%90 and finds nothing.
_URL_PUNCT = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
    "\u2015": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2026": " ", "\u00a0": " ", "\u200b": "",
}


def searchable(s):
    for a, b in _URL_PUNCT.items():
        s = (s or "").replace(a, b)
    return s


def store_links(artist, title, labels):
    q = urllib.parse.quote_plus(searchable("%s %s" % (artist or "", title or "")))
    out = [
        ("Bandcamp", "https://bandcamp.com/search?q=" + q),
        ("Beatport", "https://www.beatport.com/search?q=" + q),
        ("Qobuz", "https://www.qobuz.com/nl-nl/search?q=" + q),
        ("Juno", "https://www.junodownload.com/search/?q%5Ball%5D%5B%5D=" + q),
    ]
    for lb in (labels or [])[:1]:
        out.insert(1, ("Bandcamp: %s" % lb,
                       "https://bandcamp.com/search?q="
                       + urllib.parse.quote_plus(searchable(lb))))
    return out


def build(slug, with_labels=False):
    with open(os.path.join(EXPORTS, slug + ".json")) as f:
        data = json.load(f)
    raw_dir = os.path.join(ROOT, "data", "itunes", slug)
    local = load_local_index()

    rows = []
    for t in data["tracks"]:
        if t.get("owned"):
            rows.append({"track": t, "status": "owned", "cand": None})
            continue
        on_disk = match_local(t, local)
        if on_disk:
            rows.append({"track": t, "status": "on_disk", "cand": None,
                         "local": on_disk})
            continue
        cache = os.path.join(raw_dir, "%03d.json" % t["index"])
        payload = {}
        if os.path.exists(cache):
            with open(cache) as f:
                payload = json.load(f)
        m, c = best_match(t, payload.get("results", []))
        rows.append({"track": t, "status": m["verdict"] if m else "unidentified",
                     "cand": c, "match": m})

    if with_labels:
        print("  resolving labels via MusicBrainz (1 req/sec, cached)...")
        lookup_labels(slug, rows)
    return data, rows


def fmt_dur(sec):
    return "%d:%02d" % divmod(int(sec or 0), 60)


def write(slug, data, rows, with_labels):
    buy = [r for r in rows if r["status"] not in ("owned", "on_disk")]
    itunes_total = sum((r["cand"].get("trackPrice") or 0)
                       for r in buy if r["cand"])
    n = len(buy)

    L = ["# %s - lossless buy guide" % data["playlist"], "",
         "%d tracks, %d to buy. Identity confirmed against the iTunes catalogue; "
         "purchase routed to stores that sell lossless." % (len(rows), n), "",
         "| | |", "|---|---|",
         "| iTunes (AAC 256, lossy) | **EUR %.2f** |" % itunes_total,
         "| Lossless, estimated | **EUR %.2f - %.2f** |" % (
             n * LOSSLESS_LOW, n * LOSSLESS_HIGH),
         "",
         "Buy FLAC and convert to ALAC for the iPod -- the Classic plays ALAC "
         "natively but not FLAC without Rockbox, and AIFF tags poorly. Keep the "
         "FLAC as the archive master.", "",
         "## Buy these", "",
         "Check the running time before paying: a matching title at a different "
         "length is a different cut.", ""]

    for r in buy:
        t, c = r["track"], r["cand"]
        title = c.get("trackName") if c else t["title"]
        artist = c.get("artistName") if c else t["artist"]
        album = c.get("collectionName") if c else t.get("album")
        L.append("### %s - %s" % (artist, title))
        L.append("")
        L.append("- **%s**%s" % (fmt_dur(t["duration_sec"]),
                                 "  ·  %s" % album if album else ""))
        if r.get("labels"):
            L.append("- label: **%s**" % ", ".join(r["labels"][:3]))
        if r["status"] == "variant":
            m = r["match"]
            L.append("- ⚠ iTunes carries a %+.0fs version (`%s` vs `%s`) - "
                     "your length is the one to look for"
                     % (m["duration_delta_sec"], m["candidate_variant"] or "-",
                        m["wanted_variant"] or "-"))
        if r["status"] == "unidentified":
            L.append("- not found on iTunes, so no confirmed identity - "
                     "check the mix name yourself")
        L.append("")
        links = store_links(t["artist"], t["title"], r.get("labels"))
        L.append("  " + "  ·  ".join("[%s](%s)" % (nm, u) for nm, u in links))
        if c:
            L.append("")
            L.append("  *fallback:* [iTunes AAC 256 - EUR %.2f](%s)"
                     % (c.get("trackPrice") or 0, c.get("trackViewUrl")))
        L.append("")

    skipped = [r for r in rows if r["status"] in ("owned", "on_disk")]
    if skipped:
        L += ["## Already yours", ""]
        for r in skipped:
            t = r["track"]
            where = ("in the library" if r["status"] == "owned"
                     else "`%s`" % os.path.basename(r["local"]["path"]))
            L.append("- %s - %s - %s" % (t["artist"], t["title"], where))
        L.append("")

    if not with_labels:
        L += ["", "*Run with `--labels` to resolve each release's label - it is "
              "the fastest way into the right Bandcamp page.*", ""]

    path = os.path.join(REPORTS, slug + "-lossless.md")
    with open(path, "w") as f:
        f.write("\n".join(L))
    return path, itunes_total, n


def main(argv):
    slugs = [a for a in argv if not a.startswith("--")]
    if not slugs:
        print(__doc__)
        return 2
    with_labels = "--labels" in argv
    for slug in slugs:
        print("building lossless guide for %s" % slug)
        data, rows = build(slug, with_labels)
        path, total, n = write(slug, data, rows, with_labels)
        print("  %d to buy  |  iTunes EUR %.2f  |  lossless ~EUR %.0f-%.0f"
              % (n, total, n * LOSSLESS_LOW, n * LOSSLESS_HIGH))
        print("  report: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
