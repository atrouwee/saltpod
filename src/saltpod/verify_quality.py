#!/usr/bin/env python3
"""Verify that files claiming to be lossless actually are.

A FLAC encoded from a 320kbps MP3 is still a valid FLAC. Vinyl download codes
and resold DJ promos carry these more often than anyone admits, and no
container field reveals it -- the file reports 16/44.1 and a healthy bitrate
either way.

What does reveal it is the spectrum. Every lossy encoder discards everything
above a cutoff: roughly 16kHz for 128kbps, 19-20kHz for 320kbps, 20-21kHz for
AAC 256. Genuine lossless from an analogue or digital master carries energy up
to Nyquist (22.05kHz at 44.1). So: measure the energy above the suspect band
and compare it to the whole signal. A lossless file that is silent above 20kHz
was almost certainly lossy once.

    python3 src/verify_quality.py                 # everything in the index
    python3 src/verify_quality.py /path/to/dir    # a folder
    python3 src/verify_quality.py --strict        # also check lossy files

This is evidence, not proof. Some genuinely lossless material is simply dull
up there -- old analogue recordings, heavily processed masters. The report
says "suspect", never "fake", and prints the numbers so you can judge.
"""
import json
import os
import re
import subprocess
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INDEX = os.path.join(ROOT, "data", "local", "index.json")
REPORTS = os.path.join(ROOT, "reports")

from spectrum import (average_spectrum, spectral_edge, cliff,  # noqa: E402
                      SAMPLE_RATE)

LOSSLESS_EXT = {".flac", ".wav", ".aiff", ".aif", ".alac", ".m4a"}
# Thresholds calibrated against known fakes: the same source FLAC re-encoded
# through 320kbps and 128kbps MP3 and back to FLAC, measured alongside the
# untouched original.
#
#   real       edge 20553 Hz   cliff 32.6 dB/kHz
#   fake320    edge 20069 Hz   cliff 56.6 dB/kHz
#   fake128    edge 16721 Hz   cliff 65.8 dB/kHz
#
# The edge alone does not separate them -- 20.5k against 20.1k is nothing. The
# separation is in how the spectrum *ends*. An encoder's lowpass drops off a
# shelf; a dull master fades out. So the cliff carries the decision and the
# edge only says which encoder.
CLIFF_SUSPECT = 45.0      # dB/kHz at the edge
EDGE_CEILING = 21500.0    # true lossless at 44.1k runs close to Nyquist
EDGE_LOW = 17500.0        # an edge this low means a low-bitrate source


def ffprobe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        return None
    d = json.loads(out.stdout)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), {})
    fmt = d.get("format", {})
    return {
        "codec": a.get("codec_name"),
        "sample_rate": int(a.get("sample_rate") or 0),
        "channels": a.get("channels"),
        "bit_depth": int(a.get("bits_per_raw_sample") or a.get("bits_per_sample") or 0),
        "bitrate_kbps": round(int(fmt.get("bit_rate") or 0) / 1000) or None,
        "duration_sec": round(float(fmt.get("duration") or 0), 1),
    }


def measure(path):
    """Spectral edge and cliff steepness for one file."""
    freqs, db = average_spectrum(path)
    if freqs is None:
        return None, None
    edge = spectral_edge(freqs, db)
    return edge, cliff(freqs, db, edge)


def classify(info, edge, slope):
    ext_lossless = info["codec"] in ("flac", "alac", "pcm_s16le", "pcm_s24le",
                                     "pcm_s16be", "pcm_s24be")
    if not ext_lossless:
        return "lossy", "declared lossy (%s, %s kbps)" % (
            info["codec"], info["bitrate_kbps"])
    if edge is None:
        return "unknown", "could not measure"
    nyquist = (info["sample_rate"] or SAMPLE_RATE) / 2.0
    if slope >= CLIFF_SUSPECT and edge < min(EDGE_CEILING, nyquist - 400):
        guess = "128-160kbps" if edge < EDGE_LOW else "320kbps MP3 or AAC"
        return "suspect", ("spectrum stops dead at %.1f kHz, falling %.0f dB/kHz "
                           "-- the signature of a %s source" % (edge / 1000.0, slope, guess))
    if edge < EDGE_LOW:
        # Low edge but a gentle fade. Encoders brickwall, so this is more
        # likely a dark master or a vinyl rip than a transcode. Worth a look,
        # not worth re-buying over.
        return "dark", ("nothing above %.1f kHz, but it fades gently (%.0f "
                        "dB/kHz) rather than stopping -- probably a dark "
                        "master, not a transcode" % (edge / 1000.0, slope))
    return "ok", "runs to %.1f kHz, fading at %.0f dB/kHz" % (edge / 1000.0, slope)


def collect(argv):
    roots = [a for a in argv if not a.startswith("--")]
    paths = []
    if roots:
        for r in roots:
            r = os.path.expanduser(r)
            if os.path.isfile(r):
                paths.append(r)
                continue
            for dp, _d, fs in os.walk(r):
                for fn in sorted(fs):
                    if os.path.splitext(fn)[1].lower() in LOSSLESS_EXT | {".mp3"}:
                        paths.append(os.path.join(dp, fn))
    elif os.path.exists(INDEX):
        with open(INDEX) as f:
            paths = [t["path"] for t in json.load(f)["tracks"]]
    return paths


def main(argv):
    strict = "--strict" in argv
    paths = collect(argv)
    if not paths:
        print(__doc__)
        return 2

    rows = []
    for p in paths:
        ext = os.path.splitext(p)[1].lower()
        if ext not in LOSSLESS_EXT and not strict:
            continue
        info = ffprobe(p)
        if not info:
            continue
        edge, slope = measure(p)
        v, why = classify(info, edge, slope)
        rows.append({"path": p, "info": info, "edge_hz": edge,
                     "cliff_db_per_khz": slope, "verdict": v, "why": why})
        print("  [%-7s] %-55s %s" % (
            v, os.path.basename(p)[:55], why))

    suspect = [r for r in rows if r["verdict"] == "suspect"]
    dark = [r for r in rows if r["verdict"] == "dark"]
    L = ["# Lossless verification", "",
         "%d files checked. The test is where the spectrum ends and how "
         "abruptly: a lossy encoder's lowpass drops off a shelf, a dull master "
         "fades. Calibrated against the same track re-encoded through 320kbps "
         "and 128kbps MP3." % len(rows),
         "", "**%d likely transcoded, %d dark but probably honest.**"
         % (len(suspect), len(dark)), "",
         "| File | Codec | Rate | Depth | Edge | Cliff | Verdict |",
         "|---|---|---:|---:|---:|---:|---|"]
    order = {"suspect": 0, "dark": 1, "unknown": 2, "ok": 3, "lossy": 4}
    for r in sorted(rows, key=lambda r: (order.get(r["verdict"], 9), r["path"])):
        i = r["info"]
        L.append("| `%s` | %s | %s | %s | %s | %s | %s |" % (
            os.path.basename(r["path"])[:48], i["codec"],
            "%.1fk" % (i["sample_rate"] / 1000.0) if i["sample_rate"] else "-",
            i["bit_depth"] or "-",
            "%.1fk" % (r["edge_hz"] / 1000.0) if r["edge_hz"] else "-",
            "%.0f" % r["cliff_db_per_khz"] if r["cliff_db_per_khz"] is not None else "-",
            r["verdict"]))
    if dark:
        L += ["", "## Dark, but probably fine", ""]
        for r in dark:
            L.append("- `%s`" % r["path"].replace(os.path.expanduser("~"), "~"))
            L.append("  - %s" % r["why"])
    if suspect:
        L += ["", "## Likely transcoded from a lossy source", ""]
        for r in suspect:
            L.append("- `%s`" % r["path"].replace(os.path.expanduser("~"), "~"))
            L.append("  - %s" % r["why"])
    L += ["", "Evidence, not proof. Dull analogue masters can look like this "
          "honestly; check one by ear or by eye in a spectrogram before "
          "concluding anything.", ""]
    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, "quality.md")
    with open(path, "w") as f:
        f.write("\n".join(L))
    print("")
    print("%d checked, %d likely transcoded, %d dark" % (len(rows), len(suspect), len(dark)))
    print("report: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
