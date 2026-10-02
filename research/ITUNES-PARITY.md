# iTunes parity: what it did, what we do, and which gaps are on purpose

**Status: measured, on this device, today.** Every row was established by
reading the owner's iPod Classic or this repo's code -- not from memory and
not from documentation about what iTunes is supposed to do. Rows that could
not be established that way are marked **unknown**, which is a real answer
and the most useful column in the table.

## Why this exists

Until now iTunes' behaviour was discovered by tripping over it. In a single
session: that the `Play Counts` sidecar is a delta rather than a total, that
the iPod does not evaluate smart playlists, that the play counters were in
the `mhit` all along, that an AIFF is not an MP3 with a different extension.
Each was found because something broke or because the owner asked, never
because anyone had made a list.

A list is cheaper than the next surprise.

## Verdict vocabulary

Five words, used strictly:

| | |
|---|---|
| **parity** | we do what iTunes did |
| **better** | we do more, deliberately |
| **divergent** | we do it differently ON PURPOSE, reason given |
| **gap** | iTunes did it, we should, we do not |
| **unknown** | not investigated -- say so rather than guess |

## 1. Files iTunes maintains on the device

Walked `iPod_Control/` on the real device.

| file | size here | what it is | us | verdict |
|---|---|---|---|---|
| `iTunes/iTunesDB` | 1.0 MB | the library | read + surgical patch | **better** -- we patch, iTunes rebuilt |
| `iTunes/Play Counts` | absent now | plays since last sync, a DELTA | read, merge, never delete | **divergent** -- iTunes deleted it; see §4 |
| `Artwork/ArtworkDB` | 199 KB | artwork index | read, round-trips byte-identical | **gap** -- no writer |
| `Artwork/F1060_1.ithmb` | 53.0 MB | 259 covers at 320x320 | never opened | **gap** |
| `Artwork/F1055_1.ithmb` | 8.5 MB | 259 covers at 128x128 | never opened | **gap** |
| `Artwork/F1061_1.ithmb` | 1.6 MB | 259 covers at 56x55 | never opened | **gap** |
| `iTunes/iTunesControl` | **156.2 MB** | iTunes Store URL bag (plist ends at 7.7 MB) | untouched | **divergent** -- the Store is gone; see §7 |
| `iTunes/Extras.itdb` | 455 KB | **SQLite**: genius_config, genius_metadata, genius_similarities | untouched | **divergent** -- Genius is discontinued |
| `iTunes/iTunesPrefs`, `.plist` | 1.2 / 2.6 KB | device-side iTunes prefs | untouched | **unknown** |
| `iTunes/Rentals.plist` | 236 B | store rentals | untouched | **divergent** -- no store |
| `iTunes/PSAlbumAlbums`, `PSElementsAlbums` | 100 B each | unknown purpose | untouched | **unknown** |
| `Device/SysInfo` | 0 B | FireWire GUID lives here normally | read (GUID) | parity |
| `Device/Preferences` | 3.0 KB | binary device prefs | untouched | **unknown** |
| `Device/PlayCounts` | 42 B | **game** stats, not music -- contains the id `11010` that matches `gamestats_WO/11010/` | untouched | parity (not ours) |
| `Device/Users`, `clock`, `alarms` | small | device state | `clock` read only | parity |
| `Tones/`, `gamedata_RW/`, `gamestats_WO/` | small | ringtones, games | untouched | **divergent** -- out of scope |

And at the VOLUME ROOT, outside `iPod_Control` -- which the first sweep
missed entirely because it only walked `iPod_Control`:

| folder | state here | what iTunes did | us | verdict |
|---|---|---|---|---|
| `Notes/` | present, empty | synced text notes | untouched | **divergent** -- out of scope |
| `Calendars/` | present, empty | synced vCal | untouched | **divergent** |
| `Contacts/` | present, empty | synced vCard | untouched | **divergent** |
| `Recordings/` | present, empty | **imported voice memos back into the library** | **not read** | **gap** -- same shape as On-The-Go: something the device creates that a sync would ignore |
| `Photos/` | absent | photo library | n/a | **divergent** |
| `.rockbox/` | absent | n/a -- replacement firmware | n/a | see `research/ROCKBOX.md` |

## 2. Track fields: what iTunes AUTHORS that we do not

The round trip is byte-identical, so everything iTunes already wrote is
**preserved**. That says nothing about what we author on a track WE add.
Compared the 60 oldest `mhit`s by `date_added` (iTunes era, 2011-2018)
against the 60 newest (ours, 2026):

| field | offset | iTunes | ours | verdict |
|---|---|---|---|---|
| `sample rate` | 0x3C | 60/60 | 60/60 | parity |
| `date added` | 0x68 | 60/60 | 60/60 | parity |
| **`total tracks`** | 0x30 | 60/60 | **0/60** | **gap** |
| **`total discs`** | 0x60 | 60/60 | **0/60** | **gap** |
| **`disc number`** | 0x5C | 10/60 | **0/60** | **gap** |
| **`soundcheck`** | 0x4C | 60/60 | **0/60** | **gap -- audible** |
| `play count` | 0x50 | 37/60 | 0/60 | parity (a new track has no plays) |
| `last played` | 0x58 | 57/60 | 0/60 | parity (same reason) |
| `rating`, `volume`, `start`/`stop time`, `bookmark`, `checked` | | 0/60 | 0/60 | parity -- iTunes left them zero too |

**Soundcheck is the one that is audible.** It is iTunes' per-track volume
normalisation, and the iPod applies it when Sound Check is on. Every
iTunes-era track here carries one and no track we added does, so our tracks
play at a different loudness than theirs on the same device. The other
three are cosmetic: the Classic shows "3 of 12" where it has them.

## 3. Playlists

| | iTunes | us | verdict |
|---|---|---|---|
| regular playlists | writes membership | writes membership | parity |
| ordering within a playlist | preserved | **`state.collection_order` is the truth, sync never sorts** | **better** -- sequence is the product |
| **smart playlists** | evaluates on the desktop, writes the result as plain `mhip`s | copies the rules and the stale membership verbatim | **gap** -- see `research/SMART-PLAYLISTS.md` |
| smart playlist rules (`mhod` 50/51) | authored them | preserved as opaque blobs | gap |
| **On-The-Go playlists** | imported them back into the library | **not read -- a sync would silently drop one** | **gap** |
| podcast playlist | maintained | none written | **divergent** -- no podcasts here |
| playlist folders | supported | flat only | **unknown** whether the Classic shows them |
| `mhod` 52/53 browse indexes | wrote them | dropped/rebuilt | **divergent** -- optional; browsing is slower without |

## 4. Play counts and ratings

**The merge model, stated once.** The iPod does not update `play count` in
the iTunesDB. It writes plays into `Play Counts` as a DELTA; iTunes read
that, added it to the library total, and **deleted the file**. So the number
in iTunes was always desktop plays + iPod plays.

| | iTunes | us | verdict |
|---|---|---|---|
| read the sidecar | yes | yes | parity |
| add the delta to a running total | yes | yes | parity |
| **delete the sidecar after reading** | yes | **no** | **divergent** -- the device rebuilds it anyway, and a delta consumed wrongly cannot be recovered. We record a sha1 ledger instead so the same file is never counted twice. |
| guard against the positional trap | n/a -- iTunes owned both files | refuses when entry count != track count | **better** |
| ratings set on the device | synced back | read, replaced not summed | parity |
| ratings set on the desktop | pushed to device | **not written** | **gap** |
| last played, skip count, bookmark | synced both ways | read only | **gap** on the write side |

## 5. Audio and formats

| | iTunes | us | verdict |
|---|---|---|---|
| mp3, m4a/AAC, ALAC, WAV, AIFF | copied as-is | copied as-is | parity |
| FLAC | **refused -- iTunes never supported it** | converted to ALAC | **better** |
| conversion for the device | its own encoder | `afconvert`, ffmpeg fallback | parity |
| **tag editing** | rewrote the container | **patches in place, audio byte-identical** | **better** |
| gapless playback data | computed and stored | **not computed** | **gap** -- unmeasured whether the Classic needs it |
| volume normalisation (Sound Check) | computed | **not computed** | **gap**, see §2 |
| equaliser preset per track | supported (`mhod` 7) | preserved, never set | **divergent** |
| media type (music/podcast/audiobook/video) | set per track | music only, all 653 tracks are `0x1` | **GAP** -- scope changed 2 October 2026, see below |

## 6. Artwork

| | iTunes | us | verdict |
|---|---|---|---|
| extract embedded cover art | yes | yes, with our own parsers, 150/150 against ffprobe | parity |
| write `ArtworkDB` + `.ithmb` | yes | **no** | **gap** |
| show art on the device | yes | inherited only from what iTunes left | gap |

**The measured consequence:** 653 tracks on the device, 652 matched to a
file on the drive, **399 of those files carry cover art -- and the device
holds artwork for 259**. So **140 covers exist on disk that the iPod cannot
show**, purely because there is no ArtworkDB writer.

### Three sizes, and the device names them itself

Not a choice we get to make. The `mhlf` list inside this device's own
ArtworkDB declares three formats, each with the exact byte size of one
image:

| correlation id | declared bytes | geometry | file |
|---|---|---|---|
| 1055 | 32,768 | 128 x 128 RGB565 | `F1055_1.ithmb` |
| 1060 | 204,800 | 320 x 320 RGB565 | `F1060_1.ithmb` |
| 1061 | 6,160 | 56 x 55 RGB565 | `F1061_1.ithmb` |

32768 = 128x128x2, 204800 = 320x320x2, 6160 = 56x55x2 -- two bytes per
pixel, so every one is raw RGB565 with no header and no compression. The
firmware uses different sizes in different places (the list, now-playing,
cover flow), so **all three must be written**; writing only the largest
leaves the other views blank.

"Prefer the highest resolution" therefore applies to the SOURCE: extract
the biggest embedded cover available and downsample it to all three,
rather than extracting three times. `platform.resize_cover` already does
scale-to-cover correctly and `tags.has_art` already finds the art.

## 7. Deliberate divergences, collected

So they are never mistaken for gaps:

1. **The file on disk is master; the iPod is a slave that catches up.**
   iTunes treated its library database as the truth and the files as
   payload. We edit the file and let the device follow.
2. **Sequence is the product.** `state.collection_order` is the truth and
   sync never sorts. iTunes re-sorted by whatever column you last clicked.
3. **We never delete the `Play Counts` sidecar.** §4.
4. **Media type was "music only" and is not any more.** The owner, 2
   October 2026: *"scope is now everything that goes on ipod.. incl
   podcasts - going forward we will probably also file audiobooks under
   podcasts as that was not so much a thing back in the day, but it is
   now."*

   Measured: every one of the 653 tracks on the device is `mediatype =
   0x1`, audio. Including all ten DeepCast episodes, which are podcasts,
   run to an hour and a half, and can only be found under Artists.

   Two things follow from setting it, and the second is the better reason:
   the Podcasts menu starts working, and a podcast gets RESUME-POSITION
   behaviour -- the `bookmark_ms` field we already read and never set --
   so a 93-minute mix picks up where it stopped instead of restarting.

   **Audiobooks are to be filed as podcasts**, deliberately and against
   what iTunes did. Audiobooks were barely a category when this firmware
   shipped; the owner's judgement is that the podcast menu is where people
   now look for long spoken-word audio, and resume behaviour is the same
   either way.

   **Handle with care.** The format notes record several ways this field
   misbehaves: a mediatype of 0 duplicates the track into Videos; a podcast
   flag inconsistent with the mediatype makes iTunes drop the track on the
   next sync; two playlists carrying the podcast flag means NONE are shown.
   A one-byte change with several documented ways to break a library.

5. **No store, no Genius, no games, no ringtones.** `iTunesControl` is
   156 MB holding a 7.7 MB plist of iTunes Store endpoints for a store that
   no longer serves this device; `Extras.itdb` is a Genius database for a
   discontinued feature. We leave both alone rather than reclaim the space,
   because deleting something the firmware might open is not worth 0.1% of
   a 160 GB disk. **Noted, not acted on.**
6. **One library, no "auto sync" mode.** iTunes had manual and automatic
   management and could wipe a device to match. Every sync here is
   explicit and additive.
7. **Flat playlists.** No folders, no podcast list.

## 8. The gaps, ranked by what they cost

1. **ArtworkDB writer** -- 140 covers already on disk that the device
   cannot show. Highest visible value; the tree model already round-trips
   byte-identically.
2. **Smart playlist evaluation** -- 7 lists on the device, several stale at
   0 members. The inputs now exist (play counts, ratings, dates).
3. **Soundcheck** -- the only *audible* divergence.
4. **On-The-Go playlists** -- a playlist made on the device is silently
   dropped today. Low effort, and the failure is data loss.
5. **Writing ratings back to the device** -- we read them, we cannot set them.
6. `total tracks` / `total discs` / `disc number` -- cosmetic on the Classic.
7. **Gapless data** -- unmeasured whether the Classic needs it at all.

## 9. Unknowns, listed honestly

- `iTunesPrefs`, `iTunesPrefs.plist`, `Device/Preferences` -- never opened.
- `PSAlbumAlbums`, `PSElementsAlbums` -- 100 bytes each, purpose unknown.
- Whether the Classic needs gapless data, or computes it itself.
- Whether playlist folders display on a Classic.
- What the 148.5 MB after `iTunesControl`'s plist actually contains -- it is
  not all zeros.
- Whether a sync leaves `Extras.itdb` (Genius) inconsistent with a changed
  library, and whether the device cares.
- What `Recordings/` contains on a device that has been used to record, and
  in what format.

## 10. Could we read iTunes itself?

The owner asked whether an iPod-era iTunes build could be obtained and its
code evaluated for a proper delta.

**Reading the binary is the weakest of the three options available**, and
worth saying why before anyone spends a week on it:

| | what it gives | cost |
|---|---|---|
| **Read `libgpod` / `gtkpod` source** | fifteen years of exactly this delta analysis, across many device generations, already written down and open | free, and the best value |
| **Run an old iTunes in a VM against a scratch device** | OBSERVED behaviour -- what it actually writes, which is the only ground truth that matters | a VM, an old macOS, a spare iPod or a disk image |
| **Decompile iTunes** | the intent behind the behaviour | large, and the behaviour is what we need, not the intent |

Observation beats decompilation here because every question in this
register is of the form "what bytes does it write", not "why". A scratch
volume, an old iTunes, and a diff answers those directly -- and `rehearse`
already exists to diff two database states.

**PROPOSED, not done.** The one thing a VM would settle cheaply that
nothing else can: what iTunes writes into `soundcheck`, and whether the
Classic needs gapless data.
