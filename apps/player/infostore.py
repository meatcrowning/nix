"""Qt-free release-information storage and portable user corrections.

Downloaded entities expire independently of user choices. A reverted correction
is a timestamped tombstone so a later two-way sync cannot resurrect it.
"""
import hashlib
import json
import re
import time
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS music_info_cache (
 cache_key TEXT NOT NULL, kind TEXT NOT NULL, body_json TEXT NOT NULL,
 fetched_at REAL NOT NULL, expires_at REAL NOT NULL, error TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(cache_key,kind)
);
CREATE TABLE IF NOT EXISTS music_info_user (
 scope_key TEXT NOT NULL, kind TEXT NOT NULL, body_json TEXT NOT NULL,
 updated_at REAL NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(scope_key,kind)
);
CREATE TABLE IF NOT EXISTS music_info_links (
 scope_key TEXT PRIMARY KEY, release_id TEXT NOT NULL,
 release_group_id TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL
);
"""


def ensure_schema(con):
    con.executescript(SCHEMA)


def decode(value, fallback):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(fallback)) else fallback
    except (ValueError, TypeError):
        return fallback


def identity(row):
    value = row.get("identity_json")
    return value if isinstance(value, dict) else decode(value, {})


def scope_key(row):
    """Album corrections share a scope; distinct edition folders stay distinct.

    Paths are identical on top/book. Conventional CD/disc subdirectories belong
    to their parent edition. Loose tracks still separate by album and artist.
    Embedded identifiers affect resolution, not the lifetime of this local key.
    """
    parent = Path(row.get("path") or "").parent
    if re.fullmatch(r"(?:cd|disc|disk)[ _.-]*\d+(?:\s*[-:].*)?", parent.name, re.I):
        parent = parent.parent
    parts = [row.get("album_artist") or row.get("artist") or "",
             row.get("album") or "", str(parent)]
    if not row.get("album"):
        parts.append(row.get("path") or row.get("title") or "")
    return "album:" + hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def cache_get(con, key, kind):
    row = con.execute("SELECT * FROM music_info_cache WHERE cache_key=? AND kind=?",
                      (key, kind)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["body"] = decode(out["body_json"], {})
    out["stale"] = time.time() >= out["expires_at"]
    return out


def cache_put(con, key, kind, body, ttl, error="", preserve=False):
    old = cache_get(con, key, kind) if preserve else None
    stamp = time.time()
    if old and old["body"]:
        body, fetched = old["body"], old["fetched_at"]
    else:
        fetched = stamp
    con.execute("INSERT OR REPLACE INTO music_info_cache VALUES (?,?,?,?,?,?)",
                (key, kind, json.dumps(body, ensure_ascii=False), fetched,
                 stamp + ttl, str(error)))
    con.commit()


def user_get(con, key, kind):
    row = con.execute("SELECT * FROM music_info_user WHERE scope_key=? AND kind=?",
                      (key, kind)).fetchone()
    if row is None or row["deleted"]:
        return {}
    return decode(row["body_json"], {})


def user_put(con, key, kind, body=None):
    con.execute("INSERT OR REPLACE INTO music_info_user VALUES (?,?,?,?,?)",
                (key, kind, json.dumps(body or {}, ensure_ascii=False), time.time(),
                 int(body is None)))
    con.commit()


def effective_album(con, scope):
    link = con.execute("SELECT release_id FROM music_info_links WHERE scope_key=?",
                       (scope,)).fetchone()
    row = cache_get(con, "release:" + link[0], "album") if link else None
    album = dict(row["body"]) if row else {}
    album.update(user_get(con, scope, "album"))
    return album
