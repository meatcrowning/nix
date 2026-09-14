"""Rank local music for chatter without ever writing player's library DB.

The score blends local metadata with a bounded Last.fm snapshot.  Feedback and
recommendation receipts live in Oracle state: the player database remains
player's single-writer store.
"""
import json
import math
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

import lastfm
import trackmatch

STATE = Path(os.path.expanduser(os.environ.get(
    "MUSIC_RECOMMEND_STATE", "~/.local/state/oracle/music-recommendations.json")))
MODES = {"familiar", "rediscover", "explore"}
FEEDBACK = {"more_like_this", "not_now", "too_familiar"}


def _load():
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, STATE)


def key(artist, title):
    return trackmatch.fold(str(artist or "")) + "\0" + trackmatch.fold(str(title or ""))


def _context(now):
    local = time.localtime(now)
    part = "night" if local.tm_hour < 6 or local.tm_hour >= 21 else (
        "morning" if local.tm_hour < 12 else "afternoon" if local.tm_hour < 17 else "evening")
    season = ("winter", "spring", "summer", "autumn")[(local.tm_mon % 12) // 3]
    return part + ":" + ("weekend" if local.tm_wday >= 5 else "weekday") + ":" + season


def _rows(con):
    return [dict(r) for r in con.execute(
        "SELECT path,title,artist,album,album_artist,track,disc,year,orig_year,genre,"
        "rating,favorite,play_count,last_played FROM tracks WHERE path IS NOT NULL")]


def _lastfm_snapshot():
    """Bounded recent/history evidence; an unavailable service is non-fatal."""
    cfg = lastfm.load()
    if not lastfm.has_keys(cfg) or not lastfm.username(cfg):
        return [], [], {}
    try:
        recent = lastfm.recent_tracks(pages=4, cfg=cfg)
        top_raw = lastfm.call("user.getTopTracks", {"user": lastfm.username(cfg),
                               "period": "12month", "limit": 100}, cfg=cfg)
        top = ((top_raw.get("toptracks") or {}).get("track") or [])
        top = top if isinstance(top, list) else [top]
    except lastfm.LastfmError:
        return [], [], {}
    artists = []
    for r in recent[:8]:
        if r.get("artist"):
            artists.append(r["artist"])
    similar = {}
    # Three cacheable seeds are enough to widen a library pick without turning
    # one recommendation into a fan-out of web requests.
    state = _load()
    cache = state.get("similar_artists", {}) if isinstance(state.get("similar_artists"), dict) else {}
    now = time.time()
    for artist in dict.fromkeys(artists):
        entry = cache.get(trackmatch.fold(artist), {})
        if entry.get("until", 0) > now:
            similar[trackmatch.fold(artist)] = entry.get("names", [])
            continue
        try:
            body = lastfm.call("artist.getSimilar", {"artist": artist, "limit": 12}, cfg=cfg)
            found = [str(x.get("name") or "") for x in
                     ((body.get("similarartists") or {}).get("artist") or []) if x.get("name")]
            cache[trackmatch.fold(artist)] = {"until": now + 7 * 86400, "names": found}
            similar[trackmatch.fold(artist)] = found
        except lastfm.LastfmError:
            pass
    state["similar_artists"] = cache
    _save(state)
    return recent, top, similar


def recommend(con, mode="familiar", limit=3):
    mode = mode if mode in MODES else "familiar"
    limit = max(1, min(int(limit or 3), 12))
    now = time.time()
    state = _load()
    feedback = state.get("feedback", {}) if isinstance(state.get("feedback"), dict) else {}
    context = _context(now)
    context_genres = ((state.get("context_genres") or {}).get(context) or {})
    recent, top, similar = _lastfm_snapshot()
    remote_recent = Counter(key(r.get("artist"), r.get("track")) for r in recent if r.get("uts"))
    remote_artists = Counter(trackmatch.fold(r.get("artist")) for r in recent if r.get("uts"))
    remote_top = {key((r.get("artist") or {}).get("name") or r.get("artist"), r.get("name")): int(r.get("playcount") or 0)
                  for r in top if r.get("name")}
    related = {trackmatch.fold(n) for names in similar.values() for n in names}
    ranked = []
    for row in _rows(con):
        k = key(row["artist"], row["title"])
        fb = feedback.get("path:" + row["path"], {}) if isinstance(feedback.get("path:" + row["path"]), dict) else {}
        if fb.get("not_now", 0) > now - 14 * 86400:
            continue
        played = int(row.get("play_count") or 0) + remote_top.get(k, 0)
        last = float(row.get("last_played") or 0)
        days = (now - last) / 86400 if last else 3650
        rating = float(row.get("rating") or 0)
        favourite = 1 if row.get("favorite") else 0
        saturation = remote_recent[k] * 18 + remote_artists[trackmatch.fold(row["artist"])] * 4
        saturation += 18 if fb.get("too_familiar", 0) > now - 90 * 86400 else 0
        affinity = rating * 12 + favourite * 14 + min(12, math.log1p(played) * 3)
        rediscovery = min(24, math.log1p(days) * 3) + (12 if played and days > 90 else 0)
        novelty = (18 if not played else 0) + min(10, math.log1p(days) * 1.5)
        relation = 8 if trackmatch.fold(row["artist"]) in related else 0
        feedback_boost = 18 if fb.get("more_like_this", 0) > now - 365 * 86400 else 0
        genres = [trackmatch.fold(x) for x in str(row.get("genre") or "").split(";") if x.strip()]
        session = sum(float(context_genres.get(g, 0)) for g in genres)
        if mode == "rediscover":
            score = affinity + rediscovery + relation + feedback_boost + session - saturation
        elif mode == "explore":
            score = novelty + relation + rating * 5 + feedback_boost + session - saturation
        else:
            score = affinity + rediscovery * .55 + relation + feedback_boost + session - saturation
        ranked.append((score, row, {"days": round(days), "played": played,
                                    "related": bool(relation), "mode": mode}))
    # Album-level ranking prevents a strong track from making the app call a
    # random single-song selection a recommendation for a record.
    albums = defaultdict(list)
    for item in ranked:
        row = item[1]
        albums[(row.get("album_artist") or row.get("artist") or "", row.get("album") or row["title"])].append(item)
    picks = []
    for (artist, album), items in albums.items():
        items.sort(key=lambda x: x[0], reverse=True)
        score = sum(x[0] for x in items[:3]) / min(3, len(items))
        best = items[0]
        why = ("long-unheard favourite" if best[1].get("favorite") and best[2]["days"] > 90
               else "unplayed nearby discovery" if not best[2]["played"]
               else "away from recent rotation")
        if best[2]["related"]:
            why += "; related to recent listening"
        picks.append((score, artist, album, items, why))
    picks.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, artist, album, items, why in picks[:limit]:
        ordered = sorted(items, key=lambda x: (x[1].get("disc") or 0, x[1].get("track") or 0, x[1]["path"]))
        genres = sorted({g for x in items for g in str(x[1].get("genre") or "").split(";") if g})
        out.append({"artist": artist, "album": album, "paths": [x[1]["path"] for x in ordered],
                    "score": round(score, 1), "reason": why,
                    "track_count": len(items), "genres": genres})
    rid = "%x" % int(now * 1000)
    state.setdefault("shown", {})[rid] = {"at": now, "context": context, "items": out}
    state["shown"] = dict(list(state["shown"].items())[-100:])
    _save(state)
    return {"ok": True, "mode": mode, "recommendation_id": rid,
            "albums": out, "history": "lastfm" if recent else "local", "context": context}


def feedback(recommendation_id, value):
    if value not in FEEDBACK:
        return {"error": "feedback must be more_like_this, not_now or too_familiar"}
    state = _load()
    shown = (state.get("shown") or {}).get(str(recommendation_id), {})
    items = shown.get("items") or []
    if not items:
        return {"error": "unknown recommendation"}
    now = time.time()
    store = state.setdefault("feedback", {})
    context = str(shown.get("context") or "")
    genres = state.setdefault("context_genres", {}).setdefault(context, {}) if context else {}
    delta = 1 if value == "more_like_this" else -1
    for item in items:
        for genre in item.get("genres") or []:
            g = trackmatch.fold(genre)
            genres[g] = max(-12, min(12, float(genres.get(g, 0)) + delta))
        for path in item.get("paths") or []:
            # Path is a stable local identity; the basename is intentionally not.
            store["path:" + path] = {value: now}
    _save(state)
    return {"ok": True, "feedback": value, "items": len(items)}
