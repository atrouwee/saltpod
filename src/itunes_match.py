#!/usr/bin/env python3
"""Match an exported Apple Music playlist against the iTunes Store.

Reads data/exports/<slug>.json, queries the public iTunes Search API once per
track, caches every raw response under data/itunes/<slug>/, then scores the
candidates and writes a buy-list report.

Stdlib only, deliberately: this has to keep running on a stock macOS python.

    python3 src/itunes_match.py dayclub [--country NL] [--refresh]
"""
import json
import os
import unicodedata
import re
import sys
import time
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS = os.path.join(ROOT, "data", "exports")
RAW = os.path.join(ROOT, "data", "itunes")
REPORTS = os.path.join(ROOT, "reports")

# The Search API is documented as ~20 calls/minute before it starts returning
# 403s. 3.5s keeps us under that with room to spare; a 65-track playlist costs
# about four minutes, which is cheaper than getting rate-limited halfway.
THROTTLE_SEC = 3.5
USER_AGENT = "ipod-playlists/0.1 (personal playlist matcher)"

# Duration tolerance. Beyond this a match is a *different recording*, not a
# worse match -- the radio edit where the extended mix was wanted. This is the
# single check that stops the pipeline buying the wrong record.
DURATION_TOLERANCE_SEC = 5

MIX_WORDS = (
    "original mix", "extended mix", "extended", "radio edit", "radio mix",
    "club mix", "club edit", "dub mix", "dub", "instrumental", "remix",
    "rework", "edit", "version", "live", "acoustic", "remastered",
)
FEAT_RE = re.compile(r"\s*[\(\[]?\b(feat|ft|featuring|with)\b\.?\s[^\)\]]*[\)\]]?", re.I)
BRACKET_RE = re.compile(r"[\(\[]([^\)\]]*)[\)\]]")
PUNCT_RE = re.compile(r"[^a-z0-9]+")


def fold(s):
    """Strip diacritics without destroying the letter underneath.

    'Deso' and 'Ceşme' must not become 'd so' and 'e me'. Punctuation
    stripping has to happen *after* this, or accented letters get eaten as
    punctuation -- which quietly broke every Turkish and French title in the
    library.
    """
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    # A few letters carry no combining form and survive NFKD intact.
    for a, b in (("\u00f8", "o"), ("\u0142", "l"), ("\u00e6", "ae"),
                 ("\u0153", "oe"), ("\u00df", "ss"), ("\u0131", "i"),
                 ("\u00d0", "d"), ("\u00fe", "th")):
        s = s.replace(a, b).replace(a.upper(), b.upper())
    return s


def norm(s):
    """Fold accents, lowercase, drop punctuation, collapse whitespace."""
    return PUNCT_RE.sub(" ", fold(s).lower()).strip()


def split_title(title):
    """Return (core, variant) -- the song name and its mix descriptor.

    'Long Way (Original Mix)' -> ('long way', 'original mix')
    Bracketed text that is not a known mix word (a featured artist, say) is
    dropped from the core rather than treated as a variant.
    """
    t = title or ""
    variants = []
    for inner in BRACKET_RE.findall(t):
        low = inner.lower()
        if any(w in low for w in MIX_WORDS):
            variants.append(norm(inner))
    core = BRACKET_RE.sub(" ", t)
    core = FEAT_RE.sub(" ", core)
    core = re.sub(r"\s*-\s*(single|ep)\s*$", "", core, flags=re.I)
    # A trailing ' - Something Mix' is a variant too (Beatport's house style).
    m = re.search(r"\s-\s([^-]*)$", core)
    if m and any(w in m.group(1).lower() for w in MIX_WORDS):
        variants.append(norm(m.group(1)))
        core = core[: m.start()]
    core = norm(core)
    if not core:
        # Titles that are entirely punctuation ("
        # Seb Wildblood - :~^") normalise to nothing and take their search
        # query with them. Fall back to the title as written.
        core = norm(FEAT_RE.sub(" ", t)) or (t or "").strip()
    return core, " ".join(variants).strip()


def full_title(title):
    """Title minus featured-artist noise, accents folded, brackets kept.

    'People (We Can Transform)' keeps its parenthetical here: it is part of
    the name, not a mix descriptor, and dropping it from the search term
    throws away the most distinctive words in the query.
    """
    t = FEAT_RE.sub(" ", title or "")
    t = re.sub(r"\s*-\s*(single|ep)\s*$", "", t, flags=re.I)
    return norm(t) or norm(title) or (title or "").strip()


def norm_artist(a):
    a = FEAT_RE.sub(" ", a or "")
    a = re.sub(r"\s*[&,]\s*|\s+and\s+", " ", a, flags=re.I)
    return norm(a)


def ratio(a, b):
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def search(term, country, limit=12):
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": term, "country": country, "media": "music",
         "entity": "song", "limit": limit}
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def score(track, cand):
    """Score one candidate against the wanted track.

    Returns a dict of the component signals plus a verdict. The components are
    kept in the output on purpose -- when a row looks wrong, the reason should
    be readable without re-running anything.
    """
    w_core, w_var = split_title(track["title"])
    c_core, c_var = split_title(cand.get("trackName", ""))
    title_sim = max(ratio(w_core, c_core),
                    ratio(full_title(track["title"]), full_title(cand.get("trackName", ""))))
    artist_sim = max(
        ratio(norm_artist(track.get("artist")), norm_artist(cand.get("artistName"))),
        ratio(norm_artist(track.get("album_artist")), norm_artist(cand.get("artistName"))),
    )
    want_dur = track.get("duration_sec") or 0
    cand_dur = (cand.get("trackTimeMillis") or 0) / 1000.0
    delta = round(cand_dur - want_dur, 1) if want_dur and cand_dur else None
    within = delta is not None and abs(delta) <= DURATION_TOLERANCE_SEC
    variant_match = (w_var == c_var) or (not w_var and not c_var)

    if title_sim >= 0.95 and artist_sim >= 0.90 and within and variant_match:
        verdict = "exact"
    elif title_sim >= 0.88 and artist_sim >= 0.85 and within:
        verdict = "strong"
    elif title_sim >= 0.88 and artist_sim >= 0.85:
        # Right song, wrong recording. This is the one that needs human eyes.
        verdict = "variant"
    elif title_sim >= 0.75 and artist_sim >= 0.70:
        verdict = "weak"
    else:
        verdict = "reject"

    rank = (title_sim * 0.45) + (artist_sim * 0.35) + (0.20 if within else 0.0)
    return {
        "verdict": verdict, "rank": round(rank, 4),
        "title_sim": round(title_sim, 3), "artist_sim": round(artist_sim, 3),
        "duration_delta_sec": delta, "within_tolerance": within,
        "wanted_variant": w_var or None, "candidate_variant": c_var or None,
        "variant_match": variant_match,
    }


def best_match(track, results):
    scored = []
    for c in results:
        s = score(track, c)
        if s["verdict"] == "reject":
            continue
        scored.append((s, c))
    if not scored:
        return None, None
    order = {"exact": 0, "strong": 1, "variant": 2, "weak": 3}
    scored.sort(key=lambda sc: (order[sc[0]["verdict"]], -sc[0]["rank"]))
    return scored[0][0], scored[0][1]


def load_local_index():
    """Load the on-disk index of owned files, if one has been built."""
    path = os.path.join(ROOT, "data", "local", "index.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f).get("tracks", [])


def match_local(track, local):
    """Find an owned file on disk for this track.

    Same thresholds as the store matcher, and the same duration rule: a file
    whose length is off by more than the tolerance is a different recording,
    not a cheaper copy of this one.
    """
    w_core, _ = split_title(track["title"])
    w_artist = norm_artist(track.get("artist"))
    want_dur = track.get("duration_sec") or 0
    best, best_rank = None, 0.0
    for e in local:
        t_sim = ratio(w_core, split_title(e.get("title") or "")[0])
        a_sim = ratio(w_artist, norm_artist(e.get("artist")))
        if t_sim < 0.88 or a_sim < 0.85:
            continue
        d = e.get("duration_sec") or 0
        delta = round(d - want_dur, 1) if want_dur and d else None
        within = delta is not None and abs(delta) <= DURATION_TOLERANCE_SEC
        rank = (t_sim * 0.45) + (a_sim * 0.35) + (0.20 if within else 0.0)
        if rank > best_rank:
            best_rank = rank
            best = {"path": e["path"], "title_sim": round(t_sim, 3),
                    "artist_sim": round(a_sim, 3), "duration_delta_sec": delta,
                    "within_tolerance": within, "needs_convert": e["needs_convert"],
                    "ipod_ready": e["ipod_ready"]}
    return best if (best and best["within_tolerance"]) else None


def match_playlist(slug, country="NL", refresh=False):
    with open(os.path.join(EXPORTS, slug + ".json")) as f:
        data = json.load(f)
    raw_dir = os.path.join(RAW, slug)
    os.makedirs(raw_dir, exist_ok=True)

    local = load_local_index()
    if local:
        print("  (checking %d owned files on disk first)" % len(local))

    rows = []
    for t in data["tracks"]:
        if t.get("owned"):
            rows.append({"track": t, "status": "already_owned",
                         "match": None, "candidate": None})
            print("  [own  ] %s - %s" % (t["artist"], t["title"]))
            continue

        # Match the disk before the store. Every hit here is a track that would
        # otherwise be bought a second time.
        on_disk = match_local(t, local)
        if on_disk:
            rows.append({"track": t, "status": "on_disk",
                         "match": None, "candidate": None, "local": on_disk})
            print("  [disk ] %s - %s  ->  %s" % (
                t["artist"], t["title"],
                on_disk["path"].replace(os.path.expanduser("~"), "~")))
            continue

        cache = os.path.join(raw_dir, "%03d.json" % t["index"])
        if os.path.exists(cache) and not refresh:
            with open(cache) as f:
                payload = json.load(f)
        else:
            term = "%s %s" % (t.get("artist") or "", full_title(t["title"]))
            try:
                payload = search(term.strip(), country)
            except Exception as e:  # noqa: BLE001 - network shape varies
                payload = {"resultCount": 0, "results": [], "_error": str(e)}
            payload["_query"] = term.strip()
            payload["_fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            with open(cache, "w") as f:
                json.dump(payload, f, indent=1)
            time.sleep(THROTTLE_SEC)

        m, cand = best_match(t, payload.get("results", []))
        rows.append({
            "track": t, "status": m["verdict"] if m else "not_found",
            "match": m, "candidate": cand,
        })
        tag = m["verdict"] if m else "none"
        print("  [%-5s] %s - %s%s" % (
            tag, t["artist"], t["title"],
            "" if not m or m["duration_delta_sec"] is None
            else "  (Δ%+.0fs)" % m["duration_delta_sec"]))
    return data, rows


def cluster_albums(rows, min_tracks=3):
    """Find albums worth buying whole.

    Apple has no cart and no bulk purchase, so the only real lever on a big
    playlist is buying the album when enough of its tracks appear.
    """
    by_album = {}
    for r in rows:
        c = r.get("candidate")
        if not c or r["status"] in ("not_found", "already_owned"):
            continue
        cid = c.get("collectionId")
        if not cid:
            continue
        by_album.setdefault(cid, {
            "collection_id": cid,
            "collection_name": c.get("collectionName"),
            "artist": c.get("collectionArtistName") or c.get("artistName"),
            "collection_price": c.get("collectionPrice"),
            "collection_url": c.get("collectionViewUrl"),
            "tracks": [],
        })["tracks"].append(r)

    clusters = []
    for cid, a in by_album.items():
        n = len(a["tracks"])
        track_sum = sum((r["candidate"].get("trackPrice") or 0) for r in a["tracks"])
        a["track_count"] = n
        a["track_price_sum"] = round(track_sum, 2)
        cp = a["collection_price"]
        # A negative collectionPrice means album-only/not sold separately.
        a["album_buy"] = bool(n >= min_tracks and cp and cp > 0 and cp < track_sum)
        a["saving"] = round(track_sum - cp, 2) if a["album_buy"] else 0.0
        clusters.append(a)
    clusters.sort(key=lambda a: -a["saving"])
    return clusters


def money(v, cur):
    return "-" if v in (None, "") or v < 0 else "%s%.2f" % (
        {"EUR": "€", "USD": "$", "GBP": "£"}.get(cur, cur + " "), v)


def write_report(slug, data, rows, clusters, country):
    cur = next((r["candidate"].get("currency") for r in rows
                if r.get("candidate") and r["candidate"].get("currency")), country)
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    buyable = [r for r in rows if r["status"] in ("exact", "strong", "variant", "weak")]
    per_track_total = sum((r["candidate"].get("trackPrice") or 0) for r in buyable)

    album_ids = {a["collection_id"] for a in clusters if a["album_buy"]}
    bundled, counted = 0.0, set()
    for a in clusters:
        if a["album_buy"]:
            bundled += a["collection_price"]
            counted.update(id(r) for r in a["tracks"])
    bundled += sum((r["candidate"].get("trackPrice") or 0)
                   for r in buyable if id(r) not in counted)

    L = []
    L.append("# %s - iTunes buy list" % data["playlist"])
    L.append("")
    L.append("Store `%s` - generated %s" % (country, time.strftime("%Y-%m-%d %H:%M")))
    L.append("")
    L.append("| Outcome | Tracks |")
    L.append("|---|---:|")
    for k in ("already_owned", "on_disk", "exact", "strong", "variant", "weak", "not_found"):
        if counts.get(k):
            L.append("| %s | %d |" % (k.replace("_", " "), counts[k]))
    L.append("| **total** | **%d** |" % len(rows))
    L.append("")
    L.append("Per-track total: **%s**" % money(per_track_total, cur))
    if album_ids:
        L.append("With album bundling: **%s**  (saves %s)"
                 % (money(bundled, cur), money(per_track_total - bundled, cur)))
    L.append("")
    L.append("## Tracks")
    L.append("")
    L.append("| # | Wanted | Match | Conf | dur | Price | Buy |")
    L.append("|---:|---|---|---|---:|---:|---|")
    for r in rows:
        t, m, c = r["track"], r["match"], r["candidate"]
        want = "%s - %s" % (t["artist"], t["title"])
        if r["status"] == "already_owned":
            L.append("| %d | %s | *owned in library* | - | - | - | - |" % (t["index"], want))
            continue
        if r["status"] == "on_disk":
            loc = r["local"]
            L.append("| %d | %s | *on disk* `%s` | - | %+.0fs | - | %s |" % (
                t["index"], want, os.path.basename(loc["path"]),
                loc["duration_delta_sec"] or 0,
                "convert first" if loc["needs_convert"] else "ready"))
            continue
        if not c:
            L.append("| %d | %s | **not on iTunes** | - | - | - | Beatport/Bandcamp |"
                     % (t["index"], want))
            continue
        got = "%s - %s" % (c.get("artistName"), c.get("trackName"))
        d = m["duration_delta_sec"]
        dtxt = "-" if d is None else ("%+.0fs" % d)
        if d is not None and not m["within_tolerance"]:
            dtxt = "**%s**" % dtxt
        flag = "album" if (c.get("collectionId") in album_ids) else "track"
        L.append("| %d | %s | %s | %s | %s | %s | [%s](%s) |" % (
            t["index"], want, got, m["verdict"], dtxt,
            money(c.get("trackPrice"), cur), flag, c.get("trackViewUrl")))
    L.append("")

    if clusters:
        L.append("## Albums")
        L.append("")
        L.append("| Album | Tracks | Sum | Album | Saving | Buy whole |")
        L.append("|---|---:|---:|---:|---:|---|")
        for a in clusters:
            if a["track_count"] < 2 and not a["album_buy"]:
                continue
            L.append("| [%s](%s) | %d | %s | %s | %s | %s |" % (
                a["collection_name"], a["collection_url"], a["track_count"],
                money(a["track_price_sum"], cur), money(a["collection_price"], cur),
                money(a["saving"], cur) if a["saving"] else "-",
                "**yes**" if a["album_buy"] else "no"))
        L.append("")

    needs_eyes = [r for r in rows if r["status"] in ("variant", "weak")]
    if needs_eyes:
        L.append("## Needs your eyes")
        L.append("")
        L.append("Right song, possibly the wrong recording. Duration is the tell.")
        L.append("")
        for r in needs_eyes:
            t, m, c = r["track"], r["match"], r["candidate"]
            L.append("- **%s - %s** (%.0fs) -> %s (%.0fs, %+.0fs). wanted mix `%s`, got `%s`. %s"
                     % (t["artist"], t["title"], t["duration_sec"] or 0,
                        c.get("trackName"), (c.get("trackTimeMillis") or 0) / 1000.0,
                        m["duration_delta_sec"] or 0, m["wanted_variant"] or "-",
                        m["candidate_variant"] or "-", c.get("trackViewUrl")))
        L.append("")

    missing = [r for r in rows if r["status"] == "not_found"]
    if missing:
        L.append("## Not on iTunes - buy elsewhere")
        L.append("")
        for r in missing:
            t = r["track"]
            q = urllib.parse.quote_plus("%s %s" % (t["artist"], t["title"]))
            L.append("- **%s - %s** - [Beatport](https://www.beatport.com/search?q=%s) - "
                     "[Bandcamp](https://bandcamp.com/search?q=%s)" % (t["artist"], t["title"], q, q))
        L.append("")

    path = os.path.join(REPORTS, slug + ".md")
    os.makedirs(REPORTS, exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(L))
    return path, per_track_total, bundled, cur, counts


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    slug = argv[0]
    country = "NL"
    if "--country" in argv:
        country = argv[argv.index("--country") + 1]
    refresh = "--refresh" in argv

    print("matching %s against the %s store..." % (slug, country))
    data, rows = match_playlist(slug, country, refresh)
    clusters = cluster_albums(rows)
    path, total, bundled, cur, counts = write_report(slug, data, rows, clusters, country)

    print("")
    print("%d tracks: %s" % (len(rows), ", ".join(
        "%d %s" % (v, k) for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))))
    print("per-track %s" % money(total, cur), end="")
    if bundled < total:
        print("  ->  %s with album bundling" % money(bundled, cur))
    else:
        print("")
    print("report: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
