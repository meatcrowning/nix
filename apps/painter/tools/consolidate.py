#!/usr/bin/env python3
"""Merge the two ComfyUI model trees into one canonical root.

Both source trees live on the same filesystem, so every move is a rename(2):
instant, and no extra free space is consumed.  Nothing is deleted except exact
byte-identical duplicates, and even those are only removed after a full compare.

Safety rules this script follows:
  * --dry-run is the default; --apply is required to touch anything.
  * A rollback script is written BEFORE the first move, and it refuses to undo
    into an occupied destination.
  * Duplicates are confirmed with a full md5 of both files, not a sample.
  * A source directory is only replaced by a symlink once it is empty.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fingerprint as fp  # noqa: E402

DEST = "/home/lam/models"
SOURCES = [
    "/home/lam/Projects/cte/app/models",       # larger tree first
    "/home/lam/Downloads/git/ComfyUI/models",
]

SUBDIRS = [
    "checkpoints", "diffusion_models", "unet", "text_encoders", "clip", "vae",
    "loras", "clip_vision", "controlnet", "embeddings", "upscale_models",
    "style_models", "model_patches", "photomaker", "gligen", "hypernetworks",
    "vae_approx", "latent_upscale_models", "audio_encoders", "diffusers",
    "configs", "LLavacheckpoints", "detection", "background_removal",
    "frame_interpolation", "geometry_estimation", "optical_flow",
]

# Files that exist in both trees and are known to be interchangeable.  Anything
# else that collides stops the run.
HARDLINK_DUPES = {
    # keep -> alias that becomes a hardlink to it (same dir)
    ("vae", "z.safetensors"): "zbase.safetensors",
}


def md5(path: str, chunk: int = 8 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def is_sentinel(path: str) -> bool:
    """ComfyUI ships zero-byte `put_*_here` placeholders in every model dir."""
    try:
        return os.path.getsize(path) == 0
    except OSError:
        return False


def plan(sources, dest):
    """Return (moves, dupes, problems).  Pure inspection, no side effects."""
    moves = []       # (src, dst)
    dupes = []       # (src, dst, md5) - identical, source can go
    problems = []    # (src, dst, reason)
    claimed = {}     # dst -> src, to catch intra-run collisions

    for root in sources:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in sorted(filenames):
                src = os.path.join(dirpath, name)
                if os.path.islink(src):
                    continue
                rel = os.path.relpath(src, root)
                dst = os.path.join(dest, rel)
                if is_sentinel(src):
                    continue
                existing = claimed.get(dst)
                if existing is None and not os.path.exists(dst):
                    claimed[dst] = src
                    moves.append((src, dst))
                    continue
                other = existing or dst
                try:
                    same = os.path.getsize(src) == os.path.getsize(other) and md5(src) == md5(other)
                except OSError as exc:
                    problems.append((src, other, f"cannot compare: {exc}"))
                    continue
                if same:
                    dupes.append((src, other, "identical"))
                else:
                    problems.append((src, other, "DIFFERENT content, same relative path"))
    return moves, dupes, problems


def write_rollback(path, moves, dupes, symlinks):
    lines = [
        "#!/usr/bin/env bash",
        "# Undo the painter model consolidation.  Generated before any file was moved.",
        "# Aborts rather than overwrite anything that appeared since.",
        "set -uo pipefail",
        "fail=0",
        "undo() {  # undo <current> <original>",
        '  if [[ ! -e "$1" ]]; then echo "MISSING $1" >&2; fail=1; return; fi',
        '  if [[ -e "$2" ]]; then echo "OCCUPIED $2" >&2; fail=1; return; fi',
        '  mkdir -p "$(dirname "$2")" && mv -n "$1" "$2" || fail=1',
        "}",
        "",
    ]
    for link, original in symlinks:
        lines += [
            f'# restore real directory at {link}',
            f'if [[ -L "{link}" ]]; then rm "{link}"; mkdir -p "{link}"; fi',
        ]
    lines.append("")
    for src, dst in moves:
        lines.append(f'undo "{dst}" "{src}"')
    if dupes:
        lines.append("")
        lines.append("# These sources were deleted as verified byte-identical duplicates.")
        lines.append("# They can be recreated by copying the kept copy back:")
        for src, kept, _why in dupes:
            lines.append(f'#   cp "{kept}" "{src}"')
    lines += [
        "",
        'if (( fail )); then echo "rollback finished WITH ERRORS" >&2; exit 1; fi',
        'echo "rollback complete"',
    ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(path, 0o755)


def do_apply(moves, dupes, dest, sources, rollback_path):
    for sub in SUBDIRS:
        os.makedirs(os.path.join(dest, sub), exist_ok=True)

    symlinks = [(s, s) for s in sources]
    write_rollback(rollback_path, moves, dupes, symlinks)
    print(f"rollback script: {rollback_path}")

    moved = 0
    for src, dst in moves:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.rename(src, dst)  # same filesystem: atomic, instant
        moved += 1
    print(f"moved {moved} files")

    removed = 0
    for src, _kept, _why in dupes:
        os.unlink(src)
        removed += 1
    print(f"removed {removed} verified duplicate(s)")

    # Replace each now-empty source tree with a symlink to the canonical root.
    for root in sources:
        if not os.path.isdir(root) or os.path.islink(root):
            continue
        leftovers = []
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                p = os.path.join(dirpath, name)
                if not is_sentinel(p):
                    leftovers.append(p)
        if leftovers:
            print(f"!! {root} still holds {len(leftovers)} file(s); leaving it alone")
            for p in leftovers[:5]:
                print(f"     {p}")
            continue
        shutil.rmtree(root)
        os.symlink(dest, root)
        print(f"symlinked {root} -> {dest}")


def verify(dest, manifest):
    here = os.path.dirname(os.path.abspath(__file__))
    audit = os.path.join(here, "audit-models.py")
    rc = os.system(f'python3 {audit!r} --roots {dest!r} --diff {manifest!r}')
    return os.waitstatus_to_exitcode(rc) if hasattr(os, "waitstatus_to_exitcode") else rc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dest", default=DEST)
    ap.add_argument("--sources", nargs="+", default=SOURCES)
    ap.add_argument("--apply", action="store_true", help="actually move files")
    ap.add_argument("--dry-run", action="store_true", default=None)
    ap.add_argument("--verify", metavar="MANIFEST")
    args = ap.parse_args(argv)

    if args.verify:
        return verify(args.dest, args.verify)

    moves, dupes, problems = plan(args.sources, args.dest)

    by_dir = {}
    for src, dst in moves:
        by_dir.setdefault(os.path.basename(os.path.dirname(dst)), []).append((src, dst))
    print(f"=== plan: {len(moves)} moves, {len(dupes)} duplicates, {len(problems)} problems ===\n")
    for sub in sorted(by_dir):
        print(f"  {sub}/  ({len(by_dir[sub])} files)")
        for src, dst in by_dir[sub][:3]:
            print(f"      {src}\n   -> {dst}")
        if len(by_dir[sub]) > 3:
            print(f"      ... and {len(by_dir[sub]) - 3} more")
    if dupes:
        print("\n  duplicates (byte-identical, source will be removed):")
        for src, kept, _ in dupes:
            print(f"      {src}\n   == {kept}")
    if problems:
        print("\n  PROBLEMS:")
        for src, dst, why in problems:
            print(f"      {why}\n        {src}\n        {dst}")

    total = sum(os.path.getsize(s) for s, _ in moves if os.path.exists(s))
    print(f"\n  {total / 2**30:.1f} GiB to relocate (rename only, no copy)")

    if problems:
        print("\nrefusing to proceed while problems remain", file=sys.stderr)
        return 2
    if not args.apply:
        print("\ndry run - nothing changed.  Re-run with --apply to execute.")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    cache = os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "painter"
    )
    os.makedirs(cache, exist_ok=True)
    do_apply(moves, dupes, args.dest, args.sources, os.path.join(cache, f"rollback-{stamp}.sh"))

    # Post-move tidy: hardlink the known interchangeable alias back into place.
    for (sub, keep), alias in HARDLINK_DUPES.items():
        kpath = os.path.join(args.dest, sub, keep)
        apath = os.path.join(args.dest, sub, alias)
        if not os.path.exists(kpath):
            continue
        if not os.path.exists(apath):
            os.link(kpath, apath)
            print(f"hardlinked {alias} -> {keep}")
        elif os.stat(kpath).st_ino != os.stat(apath).st_ino and md5(kpath) == md5(apath):
            # Two separate but identical files: collapse to one inode, keeping
            # the alias name so existing workflows still resolve it.
            os.unlink(apath)
            os.link(kpath, apath)
            print(f"deduped {alias} -> hardlink of {keep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
