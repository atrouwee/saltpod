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
]

# What is already there and accepted, with a reason. A number that only ever
# goes down.
# Each number is a promise, with a reason, and only ever goes down.
BUDGET = {
    # row rendering: "is there a file for this" decides full ink vs dim, and
    # that is a presentation choice about two facts, not a business rule
    'multi-field verdict': 6,
    # `all` and `vinyl` are lookups; the pattern below already lets those by
    'filter predicate': 0,
    # "everything marked sync that is not already in THIS collection" --
    # parameterised by a collection the server does not know you are looking
    # at. A selection for an action, not a list anyone is shown.
    'tier compared to a literal': 2,
    # minutes of whatever the centre pane is currently showing: a sum over
    # the CLIENT's view, which the server has no opinion about
    'price or size arithmetic': 1,
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
