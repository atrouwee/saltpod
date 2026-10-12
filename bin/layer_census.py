#!/usr/bin/env python3
"""Does the front end still only render, or has it started deciding?

THE BOUNDARY, in one line: **a client may look things up; it may not work
them out.** Membership of a named list is a lookup. Deciding what belongs in
that list is a rule, and rules live on the server.

Why it matters more than tidiness: the native app is a second client and
anything that reads the HTTP API is a third. A rule spelled out in the page
is a rule that has to be spelled out again in Swift, and once more after
that -- three implementations of one sentence, drifting apart quietly.

This is the same instrument as the design system's token census. It does
not prove the boundary holds; it notices when it moves, which is the part
nobody does by eye.

    python3 bin/layer_census.py          # report
    python3 bin/layer_census.py --strict # exit 1 if anything is over budget
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, 'src', 'saltpod', 'curate.html')

# A rule has a shape: it reads two or more facts about a track and combines
# them into a verdict. One fact read on its own is a lookup, and fine.
RULES = [
    ('multi-field verdict',
     r"t\.\w+\s*&&\s*!?t\.\w+|!t\.\w+\s*&&\s*!?t\.\w+",
     "two track fields combined -- the server should answer this and send the answer"),
    # `return true` and `return t.vinyl` are lookups; anything that reads a
    # second thing to decide is a rule.
    ('filter predicate',
     r"if\s*\(\s*filter\s*===?\s*'[^']+'\s*\)\s*return\s+(?!true;|t\.\w+;|\(t\.lists)",
     "a filter deciding membership instead of reading t.lists"),
    ('tier compared to a literal',
     r"tier\s*===?\s*'(sync|remove|undecided)'\s*&&",
     "a decision combined with something else -- that combination is a rule"),
    ('price or size arithmetic',
     r"reduce\(\(a,\s*t\)\s*=>\s*a\s*\+",
     "a total computed from rows; the server knows the total"),
    # Debt D3 and D4 (NATIVE-PLAN 3.4): a row's law-3 state and what it
    # plays were worked out from `device || local`, `device || reachable`
    # and `if(t.audio)`. They are `t.state` and `t.play` now.
    ('row state or playback worked out',
     r"t\.device\s*\|\|\s*t\.(?:local|reachable)|if\s*\(\s*t\.(?:audio|preview)\s*\)",
     "read t.state / t.play (curate.row_state, curate.row_play)"),
    # Debt D2: the track menu's decision row -- which verb, whether it is
    # already made, and the tier it sets -- was a nested ternary over
    # device/held/tier and a `tier: onPod && !anyCol ? ...` literal.
    ('decision worked out',
     r"\?\s*\(\s*offPod|\?\s*'undecided'\s*:\s*'sync'|\bheld\s*\?\s*\(",
     "read the row's decision (curate.decision_of) or ask /api/decision"),
    # Debt D6: the order of "All on iPod" -- a sort by the client's own
    # collation, which no other client shares. It is `on_ipod_order` now.
    ('device list sorted here',
     r"filter\(\s*t\s*=>\s*t\.device\s*\)\.sort\(",
     "read on_ipod_order (curate.on_ipod_order)"),
    # Debt D8, D9: the buy pane's stages and the vinyl pane's to-do were
    # filtered and matched in the page (bc_verdict, OWN/WANT, vkey).
    ('pane stage worked out',
     r"filter\(\s*t\s*=>\s*t\.bc_verdict|(?:OWN|WANT)\.has\(|\bvkey\(",
     "read the 'synced', 'FLAC to buy', 'not looked up', 'vinyl to add' lists"),
    # Debt D10: sync progress parsed out of the log's last 60 lines.
    ('job log parsed',
     r"match\(\s*/\^@@",
     "read job.steps (curate.Job.step_line), complete and settled"),
    # Debt D5: which Apple Music cloud statuses mean owned.
    ('cloud status list',
     r"'purchased'|AM_OWNED",
     "read am_owned / am_status off the row (curate.am_row_answers)"),
]

# What is already there and accepted, with a reason. A number that only ever
# goes down.
# Each number is a promise, with a reason, and only ever goes down.
BUDGET = {
    # Was 6, labelled "row rendering" -- but five of the six were the Sync
    # button's count (offs, ons, waiting, and the off count again in the
    # data panel), which is a rule, not rendering. Those are the server's
    # now (curate.sync_counts, debt D1), and the sixth, the buy pane's "not
    # looked up yet" count, is the 'not looked up' list (D8).
    'multi-field verdict': 0,
    # `all` and `vinyl` are lookups; the pattern below already lets those by
    'filter predicate': 0,
    # "everything marked sync that is not already in THIS collection" --
    # parameterised by a collection the server does not know you are looking
    # at. A selection for an action, not a list anyone is shown.
    'tier compared to a literal': 2,
    # minutes of whatever the centre pane is currently showing: a sum over
    # the CLIENT's view, which the server has no opinion about
    'price or size arithmetic': 1,
    'row state or playback worked out': 0,
    'cloud status list': 0,
    'decision worked out': 0,
    'device list sorted here': 0,
    'pane stage worked out': 0,
    'job log parsed': 0,
}


def inline_js(path):
    s = open(path).read()
    blocks = re.findall(r'<script>(.*?)</script>', s, re.S)
    return blocks[-1] if blocks else ''


def main(argv):
    strict = '--strict' in argv
    js = inline_js(PAGE)
    # comments explain rules; they are not rules
    js = re.sub(r'//[^\n]*', '', js)
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)

    print('front end: %s' % os.path.relpath(PAGE, ROOT))
    print('%d lines of inline script\n' % js.count('\n'))
    over = []
    for name, pat, why in RULES:
        hits = re.findall(pat, js)
        budget = BUDGET.get(name, 0)
        flag = 'ok ' if len(hits) <= budget else '** '
        if len(hits) > budget:
            over.append((name, len(hits), budget))
        print('  %s%-28s %2d  (budget %d)' % (flag, name, len(hits), budget))
        if len(hits) > budget:
            print('       %s' % why)

    # ---- the other half of the boundary: two adapters, one implementation
    #
    # A SECOND CALLER IS THE PROOF AN ENDPOINT IS A BOUNDARY. An operation
    # only the page can reach is a function that happens to be addressable
    # over HTTP; one the terminal reaches too has a shape that survived
    # contact with a client that is not a browser. Five operations had no
    # verb and they were the five newest, which is how the gap always opens.
    cli = open(os.path.join(ROOT, 'src', 'saltpod', 'cli.py')).read()
    verbs = set(re.findall(r'sub\.add_parser\("([a-z_]+)"', cli))
    api = set(re.findall(r"u\.path == '/api/([a-z_]+)'",
                         open(os.path.join(ROOT, 'src', 'saltpod', 'curate.py')).read()))
    ops = set()
    try:
        sys.path.insert(0, os.path.join(ROOT, 'src'))
        from saltpod import curate as _C
        ops = {k.rsplit('/', 1)[-1] for k in _C.OPS}
        api |= ops
    except Exception as e:
        print('\n  (could not import the operations registry: %s)' % e)
    print('\n  operations     : %s' % (' '.join(sorted(ops)) or '(none found)'))
    print('  cli verbs      : %s' % ' '.join(sorted(verbs)))
    print('  http endpoints : %s' % ' '.join(sorted(api)))
    orphans = sorted(ops - verbs)
    if orphans:
        print('\n  ** operations the terminal cannot reach: %s' % ' '.join(orphans))
        print('     every entry in curate.OPS needs a verb in cli.py, or the')
        print('     native app becomes the first client to find out it is missing')
        over.append(('operations without a cli verb', len(orphans), 0))
    else:
        print('  every operation has a verb — both adapters reach the same code')

    # ---- D13: every key /api/decide reads has a `decide` option
    #
    # The check above matched operation names against verb names, so it
    # said "every operation has a verb" while `decide` could not reorder or
    # rename a collection, which /api/decide could. The question is per
    # key: each body key apply_decision (and _resolve_paths) reads must map
    # to a `decide` argument in cli.py, or be named here with the reason
    # the terminal has no twin for it.
    DECIDE_OPTION = {'keys': '"keys"', 'paths': '"keys"', 'tier': '"--tier"',
                     'collection': '"--collection"', 'mode': '"--mode"',
                     'vinyl': '"--vinyl"', 'reorder': '"--reorder"',
                     'rename_collection': '"--rename"', 'to': '"--to"'}
    DECIDE_EXEMPT = {
        'key': 'the one-key spelling of keys',
        'adopt': 'the page naming a row it holds no record for; the terminal '
                 'reaches the same files by path (paths)',
    }
    try:
        import inspect
        src_dec = inspect.getsource(_C.apply_decision) + inspect.getsource(_C._resolve_paths)
        body_keys = set(re.findall(r"body\.get\('(\w+)'|body\['(\w+)'\]|'(\w+)' in body", src_dec))
        body_keys = {k for t in body_keys for k in t if k}
    except Exception as e:
        body_keys = set()
        print('\n  (could not read apply_decision: %s)' % e)
    m = re.search(r'add_parser\("decide".*?(?=sub\.add_parser\()', cli, re.S)
    decide_src = m.group(0) if m else ''
    missing = sorted(k for k in body_keys - set(DECIDE_EXEMPT)
                     if DECIDE_OPTION.get(k) is None or DECIDE_OPTION[k] not in decide_src)
    print('\n  /api/decide keys: %s' % ' '.join(sorted(body_keys)))
    if missing:
        print('  ** decide keys the terminal cannot send: %s' % ' '.join(missing))
        print('     give `saltpod decide` an option for each, or name it in DECIDE_EXEMPT')
        over.append(('decide keys without a cli option', len(missing), 0))
    else:
        print('  every /api/decide key has a decide option (%d exempt, with reasons)'
              % len(body_keys & set(DECIDE_EXEMPT)))

    # ---- the blind spot this census had for a month
    #
    # The check above compares curate.OPS against cli.py's verbs, and it
    # passed -- "every operation has a verb" -- while FOUR WHOLE MODULES
    # (smartlists, loudness, rockbox, devprefs) could not be called by
    # anything at all. They were invisible to it because an operation only
    # counts here once it is already in OPS, so a module nothing registered
    # and nothing imported was never a candidate to be missing.
    #
    # The honest question is not "does every registered operation have a
    # verb" but "can anything reach this code". A module in src/saltpod that
    # neither adapter imports is shipped, tested, documented -- and dead.
    import ast
    src = os.path.join(ROOT, 'src', 'saltpod')
    mods = {f[:-3] for f in os.listdir(src)
            if f.endswith('.py') and not f.startswith('_')}

    def imports_of(mod):
        try:
            tree = ast.parse(open(os.path.join(src, mod + '.py')).read())
        except (OSError, SyntaxError):
            return set()
        found = set()
        for n in ast.walk(tree):
            # `from . import x, y` and `from .x import y`
            if isinstance(n, ast.ImportFrom) and n.level:
                if n.module:
                    found.add(n.module.split('.')[0])
                found |= {al.name for al in n.names}
        return found & mods

    # Everything reachable from either adapter, transitively. A module a
    # Data-sheet job runs (curate.JOB_MODULES) is started by name with runpy,
    # not imported, so it is named as a root of the walk rather than missed.
    job_mods = list(getattr(_C, 'JOB_MODULES', ())) if ops else []
    reach, stack = set(), ['cli', 'curate'] + job_mods
    while stack:
        m = stack.pop()
        if m in reach or m not in mods:
            continue
        reach.add(m)
        stack.extend(imports_of(m))

    # A module whose only caller is itself is dead however good it is.
    # The four below are named, not zeroed. Each is a research one-off that
    # ships in the manifest and has no verb: buy_lossless (one-shot purchase
    # research), spectrum and verify_quality (the lossless
    # audit), and itunesdb_patch -- which is the odd one out, a write path
    # described as "the safest way to write" that nothing writes through.
    # That last one is a real question to settle, not a one-off to accept.
    # The number only ever goes down.
    # verify_bandcamp came off the list on 12 October: the Data sheet's
    # "Verify Bandcamp durations" job runs it (curate.JOB_MODULES).
    KNOWN_UNREACHABLE = {'buy_lossless', 'itunesdb_patch', 'spectrum',
                         'verify_quality'}
    dead = sorted(mods - reach - {'__main__'} - KNOWN_UNREACHABLE)
    stale = sorted(KNOWN_UNREACHABLE & reach)
    print('\n  modules shipped: %d   reachable from cli or curate: %d'
          % (len(mods), len(reach)))
    if dead:
        print('  ** nothing can call: %s' % ' '.join(dead))
        print('     a module no adapter imports is dead code with tests --')
        print('     give it a verb, or an operation, or delete it')
        over.append(('modules nothing can reach', len(dead), 0))
    else:
        print('  no NEW unreachable module (%d known, named in the source)'
              % len(KNOWN_UNREACHABLE))
    if stale:
        # The budget is a promise that only goes down, so a module that has
        # since been wired up must come off the list rather than sit there
        # excusing the next one.
        print('  ** now reachable, remove from KNOWN_UNREACHABLE: %s' % ' '.join(stale))
        over.append(('stale entries in KNOWN_UNREACHABLE', len(stale), 0))

    if over:
        print('\nover budget:')
        for name, n, b in over:
            print('  %s: %d, budget %d' % (name, n, b))
        if strict:
            return 1
    else:
        print('\nwithin budget — the page is still rendering, not deciding')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
