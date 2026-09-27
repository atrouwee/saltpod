# Alternatives to hand-writing the iPod Classic `iTunesDB`

*Researched 2026-09-27 on the owner's Mac (macOS 26.6.1, Music.app 1.6.6) with the iPod mounted in Disk Mode. Status of each claim is marked **measured** (done on this machine/device), **documented** (primary source), or **reported** (forum/blog).*

## Recommendation

**Ranked for this owner** (Python-scriptable, no iTunes, FLAC library, named playlists):

| # | Route | Fit | Effort | Risk | Reversible |
|---|-------|-----|--------|------|------------|
| 1 | **Rockbox (dual-boot)** | Best: playlists are `.m3u8` text files, FLAC plays natively, no `iTunesDB`, sync is `rsync` | 1–2 h once (DFU flash + copy `.rockbox`), then minutes per sync | Moderate at install (one DFU flash), low afterwards | Yes: Hold-switch boots Apple firmware; `mks5lboot --bl-uninst` or an iTunes/Finder restore returns to stock |
| 2 | **Music.app + Finder sync (proven on this Mac, June 2026)** | Half-scriptable: JXA can build the playlists and add files to the Music library; the *sync itself is GUI-only* (no `update`/`sync` verb exists in Music 1.6.6 or Finder) | Low | Low | N/A (it is the stock path) |
| 3 | **Hand-written / library-written `iTunesDB`** (libgpod, iOpenPod — other researchers) | Fully scriptable, keeps stock firmware, but must produce the 6G/7G checksummed DB and transcode FLAC to ALAC | High | Moderate (empty-library symptom; recoverable from backup) | Yes, if `iPod_Control/iTunes/` is backed up first |
| 4 | **Swinsian 3.0.8** ($34.95) | Writes Classic-compatible DB + playlists by drag-and-drop, transcodes FLAC to ALAC; **iPod ops are not scriptable** | Low | Low | Yes |
| — | Doppler, Strawberry/Clementine (macOS builds), foobar2000 iPod manager, MediaMonkey, Floola/YamiPod/SharePod | Not viable on macOS in 2026 (see §2) | | | |

**The one thing that most changes the decision:** Music.app on Tahoe does *not* expose the iPod as a scriptable source and has no `update`/`sync` command (measured: `Application("Music").sources()` returns only `Library` and `iTunes Store`; the `com.apple.Music.sdef` source-kind enum is `library, audio CD, MP3 CD, radio tuner, shared library, iTunes Store, unknown`; the command list has no `update`/`sync`; `Finder.sdef` has no sync verbs; `AMPDevicesAgent` has no CLI). So the only fully scriptable routes are **Rockbox** or **writing the DB ourselves**. Between those, Rockbox is a text file and an `rsync`; the DB is a checksummed binary. The DB route is only worth it if the owner insists on the Apple UI/firmware.

**Single best next step:** read *Settings > About* on the device (Version `1.1.2` = 2007 6G thick; `2.0.4/2.0.5` = Late-2009 7G thin), back up `/Volumes/IPOD/iPod_Control/iTunes/` (already done by the coordinator), then install the **Rockbox dual-boot bootloader** with `mks5lboot` and copy a stable `.rockbox` build. Dual-boot leaves the Apple firmware, the `iTunesDB` and all 481 tracks untouched, so the test costs nothing if Rockbox is rejected.

---

## 1. Rockbox on this device

### Which generation is it? (measured + documented)

- **USB alone cannot tell.** Measured: VID `0x05AC` PID `0x1261`, `bcdDevice = 0x0001`, USB serial `<device GUID>` (that is the FireWire GUID, not the Apple serial). Rockbox's `ipod6g` target uses PID `0x1261` for all Classics (2007, 2008, 2009) ([Rockbox tracker FS#12728](https://www.rockbox.org/tracker/task/12728)). `SysInfo` is empty and `SysInfoExtended` is absent on this volume, so nothing on disk names the model.
- **Capacity does not tell**: both 2007 and 2009 shipped 160 GB (measured disk 159,840,301,056 B, 4096-byte logical blocks in Disk Mode).
- **What does tell:**
  1. **Settings > About > Version**: 2007 6G tops out at **1.1.2**; 2008 120 GB at **2.0.1**; Late-2009 160 GB runs **2.0.4/2.0.5**. A 160 GB unit on 2.0.x is therefore 2009 ([Olsro's firmware guide](https://github.com/Olsro/reddit-ipod-guides/blob/main/guides/ipod6g-flash-more-recent-firmwares.md), [Apple Community](https://discussions.apple.com/thread/5484333)).
  2. **Thickness**: 2007 160 GB = **13.5 mm / 162 g** (dual-platter CE-ATA drive); 2009 160 GB = **10.5 mm / 140 g** (single-platter ZIF) ([Apple SP572](https://support.apple.com/kb/SP572?locale=en_US), [EveryMac 6G](https://everymac.com/systems/apple/ipod/specs/ipod-classic-6th-generation-specs.html), [Apple 112601](https://support.apple.com/en-us/112601)).
  3. **Order number on the back / box**: 2007 160 GB = MB145 (silver) / MB150 (black); 2009 = MC293 / MC297 ([freemyipod](https://files.freemyipod.org/~user890104/bootloader-ipodclassic.html), EveryMac).
  4. **Apple serial suffix**: 2007 units end in Y5N, YMU, YMV or YMX ([Apple 103823](https://support.apple.com/en-us/103823)).

### Support status (documented)

- Rockbox treats every Classic as one target, `ipod6g`. It is a **stable** port; Rockbox **4.0 (April 2025)** "has stable ports for all iPod Classic/Video models" and 4.0 added 192 kHz decoding (16-bit output) and updated FLAC ([How-To Geek](https://www.howtogeek.com/rockbox-4-0-custom-firmware-mp3-players-old-ipods/), [Hackaday](https://hackaday.com/2025/04/19/rockbox-4-0-released/)).
- The `ipod6g` storage driver explicitly supports **both CE-ATA (2007 thick 160 GB, LBA48) and ZIF/PATA** drives, so either generation works on the stock HDD ([storage_ata-6g.c](https://github.com/Rockbox/rockbox/blob/master/firmware/target/arm/s5l8702/ipod6g/storage_ata-6g.c)).
- Active downstream: **Rockpod** (nuxcodes) is a Classic/Video-specific fork with SSD-aware power management and MFi digital out; upstream patches for iFlash flush/corruption landed as recently as Aug 2026 ([rockpod](https://github.com/nuxcodes/rockpod), [issue #37](https://github.com/nuxcodes/rockpod/issues/37)).

### Installing from macOS Tahoe / Apple Silicon (documented + reported)

- The bootloader lives in **NOR flash** and is installed over **DFU** (hold MENU+SELECT ~12 s until the screen goes black). The official tools: **Rockbox Utility** (GUI, documented for Windows) or **`mks5lboot`** (CLI, "for Linux and Mac"; needs `brew install libusb`; built with `make` from `utils/mks5lboot` in the Rockbox tree, verified on macOS with clang). Commands: `--dfuscan -l`, `--bl-inst bootloader-ipod6g.ipod`, `--bl-uninst` ([freemyipod install page](https://files.freemyipod.org/~user890104/bootloader-ipodclassic.html), [mks5lboot](https://github.com/Rockbox/rockbox/tree/master/utils/mks5lboot)).
- Rockbox Utility's own installer for the Classic (`BootloaderInstallS5l`) wraps the same mks5lboot code, so the macOS Rockbox Utility *can* do it; but the only Apple-Silicon walkthrough I found (M1, Monterey, Jan 2022) succeeded with the **Windows Rockbox Utility inside Parallels**, installing the bootloader first and Rockbox second, and iFixit's guide says "Windows only; Mac/Linux not recommended" ([bootloaderinstalls5l.cpp](https://github.com/Rockbox/rockbox/blob/master/utils/rbutilqt/base/bootloaderinstalls5l.cpp), [WNDERLVST](https://wnderlvst.com/stories/install-rockbox-for-ipod-classic-on-apple-silicon-mac-be514e3a-7ffd-42d7-b95b-21b50443ac09), [iFixit](https://www.ifixit.com/Guide/How+to+install+Rockbox+on+an+iPod+Classic/114824)). **Practical advice: use `mks5lboot` from a terminal** (deterministic, scriptable, no GUI autodetect), and quit Music.app / kill `AMPDeviceDiscoveryAgent` first because Finder's device agent grabs the DFU device (the same interference the freemyipod page describes for iTunes/iTunesHelper).
- I did not find a 2025–2026 report of `mks5lboot` failing on Tahoe; nor a success report. Treat "works on Tahoe" as **expected, unverified**.

### Partition layout (measured + documented)

- Rockbox requires **FAT32 ("WinPod")** and will not install on HFS+ ("MacPod"). This device is **MBR + single FAT32 partition** — exactly the layout the Classic bootloader expects (firmware is in NOR; no firmware partition, unlike Video/Nano) ([freemyipod](https://files.freemyipod.org/~user890104/bootloader-ipodclassic.html), [kinbiko](https://kinbiko.com/posts/2026-02-01-rockbox-ipod-classic-iflash-linux-sector-size/)). **Do not reformat.**
- Sector-size gotcha (only if you ever reformat): Rockbox's USB mode presents 4096-byte logical sectors; the bootloader reads the MBR with 512-byte sectors. A disk formatted from a Mac while in *Rockbox* USB mode gets "No partition found". Format only via Apple Disk Mode / iTunes restore (kinbiko, Feb 2026).

### iFlash vs stock HDD (documented)

- Works with both. Caveats apply **only to SD/mSATA adapters**: USB transfer in Rockbox "MAY not work depending on adapter and card", and plugging USB in while Rockbox runs with a bad adapter combination "will lead to filesystem corruption" — then transfer in Apple Disk Mode instead (freemyipod; [iFlash how-to](https://www.iflash.xyz/howto-install-rockbox-on-the-ipod-classics/)). On a stock HDD, Rockbox USB mode is the normal path. The 2007 6G has an LBA28 ~128 GB ceiling with iFlash boards; irrelevant with the stock 160 GB CE-ATA drive.

### The payoff: playlists and formats (documented, from source)

- **Formats**: FLAC, ALAC, WAV, AIFF, MP3, AAC, Vorbis, Opus, WavPack... all decoded in software; 4.0 handles up to 192 kHz, output 16-bit ([Wikipedia Rockbox](https://en.wikipedia.org/wiki/Rockbox)). **No transcoding of the FLAC library needed.**
- **No `iTunesDB`.** Rockbox browses the folder tree directly (File Browser) or builds its own tag database (Database, optional).
- **Playlists**: any `.m3u`/`.m3u8` anywhere; convention is `/Playlists/*.m3u8`, which the *Playlist Catalogue* menu lists. Parsing (from `apps/playlist.c`): lines starting `#` skipped; **UTF-8 BOM forces UTF-8**; **backslashes converted to `/`**; **relative paths resolved against the playlist file's directory**; Windows `C:\` prefixes stripped ([playlist.c](https://raw.githubusercontent.com/Rockbox/rockbox/master/apps/playlist.c)). So write `/Music/Artist/Album/01 Title.flac` (device-root absolute) or `../Music/...` (relative to `/Playlists/`). Absolute Mac paths (`/Users/...`) are dead on arrival ([Diskoteca guide](https://www.diskoteca.com/guides/sync-music-rockbox-ipod-mac/)).
- **Sync = `rsync`** from the Mac. Suggested: `COPYFILE_DISABLE=1 rsync -rtv --modify-window=2 --exclude '.*' --exclude '._*' "<library root>/" /Volumes/IPOD/Music/` then write `/Playlists/*.m3u8` from the JSON. `--modify-window=2` is needed for FAT's 2-second mtime granularity.

### Gotchas (documented/reported)

1. **Unicode normalisation**: macOS lists FAT32 names in **NFD** (decomposed); playlists written in NFC won't match "é/ä/ö" filenames — the exact bug the [m3u8-converter](https://github.com/h0fnar/m3u8-converter) tool exists for. Write playlist entries with `unicodedata.normalize('NFD', path)` *or* keep filenames ASCII. Test one accented track first.
2. **AppleDouble `._*` and `.DS_Store`**: created by Finder/rsync on FAT32; Rockbox hides dotfiles by default ("Show Files: Supported") and the Database ignores non-audio, so harmless but wasteful — use `COPYFILE_DISABLE=1` and `dot_clean` ([Rockbox manual ch.4](https://download.rockbox.org/daily/manual/rockbox-ipodvideo/rockbox-buildch4.html)).
3. **Long names**: FAT32 LFN allows 255 chars per component; Rockbox `MAX_PATH` is 260 for the whole path — keep `Artist/Album/NN Title.flac` short.
4. **Battery / HDD**: on a stock HDD Rockbox does a full power-down + ~530 ms re-init per spin-up; reports on battery life are mixed ("some lose up to 30 %"); Rockpod's SSD-aware sleep only helps iFlash units ([rockpod](https://github.com/nuxcodes/rockpod), [Parts Plus Pods](https://partspluspods.com.au/2025/10/29/rockbox-on-the-ipod-classic-a-complete-guide/)).
5. **Current open issues (Rockpod tracker, Jul–Sep 2026)**: intermittent hold-switch bug, dock/car 30-pin not recognised, `.rockbox` corruption on power-down with some iFlash cards, USB-audio with some DACs ([rockpod issues](https://github.com/nuxcodes/rockpod/issues)). No open clickwheel/backlight bug on stock-HDD Classics that I could find; the old 6G "clickwheel dies" reports are hardware.
6. **Dual-boot**: default boots Rockbox; power on with **Hold engaged** boots the Apple firmware; MENU+SELECT reboots. Apple firmware, `iTunesDB` and Finder sync keep working alongside.
7. **Revert**: `mks5lboot --bl-uninst` (or Rockbox Utility → Uninstall bootloader) restores the Apple NOR boot; an iTunes/Finder **Restore** also returns the unit to stock "bootloader and all". Delete `/.rockbox` and `/Playlists` afterwards ([iFlash how-to](https://www.iflash.xyz/howto-install-rockbox-on-the-ipod-classics/), [mks5lboot](https://github.com/Rockbox/rockbox/tree/master/utils/mks5lboot)).

## 2. Maintained third-party managers on macOS (2026)

| Tool | Writes Classic `iTunesDB` + playlists? | Scriptable? | Price / last update | Verdict |
|------|-----|-----|-----|-----|
| **Swinsian 3** | **Yes** — drag tracks/playlists to the iPod, transcodes FLAC→ALAC; 3.0.3 (Oct 2025) fixed ALAC transcoding to iPods, 3.0.6 (Feb 2026) fixed transcoding on copy, 3.0.8 (16 Mar 2026) fixed removing tracks from iPod playlists. Needs "Enable disk use" and Full Disk Access ([changelog](https://swinsian.com/support/changelog/), [FAQ](https://swinsian.com/support/faq/)) | AppleScript covers playback, library playlists and `add tracks to playlist`; **no iPod/device object or copy/sync verb** ([scripting](https://swinsian.com/support/scripting/)) | **$34.95**, 3.0.8, macOS 10.13+; native Apple Silicon since 3.0 (Aug 2025) | Best GUI fallback; not automatable for the device step |
| **Music.app + Finder** | Yes (measured: this device's DB was written 14 Jun 2026 on Tahoe with Apple's own `DevicesVersion 1.6.4` prefs). Tahoe 26.0 broke the "Sync Settings" button; **26.1 (Nov 2025) fixed it** per user reports; Finder right-click → Sync also works ([Apple thread 256147797](https://discussions.apple.com/thread/256147797), [thread 256140059](https://discussions.apple.com/thread/256140059), [macReports](https://macreports.com/sync-settings-not-working-in-music-after-macos-tahoe-ios-26-update-how-to-fix/)) | Library side yes; **sync no** (§3) | Free | See §3 |
| **Doppler** (Brushed Type) | No — syncs to its own iOS app only; macOS 11+ ([Doppler docs](https://brushedtype.co/docs/doppler/sync-apps/)) | — | — | Not an iPod tool |
| **Strawberry** | libgpod-based on Linux; the **macOS 0.9.3 release has no iPod support**; only unsigned dev builds from builds.strawberrymusicplayer.org add it ([forum](https://forum.strawberrymusicplayer.org/topic/336/compile-strawberry-with-libgpod-to-access-ipod)) | No | Free | Not on macOS |
| **Clementine** | libgpod on Linux; first release since 2016 was Oct 2024; macOS builds historically shipped without libgpod ([wiki](https://github.com/clementine-player/Clementine/wiki/Portable-Devices)) | No | Free | Not on macOS |
| **foobar2000 iPod manager (foo_dop)** | **Windows 32-bit only** ([components](https://www.foobar2000.org/components/view/foo_dop)) | — | — | No |
| **MediaMonkey** | **Windows/Android only**; no macOS version ([Wikipedia](https://en.wikipedia.org/wiki/MediaMonkey)) | — | — | No |
| **Floola / YamiPod / SharePod** | Discontinued; 32-bit PowerPC/Intel-era binaries, will not launch on Tahoe ([Portable Freeware](https://www.portablefreeware.com/index.php?id=1200)) | — | — | Dead |
| **Diskoteca** (new, macOS 14+) | Syncs folder trees + **M3U8** to "any mounted volume" — i.e. **Rockbox** iPods, DAPs, USB; no `iTunesDB` writing that I can confirm ([diskoteca.com](https://www.diskoteca.com/)) | Not documented | €14.99 | Only relevant if you go Rockbox, and then `rsync` does the same |
| **iOpenPod** (PyPI, Python 3.11+) | Yes, writes `iTunesDB` incl. playlists, FLAC→ALAC | Yes (Python) | Free | **Other researcher's scope** — noted here only as the ranked #3 route |

## 3. Music.app as the writer — measured, and it decides the question

- **Library side is scriptable.** Music 1.6.6's dictionary has `make` (playlists), `add` (files → library/playlist), `delete`, `refresh`, `convert`, `export`. Creating playlists from our JSON and adding local files via JXA is straightforward and we already do reads.
- **Device side is not.** Measured on this Mac: source kinds are `library | audio CD | MP3 CD | radio tuner | shared library | iTunes Store | unknown` — **no `iPod` kind**; the command set is `add back track close convert count delete download duplicate exists export fast forward make move next track open location open pause play playpause previous track print quit refresh resume reveal rewind run save search select stop` — **no `update`, no `sync`, no `eject`**. `sources()` returns `Library` and `iTunes Store` only. `Finder.sdef` mentions iPods once (desktop icon setting) and has no sync verb. `AMPDevicesAgent`/`AMPDeviceDiscoveryAgent` are launchd agents with no argv interface (strings scan found none). Shortcuts has no "sync device" action. `devicectl` (Xcode CoreDevice) targets iOS 17+ devices only.
- **(a) Disk Mode vs normal boot does not change this.** The `iPod` source kind was removed when device sync moved from iTunes to Finder in Catalina; it is absent regardless of how the device is connected. Disk Mode is Apple's own recommended state for sync/restore, and Finder's agent identifies the Classic by USB VID/PID + SCSI inquiry, so it appears in Finder's sidebar in either mode (measured: `diskutil` reports `Media Type: iPod`). If the sidebar entry is missing on a given plug-in, the fix people report is re-plugging, restarting `AMPDeviceDiscoveryAgent`, or approving its permission dialog (Sequoia 15.5 introduced one) ([Apple thread 255978644](https://discussions.apple.com/thread/255978644)).
- **(b) The only automation hook is UI scripting** (System Events clicking Finder's device pane "Sync" button, needs Accessibility permission, breaks with every Finder redesign). That is not a supported path.
- **Verdict:** Music/Finder is a **GUI-only writer**. As a workflow it is "script the library, click Sync once" — zero-risk, but not the no-iTunes, hands-off pipeline the owner asked for. Late-2026 failure modes reported: device briefly appears then vanishes from Finder (26.0), Sync Settings button dead (26.0, fixed 26.1), FAT32 iPods occasionally offered "Restore" instead of sync (Sequoia 15.0–15.3, fixed 15.4/15.5). This device syncing cleanly on 14 Jun 2026 is the strongest evidence that on *this* Mac the path works today.

## 4. Formats and tags for the stock firmware

- **Native formats** (Apple spec, Late-2009 160 GB): "AAC (8 to 320 Kbps), Protected AAC, MP3 (8 to 320 Kbps), MP3 VBR, Audible (2, 3, 4, AAX, AAX+), Apple Lossless, AIFF, and WAV" ([Apple 112601](https://support.apple.com/en-us/112601)). **No FLAC.** ALAC plays **24-bit at 44.1/48 kHz**; **96 kHz and above is refused** ("not supported" on device); output is 16/44.1 anyway ([Apple Community](https://discussions.apple.com/thread/4917752), [iLounge](https://forums.ilounge.com/threads/ipod-classic-and-24-96.274807/)). Downsample 24/96 to 48 kHz or 44.1 before converting.
- **Conversion**: use ffmpeg (installed: 8.1.2), not `afconvert` — `afconvert` strips tags and up-converts 16-bit FLAC to 32-bit ALAC by default. Command that keeps Vorbis-comment tags and embedded art:
  `ffmpeg -i in.flac -map 0 -c:a alac -c:v copy -disposition:v attached_pic -map_metadata 0 out.m4a` (add `-ar 48000 -sample_fmt s32p` for 96 k sources) ([salivity](https://salivity.github.io/ffmpeg/article/convert-flac-to-alac-m4a-using-ffmpeg), [Picmal on afconvert](https://picmal.app/blog/convert-flac-to-alac-mac)).
- **Tag landmines**: the Classic's *Artists* menu keys on **Artist, not Album Artist** — a "Various Artists" album artist does *not* group a compilation; only the **"Album is a compilation" flag** does, and it must be set on every track or the album splits ([Apple Community 6699735](https://discussions.apple.com/thread/6699735), [7579565](https://discussions.apple.com/thread/7579565)). Keep Album exact-identical per track (whitespace/case), set Sort fields consistently, and for Beatport/Bandcamp singles decide once whether "Artist – Title" singles get a synthetic Album or the compilation flag.

## 5. Risk register

| Route | What can go wrong | Reversible? | Recovery |
|---|---|---|---|
| **Rockbox** | DFU flash interrupted/failed (unit sits in DFU, black screen); wrong bootloader for firmware (**do not** dual-boot on Apple fw 2.0.2 — use 2.0.4/2.0.5 or 1.1.2); filesystem corruption if USB used in Rockbox with an incompatible iFlash card (n/a on stock HDD); NFD/NFC playlist misses; battery life worse on HDD | Yes | Hold-switch boots Apple fw; `mks5lboot --bl-uninst`; Finder **Restore** rewrites NOR and disk to stock. DFU is re-enterable by MENU+SELECT, so a bad flash is retried, not bricked (freemyipod, Olsro) |
| **Swinsian** | GUI-only device ops; transcoding bugs (three fixed in the last year); DB written by a third party could mis-set the checksum on 6G/7G → "empty library" | Yes | Restore `iPod_Control/iTunes/iTunesDB` from backup; on-device auto-backup sometimes exists as `iTunesDB.old_mlpmp` / `iT.tmp` ([copytrans](https://www.copytrans.net/support/how-do-i-repair-a-corrupt-ipod-library/)) |
| **Music.app + Finder** | Device not recognised after an OS update (26.0, 15.0–15.3 precedents); "Restore?" prompt on a healthy FAT32 iPod — never accept it casually (it erases); Music may re-encode/insist on library ownership | N/A | Wait for the point release or use Finder right-click Sync; restore only from a full `iPod_Control` backup |
| **Hand-written DB** | Wrong hash → device shows empty library or reboots; wrong `mhbd` version/field widths; artwork DB mismatch | Yes | Copy the backed-up `iTunesDB`, `iTunesPrefs*`, `Extras.itdb`, `Play Counts` back over USB — the firmware re-reads on the next boot. Finder Restore is the nuclear option and does work for Classics on Tahoe-era Finder when the device is recognised |

Common prerequisite for every route: a dated copy of `/Volumes/IPOD/iPod_Control/iTunes/` and `/iPod_Control/Device/` before the first write.

## 6. Ranking and effort (summary of the table on top)

1. **Rockbox** — 1–2 h install, then `rsync` + generated `.m3u8`; the only route where the playlist store is text and FLAC needs no transcode. Risk concentrated in one DFU flash; dual-boot keeps everything else. Open question to close first: which generation (Settings > About), and confirm `mks5lboot` builds on Tahoe (`brew install libusb`; `make` in `utils/mks5lboot`).
2. **Music.app scripted + manual Finder Sync** — ~1 h to wire JXA from our JSON; zero device risk; one human click per sync; requires FLAC→ALAC conversion into the Music library (Music imports ALAC, not FLAC).
3. **Write the DB ourselves / iOpenPod / libgpod** — days, and every write is a checksum gamble; only justified if the owner rejects both Rockbox and the manual click.
4. **Swinsian** — buy-and-drag; not scriptable; fine as an occasional GUI tool.

## Sources

- https://files.freemyipod.org/~user890104/bootloader-ipodclassic.html — bootloader install, models, FAT32, iFlash/USB caveats
- https://github.com/Rockbox/rockbox/tree/master/utils/mks5lboot — CLI options, macOS build
- https://github.com/Rockbox/rockbox/blob/master/utils/rbutilqt/base/bootloaderinstalls5l.cpp — Rockbox Utility's Classic installer
- https://github.com/Rockbox/rockbox/blob/master/firmware/target/arm/s5l8702/ipod6g/storage_ata-6g.c — CE-ATA/PATA support
- https://raw.githubusercontent.com/Rockbox/rockbox/master/apps/playlist.c — playlist path rules
- https://www.howtogeek.com/rockbox-4-0-custom-firmware-mp3-players-old-ipods/ and https://hackaday.com/2025/04/19/rockbox-4-0-released/ — Rockbox 4.0
- https://en.wikipedia.org/wiki/Rockbox — codec list
- https://kinbiko.com/posts/2026-02-01-rockbox-ipod-classic-iflash-linux-sector-size/ — sector-size odyssey
- https://github.com/nuxcodes/rockpod and https://github.com/nuxcodes/rockpod/issues — active fork, current gotchas
- https://www.iflash.xyz/howto-install-rockbox-on-the-ipod-classics/ — uninstall via iTunes restore
- https://wnderlvst.com/stories/install-rockbox-for-ipod-classic-on-apple-silicon-mac-be514e3a-7ffd-42d7-b95b-21b50443ac09 — Apple Silicon walkthrough
- https://www.ifixit.com/Guide/How+to+install+Rockbox+on+an+iPod+Classic/114824
- https://partspluspods.com.au/2025/10/29/rockbox-on-the-ipod-classic-a-complete-guide/
- https://www.diskoteca.com/guides/sync-music-rockbox-ipod-mac/ and https://www.diskoteca.com/
- https://github.com/h0fnar/m3u8-converter — macOS/Rockbox Unicode mismatch
- https://github.com/navidrome/navidrome/issues/4663 — NFD vs NFC on macOS FAT32
- https://download.rockbox.org/daily/manual/rockbox-ipodvideo/rockbox-buildch4.html — file browser / hidden files
- https://github.com/Olsro/reddit-ipod-guides/blob/main/guides/ipod6g-flash-more-recent-firmwares.md — firmware ↔ hardware map
- https://support.apple.com/en-us/103823, https://support.apple.com/en-us/112601, https://support.apple.com/kb/SP572?locale=en_US, https://everymac.com/systems/apple/ipod/specs/ipod-classic-6th-generation-specs.html — identification, formats, dimensions
- https://www.rockbox.org/tracker/task/12728 — PID 0x1261
- https://swinsian.com/support/changelog/, https://swinsian.com/support/faq/, https://swinsian.com/support/scripting/, https://swinsian.com/
- https://discussions.apple.com/thread/256147797, https://discussions.apple.com/thread/256140059, https://discussions.apple.com/thread/255978644, https://macreports.com/sync-settings-not-working-in-music-after-macos-tahoe-ios-26-update-how-to-fix/ — Tahoe/Sequoia sync behaviour
- https://forum.strawberrymusicplayer.org/topic/336/compile-strawberry-with-libgpod-to-access-ipod, https://github.com/clementine-player/Clementine/wiki/Portable-Devices
- https://www.foobar2000.org/components/view/foo_dop, https://en.wikipedia.org/wiki/MediaMonkey, https://www.portablefreeware.com/index.php?id=1200, https://brushedtype.co/docs/doppler/sync-apps/
- https://discussions.apple.com/thread/4917752, https://forums.ilounge.com/threads/ipod-classic-and-24-96.274807/ — ALAC 24/48 limit
- https://discussions.apple.com/thread/6699735, https://discussions.apple.com/thread/7579565 — Album Artist / compilation flag
- https://salivity.github.io/ffmpeg/article/convert-flac-to-alac-m4a-using-ffmpeg, https://picmal.app/blog/convert-flac-to-alac-mac — conversion
- https://www.copytrans.net/support/how-do-i-repair-a-corrupt-ipod-library/ — iTunesDB backup recovery
- Local measurements: `/System/Applications/Music.app/Contents/Resources/com.apple.Music.sdef`, `Finder.sdef`, `ioreg -p IOUSB`, `diskutil info disk26`, `ls /Volumes/IPOD/iPod_Control/`
