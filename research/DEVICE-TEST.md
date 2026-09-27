# First write to the device — 2026-09-27

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
