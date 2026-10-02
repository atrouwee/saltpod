# Rockbox delta: the on-disk contract, the skin engine, and whether "Apple glass" is real

**Status.**

- **MEASURED** -- read-only, on this machine, 2 October 2026: `ls /Volumes/IPOD/.rockbox` still
  returns "No such file or directory" (a second reading of the same fact `research/ROCKBOX.md`
  established the same day). Everything said about this repo's own behaviour --
  `src/saltpod/apply.py`, `platform.py`, `config.py`, `tags.py`, `ipod_edit.py`, `curate.py` -- is
  read directly from that source, line numbers given, nothing from memory.
- **RESEARCHED FROM SOURCES** -- the Rockbox material. `rockbox.org` and `git.rockbox.org` are both
  behind an Anubis bot-wall that blocked every direct fetch this session, exactly as
  `research/ROCKBOX.md` already found. What's different this time: the official read-only GitHub
  mirror, `github.com/Rockbox/rockbox`, is **not** behind that wall, and `gh api` reaches it
  directly. Every Rockbox source citation below is a `path:line` in that mirror, `master` branch,
  fetched this session (2 October 2026) -- master moves, so a line number is a snapshot, not a
  promise. Manual text comes from the `.tex` sources in the same mirror (`manual/...`), which is the
  same text the blocked HTML build would have shown. Two secondary sources are named explicitly where
  used: d00k.net, a Rockbox theme author's own technical write-ups (cited as a named, credentialed
  source, not an anonymous forum post), and themes.rockbox.org's own gallery (reached directly;
  only its *search UI*, not the theme pages found via web search, sat behind Anubis).
- **PROPOSED** -- Part 2.5 (generating a theme from `publish/DESIGN.md`) and all of Part 3. Neither
  is implemented, reviewed, or costed beyond the estimate given.

**Build on `research/ROCKBOX.md`, don't repeat it.** That document already established, and this one
does not re-derive: the device has no Rockbox installed; the Classic (6G/7G) port is finished and
stable since Rockbox 4.0 (April 2025); the two install paths and their risk; the File-Browser-vs-
Database distinction; the `.m3u`/`.m3u8` path grammar read out of `apps/playlist.c`; the format table
(FLAC/ALAC/WAV/AIFF/Vorbis/Opus all native, unlike Apple firmware); the first six steps of the cover-
art search order; the dual-boot mechanics and button combination; and Shapes A and B for an adapter.
This document **extends** that register with primary-source detail Anubis blocked from the first
pass, **corrects** one load-bearing claim in it, and adds the two things the owner actually asked
for this round: a real account of the skin engine's visual ceiling, and the adapter shape to reach it.

**The reopening, for the record.** `publish/HISTORY.md:133-137`: ruled out 27 September ("We're not
doing Rockbox"), reopened 2 October with a reason attached -- *"rockbox is an adaptor like native
ipod software"*, *"if we can skin that interface we might be able to make it like apple glass
effect."* `publish/CONTRIBUTING.md:227` still lists "Rockbox" under "What we will not merge" --
unchanged by this document, which is research, not a policy edit.

## Verdict vocabulary

The same five words `research/ITUNES-PARITY.md` defined, used the same way, applied here to "what
Rockbox reads or writes, and what saltpod does about it today":

| | |
|---|---|
| **parity** | saltpod already does what a Rockbox-aware sync would need |
| **better** | saltpod does more, deliberately |
| **divergent** | saltpod does it differently ON PURPOSE, or the thing is device-owned/ephemeral and a sync should never touch it |
| **gap** | Rockbox needs it, a Rockbox-aware sync should produce it, saltpod does not |
| **unknown** | not investigated -- said plainly rather than guessed |

---

# Part 1 -- the delta register

## 1.1 The on-disk contract

`research/ROCKBOX.md` section 0 already measured the Rockbox-less state of the real device and the
`F<nn>/XXXX.ext` naming scramble. The file list below is everything under `.rockbox/` this session
could pin to an exact macro or struct, fetched from `firmware/export/rbpaths.h` and the modules that
read each path.

| file | purpose, sourced | saltpod today | verdict |
|---|---|---|---|
| `.rockbox/config.cfg` | user settings incl. active theme/wps/sbs/font/colours. `CONFIGFILE`, `firmware/export/rbpaths.h:124` | never read or written | **gap** -- only matters once a pushed theme (Part 2) exists; nothing to do for plain sync |
| `.rockbox/.resume.cfg` | resume state as a *separate* file from `config.cfg`: `resume_index`, `resume_crc32` (CRC32 of the filename), `resume_elapsed`, `resume_offset`, last volume, last screen -- struct `system_status`, `apps/settings.h:337-365`; file macro `RESUMEFILE`, `rbpaths.h:123` | not read; Apple firmware's resume state lives inside the iTunesDB's own per-track fields instead of a sidecar, so this tool's model has no equivalent slot | **divergent** -- architecturally separate, nothing to merge |
| `.rockbox/.playlist_control` | the edit log of the *current, unsaved* playlist (inserts, deletes, shuffles since it was loaded), versioned -- `PLAYLIST_CONTROL_FILE_VERSION 6`, back-compatible to a long-term-support version 2, `apps/playlist.c:143-145`; macro `PLAYLIST_CONTROL_FILE`, `rbpaths.h:127` | not touched | **divergent** -- ephemeral, device-owned, the same category as Apple firmware's On-The-Go playlist (`ITUNES-PARITY.md` section 3: "not read -- a sync would silently drop one") |
| `database_idx.tcd` + `database_0.tcd` ... `database_8.tcd`, `database_12.tcd` | the tagcache: see 1.2 | not built, not read | **divergent** today (Rockbox already scans the filesystem itself); **gap** only if a PC-side tagcache writer is ever built |
| `.rockbox/most-recent.bmark`, `<dirname>.bmark` / `<playlistname>.bmark` | bookmarks: saved position plus pitch/speed, one file per directory or saved playlist, up to `MAX_BOOKMARKS 10` entries per file, `apps/bookmark.c:51-54` | not read | **gap** -- same shape as On-The-Go playlists: device-created state a sync currently drops |
| `/bookmark.ignore`, `/bookmark.unignore` | per-directory opt-out/opt-in for auto-bookmarking, `apps/bookmark.c:54-55`, `manual/configure_rockbox/bookmarking.tex:17-27` | not relevant to sync | **divergent** -- a Rockbox user preference, not library data |
| `.rockbox/Playlists/*.m3u8` (compiled-in default; see 1.3 for the correction) | the Playlist Catalogue's menu source | not written | **gap** -- this is Shape A, `research/ROCKBOX.md` section 2.4, with a path correction below |
| `.rockbox/dircache.dat`, `.rockbox/.glyphcache` | directory-listing cache, font-glyph cache, `rbpaths.h:118,128` | not touched | **divergent** -- pure on-device performance caches, self-rebuilding |
| `.rockbox/themes/*.cfg`, `.rockbox/wps/*.{wps,sbs,fms}` (+ a per-theme image subfolder) | the installed theme itself | not written | **gap** -- see Part 2/3 |

## 1.2 How music is found -- the tagcache, precisely

`research/ROCKBOX.md` section 2 already established File Browser vs Database (tagcache) as the two
modes, that the scan reads tags rather than filenames (so the `F<nn>` scramble is cosmetic in
Database mode), and that the scan can be built on a PC. This session read `apps/tagcache.c` directly
rather than synthesising from a blocked wiki page, which narrows two things that were previously
fuzzy.

**The file format, from the struct itself** (`apps/tagcache.c:115,139,145,219`):

```c
#define TAGCACHE_MAGIC           0x54434810
#define TAGCACHE_FILE_NOCOMMIT   "database_commit.ignore"
#define TAGCACHE_FILE_MASTER     "database_idx.tcd"
...
"artist", "album", "genre", "title", "filename", "composer", "comment",
"albumartist", "grouping", "year", "discnumber", "tracknumber",
"canonicalartist", "bitrate", "length", "playcount", "rating", "playtime",
"lastplayed", "commitid", "mtime", "lastelapsed", "lastoffset"
```

`database_idx.tcd` is the master index: one `struct index_entry` per track --
`int32_t tag_seek[TAG_COUNT]` (a byte offset into the matching `database_N.tcd` string file for a
text tag, or the value itself for a numeric one) plus a flag word (`FLAG_DELETED`, `FLAG_DIRCACHE`,
`FLAG_DIRTYNUM`, `FLAG_TRKNUMGEN`, `FLAG_RESURRECTED`). Every *string* tag (`artist`, `album`,
`genre`, `title`, `filename`, `composer`, `comment`, `albumartist`, `grouping`) gets its own
deduplicated, sorted `database_N.tcd` file. Every *numeric* tag -- and this is the correction, next
section -- including `playcount`, `rating`, `playtime` and `lastplayed`, lives directly inside
`database_idx.tcd` itself, not in a separate file.

**Scan roots, confirmed as a setting, not folklore.** `apps/settings_list.c:446-448`:

```c
#if defined(HAVE_MULTIDRIVE) ... "/sdcard"
#else
#define DEFAULT_TAGCACHE_SCAN_PATHS "/"
#endif
```

exposed as the user setting `tagcache_scan_paths` ("database scan paths", `settings_list.c:1898`,
`unsigned char tagcache_scan_paths[MAX_PATHLIST+1]` -- a colon-separated text field, `settings.h:630`,
matching `research/ROCKBOX.md`'s "up to 12 roots" claim rather than contradicting it). A second,
separate setting most sources (including `research/alternatives.md`) don't mention: `tagcache_db_path`
("database path", default `ROCKBOX_DIR` -- i.e. `.rockbox/` itself, `settings_list.c:1899-1900`) says
*where the `.tcd` files are stored*, independent of what's scanned. "Gather Runtime Data" is the
literal setting name `runtimedb` (`settings_list.c:1895`).

**A PC-side tagcache writer is not hypothetical tooling -- it is a one-line macro in the firmware's
own source**, and `research/ROCKBOX.md` section 2 already named four independent community tools that
do exactly this (`rbdb`, Scrobbox, `rockboxtagcache`, DAP-DB-Manager), none run this session.

## 1.3 Play counts, ratings, last played -- a correction to `research/ROCKBOX.md` section 6

`research/ROCKBOX.md` described a separate "runtime database" synthesised from a Rockbox wiki page
title it could not fetch past Anubis, and flagged two things as unknown: where exactly the data
lives, and whether any PC tool can read it back.

**Reading `apps/tagcache.c` directly resolves the first unknown, and it is not what the wiki title
implied.** `playcount`, `rating`, `playtime` and `lastplayed` are not a separate file alongside the
tagcache -- they are four of the numeric tags in the *same* tag-name array quoted above, stored as
ordinary fields inside `database_idx.tcd`, the identical master index that also holds `year`,
`bitrate` and `length`. `FLAG_RESURRECTED` exists specifically so that when a track is re-added after
a rescan, its play history is recovered "by matching filename or artist+album+title CRC32 hashes"
(matching `research/ROCKBOX.md`'s own citation of this behaviour, now tied to a concrete flag bit
rather than a paraphrase). The skin tag reference confirms the same model from the display side:
`%rp` (play count), `%rr` (rating, a 0--10 scale, not 1--5 -- `manual/appendix/wps_tags.tex:238-240`)
and `%ra` (autoscore) are grouped under one "Runtime Database" heading in the manual, but that heading
names a *feature*, not a second file.

| field | where it lives | saltpod today | verdict |
|---|---|---|---|
| play count | `database_idx.tcd`, numeric tag `playcount` | reads/merges Apple firmware's `Play Counts` sidecar only, `src/saltpod/playcounts.py` | **gap** |
| rating | `database_idx.tcd`, numeric tag `rating` (0--10) | reads the iTunesDB's rating, never writes (`ITUNES-PARITY.md` section 4) | **gap** |
| last played | `database_idx.tcd`, numeric tag `lastplayed` | not read for either firmware | **gap** |
| `playtime`, `lastelapsed`, `lastoffset` | same file -- cumulative seconds played, and what looks like a resume-position pair that overlaps in purpose with `.resume.cfg` | not read | **unknown** -- why both exist was not chased further this session |

**The second unknown narrows but does not close.** Because these four fields live inside the exact
file the PC-side builder tools already read and rewrite, a tool that *builds* `database_idx.tcd` from
file tags necessarily touches the bytes that also hold play history -- the open question is no longer
"does anything touch this file," it is "does any of the four named tools preserve or report the
numeric fields rather than overwriting them with zeros on a rebuild." Not verified; none were run
this session. Still **unknown**, now a sharper unknown than before.

## 1.4 Playlists -- the grammar, and a path this document disputes

`research/ROCKBOX.md` section 4 already has the `.m3u`/`.m3u8` grammar read out of `apps/playlist.c`
(UTF-8 BOM, backslash normalisation, relative-to-containing-directory resolution, leading-slash
device-root absolute paths) and does not need restating.

**The default Playlist Catalogue directory is `.rockbox/Playlists`, not `/Playlists` at the volume
root -- and the manual's own prose disagrees with the compiled default.** From
`firmware/export/rbpaths.h:64`:

```c
#define PLAYLIST_CATALOG_DEFAULT_DIR ROCKBOX_DIR "/Playlists"
```

`ROCKBOX_DIR` is the same macro behind `WPS_DIR` (`ROCKBOX_DIR "/wps"`), which is unambiguously
`/.rockbox/wps` -- so `PLAYLIST_CATALOG_DEFAULT_DIR` is `/.rockbox/Playlists`. This is not a stray
constant: `apps/settings_list.c:2367-2368` wires it up as the literal default of the user-facing
"playlist catalog directory" setting, and `apps/playlist_catalog.c:72-77` falls back to it whenever
`global_settings.playlist_catalog_dir` is empty. The manual text `research/ROCKBOX.md` and
`research/alternatives.md` both cited (via a mirror, since the live manual is blocked) says the
opposite: *"stored by default in the `/Playlists` directory in the root of your player's disk."* This
session could not resolve which is stale -- a years-old manual sentence, or a description that is
using "the root of your player's disk" loosely to mean "inside the Rockbox install" -- and says so
rather than picking a side. **Practically, it means Shape A in `research/ROCKBOX.md` section 2.4
targets the wrong path.** A mirrored playlist a user hasn't gone out of their way to reconfigure
would need to land in `/.rockbox/Playlists/*.m3u8`, not `/Playlists/*.m3u8`, to appear in the
Catalogue unmodified.

**`.playlist_control` is not a saved playlist and must never be treated as sync's concern.** It is
the live edit log of whatever is *currently* loaded -- Database browsing, a `.m3u8`, or a shuffled
queue -- and only an explicit "save as" from that menu produces a durable `.m3u8` file
(`manual/configure_rockbox/bookmarking.tex:28-31` notes Rockbox will even offer to save an unsaved
current playlist before it lets you bookmark it). This is the direct structural analogue of the
iTunesDB's own live "now playing" state and the On-The-Go playlist: device-owned, ephemeral, and
outside this tool's one-store model by the same reasoning `ITUNES-PARITY.md` section 7 already gives
for those two.

## 1.5 Metadata -- what Rockbox reads that Apple firmware and saltpod do not

Primary source: `manual/appendix/file_formats.tex:277-351`, the "Featureset for generic metadata
tags" table, by tag-type family (ID3, APE, Vorbis, MP4, ASF):

| feature | ID3 | APE | Vorbis | MP4 | ASF |
|---|---|---|---|---|---|
| ReplayGain | x | x | x | x | x |
| Embedded cuesheet | x | x | x | | |
| Embedded art `.jpg` | x | x | | x | x |
| Embedded art `.bmp` | | x | | | |
| Embedded art `.png` | | x | | | |
| Grouping | | x | x | x | |
| Composer | | x | x | x | x |

**ReplayGain -- the one clean "Rockbox reads something neither Apple firmware nor saltpod does."**
Apple firmware computes its own, incompatible Soundcheck value instead (`ITUNES-PARITY.md` sections 2
and 5: "the only *audible* divergence"); saltpod's own tag writer, `tags.FIELDS`
(`src/saltpod/tags.py:28`), carries `('title', 'artist', 'album', 'album_artist', 'genre', 'year',
'track')` -- no ReplayGain field at all, in either direction. **Gap**, and a different gap than
Soundcheck: ReplayGain is a value a source file can *already carry* (most FLAC rips do) and this tool
currently drops it on the floor rather than needing to compute it.

**Embedded cuesheets confirm `research/ROCKBOX.md`'s open question from the other direction.** Rockbox
reads a cuesheet either as a `<name>.cue` sidecar or embedded in ID3 (`TXXX CUESHEET`), APE or Vorbis
comments (`manual/appendix/album_art_info.tex` does not cover this; table above does). Whether any of
the 4,049 files this tool's own index covers actually carry one was not checked this session --
**unknown**, not assumed absent.

**No ID3v2 `CHAP`/`CTOC` chapter-frame support found.** Searched the manual's feature tables and the
general web; nothing confirms native chapter-frame reading, only the cuesheet mechanism above, which
is a different (older, simpler) way of marking sub-track positions. **Not found**, stated plainly
rather than inferred either way.

## 1.6 Cover art -- the embedded-art unknown, resolved

`research/ROCKBOX.md` section 5 gave the 8-step search order from a synthesis of blocked sources and
flagged one specific thing as unverified: *"Whether FLAC's own embedded `METADATA_BLOCK_PICTURE` art
is read by Rockbox's step-1 embedded-art lookup."*

**Resolved, from the primary source, `manual/appendix/album_art_info.tex:9-37`, fetched directly and
quoted verbatim:**

> 1. embedded (JPEG images in ID3v2 or MP4 tags only)
> 2. `./filename.{jpeg,jpg,bmp}`
> 3. `./albumtitle.{jpeg,jpg,bmp}`
> 4. `./cover.{jpeg,jpg,bmp}`
> 5. `./folder.jpg`
> 6. `/.rockbox/albumart/albumartist-albumtitle.{jpeg,jpg,bmp}`
> 7. `../albumtitle.{jpeg,jpg,bmp}`
> 8. `../cover.{jpeg,jpg,bmp}`

**"ID3v2 or MP4 tags only" is exact, not approximate -- Vorbis-tagged files (FLAC, Ogg) are absent
from step 1 entirely**, and the featureset table in 1.5 confirms it from the other direction: the
"Embedded albumart" row has no `x` in the Vorbis column for any of `.jpg`/`.bmp`/`.png`.
`research/ROCKBOX.md`'s guess was right; it is now a confirmed primary-source fact rather than an
unverified inference.

**Two format constraints not in `research/ROCKBOX.md`, same source:** Rockbox does not support
RLE-compressed BMP, and embedded JPEG album art "must consist of a single scan with interleaved
components" -- progressive and multi-scan JPEGs are refused because they need more memory to decode.
Anything saltpod might ever write as a `cover.jpg`-convention file for Rockbox's benefit needs a
baseline (non-progressive) JPEG encoder setting.

**Consequence for this tool's own highest-ranked gap.** `research/ROCKBOX.md` section 2.3 already
named "embedded art does not survive `convert_to_alac()`" as the one fix that helps both firmwares at
once. This sharpens *why* for Rockbox specifically: the only embedded-art path Rockbox's step 1 reads
that a FLAC/WAV/AIFF source could ever reach is the **MP4 container it gets converted into** --
Rockbox never reads art embedded in the FLAC source itself, with or without this tool's help. Fixing
art-survival-through-conversion is not a nice-to-have for Rockbox; for a converted file, it is the
*entire* embedded-art story. Verdict: **gap**, same root cause as `ITUNES-PARITY.md` section 6, now
with two firmwares depending on the same fix.

## 1.7 Formats -- addendum to the existing table

`research/ROCKBOX.md` section 3's table (MP3/AAC/ALAC/WAV/AIFF/FLAC/Vorbis/Opus/WavPack/etc.) stands.
One addition, from the same `file_formats.tex` table: the per-container tag-type matrix (ID3 for
`.mp1/.mpa/.mp2/.mp3/.rm/.ra/.rmvb/.tta`; APE for `.mpc/.ape/.mac/.wv`; Vorbis for
`.ogg/.oga/.spx/.flac`; MP4 for `.m4a/.m4b/.mp4`; ASF for `.wma/.wmv/.asf`) confirms FLAC is tagged
with Vorbis comments specifically, which is why its embedded art and cuesheet behaviour in 1.5/1.6
follow the Vorbis column and not a FLAC-specific one.

## 1.8 Dual boot -- no change, one path correction carried over

`research/ROCKBOX.md` section 7's conclusion holds: one disk, two blind firmwares, zero file-format
conflict, because Apple firmware never scans the filesystem for anything outside its own database.
Naming the actual files involved (1.1) only reinforces this -- `config.cfg`, `.resume.cfg`,
`.playlist_control`, the `.tcd` files and `.bmark` files all live inside `.rockbox/`, which Apple
firmware has no reason to open. The one practical change dual boot makes to this document's own
findings: if Shape A (mirrored playlists) is ever built, it should write to `.rockbox/Playlists/`
per 1.4's correction, not `/Playlists/` at the root.

## 1.9 Gaps, ranked by what they'd cost to close

In the shape of `ITUNES-PARITY.md` section 8, but for a Rockbox-aware sync specifically:

1. **Embedded art surviving `convert_to_alac()`** -- the single highest-leverage fix, because it is
   now established (1.6) that it is the *entire* embedded-art story for any converted file under
   Rockbox, not just a cosmetic win for Apple firmware's `ArtworkDB` gap.
2. **Mirrored `.m3u8` playlists** (Shape A) -- cheap, additive, already scoped in
   `research/ROCKBOX.md` section 2.4-2.5, now with the corrected target directory.
3. **ReplayGain passthrough** -- a field saltpod already has the file open to read; currently dropped
   on the floor for a feature Rockbox actually uses.
4. **On-The-Go playlists and bookmarks** -- the same shape of problem twice (1.1): device-created
   state a sync silently drops. Low effort each, and the failure mode is data loss either way.
5. **A PC-side tagcache writer** -- real, bounded work (the struct is now fully known, 1.2), but only
   valuable for a Rockbox-primary (Shape B) user, not a dual-boot one, since Rockbox already builds
   its own tagcache from file tags on first boot.
6. **Reading play counts/ratings back from `database_idx.tcd`** -- blocked on the unresolved tool
   question in 1.3, not on anything this session found technically hard.

## 1.10 Unknowns, listed honestly

- Whether `playtime`/`lastelapsed`/`lastoffset` genuinely duplicate `.resume.cfg`'s own resume fields
  or serve a distinct purpose -- not chased past finding both exist.
- Whether any of the four named PC-side tagcache tools (`rbdb`, Scrobbox, `rockboxtagcache`,
  DAP-DB-Manager) preserve `playcount`/`rating`/`lastplayed` on a rebuild, or zero them -- none run
  this session.
- Which of the manual's "`/Playlists` at the disk root" or the compiled
  `PLAYLIST_CATALOG_DEFAULT_DIR` is the one a current Rockbox 4.x build actually honours out of the
  box -- not resolved; flagged, not guessed.
- Whether any file in this library's own 4,049-track index carries an embedded cuesheet -- not
  checked.
- Whether ID3v2 `CHAP`/`CTOC` chapter frames are read by any Rockbox code path not covered by the
  manual's feature tables -- not found, which is not the same as confirmed absent.
- `TAGCACHE_FILE_NOCOMMIT` ("database_commit.ignore") -- its name suggests a way to suppress an
  auto-commit, which would matter to a PC-side writer trying not to race Rockbox's own scanner; its
  exact semantics were not read past the `#define`.

---

# Part 2 -- theming, and the "Apple glass" question

## 2.1 The skin files, and how a theme installs

Four file kinds, confirmed from `manual/configure_rockbox/theme_settings.tex` and
`firmware/export/rbpaths.h:105-112`:

| extension | screen it draws | lives in |
|---|---|---|
| `.wps` | While Playing Screen (the now-playing display) | `.rockbox/wps/` (`WPS_DIR`) |
| `.sbs` | base skin -- menus, browsers, and underneath the WPS/FMS | `.rockbox/wps/` |
| `.fms` | FM radio screen | `.rockbox/wps/` |
| `.cfg` | binds one theme together: which `.wps`/`.sbs`/`.fms`/font/backdrop/iconset/colours to load as a unit | `.rockbox/themes/` (`THEME_DIR`) |

Per-theme image assets live in a subfolder of `.rockbox/wps/` named after the theme (e.g.
`.rockbox/wps/cabbiev2/battery-320x240x16.bmp` -- a real path in the shipped default theme, see 2.2).
A `.cfg`'s own key=value structure (`wps:`, `sbs:`, `font:`, `backdrop:`, `colours:` and similar) is
described consistently across every secondary source this session could reach, but the canonical
reference page (`CustomConfigFile.html`) sits behind Anubis and no literal example `.cfg` exists in
the source tree to quote verbatim -- the shipped default theme, `cabbiev2`, is compiled in rather than
installed as a `.cfg` + `.wps` pair, so this session never had a real file to cite byte-for-byte.
**RESEARCHED, secondary-sourced; said plainly rather than papered over with a reconstructed example.**

Install path, from the in-firmware menu (`theme_settings.tex`): "Browse Theme Files" lists every
`.cfg` already on the device and applies one on selection; themes not already on the device come from
**themes.rockbox.org**, filtered by device target (2.4).

## 2.2 The markup language, in the Classic's own shipped syntax

Rather than reconstruct examples, this section quotes the actual theme Rockbox ships for this exact
screen -- `wps/cabbiev2.320x240x16.wps` in the source tree, which is 320×240×16bpp, the Classic's own
resolution (2.3) -- fetched verbatim:

```
# Disable Status Bar
%wd
# Load Backdrop
%X(wpsbackdrop-320x240x16.bmp)
# Preload Images
%xl(A,lock-320x240x16.bmp,0,0,2)
%xl(B,battery-320x240x16.bmp,0,0,10)
# Album Art/Info Viewport Conditional
%?C<%Vd(a)|%Vd(b)>
# Progress Bar
%V(10,162,300,15,-)
%pb(0,0,300,15,pb-320x240x16.bmp)
# Battery
%V(126,207,44,23,-)
%?bp<%?bc<%xd(Ba)|%xd(Bb)>|%?bl<|%xd(Bc)|%xd(Bd)|%xd(Be)|%xd(Bf)|%xd(Bg)|%xd(Bh)|%xd(Bi)|%xd(Bj)>>
# Album Art
%ax%Vl(a,16,32,120,120,-)
%Cl(0,0,120,120,c,c)
%Cd
```
(`Rockbox/rockbox:wps/cabbiev2.320x240x16.wps`, full file is 79 lines)

The tag families, from `manual/appendix/wps_tags.tex` (the full manual chapter, not a wiki fragment):

- **Viewports** -- `%V(x,y,[w],[h],[font])` defines one; on colour targets `%Vf([fg])`/`%Vb([bg])` set
  its colours; `%Vl('id',...)` preloads one for later; `%Vd('id')` displays it; `%Vi('label',...)` +
  `%VI('label')` name an "Info Viewport"; `%VB` sends drawing to the **backdrop layer** instead of the
  default foreground layer (`wps_tags.tex:55-97`). Two layers, named explicitly -- see 2.3.
- **Conditionals** -- `%?xx<true|false>` and `%?xx<alt1|alt2|...|else>`; `%if(tag,op,operand)` for
  `=,!=,>,>=,<,<=` comparisons against another tag, a number or text; `%and(...)`/`%or(...)` for
  combining conditions (`wps_tags.tex:569-598`).
- **Images** -- `%X(file.bmp)` loads a full-screen backdrop; `%x(n,file,[x,y])` loads and shows one
  image; `%xl(n,file,[x,y],[nimages])` preloads a **bitmap strip** -- `nimages` sub-images tiled
  vertically in one file; `%xd(n[i],[tag],[offset])` displays a preloaded sub-image, often selected by
  another tag's value (the battery/volume icon strips above); `%x9(n)` draws a **9-patch bitmap**
  across the whole viewport -- corners unscaled, edges stretched on one axis, the centre stretched on
  both (`wps_tags.tex:419-466`). This is Rockbox's rounded-corner mechanism: the radius is pixels an
  artist drew once, not a vector primitive.
- **Album art** -- `%Cl(x,y,[maxw],[maxh],h_align,v_align)` configures it, `%Cd` draws it, `%C` tests
  for its presence in a conditional (`wps_tags.tex:480-516`).
- **Bar tags** -- any of `%pb` (progress), `%pv` (volume), `%bl` (battery) etc. can take
  `(x,y,w,h,[options])`, where options include `image`, `slider` (a preloaded image centred on the
  current position), `backdrop` (an image under the bar), `nofill`/`nobar` and orientation flags
  (`wps_tags.tex:736-798`).
- **Colouring** -- `%dr(x,y,w,h,[color1,color2])` fills a rectangle; given two colours it does a
  **linear gradient fill** directly, no bitmap required (`wps_tags.tex:104-111`).
- **Runtime Database** -- `%rp` (play count), `%rr` (rating, 0--10, usable as
  `%?rr<0|1|2|...|10>`), `%ra` (autoscore) -- confirming 1.3's finding that these are plain skin tags
  over ordinary tagcache fields, not a separate subsystem (`wps_tags.tex:236-242`).

## 2.3 What is actually possible visually

**The hardware, confirmed from the firmware's own target header**
(`firmware/export/config/ipod6g.h:85-90`):

```c
#define LCD_WIDTH  320
#define LCD_HEIGHT 240
#define LCD_DEPTH  16   /* pseudo 262.144 colors */
#define LCD_PIXELFORMAT RGB565 /* rgb565 */
```

320×240, 16 bits per pixel, RGB565 -- 65,536 directly addressable colours, with the comment's
"262,144" referring to a dithering trick (2^18, i.e. 6 bits per channel) rather than a true colour
depth the framebuffer stores. No GPU; a 216 MHz ARM (`CPU_FREQ 216000000`, same file) does every pixel
operation in software.

**Transparency: two real mechanisms exist, and they are very different in cost.**

1. **Colour-key masking** -- the long-standing, cheap method. d00k.net (a named Rockbox theme author)
   calls it "magenta-based masking": one colour in the bitmap is declared the hole, binary in/out, no
   partial values.
2. **True alpha** -- confirmed in the BMP loader itself, `apps/recorder/bmp.c`. A 32-bit source BMP
   can carry a genuine alpha channel (`bool read_alpha = format & FORMAT_TRANSPARENT;`,
   `bmp.c:519`), but Rockbox does not keep the source's full 8-bit alpha resolution internally -- it
   **packs the alpha channel down to 4 bits per pixel, two pixels per byte**
   (`bmp.c:485-492`: *"pack alpha channel for 2 pixels into 1 byte and negate according to the
   internal alpha channel format"*). That is **16 levels of opacity**, not 256, and the pack/unpack
   happens per blit on that 216 MHz ARM with no hardware compositor. d00k.net's independent account
   -- "true transparent bitmaps are quite costly in terms of resources... modern devices like iPods
   can handle them at larger scales" -- is now explained by a concrete mechanism rather than taken on
   faith: the cost is real, it's per-pixel software packing, and it's why advanced theme authors (the
   same d00k.net, building the "Themify" theme) use it sparingly rather than for whole-screen panels.

**Compositing: two layers, not a stack, and the second one doesn't redraw itself.** Confirmed in
`apps/gui/skin_engine/skin_backdrops.c` (`HAVE_BACKDROP_IMAGE`, `skin_backdrop_set_buffer`/
`skin_backdrop_show`) and in the `%VB` tag (2.2): there is the **Backdrop** (one static image per
screen) and the **Foreground** (everything the skin engine actually redraws each refresh pass).
d00k.net's own description matches the source exactly: *"the Backdrop layer is basically a separate
piece of paper placed underneath... we obviously would not be able to see what is on the sheet
underneath unless we cut out a piece from the sheet on top."* There is no third layer, no arbitrary
stack of translucent panes one can place between backdrop and foreground -- a "layered" look is built
by alpha-blending individual *bitmaps* onto the one foreground over the one backdrop, not by
compositing N independent surfaces.

**Gradients -- yes, flat, axis-aligned.** `%dr`'s two-colour fill (2.2) and the built-in "Bar
(Gradient Colour)" line-selector style (`manual/configure_rockbox/theme_settings.tex`, taking a
Primary and Secondary colour) are both linear gradients with no radial option found anywhere in the
manual or the tag reference.

**Rounded corners -- yes, via 9-patch bitmaps, never a vector radius.** `%x9` (2.2): the corners are
real pixels an artist drew once; the engine stretches the edges and centre. Every rounded rectangle on
a Rockbox screen was decided by a human in an image editor, not computed by the device.

**Blur -- no primitive found.** Not in the manual's tag reference, not in the skin engine source
files read this session (`skin_render.c`, `skin_backdrops.c`, `skin_parser.c` -- not an exhaustive
symbol-by-symbol search, so "none found" rather than "confirmed absent," per the project's own rule
against filling a gap with a guess). The engine can blit a bitmap that was blurred *before* it was
saved; it has no runtime box-blur or gaussian operation over live pixels.

**Animation and frame rate -- there isn't a frame rate, because there isn't a frame clock.** The skin
engine is dirty-region and event-driven, not a compositor with vsync. Every drawable element carries a
refresh class in `apps/gui/skin_engine/skin_render.c:60-102`: `SKIN_REFRESH_STATIC` (drawn once),
`SKIN_REFRESH_DYNAMIC` (redrawn on the player's own periodic UI tick -- a clock, a peak meter,
scrolling text), or `SKIN_REFRESH_ALL` (a full repaint, e.g. on track change). Only elements matching
the current pass's class are touched. Rockbox's own "Performance" setting exposes the practical
consequence as a user-facing tradeoff -- high-performance mode updates the peak meter "as often as
possible," energy-save mode "just often enough to look fluid" -- but no fixed Hz number was found for
either (RESEARCHED, secondary, not independently timed this session). "Animation" in a theme means
`%xd` swapping to a different pre-drawn sub-image when a tag's value changes (the battery/volume/
shuffle icon strips in the cabbiev2 excerpt above), not timeline animation.

### The verdict on "Apple glass"

**Not achievable, in the literal sense iOS/macOS mean it.** That effect is a live, blurred,
saturated sample of whatever is moving *underneath* a panel, recomposited every frame as the content
behind it changes. Rockbox's skin engine has: no blur primitive; no live-content sampling (there is
nothing behind a WPS element for a panel to sample -- the backdrop is one static image, not a moving
scene); and a two-layer compositing model with only bitmap-level alpha, quantized to 16 steps, costed
explicitly as expensive by a theme author who has actually shipped alpha-heavy themes on this
hardware. There is nothing dynamic to refract, and no mechanism to refract it with if there were.

**What gets closest, concretely, and is already a known pattern in that community:**

1. **A pre-rendered backdrop with the blur baked in at design time.** Export a frosted/blurred panel
   from any image editor once, ship it as the `.bmp` backdrop. Static, but indistinguishable from
   "real" blur in a screenshot or at a glance, and costs nothing at runtime -- it's one plain blit.
   This is exactly `research/ROCKBOX.md` section 2.3's own framing applied a second time: "a static
   blurred image is just a bitmap."
2. **True 32-bit-BMP alpha for the handful of elements that genuinely need to sit "in front of" the
   glass** -- a highlight sliver, the now-playing art's frame -- used sparingly, the way Themify's own
   author describes doing it.
3. **9-patch bitmaps (`%x9`)** for the rounded-rectangle panel shapes.
4. **`%dr` two-colour gradients** for the flat sheen or vignette a glass panel often carries, where a
   bitmap would be overkill.
5. **This is not a novel proposal -- it already exists on themes.rockbox.org for this exact device.**
   Searching that gallery for `target=ipod6g` (2.4) surfaced **AMusicPod**, described in its own
   listing as "an Apple Music inspired iPod theme for video and Classic designed to look as if it was
   'Designed by Apple.'" Someone has already attempted precisely the owner's brief, on this exact
   hardware, within these exact constraints. Fetching and critiquing that theme's actual `.wps`/`.cfg`
   would be the fastest way to see how close the pre-rendered-backdrop approach gets in practice --
   **not done this session**, flagged as the obvious next research step rather than guessed at.

## 2.4 Theme distribution

**themes.rockbox.org**, filtered by device target string (`?target=ipod6g` for the Classic -- found
real and populated via search, after the gallery's own search UI returned an Anubis page; several
real, dated entries confirmed: XPloRR 2016, SlateyPod3 2024, FleshAndBones, AMusicPod, iRB_Classic).
The manual's own per-target link list (`manual/configure_rockbox/theme_settings.tex`) is missing an
`\opt{ipod6g}` entry among its two dozen other targets -- an apparent documentation gap, now resolved
by the gallery itself clearly existing and working for this target; not chased further.

**Submission format**, from the themesite's own upload requirements (RESEARCHED, secondary): a `.zip`
whose top level is a `.rockbox` folder containing whatever subset of `themes/`, `wps/`, `backdrops/`,
`fonts/`, `icons/` the theme needs, mirroring the on-device layout in 2.1 exactly.

**Programmatic generation is not a stretch -- the format is plain text and community tooling already
manipulates it mechanically.** `.wps`/`.sbs`/`.cfg` are UTF-8 text in the tag language above; nothing
about them requires the official Qt `utils/themeeditor` GUI. Confirmed existing precedent: the
**Rockbox Theme Rescaler** (`github.com/TmosDHD/Rockbox-Theme-Rescaler`), a browser-based tool that
"automatically converts Rockbox themes between 240p and 360p" by rescaling `.wps`/`.sbs`/`.fms`
coordinates and `.fnt` bitmap fonts programmatically -- exactly the kind of mechanical, scripted
transform a saltpod-side generator would also be doing, just against saltpod's own token values
instead of a resolution ratio.

## 2.5 Could saltpod generate a Rockbox theme from `publish/DESIGN.md`? (PROPOSED)

`publish/DESIGN.md` is the one asset that makes this question answerable rather than speculative: it
names every colour, radius, and row shape the web page uses as an enumerated token, not an implicit
style. Assessed token family by token family, against what 2.2/2.3 just established:

| `DESIGN.md` token family | Rockbox target | fit |
|---|---|---|
| `--ground`, `--ink` | theme-settings "Background Colour" / "Foreground Colour" | **direct** -- same two-colour model, no new mechanism needed |
| `--sel-hi` / `--sel-lo` (law 2: "where you are," hi→lo gradient) | the "Bar (Gradient Colour)" line-selector, which already takes a Primary and Secondary colour for a gradient bar | **direct, almost suspiciously so** -- the same hi-to-lo direction law 2 describes is a named Rockbox setting, not something to invent |
| `--dim`, `--faint`, `--panel`, `--raised` (white at .55/.22/.05/.09 alpha) | no runtime alpha for flat fills/text (2.3) | **one-time offline blend** -- composite each against the known `--ground` once, at generation time, and ship the resulting flat RGB565 colour. Mechanical, not a runtime cost, because both inputs are constants |
| `--orange` (law 2: "what is happening now") | a literal colour baked into a generated `%Vf`/`%Vb` or `%dr` call per element | **direct** -- one substitution per generated tag |
| radius ladder (`--r-xs/sm/md/pill`) | 9-patch bitmaps (`%x9`) | **needs a small new renderer** -- not hard, but real: an offline step that rasterises one rounded-rect-plus-border bitmap per radius actually used, once, reused across the generated theme |
| three row shapes (`.row`/`.col`/`.drow`) and the pane anatomy (law 6) | `%V` viewport placement -- hand-placed pixel rectangles, no flexbox/grid equivalent | **the real work** -- a generator has to compute literal `%V(x,y,w,h)` coordinates for every instance, which means replicating a simplified, static version of the page's own layout logic, not swapping tokens |
| type scale (`--fs-*`, `--face`/`--mono` font stacks) | Rockbox's own bitmap `.fnt` format, not TTF/web fonts | **does not transfer** -- needs a font-conversion step this session did not investigate; flagged as a real gap in the proposal, not glossed over |

**Net assessment:** the colour layer maps almost exactly onto existing Rockbox primitives, with one
mechanical offline step (alpha-blending `--dim`/`--faint`/`--panel`/`--raised` against `--ground`)
standing in for runtime alpha the engine can't afford. The radius ladder needs a small, boundable
bitmap-rendering step (four named radii, reused everywhere). The row/pane geometry is the genuinely
new piece of engineering -- a static layout compiler, not a token swap -- and the type scale does not
cross over at all without separate font work. **This is plausible, not small, and firmly PROPOSED.**
If it is built, the right framing is not "saltpod learns to draw a Rockbox theme" but "`DESIGN.md`'s
tokens become the one implementation, and the web page's CSS and a new Rockbox-skin generator become
its two adapters" -- the exact shape `publish/CONTRIBUTING.md` already names for a different pair of
clients, applied one level up, to renderers instead of transports. See Part 3.

---

# Part 3 -- the adapter shape (PROPOSED)

## The `target` value, and where it lives

A device targets `'apple'` (today's only behaviour), `'apple+rockbox'` (Shape A: mirror, nothing
about the Apple-firmware sync changes), or `'rockbox'` (Shape B: a second `new_location()` and a
different `AS_IS`/`CONVERT` split, per `research/ROCKBOX.md` section 2.4). It belongs beside `mount`
and `firewire_guid` in `data/device.json`, read by `config.load()` the same way those already are
(`src/saltpod/config.py:17-30`, the same `d.setdefault(...)` pattern that already gives `mount` a
default). A device's target is a fact about that device the owner states once, the same way its GUID
is -- not something probed at runtime, because "does this iPod have Rockbox installed" is not safe to
answer by poking `.rockbox/` on someone else's device as a side effect of a plan.

## Why this is "platform.py-shaped" but not a `platform.py` capability

The owner's own framing -- "rockbox is an adaptor like native ipod software" -- is right about the
*shape*: one operation (`sync`), multiple implementations, nothing above the choice point caring which
ran, exactly `platform.py`'s own pattern (`src/saltpod/platform.py:78-120`: `to_alac` picks
`afconvert` or `ffmpeg`, `resize_image` picks `sips` or `ffmpeg`, caller never branches). The honest
difference: `platform.py`'s choices are *detected* (`shutil.which('ffmpeg')`, an actual DiskArbitration
session probed and torn down) because they're questions about *this machine's* capabilities, safe to
answer by looking. A device's target is a fact about *that iPod*, supplied once by the person who owns
it, the same way `firewire_guid` is -- config-selected, not capability-probed. Same pattern, different
kind of input.

## What changes, what doesn't

| module | change |
|---|---|
| `config.py` | one new field, `target`, defaulted to `'apple'` |
| `apply.py` | `_sync()`/`_plan()` branch on `target` for playlist output (append the `.m3u8` render after the existing playlist loop) and, for Shape B only, `new_location()` and the `AS_IS`/`CONVERT` membership |
| new, small module (e.g. `rockbox_playlist.py`) | pure function: a device track's location + metadata -> an `.m3u8`/Extended-M3U8 string. Testable without a device, per `research/ROCKBOX.md` section 2.5's own estimate |
| `tags.py` | gains an artwork-carrying path only if 1.6's embedded-art-through-conversion fix is done -- worth doing regardless of `target`, since it benefits Apple firmware's own `ArtworkDB` gap too (`ITUNES-PARITY.md` section 6) |
| `cli.py` | `plan`/`sync` gain an optional `--target` override, the same style as the existing `--mount` override (`cli.py:144-151`), not a new subcommand |
| **unchanged**: `curate.py`'s `OPS` dict, `ipod_edit.py`, `itunesdb_write.py`, `hash58.py`, `state.py`'s `collection_order` | a target is a parameter on an existing operation, not a new one -- no new verb, no new `OPS` entry, consistent with `publish/CONTRIBUTING.md`'s "Adding a verb is not optional" rule applying only to things that *are* new verbs |

**It reaches both callers for free, and the mechanism is already more direct than `OPS`.** The page's
"Sync" button does not call `apply.sync()` in-process at all -- `curate.py`'s `/api/action` handler,
case `a == 'sync'`, shells out to `python3 -c "... from saltpod.cli import main; sys.exit(main(['sync', ...]))"`
as a subprocess (`curate.py:2110-2129`). A `--target` flag added to `cli.py`'s `sync`/`plan`
subcommands is therefore available to the terminal *and* the page the moment `_action()`'s argument
list forwards `body.get('target')` -- the page runs the literal same CLI a terminal user would, not a
parallel code path that happens to agree with it today.

## Cost

**Shape A** (mirror, Apple-firmware sync unchanged): one config field, one new small pure-function
module (~30-40 lines), one call site in `_sync()`, one CLI flag. `research/ROCKBOX.md` section 2.5's
estimate stands, with the path corrected to `.rockbox/Playlists/` per 1.4.

**Shape B** (Rockbox-primary): additionally touches `new_location()`, the `AS_IS`/`CONVERT`
membership, and `convert_to_alac()`'s call sites -- genuinely days, not hours, by the same estimate
`research/ROCKBOX.md` section 2.5 already gave.

**The theme generator (2.5)**, costed separately because it is a different kind of work from either
sync shape: a small offline colour-blend step (hours); a small, reusable 9-patch bitmap renderer
(bounded -- four radii, used everywhere); and a static layout compiler that replicates saltpod's three
row shapes and pane anatomy as literal `%V(x,y,w,h)` coordinates -- the one piece of this whole
document that is genuinely open-ended rather than bounded, because it is a second renderer for the
same design system, not a parameter on an existing one. Font conversion (2.5's type-scale row) is
unscoped entirely -- not investigated enough this session to estimate honestly.
