#!/usr/bin/env python3
"""Harness for the Last.fm client — offline, against a stub, never his account.

    tools/lastfm-test.py

It stands up a stub audioscrobbler on 127.0.0.1 and points `pylib/lastfm.py`
at it, with `$LASTFM_CONFIG` and `$LASTFM_QUEUE` in a temp directory, so
nothing here can read his credentials, write to his listening history, or send
a single packet off this machine. The one thing it asserts against the real
service is the SIGNATURE, using the worked example shape from Last.fm's own
docs — get that wrong and every write silently 4xxs.

Covered: the api_sig, the params a call actually sends, the scrobble
threshold, the offline queue (fail -> queued -> flushed with the next
success, and the 14-day drop), love/unlove, the auth flow's three steps, and
chatter's projection of a response.

The last section needs PySide6 on the path, i.e.
`oracle-qtenv python3 tools/lastfm-test.py`; without it that section is
skipped and the rest still runs.
"""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "pylib"))

TMP = tempfile.mkdtemp(prefix="lastfm-test-")
os.environ["LASTFM_CONFIG"] = str(Path(TMP) / "account.json")
os.environ["LASTFM_QUEUE"] = str(Path(TMP) / "queue.json")

import lastfm  # noqa: E402

FAILS = []
SEEN = []          # every request the stub received, as (method, params)
MODE = {"fail": False, "error": None}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _answer(self, params):
        SEEN.append((params.get("method", ""), params))
        if MODE["fail"]:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"nope")
            return
        if MODE["error"]:
            body = json.dumps({"error": MODE["error"], "message": "stub refusal"})
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())
            return
        method = params.get("method", "")
        if method == "auth.getToken":
            out = {"token": "TOK"}
        elif method == "auth.getSession":
            out = {"session": {"key": "SESSKEY", "name": "lam"}}
        elif method == "user.getRecentTracks":
            out = {"recenttracks": {"track": [
                {"name": "Gemini", "artist": {"#text": "Chet Faker"},
                 "image": [{"#text": "http://x/1.png"}], "streamable": "0"}]}}
        else:
            out = {"ok": 1}
        body = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        q = urllib.parse.urlparse(self.path).query
        self._answer(dict(urllib.parse.parse_qsl(q)))

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode()
        self._answer(dict(urllib.parse.parse_qsl(raw)))


def load_app(name, path):
    """Import an app's `main.py` under its OWN module name. Both apps call
    theirs `main`, so a plain `import main` gets whichever was imported first
    — silently, with the second app's names simply missing."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (" — " + detail if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def main():
    srv = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    lastfm.API_ROOT = "http://127.0.0.1:%d/2.0/" % srv.server_address[1]

    print("signature")
    # Last.fm's rule: name+value pairs sorted by name, concatenated, secret
    # appended, md5. `format` is excluded; api_sig itself is excluded.
    sig = lastfm.sign({"api_key": "K", "method": "auth.getToken",
                       "format": "json"}, "S")
    import hashlib
    want = hashlib.md5(b"api_keyKmethodauth.getTokenS").hexdigest()
    check("api_sig excludes format and sorts by name", sig == want, sig)

    print("\nthe credential file")
    check("nothing configured to start with", not lastfm.has_keys())
    lastfm.save(api_key="K", api_secret="S")
    check("keys land", lastfm.has_keys() and not lastfm.connected())
    check("file is 0600",
          (os.stat(lastfm.CONFIG_PATH).st_mode & 0o777) == 0o600)
    check("redacted() hides the secret",
          lastfm.redacted()["api_secret"].startswith("set ("))

    print("\nthe auth flow")
    tok = lastfm.get_token()
    check("step 1 returns a token", tok == "TOK", tok)
    url = lastfm.auth_url(tok)
    check("step 2 url carries the key and the token",
          "api_key=K" in url and "token=TOK" in url, url)
    key, name = lastfm.get_session(tok)
    lastfm.save(session_key=key, username=name)
    check("step 3 links the account",
          lastfm.connected() and lastfm.username() == "lam")

    print("\nthe scrobble threshold")
    check("a 20s track is never scrobbled", lastfm.scrobble_point(20) == 0)
    check("a 3min track counts at half", lastfm.scrobble_point(180) == 90)
    check("a 20min track counts at 4 minutes",
          lastfm.scrobble_point(1200) == 240)

    print("\na scrobble")
    SEEN.clear()
    now = int(time.time())
    n = lastfm.scrobble("Chet Faker", "Gemini", album="Built on Glass",
                        duration=250, when=now)
    check("one play accepted", n == 1, str(n))
    m, p = SEEN[-1]
    check("sent as track.scrobble", m == "track.scrobble", m)
    check("indexed fields", p.get("artist[0]") == "Chet Faker"
          and p.get("track[0]") == "Gemini"
          and p.get("timestamp[0]") == str(now), json.dumps(p))
    check("signed with the session key",
          p.get("sk") == "SESSKEY" and len(p.get("api_sig", "")) == 32)
    check("format is not in the signature body but is in the request",
          p.get("format") == "json")

    print("\nnow playing, love, unlove")
    SEEN.clear()
    lastfm.now_playing("Chet Faker", "Gemini", duration=250)
    check("track.updateNowPlaying", SEEN[-1][0] == "track.updateNowPlaying")
    lastfm.love("Chet Faker", "Gemini")
    check("track.love", SEEN[-1][0] == "track.love")
    lastfm.unlove("Chet Faker", "Gemini")
    check("track.unlove", SEEN[-1][0] == "track.unlove")

    print("\nthe offline queue")
    MODE["fail"] = True
    n = lastfm.scrobble("A", "one", duration=200, when=int(time.time()))
    check("a failed scrobble is not lost and not raised", n == 0)
    check("it is on the queue", len(lastfm._queue_read()) == 1)
    lastfm.scrobble("B", "two", duration=200, when=int(time.time()))
    check("and so is the next", len(lastfm._queue_read()) == 2)
    MODE["fail"] = False
    SEEN.clear()
    n = lastfm.scrobble("C", "three", duration=200, when=int(time.time()))
    check("the backlog goes out with the next success", n == 3, str(n))
    check("the queue is empty afterwards", lastfm._queue_read() == [])
    m, p = SEEN[-1]
    check("all three in ONE batch",
          p.get("artist[0]") == "A" and p.get("artist[2]") == "C", json.dumps(p))

    print("\nthe 14-day drop")
    MODE["fail"] = True
    lastfm.scrobble("Old", "ancient", duration=200,
                    when=int(time.time()) - 20 * 24 * 3600)
    MODE["fail"] = False
    SEEN.clear()
    lastfm.scrobble("New", "fresh", duration=200, when=int(time.time()))
    m, p = SEEN[-1]
    check("a play Last.fm would reject is dropped, not retried forever",
          p.get("artist[0]") == "New" and "artist[1]" not in p, json.dumps(p))

    print("\na refusal")
    MODE["error"] = 9
    try:
        lastfm.now_playing("A", "b")
        check("a Last.fm error body raises", False)
    except lastfm.LastfmError as e:
        check("a Last.fm error body raises with its code", e.code == 9, str(e.code))
        check("and never carries the secret",
              "S" != str(e) and "SESSKEY" not in str(e))
    MODE["error"] = None

    print("\nchatter's projection")
    # Imported for one staticmethod; importing the module builds no window.
    sys.path.insert(0, str(HERE.parents[1] / "oracle"))
    try:
        oracle = load_app("oracle_main",
                          str(HERE.parents[1] / "oracle" / "main.py"))
    except ImportError as e:
        # No Qt on the path: the client half above is what this harness is
        # for, so say what is missing rather than failing on it.
        print("  skip chatter's half — %s (run it as: "
              "oracle-qtenv python3 tools/lastfm-test.py)" % e)
    else:
        raw = {"recenttracks": {"track": [
            {"name": "Gemini", "artist": {"#text": "Chet Faker"},
             "image": [{"#text": "x"}], "streamable": "0",
             "bio": "y" * 2000}]}}
        out = oracle.Ollama._lastfm_project(raw, 20)
        text = json.dumps(out)
        check("the wrapper key is unwrapped", "recenttracks" not in text)
        check("images and streamable are dropped",
              "image" not in text and "streamable" not in text)
        check("a long string is cut", len(out["track"][0]["bio"]) < 800)
        check("the rows survive", out["track"][0]["name"] == "Gemini")
        check("the tool is offered", "lastfm" in oracle.Ollama._offered_tool_names())
        check("and a subagent can be given it",
              "lastfm" in oracle._tool_registry())

    print("\nthe finder's field filters, and the merge")
    os.environ["XDG_DATA_HOME"] = str(Path(TMP) / "data")
    os.environ["XDG_STATE_HOME"] = str(Path(TMP) / "state")
    os.environ["XDG_CACHE_HOME"] = str(Path(TMP) / "cache")
    sys.path.insert(0, str(HERE.parents[0]))
    try:
        player = load_app("player_main", str(HERE.parents[0] / "main.py"))
    except ImportError as e:
        print("  skip player's half — %s (run it as: "
              "player-qtenv python3 tools/lastfm-test.py)" % e)
    else:
        q = player.parse_query
        check("plain text is unchanged",
              q("chet faker") == (["chet", "faker"], [], None, None), str(q("chet faker")))
        check("genre: is lifted out of the words",
              q("gemini genre:soul") == (["gemini"], ["soul"], None, None), str(q("gemini genre:soul")))
        check("a quoted genre keeps its space",
              q('genre:"post rock"') == ([], ["post rock"], None, None), str(q('genre:"post rock"')))
        check("year: one value is an exact year",
              q("year:1997") == ([], [], 1997, 1997), str(q("year:1997")))
        check("year: a range", q("year:1990-1999") == ([], [], 1990, 1999))
        check("year: an open end", q("year:2010-") == ([], [], 2010, None))
        check("year: a comparison", q("year:>2010") == ([], [], 2011, None))
        check("an incomplete term matches everything, not nothing",
              q("genre:") == ([], [], None, None), str(q("genre:")))
        check("a missing year matches only an unbounded query",
              player.year_in(None, 1990, None) is False
              and player.year_in(None, None, None) is True)

        # A real Library against a throwaway DB — the merge is the point.
        prefs = player.Prefs()
        lib = player.Library(player.TagWriter(prefs))
        con = lib._con
        def add(tid, artist, title, fav=0, plays=0, last=None):
            con.execute("INSERT INTO tracks (id, path, mtime, size, title,"
                        " artist, favorite, play_count, last_played, added_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (tid, "/tmp/%d.flac" % tid, 0, 0, title, artist,
                         fav, plays, last, 0))
        add(1, "Chet Faker", "Gemini", fav=1, plays=9)      # loved HERE only
        add(2, "Chet Faker", "Talk Is Cheap", fav=0, plays=2)
        add(3, "Hadouken!", "Oxygen (Gemini Remix)", fav=0, plays=40)
        con.commit()

        st = lib.merge_lastfm({
            "loved": [{"artist": "Chet Faker", "track": "Talk Is Cheap"},
                      {"artist": "Nobody", "track": "Nothing"}],
            "plays": [{"artist": "Chet Faker", "track": "Talk Is Cheap",
                       "playcount": 17},
                      {"artist": "Hadouken!", "track": "Oxygen", "playcount": 3}],
            "recent": [{"artist": "Chet Faker", "track": "Talk Is Cheap",
                        "uts": 1999999999}]})
        rows = {r["id"]: r for r in lib._rows("SELECT * FROM tracks")}
        check("a love on last.fm hearts it here", rows[2]["favorite"] == 1)
        check("a local-only favourite is KEPT", rows[1]["favorite"] == 1)
        check("and reported rather than reconciled",
              st["local_only_loves"] == 1, str(st))
        check("a higher remote count is taken", rows[2]["play_count"] == 17)
        check("a higher LOCAL count is never lowered", rows[3]["play_count"] == 40,
              str(rows[3]["play_count"]))
        check("last_played moves forward", rows[2]["last_played"] == 1999999999)
        check("a track that is not in the library is counted, not guessed at",
              st["unmatched"] == 1, str(st))
        check("the decorated title still matched (trackmatch)",
              st["counts"] == 1, str(st))
        check("ratings are untouched",
              all(r["rating"] is None for r in rows.values()))
        lib.close()

    srv.shutdown()
    print("\n%d checks failed" % len(FAILS))
    for f in FAILS:
        print("  " + f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
