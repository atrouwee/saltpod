# What the tool does, against what tools like it do

**2026-09-29. The research is sourced; the saltpod column is verified in code.**
Four strands: iTunes/iPod jobs-to-be-done, desktop music managers, modern
curation and DJ tools, and general interaction-design practice for
stage-then-commit workflows.

The point of the exercise is a **delta**, not a wishlist — so every row says
what saltpod already does, not only what it lacks.

---

## The finding that reframes the rest

**saltpod is already a stage-then-commit tool. It has the engine and none of
the dashboard.**

Decisions accumulate in `state.json`; `plan()` diffs them against a live read
of the device; `sync()` commits. That is the git-index model, and the
interaction research is unambiguous that it is the right shape for this
workflow — better than toast-undo, better than confirm-before-each-action,
because the review step is already implied by the architecture.

What is missing is everything the model implies for the *person*:

- no way to see the pending set except inside the sync dialog
- no way to discard one staged change and keep the rest
- no way to undo a decision once made

Right now **7 track removals are staged**. Sync commits all seven or none.

## Where the friction is wrong

The research's central rule is *friction scales to blast radius*. saltpod has
it close to backwards:

| | what it should cost | what it costs today |
|---|---|---|
| a per-track decision (reversible) | nothing | nothing ✓ |
| undoing that decision | nothing | **manual re-decision; no undo anywhere** |
| deleting from the iPod pre-sync | nothing — it is staged | **irreversible loss of collection membership** |
| the device write (irreversible) | a deliberate confirm | a confirm ✓ |

---

## The delta

Legend: **✓** present · **~** partial · **✗** absent

### Breaks a near-universal convention

| | iTunes / modern tools | saltpod | gap |
|---|---|---|---|
| **Multi-select** | shift-range + cmd-toggle + right-click bulk, everywhere | ✗ `r.onclick` sets one index; no shift/cmd handling; no context menu | **567 undecided tracks, one keypress each** |
| **Bulk edit** | MediaMonkey/MusicBee batch anything | ~ only two fixed groups ("add all shortlisted", bulk lookup) | no action on an arbitrary set |
| **Capacity before sync** | iTunes' capacity bar, the most-copied convention in the category | **✓ DONE** — gauge in the footer beside the iPod status, always visible | — |
| **Sort by column** | every desktop manager | ✗ orderings are hardcoded `.sort()` calls | cannot find the biggest, oldest, worst-quality |

### Loses information the device is holding

| | | |
|---|---|---|
| **Star ratings** | the Classic sets them on the wheel and iTunes merged them back | ✗ parser reads no rating field | ratings you set on the device are invisible |
| **Play counts** | iTunes merged them, then invalidated the file | ~ `Play Counts` is **deleted** on any track-set change (correct — it is positional) but **never read first** | ~~listening history discarded~~ — **corrected 30 Sep, see below** |
| **Delete's side effect** | iTunes distinguished *remove from playlist* from *delete from library* | **✓ DONE** — `remove` is authoritative in `plan()`, so membership survives and the decision reverses cleanly | — |

### The staged-commit affordances

| | | |
|---|---|---|
| **Undo** | ⌘Z is a baseline expectation | **✓ DONE** — server-side stack, 60 deep, ⌘Z / ⌘⇧Z, labelled | — |
| **Review pending changes** | git status/diff, Terraform plan | ~ the sync dialog lists them, all-or-nothing | cannot drop one and keep the rest |
| **Trash / restore** | iTunes prompted keep-file-or-bin | ✗ file is `os.remove`d on sync | recovery is the whole-folder backup, by hand |

### Ordinary comforts

| | | |
|---|---|---|
| Smart / rule-based playlists | iTunes' were best-in-class | ~ device ones read and shown, **never written** | no saved rule |
| Saved filters | Roon Focus, foobar queries | ✗ one global cycled `filter` | |
| Duplicate detection | MusicBee/MediaMonkey do it well | ✗ `key_for()` silently **merges** near-duplicates | |
| Missing-file detection | iTunes' ! icon | ~ `no_source` at plan time only | no scan for vanished files |
| Tag editing | universal | ✗ read-only | **581 untagged files are invisible in the iPod's own menus** |
| Artwork | fetch / paste / remove | ~ extract and cache only | cannot fix a missing cover |
| Export | M3U/CSV everywhere | ✗ import only | the state is a silo — the thing the project dislikes about everyone else |
| Queue / play next | universal in players | ✗ one `<audio>`, plays the selected row | arguably out of scope: this is not a player |
| Per-track note | — | **✓ DONE** — deleted from the model, the API and the payload | — |

### What saltpod does that the others do not

Worth stating, because the delta is not one-directional:

- **Provenance as a first-class row element** — `AM · T7 · LP` plus the device
  mark. Roon and Plexamp show *some* of this; nothing shows all four places at
  once as peers.
- **Quality that is format-aware** — `320k` for lossy, `16/44.1` for lossless,
  read from the original rather than the transferred copy. Tidal and Roon
  badge quality; neither distinguishes source from copy.
- **Duration-verified purchase identity** — the ±5s check that stops you buying
  the 3:30 radio edit. No consumer tool does this.
- **Surgical in-place database patching** with byte-identical round-trip and a
  verified checksum. gtkpod regenerated; iTunes owned the file.
- **A durable, diffable audit of every write** — before/after device
  fingerprint per sync, in `history.jsonl`.

---

## Recommended order

1. ~~**Fix delete.**~~ Done 29 September. Membership survives; the decision
   reverses.
2. **Multi-select and bulk actions.** Largest leverage on the real backlog.
3. **A pending-changes view.** The structural gap; makes the tool what its
   architecture already is.
4. **Read ratings and play counts** before invalidating them.

Everything else is comfort and can wait.

---

## A correction, measured 30 September

The row above said listening history was *discarded, not migrated*. That
overstated it. Walking the 658 `mhit` records on the live device:

- **Cumulative play counts survive.** 69 tracks carry 1–6 plays right now.
  They live in the `mhit` header and in-place patching preserves them — the
  same discipline that keeps everything else intact.
- **What is lost is the `Play Counts` sidecar**, which holds only the plays
  *since the last sync*. Deleting it is correct (it is positional and a
  changed track set invalidates it) but it is deleted **without being read**,
  so those deltas never reach the cumulative figure.
- **Ratings are all zero** across all 658, so there is nothing there to lose
  yet — but nothing reads the field either, and the iPod is the only place
  a rating can be made.

So the gap is narrower than claimed and still real: read the sidecar, add
its deltas, then delete it.

## What has shipped since (29 September)

- **Delete fixed**, as above.
- **Undo/redo**, server-side, 60 deep.
- **Capacity gauge** in the footer, visible while deciding rather than only
  at the sync dialog.
- **The decision model collapsed** to `sync` / `remove` / `undecided`. Four
  tiers and a parallel `wanted` flag went to three tiers and none; `maybe`
  and `shortlisted` were used **zero times in 1,211 tracks**, and `wanted`
  restated the tier from a second column. `note` deleted, `bought` derived
  from a file existing. This was not in the delta above — the research
  surfaced it indirectly, by showing that no comparable tool asks for a mood
  when the question is binary.

So the live top of the list is now **multi-select**, then **pending-changes
review**, then **ratings and play counts**.

## Sources

Interaction design: [GitLab Pajamas](https://design.gitlab.com/patterns/destructive-actions/),
[NN/g confirmation dialogs](https://www.nngroup.com/articles/confirmation-dialog/),
[NN/g bulk actions](https://www.nngroup.com/videos/bulk-actions-design-guidelines/),
[Apple HIG undo](https://developers.apple.com/design/human-interface-guidelines/patterns/undo-and-redo/),
[Material snackbar](https://m3.material.io/components/snackbar/guidelines),
[PatternFly bulk selection](https://www.patternfly.org/patterns/bulk-selection/).
Tools: [Roon Focus](https://community.roonlabs.com/t/roon-feature-spotlight-focus/207603),
[Rekordbox My Tag](https://vibesdj.io/how-to/use-my-tag-in-rekordbox).
