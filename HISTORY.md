# How saltpod came to be

**Where it came from, what was decided along the way, and why.** The README
says what the tool is; HANDOFF says what is true right now and what to do
next. This is the record in between — the part a newcomer needs to iterate
on it without repeating a mistake that has already been paid for.

Every commit is on `main` with a message that explains itself; this is the
narrative over them. Where the owner's own words carried a decision they are
quoted, because a decision is easier to keep when you can see the sentence
that caused it.

---

## The finding that started it

The owner keeps a monthly Apple Music playlist — everything listened to that
month, an unbroken series back to 2018 — and, each quarter, picks what to
commit to owning in lossless, with the most select going to vinyl. The
ambition was to get the chosen music onto a 160 GB iPod Classic, which has no
subscription, no streaming, and no iTunes any more to feed it.

The first audit reframed the whole job. Of 4,876 tracks in the Apple Music
library, **4,661 were subscription rentals and only 110 genuinely owned.**
Matching a playlist against "your library" returned almost nothing, because
there was almost nothing there to match. A subscription track that shows a
file path is a `.movpkg` — DRM'd HLS that will never play on a Classic.

So the buy list *is* the playlist, and the tool's first job is identifying
what a recording actually is so the right one gets bought.

---

## Phase 1 — Identify, then buy (11–12 September 2026)

**Export, index, match.** A JXA script reads Music.app; an ffprobe index maps
the files already owned on an external drive; the iTunes Search API — free,
keyless, cacheable, and exact about *which recording* down to the running
time — pins identity. iTunes is the identifier, not the store: it sells AAC
256 and has no lossless tier, so purchasing was routed to Bandcamp, Beatport,
Qobuz and Juno instead.

**Duration became a first-class signal**, not a tiebreak. The failure worth
engineering against is silently buying the 3:30 radio edit when the 7:15
extended mix was wanted; beyond ±5 s a match is flagged for human eyes and
never auto-bought. The case that made it a rule: a 409-second dub where iTunes
carried only the 225-second cut.

**Three normalisation bugs were inventing absences** — punctuation stripping
ran before accents were folded, so every Turkish and French title broke;
titles made of punctuation alone lost their query; parentheticals were dropped.
Four of seven "missing" tracks matched once fixed, and the buy list went *up*,
which was the correct direction.

**A spectrum check** finds lossless files that were lossy once — a FLAC
encoded from a 320 kbps MP3 is still a valid FLAC and no container field says
so, but an encoder's lowpass ends the signal on a shelf where a real master
fades. Calibrated against deliberate fakes; the steepness of the cliff
decides, the edge frequency then names the encoder. It is tuned to never call
a dark master a fake, because the output tells someone to re-buy music.

**Bandcamp via the browser**, from a bandcamp.com tab, answered the question
no keyless API could: is *this* recording sold in lossless. It overturned an
assumption — lossless turned out roughly **price-neutral** with iTunes
(€0.99–2.00 against €1.29), not the 1.5–3× premium first estimated. Two traps
were paid for and written down: `credentials:'omit'` makes Bandcamp return a
healthy-looking 200 with zero results, and seller subdomains are unreachable
cross-origin.

## Phase 2 — Verify (25–26 September)

Q3 complete: 58 tracks, all identified, every one within ±0 s of the
catalogue running time. And then the check that had never been made:
**availability is not correctness.** Reading the exact duration off each
Bandcamp release page against the recording iTunes identified found **6 of 46
reachable hits were the wrong cut — 13%.** August was corrected from "18 of 20
available" to 15 confirmed. The case for duration: an exact title, a clean
slug with no remix or edit token, and 109 seconds longer than the identified
recording. No string heuristic can see that; only the clock can.

Also learned: scoring must *require* artist evidence, or a title-exact match
returns a remix by somebody else.

## Phase 3 — Curate, then read the iPod (27 September, morning)

**The monthly playlists are a capture, not a shopping list.** Curation turns
them into a chosen subset: one record per track across all playlists, four
tiers (seen, shortlisted, maybe, skipped) and two flags deliberately kept
separate — vinyl and bought answer different questions and a track can be
both. Monthly playlists became metadata; what reaches the iPod are
user-named **collections**.

Rebuild is non-destructive by construction — it writes only identity fields
and copies every human decision forward; tracks that vanish are flagged
orphan, never deleted. Curation happens on a **local page** with the iTunes
30-second previews (195 of 197 have one), because the artifact sandbox blocks
Apple's media host. **Every keystroke saves; there is no save button.**

**The iPod mounted** — a FAT32 160 GB Classic, Windows-formatted, which is
good news: native read-write on macOS. Reading its database cost two format
facts that are now in the README: string data starts at header+16, and the
word that looks like an encoding flag is not one. The database was healthy;
**the playlists were what was broken** — 38 references across 14 playlists
for 481 tracks, with failed-sync scars like `2018 Apr` beside `2018 Apr1`.
That was the complaint that started the project.

**A trap, twice:** macOS writes `._name` AppleDouble stubs beside every file
on FAT/exFAT, with the same extension, and ffprobe parses some of them. On the
iPod they made 876 files look like 395 orphans; on the drive they inflated the
index by 760 phantom tracks and 42 GB. Always skip `._`.

## Phase 4 — Write to the iPod (27 September, midday)

**The checksum was the frightening part and it was solved first.** Every
Classic uses hash58: HMAC-SHA1 over the file, keyed from the first eight bytes
of the device's FireWire GUID through three constant tables — no iTunes
secret. Reproduced byte-for-byte against the signature iTunes itself had
written to this device; a GUID one bit off mismatches; re-signing is
idempotent.

**The writing strategy is surgical patching, never regeneration.** Keep the
file iTunes wrote, parse it into a tree whose round-trip is byte-identical,
change only the bytes that must change, fix the length chain, zero the stale
secondary hash, re-sign. Every new playlist, entry and track record is cloned
from one the firmware already accepted on the same device. Then sign, write,
read back, verify on the device, eject. A dated backup precedes every write.

The owner ruled out the alternative in five words — **"We're not doing
Rockbox"** — and it has not been reopened.

**First device write, 27 September:** a playlist rename. Stock firmware showed
it and played the track. **Second write, 14:24:** playlist create, cloned
track record, WAV→ALAC conversion, master-library append. A report of "silent
at 22 s" was investigated and turned out to be the source file — three seconds
of trailing silence on the remaster, sample-identical after conversion.

**Sequence is the product.** The owner: *"I want to influence sequence, it's
very important."* A collection's order is kept as truth in state, new members
append and are never re-sorted, rename carries it, rebuild cannot touch it,
and sync writes exactly that order. **Third write, 15:32:** a re-sequence read
back off the device in exactly the order arranged — the proof that the order a
person sets in the page reaches a 2007 screen unchanged.

## Phase 5 — The page becomes the tool (27 September, afternoon)

One command starts a local server and opens the page; slow work runs as a
background job and streams its log in. Then the page was rebuilt around how
the owner actually works, in several passes, each one his call:

- **The list took the iPod's own selection blue** — read off a photograph of
  the device — with rounded rows separated by space instead of rules. The
  orange bar that had marked "playing" went, because *"I don't know what it
  means"*; playing is now an equaliser in the chevron's slot and the duration
  turning into a running clock, both in one orange that means only that.
- **One workspace, not tabs.** Collections left, the library in the middle,
  buy and vinyl on the right; drag between them. The only lines are the seam
  under the header, the hairline above the footer, and one either side of the
  list. Filters fold into the library pane.
- **Discogs came in** from its two exports, read on every request, nothing
  fetched. The vinyl pane shows the pipeline in its one direction — flagged
  here, wanted on Discogs, owned — and the library learned which tracks are
  already owned on record.

## Phase 6 — Where a track lives (27 September, evening)

**Every row carries `AM T7 POD LP`** — Apple Music, the drive, the iPod, a
record — in plain mono with no border, because where a track lives is a fact
about the world and the bordered pills are decisions. Owned shows in full ink,
rented stays dim. The owner set the rule: *"there should not be a difference
between origin and location … we mark it as such"* — the places are peers,
and no claim is made about which came first.

**Apple Music is read whole**: 182 playlists and all 4,892 library tracks in
three and a half seconds, cached. The cloud breakdown cross-checked the
founding finding exactly — 4,680 rentals, 111 owned, and **85 no longer
available**, rentals that have already vanished. `AM` now means *in your
library*, not *in a playlist we happened to export*, which found 91 tracks
on the iPod that are also in Apple Music.

**Two libraries behind one switcher.** The owner's model, in his words: *"It
feels like the left panel is the iPod panel … I should only edit playlists for
the iPod. But I also want to be able to view the playlists that are on Apple
Music for inspiration."* So the left pane is either the iPod — collections,
the only thing edited — or Apple Music, which is browsed and taken from and
never edited. A track earns a record only when a decision is made about it;
otherwise the queue would be the whole library.

**Music.app has no creation date for a playlist.** Its entire property list
was checked against the app; the date shown is the earliest a track was added,
which the owner accepted: *"if we look at the oldest track arrived, we get the
created date for the playlist. That's perfect."*

**Sync from the page**, top right beside the gear: never one click — it asks
the device what it holds, shows the diff, writes on confirm. **A collection may
hold what is not yet bought**: *"a playlist on the iPod where we know what
needs to go in, even though it's not purchased yet"* — sync writes what it
finds a file for and names the rest. **Every panel is one shape**, with its
single action in its own title strip.

## Phase 7 — Two libraries, side by side (27 September, night)

**The switcher was a userflow bug.** Phase 6 put the iPod and Apple Music
behind one left pane with a switcher. Every Apple Music row was already
draggable and the server already gave a dropped track its first record — but
switching to Apple Music hid the collections, which were the only place to
drop. The owner named it exactly: *"It's more of a userflow issue. And it
could be solved by having the ipod panel open on the left as a side panel, the
apple music open next to it as a left side panel and then being able to drag
tracks into the ipod. The last playlist clicked (either ipod or apple music)
is the list that shows in the middle."*

Four directions were drawn against a miniature of the page — both libraries
stacked in one pane, a spring-loaded pane that swaps for the length of a drag,
Apple Music moved to the right beside Buy and Vinyl, and the owner's own: two
panes on the left. His won, and it won on the merits: Apple Music stays
visible *while* a collection is being built, so inspiration and the thing
being made are on screen together. That was the ask from the start.

**A playlist became a thing you can pick up.** Onto a collection to pour it
in, onto `+ new` to become one. Not a copy — a declaration: every track earns
a record and joins in the playlist's own order, after what is already there.
Sync writes what has a file and names the rest, and with most of the library
rented most of a fresh playlist lands in Buy, which is the point. The `⋯` on a
playlist does all of it by clicking.

**Which list is active had to be visible** — *"we will need to visually show
in one of the two left panels which list is active"* — because both panes
now remember a pick. The active pane's pick is raised and bold; the other
pane's is bold inside a hairline with no fill. One slot, one meaning.

Then the owner tidied the chrome in two sentences: *"The collapse icons can
simply be the larger/smaller-than signs left of the title … when collapsed
you still see a couple of pixels of it and icons vertically."* And: *"the
buy/vinyl panel … can sit next to each other with the underline where there's
currently just one title … The stats/counts at the top can go right aligned,
left of the sync button with a lower opacity."* The deck under the header
emptied out and was removed; the header is one line again. A folded pane is a
24px rail, its title turned on its side.

---

## The rules that hold

Each of these has a reason above. Do not relitigate them without reading it.

- Never regenerate the database; edit in place.
- Never invent a structure; clone one the firmware already accepted.
- Sync never wipes a track it was not told about. Every non-smart playlist on
  the device is a collection — adopted on read, the owner's to edit and
  delete, whoever made it. Smart playlists are shown and never written.
- Back up before every write.
- Sequence is the product. Never sort.
- No Rockbox.
- Stdlib Python plus ffmpeg and ffprobe. Nothing fetched by the page.
- Every keystroke saves.
- The last playlist clicked is what the centre shows.
- **It all runs locally through scripts. Nothing needs a model.** Every
  capability has a verb; the page is a convenience over them.

## Where it is going

See HANDOFF for the current state and the open items. The standing ones:
the three hardware proofs still to run (track removal, playlist deletion, a
drag by hand), and progress by phase while a sync runs. The status strip and
the size estimate landed the same night they were designed, on the owner's
picks: status in the footer, opposite the keys; a new collection made on a sheet
that slides over its own pane — the owner's pick once he saw it drawn, and
the same idiom Data now uses from the right.
