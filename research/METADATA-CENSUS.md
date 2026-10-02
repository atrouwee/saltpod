# Full metadata census: what else is sitting in the files

**Status: MEASURED on this machine, 2026-10-02.** 4,050 of 4,050 files in
`data/local/index.json` scanned, 0 failed. Every reader used is the one
already in `src/saltpod/tags.py` -- `_id3_read_tag`, `_aiff_tag`,
`_flac_blocks`/`_vorbis_parse`, `_mp4_ilst`/`_mp4_children`/`_mp4_data`,
`read_wav`'s chunk walk -- nothing here is a second parser. The scan is
read-only, touched no file on the drive, and ran in 16-18 seconds with a
24-way thread pool. The raw counts behind every table below are in
`data/local/metadata_census.json`, which is gitignored (`data/local/*.json`)
and stays local -- query it directly rather than re-running the scan.

## Why this exists

A targeted scan for podcast frames found that 11 files still carry `PCST`,
`WFED`, `TGID`, `TCAT`, `TDES` and `TDRL` from an RSS feed the owner ran in
2011 -- metadata nobody knew was there, which immediately settled a design
question (podcasts classify themselves, no heuristic needed, see
`publish/PLAN-PARITY.md`). The owner's framing: *"This to me signals a full
metadata scan for all tracks i have so we might leverage that in future
based on findings from it."* This is that scan: every container, every
file, every frame/atom/key, not just the ones already known to exist.

## 1. What was scanned

| ext | files | tag system |
|---|---|---|
| .mp3 | 2,156 | ID3v2 at byte 0 |
| .wav | 724 | RIFF LIST/INFO, and (see below) an embedded ID3v2 chunk on half of them |
| .aif | 482 | ID3v2 inside a FORM `ID3 ` chunk |
| .aiff | 327 | ID3v2 inside a FORM `ID3 ` chunk |
| .flac | 244 | Vorbis comment block |
| .m4a | 117 | `moov/udta/meta/ilst` atoms |
| **total** | **4,050** | |

## 2. mp3 / aif / aiff -- ID3v2

### 2.1 Tag version and parse health

| container | v2.2 | v2.3 | v2.4 | no tag | did not parse cleanly |
|---|---|---|---|---|---|
| .mp3 | 107 | 1,685 | 177 | 187 | 15 |
| .aif | 0 | 0 | 480 | 2 | 0 |
| .aiff | 0 | 0 | 327 | 0 | 0 |
| .wav (embedded `id3 `/`ID3 ` chunk) | 0 | 226 | 142 | n/a | 0 |

**807 of 809 .aif+.aiff carry an ID3v2.4 tag, 2 carry none** -- this is an
exact match to the count already in `tags.py`'s own header comment
(`FORM/AIFF 809 of 809`, `ID3 chunk, ID3v2.4  807 (2 carry no tag at all)`),
measured independently here. Good cross-check that the reader hasn't
drifted.

v2.2 is 107/2156 mp3s (5.0%), slightly higher than the `tags.py` comment's
sampled estimate of 47/600 (7.8%) -- consistent, different sample, now a
full-population number rather than an estimate. These 107 are the ones
`write_id3` refuses rather than silently drops frames from (`write` raises
`TagError` for v2.2).

"Did not parse cleanly" is `tags.py`'s own `clean` flag from
`_id3_read_tag` -- it covers both "resynchronised and recovered" and "gave
up and stopped" without distinguishing them, by design (that distinction
lives inside the function this census does not re-implement). 15 mp3s hit
it, 0.7% of the format. All 15 still returned usable frames; none caused a
scan failure.

**Not shown as "no tag": `tags.py`'s own header comment** says 581 files
across the library have none of the seven managed fields populated
(`untagged` in `index.json`) -- 186 mp3, 366 wav, 21 m4a, 8 aif, 0 flac.
That is a different measurement from the "no tag chunk at all" column
above: a file can carry a v2.3 tag that is all `TXXX`/`COMM` and no
`TIT2`/`TPE1`/etc, which counts as untagged there and tagged here. Both are
correct; they answer different questions. Not recomputed in this census.

### 2.2 Every frame found, simple frames (45 of 72 distinct ids; file count >= 10)

| frame | occurrences | files | containers | kind | example |
|---|---|---|---|---|---|
| TIT2 | 3,113 | 3,113 | mp3 1948, wav 359, aif 479, aiff 327 | title | read today |
| TPE1 | 3,039 | 3,039 | mp3 1880, wav 358, aif 474, aiff 327 | artist | read today |
| TALB | 2,825 | 2,825 | mp3 1709, wav 357, aif 432, aiff 327 | album | read today |
| TCON | 2,801 | 2,801 | mp3 1685, wav 357, aif 432, aiff 327 | genre | read today |
| APIC | 2,169 | 1,553 | mp3 627, aif 589, aiff 757, wav 196 | cover art | read today (via `has_art`/`art_bytes`) |
| TRCK | 1,842 | 1,842 | mp3 1289, wav 226, aiff 327 | track number | read today |
| TYER | 1,724 | 1,724 | mp3 1498, wav 226 | year | read today |
| TPUB | 1,253 | 1,253 | mp3 363, aif 432, aiff 327, wav 131 | publisher/label | **unexploited** |
| TENC | 1,116 | 1,116 | mp3 789, aiff 327 | encoded-by tool | noise |
| TKEY | 1,058 | 1,058 | mp3 123, aif 477, aiff 327, wav 131 | musical key | **unexploited** |
| TBPM | 1,022 | 1,022 | mp3 132, aif 432, aiff 327, wav 131 | tempo | **unexploited** |
| TDRL | 1,014 | 1,014 | mp3 124, aif 432, aiff 327, wav 131 | release date | read today (as year) |
| TDOR | 1,004 | 1,004 | mp3 114, aif 432, aiff 327, wav 131 | original release date | deliberately not read (`tags.py` keeps it distinct from TDRL) |
| TAUT | 820 | 820 | mp3 130, aif 479, aiff 78, wav 133 | nonstandard; literal value is always the word "TRACK" | noise |
| TPE2 | 811 | 811 | mp3 811 only -- 0 in aif/aiff | album artist | read today, **mp3-only in practice** |
| TSRC | 790 | 790 | mp3 89, aif 370, aiff 253, wav 78 | ISRC | **unexploited** |
| TKY2 | 754 | 754 | mp3 113, aif 432, aiff 78, wav 131 | musical key, second notation | **unexploited** |
| TDRC | 586 | 586 | mp3 255, aiff 327, aif 4 | recording date | read today (as year) |
| TSSE | 516 | 516 | mp3 516 | encoder settings string | noise |
| UFID (no owner recovered) | 441 | 441 | aiff 176, mp3 265 | identifier, malformed (see 2.3) | **unexploited**, needs repair |
| TCOP | 391 | 391 | mp3 391 | copyright | **unexploited** |
| TLAN | 341 | 341 | mp3 341 | language | **unexploited**, low value |
| TFLT | 328 | 328 | mp3 1, aiff 327 | file type | noise (redundant with extension) |
| WOAF | 327 | 327 | aiff 327 | official audio file webpage (Beatport URL) | **unexploited** |
| WPUB | 327 | 327 | aiff 327 | publisher webpage (Beatport label URL) | **unexploited** |
| TIT1 | 318 | 318 | mp3 10, aiff 308 | content group (label/series name, e.g. "The Fat! Club") | low value |
| TPE4 | 227 | 227 | mp3 27, aiff 34, aif 128, wav 38 | remixer / modified-by | **unexploited** |
| TCOM | 199 | 199 | mp3 199 | composer | **unexploited** |
| OWNE | 142 | 142 | mp3 14, aiff 76, aif 5, wav 47 | iTunes purchase record (price/date/seller) | low value, see 2.3 |
| TDAT | 114 | 114 | mp3 114 | v2.3 date (DDMM) | noise, superseded by TDRC/TDRL |
| TPOS | 108 | 108 | mp3 108 | disc number | **unexploited** |
| TOPE | 96 | 96 | mp3 96 | original artist | low value |
| TLEN | 89 | 89 | mp3 89 | duration in ms | noise, already known from the audio |
| WXXX | 82 | 82 | mp3 82 | user URL frame | 0 distinct descriptions survived subkeying -- see note below |
| MCDI | 53 | 53 | mp3 53 | CD table-of-contents, binary | noise |
| TMED | 47 | 47 | mp3 47 | media type (e.g. CD) | noise |
| GEO | 13 | 3 | mp3 13 | v2.2 GEOB, mime `application/octet-stream` | noise, v2.2, unmapped |
| TIT3 | 12 | 12 | mp3 12 | subtitle | low value |
| TPE3 | 12 | 12 | mp3 12 | conductor | low value |
| PCST | 11 | 11 | mp3 11 | podcast flag | read today (the DeepCast classifier) |
| TDES | 11 | 11 | mp3 11 | podcast episode description | **unexploited** |
| TGID | 11 | 11 | mp3 11 | podcast episode GUID | **unexploited** |
| WFED | 11 | 11 | mp3 11 | podcast RSS feed URL | read today (the DeepCast classifier) |
| TCAT | 10 | 10 | mp3 10 | podcast category | **unexploited** |
| TKWD | 10 | 10 | mp3 10 | podcast keywords | **unexploited**, new even to `PLAN-PARITY.md` |

27 more frame ids appear on 1-9 files each, 69 occurrences total: `TCMP`
(iTunes compilation flag, 7), `RVA`/`RVAD` (old relative-volume frames, 9
combined), `TBP` (v2.2 BPM, 5), `TDEN`/`TDTG`/`TORY`/`TIME`/`TDAT`-family
stragglers, `POPM` (3, see section 7), `TSS`/`TSA`/`TSOA`/`TSOT`/`TSOP`/
`TSO2`/`TSIZ` (sort fields and v2.2 stragglers), `ULT`/`UFI`/`TT1`/`TLE`/
`TCP` (more v2.2 ids not in `tags.py`'s `_V22` upconvert table, so they
survive under their 3-character spelling), `USER`, `TEXT`, `TOLY`, `TRSN`,
and one single-file `RGAD` (ReplayGain Adjustment, an old non-standard
ID3 frame -- see section 7). Full list with exact counts is in the JSON.

**WXXX note:** 82 occurrences, but every one decoded to an empty
description, so no per-description breakdown survived -- the URL itself is
the only content and it was not separately characterised here.

### 2.3 Container frames, broken out by what they actually hold

Four frame ids are generic containers whose real name is a sub-field
inside the payload -- `TXXX`'s description, `COMM`'s description, `PRIV`'s
owner, `UFID`'s owner, `GEOB`'s content description. Treating them as one
undifferentiated bucket (the obvious first pass) hides most of what is
interesting, the same way reporting "----" without decoding `mean`/`name`
would for m4a. Broken out:

**TXXX (34 distinct descriptions, 987 occurrences, 521 files)**

| description | files | example |
|---|---|---|
| Engineer | 284 | (always empty) |
| Rip date | 114 | 2007-06-05 |
| Source | 114 | CDEP |
| Release type | 114 | Normal Release |
| Ripping tool | 74 | EAC |
| ENCODEDBY | 39 | Vidiot rip |
| PZTagEditor Info | 37 | This tag done at 27/07/2002 22:10:35. Version 4.30.0.6 |
| BPM | 37 | CD_m (not a number -- see below) |
| ENSEMBLE | 36 | VID |
| URL | 35 | mono (also not a URL) |
| Supplier | 32 | Team ZzZz |
| TraktorRemixer | 19 | Marc Romboy |
| GN/ExtData | 17 | Gracenote extended-data blob, base64-looking |
| Catalog # | 4 | AC025 |
| major_brand / minor_version / compatible_brands | 4 each | MP4 container fields duplicated into ID3 by some converter |
| Tagging tim[e] | 3 | garbled UTF-16, truncated description |
| replaygain_track_gain | 1 | -6.00 dB |
| replaygain_track_peak | 1 | 1.000000 |
| replaygain_album_gain | 1 | -6.00 dB |
| replaygain_album_peak | 1 | 1.000000 |
| CREATED, SongRights, Overlay | 1 each | one-offs |

`TXXX:BPM` and `TXXX:URL` are both noise -- the first holds "CD_m" and
similar non-numeric junk on all 37 files, the second holds "mono" rather
than a URL on all 35. Both look like a tagger wrote the wrong value into
the wrong custom field. **`TXXX:replaygain_*` is real** -- one single file
carries a complete four-value ReplayGain set (track/album gain and peak)
inside ID3, which is the ID3-side equivalent of the FLAC/Vorbis
`REPLAYGAIN_*` tags checked for in section 9.

**PRIV (13 distinct owners, 1,560 occurrences, 349 files)**

| owner | files | example |
|---|---|---|
| WM/MediaClassSecondaryID | 202 | 16 bytes, `0000000000000000` |
| WM/MediaClassPrimaryID | 202 | 16 bytes |
| WM/UniqueFileIdentifier | 191 | 114 bytes |
| WM/WMContentID | 180 | 16 bytes |
| WM/WMCollectionID | 180 | 16 bytes |
| WM/WMCollectionGroupID | 180 | 16 bytes |
| WM/Provider | 180 | 8 bytes |
| http://www.cdtag.com | 112 | 6 bytes |
| **PeakValue** | 56 | 4 bytes |
| **AverageLevel** | 56 | 4 bytes |
| XMP | 15 | 2,901 bytes, Adobe XMP packet (starts `<?xpacket`) |
| **TRAKTOR4** | 5 | 35,645 bytes, binary |
| WM/Mood | 1 | 30 bytes |

The seven `WM/*` owners are Windows Media Player library-sync bookkeeping
(DRM collection/content GUIDs) -- noise, not musically useful, left from a
library that was once managed in WMP. **`PeakValue`/`AverageLevel`
(56 files, always paired) are WMP's own loudness-leveling values** -- the
Windows Media equivalent of Apple's Sound Check, same idea as `iTunNORM`
in section 7, not currently decoded past "4 bytes present." **`TRAKTOR4`
(5 files) is Native Instruments Traktor's own binary blob** -- beatgrid
and cue-point data a DJ would actually want, at up to 35 KB per file, in
an undocumented proprietary format. `http://www.cdtag.com` is a
defunct 2000s CD-lookup service's 6-byte disc id, noise. `XMP` is Adobe's
metadata format wrapped in `PRIV`, present but not parsed here.

**COMM (13 distinct descriptions, 2,349 occurrences, 1,801 files)**

| description | files | example |
|---|---|---|
| (plain, empty description) | 1,625 | free-text comment, e.g. catalog numbers, ripper credits |
| ID3v1 | 280 | migrated ID3v1 30-byte comment |
| **iTunNORM** | 117 | see section 7 |
| ID3v1 Comment | 93 | same migration, different tagger's description string |
| **iTunPGAP** | 81 | gapless-playback flag, "0" or "1" |
| **iTunSMPB** | 73 | see section 8 |
| iTunes_CDDB_IDs | 22 | legacy FreeDB disc id |
| c0 | 16 | undocumented, looks like a truncated description |
| MusicMatch_Preference | 3 | "Excellent" -- 2003-era MusicMatch Jukebox rating word |
| iTunes_CDDB_1, iTunes_CDDB_TrackNumber | 2 each | legacy FreeDB |
| TagScanner, MusicMatch_Mood | 1 each | one-offs; `MusicMatch_Mood` literally holds "DailyTunez.com" |

**UFID (73 distinct owners, 1,317 occurrences, 1,314 files)**

| owner (as recovered) | files | identifies |
|---|---|---|
| http://www.beatport.com | 770 | Beatport's own track id, e.g. `track-633537` |
| (empty owner, raw `\x03track-NNNNNN` as the identifier bytes) | 441 | the same Beatport track id, written by a different Beatport batch with no owner string at all |
| (owner holds the stray bytes, identifier empty -- see below) | 54 occurrences / 51 files | the same Beatport track id again, a third encoding |
| http://www.cddb.com/id3/taginfo1.html | 17 | FreeDB/CDDB disc+track hash |
| http://musicbrainz.org | 16 | placeholder frame, **identifier field is empty on all 16** |
| everything else | ~19 occurrences | assorted one-offs, not itemized |

**This is a real anomaly, not just trivia: Beatport has written the same
"track id" fact in at least three incompatible byte layouts across
different download batches in this library** (confirmed by reading raw
bytes, not inferred): a clean `owner="http://www.beatport.com"` +
`identifier=b"track-NNNNNN"`; an empty owner with the identifier itself
starting `\x03track-NNNNNN`; and a third shape where a stray `" \x03"`
prefix lands inside the owner field and leaves no identifier at all. A
reader built against only the first shape -- the obvious one to find first
-- would silently miss roughly 492 of the 1,262 Beatport-pattern UFIDs.
All three still carry the same usable Beatport catalogue number once the
three shapes are known.

**GEOB (7 distinct descriptions, 10 occurrences, 5 files)**

| description | files | size | source |
|---|---|---|---|
| SfMarkers | 4 | 12 bytes | Sound Forge cue markers |
| SfAcidChunk | 1 | 24 bytes | Sound Forge/ACIDized loop data |
| SfCDInfo | 1 | 124 bytes | Sound Forge CD-ripping info |
| **Serato Overview** | 1 | 3,842 bytes | Serato DJ waveform overview |
| **Serato Autotags** | 1 | 22 bytes | Serato auto-analysis (gain/BPM/key) |
| **Serato Markers_** | 1 | 318 bytes | Serato hot cues/loops |
| **Serato Offsets_** | 1 | 14,975 bytes | Serato beatgrid offsets |

Exactly one file in the whole library has been fully analysed by Serato DJ
and carries its complete cue/beatgrid/waveform set, embedded via `GEOB`.
Not generalisable (n=1), but a real example of how much DJ-software state
can live inside a plain mp3.

## 3. m4a -- `ilst` atoms

117/117 files have a `moov/udta/meta/ilst` tree (matches `tags.py`'s own
survey). 40 distinct atom types found, including freeform (`----`)
sub-atoms decoded by their `mean`/`name` pair rather than reported as a
single undifferentiated "----".

| atom | files | kind | example |
|---|---|---|---|
| **com.apple.iTunes:iTunSMPB** | 117 (100%) | freeform, gapless encoder padding | see section 8 |
| **com.apple.iTunes:iTunNORM** | 97 (82.9%) | freeform, Sound Check | see section 7 |
| `©nam` | 97 | title | read today |
| `cpil` | 97 | compilation flag (10 set to 1, 87 to 0) | **unexploited** |
| `©ART` | 96 | artist | read today |
| `aART` | 96 | album artist | read today |
| `pgap` | 96 | gapless flag (6 set to 1, 90 to 0) | **unexploited** |
| `©day` | 96 | year (full timestamp, e.g. `2010-02-23T08:00:00Z`) | read today (as year) |
| `©alb` | 94 | album | read today |
| `trkn` | 94 | track/total | read today |
| `cnID` | 94 | iTunes Store content id (integer) | noise, dead store |
| `plID` | 94 | iTunes Store collection/album id (integer) | noise |
| `stik` | 94 | media kind enum | **unexploited** -- this is the atom that would carry podcast/audiobook classification on m4a, currently always music |
| `purd` | 94 | purchase date/time | low value |
| `apID` | 93 | Apple ID used for the purchase (email-shaped) | present; not reproduced here -- see note below |
| `cprt` | 93 | copyright | **unexploited** |
| `rtng` | 93 | content advisory rating enum, all 0 (unrated) | noise |
| `atID`, `geID`, `sfID`, `cmID` | 93/93/93/93 | more Store catalogue integers (`sfID`=143441 is Apple's own US storefront id) | noise |
| `ownr` | 85 | Apple ID account name on the purchase -- all 85 carry the owner's real name in plaintext | confirms these as the owner's own purchases, AND is personal data riding inside 85 files |
| **`xid `** | 84 | `vendor:isrc:CODE`, e.g. `TuneCore:isrc:AUWB21013009` | **unexploited**, an ISRC source for m4a, see section 7 |
| `©wrt` | 80 | composer/writer credit | **unexploited** |
| `cmID` | 80 | (listed above) | |
| `gnre` | 61 | ID3v1-style numeric genre | read today |
| `soal`/`soar`/`sonm`/`soco`/`soaa` | 47/44/41/25/5 | sort-name variants (album/artist/title/composer/album-artist) | low value, cosmetic |
| `©gen` | 33 | genre (free text) | read today |
| `disk` | 23 | disc/total | **unexploited** |
| `©cmt` | 22 | comment | low value |
| `covr` | 11 | embedded cover | read today (via `art_bytes`) |
| `akID` | 8 | Store account type | noise |
| `com.apple.iTunes:iTunMOVI` | 8 | an embedded plist (cast/studio for a video-flavoured purchase) | low value here (this is a music library) |
| `tmpo` | 4 | tempo -- 1 real value (125), 3 at 0 | **unexploited but nearly absent**, see section 7 |
| `©too` | 3 | encoder tool string | noise |
| `com.apple.iTunes:Encoding Params` | 3 | binary encoder parameters | noise |
| `flvr` | 1 | encoder flavour string | noise |

**`apID` (93 files) holds a real email address** -- the Apple ID the
purchase was made under. Not reproduced verbatim here because on at least
one file it is not the owner's own address, i.e. it can identify a third
party incidentally captured in a purchased track's metadata; the field and
its count are real, the value is in `metadata_census.json` for anyone
querying locally. `ownr` (85 files), by contrast, is the owner's own name
and is reproduced above.

No m4a file carries the lower-case podcast atoms (`pcst`, `purl`, `egid`,
`catg`, `desc`/`ldes`) that `PLAN-PARITY.md` names as the MP4 equivalents
of the mp3 podcast frames -- consistent with that document's own count of
zero m4a podcasts in the library today.

## 4. flac -- metadata blocks and Vorbis comments

All 244 files carry exactly `STREAMINFO`, `PADDING`, `SEEKTABLE`,
`VORBIS_COMMENT` -- no `PICTURE` block on any of them (matches `tags.py`'s
own note that none of the 244 FLACs carry art), no `APPLICATION`, no
`CUESHEET`.

| Vorbis comment key | files | example |
|---|---|---|
| ARTIST | 244 | The Beatles |
| TITLE | 244 | A Hard Day's Night |
| ALBUM | 244 | A Hard Day's Night (2009 Stereo Remaster) |
| DATE | 244 | 2009 |
| TRACKNUMBER | 244 | 01 |
| GENRE | 244 | Pop |
| COMMENT | 18 | "EAC FLAC -8" |

Only 7 distinct keys in the entire format -- every FLAC in this library
was tagged by the same convention (Exact Audio Copy), with none of the
variety mp3/aif/aiff show. **No `REPLAYGAIN_*` key anywhere** (checked
explicitly, section 9).

**Checked the 18-file wrinkle `tags.py` already flags** (a leading ID3v2
tag before the `fLaC` magic, "tagged by some other program's convention"):
confirmed exactly 18 files, matching that count exactly. Their ID3 frames
are `TALB TCON TENC TIT2 TLEN TPE1 TRCK TSSE TYER COMM MCDI` -- the same
facts already in the Vorbis comment block, no `APIC`, nothing new. **This
closes that question: the leading ID3 tag on those 18 files is fully
redundant, not a second source of information.**

## 5. wav -- RIFF chunks

| chunk | files | notes |
|---|---|---|
| `fmt `, `data` | 724 | every file, as required |
| `LIST` | 243 | 242 are `INFO` sub-type, 1 is an empty placeholder `LIST` chunk subtyped `ID3 ` with zero bytes of content |
| `id3 ` | 226 | lower-case, ID3v2.3 |
| `ID3 ` | 142 | upper-case, ID3v2.4 |
| `DISP` | 6 | legacy Windows "Display" chunk (caption/icon) |
| `_PMX` | 6 | not decoded, likely a DAW-specific chunk |
| `Cr8r` | 2 | Adobe Audition/Soundbooth creator chunk |
| `fact` | 2 | standard non-PCM sample-count chunk |
| `JUNK` | 1 | standard alignment padding |
| `<pre` (anomalous) | 15 | see section 6 |

| LIST/INFO field | files | example |
|---|---|---|
| INAM (title) | 241 | read today |
| ICRD (year) | 231 | read today |
| IART (artist) | 230 | read today |
| IGNR (genre) | 230 | read today |
| IPRD (album) | 226 | read today |
| ITRK (track) | 226 | read today, non-standard but round-trips |
| NITR (undocumented) | 11 | see section 6 |
| ISFT (encoder software) | 5 | noise |
| ICMT (comment) | 4 | low value |
| IENG (engineer) | 4 | low value |
| ICOP (copyright) | 4 | **unexploited** |

**368 of 724 WAV files (50.8%) carry an embedded ID3v2 chunk, which
`read_wav` never looks at.** `read_wav` only reads `LIST/INFO`. The ID3
chunk on these files carries the same seven fields (`TIT2 TPE1 TALB TCON
TRCK TYER`, plus `TPUB TKEY TBPM TDRL TDOR TAUT TSRC TKY2 TPE4 OWNE`, all
in the tables above under the `wav` column) PLUS artwork: **196 of the 368
carry an `APIC` frame that `has_art`/`art_bytes` do not check for on WAV
at all** (those functions only look inside a WAV's `id3 `/`ID3 ` chunk for
art if they already special-cased WAV -- they do, per the `has_art`
docstring, so this is confirmed read, not a gap; verified by cross-checking
that `has_art` does walk the WAV `id3 ` chunk). What is NOT read from this
chunk is everything beyond the seven fields: `TPUB`, `TKEY`, `TBPM`,
`TSRC`, `TPE4`, `TDOR`, `TAUT`, `OWNE` all sit inside these 368 WAV id3
chunks exactly as unexploited as their mp3/aiff counterparts.

**Dual-source disagreement, WAV LIST/INFO vs its own embedded ID3 chunk:**
checked all 368 files that carry both; 4 disagree, all on `title`, all the
same pattern -- the `INFO` chunk holds the bare Beatport filename
(`1930521_Emotion_Original_Mix`) and the ID3 chunk holds the proper title
(`Emotion (Original Mix)`). `read_wav` reads the worse of the two sources
on these 4 files.

## 6. Anomalies, quantified

| anomaly | count | detail |
|---|---|---|
| mp3 tags that did not parse cleanly (resync or incomplete) | 15 files | section 2.1 |
| mp3 v2.2 tags (refused by the writer, not a reader problem) | 107 files | section 2.1 |
| Beatport UFID written in 3 incompatible byte layouts | 1,262 occurrences across the 3 shapes | section 2.3 |
| ID3 text frames present but decoding to an empty string | 30 occurrences across 12 frame ids (TYER 6, TENC 4, TCOM 4, TCOP 3, TOPE 3, TPE2 3, TCON 2, TRCK 1, TALB 1, TSRC 1, TBPM 1, TPOS 1) | the frame exists, the tagger wrote nothing into it |
| TYER/TDRC/TDRL disagree on the YEAR ITSELF (not just precision) within one file | 14 files | all Beatport Acapella/remix files, e.g. TDRC "2007" vs TDRL "2012-07-23" |
| ID3 frames with an invalid text-encoding byte | 0 | checked explicitly, none found |
| Duplicate "should be singular" frame id in one file (e.g. two TIT2) | 0 | checked explicitly, none found |
| WAV LIST/INFO vs embedded ID3 disagreement | 4 files | section 5 |
| WAV pseudo-chunk `<pre` after `data`, size field reads as garbage | 15 files | not real RIFF data -- the bytes decode as leftover web-server/SQL debug text (`"...doQuery\nSQL-Statement: select download_slots.track_id..."`), meaning these particular Beatport WAV downloads have corrupted/incomplete payloads past the declared `data` chunk. Outside metadata scope, but worth knowing for audio-integrity work. |
| WAV with an empty placeholder `LIST` chunk subtyped `ID3 ` | 1 file | zero bytes of content, nothing to read |
| FLAC files with a redundant leading ID3v2 tag | 18 files | fully redundant with the Vorbis comment, confirmed, section 4 |
| TSRC values that are not ISRC-shaped | 3 of 790 | "" (empty), "DailyTunez.com", "4UsOnly.biz" -- download-site branding stuffed into the wrong field |

## 7. Specifically checked: iTunNORM, TBPM/TKEY, POPM/PCNT

**`iTunNORM` (Apple Sound Check).** Present on 117/2156 mp3 (5.4%, as a
`COMM` frame with description "iTunNORM") and 97/117 m4a (82.9%, as the
`----:com.apple.iTunes:iTunNORM` freeform atom). Zero on aif, aiff, wav,
flac. Combined: **214 of 4,050 files (5.3%)** already carry Apple's own
computed loudness-normalisation values. One decoded example (mp3):

    [eng] iTunNORM=000007D3 00000792 00005D76 000054B1 0001E224
          0003A71A 0000A107 00009B35 0000AA4E 0000E8A7

This is NOT widely present enough to replace the planned ffmpeg loudness
pass (`publish/PLAN-PARITY.md`'s -18 LUFS work) -- 94.7% of the library has
no Sound Check value at all, and the two numbers are not even on the same
scale (`iTunNORM` is Apple's old per-channel volume-adjustment format, not
LUFS). But for the 214 files that do have it, the value is free, Apple's
own, and currently thrown away. Worth a sanity-check comparison against
the ffmpeg-measured loudness once that pass runs, not worth building a
reader around on its own.

**`TBPM`/`TKEY`/`TKY2` (tempo and musical key).** 1,022 files know their
tempo (`TBPM`, across mp3/aif/aiff/wav-embedded-ID3). 1,058 files know
their key (`TKEY` and/or `TKY2` -- the union is exactly 1,058, i.e. every
file with `TKY2` also has `TKEY`). 1,004 files have both. `TKEY` holds a
traditional key name ("A#m", "Gmin", "Fmin"); `TKY2` holds the same key in
Camelot wheel notation ("11m", "9m", "12m"), the harmonic-mixing notation
DJ software uses. On m4a, 0 files carry an equivalent -- no freeform key
atom found anywhere, and `tmpo` is present on only 4/117 files, 2 of which
are literally 0 (a placeholder, not a real tempo). **This is a real,
substantial, currently-unused dataset for a DJ-facing product**: a quarter
of the whole library (1,058/4,050 = 26.1%) already has harmonic-mixing
data sitting in the files, overwhelmingly from Beatport (aif/aiff) and
Traktor-tagged mp3s.

ISRC: `TSRC` on 790 files (mp3/aif/aiff/wav), 787 of them (99.6%) genuinely
ISRC-shaped; `xid ` on 84 m4a files in `vendor:isrc:CODE` form. 874 files
total have a globally-unique recording identifier sitting unused.

**`POPM`/`PCNT` (ratings and play counts).** `POPM`: 3 files only, all
rated by "Windows Media Player 9 Series" at the byte value 255 (WMP's
top rating). `PCNT`: **0 files, anywhere, in any container.** The owner's
device carries 85 rated and 69 played tracks (per
`research/ITUNES-PARITY.md` §4), and none of that history is mirrored
into the files themselves -- ratings and play counts live only in the
iPod's own database and the device-side ledger this project already
reads, never in file tags. Confirms there is nothing to recover here; the
device databases are the only source and already covered elsewhere.

## 8. Gapless-playback data (relevant to `ITUNES-PARITY.md`'s open gap)

`ITUNES-PARITY.md` §5/§8 lists gapless playback data as a gap, "unmeasured
whether the Classic needs it." The encoder-side half of that data turns
out to already exist in the files:

| source | files | what it holds |
|---|---|---|
| m4a `----:com.apple.iTunes:iTunSMPB` | 117/117 (100%) | encoder delay, padding, sample count -- everything needed to trim the AAC priming/remainder samples |
| mp3 `COMM:iTunSMPB` | 73/2156 | the same, for mp3s iTunes re-encoded or touched |
| mp3 `COMM:iTunPGAP` | 81/2156 | a plain gapless yes/no flag |
| m4a `pgap` atom | 96/117 (6 set to 1, 90 to 0) | the same flag as a real ilst atom |

None of this is read today. It does not by itself answer whether the
Classic's firmware needs gapless data supplied at sync time, but it means
*if* the product decides gapless matters, the hard part (computing
encoder delay/padding) is already done for every m4a and a meaningful
slice of mp3s -- it would not need re-deriving from the audio.

## 9. ReplayGain, checked explicitly

**FLAC/Vorbis `REPLAYGAIN_*`: 0 of 244 files.** Checked every Vorbis
comment key in the library (section 4's table is the complete list); none
of them start with `REPLAYGAIN`. **ID3 side: 1 file** carries a full
`TXXX:replaygain_track_gain`/`_track_peak`/`_album_gain`/`_album_peak` set
(section 2.3). **One more non-standard sighting:** a single mp3 carries an
`RGAD` frame (ReplayGain Adjustment, an old pre-TXXX convention), 1 byte
of payload, not decoded further. Across the whole library, ReplayGain is
effectively absent -- 2 files out of 4,050.

## 10. Cross-container field matrix

Where the same fact is sometimes present and sometimes not, by container:

| fact | mp3 | aif | aiff | wav | flac | m4a |
|---|---|---|---|---|---|---|
| album artist | yes (811 files) | **no, 0 files** | **no, 0 files** | yes, via embedded ID3 | yes (ALBUMARTIST) | yes (`aART`) |
| musical key | yes | yes | yes | yes, via embedded ID3 | **no** | **no** |
| tempo | yes | yes | yes | yes, via embedded ID3 | **no** | yes, but only 4/117 files |
| ISRC | yes (TSRC) | yes | yes | yes, via embedded ID3 | **no** | yes (`xid `, different convention) |
| Sound Check / loudness | yes (COMM) | **no** | **no** | **no** | **no** | yes (freeform) |
| gapless encoder data | yes (73 files) | **no** | **no** | **no** | **no** | yes (117/117) |
| compilation flag | yes (TCMP, 7 files) | **no** | **no** | **no** | **no** | yes (`cpil`, 97 files) |
| podcast classification | yes (11 files) | **no** | **no** | **no** | **no** | **no** (0 files) |
| embedded cover art | yes | yes | yes | yes, via embedded ID3 (not LIST/INFO) | **no, 0 of 244** | yes |

**`TPE2`/album-artist being entirely absent from 809 aif+aiff files is
real**, verified directly against the raw frames (not just this census's
decode path) -- not a single one carries the frame. Whatever supplies
`album_artist` for those tracks in `index.json` today is not coming from
this field.

## 11. The three buckets

**READ TODAY** -- mapped by `tags.py` into one of the seven managed
fields, across every container that carries it: `TIT2`/`©nam`/`TITLE`/
`INAM` (title), `TPE1`/`©ART`/`ARTIST`/`IART` (artist), `TALB`/`©alb`/
`ALBUM`/`IPRD` (album), `TPE2`/`aART`/`ALBUMARTIST`/`IAAR` (album artist,
mp3/m4a/flac/wav only, never aif/aiff), `TCON`/`©gen`/`gnre`/`GENRE`/
`IGNR` (genre), `TYER`/`TDRC`/`TDRL`/`©day`/`DATE`/`ICRD` (year), `TRCK`/
`trkn`/`TRACKNUMBER`/`ITRK` (track). Plus `APIC`/`covr`/FLAC PICTURE/WAV
embedded-ID3 `APIC` for artwork, via `has_art`/`art_bytes`. Plus `PCST`/
`WFED` for the podcast classifier.

**PRESENT AND UNEXPLOITED**, ranked by how much it is actually worth:

1. **`TKEY`/`TKY2`** -- 1,058 files (26.1% of the library), musical key in
   two notations including Camelot. The owner is a DJ. This is the
   single highest-value unexploited field found.
2. **`TBPM`** -- 1,022 files (25.2%), tempo. Pairs directly with #1 for
   harmonic-mixing/sequencing features; 1,004 files have both.
3. **`TSRC`/`xid ` (ISRC)** -- 874 files total, 787 of the 790 `TSRC`
   values genuinely ISRC-shaped. A globally unique recording id, usable
   for external lookups (Spotify/MusicBrainz/Beatport cross-reference)
   without fuzzy artist/title matching.
4. **Beatport `UFID`** -- roughly 1,262 files once all three byte layouts
   are handled, a direct Beatport catalogue number per track.
5. **`iTunSMPB`/`iTunPGAP`/`pgap`** -- 117/117 m4a, 73+81/2156 mp3, 96/117
   m4a. Pre-computed gapless encoder data, see section 8.
6. **`iTunNORM`** -- 214 files (5.3%), Apple Sound Check. A free
   cross-check against the ffmpeg loudness pass, not a replacement for it.
7. **`TPE4`** (remixer) and **`TCOM`** (composer) -- 227 and 199 files.
   Real, specific, cheap to surface in a credits view.
8. **`TPUB`** (label/publisher) -- 1,253 files. High coverage, moderate
   value (a label browse/filter).
9. **`TCOP`/`cprt`** (copyright string) -- 391 + 93 files. Low effort,
   low but nonzero value (attribution display).
10. **`TPOS`/`disk`** (disc number) -- 108 + 23 files, same shape as the
    already-known `total tracks`/`total discs` gap in `ITUNES-PARITY.md`.
11. **PRIV `PeakValue`/`AverageLevel`** -- 56 files, WMP's own loudness
    value, same caveat as `iTunNORM`: a cross-check, not a replacement.
12. **`TRAKTOR4`/Serato `GEOB`** -- real DJ cue/beatgrid data, but opaque
    proprietary binary on a handful of files (5 and 1 respectively). Not
    worth building a decoder for this few files.

**Noise, not worth exploiting**: `TENC`/`TSSE`/`TFLT`/`TDAT`/`TLEN`/`MCDI`/
`TMED`/`TAUT` (always "TRACK")/`TXXX:BPM`/`TXXX:URL`/`TXXX:Engineer`
(always empty)/the 7 Windows Media `PRIV` GUIDs/`cnID`/`plID`/`atID`/
`geID`/`sfID`/`cmID`/`akID`/`rtng` (m4a Store bookkeeping, dead store)/
`TIT1`/`TOPE`/sort-name atoms/CDDB-era comments/MusicMatch comments.

**ANOMALIES**, see section 6 for the full table. Headline items: the
3-way incompatible Beatport UFID encoding (1,262 occurrences across the
three shapes), 15 WAV files with corrupted trailing data past the audio
chunk, 14 files where TYER/TDRC/TDRL disagree on the year itself, and 368
WAV files carrying a whole second, currently-unread ID3 tag.

## 12. What I would actually do, ranked

1. **Read `TKEY`/`TKY2`/`TBPM` into the index.** Highest file coverage
   (26.1%/25.2%), highest relevance (DJ), lowest implementation cost --
   they are plain ID3/AIFF text frames, same code path as the seven
   fields already read. No new parser needed, just two more entries in
   `_ID3_BACK` (or a parallel "extended fields" map so the seven-field
   contract in `tags.py` stays clean).
2. **Add the three Beatport UFID shapes to a single reader and surface
   the Beatport track id.** Lets the product cross-reference/relink
   purchased tracks without fuzzy matching, and documents a real
   multi-convention anomaly so a future reader doesn't quietly miss 492
   of 1,262.
3. **Read `TSRC`/`xid ` for ISRC**, with the 3 known-junk values
   filtered out. Cheap, high-confidence identifier.
4. **Fix the WAV reader's biggest blind spot**: 368 files (50.8% of
   WAV) carry a second tag source the current `read_wav` never opens.
   At minimum, read it when LIST/INFO is absent or thinner; the 4
   measured disagreements show the ID3 side is sometimes the better
   source.
5. **Flag the 15 corrupted-trailer WAV files** to the owner as a
   separate audio-integrity item -- these downloads may be truncated or
   damaged, independent of anything metadata-related.
6. **Decode `iTunSMPB` on the 117 m4a + 73 mp3** once (or if) gapless
   playback is prioritized -- the computation is already done, this
   would just be reading it.
7. **Ignore**: `iTunNORM`, WMP `PeakValue`/`AverageLevel`, `TRAKTOR4`,
   Serato `GEOB` -- all real, none worth building a reader for at
   current coverage (5.3%, 1.4%, 5 files, 1 file respectively). Revisit
   `iTunNORM` only as a sanity check once the ffmpeg loudness pass runs.
8. **Ignore everything in the "noise" list in section 11** -- populated
   on many files, worth nothing: ripper/encoder provenance strings,
   dead iTunes Store catalogue numbers, Windows Media DRM bookkeeping.
