#!/usr/bin/env python3
"""Harness for chatter's `call_api` tool. Offline and deterministic: it builds
requests and projects canned responses, and reaches no booru unless you pass
`--live` (which then does read-only GETs against danbooru and yande.re).

Never touches his screen and never touches his keyring: the credential path is
pointed at a throwaway file for the run.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

_TMP = Path(tempfile.mkdtemp(prefix="oracle-apitest-"))
os.environ["ORACLE_API_KEYS"] = str(_TMP / "api-keys.json")
os.environ.setdefault("ORACLE_CONFIG", str(_TMP / "config"))
os.environ.setdefault("ORACLE_SESSIONS", str(_TMP / "sessions"))

from PySide6.QtCore import QCoreApplication, QUrl, QUrlQuery, QTimer  # noqa: E402
from PySide6.QtNetwork import QNetworkRequest                          # noqa: E402

import main as oracle                                                  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (" — " + detail if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


app = QCoreApplication(sys.argv)

# ---- pure helpers ----------------------------------------------------------
print("dotted paths")
check("nested dict", oracle._api_dig({"file": {"url": "u"}}, "file.url") == "u")
check("list index", oracle._api_dig({"s": ["a", "b"]}, "s.1") == "b")
check("missing is None", oracle._api_dig({"a": 1}, "a.b.c") is None)
check("scalar step is None", oracle._api_dig({"a": 1}, "a.b") is None)

print("credential stripping")
u = "https://danbooru.donmai.us/posts.json?tags=fox&login=lam&api_key=SEKRIT"
safe = oracle._api_safe_url(u)
check("key gone", "SEKRIT" not in safe and "lam" not in safe, safe)
check("query kept", "tags=fox" in safe, safe)
check("clean url untouched",
      oracle._api_safe_url("https://x.test/a?b=1") == "https://x.test/a?b=1")

print("the registry")
check("every site has base/path/fields",
      all({"base", "path", "fields"} <= set(v) for v in oracle.API_SITES.values()))
blurb = oracle._api_sites_blurb()
check("blurb names every site",
      all(k in blurb for k in oracle.API_SITES))
check("tool enum matches the table",
      oracle.CALL_API_TOOL["function"]["parameters"]["properties"]["site"]["enum"]
      == sorted(oracle.API_SITES))
check("tool is offered every turn",
      "call_api" in oracle.Ollama._offered_tool_names())

# ---- projection ------------------------------------------------------------
print("projection")
danb = [{"id": i, "file_url": "https://x/%d.jpg" % i, "tag_string": "a b",
         "rating": "g", "score": i, "junk": "x" * 900} for i in range(30)]
r = oracle.Ollama._api_project(danb, "u", "application/json",
                               ["id", "file_url"], "", 0)
check("rows projected", r["rows"][0] == {"id": 0, "file_url": "https://x/0.jpg"})
check("junk dropped", "junk" not in r["rows"][0])
check("total reported", r["count_total"] == 30)
check("well under the cap",
      len(json.dumps(r["rows"])) < oracle.API_CHARS)

r2 = oracle.Ollama._api_project(danb, "u", "application/json", ["*"], "", 0)
check("star keeps whole rows", r2["rows"][0]["junk"].startswith("x"))
check("cap drops rows, never halves one",
      all(isinstance(row, dict) and "id" in row for row in r2["rows"])
      and r2["count_returned"] < 30 and r2.get("truncated") is True)

r3 = oracle.Ollama._api_project({"posts": danb}, "u", "application/json",
                                ["id"], "posts", 25)
check("select finds a wrapped list", r3["count_returned"] == 5)
check("offset honoured", r3["rows"][0] == {"id": 25})
check("no next_offset at the end", "next_offset" not in r3)

r4 = oracle.Ollama._api_project({"posts": danb}, "u", "application/json",
                                ["id"], "nope", 0)
check("bad select is an error, not a lie", "error" in r4)

r5 = oracle.Ollama._api_project({"a": 1}, "u", "application/json", None, "", 0)
check("non-list response passed through", json.loads(r5["json"]) == {"a": 1})

# ---- request building (nothing is sent) ------------------------------------
print("request building")
built = {}


class _FakeNam:
    def get(self, req):
        built["req"] = req
        built["method"] = "GET"
        return None

    def head(self, req):
        built["req"] = req
        built["method"] = "HEAD"
        return None


class _Probe(oracle.Ollama):
    pass


o = oracle.Ollama()
o._nam = _FakeNam()
o._busy = True
o._tool_results = [None]
errors = []
o.webSearchError.connect(lambda a, b: errors.append((a, b)))


def build(args):
    built.clear()
    del errors[:]
    o._tool_results = [None]
    try:
        o._call_api(args, 0, {"n": 1}, [])
    except AttributeError:
        pass          # reply is None in the fake; the request is already built
    return built.get("req")


req = build({"site": "danbooru", "params": {"tags": "fox", "limit": 5}})
url = req.url().toString()
check("site base + path", url.startswith("https://danbooru.donmai.us/posts.json"), url)
check("params sent", "tags=fox" in url and "limit=5" in url, url)
check("caller limit beats the default", "limit=20" not in url, url)

req = build({"site": "danbooru", "params": {"tags": "fox"}})
# NOT a browser UA: danbooru 403s that string on this endpoint (measured).
check("a named client UA, not a browser one",
      bytes(req.rawHeader("User-Agent")).startswith(b"chatter/")
      and b"Mozilla" not in bytes(req.rawHeader("User-Agent")))

req = build({"url": "https://api.test/v1/things", "params": {"q": "x"}})
check("bare url works", req.url().toString() == "https://api.test/v1/things?q=x")

build({"url": "ftp://nope/x"})
check("non-http refused before the network", errors and "absolute" in errors[0][1])
build({"site": "nosuchbooru"})
check("unknown site refused", errors and "unknown site" in errors[0][1])
build({"url": "https://api.test/x", "method": "POST"})
check("POST refused", errors and "read-only" in errors[0][1])
req = build({"url": "https://api.test/x", "method": "HEAD"})
check("HEAD allowed", built.get("method") == "HEAD")

print("the keyring")
Path(os.environ["ORACLE_API_KEYS"]).write_text(json.dumps({
    "danbooru": {"params": {"login": "lam", "api_key": "SEKRIT"}},
    "e621": {"basic": ["lam", "SEKRIT2"]},
    "mine": {"headers": {"Authorization": "Bearer SEKRIT3"}}}), encoding="utf-8")
check("absent entry is empty, never an exception",
      oracle.api_credentials("nothing-here") == {})
req = build({"site": "danbooru", "params": {"tags": "fox"}})
check("keyring params reach the wire", "api_key=SEKRIT" in req.url().toString())
req = build({"site": "e621", "params": {"tags": "fox"}})
check("basic auth header built",
      bytes(req.rawHeader("Authorization")).startswith(b"Basic "))
req = build({"url": "https://api.test/x", "auth": "mine"})
check("named auth entry sends its header",
      bytes(req.rawHeader("Authorization")) == b"Bearer SEKRIT3")
os.environ["ORACLE_API_KEYS"] = str(_TMP / "gone.json")
oracle.API_KEYS_PATH = str(_TMP / "gone.json")
check("missing keyring file is empty, never an exception",
      oracle.api_credentials("danbooru") == {})
build({"site": "gelbooru", "params": {"tags": "cat"}})
check("a site needing a key is refused before the network, with the fix",
      errors and "needs credentials" in errors[0][1]
      and oracle.API_KEYS_PATH in errors[0][1], str(errors))
check("...and nothing was sent", "req" not in built)

# ---- optional: the real thing ---------------------------------------------
if "--live" in sys.argv:
    print("live (read-only GETs)")
    live = oracle.Ollama()
    live._busy = True
    # Only the sites that answer anonymously; the two that do not are checked
    # for their honest refusal instead (below), since the harness has no keys.
    for site, params in (("danbooru", {"tags": "cat", "limit": 3}),
                         ("safebooru", {"tags": "cat", "limit": 3}),
                         ("konachan", {"tags": "landscape", "limit": 3}),
                         ("yandere", {"tags": "landscape", "limit": 3})):
        live._tool_results = [None]
        # n=2 on purpose: _tool_done must never reach zero here, or it would
        # POST the turn to the ollama daemon. We only want the one GET.
        live._call_api({"site": site, "params": params}, 0, {"n": 2}, [])
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.start(25000)
        while live._tool_results[0] is None and deadline.isActive():
            app.processEvents()
        got = live._tool_results[0]
        if got is None:
            check(site + " answered", False, "timed out")
            continue
        res = json.loads(got["content"])
        check(site + " returned rows",
              isinstance(res.get("rows"), list) and len(res["rows"]) > 0,
              json.dumps(res)[:300])
        if res.get("rows"):
            check(site + " rows are projected",
                  "id" in res["rows"][0], json.dumps(res["rows"][0])[:200])
            check(site + " result is under the cap",
                  len(got["content"]) <= oracle.API_CHARS + 2000,
                  str(len(got["content"])))

print()
if FAILED:
    print("FAILED: " + ", ".join(FAILED))
    raise SystemExit(1)
print("all ok")
