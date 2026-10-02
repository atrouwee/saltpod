# Contributing

This is one person's tool for one device, published because the format work
in it is hard to find anywhere else. Contributions are welcome; here is how to
make one that lands.

## Two adapters, one implementation

An operation goes in `curate.OPS` — a dict from name to a function taking a
dict and returning a dict — and both the HTTP server and the CLI dispatch
through it. Neither contains an operation of its own.

This is the server-side half of the layer rule. The client half says *a
client may look things up; it may not work them out.* This half says **the
server may not hide what it works out inside a transport.** The undo
operation lived inside `do_POST` for weeks: unreachable from the terminal,
unreachable from the native app, untestable without a socket.

**Adding a verb is not optional.** `bin/selftest.py` and
`bin/layer_census.py --strict` fail when an entry in `OPS` has no verb,
because a second caller is the only real proof an endpoint is a boundary
rather than a function that happens to be addressable over HTTP.

## Give the challenger a fair run before you conclude anything

**The incumbent arrives tuned. The challenger arrives as a first draft.**
Every comparison in this repo has been biased that way, because the
incumbent is the thing that has been debugged here for weeks and the
challenger is something written this afternoon. Measure them like that and
the incumbent always wins, and the write-up records the challenger's
first-draft problems as *its properties*.

Three times that happened here, and only the large failures got caught:

| | what the first run said | what was actually true |
|---|---|---|
| Spotlight | "no artist, no album_artist, no WAV tags" | **our own line-counting parser** forced a scalar-only attribute list. With `-plist`: 4047/4047 on every text field |
| sips | "61.8/255 worse than ffmpeg" | that compared **scale-to-cover against exact-resize** -- two different operations. Like for like: **1.0/255** |
| afconvert | identical audio, so fine | **32-bit ALAC at 2.4x the size**, with the identical audio md5 that made it look fine |

So, before concluding:

1. **Research the challenger's real interface.** Not the first invocation
   that runs. `mdls` has `-plist`; ALAC carries bit depth in format flags;
   `sips` cannot scale-to-cover in one call and needs two. None of that is
   obscure, and all of it was skipped.
2. **Build it until it does the same job.** If it does a *different* job,
   you have not built it yet, and the difference you are measuring is your
   own.
3. **Say what tuning each side got.** A comparison that does not state this
   is not a comparison.
4. **A surprising result is a bug until proven otherwise.** 117/117 on WAV
   tags was a non-random sample. 0 of 2 mount events was a missing
   callback, not a quiet drive.
5. **Then compare**, on real data, randomly sampled, and chase every
   difference to a cause. Seven of the nine remaining differences in the
   index differential turned out to be the *incumbent* being wrong.

### Use real data, not fixtures you invented

A synthetic fixture tests what you imagined. Real files test what is
actually out there. The resync test first used an image body of repeated
`JUNK`, and the resync locked onto those four bytes as a frame id -- real
cover art is megabytes of arbitrary bytes and some of them spell plausible
frame ids, which is the whole difficulty. The test now takes a real APIC
off the drive.

The same rule found: Beatport's `TDRL`, three date frames on one file, an
`ID3 ` chunk inside a WAV, a FORM file whose tag is not at byte 0, two
files whose frame sizes are wrong, and an mp3 ffprobe cannot read at all.
None of those would be in a fixture anyone invented.

## Prefer the system, but never require it

`platform.py` chooses a backend per operation and every one has a portable
fallback. macOS-preferred, not macOS-only: a contributor on Linux runs the
same code with ffmpeg underneath, and nothing above the adapter knows which
ran.

Two rules learned the hard way, both in `research/MACOS-ADAPTERS.md`:

- **A native tool's defaults are not the other tool's defaults.** afconvert
  writes 32-bit ALAC unless told otherwise — 2.4x the bytes, decoding to
  the identical audio md5, so an audio-only differential passes it.
- **Verify the event, not the setup.** A watcher that starts and stops
  cleanly is not a watcher that fires. DiskArbitration was wired, probed,
  and silently delivering nothing; attaching a real disk image found it.

## Log the operation, never the values

`observe.event()` and `observe.span()` take an operation name, counts, and
field *names*. Not field values: that is the user's metadata, it belongs in
the file. The device GUID is redacted by shape, because a log is a file
people paste into an issue.

Logging must never be able to fail a sync. Write errors are swallowed and
counted.

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
- A dependency outside the standard library, ffmpeg and ffprobe.

**Rockbox was on this list and is not any more.** The owner reopened it on
2 October 2026, and with a framing that changes what it means: *"rockbox is
an adaptor like native ipod software."* Not a fork and not a second
product -- a TARGET below the boundary, a peer of the Apple firmware, the
way `platform.py` already picks between afconvert and ffmpeg per operation
with the caller knowing nothing about it. See `research/ROCKBOX-DELTA.md`.

The original objection still stands against the thing it was aimed at: a
Rockbox-shaped rewrite of the sync path. It never applied to an adapter.
