#!/usr/bin/env python3
"""Confirm a Bandcamp hit is the SAME CUT the iTunes match identified.

bin/bandcamp_search.js answers "is it sold here". It cannot answer "is it the
recording I want", because Bandcamp search results carry no running time. This
does, by reading the `data-tralbum` blob every release page embeds and comparing
its duration against the iTunes trackTimeMillis for the same playlist position.

Why this is not done in the browser: seller pages are per-seller subdomains and
cross-origin fetch from a bandcamp.com tab is blocked by CORS. These pages are
public, so plain HTTP has no such problem -- and unlike a browser run it is
cacheable and reproducible.

    python3 src/verify_bandcamp.py 2026-july
    python3 src/verify_bandcamp.py 2026-july --refetch

Durations land in data/bandcamp/<playlist>_durations.json and are reused unless
--refetch is passed. Anything beyond +/-5s is flagged `variant` and is a human
decision, never an auto-buy.
"""
import html
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOLERANCE = 5.0
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"


def norm(s):
    s = (s or "").lower().replace("’", "'").replace("‘", "'")
    s = re.sub(r"[^a-z0-9' ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fetch_tralbum(url):
    """Return the parsed data-tralbum blob for a Bandcamp release page."""
    try:
        out = subprocess.run(
            ["curl", "-sL", "--max-time", "30", "-A", UA, url],
            capture_output=True, timeout=45,
        ).stdout.decode("utf-8", "replace")
    except (subprocess.TimeoutExpired, OSError) as e:
        return None, "fetch failed: %s" % e
    m = re.search(r'data-tralbum="([^"]*)"', out)
    if not m:
        return None, "no data-tralbum on the page (moved, sold out, or blocked)"
    try:
        return json.loads(html.unescape(m.group(1))), None
    except ValueError as e:
        return None, "unparseable data-tralbum: %s" % e


def duration_for(tr, wanted_title, url):
    """Pick the right track's duration off a track or album page."""
    tracks = tr.get("trackinfo") or []
    if not tracks:
        return None
    if len(tracks) == 1:
        return tracks[0].get("duration")
    nw = norm(wanted_title)
    for t in tracks:                                  # exact title first
        if norm(t.get("title")) == nw:
            return t.get("duration")
    slug = url.rstrip("/").split("/")[-1]
    for t in tracks:                                  # then the URL slug
        if (t.get("title_link") or "").rstrip("/").split("/")[-1] == slug:
            return t.get("duration")
    for t in tracks:                                  # then a containment match
        if nw and (nw in norm(t.get("title")) or norm(t.get("title")) in nw):
            return t.get("duration")
    return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    refetch = "--refetch" in sys.argv
    if not args:
        sys.exit("usage: verify_bandcamp.py <playlist> [--refetch]")
    slug = args[0]

    bc_path = os.path.join(ROOT, "data", "bandcamp", "%s.json" % slug)
    if not os.path.exists(bc_path):
        sys.exit("no Bandcamp data for %s - run bin/bandcamp_search.js first" % slug)
    bc = json.load(open(bc_path))

    cache_path = os.path.join(ROOT, "data", "bandcamp", "%s_durations.json" % slug)
    cache = {} if refetch or not os.path.exists(cache_path) else json.load(open(cache_path))

    itunes_dir = os.path.join(ROOT, "data", "itunes", slug)
    rows = []
    for h in bc["hits"]:
        url = h.get("url")
        if not url:
            rows.append((h, None, None, "not on bandcamp"))
            continue

        if url in cache:
            bc_dur, err = cache[url].get("duration"), cache[url].get("error")
        else:
            tr, err = fetch_tralbum(url)
            bc_dur = duration_for(tr, h["title"], url) if tr else None
            if tr and bc_dur is None and not err:
                err = "track not found among %d on the page" % len(tr.get("trackinfo") or [])
            cache[url] = {"duration": bc_dur, "error": err,
                          "artist": (tr or {}).get("artist"),
                          "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            time.sleep(1.0)

        it_path = os.path.join(itunes_dir, "%03d.json" % h["i"])
        it_dur = None
        if os.path.exists(it_path):
            res = (json.load(open(it_path)).get("results") or [{}])[0]
            if res.get("trackTimeMillis"):
                it_dur = res["trackTimeMillis"] / 1000.0

        if err:
            verdict = "unverified"
        elif bc_dur is None or it_dur is None:
            verdict = "unverified"
        elif abs(bc_dur - it_dur) <= TOLERANCE:
            verdict = "confirmed"
        else:
            verdict = "variant"
        rows.append((h, bc_dur, it_dur, verdict))

    json.dump(cache, open(cache_path, "w"), indent=1, ensure_ascii=False)

    def mmss(s):
        return "-" if s is None else "%d:%02d" % (int(s) // 60, int(s) % 60)

    counts = {}
    print("%s - duration verification against the iTunes identity match\n" % slug)
    print("  %-3s %-42s %7s %7s %8s  %s" % ("#", "track", "bandcp", "itunes", "delta", "verdict"))
    for h, bcd, itd, v in rows:
        counts[v] = counts.get(v, 0) + 1
        delta = "" if (bcd is None or itd is None) else "%+.1fs" % (bcd - itd)
        flag = {"confirmed": "  ", "variant": "!!", "unverified": " ?", "not on bandcamp": "  "}[v]
        name = ("%s - %s" % (h["artist"], h["title"]))[:42]
        print("%s %-3d %-42s %7s %7s %8s  %s"
              % (flag, h["i"], name, mmss(bcd), mmss(itd), delta, v))

    print("\n" + "  ".join("%s: %d" % (k, counts[k]) for k in sorted(counts)))
    if counts.get("variant"):
        print("\n!! %d track(s) differ by more than %.0fs. A matching title at a different"
              "\n   length is a different cut. Check these before paying."
              % (counts["variant"], TOLERANCE))

    out = os.path.join(ROOT, "data", "bandcamp", "%s_verified.json" % slug)
    json.dump([{"i": h["i"], "artist": h["artist"], "title": h["title"], "url": h.get("url"),
                "bandcamp_sec": bcd, "itunes_sec": itd, "verdict": v}
               for h, bcd, itd, v in rows], open(out, "w"), indent=1, ensure_ascii=False)
    print("\nwritten: %s" % os.path.relpath(out, ROOT))


if __name__ == "__main__":
    main()
