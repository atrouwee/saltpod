# libgpod as reference for writing the Classic's iTunesDB

Researched 2026-09-27 from a fresh clone of `github.com/gtkpod/libgpod` (HEAD `7982c55`,
2012-03-31). `path:line` references below are into that tree. **Verified** = read in source
or measured on this device's DB; **inferred** = my reading, not tested on the firmware.

## Verdict

**Feasible, and the checksum is not a blocker.** The 160 GB Classic uses libgpod's
`hash58` scheme, which is an HMAC-SHA1 whose key is derived *only* from the 8-byte
FireWire GUID plus constant tables in the source. No per-device secret from iTunes is
needed. I ported it to stdlib Python (~30 lines, below) and recomputed the hash58 of the
device's own iTunes-written `iTunesDB` (backup `backups/ipod-2026-09-27/iTunesDB`) from
GUID `<device GUID>`: **exact match** with the stored bytes at `0x58`
(`6c1c327ffd9d740505f9cc399e4f0c216bd22456`). That is the strongest possible confirmation.

The per-device "HashInfo from iTunes" problem belongs to `hash72` (nano 5G, Touch 1–3,
iPhone 1–3) and `hashAB` (iOS 4-era devices; needs a closed `libhashab.so` blob). Neither
applies to a Classic per libgpod's own model table. The iTunes-written header on this
device *also* carries a hash72-format signature at `0x72` (see §2e); libgpod writes zeros
there for Classics and gtkpod has shipped that for years, so it is inferred-safe to leave
it zeroed, and it can even be re-signed from the existing DB if ever needed.

Real remaining risks, all format rather than crypto: keep the existing `mhbd` fields
(version `0x75`, ids, language) and the section layout the device already has; give new
tracks a non-zero random 64-bit `dbid`; regenerate the master playlist's mhod-52 index
lists. Nothing requires SysInfo/SysInfoExtended for our own writer.

## 1. Project status

Verified: last commit 2012-03-31; commit counts 296 (2009), 268 (2010), 48 (2011), 4 (2012).
The last tarball release was 0.8.3 (2013, SourceForge). `formulae.brew.sh/api/formula/libgpod.json`
returns 404, so there is no Homebrew formula; MacPorts still has a `libgpod` port page.
It is autotools + glib/libxml2/sqlite3/gdk-pixbuf; I did not attempt a build on Tahoe.
Not maintained; useful purely as a spec.

## 2. The checksum, precisely

### (a) Which scheme for which model — `src/itdb_device.c:1907-1983`

`itdb_device_get_checksum_type()`:
- If `SysInfoExtended` exists, its `DBVersion` decides: 0–2 none, 3 → HASH58, 4 → HASH72,
  5 → HASHAB (`:1914-1930`).
- Otherwise by generation from the model table (`:1932-1979`):
  `CLASSIC_1/2/3, NANO_3/4` → **HASH58**; `NANO_5, TOUCH_1-3, IPHONE_1-3` → HASH72;
  `IPAD_1, IPHONE_4, TOUCH_4, NANO_6` → HASHAB; everything older → NONE.
- Model table rows for 160 GB Classics (`:209-218`): `B145`/`B150` (2007, gen 1),
  `C293`/`C297` (2009, gen 3); serial suffixes `YMU/YMX/9ZS/9ZU` (`:777-782`). All → HASH58.
  USB PID 0x1261 is not in the table (libgpod never looks at USB ids); it identifies the
  model via `ModelNumStr` in SysInfo or the serial in SysInfoExtended (§3).
- The device's own header confirms it: `hashing_scheme` at `0x30` = `0x0001` = `ITDB_CHECKSUM_HASH58`
  (`src/itdb_device.h:81`).

### (b) Inputs — `src/itdb_hash58.c`

- `generate_key(fwid)` (`:148-181`): for i in 0..3 take `lcm(fwid[2i], fwid[2i+1])`, split
  hi/lo byte, emit `table1[hi], table2[hi], table1[lo], table2[lo]` → 16-byte `y`;
  `key = SHA1(fixed[18] || y)` zero-padded to 64 bytes. Only the first 8 bytes of the GUID
  are used. `table1`, `table2` (256 B each) and `fixed` (18 B) are constants at `:45-118`.
- `itdb_compute_hash()` (`:184-233`): textbook HMAC-SHA1 with that 64-byte key over the
  entire file buffer (`itdb_len` = whole DB).
- `itdb_hash58_write_hash()` (`:235-285`): before hashing, zero `db_id` (`0x18`, 8 B),
  `unk_0x32` (`0x32`, 20 B), `hash58` (`0x58`, 20 B) and set `hashing_scheme` (`0x30`) = 1;
  hash; write the 20-byte digest at `0x58`; restore `db_id` and `unk_0x32`.
  **The hash72 bytes at `0x72` are NOT zeroed for hash58** — hash over them as they are.
- Called last thing before the file is written: `src/itdb_itunesdb.c:6118-6125`
  (`itdb_device_write_checksum`), after `fix_header` sets `total_len`.

### (c) Header offsets — `struct _MhbdHeader`, `src/db-itunes-parser.h:78-108`

| off | field | device value (measured) |
|---|---|---|
| 0x04 | header_len | 244 (libgpod also writes 244, `itdb_itunesdb.c:3830`) |
| 0x0c | unknown1 | 1 (libgpod: 1 for non-sqlite devices, `:3832-3838`) |
| 0x10 | version | 0x75 (libgpod hard-codes 0x30, `:3861`) |
| 0x14 | num_children | 6 (libgpod writes 8, `:6023`) |
| 0x18 | db_id u64 | zeroed for hash |
| 0x20 / 0x22 | platform u16 (1=Mac,2=Win) / unk | 1 / 0x0263 |
| 0x24 | id_0x24 u64 | also copied into every mhit at +0x124 (`:4103`) |
| 0x30 | hashing_scheme u16 | 1 = HASH58 |
| 0x32 | unk_0x32[20] | zeroed for hash |
| 0x46 | language_id[2] | `en` |
| 0x48 | db_persistent_id u64 | |
| 0x58 | hash58[20] | populated, reproduced exactly |
| 0x6c | timezone_offset i32 | 0x1c20 = 7200 s (CEST) |
| 0x70 | unk_0x70 u16 | 3 (libgpod writes 0 for hash58 devices, `:3893-3903`) |
| 0x72 | hash72[46] | `01 00` + 44 bytes: hash72-format signature |
| 0xa0.. | audio/subtitle lang, unk, hashAB[57] at 0xab | ffff ffff, 000a 0019, zeros |

### (d) Does it need iTunes-derived hash info? **No, not for hash58.**

- hash72 (`src/itdb_hash72.c`): AES-128 with a key in the source (`:39`) over
  `SHA1(db) || 12 random bytes`, using a per-device IV + random bytes. libgpod obtains those
  by `hash_extract()`-ing them out of an iTunes-signed DB and caching them in
  `iPod_Control/Device/HashInfo` (`:110-181`, `:218-260`); without that file it fails with
  "missing HashInfo file" (`:272`). That is the known "needs an iTunes sync first" issue.
  Extraction is only attempted for HASH72 + sqlite devices (`:230-234`), i.e. never Classics.
- hashAB (`src/itdb_hashAB.c:43-66`): `dlopen`s `$libdir/libgpod/libhashab.so` and fails
  with "Unsupported checksum type" if absent (`:114-117`). Not for Classics.

### (e) The bytes at 0x70/0x72 on this device (inferred)

`0x70 = 3` and a `01 00`-prefixed 46-byte block at `0x72` match `hash_generate()`'s output
layout exactly (`itdb_hash72.c:49-66`: `sig[0]=1, sig[1]=0, 12 random, 32 AES bytes`). So
iTunes writes *both* a hash58 and a hash72 signature into a Classic's DB, with `0x70`
plausibly a bitmask of which are present. libgpod writes `0x70 = 0` and zeros at `0x72` for
Classics (`itdb_itunesdb.c:3893-3906`, and no hash72 path runs), and the Classic firmware
is known to accept gtkpod-written DBs, so the hash72 block is not checked on this
generation. Two ways to be extra safe if we ever see a rejection: (1) just keep the field
zeroed as libgpod does; (2) port `hash_extract`/`hash_generate` (AES key is public in the
source) and recover IV+random from the current iTunes-written DB once, then re-sign — the
same trick libgpod uses for HASH72 devices. Neither needs anything from Apple.

### Python port (stdlib only), verified against the device DB

```python
import hashlib, math
def _lcm(a, b): return 1 if a == 0 or b == 0 else a * b // math.gcd(a, b)
def hash58_key(fwid: bytes) -> bytes:              # TABLE1/TABLE2/FIXED from itdb_hash58.c:45-118
    y = bytearray()
    for i in range(4):
        l = _lcm(fwid[2*i], fwid[2*i+1]); hi, lo = (l >> 8) & 0xff, l & 0xff
        y += bytes([TABLE1[hi], TABLE2[hi], TABLE1[lo], TABLE2[lo]])
    return hashlib.sha1(FIXED + y).digest().ljust(64, b"\0")
def hash58(fwid: bytes, db: bytes) -> bytes:
    k = hash58_key(fwid)
    inner = hashlib.sha1(bytes(b ^ 0x36 for b in k) + db).digest()
    return hashlib.sha1(bytes(b ^ 0x5c for b in k) + inner).digest()
def sign(db: bytearray, fwid: bytes) -> None:      # db = complete file with correct sizes
    db[0x18:0x20] = bytes(8); db[0x32:0x46] = bytes(20); db[0x58:0x6c] = bytes(20)
    db[0x30:0x32] = (1).to_bytes(2, "little")      # then restore db_id/unk_0x32 and store hash
```
(Restore the saved `0x18..0x20` and `0x32..0x46` bytes after hashing, write the digest at
`0x58`.) The three tables must be copied verbatim from `src/itdb_hash58.c`; the scratch
verifier that produced the MATCH extracts them from the C file with a regex.

## 3. Where the FireWire ID comes from

Verified, `src/itdb_device.c`:
- `itdb_device_read_sysinfo()` (`:1018-1075`) parses `iPod_Control/Device/SysInfo` line by
  line as `Key: value` into a hash table, then `itdb_device_read_sysinfo_extended()`
  (`:972-1000`) parses the `SysInfoExtended` plist and, if present, overwrites `FirewireGuid`.
- `itdb_device_get_firewire_id()` (`:1845-1853`): SysInfoExtended's `FireWireGUID` if that
  file exists, else `sysinfo["FirewireGuid"]`. `itdb_device_get_hex_uuid()` (`:1892-1904`)
  strips an optional `0x` and hex-decodes into a 20-byte zero-padded buffer.
- `itdb_device_write_sysinfo()` (`:1099-1143`) simply dumps the hash table as `Key: value\n`
  lines — no validation, no signature. A hand-written SysInfo is trusted completely.
- Model detection (`:1215-1234`): serial from SysInfoExtended, else `ModelNumStr` from
  SysInfo (`get_ipod_info_from_model_number` skips a leading letter, `:2109-2120`). **With
  our empty SysInfo libgpod returns `ipod_info_table[0]` = "Invalid"/generation UNKNOWN,
  which maps to `ITDB_CHECKSUM_NONE` — it would write an unsigned DB.** To use libgpod or
  gtkpod on this iPod you would need a SysInfo containing at least
  `ModelNumStr: xB145` (or B150/C293/C297 — whichever matches the serial suffix) and
  `FirewireGuid: 0x<device GUID>`. For our own writer none of this matters: hard-code
  the GUID (and keep it verifiable via the MATCH test above).

## 4. Minimal valid iTunesDB for writing

Verified in `src/itdb_itunesdb.c`; device layout measured on the backup.

- **Sections libgpod writes** (`itdb_write_file_internal`, `:6031-6109`), in order:
  mhsd 1 (tracks), 3 (podcast playlists), 2 (playlists), 4 (albums `mhla`), 8 (artists
  `mhli`), 6 (empty `mhlt`), 10 (empty `mhlt`), 5 (mhsd5 playlists), and 9 (genius cuid)
  only if present. num_children fixed at 8 (+1).
- **Sections the device actually has** (iTunes-written, accepted): `4, 1, 3, 2, 5, 9` with
  `num_children = 6`; type 3 and 2 are byte-identical in size (120948) — iTunes writes the
  same playlist list twice. No 6/8/10. So 6/8/10 are not required by this firmware; type 4
  is present and should be kept/regenerated. Inferred recommendation: keep the device's
  order and set, byte-copy mhsd 5 and 9 unchanged, regenerate 1, 3, 2 and 4.
- **mhbd** (`mk_mhbd`, `:3819-3908`): libgpod rewrites version to 0x30 and derives the rest
  from what it read. Inferred: preserve the existing 244-byte header verbatim, patch only
  `total_len` (0x08), `num_children` (0x14) if changed, then sign. `id_0x24` is also echoed
  into every mhit at +0x124 (`:4103`) — copy it from the header.
- **mhsd/mhlt/mhlp** (`:3930-3965`, `:4905-4920`): mhsd header 96 B, `type` at +12;
  mhlt/mhlp header 92 B with count at +8.
- **mhit** (`mk_mhit`, `:3967-4118`): libgpod writes a 0x248 (584) B header; the device's
  v0x75 mhits are 624 B (first one: id 284, visible 1, 14 mhods). Fields libgpod treats as
  meaningful: `id` (+0x10, renumbered sequentially from `FIRST_IPOD_ID` at every write by
  `prepare_itdb_for_write`, `:5930`; mhip entries reference this id), `visible` (+0x14, 1),
  `filetype_marker` (+0x18, `'M4A '`/`'MP3 '` built from the extension uppercased and
  space-padded, `:7497-7505`), `time_modified` (+0x20, Mac epoch), `size`, `tracklen` ms,
  `track_nr`, `tracks`, `year`, `bitrate`, `samplerate<<16` (+0x3c), `time_added` (+0x68),
  **`dbid`** (+0x70) and `dbid2` (+0xa8), `mediatype` (+0xd0, 1 = audio),
  `album_id` (+0x120) / `artist_id` (+0x1e0) / `composer_id` (+0x1f4) which index the mhsd 4/8
  lists (`:5873-5972`), `size` again at +0x12c, and the constant `0x808080808080` at +0x134.
  `dbid` is required non-zero: `itdb_track_add` generates a random unique 64-bit one
  (`src/itdb_track.c:176-195`); all 481 device tracks have non-zero dbids and `Play Counts`
  entries are keyed by it (`itdb_itunesdb.c:2725`). Inferred: clone an existing 624-byte
  mhit as the template for new tracks rather than emitting libgpod's 584-byte layout.
- **mhods per track** (`write_mhsd_tracks`, `:5068-5285`): every non-empty string field gets
  a mhod; nothing is unconditional in code. Ids at `:168-226`: 1 title, 2 path, 3 album,
  4 artist, 5 genre, 6 filetype, 12 composer, 22 album artist, 52/53 index/jumptable,
  100 playlist position, 200–202 album-list strings. Device minimum observed on 163 tracks
  is exactly `{1,2,3,4,5,6}`; treat those as the practical floor. String mhod encoding
  (`mk_mhod`, `:4470-4530`): 24-byte header, `type`, then `1` (UTF-16), byte length, `1`,
  UTF-16LE data; body size = 40 + 2·len. Type-6 strings on device: e.g.
  `Purchased AAC audio file`; libgpod's list at `:6943` (`MPEG audio file`, `AAC audio file`, …).
- **Playlists** (`write_playlist`, `:5473-5600`): mhyp with `type` byte 1 = master at +0x14,
  64-bit playlist id at +0x1c, `podcastflag`, `sortorder`; libgpod header 108 B vs 184 B on
  the device. Mhods: title (1) then the 0x288-byte constant "long" mhod 100
  (`mk_long_mhod_id_playlist`, `:4991-5030`); the master playlist with members additionally
  gets 5 × (mhod 52 sorted index + mhod 53 jump table) for title/artist/album/genre/composer
  (`:5553-5567`; encodings `:4700-4780` and `:4782-4805`). Device master has 19 mhods
  (`1,100,102,52,53×…`), ordinary playlists `1,100,102,50,51`. Inferred: the 52/53 lists are
  what the Classic's browse menus use; regenerate them for the master playlist. Then one
  `mhip` (76 B: childcount 1, podcast flag/group, `trackid`, timestamp, groupref) + a 44-byte
  mhod 100 carrying the position per member (`write_playlist_mhips`, `:5288-5330`;
  `mk_mhip`, `:5037-5065`); `mhip.total_len` covers both. Device's first mhip has a non-zero
  `podcastgroupid` (1248) where libgpod writes 0.
- **mhsd 4** (`mk_mhla`/`mk_mhia`, `:4820-4903`): one 88-byte `mhia` per distinct album with
  `album_id`, sql id, and mhods 200 (album), 201 (artist), 202 (sort artist).

## 5. File placement and naming

Verified, `itdb_cp_get_dest_filename` (`:7263-7390`) and `itdb_musicdirs_number_by_mountpoint`
(`src/itdb_device.c:1481-1499`): count `F00, F01, …` consecutively until the first missing
directory; pick `dir_num = random(0, count)`; filename is `libgpod%06d<ext>` with a random
6-digit number, retried until unused — **not** a 4-letter name. The 4-letter `MLTO.m4a`
style is an iTunes habit, not a firmware requirement. Extension is lower-cased because
"some iPods choke on upper-case" (`:7358-7361`); files without an extension are ignored by
the iPod. `ipod_path` is the mountpoint-relative path with `/` → `:` (`itdb_cp_finalize`,
`:7508-7527`; `itdb_filename_fs2ipod`, `:7145-7148`), giving `:iPod_Control:Music:F19:MLTO.m4a`.
Nothing in libgpod caps the number of dirs at 50; it just uses what exists.

## 6. Removing a track

Verified: `itdb_track_remove` (`src/itdb_track.c:277-287`) only unlinks the mhit from the
track list; the app must call `itdb_playlist_remove_track` (`src/itdb_playlist.c:1481-1491`)
for every playlist including the master (`pl == NULL` means the MPL) and delete the file
itself (`itdb_filename_on_ipod`, `itdb_itunesdb.c:7608-7646`, resolves the `:` path; gtkpod
does the unlink). On write, `itdb_rename_files` (`:7031-7110`) renames `Play Counts` →
`Play Counts.bak` and deletes `OTGPlaylistInfo`, `iTunesShuffle`, `iTunesStats`.
`ArtworkDB` is only rewritten when built with gdk-pixbuf (`:6006-6017`), `Extras.itdb` and
the other sqlite files only for sqlite devices (`src/itdb_sqlite.c:1760, 2149`), which
Classics are not (`itdb_device.c:1392-1398`). So: rewrite `iTunesDB`, rename `Play Counts`,
delete the file, leave `ArtworkDB`/`Extras.itdb` alone (a removed track's artwork entry
just becomes orphaned; new tracks get no art unless `mhii_link` is set, `:4094-4097`).

## 7. Python bindings

Dead. `bindings/python` is SWIG (`gpod.i.in`) against `pygobject-2.0` (`configure.ac:270`)
with Python-2 `print` statements throughout `ipod.py`/`gtkpod.py`/examples and a
`mutagen` dependency; no packaging for Python 3, no wheels, last touched 2012. Not usable
on Python 3.12/Tahoe without a rewrite; the stdlib port above is the pragmatic path.

## Sources

- https://github.com/gtkpod/libgpod (clone used; HEAD 7982c5554f78dde47fd006afbeff659201d6db3d)
- https://sourceforge.net/projects/gtkpod/files/libgpod/ (0.8.3 tarball, 2013)
- https://formulae.brew.sh/api/formula/libgpod.json → 404; https://ports.macports.org/port/libgpod/ → 200
- `src/itdb_device.c:48-52, 205-218, 775-782, 972-1000, 1018-1075, 1099-1143, 1215-1234, 1392-1398, 1481-1499, 1845-1904, 1907-2003, 2109-2120`
- `src/itdb_device.h:78-84`; `src/db-itunes-parser.h:78-108`
- `src/itdb_hash58.c:45-118, 148-233, 235-285`; `src/itdb_hash72.c:39, 46-66, 110-181, 218-300`; `src/itdb_hashAB.c:43-66, 106-145`
- `src/itdb_itunesdb.c:168-226, 3819-3965, 3967-4118, 4470-4530, 4820-4920, 4991-5065, 5068-5285, 5288-5330, 5473-5600, 5604-5750, 5873-5972, 5976-6175, 6209-6270, 6943, 7031-7110, 7145-7161, 7263-7390, 7470-7530, 7608-7646`
- `src/itdb_track.c:170-197, 277-308`; `src/itdb_playlist.c:1481-1491`; `src/itdb_sqlite.c:358-391, 1760, 2149`
- Device measurements: `~/Documents/GitHub/ipod-playlists/backups/ipod-2026-09-27/iTunesDB` (903244 B, v0x75, 481 tracks, mhsd 4/1/3/2/5/9); hash58 recomputation script `research/hash58_check.py` (needs a libgpod checkout at `libgpod/` relative to cwd; usage: `python3 hash58_check.py <iTunesDB> <device GUID>`).
