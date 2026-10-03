"""Spotify as a library source: what the owner saves and plays there.

THE ROUTE IS PLAYPI'S, deliberately (docs/reference/spotify/auth-and-scopes.md
in the PlayPi repo): the Spotify Web API through the Authorization Code
flow, with the owner's own developer app. Consent happens once in a
browser, the redirect is caught on this machine, and the refresh token is
kept so everything after runs unattended. The client secret and the token
live in data/spotify.json, which is gitignored.

WHAT IS DIFFERENT FROM PLAYPI is the job. PlayPi controls playback; this
reads a library, so the scopes are library scopes. And the November 2024
restrictions on new apps (audio features, recommendations, related artists,
Spotify's own editorial playlists) cost nothing here: BPM and key come from
the files (tags.read_extra), and the owner's saved tracks, their playlists
and the ISRC on every track are all still served.

THE ISRC IS THE POINT. Every Spotify track carries one
(`external_ids.isrc`), the global id of a recording, and the files carry
one too on 790 tracks. Matching on it is exact, where artist + title is a
guess -- so `match()` tries ISRC first and the existing duration-checked
artist + title second. What matches nothing the owner holds is what the
buy list is for, so purchasing works exactly as it did with Apple Music.

Per-track PLAY COUNTS are not in the API and never were; recently played
(the last fifty) and top tracks are. A full history only comes from the
owner's data export, which is a separate, later import.
"""
import base64
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG = os.path.join(ROOT, 'data', 'spotify.json')
CACHE = os.path.join(ROOT, 'data', 'local', 'spotify.json')

AUTH = 'https://accounts.spotify.com/authorize'
TOKEN = 'https://accounts.spotify.com/api/token'
API = 'https://api.spotify.com/v1'
# Spotify no longer accepts "localhost"; a loopback IP literal is allowed
# over plain http.
REDIRECT = 'http://127.0.0.1:8789/callback'
SCOPES = ('user-library-read playlist-read-private playlist-read-collaborative '
          'user-read-recently-played user-top-read')


class SpotifyError(Exception):
    pass


# ------------------------------------------------------------------ config

def load_config(path=CONFIG):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise SpotifyError('no %s -- create a Spotify app at '
                           'developer.spotify.com, add the redirect URI %s, and '
                           'put its client_id and client_secret in that file'
                           % (os.path.relpath(path, ROOT), REDIRECT))


def save_config(cfg, path=CONFIG):
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(cfg, fh, indent=1)
    os.chmod(tmp, 0o600)             # it holds a secret
    os.replace(tmp, path)


# -------------------------------------------------------------------- http

def _post_form(url, data, basic, opener=urllib.request.urlopen):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    req.add_header('Authorization', 'Basic ' + base64.b64encode(basic.encode()).decode())
    try:
        with opener(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise SpotifyError('token endpoint said %d: %s' % (e.code, e.read()[:200]))


class Client:
    """A session against the Web API. `opener` is injectable so the paging,
    retry and refresh logic can be tested without the network."""

    def __init__(self, cfg, opener=urllib.request.urlopen, save=save_config):
        self.cfg, self.opener, self.save = cfg, opener, save
        self._token, self._expires = None, 0

    def _basic(self):
        return '%s:%s' % (self.cfg['client_id'], self.cfg['client_secret'])

    def token(self):
        if self._token and time.time() < self._expires - 60:
            return self._token
        if not self.cfg.get('refresh_token'):
            raise SpotifyError('not logged in -- run `saltpod spotify login` once')
        got = _post_form(TOKEN, {'grant_type': 'refresh_token',
                                 'refresh_token': self.cfg['refresh_token']},
                         self._basic(), self.opener)
        self._token = got['access_token']
        self._expires = time.time() + int(got.get('expires_in', 3600))
        if got.get('refresh_token'):          # Spotify may rotate it
            self.cfg['refresh_token'] = got['refresh_token']
            self.save(self.cfg)
        return self._token

    def get(self, path, params=None, _tries=3):
        url = path if path.startswith('http') else API + path
        if params:
            url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
        req = urllib.request.Request(url)
        req.add_header('Authorization', 'Bearer ' + self.token())
        try:
            with self.opener(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 and _tries:                 # rate limited
                time.sleep(min(30, int(e.headers.get('Retry-After', '2'))))
                return self.get(url, None, _tries - 1)   # url already has the params
            if e.code == 401 and _tries:                 # token went stale
                self._token = None
                return self.get(url, None, _tries - 1)
            raise SpotifyError('%s said %d' % (path, e.code))

    def pages(self, path, params=None):
        """Every item across a paged endpoint, following `next`."""
        page = self.get(path, params)
        while True:
            for it in page.get('items') or []:
                yield it
            if not page.get('next'):
                return
            page = self.get(page['next'])


# ------------------------------------------------------------------- login

def authorize_url(cfg, state):
    return AUTH + '?' + urllib.parse.urlencode({
        'client_id': cfg['client_id'], 'response_type': 'code',
        'redirect_uri': cfg.get('redirect_uri') or REDIRECT,
        'scope': SCOPES, 'state': state, 'show_dialog': 'true'})


def login(cfg=None, open_browser=True):
    """Authorize once, in a browser, and keep the refresh token.

    Serves the redirect URI on 127.0.0.1 just long enough to catch the code,
    checks the state nonce against cross-site forgery, and exchanges it.
    """
    import http.server
    import webbrowser
    cfg = cfg or load_config()
    redirect = cfg.get('redirect_uri') or REDIRECT
    u = urllib.parse.urlparse(redirect)
    state = secrets.token_urlsafe(16)
    got = {}

    class Catch(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            ok = got.get('state') == state and 'code' in got
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(('saltpod: %s. You can close this tab.'
                              % ('connected to Spotify' if ok else 'that did not work')).encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer((u.hostname, u.port), Catch)
    t = threading.Thread(target=srv.handle_request, daemon=True)
    t.start()
    url = authorize_url(cfg, state)
    if open_browser:
        webbrowser.open(url)
    t.join(timeout=300)
    srv.server_close()
    if got.get('state') != state:
        raise SpotifyError('the reply did not carry our state nonce; refusing it')
    if 'code' not in got:
        raise SpotifyError('Spotify did not authorize: %s' % got.get('error', 'no reply in 5 minutes'))
    tok = _post_form(TOKEN, {'grant_type': 'authorization_code', 'code': got['code'],
                             'redirect_uri': redirect},
                     '%s:%s' % (cfg['client_id'], cfg['client_secret']))
    cfg['refresh_token'] = tok['refresh_token']
    cfg['scopes'] = tok.get('scope', SCOPES)
    save_config(cfg)
    return cfg


# ----------------------------------------------------------------- library

def _track(t, added=None):
    if not t or t.get('type', 'track') != 'track' or not t.get('id'):
        return None                   # local files and episodes have no id
    return {'id': t['id'], 'isrc': (t.get('external_ids') or {}).get('isrc'),
            'title': t.get('name'), 'artist': ', '.join(a['name'] for a in t.get('artists') or []),
            'artists': [a['name'] for a in t.get('artists') or []],
            'album': (t.get('album') or {}).get('name'),
            'seconds': round((t.get('duration_ms') or 0) / 1000.0, 1),
            'added_at': added}


def fetch_library(client):
    """Saved tracks, every playlist the owner can read, recently played and
    top tracks -- as plain records, ISRC included."""
    saved = [x for x in (_track(it.get('track'), it.get('added_at'))
                         for it in client.pages('/me/tracks', {'limit': 50})) if x]
    playlists = []
    for pl in client.pages('/me/playlists', {'limit': 50}):
        items = [x for x in (_track(it.get('track'), it.get('added_at'))
                             for it in client.pages('/playlists/%s/tracks' % pl['id'], {'limit': 100}))
                 if x]
        playlists.append({'id': pl['id'], 'name': pl.get('name'),
                          'owner': (pl.get('owner') or {}).get('display_name'),
                          'tracks': [t['id'] for t in items], '_items': items})
    recent = [dict(_track(it.get('track')) or {}, played_at=it.get('played_at'))
              for it in client.get('/me/player/recently-played', {'limit': 50}).get('items') or []]
    top = {}
    for rng in ('short_term', 'medium_term', 'long_term'):
        top[rng] = [x['id'] for x in (_track(t) for t in
                    client.get('/me/top/tracks', {'limit': 50, 'time_range': rng}).get('items') or []) if x]
    tracks = {}
    for t in saved + [i for p in playlists for i in p.pop('_items')] + [r for r in recent if r.get('id')]:
        tracks.setdefault(t['id'], {k: v for k, v in t.items() if k != 'played_at'})
    return {'read_at': time.strftime('%Y-%m-%d %H:%M'), 'tracks': tracks,
            'saved': [t['id'] for t in saved], 'playlists': playlists,
            'recent': [{'id': r['id'], 'played_at': r['played_at']} for r in recent if r.get('id')],
            'top': top}


def save_cache(lib, path=CACHE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(lib, fh, indent=1)
    os.replace(tmp, path)


def load_cache(path=CACHE):
    with open(path) as fh:
        return json.load(fh)


# ------------------------------------------------------------------- match

def match(spotify_tracks, index_entries, tolerance=3.0):
    """Which Spotify tracks the owner already holds as a file.

    ISRC first -- exact recording identity. Then artist + title, but only
    when the durations agree within `tolerance` seconds, the same guard the
    rest of saltpod uses so a radio edit is not taken for the album cut.
    Returns {spotify_id: {'how': 'isrc'|'name', 'path': ...}}.
    """
    from . import state as S
    by_isrc, by_key = {}, {}
    for e in index_entries:
        if e.get('isrc'):
            by_isrc.setdefault(e['isrc'].upper().replace('-', ''), e)
        by_key.setdefault(S.key_for(e.get('artist'), e.get('title')), []).append(e)
    out = {}
    for sid, t in spotify_tracks.items():
        isrc = (t.get('isrc') or '').upper().replace('-', '')
        if isrc and isrc in by_isrc:
            out[sid] = {'how': 'isrc', 'path': by_isrc[isrc].get('path')}
            continue
        names = [S.key_for(a, t.get('title')) for a in (t.get('artists') or [t.get('artist')])]
        names.append(S.key_for(t.get('artist'), t.get('title')))
        for k in names:
            hit = next((e for e in by_key.get(k, ())
                        if abs((e.get('duration_sec') or 0) - (t.get('seconds') or 0)) <= tolerance), None)
            if hit:
                out[sid] = {'how': 'name', 'path': hit.get('path')}
                break
    return out
