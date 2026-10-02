"""Per-device settings, kept out of the code and out of git.

data/device.json:
    target          "apple" or "rockbox" -- which firmware the device runs.
                    Omit it and saltpod looks at the device instead.
    mount           where the iPod mounts (default /Volumes/IPOD)
    library_root    where your owned music lives
    firewire_guid   the iPod's USB serial as shown by `ioreg -p IOUSB`.
                    On a Classic that IS the FireWire GUID the iTunesDB
                    checksum is keyed from. REQUIRED FOR "apple" ONLY --
                    Rockbox has no checksum and never looks at it.

ONE FILE, PER-TARGET SECTIONS, not two files. The settings genuinely differ
between the firmwares -- `firewire_guid` is meaningless to Rockbox, and
Rockbox's playlist directory is meaningless to the Apple firmware -- but
`mount` and `library_roots` are the same fact either way, and two files
holding one fact is two files that drift. So anything shared stays at the
top level and anything target-specific goes in a block named for its
target:

    {
      "mount": "/Volumes/IPOD",
      "library_root": "/Volumes/YourDrive/Music",
      "target": "apple",
      "apple":   {"firewire_guid": "0000000000000000"},
      "rockbox": {"playlist_dir": "/Playlists"}
    }

A key at the top level still works and still wins where a target block does
not override it, so every existing device.json keeps working untouched.

Copy data/device.example.json to data/device.json and fill it in.
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = os.path.join(ROOT, 'data', 'device.json')

TARGETS = ('apple', 'rockbox')

# What each target needs before it can do anything at all.
REQUIRED = {'apple': ('firewire_guid',), 'rockbox': ()}


def set_roots(roots):
    """Write `library_roots` back to data/device.json, keeping the rest.

    Rewrites the file the user hand-edits, so it reads it first and puts
    back exactly what was there apart from the roots -- including the
    `_note` and anything a later version adds that this one does not know
    about. A singular `library_root` is folded in and dropped, because
    leaving both would give two answers to one question.
    """
    d = {}
    if os.path.exists(PATH):
        with open(PATH) as f:
            d = json.load(f)
    d['library_roots'] = list(roots)
    d.pop('library_root', None)
    tmp = PATH + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(d, f, indent=1)
        f.write('\n')
    os.replace(tmp, PATH)
    return d['library_roots']


def detect_target(mount):
    """Which firmware this device is running, BY LOOKING. None if unsure.

    Rockbox keeps its whole installation in `.rockbox/` at the volume root,
    which is as unambiguous a marker as exists. A dual-booted device has
    both, and Rockbox wins -- it is the one that was deliberately installed.
    """
    try:
        if os.path.isdir(os.path.join(mount, '.rockbox')):
            return 'rockbox'
        if os.path.exists(os.path.join(mount, 'iPod_Control', 'iTunes', 'iTunesDB')):
            return 'apple'
    except OSError:
        pass
    return None


def load(target=None):
    """Settings for one target, with the shared keys folded in.

    THE GUID IS NOT UNIVERSAL AND USED TO BE TREATED AS IF IT WERE. `load`
    refused to return at all without sixteen hex characters, which is
    correct for the Apple firmware -- an iTunesDB with a wrong checksum
    shows an empty library -- and simply wrong for Rockbox, which has no
    checksum. A Rockbox-only owner could not start the tool.
    """
    if not os.path.exists(PATH):
        raise SystemExit('no data/device.json - copy data/device.example.json and '
                         'fill it in')
    d = json.load(open(PATH))

    d.setdefault('mount', '/Volumes/IPOD')
    chosen = (target or d.get('target') or detect_target(d['mount']) or 'apple')
    if chosen not in TARGETS:
        raise SystemExit('data/device.json: target must be one of %s'
                         % ', '.join(TARGETS))
    d['target'] = chosen
    d['target_detected'] = detect_target(d['mount'])

    # the target's own block wins over a top-level key of the same name
    for k, v in (d.get(chosen) or {}).items():
        d[k] = v

    for k in REQUIRED[chosen]:
        if k == 'firewire_guid':
            if not re.fullmatch(r'[0-9A-Fa-f]{16}', d.get('firewire_guid', '')):
                raise SystemExit(
                    "data/device.json: target 'apple' needs a 16-character "
                    "firewire_guid (the iPod's USB serial from `ioreg -p IOUSB`); "
                    "it is what the iTunesDB checksum is keyed from, and a wrong "
                    "one shows an empty library on the device")
        elif not d.get(k):
            raise SystemExit("data/device.json: target %r needs %r" % (chosen, k))

    # One drive was the first case; anyone else may keep music in several
    # places. A bare string still works and becomes a one-element list.
    roots = d.get('library_roots')
    if isinstance(roots, str):
        roots = [roots]
    if not roots and d.get('library_root'):
        roots = [d['library_root']]
    d['library_roots'] = [r for r in (roots or []) if r]
    return d
