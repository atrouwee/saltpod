#!/usr/bin/env python3
"""Vendor the saltglass design system into saltpod. Idempotent.

saltpod's page is ONE file with no build step and no external request, so
the system cannot be linked; it is copied in, between markers that say
which commit it came from:

    curate.html  <style>   <!-- saltglass:css @<sha> --> tokens.css + glass.css <!-- /saltglass:css -->
    curate.html  <head>    <!-- saltglass:js @<sha> -->  ground.js               <!-- /saltglass:js -->
    src/saltpod/glassband.py   band.py, with a provenance header

The CSS goes at the END of the page's stylesheet (so where a page rule and
a system rule tie on specificity, the system's wins) and the script goes
at the end of <head>, after the stylesheet and so before the page's own
<script>, in a tag of its own. Not in <body>: pagetest reads the body markup
as the page's DOM, and the system's code is not markup. That tag is
`<script data-saltglass>`, not a bare `<script>`, on purpose: pagetest,
layer_census and the parse check each find the page's script by the bare
tag, and the system's code is neither the page's logic nor the page's to
police.

<sha> is the source repo's HEAD, and the files are read AT that commit
(`git show <sha>:path`), not from the working tree -- so the recorded sha
always describes exactly the bytes that were copied, even if the source
has uncommitted edits. Edit upstream, commit, re-run this.

    python3 scripts/vendor_glass.py                 # from ../saltGlass
    python3 scripts/vendor_glass.py --from PATH
    python3 scripts/vendor_glass.py --check         # exit 1 if stale or tampered
"""
import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, 'src', 'saltpod', 'curate.html')
BAND = os.path.join(ROOT, 'src', 'saltpod', 'glassband.py')
DEFAULT_SRC = os.path.join(os.path.dirname(ROOT), 'saltGlass')

CSS_OPEN = '<!-- saltglass:css @%s -->'
CSS_CLOSE = '<!-- /saltglass:css -->'
JS_OPEN = '<!-- saltglass:js @%s -->'
JS_CLOSE = '<!-- /saltglass:js -->'
BAND_HEAD = ('# vendored from saltglass @%s; edit upstream, re-run scripts/vendor_glass.py\n')

CSS_RE = re.compile(r'<!-- saltglass:css @([0-9a-f]+) -->\n(.*?)<!-- /saltglass:css -->\n', re.S)
JS_RE = re.compile(r'<!-- saltglass:js @([0-9a-f]+) -->\n(.*?)<!-- /saltglass:js -->\n', re.S)
BAND_RE = re.compile(r'^# vendored from saltglass @([0-9a-f]+);[^\n]*\n')


class VendorError(Exception):
    pass


def _git(src, *args):
    r = subprocess.run(['git', '-C', src] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        raise VendorError('git %s failed in %s: %s' % (' '.join(args), src, r.stderr.strip()))
    return r.stdout


def source_sha(src):
    return _git(src, 'rev-parse', 'HEAD').strip()


def read_at(src, sha, name):
    return _git(src, 'show', '%s:%s' % (sha, name))


def blocks(src, sha):
    """The three vendored blocks exactly as they are written into saltpod."""
    tokens, glass = read_at(src, sha, 'tokens.css'), read_at(src, sha, 'glass.css')
    ground, band = read_at(src, sha, 'ground.js'), read_at(src, sha, 'band.py')
    if '</style' in tokens + glass or '</script' in ground:
        raise VendorError('a source file closes the element it is inlined into')
    css = (CSS_OPEN % sha + '\n' + tokens.rstrip('\n') + '\n\n'
           + glass.rstrip('\n') + '\n' + CSS_CLOSE + '\n')
    js = (JS_OPEN % sha + '\n<script data-saltglass>\n' + ground.rstrip('\n')
          + '\n</script>\n' + JS_CLOSE + '\n')
    if band.startswith('#!'):
        band = band.split('\n', 1)[1]
    py = BAND_HEAD % sha + band
    return css, js, py


def found(page, band_text):
    """{'css': (sha, text), 'js': ..., 'band': ...} for whatever is vendored now."""
    out = {}
    m = CSS_RE.search(page)
    if m:
        out['css'] = (m.group(1), m.group(0))
    m = JS_RE.search(page)
    if m:
        out['js'] = (m.group(1), m.group(0))
    m = BAND_RE.match(band_text or '')
    if m:
        out['band'] = (m.group(1), band_text)
    return out


def apply(page, css, js):
    """The page with both blocks in place: replaced if present, created if not."""
    if CSS_RE.search(page):
        page = CSS_RE.sub(lambda _m: css, page, count=1)
    else:
        i = page.index('</style>')
        if not page[:i].endswith('\n'):
            css = '\n' + css
        page = page[:i] + css + page[i:]
    if JS_RE.search(page):
        page = JS_RE.sub(lambda _m: js, page, count=1)
    else:
        # In <head>, after the stylesheet: before the page's own <script>,
        # and outside the body markup that pagetest parses as the page's DOM.
        i = page.index('</head>', page.index('</style>'))
        page = page[:i] + '\n' + js + page[i:]
    return page


def vendor(src):
    sha = source_sha(src)
    css, js, py = blocks(src, sha)
    page = open(PAGE).read()
    new = apply(page, css, js)
    changed = []
    if new != page:
        with open(PAGE + '.tmp', 'w') as f:
            f.write(new)
        os.replace(PAGE + '.tmp', PAGE)
        changed.append(os.path.relpath(PAGE, ROOT))
    old = open(BAND).read() if os.path.exists(BAND) else None
    if old != py:
        with open(BAND + '.tmp', 'w') as f:
            f.write(py)
        os.replace(BAND + '.tmp', BAND)
        changed.append(os.path.relpath(BAND, ROOT))
    return sha, changed


def check(src):
    """None if the vendored blocks agree with each other and with the source
    at their recorded sha; otherwise a sentence saying what is wrong. Raises
    VendorError (caller treats it as a skip) when the source is unavailable."""
    page = open(PAGE).read()
    band = open(BAND).read() if os.path.exists(BAND) else ''
    have = found(page, band)
    missing = [k for k in ('css', 'js', 'band') if k not in have]
    if missing:
        return 'not vendored: %s' % ', '.join(missing)
    shas = {k: v[0] for k, v in have.items()}
    if len(set(shas.values())) != 1:
        return 'vendored blocks disagree on the source sha: %s' % shas
    sha = shas['css']
    if not os.path.isdir(src):
        raise VendorError('source repo absent: %s' % src)
    css, js, py = blocks(src, sha)
    bad = [k for k, want in (('css', css), ('js', js), ('band', py)) if have[k][1] != want]
    if bad:
        return 'vendored %s differ from saltglass @%s -- edited by hand? re-run scripts/vendor_glass.py' % (
            ', '.join(bad), sha[:12])
    head = source_sha(src)
    if head != sha:
        return 'stale: vendored @%s, saltglass HEAD is %s' % (sha[:12], head[:12])
    return None


def main(argv):
    ap = argparse.ArgumentParser(description='vendor saltglass into saltpod')
    ap.add_argument('--from', dest='src', default=DEFAULT_SRC)
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args(argv)
    try:
        if a.check:
            why = check(a.src)
            print(why or 'vendored saltglass is current')
            return 1 if why else 0
        sha, changed = vendor(a.src)
    except VendorError as e:
        print('vendor_glass: %s' % e, file=sys.stderr)
        return 2
    print('saltglass @%s -> %s' % (sha[:12], ', '.join(changed) if changed else 'already current'))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
