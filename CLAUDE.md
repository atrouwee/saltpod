# CLAUDE.md

Context for Claude Code sessions in this repository.

## Start here

**[HANDOFF.md](HANDOFF.md) for what is true right now** — what is proven on
hardware, what is not, and what to run. Then `research/` for why: the format
notes and the device tests are the record of how this arrived where it is.

## What this is

**saltpod** — playlists on an iPod Classic without iTunes. Curate in a local
page, sequence by ear, sync to the device. The `iTunesDB` is edited in place
and signed with the checksum the Classic's firmware requires. It is a small
tool for one kind of device; keep it that way.

## Working conventions

- Python 3.9 or newer, standard library only, plus `ffmpeg`/`ffprobe`. No
  dependency is added without a reason written in the commit.
- One command, `saltpod`, plain argparse, verbs with help written as a
  sentence. Run bare it opens the page.
- The page is one file, no build step, nothing fetched from anywhere. The
  design tokens are PlayPi's; the orange appears exactly once.
- Output is a receipt: an amber mark, a label, the fact. When the tool is
  busy something on screen moves. Piped output stays plain.
- Prose, in docs and in output: plain, no emoji, no exclamation marks.
- Never regenerate the database; edit it in place. Never invent a structure;
  clone one the firmware already accepted. Sync never wipes what it was not
  told about. Backup before every write.
- A device write is proven by the device, not by a parser. `research/DEVICE-TEST.md`
  records each one, with a photograph.
