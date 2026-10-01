# HANDOFF

What is true right now, for anyone picking this up.

## Proven on hardware (a 160 GB iPod Classic, stock firmware)

- The checksum: hash58 from the device's FireWire GUID alone. No iTunes secret.
- Editing the iTunes-written database in place; round-trip is byte-identical.
- Playlist rename. Playlist create, in both stored copies. Track add: a new
  record cloned from an existing one, a WAV converted to ALAC, placed and
  played. Playlist re-sequence, read back off the device in exactly the order
  arranged. Playlist deletion. See `research/DEVICE-TEST.md`.

## All six edit operations are proven on hardware

create playlist, rename, delete (both a saltpod-made playlist and an adopted
iTunes-made one), re-sequence, add a track, and -- as of 2026-09-27 21:08 --
**remove a track**. Each one is recorded in `research/DEVICE-TEST.md` with the
before/after device counts it was verified against.

## Not yet proven

**A drag between panes, by a human hand.** CDP cannot fire HTML5 drag events,
so every drop has been exercised through the click path (`...` -> Add to
playlist). The drag handlers themselves have never been used by a person.

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

## The page, as of the night of 27 September

**Four panes.** iPod (collections) at the far left; the **source** pane
beside it, holding Apple Music and the drive behind two pills exactly as Buy
and Vinyl share the pane on the right; the list in the centre; Buy / Vinyl on
the right. You take from one source or the other, never both at once, so they
never need to be on screen together.
The switcher that used to put the two libraries behind one pane is gone -- it
hid the collections at exactly the moment you wanted to drop something on one.

**The rule that joins them:** *the last playlist clicked -- iPod or Apple Music
-- is what the centre shows.* `active` in the page holds which; the centre's
label carries the library name (`2026 July · apple music`) so it can be read
without looking left.

**Which list is active is readable from the panes.** One slot, one meaning:
the pick in the pane driving the centre is `on` (raised, bold); the other
pane's remembered pick is `was` (bold, hairline, no fill). The inactive pane's
title dims.

**A playlist is a thing you can drag.** From the Apple Music pane onto a
collection, or onto `+ new`. `pourPlaylist()` gives every track a record if it
has none and appends them in the playlist's own order after whatever is
already there -- new members append, never re-sort -- then sets the order
explicitly. Its `...` does the same by clicking: *Make a collection*, *Add all
to playlist*, *Import for curation* (known, not on the iPod -- the old import).

**Dropping a playlist does not put music on the iPod.** It declares what
belongs there; sync writes what it finds a file for and names the rest. With
4,680 of 4,892 library tracks rented, most of a fresh playlist arrives at
opacity and lands in Buy. That is the gap the tool exists to close.

**Folds.** The `<` / `>` left of each pane's title folds it; a folded pane is
a 24px rail with the title turned vertical and the chevron pointing the way
back, and the whole rail is the click. **A rail carries its name and nothing
else** -- the view marks and the plus are hidden with the body, since they
overlapped the turned title and offered to switch a view that is not on
screen. The strip is a fixed 46px when the pane is open and `height: auto`
when it is a rail, or the turned title would be clipped to 46px. Each pane is pinned to its own grid
track, so folding one never moves another. `[` and `]` still fold the outer
two. Apple Music folds by itself under 1100px, the outer two under 860px.

**The header is one line.** Brand, search in the centre, and on the right the
counts at lower opacity beside Sync and the gear. The counts give way before
the buttons do and clip at their end, because the first number matters most.
Buy / Vinyl moved into the right pane's title strip.

**Still never done by a human hand:** a drag. There are now two -- a track
onto a collection and a playlist onto one -- and both have only been driven
through the click path. CDP cannot fire HTML5 drag events.

## The drive pane

The third left pane is the music already owned, read from
`data/local/index.json` and **grouped by the folders on the drive itself**.
No taxonomy is invented: the folders are how the music was filed when it was
bought, and any scheme the tool imposed instead would be a second, worse one
to keep in your head. 72 folders, 4,048 files. Files loose in the root form
one group named after the root.

581 of those files carry no tags at all, so a blank row would be useless to
browse: **the filename stands in** as the title, and the key is derived from
it. `Bought Tracks` alone is 1,180 files and mostly untagged.

A folder drags onto a collection, or onto `+ new`, exactly as a playlist does
-- `pourFolder()`, the same shape as `pourPlaylist()`. Its `...` does the same
by clicking. `/api/local` serves the folder list; tracks come one folder at a
time, the way a peek reads one playlist.

Folding is outside-in by window width: the drive folds below 1500px, Apple
Music below 1250, the outer two below 860. Five panes need about 1500px
before the list stops being the thing that suffers.

## One implementation, two adapters

Every operation lives once, in `curate.OPS`: a table from name to function,
each taking a dict and returning a dict. No request object, no argv, no
printing, no exit codes.

```
                    curate.OPS
          decide  undo  discard  recover  tags  track
                  /              \
          HTTP handler        saltpod <verb>
       (four lines of        (argv -> dict,
        dispatch)             dict -> receipt)
```

**A second caller is the proof an endpoint is a boundary.** An operation
only the page can reach is a function that happens to be addressable over
HTTP; one the terminal reaches too has a shape that survived contact with a
client that is not a browser. Five operations had no verb and they were the
five newest, which is how the gap always opens: the page needs something,
the endpoint gets written, and the terminal is what nobody remembers. The
native app would have been the first client to find out.

Adding five argparse branches would have been five *second
implementations* — the same mistake the layer rule forbids on the client
side. Hence the table. Getting there meant lifting the undo operation out
of `do_POST`, where its whole implementation lived: a rule welded to a
transport cannot be called by the terminal, cannot be called by the native
app, and cannot be tested without a socket.

`bin/selftest.py` and `bin/layer_census.py --strict` both fail when an
entry in `OPS` has no verb, and the check caught one the hour it was
written.

### What that bought immediately

Instrumenting the table instrumented both clients at once. `observe.py`
wraps every operation in a span, so there is exactly one place an operation
is timed and one place a failure is recorded — the page, the terminal and
whatever calls the API next all run through it. Had undo still lived inside
the HTTP handler, it would have been the one operation nobody could see.

## The event log

`data/logs/events.jsonl`, one JSON object per line: `ts`, `level`, `op`,
`run`, `ms`, `msg`, `data`. A `span()` times an operation and records errors
with a trimmed traceback before re-raising; one `run` id ties every event of
one sync together. Rotates at 5 MB, three generations. Thread-safe, because
the server is threaded. The FireWire GUID is redacted by shape, because it
is a secret and a log is a file people paste.

**Logging failing is never a reason for a sync to fail** — write errors are
swallowed internally and counted, and `observe.dropped()` says how many.

`saltpod log` reads it back, with `--op`, `--run`, `--level` and
`--summary`, so the log has a second caller and not only a writer. Every
sync failure so far has been something nobody could see afterwards: a track
in two states at once, a playlist that could never settle, a track id
invalidated by an earlier removal. Each cost an evening of re-running the
whole thing to watch it happen again.

## Accessibility: what is done, and what is not

Done, with no visible change to the page at rest (checked by loading it):

| | |
|---|---|
| `:focus-visible` | a ring on the keyboard path, which was real and invisible. Reuses `--sel-hi`, law 2's own token for "where you are" |
| roles | listbox/option, generated inside `colRow()` so it is one place rather than hand-attached per row; panes and list bodies named |
| live region | one polite region, announced from `decide()` — the single function all 23 decision call sites funnel through |
| second channel | law 2's orange (playing) and law 3's opacity gap (unowned) both get a text channel; `aria-selected` carries law 2's blue |
| motion | the one unwrapped transition now respects `prefers-reduced-motion` |

**The role comes from the caller.** `colRow()` first emitted
`role="option"` unconditionally, including into three containers that are
not single-choice lists — and an `option` outside a `listbox` is invalid
ARIA that announces *worse* than no role. The sync panel's rows are
**checkboxes**, not a report, because you click one to leave it out of the
run. Both `aria-selected` and `aria-checked` read the one class string the
caller already built, never a second fact, which is why the layer census
did not move.

Still open, and deliberately: no roving tabindex on the left, source and
right panes (they are click-and-drag only today, and wiring arrow keys
there is a real redesign); the gear's busy dot and the folded-filter dot
are still colour-only; and nobody has run a screen reader against this
page.

## TODO — the front end has no behavioural test, and no accessibility one

`bin/selftest.py` is a **server** suite. Of its eighteen checks only three
touch the page, and all three are static:

| | what it proves |
|---|---|
| inline script parses | it is syntactically valid |
| no literals outside `:root` | it conforms to the design tokens |
| front end does not decide | it is within the layer-rule budget |

**None of them proves anything works.** Every behavioural bug in the page
so far was caught by a person clicking, or by me driving the browser by
hand — shift-click dragging a text selection, `⌘Z` swallowed whenever a
panel was open, the track panel unable to open the 581 files it exists
for, fields that did not look like fields. A parser cannot see any of
those.

And accessibility has never been looked at once. What is already known to
be missing, from the code as it stands:

- ~~no focus-visible styling~~ — done, see above
- ~~no ARIA roles~~ — done for the four panes and the row builder; the
  dialogs' own controls are still bare
- colour in two laws now has a second channel; the gear's busy dot and the
  folded-filter dot do not
- ~~`.row.unowned`'s opacity doing semantic work~~ — it carries a title now
- ~~no live region~~ — done; one polite region, announced from `decide()`

**Shape it would take when it is time:** drive the real page headlessly,
assert behaviour rather than markup — a shift-range marks N rows and
selects no text, a save writes the file and leaves one undo entry, Escape
closes a panel without discarding edits — plus an axe-style audit pass. It
belongs beside `selftest.py`, not inside it: different runner, different
speed, different failure modes.

Deliberately not built yet.

## Cancel is not Close

The sync panel has two ways out and they must never blur into one.

**Close** — the scrim, `esc`, the `esc` affordance — puts the panel away and
changes nothing.

**Cancel** throws the staged changes away, so it is a named button that
raises a centre prompt first. It sits in the foot beside Confirm rather than
where the closing affordances are.

There is no queued operation to cancel: **the plan is derived**, the
difference between what you have decided and what the device holds. So the
only way to empty it is to take the decisions back, and that is literally
what `/api/discard` does:

| | becomes |
|---|---|
| tracks marked remove | undecided |
| tracks marked sync, not yet copied | undecided |
| a playlist never written to the device | the collection goes |
| a playlist whose members moved | back to exactly what the device holds |
| a collection deleted but still on the device | re-adopted as it is there |

Metadata edits are **not** touched — they are already in the file, which is
the master, and undoing one is its own act with its own entry on the stack.

**It is one undo entry**, which is a deliberate departure from the brief.
That asked for no undo. Everything else in this tool reverses — law 8 — and
an action this broad is the last one that should be the exception. The
prompt says `⌘Z brings it back`, which makes it a smaller decision to take
rather than a scarier one.

Verified on the live plan: 6 removes and a new playlist went to an empty
plan, and `⌘Z` brought both back. State compared before and after **as it
loads** — identical.

That last part matters and cost a confused minute: the state *file* differed
because `migrate()` promotes a collection member from `undecided` to `sync`
**on every load**, so the file can hold one value while every read sees
another. Comparing files says they differ; comparing what loads says they do
not, and what loads is what is true.

## One store. The iPod is downstream.

**The file on disk is master. The iPod is a slave that catches up on the
next sync.** There is no such thing as "iPod metadata" to be edited, and no
reason to ever show the two side by side.

This was nearly got wrong. Reading the device turned up two stores — the
tags in the files on the drive, and the iTunesDB's own `album artist bitrate
composer filetype genre id location ms size title track_no visible year` for
all 658 tracks — and the obvious next move was a panel showing both with the
differences marked. That would have institutionalised a bug: a permanent
control on screen for a state that should not outlive one sync.

What follows from the rule:

- **Editing writes the file, always and first.** Nothing is staged in an
  overlay, nothing is written only to the device.
- **A device entry that disagrees with its file is drift**, and ending it is
  the plan's job, not the panel's job to display. Those rows join the sync
  panel like any other, tickable, in execution order.
- **Undo is forward, not backward.** Undoing after a sync rewrites the file,
  which bumps mtime, which re-probes, which finds the reverted values, which
  queues a fresh update. The device catches up again. This works only
  because `plan()` compares values rather than tracking a dirty flag — a
  flag would have been cleared by the sync and the correction would never
  have been queued.
- **The fallback in `sync()` retires.** `meta['title'] or r['title']` is
  what let the device be right about tracks the drive was wrong about: an
  untagged file copied across took its name from the state record. Useful
  while files were unfixable; once they carry their own names it is papering
  over the master, and it goes.

The measured starting point, 30 September: 581 files on the drive with no
artist or title, and **2 blank artists, 1 blank album, 12 blank genres out
of 658 on the device.** The drive is the side that is wrong.

## When the only copy is on the iPod

The file is master — so what happens to a track whose file is gone?

**You bring it home.** The iPod is a disk:
`iPod_Control/Music/F07/ABCD.mp3` is an ordinary file with a scrambled name,
and everything that makes it findable lives in the database. So the copy is
a plain copy, and the naming comes from the database entry that has been
carrying the truth all along. Once it lands on the drive it is an ordinary
local file and every other rule applies unchanged.

That is deliberately **not** an exception to "one store" — it restores it.
The alternative, editing the device entry directly, would create a second
place to edit and reintroduce exactly the drift the rule exists to prevent.

`POST /api/recover` copies the file to `<library root>/Recovered from iPod/`,
names it from the database, writes those tags into the copy where a writer
exists, records the path as the track's `origin` so the join finds it again,
and adds it to the drive index on the spot — a recovery that needs a full
reindex before it can be edited is a recovery you have to remember to
finish.

On this library the case is **1 track of 644**. It matters anyway: an iPod
outliving the machine that filled it is the ordinary way these collections
end up stranded, and the audio was never the part that went missing.

## A stored value is not a promise

Every persisted enum is now read through `oneOf(value, allowed, fallback)`.

The bug that bought this: `stab` — which source the shared pane shows — came
back from `localStorage` holding `'ipod'`, a value no current code path can
produce, left behind by a build where the source tabs and the active pane
shared a variable. Nothing validated it, so `drawSrc()` fell through both
the `'am'` and `'t7'` branches, `ensureSrcAll()` fetched the wrong index, and
album view sat on *Loading…* **permanently** — for that browser, across
reloads, with no way out but devtools.

Three values were exposed this way: `stab`, `active`, and the `MODE` object.
The booleans were safe by construction because they are compared to `'1'`.

The general rule, and it is not only about `localStorage`: **the set of legal
values moves underneath anything you persist.** The same class of bug would
have hit the tier rename if `filter` were stored — a saved `'maybe'` would
have wedged the centre list on an empty view. Validate on read, fall back to
the default, never trust what an older version of yourself wrote down.

## Multi-select

`sel` is still the cursor -- an index into `view`, and scroll memory, nudge,
play and the row menu all depend on it. The selection is a **separate set on
top of it**, and it holds **keys, not indices**: an index is invalidated by
every redraw, filter and sort, and a stale index silently acts on the wrong
track. A key is the same track forever.

The three conventions, unmodified from every list in every OS: **click**
replaces, **shift-click** takes the range from the cursor, **cmd-click**
toggles one. `⌘A` takes the visible list, `Escape` drops the selection, a
plain arrow collapses it.

**Shift+arrow now extends the selection.** It used to be an alias for nudge;
`J`/`K` keep nudge, which is saltpod's own idea, and shift+arrow goes back to
the convention it belongs to.

**A selection belongs to one list.** `MARKLIST` records which, and changing
pane, playlist, filter or search clears it. A mark you cannot see is a mark
you will act on by accident, and every action here reaches the device
eventually.

Three rules make the bulk case honest rather than merely possible:

- **A tick means all of them.** `Sync to the iPod` shows a tick only when
  every selected track is already `sync`. A tick on a mixed set would claim
  something untrue about most of the rows.
- **Already-there is a no-op, not a refusal.** Dropping ten tracks on a
  playlist that holds three of them adds the seven and says
  `7 added · 3 already there`.
- **A mixed flag turns on.** Selecting a mixed set and pressing `v` flags
  everything; it does not toggle each one to its opposite.

The cursor can sit on a row that is *not* in the selection -- cmd-click it
out of a range and it does. So with a selection live, a cursor row outside it
is drawn as an **outline instead of a fill**: still obviously the cursor,
obviously not included. Without that, the row it will skip looks exactly like
the rows it will act on.

**Dragging carries the selection.** The payload is newline-joined keys and
every drop target reads it through `dropKeys()`, so the single-track case is
one element rather than a second code path. Inside a collection a dragged
block **moves as a block and keeps its internal order** -- the sequence
within a selection is as much the product as the sequence of the list.

The server needed nothing: `/api/decide` already took `keys: [...]`, and one
bulk write is one undo step.

## One question per track: sync or remove

The tool asks a track one thing -- *does this belong on the iPod?* -- and
takes three answers: **`sync`** yes, **`remove`** no, **`undecided`** not yet
asked. That is the whole decision model.

It used to be four tiers and a flag: `seen`, `shortlisted`, `maybe`,
`skipped`, plus a separate `wanted` boolean that sync actually read. Across
1,211 real tracks `maybe` and `shortlisted` were both **zero**. Nobody
reaches for a mood when the question is binary, and `wanted` duplicated the
tier from a second column, so two fields could disagree about the same
sentence. `migrate()` in `state.py` folds the old names forward on load and
is idempotent, so no data was rewritten by hand.

Two more fields went with them. **`note`** was never written by anything and
is gone. **`bought`** is no longer stored -- a file existing on the drive is
what bought means, so it is derived, which removed a flag that could be
wrong. **`vinyl`** stays: it answers a different question and a track can be
both.

The names say what sync will do, which is the point. `Sync to the iPod` and
`Remove from the iPod` in the row menu, `s` and `x` on the keyboard, `u` back
to undecided.

## Adding to a collection is the decision to buy

Putting a track in a collection says it belongs on the iPod. If there is no
file for it and it was never bought, that is the same sentence as *I have to
go and buy this* -- so `apply_decision` promotes it to **`sync`**, and it
appears in Buy. It fires only from an undecided or removed tier, never over a
decision already made, and never for a track the index holds a file for. Pouring a folder off the drive therefore adds nothing to the buy list;
pouring an Apple Music playlist adds most of it, which is the gap the tool
exists to close.

A track leaves the buy list the same way it arrived: its `...`, where
**Undecided** withdraws the decision. Buy cards carry the three dots too, so
the menu is reachable from the list the track is actually in.

**Being in a playlist is itself the decision**, so `Undecided` is not offered
for a track in one -- the server would promote it straight back to `sync` and
the row would look broken. Take it out of the playlist first; that row sits
directly above.

## Lookup happens when a track joins the buy list, not before

Identity, price and a lossless source are only interesting for a track you
have decided to buy. Matching a whole playlist up front spends hundreds of
requests on tracks that will never be marked, and the answers go stale
before they are read. So `apply_decision` queues a single iTunes lookup the
moment a track is marked `sync` -- by hand, by menu, or by the collection
rule above -- and a background worker resolves it in about a second and
pushes `data` over SSE.

**Duration is fetched with it, and this is not optional.** Without a duration
every match scores `variant` and a human has to check each one, which is the
work the lookup was meant to remove. `wanted_seconds()` takes it from the
device, else the drive index, else the Apple Music library, through a
memoised key -> seconds map (9,000 entries, rebuilt only when either index
changes). With it, Sault - Power and Barker - Fluid Mechanics both score
`exact` instead of `variant`.

Every buy card carries a **fixed state slot**: *looking up iTunes…* while in
flight, then *iTunes exact · 8:00 · bandcamp confirmed*, or *not on iTunes ·
try Bandcamp*, or *look it up* as a link for anything marked before this
existed. One slot, four states, nothing moves. A link above the note looks up
everything still unknown in one go.

**Bandcamp is deliberately not in this path.** Its search returns an empty
page to a cookieless request, so availability needs a real bandcamp.com tab
and stays a batch job -- run against a buy list that is now short by
construction. `bin/bandcamp_search.js`, and mind the throttling note in its
header.

## Coming back to where you were

Every pane restores both its **scroll offset and its selected row**, keyed by
what was in it -- an Apple Music playlist and a drive folder are different
places, and each comes back to its own. `listKey()` is that identity
(`list:<source>:<pick>:<filter>:<query>`); `SCROLL` and `SELMEM` both key off
it.

**Three bugs are buried in this, and all three were about background tabs:**

1. The offset must be read **synchronously, before the pick changes**, under
   the key the pane is leaving. A `scroll` listener cannot be the source of
   truth: **a backgrounded tab dispatches no scroll events at all**, not even
   for a programmatic `scrollTop`, so the memory is simply absent whenever the
   window sits behind another one. The listener survives as a top-up for the
   foreground case.
2. The first version cleared a `drawing` flag inside `requestAnimationFrame`,
   which also never fires in a background tab -- so the flag wedged on and
   disabled recording for the rest of the session. It is a **deadline** now
   (`drawUntil`), because a deadline expires whether or not a callback runs.
3. `mark()` scrolls the selected row into view, which is right when you moved
   the selection and wrong during a redraw, where it fought the restore and
   won. It is skipped while a redraw is in flight.

And one that was not about tabs: an empty list still being fetched used to
clamp `sel` to 0 and then save that, wiping the remembered row before the
rows arrived. The clamp now only runs on a list that has rows.

## What the dim rows mean

**Full ink means you could put it on the iPod today** -- a file exists,
either already on the device or on a drive sync can read. **Dim means you
cannot**: not bought, or bought and not yet indexed.

It used to mean "not on the iPod yet", which dimmed tracks you already owned
and were merely waiting to copy -- a fact about the transfer rather than
about whether you have the music. The owner's intent was always the second
one: *"only the tracks that can go onto the iPod are fully bright white
because they're available, they're purchased."* Availability is the gap this
tool exists to close, so it is what the eye should catch while scanning.

The row class is `unowned`, set from `t.device || t.local`. Note that it does
not change when the drive is unplugged: `local` is read from the index, not
from the volume, so the list does not go dark when you pull the T7.

**The iPod has its own mark, at the end of the row.** A drawn Classic --
body, screen, click wheel -- at 8x13, **drawn only when the track is
actually on the device.** It was first built as an always-present mark that
went faint when absent, which was wrong twice over: a faint iPod still looks
like an iPod, and because the dim rule only dims `.t` and `.art`, the
placeholder rendered at full strength beside a title at 45% -- the phantom
was *brighter than the track name*. The slot keeps its width so nothing
shifts; the mark is either there or it is not.
It sits beside the chevron rather than in the source strip, because *is this
on the thing* is the highest-priority fact in the row and it must never move:
in the strip it slid left and right as tags appeared.

**The pill shows the figure that actually discriminates for the format.**
Bitrate is the quality knob for a lossy file -- 128 against 320 is audible.
For a lossless one it is a side-effect of how dense the music is: this
library's own lossless tracks run 807 to 1122 kbps and are all the same
fidelity. So it is `320k` for lossy and `16/44.1` for lossless. Depth and
sample rate come from the drive index, which now captures them via
`-show_streams`; until the drive is re-indexed a lossless file reads as plain
kbps, which is honest and self-correcting.

**It is the ORIGINAL on disk, never the copy on the iPod.** The device holds
a converted file -- a WAV original arrives as ALAC at about half the size --
so reading the device would report the transfer rather than the music you
own. The join is by **path**, not by artist and title: the device record
carries `origin`, the exact file it was made from, and that matched **465 of
465** device tracks where a key join matched almost none, because 581 of the
drive's files have no tags to build a key from.

*Open:* the Classic's own ALAC ceiling means a high-resolution original is
downsampled on the way across. That belongs in the sync panel, at the moment
of conversion, rather than on the row -- the row should say what you own. The
exact ceiling should be confirmed against the device before it is stated in
the interface.

**The bitrate took the pill that used to say "owned".** A number is the
better claim: it proves you hold the file *and* says what it is, where the
word only repeated what the ink already said. Nothing shows for a track you
do not own -- until it is bought there is no format to report.

**Two fixed slots close the row: bitrate, then the iPod.** Both are always
drawn and only change state, so a tag appearing to their left cannot shift
them -- verified: the mark sits at the same x on every row.

**The bitrate is computed, never read.** The iTunesDB field is not
trustworthy: 60928 for every MP3 on this device, 160 for AIFFs that are
really nearer 850 -- six distinct values across 467 tracks is a misparse, not
data. `kbps_of()` does size x 8 / seconds instead, which agrees with what the
files actually are. `local_index` now records `size` so drive files report a
bitrate too, from the next index onward.

**Dropping a list anywhere on the iPod pane makes a collection of it.**
Aiming at `+ new` is a bullseye you should not have to hit. Rows and `+ new`
stop propagation, so a precise drop still wins; the pane only catches the
misses. It lights only for a whole playlist or folder -- a lone track has no
name to make a collection out of, so that still needs a real target. The
source tab for the drive is called **Library**.

## One list view, whatever is feeding it

The centre used to be three renderers -- iPod, Apple Music, drive -- and they
had drifted apart. The filters existed on one and were **silently dropped**
on the other two: `filter` stayed set to `on iPod`, stopped applying the
moment you switched source, and resumed when you switched back. The list
meant different things in different panes without saying so.

There is one renderer now. `currentList()` answers the only question that
genuinely differs -- *which rows, and what is this called* -- and everything
after it is identical: same filters, same search, same cap, same numbering.

What still differs does so because the **list** differs, not the source:

- **A picked list is numbered** in its own order, whether it came from the
  iPod, Apple Music or the drive. The flat library is not.
- **Only our own collections can be re-sequenced.** Everything else is
  numbered but not grabbable.
- **Month separators** appear only in the flat library, because only there
  does a track belong to a month.

## Why there is no lazy loading

Measured rather than assumed, on this library:

| rows | build | paint | total | DOM nodes |
|---|---|---|---|---|
| 1,034 (the whole curation state) | 15 ms | 33 ms | **47 ms** | 24,149 |
| 4,716 (All of Apple Music) | 48 ms | 121 ms | **169 ms** | 109,721 |

Linear, no cliff, 35 MB of heap. **`CAP` is 1,200** -- deliberately above the
whole curation state, so the library is never truncated; the cap exists for
All of Apple Music and nothing else.

Virtualising would save 169 ms on exactly one list, and would put the scroll
and selection memory at risk: windowing changes the content height as rows
mount and unmount, which is the one thing `scrollTop` restoration cannot
survive. Not worth it. If a list ever appears that makes this wrong, the
cheap move is raising `CAP`, not windowing.

## Artwork comes from your own files, not only from iTunes

A row's cover used to come solely from the iTunes match, so the 466 tracks on
the device -- which arrive through `import_device` and are never looked up --
showed **5 covers between them**. The owner, pointing at a case he knew:
*"all the GTA SA albums have artwork, but don't show here."* They do: 250x250
mjpeg, embedded, in every one.

`local_index` now probes **all** streams rather than just `a:0`, so it knows
which files carry a cover, and `/api/art?key=` extracts one with ffmpeg,
scales it to 300px and caches it under `data/local/art/`. No network, no API,
no account -- and it covers the music iTunes has never heard of, which on
this drive is most of it.

| | before | after |
|---|---|---|
| artwork in the curation state | 558 | **934** of 1,034 |
| on the iPod | **5** | **381** of 466 |
| files on the drive carrying a cover | | 1,562 of 4,048 |

The source is preferred over the device: the T7 original is the full-quality
file and the one that reliably kept its art, with the iPod's own copy as the
fallback for anything whose source has gone.

**Do not put a state load in that endpoint.** The first version did, under
`LOCK`, and a screen of 200 covers then queued 200 reads of a 1.9 MB state
file behind one lock. It resolves from the cached index maps instead, and
only falls back to state for the device path. Cold 136 ms, warm 8 ms.

## Albums are a lens, not a container

Each left pane reads two ways, switched by a mark rather than a word: a stack
of lines for **lists** (collections, playlists, folders), a square of four for
**albums**. The marks sit at the top right of every pane, in the same place,
and the choice is remembered per pane.

**The two left panes are one width** (`--lw` and `--sw`, both 250px) because
they do the same job; the room comes from the centre, which has it to spare.
Their titles never wrap -- `Apple Music` is the Apple glyph and one word so
the tabs, the marks and the fold all fit one line, and the per-source count
is gone because every row in the pane already carries its own. The right
pane still wraps: its stat takes its own line, and forbidding that pushed
BUY / VINYL clean out of the pane.

**An album is not a thing this tool creates.** The Classic builds its Albums
menu out of the tracks' own tags, so putting an album on the device means
moving its tracks and nothing else. Writing a playlist named after it would
put the same record in two different menus.

That needed a change in `apply.plan`, which until now only ever copied tracks
belonging to a collection -- a track in no playlist was never written. It now
also copies tracks marked **`sync`** that belong to no collection. That tier
is the whole mechanism: drop an album on the iPod pane, or use its `...`, and
its tracks are marked `sync`; sync copies them; the device assembles the
album itself.

Off the device is the same verdict a single track gets: **`remove`** on every
track of the album, which sync reads as "take this off".

**Group on the album name alone.** Keying on artist+album looked safer and
shattered every compilation: only 904 of 4,048 files carry an `album_artist`
tag, so the GTA San Andreas radio stations came out as one album per
performer -- **389 "albums" from 466 tracks**, nearly all holding one. Keyed
on the name it is 241, the stations are whole again (Master Sounds 98.3, 29
tracks), and an album whose performers differ is shown as **Various
Artists**, which is what the device does too.

## One title strip, in every column

Each pane used to size its own title to its own contents -- different font
sizes, pills carrying an underline, one pane wrapping while another did not
-- so four titles that were each internally tidy sat at four different
heights. Measuring a pane against itself hid it; the owner saw it at a
glance: *"literally this is not aligned."*

Every column now has a **fixed 46px strip** with its content centred, and
anything a pane wants to say beyond its name goes **below** the strip as a
`.substat`. Measured: all four title centres at the same pixel, all three
fold chevrons with them, all four strips 46px.

Two things that were quietly wrong and are worth remembering:

- **`align-items: flex-end` aligns boxes, not glyphs.** The 12px fold chevron
  and the 9.5px mono title had their bottoms lined up and still read as
  misaligned, because their boxes are different heights. The chevron has its
  own centred 14x14 box now.
- **A pane's extra line belongs under the strip, not in it.** The right
  pane's stat got its own row by wrapping, so forbidding wrap pushed
  BUY / VINYL clean out of the pane.

**The plus leads the iPod pane's marks, and it is a glyph, not a word.**
`+ new` sat last in the group, so every switch to album view -- which hides
it -- dragged the two view marks sideways. It is now the first thing in the
same group, and in album view it is **invisible rather than absent**, so the
slot stays and the marks hold their position. Measured: both marks at the
same x in either view.

Watch the ordering in `drawCols`: the album branch returns early, so the
marks must be painted *and wired* before it, or switching to albums takes the
switch back with it.

**The filters fold behind a mark**, like the two views do -- a funnel in the
centre's strip. A mark cannot say *which* filter is on, so it carries an
orange dot when one is: a hidden filter silently narrowing the list would be
worse than no filter at all.

## One row layout, no position numbers

A picked list used to be numbered, which meant two grids -- one with a
position column, one without -- and the number restated what the row's own
position already said. The owner: *"the order is already shown as is."*

The numbers are gone and there is one grid. **The grab handle stays**, because
that is not decoration: re-sequencing is the product. It now answers a
sharper question than "is this list ordered" -- it appears only where a drag
would actually change something:

```
seq = L.ordered && !L.readonly && !filtered()
```

So a collection of yours shows handles; the same collection with a filter on
does not, because moving a row past neighbours you cannot see would be a lie;
and an Apple Music playlist or a drive folder never does, because their order
is not yours to set.

## What the responsive audit found

Swept 1680 -> 600px in an iframe (the page lays out to the frame, and its own
`innerWidth` fold logic responds), checking for sideways scroll, panes
spilling their bounds, clipped title strips and crushed columns. Four real
faults, all now fixed; the sweep is clean at every width.

**1. The page scrolled sideways below 975px.** The worst of the four, and the
cause is worth remembering: **a grid item keeps `min-width: auto`**, so its
min-content becomes a floor the whole grid -- and therefore the document --
cannot go under. `body` is a grid and `footer` is one of its items, so the
keyboard hints, which are `nowrap` by design, held the entire page at 975px.
The header's `.brandline` had the same fault in miniature. Both released with
`min-width: 0`. Bisected by hiding each region in turn: hiding the footer took
the document from 975 to 700; hiding the header changed nothing.

**2. At ~1100 the track title collapsed to 23px.** All four panes stayed open
until 1040, leaving a 280px centre, and the row's grid is
`44px minmax(0,1fr) auto auto` -- the source strip and tags are `auto` and do
not yield, so the title absorbed every loss. The source pane folds at 1240
now, and a `@container` query drops the source strip below a 420px centre and
the decision tags below 330px, before either can crush the title.

**3. The header counts were clipped from 1280 down** -- on this very laptop.
They are hidden under 1100 instead: a strip sliced to 45px is not a smaller
reading of the numbers. The keyboard hints go under 900 for the same reason
-- half a list of shortcuts reads as the whole list.

**4. Those two media queries did nothing at first**, because **a media query
adds no specificity**: they sat near the top of the sheet and lost on source
order to the `.counts` and `#keys` rules defined further down. They are the
last thing in the stylesheet now.

**Supported range: 600px and up.** Below about 800 all three side panes are
rails and the window is the list, which is usable but not the point of the
tool.

## Undo, and a delete that stops destroying things

**Delete used to strip a track from every collection it belonged to**, and it
had to: `plan()` would see the track in a collection, not on the device, and
add it straight back on the next sync. So the membership was sacrificed to
make the removal stick -- and nothing recorded it, so no amount of
re-deciding could put it back.

The fix is in `plan()`, not in the button: **`remove` is authoritative over
collection membership.** A removed track is never an add candidate, whatever
names it. Delete now only sets the tier, the playlists survive, and the toast
says so (`still in 2 playlists`).

**There is an undo stack**, server-side because that is where the state is.
Before every decision, `_snapshot()` copies each touched record plus
`collections` and `collection_order`; `⌘Z` restores it, `⌘⇧Z` redoes. Undo and
redo are the same move in opposite directions -- pop one stack, snapshot the
present onto the other -- so redo came free. The footer shows what `⌘Z` would
undo, by name.

It stops at the device on purpose: **a completed sync is not on the stack**,
because the only thing that can undo one is the backup it took.

## The capacity gauge

Free space now rides the health poll -- a `statvfs` is cheap enough to poll
where `plan()` is not -- and the footer carries iTunes' capacity bar,
miniaturised, beside the other things the machine has to say. It is the
most-copied convention in this category and the one you want while
*deciding*, not while syncing. The "what a sync would add" figure stays in
the sync panel, because that one does need a full database read.
