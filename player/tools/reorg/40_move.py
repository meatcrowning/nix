"""P5: execute manifest.csv. Same-filesystem os.rename only — never copies,
never overwrites (collisions get " (2)"), never deletes (only rmdir of empty
dirs). Writes _reorg/moved.csv (actual src→dst incl. deviations) as it goes,
and _reorg/rewritten.csv for cue/m3u whose entries were repointed.

  --dry-run (default)  validate everything, print stats, touch nothing
  --apply              do it
  --reverse            replay moved.csv backwards (rollback)
"""
import csv
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import REORG, ROOT, die, read_csv, write_csv

MODE = ("apply" if "--apply" in sys.argv else
        "reverse" if "--reverse" in sys.argv else "dry-run")

MOVED = REORG / "moved.csv"
KEEP_DIRS = {str(ROOT), str(ROOT / "Staging"), str(ROOT / "Transfer")}


def unsuffix_free(dst):
    """First non-existing variant of dst: dst, 'stem (2).ext', 'stem (3)…'."""
    if not os.path.lexists(dst):
        return dst
    stem, ext = os.path.splitext(dst)
    i = 2
    while os.path.lexists(f"{stem} ({i}){ext}"):
        i += 1
    return f"{stem} ({i}){ext}"


def rmdir_sweep():
    """Repeat until stable: bottom-up os.walk sees stale dirnames after a
    child rmdir, so one pass leaves empty parent skeletons behind."""
    removed = 0
    while True:
        n = 0
        for dirpath, dirnames, filenames in os.walk(ROOT, topdown=False):
            if dirpath in KEEP_DIRS or filenames or dirnames:
                continue
            try:
                os.rmdir(dirpath)
                n += 1
            except OSError:
                pass
        removed += n
        if not n:
            return removed


if MODE == "reverse":
    _, rows = read_csv(MOVED)
    n = 0
    for src, dst, kind in reversed(rows):
        s, d = ROOT / src, ROOT / dst
        if not d.exists():
            print(f"MISSING (skipped): {dst}")
            continue
        s.parent.mkdir(parents=True, exist_ok=True)
        if s.exists():
            die(f"reverse target exists: {src}")
        os.rename(d, s)
        n += 1
    print(f"reversed {n} moves; sweeping empty dirs…")
    print(f"removed {rmdir_sweep()} empty dirs")
    sys.exit(0)

_, manifest = read_csv(REORG / "manifest.csv")
work = [r for r in manifest if r[3] in ("move", "quarantine")]
holds = [r for r in manifest if r[3] == "hold"]

# --- validate ----------------------------------------------------------------
root_dev = os.stat(ROOT).st_dev
problems = []
for src, dst, kind, action, note in work:
    p = ROOT / src
    if not p.is_file():
        problems.append(f"src missing: {src}")
    elif os.stat(p).st_dev != root_dev:
        problems.append(f"cross-device: {src}")
    if not dst:
        problems.append(f"empty dst: {src}")
    elif (ROOT / dst).resolve().parts[:len(ROOT.parts)] != ROOT.parts:
        problems.append(f"dst escapes root: {dst}")
if problems:
    for p in problems[:20]:
        print("  " + p)
    die(f"{len(problems)} validation problems — stale manifest? rerun 20_plan.py")

print(f"{len(work)} files to move/quarantine, {len(holds)} held in place")
if MODE == "dry-run":
    dst_dirs = {os.path.dirname(r[1]) for r in work}
    print(f"would create ≤{len(dst_dirs)} directories; validation clean")
    sys.exit(0)

# --- move ----------------------------------------------------------------
if MOVED.exists():
    die(f"{MOVED} already exists — moves already ran? (reverse or remove it first)")

moved_rows = []
deviations = 0
with open(MOVED, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f, quoting=csv.QUOTE_ALL)
    w.writerow(["src", "dst", "kind"])
    for i, (src, dst, kind, action, note) in enumerate(work):
        s = ROOT / src
        d = unsuffix_free(str(ROOT / dst))
        if d != str(ROOT / dst):
            deviations += 1
        os.makedirs(os.path.dirname(d), exist_ok=True)
        os.rename(s, d)
        drel = os.path.relpath(d, ROOT)
        w.writerow([src, drel, kind])
        moved_rows.append((src, drel, kind))
        if (i + 1) % 2000 == 0:
            f.flush()
            print(f"  {i + 1}/{len(work)}…", flush=True)
print(f"moved {len(moved_rows)} files ({deviations} runtime collision suffixes)")

# --- rewrite cue/m3u entries ---------------------------------------------
# map: (original src dir, original basename) -> new basename + new dir
by_old = {(os.path.dirname(s), os.path.basename(s)): d for s, d, k in moved_rows}
rewrites = [r for r in manifest if r[4].startswith("rewrite-entries")
            or "rewrite-entries" in r[4]]
rewritten = []
for src, dst, kind, action, note in rewrites:
    key = (os.path.dirname(src), os.path.basename(src))
    new_rel = by_old.get(key)
    if new_rel is None:
        continue
    p = ROOT / new_rel
    old_dir = os.path.dirname(src)
    new_dir = os.path.dirname(new_rel)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        continue
    size0 = p.stat().st_size

    def repoint(entry):
        entry = entry.strip()
        old_target = os.path.normpath(os.path.join(old_dir, entry))
        moved_to = by_old.get((os.path.dirname(old_target),
                               os.path.basename(old_target)))
        if moved_to is None:
            return None
        return os.path.relpath(ROOT / moved_to, ROOT / new_dir)

    lines = []
    changed = False
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        if kind == "cue":
            m = re.match(r'(\s*FILE\s+")([^"]+)(".*)$', bare)
            if m:
                np = repoint(m.group(2))
                if np:
                    line = m.group(1) + np + m.group(3) + line[len(bare):]
                    changed = True
        elif bare and not bare.startswith("#"):
            np = repoint(bare)
            if np:
                line = np + line[len(bare):]
                changed = True
        lines.append(line)
    if changed:
        p.write_text("".join(lines), encoding="utf-8")
        rewritten.append([new_rel, size0, p.stat().st_size])
write_csv(REORG / "rewritten.csv", ["rel", "old_size", "new_size"], rewritten)
print(f"rewrote entries in {len(rewritten)} cue/m3u files")

print(f"removed {rmdir_sweep()} empty dirs")
