#!/usr/bin/env bash
#
# Guided setup for saltpod, written for a Mac that has never seen it.
#
# Check Python, check ffmpeg, find the iPod's GUID if one is plugged in, write
# data/device.json, then prove the checksum code against a database the iPod
# itself carries. Running it again is safe and cheap: every satisfied step
# says "ok" and moves on. Nothing here uses sudo or writes outside this folder.
#
# Kept compatible with bash 3.2, because that is still what macOS ships.

set -euo pipefail
cd "$(dirname "$0")/.."
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}"

# --- presentation ----------------------------------------------------------
# Dress the output only when a human is watching.
BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; RESET=""
if [ -t 1 ] && [ -n "${TERM:-}" ] && [ "${TERM}" != "dumb" ] && command -v tput >/dev/null 2>&1; then
  BOLD=$(tput bold 2>/dev/null || printf ''); DIM=$(tput dim 2>/dev/null || printf '')
  RED=$(tput setaf 1 2>/dev/null || printf ''); GREEN=$(tput setaf 2 2>/dev/null || printf '')
  YELLOW=$(tput setaf 3 2>/dev/null || printf ''); RESET=$(tput sgr0 2>/dev/null || printf '')
fi
STEP_NO=0
step()    { STEP_NO=$((STEP_NO + 1)); printf '\n%s%d) %s%s\n' "$BOLD" "$STEP_NO" "$1" "$RESET"; }
explain() { printf '   %s%s%s\n' "$DIM" "$1" "$RESET"; }
ok()      { printf '   %sok%s  %s\n' "$GREEN" "$RESET" "$1"; }
info()    { printf '   %s->%s  %s\n' "$YELLOW" "$RESET" "$1"; }
fail()    { printf '\n   %s!!%s  %s\n' "$RED" "$RESET" "$1" >&2; shift; for d in "$@"; do printf '       %s\n' "$d" >&2; done; printf '\n' >&2; exit 1; }

step "Python"
explain "saltpod is standard library only; the Python that ships with macOS is enough."
PY=$(command -v python3 || true); [ -n "$PY" ] || fail "python3 not found" "install the Xcode Command Line Tools: xcode-select --install"
V=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || fail "Python $V is too old; 3.9 or newer"
ok "python3 $V at $PY"

step "ffmpeg and ffprobe"
explain "ffprobe reads tags and durations; ffmpeg converts lossless files to ALAC and streams previews."
if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then ok "$(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f1-3)"
else fail "ffmpeg/ffprobe not found" "brew install ffmpeg"; fi

step "The iPod's identity"
explain "The Classic's checksum is keyed from its FireWire GUID, which it reports as its USB serial."
GUID=$(ioreg -p IOUSB -l -w 0 2>/dev/null | awk '/iPod@/{f=1} f && /USB Serial Number/{gsub(/"/,"",$NF); print $NF; exit}')
if [ -f data/device.json ]; then ok "data/device.json exists; leaving it alone"
elif [ -n "$GUID" ] && printf '%s' "$GUID" | grep -Eq '^[0-9A-Fa-f]{16}$'; then
  printf '{\n "firewire_guid": "%s",\n "mount": "/Volumes/IPOD",\n "library_root": ""\n}\n' "$GUID" > data/device.json
  ok "iPod found on USB; wrote data/device.json with GUID $GUID"
  info "set library_root in data/device.json to the folder your music lives in"
else
  cp -n data/device.example.json data/device.json 2>/dev/null || true
  info "no iPod on USB right now; data/device.json copied from the example"
  info "plug the iPod in, then: ioreg -p IOUSB -l -w 0 | grep -A12 iPod | grep 'USB Serial'"
fi

step "Prove the checksum"
explain "If the iPod is mounted, recompute the hash58 of the database it carries and compare."
DB=/Volumes/IPOD/iPod_Control/iTunes/iTunesDB
if [ -f "$DB" ] && [ -f data/device.json ] && grep -q '"firewire_guid": "[0-9A-Fa-f]\{16\}"' data/device.json; then
  if PYTHONPATH=src "$PY" -m saltpod.cli verify "$DB" >/dev/null 2>&1; then ok "hash58 recomputed from your GUID matches what iTunes wrote"
  else fail "hash58 does not match" "the GUID in data/device.json is wrong, or this is not a Classic"; fi
else info "skipped: no mounted iPod, or no GUID yet"; fi

step "Done"
explain "Everything else happens in the page."
info "PYTHONPATH=src python3 -m saltpod.cli        # or: pip install -e . && saltpod"
info "saltpod plan   # what a sync would change     saltpod sync   # do it"
