#!/usr/bin/env python3
"""action-menu-test — the reworked "compress to..." / "convert to..." menus.

Offscreen, no window on anyone's screen. Loads the real Main.qml and drives
BrowserPane's menu builders:

  * "compress to..." is ONE row that opens a submenu of the video size-squeezes
    (single clicked video) plus the archive formats the machine actually has;
  * "convert to..." is the video-format transcodes;
  * both submenus list only what can run — no format that would silently fail.

It also runs the archive.py and videoconv.py backends against a real clip and a
real file, so the "wire up any newly-offered format" half is proven end to end,
not just labelled. Titlebar is stubbed (the real one talks to the hyprvtb
socket, which would register buttons against this harness's pid).
"""
import os
import subprocess
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

FILER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FILER)
sys.path.insert(0, os.path.join(os.path.dirname(FILER), "pylib"))
from deskstyle import DeskStyle  # noqa: E402

from PySide6.QtCore import QUrl, QObject, Slot  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QJSValue  # noqa: E402

import main as filermain  # noqa: E402
import archive as A  # noqa: E402
import videoconv as V  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(name)


def unwrap(v):
    return v.toVariant() if isinstance(v, QJSValue) else v


def find(root, prop):
    for ch in root.children():
        try:
            if ch.property(prop) is not None:
                return ch
        except RuntimeError:
            pass
        hit = find(ch, prop)
        if hit is not None:
            return hit
    return None


class StubTitlebar(QObject):
    @Slot("QVariantList")
    def setButtons(self, b): pass
    @Slot(str)
    def setFooter(self, t): pass
    @Slot(bool)
    def setTitleEdit(self, on): pass


def spin(ms=150):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


_KEEP = []   # setContextProperty does NOT take ownership; a dropped Python ref
             # is GC'd and the QML call then hits a dead C++ object (VideoConv
             # .isVideo threw exactly that way here, silently emptying the menu).


def _cp(ctx, name, obj):
    _KEEP.append(obj)
    ctx.setContextProperty(name, obj)
    return obj


def build(app, start_dir):
    engine = QQmlApplicationEngine()
    _KEEP.append(engine)
    ctx = engine.rootContext()
    _cp(ctx, "FileOps", filermain.FileOps())
    _cp(ctx, "Remote", filermain.Remote())
    _cp(ctx, "ImgConv", filermain.ImgConv())
    _cp(ctx, "ArchiveConv", filermain.ArchiveConv())
    _cp(ctx, "WalPalette", filermain.Palette(filermain.PANEL_THEME))
    _cp(ctx, "DeskStyle", DeskStyle())
    _cp(ctx, "Settings", filermain.Settings())
    _cp(ctx, "DirWatch", filermain.DirWatch())
    _cp(ctx, "MetaSearch", filermain.MetaSearch())
    _cp(ctx, "WinCtl", filermain.WinCtl())
    _cp(ctx, "VideoConv", filermain.VideoConv())
    _cp(ctx, "Titlebar", StubTitlebar())
    _cp(ctx, "Picker", filermain.Picker(None))
    _cp(ctx, "Phone", filermain.Phone())
    ctx.setContextProperty("startDir", start_dir)
    ctx.setContextProperty("startSortField", "name")
    ctx.setContextProperty("startSortAsc", True)
    ctx.setContextProperty("startShowHidden", True)
    ctx.setContextProperty("startGridPanelH", 200)
    ctx.setContextProperty("startSplit", False)
    ctx.setContextProperty("startSplitDir", "")
    ctx.setContextProperty("startSplitRatio", 0.5)
    ctx.setContextProperty("startSplitVertical", True)
    comp = QQmlComponent(engine, QUrl.fromLocalFile(os.path.join(FILER, "qml/theme/Theme.qml")))
    theme = comp.create()
    if theme is None:
        raise SystemExit("Theme.qml failed: " + comp.errorString())
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)
    engine.load(QUrl.fromLocalFile(os.path.join(FILER, "qml/Main.qml")))
    roots = engine.rootObjects()
    if not roots:
        raise SystemExit("Main.qml failed to load")
    return engine, roots[0]


def labels(items):
    return [i.get("label") for i in (items or [])]


def make_clip(path):
    ff = V._tool("ffmpeg")
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc=size=160x120:rate=15:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:v", "libx264", "-c:a", "aac", "-shortest", path], check=True)


def main():
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on %r, not offscreen" % app.platformName())

    tmp = tempfile.mkdtemp(prefix="t_actmenu-")
    clip = os.path.join(tmp, "clip.mkv")
    txt = os.path.join(tmp, "note.txt")
    make_clip(clip)
    open(txt, "w").write("hello\n")

    engine, win = build(app, tmp)
    view = find(win, "dropTarget")
    check("Main.qml loads", view is not None)
    win.show()
    spin(200)

    vid = {"path": clip, "isDir": False, "kind": "video", "size": os.path.getsize(clip)}
    doc = {"path": txt, "isDir": False, "kind": "file", "size": os.path.getsize(txt)}

    # ---- entry menu: one "compress to...", "convert to..." only for video ----
    view.setProperty("selection", [clip])
    top = labels(unwrap(view.entryMenuItems(vid)))
    check("exactly one 'compress to...' row (the two squeezes collapsed)",
          top.count("compress to...") == 1, top)
    check("no bare 'compress to <10MB>'/'<4MB>' left at top level",
          not any(l and ("<10MB" in l or "<4MB" in l) for l in top), top)
    check("a 'convert to...' row is offered for a video", "convert to..." in top, top)
    check("'copy without audio' is still there", "copy without audio" in top, top)

    view.setProperty("selection", [txt])
    topd = labels(unwrap(view.entryMenuItems(doc)))
    check("a non-video still gets 'compress to...' (archives apply to anything)",
          "compress to..." in topd, topd)
    check("a non-video gets NO 'convert to...'", "convert to..." not in topd, topd)

    # ---- the compress submenu: squeezes (single video) + archive formats ----
    view.setProperty("selection", [clip])
    sub = labels(unwrap(view.compressMenuItems(vid)))
    check("compress submenu offers the 10MB squeeze", "under 10MB" in sub, sub)
    check("compress submenu offers the 4MB squeeze", "under 4MB" in sub, sub)
    for fmt in A.available_formats():
        check("compress submenu offers archive %s" % fmt["label"],
              fmt["label"] in sub, sub)
    check("tar.gz is one of them (tar is always present)", "tar.gz" in sub, sub)

    view.setProperty("selection", [txt])
    subd = labels(unwrap(view.compressMenuItems(doc)))
    check("a non-video's compress submenu has no size-squeeze rows",
          "under 10MB" not in subd and "under 4MB" not in subd, subd)
    check("...but does offer archive formats", "tar.gz" in subd, subd)

    view.setProperty("selection", [clip, txt])
    subm = labels(unwrap(view.compressMenuItems(vid)))
    check("a multi-selection drops the size-squeeze rows", "under 10MB" not in subm, subm)
    check("...and the archive rows carry the (2) count",
          any(l and l.endswith("(2)") for l in subm), subm)

    # ---- convert formats: only what ffmpeg can make, and all valid ----
    conv = [f["id"] for f in V.convert_formats()]
    for want in ("mp4", "webm", "mkv", "gif", "mp3"):
        check("convert offers %s" % want, want in conv, conv)

    # ---- backends actually produce valid files ----
    ap = A.out_path_for([clip], "tar.gz")
    r = subprocess.run(A._spec("tar.gz")["argv"](ap, ["clip.mkv"]), cwd=tmp)
    check("archive tar.gz builds a real file", r.returncode == 0 and os.path.exists(ap))

    for fmt in ("mp4", "webm", "gif", "mp3"):
        out = V.convert_out_path(clip, fmt)
        r = subprocess.run(V.convert_argv(clip, out, fmt), capture_output=True, text=True)
        ok = r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0
        check("convert to %s builds a real file" % fmt, ok, r.stderr[-120:] if not ok else "")

    print()
    if FAILS:
        print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    print("all action-menu checks passed")


if __name__ == "__main__":
    main()
