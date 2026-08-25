#!/usr/bin/env python3
"""Harness for the `wikipedia` tool — the citable answer.

    <an app python> apps/oracle/tools/wikipedia-test.py

It exists because a small model asked for a plain fact will invent one [his,
2026-08-24]. `web_search` returns snippets written to be clicked on and
`fetch_url` returns whatever HTML is at a URL; this tool returns an article,
its text and its URL, in one MediaWiki round trip.

Two halves. The URL builder and the result reader are pure functions, driven
here off a canned payload — no network, no window, nothing of his touched. The
last check is a REAL lookup against en.wikipedia.org, and a machine with no
route to it reports skipped rather than failed: the parse is what this file is
guarding, and the network is not ours.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

import main as oracle  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"   [{detail}]" if detail else ""))
    if not ok:
        fails.append(name)


print("chatter's wikipedia tool")

# ---- the tool is on the wire, unprompted --------------------------------
core = oracle.CORE_TOOL_NAMES
check("it is a CORE tool, so a turn never has to go looking for it",
      "wikipedia" in core, str(core[-6:]))
check("...and it is in the `web` group for a subagent",
      "wikipedia" in oracle.AGENT_TOOL_GROUPS["web"],
      str(oracle.AGENT_TOOL_GROUPS["web"]))
check("...and in the registry a subagent draws from",
      "wikipedia" in oracle._tool_registry())
schema = oracle.WIKIPEDIA_TOOL["function"]
check("the description tells the model to prefer it for facts",
      "PREFER THIS" in schema["description"])
check("query is the only required argument",
      schema["parameters"]["required"] == ["query"], str(schema["parameters"]["required"]))

# ---- one round trip: the search and the article text in ONE request -----
u = oracle.wikipedia_url("ada lovelace")
q = u.query()
check("it queries the language edition asked for",
      u.host() == "en.wikipedia.org", u.host())
check("the search and the extract ride the same call",
      "generator=search" in q and "prop=extracts" in q, q)
check("the text comes back as plain text, not wikitext", "explaintext=1" in q, q)
check("a redirect is followed, so a near-miss title still lands",
      "redirects=1" in q, q)
check("the summary is the default", "exintro=1" in q, q)
check("...and full=True asks for the whole article",
      "exintro" not in oracle.wikipedia_url("x", full=True).query())
check("another edition is just another host",
      oracle.wikipedia_url("x", lang="fr").host() == "fr.wikipedia.org")
check("a junk lang falls back to en rather than building a junk host",
      oracle.wikipedia_url("x", lang="../evil").host() == "en.wikipedia.org",
      oracle.wikipedia_url("x", lang="../evil").host())
check("...and so does an edition that is not one",
      oracle.wikipedia_url("x", lang="EVIL.example.com").host() == "en.wikipedia.org")

# ---- the result: the best match carries the text, the rest are names ----
PAYLOAD = {"query": {"pages": [
    {"index": 2, "title": "Analytical Engine",
     "fullurl": "https://en.wikipedia.org/wiki/Analytical_Engine",
     "extract": "A mechanical general-purpose computer."},
    {"index": 1, "title": "Ada Lovelace",
     "fullurl": "https://en.wikipedia.org/wiki/Ada_Lovelace",
     "extract": "A" * 9000},
]}}
r = oracle.wikipedia_result(PAYLOAD, "ada lovelace")
check("the search's own ranking decides, not the order the JSON arrived in",
      r["title"] == "Ada Lovelace", r["title"])
check("the URL is there, so the reply can cite it",
      r["url"].endswith("/Ada_Lovelace"), r["url"])
check("a long article is capped rather than dumped into the window",
      len(r["text"]) == oracle.WIKIPEDIA_CHARS, str(len(r["text"])))
check("...and says so, with where to continue",
      r.get("truncated") and r["next_offset"] == oracle.WIKIPEDIA_CHARS,
      "next_offset=" + str(r.get("next_offset")))
check("the other matches are named but cost nothing",
      r["other_matches"] == [{"title": "Analytical Engine",
                              "url": "https://en.wikipedia.org/wiki/Analytical_Engine"}],
      str(r.get("other_matches")))
r2 = oracle.wikipedia_result(PAYLOAD, "ada lovelace", offset=r["next_offset"])
check("paging on picks up where it left off",
      r2["offset"] == oracle.WIKIPEDIA_CHARS and not r2.get("truncated"),
      str(r2["offset"]) + " len=" + str(len(r2["text"])))

check("nothing found is an error the model can read, not an empty answer",
      "error" in oracle.wikipedia_result({"query": {"pages": []}}, "asdfqwer"),
      str(oracle.wikipedia_result({"query": {"pages": []}}, "asdfqwer")))
check("a page with no extract says to read it with fetch_url instead",
      "fetch_url" in oracle.wikipedia_result(
          {"query": {"pages": [{"index": 1, "title": "T", "fullurl": "u"}]}},
          "t")["error"])

# ---- and once, for real -------------------------------------------------
try:
    req = urllib.request.Request(
        bytes(oracle.wikipedia_url("ada lovelace").toEncoded()).decode(),
        headers={"User-Agent": "chatter-test/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as fh:
        live = oracle.wikipedia_result(json.loads(fh.read().decode()), "ada lovelace")
    check("a real lookup returns the article, its URL and its text",
          live.get("title") == "Ada Lovelace" and "wikipedia.org" in live.get("url", "")
          and len(live.get("text", "")) > 200,
          str(live.get("title")) + " " + str(len(live.get("text", ""))) + " chars")
except (urllib.error.URLError, TimeoutError, OSError) as e:
    print("  skip  the live lookup   [no route to en.wikipedia.org: %s]" % e)

print("FAILED: " + ", ".join(fails) if fails else "all ok")
sys.exit(1 if fails else 0)
