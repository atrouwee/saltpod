# First write to the device — 2026-09-27

> **Photographs of the device** are cited throughout by filename
> (`device-test*.jpg`). They are kept in the private working repository
> rather than published here: they are photographs of the owner's own
> hardware, not screenshots of the tool. Every claim they support is
> also stated as a before/after count taken from the database itself,
> which is the evidence that can be checked independently.


**Result: accepted.** Stock firmware booted, showed `Test Rename (saltgate)` in
Playlists with its one track (Migos — Stir Fry), and played it.
Photo: `device-test-2026-09-27.jpg`.

## What was written

The iTunes-written `iTunesDB` (v0x75, 481 tracks, 22 playlists) with exactly
these changes, via `src/itunesdb_patch.py rename-playlist`:

- playlist title mhod string `2018 Apr1` → `Test Rename (saltgate)` in **both**
  stored copies (mhsd types 2 and 3);
- the enclosing `total_len` chain (mhod → mhyp → mhsd → mhbd) grown by the
  string delta, +52 bytes overall;
- `0x70` set to 0 and the 46-byte hash72 block at `0x72` zeroed (libgpod's
  configuration), since the iTunes signature there was stale after the edit;
- `hashing_scheme` (u16 @ `0x30`) = 1 and a fresh **hash58** at `0x58`,
  computed from FireWire GUID `<device GUID>` (`src/hash58.py`).

Everything else byte-identical: track IDs, dbids, smart playlists, iTunes-Store
mhods, `0xA0+` header fields, `Play Counts`, `Extras.itdb`, `ArtworkDB`.

## What this proves

1. **hash58 from the GUID alone is sufficient** on this Classic. No
   iTunes-derived secret, no `SysInfo` needed.
2. **Zeroed hash72 is accepted** by the firmware. It was never checked.
3. **In-place patching is a valid write strategy** — the firmware re-parses a
   file whose lengths were fixed up by hand.

## Procedure that was followed

`bin/device_test.sh rehearse` (backup → device, byte-identical, proves restore)
then `bin/device_test.sh write` (patched → device, verified on-device, ejected),
then unplug, reboot, look. Backup SHA256SUMS verified before each write.

## State of the device now

Carries the patched DB. The pre-write snapshot remains canonical at
`backups/ipod-2026-09-27/` (checksummed). `bin/device_test.sh restore` puts it
back whenever wanted; there is no reason to — the renamed playlist was a
single-track failed-sync remnant.

---

# Second write — playlist create + track add — 2026-09-27 14:24

**Result: accepted.** Via `src/apply.py sync` from a test collection in state:

- `Saltgate Test` created (both stored copies) with 3 tracks — shows in
  Playlists with all three (`device-test2-playlist.jpg`).
- The Beatles — *Her Majesty* added: 26 s WAV from the T7 converted to ALAC
  (`-vn -map 0:a:0 -c:a alac -movflags +faststart`), copied to
  `Music/F32/WSCQ.m4a`, `mhit` cloned from an existing `.m4a` record, id 1246,
  appended to the master playlist in both sections, master 52/53 indexes
  dropped, `Play Counts` deleted. Appears under **Artists › The Beatles**
  (`device-test2-artist.jpg`) — so it is in the library, not just the playlist —
  and plays with correct title/artist/album (`device-test2-playing.jpg`).

**"Goes silent at 22 s" — investigated, not a defect.** The source WAV is
silent from 22.97 s to its end at 25.99 s (3.02 s trailing silence on the 2009
remaster; `silencedetect -50dB`). The ALAC is sample-identical on both counts.
The device played the file as it is.

## Proven on hardware now

rename playlist · create playlist (both sections) · playlist membership with
position mhods · new `mhit` by template cloning · new file placement · master
playlist append · dropped positional indexes · `Play Counts` deletion · ALAC
conversion · hash58 · zeroed hash72. Not yet exercised on the device: track
removal, playlist deletion (both pass on copies).

---

# Third write — playlist update (re-sequence) — 2026-09-27 15:32

**Result: accepted.** Via `saltpod sync`, `set_tracks` on a playlist already on
the device — the first edit to change an existing device playlist rather than
add one.

`Saltgate Test` re-sequenced from state, written as position mhods 1..3 to
**both** stored copies, re-signed, verified on device, ejected:

```
backup: backups/ipod-2026-09-27-153248
  playlist Saltgate Test                  3 tracks
database written and verified on device: 864532 bytes, hash58 OK
```

Read back off stock firmware after unplug and reboot
(`device-test3-order.jpg`), in exactly the order state held:

1. The Beatles — *Her Majesty*
2. 2 Pac — *I Don't Give a Fuck*
3. 28th Street Crew — *I Need A Rhythm*

**Why this one matters more than it looks.** The other writes proved the
database can be edited and the firmware will accept it. This proves the
*product* claim: **sequence is the product**, and the order a person arranges
in the page is the order the device plays. `state.collection_order` went to
position mhods unsorted, through two stored copies, past the checksum, and came
back unchanged on a 2007-era screen. Nothing in the chain reordered it.

Also worth recording: this was a pure update — `0 new, 0 added, 0 removed`. The
sync touched one playlist's membership and nothing else, which is the behaviour
the "never wipes unmentioned tracks" rule promises.

## Proven on hardware now

rename playlist · create playlist (both sections) · **update an existing device
playlist (re-sequence)** · playlist membership with position mhods · new `mhit`
by template cloning · new file placement · master playlist append · dropped
positional indexes · `Play Counts` deletion · ALAC conversion · hash58 · zeroed
hash72.

Still not exercised on the device: **track removal**, **playlist deletion**
(both pass on copies).

---

# Fourth write — a playlist created, from the page — 2026-09-27 ~18:10

**Result: accepted.** The first sync started from the page's **Sync** button
rather than the terminal: plan → the diff shown → confirm → job. `test r`, two
tracks both already on the device, so a pure playlist create; `Saltgate Test`
rewritten alongside it.

Read back off stock firmware after the eject (`device-test4-playlists.jpg`,
`device-test4-testr.jpg`): Playlists shows `test r · 2 Songs` beside `Saltgate
Test · 3 Songs`, and inside it

1. St Germain — *Sittin' Here (Atjazz Remix)*
2. The Mauskovic Dance Band — *Continue the Fun (Space Version)*

in the order arranged. The device ejected itself at the end, as sync does.

**What the owner saw, and what changed because of it:** the panel closed on
confirm and the work ran invisibly — *"I only saw the sync happening on the
iPod."* The sync now prints `## <phase>` lines and the panel stays open as the
progress surface, one line per phase, ending on *safe to unplug*. The child is
run with `-u`; block-buffered stdout would have delivered every phase at once
at the end.

## Proven on hardware now

rename playlist · create playlist (both sections) · **create from the page** ·
update an existing device playlist (re-sequence) · playlist membership with
position mhods · new `mhit` by template cloning · new file placement · master
playlist append · dropped positional indexes · `Play Counts` deletion · ALAC
conversion · hash58 · zeroed hash72.

Still not exercised on the device: **track removal**, **playlist deletion**
(both pass on copies).

---

# Fifth write — a playlist deleted, from the page — 2026-09-27 18:14

**Result: accepted.** `test r` deleted in the page (the collection's *delete*
action), then Sync. Read back off stock firmware (`device-test5-deleted.jpg`):
Playlists shows `My Shazam Tracks`, `My Shazam Tracks1`, `Saltgate Test`,
`Test Rename (saltgate)` — `test r` gone, everything the tool did not make
untouched. The owner: *"Deletion worked."*

Deletion is guarded by `state.synced_playlists`; only a playlist this tool
wrote is ever a candidate. That guard is why the iTunes-made playlists above
survive a sync in which they are not mentioned.

## Proven on hardware now

rename playlist · create playlist (both sections) · create from the page ·
**delete from the page** · update an existing device playlist (re-sequence)
· playlist membership with position mhods · new `mhit` by template cloning ·
new file placement · master playlist append · dropped positional indexes ·
`Play Counts` deletion · ALAC conversion · hash58 · zeroed hash72.

Still not exercised on the device: **track removal** (passes on copies).


---

# Sixth write — an *adopted* playlist deleted — 2026-09-27 19:01

**Result: accepted.** `2018 Dec`, a playlist **iTunes made**, not saltpod —
adopted into `collections` by `adopt_device_playlists()` on a device read, then
deleted from the page and synced.

Verified by parsing the 19:01:39 backup against the live database:

|  | before 19:01 | now |
|---|---|---|
| playlists | 23 | **22** |
| `2018 Dec` | 2 items | **not on device** |
| tracks in the library | 482 | **482** |

**The track count is the point.** Deleting a playlist that holds two tracks
must not delete the two tracks — a playlist is a reference list, and the
`mhit` records live in a different `mhsd` section. Both survived, and both are
still reachable from the master playlist.

This is a different case from the fifth write, which deleted a playlist
saltpod had created itself. Here the deletion guard (`state.synced_playlists`,
which only admits playlists this tool wrote) was satisfied by **adoption** —
the rule that every non-smart playlist on the device becomes an editable
collection. Adoption and deletion work end to end on a playlist whose origin
was iTunes.

## Proven on hardware now

rename playlist · create playlist (both sections) · create from the page ·
delete from the page · **delete an adopted iTunes-made playlist** · update an
existing device playlist (re-sequence) · playlist membership with position
mhods · new `mhit` by template cloning · new file placement · master playlist
append · dropped positional indexes · `Play Counts` deletion · ALAC conversion
· hash58 · zeroed hash72.

Still not exercised on the device: **track removal**. It remains queued —
`plan` lists *Monte Booker — interstellar house mix* (id 439) under removes,
with `2019 Feb` going 1 → 0 and `B - Exp 2` going 6 → 5. One sync away.

---

# Seventh write — a track removed — 2026-09-27 21:08

**Result: accepted. This was the last of the six edit operations.**

Verified by parsing the 21:08:55 backup against the live database:

|  | before 21:08 | now |
|---|---|---|
| tracks in the library | 482 | **481** |
| `interstellar house mix` (id 439) | present | **gone** |
| `2019 Feb` | 1 item | **0** |
| `B - Exp 2` | 6 items | **5** |

Removal is the hardest of the six because it touches three places at once: the
`mhit` record in the track section, every `mhip` that references it in any
playlist, and the master playlist. A miss in any one of them leaves a dangling
reference, which is what produced the 38 broken references across 14 playlists
that started this project. The counts above are that check: one track gone from
the library, and exactly the two playlists that referenced it shrinking by one.

## All six proven on hardware

create playlist · rename playlist · delete playlist (both a saltpod-made one
and an adopted iTunes-made one) · re-sequence a playlist · add a track ·
**remove a track**.

Underneath them: playlist membership with position mhods · new `mhit` by
template cloning · new file placement · master playlist append and removal ·
dropped positional indexes · `Play Counts` deletion · ALAC conversion ·
hash58 · zeroed hash72.

**Still never done by hand: a drag between panes.** CDP cannot fire HTML5 drag
events, so every drop has been exercised through the click path
(`⋯` → Add to playlist). The drag handlers are unproven by a human hand.
