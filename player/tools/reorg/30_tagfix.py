"""P3: apply the approved tag consistency fixes in place with mutagen.

Reads the three decision CSVs (merge_proposals, albumartist_fill, title_fixes)
exactly like 20_plan.py does, computes the per-file field changes, and writes
only files that actually differ. Dry-run by default; --apply to write.

Outputs: _reorg/retagged.csv        (rel, old/new mtime+size)  → for 50_db_remap
         _reorg/tagfix_reverse.csv  (rel, field, old_value)    → rollback record
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mutagen
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TALB, TIT2, TPE1, TPE2, TRCK
from mutagen.mp4 import MP4

from common import REORG, ROOT, die, load_jsonl, read_csv, read_tags, write_csv

APPLY = "--apply" in sys.argv

inv = load_jsonl(REORG / "inventory.jsonl")
audio = [r for r in inv if r["kind"] == "audio" and not r.get("unreadable")]

_, mrows = read_csv(REORG / "merge_proposals.csv")
merge_map = {r[1]: r[0] for r in mrows if r[4].strip().lower() == "yes"}
_, frows = read_csv(REORG / "albumartist_fill.csv")
fill_map = {}
for r in frows:
    if r[6].strip().lower() == "yes":
        fill_map[(r[0], r[1])] = (r[4].strip() or None, r[5].strip() or None)
_, trows = read_csv(REORG / "title_fixes.csv")
title_fix = {r[0]: r for r in trows if r[8].strip().lower() == "fix"}

# --- compute per-file changes ------------------------------------------------

changes = {}                   # rel -> {field: new_value}
for r in audio:
    rel = r["rel"]
    t = r["tags"]
    ch = {}
    for f in ("artist", "album_artist"):
        if t.get(f) in merge_map:
            ch[f] = merge_map[t[f]]
    fk = (os.path.dirname(rel), t.get("album") or "")
    if fk in fill_map:
        aa, alb = fill_map[fk]
        if aa and not t.get("album_artist"):
            ch["album_artist"] = aa
        if alb and not t.get("album"):
            ch["album"] = alb
    fx = title_fix.get(rel)
    if fx:
        for col, f in ((5, "artist"), (6, "title"), (7, "album")):
            if fx[col].strip():
                ch[f] = fx[col].strip()
        if len(fx) > 9 and fx[9].strip():
            ch["track"] = int(fx[9])
    # drop no-ops (title_from_stem means the title tag is actually absent)
    for f in list(ch):
        cur = t.get(f)
        if f == "title" and t.get("title_from_stem"):
            cur = None
        if cur == ch[f]:
            del ch[f]
    if ch:
        changes[rel] = ch

print(f"{len(changes)} files need tag changes "
      f"({sum(len(c) for c in changes.values())} field writes)")
for rel in list(changes)[:8]:
    print(f"  {rel}\n    {changes[rel]}")
if not APPLY:
    print("dry-run only — rerun with --apply to write")
    sys.exit(0)

# --- apply ---------------------------------------------------------------

ID3_FRAMES = {"artist": TPE1, "album_artist": TPE2, "title": TIT2,
              "album": TALB, "track": TRCK}
MP4_KEYS = {"artist": "\xa9ART", "album_artist": "aART", "title": "\xa9nam",
            "album": "\xa9alb"}
VORBIS_KEYS = {"artist": "ARTIST", "album_artist": "ALBUMARTIST",
               "title": "TITLE", "album": "ALBUM", "track": "TRACKNUMBER"}

retagged, reverse, errors = [], [], []
for rel, ch in changes.items():
    p = str(ROOT / rel)
    st0 = os.stat(p)
    try:
        audio_f = mutagen.File(p)
        if audio_f is None:
            raise RuntimeError("mutagen can't open")
        if audio_f.tags is None:
            audio_f.add_tags()
        tags = audio_f.tags
        old = read_tags(p)
        if isinstance(tags, ID3):
            for f, v in ch.items():
                tags.setall(ID3_FRAMES[f].__name__,
                            [ID3_FRAMES[f](encoding=3, text=[str(v)])])
        elif isinstance(audio_f, MP4):
            for f, v in ch.items():
                if f == "track":
                    audio_f["trkn"] = [(int(v), 0)]
                else:
                    audio_f[MP4_KEYS[f]] = [str(v)]
        else:                      # Vorbis comments / APEv2 (dict-like)
            for f, v in ch.items():
                tags[VORBIS_KEYS[f]] = [str(v)]
        audio_f.save()
    except Exception as e:      # noqa: BLE001
        errors.append((rel, repr(e)))
        continue
    st1 = os.stat(p)
    retagged.append([rel, st0.st_mtime, st0.st_size, st1.st_mtime, st1.st_size])
    for f in ch:
        reverse.append([rel, f, old.get(f) if old.get(f) is not None else ""])

write_csv(REORG / "retagged.csv",
          ["rel", "old_mtime", "old_size", "new_mtime", "new_size"], retagged)
write_csv(REORG / "tagfix_reverse.csv", ["rel", "field", "old_value"], reverse)
print(f"retagged {len(retagged)} files → retagged.csv / tagfix_reverse.csv")
if errors:
    print("ERRORS:")
    for rel, e in errors:
        print(f"  {rel}: {e}")
    die("some files failed — inspect before proceeding")
