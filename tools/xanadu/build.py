#!/usr/bin/env python3
"""Render the tracked flake source as a XanaduSpace-style 3D page field.

Pages are the tracked .nix files plus the repo-level guides. The page itself
finds the cross-file links (page.html, extractLinks) so the static artifact
and the live editor (serve.py) share one implementation.

Only `git ls-files` output is read, so nothing untracked or private enters the
page. Usage: tools/xanadu/build.py [OUT.html]  (default: stdout)
"""
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
GUIDES = {"AGENTS.md", "README.md", "apps/AGENTS.md", "home/prog/AGENTS.md",
          "home/prog/hyprvtb/PORTING.md", "home/prog/quickshell-files/AGENTS.md"}


def tracked(root):
    out = subprocess.run(["git", "-C", root, "ls-files", "-z"], check=True,
                         capture_output=True, text=True).stdout
    return sorted(f for f in out.split("\0")
                  if f and (f.endswith(".nix") or f in GUIDES)
                  and os.path.isfile(os.path.join(root, f))
                  and not os.path.islink(os.path.join(root, f)))


def group_of(path):
    parts = path.split("/")
    if len(parts) == 1:
        return "/"
    if parts[0] == "home" and len(parts) > 2:
        return "/".join(parts[:2]) + "/"
    return parts[0] + "/"


def page_of(root, path):
    with open(os.path.join(root, path), "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8", errors="replace")
    eol = text.endswith("\n")
    return {"path": path, "group": group_of(path), "text": text[:-1] if eol else text,
            "eol": eol, "hash": hashlib.sha256(raw).hexdigest()}


def page_data(root=ROOT):
    return {
        "pages": [page_of(root, p) for p in tracked(root)],
        "rev": subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True).stdout.strip(),
    }


def render(data, edit=None):
    """edit: None for the read-only page, else {"token": ...} for serve.py."""
    with open(os.path.join(HERE, "page.html"), encoding="utf-8") as fh:
        tpl = fh.read()
    enc = lambda v: json.dumps(v, separators=(",", ":")).replace("</", "<\\/")
    return tpl.replace("/*XANADU_DATA*/null", enc(data)).replace("/*XANADU_EDIT*/null", enc(edit))


def main():
    data = page_data()
    html = render(data)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"{len(data['pages'])} pages -> {sys.argv[1]}", file=sys.stderr)
    else:
        sys.stdout.write(html)


if __name__ == "__main__":
    main()
