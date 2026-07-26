#!/usr/bin/env python3
"""Dump this account's Spotify library (saved tracks, playlists, albums,
followed artists) to JSON + a flat TSV.

Stdlib only, on purpose — same reasoning as dbsync.py: a new Python dep in
~/nix means editing home/pkgs/ and a full rebuild, and this is a read-only
one-shot against a third-party API.

Auth is Authorization Code + PKCE, so there is no client secret to keep.
The client id is a public identifier but is still read from outside the repo
(this tree is public); it is cached at ~/.local/state/spotify-dump/client_id.

Usage:
    spotify-dump.py                     # auth if needed, then dump
    spotify-dump.py --client-id ID      # first run / changing apps
    spotify-dump.py --reauth            # forget the cached token

Politeness: max page sizes (fewest requests), a fixed delay between calls,
strict Retry-After compliance, no parallelism. A full library is a few
hundred requests.
"""

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

STATE_DIR = os.path.expanduser("~/.local/state/spotify-dump")
TOKEN_FILE = os.path.join(STATE_DIR, "token.json")
CLIENT_ID_FILE = os.path.join(STATE_DIR, "client_id")
OUT_DIR = os.path.expanduser("~/.local/share/spotify-dump")

REDIRECT_URI = "http://127.0.0.1:8888/callback"
CALLBACK_PORT = 8888
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"

SCOPES = (
    "user-library-read "
    "playlist-read-private "
    "playlist-read-collaborative "
    "user-follow-read"
)

# Be a good citizen: Spotify's limit is a rolling window per app, and this
# walks a whole library in one go.
RATE_DELAY = 0.15
MAX_RETRIES = 5
USER_AGENT = "spotify-dump/1.0 (personal library export)"


# --------------------------------------------------------------------------
# tiny http helpers
# --------------------------------------------------------------------------

def _post_form(url, fields):
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _get_json(url, token):
    """GET with 429/5xx backoff. Returns parsed JSON."""
    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token}",
                          "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            time.sleep(RATE_DELAY)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("Retry-After", "3")) + 1
                print(f"  rate limited, sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            if 500 <= e.code < 600:
                wait = 2 ** attempt
                print(f"  http {e.code}, retrying in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"giving up on {url} after {MAX_RETRIES} attempts")


# --------------------------------------------------------------------------
# auth (Authorization Code + PKCE)
# --------------------------------------------------------------------------

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        _CallbackHandler.result = urllib.parse.parse_qs(parsed.query)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body style='font:16px sans-serif;padding:3em'>"
            b"<h2>Authorized.</h2><p>You can close this tab and go back to "
            b"the terminal.</p></body></html>"
        )

    def log_message(self, *a):
        pass  # keep the terminal clean


def _authorize(client_id):
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    state = secrets.token_urlsafe(16)

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "scope": SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)

    print("Opening Spotify authorization in your browser.")
    print("If nothing opens, paste this URL yourself:\n")
    print("  " + url + "\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    srv = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), _CallbackHandler)
    srv.timeout = 300
    print("Waiting for the redirect (5 min timeout)...")
    while _CallbackHandler.result is None:
        srv.handle_request()
    srv.server_close()

    res = _CallbackHandler.result
    if "error" in res:
        raise SystemExit(f"Spotify returned an error: {res['error'][0]}")
    if res.get("state", [None])[0] != state:
        raise SystemExit("state mismatch - aborting (possible CSRF)")

    tok = _post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "code": res["code"][0],
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "code_verifier": verifier,
    })
    return tok


def _refresh(client_id, refresh_token):
    return _post_form(TOKEN_URL, {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    })


def _save_token(tok):
    tok = dict(tok)
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    tmp = TOKEN_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(tok, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, TOKEN_FILE)


def get_token(client_id, reauth=False):
    if not reauth and os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            tok = json.load(f)
        if tok.get("expires_at", 0) > time.time():
            return tok["access_token"]
        if tok.get("refresh_token"):
            print("Refreshing access token...")
            new = _refresh(client_id, tok["refresh_token"])
            # a refresh response may omit refresh_token; keep the old one
            new.setdefault("refresh_token", tok["refresh_token"])
            _save_token(new)
            return new["access_token"]
    tok = _authorize(client_id)
    _save_token(tok)
    return tok["access_token"]


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------

def paged(url, token, key=None, label=""):
    """Follow Spotify's `next` links. `key` digs into a wrapper object
    (followed artists nest under "artists" and are cursor-paged)."""
    items = []
    while url:
        data = _get_json(url, token)
        page = data[key] if key else data
        items.extend(page.get("items", []))
        url = page.get("next")
        if label:
            total = page.get("total")
            print(f"\r  {label}: {len(items)}"
                  + (f"/{total}" if total else ""), end="", flush=True)
    if label:
        print()
    return items


def track_row(tr, source, playlist=""):
    """Flatten a track object. Returns None for podcast episodes."""
    if not tr or tr.get("type") == "episode":
        return None
    album = tr.get("album") or {}
    return {
        "source": source,
        "playlist": playlist,
        "title": tr.get("name", ""),
        "artists": ", ".join(a["name"] for a in tr.get("artists", [])),
        "album": album.get("name", ""),
        "album_artist": ", ".join(a["name"] for a in album.get("artists", [])),
        "year": (album.get("release_date") or "")[:4],
        "duration_ms": tr.get("duration_ms") or 0,
        "track_number": tr.get("track_number") or 0,
        "disc_number": tr.get("disc_number") or 0,
        "isrc": (tr.get("external_ids") or {}).get("isrc", ""),
        "spotify_id": tr.get("id") or "",
        "is_local": bool(tr.get("is_local")),
    }


def fetch_all(token):
    out = {}

    print("Saved tracks:")
    saved = paged(f"{API}/me/tracks?limit=50", token, label="tracks")
    out["saved_tracks"] = [
        dict(track_row(i["track"], "saved"), added_at=i.get("added_at", ""))
        for i in saved if track_row(i["track"], "saved")
    ]

    print("Saved albums:")
    albums = paged(f"{API}/me/albums?limit=50", token, label="albums")
    out["saved_albums"] = [{
        "name": i["album"]["name"],
        "artists": ", ".join(a["name"] for a in i["album"]["artists"]),
        "year": (i["album"].get("release_date") or "")[:4],
        "total_tracks": i["album"].get("total_tracks", 0),
        "spotify_id": i["album"]["id"],
        "added_at": i.get("added_at", ""),
    } for i in albums]

    print("Followed artists:")
    artists = paged(f"{API}/me/following?type=artist&limit=50",
                    token, key="artists", label="artists")
    out["followed_artists"] = [
        {"name": a["name"], "spotify_id": a["id"],
         "genres": a.get("genres", [])} for a in artists
    ]

    print("Playlists:")
    playlists = paged(f"{API}/me/playlists?limit=50", token, label="playlists")
    out["playlists"] = []
    for pl in playlists:
        name = pl["name"]
        print(f"  {name}")
        items = paged(f"{API}/playlists/{pl['id']}/tracks?limit=100", token)
        rows = []
        for i in items:
            row = track_row(i.get("track"), "playlist", name)
            if row:
                row["added_at"] = i.get("added_at", "")
                rows.append(row)
        out["playlists"].append({
            "name": name,
            "spotify_id": pl["id"],
            "owner": (pl.get("owner") or {}).get("display_name", ""),
            "public": pl.get("public"),
            "track_count": len(rows),
            "tracks": rows,
        })
    return out


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------

TSV_COLS = ["source", "playlist", "artists", "title", "album", "album_artist",
            "year", "duration_ms", "isrc", "spotify_id", "added_at"]


def clean(v):
    return str(v).replace("\t", " ").replace("\n", " ").replace("\r", " ")


def write_outputs(data, out_dir):
    os.makedirs(out_dir, exist_ok=True)

    jpath = os.path.join(out_dir, "library.json")
    with open(jpath, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    rows = list(data["saved_tracks"])
    for pl in data["playlists"]:
        rows.extend(pl["tracks"])

    tpath = os.path.join(out_dir, "tracks.tsv")
    with open(tpath, "w") as f:
        f.write("\t".join(TSV_COLS) + "\n")
        for r in rows:
            f.write("\t".join(clean(r.get(c, "")) for c in TSV_COLS) + "\n")

    # deduped view - the same song usually sits in several playlists
    seen, uniq = set(), []
    for r in rows:
        key = r["isrc"] or (r["artists"].lower(), r["title"].lower())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    upath = os.path.join(out_dir, "unique.tsv")
    with open(upath, "w") as f:
        f.write("\t".join(TSV_COLS) + "\n")
        for r in uniq:
            f.write("\t".join(clean(r.get(c, "")) for c in TSV_COLS) + "\n")

    return jpath, tpath, upath, len(rows), len(uniq)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--client-id", help="Spotify app client id (cached after first use)")
    ap.add_argument("--reauth", action="store_true", help="discard the cached token")
    ap.add_argument("--out", default=OUT_DIR, help=f"output dir (default {OUT_DIR})")
    args = ap.parse_args()

    client_id = args.client_id or os.environ.get("SPOTIFY_CLIENT_ID")
    if client_id:
        os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
        with open(CLIENT_ID_FILE, "w") as f:
            f.write(client_id.strip() + "\n")
    elif os.path.exists(CLIENT_ID_FILE):
        with open(CLIENT_ID_FILE) as f:
            client_id = f.read().strip()
    if not client_id:
        raise SystemExit(
            "No client id. Pass --client-id ID once (from "
            "developer.spotify.com/dashboard); it is cached afterwards."
        )

    token = get_token(client_id, reauth=args.reauth)
    data = fetch_all(token)
    jpath, tpath, upath, n, nu = write_outputs(data, args.out)

    print()
    print(f"saved tracks     : {len(data['saved_tracks'])}")
    print(f"saved albums     : {len(data['saved_albums'])}")
    print(f"followed artists : {len(data['followed_artists'])}")
    print(f"playlists        : {len(data['playlists'])}")
    print(f"track rows       : {n}  ({nu} unique)")
    print()
    print(f"  {jpath}")
    print(f"  {tpath}")
    print(f"  {upath}")


if __name__ == "__main__":
    main()
