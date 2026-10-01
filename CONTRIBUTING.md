# Contributing

This is one person's tool for one device, published because the format work
in it is hard to find anywhere else. Contributions are welcome; here is how to
make one that lands.

## Read first

1. **README** — what it is and how to run it.
2. **HISTORY** — how it got here and why the rules are what they are.
3. **HANDOFF** — what is true right now and what is open.
4. **DESIGN** — the seven laws, the three row shapes, the twelve state words.
   Read it before touching the page; most sloppy UI is one of two laws
   broken.
5. **Format facts that cost time**, in the README. Each one is a real
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

## The layer rule

**A client may look things up. It may not work them out.**

The page is one client. The native app is a second, and anything that ever
talks to the HTTP API is a third. A rule spelled out in the page is a rule
that has to be spelled out again in Swift and once more after that — three
implementations of one sentence, drifting apart quietly.

So the server answers the questions and the clients render the answers:

| The client asks | and gets |
|---|---|
| which lists is this track in? | `lists: ['to buy', 'on T7']` |
| what album does it belong to? | `album_key` |
| do I own this on vinyl? | `vinyl_owned` |
| do I have a file for it? | `held` |
| how many to buy, and for how much? | `totals` |

Membership of a named list is a **lookup**. Deciding what belongs in that
list is a **rule**. `filter === 'to buy'` becomes
`t.lists.includes('to buy')`, and the client gains nothing by knowing why.

Two things are deliberately left client-side, and both are about the view
rather than the library: the sum of whatever the centre pane is currently
showing, and the "is there a file for this" check that decides full ink
versus dim. The server has no opinion about what you are looking at.

`python3 bin/layer_census.py` counts the rule-shaped expressions left in
the page against a budget, each with a reason. The numbers only go down.
It is the same instrument as the design system's token census: it does not
prove the boundary holds, it notices when it moves.

**And the other half: if the page can do it, the terminal must be able to
as well.** That is not a style preference — it is what made the first
hardware test possible when the browser dropped out, and it is the same
surface the native app will use. `bin/layer_census.py` prints both lists so
the gap is visible.

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
- **A new panel takes the shape the others have** — a hairline edge, a 46px
  title strip carrying the name on the left and the panel's one action on the
  right, mono section labels, a scrolling body. Look at the sync panel, and
  read DESIGN part 3.
- **A new state is a fixed slot, not a thing that appears.** Nothing shifts.
- **A name plus one number is a `.col`.** There are three row shapes and a
  fourth needs a reason. DESIGN part 4.
- **Reach for a state word that already exists** — twelve of them, DESIGN
  part 7 — before inventing a thirteenth.
- **Take values off the scale.** If you need a number that is not on it, you
  are probably solving a spacing problem with a new number instead of with
  the container.

## Run the selftest, and diff before you swap

```
python3 bin/selftest.py            # 16 checks, under four seconds
python3 bin/selftest.py --device   # include the iPod, read-only
```

It writes nothing to your library or your device: tag tests run on copies
in a temp directory, device tests read only.

**And when you replace something that works, run the old path and the new
one over the same input and diff every field — before the new one becomes
the default.** This is not caution for its own sake. A Spotlight-based
index looked correct and was 8× faster; the diff against `ffprobe` showed
it losing the artist on 103 files of 300. Chasing that turned up an AIFF
writer that had been wrong for two days and had simply never been called.
Neither was findable by reading.

The pattern to copy: both implementations, the same inputs, every field
compared, and a count of what disagreed. Keep the loser behind a flag with
the reason written beside it rather than deleting it.

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
