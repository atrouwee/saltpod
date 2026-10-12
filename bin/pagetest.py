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
// The page carries two scripts since saltglass was vendored: the system's
// ground.js in a <script data-saltglass> tag, then the page's own bare
// <script>. The markup ends where the first of them starts; the vendored
// one runs first in the same context, exactly as the browser orders them,
// so the page's script finds window.Saltglass the way it does for real.
// The stylesheet is skipped before looking for <body>: the vendored CSS
// says "<body>" in a comment, and the first match used to be the tag.
const BODY_HTML = RAW.slice(RAW.indexOf('</style>')).split('<body>')[1].split('<script')[0];
const GLASS_M = RAW.match(/<script data-saltglass>([\s\S]*?)<\/script>/);
const GLASS_JS = GLASS_M ? GLASS_M[1] : '';
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
// style: plain property writes (el.style.display = 'none') keep working as
// before; setProperty/getPropertyValue exist so a custom property written
// by script (ground.js sets --gl-scrim-a on #ground) can be read back.
class StyleDecl {
  constructor(){ this._props = new Map(); }
  setProperty(n, v){ this._props.set(n, String(v)); }
  getPropertyValue(n){ return this._props.has(n) ? this._props.get(n) : ''; }
  removeProperty(n){ this._props.delete(n); }
}
class Element extends NodeBase {
  constructor(tag){
    super(1);
    this._tag = tag.toLowerCase();
    this.tagName = tag.toUpperCase();
    this.attrs = new Map();
    this._listeners = {};
    this.style = new StyleDecl();
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
// `art` and `ground` are the ground's inputs: t1 is measured (the server
// handed it a scrim), t2 has art the server has not measured yet (null),
// t4 has no art at all. The ground test walks the cursor through them.
const TRACKS = [
  { key:'t1', artist:'Aphex Twin', title:'Flim', album:'Come to Daddy',
    device:true, held:true, tier:'sync', vinyl:false, bought:true, t7:false, am:true, local:false,
    collections:['DayClub'], playlists:['DayClub'], on_ipod:true, lists:['on iPod','synced'],
    seconds:220, vinyl_owned:false, vinyl_wanted:false, state:'ready', play:null,
    decision:{verb:'remove', on:false, sets:{tier:'remove'}, digital_only:false},
    art:'/api/art/aphex-twin-come-to-daddy.jpg', ground:{ y:0.05, scrim:0.45 } },
  { key:'t2', artist:'Burial', title:'Archangel', album:'Untrue',
    device:false, held:true, tier:'undecided', vinyl:true, bought:true, t7:true, am:false, local:true,
    collections:[], playlists:[], on_ipod:false, lists:['on T7','owned digitally','vinyl to add'], release_label:'Burial \u2014 Untrue',
    seconds:245, vinyl_owned:false, vinyl_wanted:false, state:'offline', play:null,
    decision:{verb:'sync', on:false, sets:{tier:'sync'}, digital_only:true},
    art:'/api/art/burial-untrue.jpg', ground:null },
  { key:'t3', artist:'SAULT', title:'Wildfires', album:'Untitled',
    device:false, held:false, tier:'sync', vinyl:false, bought:false, t7:false, am:true, local:false,
    collections:['WARA - Listening'], playlists:['WARA - Listening'], on_ipod:false, lists:['to buy','rented only','not looked up'],
    seconds:200, price:1.29, vinyl_owned:false, vinyl_wanted:false, state:'unowned', play:null,
    decision:{verb:'buy', on:true, sets:{tier:'sync'}, digital_only:false} },
  { key:'t4', artist:'Objekt', title:'Ganzfeld', album:'Objekt #1',
    device:false, held:false, tier:'undecided', vinyl:false, bought:false, t7:false, am:false, local:false,
    collections:[], playlists:[], on_ipod:false, lists:[], seconds:300, vinyl_owned:false, vinyl_wanted:false,
    state:'unowned', play:null, decision:{verb:'buy', on:false, sets:{tier:'sync'}, digital_only:false} },
];
const COLLECTIONS = ['DayClub', 'WARA - Listening'];
const ORDER = { 'DayClub': ['t1'], 'WARA - Listening': ['t3'] };
const TOTALS = { to_buy: 1, to_buy_eur: 1.29, to_sync: 0, to_remove: 0, on_ipod: 1,
  sync_off: 0, sync_on: 0, sync_pending: 0, sync_waiting: 0,
  synced: 0, flac_to_buy: 0, not_looked_up: 1, vinyl_to_add: 1 };
const SYNCED = ['DayClub'];
const AMP = [
  // `art` is the server's tiled mosaic for the playlist (one picture); the
  // other two have none yet, so their rows show the empty thumbnail
  { name:'DayClub', slug:'dayclub', tracks:12, created:'2025-06-01', last:'2025-06-10', imported:true, art:'/api/art?playlist=dayclub' },
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
    '/api/tracks': { tracks: TRACKS, collections: COLLECTIONS, order: ORDER, totals: TOTALS, on_ipod_order: ['t1'], vinyl_order: ['Burial \u2014 Untrue'], synced: SYNCED, slugs: ['dayclub', 'wara-listening'], updated: null },
    '/api/discogs': { wantlist: [], collection: [], files: {}, dir: 'data/discogs' },
    '/api/playlists': { playlists: AMP, read_at: '2026-01-01', library: 500 },
    '/api/device': DEV,
    '/api/local': T7,
    '/api/plan': PLAN,
    '/api/health': HEALTH,
    '/api/undo': { can_undo: 0, can_redo: 0, next: null },
    '/api/decision': { ok: true, n: 2, verb: 'sync', on: false, sets: { tier: 'sync' }, digital_only: true },
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
  // Run #0: the vendored saltglass ground.js, when the page carries it. It
  // registers Saltglass.Ground on `window` (the sandbox's) and touches no
  // page state; the page's own script then mounts the ground from it.
  if (GLASS_JS) vm.runInContext(GLASS_JS, sandbox, { filename: 'saltglass-ground.js' });
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
    // Which row and which way round is the server's `decision`
    // (curate.decision_of, debt D2, pinned in selftest); the page owns only
    // the words. So each case hands it a decision and checks the label --
    // and that the click posts the tier the server said, not one of its own.
    const dec = (verb, on, tier) => ({ verb, on, sets: { tier }, digital_only: verb === 'sync' });
    const row = (k, d) => ({ key: k, artist: 'A', title: 'B', collections: [], vinyl: false, vinyl_owned: false, decision: d });
    const cases = [
      [row('x1', dec('remove', false, 'remove')), 'Remove from iPod'],
      [row('x1', dec('remove', true, 'undecided')), "Don't remove"],
      [row('x2', dec('sync', false, 'sync')), 'Sync to iPod'],
      [row('x2', dec('sync', true, 'undecided')), "Don't sync"],
      [row('x3', dec('buy', false, 'sync')), 'Buy'],
      [row('x3', dec('buy', true, 'sync')), "Don't buy"],
    ];
    for (const [t, want] of cases) {
      openMenu(anchor, 'track', t);
      assert(label() === want, `expected "${want}", got "${label()}"`); noUndecided();
    }
    const realDecide = decide; let sent = null;
    decide = (patch, keys) => { sent = { patch, keys }; return Promise.resolve(); };
    try {
      openMenu(anchor, 'track', cases[3][0]);
      document.querySelector('#menub .m-want').onclick();
      assert(sent && sent.patch.tier === 'undecided' && sent.keys.join() === 'x2',
        `Don't sync posted ${JSON.stringify(sent)}, not the server's sets`);
      sent = null;
      openMenu(anchor, 'track', cases[5][0]);
      document.querySelector('#menub .m-want').onclick();
      assert(sent && sent.patch.tier === 'sync', `Don't buy in a collection posted ${JSON.stringify(sent)}`);
    } finally { decide = realDecide; }
    closeMenu();
    return "Remove from iPod <-> Don't remove, Sync to iPod <-> Don't sync, Buy <-> Don't buy -- one row each, never two";
  });

  // Debt D10: sync progress is the job's `steps`, not the page's parse of
  // a 60-line log window.
  record('sync rows take their state from job.steps', () => {
    SP.plan = { ok: true, adds: [{ key: 't3', artist: 'SAULT', title: 'Wildfires', bytes: 5000000, convert: false }],
      removes: [{ key: 't5', artist: 'Old', title: 'Track' }], retags: [], new: [], update: [], delete: [],
      members: {}, sizes: {}, free_bytes: 5e9, unchanged: [] };
    SP.off = new Set(); SP.state = 'running'; SP.log = [];
    buildSyncRows();
    readSyncLog({ state: 'running', steps: [{ id: 'a:t3', state: 'done', error: null },
                                            { id: 'r:t5', state: 'error', error: 'gone' },
                                            { id: 'write', state: 'waiting', error: null }],
                  log: ['@@ a:t3 done', '## copy 1/1', 'copied one'] });
    const r = id => SP.rows.find(x => x.id === id);
    assert(r('a:t3').state === 'done', `a:t3 is ${r('a:t3').state}`);
    assert(r('r:t5').state === 'error' && r('r:t5').err === 'gone', 'the error step lost its state or message');
    assert(!r('write').state, 'a waiting step was given a state');
    assert(SP.log.length === 1 && SP.log[0] === 'copied one', `prose kept ${JSON.stringify(SP.log)}`);
    SP.state = 'review';
    return 'done / error / waiting from steps; only prose in the log';
  });

  // A selection's decision is asked of the server (/api/decision), never
  // combined from the rows here: the row shows a placeholder until it lands.
  await recordAsync('law 8: a selection asks the server for its decision', async () => {
    const tick = () => new Promise(r => setTimeout(r, 0));
    const anchor = document.createElement('span');
    setMark(['t1', 't2']);
    openMenu(anchor, 'track', BYKEY.get('t1'));
    const first = document.querySelector('#menub .drow .dn').textContent;
    await tick(); await tick(); await tick();
    const row = document.querySelector('#menub .m-want');
    assert(row, `no decision row after /api/decision answered (first paint said "${first}")`);
    const got = row.querySelector('.dn').textContent;
    assert(got === 'Sync to iPod', `expected the server's "Sync to iPod", got "${got}"`);
    closeMenu(); clearMark(); draw();
    return `"${first}" until the answer, then "${got}"`;
  });

  // Debt D8/D9: the buy pane's stages and the vinyl pane's to-do are
  // server lists and totals; the panes count nothing themselves.
  record('the buy and vinyl panes read the server lists', () => {
    const was = rtab;
    rtab = 'buy'; drawRight();
    const buy = document.getElementById('rstat').innerHTML;
    assert(/<s>1<\/s> synced/.test(buy), `buy pane did not count the 'synced' list: ${buy}`);
    const la = document.getElementById('lookall');
    assert(la && /Look up the 1 /.test(la.textContent), `"Look up" did not read TOTALS.not_looked_up: ${la && la.textContent}`);
    rtab = 'vinyl'; drawRight();
    const vin = document.getElementById('rstat').innerHTML;
    assert(/<s>1<\/s> to add/.test(vin), `vinyl pane did not read 'vinyl to add': ${vin}`);
    assert(document.getElementById('rbody').innerHTML.includes('Burial \u2014 Untrue'), 'the release card lost its server label');
    rtab = was; drawRight();
    return 'synced, not looked up, vinyl to add: all looked up';
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

  // ------------------------------- law 7: nothing is keyboard-only either
  // Two holes the first glass pass left (DESIGN-GLASS.md 3.1): reordering a
  // collection was J/K only, and the footer's undo hint was a span with no
  // handler under a key cap that said ⌘Z. The menu's four Move rows call the
  // same nudge() the keys do, and #undoc is a button that calls the same
  // undo. post() is replaced for the duration so the server call each one
  // makes is observed rather than sent.
  await recordAsync('law 7: the row menu moves a row, the footer undoes', async () => {
    const tick = () => new Promise(r => setTimeout(r, 0));
    const row = c => document.querySelector('#menub .' + c);
    const anchor = document.createElement('span');
    ORDER['DayClub'] = ['t1', 't2', 't3'];
    colPick = 'DayClub'; active = 'ipod'; filter = 'all'; clearMark(); draw();
    assert(view.length === 3, `expected 3 rows in the collection view, got ${view.length}`);
    const t2 = view.find(x => x.key === 't2'); assert(t2, 't2 not in view');
    openMenu(anchor, 'track', t2);
    ['m-up', 'm-down', 'm-top', 'm-bottom'].forEach(c => assert(row(c), `no ${c} row in the track menu inside a collection`));
    assert(row('m-up').querySelector('.dk').textContent === 'K' && row('m-down').querySelector('.dk').textContent === 'J',
      'Move up / Move down do not carry their key caps (K / J)');
    const realPost = post; const posted = [];
    post = (url, body) => { posted.push({ url, body }); return Promise.resolve({ ok: true }); };
    try {
      const reorder = () => { const p = posted[posted.length - 1]; assert(p && p.url === '/api/decide' && p.body.reorder, 'no reorder was posted'); return p.body.reorder; };
      row('m-bottom').onclick(); await tick();
      assert(reorder().collection === 'DayClub' && reorder().keys.join() === 't1,t3,t2', `Move to bottom gave ${reorder().keys.join()}`);
      openMenu(anchor, 'track', view.find(x => x.key === 't2'));
      row('m-top').onclick(); await tick();
      assert(reorder().keys.join() === 't2,t1,t3', `Move to top gave ${reorder().keys.join()}`);
      openMenu(anchor, 'track', view.find(x => x.key === 't2'));
      row('m-down').onclick(); await tick();
      assert(reorder().keys.join() === 't1,t2,t3', `Move down gave ${reorder().keys.join()}`);
      openMenu(anchor, 'track', view.find(x => x.key === 't2'));
      row('m-up').onclick(); await tick();
      assert(reorder().keys.join() === 't2,t1,t3', `Move up gave ${reorder().keys.join()}`);
      const n = posted.length;
      // outside a collection there is no order to move in, so no rows
      clearMark(); colPick = null; draw();
      openMenu(anchor, 'track', ALL[0]);
      assert(!row('m-up') && !row('m-bottom'), 'Move rows offered where there is no order to move in');
      closeMenu();
      // (d) the undo hint is a button that undoes
      drawFoot();
      const u = document.getElementById('undoc');
      assert(u && u.tagName === 'BUTTON', `#undoc is ${u ? 'a ' + u.tagName : 'missing'}, not a button`);
      assert(typeof u.onclick === 'function', '#undoc has no click handler');
      await u.onclick();
      const last = posted[posted.length - 1];
      assert(posted.length === n + 1 && last.url === '/api/undo' && last.body.redo === false,
        `clicking #undoc should post /api/undo {redo:false}, saw ${JSON.stringify(last)}`);
    } finally { post = realPost; }
    return 'four Move rows (K/J caps) each post the reordered keys; none outside a collection; #undoc is a button that posts /api/undo';
  });

  // ---------------------------------------------------------------- pass()
  record('pass() honors a real filter-popover choice', () => {
    colPick = 'DayClub'; active = 'ipod'; draw();
    document.getElementById('fltoggle').onclick();
    const row = document.querySelector('#menub [data-f="to buy"]');
    assert(row, 'no "to buy" row in the filter popover');
    row.onclick();
    assert(filter === 'to buy', `choosing the row left filter=${filter}`);
    assert(pass({ lists: ['to buy'], artist: 'a', title: 'b', album: 'c' }) === true, 'pass() rejected a to-buy track while filter=to buy');
    assert(pass({ lists: ['on T7'], artist: 'a', title: 'b', album: 'c' }) === false, 'pass() accepted a non-matching track while filter=to buy');
    document.getElementById('fltoggle').onclick();
    document.querySelector('#menub [data-f="all"]').onclick();
    assert(filter === 'all', 'choosing All did not reset filter');
    return 'a real popover choice changes filter, and pass() obeys it';
  });

  // ------------------------------------------------- the filter popover
  // The filter row is gone; the funnel in the centre strip opens the row
  // menu with one radio row per filter. The counts at the right are the
  // server's totals, read from the payload, or nothing: the page computes
  // none (the layer rule). The harness's document.addEventListener is a
  // no-op, so the keyboard is exercised through menuKeys() directly, which
  // is the function the document handler delegates to.
  record('the funnel opens a filter popover of radio rows', () => {
    colPick = null; active = 'am'; filter = 'all'; clearMark(); draw();
    const t = document.getElementById('fltoggle');
    assert(t && t.getAttribute('aria-haspopup') === 'menu', '#fltoggle does not declare the popup it owns');
    assert(t.getAttribute('aria-expanded') === 'false', 'a closed toggle says it is expanded');
    assert(!document.querySelector('#flmodes .fname'), 'the strip names a filter while All is on');
    t.onclick();
    assert(MENU && MENU.kind === 'filter', 'clicking the funnel did not open the filter menu');
    assert(menu.classList.contains('on') && menu.classList.contains('fpop'), 'the menu is not shown as the filter popover');
    assert(menu.getAttribute('role') === 'menu', 'the popover is not a menu by role');
    assert(document.getElementById('fltoggle').getAttribute('aria-expanded') === 'true', 'the open toggle does not say so');
    assert(document.getElementById('menuh').textContent.trim() === 'Show', 'the strip does not say Show');
    const rows = document.querySelectorAll('#menub [role="menuitemradio"]');
    assert(rows.length === FILTERS.length, `expected a row per filter (${FILTERS.length}), got ${rows.length}`);
    const checked = rows.filter(r => r.getAttribute('aria-checked') === 'true');
    assert(checked.length === 1 && checked[0].dataset.f === filter,
      `expected exactly one checked row, for ${filter}; got ${checked.map(r => r.dataset.f).join() || 'none'}`);
    const buy = rows.find(r => r.dataset.f === 'to buy');
    assert(buy && buy.querySelector('.dk') && buy.querySelector('.dk').textContent === String(TOTALS.to_buy),
      'the to-buy count is not the server\'s total');
    assert(buy.querySelector('.dn').textContent === 'To buy', 'the label is not the filter name capitalised');
    const rented = rows.find(r => r.dataset.f === 'rented only');
    assert(rented && !rented.querySelector('.dk'), 'a count the server did not send was shown (computed in the page?)');
    // choosing sets the filter, closes, and the strip names it
    buy.onclick();
    assert(filter === 'to buy', `choosing left filter=${filter}`);
    assert(!MENU && !menu.classList.contains('on'), 'choosing did not close the popover');
    const nm = document.querySelector('#flmodes .fname');
    assert(nm && nm.textContent === 'to buy', 'the strip does not name the active filter beside the funnel');
    assert(document.getElementById('fltoggle').getAttribute('aria-expanded') === 'false', 'the toggle still says expanded');
    // the keyboard: arrows move, Escape closes and the funnel is told
    document.getElementById('fltoggle').onclick();
    assert(MENU && MENU.kind === 'filter', 'reopening the popover failed');
    const ev = k => ({ key: k, preventDefault(){} });
    assert(menuKeys(ev('ArrowDown')) === true, 'ArrowDown was not handled');
    const foc = document.querySelector('#menub .drow.focus');
    assert(foc && foc.dataset.f === FILTERS[FILTERS.indexOf('to buy') + 1], 'ArrowDown did not move from the checked row to the next');
    assert(menuKeys(ev('Escape')) === true && !MENU, 'Escape did not close the popover');
    assert(menuKeys(ev('x')) === false, 'an unrelated key was swallowed while the popover was closed');
    // and back to All
    document.getElementById('fltoggle').onclick();
    document.querySelector('#menub [data-f="all"]').onclick();
    assert(filter === 'all' && !document.querySelector('#flmodes .fname'), 'choosing All did not clear the name');
    return `${rows.length} radio rows, one checked, server counts only, choose/Escape/arrows`;
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
  record('the busy dot and the filter dot are spoken, not only coloured', () => {
    // Both were colour alone: the gear's busy marker is a CSS pseudo-element,
    // and the filter toggle was a span with a click handler, no role, and no
    // way to reach it from the keyboard.
    gearBusy(true);
    const g = document.getElementById('gear');
    assert(g.getAttribute('aria-busy') === 'true', 'aria-busy not set while a job runs');
    assert(/job is running/.test(g.getAttribute('aria-label') || ''), 'the gear does not say a job is running');
    gearBusy(false);
    assert(g.getAttribute('aria-busy') === 'false', 'aria-busy stayed true');
    assert(!/running/.test(g.getAttribute('aria-label') || ''), 'the label still says running');
    paintFilterToggle();
    const t = document.getElementById('fltoggle');
    assert(t && t.getAttribute('role') === 'button', 'the filter toggle has no button role');
    assert(t.getAttribute('tabindex') === '0', 'the filter toggle cannot be reached from the keyboard');
    assert(/filter: showing/.test(t.getAttribute('aria-label') || ''), 'the filter state is not in its name');
    // a filter that is on is named in the strip, in text, not marked by a colour
    const was = filter; filter = 'to buy'; paintFilterToggle();
    const nm = document.querySelector('#flmodes .fname');
    assert(nm && nm.textContent === 'to buy', 'an active filter is not named beside the funnel');
    assert(/showing to buy/.test(document.getElementById('fltoggle').getAttribute('aria-label') || ''), 'the toggle does not say which filter is on');
    filter = was; paintFilterToggle();
    return 'aria-busy, labels, role, tabindex, the filter named in text';
  });

  record('owned-but-offline is its own state, not unowned', () => {
    // Three states, because "buy it" and "plug the drive in" are different
    // instructions. Before this, a track on an unplugged drive rendered at
    // full ink and the Sync button counted it as ready to write.
    const mk = (k, o) => Object.assign({key:k, artist:'A', title:k, tier:'sync',
      collections:['C'], lists:[], playlists:[], seconds:100}, o);
    // `state` is the server's answer (curate.row_state, debt D3, pinned in
    // selftest); the page must render each one, never re-derive it
    const ready   = mk('ready',   {local:true,  reachable:true,  device:false, state:'ready'});
    const offline = mk('offline', {local:true,  reachable:false, device:false, t7:true, state:'offline'});
    const unowned = mk('unowned', {local:false, reachable:false, device:false, state:'unowned'});

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
    // a drive that is out is not a track that is gone: the name stays
    // legible and takes a dot, rather than being struck through
    assert(/class="away"[^>]*>T7</.test(hO), 'the drive badge lost its away marker');
    assert(!/class="gone"[^>]*>T7</.test(hO), 'the drive badge is still struck through');

    // and the Sync button must not promise what it cannot write. The count
    // is the server's (curate.sync_counts, debt D1, tested in selftest);
    // the page shows TOTALS and adds nothing up -- so it is handed the
    // answer for these three rows and must print exactly that.
    const keep = ALL, keepT = TOTALS;
    ALL = [ready, offline, unowned];
    TOTALS = Object.assign({}, keepT, {sync_off:0, sync_on:1, sync_pending:1, sync_waiting:1});
    counts();
    const sb = document.getElementById('dosync');
    assert(sb.textContent === 'Sync · 1',
      `Sync did not show the server's count: ${sb.textContent}`);
    assert(/not mounted/.test(sb.title), 'the button does not mention the ones waiting on a drive');
    ALL = keep; TOTALS = keepT; counts();
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

  // ------------------------------------ the ground follows the selection
  // The layer rule, exercised: the page hands the ground the row's own art
  // and the scrim the SERVER measured for it, and works out neither. The
  // sandbox has no getComputedStyle, so Saltglass.Ground falls back to its
  // 250 ms settle; the timers are real, so the test rests a little longer
  // than that between moves. A row the server has not measured yet must
  // leave the ground at the system's unknown default; a row with no art
  // must leave the ground flat.
  await recordAsync('the ground follows the selection, from the payload only', async () => {
    const rest = ms => new Promise(r => setTimeout(r, ms));
    const g = document.getElementById('ground');
    assert(g, 'no #ground element in the page');
    const live = () => g.querySelectorAll('img').find(i => i.classList.contains('on')) || null;
    const scrim = () => g.style.getPropertyValue('--gl-scrim-a');
    ORDER['DayClub'] = ['t1', 't2', 't3', 't4'];
    colPick = 'DayClub'; active = 'ipod'; clearMark(); draw();
    assert(view.length === 4, `expected 4 rows in the collection view, got ${view.length}`);
    const at = key => { const i = view.findIndex(t => t.key === key); assert(i >= 0, `${key} not in view`); return i; };
    const t1 = view[at('t1')], t2 = view[at('t2')], t4 = view[at('t4')];
    assert(t1.art && t1.ground && t2.art && t2.ground === null && !t4.art, 'the fixture lost the shapes this test needs');
    sel = at('t1'); mark();
    assert(!(live() && live().getAttribute('src') === t1.art), 'the ground moved before the selection had settled');
    await rest(320);
    assert(live() && live().getAttribute('src') === t1.art,
      `after the settle the live layer should show ${t1.art}, got ${live() && live().getAttribute('src')}`);
    assert(scrim() === String(t1.ground.scrim),
      `--gl-scrim-a on #ground should be the server's ${t1.ground.scrim}, got ${JSON.stringify(scrim())}`);
    sel = at('t2'); mark(); await rest(320);
    assert(live() && live().getAttribute('src') === t2.art, `the ground did not follow to ${t2.art}`);
    assert(scrim() === 'var(--gl-scrim-unknown)',
      `an unmeasured row must leave the scrim at the unknown default, got ${JSON.stringify(scrim())}`);
    sel = at('t4'); mark(); await rest(320);
    assert(!live(), 'a row without art left a picture under the page');
    clearMark(); colPick = null; draw();
    return 'measured -> its scrim; unmeasured -> --gl-scrim-unknown; no art -> flat; all after the settle';
  });

  // ------------------------------------------------ the chrome: the footer
  // The keys change with what you are looking at, and they come from the
  // page's own table (KEYS), not from anything worked out. "?" opens every
  // key by context on the menu material; Escape closes it.
  record('the footer names the keys for the context; ? lists them all', () => {
    const keys = () => document.getElementById('keys');
    const caps = () => keys().querySelectorAll('.kk').filter(k => !k.classList.contains('all')).map(k => k.textContent);
    rightFocus = false; clearMark();
    active = 'ipod'; colPick = 'DayClub'; drawFoot();
    const col = caps();
    assert(col.some(c => /take out/.test(c)) && col.some(c => /move/.test(c)), `a collection should offer take out and move, got ${col.join(' | ')}`);
    assert(keys().querySelectorAll('.kk.p').length > 0 && keys().querySelectorAll('.kk.s').length > 0, 'the keys are not split into primaries (ink) and the rest (dim)');
    assert(col.indexOf(col.find(c => /play/.test(c))) < col.indexOf(col.find(c => /search/.test(c))), 'the primaries do not come first');
    active = 'ipod'; colPick = null; drawFoot();
    const all = caps();
    assert(!all.some(c => /take out|move/.test(c)) && all.some(c => /sync/.test(c)), `All on iPod should be the collection row without take out and move, got ${all.join(' | ')}`);
    active = 'am'; drawFoot();
    const am = caps();
    assert(am.some(c => /add to collection/.test(c)) && am.some(c => /buy/.test(c)) && am.some(c => /preview/.test(c)) && !am.some(c => /take out/.test(c)),
      `an Apple Music playlist should offer add to collection, buy, preview, got ${am.join(' | ')}`);
    assert(JSON.stringify(am) !== JSON.stringify(col), 'the keys did not change between an iPod collection and an Apple Music playlist');
    active = 't7'; drawFoot();
    assert(caps().some(c => /add to collection/.test(c)) && !caps().some(c => /buy/.test(c)), `the drive's keys are wrong: ${caps().join(' | ')}`);
    rightFocus = true; drawFoot();
    assert(caps()[0] && /buy/.test(caps()[0]), `with the right pane focused the buy list's keys should lead, got ${caps().join(' | ')}`);
    rightFocus = false; active = 'ipod'; drawFoot();
    // every cap in the table is a key the keydown handler handles, by name
    const table = Object.values(KEYS).flat().map(x => x[0]);
    const known = new Set(['space', 's', 'x', 'c', 'i', '.', '/', 'b', 'v', '⇧J', '⇧K']);
    const unknown = table.flatMap(c => c.split(' ')).filter(c => !known.has(c));
    assert(!unknown.length, `caps the handler does not know: ${unknown.join(', ')}`);
    // "?" opens the listing on the menu material: every key, by context
    const a = document.getElementById('allkeys');
    assert(a && a.getAttribute('aria-haspopup') === 'menu', 'the footer has no "?" control owning a popup');
    a.onclick({ stopPropagation(){} });
    assert(MENU && MENU.kind === 'keys' && menu.classList.contains('on'), '"?" did not open the keys popover');
    assert(a.getAttribute('aria-expanded') === 'true', 'the open "?" does not say so');
    const rows = document.querySelectorAll('#menub .krow');
    const want = KEY_GROUPS.reduce((n, [k]) => n + KEYS[k].length, 0);
    assert(rows.length === want, `the popover lists ${rows.length} keys, the four contexts hold ${want}`);
    assert(document.querySelectorAll('#menub .month').length === KEY_GROUPS.length, 'the popover is not grouped by the four contexts');
    assert(rows.every(r => r.querySelector('kbd') && r.querySelector('.dn').textContent), 'a row lacks its cap or its verb');
    assert(menuKeys({ key: 'Escape', preventDefault(){} }) === true && !MENU && !menu.classList.contains('on'), 'Escape did not close the popover');
    toggleKeysMenu(); assert(MENU && MENU.kind === 'keys', 'the ? key\'s toggle did not open it');
    toggleKeysMenu(); assert(!MENU, 'the ? key\'s toggle did not close it again');
    return `${want} keys in ${KEY_GROUPS.length} groups; contexts: collection, All on iPod, Apple Music, drive, buy list`;
  });

  // ------------------------------------------ the chrome: playlist mosaics
  record('Music rows carry a mosaic from the payload, or the empty thumbnail', () => {
    stab = 'am'; drawSrc();
    const rows = document.querySelectorAll('#srcbody .col[data-am]').filter(r => r.dataset.am !== '__all__');
    assert(rows.length === AMP.length, `expected ${AMP.length} playlist rows, got ${rows.length}`);
    for (const r of rows) {
      const p = AMP.find(x => x.slug === r.dataset.am);
      const m = r.querySelector('.mosaic');
      assert(m, `${p.name} has no .mosaic slot`);
      const img = m.querySelectorAll('img');
      if (p.art) {
        assert(img.length === 1 && img[0].getAttribute('src') === p.art, `${p.name}: the mosaic should be the payload's one tiled picture ${p.art}, got ${img.map(i => i.getAttribute('src')).join()}`);
      } else {
        assert(img.length === 0, `${p.name} has no art yet but shows ${img.length} img -- the page is not allowed to build one`);
      }
      const sub = r.querySelector('.nm.two .sub');
      assert(sub && sub.textContent === `${p.tracks} tracks · ${p.created.slice(0, 7)}`, `${p.name}'s second line is ${sub && sub.textContent}`);
      assert(r.querySelector('.cnt').textContent === String(p.tracks), `${p.name}'s count is not the payload's ${p.tracks}`);
    }
    assert(!document.querySelector('#srcbody canvas'), 'a canvas in the source pane: the mosaic is the server\'s to make');
    return `${rows.length} rows: 1 with the server's mosaic, ${rows.length - 1} with the empty thumbnail; count and month from the payload`;
  });

  // ---------------------------------------------- the chrome: the panels
  await recordAsync('the panels are patterned from the system\'s parts', async () => {
    const colourStyle = html => (html.match(/style="[^"]*"/g) || []).filter(s => /color|background|border|fill|rgb|#[0-9a-f]{3}/i.test(s));
    await openSync();
    const sp = document.getElementById('sp');
    assert(sp.classList.contains('on') && SP.state === 'review', 'the sync panel did not open on the fixture plan');
    assert(!sp.querySelector('.box') && !sp.querySelector('pre'), 'Review sync still holds a .box or a bare <pre>');
    const spBad = colourStyle(sp.innerHTML);
    assert(!spBad.length, `Review sync carries a colour in an inline style: ${spBad[0]}`);
    assert(sp.querySelector('.plabel').classList.contains('gl-strip'), 'Review sync\'s title strip is not .gl-strip');
    const bar = sp.querySelector('.substat');
    assert(bar && bar.classList.contains('gl-strip'), 'Review sync\'s action bar is not .gl-strip');
    const go = document.getElementById('spgo');
    assert(go && go.classList.contains('gl-action'), 'Confirm is not the one action (.gl-action)');
    assert(document.getElementById('spdrop') && !document.getElementById('spdrop').classList.contains('gl-action'), 'Cancel should be a secondary capsule');
    const rows = sp.querySelectorAll('#spbody .row');
    assert(rows.length === 4 && rows.every(r => r.querySelector('.mark') && r.querySelector('.art') && r.querySelector('.t .n') && r.querySelector('.t .s')),
      `every plan row needs a mark, art, a name and a second line; got ${rows.length} rows`);
    assert(rows.map(r => r.querySelector('.mark').textContent).join('') === '+–~+', `the marks read ${rows.map(r => r.querySelector('.mark').textContent).join(' ')}`);
    assert(sp.querySelectorAll('#spbody .step').length === 4, 'the four infrastructure steps are not steps');
    assert(sp.querySelector('#spbody .gauge i') && sp.querySelector('#spbody .gstat b'), 'no "after" gauge with a stat line');
    assert(sp.querySelector('#spbody .fact b'), 'the summary is not a .fact with the numbers in ink');
    assert(sp.querySelectorAll('#spbody [role="checkbox"]').length === 4, 'the plan rows stopped being checkboxes');
    // the row's second line is album · duration · what happens, looked up, not computed
    const add = rows.find(r => r.dataset.id === 'a:t3');
    assert(add && add.querySelector('.s').textContent === 'Untitled · 3:20 · as is · 5 MB', `the add row's line reads ${add && add.querySelector('.s').textContent}`);
    closeSync();
    SLUGS = ['dayclub', 'wara-listening']; openSettings();
    const rs = document.getElementById('rsheet');
    assert(!rs.querySelector('.box') && !rs.querySelector('pre') && !rs.querySelector('.brow'), 'Data still holds a .box, .brow or a bare <pre>');
    const rsBad = colourStyle(rs.innerHTML);
    assert(!rsBad.length, `Data carries a colour in an inline style: ${rsBad[0]}`);
    assert(rs.querySelector('.plabel').classList.contains('gl-strip'), 'Data\'s title strip is not .gl-strip');
    assert(rs.querySelector('.two') && rs.querySelector('.two').children.length === 2, 'Data is not two columns (.two)');
    assert(rs.querySelectorAll('.fact').length >= 6 && rs.querySelectorAll('.month').length >= 6, 'Data\'s sections are not facts under labels');
    for (const id of ['doAM', 'doIndex', 'doDevice', 'doMatch', 'doVerify', 'doRebuild', 'loadMusic', 'slug', 'jobbox', 'jobname', 'jobstate', 'joblog'])
      assert(document.getElementById(id), `Data lost #${id}, which a handler uses`);
    assert(rs.querySelectorAll('button').every(b => !b.classList.contains('gl-action')), 'Data has no one action; every button is secondary');
    assert(document.getElementById('joblog').classList.contains('log'), 'the job log is not the .log pattern');
    assert(document.getElementById('slug').classList.contains('gl-field'), 'the select is not a field');
    closeSettings();
    return 'Review sync: strip, 4 marked rows, gauge, 4 steps, floating bar with the one action; Data: strip, two columns, facts, capsules, the job as a log';
  });

  // ---------------------------------------- first release, web (fr-web)
  // Esc on the "Unsaved changes" prompt is its Cancel: the prompt goes, the
  // edits and the panel stay. Its field is hidden, so nothing focused could
  // catch the key; dlgKey is what the document's keydown handler calls.
  record('Esc closes the Unsaved changes prompt, as Cancel', () => {
    const tp = document.getElementById('tp');
    TP.edits = { title: 'edited' }; tp.classList.add('on');
    askDropEdits();
    assert(dlg.classList.contains('on'), 'the prompt did not open');
    let prevented = false;
    const handled = dlgKey({ key: 'Escape', preventDefault() { prevented = true; } });
    assert(handled && prevented, 'Esc was not handled while the prompt was up');
    assert(!dlg.classList.contains('on'), 'Esc left the prompt open');
    assert(TP.edits.title === 'edited' && tp.classList.contains('on'), 'Esc discarded the edits or closed the panel');
    assert(dlgKey({ key: 'Escape', preventDefault() {} }) === false, 'with no prompt up, Esc is not the prompt\'s');
    TP.edits = {}; tp.classList.remove('on');
    return 'prompt closed; edits and panel kept';
  });

  // The blocked Review sync re-plans in place when the poll sees the iPod;
  // with the panel shut, the ordinary pre-sync read runs instead.
  record('the blocked Review sync re-plans when the iPod appears', () => {
    const real = { openSync, preSync, load };
    const calls = [];
    openSync = () => { calls.push('openSync'); };
    preSync = () => { calls.push('preSync'); };
    load = () => { calls.push('load'); return Promise.resolve(); };
    const sp = document.getElementById('sp');
    try {
      SP.state = 'blocked'; sp.classList.add('on'); lastPod = 'absent';
      podChanged('ready');
      assert(calls.includes('openSync') && !calls.includes('preSync'), `blocked panel: ${calls.join()}`);
      calls.length = 0; podChanged('ready');
      assert(!calls.length, `ready twice re-planned again: ${calls.join()}`);
      sp.classList.remove('on'); SP.state = 'review'; lastPod = 'absent';
      podChanged('ready');
      assert(calls.join() === 'preSync', `panel shut: ${calls.join()}`);
    } finally {
      openSync = real.openSync; preSync = real.preSync; load = real.load;
      sp.classList.remove('on'); SP.state = 'review';
    }
    return 'blocked: re-plans; shut: pre-sync; once per arrival';
  });

  // "Re-read the device" toasts what the server read, or why it read nothing.
  await recordAsync('Re-read the device says what it read', async () => {
    const realPost = post, realLoad = load;
    load = () => Promise.resolve();
    const said = () => document.getElementById('toast').textContent;
    try {
      post = () => Promise.resolve({ ok: true, read: 'backup', from: 'ipod-2026-01-02' });
      await rereadDevice();
      assert(/backup/.test(said()) && /ipod-2026-01-02/.test(said()), `backup read toasted as: ${said()}`);
      post = () => Promise.resolve({ ok: true, read: 'device' });
      await rereadDevice();
      assert(said() === 'device re-read', `device read toasted as: ${said()}`);
      post = () => Promise.resolve({ ok: false, error: 'no iPod and no backup to read' });
      await rereadDevice();
      assert(said() === 'no iPod and no backup to read', `refusal toasted as: ${said()}`);
    } finally { post = realPost; load = realLoad; }
    return 'device, backup (named), and the refusal';
  });

  // The file is the proof: the Buy card has no "bought" button.
  record('the buy card has no bought button', () => {
    const was = rtab; rtab = 'buy'; drawRight();
    const body = document.getElementById('rbody');
    assert(!body.querySelector('[data-bought]'), 'a card still carries the bought button');
    assert(body.innerHTML.includes('SAULT'), 'the card to buy is not drawn');
    rtab = was; drawRight();
    return 'cards drawn, no flag to set';
  });

  // The Data sheet names a music folder; the server checks it and says why not.
  await recordAsync('the Data sheet names a music folder', async () => {
    openSettings();
    const field = document.getElementById('srcpath'), btn = document.getElementById('doSource');
    assert(field && btn, 'no music folder field');
    assert(field.getAttribute('aria-label'), 'the field has no accessible name');
    const realPost = post; const posted = [];
    post = (url, body) => { posted.push({ url, body }); return Promise.resolve({ ok: false, error: 'no such folder: /x' }); };
    try {
      field.value = '/x'; await btn.onclick();
      const p = posted[0];
      assert(p && p.url === '/api/action' && p.body.action === 'source' && p.body.folder === '/x', `posted ${JSON.stringify(posted)}`);
      assert(document.getElementById('toast').textContent === 'no such folder: /x', 'the refusal was not toasted');
    } finally { post = realPost; closeSettings(); }
    return 'posts action source; toasts the refusal';
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
    rule_re = re.compile(r'([^{}@]+)\{([^{}]*)\}')
    # Every reduce block, with however many rules it holds: the page's own
    # are one rule each, the vendored saltglass one carries three. Walk to
    # the brace that closes the block rather than assuming its shape.
    rm_open = re.compile(r'@media\s*\([^)]*prefers-reduced-motion:\s*reduce[^)]*\)\s*\{')
    covered = set()
    for m in rm_open.finditer(css):
        depth, i = 1, m.end()
        while i < len(css) and depth:
            depth += {'{': 1, '}': -1}.get(css[i], 0)
            i += 1
        for sel, _body in rule_re.findall(css[m.end():i - 1]):
            for s in sel.split(','):
                covered.add(s.strip())
    assert covered, 'no @media (prefers-reduced-motion: reduce) rule found at all'
    bad = []
    for sel, body in rule_re.findall(css):
        if 'transition:' not in body and 'animation:' not in body:
            continue
        if re.search(r'(transition|animation)\s*:\s*none\b', body):
            continue
        # A FADE IS NOT MOTION. A transition of opacity alone is what Reduce
        # Motion asks for in place of movement (the saltglass ground keeps
        # its crossfade and drops its drift), so it needs no twin.
        if 'animation:' not in body and all(
                t.strip().split()[0] == 'opacity'
                for t in re.search(r'transition\s*:\s*([^;]*)', body).group(1).split(',')):
            continue
        for s in sel.split(','):
            s = s.strip()
            if s and s not in covered:
                bad.append('%s { %s }' % (s, body.strip()[:70]))
    assert not bad, 'motion not covered by any prefers-reduced-motion rule: %s' % '; '.join(bad[:5])
    return '%d selector(s) turn real motion off under prefers-reduced-motion' % len(covered)


def t_no_filter_row():
    """The filter row is gone: no .filters element, no rule for it, no #ctl.
    The funnel's popover (menuitemradio rows) is what replaced it."""
    import re
    raw = open(CURATE).read()
    css = raw.split('<style>')[1].split('</style>')[0]
    body = raw.split('</style>')[1].split('<body>')[1].split('<script')[0]
    assert 'class="filters' not in body and 'id="ctl"' not in body, 'the .filters row is still in the markup'
    assert not re.search(r'\.filters\b', css), 'a .filters rule survives in the stylesheet'
    assert 'menuitemradio' in raw, 'no menuitemradio rows -- nothing replaced the row'
    return 'no .filters markup or rule; menuitemradio rows replace it'


def t_strips_and_pills():
    """A surface ends by its fill. The four pane title strips and the four
    panel strips carry .gl-strip; the two count substats carry .gl-pill; and
    no pane, panel or bar draws a gl-seam-. The menu's and the dialog's own
    title strips float and keep theirs (the judged direction: the glass
    menus and dialogs do not move), and are the only gl-seam- left."""
    import re
    raw = open(CURATE).read()
    body = raw.split('</style>')[1].split('<body>')[1].split('<script')[0]

    def first_strip_after(anchor):
        i = body.index(anchor)
        m = re.compile(r'class="plabel[^"]*"').search(body, i)
        assert m, 'no .plabel after %s' % anchor
        return m.group(0)
    for anchor in ('id="left"', 'id="src"', 'id="mid"', 'id="right"',
                   'id="lsheet"', 'id="rsheet"', 'id="sp"', 'id="tp"'):
        strip = first_strip_after(anchor)
        assert re.search(r'\bgl-strip\b', strip), '%s strip is %s, not .gl-strip' % (anchor, strip)
    for pid in ('sstat', 'rstat'):
        assert re.search(r'class="[^"]*\bgl-pill\b[^"]*" id="%s"' % pid, body), '#%s is not a .gl-pill' % pid
    for sub in re.findall(r'<div class="substat[^"]*"[^>]*>', body):
        assert 'gl-seam-' not in sub, 'a substat still draws a seam: %s' % sub
    seams = [ln.strip() for ln in body.splitlines() if 'gl-seam-' in ln]
    stray = [ln for ln in seams if not ('id="menuh"' in ln or 'id="dlgt"' in ln or '<header' in ln or '<footer' in ln)]
    assert not stray, 'gl-seam- on a pane or panel, which ends by its fill: %s' % stray[0][:160]
    return '8 .gl-strip strips, 2 .gl-pill counts, seams only on the %d floating strips' % len(seams)


def t_ground_present():
    """The ground element, as the system wants it: first in <body>, two
    picture layers and a scrim, hidden from assistive technology."""
    import re
    html, _style = _html_and_style()
    body = html.split('</head><body>')[1]
    m = re.search(r'<(\w+)[^>]*>', body)
    assert m, 'no element in <body> at all'
    first = m.group(0)
    assert 'id="ground"' in first and 'gl-ground' in first, (
        'the first element in <body> is not #ground.gl-ground: %s' % first)
    assert 'aria-hidden="true"' in first, 'the ground is not aria-hidden: %s' % first
    inner = body.split(first, 1)[1].split('</div>\n', 1)[0]
    imgs = re.findall(r'<img\b[^>]*>', inner)
    assert len(imgs) == 2, 'the ground should carry two <img> layers, found %d' % len(imgs)
    assert all('alt=""' in i for i in imgs), 'a ground layer has alt text: %s' % imgs
    assert re.search(r'<div class="scrim">', inner), 'the ground has no .scrim'
    return 'first in body, two img layers, one scrim, aria-hidden'


def t_page_never_measures():
    """The layer rule at the ground: the server measures a cover's colour
    and hands the page the scrim; the page never reads a pixel. One hit on
    any of these names is the page starting to work something out."""
    html, _style = _html_and_style()
    hits = [name for name in ('getContext', 'getImageData', 'createImageBitmap') if name in html]
    assert not hits, 'the page can read pixels: %s' % hits
    assert 't.ground' in html or '.ground||' in html, (
        'the page does not read ground from the payload at all')
    return 'no getContext / getImageData / createImageBitmap; ground read from the payload'


def t_glass_twins_present():
    """Every motion and transparency the system adds has a twin, and all
    four twins are in the sheet in the order a browser resolves them."""
    import re
    _html, css = _html_and_style()
    # the page has reduce blocks of its own above the marker; the four twins
    # that cover the system's materials must be the system's, below it
    assert 'saltglass:css @' in css, 'saltglass is not vendored into the stylesheet'
    vendored = css[css.index('saltglass:css @'):]
    twins = [r'@media\s*\(\s*prefers-reduced-motion:\s*reduce\s*\)',
             r'@media\s*\(\s*prefers-reduced-transparency:\s*reduce\s*\)',
             r'@media\s*\(\s*prefers-contrast:\s*more\s*\)',
             r'@supports\s+not\s*\(\s*backdrop-filter:\s*blur\(1px\)\s*\)']
    where = []
    for pat in twins:
        m = re.search(pat, vendored)
        assert m, 'missing twin in the vendored block: %s' % pat
        where.append(m.start())
    # the system's own order: motion, transparency, contrast, support
    assert where == sorted(where), 'the vendored twins are out of their documented order'
    return 'reduced-motion, reduced-transparency, contrast: more, @supports not backdrop-filter'


def t_action_is_glass():
    """The one action is accent-tinted glass and the blue gradient is gone:
    no linear-gradient anywhere in the stylesheet (the page's own rules or
    the vendored system's), #dosync carries .gl-action in the markup, and
    every primary the script builds carries it too. The search field is the
    system's field."""
    import re
    html, style = _html_and_style()
    assert 'linear-gradient' not in style, 'a linear-gradient survives in the stylesheet'
    body = html.split('</style>')[1].split('<body>')[1].split('<script')[0]
    m = re.search(r'<button id="dosync"[^>]*>', body)
    assert m and 'gl-action' in m.group(0), '#dosync does not carry .gl-action: %s' % (m and m.group(0))
    q = re.search(r'<input[^>]*id="q"[^>]*>', body)
    assert q and 'gl-field' in q.group(0), '#q does not carry .gl-field: %s' % (q and q.group(0))
    script = html.split('<script>')[1].split('</script>')[0]
    bare = re.findall(r'<button class="go"[ >]', script)
    assert not bare, '%d primary button(s) built without .gl-action' % len(bare)
    n = len(re.findall(r'class="go gl-action"', script))
    return 'no gradient; #dosync and %d script-built primaries are .gl-action; #q is .gl-field' % n


def t_footer_context():
    """The footer's keys follow the context, from the page's own table; the
    ? key is handled by the keydown handler, not invented by the footer."""
    html, _style = _html_and_style()
    script = html.split('<script>')[1].split('</script>')[0]
    assert "k==='?'" in script and 'toggleKeysMenu' in script, 'the keydown handler does not handle ?'
    assert 'const KEYS=' in script, 'the keys are not a table in the page'
    return node_check('the footer names the keys for the context; ? lists them all')()


def t_playlist_rows():
    """Music rows: a .mosaic from the payload or the empty thumbnail; the
    count and the month from the payload. The page never tiles."""
    html, _style = _html_and_style()
    script = html.split('<script>')[1].split('</script>')[0]
    assert "createElement('canvas')" not in script and '<canvas' not in html, 'the page makes a canvas -- the mosaic is the server\'s to tile'
    return node_check('Music rows carry a mosaic from the payload, or the empty thumbnail')()


def t_panels_patterned():
    """#sp and #rsheet from the system's parts: no .box, no colour in an
    inline style, their strips and the sync action bar .gl-strip, the one
    action .gl-action. Rendered in the harness from the fixture plan."""
    return node_check('the panels are patterned from the system\'s parts')()


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
    check('sync rows take their state from job.steps', node_check('sync rows take their state from job.steps'))
    check('the buy and vinyl panes read the server lists', node_check('the buy and vinyl panes read the server lists'))
    check('a selection asks the server for its decision', node_check('law 8: a selection asks the server for its decision'))

    section('law 7 -- nothing is drag-only')
    check('every draggable row has a menu equivalent', node_check('law 7: nothing is drag-only'))
    check('the row menu moves a row, the footer undoes', node_check('law 7: the row menu moves a row, the footer undoes'))

    section('behaviour -- pass(), mark(), load()')
    check('load() boots every pane from the real functions', node_check('load() boots every pane'))
    check('pass() honors a real filter-popover choice', node_check('pass() honors a real filter-popover choice'))
    check('pass() honors a real search input', node_check('pass() honors a real search input'))
    check('mark() tracks the cursor, leaves MARK alone', node_check('mark() tracks the cursor without touching a MARKed row'))
    check('owned-but-offline is its own state', node_check('owned-but-offline is its own state, not unowned'))
    check('busy dot and filter state are spoken', node_check('the busy dot and the filter dot are spoken, not only coloured'))
    check('the strip shows volumes, not sources', node_check('the health strip shows volumes, not sources'))

    section('endings -- a surface ends by its fill')
    check('strips are .gl-strip, counts .gl-pill, no pane seam', t_strips_and_pills)

    section('the filter -- a popover from the funnel, no row')
    check('no .filters row remains', t_no_filter_row)
    check('the funnel opens radio rows; counts from the server', node_check('the funnel opens a filter popover of radio rows'))

    section('the ground -- the page looks up, never measures')
    check('the ground element is present and hidden', t_ground_present)
    check('the ground follows the selection, from the payload', node_check('the ground follows the selection, from the payload only'))
    check('the page never reads a pixel', t_page_never_measures)
    check('the four glass twins are in the sheet', t_glass_twins_present)

    section('first release, web -- fr-web')
    check('Esc closes Unsaved changes, as Cancel', node_check('Esc closes the Unsaved changes prompt, as Cancel'))
    check('blocked Review sync re-plans on the iPod', node_check('the blocked Review sync re-plans when the iPod appears'))
    check('Re-read the device says what it read', node_check('Re-read the device says what it read'))
    check('the buy card has no bought button', node_check('the buy card has no bought button'))
    check('the Data sheet names a music folder', node_check('the Data sheet names a music folder'))

    section('the chrome -- Sync as glass, the context footer, mosaics, the panels')
    check('the one action is glass; no gradient', t_action_is_glass)
    check('the footer keys follow the context; ? lists all', t_footer_context)
    check('Music rows carry a mosaic or the empty thumbnail', t_playlist_rows)
    check('#sp and #rsheet are patterned from the parts', t_panels_patterned)

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
