# HANDOFF

What is true right now, for anyone picking this up.

## Proven on hardware (a 160 GB iPod Classic, stock firmware)

- The checksum: hash58 from the device's FireWire GUID alone. No iTunes secret.
- Editing the iTunes-written database in place; round-trip is byte-identical.
- Playlist rename. Playlist create, in both stored copies. Track add: a new
  record cloned from an existing one, a WAV converted to ALAC, placed and
  played. See `research/DEVICE-TEST.md`.

## Not yet proven on hardware

Playlist update (re-sequencing an existing playlist), playlist deletion, track
removal. All three pass every check on copies: structure, checksum, lossless
re-parse, an independent reader. Each is one `saltpod sync` away; do them in
that order, with the iPod in front of you.

## What to run

```
./scripts/bootstrap.sh     # once
saltpod                    # the page
saltpod plan               # what a sync would change
saltpod sync               # do it
```

## What not to touch

- The format facts in the README. Each one cost time.
- `research/`. It is the record.
- The one orange in the page.
