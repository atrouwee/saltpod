# saltpod

Playlists on an iPod Classic without iTunes. Curate in a local web page,
sequence by ear, sync to the device — the database is edited in place and
signed with the checksum the Classic's stock firmware requires.

Python 3, standard library only, plus `ffmpeg`/`ffprobe`. macOS.

## Why this exists

The iPod Classic navigates by its `iTunesDB`, not by the filesystem, so files
copied onto it are invisible until something writes a database entry — and
the firmware rejects a database whose checksum is wrong, showing an empty
library. That checksum is the whole reason third-party sync stayed hard.

For the Classic it turns out to need nothing secret: **hash58**, an HMAC-SHA1
over the file keyed from the first 8 bytes of the device's FireWire GUID,
which the device reports as its USB serial. `src/hash58.py` reproduces the
signature iTunes writes, byte for byte. (The schemes that *do* need
iTunes-derived secrets — hash72, hashAB — belong to the nano 5G, Touch and
iPhone, not the Classic.)

## What it does

```sh
cp data/device.example.json data/device.json    # set your GUID, mount, library
python3 src/curate.py                             # one command; everything is in the page
python3 src/apply.py plan                         # what a sync would change
python3 src/apply.py sync                         # backup, convert, copy, write, verify, eject
```

- **Curate** — a keyboard-first page: `b` keep / `m` maybe / `x` skip, `v`
  vinyl want-list, `c` collection. `space` plays the full track from your
  library, or a 30s iTunes preview when you don't own it yet.
- **Collections are sequences.** Drag or `J`/`K` to arrange; the order you set
  is the order the iPod plays. That is the product.
- **Sync** never regenerates the database. It edits the one iTunes wrote — a
  lossless tree model whose round-trip is byte-identical — cloning every new
  structure from one the firmware already accepted, then re-signs. Tracks you
  didn't mention are left alone. FLAC/WAV/AIFF are converted to ALAC.
- **Import** what is already on the device and curate it too; map it back to
  your originals; remove what you won't listen to.

Proven on a 160 GB Classic (`research/DEVICE-TEST.md`, with photos).

## Finding your GUID

```sh
ioreg -p IOUSB -l -w 0 | grep -A12 iPod | grep "USB Serial Number"
```

Sixteen hex characters. Put them in `data/device.json`. `Device/SysInfo` on
the iPod is often empty; the USB serial is the same value.

## What is in here

| | |
|---|---|
| `src/hash58.py` | the checksum, standalone |
| `src/itunesdb.py` | read-only parser |
| `src/itunesdb_write.py` | lossless tree model: parse, edit, serialise |
| `src/ipod_edit.py` | playlist create/delete/rename/sequence, track add/remove |
| `src/apply.py` | plan and sync the curation state to the device |
| `src/curate.py` + `curate.html` | the page: curate, sequence, buy list, vinyl, data jobs |
| `src/state.py` | one record per track, decisions preserved across rebuilds |
| `src/reconcile.py` | map device tracks back to library originals |
| `research/` | the format notes and the device tests |

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
- iTunes signs a hash72 block at `0x72` on Classics; the firmware doesn't check
  it. Zero it after editing, as libgpod always did.
- Embedded cover art in AIFF is an mjpeg *video stream*; `ffmpeg` needs
  `-vn -map 0:a:0` or it muxes it into your audio.
- macOS writes `._` AppleDouble stubs on FAT32 with real extensions, and
  `ffprobe` parses some of them. Skip `._*` everywhere.

## Status

Works, on one device, for one owner. Track removal and playlist deletion pass
every check on copies but have not yet been exercised on hardware. No
artwork. No smart playlists (existing ones are preserved). Back up
`iPod_Control/iTunes` before the first write — `sync` does, every time.

MIT. The checksum is a port of libgpod's `itdb_hash58.c` (BSD-3), cross-checked
against iOpenPod.
