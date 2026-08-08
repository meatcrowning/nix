#!/usr/bin/env python3
"""surfer — minimal Qt/QML web browser for the `top` desktop.

filer's sibling: same PySide6 + QML + wal-palette stack, but the content area
is QtWebEngine — i.e. open Chromium, the same engine Vivaldi wraps — with the
browser chrome living in the hyprvtb titlebar's app-button column instead of
a toolbar (back/forward/reload/tab buttons in the REAL compositor titlebar).

In-window chrome is just one header row: an address bar with ghost scheme
handling (bare words search DuckDuckGo, host-ish strings get https://) and a
pixel-font tab strip. Everything else is the page.

Host support mirrors filer (home/prog/surfer.nix): on air this runs the
SYSTEM python3 + Fedora's python3-pyside6 (nixpkgs Mesa has no Apple Silicon
GBM driver), on top the nixpkgs build.
"""
import base64
import hashlib
import io
import json
import os
import re
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

# ---- single instance, BEFORE anything expensive -----------------------------
# surfer is the system default browser, so every link clicked elsewhere runs
# `surfer <url>` — and Main.qml's persistent WebEngineProfile can only be owned
# by ONE process. If a surfer is already up, hand it the URL and exit right
# here: `singleton` is stdlib-only and Qt-free precisely so this path never pays
# for importing PySide6 or initializing Chromium. Every failure inside it means
# "carry on and launch normally". See apps/surfer/singleton.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import singleton  # noqa: E402

if __name__ == "__main__":
    singleton.try_handoff(sys.argv[1:])   # exits 0 if a running surfer took it

from PySide6.QtCore import (QObject, Slot, Signal, QUrl, QFileSystemWatcher, Property,
                            QBuffer, QIODevice, QEvent, Qt, QPoint, QCoreApplication)
from PySide6.QtGui import QGuiApplication, QColor, QWheelEvent
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from PySide6.QtWebEngineCore import (QWebEngineScript, QWebEngineUrlScheme,
                                     QWebEngineUrlSchemeHandler, QWebEnginePermission,
                                     QWebEngineUrlRequestInterceptor, QWebEngineUrlRequestInfo,
                                     QWebEngineUrlRequestJob, QWebEngineProfile)
from PySide6.QtNetwork import (QNetworkAccessManager, QNetworkRequest,
                               QLocalServer)

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

# True on air/book, where surfer runs Fedora's system python3 + python3-pyside6
# (nixpkgs Mesa has no Apple Silicon GBM driver); False on top, which runs the
# nixpkgs build. The GPU workarounds below are air's alone.
ON_AIR = os.path.realpath(sys.executable).startswith("/usr/")

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402
from deskstyle import DeskStyle  # noqa: E402  (pylib; the desktop-wide font setting)
from kinetic import (WHEEL_GAIN, QML_WHEEL_GAIN,  # noqa: E402
                     is_wheel_detent as _is_wheel_detent)

# Same live wallpaper palette source filer parses (rewritten by wal-set.sh).
PANEL_THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"
PALETTE_KEYS = ["bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
                "highlight", "ok", "warn", "crit", "info"]
PALETTE_DEFAULTS = {
    "bg": "#000000", "bgAlt": "#120b08", "border": "#382216", "accent": "#cc4400",
    "dim": "#54382a", "text": "#cc4400", "textDim": "#8c5438", "highlight": "#21140d",
    "ok": "#e08e65", "warn": "#b86237", "crit": "#fa5c0c", "info": "#ad7457",
}


class Palette(QObject):
    """Live wallpaper palette — same parser/watcher as filer's (see
    ~/nix/apps/filer/main.py for the full commentary)."""

    changed = Signal()

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = str(path)
        self._colors = dict(PALETTE_DEFAULTS)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)
        d = os.path.dirname(self._path)
        if os.path.isdir(d):
            self._watcher.addPath(d)
        self._rewatch()
        self._load()

    def _rewatch(self):
        if os.path.exists(self._path) and self._path not in self._watcher.files():
            self._watcher.addPath(self._path)

    def _on_change(self, _):
        self._rewatch()
        self._load()

    def _load(self):
        try:
            txt = open(self._path, encoding="utf-8").read()
        except OSError:
            return
        colors = dict(self._colors)
        for m in re.finditer(r'property\s+color\s+(\w+)\s*:\s*"(#[0-9a-fA-F]{3,8})"', txt):
            name, val = m.group(1), m.group(2)
            if name in PALETTE_KEYS:
                colors[name] = val
        if colors != self._colors:
            self._colors = colors
            self.changed.emit()

    def _c(self, k):
        return QColor(self._colors.get(k, PALETTE_DEFAULTS[k]))

    def hex(self, k):
        """The raw '#rrggbb' string for a palette key (for callers building CSS,
        e.g. DarkMode's system-style override)."""
        return self._colors.get(k, PALETTE_DEFAULTS[k])

    @Property(QColor, notify=changed)
    def bg(self): return self._c("bg")
    @Property(QColor, notify=changed)
    def bgAlt(self): return self._c("bgAlt")
    @Property(QColor, notify=changed)
    def border(self): return self._c("border")
    @Property(QColor, notify=changed)
    def accent(self): return self._c("accent")
    @Property(QColor, notify=changed)
    def dim(self): return self._c("dim")
    @Property(QColor, notify=changed)
    def text(self): return self._c("text")
    @Property(QColor, notify=changed)
    def textDim(self): return self._c("textDim")
    @Property(QColor, notify=changed)
    def highlight(self): return self._c("highlight")
    @Property(QColor, notify=changed)
    def ok(self): return self._c("ok")
    @Property(QColor, notify=changed)
    def warn(self): return self._c("warn")
    @Property(QColor, notify=changed)
    def crit(self): return self._c("crit")
    @Property(QColor, notify=changed)
    def info(self): return self._c("info")


class Titlebar(QObject):
    """hyprvtb app-button bridge. QML pushes button sets; the titlebar sends
    back four things, each bounced through a Qt signal (queued across the
    VtbClient I/O thread onto the GUI thread before any UI is touched):
      clicked(id)          a button was clicked
      reordered(src, dst)  a draggable tab button was dropped on another's slot
      addrSubmitted(text)  the in-bar address editor was submitted (Enter)
      wake()               the window was un-hidden (roll-up restore) — a cue to
                           repaint (QtWebEngine blacks out after a hide)."""

    clicked = Signal(str)
    reordered = Signal(str, str)
    addrSubmitted = Signal(str)
    wake = Signal()

    # Born-correct chrome, sent BEFORE engine.load so the plugin has this pid's
    # registration in g_regs long before the window maps — otherwise the window
    # surfaces at the plugin's default bar (window title, no buttons, no address
    # editor) for the frames between map and the first QML setButtons, which is
    # the startup titlebar flash. The socket connects within microseconds of the
    # thread starting, so this REGISTER (address-bar flag riding in the same
    # write) is on the wire before QtWebEngine has even spun up. qml/Main.qml's
    # tbButtons is the source of truth; this is only the frame-0 seed and QML
    # refines it (real tab buttons, live enabled/disabled states) on the same load.
    _SEED_BUTTONS = [
        ("back",    "<",  2, "back",     False, False),
        ("fwd",     ">",  2, "forward",  False, False),
        ("reload",  "r",  0, "reload",   False, False),
        ("copyurl", "cu", 2, "copy url", False, False),
        ("darkmode", "dm", 0, "dark mode", False, False),
        ("vsplit",  "|",  0, "split right", False, False),
        ("hsplit",  "_",  0, "split down",  False, False),
        "-",
        ("newtab",  "+t", 0, "new tab",  False, False),
        ("settings", "st", 0, "userscripts folder / settings", False, True),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        # Seed the REGISTER (chrome + address-bar flag) into the client before its
        # I/O thread starts, so it lands as one atomic write on the first connect,
        # before the window maps — see _SEED_BUTTONS.
        self._client = VtbClient(
            on_click=self.clicked.emit,
            on_reorder=lambda s, d: self.reordered.emit(s, d),
            on_addr=self.addrSubmitted.emit,
            on_wake=self.wake.emit,
            buttons=self._SEED_BUTTONS,
            title_edit=True,
        )

    @Slot("QVariantList")
    def setButtons(self, buttons):
        out = []
        for b in buttons:
            if isinstance(b, str):
                out.append("-")
            else:
                out.append((str(b["id"]), str(b["label"]), int(b.get("state", 0)),
                            str(b.get("tip", "")), bool(b.get("drag", False)),
                            bool(b.get("bottom", False))))
        self._client.set_buttons(out)

    @Slot(str)
    def setFooter(self, text):
        self._client.set_footer(text)

    @Slot(bool)
    def setTitleEdit(self, on):
        """Mark the stacked title (the outer column) an editable address bar."""
        self._client.set_title_edit(on)

    @Slot(bool)
    def setLoading(self, on):
        """Page loading — the plugin draws a spinner above the address bar."""
        self._client.set_loading(on)


class Clip(QObject):
    """Clipboard access for the 'copy url' titlebar button."""

    @Slot(str)
    def copy(self, text):
        QGuiApplication.clipboard().setText(text)


class Perm(QObject):
    """Turns a QWebEnginePermission.PermissionType enum (passed from QML as a
    plain int) into human wording for the in-window grant/deny prompt. Done in
    Python so the mapping keys off the real enum instead of QML enum-name
    guesswork."""

    @Slot(int, result=str)
    def what(self, t):
        PT = QWebEnginePermission.PermissionType
        return {
            PT.Notifications.value:            "show notifications",
            PT.Geolocation.value:              "know your location",
            PT.MediaAudioCapture.value:        "use your microphone",
            PT.MediaVideoCapture.value:        "use your camera",
            PT.MediaAudioVideoCapture.value:   "use your camera & microphone",
            PT.DesktopVideoCapture.value:      "capture your screen",
            PT.DesktopAudioVideoCapture.value: "capture your screen & audio",
            PT.ClipboardReadWrite.value:       "read your clipboard",
            PT.LocalFontsAccess.value:         "see your installed fonts",
            PT.MouseLock.value:                "lock your mouse pointer",
        }.get(int(t), "use a browser feature")


class Notifier(QObject):
    """Presents web notifications on the desktop. Connected to the QML profile's
    presentNotification signal (see main() — the QML QQuickWebEngineProfile has
    no setNotificationPresenter, but it DOES emit this signal, which is the
    equivalent hook). Each granted `new Notification(...)` from a page lands
    here; we relay it to notify-send so it renders as a normal wal-themed toast
    through the same Quickshell notification server everything else uses."""

    def _icon_path(self, n):
        # web notifications often carry an icon (QImage); dump it to a reused
        # temp PNG for notify-send's -i. Fully optional — any failure omits it.
        try:
            img = n.icon()
            if img is None or img.isNull():
                return None
            p = os.path.join(tempfile.gettempdir(), "surfer-notif-icon.png")
            return p if img.save(p, "PNG") else None
        except Exception:
            return None

    def present(self, n):
        try:
            n.show()  # tell the page it was displayed (fires its onshow)
        except Exception:
            pass
        args = ["notify-send", "-a", "surfer"]
        icon = self._icon_path(n)
        if icon:
            args += ["-i", icon]
        args += [n.title() or "surfer", n.message() or ""]
        try:
            subprocess.Popen(args)
        except OSError:
            pass


# The image extensions whose completion toast carries a thumbnail and
# click-to-open (surfer/main.py). Mirrors filer/main.py IMAGE_EXTS so anything
# filer would preview - and viewer would open - gets the same treatment.
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
              ".avif", ".jxl", ".tif", ".tiff", ".ico", ".ppm", ".pgm"}


def _is_image(name):
    return os.path.splitext(name or "")[1].lower() in IMAGE_EXTS


# Content-Type -> the extension a human expects. `mimetypes.guess_extension`
# is the fallback but is not usable alone: it answers ".jpe" for image/jpeg and
# ".htm" for text/html on some tables, which is technically right and useless.
MIME_EXTS = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
    "image/webp": ".webp", "image/avif": ".avif", "image/jxl": ".jxl",
    "image/bmp": ".bmp", "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico",
    "image/svg+xml": ".svg", "image/tiff": ".tif", "image/apng": ".apng",
    "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
    "audio/mpeg": ".mp3", "audio/ogg": ".ogg", "audio/wav": ".wav",
    "audio/flac": ".flac", "audio/mp4": ".m4a",
    "application/pdf": ".pdf", "application/zip": ".zip",
    "application/gzip": ".gz", "application/json": ".json",
    "text/plain": ".txt", "text/html": ".html", "text/css": ".css",
}


def _looks_like_ext(suffix):
    """Is this trailing `.xxx` an extension, or just a dot in the name?
    `pbs.twimg.com`-style ids and version strings ("clip.v2") should not be
    mistaken for a typed file."""
    s = (suffix or "").lstrip(".")
    return bool(s) and len(s) <= 5 and s.isalnum()


def _ext_for_mime(mime):
    mime = (mime or "").split(";")[0].strip().lower()
    if not mime or mime == "application/octet-stream":
        return ""      # the server said nothing useful — don't invent a type
    if mime in MIME_EXTS:
        return MIME_EXTS[mime]
    import mimetypes
    return mimetypes.guess_extension(mime) or ""


class Downloads(QObject):
    """Desktop toasts for downloads, driven from Main.qml's onDownloadRequested.
    A SLOW or LARGE download gets a live progress toast that updates IN PLACE
    (notify-send --replace-id) with a CP437 block bar in the body — which the
    pixel DOS font renders as a real bar; every download gets a completion (or
    failure) toast. The progress toast is sent expire-never (-t 0) so it
    survives the gaps between updates — see _send. Keyed by an opaque
    per-download string from QML.

    The decision to show a progress toast at all lives here, not in QML, so it
    is testable. DESIGN 10.4 is about a download that takes TIME ("longer
    downloads ... stay on the screen until they are finished"), which is why
    the gate is duration-aware: a download that has run SLOW_MS or longer gets
    a live toast even when it is small (a small file on a slow connection waits
    just as long), while a fast download of any size is left to its single
    completion toast rather than a useless flash. LARGE_BYTES keeps the
    size-only trigger for genuinely big transfers regardless of speed."""

    LARGE_BYTES = 3 * 1024 * 1024   # a download this big toasts on size alone
    SLOW_MS = 1500.0                # ...or one that has run this long (time)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ids = {}    # key -> notify-send notification id (for --replace-id)
        self._pct = {}    # key -> last percent shown (throttle to whole-% steps)

    @staticmethod
    def _human(b):
        b = float(b)
        for u in ("B", "K", "M", "G"):
            if b < 1024 or u == "G":
                return "%dB" % b if u == "B" else "%.1f%s" % (b, u)
            b /= 1024

    @staticmethod
    def _bar(pct, width=16):
        fill = int(round(pct / 100.0 * width))
        return "█" * fill + "░" * (width - fill)  # █ filled / ░ empty

    def _send(self, key, title, body, value, persist=False, path=None):
        # -p prints the notification id so we can --replace-id (-r) it next time,
        # morphing one toast in place instead of stacking a new one per update.
        #
        # -t 0 (never expire) on the PROGRESS toast is what makes that work for a
        # long download. The server retires an ordinary toast after a few seconds,
        # and once it is gone our -r names an id it no longer has — so it opens a
        # brand new toast, with its own sound, on every whole percent. The
        # completion/failure toast deliberately keeps the default timeout: it has
        # nothing left to update and should behave like any other toast.
        args = ["notify-send", "-a", "surfer", "-p"]
        if persist:
            args += ["-t", "0"]
        rid = self._ids.get(key)
        if rid is not None:
            args += ["-r", str(rid)]
        if value is not None:
            args += ["-h", "int:value:%d" % int(value)]
        if path:
            # Which file this toast is about, for the panel: it renders a
            # thumbnail and clicking the toast opens it in the viewer.
            args += ["-h", "string:x-download-image:" + path]
        args += [title, body]
        try:
            out = subprocess.run(args, capture_output=True, text=True, timeout=2)
            nid = out.stdout.strip()
            if nid.isdigit():
                self._ids[key] = int(nid)
        except Exception:
            pass

    def _wants_progress(self, total, elapsed_ms):
        """Would a live progress toast help yet? Size alone for big transfers,
        or TIME for anything that has run long — even a small file on a slow
        connection waits visibly (DESIGN 10.4)."""
        if total > self.LARGE_BYTES:
            return True
        return elapsed_ms >= self.SLOW_MS

    @Slot(str, str, result=str)
    def fileName(self, suggested, mime):
        """The name to save under, given what QtWebEngine suggested.

        Chromium derives `downloadFileName` from the URL PATH alone, so a host
        that serves images from an extensionless path with the type in the
        query — `pbs.twimg.com/media/<id>?format=jpg&name=large`, i.e. every
        image saved from twitter — lands as a bare id with no extension, which
        no image viewer or thumbnailer will touch. Chrome itself repairs this
        from the Content-Type; we do the same, and only when the suggested name
        has no plausible extension of its own, so a correctly-named download is
        never second-guessed."""
        name = (suggested or "").strip() or "download"
        if _looks_like_ext(os.path.splitext(name)[1]):
            return name
        return name + _ext_for_mime(mime)

    @Slot(str, str, float, float, float)
    def progress(self, key, name, received, total, elapsed_ms=0.0):
        if total <= 0:
            return  # no denominator → no honest bar
        shown = key in self._pct
        if not shown and not self._wants_progress(total, elapsed_ms):
            return  # too fast AND too small — a toast would only flash
        pct = int(received * 100 / total)
        if shown and self._pct.get(key) == pct:
            return  # throttle: only re-toast on a whole-percent change
        self._pct[key] = pct
        body = "%s %d%%\n%s / %s" % (self._bar(pct), pct,
                                     self._human(received), self._human(total))
        self._send(key, "downloading " + name, body, pct, persist=True)

    @Slot(str, str, str)
    def done(self, key, name, path=""):
        # Only an image completion carries the path hint: the panel shows its
        # thumbnail and clicking the toast opens it in the viewer (filer/viewer
        # open images; a PDF or zip has neither behaviour).
        img = path if _is_image(path) else None
        self._send(key, "download complete", name, 100, path=img)
        self._ids.pop(key, None)
        self._pct.pop(key, None)

    @Slot(str, str)
    def failed(self, key, name):
        self._send(key, "download failed", name, None)
        self._ids.pop(key, None)
        self._pct.pop(key, None)


# A pragmatic GreaseMonkey API shim, prepended to every userscript so real GM
# scripts (4chan X, OneeChan, …) run. GM values are backed by the page's
# localStorage (per-origin, persisted in the profile). GM_xmlhttpRequest is a
# fetch shim — it CANNOT bypass CORS the way a real manager does, so a script's
# cross-origin calls only work where the remote sends CORS headers. `__ns`,
# `__name`, `__ver` are declared per-script before this blob.
_GM_SHIM = r"""
var __gmkey = function(k){ return "__gm__"+__ns+"__"+k; };
var __gmlisteners = {};
function GM_getValue(k, d){ try{ var v = window.localStorage.getItem(__gmkey(k)); return v===null? d : JSON.parse(v); }catch(e){ return d; } }
function GM_setValue(k, v){ var old; try{ old = GM_getValue(k); }catch(e){}
  try{ window.localStorage.setItem(__gmkey(k), JSON.stringify(v)); }catch(e){}
  var ls = __gmlisteners[k]; if(ls){ for(var i=0;i<ls.length;i++){ try{ ls[i](k, old, v, false); }catch(e){} } } }
function GM_deleteValue(k){ try{ window.localStorage.removeItem(__gmkey(k)); }catch(e){} }
function GM_listValues(){ var out=[]; var pre="__gm__"+__ns+"__"; try{ for(var i=0;i<window.localStorage.length;i++){ var kk=window.localStorage.key(i); if(kk && kk.indexOf(pre)===0) out.push(kk.slice(pre.length)); } }catch(e){} return out; }
function GM_addValueChangeListener(k, fn){ (__gmlisteners[k]=__gmlisteners[k]||[]).push(fn); return k+":"+(__gmlisteners[k].length-1); }
function GM_removeValueChangeListener(id){}
function GM_addStyle(css){ var s=document.createElement("style"); s.textContent=css; (document.head||document.documentElement||document).appendChild(s); return s; }
function GM_openInTab(url, opts){ try{ return window.open(url, "_blank"); }catch(e){ return null; } }
function GM_setClipboard(text){ try{ navigator.clipboard.writeText(text); }catch(e){} }
function GM_xmlhttpRequest(o){
  // Routed through the gmxhr:// scheme -> Python does the real request outside
  // the page's origin (no CORS block). SCOPED: only this reaches Python; normal
  // page fetches stay CORS-guarded. The reply is a JSON envelope (body base64).
  o = o||{};
  var spec = { url:o.url, method:(o.method||"GET"), headers:(o.headers||{}), data:(o.data!=null?String(o.data):null) };
  var b64 = btoa(unescape(encodeURIComponent(JSON.stringify(spec)))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
  var ctrl = new AbortController();
  fetch('gmxhr://gm/'+b64, {signal:ctrl.signal}).then(function(r){ return r.text(); }).then(function(txt){
    var env; try{ env=JSON.parse(txt); }catch(e){ if(o.onerror) o.onerror({error:'gmxhr bad envelope', status:0, readyState:4}); return; }
    if(env.__error){ if(o.onerror) o.onerror({error:env.__error, status:0, readyState:4}); return; }
    var bytes = Uint8Array.from(atob(env.body||''), function(c){ return c.charCodeAt(0); });
    var resp = { readyState:4, status:env.status, statusText:env.statusText||'', finalUrl:env.finalUrl||o.url, responseHeaders:env.headers||'' };
    var rt = o.responseType;
    if(rt==="arraybuffer"){ resp.response=bytes.buffer; resp.responseText=""; }
    else if(rt==="blob"){ resp.response=new Blob([bytes]); resp.responseText=""; }
    else { var text=new TextDecoder('utf-8').decode(bytes);
      if(rt==="json"){ try{ resp.response=JSON.parse(text); }catch(e){ resp.response=null; } resp.responseText=text; }
      else { resp.response=text; resp.responseText=text; } }
    if(o.onload) o.onload(resp);
  }).catch(function(e){ if(o.onerror) o.onerror({error:String(e), status:0, readyState:4}); });
  return { abort:function(){ try{ctrl.abort();}catch(e){} } };
}
var unsafeWindow = window;
var GM_info = { script:{ name:__name, version:__ver, namespace:__ns }, scriptHandler:"surfer", version:"0.1" };
var GM = {
  getValue:function(k,d){ return Promise.resolve(GM_getValue(k,d)); },
  setValue:function(k,v){ return Promise.resolve(GM_setValue(k,v)); },
  deleteValue:function(k){ return Promise.resolve(GM_deleteValue(k)); },
  listValues:function(){ return Promise.resolve(GM_listValues()); },
  openInTab:function(u,o){ return GM_openInTab(u,o); },
  xmlHttpRequest:GM_xmlhttpRequest, setClipboard:GM_setClipboard, addStyle:GM_addStyle, info:GM_info
};
// Also expose the GM_* API on window: some scripts feature-detect via
// window.GM_xmlhttpRequest (4chan X uses it to tell userscript from a Chrome
// extension — without it, it tries chrome.runtime.getManifest() and dies).
// Actual storage calls stay bare/lexical (per-script namespace); these are for
// detection and cross-script use.
try {
  var __W = window;
  __W.GM_getValue=GM_getValue; __W.GM_setValue=GM_setValue; __W.GM_deleteValue=GM_deleteValue;
  __W.GM_listValues=GM_listValues; __W.GM_addValueChangeListener=GM_addValueChangeListener;
  __W.GM_removeValueChangeListener=GM_removeValueChangeListener; __W.GM_addStyle=GM_addStyle;
  __W.GM_openInTab=GM_openInTab; __W.GM_setClipboard=GM_setClipboard;
  __W.GM_xmlhttpRequest=GM_xmlhttpRequest; __W.GM_info=GM_info; if(!__W.GM) __W.GM=GM;
} catch(e){}
"""


def _b64url_decode(s):
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode("ascii"))


class GmXhrHandler(QWebEngineUrlSchemeHandler):
    """Serves ``gmxhr://gm/<b64url spec>`` — the SCOPED CORS bypass for
    userscripts' GM_xmlhttpRequest. The page's fetch to this custom scheme
    (FetchApiAllowed + CorsEnabled) lands here; we do the real HTTP request with
    QNetworkAccessManager — outside any page origin, so the same-origin policy
    doesn't apply — and return a JSON envelope (body base64-encoded). Ordinary
    page fetches never touch this, so web security stays on everywhere else.

    Limitation: requests go through a separate network stack from the browser,
    so the browser's cookies aren't attached (fine for 4chan X's public GETs).

    User-Agent: these go out through QNetworkAccessManager, whose default UA is
    NOT a browser one — and a Cloudflare-fronted host (e.g. 4chan's i.4cdn.org)
    answers a non-browser UA with `429 Too Many Requests`. A userscript that
    saves the reply as a file (4chan X's image download) then writes a 17-byte
    "Too Many Requests" file instead of the image. Real userscript managers send
    the browser's UA on GM_xmlhttpRequest, so we do too (unless the script set
    its own), which makes these fetches look like the page's own requests."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        # Browser UA to stamp on requests that don't carry one. Seeded from the
        # default profile now; _wire_profile() overwrites it with the actual
        # shared profile's UA once the QML tree is up (they match today, but this
        # stays correct if the UA is ever customised).
        try:
            self._ua = QWebEngineProfile.defaultProfile().httpUserAgent() or ""
        except Exception:
            self._ua = ""

    def set_user_agent(self, ua):
        if ua:
            self._ua = ua

    def requestStarted(self, job):
        try:
            spec = json.loads(_b64url_decode(job.requestUrl().path().lstrip("/")).decode("utf-8"))
        except Exception:
            self._send(job, {"__error": "bad gmxhr request"})
            return
        method = (spec.get("method") or "GET").upper()
        target = QUrl(spec.get("url") or "")
        # Only ever proxy http(s). QNetworkAccessManager otherwise happily serves
        # file:// (turning this into an arbitrary local-file read for any page
        # that reaches the handler) and could hit localhost/LAN services (SSRF).
        if target.scheme().lower() not in ("http", "https"):
            self._send(job, {"__error": "gmxhr: only http/https targets are allowed"})
            return
        req = QNetworkRequest(target)
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                         QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        has_ua = False
        for k, v in (spec.get("headers") or {}).items():
            try:
                if str(k).lower() == "user-agent":
                    has_ua = True
                req.setRawHeader(str(k).encode(), str(v).encode())
            except Exception:
                pass
        if not has_ua and self._ua:   # else Cloudflare 429s the non-browser UA
            req.setRawHeader(b"User-Agent", self._ua.encode())
        data = spec.get("data")
        body = data.encode("utf-8") if isinstance(data, str) else b""
        if method == "GET":
            reply = self._nam.get(req)
        elif method == "POST":
            reply = self._nam.post(req, body)
        elif method == "HEAD":
            reply = self._nam.head(req)
        else:
            reply = self._nam.sendCustomRequest(req, method.encode(), body)

        state = {"done": False}

        def finish():
            if state["done"]:
                return
            state["done"] = True
            self._reply(job, reply)
            reply.deleteLater()

        def gone():
            if state["done"]:
                return
            state["done"] = True
            reply.abort()
            reply.deleteLater()

        reply.finished.connect(finish)
        job.destroyed.connect(gone)

    def _reply(self, job, reply):
        try:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            reason = reply.attribute(QNetworkRequest.Attribute.HttpReasonPhraseAttribute)
            raw = bytes(reply.readAll().data())
            headers = ""
            try:
                for h in reply.rawHeaderList():
                    headers += "%s: %s\r\n" % (bytes(h.data()).decode("latin1"),
                                               bytes(reply.rawHeader(h).data()).decode("latin1"))
            except Exception:
                pass
            if status is None:
                env = {"__error": reply.errorString() or "network error"}
            else:
                env = {"status": int(status), "statusText": reason or "",
                       "finalUrl": reply.url().toString(), "headers": headers,
                       "body": base64.b64encode(raw).decode("ascii")}
        except Exception as e:
            env = {"__error": str(e)}
        self._send(job, env)

    def _send(self, job, env):
        try:
            buf = QBuffer(job)
            buf.setData(json.dumps(env).encode("utf-8"))
            buf.open(QIODevice.OpenModeFlag.ReadOnly)
            job.reply(b"application/json", buf)
        except RuntimeError:
            pass  # the job (page) went away before we could reply


# Injected once per page (main world, load-finished): a delegated capture-phase
# click listener that opens a plain content image in a new tab. "Plain" =
# directly-clicked <img>, NOT inside a link/button (those are thumbnails or
# controls, left to the site) and big enough to be real content, not an icon.
# It signals the app by fetching the surfercmd:// scheme (CmdHandler); the page
# never sees a response.
IMAGE_CLICK_JS = r"""
(function(){
  if (window.__surfer_imgclick) return;
  window.__surfer_imgclick = true;
  document.addEventListener('click', function(e){
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var img = e.target;
    if (!img || img.tagName !== 'IMG') return;
    if (img.closest('a,button,[role="button"],[role="link"]')) return;  // thumbnail/control
    var w = img.naturalWidth || img.width, h = img.naturalHeight || img.height;
    if (w < 150 || h < 150) return;                                     // icon/spacer
    var src = img.currentSrc || img.src;
    if (!src || src.indexOf('http') !== 0 && src.indexOf('data:') !== 0) return;
    e.preventDefault(); e.stopPropagation();
    try { fetch('surfercmd://open/?u=' + encodeURIComponent(src)).catch(function(){}); } catch(_){}
  }, true);
})();
"""


# air-only diagnostic for "after a while, all page text renders badly
# antialiased, and only a restart fixes it" (chrome text stays crisp, so the
# fault is inside Chromium's raster path, not Qt's). The suspicion is that the
# GPU context is lost mid-session and Chromium silently falls back to software
# raster for the rest of the run — but chrome://gpu is useless here (QtWebEngine
# loads the page and never populates it) and Chromium's own logging prints
# nothing even at --log-level=0, so the state has to be sampled from inside a
# real, visible renderer.
#
# That is what this is: ONE 1x1 WebGL context per page, whose UNMASKED_RENDERER
# string names the driver actually serving this renderer process. Hardware says
# "Apple M2 …"; a fallback says llvmpipe/SwiftShader. It reports through the
# same surfercmd:// channel as the image-click handler. Delete this (and the
# `gpu` arm of CmdHandler) once the cause is nailed down.
#
# The context is created once and then only POLLED. An earlier version dropped
# it between samples with WEBGL_lose_context.loseContext(), which measurably
# took the shared context down with it in the same breath — "RasterDecoderImpl:
# Context lost during MakeCurrent" the instant the probe fired. An instrument
# that induces the fallback it is looking for is worse than none, so: never
# force-lose a context here, and never create a fresh one per sample either
# (Chromium force-loses the oldest once a page passes its context cap, which
# amounts to the same thing).
GPU_PROBE_JS = r"""
(function(){
  if (window.__surfer_gpuprobe) return;
  window.__surfer_gpuprobe = true;
  var gl = null, last = '';
  try {
    var c = document.createElement('canvas');
    c.width = c.height = 1;
    gl = c.getContext('webgl2') || c.getContext('webgl');
    window.__surfer_gpuprobe_ctx = gl;     // keep it alive; do NOT lose it
  } catch(_){}
  function probe(){
    var r = 'no-webgl', ver = '';
    try {
      if (gl && gl.isContextLost()) {
        r = 'CONTEXT-LOST';
      } else if (gl) {
        var dbg = gl.getExtension('WEBGL_debug_renderer_info');
        r = String(dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL)
                       : gl.getParameter(gl.RENDERER));
        ver = String(gl.getParameter(gl.VERSION));
      }
    } catch (e) { r = 'probe-error:' + e; }
    var line = r + (ver ? ' | ' + ver : '');
    if (line === last) return;             // one report per page, then only on change
    last = line;
    try {
      fetch('surfercmd://gpu/?r=' + encodeURIComponent(line)
            + '&h=' + encodeURIComponent(location.host)).catch(function(){});
    } catch(_){}
  }
  probe();
  setInterval(probe, 60000);               // background tabs are throttled to ~1/min anyway
})();
"""


# The cosmetic-filtering RUNTIME. One static script, injected by the shared
# profile at DOCUMENT CREATION into every frame. It replaces a load-finished
# runJavaScript in Main.qml, which was late by construction: the ads had already
# painted, nothing re-ran on an SPA route change, and a lazily-inserted ad slot
# brought no new rules with it.
#
# It is static because a profile-level script has to be: it is compiled once and
# shipped to every page, so it cannot bake in one site's selectors. It therefore
# carries no rules at all — it is a courier. Everything host-specific is pulled
# out of Python over the `surfercos:` scheme (CosmeticInjector), which is where
# adblock-rust actually lives:
#
#   surfercos://s/<b64 {"u":href}>              text/css   specific hide rules
#   surfercos://x/<b64 {"u":href}>              js         scriptlets, alone
#   surfercos://j/<b64 {"u":href}>              js         Cosmetic.specificJs
#                                                          (the fallback only)
#   surfercos://g/<b64 {"u":href,"c":[],"i":[]}> js        Cosmetic.genericJs
#   surfercos://p/<b64 {"u":href}>              json       procedural filters
#
# **How the flash actually dies.** Measured on PySide6 6.11 (tools/cosmetic-test.py):
# at DocumentCreation `document.documentElement` is still NULL, so there is
# nothing to append a <style> or a <script> to — anything that waits for a parent
# lands after the parser has built the whole body, and the ad gets a frame. Two
# things do work with no DOM at all, and this runtime is built on both:
#
#   * a SYNCHRONOUS XHR (the request is served in-process by CosmeticInjector —
#     no network, no disk), and
#   * `document.adoptedStyleSheets` with a constructed CSSStyleSheet.
#
# So the per-site rules — the ones that depend only on the url and therefore
# CAN be known this early — are fetched and adopted inside the document-creation
# callback itself. Constructed stylesheets are also exempt from `style-src`, so
# this is the CSP-proof path as well as the fast one. Everything that genuinely
# needs a DOM (scriptlets, the generic pass) is deferred and runs as a
# <script src>, never eval() — the scheme is registered
# ContentSecurityPolicyIgnored so a strict `script-src` cannot stop it, which
# `new Function` would not survive.
#
# The `j` request is deliberately redundant with `s`: it re-injects the same CSS
# as an ordinary <style> and carries the scriptlets. That makes it the safety net
# — if the CSS ever fails to come back, the page still ends up exactly where the
# old load-finished path left it, only earlier.
#
# Nothing here inspects, rewrites or filters a selector, so `:has()` and anything
# else the engine emits reaches the page verbatim.
#
# MAIN world, deliberately: an isolated world gets its own `history` wrapper, so
# a pushState hook installed there would never see the page's own calls — which
# is the whole point of hooking it.
#
# Three re-run triggers, all throttled onto one flush:
#   * MutationObserver — harvests only the class/id TOKENS of ADDED nodes (and of
#     class/id attribute changes), diffed against what has already been asked
#     for. No selector matching in JS and no full-document re-query per mutation:
#     a mutation storm that introduces no new token costs one lookup per node and
#     sends nothing. Plain CSS already covers a late element that matches a rule
#     we shipped; this exists for the tokens that were not on the page when the
#     generic set was narrowed to it. Above STORM records/second the observer
#     DISCONNECTS in favour of a plain poll and comes back after BACK_MS — a
#     throttle alone still pays the per-record cost, and ad-heavy pages storm.
#   * pushState/replaceState/popstate/hashchange — an SPA route change means a new
#     url and therefore a new rule set (all of YouTube after the first click).
#     Forgets the asked-for tokens and starts the page over, sync path included.
#   * DOMContentLoaded — one full sweep once the parser is done. The FIRST sweep
#     is scheduled on requestIdleCallback with a hard timeout, so it cannot be
#     starved by a busy page.
#
# The generic pass is narrowed to the class/id tokens actually on the page and
# each token is asked about exactly once (`seenC`/`seenI`) — uBO's design, via
# adblock-rust's hidden_class_id_selectors. `$generichide` is honoured on the
# engine side, inside Cosmetic.genericJs.
#
# Procedural filters (`:has-text`, `:upward`, `:matches-css`, …) come back from
# the engine JSON-encoded and UNAPPLIED — applying them is the embedder's job,
# and this runtime is the embedder. Styles are applied BY ATTRIBUTE rather than
# by element.style, so a page that watches inline styles cannot see or undo
# them.
COSMETIC_RUNTIME_JS = r"""
(function(){
  if (window.__surfer_cosmetic) return;
  window.__surfer_cosmetic = true;

  var SCHEME = 'surfercos://';
  var CHUNK      = 400;    // class/id tokens per generic request
  var THROTTLE   = 250;    // ms between generic re-queries (Brave: fetchNewClassIdRulesThrottlingMs)
  var IDLE_MS    = 1000;   // cap on how long the first sweep may sit idle (maxTimeMSBeforeStart)
  var STORM      = 400;    // mutation records/sec that mean "this page is storming"
  var POLL_MS    = 500;    // sweep interval while in storm mode
  var BACK_MS    = 10000;  // ...before going back to the observer (returnToMutationObserverIntervalMs)
  var MAX_ROOTS  = 500;    // added elements carried into one procedural re-run

  var FALLBACK = '/*surfer-fallback*/';
  var seenC = Object.create(null), seenI = Object.create(null);
  var qC = [], qI = [], roots = [], href = '', tick = null;
  var sheet = null, psheet = null, pcss = '', PROC = [];
  var cssAll = '', cssSeen = Object.create(null);
  var obs = null, poll = null, burst = 0, burstAt = 0;
  var xPending = false, jsFallback = false;

  function b64(o){
    var s = JSON.stringify(o), t = '';
    try {
      var b = new TextEncoder().encode(s);
      for (var i = 0; i < b.length; i++) t += String.fromCharCode(b[i]);
    } catch(e) { t = unescape(encodeURIComponent(s)); }
    return btoa(t).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function url(kind, payload){ return SCHEME + kind + '/' + b64(payload); }

  // ---- the fast path: needs no DOM, runs inside the document-creation call --
  // ACCUMULATE, never replace. An SPA route change re-asks for the new url's
  // rules, and on the same host the engine hands back the same string — so the
  // dedupe keeps this at one entry — but where it does not, a replace would
  // silently UN-hide whatever the previous route had hidden while that DOM is
  // still on screen. (Caught by tools/cosmetic-test.py, which gives the two
  // routes deliberately different rules.)
  function adopt(css){
    if (!css || cssSeen[css]) return;
    cssSeen[css] = 1;
    cssAll += (cssAll ? '\n' : '') + css;
    try {
      if (!sheet) {
        sheet = new CSSStyleSheet();
        document.adoptedStyleSheets = document.adoptedStyleSheets.concat([sheet]);
      }
      sheet.replaceSync(cssAll);
    } catch(e){}
  }

  function sync(kind){
    try {
      var x = new XMLHttpRequest();
      x.open('GET', url(kind, { u: location.href }), false);
      x.send();
      return (x.status === 200 || x.status === 0) ? (x.responseText || '') : '';
    } catch(e){ return ''; }
  }

  function specific(){
    var css = sync('s');
    // the handler could not read the CSS back out of the engine's JS: fall back
    // to running that JS deferred, which is exactly the old behaviour
    if (css.indexOf(FALLBACK) === 0) { jsFallback = true; return; }
    adopt(css);
  }

  // Scriptlets must run at DOCUMENT-START and in the MAIN world or they are
  // inert: uBO's json-prune shape (YouTube's playerResponse.adPlacements) works
  // by shadowing the page's own globals BEFORE the page reads them, and a
  // <script src> that waits for a parent is already too late. There is no DOM
  // yet, so an inline <script> is impossible and eval is the only way to run
  // fetched code — hence the two paths: eval now, or, if the page's CSP has no
  // 'unsafe-eval', a <script src> off the CSP-ignored scheme as soon as there
  // is a parent. Late beats inert.
  function scriptlets(){
    var t = sync('x');
    if (!t) return;
    try { (0, eval)(t); }
    catch(e) { xPending = true; }
  }

  // ---- the deferred path: engine JS as a <script src>, so a strict script-src
  // cannot block it (the scheme is ContentSecurityPolicyIgnored) and we never
  // need eval.
  function run(kind, payload){
    var r = document.head || document.documentElement;
    if (!r) return;
    var s = document.createElement('script');
    s.src = url(kind, payload);
    s.async = false;
    s.onload = s.onerror = function(){
      try { if (s.parentNode) s.parentNode.removeChild(s); } catch(e){}
    };
    r.appendChild(s);
  }

  function idle(fn){
    if (window.requestIdleCallback) requestIdleCallback(fn, { timeout: IDLE_MS });
    else setTimeout(fn, 0);
  }

  // ---- class/id harvesting -------------------------------------------------
  function note(e){
    if (!e || e.nodeType !== 1) return;
    var id = e.id;
    if (id && !seenI[id]) { seenI[id] = 1; qI.push(id); }
    var cl = e.classList;
    if (cl) for (var j = 0; j < cl.length; j++) {
      var c = cl[j];
      if (!seenC[c]) { seenC[c] = 1; qC.push(c); }
    }
  }

  function sweep(root){
    if (!root) return;
    note(root);
    var a = root.querySelectorAll ? root.querySelectorAll('[class],[id]') : null;
    if (a) for (var k = 0; k < a.length; k++) note(a[k]);
  }

  function flush(){
    tick = null;
    if (location.href !== href) { routed(); return; }
    var r = roots.length ? roots : null;
    roots = [];
    if (r) runProc(r);
    if (!qC.length && !qI.length) return;
    var c = qC, i = qI, u = location.href;
    qC = []; qI = [];
    // chunked, so a token-heavy page cannot build one absurd url
    while (c.length || i.length)
      run('g', { u: u, c: c.splice(0, CHUNK), i: i.splice(0, CHUNK) });
  }

  function schedule(){ if (!tick) tick = setTimeout(flush, THROTTLE); }

  // ---- the observer, and the escape hatch from a mutation storm ------------
  // An ad-heavy page can deliver thousands of records a second; a plain
  // debounce keeps paying the per-record cost even when it sends nothing. So
  // above STORM records/second the observer is DISCONNECTED and a plain poll
  // takes over for BACK_MS, after which the observer comes back (Brave's
  // design — the polling fallback is what stops a storm page from being
  // permanently observer-bound).
  function record(recs){
    var now = Date.now();
    if (now - burstAt > 1000) { burstAt = now; burst = 0; }
    burst += recs.length;
    for (var i = 0; i < recs.length; i++) {
      var r = recs[i];
      if (r.type === 'attributes') { note(r.target); continue; }
      var an = r.addedNodes;
      for (var j = 0; j < an.length; j++) {
        var n = an[j];
        if (!n || n.nodeType !== 1) continue;
        sweep(n);
        if (roots.length < MAX_ROOTS) roots.push(n);
      }
    }
    if (burst > STORM) { storm(); return; }
    schedule();
  }

  function observe(){
    try {
      if (!obs) obs = new MutationObserver(record);
      obs.observe(document.documentElement, { childList: true, subtree: true,
                                              attributes: true,
                                              attributeFilter: ['class', 'id'] });
    } catch(e){}
  }

  function storm(){
    if (poll) return;
    try { obs.disconnect(); } catch(e){}
    poll = setInterval(function(){
      roots = [document.documentElement];
      sweep(document.documentElement);
      schedule();
    }, POLL_MS);
    setTimeout(function(){
      clearInterval(poll); poll = null;
      burst = 0; burstAt = Date.now();
      observe();
    }, BACK_MS);
  }

  // ---- procedural filters --------------------------------------------------
  // The engine returns these JSON-encoded and does NOT apply them; applying
  // them is the embedder's job. Styles are applied BY ATTRIBUTE, never by
  // element.style: a page that watches inline styles cannot see (or undo) an
  // attribute pair backed by a stylesheet rule. One random tag per page keeps
  // the attribute names unguessable.
  var TAG = 'data-surfer-' + Math.random().toString(36).slice(2, 8);
  var attrs = Object.create(null), attrN = 0;

  function adoptProc(){
    try {
      if (!psheet) {
        psheet = new CSSStyleSheet();
        document.adoptedStyleSheets = document.adoptedStyleSheets.concat([psheet]);
      }
      psheet.replaceSync(pcss);
    } catch(e){}
  }

  function attrFor(style){
    var a = attrs[style];
    if (!a) {
      a = TAG + '-' + (attrN++);
      attrs[style] = a;
      pcss += '[' + TAG + '][' + a + ']{' + style + '}\n';
      adoptProc();
    }
    return a;
  }

  function mark(e, style){
    var a = attrFor(style);
    // never write an attribute that is already there — every write is another
    // mutation record, and that is how a filter turns into an infinite loop
    if (e.hasAttribute(a) && e.hasAttribute(TAG)) return;
    try { e.setAttribute(TAG, ''); e.setAttribute(a, ''); } catch(_){}
  }

  function act(e, action){
    var t = action && action.type;
    var arg = action && action.arg;
    if (!t || t === 'hide' || t === 'default') return mark(e, 'display:none!important');
    if (t === 'style')  return mark(e, String(arg || ''));
    if (t === 'remove') { try { e.remove(); } catch(_){} return; }
    // classList.remove / removeAttribute fire a mutation even when they remove
    // nothing, so both check first
    if (t === 'remove-attr') {
      try { if (e.hasAttribute(arg)) e.removeAttribute(arg); } catch(_){}
      return;
    }
    if (t === 'remove-class') {
      try { if (e.classList.contains(arg)) e.classList.remove(arg); } catch(_){}
      return;
    }
  }

  function rx(arg){
    if (typeof arg === 'string' && arg.length > 2 && arg.charAt(0) === '/') {
      var i = arg.lastIndexOf('/');
      if (i > 0) { try { return new RegExp(arg.slice(1, i), arg.slice(i + 1)); } catch(_){} }
    }
    return null;
  }
  function like(s, arg){
    var r = rx(arg);
    return r ? r.test(s) : String(s).indexOf(arg) !== -1;
  }
  function pair(arg){
    var i = String(arg).indexOf('=');
    return i < 0 ? [String(arg), null]
                 : [String(arg).slice(0, i).trim(),
                    String(arg).slice(i + 1).trim().replace(/^["']|["']$/g, '')];
  }
  function css(e, prop, pseudo){
    try { return getComputedStyle(e, pseudo || null).getPropertyValue(prop); }
    catch(_){ return ''; }
  }

  // One operator of a compiled procedural selector: element set in, element set
  // out. An UNKNOWN operator yields nothing — never everything; a filter we do
  // not understand must not hide the page.
  function step(op, arg, els){
    var out = [], i, j, q;
    if (op === 'css-selector') {
      for (i = 0; i < els.length; i++) {
        try { q = els[i].querySelectorAll(arg); } catch(_){ continue; }
        for (j = 0; j < q.length; j++) out.push(q[j]);
      }
      return out;
    }
    if (op === 'matches-media') { try { return matchMedia(arg).matches ? els : []; } catch(_){ return []; } }
    if (op === 'matches-path')  { return like(location.pathname + location.search, arg) ? els : []; }
    if (op === 'xpath') {
      for (i = 0; i < els.length; i++) {
        try {
          var it = document.evaluate(arg, els[i], null, 5 /* ORDERED_ITERATOR */, null), n;
          while ((n = it.iterateNext())) if (n.nodeType === 1) out.push(n);
        } catch(_){}
      }
      return out;
    }
    for (i = 0; i < els.length; i++) {
      var e = els[i], ok = false, kv;
      try {
        if (op === 'has')                  ok = !!e.querySelector(arg);
        else if (op === 'has-text')        ok = like(e.textContent || '', arg);
        else if (op === 'not')             ok = !e.matches(arg);
        else if (op === 'min-text-length') ok = (e.textContent || '').length >= (parseInt(arg, 10) || 0);
        else if (op === 'matches-attr') {
          kv = pair(arg);
          ok = e.hasAttribute(kv[0]) && (kv[1] === null || like(e.getAttribute(kv[0]) || '', kv[1]));
        }
        else if (op === 'matches-property') {
          kv = pair(arg);
          ok = kv[1] === null ? (e[kv[0]] !== undefined) : like(String(e[kv[0]]), kv[1]);
        }
        else if (op === 'matches-css' || op === 'matches-css-before' || op === 'matches-css-after') {
          kv = String(arg).split(':');
          var prop = (kv.shift() || '').trim(), want = kv.join(':').trim();
          var pseudo = op === 'matches-css-before' ? '::before'
                     : op === 'matches-css-after'  ? '::after' : null;
          ok = like(css(e, prop, pseudo), want);
        }
        else if (op === 'upward') {
          var n2 = parseInt(arg, 10), t = e;
          if (isNaN(n2)) t = e.closest(arg);
          else for (var k = 0; k < n2 && t; k++) t = t.parentElement;
          if (t && out.indexOf(t) < 0) out.push(t);
          continue;
        }
      } catch(_){ ok = false; }
      if (ok) out.push(e);
    }
    return out;
  }

  // Fast path: a chain starting with a plain css-selector is resolved by
  // querySelectorAll and the operator chain starts at 1. Only a chain that does
  // NOT start with one has to fall back to '*'.
  function runProc(from){
    if (!PROC.length || !from || !from.length) return;
    for (var f = 0; f < PROC.length; f++) {
      var sel = PROC[f].selector, els = [], start = 0, r, q, k;
      if (!sel || !sel.length) continue;
      if (sel[0].type === 'css-selector') {
        for (r = 0; r < from.length; r++) {
          try { if (from[r].matches && from[r].matches(sel[0].arg)) els.push(from[r]); } catch(_){}
          try { q = from[r].querySelectorAll(sel[0].arg); } catch(_){ continue; }
          for (k = 0; k < q.length; k++) els.push(q[k]);
        }
        start = 1;
      } else {
        for (r = 0; r < from.length; r++) {
          try { q = from[r].querySelectorAll('*'); } catch(_){ continue; }
          for (k = 0; k < q.length; k++) els.push(q[k]);
        }
      }
      for (var s = start; s < sel.length && els.length; s++)
        els = step(sel[s].type, sel[s].arg, els);
      for (var m = 0; m < els.length; m++) act(els[m], PROC[f].action);
    }
  }

  function procedural(){
    try {
      fetch(url('p', { u: location.href })).then(function(r){ return r.json(); })
        .then(function(j){
          PROC = (j && j.length) ? j : [];
          if (PROC.length) runProc([document.documentElement]);
        })["catch"](function(){});
    } catch(e){}
  }

  // ---- SPA route changes ---------------------------------------------------
  function routed(){
    if (location.href === href) return;
    href = location.href;
    seenC = Object.create(null); seenI = Object.create(null);
    qC = []; qI = []; roots = [];
    specific();                       // sync: the new route's ads are up NOW
    scriptlets();
    if (xPending) { xPending = false; run('x', { u: href }); }
    if (jsFallback) run('j', { u: href });
    procedural();
    sweep(document.documentElement);
    schedule();
  }

  function hook(name){
    var orig = history[name];
    if (typeof orig !== 'function') return;
    history[name] = function(){
      var r = orig.apply(this, arguments);
      try { setTimeout(routed, 0); } catch(e){}
      return r;
    };
  }

  function boot(){
    if (xPending)   { xPending = false; run('x', { u: location.href }); }
    if (jsFallback) run('j', { u: location.href });   // the old path, verbatim
    observe();
    procedural();
    // first full sweep on idle, but with a hard timeout so a busy page cannot
    // starve it forever
    idle(function(){ sweep(document.documentElement); schedule(); });
    document.addEventListener('DOMContentLoaded', function(){
      sweep(document.documentElement); schedule();
      if (PROC.length) runProc([document.documentElement]);
    });
    hook('pushState'); hook('replaceState');
    window.addEventListener('popstate',   function(){ setTimeout(routed, 0); });
    window.addEventListener('hashchange', function(){ setTimeout(routed, 0); });
  }

  href = location.href;
  specific();                         // BEFORE anything can paint
  scriptlets();                       // ...and before the page reads its own JSON

  if (document.documentElement) { boot(); return; }
  // DocumentCreation fires before <html> exists (measured), so everything that
  // needs a parent waits for one — the same guard the userscripts use.
  var iv = setInterval(function(){
    if (document.documentElement) { clearInterval(iv); boot(); }
  }, 0);
})();
"""


# Served as the `s` body when the CSS could not be separated out. The runtime
# recognises it and falls back to running the engine's JS the old (late) way,
# so a change to `Cosmetic._inject` costs the head start and nothing else.
FALLBACK_CSS = "/*surfer-fallback*/"


def _css_of(js):
    """Recover the CSS literal from `Cosmetic._inject`'s output.

    The engine hands out ready-to-run JS, but the flash-free path needs CSS as
    CSS: it is adopted through a constructed CSSStyleSheet at document creation,
    when there is no DOM to append a <style> to and no way to run fetched JS
    without eval. `_inject` emits it as one JSON string literal after `var css=`,
    so a JSON decoder started at that offset reads it back exactly, whatever the
    selectors contain.

    Deliberately a fallback rather than the contract: `CosmeticInjector` prefers
    a `specificCss`/`genericCss` slot on `Cosmetic` if one ever exists, and the
    parallel `surfercos://j` request re-injects the same rules the old way — so
    the worst this can cost, if the engine's JS is ever shaped differently, is
    the head start, not the blocking. Returns None (not "") when the seam is
    missing, so "no rules for this url" and "could not read them" stay distinct
    — the caller turns the second into the FALLBACK marker."""
    i = js.find("var css=")
    if i < 0:
        return None
    try:
        val, _ = json.JSONDecoder().raw_decode(js, i + len("var css="))
    except ValueError:
        return None
    return val if isinstance(val, str) else None


# `_inject` closes the style block with this, then appends `try{<scriptlet>}catch(e){}`
_COS_SEAM = "(document.head||document.documentElement).appendChild(s);}"
_COS_TAIL = "}catch(e){}}catch(e){}})();"


def _scriptlet_of(js):
    """Recover the scriptlet half of `Cosmetic._inject`'s output.

    It has to be separable because it has to run EARLIER than the CSS half can
    be appended: at document-start, in the main world, before the page reads its
    own globals. Run as one blob at document creation it would not run at all —
    `_inject` appends the <style> first, and with no documentElement that throws
    and takes the whole outer `try` (scriptlet included) with it.

    Same deal as `_css_of`: a fallback, superseded the moment `Cosmetic` grows a
    `scriptletJs` slot."""
    i = js.find(_COS_SEAM)
    if i < 0:
        return None
    tail = js[i + len(_COS_SEAM):]
    if not tail.startswith("try{"):
        return ""                      # no scriptlet for this url, cleanly
    end = tail.rfind(_COS_TAIL)
    return tail[4:end] if end >= 0 else None


# The profile-level dark-mode / system-font courier. It exists for the same
# reason COSMETIC_RUNTIME_JS does: load-finished injection is too late by
# definition. The old per-view `runJavaScript(DarkMode.js(url))` ran at
# `LoadSucceededStatus` — after images and scripts had finished, so the page
# painted light first and flipped dark only once everything loaded. This runs
# at DocumentCreation and adopts the page's style CSS as a constructed
# CSSStyleSheet before the first frame, so the theme is on the page as it
# paints. Python stays the single source of truth: the sheet is re-fetched
# (a) at each document creation and (b) whenever the app side calls
# `window.__surferPageStyleRefresh()` after a settings change, so open pages
# follow a toggle or a slider without a reload.
PAGE_STYLE_RUNTIME_JS = r"""
(function(){
  if (window.__surferPageStyle) return;
  window.__surferPageStyle = true;

  var SCHEME = 'surferstyle://';
  var SHEET_ID = '__surfer_pagestyle__';
  var sheet = null;

  function b64(o){
    var s = JSON.stringify(o), t = '';
    try {
      var b = new TextEncoder().encode(s);
      for (var i = 0; i < b.length; i++) t += String.fromCharCode(b[i]);
    } catch(e) { t = unescape(encodeURIComponent(s)); }
    return btoa(t).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
  }
  function addr(kind, payload){ return SCHEME + kind + '/' + b64(payload); }

  // Set (or strip) the page-style sheet to exactly `css` ('' strips it, which
  // is how an OFF toggle or an exception-site page drops the theme). One sheet
  // owned here, never a <style>, so no other writer and no flash.
  function apply(css){
    try {
      if (!css){
        if (sheet){
          var a = Array.prototype.slice.call(document.adoptedStyleSheets);
          var i = a.indexOf(sheet);
          if (i >= 0){ a.splice(i, 1); document.adoptedStyleSheets = a; }
          sheet = null;
        }
        return;
      }
      if (!sheet){
        sheet = new CSSStyleSheet();
        sheet.id = SHEET_ID;
        // concat, never clobber — the cosmetic courier's sheet may already be
        // adopted and must survive.
        document.adoptedStyleSheets = document.adoptedStyleSheets.concat([sheet]);
      }
      sheet.replaceSync(css);
    } catch(e){}
  }

  // Synchronous, so it works at document-creation with no DOM — the same reason
  // the cosmetic courier is synchronous. `location.href` is this document's url
  // even before <html> exists.
  function fetch(){
    var css = '';
    try {
      var x = new XMLHttpRequest();
      x.open('GET', addr('s', { u: location.href }), false);
      x.send();
      css = (x.status === 200 || x.status === 0) ? (x.responseText || '') : '';
    } catch(e){}
    apply(css);
  }

  window.__surferPageStyleRefresh = fetch;

  // Adopt at document-creation so the theme is present from the first frame.
  fetch();
})();
"""


class CosmeticInjector(QWebEngineUrlSchemeHandler):
    """The other half of COSMETIC_RUNTIME_JS: the profile-level QWebEngineScript
    that carries it, and the ``surfercos://`` scheme that feeds it rules.

    Five hosts, each taking a base64url JSON blob as its path (the gmxhr
    convention):

        surfercos://s/<b64 {"u": href}>                  text/css, specific
        surfercos://x/<b64 {"u": href}>                  the scriptlets, alone
        surfercos://j/<b64 {"u": href}>                  Cosmetic.specificJs
        surfercos://g/<b64 {"u": href, "c": [], "i": []}> Cosmetic.genericJs,
                                                          narrowed to the page's
                                                          own class/id tokens
        surfercos://p/<b64 {"u": href}>                  json, procedural filters

    This class is a pipe. It parses the request, calls `Cosmetic`, and hands the
    result back untouched — no sanitising, no selector rewriting — so whatever
    the engine emits (`:has()` included; Chromium 6.11 supports it natively)
    reaches the page exactly as written.

    `scripts` is a QVariantList because that is the only way the runtime can be
    registered at all: PySide6 6.11 does not bind QQuickWebEngineScriptCollection,
    so `profile.userScripts` is unreachable from Python (`RuntimeError: Can't find
    converter for 'QQuickWebEngineScriptCollection*'`). QML CAN reach it, and it
    takes a list of Python-made QWebEngineScript objects — so Main.qml assigns
    this to `sharedProfile.userScripts.collection`, exactly as each view already
    does with `UserScripts.scriptObjects`."""

    def __init__(self, cosmetic, parent=None):
        super().__init__(parent)
        self._cos = cosmetic
        self._scripts = None

    @Property("QVariantList", constant=True)
    def scripts(self):
        if self._scripts is None:
            s = QWebEngineScript()
            s.setName("surfer-cosmetic")
            # DocumentCreation, not DocumentReady: DOM-ready is after the parser
            # has built the page, i.e. after the ads have had their chance to
            # paint.
            s.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            s.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            s.setRunsOnSubFrames(True)     # ad slots are overwhelmingly iframes
            s.setSourceCode(COSMETIC_RUNTIME_JS)
            self._scripts = [s]
        return self._scripts

    def _specific(self, url):
        try:
            return self._cos.specificJs(url) or ""
        except Exception:
            return ""

    def _generic(self, url, classes, ids):
        try:
            return self._cos.genericJs(url, classes, ids) or ""
        except Exception:
            return ""

    _warned = False

    def _warn(self, what):
        if not CosmeticInjector._warned:
            CosmeticInjector._warned = True
            sys.stderr.write("surfer cosmetic: could not separate %s out of "
                             "Cosmetic._inject's JS — falling back to the old "
                             "load-time injection for it\n" % what)

    def _procedural(self, url):
        """Normalised procedural filters for `url`, as a JSON array of
        ``{"selector": [{"type","arg"}, …], "action": {"type","arg"}|null}``.

        adblock-rust hands `procedural_actions` back as a Vec of JSON STRINGS,
        so a list of strings is unwrapped here rather than in the page — the
        runtime should only ever see objects. Empty array when `Cosmetic` has no
        `proceduralJson` slot, which is the state until the engine side lands."""
        fn = getattr(self._cos, "proceduralJson", None)
        if not callable(fn):
            return "[]"
        # adblock-rust's `procedural_actions` is a Set[str]; a slot may hand it
        # over as the set/list itself or as one JSON document. Take either.
        try:
            data = fn(url)
        except Exception:
            return "[]"
        if isinstance(data, (set, frozenset, tuple)):
            data = list(data)
        elif isinstance(data, str):
            try:
                data = json.loads(data or "[]")
            except ValueError:
                return "[]"
        out = []
        for item in data if isinstance(data, list) else []:
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except ValueError:
                    continue
            if isinstance(item, dict) and item.get("selector"):
                out.append(item)
        return json.dumps(out)

    def requestStarted(self, job):
        body, ctype = b"", b"application/javascript"
        try:
            u = job.requestUrl()
            host = u.host()
            spec = json.loads(_b64url_decode(u.path().lstrip("/")).decode("utf-8"))
            page = str(spec.get("u") or "")
            if host == "s":
                ctype = b"text/css"
                # a real CSS accessor on Cosmetic wins if one is ever added
                fn = getattr(self._cos, "specificCss", None)
                if callable(fn):
                    css = fn(page)
                else:
                    # "" is Cosmetic's "no rules for this url" — a real answer,
                    # not a broken seam
                    js = self._specific(page)
                    css = _css_of(js) if js else ""
                if css is None:
                    self._warn("the CSS")
                    css = FALLBACK_CSS
                body = css.encode("utf-8")
            elif host == "x":
                fn = getattr(self._cos, "scriptletJs", None)
                if callable(fn):
                    sl = fn(page)
                else:
                    js = self._specific(page)
                    sl = _scriptlet_of(js) if js else ""
                if sl is None:
                    self._warn("the scriptlets")
                    sl = ""
                body = sl.encode("utf-8")
            elif host == "j":
                body = self._specific(page).encode("utf-8")
            elif host == "g":
                body = self._generic(page, spec.get("c") or [],
                                     spec.get("i") or []).encode("utf-8")
            elif host == "p":
                ctype = b"application/json"
                body = self._procedural(page).encode("utf-8")
        except Exception:
            body = b""
        try:
            buf = QBuffer(job)
            buf.setData(body)
            buf.open(QIODevice.OpenModeFlag.ReadOnly)
            job.reply(ctype, buf)
        except RuntimeError:
            pass  # the job (page) went away before we could reply


class PageStyleHandler(QWebEngineUrlSchemeHandler):
    """The `surferstyle://` feed for PAGE_STYLE_RUNTIME_JS: serves the current
    page-style (dark mode + system-font) CSS for a url, computed by the
    DarkMode bridge.

    One host, `s`, taking a base64url JSON blob ``{"u": href}`` as its path (the
    same gmxhr convention as surfercos). The reply is `text/css` and is adopted
    by the courier as a constructed CSSStyleSheet, so it never hits `style-src`
    and needs no DOM parent."""

    def __init__(self, darkmode, parent=None):
        super().__init__(parent)
        self._dm = darkmode

    def requestStarted(self, job):
        body, ctype = b"", b"text/css"
        try:
            spec = json.loads(
                _b64url_decode(job.requestUrl().path().lstrip("/")).decode("utf-8"))
            url = str(spec.get("u") or "")
            body = self._dm.css(url).encode("utf-8")
        except Exception:
            body = b""
        try:
            buf = QBuffer(job)
            buf.setData(body)
            buf.open(QIODevice.OpenModeFlag.ReadOnly)
            job.reply(ctype, buf)
        except RuntimeError:
            pass  # the page went away before we could reply


class PageStyle(QObject):
    """The profile-level dark-mode/system-font courier as a QWebEngineScript.

    Main.qml appends `scripts` to `sharedProfile.userScripts.collection`
    (PySide6 6.11 does not bind QQuickWebEngineScriptCollection, so the object
    is assembled here and handed to QML — the same route CosmeticInject.scripts
    and UserScripts.scriptObjects take). DocumentCreation + MainWorld, and
    deliberately NOT RunsOnSubFrames: the top view already composites its
    iframes through the whole-page `html` filter, so a subframe copy would
    invert embedded content a second time."""

    @Property("QVariantList", constant=True)
    def scripts(self):
        s = QWebEngineScript()
        s.setName("surfer-pagestyle")
        s.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        s.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        s.setRunsOnSubFrames(False)
        s.setSourceCode(PAGE_STYLE_RUNTIME_JS)
        return [s]


class CmdHandler(QWebEngineUrlSchemeHandler):
    """Serves ``surfercmd://<verb>/?...`` — a one-way page->app command channel
    (the page fetches it; there's no meaningful response). Currently just
    ``open`` (open a URL in a new foreground tab), used by the image-click
    handler. Emits `openTab` on the GUI thread via a queued signal; QML wires it
    to win.newTab. Reusable for any future 'page asked the browser to do X'."""

    openTab = Signal(str)

    GPU_LOG = Path.home() / ".cache" / "surfer-gpu.log"

    def _log_gpu(self, line, host):
        """Append a GPU-renderer sample, deduped: only a change of renderer
        string gets a line (plus one at the first sample and a 15-minute
        heartbeat), so an all-day session leaves a log you can read at a glance
        and the moment of any fallback is timestamped."""
        now = time.time()
        prev = getattr(self, "_gpu_last", None)
        if prev == line and now - getattr(self, "_gpu_at", 0) < 900:
            return
        tag = "CHANGED" if (prev is not None and prev != line) else "sample"
        self._gpu_last, self._gpu_at = line, now
        try:
            with open(self.GPU_LOG, "a", encoding="utf-8") as f:
                f.write("%s %-7s %s   (%s)\n"
                        % (time.strftime("%Y-%m-%dT%H:%M:%S"), tag, line, host))
        except OSError:
            pass

    def requestStarted(self, job):
        try:
            u = job.requestUrl()
            if u.host() == "gpu":
                from PySide6.QtCore import QUrlQuery
                q = QUrlQuery(u)
                fmt = QUrl.ComponentFormattingOption.FullyDecoded
                self._log_gpu(q.queryItemValue("r", fmt), q.queryItemValue("h", fmt))
            elif u.host() == "open":
                from PySide6.QtCore import QUrlQuery
                target = QUrlQuery(u).queryItemValue("u", QUrl.ComponentFormattingOption.FullyDecoded)
                # Any page can fetch surfercmd://open, so only honour schemes the
                # image-click JS actually emits (http/https/data); never let a
                # page force-open a file:// (local-file display) or other scheme.
                if target and QUrl(target).scheme().lower() in ("http", "https", "data"):
                    self.openTab.emit(target)
        except Exception:
            pass
        try:
            job.fail(QWebEngineUrlRequestJob.Error.RequestAborted)
        except Exception:
            pass


class UserScripts(QObject):
    """GreaseMonkey-style userscripts: every ``*.js`` in
    $XDG_CONFIG_HOME/surfer/userscripts/ is loaded, its ``// ==UserScript==``
    metadata parsed (@name/@namespace/@version, @match/@include, @run-at), and
    compiled into a QWebEngineScript on the shared profile — injected at
    document-start (or -end) with a GM_* API shim (see _GM_SHIM) so real GM
    scripts run. Scoped to matching URLs by an in-page guard. The folder is
    watched, so dropping/editing a file reloads live — that's how you import one.

    QtWebEngine has no Chromium-extension support, so this + the injected CSS is
    the extensibility surface. Limits: GM_xmlhttpRequest is a fetch shim (no CORS
    bypass); GM values are localStorage-backed (per-origin, not cross-domain)."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        cfg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self._dir = cfg / "surfer" / "userscripts"
        self._scripts = []
        self._qscripts = []   # QWebEngineScript objects, bound to each view's userScripts.collection
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._reload)
        self._watcher.fileChanged.connect(self._reload)
        self._ensure_dir()
        self._reload()

    def _ensure_dir(self):
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if self._dir.is_dir() and str(self._dir) not in self._watcher.directories():
            self._watcher.addPath(str(self._dir))

    @staticmethod
    def _parse_meta(text):
        meta = {"name": "", "namespace": "", "version": "", "matches": [], "run_at": "end"}
        m = re.search(r"//\s*==UserScript==(.*?)//\s*==/UserScript==", text, re.S)
        if m:
            for line in m.group(1).splitlines():
                lm = re.match(r"\s*//\s*@(\S+)\s+(.*\S)", line)
                if not lm:
                    continue
                key, val = lm.group(1).lower(), lm.group(2).strip()
                if key == "name" and not meta["name"]:
                    meta["name"] = val
                elif key == "namespace":
                    meta["namespace"] = val
                elif key == "version":
                    meta["version"] = val
                elif key in ("match", "include"):
                    meta["matches"].append(val)
                elif key == "run-at":
                    meta["run_at"] = "start" if "start" in val else "end"
        return meta

    def _enabled_path(self):
        return self._dir.parent / "userscripts.json"

    def _load_enabled(self):
        try:
            data = json.loads(self._enabled_path().read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _reload(self, *args):
        self._ensure_dir()
        enabled = self._load_enabled()
        scripts = []
        try:
            files = sorted(self._dir.glob("*.js"))
        except OSError:
            files = []
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            meta = self._parse_meta(text)
            scripts.append({
                "name": meta["name"] or f.stem, "namespace": meta["namespace"] or (meta["name"] or f.stem),
                "version": meta["version"], "file": f.name, "path": str(f),
                "matches": meta["matches"], "runAt": meta["run_at"], "code": text,
                "enabled": bool(enabled.get(f.name, True)),
            })
            if str(f) not in self._watcher.files():
                self._watcher.addPath(str(f))
        self._scripts = scripts
        self._build_qscripts()
        self.changed.emit()

    @staticmethod
    def _glob_to_re(glob):
        return "^" + "".join(".*" if c == "*" else re.escape(c) for c in glob) + "$"

    def _wrap(self, s):
        """Wrap a userscript in a URL guard + the GM shim, ready to inject."""
        guard = json.dumps([self._glob_to_re(m) for m in s["matches"]])
        header = ("var __ns=%s, __name=%s, __ver=%s;\n"
                  % (json.dumps(s["namespace"]), json.dumps(s["name"]), json.dumps(s["version"])))
        gate = ("var __g=%s;\n"
                "if(__g.length){var __m=false;for(var __i=0;__i<__g.length;__i++){"
                "try{if(new RegExp(__g[__i]).test(location.href)){__m=true;break;}}catch(e){}}"
                "if(!__m)return;}\n" % guard)
        body = (header + _GM_SHIM
                + "\ntry{\n" + s["code"]
                + "\n}catch(e){console.error('[surfer userscript]', __name, e);}\n")
        # QtWebEngine's DocumentCreation injection fires BEFORE <html> exists
        # (document.documentElement is null), but real document-start scripts
        # (4chan X) capture document.documentElement once at eval and bail if
        # it's null. So defer the body until documentElement appears — still
        # early (before the page's own scripts run for real), but valid.
        return ("(function(){\n" + gate
                + "function __run(){\n" + body + "}\n"
                "if(document.documentElement){__run();return;}\n"
                "var __iv=setInterval(function(){if(document.documentElement){clearInterval(__iv);__run();}},0);\n"
                "})();\n")

    def _build_qscripts(self):
        # Build the QWebEngineScript objects that each WebEngineView binds to via
        # userScripts.collection (the QML view IGNORES a Python QWebEngineProfile
        # — it uses its own QQuickWebEngineProfile — so profile.scripts() never
        # reaches it; the view's own userScripts collection is the path that works).
        out = []
        world = 10  # each script gets its OWN isolated world so they don't
        for s in self._scripts:  # clobber each other's globals (4chan X vs OneeChan
            if not s["enabled"]:  # both assign window.$) — like a real GM manager
                continue
            qs = QWebEngineScript()
            qs.setName(s["file"])
            qs.setInjectionPoint(
                QWebEngineScript.InjectionPoint.DocumentCreation if s["runAt"] == "start"
                else QWebEngineScript.InjectionPoint.DocumentReady)
            qs.setWorldId(world)
            qs.setRunsOnSubFrames(False)
            qs.setSourceCode(self._wrap(s))
            out.append(qs)
            world += 1
        self._qscripts = out

    @Property("QVariantList", notify=changed)
    def scriptObjects(self):
        return self._qscripts

    @Slot(str, bool)
    def setEnabled(self, file, on):
        m = self._load_enabled()
        m[str(file)] = bool(on)
        try:
            self._enabled_path().write_text(json.dumps(m), encoding="utf-8")
        except OSError:
            pass
        self._reload()

    @Slot()
    def openFolder(self):
        self._ensure_dir()
        try:
            import subprocess
            subprocess.Popen(["xdg-open", str(self._dir)])
        except OSError:
            pass

    @Property("QVariantList", notify=changed)
    def scripts(self):
        return [{k: v for k, v in s.items() if k != "code"} for s in self._scripts]


class Session(QObject):
    """Persists the open tabs (their URLs) + the active tab index to
    $XDG_STATE_HOME/surfer/session.json, so a relaunch restores what was open.

    ``split`` is the tab index in the split view's RIGHT pane, or -1 for no
    split. It is read with a default, so a session.json written before split
    view existed restores as an ordinary single-pane window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        self._path = state / "surfer" / "session.json"

    @Slot("QVariantList", int, int)
    def save(self, urls, current, split=-1):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {"tabs": [str(u) for u in urls if str(u)], "current": int(current),
                    "split": int(split)}
            self._path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    @Slot(result="QVariantMap")
    def load(self):
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            tabs = [str(u) for u in data.get("tabs", []) if str(u)]
            try:
                split = int(data.get("split", -1))
            except (TypeError, ValueError):
                split = -1
            return {"tabs": tabs, "current": int(data.get("current", 0)), "split": split}
        except (OSError, ValueError, TypeError):
            return {"tabs": [], "current": 0, "split": -1}


class Prefs(QObject):
    """Small persisted preferences in $XDG_STATE_HOME/surfer/prefs.json: the
    page zoom level (shared across all tabs), the split view's divider position
    and orientation, and the file picker's last-used folder. Every getter reads
    with a default, so an older prefs.json is always valid."""

    def __init__(self, parent=None):
        super().__init__(parent)
        state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        self._path = state / "surfer" / "prefs.json"

    def _read(self):
        try:
            d = json.loads(self._path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _write(self, d):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(d), encoding="utf-8")
        except OSError:
            pass

    @Slot(result=float)
    def loadZoom(self):
        try:
            return float(self._read().get("zoom", 1.0))
        except (TypeError, ValueError):
            return 1.0

    @Slot(float)
    def saveZoom(self, z):
        d = self._read()
        d["zoom"] = float(z)
        self._write(d)

    # split view's divider position, as the LEADING pane's fraction of the
    # window along whichever axis the split runs (0.5 = even) — one value for
    # both orientations, so re-orienting keeps the proportion. Written on
    # release of the drag, not on every motion event.
    @Slot(result=float)
    def loadSplitRatio(self):
        try:
            r = float(self._read().get("splitRatio", 0.5))
        except (TypeError, ValueError):
            return 0.5
        return min(0.92, max(0.08, r))

    @Slot(float)
    def saveSplitRatio(self, r):
        d = self._read()
        d["splitRatio"] = float(r)
        self._write(d)

    # …and which axis that is: True = a VERTICAL divider, panes side by side
    # (kitty's `|`, "split right"); False = a horizontal one, panes stacked
    # (`_`, "split down"). Read with a default, so a prefs.json written before
    # the split had an orientation restores side by side, exactly as it was.
    @Slot(result=bool)
    def loadSplitVertical(self):
        v = self._read().get("splitVertical", True)
        return bool(v) if isinstance(v, bool) else True

    @Slot(bool)
    def saveSplitVertical(self, v):
        d = self._read()
        d["splitVertical"] = bool(v)
        self._write(d)

    # the in-window file picker's last-used folder ("pickerDir"), so a page's
    # <input type=file> reopens where the last pick came from (see Files).
    def loadPickerDir(self):
        p = self._read().get("pickerDir", "")
        return str(p) if isinstance(p, str) else ""

    def savePickerDir(self, path):
        d = self._read()
        d["pickerDir"] = str(path)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(d), encoding="utf-8")
        except OSError:
            pass

    # dark-mode settings live under the "dark" key of the same prefs.json (the
    # DarkMode bridge owns the shape — global on/off, brightness, contrast, and
    # the per-site exception list).
    def loadDark(self):
        d = self._read().get("dark", {})
        return d if isinstance(d, dict) else {}

    def saveDark(self, dark):
        d = self._read()
        d["dark"] = dark
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(d), encoding="utf-8")
        except OSError:
            pass


class Files(QObject):
    """Filesystem access for the in-window file picker (FilePicker.qml), which
    serves a page's ``<input type=file>`` / upload button.

    QtWebEngine has no built-in picker for the QML view: with no
    onFileDialogRequested handler Chromium auto-rejects the request and the
    picker simply never opens (the click registers, `onchange` never fires). We
    draw our own — hence a directory lister here rather than QtQuick.Dialogs'
    FileDialog, which would pop an unthemed GTK/portal window."""

    def __init__(self, prefs, parent=None):
        super().__init__(parent)
        self._prefs = prefs

    @Slot(str, result="QVariantList")
    def listDir(self, path):
        """One directory level as {name, path, isDir, size, hidden}. Unreadable
        dirs (and unstat-able entries) degrade to empty/zero rather than raising
        — the picker must never take the window down."""
        try:
            entries = list(os.scandir(path))
        except OSError:
            return []
        items = []
        for e in entries:
            try:
                is_dir = e.is_dir()
            except OSError:
                is_dir = False
            try:
                size = 0 if is_dir else e.stat(follow_symlinks=False).st_size
            except OSError:
                size = 0
            items.append({"name": e.name, "path": e.path, "isDir": is_dir,
                          "size": size, "hidden": e.name.startswith(".")})
        return items

    @Slot(str, result=str)
    def parentOf(self, path):
        return str(Path(str(path)).parent)

    @Slot(str, result=bool)
    def isDir(self, path):
        return os.path.isdir(str(path))

    @Slot(str, str, result=str)
    def join(self, directory, name):
        return str(Path(str(directory)) / str(name))

    @Slot(result=str)
    def startDir(self):
        """Where to open: the last folder a pick came from, else ~/Downloads
        (what a page most often wants back), else $HOME."""
        last = self._prefs.loadPickerDir()
        if last and os.path.isdir(last):
            return last
        dl = str(Path.home() / "Downloads")
        return dl if os.path.isdir(dl) else str(Path.home())

    @Slot(str)
    def rememberDir(self, path):
        if path and os.path.isdir(str(path)):
            self._prefs.savePickerDir(str(path))


class Zoom(QObject):
    """The single shared page-zoom level (all tabs), persisted to prefs.json and
    the source of truth QML re-applies to every view. Ctrl+wheel is captured by
    ZoomFilter (below) and only ever lands here via bump(); the views NEVER
    persist their own zoomFactor, because QtWebEngine resets zoomFactor to 1.0 on
    every navigation and that involuntary change is indistinguishable from a real
    zoom — persisting it would clobber the saved level on every page load."""

    levelChanged = Signal()

    def __init__(self, prefs, parent=None):
        super().__init__(parent)
        self._prefs = prefs
        self._level = prefs.loadZoom()

    def _get(self):
        return self._level

    def _set(self, v):
        v = max(0.3, min(5.0, float(v)))
        if abs(v - self._level) < 1e-6:
            return
        self._level = v
        self.levelChanged.emit()
        self._prefs.saveZoom(v)

    level = Property(float, _get, _set, notify=levelChanged)

    @Slot(int)
    def bump(self, direction):
        self._set(self._level * (1.1 if direction > 0 else (1.0 / 1.1)))

    @Slot()
    def reset(self):
        self._set(1.0)


class DarkMode(QObject):
    """Page-appearance overrides, injected as one <style> per page:

      * dark mode — a whole-page CSS invert+hue-rotate filter (Dark Reader's
        *filter* mode) with adjustable brightness/contrast. Media (img/video/
        canvas/iframe/embed) gets the EXACT inverse filter, so images come out
        pixel-identical to the original at ANY brightness/contrast — dark mode
        never tints or dims them. Global on/off + a per-site exception list
        (hostnames forced OFF — the "whitelist").
      * system font — force the desktop pixel font on a page's text, so it reads
        in the same typeface as the rest of the desktop. Per-site (an opt-in set
        of hostnames); family only, so site font-sizes and layout survive. It
        combines with dark mode rather than replacing it.

    All state persists to the "dark" key of prefs.json. Application is NOT
    per-view at load-finished (that painted light first and flipped once images
    finished): a profile-level DocumentCreation courier (PAGE_STYLE_RUNTIME_JS)
    adopts the combined style as a constructed CSSStyleSheet before the first
    frame, and `css(url)` re-feeds it whenever a toggle or a slider moves —
    see PageStyleHandler. `js(url)` below remains the in-process/manual apply
    used by offscreen harnesses, not the live path.

    Known limit (shared with Dark Reader's filter mode): a full-page CSS filter
    can interfere with `position:fixed` containment on some sites.
"""

    changed = Signal()

    # The desktop's pixel font — matches qml/theme/Theme.qml's `font` (that
    # file reads DeskStyle.fontFamily, i.e. settings.json). Read the LIVE pick
    # the same way instead of pinning the default, so the system-font override
    # follows the Settings > pixel font choice. Fallback only for harnesses
    # that construct DarkMode without a DeskStyle (find/pagestyle tests).
    _SYSTEM_FONT = "More Perfect DOS VGA"

    def __init__(self, prefs, parent=None, style=None):
        super().__init__(parent)
        self._prefs = prefs
        self._style = style
        d = prefs.loadDark()
        self._enabled = bool(d.get("enabled", False))
        self._brightness = self._clamp(d.get("brightness", 100))
        self._contrast = self._clamp(d.get("contrast", 100))
        # hostnames where dark mode is turned OFF (Dark Reader's per-site
        # exceptions) — applied everywhere else when the global toggle is on.
        self._exceptions = set(str(h) for h in d.get("exceptions", []) if h)
        # hostnames where the system-font override is turned ON (opt-in per site).
        self._font_sites = set(str(h) for h in d.get("fontSites", []) if h)

    @staticmethod
    def _clamp(v):
        try:
            return max(50, min(150, int(v)))
        except (TypeError, ValueError):
            return 100

    @staticmethod
    def _host(url):
        try:
            return QUrl(url).host().lower()
        except Exception:
            return ""

    def _persist(self):
        self._prefs.saveDark({
            "enabled": self._enabled,
            "brightness": self._brightness,
            "contrast": self._contrast,
            "exceptions": sorted(self._exceptions),
            "fontSites": sorted(self._font_sites),
        })

    def _get_enabled(self):
        return self._enabled

    enabled = Property(bool, _get_enabled, notify=changed)


    def _get_brightness(self):
        return self._brightness

    brightness = Property(int, _get_brightness, notify=changed)

    def _get_contrast(self):
        return self._contrast

    contrast = Property(int, _get_contrast, notify=changed)

    @Slot(bool)
    def setEnabled(self, on):
        on = bool(on)
        if on == self._enabled:
            return
        self._enabled = on
        self._persist()
        self.changed.emit()

    @Slot(int)
    def setBrightness(self, v):
        v = self._clamp(v)
        if v == self._brightness:
            return
        self._brightness = v
        self._persist()
        self.changed.emit()

    @Slot(int)
    def setContrast(self, v):
        v = self._clamp(v)
        if v == self._contrast:
            return
        self._contrast = v
        self._persist()
        self.changed.emit()

    @Slot(str, result=bool)
    def isSystemFontSite(self, url):
        """Whether the system-font override is on for this URL's host."""
        h = self._host(url)
        return bool(h) and h in self._font_sites

    @Slot(str)
    def toggleSystemFontSite(self, url):
        h = self._host(url)
        if not h:
            return
        if h in self._font_sites:
            self._font_sites.discard(h)
        else:
            self._font_sites.add(h)
        self._persist()
        self.changed.emit()

    @Slot(str, result=bool)
    def isSiteEnabled(self, url):
        """Whether dark mode applies to this URL's host (host not in the
        exception list). Independent of the global toggle — the per-site bit."""
        h = self._host(url)
        return bool(h) and h not in self._exceptions

    @Slot(str)
    def toggleSite(self, url):
        h = self._host(url)
        if not h:
            return
        if h in self._exceptions:
            self._exceptions.discard(h)
        else:
            self._exceptions.add(h)
        self._persist()
        self.changed.emit()

    def _dark_css(self):
        # NB: keep this %-free — the literal "100%" would collide with str
        # %-formatting, so interpolate by concatenation.
        #
        # The page filter is  invert · hue · brightness(b) · contrast(c).  Media
        # gets that filter's EXACT inverse so image = original: each function is
        # self-/reciprocally-invertible (invert & hue-180 are self-inverse;
        # brightness(b)->brightness(1/b); contrast(c)->contrast(1/c)) and the
        # inverse list is the reversed sequence of inverses. Result: images are
        # untouched at any brightness/contrast, not just at 100/100.
        b = str(self._brightness)
        c = str(self._contrast)
        inv_b = str(round(10000 / self._brightness))   # 100/b as a percentage
        inv_c = str(round(10000 / self._contrast))
        return (
            "html{filter:invert(100%) hue-rotate(180deg) "
            "brightness(" + b + "%) contrast(" + c + "%)!important;"
            "background:#181818!important}"
            "img,picture,video,canvas,iframe,embed,object{"
            "filter:contrast(" + inv_c + "%) brightness(" + inv_b + "%) "
            "hue-rotate(180deg) invert(100%)!important}"
        )

    # ---- pre-compensating a colour we draw INSIDE the filtered page ----------
    #
    # Anything the chrome paints into the page — the find highlight — is drawn
    # inside `html`, so dark mode inverts it along with everything else. The
    # find highlight is the case that made this necessary: Chromium's own
    # marker yellow came out #252500 on a black page, i.e. invisible, which is
    # exactly what "find only scrolls" looks like from the outside.
    #
    # The fix is the one _dark_css already uses for media, run backwards: the
    # chain invert -> hue-rotate(180) -> brightness(b) -> contrast(c) is
    # invertible, so ask for the colour whose IMAGE under it is the palette
    # colour we wanted. Measured offscreen: the pixels that land are the
    # palette hex exactly, at any brightness/contrast.
    #
    # The CSS hue-rotate(180deg) matrix (sRGB, the shorthand filter's own
    # colour space — not a true hue rotation, which is why it is written out
    # rather than derived).
    _HUE180 = ((-0.574, 1.430, 0.144),
               (0.426, 0.430, 0.144),
               (0.426, 1.430, -0.856))
    # its inverse, computed once (determinant 1.0)
    _HUE180_INV = None

    @classmethod
    def _hue180_inv(cls):
        if cls._HUE180_INV is None:
            (a, b, c), (d, e, f), (g, h, i) = cls._HUE180
            det = (a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g))
            cls._HUE180_INV = (
                ((e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det),
                ((f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det),
                ((d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det))
        return cls._HUE180_INV

    @Slot(str, str, result=str)
    def compensate(self, url, color):
        """The `#rrggbb` to paint into this page so that it RENDERS as `color`.

        Identity when dark mode does not apply to this URL, so the caller has
        one code path and never has to ask whether the filter is on."""
        try:
            c = str(color).lstrip("#")
            want = [int(c[k:k + 2], 16) / 255.0 for k in (0, 2, 4)]
        except (ValueError, IndexError):
            return color
        if not (self._enabled and self.isSiteEnabled(url)):
            return color
        b = self._brightness / 100.0
        k = self._contrast / 100.0
        v = [(x - 0.5) / k + 0.5 for x in want]     # undo contrast(c)
        v = [x / b for x in v]                      # undo brightness(b)
        m = self._hue180_inv()                      # undo hue-rotate(180deg)
        v = [sum(m[r][j] * v[j] for j in range(3)) for r in range(3)]
        v = [1.0 - x for x in v]                    # undo invert(100%)
        return "#" + "".join("%02x" % max(0, min(255, round(x * 255))) for x in v)

    def _font_css(self):
        # Force the desktop pixel font on all page text (family only — sizes stay
        # the site's, so layout/heading hierarchy survives). Reads the LIVE pick
        # from DeskStyle so a Settings > pixel font change shows here too, falling
        # back to the default family only when no DeskStyle was supplied.
        f = json.dumps(self._style.fontFamily if self._style is not None else DarkMode._SYSTEM_FONT)
        return "*,*::before,*::after{font-family:" + f + ",monospace!important}"

    @Slot(str, result=str)
    def css(self, url):
        """The page-style CSS Python computes for this url right now (dark mode
        and/or the system-font override, whichever applies) — the body the
        `surferstyle://` courier adopts at document-creation and re-fetches on
        a settings change. Empty string = the theme should be stripped here."""
        return self._css(url)

    def _css(self, url):
        parts = []
        if self._enabled and self.isSiteEnabled(url):
            parts.append(self._dark_css())
        if self.isSystemFontSite(url):
            parts.append(self._font_css())
        return "".join(parts)

    @Slot(str, result=str)
    def js(self, url):
        """JS that installs OR removes the page-style <style> for this url given
        the current state — one call handles both apply and un-apply.

        This is the in-process/manual apply (the offscreen find-pixel harness
        drives it directly). The live page path is the DocumentCreation courier
        (PAGE_STYLE_RUNTIME_JS + PageStyleHandler), which is what lands before
        the first paint; this remains a faithful equivalent of that CSS so the
        two can never disagree about what dark mode looks like."""
        css = self._css(url)
        return (
            "(function(){var id='__surfer_pagestyle__';"
            "var s=document.getElementById(id);"
            "var css=%s;"
            "if(!css){if(s)s.remove();return;}"
            "if(!s){s=document.createElement('style');s.id=id;"
            "(document.head||document.documentElement).appendChild(s);}"
            "s.textContent=css;})();"
            % json.dumps(css)
        )


# Wheel handling here is the QtWebEngine half of the desktop's kinetic-scroll
# contract; momentum itself is synthesized COMPOSITOR-side (hyprvtb, see
# apps/pylib/kinetic.py and docs/kinetic-scroll.md). WHEEL_GAIN and the
# touchpad/wheel discriminator live in pylib/kinetic.py — the ONE place — so
# they cannot drift from apps/qmlcommon/WheelScroll.qml the way two hand-kept
# copies did.


class ZoomFilter(QObject):
    """Ctrl+wheel and Ctrl +/-/0 -> shared zoom, plus trackpad wheel-gain
    correction, installed on the top-level WINDOW (not the QApplication — an
    app-wide event filter segfaults this PySide6/Py3.14 build wrapping
    transient QObjects during focus events; a window-scoped filter only ever
    sees `obj == the window`, which is stable). The QQuickWindow receives
    input from the platform BEFORE it is delivered down to the WebEngineView
    item, so consuming it here (return True) both drives our zoom AND
    suppresses Chromium's own Ctrl+wheel / Ctrl+/- zoom — leaving zoomFactor
    to change only when we set it.

    Plain (unmodified) TOUCHPAD wheel events are consumed and re-sent scaled
    by WHEEL_GAIN, with fractional remainders carried so the sub-pixel tail of
    a kinetic glide is not rounded to death; real mouse-wheel detents
    (_is_wheel_detent) and zero-delta phase markers
    (ScrollBegin/ScrollEnd) passed through untouched so scroll sequences stay
    coherent. NB this is window-wide: wheel over the QML overlays is scaled
    too, so the file picker's KineticListView takes `wheelGain: WheelGain`
    (= 1/WHEEL_GAIN, published from pylib/kinetic.py) to undo it. Any future
    scrollable QML surface in this window must do the same."""

    _ZOOM_IN_KEYS = (Qt.Key.Key_Plus, Qt.Key.Key_Equal)  # Ctrl++ and Ctrl+=

    def __init__(self, zoom, parent=None):
        super().__init__(parent)
        self._zoom = zoom
        self._rescaling = False  # re-sent events must not be scaled again
        self._carry_px = [0.0, 0.0]  # fractional pixelDelta remainder (x, y)
        self._carry_ang = [0.0, 0.0]  # fractional angleDelta remainder (x, y)

    def _scaled(self, carry, i, v):
        carry[i] += v * WHEEL_GAIN
        out = int(carry[i])
        carry[i] -= out
        return out

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                dy = event.angleDelta().y()
                if dy != 0:
                    self._zoom.bump(1 if dy > 0 else -1)
                    return True
            elif not self._rescaling:
                px, ang = event.pixelDelta(), event.angleDelta()
                if px.isNull() and ang.isNull():
                    return False  # phase marker (Begin/End): pass untouched
                if _is_wheel_detent(px, ang):
                    return False  # real wheel: Chromium's own step, untouched
                spx = QPoint(self._scaled(self._carry_px, 0, px.x()),
                             self._scaled(self._carry_px, 1, px.y()))
                sang = QPoint(self._scaled(self._carry_ang, 0, ang.x()),
                              self._scaled(self._carry_ang, 1, ang.y()))
                if spx.isNull() and sang.isNull():
                    return True  # everything carried; a zero event would read
                    # as a fake phase marker downstream, so emit nothing
                ev = QWheelEvent(event.position(), event.globalPosition(),
                                 spx, sang, event.buttons(),
                                 event.modifiers(), event.phase(),
                                 event.inverted())
                self._rescaling = True
                try:
                    QCoreApplication.sendEvent(obj, ev)
                finally:
                    self._rescaling = False
                return True
        elif t == QEvent.Type.KeyPress:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                k = event.key()
                if k in self._ZOOM_IN_KEYS:
                    self._zoom.bump(1)
                    return True
                if k == Qt.Key.Key_Minus:
                    self._zoom.bump(-1)
                    return True
                if k == Qt.Key.Key_0:
                    self._zoom.reset()
                    return True
        return False


class HotkeyFilter(QObject):
    """The chrome's own keyboard shortcuts — today just Ctrl+F for
    find-in-page — installed on the top-level WINDOW for exactly the reason
    ZoomFilter is (see its docstring: an app-wide filter segfaults this
    PySide6/Py3.14 build, and the QQuickWindow sees platform input BEFORE the
    WebEngineView item does).

    A QML `Shortcut` is NOT an option here: while a WebEngineView has the focus
    Chromium takes the key stream, so the shortcut either never fires or races
    a page that binds Ctrl+F itself. Consuming the event here (return True) both
    opens our find bar and makes sure the page never sees the key — QtWebEngine
    has no find UI of its own for it to reach.

    Escape deliberately stays OUT of this filter. It only needs to close the bar
    while the bar's own field holds the keyboard, and Qt already delivers it
    there (FindBar.qml's Keys.onPressed); taking Escape window-wide would
    steal it from every page that uses it."""

    find = Signal()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if (event.modifiers() & Qt.KeyboardModifier.ControlModifier
                    and event.key() == Qt.Key.Key_F):
                self.find.emit()
                return True
        return False


class AdBlocker(QWebEngineUrlRequestInterceptor):
    """Ad/tracker blocking via Brave's adblock-rust engine (the `adblock` pip
    package) — the same filter engine class uBlock Origin is, so it applies the
    FULL Adblock rule syntax, not just host blocking: host-anchored rules,
    path/URL patterns (`/pagead/`, `||site.com/adframe.js`), resource-type
    options (`$script,image,third-party`), and exceptions. Cosmetic
    element-hiding (`##`) from the same engine is applied separately by the
    Cosmetic bridge (injected CSS) — together that's ~uBO-parity blocking.

    Subscribes to the same lists uBO/ABP ship — uBO's OWN filter set (the
    thing that actually kills video/pre-roll ads), EasyList, EasyPrivacy,
    StevenBlack's unified hosts, oisd big, URLhaus — cached under
    $XDG_CACHE_HOME/surfer/filters/ and refreshed in the background every
    _REFRESH_DAYS. The raw list text is fed straight to the engine, so every
    rule type is honoured.

    Three things the engine cannot do on its own, all handled here:

      * SCRIPTLETS. adblock-rust only materialises a scriptlet body once its
        RESOURCE LIBRARY is loaded — with none, `injected_script` is always the
        empty string and every `##+js(...)` rule in every list is silently a
        no-op. That is why first-party video ads (YouTube, Twitch: same origin,
        same /videoplayback endpoint as the real video — no URL to block) went
        straight through. `_load_resources()` fills it; see _UBO_TAG.
      * PROCEDURAL COSMETICS. `##…:has(…)` rules are dropped wholesale by this
        engine version. `_scan_procedural()` recovers the ones Chromium can
        evaluate natively; see `procedural_selectors`.
      * A PARSER BUG in the pinned engine — see `_sanitize`.

    Fallback: if the `adblock` module isn't importable (e.g. air's Fedora
    system-python before `pip install --user adblock`), it degrades to a
    pure-Python domain-suffix blocker built from the host-anchored subset of the
    same lists — still ~450k domains, just no path/cosmetic rules. The _BUILTIN
    set seeds both paths so blocking works on first run before any list has
    been fetched.

    Overridable via $XDG_CONFIG_HOME/surfer/blocklist.txt — one host per line,
    `# comment`, and a leading `!` ALLOW-lists a host the lists would otherwise
    block (escape hatch if a block breaks a site; becomes an `@@||host^` rule
    under the engine). A line that already looks like an Adblock rule (starts
    `||`/`@@`/`/`, or carries a `$` option) is passed to the engine VERBATIM, so
    the escape hatch is as expressive as the lists themselves rather than
    host-granular only. Subscription URLs can be replaced, one per line, in
    $XDG_CONFIG_HOME/surfer/subscriptions.txt."""

    _SUBSCRIPTIONS = [
        # uBlock Origin's own filters — the "uBlock filters" component plus the
        # four uBO ships enabled beside it. NOT optional garnish: these are where
        # the ##+js(...) scriptlet rules live, and scriptlets are the only thing
        # that stops a FIRST-PARTY video/pre-roll ad (YouTube, Twitch), which by
        # construction has no third-party URL for a network rule to match.
        # The yearly files are archive slices of the same component and uBO has
        # all of them enabled by default; dropping them loses most of its rules.
        "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/filters.txt",
        "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/filters-2020.txt",
        "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/filters-2021.txt",
        "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/filters-2022.txt",
        "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/filters-2023.txt",
        "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/filters-2024.txt",
        "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/filters-2025.txt",
        "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/filters-2026.txt",
        "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/filters-general.txt",
        "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/unbreak.txt",
        "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/privacy.txt",
        "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/quick-fixes.txt",
        "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/badware.txt",
        "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/resource-abuse.txt",
        # Adblock-syntax network lists (same ones uBlock/ABP enable by default).
        "https://easylist.to/easylist/easylist.txt",
        "https://easylist.to/easylist/easyprivacy.txt",
        # StevenBlack's unified hosts (folds in Peter Lowe's + a dozen others).
        "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
        # oisd big — a hosts/DNS-blocklist curated for exactly this domain-suffix
        # model, low false-positive, adds ~260k domains the others miss.
        "https://big.oisd.nl/",
        # URLhaus — active malware/phishing hosts (a security dimension the
        # ad/tracker lists don't cover).
        "https://urlhaus.abuse.ch/downloads/hostfile/",
    ]
    _REFRESH_DAYS = 7
    _HOSTRE = re.compile(r"^[a-z0-9._-]+$")

    # The scriptlet + redirect RESOURCE library, which adblock-rust needs before
    # it will emit a single scriptlet body. **There are two of them, because
    # there are two engines**, and the format is not interchangeable: 0.11
    # deleted the `template` resource kind (`{{1}}` placeholders) in favour of
    # plain javascript whose helper functions the engine splices in from a
    # `dependencies` field. Registering the wrong one is not an error — it just
    # silently stops substituting arguments, which is exactly the failure this
    # whole subsystem exists to remove. `_resource_source()` picks by
    # feature-detecting the engine, and the choice is part of the cache stamp.
    #
    # MODERN (top, jampe fork = adblock-rust 0.12.5). adblock-rust's own
    # assembled production library, 208 entries, kept current upstream.
    # Measured against the live fork: **100.0% of scriptlet rules resolve**
    # (9551/9554), dependencies are spliced in and arguments substituted —
    # including `json-prune-xhr-response` on YouTube's `/player` endpoint,
    # which is the modern pre-roll defence and does not exist at all in the
    # 2023 library below.
    _BRAVE_RESOURCES = ("https://raw.githubusercontent.com/brave/adblock-rust/"
                        "master/data/brave/brave-resources.json")
    # (NOT `brave/adblock-resources`'s dist/resources.json — that is Brave's own
    # 17 custom scriptlets and contains no uBO library at all.)
    #
    # LEGACY (book: Fedora system python, PyPI `adblock` 0.6.0 = adblock-rust
    # 0.5.6, which has only the template kind). uBO 1.48.6 is the LAST release
    # whose assets/resources/scriptlets.js is the flat `/// name.js` + `{{1}}`
    # template format; 1.49 turned it into the ES-module graph only >= 0.9 can
    # assemble. Measured coverage there: 2647 of 3245 scriptlet rules (81.6%),
    # the misses being mostly the newer `trusted-*` family. This branch exists
    # so book DEGRADES rather than breaks — do not delete it because top no
    # longer takes it. One tarball, stdlib tarfile, ~3.6 MB.
    _UBO_TAG = "1.48.6"
    _UBO_TARBALL = "https://codeload.github.com/gorhill/uBlock/tar.gz/refs/tags/" + _UBO_TAG

    # Rules appended after every subscription, so they win on specificity and
    # on `$important`.
    #
    # 4chan's ads are SELF-HOSTED and first-party, and EasyList carries explicit
    # `@@||4cdn.org/adv/` / `@@||4channel.org/adv/` allow-list exceptions for
    # them (easylist.txt:81918-81919) — so every ad path there passes today.
    # `$important` is the one operator that beats an `@@` exception, and a path
    # rule is the only precise instrument: blocking the HOST would take out
    # s.4cdn.org's stylesheets and sprites and i.4cdn.org's images with it, and
    # blocklist.txt (host-granular) therefore cannot express this at all.
    # `$important` here is FINAL — no exception undoes it in this engine — so
    # blocklist.txt cancels one of these by suppressing it rather than by
    # allow-listing over it; see _custom_rules().
    _CUSTOM_RULES = [
        "||4chan.org/adv/$important",
        "||4channel.org/adv/$important",
        "||4cdn.org/adv/$important",
    ]

    # Element-hiding EXCEPTION options this engine version mis-parses; see
    # _sanitize.
    _HIDE_OPT = re.compile(
        r"(?:^|,)(?:generichide|ghide|elemhide|ehide|specifichide|shide)(?:,|$)")
    _DOMAIN_OPT = re.compile(r"(?:^|,)domain=([^,]*)")

    # Cosmetic rule, either flavour: `dom##sel`, `dom#@#sel`, `dom#?#sel`.
    # Deliberately does NOT match `#$#`: that separator means "ABP snippet" in
    # an ABP list and "AdGuard CSS injection" in an AdGuard one — same token,
    # incompatible meanings — so reading it correctly needs a per-list vendor
    # flag we don't keep. Not matching it is the safe reading.
    _COSMETIC_RE = re.compile(r"^([^#!|@\s]*)#(@?)(\??)#(.+)$")
    # uBO/ABP procedural pseudo-classes Chromium has no native equivalent for.
    # A selector carrying any of these cannot be emitted as CSS at all.
    _PROC_UNSUPPORTED = re.compile(
        r":-abp-|:has-text\(|:matches-css|:matches-path\(|:matches-attr\("
        r"|:matches-media\(|:matches-prop\(|:min-text-length\(|:upward\("
        r"|:nth-ancestor\(|:xpath\(|:watch-attr\(|:remove\(|:remove-attr\("
        r"|:remove-class\(|:style\(|:others\(|:shadow\(|:if\(|:if-not\(|:contains\(")

    _BUILTIN = {
        # ad serving
        "doubleclick.net", "googlesyndication.com", "googleadservices.com",
        "adservice.google.com", "2mdn.net", "amazon-adsystem.com", "adnxs.com",
        "adsrvr.org", "rubiconproject.com", "pubmatic.com", "openx.net",
        "criteo.com", "criteo.net", "taboola.com", "outbrain.com", "moatads.com",
        "serving-sys.com", "casalemedia.com", "bidswitch.net", "sharethrough.com",
        "teads.tv", "yieldmo.com", "media.net", "zedo.com", "smartadserver.com",
        "advertising.com", "adform.net", "adcolony.com", "applovin.com",
        "adsafeprotected.com", "doubleverify.com", "3lift.com", "gumgum.com",
        "indexww.com", "contextweb.com", "sonobi.com", "districtm.io",
        # analytics / trackers
        "google-analytics.com", "googletagmanager.com", "googletagservices.com",
        "scorecardresearch.com", "quantserve.com", "chartbeat.com", "hotjar.com",
        "mixpanel.com", "segment.com", "segment.io", "branch.io", "krxd.net",
        "demdex.net", "omtrdc.net", "everesttech.net", "bluekai.com", "agkn.com",
        "rlcdn.com", "gemius.pl", "newrelic.com", "nr-data.net", "optimizely.com",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        cfg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "surfer"
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "surfer" / "filters"
        self._cfg = cfg
        self._cache = cache
        self._subs = self._resolve_subs(cfg)
        self._engine = None                 # adblock-rust Engine when available
        self._engine_dat = cache / "engine.dat"   # the COMPILED engine, cached
        self._engine_meta = cache / "engine.meta"  # what that cache was built FROM
        self._resources = cache / "resources.json"  # assembled uBO scriptlets/redirects
        self._res = []                      # the parsed resource list, if any
        # domain -> ((selector, excluded-domains), ...) for the `:has()` rules
        # this engine version drops; see _scan_procedural.
        self._proc = {}
        self._proc_n = 0
        # (blocked, third_party_only, allow) — the pure-python fallback tables,
        # swapped atomically by _compile() when there's no engine. Seeded with the
        # BUILTIN ad hosts so the ~90 obvious ones are blocked from the first
        # request, before the full engine has finished loading on the thread below.
        self._tables = (frozenset(self._BUILTIN), frozenset(), frozenset())
        # ALL blocklist compilation runs on this daemon thread — none of it is on
        # the critical path, so the window and page load start immediately. The
        # engine (self._engine) is published by a single atomic attribute
        # assignment; the interceptor reads it lock-free and just uses the BUILTIN
        # host-set until it appears (~166 ms from the compiled cache, one-time
        # ~900 ms to compile from raw lists on the very first run).
        threading.Thread(target=self._startup, daemon=True).start()

    @staticmethod
    def _log(msg):
        # Every diagnostic in this class goes through here, so `surfer adblock:`
        # greps the whole subsystem out of ~/.cache/surfer.log.
        sys.stderr.write("surfer adblock: %s\n" % msg)
        try:
            sys.stderr.flush()
        except Exception:
            pass

    def _startup(self):
        t0 = time.time()
        self._load_resources()
        # Fast path: deserialize the pre-compiled engine from cache (~5x faster
        # than re-parsing the raw lists). Falls back to a fresh compile (which
        # then seeds the cache) when there's no usable cache yet — or when the
        # cache was built from a different set of lists/resources/user rules,
        # which is what _cache_stamp() detects.
        if not self._load_engine_cache():
            self._compile()
            self._save_engine_cache()
        self._scan_procedural()
        self._log("startup complete in %.2fs" % (time.time() - t0))
        self._refresh()

    # ---- the compiled-engine cache, and knowing when it is stale ------------
    def _cache_stamp(self):
        """Identity of everything the compiled engine was built from. A cached
        engine.dat whose stamp doesn't match is ignored and rebuilt — without
        this, adding a subscription or editing blocklist.txt changed nothing
        until the 7-day refresh happened to fire."""
        h = hashlib.sha1()
        # Bump on ANY change to how the engine is built (rule sources, the
        # sanitizer, the custom-rule derivation) — the hashed inputs below
        # cannot see a code change, only a data one.
        h.update(b"v4\x00")
        # The ENGINE's own identity. adblock-rust's serialized DAT format has
        # had no cross-version compatibility since 0.10.0, so a package bump
        # must invalidate engine.dat or deserialize_from_file loads garbage —
        # and the resource format changed under us too (see _resource_source).
        h.update(("%s\x00%s\x00" % (self._adblock_version(), self._resource_source()[0])).encode())
        for url in self._subs:
            h.update(url.encode() + b"\x00")
        for rule in self._CUSTOM_RULES:
            h.update(rule.encode() + b"\x00")
        try:
            h.update((self._cfg / "blocklist.txt").read_bytes())
        except OSError:
            pass
        h.update(b"%d" % len(self._res))
        h.update(self._UBO_TAG.encode())
        return h.hexdigest()

    def _load_engine_cache(self):
        try:
            from adblock import Engine, FilterSet
        except Exception:
            self._log("`adblock` not importable — pure-python host-set fallback")
            return False
        try:
            if not self._engine_dat.exists():
                return False
            want = self._cache_stamp()
            try:
                got = self._engine_meta.read_text(encoding="utf-8").strip()
            except OSError:
                got = ""
            if got != want:
                self._log("engine cache stale (%s != %s) — recompiling"
                          % (got[:8] or "none", want[:8]))
                return False
            eng = Engine(FilterSet())
            try:
                eng.deserialize_from_file(str(self._engine_dat))
            except Exception as e:
                # adblock.DeserializationError: VersionMismatch(0) — what the
                # live 28 MB cache written by 0.5.6 raises against the fork's
                # 0.12.5. Caught by NAME as well as by type, because the class
                # is not importable from every binding version.
                if type(e).__name__ == "DeserializationError" or "ersion" in str(e):
                    self._log("engine cache is a foreign DAT format (%s) — recompiling" % e)
                else:
                    self._log("engine cache would not deserialize (%s) — recompiling" % e)
                return False
            self._engine = eng
            # Resources DO survive serialize/deserialize, but re-adding is cheap
            # and makes a refreshed resources.json take effect without waiting
            # for a list change.
            self._load_engine_resources(eng)
            self._log("loaded compiled engine from cache (%s)" % self._engine_dat)
            return True
        except Exception as e:
            self._log("engine cache unusable (%s) — recompiling" % e)
            return False

    def _save_engine_cache(self):
        eng = self._engine
        if eng is None:
            return
        try:
            self._engine_dat.parent.mkdir(parents=True, exist_ok=True)
            eng.serialize_to_file(str(self._engine_dat))
            self._engine_meta.write_text(self._cache_stamp() + "\n", encoding="utf-8")
        except Exception as e:
            self._log("could not write the engine cache (%s)" % e)

    # ---- subscription list resolution --------------------------------------
    def _resolve_subs(self, cfg):
        try:
            subs = []
            for line in (cfg / "subscriptions.txt").read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s and not s.startswith("#"):
                    subs.append(s)
            if subs:
                return subs
        except OSError:
            pass
        return list(self._SUBSCRIPTIONS)

    def _cache_path(self, url):
        return self._cache / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".txt")

    # ---- the uBO resource library ------------------------------------------
    # adblock-rust resolves a `##+js(name, arg…)` rule by looking `name` up in
    # its resource storage and substituting the args into the body's `{{1}}`,
    # `{{2}}` … placeholders. With no resources loaded the lookup always fails
    # and `injected_script` is the empty string — which is exactly the state
    # surfer shipped in, and the reason first-party video ads were untouched.
    #
    # Assembly is a faithful port of adblock-rust's own
    # `resources/resource_assembler.rs` (read_template_resources +
    # read_redirectable_resource_mapping), so the bodies we register are
    # byte-for-byte what Brave registers from the same uBO tree.
    _RES_MIME = {
        "css": "text/css", "gif": "image/gif", "html": "text/html",
        "js": "application/javascript", "json": "application/json",
        "mp3": "audio/mp3", "mp4": "video/mp4", "png": "image/png",
        "txt": "text/plain", "xml": "text/xml",
    }
    _RES_TOP_COMMENT = re.compile(r"^/\*[\S\s]+?\n\*/\s*")
    _RES_MAP_DECL = "export default new Map(["
    _RES_MAP_END = re.compile(r"^\s*\]\s*\)")
    _RES_TRAILING_COMMA = re.compile(r",([\],\}])")
    _RES_UNQUOTED_FIELD = re.compile(r"([\{,])([a-zA-Z][a-zA-Z0-9_]*):")
    _RES_TRAILING_BLOCK_COMMENT = re.compile(r"\s*/\*[^'\"]*\*/\s*$")

    @classmethod
    def _parse_scriptlets(cls, text):
        """uBO `assets/resources/scriptlets.js` (flat `/// name` format) ->
        resource dicts. A body containing `{{1}}` is a TEMPLATE (args get
        substituted); anything else is plain javascript."""
        out = []
        text = cls._RES_TOP_COMMENT.sub("", text, count=1)
        name, aliases, script = None, [], []
        for line in text.splitlines():
            if line.startswith("#") or line.startswith("// ") or line == "//":
                continue
            if name is None:
                if line.startswith("/// "):
                    name = line[4:].strip()
                continue
            if line.startswith("/// "):
                parts = line[4:].split()
                if len(parts) >= 2 and parts[0] == "alias":
                    aliases.append(parts[1])
                continue
            if line.strip():
                script.append(line.strip())
                continue
            body = ("\n".join(script) + "\n") if script else ""
            out.append({
                "name": name, "aliases": aliases,
                "content_type": "template" if "{{1}}" in body else "application/javascript",
                "content": base64.b64encode(body.encode()).decode(),
            })
            name, aliases, script = None, [], []
        return out

    @classmethod
    def _parse_redirect_map(cls, text):
        """uBO `src/js/redirect-resources.js` -> [(name, props)] . The exported
        `Map` is coerced into JSON rather than evaluated, same as upstream —
        a strict parser catches a format change instead of silently drifting."""
        lines = text.splitlines()
        try:
            start = lines.index(cls._RES_MAP_DECL)
        except ValueError:
            return []
        buf = []
        for i, line in enumerate(lines[start:]):
            if i and cls._RES_MAP_END.match(line):
                break
            cut = line.find("//")
            if cut >= 0:
                line = line[:cut]
            buf.append(cls._RES_TRAILING_BLOCK_COMMENT.sub("", line))
        blob = "".join(buf) + "]"
        blob = blob[len(cls._RES_MAP_DECL) - 1:].replace("'", '"')
        blob = "".join(blob.split())
        blob = cls._RES_TRAILING_COMMA.sub(lambda m: m.group(1), blob)
        blob = cls._RES_UNQUOTED_FIELD.sub(
            lambda m: '%s"%s":' % (m.group(1), m.group(2)), blob)
        return json.loads(blob)

    @classmethod
    def _assemble_resources(cls, tgz):
        """uBO source tarball (bytes) -> the resource list add_resource wants."""
        tf = tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz")
        root = tf.getnames()[0].split("/")[0]

        def rd(path):
            f = tf.extractfile("%s/%s" % (root, path))
            return f.read() if f is not None else None

        res = cls._parse_scriptlets(rd("assets/resources/scriptlets.js").decode())
        n_scriptlets = len(res)
        for entry in cls._parse_redirect_map(rd("src/js/redirect-resources.js").decode()):
            name, props = entry[0], entry[1]
            if props.get("params"):         # parameterised redirects: unsupported
                continue
            alias = props.get("alias") or []
            if isinstance(alias, str):
                alias = [alias]
            data = rd("src/web_accessible_resources/%s" % name)
            if data is None:
                continue
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            mime = cls._RES_MIME.get(ext, "application/octet-stream")
            if mime in ("application/javascript", "text/html", "text/plain"):
                data = data.decode("utf-8", "ignore").replace("\r", "").encode()
            res.append({"name": name, "aliases": alias, "content_type": mime,
                        "content": base64.b64encode(data).decode()})
        return res, n_scriptlets

    @staticmethod
    def _adblock_version():
        try:
            import adblock
            return str(getattr(adblock, "__version__", "?"))
        except Exception:
            return "none"

    @classmethod
    def _resource_source(cls):
        """(id, url) for the resource library this engine can actually use.

        Feature-detected, not version-gated: `Engine.add_resources` (plural) is
        the modern batch API and arrived alongside the modern resource format,
        while `add_resource` (singular) was deleted in the same release. So the
        presence of one or the other says which format the engine speaks."""
        try:
            from adblock import Engine
        except Exception:
            return ("ubo-" + cls._UBO_TAG, cls._UBO_TARBALL)
        if hasattr(Engine, "add_resource"):
            return ("ubo-" + cls._UBO_TAG, cls._UBO_TARBALL)
        return ("brave", cls._BRAVE_RESOURCES)

    def _load_resources(self):
        """Read the cached library. The cache records WHICH source it came from,
        so switching engines (and therefore resource formats) discards it rather
        than registering inert bodies."""
        want = self._resource_source()[0]
        self._res = []
        try:
            blob = json.loads(self._resources.read_text(encoding="utf-8"))
            if isinstance(blob, dict) and blob.get("source") == want:
                self._res = blob.get("resources") or []
            elif isinstance(blob, dict):
                self._log("resource cache is %r, engine wants %r — refetching"
                          % (blob.get("source"), want))
        except Exception:
            pass
        if self._res:
            self._log("resource library: %d %s entries from %s"
                      % (len(self._res), want, self._resources))
        else:
            self._log("resource library: EMPTY — no scriptlet will fire "
                      "(first run, or the fetch has not landed yet)")

    def _load_engine_resources(self, eng):
        if not self._res:
            return 0
        # Modern engines take the WHOLE set in one call and have no singular
        # form; the pinned 0.6.0 has only the singular form. Try the batch call
        # first so a bumped binding needs no edit here.
        batch = getattr(eng, "add_resources", None) or getattr(eng, "use_resources", None)
        if batch is not None:
            try:
                batch([(r["name"], r["content_type"], r["content"],
                        r.get("aliases") or []) for r in self._res])
                self._log("registered %d resources with the engine (batch)" % len(self._res))
                return len(self._res)
            except Exception as e:
                self._log("batch resource registration failed (%s); trying one at a time" % e)
        ok = bad = 0
        for r in self._res:
            try:
                eng.add_resource(name=r["name"], content_type=r["content_type"],
                                 content=r["content"], aliases=r.get("aliases") or [])
                ok += 1
            except Exception:
                bad += 1
        if ok or bad:
            self._log("registered %d resources with the engine (%d rejected)" % (ok, bad))
        return ok

    def _refresh_resources(self):
        """Fetch + reassemble the uBO resource library if the cache is stale.
        Returns True when it changed."""
        try:
            fresh = (self._resources.exists()
                     and (time.time() - self._resources.stat().st_mtime)
                     < self._REFRESH_DAYS * 86400)
        except OSError:
            fresh = False
        if fresh and self._res:
            return False
        src, url = self._resource_source()
        try:
            self._log("fetching the %s resource library" % src)
            blob = self._fetch_bytes(url, timeout=90)
            if src == "brave":
                res = [{"name": x["name"], "aliases": x.get("aliases") or [],
                        "content_type": ("template" if x.get("kind") == "template"
                                         else (x.get("kind") or {}).get("mime", "")),
                        "content": x["content"]}
                       for x in json.loads(blob.decode("utf-8"))]
                n_scriptlets = sum(1 for x in res
                                   if x["content_type"] in ("template", "application/javascript"))
            else:
                res, n_scriptlets = self._assemble_resources(blob)
        except Exception as e:
            self._log("resource fetch/assembly failed (%s) — keeping what we have" % e)
            return False
        if not res:
            self._log("resource assembly produced nothing — keeping what we have")
            return False
        try:
            self._resources.parent.mkdir(parents=True, exist_ok=True)
            self._resources.write_text(
                json.dumps({"source": src, "resources": res}), encoding="utf-8")
        except OSError as e:
            self._log("could not cache the resource library (%s)" % e)
        self._res = res
        self._log("resource library: %d %s entries (%d scriptlets, %d redirects)"
                  % (len(res), src, n_scriptlets, len(res) - n_scriptlets))
        return True

    # ---- parsing -----------------------------------------------------------
    def _add_host(self, host, target):
        host = host.strip(".").lower()
        if host and "." in host and "localhost" not in host and self._HOSTRE.match(host):
            target.add(host)

    def _parse(self, text, blocked, tp, allow):
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line[0] in "!#[":       # comments / hosts-file headers / ABP metadata
                continue
            low = line.lower()
            # hosts-file format: "0.0.0.0 ad.example.com"
            if low.startswith(("0.0.0.0", "127.0.0.1", "::1", "::", "255.255.255.255")):
                parts = line.split()
                if len(parts) >= 2:
                    self._add_host(parts[1], blocked)
                continue
            # Adblock syntax. Cosmetic / scriptlet rules can't be done here — skip.
            if any(m in line for m in ("##", "#@#", "#?#", "#$#", "#%#")):
                continue
            exception = low.startswith("@@")
            body = line[2:] if exception else line
            if not body.startswith("||"):          # only host-anchored network rules
                continue
            pattern, _, opts = body[2:].partition("$")
            third = False
            if opts:
                optset = set(opts.lower().split(","))
                if any(o.startswith("domain=") for o in optset):
                    continue                        # site-specific rule — needs a real engine
                third = "third-party" in optset or "3p" in optset
            host = pattern.rstrip("^")
            if host.endswith("/"):
                host = host[:-1]
            if any(c in host for c in "/*^:?="):    # leftover path / wildcard — unsupported
                continue
            self._add_host(host, allow if exception else (tp if third else blocked))

    def _user_rules(self):
        """blocklist.txt as (host, is_exception) pairs — the host-granular half
        of the escape hatch, and the only half the pure-python fallback can
        use. Lines that are already Adblock rules are skipped here and picked
        up verbatim by _user_raw_rules()."""
        for s in self._user_lines():
            if self._looks_like_rule(s):
                continue
            if s.startswith("!"):
                h = s[1:].strip()
                if h:
                    yield (h, True)
            else:
                yield (s, False)

    def _user_lines(self):
        try:
            lines = (self._cfg / "blocklist.txt").read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            s = line.strip()
            if s and not s.startswith("#"):
                yield s

    @staticmethod
    def _looks_like_rule(s):
        # `!` alone is our allow-list prefix; `@@` is Adblock's. Anything with a
        # path, an option or a cosmetic separator is a real rule, not a host.
        return (s.startswith(("||", "@@", "/", "$"))
                or "$" in s or "/" in s or "##" in s or "#@#" in s or "#?#" in s)

    def _user_raw_rules(self):
        for s in self._user_lines():
            if self._looks_like_rule(s):
                yield s

    def _custom_rules(self):
        """_CUSTOM_RULES, minus any the user has allow-listed.

        `$important` is final in this engine — measured: no `@@` exception
        undoes it, not even `@@…$important`. So the ONLY way blocklist.txt can
        stay a working escape hatch for these is to not emit the rule at all.
        Without this the docs would be promising an override that silently does
        nothing."""
        exempt = [h for h, exc in self._user_rules() if exc]
        for raw in self._user_raw_rules():
            if raw.startswith("@@"):
                exempt.append(raw[2:].lstrip("|").split("$")[0].strip("^").lower())
        out = []
        for rule in self._CUSTOM_RULES:
            host = rule.lstrip("|").split("/")[0].split("$")[0].lower()
            if any(e and (host == e or host.endswith("." + e) or e.startswith(host))
                   for e in exempt):
                self._log("custom rule disabled by blocklist.txt: %s" % rule)
                continue
            out.append(rule)
        return out

    def _parse_user(self, blocked, tp, allow):
        for host, exc in self._user_rules():
            self._add_host(host, allow if exc else blocked)

    # ---- feeding a list to the engine --------------------------------------
    @classmethod
    def _sanitize(cls, text):
        """Work around a parser bug in the LEGACY engine, measured not guessed.

        `@@*$ghide,domain=a.com|b.com|~www.a.com` — an element-hiding EXCEPTION
        whose `domain=` mixes positive and NEGATED entries — is read by
        adblock-rust 0.5.6 as "everywhere except the negated ones", so a single
        such rule in uBO's filters-2024.txt turned `generichide` on for EVERY
        site and silently disabled generic cosmetic filtering wholesale
        (boards.4chan.org 539 hide selectors -> 1; cnn.com 551 -> 13). Dropping
        the negations restores the rule's real, narrow intent.

        **Fixed upstream by 0.12.5, so on top this is a no-op — do NOT delete
        it as obsolete.** Measured on the fork: cnn 551 and 4chan 539 with the
        sanitizer and without it, identical. book still runs 0.5.6, where the
        difference is the whole of generic cosmetic filtering. It repairs
        exactly one rule in the current corpus and costs 0.25 s of the compile
        thread.

        Returns (text, rules-repaired)."""
        if "hide" not in text or "~" not in text:
            return text, 0
        out, n = [], 0
        for line in text.splitlines():
            if line.startswith("@@") and "~" in line and "hide" in line:
                head, sep, opts = line.partition("$")
                if sep and cls._HIDE_OPT.search(opts):
                    m = cls._DOMAIN_OPT.search(opts)
                    if m:
                        keep = [d for d in m.group(1).split("|")
                                if d and not d.startswith("~")]
                        n += 1
                        if not keep:
                            continue                # nothing positive left: drop it
                        opts = (opts[:m.start(1)] + "|".join(keep) + opts[m.end(1):])
                        line = head + "$" + opts
            out.append(line)
        return "\n".join(out), n

    # ---- procedural cosmetics ----------------------------------------------
    # **This is book's path, not top's.** adblock-rust 0.5.6 (PyPI `adblock`
    # 0.6.0, the only build Fedora's system python can get) drops every
    # `##…:has(…)` and `#?#` rule on the floor: url_cosmetic_resources never
    # returns them and there is no `procedural_actions` field to ask. top's fork
    # (0.12.5) returns `:has()` inside `hide_selectors` and everything else in
    # `procedural_actions`, so it never calls procedural_selectors() —
    # `Cosmetic._engine_procedural` is what tells the two apart. Keep this:
    # deleting it would take book from degraded to broken.
    #
    # Chromium evaluates `:has()` natively (and `:is()`/`:where()`/`:not()`),
    # so the recoverable subset is exactly: rules whose selector uses `:has()`
    # and NO uBO-only pseudo-class. Everything else (`:has-text()`,
    # `:upward()`, `:remove()`, …) needs a JS evaluator and is left alone.
    # Measured over the full subscription set: 1687 procedural rules, 1134
    # emittable, all of them domain-specific.
    def _scan_procedural(self):
        t0 = time.time()
        index, seen, kept, total = {}, set(), 0, 0
        for url in self._subs:
            try:
                text = self._cache_path(url).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line in text.splitlines():
                if "#" not in line or ":has(" not in line:
                    continue
                m = self._COSMETIC_RE.match(line.rstrip())
                if not m:
                    continue
                domains, negated, _proc, sel = m.groups()
                total += 1
                if negated or not domains:
                    # `#@#` unhides and generic procedural rules are both left
                    # out: the first needs the rule it cancels to be present in
                    # the same index, and the corpus contains none of the second.
                    continue
                if sel.startswith(("+js(", "^")) or self._PROC_UNSUPPORTED.search(sel):
                    continue
                pos, neg = [], []
                for d in domains.split(","):
                    d = d.strip().lower()
                    if not d:
                        continue
                    (neg if d.startswith("~") else pos).append(d.lstrip("~"))
                if not pos:
                    continue
                key = (sel, tuple(sorted(neg)))
                if key in seen:
                    continue
                seen.add(key)
                kept += 1
                excl = frozenset(neg)
                for d in pos:
                    index.setdefault(d, []).append((sel, excl))
        self._proc = {d: tuple(v) for d, v in index.items()}
        self._proc_n = kept
        self._log("procedural: %d `:has()` rules over %d domains recovered "
                  "from %d procedural rules in %.2fs"
                  % (kept, len(self._proc), total, time.time() - t0))

    @staticmethod
    def _dom_matches(host, pat):
        if pat.endswith(".*"):                      # uBO entity form: `example.*`
            base = pat[:-2]
            return host == base or ("." + base + ".") in ("." + host + ".")
        return host == pat or host.endswith("." + pat)

    def procedural_selectors(self, host):
        """The `:has()` selectors that apply to `host`, as plain CSS."""
        idx = self._proc
        if not idx or not host:
            return []
        host = host.lower().strip(".")
        labels = host.split(".")
        keys = [".".join(labels[i:]) for i in range(len(labels))]
        keys += [labels[i] + ".*" for i in range(max(1, len(labels) - 1))]
        out, seen = [], set()
        for k in keys:
            for sel, excl in idx.get(k, ()):
                if sel in seen:
                    continue
                if excl and any(self._dom_matches(host, n) for n in excl):
                    continue
                seen.add(sel)
                out.append(sel)
        return out

    def _compile(self):
        # Prefer the real engine; fall back to the pure-python host-set.
        if self._build_engine():
            return
        blocked = set(self._BUILTIN)
        tp, allow = set(), set()
        for url in self._subs:
            try:
                text = self._cache_path(url).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            self._parse(text, blocked, tp, allow)
        self._parse_user(blocked, tp, allow)
        tp -= blocked                               # unconditional block wins over 3p-only
        self._tables = (frozenset(blocked), frozenset(tp), frozenset(allow))
        sys.stderr.write(
            f"surfer adblock: host-set fallback — {len(blocked)} blocked + "
            f"{len(tp)} third-party-only, {len(allow)} allowed ({len(self._subs)} lists)\n")

    def _build_engine(self):
        """Build an adblock-rust Engine from the raw cached lists. Returns True
        on success (self._engine set), False if `adblock` isn't importable or
        the build fails (caller then uses the pure-python fallback)."""
        try:
            from adblock import Engine, FilterSet
        except Exception:
            return False
        try:
            t0 = time.time()
            fs = FilterSet(debug=False)
            # seed so first run (empty cache) still blocks the obvious ad hosts
            fs.add_filter_list("\n".join("||%s^" % d for d in self._BUILTIN))
            n = miss = fixed = 0
            for url in self._subs:
                try:
                    text = self._cache_path(url).read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    miss += 1
                    self._log("list not cached yet: %s" % url)
                    continue
                text, repaired = self._sanitize(text)
                fixed += repaired
                fs.add_filter_list(text)
                n += 1
            # Ours last, so they sit after every subscription; `$important`
            # is what actually beats EasyList's `@@` exceptions (see
            # _CUSTOM_RULES), position alone would not.
            custom = self._custom_rules()
            fs.add_filter_list("\n".join(custom))
            user = 0
            for host, exc in self._user_rules():    # blocklist.txt overrides
                fs.add_filter_list(("@@||%s^" if exc else "||%s^") % host)
                user += 1
            for rule in self._user_raw_rules():     # …and verbatim rules
                fs.add_filter_list(rule)
                user += 1
            self._engine = Engine(filter_set=fs)
            self._log("engine built from %d lists (%d missing, %d hide-exception "
                      "rules repaired, %d custom, %d user) in %.2fs"
                      % (n, miss, fixed, len(custom), user, time.time() - t0))
            self._load_engine_resources(self._engine)
            return True
        except Exception as e:
            self._log("engine build failed (%s); host-set fallback" % e)
            return False

    # ---- background refresh ------------------------------------------------
    def _fetch(self, url, timeout=25):
        req = urllib.request.Request(url, headers={"User-Agent": "surfer-adblock/1"})
        try:
            return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
        except ssl.SSLError:
            # Nix python may lack a cert bundle; a filter list over unverified TLS
            # is low-risk (worst case: over/under-blocking, never code execution).
            ctx = ssl._create_unverified_context()
            return urllib.request.urlopen(req, timeout=timeout, context=ctx).read().decode("utf-8", "ignore")

    def _fetch_bytes(self, url, timeout=25):
        req = urllib.request.Request(url, headers={"User-Agent": "surfer-adblock/1"})
        try:
            return urllib.request.urlopen(req, timeout=timeout).read()
        except ssl.SSLError:
            ctx = ssl._create_unverified_context()
            return urllib.request.urlopen(req, timeout=timeout, context=ctx).read()

    def _refresh(self):
        changed = fetched = failed = 0
        for url in self._subs:
            path = self._cache_path(url)
            try:
                fresh = path.exists() and (time.time() - path.stat().st_mtime) < self._REFRESH_DAYS * 86400
            except OSError:
                fresh = False
            if fresh:
                continue
            try:
                data = self._fetch(url)
            except Exception as e:
                failed += 1
                self._log("fetch failed, keeping the stale cache: %s (%s)" % (url, e))
                continue                            # keep the stale cache; try again next launch
            if data:
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(data, encoding="utf-8")
                    changed += 1
                    fetched += len(data)
                except OSError as e:
                    self._log("could not cache %s (%s)" % (url, e))
        # The resource library rides the same schedule; without it every
        # ##+js() rule in every one of those lists is a no-op.
        res_changed = self._refresh_resources()
        if changed or failed:
            self._log("refresh: %d lists updated (%.1f MB), %d failed, %d fresh"
                      % (changed, fetched / 1048576.0, failed,
                         len(self._subs) - changed - failed))
        if changed or res_changed:
            self._compile()                         # atomic swap of engine/tables
            self._save_engine_cache()               # refresh the compiled cache
            if changed:
                self._scan_procedural()

    # ---- matching ----------------------------------------------------------
    @staticmethod
    def _base(host):
        parts = host.rsplit(".", 2)
        return ".".join(parts[-2:]) if len(parts) >= 2 else host

    def _is_blocked(self, host, third_party):
        blocked, tp, allow = self._tables
        labels = host.split(".")
        suffixes = [".".join(labels[i:]) for i in range(len(labels) - 1)]
        for s in suffixes:
            if s in allow:
                return False
        for s in suffixes:
            if s in blocked or (third_party and s in tp):
                return True
        return False

    @staticmethod
    def _should_block(res):
        """`BlockerResult.matched` was removed in adblock-rust 0.13.0 in favour
        of `should_block()`; ask for the newer form first so a bumped binding
        does not silently stop blocking (a missing attribute would be swallowed
        by interceptRequest's except)."""
        fn = getattr(res, "should_block", None)
        if callable(fn):
            return bool(fn())
        return bool(getattr(res, "matched", False)) and not res.exception

    def interceptRequest(self, info):
        try:
            eng = self._engine
            if eng is not None:
                url = info.requestUrl().toString()
                fp = info.firstPartyUrl().toString() or url
                res = eng.check_network_urls(url, fp, _res_type(info))
                if self._should_block(res):
                    info.block(True)
                return
            # pure-python fallback (no engine)
            host = info.requestUrl().host().lower()
            if not host:
                return
            fp = info.firstPartyUrl().host().lower()
            third_party = (not fp) or self._base(host) != self._base(fp)
            if self._is_blocked(host, third_party):
                info.block(True)
        except Exception:
            pass


# Qt request-type enum -> adblock-rust request_type string, built lazily (the
# enum is cheap but needs QtWebEngineCore imported, which it is by here).
_RES_TYPE = None


def _res_type(info):
    global _RES_TYPE
    if _RES_TYPE is None:
        E = QWebEngineUrlRequestInfo.ResourceType
        names = {
            "ResourceTypeMainFrame": "document", "ResourceTypeSubFrame": "sub_frame",
            "ResourceTypeStylesheet": "stylesheet", "ResourceTypeScript": "script",
            "ResourceTypeImage": "image", "ResourceTypeFontResource": "font",
            "ResourceTypeObject": "object", "ResourceTypeMedia": "media",
            "ResourceTypeXhr": "xmlhttprequest", "ResourceTypePing": "ping",
            "ResourceTypeCspReport": "csp_report", "ResourceTypePluginResource": "object",
            "ResourceTypeWebSocket": "websocket", "ResourceTypeFavicon": "image",
            "ResourceTypeWorker": "other", "ResourceTypeSharedWorker": "other",
            "ResourceTypeServiceWorker": "other", "ResourceTypePrefetch": "other",
            "ResourceTypeSubResource": "other", "ResourceTypeUnknown": "other",
        }
        _RES_TYPE = {getattr(E, k).value: v for k, v in names.items() if hasattr(E, k)}
    return _RES_TYPE.get(info.resourceType().value, "other")


class Cosmetic(QObject):
    """Element-hiding (cosmetic) filtering — the half a URL interceptor can't do.
    Pulls per-site hide selectors, scriptlets and procedural filters from the
    same adblock-rust engine AdBlocker uses; `CosmeticInjector` fetches them
    over the `surfercos:` scheme and applies them. Specific (per-hostname) rules
    go in immediately; generic (`##.ad`) rules are resolved against the
    classes/ids actually on the page (adblock-rust's hidden_class_id_selectors —
    uBO's design) so only matchable selectors ship. Every slot returns an empty
    result when the engine isn't available, so the injector is a harmless no-op
    under the pure-python fallback.

    **Two engines, and the slots paper over the difference.** `top` runs the
    jampe fork (adblock-rust 0.12.5): `:has()` arrives inside `hide_selectors`
    already, `procedural_actions` carries everything Chromium cannot express as
    CSS, and `style_selectors` NO LONGER EXISTS — a `##…:style(…)` rule appears
    ONLY as a procedural action and is absent from `hide_selectors`, so dropping
    procedural handling silently loses those rules outright. `book` has PyPI's
    0.6.0 in the system python: no `procedural_actions` at all, so `:has()` is
    recovered by AdBlocker's raw-list pre-scan instead and emitted as CSS.
    `_engine_procedural()` is the one place that tells them apart."""

    # Selectors per `…{display:none!important}` rule. Blink truncates a single
    # comma-separated rule past ~1024 selectors (ABP and Vivaldi both cap
    # there); 100 is well under that and is chosen for a different reason —
    # CSS discards the WHOLE rule on one bad selector, so a small chunk keeps
    # the blast radius of one malformed list entry to 99 others.
    _CHUNK = 100

    def __init__(self, blocker, parent=None):
        super().__init__(parent)
        self._b = blocker

    def _css(self, hide, style):
        # chunk the display:none group so one invalid selector only kills its
        # chunk (CSS drops the entire comma-separated rule on a single error).
        sels = [s for s in hide if s]
        rules = [",".join(sels[i:i + self._CHUNK]) + "{display:none!important}"
                 for i in range(0, len(sels), self._CHUNK)]
        if style:
            try:
                for sel, decls in style.items():
                    rules.append("%s{%s}" % (sel, ";".join(decls)))
            except Exception:
                pass
        return "\n".join(rules)

    def _inject(self, css, script):
        if not css and not script:
            return ""
        js = ("(function(){try{var css=%s;if(css){"
              "var s=document.getElementById('surfer-cosmetic')||document.createElement('style');"
              "s.id='surfer-cosmetic';s.textContent=(s.textContent||'')+css;"
              "(document.head||document.documentElement).appendChild(s);}"
              % json.dumps(css))
        if script:
            js += "try{%s}catch(e){}" % script
        return js + "}catch(e){}})();"

    @staticmethod
    def _engine_procedural(r):
        """The engine's own procedural actions, or None if it has none to give.

        None means "this engine predates `procedural_actions`" (book's 0.6.0)
        and is NOT the same as an empty set, which means "this page has no
        procedural rules". Only the first case falls back to the pre-scan."""
        return getattr(r, "procedural_actions", None)

    def _resources_for(self, url):
        eng = self._b._engine
        if eng is None or not url:
            return None
        try:
            return eng.url_cosmetic_resources(url)
        except Exception:
            return None

    def _hide_css(self, r, url):
        """Hide selectors as CSS, with the `:has()` rules however this engine
        supplies them.

        0.12.5 puts `:has()` straight into `hide_selectors`, so adding the
        pre-scan there would only duplicate it — and duplicate it less
        accurately, the pre-scan's domain matching being an approximation of
        the engine's. Only an engine with no `procedural_actions` at all needs
        the pre-scan."""
        hide = list(r.hide_selectors)
        if self._engine_procedural(r) is None:
            try:
                hide += self._b.procedural_selectors(QUrl(url).host().lower())
            except Exception:
                pass
        # `style_selectors` existed at 0.6.0 and is GONE at 0.12.5, where a
        # `:style()` rule is a procedural action instead — hence the getattr,
        # and hence why dropping procedural handling would lose those rules.
        return self._css(hide, getattr(r, "style_selectors", None) or {})

    @Slot(str, result=str)
    def specificCss(self, url):
        """Raw CSS for `url` — what CosmeticInjector actually wants. It prefers
        this slot over reading the literal back out of `specificJs`'s output."""
        r = self._resources_for(url)
        return self._hide_css(r, url) if r is not None else ""

    @Slot(str, result=str)
    def proceduralJson(self, url):
        """Procedural filters for `url` as a JSON array of the engine's own
        JSON strings, handed through UNMODIFIED.

        Shape (verified against the live engine, not stubs):
            {"selector":[{"type":"css-selector","arg":"p"},
                         {"type":"has-text","arg":"Ad"}],
             "action":{"type":"remove"}}          # "action" absent => hide

        The engine does not apply these; CosmeticInjector's runtime does. On an
        engine with no `procedural_actions` this is `[]` on purpose: there, the
        recoverable `:has()` subset has already gone out as plain CSS through
        `specificCss`, and sending it again would apply every rule twice."""
        r = self._resources_for(url)
        if r is None:
            return "[]"
        actions = self._engine_procedural(r)
        if not actions:
            return "[]"
        try:
            return json.dumps([a if isinstance(a, str) else json.dumps(a)
                               for a in actions])
        except Exception:
            return "[]"

    @Slot(str, result=str)
    def specificJs(self, url):
        r = self._resources_for(url)
        if r is None:
            return ""
        return self._inject(self._hide_css(r, url),
                            getattr(r, "injected_script", "") or "")

    @Slot(str, "QVariantList", "QVariantList", result=str)
    def genericJs(self, url, classes, ids):
        eng = self._b._engine
        if eng is None or not url:
            return ""
        try:
            r = eng.url_cosmetic_resources(url)
            if r.generichide:                       # site opted out of generic hiding
                return ""
            sels = eng.hidden_class_id_selectors(
                [str(c) for c in classes], [str(i) for i in ids], r.exceptions)
        except Exception:
            return ""
        return self._inject(self._css(sels, {}), "")


class SingleInstance(QObject):
    """Server half of the single-instance handoff — client is `singleton.py`,
    which documents the wire protocol.

    A QLocalServer is an ordinary AF_UNIX SOCK_STREAM listener, so the stdlib
    client in singleton.py talks to it directly with no Qt on that side.

    Failure is never fatal: if the address cannot be bound we simply run without
    a server (subsequent launches then start their own process, i.e. exactly
    today's behaviour) rather than refusing to be a browser.
    """

    openUrl = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = None
        self._buf = {}
        path = singleton.socket_path()
        if not singleton.enabled():
            return
        try:
            srv = QLocalServer(self)
            # 0600. The path is usually inside $XDG_RUNTIME_DIR (already
            # 0700-per-user) but the /tmp fallback is not.
            srv.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
            # NO removeServer() here. singleton.send() already unlinked the
            # address if — and only if — a connect to it failed; a listen that
            # fails now means another surfer won the startup race and is live at
            # that address, and stealing it would leave TWO half-owners.
            if not srv.listen(path):
                sys.stderr.write(
                    f"surfer: single-instance listen on {path} failed "
                    f"({srv.errorString()}) — running without handoff\n")
                return
            srv.newConnection.connect(self._accept)
            self._server = srv
        except Exception as e:
            sys.stderr.write(f"surfer: single-instance server failed ({e})\n")

    def _accept(self):
        while self._server is not None and self._server.hasPendingConnections():
            c = self._server.nextPendingConnection()
            if c is None:
                return
            self._buf[c] = b""
            c.readyRead.connect(lambda c=c: self._read(c))
            c.disconnected.connect(lambda c=c: self._buf.pop(c, None))

    def _read(self, c):
        try:
            self._buf[c] = self._buf.get(c, b"") + bytes(c.readAll())
        except RuntimeError:            # connection died mid-read
            return
        while b"\n" in self._buf.get(c, b""):
            line, _, rest = self._buf[c].partition(b"\n")
            self._buf[c] = rest
            self._handle(c, line.decode("utf-8", "replace").strip())

    def _handle(self, c, line):
        try:
            c.write(b"OK\n")
            c.flush()
        except RuntimeError:
            pass
        if line.startswith("OPEN"):
            self.openUrl.emit(line[4:].strip())


# Spell-check dictionary discovery.
#
# Chromium does not resolve a language tag through any locale machinery: the
# string handed to setSpellCheckLanguages IS the basename of a `.bdic` file it
# opens under the dictionaries directory. So the tag has to match whatever is
# installed, and the two hosts do not agree — top gets `en-US.bdic` (built by
# surfer.nix's qwebengine_convert_dict and pointed at with
# QTWEBENGINE_DICTIONARIES_PATH), book gets Fedora's qt6-qtwebengine, whose
# dictionaries are named by the HUNSPELL locale: `en_US.bdic`, in Qt's default
# directory with no env var set. Asking for "en-US" there opens nothing and
# spell-checking is silently dead — enabled, no squiggle, no suggestions.
# Measured with tools/spell-test.py: `en-US` -> misspelled=[], `en_US` ->
# misspelled=[wrongg] + suggestions.
SPELL_TAGS = ("en-US", "en_US", "en-GB", "en_GB")


def _spell_dirs():
    """Directories Chromium will look in, most specific first."""
    dirs = []
    env = os.environ.get("QTWEBENGINE_DICTIONARIES_PATH")
    if env:
        dirs.extend(env.split(os.pathsep))
    try:
        from PySide6.QtCore import QLibraryInfo
        dirs.append(os.path.join(
            QLibraryInfo.path(QLibraryInfo.DataPath), "qtwebengine_dictionaries"))
    except Exception:
        pass
    dirs.append("/usr/share/qt6/qtwebengine_dictionaries")
    seen, out = set(), []
    for d in dirs:
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _spell_language():
    """The tag naming a .bdic that actually exists, or None."""
    for d in _spell_dirs():
        for tag in SPELL_TAGS:
            if os.path.isfile(os.path.join(d, tag + ".bdic")):
                return tag
    return None


def main():
    # air (Fedora/Asahi) has no working VA-API or Vulkan (the GPU logs show
    # vaInitialize failing + Vulkan disabled), and Chromium's handling of video
    # frames corrupts them there — every video "glitches out". Fixed on air ONLY
    # (detected by the system-python launcher path; top's GPU is fine and keeps
    # full acceleration). Must be set before QtWebEngine initializes.
    #
    # This used to be `--disable-gpu-compositing`, whose comment claimed "page
    # raster stays GPU-accelerated". It does not: that flag turns off the GPU
    # compositor for the WHOLE page, so every scroll frame of a heavy site
    # (github, with its sticky headers and deep layer tree) is composited on the
    # CPU — which is precisely the "scrolling looks like a much lower framerate"
    # report, and it got more visible once momentum made scrolls last longer.
    # The narrow flag disables only the zero-copy GPU-memory-buffer path that
    # video frames travel through, which is the part Asahi actually breaks, and
    # leaves page compositing on the GPU where scrolling needs it.
    #
    # SURFER_GPU picks the workaround without an edit:
    #   (unset)    the narrow flag above — current default
    #   softraster + --disable-gpu-rasterization. Page COMPOSITING stays on the
    #              GPU (so scrolling keeps its framerate) but every tile,
    #              glyphs included, is rasterised on the CPU by one code path
    #              that cannot be lost mid-session. This is the candidate fix
    #              for "text degrades into bad antialiasing after a while";
    #              costs some raster throughput on heavy pages.
    #   safe       the old blunt --disable-gpu-compositing, if video ever
    #              glitches out again.
    #
    # top ALSO needs a video workaround, and it is a different one — the line
    # above saying "top's GPU is fine" was wrong. On NVIDIA (595.84, RTX 5070)
    # Chromium's accelerated video decoder hands its frames over as a PLATFORM
    # GpuMemoryBuffer in multiplanar NV12, and QtWebEngine's shared-image
    # factories have no backing for that combination:
    #
    #   Could not find SharedImageBackingFactory with params: usage:
    #   Gles2Read|RasterRead|DisplayRead|Scanout, format: (Y_UV, 420, 8unorm,
    #   ExtSamplerOn), gmb_type: platform, debug_label: MailboxVideoFrameConverter
    #
    # That failure LOSES THE GL CONTEXT on the first decoded frame, so the page
    # stops painting — the video and everything around it — and the log fills
    # with `Context lost during MakeCurrent` + `non-existent mailbox` at frame
    # rate. This is the "embedded mp4s on 4chan glitch out and won't play"
    # report, and it is why webm was hit-or-miss: measured on top 2026-08-05
    # against a real WebEngineView on the sandbox output, h264/vp9/av1 all lose
    # the context on frame one while **vp8 is clean** — vp8 is the one codec
    # this stack has no hardware decoder for, so it never enters the path.
    # Disabling that one Chromium feature is enough (0 errors vs 234 in the same
    # run without it) and leaves page compositing and rasterisation on the GPU;
    # decode falls to software, which this CPU does not notice.
    # --disable-gpu-memory-buffer-video-frames does NOT fix it (measured), so
    # the narrow flag air uses is not transferable here.
    _flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    _mode = os.environ.get("SURFER_GPU", "")
    if ON_AIR:
        _gpu = "--disable-gpu-memory-buffer-video-frames"
        if _mode == "safe":
            _gpu = "--disable-gpu-compositing"
        elif _mode == "softraster":
            _gpu += " --disable-gpu-rasterization"
    else:
        # SURFER_GPU=hwvideo restores the accelerated decoder, to re-test this
        # after an NVIDIA or Qt bump.
        _gpu = "" if _mode == "hwvideo" else "--disable-features=AcceleratedVideoDecodeLinuxGL"
    if _gpu:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (_flags + " " + _gpu).strip()

    # Register the gmxhr:// scheme used for the SCOPED CORS bypass (only
    # userscripts' GM_xmlhttpRequest goes through it — see GmXhrHandler). Must be
    # done before QtWebEngine initializes. FetchApiAllowed lets fetch() target
    # it; CorsEnabled lets the page read the cross-origin response.
    scheme = QWebEngineUrlScheme(b"gmxhr")
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme
                    | QWebEngineUrlScheme.Flag.CorsEnabled
                    | QWebEngineUrlScheme.Flag.FetchApiAllowed
                    | QWebEngineUrlScheme.Flag.ContentSecurityPolicyIgnored)
    QWebEngineUrlScheme.registerScheme(scheme)

    # Register surfercmd:// — the one-way page->app command channel (CmdHandler),
    # used by the image-click handler. Same flags as gmxhr so a page fetch()
    # reaches it regardless of the page's CSP.
    cmdscheme = QWebEngineUrlScheme(b"surfercmd")
    cmdscheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    cmdscheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme
                       | QWebEngineUrlScheme.Flag.CorsEnabled
                       | QWebEngineUrlScheme.Flag.FetchApiAllowed
                       | QWebEngineUrlScheme.Flag.ContentSecurityPolicyIgnored)
    QWebEngineUrlScheme.registerScheme(cmdscheme)

    # Register surfercos:// — how the profile-level cosmetic runtime asks Python
    # for the current page's hide rules (CosmeticInjector). Same flags, and
    # ContentSecurityPolicyIgnored is load-bearing here rather than convenient:
    # the reply is executed as a <script src>, which a site with a strict
    # `script-src` would otherwise refuse.
    cosscheme = QWebEngineUrlScheme(b"surfercos")
    cosscheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    cosscheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme
                       | QWebEngineUrlScheme.Flag.CorsEnabled
                       | QWebEngineUrlScheme.Flag.FetchApiAllowed
                       | QWebEngineUrlScheme.Flag.ContentSecurityPolicyIgnored)
    QWebEngineUrlScheme.registerScheme(cosscheme)

    # surferstyle:// — how PAGE_STYLE_RUNTIME_JS (dark mode + system font) asks
    # Python for the current page's style CSS at document-creation. Same flags:
    # the reply is adopted as a constructed CSSStyleSheet, and Sandbox/script-src
    # never sees it. Registered before Chromium initializes, like surfercos.
    stylescheme = QWebEngineUrlScheme(b"surferstyle")
    stylescheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    stylescheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme
                         | QWebEngineUrlScheme.Flag.CorsEnabled
                         | QWebEngineUrlScheme.Flag.FetchApiAllowed
                         | QWebEngineUrlScheme.Flag.ContentSecurityPolicyIgnored)
    QWebEngineUrlScheme.registerScheme(stylescheme)

    # Chromium must be initialized before the QGuiApplication exists.
    QtWebEngineQuick.initialize()

    app = QGuiApplication(sys.argv)
    app.setApplicationName("surfer")
    app.setOrganizationName("surfer")  # keys the QtWebEngine profile dirs
    app.setDesktopFileName("surfer")

    # One rule for "which argv is the URL", shared with the handoff client so a
    # second launch can never disagree with the first about what it was asked
    # to open.
    start_url = singleton.pick_url(sys.argv[1:])

    # We got here, so no other surfer answered the probe at import time: become
    # the server. Later `surfer <url>` launches hand their URL to us instead of
    # contending for the Chromium profile.
    instance = SingleInstance(app)

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()

    palette = Palette(PANEL_THEME)
    style = DeskStyle()
    titlebar = Titlebar()
    clip = Clip()
    session = Session()
    userscripts = UserScripts()
    perm = Perm()
    notifier = Notifier(app)
    downloads = Downloads(app)
    prefs = Prefs()
    files = Files(prefs, app)
    zoom = Zoom(prefs, app)
    darkmode = DarkMode(prefs, app, style=style)
    adblocker = AdBlocker(app)
    cosmetic = Cosmetic(adblocker, app)
    download_dir = str(Path.home() / "Downloads")
    try:
        os.makedirs(download_dir, exist_ok=True)
    except OSError:
        pass
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Clip", clip)
    ctx.setContextProperty("Session", session)
    ctx.setContextProperty("UserScripts", userscripts)
    ctx.setContextProperty("Perm", perm)
    ctx.setContextProperty("Downloads", downloads)
    ctx.setContextProperty("Prefs", prefs)
    ctx.setContextProperty("Files", files)
    ctx.setContextProperty("Zoom", zoom)
    ctx.setContextProperty("DarkMode", darkmode)
    ctx.setContextProperty("Cosmetic", cosmetic)
    # The profile-level cosmetic runtime + its surfercos:// feed. Main.qml
    # assigns `CosmeticInject.scripts` to sharedProfile.userScripts.collection;
    # _wire_profile installs this same object as the scheme handler.
    cosinject = CosmeticInjector(cosmetic, app)
    ctx.setContextProperty("CosmeticInject", cosinject)
    # The profile-level dark-mode/system-font courier: PAGE_STYLE_RUNTIME_JS on
    # `surferstyle://`. Main.qml concats `PageStyle.scripts` onto the profile's
    # userScripts collection; _wire_profile installs pshandler as the scheme
    # handler. See PageStyle/PageStyleHandler.
    pagestyle = PageStyle(app)
    ctx.setContextProperty("PageStyle", pagestyle)
    pshandler = PageStyleHandler(darkmode, app)
    pagecmd = CmdHandler(app)
    ctx.setContextProperty("PageCmd", pagecmd)
    ctx.setContextProperty("imageClickJs", IMAGE_CLICK_JS)
    ctx.setContextProperty("gpuProbeJs", GPU_PROBE_JS if ON_AIR else "")
    ctx.setContextProperty("downloadDir", download_dir)
    ctx.setContextProperty("startUrl", start_url)
    ctx.setContextProperty("Instance", instance)
    # QML overlays in this window (the file picker) see wheel events that
    # ZoomFilter has already divided by WHEEL_GAIN for the web view; this is
    # what their WheelScroll multiplies back by. One source: pylib/kinetic.py.
    ctx.setContextProperty("WheelGain", QML_WHEEL_GAIN)
    # Ctrl+F -> the find bar. The object is both the signal source QML connects
    # to and the event filter that catches the key; installed below, once the
    # window exists.
    hotkeys = HotkeyFilter(app)
    ctx.setContextProperty("Hotkeys", hotkeys)

    theme_comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = theme_comp.create()
    if theme is None:
        print("Theme.qml failed:\n" + theme_comp.errorString(), file=sys.stderr)
        sys.exit(1)
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)

    engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
    if not engine.rootObjects():
        sys.exit(1)

    # Ctrl+wheel zoom: filter installed on the top-level window (the QML Window
    # root), upstream of the WebEngineView, so it drives our shared zoom and
    # suppresses Chromium's own Ctrl+wheel zoom. Parented to app so it lives.
    zoom_filter = ZoomFilter(zoom, app)
    engine.rootObjects()[0].installEventFilter(zoom_filter)
    # …and Ctrl+F, upstream of Chromium for the same reason (HotkeyFilter)
    engine.rootObjects()[0].installEventFilter(hotkeys)

    # Install the gmxhr scheme handler on the QML profile (found by objectName)
    # once the tree is fully built and stable — deferred onto the event loop to
    # avoid a during-load reference being reported deleted. Handlers are
    # per-profile, and the QML WebEngineProfile is the one the views use.
    gmxhr = GmXhrHandler(app)

    def _wire_profile():
        for ro in engine.rootObjects():
            prof = ro.findChild(QObject, "sharedProfile")
            if prof is not None:
                try:
                    prof.installUrlSchemeHandler(b"gmxhr", gmxhr)
                    prof.installUrlSchemeHandler(b"surfercmd", pagecmd)
                    prof.installUrlSchemeHandler(b"surfercos", cosinject)
                    prof.installUrlSchemeHandler(b"surferstyle", pshandler)
                except RuntimeError:
                    pass
                # give gmxhr the SAME UA the views send, so userscript fetches
                # aren't 429'd as non-browser traffic (see GmXhrHandler docstring)
                try:
                    gmxhr.set_user_agent(prof.property("httpUserAgent"))
                except Exception:
                    pass
                # route granted web notifications out to notify-send. The QML
                # profile persists granted/denied permissions to disk itself
                # (non-off-the-record), so a site is only prompted once.
                try:
                    prof.presentNotification.connect(notifier.present)
                except Exception:
                    pass
                # built-in ad/tracker blocking on the shared profile (all tabs)
                try:
                    prof.setUrlRequestInterceptor(adblocker)
                except Exception:
                    pass
                # Spell-checking. MUST be set here, imperatively, and NOT as QML
                # properties on the WebEngineProfile: a QQuickWebEngineProfile
                # drops spellCheckEnabled/spellCheckLanguages set at construction
                # (the spellcheck adapter isn't wired yet), so misspellings never
                # get marked — no red squiggle, no right-click suggestions.
                # Calling the setters now (tree built) makes it stick. Languages
                # first, then enable. The tag is not a locale name — it is the
                # BASENAME of a .bdic file, so it must be resolved against the
                # dictionaries that are actually installed (_spell_language).
                try:
                    lang = _spell_language()
                    if lang:
                        prof.setSpellCheckLanguages([lang])
                        prof.setSpellCheckEnabled(True)
                        sys.stderr.write(
                            "surfer spellcheck: %s enabled=%s\n"
                            % (lang, prof.isSpellCheckEnabled())
                        )
                    else:
                        sys.stderr.write(
                            "surfer spellcheck: no .bdic dictionary found in %s "
                            "— spell-checking off\n" % (_spell_dirs(),)
                        )
                except Exception as e:
                    sys.stderr.write(f"surfer spellcheck: setup failed ({e})\n")
                # Bound the Chromium disk cache. With no cap (0) Chromium lets it
                # grow without an upper limit — on this machine the cache had
                # reached 1.3 GB (~/.cache/surfer/surfer/QtWebEngine/surfer/Cache).
                # Capping it stops that runaway disk growth (and shrinks the
                # in-memory cache index with it); the level below is large enough
                # that repeat visits still hit cache, so this is not a browsing
                # cost. The real RSS win is the background-tab discard in Main.qml
                # (win.discardIdleTabs) — this one is cache sizing.
                try:
                    prof.setHttpCacheMaximumSize(512 * 1024 * 1024)   # 512 MB
                except Exception as e:
                    sys.stderr.write(f"surfer cache cap: failed ({e})\n")
                return

    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, _wire_profile)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
