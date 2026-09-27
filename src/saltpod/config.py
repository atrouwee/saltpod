"""Per-device settings, kept out of the code and out of git.

data/device.json:
    firewire_guid   the iPod's USB serial as shown by `ioreg -p IOUSB` -- on a
                    Classic that IS the FireWire GUID the checksum is keyed from
    mount           where the iPod mounts (default /Volumes/IPOD)
    library_root    where your owned music lives

Copy data/device.example.json to data/device.json and fill it in.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = os.path.join(ROOT, 'data', 'device.json')


def load():
    if not os.path.exists(PATH):
        raise SystemExit('no data/device.json - copy data/device.example.json and set your '
                         'firewire_guid (the iPod\'s USB serial from `ioreg -p IOUSB`)')
    d = json.load(open(PATH))
    if not re.fullmatch(r'[0-9A-Fa-f]{16}', d.get('firewire_guid', '')):
        raise SystemExit('data/device.json: firewire_guid must be 16 hex characters')
    d.setdefault('mount', '/Volumes/IPOD')
    # One drive was the first case; anyone else may keep music in several
    # places. A bare string still works and becomes a one-element list.
    roots = d.get('library_roots')
    if isinstance(roots, str):
        roots = [roots]
    if not roots and d.get('library_root'):
        roots = [d['library_root']]
    d['library_roots'] = [r for r in (roots or []) if r]
    return d


import re  # noqa: E402
