"""P1: one walk of the collection → _reorg/inventory.jsonl.
Audio files get their tags read with the same logic as the player."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import REORG, classify, read_tags, walk_root

t0 = time.time()
out_path = REORG / "inventory.jsonl"
REORG.mkdir(parents=True, exist_ok=True)

n = bad = 0
kinds = {}
with open(out_path, "w", encoding="utf-8") as out:
    for p, rel in walk_root():
        st = os.lstat(p)
        kind = classify(os.path.basename(p))
        row = {"rel": rel, "kind": kind, "size": st.st_size, "mtime": st.st_mtime}
        if kind == "audio":
            tags = read_tags(p)
            if tags is None:
                row["unreadable"] = True
                bad += 1
            else:
                row["tags"] = tags
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
        kinds[kind] = kinds.get(kind, 0) + 1
        n += 1
        if n % 1000 == 0:
            print(f"  {n} files…", flush=True)

print(f"{n} files in {time.time()-t0:.0f}s → {out_path}")
print("kinds:", dict(sorted(kinds.items())))
if bad:
    print(f"UNREADABLE audio files: {bad} (marked in inventory)")
