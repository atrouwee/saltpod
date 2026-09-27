# saltpod

Playlists on an iPod Classic without iTunes.

The idea in one line:

> You arrange the sequence; the tool makes the iPod carry it.

An iPod Classic navigates by its database, not by its files, so anything copied
onto it is invisible until something writes a database entry — and the firmware
refuses a database whose checksum is wrong, showing an empty library. That
checksum is why third-party sync stayed hard for fifteen years. For the Classic
it needs nothing secret: **hash58**, an HMAC-SHA1 keyed from the first eight
bytes of the device's FireWire GUID, which the device reports as its USB serial.
`src/saltpod/hash58.py` reproduces what iTunes writes, byte for byte.

This is a tool for one kind of device, built by one owner for his own iPod.
It is not a product.

**Picking this up?** [HANDOFF.md](HANDOFF.md) — what is proven, what is not,
what to run.

## Status

**Works, on one device.** Two writes to a 160 GB Classic have been accepted
by the stock firmware and played: a renamed playlist, then a created playlist
with a track added from a lossless original converted to ALAC. Playlist update,
deletion and track removal pass every check on copies and await the device.
No artwork. Existing smart playlists are preserved, never authored.
`research/DEVICE-TEST.md` records each write, with a photograph.

## Getting started

```
git clone https://github.com/atrouwee/saltpod.git
cd saltpod
./scripts/bootstrap.sh
```

The script talks you through what it is doing: it checks for Python 3.9 or
newer and for ffmpeg, finds the iPod's GUID on USB if one is plugged in and
writes `data/device.json`, then — if the iPod is mounted — recomputes the
checksum of the database it already carries and shows it matching. It never
uses sudo and writes nothing outside the repository. Running it again is cheap.

After that, one command:

```
saltpod            # the page: curate, sequence, buy list, vinyl, data jobs
saltpod plan       # what a sync would change on the device; touches nothing
saltpod sync       # backup, convert, copy, write, verify on device, eject
```

`saltpod --help` lists the rest: `device` pulls in what is already on the iPod,
`read` prints a database, `verify` checks one, `reconcile` maps device tracks
back to your originals, `index` walks the music you own, `state` rebuilds or
reports the curation state.

## The page

One file, no build step, nothing fetched from anywhere. Keyboard first.

- **Curate.** `b` keep, `m` maybe, `x` skip, `v` vinyl want-list, `c` put it in
  a collection. `space` plays the whole track from your library, or a
  30-second iTunes preview for music you do not own yet. Every keystroke saves.
- **Collections are sequences.** Drag rows, or `J`/`K` to move one, `space` to
  hear it. The order you arrange is the order the iPod plays. That is the
  product; sync never sorts.
- **Buy** lists only what you chose, with a lossless source where the running
  time was confirmed. **Vinyl** groups the want-list by release. **Data** runs
  the slow jobs — importing playlists from Music.app, matching, verifying — and
  streams their log into the page.

## How it writes

It never regenerates the database. It parses the one iTunes wrote into a tree
whose round-trip is byte-identical, changes only what must change, and
recomputes only counts and lengths — so everything undocumented travels through
untouched. Every new playlist, entry and track record is cloned from one the
firmware already accepted on the same device, then patched. Then it signs,
writes, reads back, and verifies on the device before ejecting. A dated backup
of `iPod_Control/iTunes` precedes every write, and tracks the state does not
mention are left alone.

## Format facts that cost time

- The word at mhod header+8 that looks like an encoding flag is not one; sniff
  UTF-16LE from the bytes.
- List headers `mhlt`/`mhlp`/`mhla` carry a count at `+0x08` and no total_len.
- `mhbd`'s child count is at `0x14`; `0x10` is the version. Keep the version.
- The position mhod's value is the first word of its *body*.
- iTunes stores every regular playlist twice (`mhsd` 3 and 2). Patch both.
- The master playlist's mhod 52/53 indexes are positional: drop them on any
  track change.
- The fourcc at mhit `0x18` is stored byte-reversed (`' 3PM'`). Clone from a
  track of the same extension and you never need to know.
- iTunes signs a hash72 block at `0x72` on Classics; the firmware does not
  check it. Zero it after editing, as libgpod always did.
- Embedded cover art in AIFF is an mjpeg *video stream*; ffmpeg needs
  `-vn -map 0:a:0` or it muxes it into your audio.
- macOS writes `._` AppleDouble stubs on FAT32 with real extensions, and
  ffprobe parses some of them. Skip `._*` everywhere.

## Independence and licence

Unaffiliated with Apple. MIT. The checksum is a port of libgpod's
`itdb_hash58.c` (BSD-3), cross-checked against iOpenPod's implementation.
Everything learned about the format is in `research/`, under the same licence,
so the next person does not have to learn it again.
