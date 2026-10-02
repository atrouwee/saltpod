#!/usr/bin/env python3
"""Whether the three settings that keep saltpod's write path safe are
actually where they should be -- read-only, honestly, with "unknown" as a
real answer rather than a guess dressed up as one.

THE NEAR MISS, 2026-10-02. With this iPod plugged in and saltpod's library
intact (653 tracks, 11 playlists), Finder put up its standard dialog --
"Are you sure you do not want to sync music? All existing songs and
playlists on this iPod will be removed." -- one click away from deleting all
of it. Nothing had actually synced; auto-sync was OFF the whole session, as
it should be, and nothing was destroyed. The three settings that make
saltpod's model of the device ("only saltpod writes here, nothing else
decides to overwrite it") hold are:

    Manually manage music, movies, and TV shows      MUST be ON
    Automatically sync when this iPod is connected   MUST be OFF
    Enable disk use                                   MUST be ON
                                     (saltpod cannot write without it)

Nothing in saltpod reads any of them. This module makes them visible --
`read()` for the raw reading with its source and confidence, `check()` for
findings an owner (or an assistant posting on their behalf) can act on.

THE HAZARD THIS CANNOT FIX. The dialog above is not caused by a background
sync -- it fires the instant a HUMAN unticks "Sync Music" in Finder's Music
tab for a manually-managed device, whether or not anything was about to
sync. Auto-sync being off protects against the device syncing unattended;
it does nothing against a person clicking the wrong checkbox, and no code
running on this Mac can intercept that click. All this module can do is
make sure the owner knows the state of all three settings BEFORE they open
that tab, not after. `check()` always carries this warning, because it is
the actual danger, not a hypothetical one -- it is what nearly happened.

INVESTIGATION LOG, six candidate locations, all opened read-only, all
against one real device (iPod Classic, serial redacted -- this
matches data/device.json's `firewire_guid` exactly, confirmed against the
live `ioreg -p IOUSB` enumeration rather than assumed):

  1. <mount>/iPod_Control/Device/Preferences -- 2960 bytes, no plist
     wrapper. plistlib refuses it outright; a raw ASCII/UTF-16 strings scan
     finds nothing printable anywhere in the file. First 16 bytes read as
     four little-endian uint32s: 63, 0, 256, 50 -- then zero from offset
     0x10 through 0x8F. One more non-zero mark at offset 0x90 (`00 01 00
     00`, the same value, 256, as the third header field). The rest of the
     file (offsets 0x95-0xAEB, ~2700 bytes) is zero except for a dense
     packed region in the FINAL 164 bytes (offsets 2796-2959) -- the kind
     of place the firmware's own menu settings (EQ, shuffle, repeat,
     backlight, clicker, language, date/time, legal-disclaimer-accepted)
     would live. Nothing in either region decodes as anything resembling
     "manually manage" / "auto-sync" / "disk use": those are Finder/
     Music.app vocabulary, and this file's shape is consistent with being
     on-device firmware state the device never needs told who is deciding
     to write to it. UNKNOWN -- not guessed, because nothing legible was
     found, not because the file "probably" holds it.

  2. <mount>/iPod_Control/iTunes/iTunesPrefs (1232 bytes) and
     iTunesPrefs.plist (2583 bytes). The .plist is plistlib-readable and
     wraps a dozen empty ID-list arrays (AudiobookTrackIDs, MusicGenreNames,
     etc.) plus one binary blob keyed `iPodPrefs` -- and that blob IS the
     raw iTunesPrefs file, byte for byte (`frpd` magic at offset 0 in both).
     Inside it: four repeats of a plaintext owner-name /
     computer-name pair -- a pairing record, not a
     three-way settings record. No field in it was identified as any of
     the three settings. UNKNOWN.

  3. <mount>/iPod_Control/Device/SysInfo is 0 bytes on this device --
     empty, not absent, handled the same as absent. No SysInfoExtended
     file exists here at all. Neither carries anything.

  4. ~/Library/Preferences/com.apple.Music.plist, and the ByHost variant
     for THIS Mac's hardware UUID specifically (`ioreg -rd1 -c
     IOPlatformExpertDevice` -> IOPlatformUUID, so a stale ByHost file left
     behind by a previous Mac this home directory lived on is never read).
     Both carry `devp:2:Device Information` (81 bytes) -- opaque: no
     plaintext, and this device's firewire_guid does not appear in it in
     either byte order, so it is likely encrypted or hashed and was not
     pursued further. Only the ByHost copy additionally carries
     `pref:200:Machine Preferences` (4952 bytes) -- NOT opaque noise, it
     has real structure: a run of `\\x00\\x00<len><len>` two-byte headers
     each followed by that many UTF-16LE characters (confirmed by finding
     the library name encoded exactly that way at offset 1963).
     This is very plausibly where Finder's three checkboxes actually live
     -- it is named "Machine Preferences", lives per-byhost (exactly where
     a per-Mac, per-device sync setting belongs), and is only present once
     a device has synced from this Mac. But its format is proprietary and
     undocumented, and guessing which bytes are which boolean here is
     exactly the failure mode this module exists to avoid. UNKNOWN.

  5. ~/Library/Preferences/com.apple.iPod.plist -- a `Devices` dict keyed
     by device ID, each entry carrying Serial Number, Firmware Version,
     last Connected timestamp and a Use Count. Pure connect-history/
     identification cache, no sync-mode keys of any kind. And on this Mac
     its key for a currently-connected classic iPod differs from this
     -- ONE HEX DIGIT different from this device's real serial,
     device's own serial by one hex digit in the fifth byte. That is not this
     device's entry. `_device_identity()` below checks for an EXACT match
     only and reports "not found" rather than taking the near-match as
     good enough -- this is the concrete case the "do not guess" rule
     exists for.

  6. `diskutil info <mount>` -- the one source that gives a direct,
     current, read-only answer: whether the volume is mounted at all, and
     whether it is mounted read-write. That is not quite the same fact as
     "the Enable Disk Use checkbox is ticked" (the checkbox mostly governs
     whether Finder keeps the icon visible and whether iTunes/Music
     auto-ejects it; it does not flip a filesystem read-only bit), but it
     is the fact that actually matters for "can saltpod write right now",
     and it is read-only to obtain -- `diskutil info` on a path that is
     not a real volume returns exit 0 with "Could not find disk: ..." in
     its stdout rather than failing, which `_diskutil_info()` checks for
     explicitly so that case is not mistaken for "found it, and it's
     read-only".

CONFIDENCE SUMMARY. disk_use is answerable live, from diskutil plus an
`os.access` permission check (a stat-like query, not a write -- it touches
nothing). manual_management and auto_sync are not readable from anything
this investigation could find: value `None`, confidence `'unknown'`, on
every device tested so far. That is the honest result, not a gap to paper
over -- a safety check that invents a reassuring value is worse than one
that admits it does not know.

HOUSE RULES THIS MODULE FOLLOWS: standard library only; nothing here writes
to the device, writes a Mac preference, or calls `defaults write`; every
file read handles "not present" and "not parseable" without raising;
nothing imports this yet, it is additive.
"""
import os
import plistlib
import re
import subprocess
import sys
import time

from . import config

_CONFIDENCES = ('certain', 'unknown')
_LEVELS = ('ok', 'warn', 'danger')


# ------------------------------------------------------------------ reading

def _entry(value, source, confidence='certain'):
    assert confidence in _CONFIDENCES, confidence
    return {'value': value, 'source': source, 'confidence': confidence}


def _unknown(source):
    return {'value': None, 'source': source, 'confidence': 'unknown'}


def _run(argv, timeout=10):
    """A read-only subprocess call. Returns None (never raises) if the
    binary is missing, times out, or anything else goes wrong -- a missing
    `diskutil` or `ioreg` should degrade this module, not crash it."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def _read_plist(path):
    """A plist as a dict, or None -- absent, unreadable, and unparseable
    all land here alike, which is all any caller below needs to know."""
    try:
        with open(path, 'rb') as f:
            return plistlib.load(f)
    except Exception:
        # Deliberately broad: a corrupt/foreign-format preferences file
        # must never take this module down with it.
        return None


def _diskutil_info(mount):
    """`diskutil info <mount>` as a plain dict, or None if it is not a real,
    currently-known volume. `diskutil info` on a bare directory that is not
    a volume's own mount point exits 0 and prints "Could not find disk:
    <path>" -- MEASURED, not assumed -- so that text, or the absence of the
    baseline fields every real record carries, is treated as "not found"
    rather than parsed into a misleading dict.
    """
    r = _run(['diskutil', 'info', mount])
    if r is None or r.returncode != 0 or 'Could not find disk' in r.stdout:
        return None
    info = {}
    for line in r.stdout.splitlines():
        if ':' not in line:
            continue
        k, _, v = line.partition(':')
        info[k.strip()] = v.strip()
    if 'Device Identifier' not in info and 'Volume Name' not in info:
        return None
    return info


def _mac_host_uuid():
    """This Mac's IOPlatformUUID, used to pick the one ByHost preferences
    file that is actually this machine's -- a home directory that has lived
    on more than one Mac leaves old ByHost files behind, and reading one of
    those would describe a different computer's last-known state."""
    r = _run(['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'])
    if r is None or r.returncode != 0:
        return None
    m = re.search(r'"IOPlatformUUID"\s*=\s*"([0-9A-Fa-f-]+)"', r.stdout)
    return m.group(1) if m else None


def _live_usb_serial():
    """The serial ioreg reports right now for a connected iPod -- the one
    reading here that cannot possibly be stale, since it comes from the
    live USB enumeration rather than any cached file. Walks `ioreg -l`
    output block by block: a node's own properties print directly under
    its `+-o Name@...` line, before any child node's `+-o` line, so seeing
    the serial before the next `+-o` is a reliable "it belongs to this
    node" test. Returns None if no iPod node is present at all.
    """
    r = _run(['ioreg', '-p', 'IOUSB', '-l', '-w0'])
    if r is None or r.returncode != 0:
        return None
    in_ipod_block = False
    for line in r.stdout.splitlines():
        if '+-o ' in line:
            in_ipod_block = bool(re.search(r'\+-o\s+iPod@', line))
            continue
        if in_ipod_block:
            m = re.search(r'"(?:kUSBSerialNumberString|USB Serial Number)"\s*=\s*"([0-9A-Fa-f]+)"', line)
            if m:
                return m.group(1)
    return None


def _device_file_summary(mount):
    """Sizes of the on-device candidate files, in bytes, or None if a file
    is absent or could not be stat'd. Diagnostic only -- read() does not
    derive any of the three settings from these, see the module docstring
    for why -- but a report should say plainly what was and was not there,
    and "0 bytes" (SysInfo, measured) is a different fact from "absent"
    (SysInfoExtended, measured) even though neither is usable.
    """
    paths = {
        'Device/Preferences': ('iPod_Control', 'Device', 'Preferences'),
        'Device/SysInfo': ('iPod_Control', 'Device', 'SysInfo'),
        'Device/SysInfoExtended': ('iPod_Control', 'Device', 'SysInfoExtended'),
        'iTunes/iTunesPrefs': ('iPod_Control', 'iTunes', 'iTunesPrefs'),
        'iTunes/iTunesPrefs.plist': ('iPod_Control', 'iTunes', 'iTunesPrefs.plist'),
    }
    out = {}
    for label, parts in paths.items():
        try:
            out[label] = os.path.getsize(os.path.join(mount, *parts))
        except OSError:
            out[label] = None
    return out


def _mac_sync_prefs_note():
    """One explanatory sentence, shared by manual_management and auto_sync,
    about the single Mac-side location that plausibly holds them --
    `pref:200:Machine Preferences` in this Mac's ByHost com.apple.Music
    plist. See the module docstring, finding 4, for the full investigation;
    this is the live version of the same check, so a report reflects
    whatever is actually on this Mac right now rather than frozen findings.
    """
    host = _mac_host_uuid()
    if not host:
        return ("could not determine this Mac's hardware UUID (ioreg -rd1 -c "
                "IOPlatformExpertDevice) to find the right ByHost preferences file")
    path = os.path.expanduser(
        '~/Library/Preferences/ByHost/com.apple.Music.%s.plist' % host)
    plist = _read_plist(path)
    if plist is None:
        return "%s is absent or unreadable" % path
    blob = plist.get('pref:200:Machine Preferences')
    if blob is None:
        return ("%s has no 'pref:200:Machine Preferences' key -- this iPod may "
                "never have synced from this Mac" % path)
    return ("%s carries a 'pref:200:Machine Preferences' blob (%d bytes): an "
            "undocumented binary format (length-prefixed UTF-16LE strings -- "
            "confirmed to contain the library name) with no field identified "
            "as manual management or auto-sync. Present, but not legible."
            % (path, len(blob)))


def _tail(v, n=4):
    """The last few characters of a secret, or a word saying there is none."""
    v = '' if v is None else str(v)
    return v[-n:] if v else '(none)'


def _device_identity(mount, firewire_guid):
    """Which iPod is actually attached, cross-checked rather than assumed:
    the live USB serial (cannot be stale) against data/device.json's
    configured firewire_guid, with com.apple.iPod.plist's connect-history
    cache carried along for a report to show (it is usually NOT a match for
    this device -- see the module docstring, finding 5 -- so it is never
    used to decide anything, only shown).
    """
    live = _live_usb_serial()
    cache_path = os.path.expanduser('~/Library/Preferences/com.apple.iPod.plist')
    devices = (_read_plist(cache_path) or {}).get('Devices') or {}
    cached = devices.get(firewire_guid) if firewire_guid else None

    # NEVER PRINT THE SERIAL. It is the key the iTunesDB checksum is derived
    # from, `observe.py` already redacts it by shape, and the publish leak
    # gate treats it as a secret and will abort an export that contains it.
    # This is a report people paste into messages; it said the whole thing
    # twice. The last four characters are enough to tell two iPods apart.
    if firewire_guid and live:
        if firewire_guid.upper() == live.upper():
            matches = _entry(True, 'data/device.json firewire_guid matches the live '
                              'USB serial from `ioreg -p IOUSB` (...%s)' % live[-4:])
        else:
            matches = _entry(False, 'data/device.json firewire_guid (...%s) does NOT '
                              'match the live USB serial (...%s) -- this may not be the '
                              'configured device' % (firewire_guid[-4:], live[-4:]))
    elif live and not firewire_guid:
        matches = _unknown('no firewire_guid in data/device.json to compare against the '
                            'live USB serial (...%s)' % live[-4:])
    else:
        matches = _unknown('no iPod found on the live USB enumeration '
                            '(ioreg -p IOUSB found no "iPod@..." node)')

    return {
        'configured_firewire_guid': firewire_guid,
        'live_usb_serial': live,
        'cached_in_com.apple.iPod.plist': cached,
        'matches_live': matches,
    }


def read(mount=None):
    """Everything that could be determined, read-only, about the three
    settings that keep saltpod's write path safe -- plus enough context to
    judge how much to trust each reading.

    Returns:
        {
          'manual_management': {'value', 'source', 'confidence'},
          'auto_sync':          {'value', 'source', 'confidence'},
          'disk_use':           {'value', 'source', 'confidence'},
          'device_identity':    cross-check of which iPod this is,
          'device_files':       {label: size-in-bytes-or-None, ...},
        }

    `value` is True/False when known, `None` when not; `confidence` is
    `'certain'` or `'unknown'` -- never anything softer, because a
    softer-sounding middle confidence would invite treating "probably" as
    "yes". manual_management and auto_sync come back unknown on every
    device tested so far; see the module docstring for exactly what was
    checked and why nothing there was legible.
    """
    if mount is None:
        mount = config.load()['mount']

    try:
        firewire_guid = config.load().get('firewire_guid')
    except SystemExit:
        firewire_guid = None

    device_files = _device_file_summary(mount)
    identity = _device_identity(mount, firewire_guid)

    info = _diskutil_info(mount)
    if info is None:
        disk_use = _unknown('`diskutil info %s` found no such volume -- is anything '
                             'actually mounted there?' % mount)
    elif info.get('Mounted') != 'Yes':
        disk_use = _entry(False, 'diskutil info %s: Mounted = %r' % (mount, info.get('Mounted')))
    elif info.get('Volume Read-Only') is None or info.get('Media Read-Only') is None:
        disk_use = _unknown('diskutil info %s did not report a read-only flag' % mount)
    else:
        diskutil_writable = (info['Volume Read-Only'] == 'No' and info['Media Read-Only'] == 'No')
        access_writable = os.access(mount, os.W_OK)   # a permission check -- writes nothing
        if diskutil_writable == access_writable:
            disk_use = _entry(
                diskutil_writable,
                ('the volume is mounted read-write (diskutil info %s, agrees with '
                 'os.access)' % mount) if diskutil_writable else
                ('the volume is mounted read-only (diskutil info %s)' % mount))
        else:
            disk_use = _unknown(
                'diskutil (writable=%s) and os.access (writable=%s) disagree about %s '
                '-- not trusting either alone' % (diskutil_writable, access_writable, mount))

    mac_note = _mac_sync_prefs_note()
    manual_management = _unknown(mac_note)
    auto_sync = _unknown(mac_note)

    return {
        'manual_management': manual_management,
        'auto_sync': auto_sync,
        'disk_use': disk_use,
        'device_identity': identity,
        'device_files': device_files,
    }


# ------------------------------------------------------------------- checks

def check(mount=None):
    """`read()`, turned into findings: `{'level': 'ok'|'warn'|'danger',
    'what': str, 'why': str}`. The two DANGER cases are the ones named in
    the brief -- disk use off (saltpod cannot write) and auto-sync on
    (Finder may overwrite the library unattended) -- because those are
    the only two that are actually catastrophic on their own; everything
    else here is at most a warning. The Finder-dialog hazard note is always
    included, because it is the one that actually nearly happened and no
    reading of any preference file changes that it is still live.
    """
    r = read(mount)
    findings = []

    du = r['disk_use']
    if du['value'] is True:
        findings.append({'level': 'ok', 'what': 'disk use is on', 'why': du['source']})
    elif du['value'] is False:
        findings.append({'level': 'danger',
                          'what': 'disk use looks OFF -- saltpod cannot write to this device',
                          'why': du['source']})
    else:
        findings.append({'level': 'warn', 'what': 'could not determine disk use',
                          'why': du['source']})

    mm = r['manual_management']
    if mm['value'] is True:
        findings.append({'level': 'ok', 'what': 'manually manage music looks on', 'why': mm['source']})
    elif mm['value'] is False:
        findings.append({'level': 'warn', 'what': 'manually manage music looks off',
                          'why': mm['source']})
    else:
        findings.append({'level': 'warn',
                          'what': 'could not read "manually manage music" from any file',
                          'why': mm['source']})

    asx = r['auto_sync']
    if asx['value'] is True:
        findings.append({'level': 'danger',
                          'what': 'auto-sync looks ON -- Finder may sync this iPod unattended',
                          'why': asx['source']})
    elif asx['value'] is False:
        findings.append({'level': 'ok', 'what': 'auto-sync looks off', 'why': asx['source']})
    else:
        findings.append({'level': 'warn', 'what': 'could not read auto-sync from any file',
                          'why': asx['source']})

    m = r['device_identity']['matches_live']
    if m['value'] is False:
        findings.append({'level': 'danger',
                          'what': 'the configured device does not match what is attached',
                          'why': m['source']})
    elif m['value'] is None:
        findings.append({'level': 'warn', 'what': 'could not confirm which iPod is attached',
                          'why': m['source']})
    # m['value'] is True: no finding needed, identity matching is supporting
    # context for this module, not one of the three settings it exists for.

    findings.append({
        'level': 'warn',
        'what': 'a human unticking "Sync Music" in Finder is the real hazard, not a background sync',
        'why': ('Finder\'s own dialog -- "Are you sure you do not want to sync music? All '
                'existing songs and playlists on this iPod will be removed." -- fires the '
                'moment someone unchecks that box in the Music tab, whether or not a sync '
                'was about to run. Auto-sync being off (even when confirmed above) does not '
                'guard against this: it guards against the device syncing unattended, a '
                'different hazard from a person clicking the wrong checkbox. No code running '
                'on this Mac can intercept that click -- the only defense is knowing, before '
                'that tab is opened, what state all three settings are actually in.'),
    })

    return findings


# ---------------------------------------------------------------- reporting

def _fmt_entry(label, e):
    val = 'UNKNOWN' if e['value'] is None else str(e['value'])
    return '  %-20s %-9s %-9s %s' % (label, val, e['confidence'], e['source'] or '')


def report(mount=None):
    """Print what `read()` and `check()` actually find, for a human to read
    before -- not after -- they touch Finder's Music tab. Returns the
    findings list, same as `check()`, so a caller can act on it too."""
    if mount is None:
        mount = config.load()['mount']
    r = read(mount)

    print('devprefs report -- %s' % mount)
    print()
    print(_fmt_entry('manual_management', r['manual_management']))
    print(_fmt_entry('auto_sync', r['auto_sync']))
    print(_fmt_entry('disk_use', r['disk_use']))
    print()

    ident = r['device_identity']
    print('  device identity:')
    # last four only -- see _device_identity: the serial is the key the
    # iTunesDB checksum is derived from, and this report gets pasted.
    print('    configured firewire_guid    ...%s' % _tail(ident['configured_firewire_guid']))
    print('    live USB serial             ...%s' % _tail(ident['live_usb_serial']))
    print('    matches                     %s (%s)'
          % (ident['matches_live']['value'], ident['matches_live']['confidence']))
    print()

    print('  on-device files (bytes; None = absent/unreadable):')
    for label, size in r['device_files'].items():
        print('    %-28s %s' % (label, size))
    print()

    findings = check(mount)
    mark = {'ok': ' ok ', 'warn': ' !! ', 'danger': '*** '}
    for f in findings:
        print('  %s%-7s %s' % (mark[f['level']], f['level'], f['what']))
        print('       %s' % f['why'])
        print()

    return findings


# ----------------------------------------------------------------- selftest

def selftest():
    """Exercises what can actually be tested without a live device: every
    reader comes back None (never raises) on an absent or garbage file, and
    `read()`/`check()` are well-shaped even pointed at an empty directory.
    If the configured device happens to be attached right now, one more
    check does a live pass over it and reports what it found -- but that
    check SKIPS rather than fails when nothing is mounted, so this selftest
    stays meaningful in an environment with no iPod plugged in. The
    read-only guarantee itself is structural (nothing in this module opens
    a path for writing, deletes anything, or calls `defaults write`) rather
    than something a runtime check can prove.
    """
    import tempfile

    passed, failed = [], []

    def check_(name, fn):
        try:
            detail = fn()
        except Exception as e:
            failed.append((name, '%s: %s' % (type(e).__name__, e)))
            print('  !!  %-62s %s: %s' % (name, type(e).__name__, str(e)[:70]))
            return
        passed.append((name, detail))
        print('  ok  %-62s %s' % (name, detail or ''))

    def t_missing_is_not_an_error():
        assert _read_plist('/no/such/path/at/all.plist') is None
        assert _diskutil_info('/no/such/path/at/all') is None
        return 'absent paths come back None, not an exception'

    def t_garbage_plist_is_not_an_error():
        with tempfile.NamedTemporaryFile(suffix='.plist', delete=False) as f:
            f.write(b'this is not a plist, binary or xml')
            p = f.name
        try:
            assert _read_plist(p) is None
        finally:
            os.unlink(p)
        return 'an unparseable plist comes back None, not an exception'

    def t_diskutil_on_a_plain_directory():
        # A directory that is not itself a volume's mount point -- diskutil
        # exits 0 and says "Could not find disk", which must read as "not
        # found", not as "found a volume with no reported fields".
        fake = tempfile.mkdtemp(prefix='saltpod-devprefs-selftest-')
        try:
            assert _diskutil_info(fake) is None
            return 'a non-volume directory is correctly NOT treated as a mounted volume'
        finally:
            os.rmdir(fake)

    def t_read_on_fake_mount_does_not_raise():
        fake = tempfile.mkdtemp(prefix='saltpod-devprefs-selftest-')
        try:
            r = read(fake)
            for key in ('manual_management', 'auto_sync', 'disk_use',
                        'device_identity', 'device_files'):
                assert key in r, 'read() missing key %r' % key
            for key in ('manual_management', 'auto_sync', 'disk_use'):
                e = r[key]
                assert set(e) == {'value', 'source', 'confidence'}, e
                assert e['confidence'] in _CONFIDENCES, e
            assert r['disk_use']['value'] is None, \
                'an empty directory is not a mounted volume -- disk_use must be unknown'
            return 'read() on an empty directory returns a well-shaped, honest dict'
        finally:
            os.rmdir(fake)

    def t_check_is_well_shaped_and_warns_about_finder():
        fake = tempfile.mkdtemp(prefix='saltpod-devprefs-selftest-')
        try:
            findings = check(fake)
            assert findings, 'check() returned nothing'
            for f in findings:
                assert set(f) == {'level', 'what', 'why'}, f
                assert f['level'] in _LEVELS, f
            assert any('Finder' in f['why'] for f in findings), \
                'the Finder-dialog warning is missing from check()'
            levels = [f['level'] for f in findings]
            # disk_use is unreadable on a directory that is not a real mount
            # -- NOTE: _device_identity() and the Mac-side lookups are not
            # mount-scoped (they query ioreg/preferences directly), so if a
            # real iPod happens to be attached during this run its identity
            # may still resolve and show 'ok' rather than 'warn'/'danger'.
            # What must always hold, regardless of what else is attached, is
            # that the unreadable disk_use shows up as a finding at all.
            assert any(f['what'] == 'could not determine disk use' and f['level'] == 'warn'
                       for f in findings), \
                'disk_use unknown on a fake mount must surface as a warn finding: %r' % findings
            return '%d findings, all well-shaped, Finder warning present' % len(findings)
        finally:
            os.rmdir(fake)

    def t_live_device_if_attached():
        try:
            mount = config.load()['mount']
        except SystemExit:
            return 'skipped: no data/device.json configured'
        if not os.path.isdir(os.path.join(mount, 'iPod_Control')):
            return 'skipped: nothing mounted at %s right now' % mount
        r = read(mount)
        du = r['disk_use']
        assert du['confidence'] in _CONFIDENCES, du
        findings = check(mount)
        assert findings
        return ('disk_use=%r (%s), manual_management=%r, auto_sync=%r, %d findings'
                % (du['value'], du['confidence'], r['manual_management']['value'],
                   r['auto_sync']['value'], len(findings)))

    check_('missing files/volumes read back as None, not an exception', t_missing_is_not_an_error)
    check_('a garbage plist reads back as None, not an exception', t_garbage_plist_is_not_an_error)
    check_('diskutil on a plain (non-volume) directory is "not found"', t_diskutil_on_a_plain_directory)
    check_('read() on an empty directory does not raise and is honest', t_read_on_fake_mount_does_not_raise)
    check_('check() is well-shaped and always warns about the Finder dialog',
           t_check_is_well_shaped_and_warns_about_finder)
    check_('a live pass over the real device, if one is attached', t_live_device_if_attached)

    print('\n%d passed, %d failed' % (len(passed), len(failed)))
    if failed:
        print('\nfailures:')
        for name, why in failed:
            print('  %-62s %s' % (name, why))
    # TRUE WHEN IT PASSED -- matching platform.selftest() and observe.selftest()
    # elsewhere in this package.
    return not failed


def main(argv=None):
    a = argv if argv is not None else sys.argv[1:]
    if not a or a[0] not in ('selftest', 'report'):
        print('usage: python3 -m saltpod.devprefs selftest|report')
        return 2
    if a[0] == 'selftest':
        print('saltpod.devprefs selftest   %s' % time.strftime('%Y-%m-%d %H:%M'))
        return 0 if selftest() else 1
    report()
    return 0


if __name__ == '__main__':
    sys.exit(main())
