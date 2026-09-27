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
    const names = M.userPlaylists.name();
    const counts = [];
    const pls = M.userPlaylists();
    for (const p of pls) { try { counts.push(p.tracks().length); } catch (e) { counts.push(0); } }
    const rows = names.map((nm, i) => ({ name: String(nm), tracks: counts[i] }))
      .filter((r) => SYSTEM.indexOf(r.name) === -1 && r.tracks > 0)
      .sort((a, b) => b.tracks - a.tracks);
    return JSON.stringify(rows, null, 1);
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
