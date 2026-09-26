#!/usr/bin/env python3
"""Carry out albumplan.py's plan, one batch of artists at a time.

    albumapply.py apply  --artists a..c            dry run: say what would happen
    albumapply.py apply  --artists a..c --go       do it
    albumapply.py settle [--go]                    finish acquisitions that landed
    albumapply.py status                           pending / done / failed jobs

Per album group, in this order:

  remove_copy    carry plays, ratings and favourites onto the kept copy's
                 matching tracks, then move the other copy's files to
                 aud-removed/duplicates/ and drop their rows
  dedupe_tracks  the same inside one album: a slot held twice keeps its best file
  acquire        search slskd for a lossless edition whose tracks match the
                 MusicBrainz tracklist by duration, and queue it. The swap
                 happens in `settle`, once every file has landed, decodes, and
                 matches: stats carried, the old files moved to
                 aud-removed/replaced/, the new ones dated and covered
  retag          ORIGINALDATE (the album view shows it) and the romanized
                 album artist, through tagtool (atomic, undoable); a retagged
                 album moves to aud/<album artist>/ so one artist is one folder
  art            the release group's Cover Art Archive front, when it is bigger
                 than what the album shows now and at least 600px

A group with an acquisition pending gets its retag and art in `settle`, on
the new files. Nothing is deleted: removed files go to aud-removed/ on the
library drive (his rule 7), with the same relative path, and the database is
backed up before a batch writes to it.

Run with the player's wrapped python:
  PY=$(grep -oE '/nix/store/[^" ]+-env/bin/python3[0-9.]*' "$(command -v player)" | head -1)
"""
import argparse
import collections
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import common as C
import albumplan as P

TOOLS = Path(__file__).resolve().parent.parent
ROOT = Path(C.ROOT)
REMOVED = Path(C.REMOVED)
DB = P.DB
JOBS = P.OUT / "jobs.json"
LOG = P.OUT / "apply.log"
DL = Path.home() / ".local/share/slskd/downloads"
SLSKD = "http://127.0.0.1:5030/api/v0"
KEY_FILE = Path.home() / ".secrets/slskd-api-key"

LOSSLESS_EXTS = {".flac", ".wav", ".aiff", ".aif", ".ape", ".wv", ".m4a"}
AUDIO_EXTS = LOSSLESS_EXTS | {".mp3", ".ogg", ".opus", ".mpc", ".wma", ".aac"}
COVER_RE = re.compile(r"^(cover|folder|front|albumart.*)\.(jpe?g|png|webp)$", re.I)
DISC_RE = re.compile(r"^(cd|disc|disk|digital media)\s*\d+$", re.I)
FAILED_STATES = ("Rejected", "Errored", "TimedOut", "Cancelled", "Failed")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tagtool = _load("tagtool", TOOLS / "tagtool.py")
_player_add = None


def player_add():
    global _player_add
    if _player_add is None:
        _player_add = _load("player_add", TOOLS / "player-add.py")
    return _player_add


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# --- database ----------------------------------------------------------------

def db():
    return sqlite3.connect(DB, timeout=30)


def backup_db(tag):
    dest = REMOVED / "db-backups" / f"library.db.{tag}-{time.strftime('%Y%m%d-%H%M%S')}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    s, d = db(), sqlite3.connect(dest)
    s.backup(d)
    d.close()
    s.close()
    log(f"db backup {dest}")


def album_tracks(con, album_id):
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(
        "SELECT id, path, title, track, disc, duration, codec, bitdepth,"
        " samplerate, play_count, last_played, rating, favorite FROM tracks"
        " WHERE album_id=?", (album_id,))]


def carry_stats(con, src_rows, dst_rows):
    """Plays add up, last_played is the newest, a rating/favourite the kept
    copy lacks is taken from the other. Matched by track title."""
    by_key = collections.defaultdict(list)
    for d in dst_rows:
        by_key[P.track_key(d["title"])].append(d)
    carried = 0
    for s in src_rows:
        if not (s["play_count"] or s["rating"] or s["favorite"]):
            continue
        hit = by_key.get(P.track_key(s["title"]))
        if not hit:
            log(f"  ! no match to carry stats of {os.path.basename(s['path'])}")
            continue
        con.execute(
            "UPDATE tracks SET play_count=COALESCE(play_count,0)+?,"
            " last_played=MAX(COALESCE(last_played,0),COALESCE(?,0)),"
            " rating=COALESCE(rating,?), favorite=MAX(COALESCE(favorite,0),?)"
            " WHERE id=?",
            (s["play_count"] or 0, s["last_played"], s["rating"], s["favorite"] or 0,
             hit[0]["id"]))
        carried += 1
    return carried


def move_out(con, paths, category):
    """Files to aud-removed/<category>/<path under aud>, rows dropped."""
    n = 0
    for p in paths:
        p = Path(p)
        try:
            rel = p.relative_to(ROOT)
        except ValueError:
            continue
        dest = REMOVED / category / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest = dest.with_name(f"{dest.stem}.{int(time.time())}{dest.suffix}")
        if p.exists():
            shutil.move(str(p), str(dest))
        ids = [r[0] for r in con.execute("SELECT id FROM tracks WHERE path=?", (str(p),))]
        con.executemany("DELETE FROM lyrics WHERE track_id=?", [(i,) for i in ids])
        con.executemany("DELETE FROM tracks WHERE id=?", [(i,) for i in ids])
        n += 1
    con.commit()
    return n


def prune_dirs(paths):
    """Remove album folders a move emptied (a lone cover.jpg counts as empty
    only once no audio is left)."""
    for d in sorted({Path(p).parent for p in paths}, key=lambda d: -len(d.parts)):
        while d != ROOT and ROOT in d.parents:
            try:
                left = list(d.iterdir())
            except OSError:
                break
            if any(f.suffix.lower() in AUDIO_EXTS or f.is_dir() for f in left):
                break
            for f in left:
                dest = REMOVED / "leftovers" / f.relative_to(ROOT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dest))
            d.rmdir()
            d = d.parent


def drop_orphan_albums(con):
    con.execute("DELETE FROM albums WHERE id NOT IN"
                " (SELECT DISTINCT album_id FROM tracks WHERE album_id IS NOT NULL)")
    con.commit()


# --- steps -------------------------------------------------------------------

def step_remove_copy(con, e, a, go):
    keep = album_tracks(con, e["keep"])
    other = album_tracks(con, a["album_id"])
    log(f"  remove copy `{a['dir']}` ({len(other)} tracks) -> aud-removed/duplicates")
    if not go:
        return
    carried = carry_stats(con, other, keep)
    con.commit()
    n = move_out(con, [t["path"] for t in other], "duplicates")
    prune_dirs([t["path"] for t in other])
    log(f"    moved {n}, carried stats for {carried}")


def quality(t):
    lossless = (t["codec"] or "") in P.LOSSLESS_CODECS
    return (lossless, (t["bitdepth"] or 0) <= 16, t["samplerate"] or 0, os.path.getsize(t["path"]) if os.path.exists(t["path"]) else 0)


def step_dedupe(con, e, a, go):
    rows = album_tracks(con, e["keep"])
    losers = []
    for x, y in P.doubled_tracks(rows):
        keep, lose = sorted((x, y), key=quality, reverse=True)
        losers.append((keep, lose))
    log(f"  dedupe {len(losers)} doubled track(s) in `{e['members'][0]['dir']}`")
    if not go or not losers:
        return
    for keep, lose in losers:
        carry_stats(con, [lose], [keep])
    con.commit()
    move_out(con, [lose["path"] for _, lose in losers], "duplicates")


def retag_paths(paths, tags, go, label):
    if not tags:
        return True
    r = tagtool.run({"op": "set", "paths": [str(p) for p in paths], "tags": tags,
                     "apply": bool(go)})
    if not r.get("ok"):
        log(f"  ! retag {label}: {r.get('error')}")
        return False
    log(f"  retag {label}: {tags}" + ("" if go else " (dry run)"))
    return True


def move_album_dir(con, paths, album_artist, go):
    """One artist, one folder: an album retagged to a new album artist moves
    to aud/<album artist>/<its folder name>, database paths with it."""
    if not paths:
        return paths
    src = Path(paths[0]).parent
    if any(Path(p).parent != src for p in paths):
        return paths          # a split album is the reorg pipeline's job
    pa = player_add()
    dest = ROOT / pa.safe_name(album_artist, "Unknown Artist") / src.name
    if P.fold(str(dest)) == P.fold(str(src)):
        return paths
    if dest.exists() and any(dest.iterdir()):
        clash = [p for p in paths if (dest / Path(p).name).exists()]
        if clash:
            log(f"  ! not moving `{src}` -> `{dest}`: {len(clash)} name clash(es)")
            return paths
    log(f"  move `{src.relative_to(ROOT)}` -> `{dest.relative_to(ROOT)}`")
    if not go:
        return paths
    dest.mkdir(parents=True, exist_ok=True)
    new = []
    for f in sorted(src.iterdir()):
        target = dest / f.name
        if target.exists():
            continue
        shutil.move(str(f), str(target))
        con.execute("UPDATE tracks SET path=? WHERE path=?", (str(target), str(f)))
        if str(f) in paths:
            new.append(str(target))
    con.commit()
    prune_dirs([str(src / "x")])
    return new or paths


def step_retag(con, e, go, paths=None):
    keep_rows = album_tracks(con, e["keep"]) if paths is None else None
    paths = paths if paths is not None else [t["path"] for t in keep_rows]
    tags = {}
    for a in e["actions"]:
        if a["do"] == "retag":
            tags.update(a["set"])
    if not tags:
        return paths
    want_aa = tags.pop("albumartist", None)
    if tags:
        retag_paths(paths, tags, go, "originaldate")
    if want_aa:
        if retag_paths(paths, {"albumartist": want_aa}, go, "album artist"):
            paths = move_album_dir(con, paths, want_aa, go)
    return paths


def cover_url(e):
    if e.get("rg"):
        return f"https://coverartarchive.org/release-group/{e['rg']}/front-1200"
    return None


def step_art(con, e, go, paths=None, have_px=None):
    paths = paths if paths is not None else [t["path"] for t in album_tracks(con, e["keep"])]
    if not paths:
        return
    url = cover_url(e)
    r = tagtool.run({"op": "art", "paths": paths, "art": {"url": url}}) if url else {}
    if not r.get("ok"):
        # no release-group front: tagtool's own order (the release's CAA
        # entry, iTunes, Discogs), still subject to the size check below
        r = tagtool.run({"op": "art", "paths": paths, "art": {"source": "auto"}})
    if not r.get("ok"):
        log(f"  cover: {r.get('error')}")
        return
    w = max(r.get("image", {}).get("width") or 0, r.get("image", {}).get("height") or 0)
    have = have_px if have_px is not None else next(
        (a["have_px"] for a in e["actions"] if a["do"] == "art"), 0)
    if w < P.MIN_ART_PX or w <= have:
        log(f"  cover: best found is {w}px, album has {have}px — kept")
        return
    log(f"  cover: {w}px from {r.get('source') or 'the archive'} (was {have}px)" + ("" if go else " (dry run)"))
    if go:
        r = tagtool.run({"op": "art", "plan_token": r["plan_token"], "apply": True})
        if not r.get("ok"):
            log(f"  ! cover write: {r.get('error')}")


# --- acquisition ---------------------------------------------------------------

def api(method, path, body=None, timeout=30):
    key = KEY_FILE.read_text().strip()
    req = urllib.request.Request(SLSKD + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-API-Key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        raw = f.read()
    return json.loads(raw) if raw else None


def ensure_slskd():
    try:
        if api("GET", "/application")["server"]["isLoggedIn"]:
            return True
    except Exception:
        pass
    subprocess.run(["systemctl", "--user", "start", "slskd"], check=False)
    for _ in range(30):
        time.sleep(2)
        try:
            if api("GET", "/application")["server"]["isLoggedIn"]:
                return True
        except Exception:
            continue
    return False


def search(text, wait=90):
    s = api("POST", "/searches", {"searchText": text})
    t0 = time.time()
    while time.time() - t0 < wait:
        st = api("GET", f"/searches/{s['id']}")
        if "Completed" in (st.get("state") or ""):
            break
        time.sleep(2)
    return api("GET", f"/searches/{s['id']}/responses") or []


def candidate_folders(responses):
    """(user, folder) -> files, a disc folder (CD1, Disc 2) folded into its
    album folder."""
    out = collections.defaultdict(list)
    meta = {}
    for r in responses:
        for f in r.get("files", []):
            fn = f["filename"].replace("\\", "/")
            parts = fn.split("/")
            folder = "/".join(parts[:-1])
            if len(parts) > 2 and DISC_RE.match(parts[-2]):
                folder = "/".join(parts[:-2])
            out[(r["username"], folder)].append(f)
            meta[r["username"]] = (r.get("hasFreeUploadSlot"), r.get("queueLength") or 0)
    return out, meta


def durations_match(files, ref):
    """Every reference track length (s) finds a distinct file within 3s."""
    lens = sorted((f.get("length") or 0) for f in files)
    for want in ref:
        if not want:
            continue
        best = None
        for i, got in enumerate(lens):
            if abs(got - want) <= 3:
                best = i
                break
        if best is None:
            return False
        lens.pop(best)
    return True


def pick(responses, ref, prefer_remaster):
    folders, meta = candidate_folders(responses)
    cands = []
    for (user, folder), files in folders.items():
        audio = [f for f in files if Path(f["filename"].replace("\\", "/")).suffix.lower() in AUDIO_EXTS
                 and "_temp" not in f["filename"]]
        if not audio:
            continue
        exts = {Path(f["filename"].replace("\\", "/")).suffix.lower() for f in audio}
        if not exts <= LOSSLESS_EXTS:
            continue
        # an .m4a is only lossless when it reports a bit depth (ALAC)
        if ".m4a" in exts and not all(f.get("bitDepth") for f in audio if f["filename"].lower().endswith(".m4a")):
            continue
        if len(audio) < len([x for x in ref if x]) or not durations_match(audio, ref):
            continue
        hires = any((f.get("bitDepth") or 16) > 16 or (f.get("sampleRate") or 44100) > 48000 for f in audio)
        free, q = meta[user]
        covers = [f for f in files if COVER_RE.match(Path(f["filename"].replace("\\", "/")).name)]
        rem = bool(P.REMASTER_RE.search(folder))
        cands.append({
            "user": user, "folder": folder,
            "files": [{"filename": f["filename"], "size": f["size"]} for f in audio + covers[:1]],
            "hires": hires, "free": bool(free), "queue": q, "remaster": rem,
            "rank": (not hires, rem if prefer_remaster else False, bool(free), -q, bool(covers)),
        })
    cands.sort(key=lambda c: c["rank"], reverse=True)
    return cands


def reference_lengths(e, keep):
    std = e.get("standard", {}).get("release")
    if std:
        return [t["len"] for t in P.mb_tracklist(std)]
    return [round(t["duration"] or 0) for t in keep]


def step_acquire(con, e, act, go, jobs):
    key = e["key"]
    if key in jobs and jobs[key]["status"] in ("queued", "done"):
        log(f"  acquire: already {jobs[key]['status']}")
        return True
    keep = album_tracks(con, e["keep"])
    ref = reference_lengths(e, keep)
    log(f"  acquire ({act['why']}): search \"{act['search']}\"")
    if not go:
        return True
    try:
        resp = search(act["search"])
    except Exception as ex:
        log(f"  ! search failed: {ex}")
        return False
    cands = pick(resp, ref, act.get("prefer_remaster"))
    if not cands:
        log(f"  no lossless edition matching the tracklist ({len(resp)} peers answered) — kept as is")
        jobs[key] = {"status": "unavailable", "when": time.time(), "search": act["search"]}
        return False
    c = cands[0]
    try:
        api("POST", f"/transfers/downloads/{urllib.request.quote(c['user'])}", c["files"], timeout=90)
    except Exception as ex:
        log(f"  ! enqueue from {c['user']} failed: {ex}")
        jobs[key] = {"status": "failed", "when": time.time(), "why": str(ex)}
        return False
    old = [t["path"] for m in e["members"] for t in album_tracks(con, m["album_id"])]
    jobs[key] = {
        "status": "queued", "queued_at": time.time(), "title": e["title"],
        "artist": e.get("want_album_artist") or e["artist"], "user": c["user"],
        "folder": c["folder"], "files": c["files"], "old": old, "ref": ref,
        "alternates": cands[1:4], "entry": {k: e[k] for k in ("key", "rg", "actions", "first_date", "want_album_artist", "title") if k in e},
    }
    log(f"  queued {len(c['files'])} files from {c['user']}: {c['folder'].rsplit('/', 1)[-1]}"
        + (" [hi-res]" if c["hires"] else "") + (" [remaster]" if c["remaster"] else ""))
    return True


def load_jobs():
    try:
        return json.loads(JOBS.read_text())
    except (OSError, ValueError):
        return {}


def save_jobs(jobs):
    JOBS.write_text(json.dumps(jobs, ensure_ascii=False, indent=1))


# --- commands --------------------------------------------------------------------

def in_batch(e, args):
    name = P.fold(e.get("want_album_artist") or e.get("artist") or "")
    names = {name} | {P.fold(m["album_artist"]) for m in e["members"]}
    if args.artists and ".." in args.artists:
        lo, _, hi = args.artists.partition("..")
        return any(P.fold(lo) <= n <= P.fold(hi) + "￿" for n in names)
    if args.artists:
        return any(n.startswith(P.fold(args.artists)) for n in names)
    return True


def cmd_apply(args):
    plan = json.loads(P.PLAN_JSON.read_text())
    steps = set(args.steps.split(","))
    batch = [e for e in plan if in_batch(e, args) and e["actions"]]
    log(f"apply {'GO' if args.go else 'dry run'}: {len(batch)} album groups, steps {sorted(steps)}")
    if args.go:
        backup_db("albumapply")
        if "acquire" in steps and not ensure_slskd():
            log("! slskd is not logged in — acquisitions skipped")
            steps.discard("acquire")
    jobs = load_jobs()
    con = db()
    for e in batch:
        log(f"{e.get('want_album_artist') or e['artist']} — {e['title']}")
        pending = False
        for a in e["actions"]:
            if a["do"] == "remove_copy" and "remove" in steps:
                step_remove_copy(con, e, a, args.go)
        for a in e["actions"]:
            if a["do"] == "dedupe_tracks" and "remove" in steps:
                step_dedupe(con, e, a, args.go)
        for a in e["actions"]:
            if a["do"] == "acquire" and "acquire" in steps:
                pending = step_acquire(con, e, a, args.go, jobs) and args.go
                save_jobs(jobs)
        if pending:
            continue          # retag + cover happen in settle, on the new files
        paths = None
        if "retag" in steps:
            paths = step_retag(con, e, args.go)
        if "art" in steps and any(a["do"] == "art" for a in e["actions"]):
            step_art(con, e, args.go, paths)
    if args.go:
        drop_orphan_albums(con)
    con.close()


def transfers_for(user):
    try:
        data = api("GET", f"/transfers/downloads/{urllib.request.quote(user)}")
    except urllib.error.HTTPError:
        return {}
    out = {}
    for d in (data or {}).get("directories", []):
        for f in d.get("files", []):
            out[f["filename"]] = f
    return out


def landed_paths(con, job):
    """Where each downloaded file is now: imported into aud (a DB row with its
    sanitized name added after the job was queued) or still in the downloads
    dir (the importer skipped it: the old copy held the same name)."""
    pa = player_add()
    imported, waiting = [], []
    for f in job["files"]:
        base = f["filename"].replace("\\", "/").rsplit("/", 1)[-1]
        if Path(base).suffix.lower() not in AUDIO_EXTS:
            continue
        safe = pa.safe_file(base)
        row = con.execute(
            "SELECT path FROM tracks WHERE (path LIKE ? OR path LIKE ?) AND added_at>=?"
            " ORDER BY added_at DESC LIMIT 1",
            ("%/" + safe, "%/" + base, job["queued_at"] - 5)).fetchone()
        if row:
            imported.append(row[0])
            continue
        hits = list(DL.rglob(base))
        if hits:
            waiting.append(str(hits[0]))
    return imported, waiting


def decodes(path):
    r = subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", path, "-map", "0:a",
                        "-f", "null", "-"], capture_output=True, text=True)
    return r.returncode == 0 and not r.stderr.strip()


def settle_one(con, key, job, go):
    tr = transfers_for(job["user"])
    states = [tr.get(f["filename"], {}).get("state", "") for f in job["files"]]
    if any(any(s in st for s in FAILED_STATES) for st in states):
        log(f"{job['artist']} — {job['title']}: transfer failed from {job['user']}")
        if go:
            alt = (job.get("alternates") or [None])[0]
            if alt:
                try:
                    api("POST", f"/transfers/downloads/{urllib.request.quote(alt['user'])}", alt["files"], timeout=90)
                    log(f"  requeued from {alt['user']}")
                    job.update({"user": alt["user"], "folder": alt["folder"], "files": alt["files"],
                                "alternates": job["alternates"][1:], "queued_at": time.time()})
                    return
                except Exception as ex:
                    log(f"  ! requeue failed: {ex}")
            job["status"] = "failed"
        return
    if not all("Completed, Succeeded" in st for st in states):
        return
    imported, waiting = landed_paths(con, job)
    n_audio = sum(1 for f in job["files"] if Path(f["filename"].replace("\\", "/")).suffix.lower() in AUDIO_EXTS)
    if len(imported) + len(waiting) < n_audio:
        if time.time() - job["queued_at"] < 600 or waiting:
            return        # the importer has not caught up yet
    if waiting and time.time() - max(os.path.getmtime(w) for w in waiting) < 300:
        return            # give the AutoScanner its pass first
    new = imported + waiting
    log(f"{job['artist']} — {job['title']}: landed ({len(imported)} imported, {len(waiting)} waiting on the old copy)")
    bad = [p for p in new if not decodes(p)]
    lens = []
    for p in new:
        try:
            import mutagen
            lens.append({"length": (mutagen.File(p).info.length)})
        except Exception:
            pass
    if bad or not durations_match(lens, job["ref"]):
        log(f"  ! new copy rejected: {len(bad)} undecodable, tracklist match {durations_match(lens, job['ref'])} — old copy kept")
        if go:
            job["status"] = "rejected"
            for p in bad:
                move_out(con, [p], "rejected-downloads") if p.startswith(str(ROOT)) else None
        return
    if not go:
        log("  (dry run) would swap in the new copy")
        return
    old = [p for p in job["old"] if p not in new and os.path.exists(p)]
    con.row_factory = sqlite3.Row
    old_rows = [dict(r) for p in old for r in con.execute(
        "SELECT id, path, title, play_count, last_played, rating, favorite FROM tracks WHERE path=?", (p,))]
    new_rows = [dict(r) for p in imported for r in con.execute(
        "SELECT id, path, title FROM tracks WHERE path=?", (p,))]
    carried = carry_stats(con, old_rows, new_rows)
    con.commit()
    moved = move_out(con, old, "replaced")
    prune_dirs(old)
    log(f"  swapped: {moved} old files to aud-removed/replaced, stats carried for {carried}")
    if waiting:
        dirs = sorted({str(Path(w).parent) for w in waiting})
        for d in dirs:
            subprocess.run([sys.executable, str(TOOLS / "player-add.py"), "--downloads-dir", d],
                           capture_output=True, text=True)
        imported2, still = landed_paths(con, job)
        new = imported2
        if still:
            log(f"  ! {len(still)} file(s) still in downloads after import")
        if waiting and old_rows:
            new_rows = [dict(r) for p in new for r in con.execute(
                "SELECT id, path, title FROM tracks WHERE path=?", (p,))]
            carry_stats(con, [r for r in old_rows if r["path"] not in imported], new_rows)
            con.commit()
    e = job["entry"]
    e.setdefault("members", [])
    paths = step_retag_new(con, e, new, go)
    step_art(con, e, go, paths, have_px=P.art_px(album_art_src(con, paths)))
    job["status"] = "done"
    job["done_at"] = time.time()


def album_art_src(con, paths):
    if not paths:
        return None
    r = con.execute("SELECT a.art_src FROM albums a JOIN tracks t ON t.album_id=a.id WHERE t.path=?",
                    (paths[0],)).fetchone()
    return r[0] if r else None


def step_retag_new(con, e, paths, go):
    tags = {}
    if e.get("first_date"):
        tags["originaldate"] = e["first_date"]
    retag_paths(paths, tags, go, "originaldate")
    want = e.get("want_album_artist")
    if want and paths:
        cur = tagtool.read_tags(paths[0]).get("album_artist")
        if P.fold(cur) != P.fold(want):
            if retag_paths(paths, {"albumartist": want}, go, "album artist"):
                paths = move_album_dir(con, paths, want, go)
    return paths


def cmd_settle(args):
    jobs = load_jobs()
    con = db()
    for key, job in jobs.items():
        if job.get("status") == "queued":
            try:
                settle_one(con, key, job, args.go)
            except Exception as ex:
                log(f"! settle {job.get('title')}: {ex}")
            save_jobs(jobs)
    drop_orphan_albums(con)
    con.close()
    cmd_status(args)


def cmd_status(_args):
    jobs = load_jobs()
    c = collections.Counter(j["status"] for j in jobs.values())
    print(", ".join(f"{k}: {v}" for k, v in sorted(c.items())) or "no jobs")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["apply", "settle", "status"])
    ap.add_argument("--artists")
    ap.add_argument("--steps", default="remove,acquire,retag,art")
    ap.add_argument("--go", action="store_true", help="really do it (default is a dry run)")
    args = ap.parse_args()
    P.OUT.mkdir(parents=True, exist_ok=True)
    {"apply": cmd_apply, "settle": cmd_settle, "status": cmd_status}[args.cmd](args)


if __name__ == "__main__":
    main()
