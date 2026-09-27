# iOpenPod as a write library for the Classic — research note

*Status: measured, 2026-09-27. Everything below was read from the code at commit
`a202424` (2026-08-29) cloned to `/tmp/iopenpod`, or run against our own iTunesDB
backup. Items marked **unverified** were not tested on the device.*

## Verdict

**(b-lite): vendor the ~180-line `hash58.py` (stdlib-only, MIT, BSD-3 provenance) and write our
own patch-style playlist writer; keep iOpenPod's writer as the reference spec, not as code.**
iOpenPod's parser and writer are cleanly separable from Qt and technically work as a library
(proven: parse + rebuild + re-sign of our 0x75 DB in 0.11 s), but the package needs Python 3.11+
(system is 3.9.6) plus Pillow/numpy/pycryptodome/mutagen, and its writer *regenerates* the whole
database with side-effects we do not want for playlist-only edits (artwork flag reset, Store
metadata dropped, smart playlists re-evaluated, master sort order changed). The single fact that
unblocks us: **its hash58 recomputes our DB's stored signature exactly with GUID
`<device GUID>`** — no SysInfo needed.

## 1. Repository

- Upstream: <https://github.com/TheRealSavi/iOpenPod> (author John Gibbons, MIT). PyPI `iopenpod`
  1.68.1, `requires-python >=3.11`, 25 releases. 392 stars, 40 forks, created 2025-03-01.
- Cloned to `/tmp/iopenpod` (394 commits, first 2025-02-28, last 2026-08-29). `BlackJocker1995/iOpenPod`
  from the search results is a fork, not the source.
- Qt-free CLI fork `TristonYoder/iOpenPodCLI` (cloned to `/tmp/iopenpodcli`): last commit 2026-07-05,
  still on the old flat layout (`iTunesDB_Writer/` etc.) and still lists `pyqt6` in `pyproject.toml`.
  Not a usable shortcut.

## 2. Architecture

Package layout `src/iopenpod/`: `itunesdb_shared/` (field tables), `itunesdb_parser/`,
`itunesdb_writer/`, `device/` (identity, checksum enum, write guards), `sync/` (orchestration),
`artworkdb_*`, `sqlitedb_writer/` (Nano 6G/7G only), `gui/` (PyQt6), `application/` (Qt runtime).
`scripts/check_architecture.py` enforces that `gui` never imports `sync`/`device` directly.

Qt-free import test under Homebrew Python 3.11 (`/opt/homebrew/bin/python3.11`, no third-party
packages installed): `itunesdb_shared`, `itunesdb_parser`, `itunesdb_writer`, `device` all import
with **zero** third-party modules loaded. `sync._db_io`, `sync.database_commit`, `sync.quick_writes`
fail on `PIL` (pulled in by `sync/__init__.py:57` → `sync/photos.py:19`); `artworkdb_writer` needs
numpy. With a venv of pillow+numpy+pycryptodome+mutagen the whole `sync` layer loads without Qt.
Caveat: `itunesdb_writer/__init__.py:22` eagerly imports `iopenpod.device`, so `hash58` cannot be
imported alone from the package — but it runs stand-alone once its two `mhbd_defs` imports are
replaced by four constants (tested).

Declared runtime deps (`pyproject.toml`): pyqt6, numpy, pillow, pycryptodome, mutagen, pyusb,
libusb-package, wasmtime, certifi, feedparser, requests, packaging, tqdm, tzdata, python-dateutil.
Only pycryptodome (HASH72 AES) and — indirectly — pillow/numpy matter for the DB write path.

Sizes: parser 3.4k lines, shared 3.4k, writer 6.1k (`mhbd_writer.py` 1588, `mhyp_writer.py` 641,
`mhod_writer.py` 589, `mhit_writer.py` 511, `hash72.py` 496, `mhod_spl_writer.py` 448,
`mhod52_writer.py` 344, `hashab.py` 290, `hash58.py` 279).

## 3. The checksum

- Enum and model mapping: `device/checksum.py:6-21` — HASH58 = iPod Classic (all gens), Nano 3G/4G;
  HASH72 = Nano 5G; HASHAB = Nano 6G/7G (WASM white-box AES); NONE = pre-2007.
  Classic capabilities: `device/capabilities.py:267-333` (`checksum=HASH58`, `db_version=0x30`,
  64 MiB DB cap). USB PID 0x1261 → "iPod Classic" (`device/models.py:497,528-533`).
- HASH58 = HMAC-SHA1 over the whole file with a 64-byte key derived from the 8-byte FireWire GUID
  (LCM of byte pairs → AES S-box/inverse-S-box lookups → SHA1 with 18 fixed bytes):
  `itunesdb_writer/hash58.py:127-183`. Before hashing it zeroes `db_id` (0x18, 8 B), `unk0x32`
  (0x32, 20 B) and `hash58` (0x58, 20 B) and sets `hashing_scheme` (0x30) = 1: `hash58.py:186-231`.
  Offsets: `itunesdb_shared/mhbd_defs.py:16-21`.
- **Measured on our DB** (`backups/ipod-2026-09-27/iTunesDB`, identical to the live one on
  `/Volumes/IPOD`): version 0x75, `hashing_scheme=1`, `hash_type_indicator=3`, hash72 present
  (marker `01 00`). Recomputed hash58 with `<device GUID>` = stored
  `6c1c327ffd9d740505f9cc399e4f0c216bd22456`. Exact match; no other bytes touched.
- On a Classic iOpenPod writes **hash72 first, then hash58** (`mhbd_writer.py:1329-1364`), because
  hash58 covers the hash72 bytes. hash72 = SHA1 (db_id, hash58, hash72 zeroed; `unk0x32` NOT zeroed)
  then AES-128-CBC of (sha1 + 12-byte rndpart) with a fixed key and an IV recovered from the
  *existing* iTunes-written DB (`hash72.py:168-236, 362-400`). This needs pycryptodome. It succeeded
  on our DB (IV/rndpart extracted). **Unverified:** whether the Classic firmware checks hash72 at
  all — libgpod only ever wrote hash58 for Classics, so a stale hash72 is probably tolerated, but
  we did not test it.
- GUID source order: `get_firewire_id()` `device/info.py:1056-1145` — caller-supplied `known_guid`,
  the in-process DeviceInfo store, a virtual-iPod `iPodInfo.json`, `SysInfo` `FirewireGuid`,
  `SysInfoExtended` `FireWireGUID`. On macOS the scanner sets `firewire_guid` from the ioreg
  "USB Serial Number" when it is 16 hex chars (`device/scanner.py:504-515`).
- **Empty SysInfo, no SysInfoExtended:** `detect_checksum_type()` (`info.py:983-1053`) returns
  `UNKNOWN` unless the device store already identified the model, and the writer then refuses to
  write (`mhbd_writer.py:1401-1402`). Workaround exists and is explicit: `write_itunesdb(...,
  force_checksum=ChecksumType.HASH58, firewire_id=bytes.fromhex(GUID))` (`mhbd_writer.py:869-871`,
  docstring says "for devices with empty SysInfo"). The GUI path relies on the ioreg USB serial and
  PID 0x1261, so it should identify the device too (open issues #215/#216 show identification is
  still the flakiest part of the app).

## 4. Write path

Entry points: `sync/quick_writes.py:51` `write_cached_itunesdb()` (GUI edits without a full sync)
→ `sync/database_commit.py:49` `write_database_commit()` → `sync/_db_io.py:305` `write_database()`
→ `itunesdb_writer/mhbd_writer.py:864` `write_itunesdb()`.

- **Whole rewrite, never a patch.** `write_mhbd()` (`mhbd_writer.py:258`) serialises every dataset
  from `TrackInfo`/`PlaylistInfo` objects: mhsd 1 (tracks), 3 and 2 (playlists; 3 mirrors 2), 4
  (albums), 8 (artists), 6/10 (empty Genius stubs), 5 (smart/category), then verbatim copies of
  mhsd types it does not generate (7, 9) from the old file (`mhbd_writer.py:200-252`). Our DB's
  6 datasets (4,1,3,2,5,9) became 9.
- **Files written on a Classic:** `iTunesDB` only (plus `iTunesDB.backup` beside it), via
  sibling temp file + `durable_replace` (`mhbd_writer.py:1454-1500`); `ArtworkDB` + `.ithmb` only
  when `pc_file_paths` are supplied; `iTunesPrefs`/`iTunesPrefs.plist` rewritten to set manual
  sync and totals (`database_commit.py:162-213`, `sync/itunes_prefs.py`); `Play Counts` is read,
  merged into the tracks, then deleted (`_db_io.py:31-143, 467-516`). `Extras.itdb` is untouched
  on Classics (only the Nano 6G/7G SQLite writer creates one: `sqlitedb_writer/extras_writer.py`).
  After the write it re-parses the DB and checks every `Location` exists (`_db_io.py:216-297`).
- **Audio file names:** `Music/Fxx/` chosen round-robin over `capabilities.music_dirs`
  (`sync_executor.py:4097-4124`); filename = 4 random `[A-Z0-9]` + extension, collision-checked
  (`sync_executor.py:4126-4149`). Location strings via `ipod_location_from_file_path()`
  (`sync/ipod_track_paths.py:139`).
- **IDs:** 32-bit `track_id` renumbered sequentially on every write, starting after the album/
  artist/composer ID block (`mhbd_writer.py:384-405`, `mhlt_writer.py:21-52`) — our tracks went
  284..1245 → 672..1152. Playlists reference tracks by 64-bit `db_track_id` and are remapped
  (`mhbd_writer.py:407-425`); `db_track_id` is `random.getrandbits(64)` if 0 (`mhit_writer.py:43`).
- **Master playlist:** always regenerated first in mhsd 2 and 3 with all track IDs and the type
  52/53 library-index mhods (`mhlp_writer.py:114-160`); name/ID preserved from the old DB.
  Its `sort_order` is hardcoded to 5 (`mhyp_writer.py:637`); iTunes wrote 1 on ours.
- **Removal:** planned orphan media files are `durable_unlink`ed under the write guard
  (`sync_executor.py:2335-2398`); removing a track is just omitting it from the rewrite.
- **db_version:** `max(existing header version, capabilities.db_version)` (`mhbd_writer.py:367-379`),
  so our 0x75 is preserved (default for a new DB is 0x4F, `mhbd_writer.py:129`). mhit header is
  0x270 for anything ≥ 0x2E (`mhit_defs.py:32-44`), matching ours.

Round-trip measured in memory (parse → `write_mhbd` → hash72+hash58 → reparse, 0.11 s total,
903,244 → 914,074 bytes): 481/481 tracks and 22/22/6 playlists back, all titles/artists/albums/
locations/`db_track_id`s identical, smart playlists identical. Divergences: mhod types 37/43/44
(Content Provider, Purchase Account, Purchaser Name) dropped from all tracks and all Store IDs and
unknown mhit fields zeroed; type 22 (Album Artist) added to every track; `has_artwork` 1 → 2 on
every track because the writer derives it from `artwork_count` only (`mhit_writer.py:474`,
`_track_conversion.py:121`) — consistent with open issue #178 (no cover art on Classic 7G); mhip
persistent IDs/timestamps zeroed; the "90's Music" smart playlist grew 3 → 6 items because
`live_update` playlists are re-evaluated (`_playlist_builder.py:511, 615`). Timestamps shifted by
−3600 s in my run — almost certainly because I bypassed `write_itunesdb`'s device-time context
(`itunesdb_shared/device_time.py:156-170`); **unverified**.

## 5. Format support

- Writes version 0x75 when the existing DB has it (see above); reads/writes the 0xF4 mhbd header
  with all the 0x75-era fields (`mhbd_defs.py:23-57`).
- Strings: parser honours the mhod encoding byte (2 = UTF-8, else UTF-16LE; `mhod_parser.py:113-126`);
  writer always emits UTF-16LE with encoding=1 (`mhod_writer.py:192-231`), UTF-8 only for podcast
  URL types 15/16. Matches our device.
- Transcoding: FLAC/WAV/AIFF → ALAC (or AAC) via FFmpeg (`sync/_formats.py:27-29`,
  `sync/transcoder.py:546`); MP3/AAC/ALAC copied. Chromaprint fingerprinting for matching.

## 6. Maturity and risk

- Release cadence: 25 PyPI/GitHub releases Jun–Aug 2026 (v1.0.56 → v1.68.1 on 2026-08-10); last
  push 2026-09-27 (README). 218 issues in 7 months, 36 open. Test suite 190 files.
- macOS 26.3 Classic bug: issue #1 (2026-02-24, macOS 26.3, Classic 7G, "Error parsing iTunesDB")
  was unimplemented mhod fields in the parser; fixed and closed 2026-03-02. Our 0x75 DB parses.
- Wipe/corruption history: #4 (Mar 2026, macOS, Classic 7G library wiped, device renamed
  "Audiobooks" — smart playlists written with master flag; fixed), #134 (Jun, Mini 2G empty after
  sync; tag data), #149 (Jul, Classic 6G unwritable until restore on Linux; filesystem layer
  rewritten), #175 **open** (Nano 3G: plays fine but Finder/iTunes say "could not be read"),
  #193 **open** (Classic 7G unreadable by a Volvo head unit after sync, author links it to #175),
  #178 **open** (no album art on Classic 7G despite byte-level diffs), #215/#216 **open** (Classic
  identification failures). No "bricked" reports; every case recovered via iTunes restore.
- Practical risk for us: the app is moving fast (design docs `docs/research/*.md` are dated
  Aug 2026) and every write is a full regeneration whose fidelity to iTunes output is still being
  chased (#175/#193 suggest something iTunes/Finder validate is not yet right).

## 7. Licensing

MIT, `LICENSE` "Copyright (c) 2025 John Gibbons". Vendoring any file requires keeping that
copyright + permission notice with the copied code. `hash58.py` is a port of libgpod's
`itdb_hash58.c` (Christophe Fergeau 2007, based on wtbw's proof of concept), which is
**BSD-3-Clause**, not LGPL — so a vendored `hash58.py` should carry both notices; no copyleft.
`hashab` (Nano 6/7) embeds a WASM module from `dstaley/hashab`; irrelevant to us.

## 8. Recommendation detail

(a) *Dependency*: works in a Python 3.11 venv without Qt (pillow, numpy, pycryptodome, mutagen).
Call `iopenpod.itunesdb_writer.write_itunesdb(mount, tracks, playlists=..., force_checksum=HASH58,
firewire_id=bytes.fromhex("<device GUID>"))`. Rejected as the default because it breaks the
stdlib-only policy, needs a non-system Python, and the rewrite side-effects above hit exactly the
things we care about on an iTunes-curated library (artwork flag, Store mhods, smart playlists).

(b) *Port*: the full writer is ~7k lines incl. field tables; not worth porting. Port only:
`itunesdb_writer/hash58.py` (functions `_generate_key`, `compute_hash58`, `write_hash58` + the
three tables; ~180 lines, stdlib) and, if hash72 turns out to be checked, `hash72.py`
`_compute_itunesdb_sha1`/`_hash_generate`/`_hash_extract` with AES-128-CBC done via
`openssl enc -aes-128-cbc -K … -iv … -nopad` (allowed as an external tool like ffmpeg) — ~120 lines.
Build the playlist writer ourselves as an in-place patch of the existing 0x75 file (insert/replace
mhyp chunks in mhsd 2 and 3, fix chunk and total lengths, re-sign), using `itunesdb_shared/
mhyp_defs.py`, `mhip_defs.py`, `mhod_defs.py` and `docs/research/ipod-playlist-datasets.md` as
the spec. Adding tracks later needs a 0x270-byte mhit + mhods (`mhit_defs.py`, `mhit_writer.py`).

First physical experiment (cheap, reversible): rename one playlist title in place (same length),
re-sign with hash58 only, copy to the device, check the Classic shows the new name. That proves
the signature path and answers the hash72 question before any structural writes.

## Sources

- https://github.com/TheRealSavi/iOpenPod — repo, issues #1 #4 #134 #149 #175 #178 #193 #215 #216
- https://pypi.org/pypi/iopenpod/json — 1.68.1, `>=3.11`
- https://github.com/TristonYoder/iOpenPodCLI — CLI fork
- https://raw.githubusercontent.com/gtkpod/libgpod/master/src/itdb_hash58.c — BSD-3 header
- /tmp/iopenpod/pyproject.toml (deps), LICENSE
- /tmp/iopenpod/src/iopenpod/device/checksum.py:6-40; capabilities.py:267-333; models.py:497,528-533
- /tmp/iopenpod/src/iopenpod/device/info.py:983-1053 (detect_checksum_type), 1056-1145 (get_firewire_id)
- /tmp/iopenpod/src/iopenpod/device/scanner.py:504-515 (macOS USB serial → GUID)
- /tmp/iopenpod/src/iopenpod/itunesdb_writer/hash58.py:127-231; hash72.py:168-236,362-400
- /tmp/iopenpod/src/iopenpod/itunesdb_writer/mhbd_writer.py:129,200-252,258,367-425,864-921,1295-1402,1454-1500
- /tmp/iopenpod/src/iopenpod/itunesdb_writer/mhit_writer.py:43,474; mhyp_writer.py:637; mhlt_writer.py:21-52; mhlp_writer.py:114-160; mhod_writer.py:192-231
- /tmp/iopenpod/src/iopenpod/itunesdb_shared/mhbd_defs.py:16-57; mhit_defs.py:32-44; constants.py:175,190,196-197
- /tmp/iopenpod/src/iopenpod/itunesdb_parser/mhod_parser.py:113-126
- /tmp/iopenpod/src/iopenpod/sync/_db_io.py:31-143,216-297,305-465,467-516; database_commit.py:49-213; quick_writes.py:51-113; itunes_prefs.py:1-25
- /tmp/iopenpod/src/iopenpod/sync/sync_executor.py:2335-2398,4097-4149; _playlist_builder.py:192-216,511,615; _track_conversion.py:121; _formats.py:27-29; transcoder.py:546; __init__.py:57; photos.py:19
- /tmp/iopenpod/scripts/check_architecture.py:1-60
- Test scripts and outputs: scratchpad `hash58_check.py`, `roundtrip.py`, `roundtrip_iTunesDB` (session scratch dir)
- Our data: ~/Documents/GitHub/ipod-playlists/backups/ipod-2026-09-27/iTunesDB (== /Volumes/IPOD/iPod_Control/iTunes/iTunesDB); /Volumes/IPOD/iPod_Control/Device/SysInfo is 0 bytes
