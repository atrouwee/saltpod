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


def _ident(v):
    """A key or a path, told apart by looking rather than by a flag.

    A key is `artist|title` and a path is a path. Asking the user which one
    they are holding is a question the program can answer itself.
    """
    return {"path": v} if (os.sep in v or os.path.exists(v)) else {"key": v}


def _service(a):
    """Every service verb, through the one registry the HTTP server uses.

    THE POINT IS THAT THERE IS NO LOGIC HERE. This function turns argv into a
    dict, calls the operation, and prints the dict it gets back. If a rule
    appeared in this function it would be a second implementation of that
    rule, drifting quietly from the one the page gets -- which is exactly
    what the layer rule forbids on the other side of the boundary.
    """
    import json as _json
    from . import curate as C, tags as T

    body, op = {}, "/api/" + a.cmd
    if a.cmd == "track":
        body = _ident(a.ident)
    elif a.cmd == "tags":
        fields = {}
        for pair in a.set:
            if "=" not in pair:
                fail("--set wants FIELD=VALUE", "got %r" % pair)
            f, _, v = pair.partition("=")
            f = f.strip()
            if f not in T.FIELDS:
                fail("no field called %r" % f, "one of: " + " ".join(T.FIELDS))
            fields[f] = v
        if not fields:
            fail("nothing to write", "add --set artist=... ; `saltpod track` shows the current values")
        body = dict(_ident(a.ident), fields=fields)
    elif a.cmd == "undo":
        if a.list:
            # The stacks live in the SERVER process, so a separate `saltpod
            # undo --list` sees its own empty ones. Said plainly rather than
            # printing a confident zero: two processes, two stacks, and the
            # one that matters is the one holding the page's session.
            state = {"can_undo": len(C.UNDO), "can_redo": len(C.REDO),
                     "next": C.UNDO[-1]["label"] if C.UNDO else None}
            if a.json:
                print(_json.dumps(state))
            else:
                receipt("can undo", state["next"] or "nothing")
                receipt("can redo", C.REDO[-1]["label"] if C.REDO else "nothing")
                note("this process has its own stack; a running `saltpod curate` "
                     "holds the session's")
            return 0
        body = {"redo": True} if a.redo else {}
    elif a.cmd == "discard":
        if not a.yes:
            fail("discard takes back every staged change and cannot be undone",
                 "run it again with --yes if that is what you want")
    elif a.cmd == "decide":
        body = {"keys": a.keys}
        if a.tier:
            body["tier"] = a.tier
        if a.collection:
            body["collection"] = a.collection
            body["mode"] = a.mode
        for flag in ("vinyl", "bought"):
            v = getattr(a, flag)
            if v is not None:
                body[flag] = (v == "yes")
        if len(body) == 1:
            fail("nothing decided",
                 "add --tier sync, --collection NAME, --vinyl yes or --bought yes")
    elif a.cmd == "recover":
        body = {"key": a.key}

    out = C.OPS[op](body)
    if a.json:
        print(_json.dumps(out, indent=2, default=str))
        return 0 if out.get("ok", True) else 1

    if out.get("error"):
        fail(out["error"], "")
    if a.cmd == "track":
        # RENDERED FROM THE PAYLOAD'S OWN SHAPE, not from a guess about it.
        # The first version of this read flat keys, found no `writable`, and
        # printed "no" for a file it had just successfully written -- a client
        # inventing an answer the server had already given, two lines away.
        for f, v in (out.get("fields") or {}).items():
            if v:
                receipt(f.replace("_", " "), str(v))
        fi = out.get("file") or {}
        for k, label in (("ext", "container"), ("codec", "codec"),
                         ("seconds", "seconds"), ("size", "bytes")):
            if fi.get(k) not in (None, ""):
                receipt(label, str(fi[k]))
        receipt("artwork", "yes" if fi.get("has_art") else "none")
        receipt("writable", "yes" if fi.get("writable") else (fi.get("why") or "no"),
                tone="good" if fi.get("writable") else "bad")
        dev = out.get("device") or {}
        receipt("on the iPod", "yes" if dev.get("on") else "no")
        if fi.get("path"):
            receipt("path", fi["path"])
        return 0
    for k, v in out.items():
        if k == "ok" or isinstance(v, (dict, list)):
            continue
        receipt(k.replace("_", " "), str(v))
    if out.get("ok") is False:
        return 1
    note("the file on disk is the master; the iPod catches up on the next sync"
         if a.cmd == "tags" else "")
    return 0


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
    p.add_argument("--exclude", default=None, metavar="FILE",
                   help="JSON naming tracks/playlists to leave out: "
                        '{"tracks": ["<key>"], "playlists": ["<name>"]}')
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

    p = sub.add_parser("elsewhere", help="for tracks iTunes does not carry, ask MusicBrainz and Deezer who made them and where they are sold")
    p.add_argument("slugs", nargs="+", help="playlist slugs, as listed by `saltpod state stats`")

    p = sub.add_parser("discogs", help="what the Discogs exports hold, and what is flagged but not yet on either list")
    p.add_argument("what", choices=["status", "wantlist", "collection"], nargs="?", default="status")

    # ------------------------------------------------- the service verbs
    #
    # FIVE ENDPOINTS HAD NO VERB, and they were the five newest -- which is
    # how the gap always opens: the page needs something, the endpoint gets
    # written, and the terminal is the thing nobody remembers. These do not
    # reimplement anything. Each one calls the SAME function the HTTP handler
    # calls, through `curate.OPS`, so there is one implementation and two
    # ways in. `bin/layer_census.py --strict` fails if that stops being true.

    p = sub.add_parser("track", help="everything known about one track: the panel's payload, in the terminal")
    p.add_argument("ident", help="a key (artist|title) or a path to a file on the drive")
    p.add_argument("--json", action="store_true", help="the payload as the clients see it")

    p = sub.add_parser("tags", help="write tags into the file on disk; the iPod picks them up on the next sync")
    p.add_argument("ident", help="a key (artist|title) or a path to a file on the drive")
    p.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE",
                   help="repeatable: --set artist=Lamb --set 'title=Gorecki'. "
                        "Only the fields you name are touched.")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("undo", help="step the undo stack back, or forward with --redo")
    p.add_argument("--redo", action="store_true", help="go the other way")
    p.add_argument("--list", action="store_true", help="say what is on the stack and change nothing")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("discard", help="take back every staged change so the next plan is empty; no undo")
    p.add_argument("--yes", action="store_true", help="required: this cannot be undone")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("decide", help="mark tracks: sync, remove, buy, want the vinyl, or put them in a collection")
    p.add_argument("keys", nargs="+", help="one or more track keys (artist|title)")
    p.add_argument("--tier", choices=["sync", "remove", "undecided"],
                   help="sync it, take it off, or take the decision back")
    p.add_argument("--collection", help="the collection to add to or remove from")
    p.add_argument("--mode", choices=["add", "remove", "toggle"], default="toggle",
                   help="what to do with --collection; default toggle, because a "
                        "control that undoes itself is the product's rule")
    p.add_argument("--vinyl", choices=["yes", "no"], help="want the record")
    p.add_argument("--bought", choices=["yes", "no"], help="own the digital")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("recover", help="copy a track off the iPod back onto the drive, named from the database")
    p.add_argument("key", help="the track key, as `saltpod state stats` lists them")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("log", help="what the server and the terminal have been doing, and what failed")
    p.add_argument("-n", type=int, default=25, help="how many recent events (default 25)")
    p.add_argument("--level", choices=["debug", "info", "warn", "error"],
                   help="only this level and above")
    p.add_argument("--op", help="only this operation, e.g. sync, plan, tags")
    p.add_argument("--run", help="every event of one run, by its id")
    p.add_argument("--summary", action="store_true",
                   help="counts by operation and level, and the slowest ops")
    p.add_argument("--json", action="store_true")

    sub.add_parser("version", help="print the version and exit")

    a = parser.parse_args(argv)

    if a.cmd in ("track", "tags", "undo", "discard", "recover", "decide"):
        return _service(a)

    if a.cmd == "log":
        import json as _json
        from . import observe as O
        if a.summary:
            out = O.summary()
            if a.json:
                print(_json.dumps(out, indent=2, default=str)); return 0
            for k, v in out.items():
                if isinstance(v, dict):
                    step(k.replace("_", " "))
                    for kk, vv in v.items():
                        receipt(kk, str(vv))
                elif isinstance(v, list):
                    step(k.replace("_", " "))
                    for row in v:
                        receipt(str(row.get("op", "?")) if isinstance(row, dict) else str(row),
                                ("%.0f ms" % row["ms"]) if isinstance(row, dict) and row.get("ms") is not None else "")
                else:
                    receipt(k.replace("_", " "), str(v))
            return 0
        rows = O.tail(a.n, level=a.level, op=a.op, run=a.run)
        if a.json:
            print(_json.dumps(rows, indent=2, default=str)); return 0
        if not rows:
            note("nothing logged yet; %s" % O.current_path()); return 0
        for r in rows:
            ms = ("%7.1f ms" % r["ms"]) if r.get("ms") is not None else " " * 10
            mark = {"error": "!!", "warn": " ~", "info": "  ", "debug": "  "}.get(r.get("level"), "  ")
            print(" %s %s  %-8s %-9s %s %s"
                  % (mark, (r.get("ts") or "")[11:23], r.get("op", "")[:8],
                     r.get("run", ""), ms, r.get("msg", "")[:60]))
        note("%d events from %s" % (len(rows), O.current_path()))
        return 0

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
        ex = None
        if getattr(a, "exclude", None):
            import json as _j
            ex = _j.load(open(a.exclude))
        apply.sync(mount, eject=not a.no_eject, exclude=ex); return 0
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
        roots = a.roots or config.load().get("library_roots") or []
        if not roots:
            fail("no library root", "pass folders, or set library_roots in data/device.json")
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
    if a.cmd == "elsewhere":
        from . import find_elsewhere
        return find_elsewhere.main(a.slugs)
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
