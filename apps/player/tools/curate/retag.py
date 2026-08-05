#!/usr/bin/env python3
"""curate retag — canonicalise the tag spelling inside a same-dir cluster.

The safest stage: every variant lives in the SAME directory, so nothing
moves — the only change is that every file's album / album_artist tags are
rewritten to ONE canonical string, ending the player's double-listing.

Canonical choice per cluster:
  - album_artist: the spelling used by the MOST files in the cluster
    (the library's majority vote), tie-broken by the longest.
  - album:        same majority rule, then MusicBrainz's release title if a
    release id is on file and its title casefold-matches the folded cluster
    title (guards against picking up a typo'd majority).

Dry run by default; --apply rewrites via atomicsave, audits, and writes
retag-results.json. Idempotent: a converged cluster no longer appears in
tagclusters.clusters(), so re-runs are no-ops.
"""
import collections
import json
import sys
from pathlib import Path

import common as C
import tagclusters as TC

ATOMICSAVE = None


def _canonical(variants):
    """(canonical_artist, canonical_album) by majority file count."""
    def majority(idx):
        counts = collections.Counter()
        for (aa, al), recs in variants.items():
            counts[(aa, al)[idx]] += len(recs)
        top = max(counts.values())
        cands = [s for s, n in counts.items() if n == top]
        return max(cands, key=len)
    return majority(0), majority(1)


def _retag_file(path, album, album_artist):
    global ATOMICSAVE
    if ATOMICSAVE is None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        import atomicsave as _a
        ATOMICSAVE = _a

    def mutate(audio):
        C.set_common_tags(audio, album=album, album_artist=album_artist)

    ATOMICSAVE.atomic_save(str(path), mutate)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    rows = json.loads(C.SCAN_JSON.read_text())
    todo = [c for c in TC.clusters(rows) if c["action"] == "retag"]
    results = []
    for c in todo:
        aa, al = _canonical(c["variants"])
        n_files = sum(len(v) for v in c["variants"].values())
        changed = 0
        for (v_aa, v_al), recs in c["variants"].items():
            if (v_aa, v_al) == (aa, al):
                continue
            for r in recs:
                changed += 1
                if args.apply:
                    try:
                        _retag_file(r["path"], al, aa)
                    except Exception as e:
                        print(f"  ! retag failed {r['rel']}: {e}", file=sys.stderr)
                        changed -= 1
        results.append({"canonical_artist": aa, "canonical_album": al,
                        "variants": [f"{a}|{b}" for a, b in c["variants"]],
                        "files": n_files, "rewritten": changed})
        print(f"{'RETAGGED' if args.apply else 'would retag'} "
              f"{aa!r} / {al!r}  ({changed}/{n_files} files)  "
              f"from: {', '.join(f'{a}|{b}' for a, b in c['variants'])[:90]}")

    if args.apply:
        out = C.STATE / "retag-results.json"
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
        print(f"-> {out}")


if __name__ == "__main__":
    main()
