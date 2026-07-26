"""P6: repoint the player DB at the moved files so ratings / play counts /
added_at / last_played survive, and refresh mtime/size (+ tag columns for
retagged files) so the next player rescan re-parses NOTHING (parsed: 0).
Never touches rating, favorite, play_count, added_at, last_played.
Player must be closed. Run AFTER 40_move.py --apply."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import AUDIO_EXTS, DB_PATH, REORG, ROOT, die, read_csv, read_tags

out = subprocess.run(["pgrep", "-af", "python3"], capture_output=True, text=True).stdout
for line in out.splitlines():
    if "player/main.py" in line:
        die("player appears to be running: " + line)

baseline = json.loads((REORG / "baseline.json").read_text())["db"]
_, moved = read_csv(REORG / "moved.csv")
retagged_path = REORG / "retagged.csv"
retagged = read_csv(retagged_path)[1] if retagged_path.exists() else []

moved_map = {s: d for s, d, k in moved}
audio_moves = [(s, d) for s, d, k in moved
               if k == "audio" and os.path.splitext(s)[1].lower() in AUDIO_EXTS]

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
con.execute("BEGIN IMMEDIATE")
n0 = con.execute("SELECT COUNT(*) c FROM tracks").fetchone()["c"]
if n0 != baseline["tracks"]:
    die(f"track count {n0} != baseline {baseline['tracks']} — wrong DB state?")

# 1. path remap (+ fresh mtime/size — retagged files changed both)
db_paths = {r["path"] for r in con.execute("SELECT path FROM tracks")}
new_paths = {str(ROOT / d) for s, d in audio_moves}
clash = new_paths & (db_paths - {str(ROOT / s) for s, d in audio_moves})
if clash:
    die(f"{len(clash)} destination paths already in DB — aborting")

remapped, missing = 0, []
for s, d in audio_moves:
    old_abs, new_abs = str(ROOT / s), str(ROOT / d)
    if old_abs not in db_paths:
        missing.append(s)
        continue
    st = os.stat(new_abs)
    cur = con.execute(
        "UPDATE tracks SET path=?, mtime=?, size=? WHERE path=?",
        (new_abs, st.st_mtime, st.st_size, old_abs))
    if cur.rowcount != 1:
        die(f"remap touched {cur.rowcount} rows for {s}")
    remapped += 1
print(f"remapped {remapped} paths ({len(missing)} not in DB — expected for "
      f"formats the player doesn't scan)")

# 2. tag-column refresh for retagged files (never the user-state columns)
TAG_COLS = ("title", "artist", "album", "album_artist", "track", "disc",
            "date", "year", "orig_year", "genre", "has_art")
refreshed = 0
for row in retagged:
    rel = row[0]
    new_rel = moved_map.get(rel, rel)
    new_abs = str(ROOT / new_rel)
    t = read_tags(new_abs)
    if t is None:
        die(f"can't re-read tags: {new_rel}")
    st = os.stat(new_abs)
    cur = con.execute(
        f"UPDATE tracks SET {', '.join(c + '=?' for c in TAG_COLS)}, "
        "mtime=?, size=? WHERE path=?",
        [*(t[c] for c in TAG_COLS), st.st_mtime, st.st_size, new_abs])
    if cur.rowcount == 1:
        refreshed += 1
    elif os.path.splitext(rel)[1].lower() in AUDIO_EXTS:
        die(f"retag refresh missed DB row: {new_rel}")
print(f"refreshed tag columns on {refreshed} retagged rows")

# 3. rebuild albums exactly like main.py rebuild_albums()
con.execute("""
    INSERT INTO albums (album, album_artist, year, orig_year)
    SELECT album, COALESCE(album_artist, artist, ''), MIN(year), MIN(orig_year)
      FROM tracks WHERE album IS NOT NULL
     GROUP BY album, COALESCE(album_artist, artist, '')
    ON CONFLICT(album, album_artist) DO UPDATE SET
      year=excluded.year, orig_year=excluded.orig_year
""")
con.execute("""
    UPDATE tracks SET album_id = (
      SELECT a.id FROM albums a
       WHERE a.album = tracks.album
         AND a.album_artist = COALESCE(tracks.album_artist, tracks.artist, ''))
""")
con.execute("DELETE FROM albums WHERE id NOT IN "
            "(SELECT DISTINCT album_id FROM tracks WHERE album_id IS NOT NULL)")

# 4. invariants, then commit
q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
checks = {
    "tracks": q("SELECT COUNT(*) FROM tracks"),
    "rated": q("SELECT COUNT(*) FROM tracks WHERE rating IS NOT NULL"),
    "played": q("SELECT COUNT(*) FROM tracks WHERE play_count > 0"),
    "favorite": q("SELECT COUNT(*) FROM tracks WHERE favorite = 1"),
    "last_played": q("SELECT COUNT(*) FROM tracks WHERE last_played IS NOT NULL"),
}
for k, v in checks.items():
    if v != baseline[k]:
        die(f"invariant {k}: {v} != baseline {baseline[k]} — NOT committing")
outside = q(f"SELECT COUNT(*) FROM tracks WHERE path NOT LIKE '{ROOT}/%'")
if outside:
    die(f"{outside} rows outside {ROOT} — NOT committing")
con.commit()
albums = q("SELECT COUNT(*) FROM albums")
print(f"OK — committed. invariants match baseline; albums now {albums} "
      f"(was {baseline['albums']})")
