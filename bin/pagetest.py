#!/usr/bin/env python3
"""Drive the real page headlessly and assert BEHAVIOUR, not markup.

WHY THIS EXISTS. `publish/HANDOFF.md`, under "the front end has no
behavioural test, and no accessibility one": of `bin/selftest.py`'s checks
only three touch the page at all, and all three are static -- the inline
script parses, it conforms to the design tokens, it stays within the
layer-rule budget. None of that proves anything WORKS. Every behavioural bug
in the page so far was caught by a person clicking: shift-click dragging a
text selection, cmd-Z swallowed whenever a panel was open, the track panel
unable to open the 581 files it exists for. A parser sees none of that.

THE CONSTRAINT. No new dependencies -- no Playwright, no Selenium, no npm.
The repo is stdlib Python plus ffmpeg, so there is no real browser to drive
the usual way. Three options were weighed:

1. osascript driving Safari ("Allow JavaScript from Apple Events"). REJECTED,
   with evidence, not a guess: `tell application "Safari" to get version`
   returns instantly, but anything that touches a Safari WINDOW --
   `make new document`, even `count windows` -- hangs until killed. The TCC
   database confirms why:

       sqlite3 ~/Library/Application\\ Support/com.apple.TCC/TCC.db \\
         "select client,indirect_object_identifier,auth_value from access \\
          where service='kTCCServiceAppleEvents'"
       com.apple.Terminal|com.apple.Safari|0        <- 0 = denied

   Automation access from this shell to Safari is denied, so every call that
   needs a window blocks on a permission dialog nobody is there to click.
   Getting this working needs TWO one-time, interactive toggles -- granting
   Automation access to Safari in System Settings -> Privacy & Security ->
   Automation, and enabling "Allow JavaScript from Apple Events" in Safari's
   Develop menu -- and the owner is away from the machine, so per the brief
   this is reported, not worked around.

2. Node parsing and EXECUTING the real inline script against a minimal DOM
   (CHOSEN). Not a browser: a hand-rolled ~200-line DOM/selector engine
   (Element, classList, dataset, a CSS selector matcher good enough for
   `#list .row[data-i="3"]` and `:not()`) plus stubs for fetch/localStorage/
   EventSource/performance. The real `<script>` block is sliced out of
   `curate.html` UNMODIFIED and run in a `vm` context, so `colRow()`,
   `pass()`, `mark()`, `openMenu()`, `draw()` and friends are the actual
   functions, not reimplementations. A second small script of assertions
   runs in the SAME vm context straight after -- Node keeps a Script's
   top-level `let`/`const` bindings alive across separate `runInContext`
   calls on one context (verified empirically before relying on it), the
   same way two `<script>` tags on one page share scope -- so the test code
   reaches `ALL`, `view`, `sel`, `MARK`, `colPick`, `active`... directly,
   the way `bin/selftest.py`'s `t_js_parses` already proved the script is
   at least syntactically sound.

3. A pure-Python `html.parser` harness asserting on structure only.
   Rejected as the PRIMARY approach (it cannot call a real function or
   observe a state change), but its spirit survives here for the three
   checks that are genuinely static -- see "accessibility -- static" below.

DEGRADATION. If `node` is not on PATH, every check that needs it SKIPS with
a clear reason. Nothing here fails for that reason; see `_node()`.

TWO CHECKS BELOW ARE EXPECTED TO FAIL, which is the surest sign a
behavioural test does something a parser cannot: writing it turned up two
real, previously-unflagged accessibility gaps (see "accessibility -- found
while writing this suite"). They are reported here with exact evidence, not
fixed -- see the module's final report for both. Everything else genuinely
passes against the real functions.

    python3 bin/pagetest.py

Deterministic and fast (one `node` subprocess, fixed fixtures, no network,
no device): safe for a CI-style loop. Never writes to curate.html or to any
other file in the repo.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CURATE = os.path.join(ROOT, 'src', 'saltpod', 'curate.html')
SELFTEST_PATH = os.path.join(ROOT, 'bin', 'selftest.py')

PASS, FAIL, SKIP = [], [], []
_t0 = time.time()


def _skip(reason):
    """A check() return value meaning 'skip, for this specific reason' --
    distinct from None, which selftest.py's convention reserves for the
    generic 'not applicable here'."""
    return ('__skip__', reason)


def check(name, fn):
    """Run one check. Returns a detail string, raises, returns None to skip
    generically, or returns _skip('reason') to skip with a specific reason
    (used for 'node is not installed')."""
    t = time.perf_counter()
    try:
        detail = fn()
    except Exception as e:
        FAIL.append((name, '%s: %s' % (type(e).__name__, e)))
        print('  !!  %-56s %s: %s' % (name, type(e).__name__, str(e)[:200]))
        return
    ms = (time.perf_counter() - t) * 1000
    if isinstance(detail, tuple) and len(detail) == 2 and detail[0] == '__skip__':
        SKIP.append((name, detail[1]))
        print('  ..  %-56s %s' % (name, detail[1]))
        return
    if detail is None:
        SKIP.append((name, 'not applicable here'))
        print('  ..  %-56s n/a' % name)
    else:
        PASS.append((name, detail))
        print('  ok  %-56s %-24s %6.0f ms' % (name, str(detail)[:24], ms))


def section(title):
    print('\n%s' % title)


def _node():
    return shutil.which('node')


# ---------------------------------------------------------------- the node
# harness: a minimal DOM, the real <script> from curate.html, and a second
# script of assertions run in the same vm context straight after. Both are
# written to a scratch dir and run once per process; every named check below
# just reads its own entry out of the one JSON result array.

_DRIVER_JS = r'''
'use strict';
const fs = require('fs');
const vm = require('vm');

const CURATE = process.argv[2];
const TESTS_PATH = process.argv[3];
const RAW = fs.readFileSync(CURATE, 'utf8');
const BODY_HTML = RAW.split('<body>')[1].split('<script>')[0];
const SCRIPT = RAW.split('<script>')[1].split('</script>')[0];

// ---------------------------------------------------------- a minimal DOM
// Hand-rolled on purpose (see the module docstring for why): Element with
// attributes/classList/dataset, a tiny HTML parser for innerHTML, and a CSS
// selector engine good enough for what curate.html's own script asks of it
// (#id, .class, [attr], [attr="value with spaces"], descendant combinators,
// :not(), comma lists) -- not a browser, just enough of one.
const VOID = new Set(['area','base','br','col','embed','hr','img','input',
  'link','meta','param','source','track','wbr']);

function decodeEntities(s){
  return s.replace(/&#x([0-9a-fA-F]+);/g,(_,h)=>String.fromCodePoint(parseInt(h,16)))
          .replace(/&#(\d+);/g,(_,d)=>String.fromCodePoint(parseInt(d,10)))
          .replace(/&amp;/g,'&').replace(/&lt;/g,'<').replace(/&gt;/g,'>')
          .replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&apos;/g,"'")
          .replace(/&nbsp;/g,' ').replace(/&rsaquo;/g,'›')
          .replace(/&lsaquo;/g,'‹').replace(/&mdash;/g,'—')
          .replace(/&ndash;/g,'–').replace(/&euro;/g,'€');
}
class NodeBase {
  constructor(nodeType){ this.nodeType = nodeType; this.parentNode = null; this.childNodes = []; }
  get children(){ return this.childNodes.filter(c => c.nodeType === 1); }
}
class TextNode extends NodeBase {
  constructor(text){ super(3); this.data = text; }
  get textContent(){ return this.data; }
  set textContent(v){ this.data = String(v); }
}
function makeDataset(el){
  const toAttr = p => 'data-' + String(p).replace(/[A-Z]/g, m => '-' + m.toLowerCase());
  return new Proxy({}, {
    get(_, p){ if (typeof p !== 'string') return undefined; const a = toAttr(p); return el.attrs.has(a) ? el.attrs.get(a) : undefined; },
    set(_, p, v){ el.attrs.set(toAttr(p), String(v)); return true; },
    has(_, p){ return el.attrs.has(toAttr(p)); },
  });
}
function classList(el){
  const read = () => (el.getAttribute('class') || '').split(/\s+/).filter(Boolean);
  const write = arr => el.setAttribute('class', arr.join(' '));
  return {
    add(...cs){ const s = new Set(read()); cs.forEach(c => s.add(c)); write([...s]); },
    remove(...cs){ const s = new Set(read()); cs.forEach(c => s.delete(c)); write([...s]); },
    toggle(c, force){ const s = new Set(read()); const has = s.has(c);
      const want = force === undefined ? !has : force;
      if (want) s.add(c); else s.delete(c); write([...s]); return want; },
    contains(c){ return read().includes(c); },
    get length(){ return read().length; },
  };
}
class Element extends NodeBase {
  constructor(tag){
    super(1);
    this._tag = tag.toLowerCase();
    this.tagName = tag.toUpperCase();
    this.attrs = new Map();
    this._listeners = {};
    this.style = {};
  }
  get id(){ return this.getAttribute('id') || ''; }
  set id(v){ this.setAttribute('id', v); }
  get className(){ return this.getAttribute('class') || ''; }
  set className(v){ this.setAttribute('class', v); }
  get classList(){ return classList(this); }
  get dataset(){ return makeDataset(this); }
  getAttribute(n){ return this.attrs.has(n) ? this.attrs.get(n) : null; }
  setAttribute(n, v){ this.attrs.set(n, String(v)); }
  removeAttribute(n){ this.attrs.delete(n); }
  hasAttribute(n){ return this.attrs.has(n); }
  get hidden(){ return this.hasAttribute('hidden'); }
  set hidden(v){ if (v) this.setAttribute('hidden',''); else this.removeAttribute('hidden'); }
  appendChildNode(n){ n.parentNode = this; this.childNodes.push(n); }
  get textContent(){ return this.childNodes.map(c => c.textContent).join(''); }
  set textContent(v){ this.childNodes = []; this.appendChildNode(new TextNode(String(v))); }
  get innerHTML(){ return this.childNodes.map(serialize).join(''); }
  set innerHTML(html){ this.childNodes = []; const root = parseFragment(html);
    root.childNodes.forEach(c => { c.parentNode = this; }); this.childNodes = root.childNodes; }
  get outerHTML(){ return serialize(this); }
  querySelector(sel){ return queryFirst(this, sel); }
  querySelectorAll(sel){ return queryAll(this, sel); }
  closest(sel){ let e = this; while (e) { if (e.nodeType === 1 && matchesList(e, sel)) return e; e = e.parentNode; } return null; }
  matches(sel){ return matchesList(this, sel); }
  contains(o){ let e = o; while (e) { if (e === this) return true; e = e.parentNode; } return false; }
  addEventListener(t, fn){ (this._listeners[t] = this._listeners[t] || []).push(fn); }
  removeEventListener(t, fn){ if (this._listeners[t]) this._listeners[t] = this._listeners[t].filter(f => f !== fn); }
  getBoundingClientRect(){ return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }; }
  scrollIntoView(){}
  focus(){} blur(){}
  remove(){ if (this.parentNode) { const i = this.parentNode.childNodes.indexOf(this); if (i >= 0) this.parentNode.childNodes.splice(i, 1); this.parentNode = null; } }
}
function escText(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;'); }
function serialize(n){
  if (n.nodeType === 3) return escText(n.data);
  const attrs = [...n.attrs.entries()].map(([k,v]) => ` ${k}="${escText(v)}"`).join('');
  const inner = n.childNodes.map(serialize).join('');
  if (VOID.has(n._tag)) return `<${n._tag}${attrs}>`;
  return `<${n._tag}${attrs}>${inner}</${n._tag}>`;
}

const TOKEN_RE = /<!--[\s\S]*?-->|<\/([a-zA-Z0-9-]+)\s*>|<([a-zA-Z0-9-]+)((?:\s+[a-zA-Z_:][-a-zA-Z0-9_:.]*(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*)\s*\/?>|([^<]+)/g;
const ATTR_RE = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*("([^"]*)"|'([^']*)'|[^\s"'=<>`]+))?/g;
function parseFragment(html){
  const root = new Element('div');
  const stack = [root];
  let m;
  TOKEN_RE.lastIndex = 0;
  while ((m = TOKEN_RE.exec(html))) {
    if (m[0].startsWith('<!--')) continue;
    if (m[1]) {
      const tag = m[1].toLowerCase();
      for (let j = stack.length - 1; j > 0; j--) { if (stack[j]._tag === tag) { stack.length = j; break; } }
    } else if (m[2]) {
      const tag = m[2].toLowerCase();
      const el = new Element(tag);
      ATTR_RE.lastIndex = 0;
      let am;
      const attrStr = m[3] || '';
      while ((am = ATTR_RE.exec(attrStr))) {
        const name = am[1].toLowerCase();
        const val = am[3] !== undefined ? am[3] : am[4] !== undefined ? am[4] : (am[2] !== undefined ? am[2] : '');
        el.attrs.set(name, decodeEntities(val));
      }
      if (tag === 'input' || tag === 'textarea') el.value = el.getAttribute('value') || '';
      stack[stack.length - 1].appendChildNode(el);
      const selfClose = m[0].endsWith('/>') || VOID.has(tag);
      if (!selfClose) stack.push(el);
    } else if (m[4] !== undefined) {
      const text = decodeEntities(m[4]);
      if (text.length) stack[stack.length - 1].appendChildNode(new TextNode(text));
    }
  }
  return root;
}

function parseCompound(s){
  const nots = [];
  const base = s.replace(/:not\(([^)]*)\)/g, (_, inner) => { nots.push(inner); return ''; });
  const tagM = base.match(/^[a-zA-Z][a-zA-Z0-9-]*/);
  const tag = tagM ? tagM[0].toLowerCase() : null;
  let rest = tag ? base.slice(tag.length) : base;
  let id = null; const classes = []; const attrs = [];
  const tokRe = /#([-\w]+)|\.([-\w]+)|\[([-\w:]+)(?:=("([^"]*)"|'([^']*)'|[^\]]*))?\]/g;
  let tm;
  while ((tm = tokRe.exec(rest))) {
    if (tm[1]) id = tm[1];
    else if (tm[2]) classes.push(tm[2]);
    else if (tm[3]) {
      let val = null;
      if (tm[4] !== undefined) val = tm[5] !== undefined ? tm[5] : tm[6] !== undefined ? tm[6] : tm[4];
      attrs.push([tm[3], val]);
    }
  }
  return { tag, id, classes, attrs, nots: nots.map(parseCompound) };
}
function matchesCompound(el, c){
  if (!el || el.nodeType !== 1) return false;
  if (c.tag && el._tag !== c.tag) return false;
  if (c.id && el.id !== c.id) return false;
  for (const cl of c.classes) if (!el.classList.contains(cl)) return false;
  for (const [name, val] of c.attrs) {
    if (!el.hasAttribute(name)) return false;
    if (val !== null && el.getAttribute(name) !== val) return false;
  }
  for (const n of c.nots) if (matchesCompound(el, n)) return false;
  return true;
}
const compoundCache = new Map();
function compound(s){ s = s.trim(); if (!compoundCache.has(s)) compoundCache.set(s, parseCompound(s)); return compoundCache.get(s); }
// split on whitespace for the descendant combinator, but NOT whitespace
// inside an [attr="..."] value -- `[data-f="to buy"]` is one compound, not two
function splitDescendants(sel){
  const out = []; let cur = ''; let depth = 0;
  for (const ch of sel) {
    if (ch === '[') depth++;
    if (ch === ']') depth = Math.max(0, depth - 1);
    if (/\s/.test(ch) && depth === 0) { if (cur) out.push(cur); cur = ''; }
    else cur += ch;
  }
  if (cur) out.push(cur);
  return out;
}
function matchesList(el, sel){
  return sel.split(',').map(s => s.trim()).some(part => {
    const seq = splitDescendants(part).map(compound);
    if (!matchesCompound(el, seq[seq.length - 1])) return false;
    let idx = seq.length - 2, cur = el.parentNode;
    while (idx >= 0 && cur) { if (matchesCompound(cur, seq[idx])) idx--; cur = cur.parentNode; }
    return idx < 0;
  });
}
function* walk(root){ for (const c of root.childNodes) { if (c.nodeType === 1) { yield c; yield* walk(c); } } }
function queryAll(root, sel){ return [...walk(root)].filter(el => matchesList(el, sel)); }
function queryFirst(root, sel){ for (const el of walk(root)) if (matchesList(el, sel)) return el; return null; }

const bodyEl = new Element('body');
{
  const root = parseFragment(BODY_HTML);
  root.childNodes.forEach(c => { c.parentNode = bodyEl; });
  bodyEl.childNodes = root.childNodes;
}
const htmlEl = new Element('html');
htmlEl.appendChildNode(bodyEl);
const document_ = {
  body: bodyEl,
  documentElement: htmlEl,
  querySelector: sel => queryFirst(bodyEl, sel),
  querySelectorAll: sel => queryAll(bodyEl, sel),
  getElementById: id => queryFirst(bodyEl, '#' + id),
  createElement: tag => new Element(tag),
  addEventListener(){}, removeEventListener(){},
};

// -------------------------------------------------------------- fixtures
// Four tracks covering law 8's three positions (on the device, owned but
// not on it, not owned at all) plus a plain undecided one; two AM
// playlists (one imported, one not); two T7 folders; a sync plan with one
// add/remove/retag/new-playlist so every row SHAPE in the sync panel
// renders at least once.
const TRACKS = [
  { key:'t1', artist:'Aphex Twin', title:'Flim', album:'Come to Daddy',
    device:true, held:true, tier:'sync', vinyl:false, bought:true, t7:false, am:true, local:false,
    collections:['DayClub'], playlists:['DayClub'], on_ipod:true, lists:['on iPod'],
    seconds:220, vinyl_owned:false, vinyl_wanted:false },
  { key:'t2', artist:'Burial', title:'Archangel', album:'Untrue',
    device:false, held:true, tier:'undecided', vinyl:true, bought:true, t7:true, am:false, local:true,
    collections:[], playlists:[], on_ipod:false, lists:['on T7','owned digitally'],
    seconds:245, vinyl_owned:false, vinyl_wanted:false },
  { key:'t3', artist:'SAULT', title:'Wildfires', album:'Untitled',
    device:false, held:false, tier:'sync', vinyl:false, bought:false, t7:false, am:true, local:false,
    collections:['WARA - Listening'], playlists:['WARA - Listening'], on_ipod:false, lists:['to buy','rented only'],
    seconds:200, price:1.29, vinyl_owned:false, vinyl_wanted:false },
  { key:'t4', artist:'Objekt', title:'Ganzfeld', album:'Objekt #1',
    device:false, held:false, tier:'undecided', vinyl:false, bought:false, t7:false, am:false, local:false,
    collections:[], playlists:[], on_ipod:false, lists:[], seconds:300, vinyl_owned:false, vinyl_wanted:false },
];
const COLLECTIONS = ['DayClub', 'WARA - Listening'];
const ORDER = { 'DayClub': ['t1'], 'WARA - Listening': ['t3'] };
const TOTALS = { to_buy: 1, to_buy_eur: 1.29, to_sync: 0, to_remove: 0, on_ipod: 1 };
const SYNCED = ['DayClub'];
const AMP = [
  { name:'DayClub', slug:'dayclub', tracks:12, created:'2025-06-01', last:'2025-06-10', imported:true },
  { name:'WARA - Listening', slug:'wara-listening', tracks:40, created:'2025-01-01', last:'2025-02-01', imported:true },
  { name:'Vinyl Wishlist', slug:'vinyl-wishlist', tracks:5, created:'2024-01-01', last:'2024-02-01', imported:false },
];
const T7 = { folders: [
  { name:'Bought Tracks', n:1180, lossless:300 },
  { name:'Vinyl Rips', n:40, lossless:40 },
], root:'/Volumes/T7/Music', built:'2026-01-01', total:4048 };
const DEV = { mounted:true, source:'apple', playlists:[{name:'DayClub', n:1}] };
const PLAN = {
  ok:true,
  adds:[{key:'t3', artist:'SAULT', title:'Wildfires', bytes:5000000, convert:false}],
  removes:[{key:'t5', artist:'Old', title:'Track'}],
  retags:[{key:'t1', artist:'Aphex Twin', title:'Flim', winner:'file', fields:{genre:1}}],
  new:['New Collection'], update:[], delete:[],
  members:{'New Collection':[{artist:'SAULT', title:'Wildfires', on:false, off:false}]},
  sizes:{'New Collection':1}, free_bytes:5e9, unchanged:[],
};
const HEALTH = { ipod:'absent', music:'ok', sources:[], tools:{ffmpeg:true, ffprobe:true} };

function fetchStub(url){
  const p = String(url).split('?')[0];
  const body = ({
    '/api/tracks': { tracks: TRACKS, collections: COLLECTIONS, order: ORDER, totals: TOTALS, synced: SYNCED, slugs: {}, updated: null },
    '/api/discogs': { wantlist: [], collection: [], files: {}, dir: 'data/discogs' },
    '/api/playlists': { playlists: AMP, read_at: '2026-01-01', library: 500 },
    '/api/device': DEV,
    '/api/local': T7,
    '/api/plan': PLAN,
    '/api/health': HEALTH,
    '/api/undo': { can_undo: 0, can_redo: 0, next: null },
  })[p];
  return Promise.resolve({ ok: body !== undefined, json: () => Promise.resolve(body === undefined ? {} : body) });
}
class EventSourceStub { constructor(){} close(){} }

const sandbox = {
  document: document_,
  window: { innerWidth: 1680, innerHeight: 1000 },
  localStorage: {},
  fetch: fetchStub,
  EventSource: EventSourceStub,
  Node: NodeBase,
  performance: { now: () => Date.now() },
  location: { reload(){} },
  navigator: {},
  console,
  process,
  setTimeout, clearTimeout, setInterval, clearInterval,
  AbortController,
};
vm.createContext(sandbox);
try {
  // Run #1: the REAL inline script, unmodified, sliced straight out of
  // curate.html. Its top-level function declarations (colRow, pass, mark,
  // openMenu, draw, load...) become properties of `sandbox` and are
  // reachable from outside; its top-level `let`/`const` state (ALL, view,
  // sel, MARK, colPick...) does not, by the language's own rules for Script
  // code -- but a SECOND `runInContext` call on this same context shares
  // that lexical scope, the same way two <script> tags on one page do. That
  // is what run #2 below depends on, and it was verified empirically
  // (a minimal let/function pair across two separate runInContext calls)
  // before this harness was built on top of it.
  vm.runInContext(SCRIPT, sandbox, { filename: 'curate-inline.js' });
  // Run #2: the assertions, written to their own file so they read as
  // ordinary, un-escaped JavaScript rather than a string embedded in a
  // string embedded in Python.
  const TESTS = fs.readFileSync(TESTS_PATH, 'utf8');
  vm.runInContext(TESTS, sandbox, { filename: 'pagetest-assertions.js' });
} catch (e) {
  console.log(JSON.stringify([{ name: 'harness', ok: false, error: String((e && e.stack) || e) }]));
  process.exit(1);
}
'''

_TESTS_JS = r'''
// Runs in the SAME vm context as curate.html's own <script>, straight after
// it -- so every name below (colRow, pass, mark, openMenu, draw, load, ALL,
// view, sel, MARK, colPick, active, stab, ORDER, rtab, SP...) is the real
// thing, not a stand-in. See bin/pagetest.py's module docstring for why
// this works across two separate vm.runInContext calls.
(async function () {
  const RESULTS = [];
  function record(name, fn) {
    try { const detail = fn(); RESULTS.push({ name, ok: true, detail: detail == null ? '' : String(detail) }); }
    catch (e) { RESULTS.push({ name, ok: false, error: String((e && e.message) || e) }); }
  }
  async function recordAsync(name, fn) {
    try { const detail = await fn(); RESULTS.push({ name, ok: true, detail: detail == null ? '' : String(detail) }); }
    catch (e) { RESULTS.push({ name, ok: false, error: String((e && e.message) || e) }); }
  }
  function assert(cond, msg) { if (!cond) throw new Error(msg); }
  function frag(html) { const d = document.createElement('div'); d.innerHTML = html; return d; }

  // ---------------------------------------------------- law 1: colRow slots
  // Real bug this guards: nine call sites once hand-assembled `.col`, four
  // carried a menu slot and five did not, and counts in two panes sat on
  // verticals 28px apart in the same column.
  record('colRow reserves the menu slot', () => {
    const withMenu = frag(colRow({ name: 'Folder A', cnt: 12, menu: true })).children[0];
    const withoutMenu = frag(colRow({ name: 'Folder B', cnt: 7 })).children[0];
    const moreA = withMenu.querySelector('.more'), moreB = withoutMenu.querySelector('.more');
    assert(moreA && moreB, 'one of the two rows has no .more element at all');
    assert(withMenu.children.length === withoutMenu.children.length,
      `menu:true row has ${withMenu.children.length} slots, omitting menu has ${withoutMenu.children.length} -- the 28px misalignment bug`);
    assert(withMenu.children[withMenu.children.length - 1] === moreA &&
           withoutMenu.children[withoutMenu.children.length - 1] === moreB,
      '.more is not the last slot in both shapes');
    assert(moreB.classList.contains('hold'), 'the reserved (no-menu) slot should carry .hold');
    assert(!moreA.classList.contains('hold'), 'a real menu slot should not carry .hold');
    const art1 = frag(colRow({ name: 'T', cnt: 1, art: '' })).children[0];
    const art2 = frag(colRow({ name: 'T', sub: 'S', cnt: 1, art: 'x.jpg', menu: true })).children[0];
    assert(art1.children.length === art2.children.length,
      `both declare an art slot, so both must carry ${art2.children.length} slots -- got ${art1.children.length} and ${art2.children.length}`);
    return `${withMenu.children.length} slots, stable across menu true/false/art/sub`;
  });

  // ------------------------------------- role comes from the caller (ARIA)
  // Real bug this guards: colRow() first emitted role="option"
  // unconditionally, including into containers that are not single-choice
  // lists -- an option outside a listbox is invalid ARIA.
  record('role comes from the caller (sync rows are checkboxes)', () => {
    const on = frag(colRow({ name: 'Track A', cnt: '', cls: '', role: 'checkbox' })).children[0];
    const off = frag(colRow({ name: 'Track B', cnt: '', cls: 'out', role: 'checkbox' })).children[0];
    const infra = frag(colRow({ name: 'back up the database', cnt: '', cls: 'fixed', role: null })).children[0];
    assert(on.getAttribute('role') === 'checkbox', 'a ticked sync row must be role=checkbox');
    assert(on.getAttribute('aria-checked') === 'true', 'a ticked row (no .out class) must be aria-checked=true');
    assert(off.getAttribute('aria-checked') === 'false', 'an unticked (.out) row must be aria-checked=false');
    assert(!on.hasAttribute('aria-selected') && !off.hasAttribute('aria-selected'),
      'a checkbox row must not also carry aria-selected -- that is the listbox/option vocabulary');
    assert(infra.getAttribute('role') === null, 'an infrastructure row (role:null) must carry no role at all, not a lie about being clickable');
    const normal = frag(colRow({ name: 'DayClub', cnt: 3 })).children[0];
    assert(normal.getAttribute('role') === 'option', 'the default row role must stay option for ordinary lists');
    return 'checkbox/aria-checked for sync rows, option/aria-selected elsewhere, null for infra -- never mixed';
  });

  // ------------------------------------------------- full-page boot via load()
  await recordAsync('load() boots every pane', async () => {
    await load();
    const n = document.querySelectorAll('#list .row').length;
    assert(ALL.length === 4, `fixture should produce 4 tracks, draw() saw ${ALL.length}`);
    assert(n >= 1, 'the track list rendered no rows at all');
    return `${ALL.length} tracks loaded, ${n} rows in #list`;
  });

  // --------------------------- every role=option has a listbox ancestor
  record('role=option always has a listbox ancestor', () => {
    const options = document.querySelectorAll('[role="option"]');
    assert(options.length > 0, 'nothing rendered with role=option -- the check would be vacuous');
    const orphans = options.filter(o => !o.closest('[role="listbox"]'));
    assert(orphans.length === 0,
      `${orphans.length} of ${options.length} role=option elements have no listbox ancestor, e.g. ${orphans[0] && orphans[0].outerHTML.slice(0, 120)}`);
    return `${options.length} role=option elements, all inside a listbox`;
  });

  // --------------------- every role=button has an accessible name already
  record('the ⋯ menus have an accessible name', () => {
    const buttons = document.querySelectorAll('[role="button"]');
    assert(buttons.length > 0, 'fixture produced no role=button elements to examine');
    const unnamed = buttons.filter(b => !b.hasAttribute('aria-label') && !b.hasAttribute('aria-labelledby') &&
      !b.hasAttribute('title') && !b.textContent.trim());
    assert(unnamed.length === 0, `${unnamed.length} of ${buttons.length} role=button elements have no accessible name`);
    return `${buttons.length} role=button elements, all named`;
  });

  // ------------- a container role must match what it actually holds.
  //
  // THIS CHECK FOUND A REAL BUG AND THEN HAD TO BE REWRITTEN, which is
  // worth recording. It first asserted that #rbody, being role="listbox",
  // must own at least one role=option -- and it did not, because
  // drawRight() hand-builds .card divs rather than calling colRow(). A
  // listbox owning zero options can read as EMPTY to a screen reader
  // however many cards are visibly in it.
  //
  // But the fix was not to make the cards into options. These cards are
  // things with a menu, not options you choose one of, so the container
  // role was the wrong one: #rbody is role="list" and the cards are
  // role="listitem". The original assertion encoded one particular fix
  // rather than the invariant, so it failed on the better one.
  //
  // The invariant: whatever a container CLAIMS to be, it must own the
  // children that role requires.
  record('a container role matches what it holds', () => {
    rtab = 'buy'; drawRight();
    const rbody = document.getElementById('rbody');
    const role = rbody.getAttribute('role');
    const cards = rbody.querySelectorAll('.card');
    assert(cards.length > 0, 'fixture produced no buy cards to examine');
    const NEEDS = { listbox: 'option', list: 'listitem', group: null, grid: 'row' };
    assert(role in NEEDS, `#rbody has role=${role}, which this check does not know`);
    const want = NEEDS[role];
    if (!want) return `role=${role} requires no particular child`;
    const owned = rbody.querySelectorAll(`[role="${want}"]`);
    assert(owned.length > 0,
      `#rbody is role=${role} with ${cards.length} visible .card rows and ZERO ` +
      `role=${want} descendants -- evidence: ${cards[0].outerHTML.slice(0, 200)}`);
    return `role=${role} owning ${owned.length} role=${want} of ${cards.length} cards`;
  });

  // --------------- a role=checkbox must have an AUTHORED name.
  // This found a real bug, now fixed: see the comment in colRow().
  // ARIA's checkbox role has nameFrom:author -- unlike a plain listbox
  // option, its accessible name does NOT fall back to subtree text content.
  // colRow()'s checkbox branch (the sync panel) sets role and aria-checked
  // but never aria-label/aria-labelledby, and the sync panel never passes
  // `title` either. A screen reader following the spec announces only
  // "checkbox, not checked" -- never which track or operation it is.
  // Reported, not fixed -- see bin/pagetest.py's final report.
  record('a sync checkbox names its track', () => {
    const planFixture = { ok: true,
      adds: [{ key: 't3', artist: 'SAULT', title: 'Wildfires', bytes: 5000000, convert: false }],
      removes: [], retags: [], new: [], update: [], delete: [], members: {}, sizes: {},
      free_bytes: 5e9, unchanged: [] };
    SP.plan = planFixture; SP.off = new Set(); SP.state = 'review'; SP.log = [];
    buildSyncRows(); paintSync();
    const boxes = document.querySelectorAll('[role="checkbox"]');
    assert(boxes.length > 0, 'fixture produced no checkbox rows to examine');
    const unnamed = boxes.filter(b => !b.hasAttribute('aria-label') && !b.hasAttribute('aria-labelledby') && !b.hasAttribute('title'));
    assert(unnamed.length === 0,
      `${unnamed.length} of ${boxes.length} role=checkbox rows have no aria-label/aria-labelledby/title -- ` +
      `a screen reader announces only "checkbox, not checked", never which track -- evidence: ${unnamed[0] && unnamed[0].outerHTML}`);
    return `${boxes.length} checkbox rows, all named`;
  });

  // ---------------------------------------------- law 8: a control that undoes itself
  record('law 8: one control, flips its own label', () => {
    const anchor = document.createElement('span');
    const label = () => {
      const row = document.querySelector('#menub .m-want, #menub .m-skip');
      assert(row, 'no decision row (.m-want/.m-skip) was rendered');
      return row.querySelector('.dn').textContent;
    };
    const noUndecided = () => {
      [...document.querySelectorAll('#menub .dn')].forEach(dn =>
        assert(dn.textContent !== 'Undecided', 'a third "Undecided" row exists -- law 8 forbids a separate undo affordance'));
    };
    const onIpod = { key: 'x1', artist: 'A', title: 'B', collections: [], device: true, held: true, tier: 'sync', vinyl: false, vinyl_owned: false };
    openMenu(anchor, 'track', onIpod);
    assert(label() === 'Remove from iPod', `expected "Remove from iPod", got "${label()}"`); noUndecided();
    onIpod.tier = 'remove';
    openMenu(anchor, 'track', onIpod);
    assert(label() === "Don't remove", `expected "Don't remove", got "${label()}"`); noUndecided();
    const owned = { key: 'x2', artist: 'A', title: 'B', collections: [], device: false, held: true, tier: 'undecided', vinyl: false, vinyl_owned: false };
    openMenu(anchor, 'track', owned);
    assert(label() === 'Sync to iPod', `expected "Sync to iPod", got "${label()}"`);
    owned.tier = 'sync';
    openMenu(anchor, 'track', owned);
    assert(label() === "Don't sync", `expected "Don't sync", got "${label()}"`);
    const buyT = { key: 'x3', artist: 'A', title: 'B', collections: [], device: false, held: false, tier: 'undecided', vinyl: false, vinyl_owned: false };
    openMenu(anchor, 'track', buyT);
    assert(label() === 'Buy', `expected "Buy", got "${label()}"`);
    buyT.tier = 'sync';
    openMenu(anchor, 'track', buyT);
    assert(label() === "Don't buy", `expected "Don't buy", got "${label()}"`);
    closeMenu();
    return "Remove from iPod <-> Don't remove, Sync to iPod <-> Don't sync, Buy <-> Don't buy -- one row each, never two";
  });

  // --------------------------------------------------------- law 7: no drag-only
  record('law 7: nothing is drag-only', () => {
    function dragWithoutMenu(container) {
      return container.querySelectorAll('[draggable="true"]').filter(el => {
        const more = el.querySelector('.more');
        return !more || more.getAttribute('aria-hidden') === 'true';
      });
    }
    setSrc('am'); drawCols();
    const amBad = dragWithoutMenu(document.getElementById('srcbody'));
    setSrc('t7'); drawCols();
    const t7Bad = dragWithoutMenu(document.getElementById('srcbody'));
    const albHtml = albumRows([{ album: 'X', artist: 'Y', art: '', key: 'k1', tracks: [{}], onPod: 0 }], 'src');
    const albBad = dragWithoutMenu(frag(albHtml));
    const total = amBad.length + t7Bad.length + albBad.length;
    assert(total === 0, `${total} draggable row(s) with no menu affordance (am=${amBad.length} t7=${t7Bad.length} album=${albBad.length})`);
    return 'Apple Music playlists, T7 folders and albums: every drag has a working ⋯ menu';
  });

  // ---------------------------------------------------------------- pass()
  record('pass() honors a real filter-pill click', () => {
    colPick = 'DayClub'; active = 'ipod'; draw();
    const pill = document.querySelector('#ctl [data-f="to buy"]');
    assert(pill, 'no "to buy" filter pill was rendered');
    pill.onclick();
    assert(filter === 'to buy', `clicking the pill left filter=${filter}`);
    assert(pass({ lists: ['to buy'], artist: 'a', title: 'b', album: 'c' }) === true, 'pass() rejected a to-buy track while filter=to buy');
    assert(pass({ lists: ['on T7'], artist: 'a', title: 'b', album: 'c' }) === false, 'pass() accepted a non-matching track while filter=to buy');
    document.querySelector('#ctl [data-f="all"]').onclick();
    assert(filter === 'all', 'resetting the filter pill did not reset filter');
    return 'a real pill click changes filter, and pass() obeys it';
  });
  record('pass() honors a real search input', () => {
    const qi = document.getElementById('q');
    qi.oninput({ target: { value: 'Aphex' } });
    assert(q === 'aphex', `typing left q=${JSON.stringify(q)}`);
    assert(pass({ artist: 'Aphex Twin', title: 'Flim', album: '', lists: [] }) === true, 'pass() rejected a matching artist');
    assert(pass({ artist: 'Burial', title: 'Archangel', album: '', lists: [] }) === false, 'pass() accepted a non-matching artist');
    qi.oninput({ target: { value: '' } });
    return 'a real input event changes q, and pass() obeys it';
  });

  // ---------------------------------------------------------------- mark()
  record('owned-but-offline is its own state, not unowned', () => {
    // Three states, because "buy it" and "plug the drive in" are different
    // instructions. Before this, a track on an unplugged drive rendered at
    // full ink and the Sync button counted it as ready to write.
    const mk = (k, o) => Object.assign({key:k, artist:'A', title:k, tier:'sync',
      collections:['C'], lists:[], playlists:[], seconds:100}, o);
    const ready   = mk('ready',   {local:true,  reachable:true,  device:false});
    const offline = mk('offline', {local:true,  reachable:false, device:false, t7:true});
    const unowned = mk('unowned', {local:false, reachable:false, device:false});

    const hR = rowHTML(ready,0,0), hO = rowHTML(offline,1,0), hU = rowHTML(unowned,2,0);
    assert(!/class="row[^"]*unowned/.test(hR) && !/class="row[^"]*offline/.test(hR),
      'a ready track was dimmed');
    assert(/class="row[^"]*offline/.test(hO), 'an owned track on an absent drive was not marked offline');
    assert(!/class="row[^"]*unowned/.test(hO), 'an owned track was called unowned because its drive is out');
    assert(/class="row[^"]*unowned/.test(hU), 'a track with no file anywhere was not marked unowned');
    // law 3: the state must be spoken, not only shaded
    assert(/not mounted/.test(hO), 'the offline row carries no title explaining itself');
    assert(/buy it/.test(hU), 'the unowned row lost its title');
    // the source badge is struck through when its volume is away
    assert(/class="gone"[^>]*>T7</.test(hO), 'the drive badge was not struck through');

    // and the Sync button must not promise what it cannot write
    const keep = ALL;
    ALL = [ready, offline, unowned];
    counts();
    const sb = document.getElementById('dosync');
    assert(sb.textContent === 'Sync · 1',
      `Sync counted tracks it cannot reach: ${sb.textContent}`);
    assert(/not mounted/.test(sb.title), 'the button does not mention the ones waiting on a drive');
    ALL = keep; 
    return 'ready / offline / unowned told apart, Sync counts 1';
  });

  record('the health strip shows volumes, not sources', () => {
    // A folder on the internal disk cannot be unplugged, so a dot for it is
    // a dot that never changes -- and this strip is read by glancing at
    // what is different. Added when a second source went in and the strip
    // grew a permanent green light.
    // TWO SOURCES ON ONE DRIVE IS ONE DRIVE. The server deduplicates to
    // volumes; this pins that the strip shows one slot, not two, and that
    // the boot volume never takes a slot at all.
    HEALTH.volumes = [
      {name:'Music Drive', path:'/Volumes/Music Drive', online:false,
       removable:true, sources:2},
      {name:'this Mac', path:'/', online:true, removable:false, sources:1},
    ];
    paintHealth();
    let html = document.getElementById('hstrip').innerHTML;
    assert(html.includes('Music Drive'), 'the drive lost its slot in the strip');
    // one <i> per slot; the strip also carries iPod and Music, so count
    // only the slots that name this drive
    const driveSlots = html.split('<i ').slice(1)
                           .filter(x => x.includes('Music Drive')).length;
    assert(driveSlots === 1, `one drive carrying two sources took ${driveSlots} slots`);
    assert(!html.includes('this Mac'), 'the boot volume took a slot it can never change');
    assert(html.includes('offline'), 'an unmounted drive did not read as offline');
    assert(/2 sources/.test(html), 'the title did not say how many sources are on the drive');

    // the library's reach is NOT health -- it lives with the library
    assert(!/readable/.test(html),
      'library reach is in the strip; it belongs with the library pane');

    HEALTH.volumes[0].online = true; paintHealth();
    html = document.getElementById('hstrip').innerHTML;
    assert(!html.includes('offline'), 'a mounted drive still read as offline');

    // nothing configured must not throw
    HEALTH.volumes = []; paintHealth();
    HEALTH.volumes = null; paintHealth();
    return 'one slot per removable volume, boot volume hidden';
  });

  record('mark() tracks the cursor without touching a MARKed row', () => {
    ORDER['DayClub'] = ['t1', 't2', 't3', 't4'];
    colPick = 'DayClub'; active = 'ipod'; clearMark(); draw();
    assert(view.length === 4, `expected 4 rows in the collection view, got ${view.length}`);
    sel = 2; mark();
    const rows = document.querySelectorAll('#list .row');
    const selRow = document.querySelector('#list .row[data-i="2"]');
    assert(selRow && selRow.classList.contains('sel'), 'the cursor row did not get .sel');
    assert(selRow.getAttribute('aria-selected') === 'true', 'the cursor row (no multi-select) must read aria-selected=true');
    const others = rows.filter(r => r !== selRow);
    assert(others.every(r => r.getAttribute('aria-selected') === 'false'), 'a non-cursor row kept aria-selected=true with no selection live');
    assert(document.getElementById('list').getAttribute('aria-activedescendant') === selRow.id,
      'aria-activedescendant does not point at the cursor row');
    // a real multi-selection, live: rowHTML() bakes aria-selected from MARK,
    // and mark() must not fight it -- "touching it here only in the
    // no-mark case is what keeps the two from fighting" (curate.html).
    setMark([view[0].key, view[1].key]); draw(); sel = 3; mark();
    const marked = document.querySelectorAll('#list .row.marked');
    assert(marked.length === 2, `expected 2 .marked rows, got ${marked.length}`);
    assert(marked.every(r => r.getAttribute('aria-selected') === 'true'), 'a marked row lost aria-selected when the cursor moved');
    const cursorRow = document.querySelector('#list .row[data-i="3"]');
    assert(cursorRow.classList.contains('sel'), 'the cursor row lost .sel while a selection was live');
    clearMark(); colPick = null; draw();
    return '4-row collection: cursor tracked, marked rows left alone by mark()';
  });

  console.log(JSON.stringify(RESULTS));
  process.exit(0);
})().catch(e => { console.log(JSON.stringify([{ name: 'harness', ok: false, error: String(e.stack || e) }])); process.exit(0); });
'''

_HARNESS_CACHE = None


def _run_harness():
    """Run the node driver exactly once per process; cache the per-check
    results so every node_check() below is a dict lookup, not a subprocess."""
    global _HARNESS_CACHE
    if _HARNESS_CACHE is not None:
        return _HARNESS_CACHE
    node = _node()
    if not node:
        _HARNESS_CACHE = {}
        return _HARNESS_CACHE
    tmp = tempfile.mkdtemp(prefix='saltpod-pagetest-')
    try:
        driver = os.path.join(tmp, 'driver.js')
        tests = os.path.join(tmp, 'assertions.js')
        with open(driver, 'w') as fh:
            fh.write(_DRIVER_JS)
        with open(tests, 'w') as fh:
            fh.write(_TESTS_JS)
        try:
            r = subprocess.run([node, driver, CURATE, tests],
                               capture_output=True, text=True, timeout=30)
            text = (r.stdout or '').strip()
            line = text.splitlines()[-1] if text else ''
            items = json.loads(line) if line else [
                {'name': 'harness', 'ok': False,
                 'error': 'no output on stdout -- stderr: %s' % (r.stderr or '')[-500:]}]
        except subprocess.TimeoutExpired:
            items = [{'name': 'harness', 'ok': False, 'error': 'node did not finish within 30s'}]
        except ValueError as e:
            items = [{'name': 'harness', 'ok': False,
                     'error': 'could not parse the harness output as JSON: %s' % e}]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _HARNESS_CACHE = {item['name']: item for item in items}
    return _HARNESS_CACHE


def node_check(name):
    """A check() function reading one named result out of the single node
    run. SKIPs cleanly (never fails) when node is not installed."""
    def fn():
        if not _node():
            return _skip('node not found on PATH -- see the module docstring for why '
                         'osascript/Safari was rejected instead')
        results = _run_harness()
        if name not in results:
            raise RuntimeError('the harness produced no result named %r -- it likely '
                               'crashed before reaching it; names present: %s'
                               % (name, sorted(results)))
        item = results[name]
        if not item['ok']:
            raise AssertionError(item.get('error') or 'failed')
        return item.get('detail') or 'ok'
    return fn


def t_harness_boots():
    if not _node():
        return _skip('node not found on PATH')
    results = _run_harness()
    boot = results.get('harness')
    if boot is not None and not boot['ok']:
        raise RuntimeError(boot.get('error') or 'the harness crashed with no error message')
    return '%d checks ran inside one node process' % len(results)


# ------------------------------------------------------------------ static
# accessibility checks that need no execution at all -- option 3's spirit,
# kept for exactly the sub-checks that are genuinely static. These never
# need node, so they run even when it is missing.

def _html_and_style():
    html = open(CURATE, encoding='utf-8').read()
    style = html.split('<style>')[1].split('</style>')[0]
    return html, style


def t_live_region():
    import re
    html, _style = _html_and_style()
    m = re.search(r'<div[^>]*\bid="live"[^>]*>', html)
    assert m, 'no #live element in the static page'
    tag = m.group(0)
    assert 'aria-live="polite"' in tag, 'the live region is not aria-live="polite": %s' % tag
    assert 'sr-only' in tag, 'the live region does not use the sr-only convention'
    assert "$('#live')" in html, 'nothing in the script writes into #live any more'
    return 'aria-live=polite, sr-only, and the script still targets #live'


def t_sr_only_not_display_none():
    import re
    _html, css = _html_and_style()
    m = re.search(r'\.sr-only\s*\{([^}]*)\}', css)
    assert m, 'no .sr-only rule defined'
    body = m.group(1)
    squeezed = body.replace(' ', '')
    assert 'display:none' not in squeezed, (
        '.sr-only uses display:none, which pulls content OUT of the accessibility '
        'tree -- the live region would never be announced: %s' % body.strip())
    return '.sr-only hides visually (clip + 1px box), never with display:none'


def t_reduced_motion_coverage():
    import re
    _html, css = _html_and_style()
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)   # comments can contain stray braces
    rm_re = re.compile(
        r'@media\s*\([^)]*prefers-reduced-motion:\s*reduce[^)]*\)\s*\{\s*([^{}]+?)\s*\{\s*([^{}]*?)\s*\}\s*\}')
    covered = set()
    for sel, _body in rm_re.findall(css):
        for s in sel.split(','):
            covered.add(s.strip())
    assert covered, 'no @media (prefers-reduced-motion: reduce) rule found at all'
    rule_re = re.compile(r'([^{}@]+)\{([^{}]*)\}')
    bad = []
    for sel, body in rule_re.findall(css):
        if 'transition:' not in body and 'animation:' not in body:
            continue
        if re.search(r'(transition|animation)\s*:\s*none\b', body):
            continue
        for s in sel.split(','):
            s = s.strip()
            if s and s not in covered:
                bad.append('%s { %s }' % (s, body.strip()[:70]))
    assert not bad, 'motion not covered by any prefers-reduced-motion rule: %s' % '; '.join(bad[:5])
    return '%d selector(s) turn real motion off under prefers-reduced-motion' % len(covered)


def t_token_census_ref():
    """Reference bin/selftest.py's own census rather than duplicating it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('saltpod_selftest', SELFTEST_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.t_token_census()


# -------------------------------------------------------------------- main
def _run_all():
    global PASS, FAIL, SKIP, _t0
    PASS, FAIL, SKIP = [], [], []
    _t0 = time.time()

    section('driving this page headlessly')
    check('the node harness runs cleanly', t_harness_boots)

    section('law 1 -- one slot, one meaning, nothing shifts')
    check('colRow reserves the menu slot', node_check('colRow reserves the menu slot'))

    section('ARIA -- the role comes from the caller')
    check('sync rows are checkboxes, never option', node_check('role comes from the caller (sync rows are checkboxes)'))
    check('role=option always has a listbox ancestor', node_check('role=option always has a listbox ancestor'))
    check('the ⋯ menus have an accessible name', node_check('the ⋯ menus have an accessible name'))

    section('accessibility -- static (no execution needed)')
    check('the live region exists and is aria-live=polite', t_live_region)
    check('.sr-only never uses display:none', t_sr_only_not_display_none)
    check('every transition/animation respects prefers-reduced-motion', t_reduced_motion_coverage)

    section('accessibility -- found while writing this suite (reported, not fixed)')
    check('a container role matches what it holds', node_check('a container role matches what it holds'))
    check('a sync checkbox names its track', node_check('a sync checkbox names its track'))

    section('law 8 -- a decision is one control that undoes itself')
    check('one control, flips its own label', node_check('law 8: one control, flips its own label'))

    section('law 7 -- nothing is drag-only')
    check('every draggable row has a menu equivalent', node_check('law 7: nothing is drag-only'))

    section('behaviour -- pass(), mark(), load()')
    check('load() boots every pane from the real functions', node_check('load() boots every pane'))
    check('pass() honors a real filter-pill click', node_check('pass() honors a real filter-pill click'))
    check('pass() honors a real search input', node_check('pass() honors a real search input'))
    check('mark() tracks the cursor, leaves MARK alone', node_check('mark() tracks the cursor without touching a MARKed row'))
    check('owned-but-offline is its own state', node_check('owned-but-offline is its own state, not unowned'))
    check('the strip shows volumes, not sources', node_check('the health strip shows volumes, not sources'))

    section('tokens (see bin/selftest.py -- not duplicated here)')
    check('no colour/radius/font-size literal outside :root', t_token_census_ref)


def run():
    """Run every check and return a BOOLEAN -- for folding into another
    suite's own PASS/FAIL accounting later. Prints exactly like main()
    (the caller can redirect stdout if that is unwanted); does not exit."""
    _run_all()
    return not FAIL


def main():
    print('saltpod pagetest   %s%s'
          % (time.strftime('%Y-%m-%d %H:%M'),
             '   (node not found -- behavioural checks will skip)' if not _node() else ''))
    _run_all()
    print('\n%d passed, %d failed, %d skipped   (%.1fs)'
          % (len(PASS), len(FAIL), len(SKIP), time.time() - _t0))
    if FAIL:
        print('\nfailures:')
        for name, why in FAIL:
            print('  %-56s %s' % (name, why))
        print('\nNote: a failure here is a real, evidenced gap in the page, not a')
        print('defect in the suite -- read the error text above for the exact markup.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
