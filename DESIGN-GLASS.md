# saltpod in glass: the design direction

**Status: PROPOSED. Nothing in this document is measured as built.** It extends
`publish/DESIGN.md` (which is measured and enforced) and is the direction the
owner reads before any code changes. Every factual sentence is tagged:
SOURCED (a URL a research finding fetched, cited by finding), MEASURED (run
against the repo, the captured Apple assets, the owner's covers, or the
findings' own arithmetic, cited by finding and section), or INFERRED (a
judgement). An untagged sentence inside a proposal is the proposal.

The evidence base is a set of twenty-five research findings, three competing
proposals, a judge's verdict and three adversarial verifications written in
one session and kept in the session scratchpad (`glass/findings/*.md`), not
in the repo. They are cited here by file name and section. The research was
run mostly on mid-size (Sonnet-class) agents; the proposals, judging,
verification and this document on Fable 5.1; the measurement scripts
(contrast, covers, census) are numpy/PIL/Python with no model.

Corrections to `DESIGN.md` that this document makes are stated plainly in
Part 5 and Part 6 (the `--mono` face is not what the page renders; three
tokens are self-referencing; `.offline` is missing from the vocabulary; the
tier boundary is off by one).

---

## 1. Thesis

Glass goes only where something already floats. The panes, rows and bars that
hold still today keep holding still. The type moves to the system stack. The
phone is the same DOM shown one pane at a time behind a glass tab bar and a
one-slot glass shelf that never minimise, never collapse and never leap. At
Mac width a person who knows the page sees new corners, a new face and a
glass menu, and nothing else moved. At phone width they see iPhone Music's
bottom chrome holding saltpod's own facts.

The owner's own precondition for glass is that the UI has to stop moving
first (MEASURED, `research/NATIVE-APP-SPEC.md` phase 4). That condition
decides every argument below where Apple's pattern and stillness disagree:
the large title that collapses, the tab bar that minimises, the swipe tiles,
the springs and the page that recolours with the record are all left out,
each with its reason in Part 11.

What "reads as Apple Music" is bought with, in order of cost: the system face
(one line of CSS), capsule-shaped controls in the header (three rules),
concentric radii on the floating layer (two tokens), regular glass on the
menu and dialog (one recipe), and on the phone the floating tab bar plus the
accessory shelf, the two shapes Apple names as Music's own (SOURCED, HIG
tab-bars via iphone-music S1; WWDC25 284 via glass-principles S4). Nothing
else is bought. The honest ceiling is Apple's own web glass: blur, saturate,
a translucent fill, a hairline ring and a shadow (MEASURED, web-player s1).
No lensing, no refraction, no adaptive light/dark flip; SVG refraction is
Chromium-only and paints nothing in Safari (SOURCED, WebKit 245510 via
web-feasibility s1).

---

## 2. The reference: what iPhone Music does on iOS 26 and 27

The facts the direction stands on, screen by screen. Where a number is Apple's
it says so; where it is a forum measurement or an inference it says that.

**Tab bar.** Floats above content at the bottom; items rest on Liquid Glass;
content peeks through beneath (SOURCED, HIG tab-bars JSON via iphone-music
S1). Geometry, read from Apple's own iOS 26 and 27 Sketch kits: bar 62 high,
inset 21 from the left, right and bottom edges, inner pad 4, cells 54 high,
selected pill radius 27 with fill `#787880` at 32%, label SF Pro 10
(Semibold in 27), symbol SF Pro Semibold 18; unchanged from 26 to 27
(MEASURED, design-kit-measurements s2; ios27-music-delta s2b). The 21pt inset
is Apple's own 26.1.1 change-log entry (SOURCED via design-kit s0). In the
kit's own example the bar sits at y 791..853 on an 874 screen, 21 above the
physical edge, inside the 34pt home-indicator inset (MEASURED,
owner-device-frame s3). Minimising on scroll is optional ("you can choose to
minimize the tab bar") and the person exits it "by tapping a tab or scrolling
to the top of the view" (SOURCED, HIG tab-bars via ios27 s2a); a developer
test against Music on iOS 27 says it restores only at the scroll edge, not on
a short upward scroll (SOURCED, third-party, ios27 s2a). NN/g's recorded
complaint is that the bubble "leaps up to make space for the tab bar when you
reach the top" (SOURCED, nngroup via iphone-music S13).

**Search.** iOS 26 detached it as a 62x62 circle; iOS 27 put it back inside
the capsule as an ordinary tab in Apple's own apps (SOURCED, HIG search-fields
diff of 8 Jun 2026 and MacStories via ios27 s2a). Music also has an inline
"Find in Songs" field inside a library category, which the HIG names as the
pattern for filtering a list (SOURCED, Apple Support and HIG search-fields
via iphone-music s4).

**Accessory shelf and mini player.** The HIG's own example of the tab-bar
accessory is "the MiniPlayer in Music"; accessories are for "persistent
features ... like media playback controls that stay visible across your app.
Avoid placing screen-specific actions here" (SOURCED, HIG tab-bars and WWDC25
356 via glass-principles s10, s12). Apple publishes no accessory geometry:
neither the 26 nor the 27 kit contains a mini player, accessory or minimised
bar frame (MEASURED, design-kit s9; ios27 s0 item 6). The one forum
measurement is 56 = 48 + 8 on iOS 26.2 (SOURCED, a react-native PR via
iphone-music S14). Apple's own web player at phone width draws its mini
player as a glass capsule 52 high, 12px side margins, radius 1000, art 32
radius 6, fixed to the bottom, blur 16 and saturate 220% (MEASURED,
web-player-phone-layout s1). In iOS 26.1 an empty accessory container was
reported as a bug (SOURCED, Apple developer forums via
accessory-shelf-occupancy (a)): a reserved slot with nothing in it is a
failure Apple's own developers complained about.

**Now Playing.** Dismiss chevron, artwork, title and tappable artist, favourite
and more, scrubber with times, transport, volume, a bottom row of glass
buttons (SOURCED, Apple Support via iphone-music s3). Controls float "on a
platter of liquid glass" over the art (SOURCED, 9to5Mac via
artwork-backdrops 1.2). Artwork shrinks when paused (SOURCED, iDownloadBlog
via iphone-music s3). Apple's full-screen gradient is four spinning copies of
the art through a twist shader and a Kawase blur, a GPU effect a reverse
engineer ran at 15 fps (SOURCED, aadishv via artwork-backdrops 1.1).

**Library.** A category list with Pins (max six) above it; each category a
drill-down row; the large title "Library" collapses to an inline 17 Semibold
title as content scrolls; iOS 26 placed large titles inside the scroll view
(SOURCED, Apple Support, MacStories and WWDC25 284 via iphone-music s4).
The nav bar has no container fill: titles float on the scroll-edge effect
and only the buttons are glass (MEASURED, design-kit s4). Kit numbers: bar
44 in a 54 frame, side inset 16, button 44, grouped icon buttons 104 / 160,
large title 34/41 Bold, inline title 17/22 Semibold (MEASURED, design-kit s4;
unchanged in 27, ios27 s2d).

**List rows.** Kit default row 52, large row 68 with 52 art; separator 1pt
white at 12% (MEASURED, design-kit s8). Song-row art size and radius are not
in the kit and not published (MEASURED absence, design-kit s11). Dynamic Type
at the default size: Body 17, Callout 16, Subhead 15, Footnote 13, Caption 1
12, Caption 2 11, Large Title 34/41 (SOURCED, HIG typography table via
iphone-music S35).

**Album and playlist pages.** Large art, title, artist, then the Play /
Shuffle pair, then rows (SOURCED, Apple Support via iphone-music s6). iOS
26.4 made these pages full-screen and coloured the whole page from the art,
"a color that pairs well with and evokes the artwork", black when the art is
white or grey (SOURCED, 9to5Mac via artwork-backdrops 1.2); iOS 27 extended
the idiom to artist pages (SOURCED, MacStories and 9to5Mac via ios27 s2i).
Beta testers of 26.4 called "song titles over a fully colored background in
an album list ... terrible" (SOURCED, BGR via artwork-backdrops 1.2).

**Context menus.** Touch-and-hold or the ellipsis opens the same menu
(SOURCED, MacRumors and HIG context-menus via iphone-music s7); menu 250
wide, radius 32, rows 42, pad 10 (MEASURED, design-kit s7; unchanged in 27);
destructive items last; "hide unavailable menu items, don't dim them"
(SOURCED, HIG via touch-interaction s1). Menus "spring from the action
itself" (SOURCED, WWDC25 356 via glass-motion s2).

**Sheets.** Partial-height sheets are inset glass; at full height the glass
"transitions to opaque and anchors to the edge of the screen" (SOURCED,
WWDC25 323 via touch-interaction s1; kit: half sheet glass, full sheet
`#1c1c1e`, MEASURED design-kit s6). The medium detent moved from 390x380
(iOS 26) to 386x451 with 8pt gaps in iOS 27, radius 34 both; the grabber
grew from 36 to 60 wide (MEASURED, ios27 s2e). The grabber can be tapped "to
cycle through the detents" (SOURCED, HIG sheets via touch-interaction s1).

**The material.** Two variants, Regular and Clear, never mixed; Clear needs a
dimming layer and all three of its conditions (media-rich content, content
that tolerates dimming, bold bright content above) (SOURCED, WWDC25 219 via
glass-principles s2). Glass is for the floating layer, never the content
layer; never stacked; tint only the primary action, and put the colour on the
background not the label (SOURCED, 219, HIG materials and color via
glass-principles s1, s8, s10). Concentricity: capsule radius = height / 2; a
nested shape's radius = the parent's minus the padding (SOURCED, WWDC25 356
via glass-principles s5). Apple's own three accessibility settings: Reduce
Transparency makes glass "frostier", Increase Contrast makes elements
"predominantly black or white" with a border, Reduce Motion "disables any
elastic properties" (SOURCED, 219 via accessibility s1). iOS 26.1 added a
Clear/Tinted switch and iOS 27 a slider whose default is "more tinted than
the Clear setting of iOS 26" (SOURCED, TechCrunch and MacStories via
failure-modes B, ios27 s2g). On the web, iOS Safari cannot read Reduce
Transparency (`prefers-reduced-transparency` unsupported through 27.2) but
can read Increase Contrast (`prefers-contrast: more`) and Reduce Motion
(SOURCED, caniuse and MDN via accessibility 0.1, web-feasibility s1).

**macOS.** Tahoe's inset glass sidebars were criticised ("a weird strip of
the window background ... looks broken"; "I can barely see the selection
highlight") (SOURCED, mjtsai roundup via desktop-glass s3) and macOS 27 moved
sidebars back to the window edge with semi-bold selection (SOURCED, WWDC26
289 via desktop-glass s2). This is the platform the page is used on most.

**Apple's web player at phone width** does not copy the native chrome: a fixed
52px glass top bar with a hamburger drawer, no bottom tab bar, no safe-area
handling, and the one capsule mini player above (MEASURED,
web-player-phone-layout s0, s1). saltpod copies the native app, not the web
player, because the owner named the native app, because four parallel
destinations in a drawer are hidden, and because the capsule mini player is
Apple's own web precedent for the shelf (INFERRED, web-player-phone-layout
s5). Apple's web glass turns off when the window loses focus and goes solid
under Increase Contrast (MEASURED, web-player s3).

**The owner's phone** is an iPhone 17 Pro, 402x874, status inset 62, home
inset 34; whether it runs iOS 26.6 or 27 is not confirmed (MEASURED,
owner-device-frame s0, s1). No iPad is in evidence after 2025. The kit is
drawn only at 402x874 (MEASURED, owner-device-frame s4).

---

## 3. The direction

### 3.1 Mac width (>= 1000px): today's layout, with four visible changes

Today's geometry at 1512x813 (MEASURED, desktop-glass s4): header 58; `#work`
719.6; left 250 at x0, source 250 at x250, mid 692 at x500, right 320 at
x1192; footer 35.4; `.plabel` 46; `.row` 62; `.col` 34.9. All of it stays.
The four-pane grid, the fold rails, the keyboard model, drag and drop, the
hover-revealed `.more`, the right-edge `#sp` and `#tp` panels, the in-column
`#lsheet`, the fixed `#rsheet`, the centred `#dlg`: unchanged in position,
size and behaviour. That is the direction, not an omission.

What changes at rest:

1. **The face.** `--face` resolves to SF Pro on Apple hardware. The mono does
   not change in practice: `--mono` names IBM Plex Mono, nothing loads it and
   it is not installed, so the mono is already SF Mono (MEASURED, type-colour
   headline 1; verifier-laws s1 law 5: `~/Library/Fonts`, `/Library/Fonts`,
   `fc-list` and `system_profiler` all empty for Plex; `<head>` carries no
   `<link>`).
2. **Header controls become capsules.** `#q` (400x32) takes `--r-pill`;
   `#dosync` (55.6x32) takes `--r-pill` and keeps its blue fill; `#gear`
   (32x32) becomes a circle. No `backdrop-filter` on any of them: the band is
   flat `--ground` and glass over a flat token changes zero pixels (MEASURED,
   desktop-glass s4 option G). Three groups is the HIG ceiling; one primary
   action, trailing, tinted (SOURCED, HIG toolbars via glass-principles s7).
3. **The floating layer is regular glass.** `#menu` and `#dlgbox` take the
   glass recipe (Part 3.4) and the new `--r-lg` corner. `#toast` stays what it
   is today, an opaque inverted pill (`--ink` on `--ground`, 15:1), because it
   is the most legible element on the page, an interrupt of about two seconds,
   and glass on it would stack on the open glass sheet on the phone
   (verify-legibility s3, recommended; failure-modes G5). `#sp`, `#tp`,
   `#lsheet`, `#rsheet` stay opaque `--ground`: large, text-dense, two of them
   over a load-bearing scrim, and Apple's own rule that a full-height sheet
   goes opaque (SOURCED via glass-principles s4). They gain only the
   tokenised rim and shadow they already draw.
4. **The selected row is repaired.** `--on-sel-dim`, `--on-sel-line` and
   `--on-sel-hi` are defined as references to themselves at `curate.html`
   42-44 and compute to invalid, so the selected row's secondary text falls
   back to inherited white and the top highlight never draws (MEASURED by
   four findings: accessibility 0.4, type-colour headline 5, desktop-glass
   s9, verifier-laws). Setting them to `DESIGN.md`'s values makes the
   selected row look different, and correctly so. In the same change the blue
   fills start at a new `--sel-top` so white text passes at the row centre
   (Part 4).

Smaller visible changes at Mac width, each a repair of a law rather than a
redesign: `.col.on.pend .cnt` becomes an orange dot beside an `--ink` count
on the raised row (orange text on `--raised` is 4.06, fails; MEASURED,
accessibility C5); menu rows Move up / Move down / Move to top / Move to
bottom appear, closing the hole where `nudge()` is keyboard-only today
(MEASURED, touch-interaction s2.3); `#undoc` in the footer becomes clickable
(today a span with no handler; MEASURED, verifier-laws law 7); the segment
pill "Library" in the source pane is renamed "Drive" so that one word means
one thing (Part 3.2).

Not changed at Mac width, and said so because findings proposed them: no
inset glass sidebar (walked back in macOS 27; over `--ground` it blurs
nothing; it breaks the 24px fold rails: desktop-glass s2, s3, s4); no
scroll-edge effect (nothing floats over the lists; "shouldn't be used where
there aren't any floating UI elements", SOURCED WWDC25 356 via
glass-principles s4); no large title; no per-album backdrop under panes.

### 3.2 Phone width (< 700px): one pane at a time, the same DOM

Frame: 402x874 standalone, status bar 62 (not ours, opaque, style `black`),
home indicator inside the bottom 34. Tier boundary 700 and the middle tier
(700-999) come from phone-information-architecture s6 and are not redrawn
here; no device for the middle tier is known (owner-device-frame s0).

```
 y 0    system status bar (62)                                  not ours
 y 62   HEADER, in flow, 52, opaque --ground      [ (#q 44 capsule "Find in ...") ] (gear 44) [ SYNC . 2 ]
 y 114  .plabel of the pane on top, in flow, 46   [<] Name                           Select / the pane's action
 y 160  .filters (pushed page only), 44, one scrolling row of pills
 y 204  .pbody: the ONE scroller, --ground, rows flat; content scrolls UNDER the two shapes below
 y 731  SHELF   glass capsule, inset 21, 52 high   (dot / art)  what is happening now     [ play/pause slot ]
 y 783  gap 8
 y 791  TAB BAR glass capsule, inset 21, 62 high   [ iPod ]   [ Library ]   [ Buy ]
 y 853  21 to the physical edge; the home indicator sits in it
```

- **The header is the existing `<header>`**, kept in flow (not fixed) so iOS
  26 Safari does not sample it for its toolbar tint (SOURCED, 1ar.io via
  web-feasibility s5). `h1` and `.counts` are hidden at this width. `#q`
  grows to a 44 capsule, `#gear` to a 44 circle, and `#dosync` stays here as
  the trailing tinted capsule at 44 (judge graft G1, from
  design-structure-first s1.1): HIG puts a primary action in the toolbar,
  "stays separate and appears tinted", and keeps screen-specific actions out
  of the accessory (SOURCED, HIG toolbars and tab-bars via glass-principles
  s7, s10). One Sync element at every width; the proposal's own risk of two
  controls disagreeing is gone. The owner should still see the alternative
  (Sync in the shelf) once in the mock, as the judge asked.
- **`#q` filters the current list**, nothing more: `qi.oninput` runs
  `pass()` over `currentList()` (MEASURED, critic-2). Its placeholder names
  that scope ("Find in All on iPod"), which is Apple's inline "Find in Songs"
  (SOURCED via iphone-music s4). There is no Search tab: the server has no
  library-wide search endpoint, and the layer rule forbids inventing one in
  the page.
- **The `.plabel` is the pane's strip exactly as today** (law 6): 46 high,
  name left, the pane's one action right. On the pushed page the leading slot
  holds a 44x44 back chevron (a new element, hidden at Mac width, in the slot
  the `.fold` occupies on the other panes); its right slot holds Select /
  Done (Part 5, law 6). The pushed page's title is set in the face at 17/600,
  Apple's inline title (MEASURED, design-kit s4); the roots' names (iPod,
  Library, Buy) stay mono uppercase (Part 5, law 5).
- **Roots and the pushed page.** Roots are `aside.left` (tab iPod),
  `aside.srcpane` (tab Library, segments Music | Drive in the strip) and
  `aside.right` (tab Buy, segments Buy | Vinyl). The pushed page is
  `section.mid`: tapping any `.col` in a root sets `body.pg` and pushes
  history; the back chevron, the system edge swipe (`popstate`) or re-tapping
  the active tab clears it. One boolean of view state; `currentList()` is
  already a pure function of `(active, pick)` (MEASURED, phone-IA s1).
  Inactive roots carry the `hidden` attribute and the pushed-away root is
  `inert` for the whole of `body.pg`, so VoiceOver never walks into a
  translated-off pane (verify-legibility R5, fix 5).
- **The tab is called Library and the drive segment is called Drive.** Today
  the source pane's segment pills read "Music" and "Library" and the pane's
  own `aria-label` is "Source" (MEASURED, `curate.html` 845), so a tab named
  LIBRARY would hold a segment named Library (verifier-laws law 1). Renaming
  the segment to Drive costs one word at every width, and the page already
  calls the condition "needs a drive" in its filter chips. The alternative
  (tab SOURCE) is an open decision (Part 12).
- **The shelf and the tab bar are two new elements at the end of `<body>`**
  (DOM order = tab order, accessibility E1), `position: fixed`, siblings of
  `#work`, never inside anything with `opacity`, `filter`, `mask` or
  `clip-path` (the backdrop-root rule, MEASURED glass-motion s0). At >= 700px
  they are `display: none`; they do not exist as a presentation there. Both
  are drawn by inset (`inset-inline: var(--bar-inset)`), never by a fixed
  width, so a 320px viewport and 200% zoom reflow instead of overflowing
  (verify-legibility R7, fix 7).
- **The footer is hidden at this width.** `#keys` already is below 900
  (MEASURED). `#hstrip`'s facts move: the iPod state to the shelf's idle
  line, GB free to the shelf's idle line and the Data sheet, Music state and
  volume state to the Data sheet, the drive's offline state also to the
  Library banner (Part 7).
- **Clearance and meta.** `.pbody` gets `padding-bottom: calc(var(--bar-inset)
  + var(--tab-h) + var(--chrome-gap) + var(--shelf-h) + 16px)` = 159px.
  `env(safe-area-inset-bottom)` is not added to the bar's offset: the kit
  draws the bar 21 above the physical edge, inside the 34 inset (MEASURED,
  owner-device-frame s3). Four meta additions: `viewport-fit=cover`,
  `apple-mobile-web-app-capable`, `apple-mobile-web-app-status-bar-style`
  `black`, `theme-color #141d29`; `100dvh` with a `100vh` fallback
  (standalone-home-screen-mode s10). `--bar-inset` is 21 only under
  `@media (display-mode: standalone)`; in a Safari tab the bars sit at the
  layout-viewport bottom, because `bottom: 21px` there floats above Safari's
  own toolbar (SOURCED via web-feasibility s5; verify-feasibility F6).

### 3.3 The shelf and the tab bar, exactly

**The shelf** is one static glass capsule, 52 high, radius 26 (capsule =
h/2), inset 21 on both sides so it shares an edge with the bar. Its height
is Apple's web mini player (MEASURED, web-player-phone-layout s1); the 8px
gap above the bar is the one chrome number no Apple source measures (the
forum's 56 = 48 + 8, SOURCED via iphone-music S14) and is flagged as such.

It has one meaning, law 2's "what is happening now", and three values in
fixed priority (accessory-shelf-occupancy (d), narrowed by verifier-laws
fix 1):

1. **SYNCING**: orange dot, `--ink` mono "Syncing 14 of 38"; tap opens the
   sync sheet. Lost contact mid-sync: the line freezes and reads "Lost contact
   · sync continues on the Mac" in the `.lost` style, no orange, nothing
   animating (phone-liveness s6).
2. **PLAYING**: 28px art at `--r-xs` (the `.albart` size; the capsule's 12px
   inset makes 28 + 24 = 52 exactly), the name in the face, the artist in
   `--dim-glass` mono, the orange `.eq` bars, and a 44x44 play/pause in the
   trailing cell; tap elsewhere opens `#tp`. No next or previous: saltpod has
   no queue (MEASURED, accessory-shelf (b)).
3. **IDLE**: one line about the link to the device, in severity order: "Can't
   reach the Mac" (`.lost`, tap retries) > "iPod not connected" / "iPod
   waking" / "Ejected 14:32 · safe to unplug" > "iPod ready · 150 GB free".
   Tap opens the Data sheet.

The drive's offline state is not a shelf value (it lives in the Library
banner and the Data sheet) and the pending count is not a shelf value (it
lives on Sync). The trailing cell is a reserved play/pause slot, `visibility:
hidden` when nothing plays, the `.more.hold` pattern (MEASURED, `curate.html`
764); nothing in the shelf ever appears. The three values are three children
stacked in one grid cell; the two inactive ones carry `inert` and
`aria-hidden` during the 150ms fade and `hidden` once it ends, never a
focusable `aria-hidden` button (verify-legibility R4, fix 4). The idle
headline is computed on the server (Part 5, the layer rule).

**The tab bar** is 62 high, inset 21, inner pad 4, three cells of
`flex: 1 1 0; min-width: 0` (117x54 at 402), selected pill 54 high radius
27 (MEASURED kit numbers, ios27 s2b). Labels IPOD / LIBRARY / BUY in mono
uppercase 11px 600 with `--ls-ctrl`, ellipsised with the full name kept as
the accessible name; glyphs 24px from the inline Phosphor sprite, outline at
rest and filled when selected in the same 256 box so nothing shifts
(tab-bar-iconography). The active tab is the pill plus the filled glyph in
`--sel-hi` (an icon, 3:1 floor) plus the label in `--ink`; the inactive
labels sit in `--dim-glass`. The pill's fill is `--raised` (Part 4.1). The
bar never minimises.

### 3.4 Material system

Regular glass only. Clear is never used: its three conditions are not met
anywhere on a dark page of lists. Glass is never on rows, never on a pane
body, never on a bar that nothing scrolls under.

| Surface | Mac width | Phone width | Dimming layer |
|---|---|---|---|
| Page ground, panes, `.pbody`, rows, cards | flat `--ground` | flat `--ground` | none |
| Header band | flat; controls take capsule shape, no blur | flat, in flow | none |
| `.plabel` strips, `.filters`, `.substat` | flat, in flow | flat, in flow (hard style by construction: opaque plus hairline) | none |
| Footer | flat | hidden | none |
| `#menu` | GLASS regular, `--r-lg`, anchored | GLASS regular, medium-detent sheet, `--r-sheet` | `--scrim` on phone only |
| `#toast` | OPAQUE inverted pill, as today; hidden with the `hidden` attribute, never `opacity: 0` | same, placed above the shelf | none |
| `#dlgbox` | GLASS regular, `--r-lg` | same | `--scrim-deep` (the existing .72) |
| `#sp` sync review | OPAQUE, rim and shadow tokens | OPAQUE large-detent sheet, `--r-sheet` top corners | `--scrim` (the existing .55, load-bearing) |
| `#tp` track panel | OPAQUE body; the art region is the one art-backed surface (Part 7) | OPAQUE large-detent sheet | `--scrim` |
| `#lsheet`, `#rsheet` | OPAQUE as today | OPAQUE large-detent sheets | `--scrim` |
| Shelf | n/a | GLASS regular capsule; SOLID twin while any sheet, menu or dialog is open | none (content scrolls under) |
| Tab bar | n/a | GLASS regular capsule; SOLID twin while any sheet, menu or dialog is open | none |
| Scroll edge under bars | none (nothing floats) | none: the 27 kit draws no bottom scroll edge (MEASURED, ios27 s2b); the top strips are in flow | none |

The phone stacking rule (verify-feasibility F1): while `#menu`, `#dlg`,
`#sp`, `#tp` or any sheet is open at phone width, the tab bar and shelf take
their Solid twin (`backdrop-filter: none; background: var(--ground)`) under
the scrim. A value change, not a position change (law 1). Live blurs then
never exceed two at rest and one when something is open, and "never stack
glass on glass" is true by construction.

The recipe, one set of tokens (Part 4.2). Every glass element has
`background: transparent` and no `backdrop-filter` on the host; the fill and
blur live on `::before` (`position: absolute; inset: 0; border-radius:
inherit; z-index: -1`): `backdrop-filter: blur(var(--glass-blur))
saturate(var(--glass-sat))` with the `-webkit-` twin and `background:
var(--glass-fill)`; the rim is `::after` with `box-shadow: inset 0 0 0 1px
var(--glass-rim)`; the element carries `box-shadow: var(--shadow-float)`.
This is Apple's own web structure (MEASURED, web-player s1) and it is also
the condition under which Safari 26 does not sample a fixed element for its
toolbar tint: pseudo-elements are invisible to the tinting algorithm, the
host itself is sampled, and `opacity: 0` elements are still sampled
(SOURCED, 1ar.io re-fetched by verify-feasibility s1). Today's `#toast` is
fixed, `opacity: 0` and white-backed, so the page in a Safari 26 tab can
already tint the toolbar white (MEASURED, `curate.html` 616-619); the
`hidden` attribute fixes it.

The fill alpha .85 is the floor at which `--ink` passes 4.5:1 over pure white
behind the glass (10.65) and `--dim-glass` (.75) passes (6.82); `--dim`
(.55) is 4.49 and fails by rounding, `--faint` as text is 1.93, ink at
opacity .5 is 4.00 (MEASURED, verify-legibility s1 R1). So on every glass
surface the dim and faint tokens are re-declared once on the surface,
`--dim: var(--dim-glass); --faint: var(--glass-rim-hc)`, rather than rule by
rule, and no glass surface dims a row with `opacity` (Part 4.1). Over the
real library the bound is kinder: under a 44px thumbnail in a row the worst of
the 60 covers composites to a glass surface where `--ink` is 12.77 and
`--dim-glass` 7.93; the pure-white bound is reached only by full-bleed art
under glass, which this design never draws (MEASURED, verify-legibility
"not refuted", covers.py).

### 3.5 Motion

What moves, and only this:

| # | What | How | Duration | Reduced-motion twin |
|---|---|---|---|---|
| 1 | Panels and sheets in and out (`#sp`, `#tp`, `#lsheet`, `#rsheet`; phone bottom sheets) | `transform` only, as today | `--t-base` `--ease-out` | `transition: none` (already in the reduce block) |
| 2 | Push and pop on the phone | `transform: translateX` on `section.mid` and the root, siblings of the glass; no parallax | `--t-base` `--ease-out` | instant swap |
| 3 | Menu open | `transform: scale(.96)` plus `opacity` on `#menu` itself, origin at the anchor | `--t-fast` | instant |
| 4 | Shelf value change | `opacity` cross-fade of the three children, never of the glass | 150ms linear | keep the fade (a fade is Apple's own reduce-motion practice, SOURCED HIG accessibility via glass-motion s2), listed flat in the reduce block |
| 5 | Toast | `@starting-style` fade in on `hidden` removal, or none | `--t-fast` | none |
| 6 | `.eq` bars, `.loading` ring, `.look.on` pulse | as today | as today | `animation: none` (existing) |

What never moves: the tab bar, the shelf's glass, the `.plabel` strips, the
filter row, rows at rest, the page ground, the blur radius (a constant token;
what changes between detents is the fill alpha, glass-motion s5 row 4), the
rim (static, no pointer-tracked highlight), the title (no large-title
collapse). No springs: Apple publishes no millisecond values anywhere
reachable (MEASURED, glass-motion s2; the 27 kit carries geometry, not
timing) and the file's own `.22s cubic-bezier(.32,.72,0,1)` already exists.
No View Transitions. Detents are two fixed sizes reached by tapping the
grabber (SOURCED, HIG sheets via touch-interaction s1); no drag-to-resize.

Rules the implementation keeps (glass-motion s6, MEASURED in Chromium, Safari
untested): glass moves by `transform` and by its own geometry; it is never
the child of anything that fades, masks, filters or clips (a parent at
`opacity: .99` destroys the blur, MEASURED glass-motion s0); blur never
animates; every top-layer exit is timed in JS before `close()`; every new
`transition:` or `animation:` is written flat and listed in the
`prefers-reduced-motion` block, or pagetest's gate fails (MEASURED,
`bin/pagetest.py` 915-939).

---

## 4. Token changes

Rule kept: every colour, radius, tracking and size is a token in `:root`; the
census must come back clean. It is clean today for its four classes, but the
stylesheet carries literals the census does not look for: `rgba(255,255,252,
.13)` once, `rgba(7,12,19, ...)` four times, `rgba(0,0,0, ...)` three times,
`rgba(106,169,244, ...)` twice, and one negative tracking `-.005em`
(MEASURED, proposal-least-movement s3 and verify-feasibility s3, counts
agree). This pass tokenises all of them and extends the census so they
cannot drift back (Part 11, phase 0).

### 4.1 Colour

| Token | Today | Proposed | Why |
|---|---|---|---|
| `--on-sel-dim` | `var(--on-sel-dim)` (self-reference, invalid) | `rgba(255,255,255,.82)` | repair; `DESIGN.md`'s stated value (MEASURED defect, four findings) |
| `--on-sel-line` | self-reference | `rgba(255,255,255,.55)` | same |
| `--on-sel-hi` | self-reference | `rgba(255,255,255,.16)` | same |
| `--sel-top` | none | `#2f6fd0` | the top stop of every blue fill (`.row.sel`, `#dosync`, `button.go`, `.drow:hover`, drop hovers). White on it is 4.87 at the top edge and 5.6 at the row centre; today's `--sel-hi` top gives 2.44 and 4.15 (MEASURED, accessibility 0.3, verify-legibility). `--on-sel-dim` on the new fill: 3.84 at the top edge (no text sits there), 4.58 at the centre, 4.88 where the subtitle sits (MEASURED, verify-legibility). `--sel-hi` itself is unchanged and keeps its jobs as a mark on the ground. The light still falls from the top; it starts one step lower |
| `--glass-fill` | none | `rgba(20,29,41,.85)` | `--ground` at the contrast floor; a blue-black ground needs a blue-black fill, not Apple's neutral grey (MEASURED, web-player s5; INFERRED) |
| `--glass-rim` | none | `rgba(255,255,252,.40)` | the floating edge: 3.77 on the ground, 3.14 over glass over white, the 3:1 non-text floor the checklist asks for (verify-legibility R3, fix 3; .30 was 2.70). Apple's web uses .20 and a shadow; a shadow is not readable under Increase Contrast |
| `--glass-rim-hc` | none | `rgba(255,255,252,.50)` | 5.14 on the ground; the real 1px border under `prefers-contrast: more` and the Solid twin, as Apple's own web does (MEASURED, web-player s3). Also the `--faint` replacement on glass |
| `--dim-glass` | none | `rgba(255,255,252,.75)` | secondary text on glass, 6.82 over white at .85 fill; `--dim` stays for opaque grounds only (5.92 there) |
| `--scrim` | literal `rgba(7,12,19,.55)` on `#spscrim` | token, same value | also the phone sheet scrim |
| `--scrim-deep` | literal `rgba(7,12,19,.72)` on `#dlg` | token, same value | |
| `--shadow-float` | literal `0 14px 28px rgba(0,0,0,.45)` on `#menu` | token, same value | applied to the dialog too: one floating idiom |
| `--shadow-panel` / `--shadow-sheet` | literal `-18px 0 46px rgba(7,12,19,.5)` on `#sp`/`#tp` | token; sheets rotate it to `0 -18px 46px` | |
| `--lift` | literal `rgba(255,255,252,.13)` on `#q:focus` | token, same value | |
| `--drop-fill` / `--drop-wash` | two `rgba(106,169,244, ...)` literals | `color-mix(in srgb, var(--sel-hi) 12%, transparent)` / `7%` | derived from the blue they are; `color-mix` is already used on `.row.marked` (MEASURED, verify-feasibility) |
| `--tab-on` | none | not a new token: the selected pill uses `--raised` (white .09) | "selected fill" is `--raised`'s stated job. Three hues stay three (ground, blue, orange; verifier-laws law 2). The glyph in `--sel-hi` on an ink pill over glass over white measures 3.43 at .08 and 3.23 at .10 (MEASURED, verify-legibility R2), so .09 is about 3.3, INFERRED by interpolation and to be asserted by gate G2. The kit's own `rgba(120,120,128,.32)` gives 3.26 but is a fourth hue; it is the owner's alternative (Part 12) |
| `--ground`, `--seam`, `--ink`, `--dim`, `--faint`, `--panel`, `--raised`, `--sel-hi`, `--sel-lo`, `--orange` | unchanged | unchanged | the identity, read off the device |

Scoping on glass (verify-legibility fix 1): `#menu`, `#dlgbox` and the phone
menu sheet re-declare `--dim: var(--dim-glass); --faint:
var(--glass-rim-hc)`. `.drow.todo .dn` and `.drow.skip .dn` take
`--dim-glass` with the existing strike as the second cue; `.drow.inert`
drops `opacity: .5` for `--dim-glass` text and `aria-disabled`; input borders
on glass take `--glass-rim-hc`. `.tag.skip` on the selected row (white at .5
on the new blue, 2.68) becomes `--on-sel-dim` plus strike in the same commit
as `--sel-top`.

### 4.2 Glass parameters (a new census class, "glass")

| Token | Value | Why |
|---|---|---|
| `--glass-blur` | `16px` | Apple's web chrome value (MEASURED, web-player s1); the kit's 30 is Sketch units with lensing, not CSS px (ios27 s2g); never animated |
| `--glass-sat` | `180%` | the lower of Apple's own two web values (180-220, MEASURED prod.css). On a blue-black ground 220% pushes cover colours toward law 2's blue (4 of 35 covers were more than 30% blue under a sidebar, MEASURED desktop-glass s4). One eyeballed choice; check on the device |

### 4.3 Radius ladder, with concentricity

Rule (SOURCED, WWDC25 356 via glass-principles s5): a capsule's radius is
half its height; a nested shape's radius is the parent's minus the padding
between them. Precedence (verifier-laws fix 9): the ladder governs artwork
and content; concentricity governs controls and containers. The ladder gains
two steps, both derived from existing values so nesting is concentric by
construction.

| Token | Today | Proposed | Band / derivation |
|---|---|---|---|
| `--r-xs` | 4px | 4px | <= 28px: thumbnails, mode marks, the shelf's 28px art |
| `--r-sm` | 8px | 8px | nested rows, menu rows, wells, 44px artwork |
| `--r-md` | 10px | 10px | rows, cards, containers |
| `--r-lg` | none | 14px | floating surfaces at Mac width: `#menu`, `#dlgbox`. = `--r-sm` 8 + the menu body's 6px padding, so `.drow` inside the menu is concentric without changing `.drow`. The dialog's inner rows sit 14-16 from its edge with an 8px radius; by the rule the outer should be 22-24; the 8px residue is accepted rather than a third floating step |
| `--r-sheet` | none | 24px | phone sheet top corners. = `--r-md` 10 + `.pbody`'s 14px side padding, so a `.row` inside a sheet is concentric. Apple's kit value is 34 (MEASURED, design-kit s6); 34 would need 24px padding or a 10px inner radius. The kit pair 20 / 34 is the owner's alternative (Part 12) |
| `--r-pill` | 99px | 99px | unchanged; now also `#q`, `#dosync`, `#gear`, the tab bar, the shelf |

### 4.4 Type

| Token | Today | Proposed | Why |
|---|---|---|---|
| `--face` | `"Helvetica Neue", Helvetica, Arial, sans-serif` | `-apple-system, system-ui, "Helvetica Neue", Helvetica, Arial, sans-serif` | SF Pro with Text/Display optical sizing on every Apple device (SOURCED, webkit.org/blog/3709 via type-colour); Helvetica Neue elsewhere, as today. Never names "SF Pro" (not licensed for the web) |
| `--mono` | `"IBM Plex Mono", ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace` | `ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace` | removes a face that is never loaded and not installed (MEASURED). Law 5 is a rule about role, not a typeface. `DESIGN.md`'s token table and the brief's "mono (IBM Plex Mono)" describe a face the page does not render; this is the correction |

Scale: Mac width unchanged, all eleven tokens. The phone re-declares the same
names in a second `:root` block inside `@media (max-width: 699px)` on Apple's
Dynamic Type steps (SOURCED, HIG typography via type-colour s1):

| Token | Mac | Phone | Meets |
|---|---|---|---|
| `--fs-tag` | 9 | 11 | Caption 2; also the tab label |
| `--fs-label` | 9.5 | 11 | Caption 2 |
| `--fs-meta` | 10.5 | 12 | Caption 1; the shelf's status line |
| `--fs-ctrl` | 11 | 13 | Footnote |
| `--fs-field` | 12 | 16 | the iOS no-zoom floor for inputs (SOURCED via accessibility D4) |
| `--fs-text` | 13 | 15 | Subhead |
| `--fs-row` | 13.5 | 16 | Callout |
| `--fs-name` | 14 | 16 | Callout; two tokens, one value on the phone (`DESIGN.md`'s open merger, answered for the phone only) |
| `--fs-base` | 15 | 17 | Body |
| `--fs-mark` | 18 | 17 | the pushed page's title in the strip (inline title 17/600) |
| `--fs-glyph` | 19 | 20 | Title 3 |

No `--fs-large`: there is no large title. Weights: face 400 and 600; 700
stays on the wordmark and on `.t .n` at Mac width (600 on the phone, where
SF at 16 is heavy enough; INFERRED, confirm in the mock).

### 4.5 Tracking

| Token | Today | Proposed | Why |
|---|---|---|---|
| `--ls-label` | .18em | .18em Mac / .14em phone | at 11px, .18em reads sparse (type-colour s4.2) |
| `--ls-ctrl`, `--ls-stat`, `--ls-mono`, `--ls-face` | unchanged | unchanged | five jobs stay five jobs |
| `--ls-tight` | literal `-.005em` on `.t .n` | token, same value | with SF via `-apple-system` the face applies its own tracking table (INFERRED, type-colour); one device check decides whether this goes to 0 |

### 4.6 Sizes, chrome and durations

No new spacing step: `2 4 6 7 8 9 10 12 14 16 24` holds. The chrome numbers
are kit constants, named, not spacing.

| Token | Value | Why |
|---|---|---|
| `--hbtn` | 32px Mac / 44px phone | the header's three controls; 44 is Apple's touch target (SOURCED via accessibility s3) |
| `--hit` | 44px | `min-height` / `min-width` on every phone pointer target: `.col`, `.drow`, `.more`, the back chevron, tab cells; `.pill` gets `padding: 0 8px` so adjacent 44 slops do not overlap (verify-legibility R8) |
| `--tab-h` | 62px | kit (MEASURED) |
| `--shelf-h` | 52px | Apple's web mini player (MEASURED) |
| `--bar-inset` | 21px in standalone, 0 in a Safari tab | kit, Apple's own 26.1.1 change log (MEASURED); the tab-mode value from verify-feasibility F6 |
| `--chrome-gap` | 8px | shelf-to-bar gap; the one unmeasured chrome number, flagged |
| `--ic-tab` / `--ic-bar` | 24px / 22px | glyph boxes, eye-matched to the kit's Semibold 18 / Medium 17 (tab-bar-iconography) |
| `--t-fast` / `--t-base` | 120ms / 220ms | the durations the file already uses (MEASURED: `.18s`, `.22s` at lines 507, 618, 628, 705, 710; `.18` retires into `.22`) |
| `--ease-out` | `cubic-bezier(.32,.72,0,1)` | the file's existing panel curve, tokenised |

Tier boundaries cannot be tokens (custom properties are not allowed in
`@media` conditions). Today's rule at `curate.html` 785 is `@media
(max-width: 1000px)`, which includes 1000 and sets `--lw` 200 (MEASURED,
verifier-laws s3), so "pixel for pixel at >= 1000" was off by one. The
boundaries become `(min-width: 1000px)` for the wide tier and `(max-width:
999.98px)` / `(max-width: 699.98px)` below, in `@media` and in `matchMedia`
alike, and selftest asserts the comparator with the number wherever it
appears.

### 4.7 The five biggest changes, named

1. `--face` to the system stack: the one line that most changes what the page
   looks like; the mono does not change in practice.
2. `--sel-top` on every blue fill, plus the `--on-sel-*` repair: the selected
   row and the Sync button look different, and pass.
3. `--glass-fill` .85, `--glass-rim` .40, `--dim-glass` .75 and the scoping
   rule on glass surfaces: the material, defined once.
4. `--r-lg` 14 and `--r-sheet` 24: two concentric steps on the ladder.
5. The phone `:root` block: eleven type sizes re-declared on Apple's steps, the
   16px input floor, and the chrome constants (`--hit`, `--tab-h`,
   `--shelf-h`, `--bar-inset`).

---

## 5. The eight laws and the layer rule

**Law 1, one slot, one meaning; nothing shifts. Kept and strengthened.** The
tab bar never minimises; `.plabel` is in flow at a fixed 46 on both widths;
`.more` is always visible on touch (today's hover reveal is already a breach
for a finger, MEASURED accessibility 0.5); Sync is one permanent capsule in
the header at every width; the shelf's trailing cell is a reserved slot. One
place the law was nearly bent and is not: the shelf. Today's health strip is
"one slot per dependency, always present, changing state rather than
appearing" (MEASURED, `curate.html` 539-542). Folding five facts into one
slot would have hidden the device fact while a track plays. The shelf
therefore has one meaning (what is happening now) and its idle value is the
link to the device only; the drive, Music and the pending count keep their
own homes (verifier-laws fix 1). Select mode is not a shelf value (judge
graft G5 withdrawn, verifier-laws fix 5).

**Law 2, blue is space, orange is time. Kept, hue and meaning unchanged.**
Glass has no hue of its own (SOURCED, HIG color via glass-principles s8). Blue
fills start at `--sel-top` for legibility. Blue never sits as text on glass
(4.36 over white, fails 4.5), only as a mark: the active tab glyph, the focus
ring. Orange never sits as text on glass (3.29 over white) or on `--raised`
(4.06): on those surfaces it is a dot or the `.eq` bars beside `--ink` text
(judge graft G9, from proposal-artwork-ground s7). The three-hue discipline
holds: the selected pill is ink-alpha, not the kit's grey. Apple Music's red
is not introduced: it sits 30 degrees from the orange and has no job
(MEASURED, type-colour s5.1). The scoping sentence design-structure-first
proposed for this law is not needed and the law is not reworded.

**Law 3, full ink means you could act on it today. Kept.** The library view
with the drive out dims 3,970 of 4,050 rows (98%), which flattens the law
(MEASURED, non-track-surfaces s4.4); the three options are an owner
decision (Part 12), not changed here. `.offline` exists in the code
(`curate.html` 357) and not in `DESIGN.md` Part 7; the doc pass adds it.

**Law 4, facts are plain; decisions get chrome. Kept and read across the
material.** Glass is chrome and goes exactly on the surfaces that hold
decisions (menu, dialog) or hold the primary (Sync's capsule shape). The
shelf's status line is a fact: plain mono on the glass, no pill, no border. A
fact never gets glass of its own. Two corrections the verification forced:
the pushed page's action capsules are never empty (an empty capsule is chrome
with nothing in it) and never `--raised` (whose job is "selected fill"); they
sit in `--panel` and the right one becomes `.inert` carrying its fact ("a
collection") once the verb has been answered (verifier-laws fix 7). And the
page's unreachable fallback, which today invents `{ipod: 'absent', music:
'closed'}` on any fetch failure (MEASURED, `curate.html` 3395), is a
fabricated fact and is replaced (the layer rule, below).

**Law 5, mono is machine truth; the face is human content. Kept; the faces
change to the system's.** One application stated precisely (verifier-laws fix
6): on the phone the pushed page's title is a human-named thing (a collection,
an album, a playlist) and is set in the face; `#midh` today renders the title
and the `L.lib` suffix ("on the iPod", "apple music") in one span (MEASURED,
`curate.html` 1424), so the suffix is split into its own mono `.lib` span.
The roots' names (iPod, Library, Buy) and the tab labels are the machine's
index and stay mono uppercase.

**Law 6, every pane has the same anatomy. Kept.** Phone sheets keep `.plabel`
plus `.pbody` plus `.substat`. Two new containers are strips, not panes: the
**bar** (a row of tabs, no body) and the **shelf** (one slot plus a reserved
control); Part 3 of `DESIGN.md` gains them with `--strip-h` 62 and 52 and
`.seam` = the glass rim. The pushed page's one action is Select / Done in the
strip's right slot, which is also law 8 (the control flips its own label).

**Law 7, nothing is drag-only. Kept and extended at every width.** `.more`
visible on every row on touch; long-press opens the same menu; menu rows Move
up / Move down / Move to top / Move to bottom are added at every width. Undo,
which today is Cmd-Z only with its hint hidden below 900px (MEASURED,
`curate.html` 1044-1047, 794), gets a fixed home: a permanent row in the Data
sheet painted by `paintUndo()` from `UNDOC.next` ("Undo: Sync to iPod, 3
tracks" / "Redo: ..." / `.inert` "Nothing to undo"), present always, a fact
when empty, a flipping label; and `#undoc` becomes clickable on the Mac
(verifier-laws fix 4). No appearing undo capsule (that would breach law 1).
Swipe tiles are not added in this pass.

**Law 8, a control undoes itself. Kept.** The back chevron is the fold
chevron's slot on the phone. The touch menu keeps its two `.inert` fact rows
in their slots at 44px, dimmed, as the law's own sentence requires ("keeps its
slot, the menu must not resize"); touch-interaction 5.3's move of those rows
into the header is dropped, its hiding of the `.dk` key chips kept
(verifier-laws fix 3). The Solid chrome control is a two-segment choice
(Glass | Solid) in the existing `.pill` vocabulary.

**The layer rule** (`bin/layer_census.py`: a client may look things up, never
work them out). The page is at exactly budget on every line today: six
multi-field verdicts, zero filter predicates, two tier comparisons, one price
arithmetic (MEASURED, verifier-laws s2). Two things this direction nearly
added in the page, and does not:

- The shelf's idle headline (reach > iPod state > ready) would have been five
  server facts combined into one verdict in the page, the sentence that must
  then be spelled again in Swift. It is computed on the server: `/api/health`
  gains `headline: {level, text}`; the page overlays only `reach`, the one
  fact only the client can know (phone-liveness s4, s7).
- The unreachable fallback at `curate.html` 3395 becomes `HEALTH = {reach:
  'unreachable', since}` and nothing else; `paintHealth` paints one slot from
  it; the last good values are kept in `LASTGOOD` with a timestamp so "as of
  14:32" is a real time (phone-liveness s7). `reach` and `headline` are
  named as server fields in the API notes so the native app reads the same
  sentence.

Everything else the phone shows is a lookup: "14 of 38" from the job tick,
PLAYING from `#au`, "Showing 80 of 4,050" from `T7.reach`, Preview / Arrange
/ Make it a collection from `view[0]`, `canSeq`, `L.takeover` and `L.pour`,
Move rows from the same `reorder` call `nudge()` makes, the tint spec and its
blue-band chroma clamp from the server (judge grafts G7, G10).

---

## 6. Rows, the pane anatomy and the state vocabulary

Three row shapes, still three.

| Shape | Mac | Phone |
|---|---|---|
| `.row` | 62px, grid `44 / 1fr / auto / auto`, unchanged | 62px; `.src` hides under the existing container query (<= 420) but `.tags .tag` hides only at <= 330, so at 402 the tags would show and squeeze the title to about 100px (MEASURED, verify-feasibility s1 item 13): the phone query hides them; `.more` opacity 1 at 44x44; `touch-action: pan-y`; `draggable=false` under `(pointer: coarse)` |
| `.col` | 35px unchanged | `min-height: var(--hit)`; padding unchanged, the extra is air (about nine fewer rows per screen than 35 would give; 40 is the owner's alternative) |
| `.drow` | about 33px, in a glass `#menu` at `--r-lg` | `min-height: var(--hit)` in the medium-detent sheet; `.dk` chips hidden under `(hover: none)`; the two `.inert` rows stay in place |

The pane anatomy at phone width: `.plabel` (46; leading slot = fold or back;
name; trailing slot = the pane's one action), optional `.filters` (44, one
scrolling row of pills with 44 slop), `.pbody` (the one scroller, with the
159px bottom clearance), optional `.substat` (pinned above the shelf, as the
Buy pane's stat line is today). Sheets add a 60x4 grabber and a visible Close
in the strip's trailing slot. The shelf's PLAYING child (art, name, button) is
a strip child, not a fourth row shape.

State words: every existing word keeps its meaning (`.on .was .sel .marked
.pend .out .fixed .doing .done .err .todo .dim .unowned .inert`). Additions:

| Word | Kind | Meaning |
|---|---|---|
| `.offline` | row state (existing in code, missing from `DESIGN.md` Part 7) | you own this, but the drive holding it is not mounted |
| `.lost` | strip and control state (new; judge graft G3 from design-structure-first s6) | the page cannot see the Mac. Not `.off` (which claims "not here" about a device the page cannot see) and not orange (nothing is happening). Three homes: the shelf's idle rank 1, the disabled Sync's reason, the list's "as of 14:32" header |
| `body.pg` | mode, phone only | a page is on top |
| `html[data-glass="solid"]` | mode | the Solid chrome choice |
| `HEALTH.reach` | server-named axis | `ok` or `unreachable`; the one client-originated fact |

The shelf reuses `.doing` (syncing) and `.playing` (the row's own word) for
its children; idle is the default child. No new row state.

---

## 7. Every current surface, mapped

| Surface | Mac width | Phone width | Material |
|---|---|---|---|
| **Header: brandline, `#q`, `.counts`, `#dosync`, `#gear`** | the band stays flat; `#q` a 400x32 capsule with placeholder "search everything /"; `#dosync` a blue capsule starting at `--sel-top`; `#gear` a circle | `h1` and `.counts` hidden; `#q` a 44 capsule ("Find in All on iPod"), `#gear` 44 with its orange `.busy` dot, `#dosync` 44 trailing with its count ("Sync · 2"), disabled with the `.lost` reason when unreachable; `#q` gets `appearance: none` so iOS draws the capsule (verify-feasibility F5) | flat; shape only |
| **iPod pane `aside.left`** | as today: `.month` groups (collections, smart lists with their counts in `.cnt` and the word "smart" in the section label, "on the iPod", Podcasts 10); `.col.on.pend .cnt` = dot + ink; `.more.hold` reserved on every row | root tab iPod; the same body; `.col` at 44; `+` stays in the strip's action slot; list/album marks move into the gear sheet as two check rows | flat |
| **Source pane `aside.srcpane`** | segments Music \| Drive in the strip (renamed from Library); rows as today; the note "80 of 4,050 readable right now" as the `.substat` | root tab Library; segments in the strip with 44 slop; when the drive is out, a `.month`-styled line under the segments: "Showing 80 of 4,050 · drive offline", `.off` dot, no orange (judge graft G6, from accessory-shelf (c)); rows at `.offline` as today | flat |
| **Mid pane `section.mid`** | as today; `#midh` split into `.name` and a mono `.lib` span; menu rows Move up/down/top/bottom; Select in the strip's action slot (optional at this width) | the pushed page: back chevron, title in the face 17/600, Select / Done; `.filters` as one scrolling row (the funnel is dropped, it existed to fold a wrapping block); first block of `.pbody` = a static header: sharp cover 200 at `--r-lg` (the first member's art, or the album's), mono stat line ("17 tracks · 62 min · on the iPod"), then the two action capsules in `--panel`: Preview (plays the first row through `#au`) and the server's verb (Make it a collection / Arrange / `.inert` "a collection"); it scrolls away with the content, nothing cross-fades (judge graft G2, corrected). Rows 62, flat. Album page: track number in the art slot | flat |
| **Buy pane `aside.right`** | as today | root tab Buy; segments Buy \| Vinyl; cards with `.more` at 44 and capsule action buttons 44 high, 12 apart; the stat foot pinned above the shelf; no swipes this pass | flat |
| **Health strip `#hstrip`** | as today, hard style, opaque; the slot order unchanged; `.lost` as a value in the Mac slot when unreachable, with no iPod, Music or drive lights (they are unknown, not off) | hidden; its facts in the shelf's idle line (iPod state, GB free), the Library banner (drive), the Data sheet (all of them, plus Music and ffmpeg/config warnings) | flat |
| **Sync review `#sp` + `#spscrim`** | opaque, as today, rim and shadow tokenised; bars n/a | large-detent opaque sheet over `--scrim`, `--r-sheet` top corners; summary note and capacity gauge pinned under the strip; rows `role=checkbox` at 44; Cancel apart from Confirm, `padding-bottom` for the inset; cannot be swiped away while running; the bars go Solid beneath it; when the iPod is not mounted it opens and says so, and prints the Disk Mode instructions only then, never when the Mac is unreachable (phone-liveness M11) | opaque |
| **Sheets `#lsheet` (new collection), `#rsheet` (Data)** | as today | large-detent opaque sheets; Data gains three rows: the Glass \| Solid choice, the Undo row, and a Refresh row (standalone has no reload; standalone-home-screen s9); storage note: the Home Screen app has its own localStorage, so folds and filters set in a tab do not carry over (SOURCED, WebKit 181849 via standalone s8) | opaque |
| **Track detail `#tp`** | fixed right as today; the body opaque; the art region at the top holds the sharp cover at `--r-lg` with the kit-27 shadow on a tinted field: the server's 4x3 tint grid rendered as a tiny PNG upscaled by `background-size: cover` with no `filter`, under a `--ground` scrim of .60 plus the per-cover `scrim` scalar (five white sleeves need about .7; 55 of 60 pass at .60, MEASURED artwork-backdrops s2); no text on the field, no well: every line of text starts on the opaque body (judge graft G7, corrected by verifier-laws fix 8). The tint grid's chroma in the 195-235 hue band is clamped on the server to the ground's own .51 so the room is never bluer than the device (graft G10; it changes 2 of 35 covers). The tint spec is cached by image hash beside the cover, generated lazily at 13-20ms (MEASURED, artwork-backdrops s4), and is the same product the firmware backdrop in `research/GLASS-UI.md` s6 reads | large-detent opaque sheet from the shelf's PLAYING value or the menu's Get info; the same art region | opaque; one tinted content region |
| **Menus `#menu`** | glass, `--r-lg`, anchored, `transform-origin` at the anchor; `--dim` and `--faint` scoped; roles per variant: a plain action menu is `role=menu` with `role=menuitem` rows, arrows and Escape-to-anchor; the `.inert` facts are `menuitem` with `aria-disabled`; a menu that holds the `#menunew` field (add to playlist) is `role=dialog aria-modal aria-labelledby` and its anchor declares `aria-haspopup="dialog"` (verify-legibility R6, fix 6) | medium-detent glass sheet 386 wide, `--r-sheet`, 44 rows, `.dk` hidden, destructive last; `openMenu()` writes inline `left/top` today (MEASURED, `curate.html` 2863), so the phone rule carries `!important` or `openMenu()` skips the inline position when the tier matches (verify-feasibility F3); sub-pages keep a 44px back chevron (Back is not Close) | glass |
| **Dialog `#dlg`** | glass box at `--r-lg` over the .72 scrim; everything on it passes because the scrim does the work (ink 15.49, `--dim` 5.67, orange 4.79; MEASURED verify-legibility) except the `--faint` input border, which goes `--glass-rim-hc` | unchanged, `min(420px, 92vw)` fits 402 | glass |
| **Podcast show** | the `Podcasts` `.col` (10) opens a read-only list of `.row`s; an episode is a track (`mediatype 4`); the `.dur` slot carries elapsed / full in orange while playing and would carry a resume position in `--dim` if `bookmark_ms` reached the page (it does not today); `mmss(5648)` prints `94:08`, Apple's own format is `1:34:08` (an owner decision); no Follow, Save, Download or Played verbs: they do not exist here (non-track-surfaces s2) | the same, as a pushed page | flat |
| **Mixes** | not a surface of the page today (the CLI previews them; `curate.html` has none). When built: a `.month` "mixes · preview" group in the iPod pane of `.col` rows via `colRow()` with `.nm.two` (family / era) and the size in `.cnt`; the tile a 2x2 of the first four members' real covers, which the server must name (mockdata carries no member keys; non-track-surfaces s1); plain, no chrome (a mix is an observed computation, not a decision) | the same | flat |
| **Sources and the volume** | the Drive segment; `.away` in the provenance slot; the volume's state in the health strip | the Library banner; a Data sheet row per volume with its name and state word; never orange for a drive that is merely unplugged (non-track-surfaces s4.3) | flat |
| **Buy list** | cards as today, `.substat` foot | see the Buy pane row | flat |
| **Toast** | opaque inverted pill, hidden with `hidden` | the same, above the shelf | opaque |

---

## 8. Accessibility and performance, as gates

Legend: PASS = satisfied by the design as written; GATE = asserted by a
script before merge; DEVICE = a pass on the iPhone 17 Pro that no script can
replace; OWNER = a judgement in the visual review.

### 8.1 Accessibility (findings/accessibility.md s7, with the verifiers' corrections)

| # | Check | Status |
|---|---|---|
| A1 | glass degrades to solid, bordered chrome under `prefers-contrast: more` | PASS by the token twins; the mock draws the twin frames |
| A2 | a visible in-page Solid chrome control, stored in localStorage in try/catch | PASS (Data sheet, Glass \| Solid) |
| A3 | every transition has a reduce-motion rule | GATE: `t_reduced_motion_coverage` (exists, pagetest 915-939) |
| A4 | glass has its own 1px edge always, as a token | PASS (`--glass-rim` .40 >= 3:1 on ground and over white glass) |
| A5 | `@supports not (backdrop-filter)` falls back to the opaque twin | PASS |
| B1 | the existing 20 pagetest checks stay green | GATE |
| B2 | tab bar = `<nav aria-label>` > `role=tablist` > three `role=tab` with `aria-selected` and `aria-controls`, roles present in markup, labels as text | PASS; GATE: pagetest sees the roles only if they are in markup, not set by a `matchMedia` callback |
| B3 | the active tab changes by toggling attributes, never re-rendering the list | PASS |
| B4 | the shelf is `role=region aria-label="Now"`, each value a real named button ("Open sync review, 14 of 38") | PASS |
| B5 | sheets and panels are `role=dialog aria-modal aria-labelledby`, `inert` on header, `#work`, shelf and bar while open and off on every close path (Escape, scrim tap, Close, `popstate`), focus in on open and back on close, a visible Close | PASS; GATE G3 |
| B6 | honest popup roles per menu variant | PASS; GATE G3 checks the pairing per anchor |
| B7 | the three row states join the accessible name, not only `title` | GATE (pagetest asserts it) |
| B8 | `#live` stays the one announcer | PASS |
| B9 | nothing that must stay reachable is `display: none`; inactive tabpanels are `hidden` on purpose | PASS |
| B10 | one blue control, Sync, first in the header's tab order, 44x44 on the phone without scrolling | PASS (G1) |
| C1 | every text token on every glass surface >= 4.5 over `#fff` at the declared fill | GATE G2, run over the pairs actually declared inside each glass surface, not only the tokens named here |
| C2 | `--dim` only on opaque grounds | PASS by the scoping rule; GATE G2 |
| C3 | text on the selection fill >= 4.5 at its real position | PASS at centre (4.58 / 5.6) and subtitle (4.88); the top edge (3.84) holds no text; GATE G2 samples 0 / 50 / 68 / 100% |
| C4 | no custom property references itself | GATE G1 |
| C5 | orange text only on `--ground` / `--seam`; dot + ink elsewhere | PASS |
| C6 | blue never the only cue of the active tab | PASS (pill + fill + weight + `aria-selected`); GATE G2 composites the glyph over `--raised` over the fill over white and asserts >= 3 |
| C7 | non-text >= 3:1: rim, input borders on glass, focus ring, tab glyphs | PASS (rim 3.14 worst; focus ring 6.94 on ground, 4.36 on glass over white) |
| C8 | the mock shows the chrome over the brightest and darkest real covers in both modes with ratios printed | OWNER + GATE (the covers script) |
| C9 | text never sits on cover art | PASS (no text on the `#tp` field) |
| C10 | every state has a second channel beside colour | PASS (law 3 already demands it) |
| D1 | every pointer target >= 44 on the phone | GATE G4 (touch-target lint under the phone query) |
| D2 | >= 8px between adjacent hit areas, or each >= 44 | PASS (`.pill` padding; tab cells 117) |
| D3 | `.more` visible without hover on touch | PASS |
| D4 | inputs >= 16px on the phone; no `maximum-scale` | PASS (`--fs-field` 16) |
| D5 | text floor 11px for anything the person must read; the layout survives 200% zoom and 320px without horizontal scroll or clipping Sync | PASS by inset-drawn bars and ellipsised labels; the mock draws a 320 frame; at 200% the labels truncate, the names do not |
| D6 | safe areas respected | PASS (the bars sit inside the inset by design, `viewport-fit=cover` set) |
| E1-E5 | one tab stop per composite, DOM order = visual order, the existing list keys, the focus ring, dialog focus, focus surviving redraws | PASS / GATE B1 |
| E6 | `aria-activedescendant` kept only if VoiceOver announces the active row on the device | DEVICE |
| F1-F5 | VoiceOver order and names, row states spoken, Increase Contrast and Reduce Motion on, 200% text, desktop keyboard-only loop | DEVICE |
| G1-G5 | the new gates: self-reference check; contrast table from tokens over `#fff` and `#000` per glass surface; haspopup/menu and dialog/aria-modal pairing and `inert` toggling; touch-target lint; the existing reduce-motion gate and census | GATE, none needs a framework |

### 8.2 Performance budget (findings/web-feasibility.md s4, verify-feasibility s2)

| | Mac width | Phone width |
|---|---|---|
| Persistent live blurs | 0 | 2: tab bar 360x62 = 22,320 px plus shelf 360x52 = 18,720 px = 41,040 px, 11.7% of the 402x874 viewport (MEASURED arithmetic) |
| Live blurs with something open | 1 (menu <= 320x457 = 146k px; dialog 420 wide under its scrim) | 1 (the medium sheet 386x451 = 174k px, or the dialog); the two bars go Solid beneath it |
| Ceiling at any moment | 1 | 2 (the toast is never glass) |
| Blur radius | 16px, constant | 16px, constant |
| What changes behind the glass per frame | nothing: a flat band or a scrim | the scrolling list under the two bars, 41k px; 2.2x the area of Apple's own shipped phone-web capsule at the same radius (MEASURED, web-player-phone-layout s1) |
| `will-change` | none on glass | none on glass |
| Rows | never glass; `content-visibility: auto` with `contain-intrinsic-size: auto 62px` on `.row` only, only in the library view, never on an ancestor of a fixed or glass element (it creates a containing block, SOURCED via web-feasibility s2; Safari 18+; WebKit 281570 does not apply, rows carry no SVG text) | same |
| Measured so far | no measurable cost at any option on the M3 Pro (MEASURED, desktop-glass s6); Chrome 154 held 16.7ms p95 with six blur panels over 650 rows (MEASURED, web-feasibility s4) | NOT measured: no iPhone in any session. WebKit renders `backdrop-filter` as a `CABackdropLayer`, the same CoreAnimation primitive the system materials use (SOURCED, PlatformCALayerCocoa.mm via verify-feasibility s2; INFERRED that this makes the cost comparable) |
| Gate | pagetest and selftest green; screenshot diff at 1512 and 1024 | DEVICE, before any phone CSS lands: scroll the 650 and 4,000 row lists in a Safari tab and standalone with both bars live; open the medium sheet; confirm the blur holds through motion rows 1-3; read Safari's bottom toolbar tint on the current page before and after the toast fix; lock the phone for 60s mid-sync and record whether `visibilitychange` fires, the EventSource `readyState`, and whether the next poll succeeds (phone-liveness s10). 60fps is the right bar: iPhone Safari renders near 60Hz by default (SOURCED, search summaries via verify-feasibility) |
| Optional | glass off when the window loses focus (Apple's own web does; MEASURED web-player s3) | glass off while `document.hidden` |

---

## 9. Failure modes designed against

From findings/failure-modes.md G1-G15, each with its mitigation here.

| # | Failure | Mitigation in this design |
|---|---|---|
| G1 | text over busy or bright content is illegible; a translucent surface has no fixed contrast | fill .85 is the floor computed against pure white, not the typical cover; `--dim-glass` on glass; nothing bright is ever full-bleed under glass; gate G2 |
| G2 | a washed-out bright bar on a bright page (Tahoe Music) | dark-only; the fill is derived from the ground; every glass surface draws its own 1px rim at >= 3:1 |
| G3 | the bar hides content and competes for attention | 159px bottom clearance so the last row is never trapped; no scroll-edge slab; the shelf carries one fact |
| G4 | fussy edges, shimmer, bubble animations | one static rim; no specular; no springs; blur never animates; Reduce Motion honoured by gate |
| G5 | glass on glass, glass in the content layer, mixed variants | rows and panes flat; Regular only; the bars go Solid while a sheet is open; the toast is opaque |
| G6 | tint everywhere dilutes meaning | tint only Sync; blue and orange stay marks on glass; no new hue in `:root` |
| G7 | the active or selected state is lost on glass | the active tab is pill + filled glyph + weight; selection stays an opaque fill on flat rows and starts at `--sel-top` |
| G8 | people cannot get a solid UI; Safari cannot read Reduce Transparency | the Glass \| Solid control in the Data sheet; `prefers-contrast: more` auto-solid; `prefers-reduced-transparency` as an additive extra |
| G9 | accessibility modes break layouts | the Solid state is a token swap, designed as a first-class twin and drawn in the mock; roles and roving focus unchanged (pagetest) |
| G10 | heat and dropped frames from live blur over scrolling lists | no glass on rows; two live blurs at rest, 41k px; the device gate before code lands |
| G11 | layout shifts and collapse unpredictability | nothing minimises, nothing leaps; the shelf's slot is reserved with a true idle value; the header is in flow |
| G12 | controls too small or crowded in floating capsules | `--hit` 44 everywhere; tab cells 117x54; `.pill` side padding; adjacent slops 8px apart |
| G13 | artwork shrunk, space wasted around the floating bar | the one art-backed region is the track sheet, where the cover is sharp and large and the field carries no text |
| G14 | search hidden behind navigation | `#q` stays persistent in the header at every width |
| G15 | inset sidebars waste a strip of window background | panes run to the edge on the Mac; no sidebar on the phone |

Two failures the research added beyond that list: the empty accessory
container (Apple's 26.1 regression; the shelf always carries a true fact) and
the fabricated fallback state (the page today paints "iPod absent, Music
closed" whenever the Mac is asleep; `reach` becomes its own axis).

---

## 10. What the verification changed, and what the losing proposals gave

Three adversarial verifiers read the winning proposal with the judge's grafts
and each found it survived with required fixes. Every fix is in the direction
above; this is the record of what was refuted and what moved.

**Legibility and accessibility** (findings/verify-legibility.md) refuted:
that `--dim` is never used on glass (nine `--dim` rules, two `--faint` text
rules and one `opacity: .5` row already sit inside `#menu` and `#dlgbox`;
the Mac menu has no scrim and would have failed its own gate), so the dim and
faint tokens are now scoped per glass surface and no glass row is dimmed by
opacity; that the active glyph passes at 4.36 (it sits on the pill, not bare
glass; on the grafted ink .16 pill it measures 2.70), so the pill is `--raised`
at .09 with the gate measuring glyph over pill over fill over white; that a
.30 rim meets the checklist's own 3:1 (it is 2.70 on the ground), so the rim
is .40; that stacked shelf buttons hidden by opacity are valid (they are
focusable and `aria-hidden`), so inactive values are `inert` then `hidden`;
that "same DOM, one pane at a time" leaves the tree clean (translated-off
listboxes stay in VoiceOver's order), so inactive panes are `hidden` and the
pushed-away root `inert`; that `#menu` can be `role=menu` for every variant
(one holds an `<input>`), so roles follow the variant; that fixed 360px
capsules reflow (they overflow 320 and 200% zoom), so the bars are drawn by
inset; and that 44px slop on adjacent `.pill`s is safe (they overlap), so the
pills gain side padding. It also recommended keeping the toast opaque, which
is taken.

**Feasibility in one file** (findings/verify-feasibility-one-file.md)
refuted: "toast by opacity, as today" (Safari 26 samples `opacity: 0` fixed
elements; the bug exists on the page now), so the toast is hidden with
`hidden`; "glass on `::before`" as a complete dodge (the host must carry no
background and no backdrop-filter of its own), so the recipe says so; "tags
already hide at 402" (only `.src` does), so the phone query hides them; "the
phone menu sheet by CSS alone" (`openMenu()` writes inline `left/top`), so a
guarded tier branch exists; "never stack glass on glass" against the
geometry (the sheet sat over the two bars), so the bars go Solid while
anything is open; "ceiling 3" (a glass toast over the sheet made 4), so the
ceiling is 2; "a second `:root` block is census-clean" (the census skips only
the first block and is blind to eight `rgba` literals), so the census learns
to skip every `:root` block and gains the patterns; and "pagetest will see
the phone layer" (the sandbox has no `matchMedia`, `history`,
`window.addEventListener`, `IntersectionObserver` or `document.hidden`; an
unguarded call kills all twenty checks), so every new API is feature-detected
at the call site with the Mac behaviour as the fallback.

**The eight laws and the layer rule** (findings/verifier-laws-and-layer-rule.md)
refuted: the five-rank shelf (law 1: the device fact disappeared while a track
played), so the shelf has one meaning and three values; Sync in both the
header and the shelf (the handed text contradicted itself), so Sync is in the
header only and the shelf's trailing cell is a reserved slot; the idle
headline computed in the page and the fabricated unreachable fallback (the
layer rule and law 4), so the headline is a server field and the fallback
paints only `reach`; moving the `.inert` rows out of the touch menu (law 8's
own sentence), so they stay in their slots; undo with no phone control (one
of six server operations), so the Data sheet carries a permanent Undo row;
Select mode as a shelf value (law 1 and law 6; the count and the bulk verbs
already exist), so it is the pushed page's one action; the face on the whole
`#midh` span (law 5: the `L.lib` suffix is machine truth), so the suffix is
split; empty `--raised` action capsules (law 4), so they are `--panel` and
never empty; text in wells on the art region (law 4), so no text sits on the
field; the shelf art radius stated two ways, so it is 28 at `--r-xs` with a
precedence sentence; one word for two slots (LIBRARY), so the segment is
Drive; and the tier comparator, so it is `min-width: 1000px`.

**What design-structure-first contributed** (the runner-up, 37/50 to the
winner's 43; judge s1): Sync in the header on both widths with the HIG
argument; the pushed page's static header block and action slot; the `.lost`
state word with its three homes; the Library offline banner shape; the role
wording for the tab bar, shelf, Back and menus; the list of server fields the
phone's honesty depends on (`health.job`, `health.build`, a 409 on a
concurrent sync, `reach` as its own axis). What it proposed and the direction
does not take: the large title and its collapse, the Search tab, a scoping
sentence on law 2, push parallax, springs, a View Transition on the cover,
swipe tiles, drag-to-detent sheets, four live blurs on a pushed page.

**What proposal-artwork-ground contributed** (30/50): the track sheet as the
one art-backed surface, with its measured spec (scrim .60 plus the per-cover
scalar, the 4x3 tint grid upscaled with no filter, the kit-27 shadow on the
sharp cover); `artground/measure.py` as the contrast gate for that region;
the orange dot + ink count on raised rows; the server-side blue-band chroma
clamp; the rule that the room, if it ever changes colour, changes after the
list has changed and never before. What it proposed and the direction does
not take: the page-wide art ground, the `--dim` .55 to .70 re-pitch, wells on
the header, footer and playing row, the three-stop dial, the kit radii 20 /
34 as the default.

---

## 11. Implementation phases and gates

Each phase lands only when its gates pass; the owner's visual review is a
gate, not a courtesy.

**Phase 0, repairs and the census.** Set `--on-sel-dim/-line/-hi` to their
values; tokenise the eight `rgba` literals and `-.005em`; `.tag.skip` on the
selected row; change the tier rule at `curate.html` 785 to `min-width:
1000px` / `max-width: 999.98px`; replace the unreachable fallback at 3395
with `{reach, since}` and `LASTGOOD`; extend the census (skip every `:root`
block; `rgba(` outside `:root`; `letter-spacing: -?N em`; "no custom property
references itself"; the "glass" class); add the comparator assertion. Gates:
token census clean, pagetest 20/20, layer census at budget, no visible change
except the selected row (say so in the commit).

**Phase 1, Mac width.** `--face`, `--mono`; capsule header controls;
`--sel-top` on the blue fills; `--r-lg`; the glass recipe on `#menu` and
`#dlgbox` with the scoped dim tokens, `--glass-rim` .40 and the opaque twins
(`prefers-contrast: more`, `[data-glass="solid"]`, `@supports not`); the
toast hidden with `hidden`; menu roles per variant; `.col.on.pend` dot + ink;
Move rows; clickable `#undoc`; the segment renamed Drive; `#midh` split;
`.offline` added to `DESIGN.md` Part 7 and the bar and shelf added to Part 3.
Gates: token census, pagetest with G1-G3, layer census, a before/after
screenshot diff at 1512 and 1024 (SF and Helvetica Neue have different
advance widths; nowrap labels in `#stabs`, `.counts`, `.substat` may ellipsise
differently), and the owner's visual review of the four-pane page with one
menu open over the blue row and over cover thumbs, which is where .85 glass
visibly reads (proposal-least-movement risk 1).

**Phase 2, server fields the phone needs.** `/api/health` gains `reach`-aware
`headline: {level, text}`, `job: {id, name, state, seconds}` for a running
sync, `build` (hash or mtime of `curate.html`); a 409 on a second concurrent
sync; `id:` on pushed events. Gates: layer census (no new rule in the page),
every operation keeps its cli verb, the existing pagetest health checks.

**Phase 3, the phone layer.** Precondition, before any CSS lands: the
ten-minute on-device pass in Part 8.2 on a throwaway test page. Then: the
phone `:root` block; the four meta tags and the touch-icon route; the tab bar
and shelf as fixed siblings at the end of `<body>` with roles in markup;
push/pop with feature-detected `history` and `matchMedia`; the re-attach
sequence on `visibilitychange`, `pageshow` and `online` (phone-liveness s8);
sheets with `inert`; the medium-detent menu sheet; the Data sheet's Glass |
Solid, Undo and Refresh rows; the Library banner; the three liveness states;
`.pbody` clearance; `--bar-inset` under `display-mode: standalone`. Gates:
pagetest 20/20 under the unchanged sandbox plus G2-G4, token census, layer
census, the VoiceOver device pass F1-F5, and the owner's visual review of the
ten phone screens in Part 3.2 plus the Solid twins and the 320 frame.

**Phase 4, the art region.** The tint spec and clamp on the server; the `#tp`
art region. Gates: `artground/measure.py` over every cached tint at the
sheet's scrim asserting `--ink` >= 4.5 on the p99 pixel (only an orange mark
may sit on the field, and only if the gate passes for it); the owner sees it
once.

**Deliberately deferred, with the reason:** the large title and its collapse
(the owner's condition); tab-bar minimise and the inline shelf (optional per
the HIG; law 1; NN/g's complaint); swipe actions on rows (motion on a
frequent interaction, SOURCED HIG motion via glass-motion s2; the spec is
touch-interaction 5.2 when wanted); draggable detents and an Arrange-mode
handle (the Move rows give the function); a per-album backdrop under chrome
or panes (needs a desaturation rule and the owner's eye); an inset sidebar
(walked back by Apple); scroll-edge effects; a light appearance (type-colour
s6 has the table; it doubles every contrast check and the ground is a
photograph of a dark device); Apple Music's red; lensing, pointer-tracked
specular, View Transitions, springs; a Search tab, next/previous, a queue; a
mixes surface in the page (needs member covers from the server); icons beyond
the 18-symbol sprite; a manifest or service worker (plain HTTP over the LAN);
the middle tier's mock (no device known); haptics (not reachable from a web
page on iOS 26.5+, SOURCED via touch-interaction s3.4).

---

## 12. Open decisions for the owner

1. **Which iOS, and is there an iPad?** Settings > General > About. The mock
   draws iOS 27 (medium sheet 386x451); on 26.x it is 390x380 and the labels
   are Medium. No iPad is in evidence after 2025.
2. **Sync in the header (as drawn) or in the shelf.** The HIG puts a primary
   action in the toolbar; the mock shows both once.
3. **Radii: 14 / 24 derived from the page's own padding (as drawn), or
   Apple's 20 / 34.** The kit values need different inner padding or a
   10px inner radius.
4. **The selected tab pill: `--raised` ink-alpha (as drawn; three hues, about
   3.3:1 for the glyph) or the kit's grey at 32% (3.26:1, a fourth hue).**
5. **Tab wording: Library with the segment renamed Drive (as drawn), or the
   tab named Source and the segments left alone.**
6. **The 98%-offline library view**: per-row dimming as today; or state it
   once at the pane and render rows at full ink (a law 3 wording change); or
   show only the readable 80 by default with the "needs a drive" chip for the
   rest (Apple's Downloaded filter).
7. **Glass on by default (as drawn, because every text token on glass passes
   at the .85 floor) or Solid by default.**
8. **`.col` on the phone at 44 (Apple's target, about nine fewer rows per
   screen) or 40 (above Apple's 28 floor).**
9. **`--glass-sat` 180% or 220%**: one token; it decides whether blue covers
   under the bars rhyme with the selection blue. Judge on the device.
10. **Status-bar style `black` (as drawn) or `default` + theme-color**, decided
    before the icon is added: iOS caches it at install time.
11. **Episode durations as `1:34:08`** (Apple's own format) or `94:08` as
    today; and whether `bookmark_ms` reaches the page so a half-played
    episode shows its position.
12. **The mix tile**: a 2x2 of the members' real covers (needs the server to
    name them) or no tile until it does.

---

## 13. SOURCES

Repo (MEASURED, read-only for this document): `publish/DESIGN.md`;
`src/saltpod/curate.html` (`:root` 17-76, header 95-144, grid and folds
146-240, rows 242-423, panes 425-495, sheets 497-529, footer 531-572, dialog
576-620, `#tp` 622-692, `#sp` 694-783, media rules 785-794, markup 817-925;
the lines cited inline: 42-44, 357, 364-366, 429, 467, 539-542, 616-619,
764, 785, 794, 845, 850, 1044-1047, 1424, 2863, 2980, 3029-3091, 3395);
`bin/pagetest.py` (sandbox 340-432, `t_reduced_motion_coverage` 915-940);
`bin/selftest.py` (`t_token_census` 371-386); `bin/layer_census.py` (run:
6/6, 0/0, 2/2, 1/1); `research/NATIVE-APP-SPEC.md` phase 4;
`research/GLASS-UI.md` s6; `research/IPAD.md`.

The research set, in the session scratchpad (`glass/findings/`): brief.md;
iphone-music, ipad-music, glass-principles, failure-modes, web-feasibility,
web-player, web-player-phone-layout, type-colour, accessibility,
touch-interaction, artwork-backdrops, phone-information-architecture,
accessory-shelf-occupancy, non-track-surfaces, design-kit-measurements,
ios27-music-delta, desktop-glass-surfaces, tab-bar-iconography,
standalone-home-screen-mode, owner-device-frame,
phone-liveness-and-unreachable-states, glass-motion-on-the-web, critic-1/2/3;
the three proposals (proposal-least-movement, design-structure-first,
proposal-artwork-ground); judge.md; verify-legibility.md,
verify-feasibility-one-file.md, verifier-laws-and-layer-rule.md. Also
current.jpg, mockdata.json, measured.txt, the 60 covers, the Apple kits and
web-player CSS captured there, and the scripts (`desk/contrast.py`,
`artground/measure*.py`, `verify-legibility/contrast.py`, `covers.py`).

Apple, via those findings (fetched there; none re-fetched for this document):
- WWDC25 219 Meet Liquid Glass: https://developer.apple.com/videos/play/wwdc2025/219/
- WWDC25 356 Get to know the new design system: https://developer.apple.com/videos/play/wwdc2025/356/
- WWDC25 284 Build a UIKit app with the new design: https://developer.apple.com/videos/play/wwdc2025/284/
- WWDC25 323, 208, 310; WWDC26 289 Modernize your AppKit app: https://developer.apple.com/videos/play/wwdc2026/289/
- HIG DocC JSON: tab-bars, toolbars, search-fields, materials, color, accessibility, motion, scroll-views, sidebars, split-views, sheets, menus, context-menus, typography, under https://developer.apple.com/tutorials/data/design/human-interface-guidelines/
- Adopting Liquid Glass: https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass
- Apple newsroom, 9 Jun 2025: https://www.apple.com/newsroom/2025/06/apple-introduces-a-delightful-and-elegant-new-software-design/
- Apple iOS 26 UI kit (Sketch): https://sketch.com/s/f63aa308-1f82-498c-8019-530f3b846db9 ; iOS 27 UI kit: https://www.sketch.com/s/04c24d8b-38fb-4afb-8836-36617e022f02 ; Design Resources: https://developer.apple.com/design/resources/
- music.apple.com production CSS and JS (captured): https://music.apple.com/assets/index~ed2e8b4c1d.css
- Apple Support: music player controls, queue, search, playlists, pins, podcasts (URLs in iphone-music and non-track-surfaces)
- Apple developer forums: accessory container 26.1 https://developer.apple.com/forums/thread/803428 ; SF Symbols licence https://developer.apple.com/forums/thread/739523
- Safari HTML reference meta tags (archived): https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/SafariHTMLRef/Articles/MetaTags.html

Standards and browsers:
- WCAG 2.2 Understanding: non-text contrast https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html ; target size https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html
- ARIA APG tabs, listbox, modal dialog: https://www.w3.org/WAI/ARIA/apg/patterns/
- MDN: backdrop-filter, inert, prefers-contrast, prefers-reduced-transparency, @starting-style, Media Session, display-mode
- CSSWG filter-effects-2 (backdrop root): https://drafts.csswg.org/filter-effects-2/
- caniuse prefers-reduced-transparency: https://caniuse.com/mdn-css_at-rules_media_prefers-reduced-transparency ; Chrome's guidance: https://developer.chrome.com/blog/css-prefers-reduced-transparency
- WebKit: Safari 26.0 and 27.0 features https://webkit.org/blog/17333/webkit-features-in-safari-26-0/ , https://webkit.org/blog/18325/webkit-features-for-safari-27-0/ ; system font https://webkit.org/blog/3709/using-the-system-font-in-web-content/ ; bugs 245510, 158807/158483, 231724, 198277, 261858, 297779, 301108; PlatformCALayerCocoa.mm https://raw.githubusercontent.com/WebKit/WebKit/main/Source/WebCore/platform/graphics/ca/cocoa/PlatformCALayerCocoa.mm
- Safari 26 toolbar tinting from fixed elements: https://1ar.io/updates/safari-26-liquid-glass-web/ ; https://benfrain.com/ios26-safari-theme-color-tab-tinting-with-fixed-position-elements/
- Safari ancestor-fade scroll drop: https://dev.to/esatturan/safari-dropped-my-scroll-because-of-a-css-fade-on-an-ancestor-51a5
- TetraLogical VoiceOver support tables: https://tetralogical.github.io/screen-reader-HTML-support/VO-ios.html ; Vispero on aria-modal: https://vispero.com/resources/the-current-state-of-modal-dialog-accessibility/
- SSE spec and mobile suspension: https://html.spec.whatwg.org/multipage/server-sent-events.html ; https://www.server-sent-events.com/frontend-consumption-client-patterns/mobile-background-tab-handling/resuming-sse-streams-after-mobile-tab-suspension/ ; bfcache https://web.dev/articles/bfcache
- Practitioner glass budget (one blog, heuristic): https://www.buildmvpfast.com/blog/liquid-glass-css-backdrop-filter-recipes-2026 ; tiny-image upscale: https://www.mux.com/blog/blurry-image-placeholders-on-the-web
- Phosphor Icons (MIT): https://unpkg.com/@phosphor-icons/core@2.1.1/

Critiques and press:
- NN/g, Liquid Glass Is Cracked: https://www.nngroup.com/articles/liquid-glass/
- mjtsai roundup: https://mjtsai.com/blog/2025/12/29/liquid-glass-disbelief/ ; hicks.design Music in Tahoe: https://hicks.design/journal/apple-music-in-tahoe ; pimpmytype: https://pimpmytype.com/liquid-glass/
- MacStories iOS 26 review p15 and iOS 27 review p2, p10: https://www.macstories.net/stories/ios-and-ipados-27-review/2/
- 9to5Mac: iOS 26.1 mini player https://9to5mac.com/2025/11/04/ios-26-1-gave-apple-music-convenient-new-trick/ ; 26.4 album pages https://9to5mac.com/2026/03/25/apple-music-in-ios-26-4-has-new-design-for-albums-playlists-and-more/ ; iOS 27 Music https://9to5mac.com/2026/06/19/apple-music-in-ios-27-introduces-new-design-changes-in-two-key-areas/
- MacRumors: iOS 27 Liquid Glass changes https://www.macrumors.com/2026/06/10/how-liquid-glass-is-changing-in-ios-27/ ; 26.1 battery test https://www.macrumors.com/2025/10/24/ios-26-1-liquid-glass-battery-test/
- BGR, 26.4 beta critique: https://www.bgr.com/2108826/apple-music-update-users-torn-feb-2026/
- TechCrunch, 26.1 Tinted option: https://techcrunch.com/2025/10/20/apple-will-let-users-roll-back-the-liquid-glass-look-with-new-tinted-option/
- piunikaweb, web player beta: https://piunikaweb.com/2026/04/30/apple-music-web-player-redesign-beta/ ; 9to5Google, Android 7.0: https://9to5google.com/2026/09/30/apple-music-7-0-redesign-liquid-glass/
- donnywals, iOS 26 tab bars: https://www.donnywals.com/exploring-tab-bars-on-ios-26-with-liquid-glass/
- Device sizes: https://useyourloaf.com/blog/iphone-17-screen-sizes/
- Now Playing gradient reverse-engineering: https://www.aadishv.dev/music
