#!/usr/bin/env python3
"""smartlist-test.py — the smart-playlist rule engine, headless.

Runs entirely inside a throwaway XDG_DATA_HOME/XDG_STATE_HOME/XDG_CACHE_HOME
with a scratch library.db of fifteen invented tracks: the LIVE library, the
live smartlists.json and the running player are never touched, and no audio
device or Wayland connection is needed (QT_QPA_PLATFORM=offscreen, and nothing
here builds a Player or a QML engine at all).

    QT_QPA_PLATFORM=offscreen python3 apps/player/tools/smartlist-test.py

Four layers:

  1. the SQL builder — every field kind against every operator, checked by the
     exact set of track titles it returns;
  2. injection — a rule value and a list name made of SQL, which must come back
     as text that matched nothing rather than as a statement;
  3. the store — seeding, round-tripping, unique names, delete/duplicate,
     restore_defaults, and a hand-corrupted file;
  4. the eight seeded defaults, including "4+ starred & liked", against the
     same fixture — the one place the built-ins' MEANING is asserted.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent


def _relaunch_under_player_python():
    """main.py imports PySide6, which a plain `python3` here does not have.

    Resolved the way tools/soulseek-missing.py does it — READ the `player`
    wrapper and take the env path out of it. Never source it: running the
    wrapper's body launches the app (apps/AGENTS.md, and the memory that a
    borrowed surfer env opened three tabs in his live browser).
    """
    if os.environ.get("SMARTLIST_TEST_RELAUNCHED"):
        return
    p = shutil.which("player")
    text = ""
    if p:
        try:
            text = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            pass
    m = re.search(r"/nix/store/[^\" ]+-env/bin/python3[0-9.]*", text)
    if not m:
        sys.exit("no PySide6, and no `player` wrapper to resolve its python from")
    os.environ["SMARTLIST_TEST_RELAUNCHED"] = "1"
    os.execv(m.group(0), [m.group(0), str(Path(__file__).resolve())] + sys.argv[1:])


try:
    import PySide6  # noqa: F401
except ModuleNotFoundError:
    _relaunch_under_player_python()

_tmp = tempfile.TemporaryDirectory(prefix="smartlist-test-")
for var in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[var] = str(Path(_tmp.name) / var.lower())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(APP))
import main as P  # noqa: E402  (must follow the env setup above)

DAY = 86400.0
NOW = time.time()

# title, artist, album, album_artist, genre, codec, year, rating, favorite,
# play_count, duration, added_at, last_played
FIXTURE = [
    ("Alpha",   "Boards of Canada", "Geogaddi", "Boards of Canada", "IDM",
     "flac", 2002, 1.0,  0, 40, 300, NOW - 400 * DAY, NOW - 2 * DAY),
    ("Beta",    "Boards of Canada", "Geogaddi", "Boards of Canada", "IDM",
     "flac", 2002, 0.79, 1, 12, 200, NOW - 400 * DAY, NOW - 90 * DAY),
    ("Gamma",   "Autechre",         "Tri Repetae", "Autechre", "IDM",
     "flac", 1995, 0.8,  0,  5, 420, NOW - 30 * DAY,  NOW - 1 * DAY),
    ("Delta",   "Autechre",         "Tri Repetae", "Autechre", "Electronic",
     "mp3",  1995, 0.6,  1,  0, 180, NOW - 30 * DAY,  None),
    ("Epsilon", "Wu-Lu",            "LOGGERHEAD", "Wu-Lu", "Punk",
     "mp3",  2022, None, 1,  3, 150, NOW - 2 * DAY,   NOW - 0.5 * DAY),
    ("Zeta",    "Wu-Lu",            "LOGGERHEAD", "Wu-Lu", "Punk",
     "mp3",  2022, 0.2,  0,  0, 95,  NOW - 2 * DAY,   None),
    ("Eta",     "Oneohtrix Point Never", "R Plus Seven", "Oneohtrix Point Never",
     "Ambient", "flac", 2013, 0.99, 0, 20, 240, NOW - 100 * DAY, NOW - 10 * DAY),
    ("Theta",   "Oneohtrix Point Never", "R Plus Seven", "Oneohtrix Point Never",
     "Ambient", "flac", 2013, None, 0, 1, 60,  NOW - 100 * DAY, NOW - 200 * DAY),
    ("Iota",    "羊文学",            "our hope",   "羊文学", "Rock",
     "flac", 2022, 0.8,  1, 30, 270, NOW - 5 * DAY,   NOW - 3 * DAY),
    ("Kappa",   "羊文学",            "our hope",   "羊文学", "Rock",
     "m4a",  2022, None, 0,  0, 210, NOW - 5 * DAY,   None),
    ("Lambda",  "Duster",           "Stratosphere", "Duster", "Slowcore",
     "flac", 1998, 0.4,  0,  8, 130, NOW - 700 * DAY, NOW - 400 * DAY),
    ("Mu",      "Duster",           "Stratosphere", "Duster", None,
     "flac", 1998, None, 0,  0, 110, NOW - 700 * DAY, None),
    ("Nu",      "MF DOOM",          "MM..FOOD",   "MF DOOM", "Hip Hop",
     "mp3",  2004, 1.0,  1, 55, 175, NOW - 1 * DAY,   NOW - 0.2 * DAY),
    ("Xi",      "MF DOOM",          "MM..FOOD",   "MF DOOM", "Hip Hop",
     "mp3",  2004, 0.6,  0,  2, 205, NOW - 1 * DAY,   NOW - 15 * DAY),
    ("O'Brien", "The Fall",         "Hex Enduction Hour", "The Fall", "Post-Punk",
     "flac", 1982, 0.2,  0,  1, 500, NOW - 900 * DAY, None),
]

fails = []
checks = 0


def check(ok, what, detail=""):
    global checks
    checks += 1
    if not ok:
        fails.append(f"{what}{(': ' + detail) if detail else ''}")
        print(f"  FAIL  {what}" + (f"\n        {detail}" if detail else ""))
    return ok


def build_db():
    con = P.open_db()
    con.create_function("cfold", 1, P._cfold, deterministic=True)
    for i, t in enumerate(FIXTURE):
        (title, artist, album, aartist, genre, codec, year, rating, fav,
         plays, dur, added, played) = t
        con.execute(
            "INSERT INTO tracks (path, mtime, size, title, artist, album,"
            " album_artist, track, disc, year, orig_year, genre, duration, codec,"
            " rating, favorite, play_count, added_at, last_played, has_art)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"/scratch/{i}.{codec}", 1.0, 100, title, artist, album, aartist,
             i + 1, 1, year, year, genre, float(dur), codec, rating, fav, plays,
             added, played, 1 if i % 2 == 0 else 0))
    con.commit()
    return con


def titles(con, spec):
    sql, params = P.smart_sql(P.normalize_smart(spec))
    return [r["title"] for r in con.execute(sql, params)]


def matched(con, rules, match="all"):
    return set(titles(con, {"name": "t", "match": match, "rules": rules}))


def rule(field, op, value=None):
    r = {"field": field, "op": op}
    if value is not None:
        r["value"] = value
    return r


# ---------------------------------------------------------------------------
# 1. the SQL builder, kind by kind
# ---------------------------------------------------------------------------

def test_rules(con):
    print("\n-- rules --")

    # text
    check(matched(con, [rule("artist", "contains", "duster")]) == {"Lambda", "Mu"},
          "contains is case-insensitive")
    check(matched(con, [rule("artist", "contains", "羊文")]) == {"Iota", "Kappa"},
          "contains works on Japanese (cfold, not SQLite lower())")
    check(matched(con, [rule("album", "is", "geogaddi")]) == {"Alpha", "Beta"},
          "is, folded")
    check(matched(con, [rule("artist", "starts with", "MF")]) == {"Nu", "Xi"},
          "starts with")
    check(matched(con, [rule("title", "ends with", "ta")])
          == {"Beta", "Delta", "Zeta", "Eta", "Theta", "Iota"}, "ends with")
    check("Mu" in matched(con, [rule("genre", "does not contain", "rock")]),
          "does not contain keeps a NULL column",
          "a track with no genre must not be dropped by a negative text rule")
    check(matched(con, [rule("genre", "is unset")]) == {"Mu"}, "text is unset")
    check(len(matched(con, [rule("genre", "is set")])) == len(FIXTURE) - 1,
          "text is set")
    check(matched(con, [rule("anytext", "contains", "geogaddi")]) == {"Alpha", "Beta"},
          "any text spans the four tags the search box uses")
    check(matched(con, [rule("anytext", "contains", "O'Brien")]) == {"O'Brien"},
          "a quote in a value is a literal, not a syntax error")

    # stars — the epsilon is what keeps 0.79 inside "4+"
    check(matched(con, [rule("rating", "at least", 4)])
          == {"Alpha", "Beta", "Gamma", "Eta", "Iota", "Nu"},
          "4+ stars includes an externally-tagged 0.79")
    check(matched(con, [rule("rating", "at least", 5)]) == {"Alpha", "Eta", "Nu"},
          "5 stars includes an externally-tagged 0.99")
    check(matched(con, [rule("rating", "at most", 2)]) == {"Zeta", "O'Brien", "Lambda"},
          "at most 2 stars (0.4 IS two stars, and is in)")
    check(matched(con, [rule("rating", "is", 3)]) == {"Delta", "Xi"}, "is 3 stars")
    check(matched(con, [rule("rating", "is unset")]) == {"Epsilon", "Theta", "Kappa", "Mu"},
          "unrated")
    check("Epsilon" in matched(con, [rule("rating", "is not", 5)]),
          "is not N stars keeps unrated tracks")

    # bool
    check(matched(con, [rule("favorite", "is", True)])
          == {"Beta", "Delta", "Epsilon", "Iota", "Nu"}, "liked = yes")
    check(len(matched(con, [rule("favorite", "is", False)])) == len(FIXTURE) - 5,
          "liked = no")

    # counts / minutes / date
    check(matched(con, [rule("play_count", "at least", 30)]) == {"Alpha", "Iota", "Nu"},
          "play count at least")
    check(matched(con, [rule("year", "at most", 1995)])
          == {"Gamma", "Delta", "O'Brien"}, "year at most")
    check(matched(con, [rule("duration", "at least", 7)]) == {"Gamma", "O'Brien"},
          "length in MINUTES, not seconds")
    check(matched(con, [rule("added_at", "in the last", 7)])
          == {"Epsilon", "Zeta", "Iota", "Kappa", "Nu", "Xi"}, "added in the last week")
    check("Alpha" in matched(con, [rule("added_at", "not in the last", 7)]),
          "not in the last N days")
    check(matched(con, [rule("last_played", "is unset")])
          == {"Delta", "Zeta", "Kappa", "Mu", "O'Brien"}, "never played")

    # match all / any
    check(matched(con, [rule("rating", "at least", 4), rule("favorite", "is", True)],
                  "all") == {"Beta", "Iota", "Nu"}, "match all is an intersection")
    check(matched(con, [rule("rating", "at least", 4), rule("favorite", "is", True)],
                  "any")
          == {"Alpha", "Beta", "Gamma", "Eta", "Iota", "Nu", "Delta", "Epsilon"},
          "match any is a union")
    check(len(matched(con, [])) == len(FIXTURE), "no rules means every track")

    # order and limit
    ordered = titles(con, {"name": "t", "rules": [rule("rating", "at least", 4)],
                           "sort": "rating", "desc": True})
    check(ordered[:3] == ["Alpha", "Nu", "Eta"], "sort by rating, high to low",
          str(ordered))
    check(titles(con, {"name": "t", "rules": [], "sort": "added", "desc": True,
                       "limit": 3}) == ["Nu", "Xi", "Epsilon"],
          "recently added, limited")
    check(len(titles(con, {"name": "t", "rules": [], "sort": "random"})) == len(FIXTURE),
          "random order still returns everything")

    # nonsense is skipped, never raised
    check(matched(con, [rule("no_such_field", "contains", "x"),
                        rule("artist", "contains", "duster")]) == {"Lambda", "Mu"},
          "an unknown field drops that rule only")
    spec = P.normalize_smart({"name": "x", "rules": [rule("rating", "explode", 4)]})
    check(spec["rules"][0]["op"] == "at least",
          "an unknown operator falls back to the field's first")
    check(P.normalize_smart({"sort": "sideways"})["sort"] == "artist",
          "an unknown sort key falls back")
    check(P.normalize_smart({"limit": "many"})["limit"] == 0, "a junk limit is 0")
    check(P.normalize_smart({})["name"] == "new playlist", "an empty spec is nameable")


# ---------------------------------------------------------------------------
# 2. injection — a spec is user-editable JSON that syncs between machines
# ---------------------------------------------------------------------------

def test_injection(con):
    print("\n-- injection --")
    evil = "'; DROP TABLE tracks; --"
    check(matched(con, [rule("artist", "contains", evil)]) == set(),
          "a SQL value matches nothing")
    check(con.execute("SELECT COUNT(*) c FROM tracks").fetchone()["c"] == len(FIXTURE),
          "…and the tracks table is still there")

    # A LIKE metacharacter is the user's literal text, not a wildcard.
    check(matched(con, [rule("album", "contains", "%")]) == set(),
          "% is a literal, not 'match everything'")
    check(matched(con, [rule("album", "contains", "M_.")]) == set(),
          "_ is a literal, not 'any character'")
    check(matched(con, [rule("album", "contains", "MM..FOOD")]) == {"Nu", "Xi"},
          "…and the escaping does not break an ordinary match")

    sql, params = P.smart_sql(P.normalize_smart(
        {"name": "x", "rules": [rule("artist", "is", evil)], "limit": 5}))
    check(evil not in sql, "no value is ever interpolated into the SQL text", sql)
    check(evil.casefold() in params, "…it is a bound parameter", str(params))

    # The limit is the one number that IS interpolated, so it has to be an int.
    sql, _ = P.smart_sql(P.normalize_smart({"limit": "7); DROP TABLE tracks; --"}))
    check("DROP" not in sql, "a junk limit cannot reach the SQL", sql)


# ---------------------------------------------------------------------------
# 3. the store
# ---------------------------------------------------------------------------

def test_store():
    print("\n-- store --")
    path = Path(os.environ["XDG_STATE_HOME"]) / "player" / "store-test.json"
    s = P.SmartLists(path)
    check(s.names() == [d["name"] for d in P.DEFAULT_SMART_LISTS],
          "a fresh install is seeded with the built-ins", str(s.names()))
    check(path.exists(), "…and the seed is written out")

    n = s.save({"name": "punk", "match": "all", "sort": "title",
                "rules": [rule("genre", "contains", "punk")]})
    check(n == "punk" and "punk" in s.names(), "save adds a list")
    check(P.SmartLists(path).get("punk")["rules"][0]["value"] == "punk",
          "…and it survives a reload")

    check(s.save({"name": "punk", "rules": []}) == "punk 2",
          "a colliding NAME is suffixed, not silently merged")
    check(s.save({"name": "punk", "rules": [rule("genre", "is", "punk")]},
                 old_name="punk") == "punk",
          "…but re-saving the SAME list keeps its name")
    check(s.get("punk")["rules"][0]["op"] == "is", "…with the new rules")

    check(s.save({"name": "renamed", "rules": []}, old_name="punk") == "renamed",
          "rename in place")
    check(s.get("punk") is None, "…the old name is gone")

    made = s.duplicate("renamed")
    check(made == "renamed copy", "duplicate names itself", made)
    check(s.names().index(made) == s.names().index("renamed") + 1,
          "…and lands next to its original")

    check(s.remove("renamed copy") and s.get("renamed copy") is None, "delete")
    check(s.remove("nothing here") is False, "deleting a missing list is False, not a raise")

    s.remove("unrated")
    s.remove("5 starred")
    edited = s.get("4+ starred")
    edited["limit"] = 42
    s.save(edited, old_name="4+ starred")
    check(s.restore_defaults() == 2, "restore brings back exactly what was deleted")
    check(s.get("4+ starred")["limit"] == 42,
          "…and never overwrites an edited built-in that is still there")
    check(s.restore_defaults() == 0, "restoring twice restores nothing")

    # A file that a hand edit, a bad sync merge or a future version left junk in.
    bad = Path(os.environ["XDG_STATE_HOME"]) / "player" / "bad.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{ not json at all", encoding="utf-8")
    check(P.SmartLists(bad).names() == [d["name"] for d in P.DEFAULT_SMART_LISTS],
          "an unreadable file re-seeds instead of raising")
    bad.write_text(json.dumps({"version": 99, "lists": [
        {"name": "ok", "rules": [{"field": "artist", "op": "contains", "value": "x"}]},
        "not even a dict",
        {"name": "ok", "rules": []},
        {"name": "  ", "rules": [{"field": "from the future", "op": "?"}]},
    ]}), encoding="utf-8")
    got = P.SmartLists(bad)
    check(got.names() == ["ok", "ok 2", "new playlist"],
          "junk entries are dropped and duplicate names de-collided", str(got.names()))
    check(got.get("new playlist")["rules"] == [], "an unknown field is dropped")


# ---------------------------------------------------------------------------
# 4. the built-ins, against the fixture
# ---------------------------------------------------------------------------

def test_defaults(con):
    print("\n-- the built-in lists --")
    by_name = {d["name"]: d for d in P.DEFAULT_SMART_LISTS}

    check(set(titles(con, by_name["5 starred"])) == {"Alpha", "Eta", "Nu"},
          "5 starred")
    check(set(titles(con, by_name["4+ starred"]))
          == {"Alpha", "Beta", "Gamma", "Eta", "Iota", "Nu"}, "4+ starred")
    check(set(titles(con, by_name["favorites"]))
          == {"Beta", "Delta", "Epsilon", "Iota", "Nu"}, "favorites")
    check(set(titles(con, by_name["unrated"]))
          == {"Epsilon", "Theta", "Kappa", "Mu"}, "unrated")
    check(set(titles(con, by_name["most played"]))
          == {t[0] for t in FIXTURE if t[9] > 0}, "most played excludes never-played")
    check(set(titles(con, by_name["recently played"]))
          == {t[0] for t in FIXTURE if t[12] is not None}, "recently played")
    check(titles(con, by_name["recently added"])[0] == "Nu", "recently added leads")

    # HIS request: the 4+ star list WITH the liked tracks in it.
    both = titles(con, by_name["4+ starred & liked"])
    check(set(both) == {"Alpha", "Beta", "Gamma", "Eta", "Iota", "Nu",   # 4+ stars
                        "Delta", "Epsilon"},                            # liked, under 4
          "4+ starred & liked is a UNION of the two", str(sorted(both)))
    check(len(both) == len(set(both)), "…with no track listed twice")
    check(both[0] in ("Alpha", "Nu"), "…best-rated first", str(both[:3]))
    check(by_name["4+ starred & liked"]["match"] == "any",
          "…and it is one flip away from being the intersection")


def main():
    con = build_db()
    test_rules(con)
    test_injection(con)
    test_store()
    test_defaults(con)
    print(f"\n{checks - len(fails)}/{checks} checks passed")
    if fails:
        print("\nFAILURES:")
        for f in fails:
            print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        _tmp.cleanup()
