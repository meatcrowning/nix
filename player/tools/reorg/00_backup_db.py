"""P0: backup the player DB (sqlite backup API, WAL-safe) + tagwrites journal,
and record disk/DB baselines to _reorg/baseline.json. Player must be closed."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, REORG, DB_PATH, STATE_DIR, classify, walk_root, die

# player closed? (match the real process, not this script's own cmdline)
out = subprocess.run(["pgrep", "-af", "python3"], capture_output=True, text=True).stdout
for line in out.splitlines():
    if "player/main.py" in line:
        die("player appears to be running: " + line)

if not ROOT.is_dir():
    die(f"{ROOT} not mounted")
REORG.mkdir(parents=True, exist_ok=True)

stamp = time.strftime("%Y%m%d-%H%M%S")
bak = REORG / f"library.db.bak-{stamp}"
src = sqlite3.connect(DB_PATH)
dst = sqlite3.connect(bak)
with dst:
    src.backup(dst)
dst.close()

q = lambda sql: src.execute(sql).fetchone()[0]  # noqa: E731
db = {
    "tracks": q("SELECT COUNT(*) FROM tracks"),
    "rated": q("SELECT COUNT(*) FROM tracks WHERE rating IS NOT NULL"),
    "played": q("SELECT COUNT(*) FROM tracks WHERE play_count > 0"),
    "favorite": q("SELECT COUNT(*) FROM tracks WHERE favorite = 1"),
    "last_played": q("SELECT COUNT(*) FROM tracks WHERE last_played IS NOT NULL"),
    "albums": q("SELECT COUNT(*) FROM albums"),
    "lyrics": q("SELECT COUNT(*) FROM lyrics"),
    "null_albumartist": q("SELECT COUNT(*) FROM tracks WHERE album_artist IS NULL"),
    "null_album": q("SELECT COUNT(*) FROM tracks WHERE album IS NULL"),
}
src.close()

journal = STATE_DIR / "tagwrites.log"
if journal.exists():
    shutil.copy2(journal, REORG / f"tagwrites.log.bak-{stamp}")

files = bytes_total = audio = 0
kinds = {}
for p, rel in walk_root():
    st = os.lstat(p)
    files += 1
    bytes_total += st.st_size
    k = classify(os.path.basename(p))
    kinds[k] = kinds.get(k, 0) + 1
    if k == "audio":
        audio += 1

baseline = {"stamp": stamp, "db_backup": str(bak),
            "disk": {"files": files, "bytes": bytes_total, "audio": audio,
                     "kinds": dict(sorted(kinds.items()))},
            "db": db}
(REORG / "baseline.json").write_text(json.dumps(baseline, indent=2))
print(json.dumps(baseline, indent=2))
