"""`saltpod` -- the one command.

Deliberately plain argparse, in the PlayPi manner. Run with no verb it opens
the page, the way `sslook` alone starts its walkthrough; everything else is a
verb with a help line that says what it does in a sentence.
"""
import argparse
import os
import sys

from . import __version__
from .console import receipt, step, note, fail


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from . import curate
        return curate.main()

    parser = argparse.ArgumentParser(
        prog="saltpod",
        description="Playlists on an iPod Classic without iTunes: curate in a page, "
                    "sequence by ear, sync to the device.")
    sub = parser.add_subparsers(dest="cmd", metavar="verb")

    p = sub.add_parser("curate", help="open the page; curating, sequencing and data jobs all happen there")
    p.add_argument("--port", type=int, default=7654)
    p.add_argument("--no-open", action="store_true", help="start the server without opening a browser")

    p = sub.add_parser("plan", help="say what a sync would change on the device, and touch nothing")
    p.add_argument("--mount", help="where the iPod is mounted; default from data/device.json")

    p = sub.add_parser("sync", help="make the iPod match the curation state: backup, convert, copy, write, verify, eject")
    p.add_argument("--mount")
    p.add_argument("--no-eject", action="store_true", help="leave the iPod mounted afterwards")

    p = sub.add_parser("device", help="pull the tracks already on the iPod into the curation state")
    p.add_argument("--mount")

    p = sub.add_parser("read", help="print what the iPod's database holds: tracks and playlists")
    p.add_argument("path", nargs="?", help="a mount point or an iTunesDB file; default from data/device.json")

    p = sub.add_parser("verify", help="check a database's checksum against the device GUID")
    p.add_argument("path", nargs="?")

    p = sub.add_parser("reconcile", help="map the tracks on the iPod back to the originals in your library")
    p.add_argument("--mount")

    p = sub.add_parser("index", help="index the audio files you own, so sync knows where they are")
    p.add_argument("roots", nargs="*", help="folders to walk; default the library root in data/device.json")

    p = sub.add_parser("state", help="the curation state: rebuild it, or print its counts")
    p.add_argument("what", choices=["rebuild", "stats", "buylist", "vinyl", "collections"], nargs="?", default="stats")

    p = sub.add_parser("applemusic", help="read Apple Music: its playlists, their dates, and every track in the library")
    p.add_argument("what", choices=["read", "playlists", "peek"], nargs="?", default="read")
    p.add_argument("name", nargs="?", help="for peek: the playlist to look inside, without importing it")

    p = sub.add_parser("discogs", help="what the Discogs exports hold, and what is flagged but not yet on either list")
    p.add_argument("what", choices=["status", "wantlist", "collection"], nargs="?", default="status")

    sub.add_parser("version", help="print the version and exit")

    a = parser.parse_args(argv)
    if a.cmd == "version":
        print(__version__); return 0
    if a.cmd == "curate":
        from . import curate
        return curate.main(["--port", str(a.port)] + (["--no-open"] if a.no_open else []))
    if a.cmd in ("plan", "sync"):
        from . import apply
        apply._cfg()
        mount = a.mount or apply.MOUNT
        if not os.path.exists(os.path.join(mount, apply.DB_REL)):
            fail(f"no iPod at {mount}", "plug it in and put it in Disk Mode (hold Select+Menu, then Select+Play)")
        if a.cmd == "plan":
            apply.print_plan(apply.plan(mount)); return 0
        apply.sync(mount, eject=not a.no_eject); return 0
    if a.cmd == "device":
        from . import state
        state.import_device(a.mount); return 0
    if a.cmd == "read":
        from . import itunesdb
        return itunesdb.main([a.path] if a.path else [])
    if a.cmd == "verify":
        from . import hash58, config
        cfg = config.load()
        path = a.path or os.path.join(cfg["mount"], "iPod_Control/iTunes/iTunesDB")
        if os.path.isdir(path):
            path = os.path.join(path, "iPod_Control/iTunes/iTunesDB")
        data = open(path, "rb").read()
        ok = hash58.verify(data, cfg["firewire_guid"])
        receipt("database", path)
        receipt("hash58", "matches the device GUID" if ok else "DOES NOT MATCH -- the iPod will show an empty library",
                tone="good" if ok else "bad")
        return 0 if ok else 1
    if a.cmd == "reconcile":
        from . import reconcile
        return reconcile.main(["--mount", a.mount] if a.mount else [])
    if a.cmd == "index":
        from . import local_index, config
        roots = a.roots or [config.load().get("library_root", "")]
        if not roots[0]:
            fail("no library root", "pass folders, or set library_root in data/device.json")
        return local_index.main(roots)
    if a.cmd == "applemusic":
        from . import curate as C
        if a.what == "read":
            step("reading Music.app")
            d = C.refresh_am_index()
            receipt("playlists", str(len(d["playlists"])))
            receipt("library tracks", str(len(d.get("library") or [])))
            receipt("cached", os.path.relpath(C.AM_INDEX, os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
            return 0
        if a.what == "playlists":
            d = C.am_index()
            if not d["playlists"]:
                fail("nothing read yet", "run: saltpod applemusic read")
            have = set(C.playlist_slugs())
            import re as _re
            for p in d["playlists"]:
                slug = _re.sub(r"^-|-$", "", _re.sub(r"[^a-z0-9]+", "-", p["name"].lower()))
                print("%-38s %5d  created %s  last %s  %s"
                      % (p["name"][:38], p["tracks"], (p["created"] or "?")[:10],
                         (p["last"] or "?")[:10], "imported" if slug in have else ""))
            note("%d playlists; created is the earliest a track in it was added, "
                 "because Music.app has no creation date" % len(d["playlists"]))
            return 0
        if not a.name:
            fail("peek needs a playlist name", 'try: saltpod applemusic peek "Jazz Party"')
        import subprocess as _sp
        r = _sp.run(["osascript", "-l", "JavaScript", "bin/export_playlists.js", "--peek", a.name],
                    capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        import json as _json
        d = _json.loads(r.stdout or "{}")
        if d.get("error"):
            fail(d["error"], "saltpod applemusic playlists lists the names")
        for t in d.get("tracks", []):
            print("%-30s %-34s %s" % (t["artist"][:30], t["title"][:34], t["cloud"]))
        note("%d tracks; nothing was imported" % len(d.get("tracks", [])))
        return 0
    if a.cmd == "discogs":
        from . import discogs, state as _state
        d = discogs.payload()
        if a.what == "status":
            for k in ("wantlist", "collection"):
                f = d["files"][k]
                receipt(k, ("%d releases, exported %s" % (f["rows"], f["modified"]))
                        if f["modified"] else "not found at " + f["path"],
                        tone="good" if f["modified"] else "bad")
            own = {x["key"] for x in d["collection"]}
            want = {x["key"] for x in d["wantlist"]}
            st = _state.load()
            flagged = {}
            for r in st["tracks"].values():
                if not r["vinyl"]:
                    continue
                alb = (r.get("itunes") or {}).get("album") or (r.get("device") or {}).get("album") or ""
                flagged[discogs.norm(r["artist"]) + "|" + discogs.norm(alb)] = \
                    "%s - %s" % (r["artist"], alb or "(unknown release)")
            todo = [v for k, v in sorted(flagged.items()) if k not in own and k not in want]
            receipt("flagged for vinyl", "%d releases" % len(flagged))
            receipt("to add on Discogs", "%d" % len(todo), tone="good" if not todo else None)
            for v in todo:
                print("   " + v)
            note("drop fresh exports at %s/{wantlist,collection}.csv" % d["dir"])
            return 0
        for x in d[a.what]:
            print("%-28s %-38s %s" % (x["artist"][:28], x["title"][:38],
                                      " · ".join(y for y in (x["label"], x["format"], x["year"]) if y and y != "0")))
        note("%d releases" % len(d[a.what]))
        return 0
    if a.cmd == "state":
        from . import state
        {"rebuild": state.rebuild, "stats": state.stats, "buylist": state.buylist,
         "vinyl": state.vinyl_list, "collections": state.collections}[a.what]()
        return 0
    parser.print_help(); return 0


if __name__ == "__main__":
    sys.exit(main())
