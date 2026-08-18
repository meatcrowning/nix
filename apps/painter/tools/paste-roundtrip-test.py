#!/usr/bin/env python3
"""paste-roundtrip-test.py — does viewer's copy (clipfile --image) round-trip
into painter's REAL QClipboard read, against a real Wayland selection?

The sandbox cannot answer this: `sandbox-never-takes-the-seat` gives a sandbox
window `no_focus`, and Qt only delivers a Wayland selection to the focused
surface — so a paste probe launched there reads an empty clipboard and proves
nothing. Prior spirits verified the COPY side with `wl-paste` (clipfile-test.sh)
but nobody exercised painter's actual `_clipboard_offer` path against a real
selection with a focused window until this.

So the whole thing happens inside a HEADLESS sway: no output, no window, its own
seat and clipboard, on a scratch XDG_RUNTIME_DIR — his session is unreachable by
construction (the same isolation clipfile-test.sh uses).

    python3 apps/painter/tools/paste-roundtrip-test.py FILE.png|jpg|...
    # exit 0 = a real clipfile --image copy reads back through painter's
    # QClipboard as a file URI (hasUrls) whose local path is the file, with the
    # image offer decoding too. exit 1 = something failed.

Usage inside the repo, any python (stdlib + subprocess); the Qt reader re-execs
under painter's own wrapper python so the imageformat plugins are present.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLIPFILE = (HERE.parent.parent / "pylib" / "clipfile.py").resolve()

READER = """\
import os, sys
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickWindow
from PySide6.QtCore import QTimer
app = QGuiApplication(sys.argv)
win = QQuickWindow(); win.setTitle("paste-reader"); win.resize(200,100)
win.show(); win.requestActivate()
def go():
    md = QGuiApplication.clipboard().mimeData()
    urls = [u.toLocalFile() for u in md.urls()] if md.hasUrls() else []
    img = QGuiApplication.clipboard().image() if md.hasImage() else None
    print("HASURLS=%s" % md.hasUrls(), flush=True)
    print("URLS=%r" % urls, flush=True)
    print("HASIMAGE=%s" % md.hasImage(), flush=True)
    print("IMG=%sx%s null=%s" % (
        img.width() if img else 0, img.height() if img else 0,
        True if img is None or img.isNull() else False), flush=True)
    print("HASTEXT=%s" % md.hasText(), flush=True)
    app.exit(0 if md.hasUrls() and urls else 1)
QTimer.singleShot(2000, go)
app.exec()
"""


def _sway_bin():
    for p in os.listdir("/nix/store"):
        cand = "/nix/store/" + p + "/bin/sway"
        if p.endswith("-sway-1.12") and os.path.exists(cand):
            return cand
    return "sway"  # fall back to PATH


def _borrow_painter_env():
    import re, shutil
    wrapper = shutil.which("painter")
    if not wrapper:
        raise SystemExit("no painter wrapper on PATH")
    text = Path(os.path.realpath(wrapper)).read_text(errors="replace")
    m = re.search(r'(/nix/store/\S+?/bin/python3)"?\s+\S*main\.py', text)
    if not m:
        raise SystemExit("no main.py interpreter in painter wrapper")
    py = m.group(1)
    body = "\n".join(ln for ln in text.splitlines()
                     if not ln.startswith("#!")
                     and "singleton.py" not in ln
                     and not ln.startswith("exec "))
    out = subprocess.run(["bash", "-c", body + "\nexec env -0\n"],
                         capture_output=True, check=True).stdout
    env = {}
    for entry in out.split(b"\0"):
        if not entry or b"=" not in entry:
            continue
        k, v = entry.decode(errors="replace").split("=", 1)
        if k in ("HOME", "PWD", "SHLVL", "_"):
            continue
        env[k] = v
    return py, env


def main():
    src = os.path.abspath(sys.argv[1])
    if not os.path.isfile(src):
        print("no such file:", src)
        return 2
    run = tempfile.mkdtemp(prefix="ptest-")
    cfg = os.path.join(run, "config")
    with open(cfg, "w") as f:
        f.write("exec true\n")
    env = dict(os.environ)
    for k in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "DISPLAY"):
        env.pop(k, None)
    env.update({"XDG_RUNTIME_DIR": run, "WLR_BACKENDS": "headless",
                "WLR_LIBINPUT_NO_DEVICES": "1"})
    sway = subprocess.Popen([_sway_bin(), "-c", cfg], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    failed = 1
    try:
        wl = None
        for _ in range(100):
            time.sleep(0.2)
            for s in Path(run).glob("wayland-*"):
                if s.is_socket():
                    wl = s.name
                    break
            if wl and sway.poll() is None:
                break
        if not wl or sway.poll() is not None:
            print("FAIL sway never came up (rc=%s)" % sway.poll())
            return 1
        nenv = dict(env, XDG_RUNTIME_DIR=run, WAYLAND_DISPLAY=wl)

        r = subprocess.run([sys.executable, str(CLIPFILE), "--image", src],
                           env=nenv, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            print("FAIL clipfile copy:", r.stderr.strip())
            return 1
        print("ok  clipfile --image copies %s" % os.path.basename(src))

        types = subprocess.run(["wl-paste", "--list-types"], env=nenv,
                               capture_output=True, text=True, timeout=15)
        for want in ("text/uri-list", "image/"):
            if want not in types.stdout:
                print("FAIL wl-paste offer missing %r: %r"
                      % (want, types.stdout))
                return 1
        print("ok  selection offers text/uri-list + image/*")

        py, penv = _borrow_painter_env()
        penv.pop("WAYLAND_DISPLAY", None)
        penv.pop("DISPLAY", None)
        penv["XDG_RUNTIME_DIR"] = run
        penv["WAYLAND_DISPLAY"] = wl
        reader = os.path.join(run, "reader.py")
        with open(reader, "w") as f:
            f.write(READER)
        r2 = subprocess.run([py, reader], env=penv, capture_output=True,
                            text=True, timeout=30)
        print("--- reader stdout ---")
        print(r2.stdout)
        if r2.returncode != 0:
            print("FAIL painter's QClipboard read rejected the selection")
            print("--- reader stderr ---")
            print(r2.stderr)
            return 1
        ok_urls = any(line.startswith("URLS=") and src in line
                      for line in r2.stdout.splitlines())
        ok_img = any(line.startswith("IMG=") and "null=False" in line
                     for line in r2.stdout.splitlines())
        if not ok_urls or not ok_img:
            print("FAIL the selection did not read back as this file + pixels")
            return 1
        print("ok  painter's QClipboard read resolves %s as a file + pixels"
              % os.path.basename(src))
        failed = 0
        return 0
    finally:
        sway.terminate()
        try:
            sway.wait(timeout=5)
        except subprocess.TimeoutExpired:
            sway.kill()
        for f in Path(run).glob("wayland-*"):
            f.unlink()
        if failed:
            print("artifacts in", run)


if __name__ == "__main__":
    sys.exit(main())
