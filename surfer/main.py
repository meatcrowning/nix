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
import json
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Slot, Signal, QUrl, QFileSystemWatcher, Property
from PySide6.QtGui import QGuiApplication, QColor
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from PySide6.QtWebEngineCore import QWebEngineScript

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


class Clip(QObject):
    """Clipboard access for the 'copy url' titlebar button."""

    @Slot(str)
    def copy(self, text):
        QGuiApplication.clipboard().setText(text)


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
  o = o||{}; var ctrl = new AbortController();
  var init = { method:(o.method||"GET"), headers:(o.headers||{}), signal:ctrl.signal, credentials:(o.anonymous?"omit":"include"), mode:"cors" };
  if(o.data!=null) init.body = o.data;
  fetch(o.url, init).then(function(r){
    var rt = o.responseType;
    var body = (rt==="arraybuffer")? r.arrayBuffer() : (rt==="blob")? r.blob() : r.text();
    return Promise.resolve(body).then(function(b){
      var hdr=""; try{ r.headers.forEach(function(v,k){ hdr += k+": "+v+"\r\n"; }); }catch(e){}
      var resp = { readyState:4, status:r.status, statusText:r.statusText, finalUrl:r.url, responseHeaders:hdr };
      if(rt==="arraybuffer"||rt==="blob"){ resp.response=b; resp.responseText=""; }
      else if(rt==="json"){ try{ resp.response=JSON.parse(b); }catch(e){ resp.response=null; } resp.responseText=b; }
      else { resp.response=b; resp.responseText=b; }
      if(o.onload) o.onload(resp);
    });
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


def main():
    # CORS bypass for userscripts' GM_xmlhttpRequest (a fetch shim): disable the
    # same-origin policy so cross-origin requests (4chan X archives, media title
    # lookups, etc.) aren't blocked. NB this lowers security browser-wide — it's
    # a deliberate trade-off for a personal userscript-running browser. Must be
    # set before QtWebEngine initializes.
    _flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "disable-web-security" not in _flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (_flags + " --disable-web-security").strip()

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
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Clip", clip)
    ctx.setContextProperty("Session", session)
    ctx.setContextProperty("UserScripts", userscripts)
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

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
