# macOS adapters: what the system already does for us

**Status: measured.** Everything here was run on this machine against
real files; the sections that were PROPOSED are now built, and two of the
three proposals turned out to be wrong in a way only running them showed.

These all live in the **server**, which is the point. A client never calls
them, so the web page and the native app both get the benefit without
either knowing. It is the layer rule paying out in the other direction: put
it below the boundary and every client inherits it.

## The one that matters most

**The drive index spawns `ffprobe` 4,048 times.** Spotlight has already
indexed those files, and answers in one call.

```
ffprobe, one file at a time      130 s
mdls, one call for all of them     2.2 s        60x
```

Measured over 600 real files: **0.53 ms each** against ffprobe's 32 ms.
The T7 is indexed — the query returned all 600.

**It is a fast path, not a replacement.** Per container, Spotlight is
missing:

| | has | missing |
|---|---|---|
| mp3 / m4a / flac | album artist title duration sample_rate channels size | `album_artist` `codec` `bit_depth` `has_art` |
| aiff | the above plus bit_depth | `album_artist` `codec` `has_art` |
| **wav** | duration sample_rate bit_depth channels size | **every tag** — Spotlight does not read `LIST/INFO` |

Which suggests the right split rather than a straight swap:

- **Spotlight** for the technical fields — duration, sample rate, channels,
  bit depth, size
- **`tags.py`** for the editable ones — artist, title, album, album_artist,
  genre. We already have these readers, they only touch the tag span, and
  using them here means **the index and the editor agree by construction**
  instead of being two views of the same file
- **`ffprobe`** for what is genuinely left: `has_art`, and codec where the
  extension does not settle it

## ffmpeg is 36 MB of dylibs, and most of what it does ships with macOS

`ffmpeg` itself is 420 KB but links 21 homebrew dylibs — **36 MB** that
would all have to be bundled and signed inside-out.

**`afconvert` makes the ALAC the iPod needs, and the audio is identical.**

```
afconvert -f m4af -d alac in.wav out.m4a
  -> alac, 44100, 2ch, 16-bit, 2.0 MB
ffmpeg  -c:a alac
  -> alac, 44100, 2ch, 16-bit, 2.0 MB
audio md5: IDENTICAL
```

`/usr/bin/afconvert`. Nothing to bundle, nothing to sign, and conversion is
the main reason ffmpeg is here at all.

**`sips` does the artwork sizes exactly** — `-z 128 128` and `-z 320 320`
return precisely 128 and 320, which is what ArtworkDB wants.

**`qlmanage` is not the answer for extraction.** Tested: 757 ms against
ffmpeg's 95 ms, and it returns a 250×250 QuickLook thumbnail rather than
the embedded cover. Wrong thing, slower.

The honest route to removing ffmpeg entirely is our own code: **`tags.py`
already parses `APIC` frames** — it carries them through on every write.
Reading the image bytes out is a small addition to a parser that exists,
and it would be more correct than shelling out, because it returns the
cover that is actually in the file rather than whatever a decoder picks.

What would be left needing ffmpeg: the on-the-fly mp3 preview stream for
`/api/audio`. That could serve the original instead, or convert once to a
cache.

## Why these beat a rewrite

Measured separately (`NATIVE-APP-SPEC.md`): 94% of `plan()` was waiting on
a disk, so Swift bought nothing. Every adapter here removes *work*, which
is the only thing that was ever going to help:

| | today | with the adapter |
|---|---|---|
| index the drive | 130 s | **~2 s** |
| `plan()` | 2,677 ms | **54 ms** (mtime cache, already built) |
| bundle size | +36 MB of ffmpeg dylibs | **0**, if the last use goes |

## BUILT, and what measuring changed

`src/saltpod/platform.py`. Every operation has a portable fallback, so this
is macOS-*preferred*, not macOS-only: the module detects what the system
provides and picks per operation.

| | native | fallback |
|---|---|---|
| `to_alac` | afconvert | ffmpeg |
| `resize_cover` | sips | ffmpeg |
| `watch_mounts` | DiskArbitration | 2s poll |
| `watch_tree` | FSEvents | mtime walk |

Three things in the plan this file used to end with were wrong, and only
running both sides found them.

### afconvert defaults to 32-bit ALAC

```
source               flac 44100 2ch 16-bit   18.6 MB
ffmpeg -c:a alac     alac 44100 2ch 16-bit   19.2 MB
afconvert -d alac    alac 44100 2ch 32-bit   46.3 MB   <- 2.4x
afconvert -d alac/1  alac 44100 2ch 16-bit   19.1 MB
```

**All four decode to the same audio md5** — which is exactly why the
differential at the top of this file, the one that compared the audio,
passed it. A 160 GB iPod would have filled two and a half times faster, and
the Classic's decoder is specified for 16-bit ALAC, so it may well not have
played at all.

ALAC carries the source bit depth in its format flags (`/1` = 16, `/3` =
24). The flag is read off the source now, not hardcoded.

**The lesson is about the test, not the codec:** a differential that
compares only the thing you were worried about will pass the thing you were
not.

### sips does not preserve aspect ratio

`sips -z H W` resamples to exactly those dimensions. ffmpeg's
`scale=...:force_original_aspect_ratio=increase,crop=...` scales to cover
and then crops. On a square cover they agree — which is most album art, and
why this would have looked right in every test.

Mean absolute pixel difference against ffmpeg's output:

| | square source | 900x300 source |
|---|---|---|
| `resize_cover` (two sips calls) | 2.7 / 255 | **2.0 / 255** |
| `resize_image` (one `sips -z`) | 2.7 / 255 | **61.8 / 255** |

So they are two operations, not one with a flag. `resize_cover` computes
the proportional target itself and then crops, rather than hoping a flag
preserves the ratio.

### Disk appeared is not disk mounted

This file used to name `DARegisterDiskAppearedCallback`, and that callback
alone **does not work**. It fires when the device node appears, which is
*before* the volume is in `/Volumes` — so a rescan from inside it sees no
change, and the baseline it then fails to update swallows the matching
unmount too. Verified by attaching and detaching a real disk image: **0
events out of 2**, while the callbacks themselves fired perfectly.

The mount arrives as a *description change*. With
`DARegisterDiskDescriptionChangedCallback` registered as well:

| | attach | detach |
|---|---|---|
| DiskArbitration | **136 ms** | **190 ms** |
| 2s poll | 1,514 ms | 1,991 ms |

FSEvents was verified the same way: start a watch on a temp directory,
write a real file into it, assert the event comes back with the right path.

## Conversion no longer uses `-map_metadata 0`

**ffmpeg's reader and ffmpeg's metadata mapping disagree with each other.**
Measured on a real AIFF carrying both a `NAME` chunk and an ID3 tag:

| | title |
|---|---|
| `NAME` chunk | Galore feat. Stephen Simmon**s** (Album Version) |
| ID3 `TIT2` | Galore feat. Stephen Simmon**ds** (Original Mix) |
| `ffprobe` on the source | the TIT2 — agreeing with our reader |
| ffmpeg's converted output | **the NAME chunk** |

On 21 of the 809 AIFFs here, that `NAME` chunk is the raw download
filename.

So the pipeline changed shape. afconvert makes the audio and carries **no
metadata at all** — the better starting point, because there is nothing to
disagree with — and `tags.py` writes the tags. The device and the index now
agree *by construction*, because one piece of code reads and writes them,
instead of agreeing because two tools happened to choose alike. afconvert's
output is `ftyp|moov|free|mdat`, exactly the layout the M4A writer handles.
