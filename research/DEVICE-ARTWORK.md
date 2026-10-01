# Artwork on the device

**Status: measured.** Every figure below came from reading the iPod on
30 September 2026. The last section is proposed and says so.

## What I said, and what is actually true

I told AJ that saltpod-added tracks show no cover on the device, because
`ipod_edit.track_add` writes `ArtworkDB mhii link: none`. That part is
right. The implication I drew from it — that the device shows no artwork —
was too broad.

**478 of 658 tracks carry an artwork link**, pointing at **259 distinct
images**. iTunes put them there and in-place patching has preserved them
throughout. The 180 without a link are the gap, and they are the ones
saltpod added.

## The format, exactly

`iPod_Control/Artwork/` holds four files, 60 MB in total:

| File | Bytes | Per image | What it is |
|---|---|---|---|
| `ArtworkDB` | 198,944 | — | the index |
| `F1055_1.ithmb` | 8,486,912 | **32,768** | **128 × 128** RGB565 |
| `F1060_1.ithmb` | 53,043,200 | **204,800** | **320 × 320** RGB565 |
| `F1061_1.ithmb` | 1,595,440 | **6,160** | **56 × 55** RGB565 |

All three divide by 259 exactly, which is the check that the sizes are
right rather than a plausible guess. Three thumbnails per image, one file
per size, raw pixels back to back with no header — position in the file is
the address, and the database holds the offset.

`ArtworkDB` itself is `mhfd` → three `mhsd` sections → `mhli` (259 `mhii`
image items), `mhla` (empty), `mhlf` (3 `mhif` format records). 777 `mhni`
records, which is 259 × 3: one per thumbnail.

Read back from the device, the first 128 × 128 thumbnail decodes to a real
image — all 16,384 pixels non-black, sane colours. So the layout above is
not inferred, it is confirmed against pixels.

## The two things that make this cheap

**1. ffmpeg already produces the exact bytes.** No new dependency, no
hand-written scaler or colour conversion:

```
ffmpeg -i cover.jpg -vf scale=320:320 -pix_fmt rgb565le -f rawvideo -
```

Verified for all three sizes — 32,768, 204,800 and 6,160 bytes out,
matching what the device expects to the byte.

**2. `itunesdb_write` already round-trips ArtworkDB.** This was the
surprise, and it is the whole estimate. The tree model written for the
iTunesDB parses and re-serialises `ArtworkDB` **byte-identically** once it
is told about three more container types:

```python
LISTS.update({b'mhli': b'mhii', b'mhlf': b'mhif', b'mhla': b'mhaf'})
ITEMS_WITH_MHODS.update({b'mhii', b'mhni'})
```

198,944 bytes in, 198,944 out, identical. The generic "keep anything
unexpected rather than lose it" design paid for itself on a format it was
never written for.

ArtworkDB is **not** hash58-signed — the round trip above did no hashing
and still matched. One less thing.

## PROPOSED — what building it takes

Not built. In order:

1. Let `parse()` accept an `mhfd` root and add the three list mappings.
   Small, and the round trip above is the test.
2. Build an `mhii` plus three `mhni` records for a new image, copying the
   shape of the 259 that are already there rather than inventing one.
3. Append the three thumbnails to the `.ithmb` files and record the
   offsets. Appending means existing images never move.
4. Point the track's `mhit` at the new `mhii` — the field at `0x160` that
   `track_add` currently writes as zero.

The test to pass is the one the device write already meets: round-trip
byte-identical before any edit, and after the edit change only the records
intended.

**What it would fix:** 180 tracks on this device with no cover, and every
track saltpod adds from here on.
