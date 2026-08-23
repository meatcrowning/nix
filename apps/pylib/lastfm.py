"""Last.fm, for every app on this desktop that has a reason to ask.

ONE ACCOUNT, ONE CREDENTIAL FILE. player scrobbles what it plays and loves
what he hearts; chatter's agents read his listening history and can love a
track back. Both are the same Last.fm account, so neither owns the
credentials — they live at `~/.config/lastfm/account.json` (override
`$LASTFM_CONFIG`), 0600, and this module is the only thing that reads or
writes them.

**Stdlib only, no Qt.** player calls it from a worker thread, chatter's
agent tool calls it from the tool executor, and `tools/lastfm-connect.py`
calls it from a terminal — a Qt import here would make the CLI a GUI
dependency for nothing.

**The secret never leaves this file.** `api_secret` signs a request and is
never sent; `session_key` is sent but never printed, never put in an error
string, and `redacted()` is what anything user-facing gets. The API key is
NOT in this repo — `~/nix` is public (root AGENTS.md) — so a fresh machine
runs the connect tool once.

The auth flow is Last.fm's desktop one, three steps and a browser:

    token = get_token()          # unauthenticated, signed with the secret
    webbrowser.open(auth_url(token))   # he approves it while logged in
    save_session(*get_session(token))  # -> session key + username

A session key does not expire; only he can revoke it, from the Last.fm
account page.
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_ROOT = "https://ws.audioscrobbler.com/2.0/"
AUTH_PAGE = "https://www.last.fm/api/auth/"
#: Where he creates the API account that yields the key and the secret. Named
#: here because the connect tool and both apps' error strings point at it.
CREATE_PAGE = "https://www.last.fm/api/account/create"
USER_AGENT = "player/1.0 (+https://github.com/meatcrowning/nix)"

CONFIG_PATH = Path(os.path.expanduser(
    os.environ.get("LASTFM_CONFIG", "~/.config/lastfm/account.json")))

#: Scrobbles that could not be sent (no network, Last.fm down) wait here and
#: go out with the next successful one. Last.fm accepts a scrobble up to 14
#: days old, so a queue older than that is dropped rather than rejected.
QUEUE_PATH = Path(os.path.expanduser(
    os.environ.get("LASTFM_QUEUE",
                   "~/.local/state/lastfm/scrobble-queue.json")))
QUEUE_MAX = 500
QUEUE_MAX_AGE = 14 * 24 * 3600

#: A track under this many seconds is never scrobbled — Last.fm's own rule,
#: enforced here so a caller cannot get itself rate-limited by ignoring it.
MIN_TRACK_SECONDS = 30
#: And the point at which one counts: half its length, or four minutes,
#: whichever comes first. The same threshold player already uses for its own
#: play counts, so one listen is one of each.
SCROBBLE_POINT_SECONDS = 240

TIMEOUT = 15.0


class LastfmError(Exception):
    """A refusal from Last.fm, or a transport failure. `code` is Last.fm's own
    numeric error when it gave one (6 = no such user, 9 = invalid session key,
    29 = rate limited), else 0."""

    def __init__(self, message, code=0):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# The credential file
# ---------------------------------------------------------------------------

def load():
    """The account file as a dict, or {} — never raises."""
    try:
        d = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save(**fields):
    """Merge `fields` into the account file, 0600, creating the directory.

    Merging rather than replacing is what lets the connect tool write the key
    and the secret in one run and the session in another."""
    d = load()
    d.update({k: v for k, v in fields.items() if v is not None})
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)
    return d


def forget_session():
    """Disconnect: drop the session key and the username, keep the API key and
    the secret so reconnecting is one approval and not a new API account."""
    d = load()
    d.pop("session_key", None)
    d.pop("username", None)
    if not d:
        try:
            CONFIG_PATH.unlink()
        except OSError:
            pass
        return {}
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)
    return d


def has_keys(cfg=None):
    """Is there an API key and secret — i.e. can the connect flow even start?"""
    c = load() if cfg is None else cfg
    return bool(c.get("api_key")) and bool(c.get("api_secret"))


def connected(cfg=None):
    """Is an account actually linked (keys AND an approved session)?"""
    c = load() if cfg is None else cfg
    return has_keys(c) and bool(c.get("session_key"))


def username(cfg=None):
    c = load() if cfg is None else cfg
    return str(c.get("username") or "")


def status():
    """One dict for any UI: what is configured, who as, and how big the
    backlog is. Carries no secret — see `redacted`."""
    c = load()
    return {"keys": has_keys(c), "connected": connected(c),
            "username": username(c), "queued": len(_queue_read())}


def redacted():
    """The account file with the two secrets replaced by a length — what an
    error message, a log line or an agent tool result may show."""
    c = load()
    out = dict(c)
    for k in ("api_secret", "session_key"):
        if out.get(k):
            out[k] = "set (%d chars)" % len(str(out[k]))
    return out


# ---------------------------------------------------------------------------
# Signed calls
# ---------------------------------------------------------------------------

def sign(params, secret):
    """Last.fm's api_sig: every parameter except `format` and `callback`,
    sorted by name, concatenated as name+value with no separators, the secret
    appended, md5 hex."""
    parts = "".join(k + str(params[k]) for k in sorted(params)
                    if k not in ("format", "callback", "api_sig"))
    return hashlib.md5((parts + secret).encode("utf-8")).hexdigest()


def request_params(method, params=None, signed=False, cfg=None):
    """The full, signed, urlencoded body for one call — WITHOUT sending it.

    Split out of `call` because chatter cannot use `call`: a blocking urllib
    round trip on the GUI thread freezes the window mid-reply, so it takes
    this string and puts it on its own QNetworkAccessManager. The credentials
    and the signature stay here either way, which is the point."""
    c = load() if cfg is None else cfg
    key = str(c.get("api_key") or "")
    if not key:
        raise LastfmError("no Last.fm API key configured — run "
                          "apps/player/tools/lastfm-connect.py")
    p = {k: v for k, v in (params or {}).items()
         if v is not None and v != ""}
    p["method"] = method
    p["api_key"] = key
    if signed:
        secret = str(c.get("api_secret") or "")
        if not secret:
            raise LastfmError("no Last.fm API secret configured")
        sk = str(c.get("session_key") or "")
        if sk and "token" not in p:
            p["sk"] = sk
        p["api_sig"] = sign(p, secret)
    p["format"] = "json"
    return urllib.parse.urlencode(p)


def call(method, params=None, signed=False, post=False, cfg=None):
    """One API call. Returns the parsed JSON body.

    `signed` adds `api_sig` (and `sk`, when a session exists); `post` sends
    the parameters as a form body, which every write method requires. Raises
    `LastfmError` for a transport failure or a Last.fm `error` body — the
    message never carries the session key or the secret."""
    data = request_params(method, params, signed=signed, cfg=cfg).encode("utf-8")
    headers = {"User-Agent": USER_AGENT}
    if post:
        req = urllib.request.Request(API_ROOT, data=data, headers=headers)
    else:
        req = urllib.request.Request(API_ROOT + "?" + data.decode(),
                                     headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        # A Last.fm refusal is a 4xx WITH a JSON body that says why; that is
        # far more use than "HTTP Error 403".
        raw = b""
        try:
            raw = e.read()
        except OSError:
            pass
        obj = _json_or_none(raw)
        if isinstance(obj, dict) and obj.get("message"):
            raise LastfmError(str(obj["message"]),
                              int(obj.get("error") or 0)) from None
        raise LastfmError("HTTP %s from Last.fm" % e.code) from None
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise LastfmError("cannot reach Last.fm: %s" % e) from None

    obj = _json_or_none(body)
    if obj is None:
        raise LastfmError("Last.fm returned something that is not JSON")
    if isinstance(obj, dict) and obj.get("error"):
        raise LastfmError(str(obj.get("message") or "Last.fm error"),
                          int(obj.get("error") or 0))
    return obj


def _json_or_none(raw):
    try:
        return json.loads(raw.decode("utf-8", "replace") or "null")
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# The auth flow
# ---------------------------------------------------------------------------

def get_token(cfg=None):
    """Step one: an unauthorized request token."""
    obj = call("auth.getToken", signed=True, cfg=cfg)
    tok = str((obj or {}).get("token") or "")
    if not tok:
        raise LastfmError("Last.fm gave no token")
    return tok


def auth_url(token, cfg=None):
    """Step two: the page HE opens to approve that token."""
    c = load() if cfg is None else cfg
    return AUTH_PAGE + "?" + urllib.parse.urlencode(
        {"api_key": str(c.get("api_key") or ""), "token": token})


def get_session(token, cfg=None):
    """Step three, after he has approved it: (session_key, username).

    Fails with error 14 until the token is authorized, which is the only way
    to tell "he has not clicked yes yet" from "this token is dead"."""
    obj = call("auth.getSession", {"token": token}, signed=True, cfg=cfg)
    sess = (obj or {}).get("session") or {}
    key, name = str(sess.get("key") or ""), str(sess.get("name") or "")
    if not key:
        raise LastfmError("Last.fm gave no session key")
    return key, name


# ---------------------------------------------------------------------------
# Scrobbling
# ---------------------------------------------------------------------------

def scrobble_point(duration):
    """When a track of `duration` seconds counts as listened to — half of it or
    four minutes, whichever is sooner. 0 for anything too short to scrobble at
    all, which is how a caller asks "is this scrobbleable?" in one call."""
    d = float(duration or 0.0)
    if d < MIN_TRACK_SECONDS:
        return 0.0
    return min(d / 2.0, float(SCROBBLE_POINT_SECONDS))


def now_playing(artist, track, album="", duration=0, album_artist="",
                mbid="", cfg=None):
    """Tell Last.fm what is playing right now. Not a scrobble, not queued —
    it expires on its own, so a failure is nothing to retry."""
    return call("track.updateNowPlaying", _track_params(
        artist, track, album, duration, album_artist, mbid),
        signed=True, post=True, cfg=cfg)


def scrobble(artist, track, album="", duration=0, album_artist="", mbid="",
             when=None, cfg=None):
    """Submit one play, and flush anything the queue is holding with it.

    A failure is never lost and never raised at the caller: the play goes on
    the queue and the next successful scrobble carries it. The return is the
    number of plays actually accepted."""
    entry = _track_params(artist, track, album, duration, album_artist, mbid)
    entry["timestamp"] = int(when if when is not None else time.time())
    if not entry.get("artist") or not entry.get("track"):
        return 0
    pending = _queue_read() + [entry]
    return _flush(pending, cfg=cfg)


def flush_queue(cfg=None):
    """Try the backlog on its own — what a "retry now" button calls."""
    pending = _queue_read()
    return _flush(pending, cfg=cfg) if pending else 0


def _flush(pending, cfg=None):
    cutoff = time.time() - QUEUE_MAX_AGE
    pending = [e for e in pending if float(e.get("timestamp") or 0) > cutoff]
    pending = pending[-QUEUE_MAX:]
    sent = 0
    # Last.fm takes up to 50 plays per batch, indexed [0]..[49].
    while pending:
        batch, rest = pending[:50], pending[50:]
        params = {}
        for i, e in enumerate(batch):
            for k, v in e.items():
                params["%s[%d]" % (k, i)] = v
        try:
            call("track.scrobble", params, signed=True, post=True, cfg=cfg)
        except LastfmError:
            _queue_write(pending)
            return sent
        sent += len(batch)
        pending = rest
    _queue_write([])
    return sent


def _track_params(artist, track, album, duration, album_artist, mbid):
    p = {"artist": str(artist or "").strip(),
         "track": str(track or "").strip()}
    if album:
        p["album"] = str(album).strip()
    if album_artist and str(album_artist).strip() != p["artist"]:
        p["albumArtist"] = str(album_artist).strip()
    if duration:
        p["duration"] = int(float(duration))
    if mbid:
        p["mbid"] = str(mbid)
    return p


def _queue_read():
    try:
        d = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        return [e for e in d if isinstance(e, dict)] if isinstance(d, list) else []
    except (OSError, ValueError, TypeError):
        return []


def _queue_write(entries):
    try:
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = QUEUE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries), encoding="utf-8")
        os.replace(tmp, QUEUE_PATH)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Reading a whole account back — what the local library is merged FROM
# ---------------------------------------------------------------------------
#
# Last.fm pages at 1000 rows a request and answers with `@attr.totalPages`, so
# these walk it. `PAGE_CAP` is the stop: a library this size is a handful of
# requests, and an account whose paging is broken must not spin forever.
PAGE_SIZE = 1000
PAGE_CAP = 40


def _rows(obj, *path):
    """The list at `path`, however Last.fm wrapped it. A ONE-row response is a
    bare object rather than a list of one — the single sharpest edge in this
    API, and the reason a naive merge silently skips accounts with one loved
    track."""
    for k in path:
        obj = (obj or {}).get(k)
    if obj is None:
        return []
    return obj if isinstance(obj, list) else [obj]


def _pages(method, params, listpath, cfg=None, cap=PAGE_CAP):
    """Every row of a paged method, as one list."""
    out, page, total = [], 1, 1
    while page <= min(total, cap):
        p = dict(params)
        p.update({"limit": PAGE_SIZE, "page": page})
        obj = call(method, p, cfg=cfg)
        wrapper = (obj or {}).get(listpath[0]) or {}
        out += _rows(obj, *listpath)
        try:
            total = int((wrapper.get("@attr") or {}).get("totalPages") or 1)
        except (TypeError, ValueError):
            total = 1
        page += 1
    return out


def loved_tracks(user=None, cfg=None):
    """[{artist, track, uts}] — everything he has hearted on Last.fm."""
    c = load() if cfg is None else cfg
    rows = _pages("user.getLovedTracks", {"user": user or username(c)},
                  ("lovedtracks", "track"), cfg=c)
    return [{"artist": ((r.get("artist") or {}).get("name")
                        or (r.get("artist") or {}).get("#text") or ""),
             "track": r.get("name") or "",
             "uts": _uts(r)}
            for r in rows if r.get("name")]


def top_tracks(user=None, cfg=None):
    """[{artist, track, playcount}] over ALL time — the per-track scrobble
    total, which is the only place Last.fm publishes a play count."""
    c = load() if cfg is None else cfg
    rows = _pages("user.getTopTracks",
                  {"user": user or username(c), "period": "overall"},
                  ("toptracks", "track"), cfg=c)
    out = []
    for r in rows:
        try:
            n = int(r.get("playcount") or 0)
        except (TypeError, ValueError):
            n = 0
        if r.get("name") and n > 0:
            out.append({"artist": ((r.get("artist") or {}).get("name") or ""),
                        "track": r["name"], "playcount": n})
    return out


def recent_tracks(user=None, pages=3, cfg=None):
    """[{artist, track, uts}] most recent first — where `last_played` comes
    from. Capped: the whole history is not worth downloading for a timestamp
    the merge only ever moves FORWARD."""
    c = load() if cfg is None else cfg
    rows = _pages("user.getRecentTracks", {"user": user or username(c)},
                  ("recenttracks", "track"), cfg=c, cap=max(1, int(pages)))
    return [{"artist": ((r.get("artist") or {}).get("#text")
                        or (r.get("artist") or {}).get("name") or ""),
             "track": r.get("name") or "", "uts": _uts(r)}
            for r in rows if r.get("name")]


def _uts(row):
    try:
        return int((row.get("date") or {}).get("uts") or 0)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# The two writes that are not a scrobble
# ---------------------------------------------------------------------------

def love(artist, track, cfg=None):
    return call("track.love", {"artist": artist, "track": track},
                signed=True, post=True, cfg=cfg)


def unlove(artist, track, cfg=None):
    return call("track.unlove", {"artist": artist, "track": track},
                signed=True, post=True, cfg=cfg)
