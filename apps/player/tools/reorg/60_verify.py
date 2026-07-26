"""P8: post-move verification against baseline.json.
--restore-drift additionally restores rating/favorite/play_count from the
backup DB for any drifted row (expected: none)."""
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import AUDIO_EXTS, DB_PATH, REORG, ROOT, classify, read_csv, walk_root

RESTORE = "--restore-drift" in sys.argv
baseline = json.loads((REORG / "baseline.json").read_text())
_, moved = read_csv(REORG / "moved.csv")
retagged = read_csv(REORG / "retagged.csv")[1] if (REORG / "retagged.csv").exists() else []
rewritten = read_csv(REORG / "rewritten.csv")[1] if (REORG / "rewritten.csv").exists() else []
fails = []


def check(name, ok, detail=""):
    print(f"  [{'ok' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)


# 1. file count + byte reconciliation. walk_root() skips _quarantine/_inbox
# (they must not look like library content to the planner) but files parked
# there absolutely count here — walk manually, excluding only _reorg.
files = bytes_now = 0
audio_left_outside = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    if Path(dirpath) == ROOT:
        dirnames[:] = [d for d in dirnames if d != "_reorg"]
    for name in filenames:
        p = os.path.join(dirpath, name)
        rel = os.path.relpath(p, ROOT)
        files += 1
        bytes_now += os.lstat(p).st_size
        top = rel.split("/", 1)[0]
        if classify(name) == "audio" and (
                top in ("Staging", "Transfer") or "/" not in rel):
            audio_left_outside.append(rel)
delta = (sum(float(r[4]) - float(r[2]) for r in retagged)
         + sum(float(r[2]) - float(r[1]) for r in rewritten))
check("file count unchanged", files == baseline["disk"]["files"],
      f"{files} vs {baseline['disk']['files']}")
check("bytes reconcile (retag+rewrite deltas)",
      bytes_now == baseline["disk"]["bytes"] + delta,
      f"{bytes_now} vs {baseline['disk']['bytes']} + {delta:.0f}")

# 2. every move landed
src_gone = dst_there = True
for s, d, k in moved:
    if (ROOT / s).exists() and s != d:
        src_gone = False
    if not (ROOT / d).exists():
        dst_there = False
check("all moved srcs gone", src_gone)
check("all moved dsts present", dst_there)

# 3. no stray audio outside the new tree (held duplicates are the exception)
_, manifest = read_csv(REORG / "manifest.csv")
held = {r[0] for r in manifest if r[3] == "hold"}
stray = [r for r in audio_left_outside if r not in held]
check("no audio left in Staging/Transfer/root", not stray,
      f"{len(stray)} stray, {len(held)} held" + (f" e.g. {stray[:3]}" if stray else ""))

# 4. DB invariants + paths exist
con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
for k, sql in (("tracks", "SELECT COUNT(*) FROM tracks"),
               ("rated", "SELECT COUNT(*) FROM tracks WHERE rating IS NOT NULL"),
               ("played", "SELECT COUNT(*) FROM tracks WHERE play_count > 0"),
               ("favorite", "SELECT COUNT(*) FROM tracks WHERE favorite = 1"),
               ("last_played", "SELECT COUNT(*) FROM tracks WHERE last_played IS NOT NULL")):
    check(f"db {k} == baseline", q(sql) == baseline["db"][k])
dead = [r["path"] for r in con.execute("SELECT path FROM tracks")
        if not os.path.exists(r["path"])]
check("all db paths exist on disk", not dead,
      f"{len(dead)} dead" + (f" e.g. {dead[:2]}" if dead else ""))

# 5. lrc pairing — every lrc the planner moved as "paired"/"paired-global"
# must sit next to same-stem audio (one unpaired lrc rode along with its dir;
# that's expected and only informational)
expect_paired = sum(1 for r in manifest
                    if r[2] == "lrc" and r[4].startswith("paired"))
lrc_ok = lrc_bad = 0
for p, rel in walk_root():
    if not rel.endswith(".lrc"):
        continue
    stem = p[:-4]
    if any(os.path.exists(stem + e) for e in AUDIO_EXTS | {".mp4"}):
        lrc_ok += 1
    else:
        lrc_bad += 1
check("planned lrc pairings intact", lrc_ok >= expect_paired,
      f"{lrc_ok} paired (expected ≥{expect_paired}), {lrc_bad} unpaired ride-alongs")

# 6. rating/state drift vs backup (via the move map)
bak = sqlite3.connect(json.loads((REORG / "baseline.json").read_text())["db_backup"])
bak.row_factory = sqlite3.Row
moved_abs = {str(ROOT / s): str(ROOT / d) for s, d, k in moved}
drift = []
for r in bak.execute("SELECT path, rating, favorite, play_count FROM tracks"):
    new_path = moved_abs.get(r["path"], r["path"])
    live = con.execute("SELECT rating, favorite, play_count FROM tracks WHERE path=?",
                       (new_path,)).fetchone()
    if live is None:
        drift.append((new_path, "row missing"))
    elif (live["rating"], live["favorite"], live["play_count"]) != \
         (r["rating"], r["favorite"], r["play_count"]):
        drift.append((new_path, "values differ"))
        if RESTORE:
            con.execute("UPDATE tracks SET rating=?, favorite=?, play_count=? "
                        "WHERE path=?",
                        (r["rating"], r["favorite"], r["play_count"], new_path))
check("zero rating/favorite/playcount drift", not drift,
      f"{len(drift)}" + (f" e.g. {drift[:3]}" if drift else ""))
if RESTORE and drift:
    con.commit()
    print(f"  restored {len(drift)} drifted rows from backup")

print()
print("ALL CHECKS PASSED" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
