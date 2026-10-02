# What is still to do

**Status: a list, kept honest.** Opened 2 October 2026 after the owner
pointed out the obvious: *"feels like you keep on missing things that you
could have also done, like mark those podcasts as actual podcasts."*

He is right, and the reason is worth naming so it stops happening. Work
went depth-first on whatever was in front of it. The iPod was mounted for
an hour and the only thing written to it was artwork -- while the podcast
media type, the play-count merge and the smart playlists all needed that
same connected device and were all already decided. **Device-dependent
work has to be batched while the device is there.**

A second pattern, just as costly: a module gets built and verified and
then nothing can call it. Seven of them, below.

---

## 1. Built and verified, but NOTHING CAN CALL IT

**CLOSED 2 October**, and the census that was supposed to catch this has
been fixed so it closes for good.

| module | verb | state |
|---|---|---|
| `smartlists` | `saltpod smartlists show\|check` | DONE -- `check` diffs our evaluation against what iTunes materialised |
| `loudness` | `saltpod loudness show\|scan\|import\|track` | DONE -- the write path is still open, see section 2 |
| `rockbox` | `saltpod rockbox plan\|write` | DONE -- needed a translation layer that did not exist, below |
| `devprefs` | `saltpod devprefs show\|check` | DONE |
| `podcasts` | `saltpod podcasts status\|rehearse\|write` | DONE -- the device write last session went through a throwaway script, which is the same bug one layer along |
| `playcounts` | `saltpod plays` | DONE -- merge has now run, 324 plays across 168 tracks |
| `artwork` / `artworkdb` | `saltpod art` | DONE |

Three things only became visible once someone tried to write the verbs.

**`rockbox` was unreachable for a deeper reason than a missing verb.** It
takes `{name: [(device_path, title, seconds)]}`; `state.py` holds
`collection_order` as `{name: [track_key]}` and keeps the path as iPod
colon-notation (`:iPod_Control:Music:F46:VXBJ.m4a`) on the track record.
No caller could have satisfied that interface without a translation
nobody had written. It is now `rockbox.collections_from_state()`, and all
three collections render.

**The 19-minute loudness scan was invisible to its own module.** It was
written to `data/local/loudness_scan.json` by a one-off script;
`analyse_cached` reads `data/local/loudness_cache.json`. Every one of
those 4,044 files would have been re-measured. `saltpod loudness import`
folds one into the other -- the scan carries `size` and `mtime`, which are
exactly the two keys the cache tests for freshness, so an imported entry
is indistinguishable from one measured here and goes stale on the same
evidence.

**The census was asking the wrong question.** `bin/layer_census.py`
compared `curate.OPS` against `cli.py`'s verbs and said *"every operation
has a verb"* -- true, and useless, because a module nothing had registered
was never a candidate to be missing. It now walks the import graph from
both adapters and names any shipped module neither can reach. It found
six on the first run, `podcasts` among them.

Five remain, named in the source with a budget that only goes down:
`buy_lossless`, `verify_bandcamp`, `spectrum` and `verify_quality` are
research one-offs that ship without a verb. **`itunesdb_patch` is the one
to settle** -- it describes itself as *"the safest way to write"* and
nothing writes through it.

## 2. DECIDED, DESIGNED, NOT BUILT

**Podcast media type.** The scope changed this morning -- everything that
goes on the iPod, with audiobooks filed as podcasts. The design is settled
(a collection named Podcasts whose effect is a `mediatype`, seeded from
the files that already declare themselves). The classification question
answered itself: 11 files still carry `PCST`/`WFED` from a 2011 RSS feed.
Every one of the 653 tracks on the device is still `mediatype 0x1`, and
the ten DeepCast episodes still only appear under Artists.

**Sound Check.** Target decided and derived (-18 LUFS, the first level at
which nothing in this library needs amplifying). The full-library scan is
now DONE -- 4,044 files measured in 19 minutes. Not one value has been
written to a track.

**Smart playlist membership.** The evaluator reproduces iTunes exactly --
all 24 Top 25 members in order -- and independently computed the same 178
Recently Added tracks the device itself later materialised. It writes
nothing.

**Rockbox `.m3u8` output.** Written and tested against a simulated device
root. Never wired into a sync, and never run against a real Rockbox iPod
because there is not one here.

## 3. BUILT, NEVER RUN against real state

**`plays adopt`.** 69 tracks on the device carry a play count, 197 plays
reaching back to 2018. State has zero. One command, never run.

**The Play Counts merge.** Seven sidecars sit in `backups/`, and the
oldest holds **124 plays across 100 tracks** from before saltpod first
touched the device -- listening history nothing has ever collected. The
merge ledger is empty.

## 4. FOUND IN RESEARCH, NEVER ACTED ON

| finding | scale | what it is worth |
|---|---|---|
| `TKEY`/`TKY2` musical key | 1,058 files | sequencing by key, for a DJ library |
| `TBPM` tempo | 1,022 files | the same |
| `iTunNORM` | 214 files | Apple's own Sound Check value, free, currently discarded |
| `TSRC` ISRC | 790 files | a global recording identifier -- better matching than artist+title |
| `TPUB` label | 1,253 files | browsing by label |
| WAV `id3 ` chunks | 368 files | now READ; still refused for WRITING |
| ID3v2.2 tags | 47 files | refused for writing, needs a converter |

## 5. NOT STARTED

- **On-The-Go playlists** -- made on the device, silently dropped by a sync
- **Recordings/** -- the same, for voice memos
- **Ratings to the device** -- read, cannot be set; one byte at `mhit`+0x1F
- `total tracks` / `total discs` / `disc number` -- cosmetic
- **Gapless data** -- unmeasured whether the Classic needs it

## 6. TESTING AND QUALITY

- `bin/pagetest.py` is **not wired into `bin/selftest.py`** -- it has to be
  run by hand, which means it will stop being run
- **No screen reader has ever been run** against the page
- No roving tabindex on the left, source and right panes
- The gear's busy dot and the folded-filter dot are still colour-only
- Three of the seven new modules' selftests need a device and FAIL rather
  than SKIP when it is absent

## 7. THE DEVICE-DEPENDENT BATCH

When the iPod is next connected, these should go together in one session
rather than one per reconnection:

1. `plays adopt` and the sidecar merge  (reads, then writes state only)
2. the podcast media type on the 11 declared files
3. Sound Check values from the completed scan
4. smart playlist membership -- with the gate that Top 25 must come out
   matching what iTunes wrote
5. a re-read afterwards to confirm all four survived

Each is reversible, each has a backup, and all four need the same cable.
