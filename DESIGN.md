# The saltpod design system

**Status: measured, and now enforced.** Everything here was read out of
`src/saltpod/curate.html` and describes what the code does today. As of the
29 September tightening pass, **every radius, tracking value, font size and
colour in the stylesheet is a token** — there are zero literals outside
`:root`, so the scales below are not advice, they are the only values that
exist.

The page is one file, no build step, ~630 lines of CSS and 307 rules. Small
enough that the system was implicit for a long time, and large enough that it
had drifted. This document exists so a new part gets built out of the
existing vocabulary instead of beside it.

**The first drift register was wrong in three places**, and the second pass
says so. Counting values without weighting them by use made systematic
choices look like accidents. What survived is recorded in Part 8 under *what
the register got wrong* — that section is the useful one.

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

**The rule runs down a column as well as across a row.** A slot that exists
on some rows of a list and not others makes the column beside it step
sideways between them — the same violation, one axis over, and harder to
see because each row looks fine on its own. Found on 30 September: five of
the nine lists omitted the menu slot, so counts in the iPod and source panes
sat on two verticals 28px apart in the same column. Every row in a list
reserves every slot the list uses.

### 2. Blue is space. Orange is time.

`--sel-hi` / `--sel-lo` mark **where you are**: the cursor, the selection, a
drop target, the pointer. `--orange` marks **what is happening now**: the
playing track, a track in flight, a count with work waiting, a failure. A
drop target borrows the blue because a drop is also a "here".

*This law was restated on 29 September after auditing all 27 uses.* It read
"orange is what you hear", which was **not what the code does** — orange also
carried in-flight, pending and error. Rather than invent a fourth hue for
each, the honest reading is that every orange in the product means *attention
is warranted here, now*, which is coherent and is what a reader already
infers. Blue is spatial, orange is temporal; neither is ever decorative.

The audit found exactly one genuine violation: the sync panel's capacity
gauge filled with the position-blue for what is a **quantity** — neither a
place nor an event — and in doing so invented a second gauge beside the one
the footer already had. Fixed to match the footer: `--dim` fill, pill radius,
orange only when it will not fit.

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

### 8. A control undoes itself

**The same control that did a thing is the one that takes it back, and it
says so by changing its own label.** *Buy* becomes *Don't buy*. *Want vinyl*
becomes *Unwant vinyl*. *Remove from iPod* becomes *Don't remove*. The fold
chevron that closed a pane opens it; the row you unticked in the sync panel
is struck through and un-ticks with the same click.

Two consequences, and they are the point:

- **No separate undo affordance.** An "Undecided" row used to sit under the
  two decisions as a third choice. It was never a thing anyone would pick —
  it was the undo of the row above, wearing a noun.
- **No tick either.** The flipped label *is* the state indicator. *Unwant
  vinyl* already tells you it is wanted; a tick beside it says the same
  thing twice, in the opposite direction.

**Offer only the verb that means something here.** A track already on the
iPod cannot be "synced" — it is there. A track that was never on it cannot
be "removed". So the decision row is one row, chosen by where the track
actually is:

| Where the track is | The control |
|---|---|
| on the iPod | *Remove from iPod* / *Don't remove* |
| owned, not on it | *Sync to iPod* / *Don't sync* |
| not owned | *Buy* / *Don't buy* |

The undo drops the object, because the row it undoes already named it:
*Sync to iPod* → *Don't sync*, never *Don't sync to iPod*.

**And when the question is already answered by the world, the control stops
being one.** Own the record and there is nothing to want or unwant, so that
row becomes `.inert`: it keeps its slot — the menu must not resize under the
cursor — dims, and says *Owned on vinyl*. Same for a file you already hold:
*Owned digitally*. That is law 4 inside the menu, a fact where a decision
used to be.

**There is no standing rule, only one-off decisions.** A track that was
never on the iPod cannot be removed from it, and marking one "never sync"
would be a rule about the future rather than a decision about now. So the
negative is offered only where it means something, and the `x` key says
*not on the iPod* rather than inventing a list nobody asked for.

---

## 2. Tokens

Every value in the stylesheet now comes from here. A literal in a rule is a
bug — the census at the bottom of Part 8 is how that stays true.

### Colour

| Token | Value | Job |
|---|---|---|
| `--ground` | `#141d29` | every surface |
| `--seam` | `#070c13` | recessed: log wells, the page behind panes |
| `--ink` | `#fffffc` | actionable text, live values |
| `--dim` | `white .55` | secondary text, all labels, **quantity fills** |
| `--faint` | `white .22` | hairlines, borders, disabled |
| `--panel` | `white .05` | hover, quiet fill |
| `--raised` | `white .09` | selected fill, gauge track |
| `--sel-hi` / `--sel-lo` | `#6aa9f4` / `#1450b8` | **where you are** (law 2) |
| `--orange` | `#f75c03` | **what is happening now** (law 2) |

The blue pair was read off a photograph of the device: bright at the top,
deeper below. Every gradient runs `hi → lo`, so the light always falls from
the same direction.

**On the selection.** The blue is the only ground in the product that carries
its own foreground, and it was written out as a literal 21 times in four
different alphas (`.7`, `.8`, `.82`, `.85`) all meaning the same thing.

| Token | Value | Job |
|---|---|---|
| `--on-sel` | `#fff` | primary text on the selection |
| `--on-sel-dim` | `white .82` | secondary text on the selection |
| `--on-sel-line` | `white .55` | a border on the selection |
| `--on-sel-hi` | `white .16` | the top highlight inside the gradient |

### Radius — a ladder, not a value

A small box wants a small corner; the ratio in this product is roughly a
sixth of the box. That is a rule, not drift, and it now has four steps.

| Token | Value | Band |
|---|---|---|
| `--r-xs` | `4px` | ≤28px — thumbnails, mode marks |
| `--r-sm` | `8px` | nested rows, menu rows, wells, artwork |
| `--r-md` | `10px` | rows, cards, containers, the primary button |
| `--r-pill` | `99px` | pills, bars, dots — anything whose height is its radius |

### Tracking — five jobs

Uppercase mono needs air and the amount depends on what the label is *for*;
lowercase mono and display face need almost none.

| Token | Value | Job |
|---|---|---|
| `--ls-label` | `.18em` | uppercase section and pane labels |
| `--ls-ctrl` | `.1em` | uppercase tags, buttons, tabs, shortcuts |
| `--ls-stat` | `.06em` | uppercase stat lines |
| `--ls-mono` | `.02em` | lowercase mono |
| `--ls-face` | `.01em` | the wordmark |

### Type — eleven sizes, each naming its job

| Token | Value | Job |
|---|---|---|
| `--fs-tag` | `9px` | tags, provenance strip |
| `--fs-label` | `9.5px` | every pane label, section label, stat line |
| `--fs-meta` | `10.5px` | counts, subtitles, logs |
| `--fs-ctrl` | `11px` | buttons, `kbd` |
| `--fs-field` | `12px` | inputs |
| `--fs-text` | `13px` | prose |
| `--fs-row` | `13.5px` | list rows |
| `--fs-name` | `14px` | a track name |
| `--fs-base` | `15px` | the page's own base |
| `--fs-mark` | `18px` | the wordmark |
| `--fs-glyph` | `19px` | the gear |

`--fs-text` and `--fs-row` stay half a pixel apart on purpose: one is prose,
one is a list row, and they never sit in the same container. Merging them
would be the only change in this pass you could see.

| Token | Stack |
|---|---|
| `--face` | `"Helvetica Neue", Helvetica, Arial, sans-serif` |
| `--mono` | `"IBM Plex Mono", ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace` |

### Layout

| Token | Value | Job |
|---|---|---|
| `--lw` | `250px` | iPod pane — the two left panes are one width because they do one job |
| `--sw` | `250px` | source pane |
| `--rw` | `320px` | buy / vinyl pane |
| `--hbtn` | `32px` | every header control: search, Sync, the gear |

Fixed heights: **46px** for `.plabel` — the one number that aligns the title
of all four columns. Taking it from `align-items` instead is what made the
titles look crooked; the boxes aligned, the glyphs did not.

### Spacing

`2 · 4 · 6 · 7 · 8 · 9 · 10 · 12 · 14 · 16 · 24`

Eleven steps, not the seven the first register proposed — see Part 8. **7px
and 9px are load-bearing**: they are the vertical paddings that make `.drow`
and `.row` land on their intended heights, used seven and six times
respectively. Forcing them onto even numbers would change the density of
every list in the product.

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

### One title strip, four containers

The dialog and the menu had each grown a near-copy of `.plabel` — same
family, size, tracking, transform and colour, differing only in height and
in whether they drew their own edge. Three rules that had to be kept in step
by hand, and were not.

It is the same shape of thing as the radius ladder: **the strip gets shorter
as the surface gets lighter**, and a surface that floats has to draw the
edge its container does not.

| Container | `--strip-h` | `.seam` |
|---|---|---|
| pane | 46px | no — the column already has an edge |
| panel | 46px | yes |
| dialog | 40px | yes |
| menu | 34px | yes |

One class, one modifier, two custom properties per container. `.seam` means
exactly one thing: *this surface floats, so it draws its own edge* — a
bottom hairline and a `--panel` ground.

**The scrim is load-bearing, not decoration.** The sync plan is a diff taken
against the device a moment ago; letting you change a decision behind it
would make the list on screen a lie.

---

## 4. Rows — three shapes, three jobs

There are exactly three. Adding a fourth needs a reason.

**`.col` has one builder, `colRow()`, and every list goes through it.** Nine
places used to assemble it by hand and they disagreed about their own
internals: four carried a menu slot and five did not, six repeated the same
inline truncation style that `.col .nm` already does, and the album row
nested two more inline-styled spans on top of that. Variants are class and
content — never a different shape.

```js
colRow({name, sub, cnt, cls, attrs, title, art, menu})
//  <div class="col {cls}"> [albart] .nm[.two] .cnt .more[.hold] </div>
```

The menu slot is **reserved, not omitted**, when a row has no menu:
`.more.hold` is `visibility: hidden` and keeps its 28px. That is what holds
every count and every set of dots on the same two verticals down a pane.

### `.row` — a track
`grid 44px / 1fr / auto / auto`, `gap 14px`, `padding 9px 10px`, `radius
10px`, `margin-bottom 3px`.
The only grid of the three, because a track has four fixed regions: artwork,
name, provenance, actions. Fixed columns are what stop the iPod mark moving
between rows.

### `.col` — a named thing with a count
`flex`, `gap 8px`, `padding 8px 10px`, `radius 10px`, `font 13.5px`,
`margin-bottom 2px`. Four slots, always in order: optional `.albart`, then
`.nm`, `.cnt`, `.more`.
Playlists, folders, smart lists, source lists, albums, sync-review rows —
**six lists, one component.** If your new thing is a name plus one number,
it is a `.col`, and it is built by `colRow()`.

Variants: `.nm.two` carries a second line (an album's artist under its
title) via a `.sub` span; `art:` adds the 28px thumbnail; `menu:false`
reserves the dots slot without filling it.

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
| `.inert` | a fact sitting in a list of choices: keeps its slot, dims, does not respond |

There is no state word for "no decision". In the model `tier` holds
`undecided` for 1,004 of 1,211 tracks, but **it is the null, not a choice** —
it has no label, no tag, no filter chip and no key. You reach it by pressing
the same control again (law 8). The filters name the three pending
decisions instead, in the menu's own words: *to buy*, *to sync*,
*to remove*.

`.marked` deliberately uses the same blue as `.sel` at 34% rather than a
second hue: a different colour would say "a different kind of thing", when it
is the same thing in quantity. And a cursor row that is *not* in the
selection is drawn as an outline, so the one row an action will skip never
looks like the rows it will act on.

---

## 8. Drift register — second pass

The first register counted every value equally and proposed cuts on that
basis. Re-measuring with **use weighted by frequency and by what the value is
doing** reversed three of its five recommendations. This is the corrected
record.

### What was actually fixed, 29 September

| Axis | Before | After | Visible? |
|---|---|---|---|
| **colour literals** | `#fff ×12`, 21 white `rgba()` in four alphas for one job | 4 tokens, **0 literals outside `:root`** | no |
| **radius** | 9 values | 4 named steps (`xs sm md pill`) | ≤2px on elements ≤44px |
| **tracking** | 10 values | 5 named jobs | ≤.04em |
| **font size** | 12 sizes, three pairs a half-pixel apart | 11 tokens; `10→10.5`, `12.5→13` merged | ≤0.5px |
| **spacing** | 17 values | 11; retired `3 5 11 18 20 22` | ≤3px, six sites |
| **law 2 violation** | panel gauge filled with the position-blue | `--dim`, matching the footer gauge | yes — intended |

Measured after: `.row` 62px, `.col` 35px, `.plabel` 46px — **unchanged**. The
only geometry that moved was the footer strip (+7px, from `kbd` padding) and
the filter bar (+3px, from `.pill` padding).

### What the register got wrong

**1. Spacing is less drifted than the count suggested.** "17 values for a
four-step job" weighted a value used 18 times the same as one used once. Of
the 17, **eleven are systematic** — five or more uses with a consistent job —
and only six were genuine one-offs. The proposed `2·4·6·8·10·14·24` would
have dropped `12px` (used **14 times**) and forced `7px` and `9px` onto even
numbers, changing row density across 643 rows to satisfy a table.

**2. The radius spread was a ladder, not drift.** `.art` at 44px uses 7px,
`.albart` at 28px uses 4px, `.modes span` at 18px uses 5px. That is the same
optical rule three times — corner scales with box — and flattening everything
to `8/10/99` would have made the small thumbnails look like buttons. The fix
was to *name the ladder*, not remove it.

**3. Tracking has five jobs, not three.** The register proposed
`.06 · .1 · .18` and would have swept `.01em` (the 18px wordmark, where large
type wants *tighter* tracking) and `.02em` (lowercase mono, which needs
almost none) in with the uppercase values. Uppercase and lowercase mono are
different typographic problems.

### What the register got right

**Colour literals.** This was the real one. 21 white literals in four alphas
meaning "text on the selection blue" — changing the selection treatment meant
finding 34 places, and the four alphas were four different answers to one
question. Now four tokens, zero literals.

**The half-pixel font pairs.** `10`/`10.5` and `12`/`12.5` were genuinely
accidental: both members of each pair did the same job in the same kind of
container. Merged, invisibly.

### Still open

- **Naming.** Three schemes coexist: semantic (`.row`, `.col`, `.month`),
  abbreviated inside menus (`.dn`, `.dc`, `.dk`), and id-scoped (`#sp …`).
  **Proposed: leave it.** Renaming touches every template string for no
  behaviour change, and each scheme is consistent within its container.
- **`--fs-text` vs `--fs-row`.** Half a pixel apart, two stated jobs. Merging
  is the one remaining change that would be visible, so it needs a decision
  rather than a rule.

### The census

This is what keeps the system true. Run it after touching the stylesheet:

```
python3 - <<'EOF'
import re
css = open('src/saltpod/curate.html').read().split('<style>')[1].split('</style>')[0]
body = css.split('}', 1)[1]          # everything after :root
for label, pat in [('font size',  r'font(?:-size)?:\s*(?:[^;]*?\s)?([\d.]+px)'),
                   ('radius',     r'border-radius:\s*([\d.]+px)'),
                   ('tracking',   r'letter-spacing:\s*([\d.]+em)'),
                   ('white',      r'(?<![\w-])#fff(?![\w\d])|rgba\(255,\s*255,\s*255')]:
    print('%-10s %s' % (label, sorted(set(re.findall(pat, body))) or 'clean'))
EOF
```

All four must come back clean.

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
