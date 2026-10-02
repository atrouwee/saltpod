# Testing backlog: what is built but not yet proven on hardware

**Status: a queue, not a record.** Everything here is implemented and
verified as far as it can be without the owner present. Each item says what
it needs from a human, and what the result would mean -- so a test is never
run without knowing in advance what each outcome proves.

Opened 2 October 2026, when the owner stepped away from the machine.

## The rule that put things here

Writing to the device while nobody can observe or intervene is a bad trade.
The iPod stays mounted and readable; it is not written to until someone is
watching. Everything below is blocked on that, not on code.

---

## 1. Does the artwork appear? -- THE OPEN QUESTION

**State:** one cover is on the device, for *Adrian Waterhouse -- DeepCast
Apr'11 - Episode 008*. The ArtworkDB has 260 entries where it had 259, and
all three `.ithmb` files grew by exactly the right number of bytes.

**The first attempt showed the grey placeholder, not the cover.** The write
deliberately left `mhit`+0x1D alone so the flag could be tested separately.
It has since been set to 0 -- one byte changed outside the header, hash58
re-signed and verified on read-back -- and not yet looked at.

**What it needs:** eject, find the track, look at the screen.

**What each outcome means:**

| | |
|---|---|
| the cover appears | `mhit`+0x1D is the flag. Write the other 223 with both the entry and the flag. |
| the placeholder appears | The flag is not it either. Next suspect is the `mhni` geometry at +0x20, which was cloned from the template without being understood -- a wrong dimension there would plausibly give a placeholder rather than a broken image. |

**Why the flag is suspected:** it is 0 on 243 of the 253 tracks that have
artwork and 1 on 393 of the 400 that do not. A 96% signal, and the ten
exceptions are all GTA radio jingles.

**Undo if needed:** `backups/artwork-2026-10-02-121714` holds the previous
ArtworkDB and the previous `.ithmb` lengths. Restoring is exact and was
proven before the write -- the operation only ever appends.

## 2. The other 223 covers

Blocked on item 1. Fully rehearsed against copies: 259 -> 483 entries,
every blob verified at the offset the database claims, the original 259
entries byte-identical, 45 seconds, the device grows 54.6 MB.

## 3. Smart playlist membership written to the device

The evaluator matches iTunes exactly -- all 24 Top 25 Most Played members,
in order -- and independently computed the same 178 tracks for Recently
Added that the device itself later materialised. **Nothing has been
written.**

**What it needs:** a sync with someone watching, then confirming on the
device that Recently Added and Recently Played are populated and that Top
25 Most Played did not change.

**The risk to watch:** the owner chose to re-evaluate ALL smart playlists
every sync, so a sync overwrites the two lists that are currently correct.
The gate is that Top 25 must come out identical to what iTunes wrote.

## 4. Soundcheck written to the device

Measurement is built and the target is decided (-18 LUFS, the first level
at which nothing in this library needs amplifying). **No value has been
written to any track.**

**What it needs:** write it for a handful of tracks, then listen with Sound
Check ON in the iPod's settings and confirm the loudness is level against
an iTunes-era track that already has a value.

**Note:** five tracks in ninety would still have a true peak above -1 dBFS
after attenuation. Whether to cap those is undecided.

## 5. Media type: podcasts and audiobooks

Scope changed 2 October: everything that goes on the iPod, with audiobooks
filed AS podcasts. Every track on the device is currently `mediatype 0x1`.

**Undecided and needs the owner:** how a track is classified. By folder, by
a tag, by duration, or by an explicit decision in the page. Worth deciding
deliberately rather than inferring from the file layout.

**Handle with care** -- the format notes record that mediatype 0 duplicates
a track into Videos, that a podcast flag inconsistent with the mediatype
makes iTunes drop the track on the next sync, and that two playlists with
the podcast flag means none are shown.

## 6. Finder's sync settings

Not a code item, but it belongs in the queue because it nearly cost the
library.

The settings are currently correct: *Manually manage* ON, *Automatically
sync* OFF, *Enable disk use* ON. The hazard is not a background sync --
auto-sync was off all day and nothing was destroyed. The hazard is a human
unticking "Sync music onto AJ's iPod" in Finder's Music tab, which warns
that **all existing songs and playlists will be removed** and means it.

**Also worth knowing:** `backups/` holds `iPod_Control/iTunes` only -- the
database and playlists, not the 9.7 GB of audio. A wipe would be
recoverable in structure but the files would have to be re-synced. Take a
full backup before experimenting with Finder's sync settings.

## 7. Things no test here can reach

- **A screen reader has never been run against the page.** The
  accessibility work is reasoned from markup, not observed.
- **Liquid Glass**, if the native app happens -- a compositor effect that
  does not survive an offscreen render.
- **A volume with Spotlight indexing disabled**, and a drive reattached
  after being changed elsewhere. Both fall back to ffprobe by design;
  neither has been exercised.
