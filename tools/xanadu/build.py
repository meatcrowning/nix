#!/usr/bin/env python3
"""Render the tracked flake source as a XanaduSpace-style 3D page field.

Pages are the tracked .nix files plus the repo-level guides; links are the
cross-file references that actually bind this config together (umport imports
everything, so `imports = [...]` edges are nearly absent):

  path    a line naming another page's path (./rel, repo-relative, ~/nix/...,
          or a unique *.nix basename)
  option  an options.my.* declaration and every config.my.* use
  unit    a systemd unit defined in one page and named in another
  file    a home.file / xdg.configFile target deployed by one page and named
          in another
  overlay a package an overlay replaces and the pages that use it

Only `git ls-files` output is read, so nothing untracked or private enters the
page. Usage: tools/xanadu/build.py [OUT.html]  (default: stdout)
"""
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
GUIDES = {"AGENTS.md", "README.md", "apps/AGENTS.md", "home/prog/AGENTS.md",
          "home/prog/hyprvtb/PORTING.md", "home/prog/quickshell-files/AGENTS.md"}


def tracked():
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"], check=True,
                         capture_output=True, text=True).stdout
    files = [f for f in out.split("\0") if f]
    return sorted(f for f in files
                  if (f.endswith(".nix") or f in GUIDES)
                  and os.path.isfile(os.path.join(ROOT, f))
                  and not os.path.islink(os.path.join(ROOT, f)))


def group_of(path):
    parts = path.split("/")
    if len(parts) == 1:
        return "/"
    if parts[0] == "home" and len(parts) > 2:
        return "/".join(parts[:2]) + "/"
    return parts[0] + "/"


def main():
    paths = tracked()
    pages = []
    idx = {}
    for p in paths:
        with open(os.path.join(ROOT, p), encoding="utf-8", errors="replace") as fh:
            text = fh.read().expandtabs(2)
        lines = text.rstrip("\n").split("\n")
        idx[p] = len(pages)
        pages.append({"path": p, "group": group_of(p), "lines": lines, "hosts": []})

    by_base = defaultdict(list)
    for p in paths:
        by_base[os.path.basename(p)].append(p)

    links = {}

    def link(kind, a, al, b, bl, label):
        if a == b:
            return
        key = (kind, a, al, b, bl)
        if key not in links:
            links[key] = {"k": kind, "a": a, "al": al, "b": b, "bl": bl, "t": label}

    token = re.compile(r"(?:~/nix/|/home/lam/nix/|\.\.?/)?[A-Za-z0-9_@.+-]+(?:/[A-Za-z0-9_@.+-]+)*")

    def resolve(src, tok):
        cands = []
        for pre in ("/home/lam/nix/", "~/nix/"):
            if tok.startswith(pre):
                cands.append(tok[len(pre):])
        if tok.startswith("./") or tok.startswith("../"):
            cands.append(os.path.normpath(os.path.join(os.path.dirname(src), tok)))
        cands.append(tok)
        for c in cands:
            for v in (c, c + ".nix", c.rstrip("/") + "/default.nix"):
                if v in idx:
                    return v
        if tok.endswith(".nix") and "/" not in tok and len(by_base[tok]) == 1:
            return by_base[tok][0]
        return None

    # declarations first: options, units, deployed files, overlay packages
    opt_decl, unit_decl, file_decl, pkg_decl = {}, {}, {}, {}
    re_opt = re.compile(r"options\.(my\.[A-Za-z0-9_.]+?)\s*=")
    re_unit = re.compile(r"systemd\.(?:user\.)?(services|timers|paths|sockets)\.\"?([A-Za-z0-9_@-]+)\"?\s*=")
    re_file = re.compile(r"(xdg\.configFile|home\.file|xdg\.dataFile)\.\"([^\"]+)\"")
    re_pkg = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*=\s*prev\.")
    for p in paths:
        for i, line in enumerate(pages[idx[p]]["lines"], 1):
            for m in re_opt.finditer(line):
                opt_decl.setdefault(m.group(1), (p, i))
            for m in re_unit.finditer(line):
                unit_decl.setdefault(m.group(2), (p, i, m.group(1)[:-1]))
            for m in re_file.finditer(line):
                tgt = m.group(2)
                if m.group(1) == "xdg.configFile":
                    tgt = ".config/" + tgt
                elif m.group(1) == "xdg.dataFile":
                    tgt = ".local/share/" + tgt
                if len(tgt) >= 10 and "/" in tgt:
                    file_decl.setdefault(tgt, (p, i))
            if p.startswith("overlays/"):
                m = re_pkg.match(line)
                # a package-set scope (kdePackages) is "used" by every KDE page
                if m and not m.group(1).endswith("Packages"):
                    pkg_decl.setdefault(m.group(1), (p, i))

    unit_uses = {n: re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(n) + r"\.(service|timer|path|socket)\b|"
                               r"(?:services|timers)\.\"?" + re.escape(n) + r"\b")
                 for n in unit_decl if len(n) >= 4}
    pkg_uses = {n: re.compile(r"pkgs\.(?:kdePackages\.)?" + re.escape(n) + r"\b") for n in pkg_decl}
    host_re = re.compile(r"host\s*[!=]=\s*\"(top|air)\"|isx86_64|isAarch64|isDarwin")

    for p in paths:
        pg = pages[idx[p]]
        for i, line in enumerate(pg["lines"], 1):
            hm = host_re.search(line)
            if hm:
                h = hm.group(1) or ("top" if "x86" in hm.group(0) else "air")
                pg["hosts"].append([i, h])
            for m in token.finditer(line):
                tok = m.group(0).rstrip(".")
                if "/" not in tok and not tok.endswith(".nix"):
                    continue
                tgt = resolve(p, tok)
                if tgt:
                    link("path", p, i, tgt, 1, tok)
            for m in re.finditer(r"config\.(my\.[A-Za-z0-9_.]+)", line):
                name = m.group(1)
                for decl, (dp, dl) in opt_decl.items():
                    if name == decl or name.startswith(decl + ".") or decl.startswith(name + "."):
                        link("option", p, i, dp, dl, decl)
            for n, rx in unit_uses.items():
                dp, dl, kind = unit_decl[n]
                if p != dp and rx.search(line):
                    link("unit", p, i, dp, dl, n + "." + kind)
            for tgt, (dp, dl) in file_decl.items():
                if p != dp and tgt in line:
                    link("file", p, i, dp, dl, "~/" + tgt)
            for n, rx in pkg_uses.items():
                dp, dl = pkg_decl[n]
                if p != dp and rx.search(line):
                    link("overlay", p, i, dp, dl, n)

    out = {
        "pages": [{"path": pg["path"], "group": pg["group"], "text": "\n".join(pg["lines"]),
                   "hosts": pg["hosts"]} for pg in pages],
        "links": [{**l, "a": idx[l["a"]], "b": idx[l["b"]]} for l in links.values()],
        "rev": subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True).stdout.strip(),
    }
    with open(os.path.join(HERE, "page.html"), encoding="utf-8") as fh:
        tpl = fh.read()
    data = json.dumps(out, separators=(",", ":")).replace("</", "<\\/")
    html = tpl.replace("/*XANADU_DATA*/null", data)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as fh:
            fh.write(html)
        kinds = defaultdict(int)
        for l in out["links"]:
            kinds[l["k"]] += 1
        print(f"{len(pages)} pages, {len(out['links'])} links {dict(kinds)} -> {sys.argv[1]}",
              file=sys.stderr)
    else:
        sys.stdout.write(html)


if __name__ == "__main__":
    main()
