#!/usr/bin/env osascript -l JavaScript
//
// Export Apple Music playlists to JSON.
//
// Usage:
//   osascript -l JavaScript bin/export_playlists.js --list
//   osascript -l JavaScript bin/export_playlists.js "DayClub" [more names...]
//   osascript -l JavaScript bin/export_playlists.js --all
//
// Properties are fetched a whole column at a time (pl.tracks.name(), not
// t.name() per track). Per-track access costs one Apple event each and takes
// minutes on a 4,876-track library; column access is one event and takes
// under a second. This matters more than it looks.
//
ObjC.import('Foundation');

const OUT_DIR = $.NSString.alloc.initWithUTF8String(
  '~/Documents/GitHub/ipod-playlists/data/exports').stringByExpandingTildeInPath.js;

function writeFile(path, text) {
  $.NSString.alloc.initWithUTF8String(text)
    .writeToFileAtomicallyEncodingError(path, true, $.NSUTF8StringEncoding, null);
}

function slug(s) {
  return s.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'untitled';
}

// Columns we can pull in bulk. `location` is deliberately absent: it throws for
// every subscription track, and a throw inside a column fetch loses the batch.
const COLUMNS = ['name', 'artist', 'albumArtist', 'album', 'duration', 'year',
                 'kind', 'cloudStatus', 'genre', 'databaseID', 'trackNumber'];

function exportPlaylist(pl) {
  const cols = {};
  for (const c of COLUMNS) {
    try { cols[c] = pl.tracks[c](); } catch (e) { cols[c] = null; }
  }
  const n = (cols.name || []).length;
  const tracks = [];
  for (let i = 0; i < n; i++) {
    const get = (c) => (cols[c] && cols[c][i] !== undefined ? cols[c][i] : null);
    const cloud = String(get('cloudStatus'));
    tracks.push({
      index: i + 1,
      title: get('name'),
      artist: get('artist'),
      album_artist: get('albumArtist'),
      album: get('album'),
      duration_sec: get('duration'),
      year: get('year'),
      kind: String(get('kind')),
      cloud_status: cloud,
      genre: get('genre'),
      database_id: get('databaseID'),
      track_number: get('trackNumber'),
      // The one classification the whole pipeline turns on. `subscription`
      // means rented: no file exists that an iPod Classic could ever play.
      owned: ['purchased', 'matched', 'uploaded'].indexOf(cloud) !== -1,
    });
  }
  return {
    playlist: pl.name(),
    exported_at: new Date().toISOString(),
    track_count: n,
    owned_count: tracks.filter((t) => t.owned).length,
    tracks: tracks,
  };
}

function run(argv) {
  const M = Application('Music');
  const SYSTEM = ['Music', 'Music Videos', 'Recently Added', 'Recently Played',
                  'Top 25 Most Played', 'My Top Rated'];

  if (argv.indexOf('--list') !== -1) {
    // Music.app does NOT expose when a playlist was created -- a playlist's
    // whole property list is id, index, name, persistentID, duration, size,
    // time, visible, specialKind, loved, hated, smart, shared, genius. So it
    // is derived: the earliest date a track in it was added is when the
    // playlist was built, which for a monthly is exactly right. `last` is the
    // most recent, so a playlist still being added to is visible as such.
    // dateAdded comes back a whole column at a time, like every other read
    // here; per-track would cost one Apple event each and time out.
    const names = M.userPlaylists.name();
    const pls = M.userPlaylists();
    const rows = [];
    for (let i = 0; i < pls.length; i++) {
      const name = String(names[i]);
      if (SYSTEM.indexOf(name) !== -1) continue;
      let count = 0, created = null, last = null;
      try { count = pls[i].tracks().length; } catch (e) { count = 0; }
      if (!count) continue;
      try {
        const ds = pls[i].tracks.dateAdded();
        for (const d of ds) {
          if (!d) continue;
          const t = new Date(d).getTime();
          if (isNaN(t)) continue;
          if (created === null || t < created) created = t;
          if (last === null || t > last) last = t;
        }
      } catch (e) { /* a playlist that will not give up its dates still lists */ }
      rows.push({ name: name, tracks: count,
                  created: created === null ? null : new Date(created).toISOString(),
                  last: last === null ? null : new Date(last).toISOString() });
    }
    rows.sort((a, b) => String(b.created || '').localeCompare(String(a.created || '')));
    return JSON.stringify(rows, null, 1);
  }

  if (argv.indexOf('--index') !== -1) {
    // Everything the page needs to know about Apple Music, in one pass:
    // which playlists exist and when they were made, and every track in the
    // library so a record can be marked as living there whether or not its
    // playlist was ever exported. Columns, never per-track.
    const names = M.userPlaylists.name();
    const pls = M.userPlaylists();
    const playlists = [];
    for (let i = 0; i < pls.length; i++) {
      const name = String(names[i]);
      if (SYSTEM.indexOf(name) !== -1) continue;
      let count = 0, created = null, last = null;
      try { count = pls[i].tracks().length; } catch (e) { count = 0; }
      if (!count) continue;
      try {
        const ds = pls[i].tracks.dateAdded();
        for (const d of ds) {
          if (!d) continue;
          const t = new Date(d).getTime();
          if (isNaN(t)) continue;
          if (created === null || t < created) created = t;
          if (last === null || t > last) last = t;
        }
      } catch (e) { /* a playlist that will not give up its dates still lists */ }
      playlists.push({ name: name, tracks: count,
                       created: created === null ? null : new Date(created).toISOString(),
                       last: last === null ? null : new Date(last).toISOString() });
    }
    playlists.sort((a, b) => String(b.created || '').localeCompare(String(a.created || '')));
    let library = [];
    try {
      const lib = M.libraryPlaylists[0];
      const ns = lib.tracks.name(), as = lib.tracks.artist(),
            al = lib.tracks.album(), du = lib.tracks.duration(),
            cs = lib.tracks.cloudStatus();
      for (let i = 0; i < ns.length; i++) {
        library.push({ artist: String(as[i] || ''), title: String(ns[i] || ''),
                       album: String(al[i] || ''), secs: Math.round(du[i] || 0),
                       cloud: String(cs[i] || '') });
      }
    } catch (e) { library = []; }
    return JSON.stringify({ playlists: playlists, library: library });
  }

  if (argv.indexOf('--peek') !== -1) {
    // One playlist's tracks, for looking at. Nothing is written; this is the
    // inspiration path, as against --all which imports.
    const want = argv[argv.indexOf('--peek') + 1];
    let pl = null;
    try { pl = M.userPlaylists.whose({ name: want })[0]; } catch (e) { pl = null; }
    if (!pl) return JSON.stringify({ error: 'no playlist named ' + want });
    const cols = {};
    for (const c of ['name', 'artist', 'album', 'duration', 'cloudStatus']) {
      try { cols[c] = pl.tracks[c](); } catch (e) { cols[c] = null; }
    }
    const n = (cols.name || []).length;
    const rows = [];
    for (let i = 0; i < n; i++) {
      const g = (c) => (cols[c] && cols[c][i] !== undefined ? cols[c][i] : null);
      rows.push({ artist: String(g('artist') || ''), title: String(g('name') || ''),
                  album: String(g('album') || ''), secs: Math.round(g('duration') || 0),
                  cloud: String(g('cloudStatus') || '') });
    }
    return JSON.stringify({ name: want, tracks: rows });
  }

  let targets = argv.filter((a) => a.indexOf('--') !== 0);
  if (argv.indexOf('--all') !== -1) {
    targets = M.userPlaylists.name().map(String).filter((n) => SYSTEM.indexOf(n) === -1);
  }
  if (!targets.length) return 'no playlist named; use --list, --all, or a name';

  const done = [];
  for (const name of targets) {
    let pl;
    try { pl = M.userPlaylists.byName(name); pl.name(); }
    catch (e) { done.push({ playlist: name, error: 'not found' }); continue; }
    const data = exportPlaylist(pl);
    if (!data.track_count) { done.push({ playlist: name, error: 'empty' }); continue; }
    const path = OUT_DIR + '/' + slug(name) + '.json';
    writeFile(path, JSON.stringify(data, null, 1));
    done.push({ playlist: name, tracks: data.track_count, owned: data.owned_count, file: path });
  }
  return JSON.stringify(done, null, 1);
}
