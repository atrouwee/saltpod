// Bandcamp availability check, run in the browser from a bandcamp.com tab.
//
// WHY THE BROWSER: Bandcamp has no API, and a plain server-side request gets a
// resultless page. Two hard-won constraints:
//
//   1. DO NOT pass credentials:'omit'. Bandcamp serves a page with ZERO
//      search results to cookieless requests. It returns 200 and ~150KB of
//      HTML, so it looks fine and silently finds nothing. Default credentials
//      (the browser's own session) is what makes it work.
//   2. Run from a bandcamp.com tab and only fetch bandcamp.com/search. Seller
//      pages are per-seller subdomains: cross-origin for CORS, and the Chrome
//      extension grants site access per domain. Search alone is same-origin.
//
//   3. PACE IT, AND CHECK THE HIT RATE. Bandcamp starts serving resultless
//      pages once you have queried too fast for too long -- the same 200-with-
//      nothing-in-it as trap 1, but earned rather than configured. A 550ms gap
//      held for ~120 queries and then every result went empty; five of those
//      "misses" found their track immediately when retried at 1.5s. Use ~1.5s,
//      and treat a hit rate much below 60%, or a run of consecutive misses at
//      the tail, as throttling rather than absence. Re-run misses; never trust
//      them. A false "not on Bandcamp" quietly removes a lossless source from
//      the buy list and nothing will ever contradict it.
//
// COST: ~45s of CDP budget per call is the ceiling. At ~1.5s per query that is
// ~25 tracks per minute. Chunk the list; accumulate into window.__res. Note
// the evaluate returns before an await'd loop finishes -- the page keeps
// working, so poll a counter rather than trusting the return value.
//
// LIMIT: search results carry no running time, so this establishes AVAILABILITY,
// never identity of the cut. Confirm length on the release page before paying.

window.__norm = s => (s || '').toLowerCase()
  .normalize('NFD').replace(/[̀-ͯ]/g, '')
  .replace(/[’'`´]/g, "'").replace(/&/g, 'and')
  .replace(/\(.*?\)|\[.*?\]/g, ' ')
  .replace(/[^a-z0-9' ]/g, ' ').replace(/\s+/g, ' ').trim();

// Drift must be checked against the RAW title: __norm strips parentheses, so
// "Long Way (Original Mix)" would otherwise look like drift against its own name.
window.__drift = (url, rawTitle) => {
  const slug = url.split('/').pop().toLowerCase(), rt = rawTitle.toLowerCase();
  return ['remix', 'edit', 'version', 'mix', 'live', 'instrumental', 'rework', 'dub', 'radio']
    .filter(w => slug.includes(w) && !rt.includes(w));
};

window.__search = async (artist, title) => {
  const html = await (await fetch('https://bandcamp.com/search?q=' +
    encodeURIComponent(artist + ' ' + title))).text();
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const res = [...doc.querySelectorAll('li.searchresult')].map(el => ({
    type: el.querySelector('.itemtype')?.textContent.trim(),
    heading: el.querySelector('.heading')?.textContent.trim(),
    sub: (el.querySelector('.subhead')?.textContent || '').replace(/\s+/g, ' ').trim(),
    url: el.querySelector('.itemurl')?.textContent.trim(),
  })).filter(r => r.url);

  const nt = window.__norm(title);
  const aParts = window.__norm(artist).split(' and ')
    .flatMap(x => x.split(' ')).filter(w => w.length > 2);

  // ARTIST EVIDENCE IS MANDATORY. Without it, a title-exact TRACK alone scored
  // high enough to return a Salvador Reynoso remix for "Portishead - Glory Box".
  const rank = res.map(r => {
    const nh = window.__norm(r.heading), ns = window.__norm(r.sub + ' ' + r.url);
    const titleExact = nh === nt;
    const titlePart = !titleExact && (nh.includes(nt) || nt.includes(nh));
    const aRatio = aParts.length ? aParts.filter(w => ns.includes(w)).length / aParts.length : 0;
    return { ...r, titleExact, titlePart, aRatio,
      s: (titleExact ? 100 : titlePart ? 60 : 0) + 40 * aRatio +
         (r.type === 'TRACK' ? 10 : r.type === 'ALBUM' ? 4 : 0) };
  }).filter(r => (r.titleExact || r.titlePart) && r.aRatio > 0)
    .sort((a, b) => b.s - a.s);

  if (!rank.length) return null;
  const top = rank[0];
  return { ...top, strong: top.titleExact && top.aRatio >= 0.5,
           drift: window.__drift(top.url, title) };
};

// Usage, one chunk at a time:
//
//   const CHUNK = [["FaltyDL","Be My Baby"], ["Mona Yim","Nevermind"]];
//   window.__res = window.__res || [];
//   for (const [a,t] of CHUNK) {
//     let r = null; try { r = await window.__search(a,t); } catch(e) {}
//     window.__res.push({artist:a, title:t, url:r?.url||null,
//       release:(r?.sub||'').replace(/^from /,''), strong:!!r?.strong, drift:r?.drift||[]});
//     await new Promise(z => setTimeout(z, 600));
//   }
//   JSON.stringify(window.__res.map(x=>`${x.url?(x.strong?(x.drift.length?'DRIFT':'Y'):'weak'):'N'}|${x.url||x.title}`))
//
// A verdict of DRIFT or weak is a human decision, never an auto-buy.
