# Writing tags to the files on disk

**Status: measured.** Every number below came from running the commands on
copies of real files off the T7 on 30 September 2026. Nothing here is
proposed except the section that says so.

## Why this document exists

The plan was: edit a track's fields, write them into the file on disk, and
let the next sync carry the change onto the iPod. The obvious instrument is
ffmpeg, which the project already depends on. **It is the wrong instrument,**
and finding that out cost ten minutes rather than 4,048 damaged files.

## What `ffmpeg -c copy -map 0` actually does

The standard "lossless tag write" incantation. Run on one sample of each
container, comparing the decoded audio's MD5 before and after.

| | audio MD5 | file size | what happened |
|---|---|---|---|
| **MP3** | **CHANGED** | 6,293,479 → 6,292,457 | ffmpeg **prepended a Xing/LAME header frame** (absent before, present after) and rewrote ID3v2.4 as v2.3. Duration moved 302.413333 → 302.420658 — one frame, ~7 ms. |
| **M4A** | identical | 3,938,676 → 3,416,140 | `mdat` byte-identical. But the 485,876-byte `free` atom was **dropped**, and `moov` shrank 94,089 → 57,425 — **36 KB of metadata ffmpeg did not understand and therefore did not keep.** |

So: ffmpeg is a **remuxer**, not a tag writer. It rebuilds the container from
what it understands and silently discards what it does not. On MP3 it alters
the audio stream. Neither is acceptable in a tool whose selling point is a
byte-identical round trip.

This is the same rule the project already applies to the iTunesDB, in
CONTRIBUTING: *"Anything that regenerates the database rather than patching
it"* will not be merged. An audio file is a database too.

## Every container already has room to grow

The formats were designed for this. Measured on the same samples:

| Container | Where tags live | Padding already present |
|---|---|---|
| **FLAC** | `VORBIS_COMMENT` block | **8,192-byte `PADDING` block**, last before the audio |
| **M4A** | `moov/udta/meta/ilst` | **485,876-byte `free` atom** — iTunes' own headroom |
| **MP3** | `ID3v2` header at byte 0 | ID3v2 carries a padding field by design |

A FLAC's audio starts at byte 8,719 behind 8 KB of padding whose entire
purpose is to let tags change without moving a single audio byte. The M4A
has half a megabyte of it.

**So the operation is: grow the tag block, shrink the padding by the same
amount, touch nothing else.** The audio never moves. If an edit ever exceeds
the padding, rewrite the file once with a larger pad and copy the audio
verbatim — the same fallback the iTunesDB code already has.

## Two stores, and only one of them has the problem

There are **two independent copies of every track's metadata**, and it
matters which one you are fixing.

**The iPod carries its own.** The database holds, per track: `album artist
bitrate composer filetype genre id location ms size title track_no visible
year`. The Classic's menus are built from *this*, never from the audio
file's tags — which is why patching the database is enough to change what
the device shows.

Measured on the live device: **658 tracks, 2 blank artists, 1 blank album,
12 blank genres.** The iPod's metadata is essentially complete.

**The drive is where the problem is.** 581 files with no artist or title —
and of those, **about one is on the iPod.**

The reason the device is already fine is a fallback that has been in
`sync()` all along:

```python
meta['title']  = meta['title']  or r['title']
meta['artist'] = meta['artist'] or r['artist']
```

An untagged file copied to the device gets its name from the **state
record**, not from the file. So the device has been right about tracks the
drive is wrong about, this whole time.

That splits the work in two, and they are not the same job:

| Goal | What it needs | Cost |
|---|---|---|
| **The iPod shows the right thing** | edit in state, patch the DB entry on sync | small — the fallback already does most of it |
| **The drive itself is correct** (Apple Music, Rekordbox, any other tool) | real tag writers per container | one writer per format |

## PROPOSED — the writers, in the order they actually pay off

My first instinct was FLAC-first because it is the simplest format. That was
wrong: **zero of the 581 untagged files are FLAC.** Building it first would
have fixed nothing.

The 581, by container:

| Container | Untagged | Where tags live |
|---|---|---|
| **WAV** | **366** | RIFF `LIST/INFO` chunk, or an `id3 ` chunk |
| **MP3** | **186** | ID3v2 at byte 0 |
| M4A | 21 | `moov/udta/meta/ilst`, against the `free` atom |
| AIF | 8 | ID3 chunk |
| FLAC | **0** | — |

So: **WAV, then MP3**, and those two cover 95% of the backlog. M4A and AIFF
after. FLAC last, or never — build it when a FLAC actually needs fixing.

RIFF is the simplest of the lot, which is a happy accident: chunks are
`<4-char id><u32 little-endian size><data>`, and a `LIST/INFO` chunk can be
replaced or appended without touching the `data` chunk that holds the audio.

## ALAC

**There are no ALAC files on the drive** — 0 of 4,048. The 117 `.m4a` files
are all AAC.

ALAC is a *codec inside an M4A container*, so the M4A writer covers it for
free: tags live in `moov/udta/meta/ilst`, nowhere near the audio stream, and
the atom surgery is identical whether the `mdat` holds AAC or ALAC.

Sync *creates* ALAC — `CONVERT` turns FLAC/WAV/AIFF into it, which is 1,776
of the drive's files and 158 of the 643 currently on the device. **Those
copies never need their tags written**, because the Classic reads the
database. Fixing an ALAC file on the iPod would be writing to a store
nothing reads.

**The test that has to pass**, borrowed from `bin/device_test.sh rehearse`:
write a tag, read it back, and assert the decoded audio MD5 is unchanged and
every byte outside the tag block is unchanged. That is the same standard the
device write already meets.

## Built: WAV and ID3v2 (30 September)

| Container | Writable | Waiting |
|---|---|---|
| WAV | **355** | 10 carry an `id3 ` chunk |
| MP3 | **139** | 48 are ID3v2.2 |
| AIFF | **8** | — |
| M4A | — | 21, no writer yet |
| **Of the 581 untagged** | **502** | 79 |

Across the whole drive, **3,214 of 4,049** files are writable.

**ID3v2 writes in place when it fits**, which it almost always does: an ID3
tag is padded by design and the median file here carries 1,142 spare bytes,
455 of 532 carrying at least 256. Verified on one file of each version —
audio offset unchanged, audio MD5 unchanged, file size **+0**, stable over
three writes. A v2.3 file carrying a 57,513-byte cover kept it byte for
byte.

Two things the testing corrected:

- **ID3v2.2 is refused, not converted.** Its frame ids are three characters
  to v2.3's four, so carrying an unmapped frame across writes a malformed
  header and loses everything after it. The first attempt did exactly that:
  an 11-frame tag came back as 5 and the cover art was gone. 47 of 600
  sampled files are v2.2 and they wait for a real converter.
- **The guarantee had to be stated more carefully.** The audio *bytes* are
  never altered — that is unconditional. Their *offset* holds only when the
  new tag fits the old one's space. Adding a tag to a file that never had
  one necessarily pushes the audio down; `verify(..., in_place=False)` is
  the honest form, and `write()` returns whether it stayed put. The next
  write to that file fits the pad and moves nothing.

## Freshness: how sync knows the device copy is stale

`mtime` is the cheap gate, value comparison is the truth.

The drive index records `album album_artist artist bit_depth channels codec
duration_sec ext has_art ipod_ready needs_convert path sample_rate size title
untagged` — and **no mtime**, so every `index` run re-probes all 4,048 files
with ffprobe. Recording `mtime` is worth doing on its own merits.

Then:

- **mtime decides whether to look.** File newer than the indexed mtime →
  re-probe it. Everything else is skipped.
- **Values decide whether to act.** `plan()` compares the file's tags against
  what the device holds and queues an update if they differ.

Using mtime alone would be wrong, and using a dirty flag would be worse.
A flag gets cleared by the sync, so **undoing an edit after a sync would not
queue the correction** — the exact case that has to work. Comparing values
means the truth is always derived, never remembered, which is the same rule
that makes `bought` derived from a file existing and makes `plan()` a diff
against a live device read.

Undo after a sync is therefore not a rollback of the device. It rewrites the
file, which bumps mtime, which re-probes, which finds the reverted values,
which queues a fresh update. **The device catches up on the next sync** —
stage-then-commit, extended to metadata.
