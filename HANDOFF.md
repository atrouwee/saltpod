# HANDOFF

What is true right now, for anyone picking this up.

## Proven on hardware (a 160 GB iPod Classic, stock firmware)

- The checksum: hash58 from the device's FireWire GUID alone. No iTunes secret.
- Editing the iTunes-written database in place; round-trip is byte-identical.
- Playlist rename. Playlist create, in both stored copies. Track add: a new
  record cloned from an existing one, a WAV converted to ALAC, placed and
  played. Playlist re-sequence, read back off the device in exactly the order
  arranged. Playlist deletion. See `research/DEVICE-TEST.md`.

## Not yet proven on hardware

**Track removal** -- the last of the six edit operations. It passes every check
on copies: structure, checksum, lossless re-parse, an independent reader. It is
one `saltpod sync` away, with the iPod in front of you.

Also never performed by hand: a drag between panes. CDP cannot fire HTML5 drag
events, so every drop in this codebase has been exercised through the click
path (`...` -> Add to playlist) instead.

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

## What is imported, and what is not

25 of Apple Music's 182 playlists are in `data/exports/`: the 21 monthlies for
2025 and 2026, plus DayClub, Vinyl, SET - 2025 - Dani and iPod Classic
Selection -- and, as of 2026-09-27, the four playlists *created* in those two
years (WARA - Listening, WARA - UPtemp, Sound Bath, Jazz Party).

The other 157 hold 6,121 tracks and are deliberately out: every monthly from
2017 to 2024, and the long-running archives (Favourite Songs 922, My Shazam
Tracks 539, Echt heel chill 496).

**A monthly does not stand in for a named playlist.** Measured across the 14
named playlists still active in 2025-26: only 18% of their 2,660 tracks appear
in an imported monthly. The exception is a listening list built from what was
actually played -- WARA - Listening is 60% covered, WARA - UPtemp 100% -- while
an archive that reaches back years is not covered at all (Roadtrip 0%, Echt
heel chill 1%). Import a playlist if you want its tracks; do not assume.

## Live updates, and the run log

The page holds an **SSE** connection to `/api/events`. Two kinds of push, and
the difference is deliberate:

- **`data`** -- the facts moved (a job finished, the device was read). The page
  re-fetches and redraws **in place**. Not a refresh: a refresh mid-curation
  loses scroll position, the open sheet and the selected collection, which is
  worse than a stale count.
- **`reload`** -- `curate.html` itself changed on disk, so nothing short of a
  real reload will pick it up. Save the file and every open tab has the new
  page within a second. That is the dev loop; there is no build step.

`EventSource` reconnects by itself, so restarting the server heals every open
tab without a keystroke.

**Every job now writes a durable log.** `data/logs/<timestamp>-<job>.log` gets
each line as it streams, and `data/logs/history.jsonl` gets one record per run
-- id, state, duration, and for a sync the device **before and after**
(track count, every playlist and its length, what was added, removed or
resized). `/api/history` serves the last 50.

This was a real gap: job logs used to live only in memory, capped at 400 lines
and gone on restart, for a tool whose entire purpose is writing to hardware.
Answering "what did that sync actually change?" meant parsing a backup by hand.
Now it is one line of `history.jsonl`.

## Pre-sync on reconnect

Plug the iPod back in and the page re-reads the device and recomputes the plan
before offering you a Sync button. The counts on screen are otherwise
describing a device that may have changed since page load -- which is exactly
how a stale `Sync · 1` survived a sync that had already done the work.

**The bug underneath it is worth remembering.** The page asked `t.device`,
which was `bool(device_metadata_blob)`. Sync clears `on_ipod` on removal but
deliberately keeps the blob, because the origin path and duration stay useful.
So `device` meant *has ever been on the iPod*, and a removed track kept its
`POD` tag, kept appearing under the "on iPod" filter, kept offering "Delete
from iPod", and counted in the Sync badge forever. `device` now means **on the
iPod right now**; `had_device` carries the old meaning where it is wanted.
