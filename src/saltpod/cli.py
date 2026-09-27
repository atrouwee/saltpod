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
    if a.cmd == "state":
        from . import state
        {"rebuild": state.rebuild, "stats": state.stats, "buylist": state.buylist,
         "vinyl": state.vinyl_list, "collections": state.collections}[a.what]()
        return 0
    parser.print_help(); return 0


if __name__ == "__main__":
    sys.exit(main())
