"""How the tool talks. Ported from saltgate's walkthrough, kept small.

Three rules, all from there:
  * a line the tool prints is a receipt: an amber mark, a label, the fact;
  * whenever the tool is busy something on screen must be MOVING -- a label
    that merely sits there reads as a hang;
  * dress the output only when a human is watching. Piped or redirected
    output stays plain, so logs and `less` do not fill with escape codes.
"""
import os
import sys
import threading

AMBER, GREY, RED, GREEN, BOLD, RESET = ("\033[38;5;214m", "\033[38;5;245m", "\033[38;5;203m",
                                        "\033[38;5;114m", "\033[1m", "\033[0m")
SPIN = "◐◓◑◒"
COL = 10                                   # width of the label column


def interactive():
    return sys.stdout.isatty() and os.environ.get("TERM", "") not in ("", "dumb")


def _c(code, text):
    return f"{code}{text}{RESET}" if interactive() else text


def receipt(label, text, tone="accent"):
    """`◆ label      text` -- the unit of output."""
    mark = _c(AMBER if tone == "accent" else RED if tone == "bad" else GREEN if tone == "good" else GREY, "◆")
    print(f"  {mark} {_c(GREY, label.ljust(COL))} {text}")


def out(text=""):
    print(f"  {' ' * COL}  {text}" if text else "")


def note(text):
    print(f"  {' ' * COL}  {_c(GREY, text)}")


def step(title):
    print(f"\n{_c(BOLD, title)}")


def fail(text, *details):
    print(f"\n  {_c(RED, '!!')} {text}", file=sys.stderr)
    for d in details:
        print(f"      {d}", file=sys.stderr)
    sys.exit(1)


def options(items, per_row=3, default=0, tags=None, legend=None):
    """A numbered menu, `[n]` per item, three to a row, with a status tag.

        [1] Curate  beta     [2] Plan    ok       [3] Sync    ok

    Returns the chosen key. Non-interactive callers get the default.
    """
    tags = tags or {}
    if not interactive():
        return items[default][0]
    width = max(len(lbl) for _, lbl in items) + 2
    for i in range(0, len(items), per_row):
        row = ""
        for j, (key, lbl) in enumerate(items[i:i + per_row], i + 1):
            tag = tags.get(key, "")
            row += f"  {_c(AMBER, f'[{j}]')} {lbl.ljust(width)}{_c(GREY, tag.ljust(12))}"
        print(row)
    if legend:
        note(legend)
    while True:
        ans = input(f"  {_c(GREY, f'[{default + 1}]')} ").strip()
        if not ans:
            return items[default][0]
        if ans.isdigit() and 1 <= int(ans) <= len(items):
            return items[int(ans) - 1][0]


class Spinner:
    """A moving glyph on one line, started and stopped explicitly."""

    def __init__(self, label):
        self.label = label
        self._stop = threading.Event()
        self._t = None

    def __enter__(self):
        if interactive():
            self._t = threading.Thread(target=self._loop, daemon=True)
            self._t.start()
        return self

    def _loop(self):
        i = 0
        while not self._stop.is_set():
            sys.stdout.write(f"\r  {AMBER}{SPIN[i % 4]}{RESET} {GREY}{self.label}{RESET}   ")
            sys.stdout.flush()
            i += 1
            self._stop.wait(0.15)

    def __exit__(self, *a):
        self._stop.set()
        if self._t:
            self._t.join(timeout=1)
            sys.stdout.write("\r" + " " * 80 + "\r")
            sys.stdout.flush()
