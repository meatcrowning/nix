#!/usr/bin/env python3
"""Inventory model files before and after the consolidation move.

Writes one TSV row per file: relative path, size, mtime, a cheap content sample
hash, and the fingerprinter's verdict.  `--diff` re-scans and compares against an
earlier manifest so a move can be proven lossless without re-reading 247G.

The sample hash covers the first and last mebibyte plus the exact size.  That is
not a full checksum, but a rename cannot alter it, and any truncation or partial
copy changes either the size or the tail.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fingerprint as fp  # noqa: E402

SAMPLE = 1024 * 1024


def sample_hash(path: str, size: int) -> str:
    h = hashlib.sha256()
    h.update(str(size).encode())
    with open(path, "rb") as fh:
        h.update(fh.read(SAMPLE))
        if size > SAMPLE * 2:
            fh.seek(-SAMPLE, os.SEEK_END)
            h.update(fh.read(SAMPLE))
    return h.hexdigest()[:32]


def collect(roots, with_hash=True):
    rows = {}
    for root in roots:
        root = os.path.abspath(root)
        for full, hint, st in fp.iter_model_files(root):
            rel = os.path.relpath(full, root)
            # Key by <subdir>/<basename> so the same file compares equal across roots.
            key = rel.replace(os.sep, "/")
            res = fp.classify(full, hint)
            rows[key] = {
                "key": key,
                "size": st.st_size,
                "mtime_ns": st.st_mtime_ns,
                "hash": sample_hash(full, st.st_size) if with_hash else "-",
                "role": res.get("role") or "?",
                "family": res.get("family") or "?",
                "src": full,
            }
    return rows


FIELDS = ("key", "size", "mtime_ns", "hash", "role", "family")


def write_tsv(rows, out):
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\t".join(FIELDS) + "\n")
        for key in sorted(rows):
            r = rows[key]
            fh.write("\t".join(str(r[f]) for f in FIELDS) + "\n")


def read_tsv(path):
    rows = {}
    with open(path, "r", encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            vals = line.rstrip("\n").split("\t")
            r = dict(zip(header, vals))
            r["size"] = int(r["size"])
            rows[r["key"]] = r
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--roots", nargs="+", required=True)
    ap.add_argument("--out")
    ap.add_argument("--diff", metavar="MANIFEST", help="compare against an earlier manifest")
    ap.add_argument("--no-hash", action="store_true")
    args = ap.parse_args(argv)

    rows = collect(args.roots, with_hash=not args.no_hash)
    print(f"scanned {len(rows)} model files across {len(args.roots)} root(s)", file=sys.stderr)

    if args.out:
        write_tsv(rows, args.out)
        print(f"wrote {args.out}", file=sys.stderr)

    if args.diff:
        old = read_tsv(args.diff)
        missing = sorted(set(old) - set(rows))
        added = sorted(set(rows) - set(old))
        changed = []
        for key in sorted(set(old) & set(rows)):
            o, n = old[key], rows[key]
            if o["size"] != n["size"] or (o["hash"] != "-" and o["hash"] != n["hash"]):
                changed.append(key)
        for key in missing:
            print(f"MISSING  {key}")
        for key in added:
            print(f"ADDED    {key}")
        for key in changed:
            print(f"CHANGED  {key}")
        ok = not missing and not changed
        print(
            f"\n{len(old)} before, {len(rows)} after: "
            f"{len(missing)} missing, {len(added)} added, {len(changed)} changed",
            file=sys.stderr,
        )
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
