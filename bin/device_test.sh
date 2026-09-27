#!/bin/bash
# The first physical write test. Narrow on purpose: one playlist renamed in
# place, everything else byte-identical, hash58 re-signed, stale hash72 zeroed.
#
#   bin/device_test.sh rehearse   # copy the backup over the device DB (identical bytes) and verify
#   bin/device_test.sh write      # write the patched DB, verify it landed, eject
#   bin/device_test.sh restore    # put the backup back, verify, eject
#
# After `write`: unplug, let the iPod reboot, open Music > Playlists and look
# for "Test Rename (saltgate)" with its one track. Empty library = bad DB ->
# plug in, Disk Mode, `restore`. Nothing here is unrecoverable while the backup
# in backups/ matches its SHA256SUMS.
set -euo pipefail
export DEVELOPER_DIR=/Library/Developer/CommandLineTools
cd "$(dirname "$0")/.."
MOUNT=/Volumes/IPOD
DEV="$MOUNT/iPod_Control/iTunes/iTunesDB"
BAK=backups/ipod-2026-09-27/iTunesDB
GUID=$(python3 -c "import json;print(json.load(open('data/device.json'))['firewire_guid'])")
PATCHED=/tmp/patched.db

[ -f "$DEV" ] || { echo "iPod not mounted at $MOUNT"; exit 1; }
(cd backups/ipod-2026-09-27 && shasum -a 256 -c SHA256SUMS --quiet) && echo "backup checksums OK"

case "${1:-}" in
  rehearse)
    cp -p "$BAK" "$DEV" && cmp "$BAK" "$DEV" && echo "rehearsal: backup written to device, byte-identical"
    env PYTHONPATH=src python3 -m saltpod.hash58 verify "$DEV" $GUID | tail -1
    ;;
  write)
    [ -f "$PATCHED" ] || env PYTHONPATH=src python3 -m saltpod.itunesdb_patch rename-playlist "$BAK" $GUID "2018 Apr1" "Test Rename (saltgate)" --out "$PATCHED"
    env PYTHONPATH=src python3 -m saltpod.hash58 verify "$PATCHED" $GUID | grep -q MATCH || { echo "patched file does not verify - refusing"; exit 1; }
    cp -p "$PATCHED" "$DEV" && sync && cmp "$PATCHED" "$DEV" && echo "patched DB written to device, byte-identical to $PATCHED"
    env PYTHONPATH=src python3 -m saltpod.hash58 verify "$DEV" $GUID | tail -1
    env PYTHONPATH=src python3 -m saltpod.itunesdb "$DEV" | grep -E "tracks,|Test Rename"
    diskutil eject "$MOUNT" && echo "ejected - unplug, let it reboot, check Music > Playlists"
    ;;
  restore)
    cp -p "$BAK" "$DEV" && sync && cmp "$BAK" "$DEV" && echo "backup restored to device, byte-identical"
    env PYTHONPATH=src python3 -m saltpod.hash58 verify "$DEV" $GUID | tail -1
    diskutil eject "$MOUNT" && echo "ejected"
    ;;
  *) sed -n '2,12p' "$0"; exit 1;;
esac
