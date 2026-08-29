#!/usr/bin/env python3
"""Open a folder Dolphin is showing over sftp:// with any local program.

Dolphin's own "Open With" is useless on a remote folder: KIO can download a
FILE to /tmp for an app that only takes paths, but it cannot do that for a
directory, so the menu only ever offers apps that declare X-KDE-Protocols=sftp
-- which on this desktop is nothing. So: sshfs-mount the remote once, translate
the URL to the local path under that mount, and hand THAT to the app the user
picks. From the app's side it is an ordinary directory.

The picker is kdialog (KDE's own, so it matches the rest of the session) listing
every installed .desktop that claims inode/directory, plus a free-text "other
command" row so the answer is genuinely "whichever program you want".

Mounts live at ~/mnt/sftp/<user@host[-port]> and are left up on purpose --
remounting per click costs a full ssh handshake, and `reconnect` survives the
laptop sleeping.
"""

import os
import shlex
import subprocess
import sys
from configparser import RawConfigParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

MNT = Path.home() / "mnt" / "sftp"


def die(msg):
    subprocess.run(["kdialog", "--title", "open with", "--sorry", msg])
    sys.exit(1)


def sshfs_bin():
    # Fedora's own sshfs on book pairs with its setuid fusermount3; prefer it.
    for p in ("/usr/bin/sshfs", "/usr/sbin/sshfs"):
        if os.path.exists(p):
            return p
    return "sshfs"


def mount(user, host, port):
    spec = f"{user}@{host}" if user else host
    tag = f"{spec}-{port}" if port else spec
    point = MNT / tag
    if os.path.ismount(point):
        return point
    point.mkdir(parents=True, exist_ok=True)
    cmd = [sshfs_bin(), f"{spec}:/", str(point),
           "-o", "reconnect,ServerAliveInterval=15,ServerAliveCountMax=3,"
                 "idmap=user,follow_symlinks,dir_cache=yes"]
    if port:
        cmd += ["-p", str(port)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.ismount(point):
        die(f"could not mount {tag}\n\n{(r.stderr or '').strip()}")
    return point


def local_paths(urls):
    point = None
    out = []
    for u in urls:
        s = urlsplit(u)
        if s.scheme != "sftp":
            out.append(unquote(s.path) if s.scheme == "file" else u)
            continue
        if point is None:
            point = mount(s.username, s.hostname, s.port)
        out.append(str(point / unquote(s.path).lstrip("/")))
    return out


def dir_apps():
    seen, apps = set(), []
    dirs = os.environ.get(
        "XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
    dirs = [os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))] + dirs
    for d in dirs:
        p = Path(d) / "applications"
        if not p.is_dir():
            continue
        for f in sorted(p.rglob("*.desktop")):
            if f.name in seen:
                continue
            cp = RawConfigParser(interpolation=None, strict=False)
            try:
                cp.read(f, encoding="utf-8")
                e = cp["Desktop Entry"]
            except Exception:
                continue
            if e.get("Type") != "Application" or e.get("NoDisplay", "").lower() == "true":
                continue
            if "inode/directory" not in e.get("MimeType", ""):
                continue
            seen.add(f.name)
            apps.append((str(f), e.get("Name", f.stem)))
    apps.sort(key=lambda a: a[1].lower())
    return apps


def main():
    urls = sys.argv[1:]
    if not urls:
        die("no folder given")
    apps = dir_apps()
    menu = ["kdialog", "--title", "open with", "--menu", "open the folder with"]
    for path, name in apps:
        menu += [path, name]
    menu += ["!other", "other command…"]
    r = subprocess.run(menu, capture_output=True, text=True)
    if r.returncode != 0:
        return
    choice = r.stdout.strip()
    if not choice:
        return

    paths = local_paths(urls)

    if choice == "!other":
        r = subprocess.run(
            ["kdialog", "--title", "open with", "--inputbox",
             "command (the folder is appended)", "kitty"],
            capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            return
        subprocess.Popen(shlex.split(r.stdout.strip()) + paths,
                         cwd=paths[0], start_new_session=True)
        return

    subprocess.Popen(["gio", "launch", choice] + paths, start_new_session=True)


if __name__ == "__main__":
    main()
