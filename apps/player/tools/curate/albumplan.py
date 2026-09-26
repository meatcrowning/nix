#!/usr/bin/env python3
"""Plan the album view down to ONE good version of every album.

His rules (memory: library-album-policy): one version per album, the highest
quality available, remastered if a remaster exists, dated with the ORIGINAL
release date, and a proper cover. The tie-breaks he chose: the remaster's
standard tracklist (a bonus DISC is not part of the album; bonus tracks on the
same disc are fine), a regional edition that is a superset of the others wins,
romanized artist names with collaborations filed under the primary artist,
incomplete albums completed lossless, lossless capped at 16/44.1 unless
hi-res is the only lossless source, compilations kept as their own albums.

This step only PLANS. It reads the player DB (read-only), each file's
MusicBrainz ids, and MusicBrainz itself (1 req/s, cached in the curate
state dir), and writes:

    ~/.cache/library-curate/albumplan/plan.json     one entry per album group
    ~/.cache/library-curate/albumplan/report.md     the same, per artist, for him

    albumplan.py plan [--artists a..c | --artists asa-chang | --limit-artists N]
    albumplan.py report

An album group is a MusicBrainz release group: every edition, reissue and
remaster of one album. Library albums without a MusicBrainz id are matched by
a release-group search that must agree on both artist and title, and are
otherwise reported as unresolved rather than guessed at.

Run with the player's wrapped python (has mutagen + PIL):
  PY=$(grep -oE '/nix/store/[^" ]+-env/bin/python3[0-9.]*' "$(command -v player)" | head -1)
"""
import argparse
import collections
import difflib
import io
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.parse

import common as C

DB = os.path.expanduser(os.environ.get(
    "PLAYER_DB", "~/.local/share/player/library.db"))
OUT = C.STATE / "albumplan"
PLAN_JSON = OUT / "plan.json"
#: path<TAB>ffmpeg error for every file that failed a full decode
#: (ffmpeg -v error -xerror -map 0:a -f null). A damaged track counts as
#: missing: the album is re-acquired rather than kept with a hole in it.
INTEGRITY = C.STATE / "integrity.tsv"
REPORT_MD = OUT / "report.md"

LOSSLESS_CODECS = {"FLAC", "ALAC", "WAV", "AIFF", "WavPack", "APE", "TTA"}
#: a cover smaller than this on its long edge is not "a proper cover"
MIN_ART_PX = 600
VA_NAMES = {"various artists", "various", "va", "v a"}

#: edition noise stripped from a title before two titles are compared
EDITION_RE = re.compile(
    r"\s*[\(\[\{][^)\]\}]*(remaster|deluxe|edition|expanded|anniversary|bonus|"
    r"reissue|version|special|mono|stereo|\b\d{4}\b)[^)\]\}]*[\)\]\}]"
    r"|\s*[-–:]\s*(\d{4}\s+)?(remaster(ed)?|deluxe|special|expanded)\b.*$",
    re.I)
REMASTER_RE = re.compile(r"remaster", re.I)


def fold(s):
    return C.fold(s or "")


def bare_title(s):
    return fold(EDITION_RE.sub("", s or "")).strip()


def search_title(s):
    """A title for a Soulseek search: edition noise dropped, script intact."""
    return re.sub(r"\s+", " ", EDITION_RE.sub("", s or "")).strip() or (s or "")


def is_va(name):
    return fold(name) in VA_NAMES


def non_latin(s):
    for ch in s or "":
        if ch.isalpha():
            n = unicodedata.name(ch, "")
            if not n.startswith("LATIN") and "FULLWIDTH LATIN" not in n:
                return True
    return False


# --- library side ------------------------------------------------------------

def read_mbids(path):
    """(release_id, release_group_id, artist_id) from a file's own tags."""
    import mutagen
    try:
        a = mutagen.File(path)
    except Exception:
        return None, None, None
    if a is None or a.tags is None:
        return None, None, None
    t = a.tags

    def first(v):
        if not v:
            return None
        v = v[0] if isinstance(v, list) else v
        if isinstance(v, bytes):
            v = v.decode("utf-8", "replace")
        v = str(getattr(v, "text", [v])[0] if hasattr(v, "text") else v)
        return v.split("/")[0].strip() or None

    def get(*keys):
        for k in keys:
            try:
                v = t.get(k)
            except Exception:
                v = None
            if v:
                return first(v)
        return None
    rel = get("TXXX:MusicBrainz Album Id", "musicbrainz_albumid",
              "----:com.apple.iTunes:MusicBrainz Album Id")
    rg = get("TXXX:MusicBrainz Release Group Id", "musicbrainz_releasegroupid",
             "----:com.apple.iTunes:MusicBrainz Release Group Id")
    art = get("TXXX:MusicBrainz Album Artist Id", "musicbrainz_albumartistid",
              "----:com.apple.iTunes:MusicBrainz Album Artist Id",
              "TXXX:MusicBrainz Artist Id", "musicbrainz_artistid",
              "----:com.apple.iTunes:MusicBrainz Artist Id")
    return rel, rg, art


def art_px(art_src):
    """Long edge in pixels of the image the player shows for an album, or 0."""
    if not art_src:
        return 0
    from PIL import Image
    try:
        if art_src.startswith("file:"):
            with Image.open(art_src[5:]) as im:
                return max(im.size)
        if art_src.startswith("embedded:"):
            import mutagen
            m = mutagen.File(art_src[9:])
            data = None
            if m is not None and m.tags is not None:
                t = m.tags
                if hasattr(t, "getall") and t.getall("APIC"):
                    data = t.getall("APIC")[0].data
                elif "covr" in t:
                    data = bytes(t["covr"][0])
            if data is None and hasattr(m, "pictures") and m.pictures:
                data = m.pictures[0].data
            if data is None and m is not None and m.tags is not None:
                import base64
                from mutagen.flac import Picture
                b64 = m.tags.get("metadata_block_picture")
                if b64:
                    data = Picture(base64.b64decode(b64[0])).data
            if data:
                with Image.open(io.BytesIO(data)) as im:
                    return max(im.size)
    except Exception:
        return 0
    return 0


def load_damaged():
    out = {}
    try:
        for line in INTEGRITY.read_text().splitlines():
            path, _, err = line.partition("\t")
            # a broken embedded cover is not broken audio
            if err and "png @" not in err and "mjpeg @" not in err:
                out[path] = err.strip()
    except OSError:
        pass
    return out


def load_library():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    albums = {r["id"]: dict(r) for r in con.execute("SELECT * FROM albums")}
    tracks = collections.defaultdict(list)
    for r in con.execute(
            "SELECT id, album_id, path, title, artist, album, album_artist,"
            " track, disc, duration, codec, bitdepth, samplerate, year,"
            " orig_year, play_count, rating, favorite FROM tracks"):
        if r["album_id"] in albums:
            tracks[r["album_id"]].append(dict(r))
    con.close()
    return albums, tracks


def describe_album(a, ts, damaged):
    codecs = collections.Counter(t["codec"] for t in ts)
    ll = sum(1 for t in ts if (t["codec"] or "") in LOSSLESS_CODECS)
    slots = collections.Counter(((t["disc"] or 1), t["track"]) for t in ts if t["track"])
    return {
        "album_id": a["id"], "album": a["album"], "album_artist": a["album_artist"],
        "dir": os.path.dirname(ts[0]["path"]).split("/aud/", 1)[-1] if ts else None,
        "tracks": len(ts),
        "codecs": dict(codecs),
        "lossless_frac": round(ll / len(ts), 3) if ts else 0,
        "max_bitdepth": max((t["bitdepth"] or 0) for t in ts) if ts else 0,
        "max_samplerate": max((t["samplerate"] or 0) for t in ts) if ts else 0,
        "doubled_slots": sum(n - 1 for n in slots.values() if n > 1),
        "orig_year": a["orig_year"], "year": a["year"],
        "art_src": a["art_src"],
        "plays": sum((t["play_count"] or 0) for t in ts),
        "rated": sum(1 for t in ts if t["rating"] or t["favorite"]),
        "damaged": [os.path.basename(t["path"]) for t in ts if t["path"] in damaged],
    }


# --- MusicBrainz side ----------------------------------------------------------

def mb_release(rel_id):
    d = C.mb_get(f"release/{rel_id}", "inc=release-groups+artist-credits")
    return d if d and "error" not in d else None


def mb_rg(rg_id):
    d = C.mb_get(f"release-group/{rg_id}", "inc=artist-credits")
    return d if d and "error" not in d else None


def mb_rg_releases(rg_id):
    out, offset = [], 0
    while True:
        d = C.mb_get("release", f"release-group={rg_id}&inc=media+artist-credits&limit=100&offset={offset}")
        if not d or "error" in d:
            break
        out += d.get("releases", [])
        offset += 100
        if offset >= d.get("release-count", 0):
            break
    return out


def mb_tracklist(rel_id):
    d = C.mb_get(f"release/{rel_id}", "inc=recordings")
    if not d or "error" in d:
        return []
    out = []
    for m in d.get("media", []):
        for t in m.get("tracks", []):
            out.append({"disc": m.get("position", 1), "pos": t.get("position"),
                        "title": t.get("title"),
                        "len": round((t.get("length") or 0) / 1000)})
    return out


LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')


def mb_search_rg(artist, title):
    esc = lambda s: LUCENE_SPECIAL.sub(r"\\\1", s)  # noqa: E731
    q = f'releasegroup:"{esc(bare_title(title) or title)}" AND artist:"{esc(artist)}"'
    d = C.mb_get("release-group", "query=" + urllib.parse.quote(q) + "&limit=5")
    if not d or "error" in d:
        return None
    want_t, want_a = bare_title(title), fold(artist)
    for g in d.get("release-groups", []):
        if int(g.get("score", 0)) < 90:
            continue
        got_t = bare_title(g.get("title"))
        credit = " ".join(fold(c.get("name", "")) + " " + fold(c.get("artist", {}).get("sort-name", ""))
                          for c in g.get("artist-credit", []))
        if difflib.SequenceMatcher(None, want_t, got_t).ratio() < 0.88:
            continue
        a_tokens = {w for w in re.split(r"\W+", want_a) if len(w) > 2}
        if a_tokens and not any(w in credit for w in a_tokens) and want_a not in credit:
            continue
        return g["id"]
    return None


def romanized(artist_id, name, lib_spellings=(), credited=()):
    """His rule 3: artists are filed under a romanized name. MB's own name
    when it is already Latin. Otherwise a Latin spelling already in his
    library, if MusicBrainz knows it (an alias, or a name some release was
    credited as: "Asa-Chang & Junray" rather than the alias "Junrei"); failing
    that an English/Latin-script primary alias."""
    if not non_latin(name) or not artist_id:
        return name
    d = C.mb_get(f"artist/{artist_id}", "inc=aliases")
    if not d or "error" in d:
        return name
    known = {fold(al.get("name")) for al in d.get("aliases", [])}
    known |= {fold(d.get("sort-name")), fold(d.get("name"))} | {fold(c) for c in credited}
    for spelling in lib_spellings:
        if not non_latin(spelling) and fold(spelling) in known:
            return spelling
    best = None
    for al in d.get("aliases", []):
        loc = (al.get("locale") or "")
        if non_latin(al.get("name")):
            continue
        rank = (al.get("primary") is True, loc == "en", loc.endswith("Latn"))
        if best is None or rank > best[0]:
            best = (rank, al["name"])
    if best:
        return best[1]
    sort = d.get("sort-name") or ""
    return sort if sort and not non_latin(sort) and "," not in sort else name


# --- choosing the one version --------------------------------------------------

def release_shape(r):
    media = r.get("media") or []
    return len(media), sum(m.get("track-count") or 0 for m in media)


def choose_target(releases):
    """→ (standard_release, target_release, standard_discs) or (None, None, 0).

    standard = the commonest shape among official releases (a bonus disc is a
    different disc count, so it never defines the album). target = the
    largest-tracklist edition with the standard disc count (a same-disc bonus
    track or a superset regional edition is allowed), preferring the most
    recent explicit remaster of it."""
    off = [r for r in releases if (r.get("status") or "Official") == "Official"
           and release_shape(r)[1] > 0] or [r for r in releases if release_shape(r)[1] > 0]
    if not off:
        return None, None, 0
    discs = collections.Counter(release_shape(r)[0] for r in off).most_common(1)[0][0]
    same = [r for r in off if release_shape(r)[0] == discs]
    counts = collections.Counter(release_shape(r)[1] for r in same)
    std_n = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    std = min((r for r in same if release_shape(r)[1] == std_n),
              key=lambda r: r.get("date") or "9999")
    top_n = max(release_shape(r)[1] for r in same)
    top = [r for r in same if release_shape(r)[1] == top_n]

    def rank(r):
        rem = bool(REMASTER_RE.search((r.get("disambiguation") or "") + " " + (r.get("title") or "")))
        return (rem, r.get("date") or "")
    target = max(top, key=rank)
    return std, target, discs


BRACKETS_RE = re.compile(r"\s*[\(\[\{][^)\]\}]*[\)\]\}]|\s+[-–]\s.*$")


def track_key(title):
    """A track title reduced for matching: every bracketed aside and any
    " - suffix" dropped ("The Squeeze (LTD CD only)" == "The Squeeze-",
    "Out of Control" == "Out of Control (Back for More)")."""
    k = fold(BRACKETS_RE.sub("", title or ""))
    return re.sub(r"[^\w]+", " ", k).strip() or fold(title)


def match_tracks(lib_tracks, std_tracks):
    """Which standard tracks the library copy has. Title first (asides
    stripped), then position+duration."""
    have = {}
    by_title = collections.defaultdict(list)
    for t in lib_tracks:
        by_title[track_key(t["title"])].append(t)
    missing = []
    for s in std_tracks:
        k = track_key(s["title"])
        hit = by_title.get(k)
        if not hit and k:
            close = difflib.get_close_matches(k, by_title.keys(), n=1, cutoff=0.85)
            hit = by_title.get(close[0]) if close else None
        if not hit and s["len"]:
            hit = [t for t in lib_tracks if t["track"] == s["pos"]
                   and (t["disc"] or 1) == s["disc"]
                   and abs((t["duration"] or 0) - s["len"]) <= 3]
        if hit:
            have[(s["disc"], s["pos"])] = hit[0]["id"]
        else:
            missing.append(f'{s["disc"]}-{s["pos"]} {s["title"]}')
    return have, missing


def score_copy(d):
    return (d["complete"], d["lossless_frac"] >= 1, d["remaster"], d["tracks"] - d["doubled_slots"],
            d["lossless_frac"], d["plays"])


def plan_group(key, members, rg, releases, lib_artist_id, lib_spellings=()):
    """members: list of described library albums in this group."""
    entry = {"key": key, "rg": rg["id"] if rg else None, "members": members,
             "actions": [], "notes": []}
    if not rg:
        entry["title"] = members[0]["album"]
        entry["artist"] = members[0]["album_artist"]
        entry["notes"].append("no MusicBrainz match — completeness and edition unknown")
        std_tracks, target = [], None
    else:
        entry["title"] = rg.get("title")
        credit = rg.get("artist-credit") or []
        primary = credit[0]["artist"] if credit else {}
        entry["artist"] = credit[0]["name"] if credit else members[0]["album_artist"]
        entry["first_date"] = rg.get("first-release-date") or None
        entry["type"] = rg.get("primary-type")
        std, target, discs = choose_target(releases)
        std_tracks = mb_tracklist(std["id"]) if std else []
        if target:
            entry["target"] = {
                "release": target["id"], "title": target.get("title"),
                "date": target.get("date"), "country": target.get("country"),
                "disambiguation": target.get("disambiguation") or "",
                "shape": release_shape(target),
                "remaster": bool(REMASTER_RE.search((target.get("disambiguation") or "") + " " + (target.get("title") or ""))),
            }
            entry["standard"] = {"release": std["id"], "shape": release_shape(std)}
        credited = {c.get("name") for r in releases for c in (r.get("artist-credit") or [])[:1]}
        want_artist = entry["artist"] if is_va(entry["artist"]) else romanized(
            primary.get("id") or lib_artist_id, primary.get("name") or entry["artist"],
            lib_spellings, credited)
        entry["want_album_artist"] = want_artist

    for m in members:
        m_tracks = m.pop("_tracks")
        broken = set(m["damaged"])
        m_tracks = [t for t in m_tracks if os.path.basename(t["path"]) not in broken]
        if std_tracks:
            have, missing = match_tracks(m_tracks, std_tracks)
            m["missing"] = missing
            m["complete"] = not missing
        else:
            m["missing"] = []
            m["complete"] = False if broken else None
        m["remaster"] = bool(REMASTER_RE.search(m["album"] or "") or REMASTER_RE.search(m["dir"] or ""))
        m["art_px"] = art_px(m.pop("art_src"))

    members.sort(key=score_copy, reverse=True)
    keep = members[0]
    entry["keep"] = keep["album_id"]
    for other in members[1:]:
        entry["actions"].append({"do": "remove_copy", "album_id": other["album_id"],
                                 "dir": other["dir"], "tracks": other["tracks"],
                                 "plays": other["plays"], "rated": other["rated"]})
    if keep["doubled_slots"]:
        entry["actions"].append({"do": "dedupe_tracks", "album_id": keep["album_id"],
                                 "n": keep["doubled_slots"]})
    need_full = keep["complete"] is False or keep["lossless_frac"] < 1
    if need_full and (rg or keep["damaged"]):
        why = []
        if keep["damaged"]:
            why.append(f'{len(keep["damaged"])} damaged')
        if keep["missing"]:
            why.append(f'missing {len(keep["missing"])} of {len(std_tracks)}')
        if keep["lossless_frac"] < 1:
            why.append("lossy" if keep["lossless_frac"] == 0 else f'{keep["lossless_frac"]:.0%} lossless')
        entry["actions"].append({"do": "acquire", "why": ", ".join(why),
                                 "search": f'{entry.get("want_album_artist") or entry["artist"]} {search_title(entry["title"])}',
                                 "prefer_remaster": bool(entry.get("target", {}).get("remaster"))})
    elif rg and entry.get("target", {}).get("remaster") and not keep["remaster"]:
        entry["notes"].append("a remaster exists; the kept copy is not it")
        entry["actions"].append({"do": "acquire", "why": "remaster available",
                                 "search": f'{entry.get("want_album_artist") or entry["artist"]} {search_title(entry["title"])} remaster',
                                 "prefer_remaster": True})
    fd = entry.get("first_date")
    if fd and keep["orig_year"] != int(fd[:4]):
        entry["actions"].append({"do": "retag", "album_id": keep["album_id"],
                                 "set": {"originaldate": fd},
                                 "was": keep["orig_year"]})
    want = entry.get("want_album_artist")
    if want and fold(want) != fold(keep["album_artist"]):
        entry["actions"].append({"do": "retag", "album_id": keep["album_id"],
                                 "set": {"albumartist": want},
                                 "was": keep["album_artist"]})
    if keep["art_px"] < MIN_ART_PX:
        entry["actions"].append({"do": "art", "album_id": keep["album_id"],
                                 "have_px": keep["art_px"],
                                 "release": entry.get("target", {}).get("release"),
                                 "rg": entry["rg"]})
    return entry


# --- commands --------------------------------------------------------------------

def select_artists(albums, args):
    names = sorted({a["album_artist"] or "" for a in albums.values()}, key=lambda s: fold(s))
    if args.artists:
        if ".." in args.artists:
            lo, _, hi = args.artists.partition("..")
            lo, hi = fold(lo), fold(hi) + "￿"
            names = [n for n in names if lo <= fold(n) <= hi]
        else:
            names = [n for n in names if fold(n).startswith(fold(args.artists))]
    if args.limit_artists:
        names = names[:args.limit_artists]
    return set(names)


def cmd_plan(args):
    OUT.mkdir(parents=True, exist_ok=True)
    albums, tracks = load_library()
    damaged = load_damaged()
    chosen = select_artists(albums, args)
    todo = [a for a in albums.values() if (a["album_artist"] or "") in chosen and tracks.get(a["id"])]
    print(f"{len(todo)} albums across {len(chosen)} album artists", flush=True)

    # 1. resolve each library album to a release group
    groups = collections.defaultdict(list)
    artist_of = {}
    resolved = []
    t0 = time.time()
    for i, a in enumerate(sorted(todo, key=lambda a: fold(a["album_artist"]))):
        ts = tracks[a["id"]]
        ids = collections.Counter()
        rels = collections.Counter()
        arts = collections.Counter()
        for t in ts[:6]:
            rel, rgid, art = read_mbids(t["path"])
            if rgid:
                ids[rgid] += 1
            if rel:
                rels[rel] += 1
            if art:
                arts[art] += 1
        rgid = ids.most_common(1)[0][0] if ids else None
        if not rgid and rels:
            r = mb_release(rels.most_common(1)[0][0])
            rgid = (r or {}).get("release-group", {}).get("id")
        how = "tag" if rgid else None
        if not rgid and not is_va(a["album_artist"]):
            rgid = mb_search_rg(a["album_artist"] or ts[0]["artist"] or "", a["album"] or "")
            how = "search" if rgid else None
        d = describe_album(a, ts, damaged)
        d["_tracks"] = ts
        resolved.append((a, d, rgid, how, arts))
        if (i + 1) % 50 == 0:
            print(f"  resolved {i+1}/{len(todo)} ({time.time()-t0:.0f}s)", flush=True)

    # A searched match is only as good as its artist. Casiopea's 1979
    # self-titled album found a 2016 "Casiopea" by an Argentinian band: the
    # search agreed on both names. So a searched group must credit the artist
    # id his tagged albums by the same album artist carry, and cannot have
    # first come out after his own copy's date.
    lib_artist_ids = collections.defaultdict(collections.Counter)
    spellings = collections.defaultdict(collections.Counter)
    for a, d, rgid, how, arts in resolved:
        if how == "tag" and arts:
            lib_artist_ids[fold(a["album_artist"])][arts.most_common(1)[0][0]] += 1
    for a, d, rgid, how, arts in resolved:
        if how == "search":
            rg = mb_rg(rgid) or {}
            ids = {c.get("artist", {}).get("id") for c in rg.get("artist-credit") or []}
            known = lib_artist_ids.get(fold(a["album_artist"]))
            first = (rg.get("first-release-date") or "")[:4]
            mine = a.get("orig_year") or a.get("year")
            if (known and not ids & set(known)) or (first and mine and int(first) > int(mine) + 1):
                d.setdefault("notes", []).append(f"rejected search match {rgid} ({first})")
                rgid = None
        key = rgid or f'lib:{fold(a["album_artist"])}|{bare_title(a["album"])}'
        groups[key].append(d)
        if arts:
            artist_of[key] = arts.most_common(1)[0][0]

    # Which spellings he already files each MB artist under, across ALL of
    # that artist's albums (his "Junray" lives on one album, 巡礼 on another).
    rgs = {}
    for key, members in groups.items():
        rg = mb_rg(key) if not key.startswith("lib:") else None
        rgs[key] = rg
        aid = artist_of.get(key)
        if not aid and rg and rg.get("artist-credit"):
            aid = rg["artist-credit"][0].get("artist", {}).get("id")
        artist_of[key] = aid
        for m in members:
            spellings[aid][m["album_artist"]] += m["tracks"]

    # 2. plan each group
    plan = []
    for j, (key, members) in enumerate(sorted(groups.items(), key=lambda kv: fold(kv[1][0]["album_artist"]))):
        rg = rgs[key]
        releases = mb_rg_releases(key) if rg else []
        aid = artist_of.get(key)
        lib_sp = [n for n, _ in spellings.get(aid, collections.Counter()).most_common()]
        lib_sp += [m["album_artist"] for m in members if m["album_artist"] not in lib_sp]
        plan.append(plan_group(key, members, rg, releases or [], aid, lib_sp))
        if (j + 1) % 50 == 0:
            print(f"  planned {j+1}/{len(groups)} ({time.time()-t0:.0f}s)", flush=True)
    PLAN_JSON.write_text(json.dumps(plan, ensure_ascii=False, indent=1))
    print(f"wrote {PLAN_JSON} ({len(plan)} album groups)")
    cmd_report(args)


def cmd_report(_args):
    plan = json.loads(PLAN_JSON.read_text())
    counts = collections.Counter()
    by_artist = collections.defaultdict(list)
    for e in plan:
        by_artist[fold(e.get("want_album_artist") or e["artist"] or "?")].append(e)
        for a in e["actions"]:
            counts[a["do"]] += 1
        if not e["rg"]:
            counts["unresolved"] += 1
        if not e["actions"]:
            counts["already_right"] += 1
    lines = ["# Album plan", "",
             f"{len(plan)} albums. " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())), ""]
    for artist in sorted(by_artist):
        names = collections.Counter(e.get("want_album_artist") or e["artist"] for e in by_artist[artist])
        lines.append(f"## {names.most_common(1)[0][0]}")
        for e in sorted(by_artist[artist], key=lambda e: e.get("first_date") or "9999"):
            keep = next(m for m in e["members"] if m["album_id"] == e["keep"])
            yr = (e.get("first_date") or "????")[:4]
            tgt = e.get("target")
            head = f'- **{e["title"]}** ({yr})'
            if tgt:
                head += f' — target: {tgt["title"]} {tgt["date"] or ""} {tgt["country"] or ""} {tgt["shape"][1]} tracks' + (" [remaster]" if tgt["remaster"] else "")
            lines.append(head)
            cod = "/".join(f"{k}×{v}" for k, v in keep["codecs"].items())
            lines.append(f'  - keep `{keep["dir"]}` — {keep["tracks"]} tracks, {cod}, art {keep["art_px"]}px'
                         + ("" if keep["complete"] is not False else f', missing {len(keep["missing"])}: ' + "; ".join(keep["missing"][:6]) + ("…" if len(keep["missing"]) > 6 else "")))
            for a in e["actions"]:
                if a["do"] == "remove_copy":
                    lines.append(f'  - remove `{a["dir"]}` ({a["tracks"]} tracks' + (f', {a["plays"]} plays carried' if a["plays"] else "") + (f', {a["rated"]} rated carried' if a["rated"] else "") + ")")
                elif a["do"] == "acquire":
                    lines.append(f'  - acquire lossless ({a["why"]}) — search "{a["search"]}"')
                elif a["do"] == "retag":
                    (k, v), = a["set"].items()
                    lines.append(f'  - set {k} = {v} (was {a["was"]})')
                elif a["do"] == "art":
                    lines.append(f'  - cover: fetch ({a["have_px"]}px now)')
                elif a["do"] == "dedupe_tracks":
                    lines.append(f'  - remove {a["n"]} doubled track(s) inside the album')
            for n in e["notes"]:
                lines.append(f"  - note: {n}")
        lines.append("")
    REPORT_MD.write_text("\n".join(lines))
    print(f"wrote {REPORT_MD}")
    print(", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "report"])
    ap.add_argument("--artists", help="album-artist prefix (asa-chang) or fold-range (a..c)")
    ap.add_argument("--limit-artists", type=int)
    args = ap.parse_args()
    {"plan": cmd_plan, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
