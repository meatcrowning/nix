#!/usr/bin/env python3
"""How an Anima prompt is SPELLED, and where its negative goes.

Two mechanical rules he asked not to have to restate to a model [2026-08-24]:
the tags are written the way Danbooru writes them (spaces, `@artist`), and on a
NegPip family the negative belongs INSIDE the positive at a negative weight
with its own box left empty. Both are code, so both are pinned here.

No backend and no weights: the transform is pure, and the fold is checked by
building the graph with `--dry-run`.

    painter-qtenv python3 tools/anima-test.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent / "pylib"))

import boorutags as B  # noqa: E402
import graph as G  # noqa: E402

FAILED = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label
          + (("  — " + detail) if detail and not cond else ""))
    if not cond:
        FAILED.append(label)


print("\nthe spelling")
cases = [
    ("1girl, looking_at_viewer", "1girl, looking at viewer"),
    ("1girl, ^_^, >_<", "1girl, ^_^, >_<"),                 # emoticons keep it
    ("masterpiece, score_9, score_7_up", "masterpiece, score_9, score_7_up"),
    ("artist:toi8, 1girl", "@toi8, 1girl"),
    ("by hito_komoru, 1girl", "@hito komoru, 1girl"),
    ("@sakimichan, 1girl", "@sakimichan, 1girl"),
    ("by the window, a cat sits", "by the window, a cat sits"),   # prose
    ("1girl,   multi\nline", "1girl, multi line"),
    ("(lowres, low_quality:-1.0), 1girl", "(lowres, low quality:-1.0), 1girl"),
    ("a girl (smiling:1.2) in the rain", "a girl (smiling:1.2) in the rain"),
    ("", ""),
]
for src, want in cases:
    got = G.danbooru_prompt(src)
    check("%r" % (src[:38] or "(empty)"), got == want, "got %r want %r" % (got, want))
check("the family asks for it",
      json.loads((HERE.parent / "families" / "anima.json").read_text())
      .get("prompt_transform") == "danbooru")

print("\nthe vocabulary")
check("a real tag resolves", (B.resolve("1girl") or {}).get("tag") == "1girl")
check("an alias resolves to the canonical tag",
      (B.resolve("sole_female") or {}).get("tag") == "1girl")
check("...spelled either way", (B.resolve("sole female") or {}).get("tag") == "1girl")
check("an invented tag does not", B.resolve("smiling_softly") is None)
hits = B.search("windowsill", limit=5)
check("search finds it", any(h["tag"] == "windowsill" for h in hits), str(hits)[:120])
art = B.search("toi8", category="artist", limit=3)
check("an artist is known to be one",
      bool(art) and art[0]["category"] == "artist", str(art)[:120])
check("search is ordered by how used a tag is",
      [h["posts"] for h in B.search("girl", limit=5)]
      == sorted((h["posts"] for h in B.search("girl", limit=5)), reverse=True))
got = B.check("1girl, smiling_softly, sole female, (lowres:-1.0), @toi8, "
              "She sits on the sill.")
check("check names the invented one", got["unknown"] == ["smiling_softly"], str(got))
check("...and the one that has a real name", bool(got["renamed"]), str(got))
check("...and leaves prose alone",
      "She sits on the sill." not in got["unknown"], str(got))
check("a weight and an @ do not hide a real tag",
      "lowres" in got["known"] and "@toi8" in got["known"], str(got))

print("\nthe negative, on a NegPip family")
tmp = Path(tempfile.mkdtemp(prefix="anima-test-"))
env = dict(os.environ, XDG_STATE_HOME=str(tmp))    # never read HIS painter prefs


def build(*extra):
    out = tmp / "g.json"
    argv = [sys.executable, str(HERE / "smoke.py"), "--dry-run", "--mode", "anime",
            "--prompt", "1girl, solo", "--negative", "lowres, low_quality",
            "--dump-graph", str(out)] + list(extra)
    r = subprocess.run(argv, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print(r.stdout[-600:], r.stderr[-600:])
        return {}, r
    doc = json.loads(out.read_text())
    roles = {}
    for n in doc.values():
        role = (n.get("_meta") or {}).get("painter_role")
        if role:
            roles[role] = n
    return roles, r


roles, r = build()
pos = (roles.get("encode_pos") or {}).get("inputs", {}).get("text", "")
neg = (roles.get("encode_neg") or {}).get("inputs", {}).get("text", "")
check("the negative moves into the positive, at a NEGATIVE weight",
      "(lowres, low quality:-1)" in pos, pos[:200])
check("...and its own box is left empty", neg == "", repr(neg))
check("...and it is reported, not silent", "negpip" in r.stdout, r.stdout[-300:])
roles, r = build("--no-negpip-fold")
pos = (roles.get("encode_pos") or {}).get("inputs", {}).get("text", "")
neg = (roles.get("encode_neg") or {}).get("inputs", {}).get("text", "")
check("opting out keeps the two boxes", "lowres" not in pos and "lowres" in neg,
      "%r / %r" % (pos[:80], neg[:80]))

print()
if FAILED:
    print("FAILED: " + ", ".join(FAILED))
    sys.exit(1)
print("all good")
