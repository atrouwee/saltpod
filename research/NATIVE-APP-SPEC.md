# The macOS app, specified against what the web version actually is

**Status: measured, except the section marked PROPOSED.** Every capability
claim below was compiled on this machine on 1 October 2026 with Xcode 27 /
Swift 6.4. Every figure about the web version was counted from
`src/saltpod/curate.html`.

This replaces the 29 September survey in `NATIVE-APP.md`, which asked
"could we build this". The answer changed shape in between, because the web
version stopped being a program with a server attached and became **a client
of a contract**.

## What changed, and why it matters more than the toolchain

On 29 September the native app would have been a reimplementation. Three
things since mean it is now a second client of something that already
exists:

1. **The layer rule.** `CONTRIBUTING` now states it: *a client may look
   things up; it may not work them out.* `/api/tracks` answers the
   questions — `lists`, `album_key`, `held`, `vinyl_owned`, `totals` —
   instead of shipping 37 raw facts for each client to reason over.
   `bin/layer_census.py` holds the line.
2. **The design system is written down.** Eight laws, nine colour tokens,
   four radii, five tracking values, eleven type sizes, three row shapes,
   twelve state words — all in `DESIGN.md`, all enforced by a census.
   A native client has a specification to match, not a screenshot.
3. **The terminal already does it.** The first hardware sync ran entirely
   from the CLI because the browser dropped out mid-test. That was not a
   workaround; it was the parity rule paying out.

## Measured: what the platform gives that the web version built by hand

Compiled and run headless, no Xcode project, no `.xcodeproj`:

```
Table + selection + sortOrder      : compiles
inspector() right-hand panel       : compiles
contextMenu(forSelectionType:)     : compiles
keyboardShortcut on a toolbar item : compiles
UndoManager as a proxy             : compiles
```

Against what that cost in the browser:

| | web version | native |
|---|---|---|
| multi-select — ranges, cmd-toggle, a set of keys | **61 references** | `Table(selection:)` |
| scroll and selection memory | **23 references** | the table keeps it |
| menu placement, flipping at the viewport edge | **47 references** | `.contextMenu` |
| drag and drop plumbing | **36 references** | drag modifiers |
| keyboard navigation | 7 references | free |
| panel slide and scrim | **33 references** | `.inspector()` |
| **column sort** | never built | `sortOrder:` — free |

`.contextMenu(forSelectionType:)` is the one worth calling out: it hands
the menu the **current selection**, which is precisely the behaviour that
took the most care to get right in the page — the menu acting on the marked
set, a tick meaning *all of them*, the cursor-outside-the-selection case.

**Column sort is in the gap analysis and has never been built.** The native
client gets it for nothing.

## The contract, as it stands today

**23 HTTP endpoints, 13 CLI verbs.** The gap is real and worth closing
before any Swift is written, because the five endpoints without a verb are
exactly the newest ones:

| endpoint | CLI verb |
|---|---|
| `tracks` `plan` `playlists` `health` `device` `library` `local` `discogs` `art` `audio` `job` `history` `events` `looking` `music` `peek` `action` `decide` | covered or internal |
| **`tags`** | — |
| **`track`** | — |
| **`undo`** | — |
| **`discard`** | — |
| **`recover`** | — |

Closing it is not ceremony. A verb is a second caller, and a second caller
is what proves the endpoint is really a boundary rather than a function the
page happens to reach over HTTP.

## PROPOSED — the shape of the first iteration

**Not a port. A second client.** It talks to the same local server over the
same HTTP, which means:

- no format code in Swift — `itunesdb`, `hash58`, `tags`, `apply` stay put,
  and they are the proven, byte-identical-round-trip part
- no rules in Swift — the layer census already forbids them in the page and
  the same rule applies here
- the two clients cannot disagree about what a list contains, because
  neither of them decides

### Phase 1 — read only
The four panes, `Table` for the centre, the health strip. Proves the
contract, the design tokens and the row shapes. Nothing can go wrong with
the device because nothing writes.

### Phase 2 — decisions
The row menu on a selection, the tier toggles, collections. All of it is
`POST /api/decide`, which already exists and already takes a key array.
`UndoManager` proxies `/api/undo` — **the stack stays on the server**,
because two undo stacks would be two truths.

### Phase 3 — the panels
Sync review and track detail as `.inspector()`. The sync panel's "one list,
twice" behaviour — the rows you approve are the rows that tick — maps
directly onto a list whose row state changes in place.

### Phase 4 — glass
Only here. `glassEffect`, `GlassEffectContainer`, `glassEffectID` and
`ToolbarSpacer` all compile (verified 29 September). Last because the UI
has to stop moving first, which was AJ's own condition.

## What I can and cannot verify alone

**Can:** build, bundle, sign, launch and screenshot without an Xcode UI.
`ImageRenderer` renders a SwiftUI view to PNG in-process, so layout, type,
spacing, table structure and control state are all checkable from here.

**Cannot:** Liquid Glass. It is a compositor effect and does not survive an
offscreen render. The same split as the web version — structure I can
iterate alone, material needs eyes on a real window.

## Would Swift be faster? Measured: no.

Profiled `plan()` against the real device and the real drive:

```
plan()                     2,677 ms
  _metadata_drift          2,543 ms
    BufferedReader.read    2,513 ms   <- waiting on the T7 over USB
  everything else            164 ms
```

**94% of it is waiting on a disk.** Swift waits exactly as long. The
binary work Swift would actually speed up is the part that is already
fast:

| | |
|---|---|
| parse the 1.1 MB iTunesDB | **5.8 ms** |
| re-serialise it | **5.4 ms** |
| hash58 over the whole file | **0.4 ms** |
| read the typed view | 7.8 ms |
| load 1.9 MB of state JSON | 6.3 ms |

There is no CPU-bound work here to win. `hashlib` and `json` are C
already, the files are megabytes rather than gigabytes, and nothing in
this project vectorises — so Accelerate, SIMD and Metal have nothing to
do. **Native hardware buys nothing a rewrite could collect.**

### What did buy something: the gate, finally wired

A `getmtime` is **0.001 ms** against a read's **3.7 ms** — the gate is
three thousand times cheaper than the read it avoids. Caching tags against
the file's mtime:

```
plan() cold   2,545 ms
plan() warm      54 ms      47x
```

And it still notices: editing one file's album put exactly one retag back
in the plan, in 62 ms, because only that file was re-read.

**So the performance argument for a rewrite is dead.** The argument that
survives is packaging — an interpreter inside an App Store bundle — and
that is a different argument, which the section below makes on its own
terms. Decide it there, not on speed.

### Headless

The server already is: `saltpod curate --no-open` binds a port and serves.
Nothing about it needs a window, which is what let the whole first
hardware sync run from the terminal.

Three ways to keep it that way, in order of how much they ask of the user:

| | |
|---|---|
| the app spawns it as a child and kills it on quit | nothing to install, dies with the app |
| a `LaunchAgent` plist in `~/Library/LaunchAgents` | survives reboots, runs with no app open, standard macOS |
| the user runs it in a terminal | what happens today; fine for one person |

A Swift server would be a single 68 KB binary, which makes the LaunchAgent
route trivial. A Python one needs the interpreter resolved first — the
only place the language choice actually touches this.

## Shipping, and the Python question

**With a developer profile the App Store is back on the table — but only if
the server is Swift.** Having the profile does not lift the sandbox. The
four things I said would block it all have proper APIs, and all four
compile:

| shelled out to | proper API |
|---|---|
| `diskutil eject` | `NSWorkspace.unmountAndEjectDevice(atPath:)` |
| writing to `/Volumes/IPOD` | a security-scoped bookmark on a volume the user picks once |
| `osascript` to Music.app | Apple Events, gated by `com.apple.security.automation.apple-events` |
| `ffmpeg` | a bundled helper; a child process inherits the sandbox |

None of them needs a shell. What *is* hard to get past review is bundling
an interpreter and spawning it to run bundled scripts. So the packaging
question and the rewrite question are the same question.

**Is Python common in Swift apps? No.** It happens — scientific and ML
apps ship runtimes — but inside a Mac app it reads as a wrapper rather than
an app, and it costs 24–84 MB plus a dylib tree that all has to be signed
inside-out.

### What a rewrite actually is, measured

5,585 lines of Python, and they are not equal:

| | lines | risk |
|---|---|---|
| **format** — `itunesdb`, `itunesdb_write`, `ipod_edit`, `hash58`, `tags` | **1,253** | **the crown jewels.** Byte-identical round trip, hash58, proven on hardware. A rewrite means re-earning that trust. |
| **core** — `apply`, `state`, `reconcile`, `local_index`, `config` | 1,077 | mechanical. `plan()`'s output is the test. |
| **server** — `curate.py` | 1,704 | plumbing |
| **side** — lookups, reports, one-offs | 1,551 | **does not need to ship in the app at all** |

So the app is ~2,300 lines of real port plus a server, not 5,585.

### And the web keeps working — that is the point

**Swift serves the same HTTP with no dependency.** `NWListener` from
Network.framework, which is in the OS: 68 KB binary, no SwiftNIO, no
Vapor, no package at all. Verified — it answered
`GET /api/tracks` with JSON.

So the architecture does not become "a native app instead of the web one".
It becomes:

```
          Swift core  (format + rules)
                |
          Swift HTTP server
           /                curate.html      native UI
   (one file,       (Table, inspector,
    no build)        UndoManager)
```

One truth, two clients — the same shape the layer rule already describes,
with the truth rewritten underneath. **The page stays exactly as it is**:
one file, no build step, edit and reload. It remains the fast surface, and
the native app stops being a reason to slow down.

### PROPOSED — how to make the port provable rather than hopeful

The format code is the risk, and it is also the easiest thing in the
project to verify, because correctness is already defined as *the same
bytes*:

**Run both implementations against the same database and diff the output.**
Python parses and re-serialises; Swift parses and re-serialises; the bytes
must match, and `hash58` must verify both. Do it over every backup in
`backups/` — there are several, from real device states — and the port is
proven rather than believed. That is the same standard `rehearse` already
sets, pointed at a second implementation instead of a second write.

## The two questions to settle before starting

1. ~~**Does the native app ship the server, or require it running?**~~
   **Answered 1 October: rewrite it in Swift.** I had ruled this out on the
   grounds that two implementations would drift — but that is only true if
   both survive. If the Swift server serves the same endpoints and the same
   page, Python is replaced rather than duplicated, there is still one
   truth, and the web UI keeps working unchanged. It is also what makes the
   App Store route viable, since bundling an interpreter is the part review
   does not like.
2. **Does an iPad or iPhone version follow?** The earlier research said the
   USB-C storage access exists. But the layer rule makes this a different
   question than it was: a phone client would need the *server* reachable,
   not just the device, and the server is where the iPod is plugged in.
