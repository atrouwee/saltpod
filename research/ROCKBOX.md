# Rockbox: what supporting it would mean, and whether the architecture fits

**Status.** Three kinds of claim appear below, tagged inline:

- **MEASURED** -- established by reading this repo's own source, or by a read-only inspection of
  `/Volumes/IPOD` done for this document on 2026-10-02. Nothing was written to the device.
- **RESEARCHED** -- established from external sources, cited inline with URLs. Most of this was
  fetched fresh this session (2026-10-02); a substantial block (install status, codec list, the
  exact playlist path grammar read out of Rockbox's own `apps/playlist.c`, dual-boot mechanics, the
  risk register) already exists in this repo at `research/alternatives.md`, dated 2026-09-27, and
  is carried forward here with attribution rather than re-derived. Where a secondary web source and
  that primary-source read disagree, the primary-source read wins and the disagreement is said
  plainly.
- **PROPOSED** -- a design sketch written for this document. Not implemented, not reviewed, and --
  see below -- not currently something this repo's own contribution policy accepts.

**This question has already been asked and answered once.** `publish/HISTORY.md` records it in five
words: *"The owner ruled out the alternative in five words -- 'We're not doing Rockbox' -- and it
has not been reopened."* `publish/CONTRIBUTING.md` lists Rockbox under "What we will not merge."
`research/alternatives.md` (2026-09-27) had in fact ranked Rockbox dual-boot as the **best-fitting**
route of four for this exact device -- text-file playlists, no transcoding, fully scriptable -- and
recommended the hand-written-`iTunesDB` route (what became saltpod) specifically *because* the
owner wanted to keep the Apple firmware and UI, not because Rockbox was technically worse. That
reasoning is still good: nothing in this document argues the owner should run Rockbox.

What changed is the question. "How do we support Rockbox *users*" is not "should this iPod run
Rockbox" -- it is about people who run this tool against their own, already-Rockbox'd device. This
document answers that question on its own terms and leaves the policy call -- whether
`CONTRIBUTING.md`'s line should move -- to the owner. It is research, not a decision.

## 0. This device, measured

Read-only, 2026-10-02:

```
$ ls -la /Volumes/IPOD/.rockbox
ls: /Volumes/IPOD/.rockbox: No such file or directory
```

No Rockbox install on the owner's own Classic -- confirms the HISTORY.md decision is still in
effect. The current on-disk layout, also read-only:

```
$ ls /Volumes/IPOD/iPod_Control/Music/F00
DMJO.mp3  HJBP.mp3  JNAG.mp3  MRPL.m4a  NJLA.mp3  OQAY.mp3  RUSO.mp3  TQOC.m4a  TYBO.m4a  WBIE.mp3
```

Ten unrelated tracks, two formats, four-letter scrambled names, one shared folder -- exactly what
`apply.new_location()` produces (`src/saltpod/apply.py:137`): a random `F%02d` folder from 50 and a
random 4-letter stem, independent of the track's artist, album or title. This single fact turns out
to matter more than the naming ugliness it is usually criticised for -- see 2.3.

## 1. Is Rockbox alive on the Classic?

**Yes, and the historically-hardest part is long settled.** The Classic (6G, 2007; 7G "thin", 2009)
uses Apple/Samsung's S5L8702 SoC, a generation harder than the PortalPlayer chips in iPods 1-5.5G:
getting code execution at all required the **freemyipod** project to find and exploit a bootrom bug
nicknamed "Pwnage 2.0" in the X.509 parsing stack, then reverse-engineer the hardware -- audio,
clickwheel, storage, the undocumented "Mikey" audio/power chip -- with no vendor documentation,
starting January 2011 (<https://freemyipod.org/>,
<https://terminalbytes.com/reverse-engineering-ipod-classic-mikey-chip/>; the port has had tickets
open as late as 2017 for things like earbud-remote support).

That work is finished and the result is stable, not experimental. `research/alternatives.md` (RESEARCHED,
2026-09-27) already established, from the release notes directly: **Rockbox 4.0 (April 2025) "has
stable ports for all iPod Classic/Video models"** and added 192 kHz decode in that release
(<https://www.howtogeek.com/rockbox-4-0-custom-firmware-mp3-players-old-ipods/>,
<https://hackaday.com/2025/04/19/rockbox-4-0-released/>). Rockbox treats every Classic generation as
one target, `ipod6g`, keyed off USB PID `0x1261` regardless of 2007/2008/2009 hardware revision
(<https://www.rockbox.org/tracker/task/12728>), and the `ipod6g` storage driver explicitly handles
both the 2007 thick unit's CE-ATA drive and the 2009 thin unit's ZIF/PATA drive
(<https://github.com/Rockbox/rockbox/blob/master/firmware/target/arm/s5l8702/ipod6g/storage_ata-6g.c>).
There is an actively maintained downstream fork, **Rockpod**, adding SSD-aware power management,
with patches landing as recently as August 2026 (<https://github.com/nuxcodes/rockpod>).

**Installation is not risk-free, but the risk is concentrated and reversible.** Two install paths
exist and this session found both in circulation: an older **emCORE/freemyipod** bootloader method
that the project itself now marks deprecated and warns not to use for new installs
(<https://files.freemyipod.org/~user890104/bootloader-ipodclassic.html>), and the current official
path -- flashing a small bootloader into NOR flash over USB DFU (hold MENU+SELECT ~12s) with either
the Rockbox Utility GUI or the `mks5lboot` CLI, after which the device dual-boots. iFixit's own guide
for the *old* path carries a plain warning -- *"Multiple people have reported it bricking their
iPod"* -- and its comment section documents real failures
(<https://www.ifixit.com/Guide/How+to+install+Rockbox+on+an+iPod+Classic/114824>). But freemyipod's
own documentation of the *current* method says the opposite: Rockbox and its bootloader "are fully
reversible by doing an iTunes Restore," and a DFU session interrupted mid-flash just leaves the
device in DFU mode, re-enterable by MENU+SELECT -- a failed flash is retried, not fatal
(<https://files.freemyipod.org/~user890104/bootloader-ipodclassic.html>). `research/alternatives.md`
did not find a 2025-2026 report of the modern method failing on Apple Silicon macOS, nor a success
report either -- "expected, unverified" is the honest state of that specific combination.

**No popularity number exists, and this document does not invent one.** Rockbox's own forum stats
page and wiki are protected by an anti-bot wall (Anubis) that this session's fetch tools could not
pass, so nothing from them is cited here. A web search surfaced what looks like a project
download-counter (figures on the order of hundreds of thousands per year in the mid-2020s, down from
millions in 2008) on a third-party mirror domain that failed to resolve when this session tried to
fetch it directly -- so that number is **not independently verified and is not used**. Even if real,
a download counter for the Rockbox *build* would span every supported target (dozens of Sansas,
iriver devices, iPods of every generation) and would not isolate "iPod Classic users." **No source
found in this research gives a number, or even an order-of-magnitude estimate, for iPod-Classic-
specific Rockbox users**, and the honest answer is that one was not found, not that it is small or
large.

## 2. How does Rockbox find music?

**Two independent modes, and neither reads the iTunesDB.** `research/alternatives.md` already
states this plainly: *"No `iTunesDB`. Rockbox browses the folder tree directly (File Browser) or
builds its own tag database (Database, optional)."* This session's research corroborates it from a
different angle: Rockbox's own wiki carries a page titled **"Convert iTunesDB to TagCache"**
(<https://www.rockbox.org/wiki/ConvertiTunesDBtoTagCache.html> -- page exists and is indexed, though
its content could not be fetched past the site's anti-bot wall this session) -- a conversion tool
would not need to exist if Rockbox could read the format natively. A second, independent account
puts it directly: *"Rockbox has no iTunesDB parser... music dispersed through files in random
directories [under Apple firmware] vs. Rockbox [which] is directory-based,"* meaning the same
library has to be made visible twice, once per firmware, in two different index structures
(aggregated from forum discussion surfaced by this session's search; not independently re-verified
against Rockbox source).

**File Browser** is the simpler mode: it walks the filesystem and shows what is there, nothing more.
It needs no index and no scan. In this mode a readable filename matters, because the filename *is*
what is shown.

**Database (tagcache)** is the mode that matters for a curated library. It is built by a background
thread (`apps/tagcache.c`) that walks a configurable set of root directories (default `/` -- i.e.
the whole volume -- on every target except Android, which defaults to `/sdcard`; up to 12 roots can
be configured, colon-separated), probes every file with a recognised audio extension through
Rockbox's metadata library, and writes the result to `database_tmp.tcd` as it goes. A commit step
turns that into the final files: numeric fields go straight into a master index,
**`database_idx.tcd`**, one fixed-size record per track, and every non-numeric tag (artist, album,
genre, title, filename, ...) gets its own deduplicated, sorted **`database_<N>.tcd`** file
(synthesised from <https://github.com/jasonbot/rockbox-db-refresh>,
<https://www.rockbox.org/wiki/TagcacheDBFormat>, and the manual's own description that "the first
time you use the database, Rockbox will scan your disk for audio files," fetched via a mirror at
<https://docs.huihoo.com/rockbox/rockbox-ipodvideo/rockbox-buildch4.html>). Crucially: **because the
scan walks the whole volume by default and reads tags rather than filenames, it does not care that
`iPod_Control/Music/F00/DMJO.mp3` has a scrambled name.** The Database browser shows the track by its
ID3/MP4/Vorbis-comment tags -- artist, album, title -- exactly as this tool already writes them. A
scrambled filename is only a cosmetic problem, and only for someone who deliberately switches to
File Browser mode.

**The scan can also be built on a PC, not just on-device**, which directly answers the prompt's
question about `database_*.tcd` and a PC-side tool. Several independent tools exist for exactly
this: **`rbdb`**, a static Go binary that "scans a Rockbox device root to read metadata from all
audio files, writing a complete tagcache database to `<root>/.rockbox/`"
(<https://github.com/jasonbot/rockbox-db-refresh> references it; also surfaced directly as a
search result); **Scrobbox**, a Linux companion app with a "Database Rebuilder to rebuild Rockbox
tagcache `.tcd` files on your PC without booting into Rockbox"
(<https://github.com/RoyLikesAudio/Scrobbox>); **`rockboxtagcache`**
(<https://github.com/csetera/rockboxtagcache>) and **DAP-DB-Manager**
(<https://github.com/vakintosh/DAP-DB-Manager>, claiming "180x faster" than an on-device scan); and
Rockbox's own in-tree `tools/database/database.c`, buildable with `make database`, though multiple
forum/tracker threads describe it as fiddly to compile
(<https://www.rockbox.org/tracker/task/8499>, <https://www.rockbox.org/tracker/task/9371>). None of
these were run or verified in this session -- they are cited as evidence that "build the index on a
computer, not the device" is an established, multiply-implemented pattern in the Rockbox ecosystem,
not a hypothetical.

## 3. Formats

**Confirmed: Rockbox decodes FLAC and ALAC natively on the Classic, and therefore the ALAC
conversion this tool performs today is unnecessary for a Rockbox target.** Three independent sources
agree: `research/alternatives.md`, reading Wikipedia's Rockbox codec table directly, lists "FLAC,
ALAC, WAV, AIFF, MP3, AAC, Vorbis, Opus, WavPack... all decoded in software" and states outright,
**"No transcoding of the FLAC library needed."** This session's own fetch of the manual's file-formats
appendix (a mirror of the iPod Video build, structurally identical to the Classic build since
Rockbox's codec library is shared across targets --
<https://docs.huihoo.com/rockbox/rockbox-ipodvideo/rockbox-buildap1.html>) lists both **FLAC** and
**Apple Lossless (`.m4a`/`.mp4`)** explicitly as lossless codecs, alongside WAV, AIFF and WavPack.
And the general Rockbox Wikipedia entry and forum discussion corroborate Vorbis and FLAC as
long-standing, with Opus support maturing later (a 2022 forum thread notes Opus was not yet
supported on all targets at that point; by Rockbox 4.0 in 2025 it is listed as supported). This
repo's own README already half-knew this -- "The Classic plays ALAC natively but not FLAC **without
Rockbox**" (`README.md:103`) -- this document is the confirmation that clause was gesturing at.

| format | Apple stock firmware | Rockbox on the same Classic |
|---|---|---|
| MP3 | yes | yes |
| AAC / `.m4a` | yes | yes |
| ALAC | yes (24-bit, 44.1/48 kHz only -- 96 kHz refused, per `research/alternatives.md` citing Apple/iLounge) | yes, and Rockbox 4.0 handles up to 192 kHz |
| WAV | yes (but "carries no reliable tags," `README.md:78`) | yes |
| AIFF | yes ("tags poorly," `README.md:103`) | yes |
| **FLAC** | **no -- refused by the firmware entirely** | **yes, natively** |
| Ogg Vorbis | no | yes |
| Opus | no | yes (modern builds) |
| WavPack, Musepack, Speex, mod/chiptune formats | no | yes |

So for a Rockbox target, `apply.convert_to_alac()` (`src/saltpod/apply.py:91`) has nothing to do on
a FLAC source: the file can be copied as-is, the way `AS_IS` already handles `.mp3`/`.m4a`/`.aac`
today. WAV and AIFF are a smaller win -- both already play on Apple firmware, so the existing
divergence stays (`ITUNES-PARITY.md` section 5: WAV/AIFF "copied as-is" today, parity either way) --
but the FLAC case is exactly the one this tool currently spends CPU time and loses fidelity headroom
on, for no benefit to a Rockbox listener.

## 4. Playlists

**`.m3u` and `.m3u8`, and the path grammar has already been read directly out of Rockbox's own
source** (`apps/playlist.c`, via `research/alternatives.md`, 2026-09-27,
<https://raw.githubusercontent.com/Rockbox/rockbox/master/apps/playlist.c>):

- Lines starting `#` are skipped (except the `#EXTM3U`/`#EXTINF` extended-format markers).
- **A UTF-8 byte-order mark forces UTF-8 parsing** -- without it, non-ASCII filenames (accents,
  Cyrillic) can fail to match. This session's web research corroborates the recommendation
  independently: a Rockbox forum account of a from-scratch playlist workflow says Rockbox "prefers
  the format to be UTF-8-BOM with LF line endings (.m3u8), otherwise it won't load files with exotic
  characters."
- **Backslashes are converted to forward slashes** on read, so a path written on a Windows host
  still resolves.
- **Relative paths resolve against the directory the playlist file itself sits in**, not the device
  root and not the current browse location.
- **Absolute paths are device-root paths with a leading slash** -- `/iPod_Control/Music/F04/ABCD.m4a`
  is a real, working example, not a sketch: it appears verbatim in a 2026-08-31 feature proposal on
  a sibling tool (see below). A Windows drive letter (`C:\...`) or a host path (`/Users/...`) is
  "dead on arrival" (`research/alternatives.md`).
- Rockbox recognises the extension and loads a playlist either by selecting it directly in the File
  Browser, or through the **Playlist Catalogue**, a menu that specifically lists whatever is in
  **`/Playlists`** at the device root (confirmed independently this session via the manual mirror,
  chapter 4: *"All playlists in the Playlist catalog are stored by default in the `/Playlists`
  directory in the root of your player's disk"*). `research/alternatives.md` already names this as
  the convention to target: `/Playlists/*.m3u8`.

**Does Rockbox read the iTunesDB's playlists? No -- confirmed, not merely expected.** Section 2
above establishes Rockbox has no iTunesDB parser at all; playlists are no exception. A playlist this
tool writes into the iTunesDB today is invisible to Rockbox regardless of format, and a `.m3u8`
written to `/Playlists` is invisible to Apple firmware, because Apple firmware never looks at the
filesystem for playlists -- only at its own database. The two are genuinely separate expressions of
"what belongs in this list," not two views of one fact, which has a direct consequence for section
2.4 below.

A live, independent confirmation of the whole path convention turned up during this research:
**TheRealSavi/iOpenPod issue #192**, *"Automatically mirror iPod playlists to Rockbox-compatible
M3U8 files"* (<https://github.com/TheRealSavi/iOpenPod/issues/192>, opened 2026-08-31, open,
unimplemented, 0 comments at time of reading). iOpenPod is the same sibling project this repo's own
README names as an alternative ("the sync step (iOpenPod or Rockbox - untested)," `README.md:84`,
and `research/alternatives.md`'s ranked #3). The issue proposes exactly the shape sketched in 2.4:
keep writing the normal `iTunesDB` for Apple firmware, and *additionally* mirror the same playlists
into `/Playlists` as Extended M3U8, built from "the final iTunesDB `Location`, normalized to a
Rockbox device-root path" -- with the example output:

```
#EXTM3U
#EXTINF:243,Grace Potter - Stars
/iPod_Control/Music/F04/ABCD.m4a
```

That is not a hypothetical a priori design -- it is someone else, independently, converging on the
same shape for a closely related tool, in the same month as the owner's question. It is cited here
as corroborating RESEARCH, not as code this repo depends on; it was not implemented at time of
reading and this repo borrows nothing from it but the confirmation.

## 5. Cover art

**Rockbox's search order is longer than this tool's current gap, and in one dimension genuinely
easier.** From the manual appendix (RESEARCHED this session, aggregated from search of
<https://www.rockbox.org/wiki/AlbumArt.html> and a mirrored manual appendix; the live wiki page
itself was blocked by the same anti-bot wall as elsewhere):

1. embedded art (JPEG in ID3v2 or MP4/M4A tags only -- **not** FLAC's own `METADATA_BLOCK_PICTURE`,
   per this list; unverified independently)
2. `./<filename>.{jpeg,jpg,bmp}` -- same basename as the track, same folder
3. `./<albumtitle>.{jpeg,jpg,bmp}`
4. `./cover.{jpeg,jpg,bmp}`
5. `./folder.jpg`
6. `/.rockbox/albumart/<albumartist>-<albumtitle>.{jpeg,jpg,bmp}` -- a device-wide cache keyed by
   artist+album, filled by Rockbox itself or a sync tool
7. `../<albumtitle>.{jpeg,jpg,bmp}` -- one directory up
8. `../cover.{jpeg,jpg,bmp}`

Filesystem-unsafe characters in `albumtitle`/`albumartist` (`\ / : < > ? * |`) are replaced with `_`;
doublequotes become single quotes; if no album artist tag exists, artist is used instead.

**This is strictly easier than ArtworkDB in one respect and strictly harder in another, and which
one dominates depends entirely on this tool's own file layout.** `research/ITUNES-PARITY.md` section
6 already states this tool writes **no** `ArtworkDB` at all -- a documented gap, 140 of 399
art-bearing files on this device have no art the Classic can show (`ITUNES-PARITY.md:131-134`).
Embedded-tag art (step 1) sidesteps that gap completely for both firmwares at once: `local_index.py`
already probes every stream for a cover and finds one on 1,562 of 4,048 drive files (`HANDOFF.md`
"Artwork comes from your own files"), and Rockbox reads the same embedded tag Apple firmware's
`ArtworkDB` was built from in the first place.

**But steps 2-8 all assume one directory per release, and this tool's own naming defeats that
assumption by construction.** Section 0 measured it directly: `F00` on the real device holds ten
unrelated tracks from (at minimum) two different releases, because `new_location()` picks a random
folder from 50 for every track regardless of what it is (`src/saltpod/apply.py:137-144`). A
`cover.jpg` dropped next to one track in `F00` would be found by **every other track that happens to
land in `F00`** under step 4 -- wrong art, non-deterministically, depending on which 50-way coin flip
each track landed on. **The cover.jpg/folder.jpg fallback is not available to this tool's current
layout at all, for either firmware, unless the per-track folder scrambling is replaced with
per-album folders.** The only art path that works under the F<nn> scheme as it stands is step 1,
embedded tags -- which is exactly where `convert_to_alac()`'s current behaviour is weakest (see 2.2):
`afconvert` strips all metadata, and `tags.FIELDS` (`src/saltpod/tags.py:25`) carries text fields
only, no artwork, so a FLAC/WAV/AIFF source's embedded cover does not survive the trip to the device
today, for either firmware's benefit.

## 6. Play counts and ratings

**Tracked, but in a completely separate accounting system from the one this tool already reads.**
When "Gather Runtime Data" is enabled, Rockbox's runtime database records, per track: **Rating** (1
byte), **Play Count** (4 bytes), and **last time played** (4 bytes, a relative timestamp) --
synthesised from a Rockbox wiki page (`RuntimeDatabase`, title confirmed via search, content behind
the same anti-bot wall) and corroborated by the manual's own warning that "Initialize Now removes
all database files (**removing runtimedb data also**) and rebuilds the database from scratch," while
"Update Now" preserves it -- implying the runtime stats live alongside, and survive independently of,
the tagcache's string/index files. This data is used on-device for "most played," "unplayed" and
"recently played" smart views in the Database browser.

**It does not touch, and is not touched by, the iTunesDB's `Play Counts` sidecar this tool already
merges** (`research/itunesdb-format.md` section 7, `ITUNES-PARITY.md` section 4,
`src/saltpod/playcounts.py`). They are two counters pointed at the same physical files through two
unrelated index structures. A dual-boot listener who plays a track under Rockbox racks up a play in
Rockbox's runtime database; the same track played under Apple firmware racks up a play in the
iTunesDB's `Play Counts` file; **neither firmware's counter knows the other exists**, and this tool's
`playcounts.py` today only ever reads the Apple-firmware one. Community PC-side tools exist that can
inspect `.tcd` files generally (section 2), but **no tool or method surfaced in this research reads
or merges Rockbox's runtime play-count data from a computer** -- this is a genuine unknown, not
something confirmed absent. Supporting Rockbox users fully would mean either accepting two
disjoint play-count histories, or building a second reader -- a real, separate piece of work, not
covered by anything already proposed below.

## 7. Dual boot

**Yes, normally -- and the two firmwares are not just compatible, they are structurally blind to
each other, which is good news for coexistence.** `research/alternatives.md` (RESEARCHED, primary
sources) is specific: the Rockbox bootloader lives in NOR flash, is installed alongside the Apple
firmware rather than over it, and after install the device **boots Rockbox by default; holding the
Hold switch engaged at power-on boots the Apple firmware instead**; MENU+SELECT reboots. (A couple of
secondary web sources this session found describe a different button combination for reaching Apple
firmware -- e.g. "Menu + Center" -- which disagrees with the Hold-switch account; this document
follows `research/alternatives.md`'s version, sourced to freemyipod and an Olsro firmware guide, as
the more carefully attributed of the two, and flags the disagreement rather than silently picking a
side.) Reverting is a single command, `mks5lboot --bl-uninst`, or an iTunes/Finder Restore, which
"returns the unit to stock, bootloader and all."

**One disk, two completely separate views, zero file-format conflict.** Section 2 already
establishes Rockbox has no iTunesDB parser and Apple firmware has no Rockbox-playlist or tagcache
reader. The practical consequence: adding a `/Playlists/*.m3u8` folder and leaving the iTunesDB
exactly as this tool writes it today changes **nothing** about what Apple firmware shows, because
Apple firmware does not scan the filesystem for anything other than what its own database points at.
The two coexist on one FAT32 volume, each firmware looking only at its own index, both pointed at
the same files on the same disk. That is the precondition that makes the "mirror, don't replace"
shape in 2.4 cheap rather than merely possible.

**This does mean two separate libraries to keep honest, not one.** A track removed from Apple
firmware's library (this tool's existing `remove` tier) does not disappear from a Rockbox `.m3u8`
unless something also rewrites that playlist; the reverse is also true. Nothing in this tool's
one-store model breaks here -- the file on disk is still master -- but "the iPod is a slave that
catches up" (`HANDOFF.md`, "One store. The iPod is downstream.") would need to mean **both indices
catch up**, not one.

## Part 2 -- the architecture question

### 2.1 What already works unchanged

More than first appears, and all of it follows from decisions this tool already made for reasons
that had nothing to do with Rockbox:

- **"The file on disk is master" is firmware-agnostic by construction** (`HANDOFF.md`). Nothing
  about that rule mentions iTunesDB, ArtworkDB or any Apple-specific structure -- it says tags live
  in the file, the device is downstream of the file, and editing writes the file first, always.
  Adding a second downstream consumer (a Rockbox index) does not strain that model; it is the model
  working exactly as advertised, a second time.
- **`tags.py` writes real tags into the real file, patching rather than regenerating**
  (`src/saltpod/tags.py:1-18`). This is the one piece of work a Rockbox-facing feature would
  otherwise have to invent from scratch, and it already exists, already guarantees audio-byte
  identity, and already has a selftest. Both Rockbox's embedded-art lookup and its tagcache scan
  read exactly the fields this writer already produces.
- **The AS_IS/CONVERT split in `apply.py`** (`src/saltpod/apply.py:58-59`) is already the right
  shape for a format decision that varies by target -- it just has the wrong membership for a
  Rockbox target (FLAC belongs in `AS_IS`, not `CONVERT`, for that case only). The branch point
  already exists; only the set membership would need to vary by target.
- **`curate.OPS` / "two adapters, one implementation"** (`publish/CONTRIBUTING.md`) is the right
  answer to a different question than this one. That pattern governs **who may call an operation**
  (the page, or the terminal) and insists the rule lives once regardless of caller. A Rockbox target
  is not a second caller of an existing operation -- it is a second **kind of output** from the
  `plan`/`sync` operation itself. The closer existing precedent is `platform.py`'s per-operation
  backend selection with a portable fallback (`publish/CONTRIBUTING.md`, "Prefer the system, but
  never require it") -- one operation (`to_alac`, say), multiple implementations chosen by what is
  available, with nothing above the choice point aware of which ran. A target concept wants the
  same shape: one `sync()`, a target-dependent choice of *what gets written*, nothing in `curate.OPS`
  or the page needing to know which.
- **FLAC and ALAC are both natively playable by Rockbox** (section 3): a sync aimed at a dual-boot
  device does not have to choose one audio copy over the other. The *same converted ALAC file*
  already serves a Rockbox listener as well as it serves Apple firmware -- Rockbox does not need the
  FLAC original on-device to play losslessly. This matters because it means the cheapest Rockbox
  support does not require re-architecting what gets copied, only what gets written *alongside* it.

### 2.2 What would have to change

| area | today | for a Rockbox target | forced? |
|---|---|---|---|
| `new_location()` naming | random `F<nn>/XXXX.ext`, 50-way scatter (`apply.py:137`) | no functional reason to change -- Database mode reads tags, not filenames (section 2) | **no** -- only a File-Browser-mode nicety |
| playlists | written into the iTunesDB (`ipod_edit.E.playlist_*`) | also written as `/Playlists/<name>.m3u8`, device-root paths, UTF-8 BOM | **yes** -- Rockbox has no iTunesDB reader at all (section 4) |
| FLAC handling | always converted to ALAC (`CONVERT` set, `apply.py:59`) | copy as-is for a Rockbox-only target; conversion stays pointless-but-harmless for a dual-boot target (section 3) | **conditionally** -- only matters if a Rockbox-only mode is built |
| cover art | no writer at all; embedded tags are the only thing that already helps either firmware (section 5) | embedded art needs to survive `convert_to_alac()`, which today strips it; `cover.jpg`/`folder.jpg` need per-album folders this tool does not have | **yes, for embedded art to keep working on converted files; folder-colocated art is a bigger, separate change** |
| play counts/ratings | reads and merges the iTunesDB `Play Counts` sidecar only (`playcounts.py`) | Rockbox's runtime database is a second, disjoint counter; no reader exists anywhere surveyed in this research (section 6) | **only if parity across both firmwares' play history is a goal -- not needed for playback itself** |

### 2.3 The cover-art complication, stated once

This is the one finding in this research that is not simply "Rockbox needs X, write X." The F<nn>
scramble was presumably chosen to mirror what iTunes itself does on a Classic (spreading files
across up to 50 folders is iTunes' own historical FAT directory-entry-count workaround, not a design
original to this tool). It costs nothing under the iTunesDB model, where every track is found by
database lookup, never by path convention. It costs real functionality under **any** scheme that
expects one folder per release -- which is three of Rockbox's eight art-search steps, and would
equally break a hypothetical future "write cover.jpg per album" feature for Apple firmware's own
benefit, since Apple firmware's `ArtworkDB` is the same story: gap, not divergence
(`ITUNES-PARITY.md` section 6). Fixing embedded-art survival through `convert_to_alac()` (teach
`tags.FIELDS`-adjacent code to carry one artwork blob, and have `afconvert`'s output picked up by a
writer that can embed it) closes most of the practical gap for both firmwares with one piece of
work, without touching folder layout at all.

### 2.4 The smallest honest shape (PROPOSED)

Two shapes, not one, because "support Rockbox users" splits into two different people with
different costs:

**Shape A -- the dual-boot mirror.** For the much more likely case (section 7: Rockbox on a Classic
is normally dual-boot, not a replacement) -- someone who still wants Apple firmware's UI day to day,
and Rockbox for the formats or features Apple's firmware lacks. This is additive and does not touch
anything the Apple-firmware sync already does:

```
sync(mount, target='apple')              # exactly what sync() does today, unchanged
sync(mount, target='apple+rockbox')      # PROPOSED: the above, plus --
                                          #   for each collection, after the iTunesDB write,
                                          #   render /Playlists/<name>.m3u8:
                                          #     #EXTM3U
                                          #     #EXTINF:<seconds>,<artist> - <title>
                                          #     /<device-root path to the same Fxx/XXXX.ext>
                                          #   UTF-8 with BOM, one file per collection.
```

No change to `new_location()`, `convert_to_alac()`, or anything that decides what gets copied -- the
mirror points at files the existing sync already placed. Cost: one new, small, pure function (path
of a device track -> an m3u8 string) plus one call site in `_sync()` after the existing playlist
loop, gated by a `target` value living beside `mount`/`firewire_guid` in `config.py`. It is, in
shape, almost exactly what `TheRealSavi/iOpenPod` issue #192 independently proposed for a sibling
tool in the same month (section 4) -- which is reassuring convergent evidence, not a dependency.

**Shape B -- Rockbox-primary.** For someone who genuinely does not want Apple firmware's view to
matter -- the case this tool's own `research/alternatives.md` already rated as the *better-fitting*
route a year ago, for a user who does not insist on keeping Apple's UI. This is a real second mode,
not a toggle:

- `new_location()` grows a second implementation that lays out `Music/<artist>/<album>/<track>.ext`
  instead of `F<nn>/XXXX`, which also makes `cover.jpg` viable (section 5, steps 4/5/7/8).
- `CONVERT` loses `.flac` for this target (section 3); FLAC copies as-is.
- the playlist writer targets `/Playlists/*.m3u8` as the **only** playlist output, since there is no
  Apple-firmware iTunesDB to keep honest alongside it.
- `convert_to_alac()` is only invoked for WAV/AIFF sources, which still benefit from real tags the
  way ALAC does today.

Shape B is real, separable work -- not a flag on Shape A -- and it is the one that actually collides
with `publish/CONTRIBUTING.md`'s current "What we will not merge: ... Rockbox" line. Shape A does
not: it never stops writing the `iTunesDB`, never changes what Apple firmware sees, and a Rockbox
user who never installs it loses nothing. Whether that distinction is enough to revisit the
CONTRIBUTING line is the owner's call, not this document's.

### 2.5 Rough cost

Shape A: `config.py` (one new field), `apply.py` (`_sync()`, one call site, ~10-20 lines), one new
small module for m3u8 rendering (~30-40 lines, pure function, easily tested without a device). No
change to `curate.py`, `ipod_edit.py`, `itunesdb_write.py`, `tags.py`, or the page. Verb surface
grows by zero -- it is a parameter on the existing `sync` operation, not a new one, so it needs no
new `OPS` entry and no new CLI verb, consistent with "two adapters, one implementation" even though
the pattern it extends is `platform.py`'s, not `curate.OPS`'s.

Shape B additionally touches: `apply.py` (`new_location()`, the `AS_IS`/`CONVERT` membership,
`convert_to_alac()`'s call sites), `tags.py` or a new artwork-aware writer (to carry embedded art
through a conversion, which also benefits Apple firmware's own gap per `ITUNES-PARITY.md` section 6
-- this is the one piece of Shape B worth doing regardless of Rockbox), and `local_index.py` if
per-album folder grouping is wanted on the drive side rather than only on the device side. Genuinely
days of work and testing, by the same estimate `research/alternatives.md` already gave the
hand-written-DB route generally: real, not free, and not proven on hardware by anything in this
document.

## Unknowns, listed honestly

- Whether FLAC's own embedded `METADATA_BLOCK_PICTURE` art is read by Rockbox's step-1 embedded-art
  lookup -- the source list found this session named ID3v2/MP4 tags only; not independently
  confirmed either way for FLAC specifically.
- Whether a PC-built `database_idx.tcd` (section 2) is accepted by Rockbox without ever having
  booted Rockbox on that device first to create the initial `.rockbox` folder structure -- not
  tested, not found stated anywhere surveyed.
- Whether any tool anywhere can read Rockbox's runtime play-count/rating data from a computer
  (section 6) -- not found, genuinely unknown rather than confirmed absent.
- The exact Apple-firmware button combination to reach stock boot after installing Rockbox --
  `research/alternatives.md` says Hold-switch; other web accounts found this session say a button
  chord. Not resolved here.
- Whether `rbutilqt`/`mks5lboot` actually completes successfully on current Apple Silicon macOS --
  `research/alternatives.md` already flagged this as unverified either way, and this session found
  nothing newer.
- Any real number, or even order of magnitude, for how many iPod Classic owners run Rockbox. Not
  found. Said plainly rather than estimated.

## Sources consulted this session (beyond what `research/alternatives.md` already cites)

- <https://freemyipod.org/> and <https://terminalbytes.com/reverse-engineering-ipod-classic-mikey-chip/> -- why the Classic was hard
- <https://www.rockbox.org/wiki/ConvertiTunesDBtoTagCache.html> -- page exists (title only; content blocked by Anubis)
- <https://github.com/jasonbot/rockbox-db-refresh>, <https://www.rockbox.org/wiki/TagcacheDBFormat> -- tagcache file structure
- <https://github.com/RoyLikesAudio/Scrobbox>, <https://github.com/csetera/rockboxtagcache>, <https://github.com/vakintosh/DAP-DB-Manager> -- PC-side database builders
- <https://www.rockbox.org/tracker/task/8499>, <https://www.rockbox.org/tracker/task/9371> -- in-tree `make database` tool, compile difficulties
- <https://docs.huihoo.com/rockbox/rockbox-ipodvideo/rockbox-buildap1.html>, `-buildch4.html` -- manual mirror (file formats, file browser, database basics, `/Playlists` convention), used because `rockbox.org` and `download.rockbox.org` are both behind an Anubis bot-wall that blocked every fetch attempt this session
- <https://www.rockbox.org/wiki/AlbumArt.html> -- cover-art search order (title/content via search synthesis; live page blocked)
- <https://www.rockbox.org/wiki/RuntimeDatabase> -- runtime database fields (title/content via search synthesis; live page blocked)
- <https://github.com/TheRealSavi/iOpenPod/issues/192> -- independent, concurrent proposal of the same mirror-playlist shape, fetched directly via `gh api` (full issue body quoted above)
- <https://www.ifixit.com/Guide/How+to+install+Rockbox+on+an+iPod+Classic/114824> -- the older, riskier install path's own bricking warnings
- <https://partspluspods.com.au/2025/10/29/rockbox-on-the-ipod-classic-a-complete-guide/> -- recent (Oct 2025) general-audience account, used only for corroboration, not as primary
- Download/popularity figures found via search on a third-party mirror domain that failed to resolve on direct fetch -- explicitly not used; see section 1
