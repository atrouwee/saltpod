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
reports the curation state, `applemusic` reads your Music.app library, and
`discogs` reports on your Discogs exports.

Every one of them is a plain local script. Nothing here calls a model, a
remote service, or anything but Music.app on your own machine and two public
HTTP endpoints you can see in the source.

## The two libraries it reads

**Apple Music**, over AppleScript, on your machine:

```
saltpod applemusic read              # playlists, their dates, and every library track
saltpod applemusic playlists         # what exists, and what you have imported
saltpod applemusic peek "Jazz Party" # look inside one without importing it
```

The read is cached at `data/exports/_apple_music.json`, so the page opens
instantly and you refresh when you want to. Music.app has **no creation date
for a playlist** — its whole property list is id, index, name, persistentID,
duration, size, time, visible, specialKind, loved, hated, smart, shared,
genius — so the date shown is derived: the earliest a track in it was added.
That is exact for a playlist built in one go and wrong for one assembled from
back catalogue, which will read as the age of its oldest track.

Everything in the library is browsable, but a track earns a record only when
you decide on it. Otherwise the curation queue would be your whole library and
would mean nothing.

**Discogs**, from its own exports. Download both CSVs from your Discogs
account and drop them in:

```
data/discogs/wantlist.csv
data/discogs/collection.csv
saltpod discogs status               # what they hold, and what is flagged but on neither
```

They are read on every request; nothing is fetched and no account is
connected. A track meets a release on artist + album, lowercased, with
bracketed suffixes like `(2)` and `(Remastered)` stripped. The match is strict
on purpose — a wrong "you own this" is worse than a missing one.

One gotcha the wantlist export will cost you otherwise: it carries a trailing
`Date Added` column its header does not name, so pad headers rather than
trusting them.

## The page

One file, no build step, nothing fetched from anywhere. Keyboard first.

- **Curate.** `b` keep, `m` maybe, `x` skip, `v` vinyl want-list, `c` put it in
  a collection. `space` plays the whole track from your library, or a
  30-second iTunes preview for music you do not own yet. Every keystroke saves.
- **Collections are sequences.** Drag rows, or `J`/`K` to move one, `space` to
  hear it. The order you arrange is the order the iPod plays. That is the
  product; sync never sorts.
- **Buy** lists only what you chose, with a lossless source where the running
  time was confirmed. **Vinyl** shows the pipeline in its one direction —
  flagged here, wanted on Discogs, owned — so the first group is the to-do.
- **Where a track lives**, on every row, in a fixed order: `AM T7 POD LP`.
  Apple Music, the drive you keep your files on, the iPod, a record you own.
  The places are peers; no claim is made about which came first, because a
  track can be in all four and the order is unknowable. Owned shows in full
  ink and rented stays dim, and a row still to be synced is dimmed. The
  subtitle separately names what a click would play.
- **Two libraries, one switcher.** The left pane is either your iPod —
  collections, the only thing you edit, and what sync writes — or Apple Music,
  which is there to take from and never edited.
- The gear runs the slow jobs — reading Apple Music, importing a playlist,
  matching, verifying — and streams their log into the page.

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

## Reading further

**HISTORY.md** is how this came to be — the finding that started it, every
phase since, and the owner's own words where they carried a decision. Read it
before changing a rule; each one has a reason there. **CONTRIBUTING.md** is
how to run it against your own Classic and what a change that lands looks
like. **HANDOFF.md** is what is true right now.

## Independence and licence

Unaffiliated with Apple. MIT. The checksum is a port of libgpod's
`itdb_hash58.c` (BSD-3), cross-checked against iOpenPod's implementation.
Everything learned about the format is in `research/`, under the same licence,
so the next person does not have to learn it again.
