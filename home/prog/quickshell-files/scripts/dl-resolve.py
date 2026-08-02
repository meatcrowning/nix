#!/usr/bin/env python3
"""dl-resolve.py <original-download-path>

Resolve the CURRENT real on-disk location of a downloaded file and print it
(one line, absolute path), or print nothing if it cannot be found.

Why this exists: the panel's image-download completion toast is handed the path
surfer saved the file to (~/Downloads/<name>), but `sort-downloads` files
finished image downloads out of ~/Downloads into ~/Pictures (and videos into
~/Videos) within seconds of the download finishing — a `systemd` .path unit
fires on any change to ~/Downloads and moves once the file is stable (~4s).
By the time the user clicks the toast the file is no longer at the path the
toast was given, so a raw `xdg-open ~/Downloads/<name>` and a thumbnail pointed
at ~/Downloads/<name> both fail with "Cannot open". This is that
path-vs-reality mismatch, surfaced.

Resolution order:
  1. If the original path still exists, it is the file - print it.
  2. Otherwise look for the file where it could have been sorted to
     (~/Pictures, ~/Videos, and ~/Downloads), matching the basename exactly or
     the `stem (n)ext` collision form sort-downloads produces when the target
     already held a file. Of any match, print the most recently written.

Only regular files count; nothing that does not share the original's name
shape is ever picked. Prints nothing when there is no candidate, so the card
degrades to having no openable/thumbnail image rather than opening a dead path.
"""
import os
import sys
from pathlib import Path


def main():
    orig = sys.argv[1] if len(sys.argv) > 1 else ""
    if not orig:
        return
    p = Path(orig)
    if p.is_file():
        print(p)
        return

    base = p.name
    stem, ext = os.path.splitext(base)
    home = Path.home()
    best = None
    best_m = -1
    for d in (home / "Pictures", home / "Videos", home / "Downloads"):
        if not d.is_dir():
            continue
        try:
            entries = list(d.iterdir())
        except OSError:
            continue
        for cand in entries:
            if not cand.is_file():
                continue
            n = cand.name
            if n == base:
                pass  # exact match - a candidate
            elif ext and n.startswith(stem + " (") and n.endswith(ext):
                pass  # sort-downloads collision form: "stem (n)ext"
            else:
                continue
            try:
                m = cand.stat().st_mtime
            except OSError:
                continue
            if m > best_m:
                best, best_m = cand, m
    if best is not None:
        print(best)


if __name__ == "__main__":
    main()
