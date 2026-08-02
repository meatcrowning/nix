#!/usr/bin/env python3
"""Build an album-origin-only missing work list, in spotify-missing.py's exact
TSV format (COLS + sources), so soulseek-missing.py can be pointed at just the
saved-album tracks.

Same dedup + local-match logic as spotify-missing.py, but keeps only rows whose
primary source is a saved album. Writes the album-only rows to --out.
"""
import argparse, json, os, sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "pylib"))
import trackmatch

DUMP = os.path.expanduser("~/.local/share/spotify-dump")
COLS = ["artists", "title", "album", "year", "duration_ms", "isrc",
        "spotify_id", "sources"]

def clean(v):
    return str(v).replace("\t", " ").replace("\n", " ").replace("\r", " ")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump-dir", default=DUMP)
    ap.add_argument("--snap", default=os.path.join(DUMP, "library-snapshot.db"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(os.path.join(args.dump_dir, "library.json")) as f:
        data = json.load(f)

    conn = sqlite3.connect(f"file:{args.snap}?mode=ro", uri=True)
    index = {}
    for artist, title, album, dur, path in conn.execute(
            "SELECT artist, title, album, duration, path FROM tracks"):
        rec = (artist or "", title or "", album or "", dur or 0.0, path or "")
        for k in trackmatch.keys(artist, title):
            index.setdefault(k, []).append(rec)
    conn.close()

    rows = list(data.get("saved_tracks", []))
    for pl in data.get("playlists", []):
        rows.extend(pl.get("tracks", []))
    for alb in data.get("saved_albums", []):
        rows.extend(alb.get("tracks", []))

    uniq = {}
    for r in rows:
        if r.get("is_local"):
            continue
        key = r.get("isrc") or (r["artists"].lower(), r["title"].lower())
        tag = r.get("playlist") or r.get("source", "")
        if key in uniq:
            src = uniq[key]["_sources"]
            if tag and tag not in src:
                src.append(tag)
            continue
        r = dict(r)
        r["_sources"] = [tag] if tag else []
        uniq[key] = r

    out_rows = []
    for t in uniq.values():
        # keep only tracks whose primary source tag is a saved album
        if t.get("source") != "album":
            continue
        hits = []
        for k in trackmatch.keys(t.get("artists", ""), t.get("title", "")):
            hits.extend(index.get(k, []))
        if hits:
            continue  # already local
        row = {c: t.get(c, "") for c in COLS if c != "sources"}
        row["sources"] = "; ".join(t.get("_sources", []))
        out_rows.append(row)

    with open(args.out, "w") as f:
        f.write("\t".join(COLS) + "\n")
        for r in out_rows:
            f.write("\t".join(clean(r.get(c, "")) for c in COLS) + "\n")
    print(f"{len(out_rows)} album-origin missing tracks -> {args.out}")

if __name__ == "__main__":
    main()
