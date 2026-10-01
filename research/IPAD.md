# The iPad question

**Status: no MEASURED section.** This machine has no iPad and no cable to put
one next to the iPod. Every claim below is either **RESEARCHED FROM SOURCES**
-- found in Apple's own documentation, a developer forum, a shipping app, or
this repo's own code, cited inline -- or marked **PROPOSED**, meaning it is an
architecture suggestion, not a verified fact. Where the research turned up
nothing either way, that is said plainly rather than guessed at.

## The two propositions

The owner, on being asked whether the native app (`research/NATIVE-APP-SPEC.md`)
should extend to iPad: *"I still am open to an iPad as it can be a great way
to manage/curate playlists already on the iPod, but also allows for
additional external storage so technically the whole thing could work there
too."*

That is two different products and they do not share a verdict:

- **(A) iPad as a client.** The iPod stays plugged into the Mac. The server
  runs on the Mac, same as today. The iPad runs a SwiftUI app that talks to
  that server over the LAN. Nothing about the layer rule changes -- the iPad
  is a fourth caller of `/api/*`, same shape as the page and the native Mac
  app (`research/NATIVE-APP-SPEC.md`'s Phase 1-4).
- **(B) iPad as the whole thing.** The iPod and a library drive both plug
  into the iPad over USB-C. The server -- Python today, Swift if
  `NATIVE-APP-SPEC.md`'s rewrite happens -- runs on iPadOS itself, and the
  iPad's own WKWebView or a native UI is the only client there is.

(A) is a restatement of work already specced. (B) is a different machine
entirely: it asks whether iPadOS's sandbox will let an app do to a USB disk
what this project has only ever done from a Mac.

## (A) iPad as a client

### What the layer rule asks of it

`publish/CONTRIBUTING.md`: *"a client may look things up, it may not work
them out."* An iPad client changes nothing about that contract -- it needs
the same `/api/tracks`, `/api/decide`, `/api/undo` the page and the Mac app
already use. The only new requirement is that the **server be reachable**,
not that the device be present. The iPod stays plugged into the Mac; the
iPad never touches it.

### Reaching the server: Bonjour and plain HTTP

Two solved problems, both well inside iOS's standard toolkit:

- **Discovery.** Since iOS 14, any connection to an address on the local
  subnet requires the user's Local Network permission, surfaced via
  `NSLocalNetworkUsageDescription`, and Bonjour/mDNS browsing additionally
  needs the service type declared in `NSBonjourServices`
  ([Apple Developer Forums, Local Network Privacy FAQ](https://developer.apple.com/forums/thread/663775);
  [nilcoalescing.com](https://nilcoalescing.com/blog/GettingReadyForNewiOS14LocalNetworkPrivacyRestrictions/)).
  This is a one-time permission prompt, not a blocker -- every AirPlay and
  network-printer app on iPad clears the same bar.
- **Plain HTTP to a local address.** App Transport Security blocks `http://`
  by default, but `NSAllowsLocalNetworking` in `Info.plist` exempts
  `.local` hostnames and local addresses specifically, without opening the
  app to arbitrary remote HTTP
  ([Apple's Cocoa Keys reference](https://developer.apple.com/library/archive/documentation/General/Reference/InfoPlistKeyReference/Articles/CocoaKeys.html)).

`research/NATIVE-APP-SPEC.md` already verified that `NWListener` from
Network.framework answers `GET /api/tracks` with no dependency, and that it
compiles to a 68 KB binary. `NWListener` also supports advertising itself as
a Bonjour service in the same framework call -- **PROPOSED**: the Mac's
Swift server advertises `_saltpod._tcp` on the LAN the moment it starts,
and the iPad app browses for exactly that service type. This was not
measured here, but it is the same API family already proven to serve HTTP,
not a new dependency.

### Sharing the Mac's code: multiplatform, not Catalyst

Mac Catalyst runs an iPad app's UIKit code *on* the Mac -- the wrong
direction for a tool whose Mac client is being specced in SwiftUI with
`Table`, `.inspector()` and `contextMenu(forSelectionType:)`
(`research/NATIVE-APP-SPEC.md`). The fit here is a **SwiftUI multiplatform
target**: one app target, multiple destinations, sharing the model and
networking layer by default and conditionalizing only the UI
([WWDC22, "Use Xcode to develop a multiplatform app"](https://developer.apple.com/videos/play/wwdc2022/110371/);
[vp0.com comparison](https://vp0.com/blogs/swiftui-macos-catalyst-app-template)).
**PROPOSED:** the HTTP client, the undo-stack proxy and the view models stay
one Swift module; only the top-level view swaps `Table` for `NavigationSplitView`
+ `List`, same as the Mac app already swaps `Table` in for what the browser
built from scratch.

### Touch, and "nothing is drag-only"

The product's design law 7, `publish/DESIGN.md`: *"Every drag has a menu
equivalent. Dragging is faster once you know it; a menu is how you find out
it is possible."* This was written for a mouse-and-trackpad page, but it
turns out to already answer the touch question, because the web client does
not actually rely on `HTMLElement` drag events for its central claim.
Reordering a collection goes through `nudge(dir)` in
`src/saltpod/curate.html` (line 1469): it moves the selected row one place
in `ORDER[col]` and posts `{reorder: {collection, keys}}` to `/api/decide`
-- today reachable only by the `J`/`K` keyboard shortcuts
(`src/saltpod/curate.html` lines 3107-3108), with **no on-screen button**.
That endpoint is the same one a drag-and-drop reorder calls.

So the contract already has a drag-free way to change sequence; the web
client just never built a visible control for it, because a keyboard was
always in the room. An iPad client needs one: explicit **Move Up / Move
Down** affordances (or a "Move to position" sheet) wired to the same
`reorder` call `nudge()` already makes, not a reimplementation of the rule.

This also sidesteps a real gap in the platform. SwiftUI's `List` reordering
(`.onMove`, `EditMode`) is a drag gesture with no built-in non-drag
alternative: VoiceOver users lost even the old "move up/move down" custom
actions between iOS 15 and 16, and the framework still has no shipped
replacement
([Apple Developer Forums, "the reorder button in the list that state on edit mode"](https://developer.apple.com/forums/thread/743351);
[mobilea11y.com](https://mobilea11y.com/guides/swiftui/swiftui-sort-priority/)).
Building the iPad client's reordering control as an explicit button pair
against `/api/decide` -- rather than leaning on `.onMove` -- is therefore
not just consistent with law 7, it is the only path that is not already a
known accessibility regression in the framework.

### What the Mac app already settled, reused here

| question | Mac app answer (`NATIVE-APP-SPEC.md`) | applies to iPad client |
|---|---|---|
| format code in the client? | no -- stays server-side | same |
| undo stack | server-side, `UndoManager` proxies it | same |
| contract | 23 HTTP endpoints, reorder already one of them | same |
| what's new | `Table`, `.inspector()`, `contextMenu` | `List`, `.sheet()`, no multi-window inspector pattern on compact iPad widths |
| sequence control | not yet decided | **must be an explicit button, not `.onMove`** (above) |

### Verdict (A)

**Build it. It is close to free given the Mac app work already specced.**
The only genuinely new pieces are Bonjour advertisement on the server (small,
same framework already verified) and an explicit reorder control (which the
contract already supports and the web client already half-built as a
keyboard shortcut). The remaining condition is the one `NATIVE-APP-SPEC.md`
already names: the Mac has to be the one with the iPod plugged in, awake,
and running the server -- a `LaunchAgent`, or a terminal left open, same as
today. An iPad client adds no new requirement on that score; it just adds a
second screen that needs the first machine to be alive.

## (B) iPad as the whole thing

### What iPadOS documents about external storage

Apple's own support article states the requirement plainly: *"An external
storage device must have only a single data partition, and it must be
formatted as APFS, APFS (encrypted), macOS Extended (HFS+), exFAT (FAT64),
FAT32, or FAT"*
([Apple Support, "Connect external storage devices to iPad"](https://support.apple.com/guide/ipad/external-storage-devices-ipad75b7b23f/ipados)).
Filesystem support arrived in stages:

| filesystem | arrived | read/write |
|---|---|---|
| HFS+, APFS, APFS (encrypted) | iPadOS 14 | read/write |
| exFAT, FAT32 | iPadOS 15 | read/write |
| NTFS | iPadOS 15 | **read-only** |
| FAT | iPadOS 13 (original Files-app external-storage support) | read/write |

([Seagate/LaCie knowledge base](https://www.seagate.com/support/kb/lacie/ipados-external-storage-supported-functions/))

A mounted volume shows up under **Locations** in the Files sidebar, the same
place iCloud Drive and SMB shares appear, on iPadOS 16 and later
([elluminetpress.com](https://elluminetpress.com/2023/09/connecting-an-external-drive-to-an-ipad/)).
An older, more informal FAQ from the iOS 13 era claims iOS can in fact mount
*"all non-encrypted file systems supported by the Mac's Disk Utility"* --
broader than Apple's current official list, but it is a journalist's
paraphrase, not a primary source, and it is six years old
([TidBITS, "USB Storage with iOS 13: The FAQ"](https://tidbits.com/2019/10/16/usb-storage-with-ios-13-the-faq/)).
Treat the official list as the floor and that line as unconfirmed upside.

Power: *"The iPad provides up to 7.5W of power delivery to connected
devices"*, and the same page warns that extended use drains the iPad's own
battery faster
([Seagate/LaCie](https://www.seagate.com/support/kb/lacie/ipados-external-storage-supported-functions/)).
At least one bus-powered external drive owner on the TidBITS comment thread
above reports needing a powered USB hub even through Apple's own Camera
Adapter. The iPod Classic has a spinning 1.8" hard drive, not flash, and
historically ran fine on a plain USB 2.0 port's 2.5 W bus power when syncing
from a Mac or PC -- so 7.5 W from an iPad should be generous rather than
marginal, but this is an inference, not a measurement.

### The iPod Classic specifically

What is known, some of it from this repo's own prior research:

- The Classic is formatted **HFS+** if it was first synced on a Mac, or
  **FAT32** if first synced on a PC -- both on Apple's supported list, and
  it presents a **single visible data partition** to the host OS either way
  ([forums.macrumors.com, "iPod Classic = FAT-32?"](https://forums.macrumors.com/threads/ipod-classic-fat-32.428433/)).
  The format question that matters for iPadOS is therefore almost certainly
  already settled, whichever way this specific unit was formatted.
- On macOS, `diskutil` reports `Media Type: iPod` and Finder identifies the
  Classic "by USB VID/PID + SCSI inquiry" (`research/alternatives.md`, line
  92) -- that is, the device answers a standard SCSI INQUIRY command with
  vendor/product strings its own firmware supplies, which is ordinary USB
  mass-storage behaviour, not an Apple-proprietary back channel. That is
  suggestive that iPadOS's external-storage stack, which shares its USB and
  mass-storage layers with macOS, would see the same device the same way --
  but Disk Arbitration and Finder's volume-mounting path on macOS is not the
  same code as the Files app's external-storage path on iPadOS, and nothing
  found here confirms the two behave identically for a 2007-2009-era device.
- **No source found, in either direction, reports plugging an iPod Classic
  (or any legacy USB mass-storage media player) into an iPad and seeing it
  in Files.** Every success story found in this research is a USB flash
  drive or SSD, freshly formatted by a computer specifically for this use.
  That silence is not evidence against it -- it may simply be an untried
  pairing -- but it means proposition (B) currently rests on an inference
  from documentation about a different class of device, not a confirmed
  case.

### How a third-party app would get read-write access

The mechanism exists and is demonstrated, independent of the iPod question:

- `UIDocumentPickerViewController` can be presented for `.folder` content
  types; the user picks a folder (including one inside an external volume
  shown in Files), and with `asCopy: false` the app gets the **original**
  URLs rather than copies placed in an Inbox
  ([gitconnected, "Swift/iOS: File Import and Export 3 ways"](https://levelup.gitconnected.com/swift-ios-file-import-and-export-choose-destination-folder-filename-and-save-to-files-app-3-ways-240770633fe1)).
- Calling `startAccessingSecurityScopedResource()` on that folder URL, then
  enumerating with `FileManager.enumerator(at:)`, reaches every file beneath
  it -- confirmed working for a nested folder tree by an Apple DTS engineer
  on the developer forums, albeit in an iCloud Drive example, not an
  external-volume one
  ([Apple Developer Forums, "Access all files in UIDocumentPickerController while picking folder"](https://developer.apple.com/forums/thread/734738)).
- This is the exact mechanism third-party apps already use for USB drives
  specifically: FE File Explorer markets itself on viewing, copying, moving,
  renaming and deleting files directly on a connected USB drive or SD card,
  not only copying them into the app first
  ([FE File Explorer Pro, App Store listing](https://apps.apple.com/us/app/fe-file-explorer-pro/id499470113)).
- Python interpreters on iPadOS get no shortcut around any of this. Pyto's
  own documentation describes exactly the same bookmark mechanism --
  *"Establishing the bookmark is done through user interaction... Pyto then
  keeps track of the file and handles the permissions"*
  ([Pyto file_system docs](https://pyto.readthedocs.io/en/latest/library/file_system.html)).
  There is no private API these apps use that a plain Swift app cannot.

So the general capability -- pick a folder on an external volume, get
read-write to everything under it, including a database file you rewrite in
place -- is real and demonstrated for USB mass-storage devices in general.
It is not demonstrated for *this* device, because that depends on the open
question above: whether the iPod ever appears as a folder to pick in the
first place.

### Two caveats the research did not resolve

- **Volume of small writes.** A sync here means thousands of file writes
  into `iPod_Control/Music` plus one in-place rewrite of the iTunesDB.
  Apple's own guidance for external and networked volumes is only a general
  caution -- *"reading or writing files stored on USB drives can be slow...
  apps should always perform file system operations on a background queue"*
  -- with no published numbers for how many coordinated writes per second a
  `NSFileCoordinator`-mediated external volume actually sustains. Nothing
  found here says this is fine, and nothing found here says it is not;
  `bin/device_test.sh rehearse` already proves the Mac path is fast because
  it uses ordinary POSIX file I/O against a locally-mounted disk, which is
  not the API an iPadOS app would be forced to use.
- **No headless mode.** `research/NATIVE-APP-SPEC.md` lists three ways to
  keep the Mac server running without a visible window, from a spawned
  child process up to a `LaunchAgent` that survives reboots with no app
  open. iPadOS has nothing equivalent: `beginBackgroundTask` grants roughly
  30 seconds after the app leaves the foreground, not enough to carry a
  bulk sync, and `BGProcessingTask` is an OS-scheduled, typically-overnight
  grant, not an on-demand one
  ([Apple Developer Forums background-task discussion](https://developer.apple.com/forums/thread/695910)).
  In practice this means every sync on an iPad-as-the-whole-thing design has
  to run start-to-finish with the app open and the screen awake -- survivable
  for a user-initiated sync, but it rules out the "leave it running and come
  back" pattern the Mac's `LaunchAgent` option offers.

### Verdict (B)

**Undetermined, not disproven, and not worth designing further until the
one open fact is settled.** Every documented capability needed downstream of
"the iPod mounts" -- read-write via a folder picker, in-place editing, even
Python interpreters that could run the existing server code -- is real and
already demonstrated for USB mass-storage devices in general. The entire
proposition stands or falls on a single fact this research could not find
evidence for in either direction: does iPadOS's Files/external-storage stack
actually mount a 2007-2009 iPod Classic in disk mode as a browsable volume.
Nobody has published that they tried it. Do not write a line of iPad-native
storage code before finding out.

## The one experiment that settles (B)

Everything else here is downstream of this single check, and it costs five
minutes and a cable:

1. Put the iPod Classic into disk mode (as this project already does for
   every Mac-side test).
2. Connect it to the iPad -- a USB-C hub or dock with a USB-A port will be
   needed, since the Classic uses the old 30-pin dock connector.
3. Open the **Files** app on the iPad and check the sidebar under
   **Locations**.

If the iPod does not appear there at all, proposition (B) is dead and there
is nothing further to test -- no third-party app can see a volume the
system itself does not mount. If it does appear:

4. Tap into it and confirm `iPod_Control/Music` is browsable.
5. Create a new empty folder or a small text file inside it from the Files
   app itself, to confirm the mount is read-write and not read-only.

That five-step test, done once, turns the entire verdict on (B) from
"undetermined" into either "dead" or "worth a real prototype" -- and it
requires nothing this repo does not already have except the iPad and a USB-C
hub.

## Summary

| | (A) iPad as a client | (B) iPad as the whole thing |
|---|---|---|
| what's proven | the whole mechanism -- it is the Mac app's own contract, reused | the general USB mass-storage read/write mechanism, for *other* devices |
| what's open | Bonjour advertisement (small, same framework already verified); an explicit reorder control | whether iPadOS mounts the iPod Classic at all |
| the blocking fact, if any | none found | whether `research/alternatives.md`'s "USB VID/PID + SCSI inquiry" identification that works in macOS's Disk Arbitration also triggers iPadOS's Files external-storage path -- unconfirmed either way |
| headless / unattended | not needed -- the Mac is already the thing left running | not available on iPadOS; every sync must run foreground, screen-awake, start to finish |
| recommendation | build it, after the Mac app's contract is in place | run the five-minute Files-app test above before any design work |
