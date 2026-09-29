# The saltpod design system

**Status: measured.** Everything in Parts 1–7 was read out of
`src/saltpod/curate.html` on 29 September 2026 and describes what the code
does today, with counts. Part 8 is the **drift register** — measured
divergence, with a proposed canonical scale that is *not yet true*. Nothing
here is aspirational unless it says PROPOSED.

The page is one file, no build step, 611 lines of CSS and 307 rules. That is
small enough that the system was implicit for a long time, and large enough
that it had started to drift. This document exists so a new part can be built
out of the existing vocabulary instead of beside it.

---

## 1. The laws

Seven rules that decide most arguments before they start. They are not style
preferences; each one came from a bug or a misread screen.

### 1. One slot, one meaning; nothing shifts

A state is a **fixed slot that changes value**, never a thing that appears.
Layout that moves at the moment something happens moves it out from under
your attention.

Worked example — the sync panel's status marks sit in the `.cnt` slot that
already holds a count on every other row, so a row that is *about to be
removed* and a row that is *being removed* are the same row in the same
place. The earlier version had a separate checkbox column that vanished when
the run started, and the whole list jumped.

### 2. Blue is where you are. Orange is what you hear.

`--sel-hi` / `--sel-lo` mark **position**: the cursor, the selection, a drop
target. `--orange` marks **sound**: the playing track, and by extension
anything mid-flight. The two never mean the same thing, and neither is ever
used decoratively. A drop target borrows the blue because a drop is also a
"here", never a "hear".

### 3. Full ink means you could act on it today

`--ink` on a row means a file exists and sync could copy it now. Dimmed
(`.unowned`) means it could not — unbought, or bought and not yet indexed.
**That gap is what the tool exists to close**, so it is the first thing the
eye separates. No other dimension is allowed to compete for opacity.

### 4. Facts are plain; decisions get chrome

Where a track *lives* (`AM T7 LP`, the iPod mark) is a fact about the world:
plain text, no border, no background. Anything you *decided* gets a border, a
fill or a pill. A reader can therefore tell what the tool observed from what
they told it, without a legend.

### 5. Mono is machine truth; the face is human content

`--mono` carries counts, labels, keys, quality figures, shortcuts, status —
anything the machine knows. `--face` carries names, titles and prose —
anything a person wrote. Section labels are mono and uppercase at `.18em`
because they are the machine's index of the page, not headings.

### 6. Every pane has the same anatomy

A 46px `.plabel` strip with the name on the left and the pane's one action on
the right, mono `.month` section labels inside, a scrolling `.pbody`, and
optionally a `.substat` line at the foot. Five surfaces already follow this;
a sixth must too. This is what makes a new pane read as part of the product
rather than as a visitor.

### 7. Nothing is drag-only

Every drag has a menu equivalent. Dragging is faster once you know it; a menu
is how you find out it is possible.

---

## 2. Tokens

### Colour — the whole palette, defined once in `:root`

| Token | Value | Job |
|---|---|---|
| `--ground` | `#141d29` | every surface |
| `--seam` | `#070c13` | recessed: log wells, the page behind panes |
| `--ink` | `#fffffc` | actionable text, live values |
| `--dim` | `rgba(255,255,252,.55)` | secondary text, all labels |
| `--faint` | `rgba(255,255,252,.22)` | hairlines, borders, disabled |
| `--panel` | `rgba(255,255,252,.05)` | hover, quiet fill |
| `--raised` | `rgba(255,255,252,.09)` | selected fill, gauge track |
| `--sel-hi` / `--sel-lo` | `#6aa9f4` / `#1450b8` | **where you are** (law 2) |
| `--orange` | `#f75c03` | **what you hear**, and in-flight |

The blue pair was read off a photograph of the device: bright at the top,
deeper below. Every gradient in the product runs `--sel-hi` → `--sel-lo` in
that order, so the light always falls from the same direction.

### Type

| Token | Stack |
|---|---|
| `--face` | `"Helvetica Neue", Helvetica, Arial, sans-serif` |
| `--mono` | `"IBM Plex Mono", ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace` |

Sizes actually in use, by frequency: **9.5px ×9** (the label size — every
`.plabel`, `.month`, `.substat`), **13px ×4** and **13.5px ×2** (row and
prose text), **11px ×4** (buttons, `kbd`), **10px ×3** and **10.5px ×3**
(counts, log), **9px ×4** (tags), **12/12.5px ×4**, **14px ×2**, 18px, 19px
(the wordmark).

Letter-spacing: **`.18em`** on every uppercase mono label (×4 rules),
**`.06em`** on stat lines (×6), **`.1em`** on tags and shortcuts (×4).

### Layout

| Token | Value | Job |
|---|---|---|
| `--lw` | `250px` | iPod pane — the two left panes are one width because they do one job |
| `--sw` | `250px` | source pane |
| `--rw` | `320px` | buy / vinyl pane |
| `--hbtn` | `32px` | every header control: search, Sync, the gear |

Fixed heights: **46px** for `.plabel` — the one number that aligns the title
of all four columns. Getting this from `align-items` instead of a fixed
height is what made the titles look crooked; boxes aligned, glyphs did not.

### Radius

**10px** (×10) is the row and container radius. **8px** (×6) is the inner
radius — menu rows, wells. **99px** (×7) is the pill. Everything else is
drift; see Part 8.

---

## 3. Containers

| | What it is | Where |
|---|---|---|
| **pane** | `aside`/`section` in the page grid: `.plabel` + `.pbody` (+ `.substat`) | the four columns |
| **sheet** | a pane-shaped surface that slides *within* a column, same anatomy | new collection, settings |
| **panel** | a pane-shaped surface fixed to the right edge over a scrim, same anatomy | sync review |
| **dialog** | centred modal, `min(420px, 92vw)`, for a confirm that is not a list | rename, delete |
| **menu** | anchored popover of `.drow`s | the `⋯` on every row and list |

A panel is a pane that happens to be fixed. It gets the same `.plabel`, the
same `.pbody`, the same `.month` labels and the same `.substat` foot — the
only things it adds are the slide and the scrim, because nothing existing
does either.

**The scrim is load-bearing, not decoration.** The sync plan is a diff taken
against the device a moment ago; letting you change a decision behind it
would make the list on screen a lie.

---

## 4. Rows — three shapes, three jobs

There are exactly three. Adding a fourth needs a reason.

### `.row` — a track
`grid 44px / 1fr / auto / auto`, `gap 14px`, `padding 9px 10px`, `radius
10px`, `margin-bottom 3px`.
The only grid of the three, because a track has four fixed regions: artwork,
name, provenance, actions. Fixed columns are what stop the iPod mark moving
between rows.

### `.col` — a named thing with a count
`flex`, `gap 8px`, `padding 8px 10px`, `radius 10px`, `font 13.5px`,
`margin-bottom 2px`. A `.cnt` on the right holds the count.
Playlists, folders, source lists, sync-review rows. **If your new thing is a
name plus one number, it is a `.col`.**

### `.drow` — a menu line
`flex`, `gap 10px`, `padding 7px 10px`, `radius 8px`, `font 13.5px`.
Tighter than `.col` and one radius step smaller, because it sits inside
another surface. `.dn` name, `.dc` right-hand mark, `.dk` shortcut.

---

## 5. Labels, stats and prose

| Class | Spec | Job |
|---|---|---|
| `.plabel` | 46px, mono 9.5/.18em upper, `--dim`, `.name` in `--ink` | the pane's title strip |
| `.month` | mono 9.5/.18em upper, `margin 22px 0 6px`, `padding 0 10px` | a section label inside a body |
| `.substat` / `.pstat` | mono 9.5/.06em, `--dim`; `s` un-struck to `--ink` | the running totals at a pane's foot |
| `p.note` | 13px, `--dim`, `line-height 1.5`; `s` to `--ink` | prose and empty states |

The `<s>` convention is the product's own: in any stat line, wrap the
**number** in `<s>` and it lifts to `--ink` against `--dim` prose. It is not
strikethrough — `text-decoration: none` is set — it is the cheapest possible
"this is the value" marker, and it reads in both mono and face contexts.

---

## 6. Controls

| Class | Spec |
|---|---|
| `button` | mono 11px/.08em upper, `1px --faint`, `padding 7px 12px` |
| `button.go` | inverted: `--ink` ground, `--ground` text |
| `#dosync` | the blue gradient, `radius 10px`, height `--hbtn` — the one primary action on the page |
| `.pill` | mono 10px/.14em upper, underline-on-active; a tab |
| `.tag` | mono 9px/.1em upper, `radius 99px`, `1px --faint`; a state on a row |
| `.act` | the small text affordance in a title strip (`esc`, `+`) |
| `kbd` | mono 11px, `1px --faint`; a key name |
| `.card` | `--panel`, `radius 10px`, `padding 10px 12px` |

There is **one** primary action on the page at a time, and it is blue. A
second blue button would break law 2.

---

## 7. State vocabulary

The same words mean the same thing on every surface. Use these before
inventing one.

| Class | Meaning |
|---|---|
| `.on` | currently chosen / active |
| `.was` | chosen, but the focus has moved to another pane |
| `.sel` | the cursor is here (single) |
| `.marked` | in the multi-selection |
| `.pend` | has work waiting — count turns `--orange` |
| `.out` | excluded by you: struck through, stays in place |
| `.fixed` | happens regardless; not yours to pick |
| `.doing` | in flight now — mark turns `--orange` |
| `.done` | finished |
| `.err` | failed — text and mark turn `--orange` |
| `.todo` | queued, not started |
| `.dim` / `.unowned` | you cannot act on this yet (law 3) |

`.marked` deliberately uses the same blue as `.sel` at 34% rather than a
second hue: a different colour would say "a different kind of thing", when it
is the same thing in quantity. And a cursor row that is *not* in the
selection is drawn as an outline, so the one row an action will skip never
looks like the rows it will act on.

---

## 8. Drift register

**Measured divergence from the scales above.** This is the part to argue
with. Counts are occurrences in the stylesheet.

### Spacing — 17 distinct values for a 4-step job

In use: `8px ×18`, `10px ×18`, `14px ×17`, `12px ×14`, `6px ×10`, `7px ×7`,
`4px ×7`, `16px ×7`, `2px ×7`, `9px ×6`, `24px ×5`, `5px ×3`, `18px ×2`,
`22px ×1`, `20px ×1`, `11px ×1`, `3px ×1`.

**PROPOSED scale: 2 · 4 · 6 · 8 · 10 · 14 · 24.** That keeps every value used
more than five times and retires the nine one-offs. `7px`, `9px`, `11px`,
`18px`, `20px`, `22px` have no job that `6/8/10/16/24` cannot do.

### Font size — 12 sizes, several a half-pixel apart

`13px` and `13.5px` both exist; so do `12px` and `12.5px`, `10px` and
`10.5px`.

**PROPOSED scale: 9 · 9.5 · 11 · 13 · 19.** Five sizes, each with a stated
job: tag, label, control, content, wordmark. The half-steps are invisible and
cost a decision every time.

### Radius — 9 values

`99px ×7`, `10px ×10`, `8px ×6` are the system. `7px`, `6px`, `5px`, `4px ×2`,
`3px`, `1px` are drift.

**PROPOSED: 8 · 10 · 99 only.**

### Letter-spacing — 10 values

`.18em`, `.1em`, `.06em` carry real meaning (label / tag / stat). `.01em`,
`.02em`, `.05em`, `.08em`, `.12em`, `.14em`, `.16em` are indistinguishable
from their neighbours at these sizes.

**PROPOSED: .06 · .1 · .18 only.**

### Colour literals outside `:root`

`#fff ×12` and **22 `rgba()` literals** live in rules rather than tokens.
Most are white at an alpha for text on the selection blue.

**PROPOSED:** add `--on-sel` (`#fff`) and `--on-sel-dim`
(`rgba(255,255,255,.82)`) and replace all of them. Today a change to the
selection treatment means finding 34 places.

### Naming

Three prefixes coexist: bare semantic names (`.row`, `.col`, `.month`),
two-letter abbreviations inside menus (`.dn`, `.dc`, `.dk`), and id-scoped
ones (`#sp …`). The abbreviations are only legible next to `.drow`.

**PROPOSED:** leave them. Renaming touches every template string for no
behaviour change, and the pattern is consistent *within* its container.
Recorded here so the next reader knows it was a decision.

---

## How to add something

1. **Find the pane anatomy** (law 6) and use it: `.plabel` + `.pbody`
   (+ `.substat`).
2. **Pick one of the three row shapes** (Part 4). A name and a number is a
   `.col`.
3. **Use a state word that already exists** (Part 7) before inventing one.
4. **Take a value off the scale** (Part 2). If you need one that is not
   there, you are probably solving a spacing problem with a new number
   instead of with the container.
5. **Check it against the laws** (Part 1). Most sloppiness is law 1 or law 6.
