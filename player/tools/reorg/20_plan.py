"""P2: turn the inventory into review files + a move manifest. Deterministic,
re-runnable: decision CSVs are only *created* if absent, never overwritten —
run once to generate proposals, edit them, run again to fold them in.

Outputs in _reorg/:
  merge_proposals.csv   artist/albumartist variant clusters   (edit: apply)
  albumartist_fill.csv  albums with missing albumartist       (edit: apply / value)
  title_fixes.csv       placeholder titles + web rips         (edit: action / new_*)
  duplicates_report.txt cross-zone dirs mapping to one album  (info; drives holds)
  manifest.csv          the full move plan
  plan_report.txt       stats + everything that needs eyeballs
"""
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (AUDIO_EXTS, INBOX_REL, QUARANTINE_REL, REORG, ROOT,
                    load_jsonl, read_csv, san, write_csv, die)

INV = REORG / "inventory.jsonl"
if not INV.exists():
    die("run 10_inventory.py first")
inv = load_jsonl(INV)
audio = [r for r in inv if r["kind"] == "audio" and not r.get("unreadable")]
unreadable = [r for r in inv if r.get("unreadable")]


# --- decision file: artist variant merges -----------------------------------

SEP_RE = re.compile(r"\s+(?:&|and|with|feat\.?|featuring|x)\s+|,\s+", re.IGNORECASE)


def norm_key(s):
    s = unicodedata.normalize("NFKC", s).casefold()
    s = re.sub(r"\s+(?:&|with)\s+", " and ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if s.startswith("the "):
        s = s[4:]
    return s


def build_merge_proposals():
    counts = defaultdict(int)          # value -> n tracks using it
    sample = {}
    as_aa = set()                      # values that appear as album_artist
    for r in audio:
        t = r["tags"]
        for v in {t.get("artist"), t.get("album_artist")} - {None}:
            counts[v] += 1
            sample.setdefault(v, r["rel"])
        if t.get("album_artist"):
            as_aa.add(t["album_artist"])
    clusters = defaultdict(list)
    for v in counts:
        clusters[norm_key(v)].append(v)
    rows = []
    for key in sorted(clusters):
        vs = clusters[key]
        if len(vs) < 2:
            continue
        canon = max(vs, key=lambda v: (counts[v], v))
        for v in sorted(vs):
            if v != canon:
                rows.append([canon, v, counts[v], sample[v], "yes"])
    # manual candidates: same primary artist, both have a collab separator.
    # Only album_artist-level values — track-artist "feat." variants don't
    # affect grouping or folders and would drown the review in noise.
    primaries = defaultdict(list)
    for v in counts:
        if v not in as_aa:
            continue
        parts = SEP_RE.split(v, maxsplit=1)
        if len(parts) > 1 and parts[0].strip():
            primaries[norm_key(parts[0])].append(v)
    seen_pairs = {(r[0], r[1]) for r in rows}
    for key in sorted(primaries):
        vs = sorted(set(primaries[key]))
        if len(vs) < 2:
            continue
        canon = max(vs, key=lambda v: (counts[v], v))
        for v in vs:
            if v != canon and norm_key(v) != norm_key(canon) \
                    and (canon, v) not in seen_pairs:
                rows.append([canon, v, counts[v], sample[v], "no"])
    return rows


MERGES = REORG / "merge_proposals.csv"
MERGE_HDR = ["canonical", "variant", "n_tracks", "sample_path", "apply"]
if not MERGES.exists():
    write_csv(MERGES, MERGE_HDR, build_merge_proposals())
    print(f"wrote {MERGES} (review: apply=yes/no)")
_, mrows = read_csv(MERGES)
merge_map = {r[1]: r[0] for r in mrows if r[4].strip().lower() == "yes"}


# --- effective tags pass 1: merges ------------------------------------------

def eff(r):
    t = dict(r["tags"])
    if t.get("artist") in merge_map:
        t["artist"] = merge_map[t["artist"]]
    if t.get("album_artist") in merge_map:
        t["album_artist"] = merge_map[t["album_artist"]]
    return t


# --- decision file: albumartist / album fills --------------------------------

def group_key(r):
    return (os.path.dirname(r["rel"]), (r["tags"].get("album") or ""))


def build_fills():
    groups = defaultdict(list)
    for r in audio:
        t = eff(r)
        if t.get("album") and not t.get("album_artist"):
            groups[group_key(r)].append(t)
    rows = []
    for (d, alb) in sorted(groups):
        ts = groups[(d, alb)]
        artists = sorted({t.get("artist") or "?" for t in ts})
        prop = artists[0] if len(artists) == 1 else "Various Artists"
        rows.append([d, alb, len(ts), " | ".join(artists), prop, "", "yes"])
    # whole dirs where no track has an album tag → propose album=dirname
    noalb = defaultdict(list)
    for r in audio:
        t = eff(r)
        if not t.get("album"):
            noalb[os.path.dirname(r["rel"])].append(t)
    for d in sorted(noalb):
        if d == "":            # loose at root → Singles route, no fill
            continue
        ts = noalb[d]
        if len(ts) < 3:        # scattered singles keep the Singles route
            continue
        artists = sorted({t.get("artist") or "?" for t in ts})
        prop = artists[0] if len(artists) == 1 else "Various Artists"
        rows.append([d, "", len(ts), " | ".join(artists), prop,
                     os.path.basename(d), "no"])
    return rows


FILLS = REORG / "albumartist_fill.csv"
FILL_HDR = ["dir", "album", "n_tracks", "artists", "albumartist_fill",
            "album_fill", "apply"]
if not FILLS.exists():
    write_csv(FILLS, FILL_HDR, build_fills())
    print(f"wrote {FILLS} (review: apply / albumartist_fill / album_fill)")
_, frows = read_csv(FILLS)
fill_map = {}                  # (dir, album) -> (albumartist or None, album or None)
for r in frows:
    if r[6].strip().lower() == "yes":
        fill_map[(r[0], r[1])] = (r[4].strip() or None, r[5].strip() or None)


# --- decision file: title fixes / rips ---------------------------------------

PLACEHOLDER_RE = re.compile(r"^(track|untitled)\s*\d+$", re.IGNORECASE)
YT_ID_RE = re.compile(r"\[[A-Za-z0-9_-]{11}\]")
NUM_ID_RE = re.compile(r"\[\d{6,}\]")


def build_title_fixes():
    rows = []
    for r in audio:
        t = r["tags"]
        rel = r["rel"]
        base = os.path.basename(rel)
        reasons = []
        if PLACEHOLDER_RE.match(t.get("title") or ""):
            reasons.append("placeholder-title")
        if t.get("title_from_stem"):
            reasons.append("no-title-tag")
        if "soundcloud" in rel.lower():
            reasons.append("soundcloud-rip")
        if YT_ID_RE.search(base) or NUM_ID_RE.search(base):
            reasons.append("web-rip-id")
        if reasons:
            rows.append([rel, ";".join(sorted(set(reasons))),
                         t.get("artist") or "", t.get("title") or "",
                         t.get("album") or "", "", "", "", "leave"])
    return rows


TITLES = REORG / "title_fixes.csv"
TITLE_HDR = ["rel", "why", "artist", "title", "album",
             "new_artist", "new_title", "new_album", "action"]
if not TITLES.exists():
    write_csv(TITLES, TITLE_HDR, build_title_fixes())
    print(f"wrote {TITLES} (review: action=leave/fix/inbox + new_* values)")
_, trows = read_csv(TITLES)
title_fix = {}                 # rel -> row
for r in trows:
    if r[8].strip().lower() in ("fix", "inbox"):
        title_fix[r[0]] = r


# --- destinations ------------------------------------------------------------

def eff2(r):
    """Effective tags with all three decision layers applied (virtually)."""
    t = eff(r)
    fk = (os.path.dirname(r["rel"]), (r["tags"].get("album") or ""))
    if fk in fill_map:
        aa, alb = fill_map[fk]
        if aa and not t.get("album_artist"):
            t["album_artist"] = aa
        if alb and not t.get("album"):
            t["album"] = alb
    fx = title_fix.get(r["rel"])
    if fx and fx[8].strip().lower() == "fix":
        for col, key in ((5, "artist"), (6, "title"), (7, "album")):
            if fx[col].strip():
                t[key] = fx[col].strip()
        if len(fx) > 9 and fx[9].strip():
            t["track"] = int(fx[9])
    return t


ext_of = lambda rel: os.path.splitext(rel)[1]  # noqa: E731

dest_dir = {}                  # rel -> destination dir (rel, POSIX)
for r in audio:
    rel = r["rel"]
    fx = title_fix.get(rel)
    if fx and fx[8].strip().lower() == "inbox":
        dest_dir[rel] = INBOX_REL
        continue
    t = eff2(r)
    folder_artist = t.get("album_artist") or t.get("artist")
    if t.get("album"):
        dest_dir[rel] = f"{san(folder_artist, 'Unknown Artist')}/{san(t['album'], 'Unknown Album')}"
    elif folder_artist:
        dest_dir[rel] = f"{san(folder_artist, 'Unknown Artist')}/Singles"
    else:
        dest_dir[rel] = INBOX_REL

# tagless files inside an otherwise-tagged album dir follow their siblings
# (keeping their original name) instead of landing in _inbox
sib_dests = defaultdict(set)
for r in audio:
    d = dest_dir[r["rel"]]
    if d != INBOX_REL and not d.endswith("/Singles"):
        sib_dests[os.path.dirname(r["rel"])].add(d)
adopted = set()
for r in audio:
    rel = r["rel"]
    fx = title_fix.get(rel)
    if dest_dir[rel] == INBOX_REL and not (fx and fx[8].strip().lower() == "inbox"):
        sibs = sib_dests.get(os.path.dirname(rel))
        if sibs and len(sibs) == 1:
            dest_dir[rel] = next(iter(sibs))
            adopted.add(rel)

# per-destination multi-disc flag
multi_disc = defaultdict(bool)
for r in audio:
    t = eff2(r)
    if (t.get("disc") or 0) > 1:
        multi_disc[dest_dir[r["rel"]]] = True

dest_file = {}                 # rel -> full destination rel path
for r in audio:
    rel = r["rel"]
    d = dest_dir[rel]
    t = eff2(r)
    stem_src = san(Path(rel).stem)
    if d == INBOX_REL or rel in adopted:
        name = san(Path(rel).stem) + ext_of(rel)
    elif d.endswith("/Singles"):
        name = f"{san(t['title'])}{ext_of(rel)}"
    elif t.get("track") is None:
        name = f"{stem_src}{ext_of(rel)}"       # vinyl A1/B4 etc.
    elif multi_disc[d]:
        name = f"{t.get('disc') or 1}-{t['track']:02d} {san(t['title'])}{ext_of(rel)}"
    else:
        name = f"{t['track']:02d} {san(t['title'])}{ext_of(rel)}"
    dest_file[rel] = f"{d}/{name}"


# --- duplicate albums across source dirs -------------------------------------

by_dest = defaultdict(lambda: defaultdict(list))   # dest_dir -> src_dir -> rels
for r in audio:
    rel = r["rel"]
    d = dest_dir[rel]
    if d != INBOX_REL and not d.endswith("/Singles"):
        by_dest[d][os.path.dirname(rel)].append(rel)

held_dirs = set()
dup_lines = []
for d in sorted(by_dest):
    srcs = by_dest[d]
    real_srcs = {s for s in srcs if len(srcs[s]) > 1 or len(srcs) > 1}
    if len(srcs) < 2:
        continue
    # collision = two different source dirs produce the same destination file
    owners = defaultdict(set)
    for s, rels in srcs.items():
        for rel in rels:
            owners[dest_file[rel]].add(s)
    colliding = {f for f, os_ in owners.items() if len(os_) > 1}
    kind = "COLLIDING" if colliding else "DISJOINT-MERGE"
    dup_lines.append(f"[{kind}] {d}")
    for s in sorted(srcs):
        n = len(srcs[s])
        sz = sum(next(r["size"] for r in audio if r["rel"] == rel) for rel in srcs[s])
        dup_lines.append(f"    {n:3d} tracks {sz/1e6:8.1f} MB  {s or '(root)'}")
    if colliding:
        for f in sorted(colliding)[:5]:
            dup_lines.append(f"      collides: {f}")
        for s in srcs:
            if s:              # loose root files never hold a whole dir
                held_dirs.add(s)
        dup_lines.append("      → all source dirs HELD (resolve at Gate C)")
    dup_lines.append("")

(REORG / "duplicates_report.txt").write_text("\n".join(dup_lines) or "none\n")


# --- sidecar destinations -----------------------------------------------------

own_dests = defaultdict(set)       # src dir -> dests of audio directly in it
subtree_dests = defaultdict(set)   # src dir -> dests of all audio at/below it
for r in audio:
    rel = r["rel"]
    d = dest_dir[rel]
    if d == INBOX_REL or os.path.dirname(rel) in held_dirs:
        continue
    p = os.path.dirname(rel)
    own_dests[p].add(d)
    while True:
        subtree_dests[p].add(d)
        if not p:
            break
        p = os.path.dirname(p)


def _dest_at(d):
    """Unique destination of audio in dir d — its own files first (a stray
    differently-tagged bonus subdir must not poison the album root), then the
    whole subtree (covers at the root of a disc-subdir album)."""
    for m in (own_dests, subtree_dests):
        s = m.get(d)
        if s and len(s) == 1:
            return next(iter(s))
    return None


def place_sidecar(d, base):
    """Destination for a sidecar living in src dir d: nearest dir at-or-above
    d with an attributable audio destination, preserving the relative path
    below it (keeps Scans/, Covers/ subfolders). None → quarantine."""
    cur, below = d, []
    while True:
        dd = _dest_at(cur)
        if dd:
            below.reverse()
            return "/".join([dd, *below, base])
        if not cur:
            return None
        below.append(os.path.basename(cur))
        cur = os.path.dirname(cur)


# audio rel -> renamed basename (for lrc pairing and cue/m3u rewriting)
stem_map = {}                  # (src_dir, src_stem) -> dest audio rel
global_stems = defaultdict(list)   # stem -> audio rels (orphaned-lrc rescue)


def norm_stem(s):
    """'1-05 Amethyst' / '05. Amethyst' / '05 Amethyst' → '05 amethyst':
    old exports disc-prefix or dot the track number; the audio may not."""
    s = re.sub(r"^\d+-(?=\d)", "", s)
    s = re.sub(r"^(\d+)\.\s*", r"\1 ", s)
    return s.casefold()


for r in audio:
    rel = r["rel"]
    stem_map[(os.path.dirname(rel), Path(rel).stem)] = rel
    global_stems[norm_stem(Path(rel).stem)].append(rel)

manifest = []                  # [src_rel, dst_rel, kind, action, note]
for r in audio:
    rel = r["rel"]
    src_d = os.path.dirname(rel)
    if src_d in held_dirs:
        manifest.append([rel, "", "audio", "hold", "duplicate-album"])
    elif r.get("unreadable"):
        manifest.append([rel, "", "audio", "hold", "unreadable"])
    elif dest_file[rel] != rel:      # already in place (re-runs) → no row
        manifest.append([rel, dest_file[rel], "audio", "move", ""])

for r in inv:
    kind = r["kind"]
    if kind == "audio":
        continue
    rel = r["rel"]
    d = os.path.dirname(rel)
    base = os.path.basename(rel)
    if d in held_dirs:
        manifest.append([rel, "", kind, "hold", "duplicate-album"])
        continue
    if kind == "junk":
        manifest.append([rel, f"{QUARANTINE_REL}/{rel}", kind, "quarantine", ""])
        continue
    if kind == "lrc":
        partner = stem_map.get((d, Path(rel).stem))
        note = "paired"
        if partner is None:
            # audio moved away in an earlier manual sort — adopt the unique
            # same-stem audio file anywhere in the library
            cands = global_stems.get(norm_stem(Path(rel).stem), [])
            if len(cands) == 1:
                partner, note = cands[0], "paired-global"
        if partner and dest_dir.get(partner) and os.path.dirname(partner) not in held_dirs:
            dst = str(Path(dest_file[partner]).with_suffix(".lrc"))
            manifest.append([rel, dst, kind, "move", note])
            continue
        # unpaired lrc falls through to generic sidecar handling
    dst = place_sidecar(d, base)
    if dst is not None:
        note = "rewrite-entries" if kind in ("cue", "m3u", "m3u8") else ""
        manifest.append([rel, dst, kind, "move", note])
    elif kind in ("m3u", "m3u8"):
        manifest.append([rel, f"{QUARANTINE_REL}/playlists/{rel}", kind,
                         "quarantine", "not album-local"])
    else:
        manifest.append([rel, f"{QUARANTINE_REL}/{rel}", kind, "quarantine",
                         "unattributable"])

# same-destination collisions inside the manifest → plan-time " (2)" suffix
taken = {}
renamed = 0
for row in manifest:
    if row[3] not in ("move", "quarantine") or not row[1]:
        continue
    dst = row[1]
    if dst in taken:
        stem, ext = os.path.splitext(dst)
        i = 2
        while f"{stem} ({i}){ext}" in taken:
            i += 1
        row[1] = f"{stem} ({i}){ext}"
        row[4] = (row[4] + "; " if row[4] else "") + "suffixed"
        renamed += 1
    taken[row[1]] = row[0]

# drop already-in-place rows (idempotent re-runs on the organized tree)
manifest = [r for r in manifest if not (r[3] == "move" and r[0] == r[1])]
write_csv(REORG / "manifest.csv", ["src", "dst", "kind", "action", "note"],
          manifest)


# --- report -------------------------------------------------------------------

acts = defaultdict(int)
for row in manifest:
    acts[row[3]] += 1
inbox_n = sum(1 for row in manifest if row[1].startswith(INBOX_REL + "/") or row[1] == INBOX_REL)
singles_n = sum(1 for rel, d in dest_dir.items() if d.endswith("/Singles"))
artists = {d.split("/")[0] for d in dest_dir.values()
           if d not in (INBOX_REL,)}
rep = [
    f"audio files: {len(audio)}  (unreadable: {len(unreadable)})",
    f"manifest rows: {len(manifest)}  actions: {dict(sorted(acts.items()))}",
    f"destination artists: {len(artists)}  album dirs: {len(by_dest)}",
    f"singles-routed tracks: {singles_n}   inbox-routed: {inbox_n}",
    f"plan-time suffix collisions: {renamed}",
    f"held source dirs (duplicates): {len(held_dirs)}",
    f"merges applied: {len(merge_map)}   fills applied: {len(fill_map)}   "
    f"title fixes/inbox: {len(title_fix)}",
    "",
    "held dirs:",
    *[f"  {d}" for d in sorted(held_dirs)],
    "",
    "unreadable files:",
    *[f"  {r['rel']}" for r in unreadable],
]
(REORG / "plan_report.txt").write_text("\n".join(rep) + "\n")
print("\n".join(rep[:8]))
print(f"→ {REORG}/manifest.csv, duplicates_report.txt, plan_report.txt")
