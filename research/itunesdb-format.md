# iTunesDB binary format — spec view for writing to an iPod Classic (PID 0x1261)

Status: **research, from primary format documentation plus measurements of our own device**; nothing here is a settled
implementation spec. Written 2026-09-27 as the independent cross-check against the libgpod and iOpenPod source reads.

## Sources and tags

| Tag | Source |
|---|---|
| **W** | ipodlinux wiki, *ITunesDB/iTunesDB File*, final revision (last modified 13 Nov 2017), static mirror <http://www.ipodlinux.org/ITunesDB/iTunesDB_File.html>; identical text in Wayback <https://web.archive.org/web/20090926145427/http://ipodlinux.org/wiki/ITunesDB/iTunesDB_File> and the single-page 2009 snapshot <https://web.archive.org/web/20090223143020/http://ipodlinux.org/wiki/ITunesDB>. The wiki documents versions only up to 0x1A (iTunes 7.5). |
| **W-basic / W-art / W-pc / W-misc** | Sub-pages: <https://web.archive.org/web/20091227183536/http://www.ipodlinux.org/wiki/ITunesDB/Basic_Information>, <https://web.archive.org/web/20081204101212/http://ipodlinux.org/wiki/ITunesDB/Artwork_Database>, <https://web.archive.org/web/20081204101310/http://ipodlinux.org/wiki/ITunesDB/Play_Counts_File>, <https://web.archive.org/web/20090615051649/http://ipodlinux.org/wiki/ITunesDB/Misc._Files>. No "Hash" sub-page ever existed (checked the Wayback CDX index for `ipodlinux.org/wiki/*`). |
| **L** | libgpod 0.8.x (GitHub mirror fadingred/libgpod): `src/itdb_itunesdb.c` (`mk_mhbd`, `mk_mhit`, `mk_mhip`, `mk_mhod`, write order), `src/itdb_hash58.c`, `src/itdb_hash72.c`, `src/itdb_device.c`, `NEWS`, `README.overview`, `README.SysInfo`. Used only as *documentation* (comments, header layout, hash procedure); the C-code read is the other researcher's. |
| **F** | foobar2000 iPod manager (reupen/ipod_manager) `foo_dop/writer_itunesdb.cpp` — a second, independent writer that targets iTunes-10-era DBs. |
| **D** | Measurements on our device's DB (`backups/ipod-2026-09-27/iTunesDB`, v0x75, 481 tracks, 22 playlists) made in this session with a throw-away Python dump. |
| flashpod | <https://flashpod.dev/> (1st/2nd-gen DB size cliff). |

Where W and L disagree it is said inline; D usually settles it.

## 1. `mhbd` — database header

Header length is version-dependent: 0x68 for version ≤ 0x15, 0xBC for ≥ 0x17 (W), **0xF4 on D (v0x75) and 0xF4 is also what L writes** (`mk_mhbd` ends with 57 bytes of hashAB + 16 "dummy" bytes). All integers little-endian (W-basic).

| Off | Size | Field | Notes / source |
|---|---|---|---|
| 0x00 | 4 | `mhbd` | |
| 0x04 | 4 | header length | see above |
| 0x08 | 4 | total length | = file size (W) |
| 0x0C | 4 | 1 | W "always 1". F writes it as a *format* byte (1 = plain iTunesDB, 2 = zlib-compressed iTunesCDB) + 3 bytes; D = 1 |
| 0x10 | 4 | version | see version table below. D = 0x75 |
| 0x14 | 4 | number of `mhsd` children | D = 6 |
| 0x18 | 8 | database id | W: "not checked by the iPod". **Zeroed while hashing** (L, F). D nonzero |
| 0x20 | 2 | platform | L: 1 = Mac OS X, 2 = Windows. W says "always 2" at offset 32 (its authors were on Windows). D = 1 |
| 0x22 | 2 | unknown (`unk_0x22`) | L copies it through; D = 0x0263 |
| 0x24 | 8 | `id_0x24` | L "unknown id", **repeated in every `mhit` at +0x124 and in non-master `mhyp` at +0x3C (D)**. W lists an 8-byte unknown at 38 — W's offsets 32/38 are off; D matches L |
| 0x2C | 4 | 0 | |
| 0x30 | 2 | hashing scheme | 0 none, 1 = hash58, 2 = hash72, 3 = hashAB (L writes it via the hash routine; F calls it "candy_version": 1 for Classic/Nano 3G, 2 for hash72 devices, 3 for hashAB). W: "must be 0x01 for Nano 3G and Classic". **D = 1** |
| 0x32 | 20 | `unk_0x32` | zeroed for the hash58 computation (L). D = zeros |
| 0x46 | 2 | language | ASCII, e.g. `en` (W says offset 70). D = `en` |
| 0x48 | 8 | library persistent id | matches iTunes' "Library Persistent ID" (W). D nonzero |
| 0x50 | 4 | `unk_0x50` | L: seen 5 (Nano 3G), 1 (iPod Color). D = 1 |
| 0x54 | 4 | `unk_0x54` | L: seen 0x4D / 0x0F. D = 0x9F |
| 0x58 | 20 | **hash58** | W "obscure hash at 88". D nonzero |
| 0x6C | 4 | timezone offset, seconds | L. D = 7200 (CEST) |
| 0x70 | 2 | signature flags | L writes 2 for hash72 devices, 4 for hashAB, **0 for Classic**; F writes bit flags (Classic gets hash58+hash72 bits). D = 3. Since L's Classic DBs carry 0 and work, treat as advisory |
| 0x72 | 46 | **hash72** | starts `01 00` (L `hash_generate`). D nonzero; L leaves it zero on a Classic |
| 0xA0 | 2+2 | audio language, subtitle language | L. D = 0xFFFF, 0xFFFF |
| 0xA4 | 2,2,2,1 | `unk_0xa4/a6/a8`, 0 | D = 0x19, 0x0A, 0, 0 |
| 0xAB | 57 | hashAB | zero on non-iOS devices (L). D zeros |
| 0xE4 | 16 | zero | L "dummy space" |

**Version values** (W + L comment in `mk_mhbd`): 0x09 iTunes 4.2 · 0x0A 4.5 · 0x0B 4.7 · 0x0C 4.71/4.8 · 0x0D 4.9 · 0x0E 5 · 0x0F 6 · 0x11 6.0.2 · 0x12 6.0.5 · 0x13 7.0 · 0x14 7.1 · 0x15 7.2 · 0x17 7.3 · 0x18 7.3.1 · 0x19 7.4 · 0x1A 7.5 · 0x28 8.2.1 · 0x2A 9.0.1 · 0x2E 9.1 · 0x30 9.2 (L writes this) · 0x37 10.1 (F writes this) · **0x75 = iTunes 12.x (D)**.
**Which to write:** L's comment warns "newer ipods won't work if the library version number is too old", so 0x13/0x19 is *less* safe, not more. Two proven-on-Classic combinations exist: L's (0x30 with L-sized chunks) and iTunes' own (0x75 with D-sized chunks). Recommendation: **keep 0x75 and clone every unknown header field from the existing DB** (0x22, 0x24, 0x50, 0x54, 0xA0–0xA9, timezone, language, library id); regenerate only counts, sizes and the hash.

### Checksum: what the Classic checks and how to compute it

- Which hash: L maps generation `CLASSIC_3` (the 2009 160 GB, PID 0x1261 — L's model table lists C293/C297 as CLASSIC_3) to **hash58 only**; hash72 is for Nano 5G/iPhone OS 2–3, hashAB for iOS 4-era devices (`itdb_device_get_checksum_type`, README.overview feature matrix: "iPod Classic: hash58 yes, hash72 no"). With `SysInfoExtended` present L instead reads its `DBVersion` key (3 → hash58, 4 → hash72, 5 → hashAB).
- Consequence of a bad/missing hash (L NEWS 0.6.0): "the iPod won't show any track (ie it will look empty)". README.SysInfo: "the iPod won't recognize what libgpod wrote to it and will behave as if it's empty". Not a crash — an empty library.
- **hash58 procedure** (L `itdb_hash58_write_hash`, F does the same): (1) set u16 @0x30 = 1; (2) zero @0x18 (8), @0x32 (20), @0x58 (20); (3) key = `generate_key(firewire_id)` (fixed tables + SHA-1, in `itdb_hash58.c`); (4) HMAC-SHA1(key, **entire file**) → 20 bytes at 0x58; (5) restore 0x18 and 0x32. F additionally zeroes the hash72/hashAB areas while hashing and patches the db id at 0x18 back in afterwards — equivalent, since it writes those hashes in the same pass.
- **The key input** is the 16-hex-digit "FirewireGuid". L reads it from `iPod_Control/Device/SysInfo` line `FirewireGuid: 0x<16 hex>`; README.SysInfo says it equals the device's USB serial string (`lsusb -v | grep Serial`, F also requires exactly 16 chars). **D: `Device/SysInfo` is 0 bytes and there is no `SysInfoExtended` or `HashInfo`**; `ioreg -p IOUSB` reports the iPod (idProduct 4705 = 0x1261) with `USB Serial Number = <device GUID>`, which is the value to use.
- **hash72** (L `itdb_hash72.c`): SHA-1 over the whole file with @0x18, @0x58 and @0x72 zeroed; signature = `01 00` + 12 random bytes + AES-128-CBC (fixed key, per-device IV) of sha1‖random → 46 bytes at 0x72. The IV/random pair cannot be derived; L recovers it from an existing valid hash72 (`hash_extract`) into `Device/HashInfo`. Only needed if we want to reproduce iTunes' belt-and-braces header; L's Classic DBs have hash72 = 0 and 0x70 = 0.

## 2. `mhsd` sections

Header: `mhsd`, header length (0x60 on D), total length, type at +0x0C; rest zero. Child list objects: `mhlt`/`mhlp`/`mhla` carry the *count* at +8 instead of a total length (W).

| Type | Content | Required? | Source |
|---|---|---|---|
| 1 | `mhlt` → `mhit` tracks | yes — L's parser aborts "no mhsd type 1" | W, L |
| 2 | `mhlp` → normal playlists | yes (L: "no mhsd type 2 or type 3") | W, L |
| 3 | `mhlp` → podcast-style playlist list | optional; if podcasts are used it must lie **between type 1 and type 2** for them to list (W). On D it is byte-identical to type 2 (no podcast playlist) | W, D |
| 4 | `mhla` → `mhia` album items (first seen iTunes 7.1) | not documented as required; L always writes it. D has 245 items | W, L, D |
| 5 | `mhlp` of "mhsd5" playlists: on D six empty smart lists *Music, Videos, Movies, TV Shows, Audiobooks, Rentals* with mhod 50/51 and **0 mhips**; L writes it always, forces mhip count 0, and stores a type at `mhyp`+0x50/0x52 | not documented as required | W (first seen 7.3), L, D |
| 6, 10 | L writes an *empty `mhlt`* "whatever it is" | no | L |
| 8 | artists list (L `write_mhsd_artists`) | no | L |
| 9 | Genius CUID: **no chunk inside — 32 ASCII hex chars** (`6e1173ef…de0b` on D); L writes it only if it has one | no | L, D |

Order on D: 4, 1, 3, 2, 5, 9. L writes 1, 3, 2, 4, 8, 6, 10, 5, 9. W: "order is not guaranteed" except the type-3 rule. Nothing documents what a Classic does with a *missing* 4/5/9; both writers include 4 and 5, so the safe minimum is 1, 3, 2, 4, 5 with the count at `mhbd`+0x14 matching exactly.

## 3. `mhit` — track item

Header length by version (W): 0x9C (≤0x0B), 0xF4 (≥0x0C), 0x148 (0x12–0x13), 0x184 (≥0x14). **L writes 0x248; D (v0x75) is 0x270.** Bytes past 0x184 are undocumented; on D they hold 64-bit copies of gapless data, purchase metadata and `id_0x24` (+0x124). Offsets below are W's; the D column is the first track on the device (a purchased AAC).

| Off | Sz | Field | Mandatory for play/menu | Notes | D |
|---|---|---|---|---|---|
| 0x0C | 4 | mhod count | yes | | 14 |
| 0x10 | 4 | **id** | yes | u32, unique, referenced by `mhip` | 0x11C |
| 0x14 | 4 | **visible** | yes | 1 = shown; anything else hides the track (W) | 1 |
| 0x18 | 4 | filetype fourcc | yes on 5G+ | `MP3 `, `M4A `, `M4P `, `AAC ` as a LE u32 of the ASCII (W); 0 on ≤4G | `M4A ` |
| 0x1C | 1,1 | type1, type2 | — | CBR MP3 0/1, VBR MP3 1/1, AAC 0/0 (W). D: MP3 → (0,1), M4A → (0,0) | 0,0 |
| 0x1E | 1 | compilation | — | | 0 |
| 0x1F | 1 | rating | — | stars × 20 | 0 |
| 0x20 | 4 | last modified | — | Mac time (s since 1904) | |
| 0x24 | 4 | **size** bytes | yes | | 11 429 494 |
| 0x28 | 4 | **length** ms | yes | | 329 320 |
| 0x2C | 4 | track number | menu | | 1 |
| 0x30 | 4 | total tracks | — | | 1 |
| 0x34 | 4 | year | — | | 2012 |
| 0x38 | 4 | bitrate | display | kbps | 256 |
| 0x3C | 4 | **sample rate × 0x10000** | yes | | 44100<<16 |
| 0x40..0x4C | 4 each | volume, start time, stop time, soundcheck | — | 0 = default | 0 |
| 0x50, 0x54 | 4 | play count, play count 2 | — | iPod does not update these; see Play Counts | 0 |
| 0x58 | 4 | last played | — | | 0 |
| 0x5C, 0x60 | 4 | disc number, total discs | — | | 1,1 |
| 0x64 | 4 | userid | — | store DRM only | 0 |
| 0x68 | 4 | date added | — | Mac time | set |
| 0x6C | 4 | bookmark time | — | | 0 |
| 0x70 | 8 | **dbid** | yes | u64; links to ArtworkDB `mhii`; copied into `mhip`+0x2C on D | set |
| 0x78 | 1 | checked | — | W: 0 = checked | 0 |
| 0x79 | 1 | application rating | — | | 0 |
| 0x7A | 2 | BPM | — | | 0 |
| 0x7C | 2 | artwork count | artwork only | must be ≥1 for artwork to show (W) | 0 |
| 0x7E | 2 | unk9 | — | 0xFFFF for MP3/AAC, 0 WAV | 0xFFFF |
| 0x80 | 4 | artwork size | — | | 0 |
| 0x88 | 4 | sample rate 2 | — | IEEE float | 44100.0 |
| 0x8C | 4 | date released | — | | 0 |
| 0x90 | 2,2 | unk14/1, unk14/2 | — | 0x0C MP3, 0x33 AAC; then 0/1 | 0x33, 1 |
| 0x94 | 4 | unk15 | — | DRM-related | 0xFFFFFFFF |
| 0x9C, 0xA0 | 4 | skip count, last skipped | — | | 0 |
| 0xA4 | 1 | **has_artwork** | — | **0x02 = no artwork, 0x01 = has artwork** (W). D: 479×1, 2×2 | 1 |
| 0xA5 | 1 | skip when shuffling | — | | 0 |
| 0xA6 | 1 | remember playback position | — | | 0 |
| 0xA7 | 1 | flag4 / podcast flag | consistency | must be 0 for non-podcasts, else iTunes may delete the track on sync (W) | 0 |
| 0xA8 | 8 | dbid2 | — | equals dbid on D | = dbid |
| 0xB0 | 1,1,1,1 | lyrics flag, movie file flag, played_mark, unk17 | — | played_mark 2 = "unplayed" bullet for podcasts | 0,0,2,0 |
| 0xB8 | 4 | pregap | gapless | samples | 2112 |
| 0xBC | 8 | sample count | gapless | | set |
| 0xC8 | 4 | postgap | gapless | | 316 |
| 0xCC | 4 | unk27 | — | 1 for MP3-encoder files | 1 |
| 0xD0 | 4 | **mediatype** | yes | 0 both menus, **1 audio**, 2 video, 4 podcast, 6 video podcast, 8 audiobook, 0x20 music video, 0x40 TV show, 0x60 TV show + music (W) | 1 |
| 0xD4, 0xD8 | 4 | season, episode | — | TV only | 0 |
| 0xF8 | 4 | gapless data | gapless MP3 | bytes from first sync frame to 8th-last frame; 0 disables gapless for MP3 (W) | 0 |
| 0x100 | 2,2 | gapless track flag, gapless album flag | — | | 1, 0 |
| 0x104 | 20 | unk39 | — | "a hash, not checked" (W) | 0 |
| 0x120 | 4 | (undocumented) | — | D: 0x27, equal to `mhia`+0x10 of the track's album item — probably the album-list link (W's 0x13A "AlbumID" is the older layout) | 0x27 |
| 0x124 | 8 | `id_0x24` copy | — | L, D | |
| 0x160 | 4 | mhii link | artwork | nonzero → artwork looked up by this ArtworkDB `mhii` id instead of dbid (W) | 0x64 on D |

**Menu placement**: `mediatype` decides Music vs Videos vs Podcasts (W's table above); `visible ≠ 1` hides the track (W); `type1/type2` do not hide anything documented. A track with `mediatype = 8` still does not show under Audiobooks unless the file is `.m4b`/`.aa` (W).
**Mandatory mhods** (W): at minimum a Location (type 2); Filetype (6) "always present, not totally necessary"; a Title (1) for the menu.

## 4. `mhod` — string objects

Types (W): 1 title · **2 location** (`:iPod_Control:Music:F00:XXXX.m4a`, colons; must be < 112 bytes / 56 UTF-16 chars or the song is skipped) · 3 album · 4 artist · 5 genre · 6 filetype · 7 EQ · 8 comment · 9 category · 12 composer · 13 grouping · 14 description · 15 podcast enclosure URL · 16 podcast RSS URL (15/16 are UTF-8/ASCII with **no length word**, body starts at +0x18) · 17 chapter data · 18 subtitle · 19–21 TV show/episode/network · 22 album artist · 23 sort artist · 24 keywords · 27 sort title · 28 sort album · 29 sort album artist · 30 sort composer · 31 sort show · 50/51 smart playlist · 52 library index · 53 letter jump table · 100 playlist column defs / position · 200–204 album-list strings. D also uses 37, 43, 44 (store ISRC / purchaser email / name), 55 and 102 — undocumented; copy verbatim or omit.

String body layout (types < 50 except 15/16), header length always 0x18 (W, L):

| Off | Sz | Value | Notes |
|---|---|---|---|
| 0x18 | 4 | 1 | W calls it "position"; L writes 1 = "string type UTF16", 2 = UTF-8 on endian-reversed phone DBs. **W: if 0 on the Location mhod the track shows but will not play** |
| 0x1C | 4 | byte length | UTF-16 → 2 × chars |
| 0x20 | 4 | 1 | W: was thought to be the encoding flag, "definitely incorrect"; L: "unknown, set to 1". D: 1 on all 3 689 strings (this is the gotcha in our parser) |
| 0x24 | 4 | 0 | |
| 0x28 | len | data | **no NUL terminator, no padding** (W); total length = 40 + len |

Encoding: every source that writes for a Classic writes **UTF-16LE**; UTF-8 (flag 2) is documented only for reversed-endian mobile-phone DBs (W, L). Nothing documents UTF-8 acceptance by Classic firmware — write UTF-16LE. Strings over ~512 characters make the iPod reboot continuously (W).

Filetype (6) strings observed on D: `MPEG audio file` (226), `AAC audio file` (171), `Purchased AAC audio file` (84). `Apple Lossless audio file` is the gtkpod/iTunes convention but is **not measured** here (no ALAC on D).

## 5. Playlists — `mhlp`, `mhyp`, `mhip`

`mhlp`: header 0x5C on D, count at +8. **The first `mhyp` must be the master (Library) playlist** (W).

`mhyp` (W fields; header ≥ 0x30; L writes 0x6C; **D = 0xB8**):

| Off | Sz | Field | Notes |
|---|---|---|---|
| 0x0C | 4 | mhod count | **only mhods before the first `mhip`** (W); D master = 19, plain lists = 3 (title, 100, 102) |
| 0x10 | 4 | mhip count | L forces 0 in mhsd type 5 |
| 0x14 | 1 | is_master | 1 only on the Library playlist (W "hidden bit"; L `pl->type`) |
| 0x15 | 3 | flags | 0 |
| 0x18 | 4 | timestamp | Mac time |
| 0x1C | 8 | persistent id | random u64 (W) |
| 0x24 | 4 | 0 | |
| 0x28 | 2 | string mhod count | 1 (W, L) |
| 0x2A | 2 | podcast flag | 1 on at most **one** playlist, which then appears under Music → Podcasts instead of Playlists; two flagged lists → neither shows (W). D: 0 everywhere |
| 0x2C | 4 | sort order | 1 = manual; 3 title, 4 album, 5 artist … (W table). D: 1 |
| 0x3C | 8 | `id_0x24` copy | D, non-master only |
| 0x44 | 8 | persistent id copy | D |
| 0x50 | 2+2 | mhsd5 type | L, type-5 lists only |
| 0x58 | 4 | second timestamp | D (probably modified time) |

Children in order: title mhod (1) · optional **column-definition mhod 100** (0x288 bytes; "absolutely optional, the iPod doesn't use it" — W; L writes one anyway) · mhod 50 + 51 for smart lists · master only: pairs of mhod 52 (index) + 53 (letter table) · then `mhip`s, each followed by its **position mhod 100** (0x2C bytes, position at +0x18, "not optional" — W; since v0x0D it is a child of the `mhip` and counted in the `mhip`'s sizes, not in the `mhyp` mhod count).

`mhip` (76 bytes on L and D):

| Off | Sz | Field | Notes |
|---|---|---|---|
| 0x0C | 4 | mhod count | 1 |
| 0x10 | 2 | podcast group flag | 0 normal, 0x100 = podcast group header (then the child is a title mhod and track id = 0). Non-zero on normal songs "breaks iPods" (W) |
| 0x12 | 2 | unk | 0 |
| 0x14 | 4 | group id | unique, must not collide with any track id (W). D: 1248… |
| 0x18 | 4 | **track id** | = `mhit`+0x10 |
| 0x1C | 4 | timestamp | added-to-playlist time |
| 0x20 | 4 | podcast group ref | 0 |
| 0x2C | 8 | track dbid | D only; L writes 0 and works |
| 0x3C | 8 | random u64 | D only |

Position values: W "do not have to be sequential, numbers can be skipped"; D master uses 74333, 74338, … (step 5, not unique, not sorted), other lists are sequential. Menu order follows the `mhip` order with sort order 1 (W); the position mhod is still required.

**Master playlist needs** (W, D): first in the list; is_master = 1; title = the iPod's name; **every track as an `mhip`** (D: 481/481); mhod 52/53 indexes are optional but browsing is slower without them (W) — they index `mhit` *positions* (0-based), so they must be rebuilt or dropped whenever tracks are inserted or removed. No podcast playlist is required (D has none).

## 6. Smart playlists (mhod 50/51) — preservation only

50 = flags/limits (58 zero bytes of padding), 51 = rules (variable). Both are opaque blobs to us: copy the whole mhod byte-for-byte, keep them in the same `mhyp` between the title/100 mhods and the `mhip`s, and keep the `mhyp` mhod count. D shows iTunes materialises the members (Top 25 has 25 `mhip`s; others 0) — copy those `mhip`s too; nothing says the Classic evaluates rules itself.

## 7. Other files on a Classic

| File | On D | Matters for us? | Source |
|---|---|---|---|
| `iTunes/iTunesDB` | 903 KB, v0x75 | yes | |
| `iTunes/Play Counts` | `mhdp`, header 0x60, entry 0x1C, 481 entries | read-only feedback: the iPod deletes/rebuilds it when it sees a changed iTunesDB; iTunes merges then deletes it. Entries are by `mhit` position | W-pc, D |
| `iTunes/iTunesPrefs` (+ `.plist`) | `frpd`, 1232 bytes (W documents a 236-byte layout) | iTunes-only sync prefs; leave alone | W-misc, D |
| `iTunes/Extras.itdb` | **SQLite 3 file**, 454 KB | undocumented in W and unused by L; leave alone | D |
| `iTunes/iTunesControl`, `Rentals.plist`, `PSAlbumAlbums`, `PSElementsAlbums` | present | opaque; leave alone | W-misc, D |
| `Artwork/ArtworkDB` + `F10xx_1.ithmb` | `mhfd` header, 3 ithmb files | see below | W-art, D |
| `iTunesSD`, `iTunesStats`, `iTunesShuffle`, `iTunesPState` | absent | Shuffle only | W-misc |
| `OTGPlaylist*`, `iTunesEQPresets`, `iTunesLock` | absent | OTG lists = older iPods; `iTunesLock` is a transient mutex | W-basic |
| `Device/SysInfo`, `SysInfoExtended`, `HashInfo` | SysInfo empty, others absent | hash58 needs the FirewireGuid (§1) | L README.SysInfo |

**Artwork**: `mhit` ↔ `mhii` link is by dbid, or by `mhii link` at `mhit`+0x160 when non-zero (W). No source documents the Classic refusing an iTunesDB because ArtworkDB disagrees; stale `mhii`s simply dangle. For a new track without artwork: `has_artwork = 2`, `artwork count = 0`, `artwork size = 0`, `mhii link = 0`, no artwork mhods, and leave ArtworkDB untouched (W field notes; D has two such tracks). Deleting a track leaves an orphan `mhii` — acceptable per the same reasoning, untested.

## 8. Ordering and IDs

- **Track id** (u32): unique, referenced by `mhip`s (W). D: strictly ascending in the `mhlt`, 284…1245, non-contiguous → sequential is *not* required; keep existing ids stable and allocate new ones above max (also keeps `mhip.group_id` values from colliding — W says group ids must not equal any track id).
- **dbid** (u64): "iTunes randomly creates this value for a newly formatted iPod, then increments it by 1 for each song" (W); D values look random. Any unique 64-bit value; it joins ArtworkDB and, on D, is echoed in `mhip`+0x2C and `mhia`+0x20. Keep it stable across rewrites (artwork link).
- **Playlist persistent id**: random u64 (W); `mhip.group_id` unique u32.
- **`mhit` order**: D is by id; L writes in library order. Play Counts entries and mhod 52 indexes are positional, so appending new tracks at the end and rebuilding/dropping mhod 52/53 is the least disruptive.
- **Timestamps**: Mac epoch (seconds since 1904-01-01), local-time adjusted via `mhbd`+0x6C (L `device_time_time_t_to_mac`).

## 9. Minimal viable write, and known killers

**Checklist** (smallest structure both writers and W agree on):
1. `mhbd` 0xF4 with all unknown fields cloned from the current DB; version 0x75 (or ≥0x28); child count exact.
2. `mhsd` 1 → `mhlt` → one `mhit` per track (header 0x270 cloned-and-patched, or 0x248 as L) with id, visible=1, fourcc, size, length, sample rate<<16, bitrate, dbid, has_artwork=2, mediatype=1, unk9=0xFFFF, date added; mhods 1, 2, 3, 4, 5, 6 as UTF-16LE with the body words `1, len, 1, 0`.
3. `mhsd` 3 and `mhsd` 2, each an `mhlp` whose first `mhyp` is the master (is_master=1, name, all tracks, sort 1), then user playlists; each `mhip` 76 bytes with a 0x2C position mhod; every existing smart list copied verbatim.
4. `mhsd` 4 (`mhla`) and `mhsd` 5 copied through from the current DB (or 4 regenerated); `mhsd` 9 copied.
5. Every `total length` fixed up bottom-up; `mhbd`+0x08 = file size.
6. hash58: 0x30 = 1, zero 0x18/0x32/0x58, HMAC-SHA1 with the key from `<device GUID>`, write at 0x58, restore 0x18. Optionally leave 0x70 = 0 and 0x72 zeroed (L's proven Classic shape).
7. Music files copied under `iPod_Control/Music/Fxx/` with names matching the Location mhod (colon path); VFAT long names (gtkpod TROUBLESHOOTING: an msdos/8.3 mount makes files invisible to the DB).

**Documented empty-library / crash triggers**: wrong or missing hash58 → empty library (L NEWS, README.SysInfo) · Location > 112 bytes → track skipped (W) · Location mhod body word @+0x18 = 0 → shows, won't play (W) · any string > ~512 chars → reboot loop (W) · `visible ≠ 1` hides; `mediatype` 0 duplicates into Videos (W) · two playlists with podcast flag → none shown (two DIFFERENT playlists — one playlist written into both type 2 and type 3 carries the flag in BOTH; libgpod's `write_playlist` emits `podcastflag` for every section, and flagging only the type-3 copy gave a menu that counted ten episodes and would not open); type-3 `mhsd` not between 1 and 2 → podcasts missing (W) · non-zero podcast group flag on a normal `mhip` "breaks iPods" (W) · `mhyp` mhod count including the per-`mhip` position mhods, or missing position mhods (W) · podcast flag4 inconsistent with mediatype → iTunes drops the track on next sync (W) · version too old for the device (L) · DB larger than the firmware's load limit → silently empty (flashpod: 3 776 000 bytes on a 1st gen; Classic limit unmeasured, our DB is 0.9 MB).

## Top uncertainties

1. Whether v0x75 + hash58-only + zeroed hash72 is accepted (L's proven combination used v0x30). Test with a byte-identical rewrite of the current DB first (only the hash recomputed), then with hash72 zeroed.
2. Whether a missing/stale `mhsd` 4 (albums) or 5 changes Classic behaviour — undocumented; both writers include them.
3. `mhit` bytes 0x184–0x270 and the mhod types 37/43/44/55/102: undocumented; clone from the existing DB and zero for new tracks, untested.
