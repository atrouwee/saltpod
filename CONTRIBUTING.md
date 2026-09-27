# Contributing

This is one person's tool for one device, published because the format work
in it is hard to find anywhere else. Contributions are welcome; here is how to
make one that lands.

## Read first

1. **README** — what it is and how to run it.
2. **HISTORY** — how it got here and why the rules are what they are.
3. **HANDOFF** — what is true right now and what is open.
4. **Format facts that cost time**, in the README. Each one is a real
   afternoon. Keep them, add to them.

## How to run it against your own iPod

Only the Classic is supported — every model of it uses the same checksum,
keyed from the device's FireWire GUID. Nano 5G and later, Touch and iPhone
use a different scheme that needs a secret this tool does not have.

```
scripts/bootstrap.sh          # finds the iPod on USB, writes data/device.json,
                              # proves the checksum against the database it carries
saltpod read                  # what the device holds
saltpod plan                  # what a sync would change -- touches nothing
```

Everything is a plain local script. It reads Music.app on your machine over
AppleScript, and reaches two public HTTP endpoints you can see in the source
(the iTunes Search API and Bandcamp release pages). Nothing else, and nothing
needs a model.

## The shape of a good change

- **One file, no build, nothing fetched** for the page. It is served from disk
  on every request, so an edit is a refresh away.
- **Python changes need the server restarted**; HTML does not.
- **Paths are relative to the repo, never to a home directory.** The leak gate
  catches `/Users/<name>` but not `~/...`, and a hardcoded `~` path once made
  every import silently write nothing after the repo was renamed.
- **Never write to the device from a test.** `bin/device_test.sh rehearse`
  writes a backup back and proves the round trip; `write` is the only path
  that changes the iPod, and `restore` undoes it.
- **A new verb goes in `cli.py` with a help line that says what it does in a
  sentence.** If the page can do it, the terminal must be able to as well.
- **A new panel takes the shape the others have** — a hairline edge, a title
  strip carrying the name on the left and the panel's one action on the
  right, mono section labels. Look at the sync panel.
- **A new state is a fixed slot, not a thing that appears.** Nothing shifts.

## Before opening a pull request

- Run the verbs you touched. There is no test suite for the format code
  beyond the device itself; the proof is `rehearse` round-tripping
  byte-identical and `plan` reporting what you expect.
- If you changed a format fact, say what you observed and on what firmware.
- If you found a new one, add it to the README's list with what it cost.

## What we will not merge

- Anything that regenerates the database rather than patching it.
- Anything that sorts a collection.
- Rockbox.
- A dependency outside the standard library, ffmpeg and ffprobe.
