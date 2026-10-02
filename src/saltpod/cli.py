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


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _local_index():
    """Index entries with `path` already pointing at a copy that exists.

    Goes through local_index.load() rather than reading the json here, so
    a track with copies in two roots resolves to the mounted one for every
    verb at once instead of only the ones that remembered to look.
    """
    from . import local_index as _LI
    return _LI.load()["tracks"]


def _mhod_of(node, typ):
    """One mhod string off a parsed node -- the three-line walk several verbs
    were each about to write for themselves."""
    from . import itunesdb_write as W
    for c in node.children:
        if c.magic == b"mhod" and W.mhod_type(c) == typ:
            return W.mhod_string(c)
    return ""


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

    p = sub.add_parser("sources", help="the folders your music lives in; add one and the index learns it without forgetting the rest")
    p.add_argument("what", choices=["list", "add", "remove"], nargs="?", default="list")
    p.add_argument("folder", nargs="?", help="for add/remove")
    p.add_argument("--json", action="store_true")

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

    p = sub.add_parser("art", help="cover art on the device: what is missing, rehearse it, write it")
    p.add_argument("what", choices=["status", "rehearse", "write"], nargs="?", default="status",
                   help="status: how many covers the iPod cannot show; "
                        "rehearse: do it all against COPIES and verify; "
                        "write: do it for real, after a backup")
    p.add_argument("--limit", type=int, default=0, help="only this many tracks (0 = all)")
    p.add_argument("--mount")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("plays", help="play counts and ratings: what the iPod recorded, and fold it into the library")
    p.add_argument("what", choices=["show", "device", "adopt", "merge"], nargs="?", default="show",
                   help="show: what the library holds; device: what is on the iPod right now; "
                        "adopt: take the counts iTunes left in the iTunesDB; "
                        "merge: add the Play Counts delta (the file is never deleted)")
    p.add_argument("--mount")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("loudness", help="Sound Check: how loud each track really is, and what the iPod should be told about it")
    p.add_argument("what", choices=["show", "scan", "import", "track", "rehearse", "write"],
                   nargs="?", default="show",
                   help="show: what the measurements say (no drive needed); "
                        "scan: measure the library (slow, needs the drive); "
                        "import: fold a finished scan file into the cache; "
                        "track: measure one file; "
                        "rehearse: work out every Sound Check value and write nothing; "
                        "write: put them on the device, after a backup")
    p.add_argument("path", nargs="?", help="for `track` the audio file; for `import` the scan json")
    p.add_argument("--target", type=float, default=-18.0,
                   help="the loudness to normalise to, in LUFS (default -18, the measured iTunes target)")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--limit", type=int, default=0, help="only this many files (0 = all)")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("devprefs", help="the device settings that decide whether saltpod may write at all")
    p.add_argument("what", choices=["show", "check"], nargs="?", default="show",
                   help="show: everything that could be read; check: just the findings")
    p.add_argument("--mount")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("rockbox", help="write the collections as .m3u8 playlists a Rockbox iPod can read")
    p.add_argument("what", choices=["plan", "write"], nargs="?", default="plan",
                   help="plan: what would change on the device, touching nothing; write: do it")
    p.add_argument("--mount")
    p.add_argument("--dir", help="playlist directory on the device (default .rockbox/Playlists)")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("smartlists", help="the smart playlists on the device: their rules, and whether we agree with iTunes about what is in them")
    p.add_argument("what", choices=["show", "check"], nargs="?", default="show",
                   help="show: the rules, decoded; check: evaluate them and diff against what iTunes materialised")
    p.add_argument("--mount")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("podcasts", help="file episodes as podcasts so the iPod resumes them instead of restarting")
    p.add_argument("what", choices=["status", "rehearse", "write"], nargs="?", default="status",
                   help="status: what declares itself a podcast and what the device thinks; "
                        "rehearse: do it against a COPY and verify; write: do it for real, after a backup")
    p.add_argument("--mount", help="the device, or an iTunesDB file to rehearse against")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("repair", help="fields on the device that disagree with the files, and putting them right")
    p.add_argument("what", choices=["check", "sizes"], nargs="?", default="check",
                   help="check: what disagrees, touching nothing; sizes: write the real file sizes")
    p.add_argument("--mount")
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

    if a.cmd == "art":
        import json as _json
        from . import artworkdb as ADB, artwork as AW, tags as T, state as S
        from . import itunesdb_write as W, config as CFG
        mount = a.mount or (CFG.load().get("mount") or "/Volumes/IPOD")
        adir = os.path.join(mount, "iPod_Control", "Artwork")
        dbp = os.path.join(mount, "iPod_Control", "iTunes", "iTunesDB")
        if not os.path.exists(dbp):
            fail("no iPod at " + mount, "plug it in and put it in Disk Mode")

        root = W.parse(open(dbp, "rb").read())
        mhits = []
        for sect in root.children:
            for lst in sect.children:
                if getattr(lst, "magic", None) == b"mhlt":
                    mhits = [c for c in lst.children if c.magic == b"mhit"]

        def mstr(m, t):
            for c in m.children:
                if c.magic == b"mhod" and W.mhod_type(c) == t:
                    return W.mhod_string(c)
            return ""

        adb = ADB.parse(os.path.join(adir, "ADB" if False else "ArtworkDB"))
        have = ADB.dbids(adb)
        fmts = ADB.formats(adb)
        idx = {}
        for e in _local_index():
            idx[S.key_for(e.get("artist"), e.get("title"))] = e

        todo = []
        import struct as _st
        for m in mhits:
            dbid = _st.unpack_from("<Q", m.hdr, 0x70)[0]
            if dbid in have:
                continue
            e = idx.get(S.key_for(mstr(m, 4), mstr(m, 1)))
            if e and e.get("has_art") and os.path.exists(e["path"]):
                todo.append((dbid, e["path"], mstr(m, 4), mstr(m, 1)))
        if a.limit:
            todo = todo[:a.limit]

        receipt("tracks on the device", str(len(mhits)))
        receipt("covers the device holds", str(len(have)))
        receipt("formats it wants", " ".join("%d(%dB)" % kv for kv in sorted(fmts.items())))
        receipt("covers we could add", str(len(todo)),
                tone="good" if todo else None)
        if a.what == "status":
            for _d, _p, ar, ti in todo[:12]:
                print("   %-30s %s" % (str(ar)[:30], str(ti)[:38]))
            if len(todo) > 12:
                note("and %d more" % (len(todo) - 12))
            return 0
        if not todo:
            note("nothing to add"); return 0

        if a.what == "rehearse":
            import shutil as _sh
            import tempfile as _tf
            work = _tf.mkdtemp(prefix="saltpod-art-rehearse-")
            step("copying the artwork files AND the database so nothing on the device is touched")
            _sh.copy2(os.path.join(adir, "ArtworkDB"), work)
            _sh.copy2(dbp, work)
            for c in fmts:
                _sh.copy2(os.path.join(adir, "F%d_1.ithmb" % c), work)
            target, where = work, "the copies"
        else:
            target, where = adir, "THE DEVICE"
            from . import apply as A
            import time as _t
            A._cfg()
            step("backing up before writing to " + where)
            # apply.backup() copies iPod_Control/iTunes and would NOT have
            # covered the artwork files this is about to change. The undo for
            # an append-only operation is the old database plus the previous
            # lengths, so that is what gets kept -- 199 KB, not 63 MB.
            snap = os.path.join(_repo_root(), "backups",
                                "artwork-%s" % _t.strftime("%Y-%m-%d-%H%M%S"))
            A.backup(mount)
            ADB.snapshot(adir, snap)
            receipt("undo point", os.path.relpath(snap, _repo_root()))

        step("rendering %d covers" % len(todo))
        entries = []
        for dbid, path, ar, ti in todo:
            art = T.art_bytes(path)
            if not art:
                continue
            try:
                entries.append((dbid, AW.render_all(art[1], {c: AW.CLASSIC_FORMATS[c]
                                                             for c in fmts})))
            except Exception as e:
                note("skipped %s - %s: %s" % (str(ar)[:20], str(ti)[:20], e))
        res = ADB.add(target, entries)
        receipt("added", "%d covers to %s" % (len(res["added"]), where))

        # THE LINK LIVES IN THE TRACK, and writing only the ArtworkDB is
        # exactly half the job -- it cost three hardware tests to learn.
        # mhit+0xA4 says whether the track has artwork and mhit+0x160 names
        # the image id; without them the firmware shows its placeholder no
        # matter how correct the ArtworkDB is.
        if res["added"]:
            by_dbid = {}
            for m in mhits:
                by_dbid[_st.unpack_from("<Q", m.hdr, 0x70)[0]] = m
            src_bytes = {d: len(T.art_bytes(p)[1]) for d, p, _a, _t in todo
                         if T.art_bytes(p)}
            linked = 0
            for dbid in res["added"]:
                m = by_dbid.get(dbid)
                if not m:
                    continue
                ADB.link_track(m, res["image_ids"][dbid], src_bytes.get(dbid))
                linked += 1
            blob = W.serialise(root, CFG.load()["firewire_guid"])
            from . import hash58 as H
            if not H.verify(blob, CFG.load()["firewire_guid"]):
                fail("the re-signed database does not verify", "nothing written")
            if a.what == "rehearse":
                open(os.path.join(target, "iTunesDB"), "wb").write(blob)
            else:
                tmp = dbp + ".new"
                open(tmp, "wb").write(blob)
                os.replace(tmp, dbp)
            receipt("tracks linked", "%d, hash58 re-signed and verified" % linked)
        for c in sorted(res["before"]):
            receipt("F%d_1.ithmb" % c, "%d -> %d bytes" % (res["before"][c], res["after"][c]))
        if res["skipped"]:
            for d, why in res["skipped"][:5]:
                note("skipped %016x: %s" % (d, why))

        # the gate: every blob is where the database says it is
        after = ADB.parse(os.path.join(target, "ArtworkDB"))
        bad = 0
        for dbid, blobs in entries:
            m = next((x for x in ADB.images(after).children
                      if (x.get32(0x14) | (x.get32(0x18) << 32)) == dbid), None)
            if not m:
                bad += 1; continue
            for mhod, corr in ADB._mhnis(m):
                ofs = _st.unpack_from("<I", mhod.body, 0x14)[0]
                size = _st.unpack_from("<I", mhod.body, 0x18)[0]
                with open(os.path.join(target, "F%d_1.ithmb" % corr), "rb") as fh:
                    fh.seek(ofs)
                    if fh.read(size) != blobs[corr]:
                        bad += 1
        receipt("verified", "every blob is at the offset the database claims"
                if not bad else "%d MISMATCHES" % bad, tone="good" if not bad else "bad")
        if a.what == "rehearse":
            note("nothing on the device was touched; the copies are in " + target)
        return 0 if not bad else 1

    if a.cmd == "plays":
        import datetime
        import json as _json
        from . import playcounts as PC, state as S, config as CFG, itunesdb as I
        mount = a.mount or (CFG.load().get("mount") or "/Volumes/IPOD")
        dbp = os.path.join(mount, "iPod_Control/iTunes/iTunesDB")
        if a.what == "device":
            if not os.path.exists(dbp):
                fail("no iPod at " + mount, "plug it in and put it in Disk Mode")
            side = PC.find(mount)
            tr = I.read(dbp)["tracks"]
            played = [t for t in tr if t.get("play_count")]
            receipt("tracks on the device", str(len(tr)))
            receipt("with a play count", "%d, %d plays in total"
                    % (len(played), sum(t["play_count"] for t in played)))
            receipt("Play Counts sidecar", "present" if side else
                    "not there -- the iPod writes one only once something has played")
            if side:
                try:
                    rows = PC.read(side, dbp)
                    receipt("unmerged plays", "%d tracks, %d plays"
                            % (len(rows), sum(r["plays"] for r in rows)))
                except PC.PlayCountError as e:
                    receipt("sidecar", str(e), tone="bad")
            for t in sorted(played, key=lambda x: -x["play_count"])[:12]:
                lp = (datetime.date.fromtimestamp(t["last_played"]).isoformat()
                      if t.get("last_played") else "-")
                print("   %-28s %-28s %4d  %s"
                      % (str(t["artist"])[:28], str(t["title"])[:28], t["play_count"], lp))
            return 0
        if a.what in ("adopt", "merge"):
            if not os.path.exists(dbp):
                fail("no iPod at " + mount, "plug it in and put it in Disk Mode")
            st = S.load()
            if a.what == "adopt":
                n = PC.adopt_db_counts(st, dbp)
                S.save(st)
                receipt("adopted", "%d tracks took the count iTunes left on the device" % n)
                note("a one-off floor, not a delta; running it again cannot inflate anything")
                return 0
            side = PC.find(mount)
            if not side:
                fail("no Play Counts file on the device",
                     "the iPod writes one only after something has been played")
            try:
                rows = PC.read(side, dbp)
            except PC.PlayCountError as e:
                fail(str(e), "")
            out = PC.merge(st, rows, PC.fingerprint(side))
            S.save(st)
            for k, v in out.items():
                receipt(str(k), str(v))
            note("the sidecar was NOT deleted; the iPod clears it itself on the next sync")
            return 0
        st = S.load()
        got = [r for r in st["tracks"].values() if r.get("plays") or r.get("rating")]
        if a.json:
            print(_json.dumps(sorted(got, key=lambda r: -(r.get("plays") or 0))[:200],
                              indent=2, default=str))
            return 0
        if not got:
            note("nothing counted yet -- try: saltpod plays adopt")
            return 0
        for r in sorted(got, key=lambda x: -(x.get("plays") or 0))[:25]:
            lp = (datetime.date.fromtimestamp(r["last_played"]).isoformat()
                  if r.get("last_played") else "-")
            print("   %-28s %-28s %4s %5s  %s"
                  % (str(r["artist"])[:28], str(r["title"])[:28], r.get("plays") or "",
                     "*" * (r.get("rating") or 0), lp))
        note("%d tracks carry a count or a rating" % len(got))
        return 0

    if a.cmd == "loudness":
        import json as _json
        from . import loudness as L

        if a.what == "track":
            if not a.path:
                fail("which file?", "saltpod loudness track '/path/to/a track.mp3'")
            r = L.analyse(a.path, a.target)
            if r is None:
                fail("could not measure that file", "ffmpeg could not decode it; `saltpod loudness track` needs a readable audio file")
            if a.json:
                print(_json.dumps(r, indent=2)); return 0
            receipt("integrated loudness", "%.1f LUFS" % r["lufs"])
            receipt("true peak", "%+.1f dBTP" % r["true_peak"])
            receipt("gain to reach %.0f LUFS" % a.target, "%+.1f dB" % r["gain_db"])
            receipt("Sound Check raw", str(r["raw"]), tone="good")
            if r["clips_after"]:
                note("this would clip once that gain is applied -- the device should not be told to raise it")
            return 0

        if a.what == "import":
            src = a.path or os.path.join(_repo_root(), "data", "local", "loudness_scan.json")
            if not os.path.exists(src):
                fail("no scan file at " + src, "run `saltpod loudness scan` first, or name the file")
            r = L.import_scan(src)
            if a.json:
                print(_json.dumps(r, indent=2)); return 0
            receipt("rows in the scan", str(r["read"]))
            receipt("folded into the cache", str(r["imported"]), tone="good" if r["imported"] else None)
            receipt("already there", str(r["already"]))
            if r["skipped"]:
                note("%d skipped -- no measurement to fold (ffmpeg could not read them)" % r["skipped"])
            return 0

        if a.what == "scan":
            from . import local_index as LI
            paths = [e["path"] for e in _local_index() if e.get("path")]
            if a.limit:
                paths = paths[:a.limit]
            if not paths:
                fail("nothing indexed", "run `saltpod index` first")
            missing = [p for p in paths if not os.path.exists(p)]
            if missing:
                fail("%d of %d indexed files are not on disk" % (len(missing), len(paths)),
                     "the library drive is probably unplugged -- `saltpod loudness show` reads what was already measured")
            seen = [0]

            def _tick(done, total):
                seen[0] = done
                if done % 100 == 0 or done == total:
                    sys.stderr.write("\r  measured %d/%d" % (done, total)); sys.stderr.flush()

            step("measuring %d files with %d workers" % (len(paths), a.workers))
            res = L.scan(paths, a.target, workers=a.workers, progress=_tick)
            sys.stderr.write("\n")
            ok = [r for r in res.values() if r]
            receipt("measured", "%d of %d" % (len(ok), len(paths)), tone="good")
            return 0

        if a.what in ("rehearse", "write"):
            from . import itunesdb_write as W, ipod_edit as E, state as S
            from . import config as CFG, hash58 as H
            mount = (CFG.load().get("mount") or "/Volumes/IPOD")
            dbp = os.path.join(mount, "iPod_Control", "iTunes", "iTunesDB")
            if not os.path.exists(dbp):
                fail("no iPod at " + mount, "plug it in and put it in Disk Mode")
            rows = L.cached_rows()
            if not rows:
                fail("nothing measured", "`saltpod loudness import` or `scan` first")
            # The measurements are keyed by PATH, the device by artist|title.
            # The index is what joins them, and it already resolves a track
            # to whichever copy exists -- so this works with the library
            # drive unplugged, because the numbers are already in the cache.
            by_key = {}
            for e in _local_index():
                m = rows.get(e.get("path")) or rows.get(e.get("elsewhere") or "")
                if m and m.get("lufs") is not None:
                    by_key[S.key_for(e.get("artist"), e.get("title"))] = m

            root = W.parse(open(dbp, "rb").read())
            plan, unmeasured, clipping, unchanged = [], 0, 0, 0
            for t in E.tracks(root):
                m = by_key.get(S.key_for(_mhod_of(t, 4), _mhod_of(t, 1)))
                if not m:
                    unmeasured += 1
                    continue
                gain = a.target - m["lufs"]
                tp = m.get("true_peak")
                # A QUIET TRACK IS THE ONE CASE THAT CAN DO HARM. Attenuating
                # never clips; amplifying a master that already peaks near
                # full scale does. Those get 1000 -- "no change" -- rather
                # than a gain that would make them worse.
                if gain > 0 and tp is not None and (tp + gain) > -1.0:
                    raw = 1000
                    clipping += 1
                else:
                    raw = L.soundcheck_for(m["lufs"], a.target)
                was = t.get32(0x4C)
                if was == raw:
                    unchanged += 1
                    continue
                plan.append((t, was, raw))

            receipt("tracks on the device", str(len(list(E.tracks(root)))))
            receipt("have a measurement", str(len(list(E.tracks(root))) - unmeasured))
            receipt("no measurement, left alone", str(unmeasured))
            receipt("already correct", str(unchanged))
            receipt("would be written", str(len(plan)), tone="good" if plan else None)
            if clipping:
                note("%d are quieter than the target AND would clip if raised -- "
                     "those get 1000 (no change) rather than a gain that hurts" % clipping)
            if plan:
                lo = min(r for _t, _w, r in plan); hi = max(r for _t, _w, r in plan)
                receipt("raw range", "%d .. %d  (1000 = no change)" % (lo, hi))
                for t, was, raw in plan[:6]:
                    print("   %-34s %6d -> %6d" % (_mhod_of(t, 1)[:34], was, raw))
            if a.what == "rehearse" or not plan:
                note("nothing was written") if a.what == "rehearse" else None
                return 0

            from . import apply as A
            A.backup(mount)
            for t, _was, raw in plan:
                t.set32(0x4C, raw)
            guid = CFG.load()["firewire_guid"]
            blob = W.serialise(root, guid)
            if not H.verify(blob, guid):
                fail("the re-signed database does not verify", "nothing written")
            open(dbp, "wb").write(blob)
            back = W.parse(open(dbp, "rb").read())
            have = sum(1 for t in E.tracks(back) if t.get32(0x4C))
            step("wrote %d Sound Check values" % len(plan))
            receipt("tracks now carrying a value", str(have), tone="good")
            receipt("hash58", "re-signed and verified", tone="good")
            return 0

        # show -- deliberately reads the cache alone, so it works with the
        # library drive unplugged. A report that needs the drive to say what
        # was already measured is a report nobody can read.
        rows = L.cached_rows()
        if not rows:
            fail("nothing measured yet",
                 "`saltpod loudness import` folds in a finished scan, `saltpod loudness scan` makes one")
        lufs = sorted(r["lufs"] for r in rows.values() if r.get("lufs") is not None)
        raws = [L.soundcheck_for(v, a.target) for v in lufs]
        louder = sum(1 for v in lufs if v > a.target)
        quieter = len(lufs) - louder
        peaks = [r.get("true_peak") for r in rows.values() if r.get("true_peak") is not None]
        clip = sum(1 for r in rows.values()
                   if r.get("lufs") is not None and r.get("true_peak") is not None
                   and (r["true_peak"] + (a.target - r["lufs"])) > -1.0)
        if a.json:
            print(_json.dumps({"measured": len(lufs), "target": a.target,
                               "louder_than_target": louder, "quieter_than_target": quieter,
                               "would_clip_after_gain": clip,
                               "lufs_min": lufs[0], "lufs_median": lufs[len(lufs) // 2],
                               "lufs_max": lufs[-1],
                               "raw_min": min(raws), "raw_max": max(raws)}, indent=2))
            return 0

        def _q(vals, p):
            return vals[int(p * (len(vals) - 1))]

        receipt("files measured", str(len(lufs)))
        receipt("target", "%.0f LUFS" % a.target)
        receipt("loudness", "min %.1f   median %.1f   max %.1f LUFS"
                % (lufs[0], _q(lufs, .5), lufs[-1]))
        receipt("louder than the target", "%d  (the iPod would turn these DOWN)" % louder,
                tone="good")
        receipt("quieter than the target", "%d  (it would turn these UP)" % quieter,
                tone="warn" if quieter else None)
        receipt("Sound Check raw", "%d .. %d   (1000 is no change)" % (min(raws), max(raws)))
        if clip:
            note("%d would clip once the gain is applied -- those need the flag checked before writing" % clip)
        note("nothing is written to the device until `saltpod sync`; this verb only measures")
        return 0

    if a.cmd == "devprefs":
        import json as _json
        from . import devprefs as DP
        # read()/report() call config.load() when mount is None, and that
        # exits the process when no device is configured. A verb whose job is
        # to SAY what the settings are should answer that, not vanish.
        try:
            mount = a.mount or __import__("saltpod.config", fromlist=["x"]).load().get("mount")
        except SystemExit:
            fail("no device configured", "run `saltpod curate` once, or pass --mount")
        if not mount:
            fail("no mount to look at", "pass --mount /Volumes/IPOD")

        if a.json:
            print(_json.dumps({"read": DP.read(mount), "findings": DP.check(mount)},
                              indent=2, default=str))
            return 0
        if a.what == "show":
            findings = DP.report(mount)
        else:
            findings = DP.check(mount)
            for f in findings:
                mark = {"ok": "ok ", "warn": "!! ", "danger": "***"}.get(f["level"], "   ")
                print(" %s %s" % (mark, f["what"]))
                print("      %s" % f["why"])
        bad = [f for f in findings if f["level"] == "danger"]
        return 1 if bad else 0

    if a.cmd == "rockbox":
        import json as _json
        from . import rockbox as R, state as S, config as CFG
        mount = a.mount or (CFG.load().get("mount") or "/Volumes/IPOD")
        if not os.path.isdir(mount):
            fail("no device at " + mount, "plug it in, or pass --mount")
        # Writing .rockbox/Playlists onto Apple firmware is useless rather
        # than harmful -- the Apple firmware never reads it. Say so and stop
        # instead of leaving files the device will silently ignore.
        seen = CFG.detect_target(mount)
        if seen != "rockbox":
            note("this device looks like %s firmware, not Rockbox"
                 % (seen or "neither Rockbox nor Apple"))
            if a.what == "write":
                fail("refusing to write Rockbox playlists to a non-Rockbox device",
                     "Apple firmware never reads .rockbox/Playlists; use `saltpod sync` instead")

        cols, skipped = R.collections_from_state(S.load())
        if not cols:
            fail("no collections to write", "arrange some in `saltpod curate` first")
        for sk in skipped:
            note("skipped %s in %s -- %s" % (sk["key"], sk["collection"], sk["why"]))

        pl = R.plan_playlists(mount, cols, a.dir)
        if a.what == "plan":
            if a.json:
                print(_json.dumps(pl, indent=2)); return 0
            receipt("playlist directory", pl["dir"])
            for k, tone in (("new", "good"), ("changed", "good"), ("unchanged", None)):
                if pl[k]:
                    receipt(k, "%d  (%s)" % (len(pl[k]), ", ".join(pl[k])), tone=tone)
            if pl["extra"]:
                note("%d file(s) there that no collection maps to: %s"
                     % (len(pl["extra"]), ", ".join(pl["extra"])))
            if not (pl["new"] or pl["changed"]):
                note("nothing to do -- the device already matches")
            return 0

        res = R.write_playlists(mount, cols, a.dir)
        if a.json:
            print(_json.dumps(res, indent=2)); return 0
        receipt("playlist directory", res["dir"])
        for w in res["written"]:
            receipt(w["collection"], "%s  %d tracks  %d bytes"
                    % (w["file"], w["tracks"], w["bytes"]), tone="good")
        for e in res["errors"]:
            note("FAILED %s -- %s" % (e["collection"], e["error"]))
        return 1 if res["errors"] else 0

    if a.cmd == "smartlists":
        import json as _json
        from . import smartlists as SL, ipod_edit as E, itunesdb_write as W, config as CFG
        mount = a.mount or (CFG.load().get("mount") or "/Volumes/IPOD")
        dbp = mount if os.path.isfile(mount) else os.path.join(
            mount, "iPod_Control", "iTunes", "iTunesDB")
        if not os.path.exists(dbp):
            fail("no iPod database at " + dbp, "plug it in and put it in Disk Mode")

        root = W.parse(open(dbp, "rb").read())
        found = []
        for typ, kind in ((2, "regular"), (5, "media-type")):
            sect = W.section(root, typ)
            for pl in (E.playlists(root, sect) if sect is not None else []):
                if E.is_smart(pl):
                    found.append((kind, pl))
        if not found:
            note("no smart playlists on this device"); return 0

        tracks = SL.load_tracks(root) if a.what == "check" else None
        out, failed = [], 0
        for kind, pl in found:
            name = E.pl_name(pl) or "?"
            row = {"name": name, "kind": kind}
            try:
                parsed = SL.parse_rules(pl)
            except ValueError as e:
                row["error"] = str(e)
                out.append(row)
                continue
            row["understood"] = parsed["understood"]
            row["reasons"] = parsed["reasons"]
            row["live"] = parsed["live"]
            row["materialized"] = len(SL.materialized_ids(pl))
            row["describe"] = SL.describe(parsed)

            if a.what == "check":
                if not parsed["understood"]:
                    row["verdict"] = "cannot verify"
                else:
                    expected = SL.materialized_ids(pl)
                    got = [t["id"] for t in SL.evaluate(parsed, tracks)]
                    gs = set(got)
                    misses = [i for i in expected if i not in gs]
                    extras = [i for i in got if i not in set(expected)]
                    # Order only means something where a limit made iTunes
                    # choose one; without a limit the mhip order is arbitrary.
                    ordered = bool(parsed["limit"] and parsed["limit"].get("enabled"))
                    common = [i for i in got if i in set(expected)]
                    order_ok = (not ordered) or common == list(expected)
                    # WHY a miss happened decides whether it is a bug. The
                    # device's list is a snapshot from before saltpod's own
                    # writes, so a track excluded by a rule reading a field
                    # saltpod changed is the evaluator being right.
                    by_id = {t["id"]: t for t in tracks}
                    reasons = {}
                    for i in misses:
                        t = by_id.get(i)
                        for line in (SL.why_not(parsed, t) if t else ["not on the device"]):
                            reasons[line] = reasons.get(line, 0) + 1
                    row["why"] = sorted(reasons.items(), key=lambda kv: -kv[1])
                    row.update({"evaluated": len(got), "misses": len(misses),
                                "extras": len(extras), "order_checked": ordered,
                                "order_ok": order_ok})
                    bad = bool(misses) or not order_ok
                    row["verdict"] = "FAIL" if bad else "agrees"
                    failed += bool(bad)
            out.append(row)

        if a.json:
            print(_json.dumps(out, indent=2, default=str)); return 0

        for row in out:
            print()
            receipt(row["name"], row["kind"])
            if row.get("error"):
                note("could not parse: " + row["error"]); continue
            for line in row["describe"].splitlines():
                print("      " + line)
            if a.what == "show":
                receipt("  iTunes materialised", str(row["materialized"]))
                if not row["understood"]:
                    note("not understood, so saltpod will not evaluate it: "
                         + "; ".join(row["reasons"]))
                continue
            if row["verdict"] == "cannot verify":
                note("not understood -- refusing to evaluate rather than half-apply it")
                continue
            receipt("  iTunes materialised", str(row["materialized"]))
            receipt("  saltpod evaluates", str(row["evaluated"]),
                    tone="good" if row["verdict"] == "agrees" else "warn")
            if row["misses"]:
                note("%d tracks iTunes has that we do not" % row["misses"])
                for line, n in (row.get("why") or []):
                    note("   %d of them rejected by: %s" % (n, line))
            if row["extras"]:
                note("%d we find that iTunes does not -- expected, the device is stale"
                     % row["extras"])
            if row["order_checked"] and not row["order_ok"]:
                note("same tracks, different order -- the limit sort disagrees")
        print()
        if a.what == "check":
            if failed:
                receipt("verdict", "%d of %d differ from what iTunes materialised" % (failed, len(out)),
                        tone="warn")
            else:
                receipt("verdict", "every understood playlist matches what iTunes materialised",
                        tone="good")
        return 1 if failed else 0

    if a.cmd == "podcasts":
        import json as _json
        import shutil as _sh
        import tempfile as _tf
        from . import podcasts as P, ipod_edit as E, itunesdb_write as W
        from . import config as CFG, state as S, hash58 as H

        mount = a.mount or (CFG.load().get("mount") or "/Volumes/IPOD")
        # A plain file is accepted so a backup can be rehearsed against with
        # no hardware attached -- the same affordance `smartlists` has, and
        # the reason this verb could be tested at all before the iPod
        # came back.
        as_file = os.path.isfile(mount)
        dbp = mount if as_file else os.path.join(mount, "iPod_Control", "iTunes", "iTunesDB")
        if not os.path.exists(dbp):
            fail("no iPod database at " + dbp, "plug it in, or pass --mount with a backup file")

        root = W.parse(open(dbp, "rb").read())

        # WHICH TRACKS ARE PODCASTS IS NOT A GUESS. iTunes stamped PCST/WFED
        # into these files when they were subscribed to; the files still
        # carry it. `declares_podcast` reads that, so nothing here infers a
        # podcast from a genre string or a folder name.
        idx = {S.key_for(e.get("artist"), e.get("title")): e for e in _local_index()}
        want, unreadable = set(), 0
        for t in E.tracks(root):
            e = idx.get(S.key_for(_mhod_of(t, 4), _mhod_of(t, 1)))
            if not e or not e.get("path"):
                continue
            if not os.path.exists(e["path"]):
                unreadable += 1
                continue
            try:
                if P.declares_podcast(e["path"]):
                    want.add(E.track_dbid(t))
            except Exception:
                unreadable += 1

        pl = P.plan(root, want)
        flagged = P._flagged_playlists(root)
        if a.json and a.what == "status":
            print(_json.dumps({"plan": pl, "flagged_playlists": flagged,
                               "unreadable": unreadable}, indent=2, default=str))
            return 0

        receipt("tracks on the device", str(len(list(E.tracks(root)))))
        receipt("declare themselves podcasts", str(len(pl["tracks"])),
                tone="good" if pl["tracks"] else None)
        receipt("already filed as podcasts", str(pl["already"]))
        receipt("playlists carrying the podcast flag",
                ", ".join(map(str, flagged)) if flagged else "none",
                tone="warn" if len(flagged) > 1 else None)
        if unreadable:
            note("%d files could not be read -- the library drive may be unplugged" % unreadable)
        for r in pl["tracks"][:12]:
            print("   %-28s %s" % (str(r["artist"])[:28], str(r["title"])[:40]))
        if len(pl["tracks"]) > 12:
            note("and %d more" % (len(pl["tracks"]) - 12))

        if a.what == "status":
            return 0
        if not want:
            note("nothing to file"); return 0

        if a.what == "rehearse":
            work = _tf.mkdtemp(prefix="saltpod-podcasts-")
            _sh.copy2(dbp, work)
            target = os.path.join(work, os.path.basename(dbp))
            where = "the copy"
        else:
            if as_file:
                fail("`write` needs the device, not a file", "pass --mount /Volumes/IPOD")
            from . import apply as A
            A.backup(mount)
            target, where = dbp, "THE DEVICE"

        root2 = W.parse(open(target if a.what == "rehearse" else dbp, "rb").read())
        try:
            res = P.apply(root2, want)
        except P.PodcastError as e:
            fail("refusing to write: " + str(e), "nothing was changed")

        guid = CFG.load()["firewire_guid"]
        blob = W.serialise(root2, guid)
        if not H.verify(blob, guid):
            fail("the re-signed database does not verify", "nothing written")
        open(target, "wb").write(blob)

        # Read it back from what was actually written, not from the tree in
        # memory -- the tree is what we believe, the file is what happened.
        back = W.parse(open(target, "rb").read())
        filed = sum(1 for t in E.tracks(back) if t.get32(P.MEDIATYPE) == P.PODCAST)
        again = P._flagged_playlists(back)

        step("wrote to %s" % where)
        receipt("tracks filed as podcasts", str(filed), tone="good")
        receipt("playlist", "%s%s" % (res["playlist"], " (created)" if res["created"] else ""))
        receipt("members", str(res["members"]))
        receipt("flagged playlists after the write",
                ", ".join(map(str, again)), tone="warn" if len(again) != 1 else "good")
        receipt("hash58", "re-signed and verified", tone="good")
        if len(again) != 1:
            note("exactly one flagged playlist is required -- the firmware shows none otherwise")
            return 1
        if a.what == "rehearse":
            note("that was a copy; nothing on the device changed")
        return 0

    if a.cmd == "repair":
        import json as _json
        from . import itunesdb_write as W, ipod_edit as E, config as CFG, hash58 as H
        mount = a.mount or (CFG.load().get("mount") or "/Volumes/IPOD")
        dbp = os.path.join(mount, "iPod_Control", "iTunes", "iTunesDB")
        if not os.path.exists(dbp):
            fail("no iPod at " + mount, "plug it in and put it in Disk Mode")
        root = W.parse(open(dbp, "rb").read())
        rows = E.size_audit(root, mount)
        if a.json:
            print(_json.dumps([{k: v for k, v in r.items() if k != "mhit"}
                               for r in rows], indent=2))
            return 0
        receipt("tracks on the device", str(len(list(E.tracks(root)))))
        receipt("size field disagrees with the file", str(len(rows)),
                tone="warn" if rows else "good")
        if not rows:
            note("every track's recorded size matches the file"); return 0
        tpl = [r for r in rows if r["was"] == 3629903]
        off = [r for r in rows if r["delta"] == -56]
        if tpl:
            receipt("  carrying the template's size", "%d  (3629903 bytes)" % len(tpl))
            worst = max(tpl, key=lambda r: r["now"])
            note("worst: %.0f MB declared as %.1f MB" % (worst["now"] / 1e6, 3629903 / 1e6))
        if off:
            receipt("  exactly 56 bytes too large", "%d  (retagged after the record was written)" % len(off))
        if a.what == "check":
            note("`saltpod repair sizes` writes the real sizes, after a backup")
            return 0

        from . import apply as A
        A.backup(mount)
        fixed = E.size_repair(root, mount)
        guid = CFG.load()["firewire_guid"]
        blob = W.serialise(root, guid)
        if not H.verify(blob, guid):
            fail("the re-signed database does not verify", "nothing written")
        open(dbp, "wb").write(blob)
        # Re-read from the file, not the tree: the tree is what we believe.
        back = W.parse(open(dbp, "rb").read())
        left = E.size_audit(back, mount)
        step("wrote %d corrected sizes" % len(fixed))
        receipt("still disagreeing", str(len(left)), tone="good" if not left else "warn")
        receipt("hash58", "re-signed and verified", tone="good")
        return 0 if not left else 1

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
    if a.cmd == "sources":
        import json as _json
        from . import local_index as LI, config as CFG
        cfg = CFG.load()
        roots = list(cfg.get("library_roots") or [])
        d = LI.load(resolved=False)

        if a.what == "list":
            tracks = d.get("tracks", [])
            rows = []
            for r in roots:
                rp = os.path.expanduser(r)
                # A track counts for a root if ANY of its copies is under it.
                n = sum(1 for e in tracks
                        if any((c or "").startswith(rp)
                               for c in [e.get("path")] + list(e.get("copies") or [])))
                rows.append({"root": r, "mounted": os.path.isdir(rp), "tracks": n})
            reachable = sum(1 for e in tracks if os.path.exists(LI.resolve(e)))
            if a.json:
                print(_json.dumps({"roots": rows, "indexed": len(tracks),
                                   "reachable_now": reachable}, indent=2))
                return 0
            for r in rows:
                receipt(r["root"], "%d tracks   %s"
                        % (r["tracks"], "mounted" if r["mounted"] else "NOT MOUNTED"),
                        tone="good" if r["mounted"] else "warn")
            extra = [r for r in (d.get("roots") or []) if r not in roots]
            for r in extra:
                note("%s is in the index but not in device.json" % r)
            receipt("tracks indexed", str(len(d.get("tracks", []))))
            receipt("readable right now", str(reachable),
                    tone="good" if reachable else "warn")
            if reachable < len(d.get("tracks", [])):
                note("the rest live on a root that is not mounted")
            return 0

        if not a.folder:
            fail("which folder?", "saltpod sources %s '/path/to/music'" % a.what)
        folder = os.path.abspath(os.path.expanduser(a.folder))

        if a.what == "remove":
            if folder not in [os.path.abspath(os.path.expanduser(r)) for r in roots]:
                fail("not a source: " + folder, "`saltpod sources list` shows them")
            kept = [r for r in roots
                    if os.path.abspath(os.path.expanduser(r)) != folder]
            CFG.set_roots(kept)
            receipt("removed", folder, tone="good")
            note("the index still holds its tracks -- `saltpod index` rebuilds, "
                 "and needs every remaining root mounted")
            return 0

        # add
        if not os.path.isdir(folder):
            fail("no such folder: " + folder)
        if folder in [os.path.abspath(os.path.expanduser(r)) for r in roots]:
            note("already a source"); return 0
        step("walking %s" % folder)
        try:
            res = LI.add_root(folder)
        except LI.MissingRoot as e:
            fail("could not read " + str(e))
        CFG.set_roots(roots + [folder])
        if a.json:
            print(_json.dumps(res, indent=2)); return 0
        receipt("files found", str(res["walked"]))
        receipt("new tracks", str(res["new_tracks"]),
                tone="good" if res["new_tracks"] else None)
        receipt("copies of tracks already indexed", str(res["copies_of_known"]),
                tone="good" if res["copies_of_known"] else None)
        if res["skipped"]:
            note("%d could not be probed" % res["skipped"])
        receipt("tracks indexed in total", str(res["total"]))
        if res["copies_of_known"]:
            note("those are now second locations for tracks saltpod already knew -- "
                 "it will read whichever copy is mounted")
        return 0

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
