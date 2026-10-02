# iTunesDB smart playlists (mhod 50/51) -- wire format and evaluator spec

**Status**: Mixed, marked inline with tags. **MEASURED** = decoded here, read-only, from this
machine's real iPod (`/Volumes/IPOD/iPod_Control/iTunes/iTunesDB`, v0x75, 653 tracks) and cross-checked
against 11 backups in `backups/ipod-*/iTunesDB` captured 2026-09-27 through 2026-10-01.
**RESEARCHED FROM SOURCES** = taken from libgpod's own C source (primary) and the ipodlinux wiki
(secondary, via a surviving mirror), cited inline, not independently verified against bytes on this
device because this device's 13 smart playlists (7 user-visible + 6 media-type) never exercise that
part of the format (noted where it applies -- string-type rules in particular). **PROPOSED** = a
hypothesis, not a finding;
every occurrence is called out explicitly and none of it should be coded against without further
checking. Where a source and this device's real bytes disagree, **the real bytes win** and the
disagreement is stated plainly rather than silently resolved.

This supersedes the "opaque blob, copy verbatim" treatment in `research/itunesdb-format.md` section 6
for anyone who wants to evaluate rules instead of just preserving them. It does not edit that file.

## Sources

| Tag | Source |
|---|---|
| **L** | libgpod, GitHub mirror `fadingred/libgpod`, `master` branch, fetched 2026-10-02: `src/itdb.h` (enums, struct docs), `src/itdb_itunesdb.c` (wire-format read/write, functions `get_mhod`/`mk_mhod`), `src/itdb_playlist.c` (`itdb_splr_get_field_type`, `itdb_splr_get_action_type`, `itdb_splr_eval`, `itdb_spl_update` -- the actual reference evaluator). This is the same project tagged **L** in `research/itunesdb-format.md`; the SPL-specific files were not read there. |
| **L2** | `strawberrymusicplayer/strawberry-libgpod` (a maintained fork), `src/itdb.h`, fetched 2026-10-02, used only to check whether `fadingred/libgpod` is missing anything newer. It is not -- same field table, same gaps. |
| **W-mirror** | `www.ipodlinux.org` no longer serves the wiki: it now resolves to an unrelated parked domain with a mismatched TLS certificate (confirmed 2026-10-02 -- `curl` to `https://www.ipodlinux.org/ITunesDB/iTunesDB_File.html` fails with "Host: www.ipodlinux.org is not in the cert's altnames"). A content-identical mirror is live at `https://seshan.xyz/flow/files/ipodlinux/ITunesDB/iTunesDB_File.html`. Used as a secondary cross-check; every number it gave matched **L** exactly, so **L** is cited as primary throughout and W-mirror is noted only where it adds something L's comments don't spell out. |
| **D** | This session's own read-only decode of `/Volumes/IPOD/iPod_Control/iTunes/iTunesDB` plus 11 backup copies under `backups/ipod-*/iTunesDB`, using a throwaway script built on this repo's own `saltpod.itunesdb_write.parse()` / `saltpod.ipod_edit` helpers. The device was never written to. |

## Part 1 -- wire format (RESEARCHED FROM SOURCES, cross-checked against D)

### 1.1 Container: where mhod 50/51 sit

Unchanged from `research/itunesdb-format.md` section 5: a smart playlist's `mhyp` carries a title
mhod (1), optionally a column-definition mhod (100), then **mhod 50 immediately followed by mhod
51**, then any materialised `mhip`s. Both mhod 50 and 51 use the ordinary 24-byte (0x18) mhod header
(magic, header_len, total_len, type, then 8 more bytes) -- confirmed by **D** (every mhod 50/51 header
on this device is `6d686f6418000000 ... 32000000`/`33000000`, header_len = 0x18) and by **L**'s writer,
which does `put32lint(cts, 24)` for both types before writing their bodies (`itdb_itunesdb.c`,
`mk_mhod`, cases `MHOD_ID_SPLPREF` / `MHOD_ID_SPLRULES`). This means this repo's existing
`itunesdb_write.Node` -- whose `.body` is everything after the 24-byte header -- needs no changes to
carry these two types; only the body needs interpreting. All offsets below are **body-relative**
(i.e. relative to the first byte after the 24-byte mhod header) unless stated otherwise.

### 1.2 mhod 50 -- SPLPref (preferences and limit)

Total mhod length is fixed at 96 bytes (24-byte header + 72-byte body) -- **L** writes exactly
`put32lint(cts, 96)` and never anything else; **D** confirms: all 15 SPLPref instances across both
mhsd-2 and mhsd-5 sections, on the device and in every backup, have `total_len = 0x60` (96) and
`body_len = 72`. Little-endian throughout (unlike mhod 51 -- see 1.3).

| Off | Sz | Field | Notes |
|---|---|---|---|
| 0x00 | 1 | `liveupdate` | 1 = live updating on |
| 0x01 | 1 | `checkrules` | 1 = apply the mhod-51 rules; 0 = every track matches (rules ignored) (L `itdb.h` struct doc: "Match this number of rules. If set to 0, ignore rules" -- the wire value is written as a plain 0/1 boolean: `put8int(cts, checkrules? 1:0)`) |
| 0x02 | 1 | `checklimits` | 1 = apply the limit (0x03..0x0D below); 0 = unlimited |
| 0x03 | 1 | `limittype` | 1 minutes, 2 MB, 3 songs, 4 hours, 5 GB (`ItdbLimitType`) |
| 0x04 | 1 | `limitsort` (low byte) | see table below; the enum is nominally 32-bit but only the low byte is on the wire (`put8int(cts, limitsort & 0xff)`) |
| 0x05 | 3 | unknown | zero on every D sample |
| 0x08 | 4 | `limitvalue` (LE u32) | the number typed next to "Limit to" |
| 0x0C | 1 | `matchcheckedonly` | 1 = only tracks checked in iTunes/on-device are eligible |
| 0x0D | 1 | `limitsort` opposite flag | 1 flips a "most X" sort to "least X" -- see below |
| 0x0E | 2 | unknown | zero on every D sample |
| 0x10 | 56 | padding | zero on every D sample (`put32_n0(cts, 14)`, i.e. fourteen zero u32 words) |

**Limit type** (`ItdbLimitType`, L `itdb.h`): `1`=minutes, `2`=MB, `3`=songs, `4`=hours, `5`=GB.

**Limit sort** (`ItdbLimitSort`, L `itdb.h`), low byte on the wire:

| Byte | Meaning |
|---|---|
| 0x02 | random |
| 0x03 | song name (alphabetical) |
| 0x04 | album |
| 0x05 | artist |
| 0x07 | genre |
| 0x10 | most recently added |
| 0x14 | most often played |
| 0x15 | most recently played |
| 0x17 | highest rating |

The "least/lowest" variants of recently-added, often-played, recently-played and rating are **not**
separate wire values: they are the *same* low byte as their "most/highest" counterpart, with the
0x0D "opposite" byte set to 1 (L `itdb.h` comment on `ItdbLimitSort`: "the values ... are really 0x10,
0x14, 0x15, 0x17, with the 'limitsort_opposite' flag set ... really very terribly awfully weird").
There is no wire encoding for "least recently added" etc. distinct from flipping that one bit.

### 1.3 mhod 51 -- SPLRules (the rule list)

**Everything inside mhod 51, starting at the `SLst` magic, is big-endian -- including the UTF-16
string data for string-type rules.** This is the one place in the whole iTunesDB that is not
little-endian (L `itdb_itunesdb.c` comment: "for some reason the SLst part is the only part of the
iTunesDB with big-endian encoding, including UTF16 strings"). `research/itunesdb-format.md` does not
call this out and would mislead a byte-for-byte reader; this is the correction.

Header, body-relative offsets:

| Off | Sz | Field | Notes |
|---|---|---|---|
| 0x00 | 4 | `SLst` | ASCII magic, not endian-sensitive |
| 0x04 | 4 | unknown (BE) | L calls it `unk004`; zero on D is not guaranteed -- D shows `0x00010001` on every one of this device's 13 smart playlists (7 user-visible + 6 media-type), i.e. not actually zero. Meaning undetermined; copy through. |
| 0x08 | 4 | rule count (BE) | |
| 0x0C | 4 | match operator (BE) | 0 = match **all** (AND), 1 = match **any** (OR) (`ITDB_SPLMATCH_AND`/`_OR`) |
| 0x10 | 120 | padding | zero on every D sample (`put32_n0(cts, 30)`, thirty zero u32 words) |
| 0x88 | -- | first rule | rules start at body offset 136 (0x88) regardless of padding content |

Each rule, relative to its own start (`rseek`):

| Off | Sz | Field | Notes |
|---|---|---|---|
| 0x00 | 4 | field id (BE) | see field table below |
| 0x04 | 4 | action id (BE) | see action table below |
| 0x08 | 44 | padding | zero on every D sample (`put32_n0(cts, 11)`) |
| 0x34 | 4 | value length (BE) | byte length of the UTF-16BE string for string fields; literal `0x44` (68) for every other field type |
| 0x38 | varies | value | string rule: `length` bytes of UTF-16BE text, no terminator, max 255 chars (`ITDB_SPL_STRING_MAXLEN`). Non-string rule: 68 bytes, see below. |

Non-string value block (68 bytes starting at rule offset 0x38), all big-endian:

| Off (from rule start) | Sz | Field |
|---|---|---|
| 0x38 | 8 | `fromvalue` (u64) |
| 0x40 | 8 | `fromdate` (**i64**, signed) |
| 0x48 | 8 | `fromunits` (u64) |
| 0x50 | 8 | `tovalue` (u64) |
| 0x58 | 8 | `todate` (**i64**, signed) |
| 0x60 | 8 | `tounits` (u64) |
| 0x68 | 20 | unknown (`unk052..unk068` in L, 5 x u32) -- zero on every D sample except where noted (field 0x28 "Playlist" is documented by L to use these, not seen on D) |

A rule's total byte length is therefore `56 + length` where `length` is the value at offset 0x34
(56 for the field/action/padding/length-field prefix, then the value). Non-string rules are always
`56 + 68 = 124` bytes.

**Caveat**: none of the 13 smart playlists on this device use a string-type rule (all 25 rules
observed, counting each logical playlist once rather than its duplicate type-2/type-3 copy, are
int/date/binary_and -- see Part 2). The 24-byte-header and the SLst/padding/rule-prefix
layout above are MEASURED; the specific **string value encoding (UTF-16BE, no terminator)** is
RESEARCHED FROM SOURCES only (L's reader/writer agree with each other and with the W-mirror text, but
this device gives no bytes to check it against). Implement it as documented, but don't treat it as
device-confirmed the way the rest of this section is.

### 1.4 Field ids (`ItdbSPLField`, L `itdb.h`)

All ids below are the 4-byte big-endian value at rule offset 0x00. "Type" is the field's data type,
which also selects which actions are legal (1.5) and which bytes of the value block matter (1.6):
`string`, `int`, `date` (a mac-epoch timestamp, or a relative "in the last" offset), `bool`,
`playlist` (cross-references another playlist by id), `binary_and` (bitmask test, only used for Video
Kind).

| Id | Field | Type | Id | Field | Type |
|---|---|---|---|---|---|
| 0x02 | Song Name | string | 0x29 | Purchase | bool |
| 0x03 | Album | string | 0x36 | Description | string |
| 0x04 | Artist | string | 0x37 | Category | string |
| 0x05 | Bitrate | int | 0x39 | Podcast | int (see 2.5 -- L never implements this one) |
| 0x06 | Sample Rate | int | 0x3c | Video Kind | binary_and |
| 0x07 | Year | int | 0x3e | TV Show | string |
| 0x08 | Genre | string | 0x3f | Season Number | int |
| 0x09 | Kind (filetype string, e.g. "MP3-File") | string | 0x44 | Skip Count | int |
| 0x0a | Date Modified | date | 0x45 | Last Skipped | date |
| 0x0b | Track Number | int | 0x47 | Album Artist | string |
| 0x0c | Size | int | 0x4e | Sort Song Name | string |
| 0x0d | Time (track length, ms) | int | 0x4f | Sort Album | string |
| 0x0e | Comment | string | 0x50 | Sort Artist | string |
| 0x10 | Date Added | date | 0x51 | Sort Album Artist | string |
| 0x12 | Composer | string | 0x52 | Sort Composer | string |
| 0x16 | Play Count | int | 0x53 | Sort TV Show | string |
| 0x17 | Last Played | date | 0x5a | Album Rating | int |
| 0x18 | Disc Number | int | | | |
| 0x19 | Rating | int | | | |
| 0x1f | Compilation | bool | | | |
| 0x23 | BPM | int | | | |
| 0x27 | Grouping | string | | | |
| 0x28 | Playlist | playlist | | | |

Note the gaps: 0x0f, 0x11, 0x13-0x15, 0x1a-0x1e, 0x20-0x22, 0x24-0x26, 0x2a-0x35, 0x38, 0x3a-0x3b,
0x3d, 0x40-0x43, 0x46, 0x48-0x4d, 0x54-0x59 are not defined by L at all. **This device uses one such
undefined id, 0x9a (154), on the "Favourite Songs" playlist -- see 2.4. It is not in L or L2's field
table.** Treat any id not in this table the way this doc treats 0x9a: decode the wire structure (it's
still well-formed), but do not guess its semantics.

### 1.5 Action ids (`ItdbSPLAction`, L `itdb.h`) -- bitmask structure

L's own doc comment gives the intended bit layout (a comment attributed to Samuel "Otto" Wood, the
original reverse-engineer): high byte selects string-vs-int and NOT; low bits select the comparison.
In practice only a handful of combinations are ever emitted (the same 20 the W-mirror table lists)
and L defines exactly those 20 as named constants; nothing here is 32-bit "free-form", so implement
against the table, not the bit description.

| Hex | Name | Meaning |
|---|---|---|
| 0x00000001 | `IS_INT` | is / is set |
| 0x00000010 | `IS_GREATER_THAN` | is greater than ("is after" for dates in iTunes UI) |
| 0x00000040 | `IS_LESS_THAN` | is less than ("is before" for dates) |
| 0x00000100 | `IS_IN_THE_RANGE` | is in the range [from..to] |
| 0x00000200 | `IS_IN_THE_LAST` | is in the last N units (dates only) |
| 0x00000400 | `BINARY_AND` | `(value & fromvalue) != 0` |
| 0x00000800 | `BINARY_UNKNOWN1` | seen on newer iPods on Video Kind; L's comment hypothesises `((val & from) == val) && (val & to)` but is explicitly unsure. D's one example (Rentals, 2.6) has `from == to`, which doesn't exercise the from/to distinction either way. |
| 0x01000001 | `IS_STRING` | is (string) |
| 0x01000002 | `CONTAINS` | contains |
| 0x01000004 | `STARTS_WITH` | starts with |
| 0x01000008 | `ENDS_WITH` | ends with |
| 0x02000001 | `IS_NOT_INT` | is not / is not set |
| 0x02000010 | `IS_NOT_GREATER_THAN` | (not exposed in iTunes UI) |
| 0x02000040 | `IS_NOT_LESS_THAN` | (not exposed in iTunes UI) |
| 0x02000100 | `IS_NOT_IN_THE_RANGE` | (not exposed in iTunes UI) |
| 0x02000200 | `IS_NOT_IN_THE_LAST` | is not in the last N units |
| 0x02000400 | `NOT_BINARY_AND` | `(value & fromvalue) == 0` |
| 0x02000800 | `BINARY_UNKNOWN2` | negation of 0x00000800, same caveat |
| 0x03000001 | `IS_NOT` | is not (string) |
| 0x03000002 | `DOES_NOT_CONTAIN` | does not contain |
| 0x03000004 | `DOES_NOT_START_WITH` | (not exposed in iTunes UI) |
| 0x03000008 | `DOES_NOT_END_WITH` | (not exposed in iTunes UI) |

Bitmask reading of the above (L doc comment, for recognising an id not in the table): high byte bit 0
(0x01000000) = string-typed value; high byte bit 1 (0x02000000) = NOT; low 16 bits bit 0 = simple IS,
bit 1 = contains, bit 2 = begins with, bit 3 = ends with, bit 4 = greater than, bit 6 = less than,
bit 8 = range, bit 9 = in the last, bit 10 = binary AND, bit 11 = unknown. Bits 5 and 7 (greater-or-
equal, less-or-equal) are listed by L as "probably" that meaning but have no named constant and were
not seen on D.

**Which actions are legal for which field type** (from `itdb_splr_get_action_type`, L
`itdb_playlist.c` -- an evaluator should validate against this, not accept any field/action pairing):

| Field type | Legal actions |
|---|---|
| string | `IS_STRING`, `IS_NOT`, `CONTAINS`, `DOES_NOT_CONTAIN`, `STARTS_WITH`, `DOES_NOT_START_WITH`, `ENDS_WITH`, `DOES_NOT_END_WITH` |
| int | `IS_INT`, `IS_NOT_INT`, `IS_GREATER_THAN`, `IS_NOT_GREATER_THAN`, `IS_LESS_THAN`, `IS_NOT_LESS_THAN`, `IS_IN_THE_RANGE`, `IS_NOT_IN_THE_RANGE` |
| bool | `IS_INT` ("is set"), `IS_NOT_INT` ("is not set") only |
| date | `IS_INT`, `IS_NOT_INT`, `IS_GREATER_THAN`, `IS_NOT_GREATER_THAN`, `IS_LESS_THAN`, `IS_NOT_LESS_THAN` (absolute-date forms), `IS_IN_THE_RANGE`, `IS_NOT_IN_THE_RANGE`, `IS_IN_THE_LAST`, `IS_NOT_IN_THE_LAST` |
| playlist | `IS_INT` ("is in this playlist"), `IS_NOT_INT` ("is not in this playlist") only |
| binary_and | `BINARY_AND`, `NOT_BINARY_AND`, `BINARY_UNKNOWN1`, `BINARY_UNKNOWN2` only |

### 1.6 Date and "in the last N" encoding -- RESEARCHED FROM SOURCES, confirmed against D

The task brief that set up this research guessed a "0x2C / units of seconds" scheme. **That scheme
does not appear anywhere in L's source or in this device's bytes.** The real mechanism, confirmed
both in L's code and in D's "Recently Added"/"Recently Played" rules (2.3):

- Absolute date comparisons (`IS_INT`/`IS_NOT_INT`/`IS_GREATER_THAN`/`IS_LESS_THAN`/range on a `date`
  field): `fromvalue`/`tovalue` hold a **Mac timestamp** (seconds since 1904-01-01, the same epoch
  this repo's `itunesdb._mactime()` already handles) written through
  `device_time_time_t_to_mac()`/`_mac_to_time_t()` (L `itdb_itunesdb.c`). `fromdate`/`fromunits` are
  unused (0/1) for this form.
- "In the last" (`IS_IN_THE_LAST`/`IS_NOT_IN_THE_LAST`, dates only): `fromvalue` is **not** a real
  value -- it is the literal sentinel `0x2dae2dae2dae2dae` (`ITDB_SPL_DATE_IDENTIFIER`, L `itdb.h`),
  meaning "today, computed at evaluation time, not stored". The actual window is
  `fromdate * fromunits` seconds, where `fromdate` is a **signed** count (negative, since it means
  "N units ago") and `fromunits` is the **literal number of seconds in one unit** -- not a code, a
  plain integer. L publishes three constants for this (`ItdbSPLActionLast`): `86400` (a day),
  `604800` (a week), `2628000` (a month, 30.4167 days). Its own comment adds, disabled behind `#if 0`
  (so not part of the compiled public API, but illustrative of how open the field really is): hours
  (3600), minutes (60), years (31536000), and a set of joke units (fortnight, lunar cycle, swatch
  beat, "ostent") that all work on the wire precisely because `fromunits` is just seconds, not an
  enum.
  - **D confirms this exactly.** Both "Recently Added" (Date Added field) and "Recently Played"
    (Last Played field) carry `fromvalue = 0x2dae2dae2dae2dae`, `fromdate = -2`, `fromunits = 604800`
    -- i.e. "in the last 2 weeks", matching their names.
  - Reference evaluation (L `itdb_splr_eval`): `t = now(); t += fromdate * fromunits; return
    stored_value > t` for `IS_IN_THE_LAST` (`<=` for the NOT form). `stored_value` here is the
    track's date field already converted to Unix time. Mac-epoch conversion only applies to the
    absolute-date forms above; it is explicitly skipped for `IN_THE_LAST`/`NOT_IN_THE_LAST` in L's
    parser (`if ((at == ITDB_SPLAT_RANGE_DATE) || (at == ITDB_SPLAT_DATE)) { convert }` -- the
    `INTHELAST` action type is not in that condition).

### 1.7 Evaluating a rule against a track -- RESEARCHED FROM SOURCES (`itdb_splr_eval`, L `itdb_playlist.c`)

This is L's actual reference evaluator, transcribed field-by-field because it is the part an
implementation most needs and is easiest to get subtly wrong:

- **string**: `strcomp` = the track's string for that field (title/album/artist/genre/kind-string/
  comment/composer/grouping/album_artist/tvshow). `IS_STRING`: `strcomp == rule.string` (exact,
  **case-sensitive** -- plain `strcmp`). `CONTAINS`/`STARTS_WITH`/`ENDS_WITH` and their `DOES_NOT_*`
  negations: also plain `strstr`/`strncmp`, **case-sensitive**. If either string is empty/absent,
  every comparison in L's code returns `FALSE` (not an error). iTunes itself is case-insensitive in
  its own UI; L's evaluator is not. This is worth flagging to whoever writes ours: matching L's
  reference byte-for-byte means case-sensitive comparisons, which will disagree with what a user
  typing into iTunes expects. Decide explicitly rather than inheriting this silently.
- **int**: `IS_INT`/`IS_NOT_INT` = `==`/`!=`; `IS_GREATER_THAN`/`IS_LESS_THAN` = `>`/`<` against
  `fromvalue`; `IS_IN_THE_RANGE`/`IS_NOT_IN_THE_RANGE` = inclusive both-orderings range check against
  `[fromvalue, tovalue]` (handles the range being given backwards).
- **bool**: `IS_INT` means "is set" (`boolcomp != 0`); `IS_NOT_INT` means "is not set".
- **date**: as in 1.6.
- **binary_and**: `BINARY_AND`: `(mediatype & fromvalue) != 0`. `NOT_BINARY_AND`: the same test,
  negated. (`BINARY_UNKNOWN1`/`2` are not implemented in `itdb_splr_eval` at all -- they fall through
  to "unknown action type" and `itdb_spl_action_known()` only warns, it doesn't reject. Rentals (2.6)
  uses `BINARY_UNKNOWN1` for real, so an evaluator aiming to actually reproduce iTunes needs to
  implement this case even though L's own reference does not.)
- **playlist**: looks up the *other* playlist by id (`fromvalue`) and tests current membership
  (`IS_INT` = is a member, `IS_NOT_INT` = is not). This is the one field whose "value" is not a track
  property at all -- see 3.3.
- **Field 0x39 (Podcast) has a declared type (`int`, per `itdb_splr_get_field_type`) but
  `itdb_splr_eval`'s field switch has no `case` for it at all** (confirmed by grepping the function
  body in `itdb_playlist.c`: every other int/date/bool/string/playlist/binary_and field from the
  table in 1.4 has a case; `ITDB_SPLFIELD_PODCAST` does not). Un-handled fields fall through to
  `g_return_val_if_reached(FALSE)`, i.e. **L's own reference evaluator always returns FALSE for a
  Podcast rule**, which -- combined with AND-matching -- would make any playlist using "Podcast is
  not 1" under match-all (exactly what this device's Recently Added/Recently Played/Top 25 Most
  Played all do, see 2.3) **always empty** if L's eval were ported literally. Do not port it
  literally for this field: implement Podcast by reading the track's mediatype (podcast = 4, video
  podcast = 6, per `research/itunesdb-format.md` section 3's mediatype table) the same way Video Kind
  already has to.

**Combining rules** (`itdb_spl_update`, L `itdb_playlist.c`): start `true` for match-all (AND, operator
0), `false` for match-any (OR, operator 1); an empty rule list always matches. For AND, stop at the
first `false` rule (result `false`); for OR, stop at the first `true` rule (result `true`).
`matchcheckedonly` filters the candidate set *before* rule matching, on the track's "checked" flag.

**Applying the limit** (same function, continued): sort the matched set by `limitsort` using the
obvious comparator per sort key (title/album/artist/genre alphabetically; most/least recently
added/played by timestamp descending/ascending; most/least often played by play count
descending/ascending; highest/lowest rating descending/ascending; random = shuffle). Then walk the
sorted list accumulating a running total and stop once it would exceed `limitvalue`:
`songs` -> +1 per track; `minutes` -> `+= length_ms/60000`; `hours` -> `+= length_ms/3600000`;
`MB` -> `+= size/1048576`; `GB` -> `+= size/1073741824`. A track is only added if adding it would not
exceed the limit (so the last track that would overflow it is dropped, not truncated).

## Part 2 -- what's actually on this device (MEASURED)

Decoded read-only from `/Volumes/IPOD/iPod_Control/iTunes/iTunesDB`, cross-checked byte-for-byte
identical in all 11 `backups/ipod-*/iTunesDB` copies in this repo (2026-09-27 through 2026-10-01) and
against the tracks each playlist actually has materialised, via `saltpod.itunesdb.read()`. Every
smart playlist on the device appears **twice**, byte-identical, once under mhsd type 2 (normal
playlists) and once under type 3 (podcast-style list) -- matching the existing finding in
`research/itunesdb-format.md` section 2 ("On D it is byte-identical to type 2"); only the type-2 copy
is shown below. The six media-type lists live only under mhsd type 5.

Method (read-only, no write):

```
PYTHONPATH=src python3 -c "
from saltpod import itunesdb_write as W, ipod_edit as E
root = W.parse(open('/Volumes/IPOD/iPod_Control/iTunes/iTunesDB','rb').read())
..."
```

### 2.1 Favourite Songs

```
match all, [Video Kind binary-AND 0x1 (-> mediatype bit 0x1 = audio),
            field 0x9a is 2 (UNKNOWN FIELD, see 2.4)],
limit 50000 songs (checklimits=1, i.e. "on", but 50000 is effectively unlimited for this library of
            653 tracks) by limitsort=1 (UNKNOWN VALUE, see 2.4), live updating.
Materialised: 0 mhips.
```

### 2.2 90’s Music / 90s Music

```
match all, [Video Kind binary-AND 0x21 (-> mediatype bits 0x20|0x1 = music video OR audio... see
            caveat below), Year is in the range [1990..1999]],
no limit, live updating.
Materialised: 3 mhips (identical set in both playlists).
```

Byte-identical mhod 50 and mhod 51 between "90’s Music" and "90s Music" -- these are two copies of
the same smart playlist under slightly different names, not independently configured.

**Matches membership.** The 3 materialised tracks (via `I.read()`): year 1992 ("Percolator (Original
Version)" -- Cajmere), year 1997 ("Check Yo Self" -- Ice Cube), year 1999 ("Video Killed the Radio
Star" -- The Buggles). All three are 1990-1999 as the name promises.

Caveat on the Video Kind mask: 0x21 = bits 0x20 and 0x1. Per `research/itunesdb-format.md` section 3,
mediatype 0x20 is "music video" and (per this doc's own measurements, 2.6) bit 0x1 shows up elsewhere
meaning plain audio. A mask combining them most likely means "audio tracks or music videos", which is
a sensible scope for a "decade" smart playlist (include music videos from the era, not just songs);
not independently confirmed beyond that it doesn't contradict anything.

### 2.3 My Top Rated

```
match any, [Rating is greater than 60 (i.e. more than 3 stars)],
no limit, live updating.
Materialised: 0 mhips.
```

**Matches membership, and this one is a clean control, not staleness**: across all 653 tracks on the
device, **zero** currently have `rating > 0` at all (checked directly). Zero materialised members is
the only correct answer here, which is exactly why it's a useful control: it shows the "0 members"
cases below are not just an artefact of how this project's tooling reads ratings.

### 2.4 Favourite Songs -- the two unresolved readings (PROPOSED, not confirmed)

- **Field 0x9a, action `IS_INT` (0x00000001), fromvalue = tovalue = 2.** Not in L's or L2's field
  table (checked both the actively-ported `fadingred/libgpod` and the `strawberrymusicplayer` fork;
  neither defines anything above 0x5a). iTunes added a per-track "Loved"/"Disliked" attribute around
  version 12.2 (Apple Music integration, after libgpod's active development had effectively stopped),
  which is a plausible origin for an id libgpod never learned about. **Hypothesis, not a finding**:
  0x9a could be that Loved/Disliked state, with value 2 meaning "loved" (by analogy with a
  0=none/1=disliked/2=loved enumeration) -- this is PROPOSED, unconfirmed, and should not be coded
  against without independent verification (e.g. loving a track in iTunes and diffing the DB, or
  finding this id in a newer source than L/L2).
  Raw bytes (rule-relative): `field=0000009a action=00000001 pad(44x00) length=00000044 fromvalue=0000000000000002 fromdate=0 fromunits=1 tovalue=0000000000000002 todate=0 tounits=1`.
- **`limitsort` low byte = 1.** Not in L's `ItdbLimitSort` table (which starts at 0x02). Since
  `checklimits=1` but the limit (50000 songs) is high enough to never bind for this library, the sort
  order may simply never have been meaningfully set by iTunes for this particular auto-generated
  playlist -- PROPOSED, unconfirmed, shown as raw rather than guessed.

Everything else in this document avoided inventing readings for exactly this reason; these two are
flagged rather than folded into the field/action tables above.

### 2.5 Recently Added / Recently Played / Top 25 Most Played

```
Recently Added:  match all, [Date Added is in the last 2 week(s)
                              (fromvalue=0x2dae2dae2dae2dae, fromdate=-2, fromunits=604800),
                              Podcast is not 1],
                 no limit, live updating.  Materialised: 0 mhips.

Recently Played: match all, [Last Played is in the last 2 week(s)
                              (fromvalue=0x2dae2dae2dae2dae, fromdate=-2, fromunits=604800),
                              Podcast is not 1],
                 no limit, live updating.  Materialised: 0 mhips.

Top 25 Most Played: match all, [Podcast is not 1, Play Count is greater than 0],
                 limit 25 songs by most often played, live updating.
                 Materialised: 24 mhips.
```

**Top 25 Most Played matches membership exactly.** Its 24 materialised tracks, read via
`I.read()`, are strictly sorted descending by `play_count` (14, 13, 9, 9, 9, 7, 6, 5, 4, 4, 4, 4, 4,
4, 4, 4, 4, 3, 3, 3, 3, 2, 2, 2 -- the limit cut it at 24 songs, exactly "limit 25" minus whatever the
device's own tie-handling dropped, consistent with "limit 25" and "sort by most often played").

**Recently Added is the clean proof of the staleness this whole project exists to fix.** As of
2026-10-02, **178 of 653 tracks** on this device have a `date_added` within the last 14 days (checked
directly against the mhit field, which -- unlike play count/rating/last played -- is written once at
sync time and not subject to the "iPod doesn't update it" caveat in `playcounts.py`). The playlist's
own rule is exactly "in the last 2 weeks". Yet the device shows **0 materialised members**, and has
shown 0 in every one of the 11 backups this repo holds going back to 2026-09-27 -- i.e. this playlist
has been stale for at least the entire period this project has been observing the device. This is
precisely the gap an evaluator is meant to close: the rule is simple, correct, and currently false on
the device only because nothing but iTunes ever re-evaluates it.

**Recently Played is not as clean a proof**: no track on the device has `last_played` within the
window either (most recent is 2026-03-28, over six months stale), so 0 materialised members doesn't
provably show the bug the way Recently Added does -- see 3.2 for why `last_played` itself is a
two-tier field (mhit vs. the `Play Counts` sidecar) and can't be trusted on its own anyway.

### 2.6 The six media-type lists (mhsd type 5)

All six: `match all`, no limit, live updating, 0 materialised mhips (this repo's own
`research/itunesdb-format.md` section 2 already notes libgpod forces `mhip` count to 0 for mhsd-5
lists; D confirms the same here). Two Video Kind rules each, both AND-masks against the same
mediatype field used by `research/itunesdb-format.md` section 3 (mhit+0xD0, 4-byte LE):

```
Music:      Video Kind binary-AND  from=to=0x1021b1   AND  Video Kind NOT-binary-AND  from=to=0x208004
Videos:     Video Kind binary-AND  from=to=0xc42       AND  Video Kind NOT-binary-AND  from=to=0x20a004
Movies:     Video Kind binary-AND  from=to=0x402        AND  Video Kind NOT-binary-AND  from=to=0x20a004
TV Shows:   Video Kind binary-AND  from=to=0x40         AND  Video Kind NOT-binary-AND  from=to=0x20a004
Audiobooks: Video Kind binary-AND  from=to=0x8          AND  Video Kind NOT-binary-AND  from=to=0x20a004
Rentals:    Video Kind binary-AND  from=to=0x42         AND  Video Kind "binary-unknown1" from=to=0x8000
```

Partial sense-check against `research/itunesdb-format.md`'s mediatype table (0=both menus, 1 audio, 2
video, 4 podcast, 6 video podcast, 8 audiobook, 0x20 music video, 0x40 TV show, 0x60 TV show+music):
TV Shows' mask (0x40) and Audiobooks' mask (0x8) are **exact single-bit matches** to that table.
Movies' mask (0x402 = 0x400 | 0x2) and Rentals' first mask (0x42 = 0x40 | 0x2) both include the
documented "video" bit (0x2) plus additional bits -- 0x400 and (shared across all six) 0x2000,
0x8000, 0x200000 -- that are **not in the documented mediatype table at all**. This is a real,
measured finding, not a guess: **the mediatype field at mhit+0xD0 is used with bits well above the
previously-documented 0x60 ceiling on this device** (the common exclusion mask across all six lists,
0x20a004 = bits 0x4|0x2000|0x8000|0x200000, and Rentals' separate 0x8000 check, both sit outside the
documented range). `research/itunesdb-format.md`'s offset and size for mediatype (0xD0, 4 bytes LE)
are still correct; only the assumption that its *value space* tops out at 0x60 is now known to be
incomplete. This doc does not attempt to name what 0x400/0x2000/0x8000/0x200000 mean individually --
0x8000 is probably "rental" given it's the one Rentals checks for and nothing else does, but that is
PROPOSED, not confirmed.

## Part 3 -- what our evaluator would have, and would not have (grounded in this repo's own code)

### 3.1 What a track record gives us today

The write path this repo already has (`src/saltpod/ipod_edit.py`: `track_add()`'s `meta` dict,
line 263; `retag()`'s field map, line 200) and the read path (`src/saltpod/itunesdb.py`'s `_tracks()`)
together define the fields in active use: `album`, `artist`, `bitrate`, `composer`, `filetype`
(the Kind string), `genre`, `id`, `location`, `ms` (-> SPLFIELD Time), `size`, `title`, `track_no`,
`visible`, `year`. These map onto SPLFIELD ids directly and are evaluable right now:

| SPLField | Our field | Note |
|---|---|---|
| 0x02 Song Name | `title` | |
| 0x03 Album | `album` | |
| 0x04 Artist | `artist` | |
| 0x05 Bitrate | `bitrate` | |
| 0x07 Year | `year` | |
| 0x08 Genre | `genre` | |
| 0x09 Kind | `filetype` | this is the human string ("AAC audio file"), which is what `itdb_splr_eval` actually compares against (`track->filetype`), not the fourcc |
| 0x0b Track Number | `track_no` | |
| 0x0c Size | `size` | |
| 0x0d Time | `ms` | |
| 0x12 Composer | `composer` | |

`itunesdb.py`'s `_tracks()` (lines ~93-109) also reads several more mhit fields unconditionally,
not part of the task's working list above but already flowing through `I.read()` today: `rating`
(mhit+0x1F), `play_count`/`play_count2` (mhit+0x50/0x54), `last_played` (mhit+0x58), `disc_no`
(mhit+0x5C), `date_added` (mhit+0x68), `bookmark_ms` (mhit+0x6C), plus `sample_rate` (mhit+0x3C>>16).
And its MHOD-string map additionally decodes `comment` (mhod 8) and `grouping` (mhod 13) when present
on a track, again not part of the 14-field list but already there. Worth knowing before assuming a
field needs new plumbing -- some of what follows is "missing from the narrow contract" rather than
"missing from the codebase".

### 3.2 Fields we cannot evaluate yet, and where they'd come from

| SPLField | mhit offset (per `research/itunesdb-format.md` section 3) | Currently read? | Notes |
|---|---|---|---|
| 0x06 Sample Rate | 0x3C (LE, <<16) | Yes, by `itunesdb.py`, not by `ipod_edit.py`'s write contract | cheap to add to the 14-field record |
| 0x0a Date Modified | 0x20 ("last modified") | **No** -- not read anywhere in this repo | genuine gap, trivial to add (plain mactime) |
| 0x0e Comment | mhod type 8 | Yes, conditionally (if the mhod exists) | not in the 14-field record |
| 0x10 Date Added | 0x68 | Yes | not in the 14-field record; reliable (see 3.3) |
| 0x16 Play Count | 0x50 | Yes, but **stale** | the iPod never updates this field on-device (`playcounts.py` docstring); true current value needs the `Play Counts` sidecar merged in |
| 0x17 Last Played | 0x58 | Yes, but **stale** for the same reason | same caveat; sidecar entry offset 0x04 |
| 0x18 Disc Number | 0x5C | Yes | not in the 14-field record |
| 0x19 Rating | 0x1F | Yes, but **stale** | on-device rating changes (clickwheel) queue in the sidecar (offset 0x0C) until the next iTunes sync, same two-tier problem as play count |
| 0x1f Compilation | 0x1E | **No** | genuine gap, 1-byte flag |
| 0x23 BPM | 0x7A | **No** | genuine gap, 2-byte field |
| 0x27 Grouping | mhod type 13 | Yes, conditionally | not in the 14-field record |
| 0x28 Playlist | n/a -- cross-reference | **No**, and it isn't a track field at all | needs the *other* playlist's materialised membership (or its own rule tree, if it's smart) plus its persistent id (`mhyp`+0x1C per section 5); this is an evaluator-level join, not a record field |
| 0x29 Purchase | no documented offset | **No**, offset unknown | undocumented in `research/itunesdb-format.md` entirely |
| 0x36 Description, 0x37 Category | mhod types 14, 9 | Yes, conditionally (podcast-oriented, rare on this library) | not in the 14-field record |
| 0x39 Podcast | n/a (derived) | **No** | derive from mediatype (0xD0) bits 4/6, per 1.7's note that L's own reference never implements this field |
| 0x3c Video Kind | 0xD0 (mediatype, 4-byte LE) | **No** -- mediatype itself is never read by `itunesdb.py` | needed for all six media-type lists and for the derived Podcast field above; see 2.6 for the fact that its value space is wider than previously documented |
| 0x3e TV Show | mhod types 19-21 region | **No** | not in the current MHOD map at all |
| 0x3f Season Number | no documented offset | **No**, offset unknown | undocumented in `research/itunesdb-format.md` |
| 0x44 Skip Count | 0x9C | **No** | documented offset, never read; sidecar offset 0x14 |
| 0x45 Last Skipped | 0xA0 | **No** | documented offset, never read; sidecar offset 0x18 |
| 0x47 Album Artist | mhod type 22 | **No** -- type 22 is not in `itunesdb.py`'s `MHOD` map at all | genuine gap, needed for Album Artist rules and for interpreting mixed-artist albums generally |
| 0x4e-0x53 Sort fields | mhod types 23-31 region (partially listed in `research/itunesdb-format.md` section 4) | **No** | not seen on any of this device's smart playlists; lowest priority |
| 0x5a Album Rating | no documented offset | **No**, offset unknown | possibly a computed value (e.g. derived from the album's tracks' ratings) rather than a stored one -- PROPOSED, unconfirmed |
| 0x9a (undocumented) | unknown | **No** | see 2.4 -- not even in the reference library's field table, semantics unconfirmed |

**Summary**: `play count`, `rating`, `last played`, `date added`, and `skip count`/`last skipped` are
the fields the task asked about by name. Of those, **date added** is reliably available today (just
not plumbed into the narrow 14-field record) and does not need the sidecar. **Play count, rating, and
last played are available in the mhit but are only as fresh as the last iTunes sync** -- genuinely
evaluating "Top 25 Most Played" or "My Top Rated" against *current* on-device listening requires
merging in `iPod_Control/iTunes/Play Counts` via this repo's existing `saltpod.playcounts.read()`
first (entry layout: offset 0x00 plays, 0x04 last played, 0x08 bookmark ms, 0x0C rating, 0x14 skip
count, 0x18 last skipped -- all confirmed in `playcounts.py` against seven real sidecars). **Skip
count and last skipped have documented mhit offsets (0x9C, 0xA0) that nothing in this codebase reads
at all** -- not stale, just absent.

### 3.3 The "Playlist" field is not a track field

Rule field 0x28 asks "is this track in playlist P", referencing another playlist by id. An evaluator
needs: (a) that playlist's persistent id, from `mhyp`+0x1C (`research/itunesdb-format.md` section 5);
(b) that playlist's current membership -- which, if P is itself smart, means recursively evaluating
P first. None of our current tooling resolves a playlist by persistent id or tracks cross-playlist
dependencies; this is new evaluator machinery, not a missing record field. It was not exercised by
any playlist on this device (not seen in Part 2), so it's lower priority than the mediatype gap.
