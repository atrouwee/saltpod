# What is still to do

**Status: a list, kept honest.** Rewritten 2–3 October 2026 after a long
night on the device, because the previous version still listed Sound
Check and podcasts as unbuilt.

Three patterns are worth naming, because each one has cost something:

1. **Device-dependent work has to be batched while the device is there.**
   (The original reason this file exists.)
2. **A module gets built and verified, and then nothing can call it.**
   `bin/layer_census.py` now walks the import graph from both adapters and
   names any shipped module neither can reach. Five remain, below.
3. **A write is not verified by reading it back.** On 2 October two writes
   verified from the page cache, the iPod was unplugged without an eject,
   and the device showed an empty library — Sound Check had reached 619 of
   653 tracks. Every device write now goes through `ipod_edit.write_db`
   (fsync the file *and* the directory, re-read from a fresh descriptor),
   and unsupervised ones through `guarded_write`, which restores the
   original bytes itself if any invariant fails.

---

## 0. OPEN AND BLOCKING: the Podcasts menu will not open

The main menu shows **Podcasts (10)**. Clicking it does nothing — the
screen stays on the main menu. Three fixes have been written and failed:

| tried | matched | result |
|---|---|---|
| mediatype 4 + podcast flag on the type-3 copy | the format doc | counts 10, will not open |
| a show header mhip, episodes grouped under it | libgpod `write_one_podcast_group` exactly | will not open |
| podcast flag on the type-2 copy too | libgpod `write_playlist` exactly | will not open |

**The leading lead, not yet tested:** libgpod's source says *"podcasts do
not show up in the MPL"* (itdb_itunesdb.c:5891). All ten episodes are
members of the master playlist in both sections, because they were added
as music first. "Does nothing" fits a show list that comes up empty after
the firmware filters out master members.

**The master-playlist lead is dead** — the sweep ported libgpod's reader
and ran it on the device's database: to libgpod it is a correct podcast
database, and neither libgpod path excludes podcasts from the master. So
the firmware checks something libgpod never reads.

**Fourth attempt, written 3 October while the owner was away**, through
`guarded_write`, rehearsed against all fifteen checks in
`research/TAXONOMY.md` §1 first:

- the show header's `0x3C` zeroed — it had been cloned from episode 1, so
  the two rows shared a 64-bit id, the one structurally invalid element in
  the database
- libgpod's layout: header id smallest, positions equal to row ids
- the type-2 copy rebuilt byte-identical to type 3 except the group ref
  (Apple's invariant; 0 of 10 rows matched)
- on the episodes: skip-when-shuffling, remember-position and flag4 set,
  unplayed mark, a release date, and one album entry instead of three

**To test:** click Podcasts. If it opens, the parts get reverted one at a
time to find which mattered. If it does not, the next step is Apple ground
truth — let Finder write ONE podcast episode and diff its bytes against
ours — which needs the owner's go-ahead, because Apple's sync renumbers
ids and restamps records (it did at 12:31).

---

## 1. Done since the last version of this file

| | |
|---|---|
| Sound Check | 653/653 tracks, −18 LUFS, from the cached scan; two that would clip if raised get 1000 instead |
| File size | 344 tracks wrong, in **two** fields — `0x24` and its undocumented mirror at `0x12C` — both repaired |
| Podcasts | 10 tracks at mediatype 4, flagged list in both sections, show header written. **Menu still will not open** — see §0 |
| Multiple sources | `saltpod sources list/add/remove`; one track in two places is one track with `copies`, resolved to whichever is mounted |
| Health strip | one slot per removable *volume*, not per source; library reach moved to the library pane |
| Row states | owned-and-ready / owned-but-drive-offline (a dot on the drive badge) / not owned; "needs a drive" filter; Sync counts only what it can write |
| Verbs | `smartlists` `loudness` `rockbox` `devprefs` `podcasts` `sources` `repair` |
| Key, tempo, ISRC, label | `tags.read_extra`, read-only; 36/36/36/53 agree with ffprobe on the local files |
| WAV writing | 368 WAVs with an id3 chunk are writable; unmanaged INFO entries (NITR on 11 files) and `adtl` cue labels are no longer stripped |
| ID3v2.2 | converted to v2.3, every frame or none; 11 of 11 frames and the cover survive |
| Untagged MP3s | writable — `supported()` had a branch that could never run |
| `pagetest.py` | inside `selftest.py`; 25 passing |

---

## 2. Found on 2 October, and what it changes

**The 12:31 write was Apple's.** Music.app or Finder synced the device that
lunchtime: iTunes' signature flags and a populated hash72 appeared, the
album list was rebuilt 245 → 338, track ids were renumbered on 612 tracks,
and 178 records were re-stamped from a donor (the bogus size, its mirror,
an inherited Genius id). Earlier commits blamed `track_add`; that was wrong.
**Keep Music.app closed while the iPod is mounted** — `devprefs` cannot read
the auto-sync setting, so nothing warns about it.

**hash72 is stale.** Since 12:31 every database carries flags saying hash72
is present, with a hash72 over Apple's content; saltpod re-signs only
hash58. Not visibly breaking anything. Before 12:31 both were zero and
everything worked, so zeroing both is the known-good state — waiting on
the sweep's integrity slice.

**Genius is local.** `mhit+0x1E4` holds the `genius_id` that joins a track
to its row in `Extras.itdb` (64 hits at that offset; 63 random integers
give none). The similarity graph itself is gone — it referenced 937 ids
this library does not own — but a mix built from our own data could be
written as ordinary playlists.

---

## 3. Open, needs the iPod

- **Podcasts** — §0, waiting on the sweep
- **Zero hash72 and the signature flags** — waiting on the sweep
- **Smart playlist membership write** — the gate passed (Top 25 matches
  what iTunes wrote, 0 misses); the write path is not built
- **Ratings to the device** — `mhit+0x1F`; 0 of 653 carry one
- **On-The-Go playlists** — made on the device, silently dropped by a sync
- **Bitrate** — wrong on 390 tracks (224 MP3s at the constant 60928; 166
  ALAC files at 160 and labelled "AAC"). Display-only: the fourcc routing
  field is right and the firmware plays them. Low priority.

## 4. Open, needs the library drive

- **Re-index** — repairs the 118 rows restored with null timestamps after
  the fold bug, and carries key/tempo/ISRC/label for all 4,050
- **Differential on the real files** for the WAV writer (368) and the v2.2
  converter (47) — both are proven on built files only
- **Verify `soundcheck_from_itunnorm`** against a track whose iTunes-written
  Sound Check is known
- **Art for the 44 local MP3s** — every local AIFF has a cover, no MP3 does

## 5. Open, no hardware

- **Genius-style mixes** — cluster on genre, era, key and tempo; write as
  playlists and as `.m3u8`
- **`.m3u8` into sync** — the writer is built and wired to real collections
- **Rebuild the browse indexes** instead of dropping them — measured in
  `research/BROWSE-INDEXES.md`: Apple writes ten sort types (libgpod
  five); nine reproduce to within 1–17 out-of-order pairs of 480, `0x23` is
  unidentified. Not to ship until all ten match exactly.
- **Five unreachable shipped modules** — four research one-offs, and
  `itunesdb_patch`, which calls itself "the safest way to write" and
  nothing writes through
- **Accessibility**: no screen reader has ever been run; no roving tabindex
  on the left, source and right panes; the gear's busy dot and the folded
  filter dot are colour-only

## 6. Unknowns

| | how to find out |
|---|---|
| Whether the master playlist's 390 timestamp-shaped positions matter | the format doc says menu order follows mhip order, not the value — compare on-screen order against both |
| What `mhit+0x1F4` is (track id + 1 on 653 of 653) | change it on a copy for one track, see whether anything on the device moves |
| Why a 28-byte block at `0x0DC` reappears at `0x1B0` | diff the two across tracks that iTunes wrote and tracks Apple's sync rewrote |
| Whether the Classic reads the `0x12C` size mirror at all | set them deliberately different on one track in a copy, play it |
