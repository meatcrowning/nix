#!/usr/bin/env python3
"""dbsync merge test — two divergent copies of the REAL library database.

    python3 player/tools/test-dbsync.py [path/to/library.db]

Snapshots the live database into a temp dir (read-only, safe while the player
is running), diverges the two copies the way two machines would, merges A into
B, and asserts every rule in the merge table of docs/agents/air-library-share.md.
Touches nothing outside the temp dir. This is A5.1 of that plan.
"""
import shutil, sqlite3, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dbsync

LIVE = Path(sys.argv[1]) if len(sys.argv) > 1 else dbsync.db_path()
TD = tempfile.TemporaryDirectory()
SD = Path(TD.name)
BASE = SD / "lib.db"
dbsync.snapshot(str(LIVE), str(BASE))   # WAL-safe; never `cp` a live database
A, B = SD / "a.db", SD / "b.db"
for p in (A, B):
    shutil.copy(BASE, p)

now = time.time()
ca, cb = sqlite3.connect(A), sqlite3.connect(B)
for c in (ca, cb):
    c.row_factory = sqlite3.Row
    dbsync.ensure_columns(c)

ids = [r[0] for r in ca.execute("SELECT id FROM tracks ORDER BY id LIMIT 6")]
t1, t2, t3, t4, t5, t6 = ids
paths = {i: ca.execute("SELECT path FROM tracks WHERE id=?", (i,)).fetchone()[0] for i in ids}

# t1: A played it more            -> max wins
ca.execute("UPDATE tracks SET play_count=10, last_played=? WHERE id=?", (now, t1))
cb.execute("UPDATE tracks SET play_count=3,  last_played=? WHERE id=?", (now - 999, t1))
# t2: B played it more            -> B must survive a pull FROM A
ca.execute("UPDATE tracks SET play_count=1 WHERE id=?", (t2,))
cb.execute("UPDATE tracks SET play_count=7 WHERE id=?", (t2,))
# t3: rated on both, A newer      -> A's rating wins
ca.execute("UPDATE tracks SET rating=1.0, meta_mtime=? WHERE id=?", (now, t3))
cb.execute("UPDATE tracks SET rating=0.2, meta_mtime=? WHERE id=?", (now - 500, t3))
# t4: rated on both, B newer      -> B keeps its own
ca.execute("UPDATE tracks SET rating=1.0, meta_mtime=? WHERE id=?", (now - 500, t4))
cb.execute("UPDATE tracks SET rating=0.2, meta_mtime=? WHERE id=?", (now, t4))
# t5: favourite set on A only
ca.execute("UPDATE tracks SET favorite=1, meta_mtime=? WHERE id=?", (now, t5))
# t6: rating cleared on A, later  -> the CLEAR must propagate (None is a value)
ca.execute("UPDATE tracks SET rating=NULL, meta_mtime=? WHERE id=?", (now, t6))
cb.execute("UPDATE tracks SET rating=0.8,  meta_mtime=? WHERE id=?", (now - 500, t6))

# a track only A knows about -> inserted, never the reverse-deleted
ca.execute("INSERT INTO tracks (path, mtime, size, title, album, album_artist, added_at, play_count)"
           " VALUES ('/run/media/lam/SSD/aud/ZZ/new.flac', 1.0, 1, 'newtrack', 'ZZ', 'ZZ', ?, 2)", (now,))
# a track only B knows about -> must still be there afterwards
cb.execute("INSERT INTO tracks (path, mtime, size, title, album, album_artist, added_at)"
           " VALUES ('/run/media/lam/SSD/aud/ZZ/bonly.flac', 1.0, 1, 'bonly', 'ZZ', 'ZZ', ?)", (now,))

# lyrics: A has synced, B has plain -> synced wins
ca.execute("INSERT OR REPLACE INTO lyrics VALUES (?,?,?,?,?,?)", (t1, "lrclib", 1, "[00:01.00]hi", now, 0))
cb.execute("INSERT OR REPLACE INTO lyrics VALUES (?,?,?,?,?,?)", (t1, "embedded", 0, "plain words", now + 50, 0))
# B has a verdict, A has only a miss -> verdict wins, attempts keeps the max
ca.execute("INSERT OR REPLACE INTO lyrics VALUES (?,?,?,?,?,?)", (t2, "none", 0, "", now, 5))
cb.execute("INSERT OR REPLACE INTO lyrics VALUES (?,?,?,?,?,?)", (t2, "instrumental", 0, "", now - 10, 1))
# A has a miss with a higher attempt count, B has a miss -> backoff not reset
ca.execute("INSERT OR REPLACE INTO lyrics VALUES (?,?,?,?,?,?)", (t3, "none", 0, "", now, 4))
cb.execute("INSERT OR REPLACE INTO lyrics VALUES (?,?,?,?,?,?)", (t3, "none", 0, "", now - 10, 1))

ca.commit(); cb.commit()
before_b = cb.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
ca.close(); cb.close()

# ---- the merge under test: A -> B (a `pull` on B) ----
st = dbsync.merge(str(A), str(B))

cb = sqlite3.connect(B); cb.row_factory = sqlite3.Row
g = lambda i, col: cb.execute(f"SELECT {col} FROM tracks WHERE path=?", (paths[i],)).fetchone()[0]
L = lambda i: cb.execute("SELECT l.* FROM lyrics l JOIN tracks t ON t.id=l.track_id WHERE t.path=?",
                         (paths[i],)).fetchone()

fails = []
def check(what, got, want):
    if got != want:
        fails.append(f"  {what}: got {got!r}, want {want!r}")
    print(f"{'ok  ' if got == want else 'FAIL'} {what}: {got!r}")

check("t1 play_count max",        g(t1, "play_count"), 10)
check("t1 last_played newest",    round(g(t1, "last_played"), 3), round(now, 3))
check("t2 local higher plays kept", g(t2, "play_count"), 7)
check("t3 newer rating wins",     g(t3, "rating"), 1.0)
check("t4 older rating rejected", g(t4, "rating"), 0.2)
check("t5 favourite propagates",  g(t5, "favorite"), 1)
check("t6 rating clear propagates", g(t6, "rating"), None)
check("new track inserted",       cb.execute("SELECT title FROM tracks WHERE path='/run/media/lam/SSD/aud/ZZ/new.flac'").fetchone()[0], "newtrack")
check("new track album_id NULL",  cb.execute("SELECT album_id FROM tracks WHERE path='/run/media/lam/SSD/aud/ZZ/new.flac'").fetchone()[0], None)
check("b-only track survives",    cb.execute("SELECT COUNT(*) FROM tracks WHERE path='/run/media/lam/SSD/aud/ZZ/bonly.flac'").fetchone()[0], 1)
check("no deletions",             cb.execute("SELECT COUNT(*) FROM tracks").fetchone()[0], before_b + 1)
check("t1 synced lyrics win",     (L(t1)["source"], L(t1)["synced"]), ("lrclib", 1))
check("t2 verdict beats none",    L(t2)["source"], "instrumental")
check("t2 attempts max kept",     L(t2)["attempts"], 5)
check("t3 attempts not reset",    L(t3)["attempts"], 4)
print("\nstats:", st)

# idempotence: merging again must change nothing
st2 = dbsync.merge(str(A), str(B), quiet=True)
check("second merge is a no-op", all(v == 0 for v in st2.values()), True)

print("\nFAILURES:" if fails else "\nALL PASS")
print("\n".join(fails))
sys.exit(1 if fails else 0)
