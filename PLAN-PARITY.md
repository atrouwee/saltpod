# Closing the iTunes gaps: the plan to execute against

**Status: a plan, not a record.** Nothing here is built unless a phase says
DONE. Every figure is measured -- see `research/ITUNES-PARITY.md` for where
each came from.

## The rule every phase obeys

This writes to a device that holds the owner's library, and a wrong
iTunesDB checksum shows an **empty library** on screen. So:

1. **Rehearse against a backup first.** `backups/` holds seven real device
   states. A phase is not ready to touch hardware until it has run against
   one and the result verified.
2. **Byte-identical where nothing changed.** The round trip already proves
   this for the whole database. After a write, every node we did not
   deliberately touch must still serialise to the same bytes.
3. **hash58 verifies, or it does not ship.** Checked before the file is
   moved into place, not after.
4. **A dated backup precedes every device write.** Already true; keep it.
5. **The differential rule.** Where there is an existing implementation --
   iTunes' own output sitting on the device -- diff against it and chase
   every difference to a cause before declaring agreement.

## Phase 1 -- ArtworkDB writer

**Why first:** 140 covers already on disk that the iPod cannot show. 653
tracks on the device, 652 matched to a file, 399 of those files carry art,
and the device holds 259.

**DONE already:**
- `tags.art_bytes()` -- the largest embedded cover, 91/91 decode
- `artwork.render()` -- all three sizes to exact byte counts, no ffmpeg
- verified against iTunes' own thumbnails: 0.9-7.7 of 255, visually
  identical
- the link found by measuring: `mhii`+0x14 is the song dbid; inside each
  `mhni`, +0x10 is the correlation id, +0x14 the offset into the `.ithmb`,
  +0x18 the byte size

**LEFT:**
1. Append RGB565 to the three `.ithmb` files, recording each offset.
2. Build an `mhii` per track -- dbid from `mhit`+0x70 -- with one `mhni`
   per format, cloned from an entry the firmware already accepted rather
   than authored from the spec. This is the same rule the iTunesDB writer
   follows and the reason it has never produced an empty library.
3. Update the `mhli` count and every enclosing length.
4. Set the track's artwork flags in the `mhit` so the firmware looks.

**Verification gate:**
- round trip an untouched ArtworkDB byte-identically (already a check)
- add art for one track against a BACKUP, re-parse, confirm exactly one
  new `mhii` and three new `mhni`, and the rest byte-identical
- confirm the appended `.ithmb` bytes are at the offsets the `mhni` claim
- only then: one track on real hardware, eject, look at the screen

**Rollback:** the `.ithmb` files are append-only here, so truncating to the
previous length plus restoring ArtworkDB is a complete undo.

**DECIDED:** rehearse fully against a backup, then write **one track** to
the real device and the owner looks at the screen before anything else is
written.

## Phase 2 -- Smart playlist evaluation

**Why second:** the inputs only exist now. Recently Added has 178 tracks
qualifying and shows 0.

**DECIDED:** re-evaluate ALL of them on every sync. The rules are the
truth and membership is derived -- which is what iTunes did, and the only
way a list stays correct rather than correct-once. It does mean a sync
overwrites lists the device currently shows, including the two that are
right today, so the verification gate below is the safeguard and is not
optional.

**DONE already:** `research/SMART-PLAYLISTS.md` decodes the rules and the
decode is verified against real membership -- Top 25 Most Played's 24
members are strictly descending by play count.

**LEFT:**
1. Parse `mhod` 51 into rules and `mhod` 50 into limits. Read only; the
   blobs stay preserved on write.
2. Evaluate against the state. **Refuse any playlist containing a rule we
   do not understand** rather than evaluate it partially -- a half-applied
   rule produces a wrong list that looks right.
3. Write membership as plain `mhip`s, in the order the limit-sort asks for.

**Known unknowns to design around, from the research:**
- field `0x9a` in Favourite Songs exists in no libgpod table. That playlist
  is refused until it is understood.
- libgpod's own evaluator has **no case for the Podcast field** despite
  declaring it typed. Three of this device's playlists use that rule, so
  the reference implementation cannot be copied blindly here.

**Verification gate:** evaluate Top 25 Most Played and compare against the
24 members iTunes already wrote. They should agree. If they do not, the
evaluator is wrong and not the device.

## Phase 3 -- Soundcheck

**What it is:** Apple's volume normalisation, the same job as ReplayGain.
Encoding confirmed on this device: `raw = 1000 * 10^(-dB/10)`, so 1000 is
0 dB and larger is more attenuation. Measured range -0.98 to -10.38 dB
across the 85 tracks that have one, median -5.77.

**Why it matters:** it is the only *audible* divergence. Tracks we add
carry no value, so with Sound Check on they play louder than the
iTunes-era ones beside them.

**The cost, stated plainly:** computing it means measuring loudness per
track. That is an analysis pass over the whole audio, not a tag read, and
nothing in `platform.py` does it today -- afconvert cannot. It would
reintroduce an ffmpeg dependency for exactly the thing we have been
removing one, unless we implement loudness ourselves.

**DECIDED (2 October 2026).** ffmpeg measures it, for every file, but
**computed once and cached** -- on first copy to the device, not on every
sync. It is the one job ffmpeg keeps.

**AND THE TARGET IS A CHOICE, NOT A COPY.** The owner: *"we should have a
target loudness for ipod to perform best, not just flatten it all out."*
So the reference was derived rather than assumed.

What Apple actually aimed at, from the 20 tracks here carrying both a
Sound Check value and measurable audio -- measured loudness plus Apple's
own gain is where Apple was moving the track TO:

    implied target   -17.69 .. -12.28 LUFS   median -15.18   SPREAD 5.41 dB

That spread is the finding. Sound Check was not a LUFS normaliser; it used
an older RMS measure, so it never landed tracks on one level. **Targeting
LUFS properly is better than Apple, not merely equal to it.**

Then the library itself, 90 random tracks:

    integrated loudness   min -17.4   median -11.0   max -5.2 LUFS
    true peak             min  -4.0   median  +0.4   max  +4.0 dBFS

The peaks already clip in the source -- these are loudness-war masters.
Which decides the target:

| target | need AMPLIFYING | exceed -1 dBFS true peak |
|---|---|---|
| -14 LUFS | 24/90 | 21 |
| -16 LUFS | 10/90 | 15 |
| **-18 LUFS** | **0/90** | 5 |
| -20 LUFS | 0/90 | 1 |

**-18 LUFS**, because it is the first target where NOTHING needs
amplifying. Every track is attenuated, so the gain can never add clipping
of its own, and the iPod's volume control takes over with the amplifier
working in more of its range. It is also exactly the ReplayGain 2.0
reference, and about 3 dB more conservative than Apple's loose -15.

Stored as Apple's encoding so the firmware understands it:
`raw = 1000 * 10^(-dB/10)`, where dB = -18 - measured_LUFS.

**Still open:** whether to cap gain for the five tracks whose true peak
would still sit above -1 dBFS after attenuation.

## Phase 4 -- Things the device creates that a sync ignores

**On-The-Go playlists** and **Recordings**. Both are made ON the device and
neither is read, so a sync can discard them. The failure mode is losing
something rather than missing something, which is why this ranks above the
cosmetic gaps despite being small.

**LEFT:** read the On-The-Go `mhyp`, import as a collection, and leave the
device's copy alone. Walk `Recordings/` and index what is there.

## Phase 5 -- Ratings to the device

We read them and cannot set them. One byte at `mhit`+0x1F, stars times 20.
Small, and only worth doing once the page has somewhere to set a rating.

## What runs during a sync

**DECIDED:** artwork, smart playlists and the play-count merge all run as
part of a normal sync; everything else stays an explicit verb.

The play-count merge runs FIRST, before anything is written. That is not
an ordering preference -- the device clears the `Play Counts` sidecar the
moment it sees a changed iTunesDB, so the start of a sync is the only
moment that delta exists.

## Not planned

`total tracks`, `total discs`, `disc number` -- cosmetic on a Classic.
Gapless data -- unmeasured whether the firmware needs it at all, and
measuring that is a separate question from building it.
