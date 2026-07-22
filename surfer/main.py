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
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import (QObject, Slot, Signal, QUrl, QFileSystemWatcher, Property,
                            QBuffer, QIODevice)
from PySide6.QtGui import QGuiApplication, QColor
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from PySide6.QtWebEngineCore import (QWebEngineScript, QWebEngineUrlScheme,
                                     QWebEngineUrlSchemeHandler, QWebEnginePermission)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402

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
    ~/nix/filer/main.py for the full commentary)."""

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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = VtbClient(
            on_click=self.clicked.emit,
            on_reorder=lambda s, d: self.reordered.emit(s, d),
            on_addr=self.addrSubmitted.emit,
            on_wake=self.wake.emit,
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


class Downloads(QObject):
    """Desktop toasts for downloads, driven from Main.qml's onDownloadRequested.
    A large download gets a live progress toast that updates IN PLACE (notify-send
    --replace-id) with a CP437 block bar in the body — which the pixel DOS font
    renders as a real bar; every download gets a completion (or failure) toast.
    Keyed by an opaque per-download string from QML."""

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

    def _send(self, key, title, body, value):
        # -p prints the notification id so we can --replace-id (-r) it next time,
        # morphing one toast in place instead of stacking a new one per update.
        args = ["notify-send", "-a", "surfer", "-p"]
        rid = self._ids.get(key)
        if rid is not None:
            args += ["-r", str(rid)]
        if value is not None:
            args += ["-h", "int:value:%d" % int(value)]
        args += [title, body]
        try:
            out = subprocess.run(args, capture_output=True, text=True, timeout=2)
            nid = out.stdout.strip()
            if nid.isdigit():
                self._ids[key] = int(nid)
        except Exception:
            pass

    @Slot(str, str, float, float)
    def progress(self, key, name, received, total):
        if total <= 0:
            return
        pct = int(received * 100 / total)
        if self._pct.get(key) == pct:
            return  # throttle: only re-toast on a whole-percent change
        self._pct[key] = pct
        body = "%s %d%%\n%s / %s" % (self._bar(pct), pct,
                                     self._human(received), self._human(total))
        self._send(key, "downloading " + name, body, pct)

    @Slot(str, str)
    def done(self, key, name):
        self._send(key, "download complete", name, 100)  # reuses the progress toast
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
    so the browser's cookies aren't attached (fine for 4chan X's public GETs)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)

    def requestStarted(self, job):
        try:
            spec = json.loads(_b64url_decode(job.requestUrl().path().lstrip("/")).decode("utf-8"))
        except Exception:
            self._send(job, {"__error": "bad gmxhr request"})
            return
        method = (spec.get("method") or "GET").upper()
        req = QNetworkRequest(QUrl(spec.get("url") or ""))
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                         QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        for k, v in (spec.get("headers") or {}).items():
            try:
                req.setRawHeader(str(k).encode(), str(v).encode())
            except Exception:
                pass
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
    $XDG_STATE_HOME/surfer/session.json, so a relaunch restores what was open."""

    def __init__(self, parent=None):
        super().__init__(parent)
        state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        self._path = state / "surfer" / "session.json"

    @Slot("QVariantList", int)
    def save(self, urls, current):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {"tabs": [str(u) for u in urls if str(u)], "current": int(current)}
            self._path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    @Slot(result="QVariantMap")
    def load(self):
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            tabs = [str(u) for u in data.get("tabs", []) if str(u)]
            return {"tabs": tabs, "current": int(data.get("current", 0))}
        except (OSError, ValueError, TypeError):
            return {"tabs": [], "current": 0}


class Prefs(QObject):
    """Small persisted preferences (currently just the page zoom level, shared
    across all tabs) in $XDG_STATE_HOME/surfer/prefs.json."""

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
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(d), encoding="utf-8")
        except OSError:
            pass


def main():
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

    # Chromium must be initialized before the QGuiApplication exists.
    QtWebEngineQuick.initialize()

    app = QGuiApplication(sys.argv)
    app.setApplicationName("surfer")
    app.setOrganizationName("surfer")  # keys the QtWebEngine profile dirs
    app.setDesktopFileName("surfer")

    start_url = ""
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            start_url = arg
            break

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()

    palette = Palette(PANEL_THEME)
    titlebar = Titlebar()
    clip = Clip()
    session = Session()
    userscripts = UserScripts()
    perm = Perm()
    notifier = Notifier(app)
    downloads = Downloads(app)
    prefs = Prefs()
    download_dir = str(Path.home() / "Downloads")
    try:
        os.makedirs(download_dir, exist_ok=True)
    except OSError:
        pass
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Clip", clip)
    ctx.setContextProperty("Session", session)
    ctx.setContextProperty("UserScripts", userscripts)
    ctx.setContextProperty("Perm", perm)
    ctx.setContextProperty("Downloads", downloads)
    ctx.setContextProperty("Prefs", prefs)
    ctx.setContextProperty("downloadDir", download_dir)
    ctx.setContextProperty("startUrl", start_url)

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
                except RuntimeError:
                    pass
                # route granted web notifications out to notify-send. The QML
                # profile persists granted/denied permissions to disk itself
                # (non-off-the-record), so a site is only prompted once.
                try:
                    prof.presentNotification.connect(notifier.present)
                except Exception:
                    pass
                return

    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, _wire_profile)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
